use aerodrome_slipstream_reducer::pb;
use backfill_common::pb::pinax::graph::backfill::v2 as output;
use prost::Message;
use serde_json::Value;
#[path = "support/oracle.rs"]
mod oracle;

fn bytes(value: &Value) -> Vec<u8> {
    hex::decode(value.as_str().unwrap().trim_start_matches("0x")).unwrap()
}

#[test]
fn seeded_swaps_match_every_independent_wasm_operation_and_abort() {
    let corpus: Value =
        serde_json::from_slice(include_bytes!("../fixtures/graph-node-swap-handlers.json"))
            .unwrap();
    assert!(corpus["cases"].as_array().unwrap().len() >= 15);
    for case in corpus["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut b = oracle::original();
        b.parent_hash = b.hash.clone();
        b.number += 1;
        b.hash = vec![68; 32];
        b.timestamp = case["timestamp"].as_u64().unwrap();
        let mut candidate = b.candidates[4].clone();
        candidate.wave = 0;
        candidate.address = bytes(&case["log"]["address"]);
        candidate.topics = case["log"]["topics"]
            .as_array()
            .unwrap()
            .iter()
            .map(bytes)
            .collect();
        candidate.data = bytes(&case["log"]["data"]);
        let pool = candidate.address.clone();
        b.candidates = vec![candidate];
        b.pools_created.clear();
        let provenance = Some(pb::SlotProvenance {
            source: pb::SlotSource::InBlock as i32,
            last_change_block: b.number,
            last_change_ordinal: 1,
        });
        let mut calls = pb::CallAnswers::default();
        let mut growth = pb::FeeGrowthGlobalAnswer {
            pool: pool.clone(),
            p0: provenance,
            p1: provenance,
            ..Default::default()
        };
        for call in case["raw_calls"].as_array().unwrap() {
            let result = bytes(&call["retval"]["data"]);
            match call["function"].as_str().unwrap() {
                "feeGrowthGlobal0X128()" => growth.fee_growth_global0_x128 = result,
                "feeGrowthGlobal1X128()" => growth.fee_growth_global1_x128 = result,
                "ticks(int24)" => {
                    let argument = bytes(&call["calldata"]);
                    let tick =
                        i32::from_be_bytes(argument[argument.len() - 4..].try_into().unwrap());
                    calls.ticks.push(pb::TickAnswer {
                        pool: pool.clone(),
                        tick,
                        staked_liquidity_net: result[80..96].to_vec(),
                        fee_growth_outside0_x128: result[96..128].to_vec(),
                        p_staked: provenance,
                        p_fee0: provenance,
                        reasons: 2,
                    });
                }
                // The deployed getPool getter-copy mutations are intentionally
                // lost. Retain the actual calls in the independent oracle.
                "getPool(address,address,int24)" => (),
                function => panic!("unexpected oracle function {function}"),
            }
        }
        calls.fee_growth.push(growth);
        b.calls = Some(calls);
        let got = oracle::run_seeded(&b, &[0], case["seed_rows"].as_array().unwrap());
        let expected =
            output::BlockChanges::decode(bytes(&case["changes_hex"]).as_slice()).unwrap();
        assert_eq!(
            got.operations.len(),
            expected.operations.len(),
            "{name}: operation count"
        );
        for (index, (a, b)) in got.operations.iter().zip(&expected.operations).enumerate() {
            assert_eq!(a, b, "{name}: operation {index}");
        }
        assert_eq!(got, expected, "{name}: entire envelope");
    }
}
