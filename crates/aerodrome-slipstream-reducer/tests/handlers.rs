use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    handlers::SupportedHandler,
    hosts::HostSet,
    identity::{build_descriptor, InputBinding, OUTPUT_MODULE, OUTPUT_TYPE},
    input::{validate_block, BlockInput},
    pb,
    state::{BlockStore, HandlerStatus, MemoryBackend},
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
fn original() -> pb::ExtractorBlock {
    let bytes = include_bytes!("../fixtures/first-pool-extractor.pb");
    assert_eq!(
        hex::encode(Sha256::digest(bytes)),
        "e4cd95b41894ac5a84bb3fd36da75791d58686612fa9b9a4e9efeb1d04e3adb4"
    );
    pb::ExtractorBlock::decode(bytes.as_slice()).unwrap()
}
fn validate(b: &pb::ExtractorBlock) -> BlockInput {
    validate_block(
        &Frame {
            kind: FrameKind::Observed,
            block_number: b.number,
            block_hash: b.hash.clone().try_into().unwrap(),
            payload: b.encode_to_vec(),
        },
        b.parent_hash.clone().try_into().unwrap(),
    )
    .unwrap()
}
fn backend(b: &pb::ExtractorBlock, binding: &InputBinding) -> MemoryBackend {
    MemoryBackend::from_images(
        binding,
        Boundary {
            block_number: b.number - 1,
            block_hash: b.parent_hash.clone().try_into().unwrap(),
        },
        BTreeMap::new(),
        BTreeMap::new(),
    )
    .unwrap()
}
fn word(n: u64) -> Vec<u8> {
    let mut bytes = vec![0; 32];
    bytes[24..].copy_from_slice(&n.to_be_bytes());
    bytes
}
fn raw(bytes: Vec<u8>) -> Option<pb::RawRetval> {
    Some(pb::RawRetval {
        kind: Some(pb::raw_retval::Kind::Value(bytes)),
    })
}
fn synthetic(name: &str) -> pb::ExtractorBlock {
    let mut b = original();
    b.candidates
        .retain(|c| c.log_index == 172 || c.log_index == 171);
    if let Some(n) = name.strip_prefix("spacing_") {
        let n: u64 = n.parse().unwrap();
        b.candidates[0].topics[3] = word(n);
        b.pools_created[0].tick_spacing = n as i32;
    }
    if name == "excluded_pool" {
        let pool = hex::decode("8fe8d9bb8eeba3ed688069c3d6b556c9ca258248").unwrap();
        b.candidates[0].data[12..32].copy_from_slice(&pool);
        b.pools_created[0].pool = pool;
        b.candidates.truncate(1);
    }
    let tick = match name {
        "tick_wrap_positive" => Some(word(1 << 31)),
        "tick_wrap_negative" => {
            let mut v = vec![255; 32];
            v[28..].copy_from_slice(&(-2147483649_i64).to_be_bytes()[4..]);
            Some(v)
        }
        "tick_overflow" => Some(word(1 << 32)),
        _ => None,
    };
    if let Some(tick) = tick {
        b.candidates[1].data[32..64].copy_from_slice(&tick);
    }
    if name == "timestamp_wrap" {
        b.timestamp = 1 << 31;
    }
    if name == "timestamp_overflow" {
        b.timestamp = 1 << 32;
    }
    if matches!(name, "cached_tokens" | "repeated_initialize") {
        b.parent_hash = b.hash.clone();
        b.number += 1;
        b.hash = vec![68; 32];
        b.timestamp += 1;
        b.calls = Some(pb::CallAnswers::default());
        if name == "cached_tokens" {
            b.candidates.truncate(1);
        } else {
            b.candidates.remove(0);
            b.pools_created.clear();
            b.candidates[0].wave = 0;
        }
    }
    for a in &mut b.calls.as_mut().unwrap().erc20 {
        match name {
            "metadata_reverted" => {
                let r = Some(pb::RawRetval {
                    kind: Some(pb::raw_retval::Kind::Reverted(pb::raw_retval::Null {})),
                });
                a.symbol = r.clone();
                a.name = r.clone();
                a.total_supply = r.clone();
                a.decimals = r;
                a.rpc_failed_mask = 15;
            }
            "metadata_bytes32" => {
                let mut v = vec![0; 32];
                v[..5].copy_from_slice(b"A\0B\xffC");
                a.symbol = raw(v.clone());
                a.name = raw(v);
            }
            "metadata_sentinel" => {
                a.symbol = raw(word(1));
                a.name = raw(word(1));
            }
            "metadata_invalid" => {
                a.symbol = raw(vec![171]);
                a.name = raw(vec![171]);
                a.total_supply = raw(vec![171]);
                a.decimals = raw(word(256));
            }
            _ => (),
        }
    }
    b
}
fn run(b: &pb::ExtractorBlock, indexes: &[usize]) -> output::BlockChanges {
    run_seeded(b, indexes, &[])
}
fn run_seeded(b: &pb::ExtractorBlock, indexes: &[usize], seed: &[Value]) -> output::BlockChanges {
    let binding = binding();
    let input = validate(b);
    let mut backend = backend(b, &binding);
    let mut hosts = HostSet::default();
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
        backend = MemoryBackend::from_images(
            &binding,
            boundary.clone(),
            rows,
            BTreeMap::from([(pool, boundary)]),
        )
        .unwrap();
        hosts.seed(pool, original.number, original.number).unwrap();
    }
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
fn first_handlers_match_every_graph_node_operation_and_source() {
    let corpus: Value =
        serde_json::from_slice(include_bytes!("../fixtures/graph-node-first-handlers.json"))
            .unwrap();
    assert_eq!(corpus["cases"].as_array().unwrap().len(), 18);
    for case in corpus["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let bytes = hex::decode(case["changes_hex"].as_str().unwrap()).unwrap();
        let mut expected = output::BlockChanges::decode(bytes.as_slice()).unwrap();
        let got = if name == "real_first_pool" {
            // Compare complete operations of actual groups0 and3, renumbering
            // only dense indices because NPM/Mint are outside this checkpoint.
            expected
                .operations
                .retain(|op| op.handler_group_order == 0 || op.handler_group_order == 3);
            for (index, op) in expected.operations.iter_mut().enumerate() {
                op.operation_index = index as u64;
                if op.handler_group_order == 3 {
                    op.handler_group_order = 1;
                }
            }
            run(&original(), &[0, 3])
        } else {
            let b = synthetic(name);
            let indexes = (0..b.candidates.len()).collect::<Vec<_>>();
            run_seeded(&b, &indexes, case["seed_rows"].as_array().unwrap())
        };
        assert_eq!(got, expected, "{name}");
    }
}
#[test]
fn unknown_hosts_and_unsupported_handlers_cannot_execute() {
    let b = original();
    let input = validate(&b);
    let hosts = HostSet::default();
    assert!(SupportedHandler::match_candidate(&input, &hosts, 3)
        .err()
        .unwrap()
        .0
        .contains("UnknownPoolHost"));
    assert!(SupportedHandler::match_candidate(&input, &hosts, 1)
        .err()
        .unwrap()
        .0
        .contains("UnsupportedHandler: Transfer"));
    assert!(SupportedHandler::match_candidate(&input, &hosts, 2)
        .err()
        .unwrap()
        .0
        .contains("UnsupportedHandler: IncreaseLiquidity"));
}
#[test]
fn missing_metadata_answer_poison_prevents_sealing_even_after_bundle_save() {
    let mut b = synthetic("isolated_original");
    b.calls.as_mut().unwrap().erc20.clear();
    let binding = binding();
    let input = validate(&b);
    let backend = backend(&b, &binding);
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    let handler = SupportedHandler::match_candidate(&input, &HostSet::default(), 0)
        .unwrap()
        .unwrap();
    assert!(store
        .run_handler(handler.source_trigger_order(), |journal| handler
            .run(journal)
            .map(|_| ()))
        .unwrap_err()
        .0
        .contains("MissingCallAnswer"));
    assert!(store.seal().is_err());
    assert!(backend.rows().is_empty());
    assert!(backend.sources().is_empty());
}
