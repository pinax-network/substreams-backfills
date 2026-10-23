use aerodrome_slipstream_reducer::pb;
use backfill_common::pb::pinax::graph::backfill::v2 as output;
use prost::Message;
use serde_json::Value;
#[path = "support/oracle.rs"]
mod oracle;
use oracle::{original, run_seeded};

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
    assert_eq!(run_seeded(&original(), &[0, 3, 4], &[]), expected);
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
