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
    let mut hosts = HostSet::default();
    hosts
        .record_creation_outcome(
            &input,
            original().pools_created[0].pool.clone().try_into().unwrap(),
            true,
        )
        .unwrap();
    assert!(SupportedHandler::match_candidate(&input, &hosts, 4)
        .unwrap()
        .is_some());
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

#[test]
fn first_pool_npm_handlers_match_real_graph_node_before_initialize() {
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
    expected.operations.retain(|op| op.handler_group_order <= 3);
    assert_eq!(run(&original(), &[0, 1, 2, 3]), expected);
}

fn npm_probe(name: &str) -> pb::ExtractorBlock {
    let mut b = original();
    let signature = |s: &str| alloy_primitives::keccak256(s).to_vec();
    let increase = b.candidates[2].clone();
    for c in &mut b.candidates {
        if c.log_index == 176 && name == "flash" {
            c.topics = vec![
                signature("Flash(address,address,uint256,uint256,uint256,uint256)"),
                word(7),
                word(8),
            ];
            c.data = vec![0; 128];
        }
        if c.log_index == 178 {
            if name == "decrease" {
                c.topics[0] = signature("DecreaseLiquidity(uint256,uint128,uint256,uint256)");
            }
            if matches!(name, "collect" | "negative_collect_fees") {
                c.topics[0] = signature("Collect(uint256,address,uint256,uint256)");
                c.data[..32].copy_from_slice(&word(9));
                if name == "negative_collect_fees" {
                    c.data[32..].fill(0);
                }
            }
        }
        if c.log_index == 177 {
            if name == "transfer_burn" {
                c.topics[2] = word(0);
            }
            if name == "negative_collect_fees" {
                c.topics = increase.topics.clone();
                c.topics[0] = signature("DecreaseLiquidity(uint256,uint128,uint256,uint256)");
                c.data = increase.data.clone();
            }
        }
    }
    b.candidates.retain(|c| {
        (c.log_index != 176 || name == "flash")
            && (c.log_index != 177 || name != "new_increase")
            && (name != "missing_tokens" || c.source == pb::DataSourceKind::PositionManager as i32)
    });
    if name == "missing_tokens" {
        b.pools_created.clear();
    }
    if name == "positions_reverted" {
        for p in &mut b.calls.as_mut().unwrap().positions {
            p.result = Some(pb::position_answer::Result::Reverted(
                pb::raw_retval::Null {},
            ));
        }
    }
    if matches!(name, "get_pool_zero" | "pool_guard") {
        for a in &mut b.calls.as_mut().unwrap().get_pool {
            if name == "get_pool_zero" {
                a.pool = vec![0; 20];
                a.created_block = 0;
            } else {
                a.pool = hex::decode("8fe8d9bb8eeba3ed688069c3d6b556c9ca258248").unwrap();
            }
        }
    }
    if name == "block_guard" {
        b.number = 14_317_993;
        for c in &mut b.candidates {
            if c.wave == 1 {
                c.host_order_key = 2 + b.number * (1 << 24) + 172;
            }
        }
        // These immutable synthetic answers are now carried from the original
        // creation block; zero provenance remains zero.
        let carry = |p: &mut Option<pb::SlotProvenance>| {
            if let Some(p) = p {
                if p.source == pb::SlotSource::InBlock as i32 {
                    p.source = pb::SlotSource::Carried as i32;
                }
            }
        };
        let calls = b.calls.as_mut().unwrap();
        for p in &mut calls.positions {
            if let Some(pb::position_answer::Result::Value(v)) = &mut p.result {
                carry(&mut v.p_key);
                carry(&mut v.p_fee0);
                carry(&mut v.p_fee1);
            }
        }
        for t in &mut calls.ticks {
            carry(&mut t.p_staked);
            carry(&mut t.p_fee0);
        }
    }
    if name == "flash" {
        let p = Some(pb::SlotProvenance {
            source: pb::SlotSource::InBlock as i32,
            last_change_block: b.number,
            last_change_ordinal: 1,
        });
        b.calls.as_mut().unwrap().fee_growth = vec![pb::FeeGrowthGlobalAnswer {
            pool: b.pools_created[0].pool.clone(),
            fee_growth_global0_x128: word(123),
            fee_growth_global1_x128: vec![255; 32],
            p0: p,
            p1: p,
        }];
    }
    if name.starts_with("existing_") {
        let keep = if name == "existing_transfer_no_calls" {
            177
        } else {
            178
        };
        b.candidates.retain(|c| c.log_index == keep);
        b.pools_created.clear();
        b.parent_hash = b.hash.clone();
        b.number += 1;
        b.hash = vec![68; 32];
        b.timestamp += 1;
        let mut calls = pb::CallAnswers::default();
        if name == "existing_fee_reverted" {
            calls.positions = vec![pb::PositionAnswer {
                token_id: original().calls.unwrap().positions[0].token_id.clone(),
                result: Some(pb::position_answer::Result::Reverted(
                    pb::raw_retval::Null {},
                )),
            }];
        }
        b.calls = Some(calls);
    }

    b
}
#[test]
fn npm_and_flash_match_every_operation_of_synthetic_graph_node_probes() {
    let corpus: Value =
        serde_json::from_slice(include_bytes!("../fixtures/graph-node-npm-flash.json")).unwrap();
    assert_eq!(corpus["cases"].as_array().unwrap().len(), 14);
    for case in corpus["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let b = npm_probe(name);
        let bytes = hex::decode(case["changes_hex"].as_str().unwrap()).unwrap();
        let expected = output::BlockChanges::decode(bytes.as_slice()).unwrap();
        assert_eq!(
            run_seeded(
                &b,
                &(0..b.candidates.len()).collect::<Vec<_>>(),
                case["seed_rows"].as_array().unwrap()
            ),
            expected,
            "{name}"
        );
    }
}
#[test]
fn absent_position_answer_is_fatal_even_for_try_positions() {
    let mut b = npm_probe("missing_tokens");
    b.calls.as_mut().unwrap().positions.clear();
    let binding = binding();
    let input = validate(&b);
    let backend = backend(&b, &binding);
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    let h = SupportedHandler::match_candidate(&input, &HostSet::default(), 0)
        .unwrap()
        .unwrap();
    assert!(store
        .run_handler(h.source_trigger_order(), |j| h.run(j).map(|_| ()))
        .unwrap_err()
        .0
        .contains("MissingCallAnswer"));
    assert!(store.seal().is_err());
}

#[test]
fn missing_flash_answer_poisons_the_block_after_earlier_successful_handlers() {
    let mut b = npm_probe("flash");
    b.calls.as_mut().unwrap().fee_growth.clear();
    let binding = binding();
    let input = validate(&b);
    let backend = backend(&b, &binding);
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    let mut hosts = HostSet::default();
    for index in 0..b.candidates.len() - 1 {
        let h = SupportedHandler::match_candidate(&input, &hosts, index)
            .unwrap()
            .unwrap();
        let mut created = None;
        store
            .run_handler(h.source_trigger_order(), |j| {
                created = h.run(j)?;
                Ok(())
            })
            .unwrap();
        if let Some(pool) = created {
            hosts.record_creation_outcome(&input, pool, true).unwrap();
        }
    }
    let h = SupportedHandler::match_candidate(&input, &hosts, b.candidates.len() - 1)
        .unwrap()
        .unwrap();
    assert!(store
        .run_handler(h.source_trigger_order(), |j| h.run(j).map(|_| ()))
        .unwrap_err()
        .0
        .contains("MissingCallAnswer"));
    assert!(store.seal().is_err());
    assert!(backend.rows().is_empty());
}
