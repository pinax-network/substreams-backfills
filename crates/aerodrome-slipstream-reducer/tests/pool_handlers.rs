use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    handlers::SupportedHandler,
    hosts::HostSet,
    identity::{build_descriptor, InputBinding, OUTPUT_MODULE, OUTPUT_TYPE},
    input::validate_block,
    pb,
    state::{BlockStore, EntityBackend, HandlerStatus, Key, MemoryBackend, SealedBlock},
};
use backfill_common::{
    clock::{Frame, FrameKind},
    descriptor::ExtractorIdentity,
    pb::pinax::graph::backfill::v2 as output,
    state_snapshot::Boundary,
};
use prost::Message;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

// Oracle checkpoints carry cache images, including explicit Null. Keep the
// production DB seed validator strict; this read-only backend supplies the
// actual oracle cache image while delegating identity/source validation.
struct OracleSeed {
    database: MemoryBackend,
    cache: BTreeMap<Key, Vec<output::EntityField>>,
}
impl EntityBackend for OracleSeed {
    fn boundary(&self) -> &Boundary {
        self.database.boundary()
    }
    fn compatibility_id(&self) -> [u8; 32] {
        self.database.compatibility_id()
    }
    fn get(
        &self,
        key: &Key,
    ) -> aerodrome_slipstream_reducer::Result<Option<Vec<output::EntityField>>> {
        Ok(self.cache.get(key).cloned())
    }
    fn has_source(&self, pool: &aerodrome_slipstream_reducer::Address) -> bool {
        self.database.has_source(pool)
    }
    fn commit(&mut self, _: SealedBlock) -> aerodrome_slipstream_reducer::Result<()> {
        Err(aerodrome_slipstream_reducer::ReducerError(
            "read-only oracle fixture backend".into(),
        ))
    }
}

fn original() -> pb::ExtractorBlock {
    pb::ExtractorBlock::decode(include_bytes!("../fixtures/first-pool-extractor.pb").as_slice())
        .unwrap()
}
fn binding() -> InputBinding {
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let bytes = build_descriptor(&extractor, &"33".repeat(20), true).unwrap();
    InputBinding::new(&bytes, Sha256::digest(&bytes).into(), &extractor).unwrap()
}
fn run(b: &pb::ExtractorBlock, indexes: &[usize]) -> output::BlockChanges {
    run_seeded(b, indexes, &[])
}
fn run_seeded(b: &pb::ExtractorBlock, indexes: &[usize], seed: &[Value]) -> output::BlockChanges {
    let binding = binding();
    let input = validate_block(
        &Frame {
            kind: FrameKind::Observed,
            block_number: b.number,
            block_hash: b.hash.clone().try_into().unwrap(),
            payload: b.encode_to_vec(),
        },
        b.parent_hash.clone().try_into().unwrap(),
    )
    .unwrap();
    let mut backend = MemoryBackend::from_images(
        &binding,
        Boundary {
            block_number: b.number - 1,
            block_hash: b.parent_hash.clone().try_into().unwrap(),
        },
        BTreeMap::new(),
        BTreeMap::new(),
    )
    .unwrap();
    let mut hosts = HostSet::default();
    let mut cache = BTreeMap::new();
    if !seed.is_empty() {
        let mut rows = BTreeMap::new();
        for value in seed {
            let bytes = hex::decode(value.as_str().unwrap()).unwrap();
            let image = output::SetEntity::decode(bytes.as_slice()).unwrap();
            let key = image.key.unwrap();
            let Some(output::entity_id::Value::String(id)) = key.id.unwrap().value else {
                panic!("string id")
            };
            rows.insert(
                aerodrome_slipstream_reducer::state::Key::new(&key.entity_type, &id),
                image.written_fields,
            );
        }
        let original = original();
        let pool = original.pools_created[0].pool.clone().try_into().unwrap();
        let boundary = Boundary {
            block_number: original.number,
            block_hash: original.hash.try_into().unwrap(),
        };
        cache = rows.clone();
        for fields in rows.values_mut() {
            fields.retain(|f| !backfill_common::field_is_null(f));
        }
        backend = MemoryBackend::from_images(
            &binding,
            boundary.clone(),
            rows,
            BTreeMap::from([(pool, boundary)]),
        )
        .unwrap();
        hosts.seed(pool, original.number, original.number).unwrap();
    }

    let backend = OracleSeed {
        database: backend,
        cache,
    };
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    for &index in indexes {
        let Some(handler) = SupportedHandler::match_candidate(&input, &hosts, index).unwrap()
        else {
            continue;
        };
        let mut created = None;
        let status = store
            .run_handler(handler.source_trigger_order(), |journal| {
                created = handler.run(journal)?;
                Ok(())
            })
            .unwrap();
        if let Some(pool) = created {
            assert_eq!(status, HandlerStatus::Committed);
            hosts.record_creation_outcome(&input, pool, true).unwrap();
        }
    }
    let mut result = store.seal().unwrap().changes().clone();
    result.compatibility_id.clear();
    result
}
#[test]
fn real_first_mint_matches_original_wasm_operations() {
    let corpus: Value =
        serde_json::from_slice(include_bytes!("../fixtures/graph-node-first-handlers.json"))
            .unwrap();
    let case = corpus["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "real_first_pool")
        .unwrap();
    let bytes = hex::decode(case["changes_hex"].as_str().unwrap()).unwrap();
    let mut expected = output::BlockChanges::decode(bytes.as_slice()).unwrap();
    expected
        .operations
        .retain(|op| [0, 3, 4].contains(&op.handler_group_order));
    for (index, op) in expected.operations.iter_mut().enumerate() {
        op.operation_index = index as u64;
        op.handler_group_order = match op.handler_group_order {
            0 => 0,
            3 => 1,
            4 => 2,
            _ => unreachable!(),
        };
    }
    assert_eq!(run(&original(), &[0, 3, 4]), expected);
}

#[test]
fn seeded_pool_handlers_match_independent_wasm_operations() {
    let corpus: Value =
        serde_json::from_slice(include_bytes!("../fixtures/graph-node-pool-handlers.json"))
            .unwrap();
    assert_eq!(corpus["cases"].as_array().unwrap().len(), 11);
    for case in corpus["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut b = original();
        b.parent_hash = b.hash.clone();
        b.number += 1;
        b.hash = vec![68; 32];
        b.timestamp = case["timestamp"].as_u64().unwrap();
        let mut candidate = b.candidates[4].clone();
        candidate.wave = 0;
        candidate.address = hex::decode(case["log"]["address"].as_str().unwrap()).unwrap();
        candidate.topics = case["log"]["topics"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| hex::decode(v.as_str().unwrap()).unwrap())
            .collect();
        candidate.data = hex::decode(case["log"]["data"].as_str().unwrap()).unwrap();
        b.candidates = vec![candidate];
        b.pools_created.clear();
        let mut calls = pb::CallAnswers {
            ticks: b.calls.take().unwrap().ticks,
            ..Default::default()
        };
        for answer in &mut calls.ticks {
            let p = Some(pb::SlotProvenance {
                source: pb::SlotSource::InBlock as i32,
                last_change_block: b.number,
                last_change_ordinal: 1,
            });
            answer.p_staked = p;
            answer.p_fee0 = p;
            if name == "tick_misbinding_negative" {
                answer.staked_liquidity_net = vec![255; 16];
                answer.staked_liquidity_net[15] = 249;
                answer.fee_growth_outside0_x128 = vec![0; 32];
                answer.fee_growth_outside0_x128[31] = 11;
            }
        }
        b.calls = Some(calls);
        let got = run_seeded(&b, &[0], case["seed_rows"].as_array().unwrap());
        let bytes = hex::decode(case["changes_hex"].as_str().unwrap()).unwrap();
        let expected = output::BlockChanges::decode(bytes.as_slice()).unwrap();
        assert_eq!(
            got.operations.len(),
            expected.operations.len(),
            "{name}: operation count"
        );
        for (index, (a, b)) in got.operations.iter().zip(&expected.operations).enumerate() {
            assert_eq!(a, b, "{name}: operation {index}");
        }
        assert_eq!(got, expected, "{name}: envelope");
    }
}
