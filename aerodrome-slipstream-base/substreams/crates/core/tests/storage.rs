use aerodrome_extractor_core::{
    carry::{self, InMemoryCarry, StoreOp},
    config::{Config, PARAMS},
    keccak, layout,
    pb::{eth, internal as i, v1 as p},
    storage::storage_deltas,
    Address, Word,
};
use prost::Message;
use std::collections::{BTreeMap, HashMap};

const POOL: Address = [1; 20];
fn cfg() -> Config {
    Config::parse(PARAMS).unwrap()
}
fn registry() -> BTreeMap<Address, i::PoolRecord> {
    BTreeMap::from([(
        POOL,
        i::PoolRecord {
            tick_spacing: 1,
            created_block: 13_899_663,
            ..Default::default()
        },
    )])
}
fn change(address: Address, key: Word, old: Word, new: Word, ordinal: u64) -> eth::StorageChange {
    eth::StorageChange {
        address: address.to_vec(),
        key: key.to_vec(),
        old_value: old.to_vec(),
        new_value: new.to_vec(),
        ordinal,
    }
}
fn fee(old: u128, new: u128, ordinal: u64) -> eth::StorageChange {
    change(
        POOL,
        layout::uint_word(7),
        layout::uint_word(old),
        layout::uint_word(new),
        ordinal,
    )
}
fn call(changes: Vec<eth::StorageChange>, reverted: bool) -> eth::Call {
    eth::Call {
        // Neither call.address nor its caller is the changed pool.
        address: vec![9; 20],
        caller: vec![8; 20],
        state_reverted: reverted,
        status_failed: false,
        status_reverted: false,
        storage_changes: changes,
        ..Default::default()
    }
}
fn block(calls: Vec<eth::Call>) -> eth::Block {
    eth::Block {
        number: 13_899_663,
        ver: 5,
        transaction_traces: vec![eth::TransactionTrace {
            index: 5,
            status: 1,
            calls,
            ..Default::default()
        }],
        ..Default::default()
    }
}
fn mapping(key: Word, slot: u128) -> (Word, HashMap<String, String>) {
    let mut preimage = key.to_vec();
    preimage.extend(layout::uint_word(slot));
    let base = keccak(&preimage);
    (
        base,
        HashMap::from([(hex::encode(base), hex::encode(preimage))]),
    )
}
fn plus(mut value: Word, n: u8) -> Word {
    for _ in 0..n {
        for byte in value.iter_mut().rev() {
            let (v, carry) = byte.overflowing_add(1);
            *byte = v;
            if !carry {
                break;
            }
        }
    }
    value
}

#[test]
fn ordinal_order_and_ancestor_rollback_win_over_vector_order_and_call_address() {
    let mut b = block(vec![
        call(vec![fee(11, 99, 40)], true),
        call(vec![fee(7, 11, 30)], false),
        call(vec![fee(3, 7, 10)], false),
    ]);
    b.transaction_traces.push(eth::TransactionTrace {
        index: 7,
        status: 2,
        calls: vec![call(vec![fee(11, 88, 50)], false)],
        ..Default::default()
    });
    let out = storage_deltas(&cfg(), &b, &registry()).unwrap();
    assert!(out.anomalies.is_empty());
    assert_eq!((out.relevant_writes, out.reverted_writes_skipped), (2, 2));
    assert_eq!(out.fee_growth.len(), 1);
    let w = out.fee_growth[0].write.as_ref().unwrap();
    assert_eq!((w.ordinal, w.tx_index, w.reverted_skipped), (30, 5, 2));
    assert_eq!(w.word, layout::uint_word(11));
    b.transaction_traces[0].calls.reverse();
    b.transaction_traces.reverse();
    assert_eq!(storage_deltas(&cfg(), &b, &registry()).unwrap(), out);
}

#[test]
fn only_reverted_writes_leave_carry_untouched() {
    let initial = storage_deltas(
        &cfg(),
        &block(vec![call(vec![fee(0, 15, 2)], false)]),
        &registry(),
    )
    .unwrap();
    let mut carry = InMemoryCarry::default();
    carry.apply(&carry::pool_slot_ops(&initial, 13_899_662).unwrap());
    let out = storage_deltas(
        &cfg(),
        &block(vec![call(vec![fee(15, 90, 5)], true)]),
        &registry(),
    )
    .unwrap();
    assert_eq!((out.relevant_writes, out.reverted_writes_skipped), (0, 1));
    assert!(out.fee_growth.is_empty());
    carry.apply(&carry::pool_slot_ops(&out, 13_899_663).unwrap());
    let saved =
        i::SlotWord::decode(carry.get(&format!("f:{}:0;", hex::encode(POOL))).unwrap()).unwrap();
    assert_eq!(saved.word, vec![15]);
    assert_eq!(saved.block, 13_899_662);
}

#[test]
fn initialized_then_cleared_tick_keeps_marker_and_deletes_words_in_exactly_one_shard() {
    let (base, pre) = mapping(layout::int_word(-1), 17);
    let mut c = call(
        vec![
            change(POOL, plus(base, 2), layout::uint_word(5), [0; 32], 50),
            change(POOL, base, layout::uint_word(10), [0; 32], 40),
            change(POOL, base, [0; 32], layout::uint_word(10), 10),
        ],
        false,
    );
    c.keccak_preimages = pre;
    let out = storage_deltas(&cfg(), &block(vec![c]), &registry()).unwrap();
    assert!(out.anomalies.is_empty());
    assert_eq!(
        out.ticks.iter().map(|v| v.member).collect::<Vec<_>>(),
        vec![0, 2]
    );
    let ops: Vec<_> = (0..8)
        .flat_map(|s| carry::tick_slot_ops(&out, 42, s).unwrap())
        .collect();
    assert_eq!(ops.len(), 2);
    assert!(matches!(ops[0], StoreOp::Set { .. }));
    assert!(matches!(ops[1], StoreOp::Delete { .. }));
}

#[test]
fn marker_requires_a_successful_zero_to_nonzero_write() {
    let (base, pre) = mapping(layout::int_word(1), 17);
    let mut reverted = call(
        vec![change(POOL, base, [0; 32], layout::uint_word(3), 5)],
        true,
    );
    reverted.keccak_preimages = pre;
    let successful = call(
        vec![change(
            POOL,
            base,
            layout::uint_word(7),
            layout::uint_word(8),
            10,
        )],
        false,
    );
    assert!(
        storage_deltas(&cfg(), &block(vec![reverted, successful]), &registry())
            .unwrap()
            .ticks
            .is_empty()
    );
}

#[test]
fn position_fragment_uses_first_old_across_reverted_writes_and_ignores_liquidity() {
    let (base, pre) = mapping(layout::uint_word(17), 13);
    let old = layout::uint_word(1);
    let mut liquidity_only = old;
    liquidity_only[0] = 7;
    let mut reverted = call(
        vec![change(
            cfg().npm,
            plus(base, 1),
            old,
            layout::uint_word(9),
            5,
        )],
        true,
    );
    reverted.keccak_preimages = pre;
    let committed = call(
        vec![change(cfg().npm, plus(base, 1), old, liquidity_only, 10)],
        false,
    );
    let mut b = block(vec![committed, reverted]);
    assert!(storage_deltas(&cfg(), &b, &registry())
        .unwrap()
        .positions
        .is_empty());
    b.transaction_traces[0].calls[0].storage_changes[0]
        .new_value
        .fill(0);
    let out = storage_deltas(&cfg(), &b, &registry()).unwrap();
    assert_eq!(out.positions.len(), 1);
    assert!(matches!(
        carry::position_slot_ops(&out, b.number, 1).unwrap()[0],
        StoreOp::Delete { .. }
    ));
}

#[test]
fn ties_layout_drift_and_system_writes_are_not_admitted_to_carry() {
    let mut b = block(vec![call(vec![fee(1, 2, 3), fee(2, 3, 3)], false)]);
    b.system_calls.push(call(
        vec![change(
            POOL,
            layout::uint_word(90_000),
            [0; 32],
            layout::uint_word(1),
            5,
        )],
        false,
    ));
    let out = storage_deltas(&cfg(), &b, &registry()).unwrap();
    for kind in [
        p::AnomalyKind::AnomalyOrdinalTie,
        p::AnomalyKind::AnomalyUnclassifiedPoolSlot,
        p::AnomalyKind::AnomalySystemCallTouchedTarget,
    ] {
        assert!(out.anomalies.iter().any(|a| a.kind == kind as i32));
    }
    assert!(out.fee_growth.is_empty());
    assert!(carry::pool_slot_ops(&out, b.number).is_err());
    assert!(carry::tick_slot_ops(&out, b.number, 0).is_err());
    assert!(carry::position_slot_ops(&out, b.number, 0).is_err());
}

#[test]
fn alignment_version_preimage_and_wire_truncation_refusals() {
    let (base, pre) = mapping(layout::int_word(1), 17);
    let mut c = call(
        vec![change(
            POOL,
            plus(base, 1),
            [0; 32],
            layout::uint_word(1),
            5,
        )],
        false,
    );
    c.keccak_preimages = pre;
    let mut b = block(vec![c]);
    let mut r = registry();
    r.get_mut(&POOL).unwrap().tick_spacing = 10;
    let out = storage_deltas(&cfg(), &b, &r).unwrap();
    assert_eq!(
        out.anomalies[0].kind,
        p::AnomalyKind::AnomalyTickAlignment as i32
    );
    b.ver = 3;
    assert_eq!(
        storage_deltas(&cfg(), &b, &r).unwrap().anomalies[0].kind,
        p::AnomalyKind::AnomalyUnsupportedBlockVersion as i32
    );
    b.ver = 4;
    b.transaction_traces[0].calls[0].storage_changes[0]
        .new_value
        .push(0);
    assert!(storage_deltas(&cfg(), &b, &r).is_err());
    b.transaction_traces[0].calls[0].storage_changes[0]
        .new_value
        .pop();
    *b.transaction_traces[0].calls[0]
        .keccak_preimages
        .values_mut()
        .next()
        .unwrap() = "11".repeat(64);
    assert!(storage_deltas(&cfg(), &b, &r).is_err());
}

#[test]
fn deployment_start_and_uint80_pool_id_are_checked() {
    let (base, pre) = mapping(layout::uint_word(1u128 << 64), 12);
    let mut c = call(
        vec![change(cfg().npm, base, [0; 32], layout::uint_word(9), 5)],
        false,
    );
    c.keccak_preimages = pre;
    let mut b = block(vec![c]);
    assert!(storage_deltas(&cfg(), &b, &BTreeMap::new()).is_err());
    b.number = cfg().npm_start - 1;
    assert!(storage_deltas(&cfg(), &b, &BTreeMap::new())
        .unwrap()
        .pool_keys
        .is_empty());
}

#[test]
fn tick_carry_uses_log_ordinals_not_wave_order_and_retains_signed_ticks() {
    let event = |tick, ordinal, swap| {
        let mut data = vec![0; if swap { 160 } else { 64 }];
        let end = data.len();
        data[end - 32..].copy_from_slice(&layout::int_word(tick));
        p::CandidateLog {
            address: POOL.to_vec(),
            source: p::DataSourceKind::Pool as i32,
            abi_decoded: true,
            topics: vec![keccak(if swap {
                b"Swap(address,address,int256,int256,uint160,uint128,int24)"
            } else {
                b"Initialize(uint160,int24)"
            })
            .to_vec()],
            data,
            log_ordinal: ordinal,
            ..Default::default()
        }
    };
    let mut b = p::ExtractorBlock {
        candidates: vec![event(-100, 30, true), event(0, 10, false)],
        audit: Some(p::ExtractorAudit::default()),
        ..Default::default()
    };
    b.candidates[0].topics.extend([vec![0; 32], vec![0; 32]]);
    let ops = carry::last_tick_ops(&b).unwrap();
    assert_eq!(
        ops.iter()
            .map(|(_, tick, ord)| (*tick, *ord))
            .collect::<Vec<_>>(),
        vec![(0, 10), (-100, 30)]
    );
    b.candidates[0].abi_decoded = false;
    b.candidates[0].data.clear();
    assert_eq!(carry::last_tick_ops(&b).unwrap().len(), 1);
    b.candidates[0].abi_decoded = true;
    assert_eq!(carry::last_tick_ops(&b).unwrap().len(), 1);
    b.candidates[1].abi_decoded = false;
    b.candidates[1].data.extend([0; 32]);
    assert_eq!(
        carry::last_tick_ops(&b).unwrap().len(),
        1,
        "Graph Node accepts trailing data despite Abigen flag"
    );
}

#[test]
fn tick_carry_matches_independent_graph_node_decode_or_refuses_unsupported_domain() {
    let corpus: serde_json::Value = serde_json::from_str(include_str!(
        "../../../fixtures/tick-decoder-graph-node.json"
    ))
    .unwrap();
    assert_eq!(corpus["alloy_dyn_abi"], "1.7.2");
    let mut counts = [0, 0, 0];
    for case in corpus["events"].as_array().unwrap() {
        let candidate = p::CandidateLog {
            source: p::DataSourceKind::Pool as i32,
            address: POOL.to_vec(),
            topics: case["topics"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| hex::decode(v.as_str().unwrap()).unwrap())
                .collect(),
            data: hex::decode(case["data"].as_str().unwrap()).unwrap(),
            log_ordinal: 100,
            // Deliberately false for every case: Abigen is never authoritative.
            abi_decoded: false,
            ..Default::default()
        };
        let block = p::ExtractorBlock {
            candidates: vec![candidate],
            audit: Some(p::ExtractorAudit::default()),
            ..Default::default()
        };
        let result = carry::last_tick_ops(&block);
        match case["result"].as_array() {
            None => {
                assert!(result.unwrap().is_empty(), "{case}");
                counts[0] += 1;
            }
            Some(fields) => {
                let value = fields.iter().find(|v| v["name"] == "tick").unwrap()["value"]
                    .as_str()
                    .unwrap();
                let value = value
                    .strip_prefix("Int(")
                    .unwrap()
                    .strip_suffix(", 24)")
                    .unwrap();
                let supported = value
                    .parse::<i64>()
                    .ok()
                    .filter(|v| (-8_388_608..=8_388_607).contains(v));
                if let Some(tick) = supported {
                    let operations = result.unwrap();
                    assert_eq!(operations.len(), 1);
                    assert_eq!(operations[0].1, tick, "{case}");
                    counts[1] += 1;
                } else {
                    assert!(result.is_err(), "{case}");
                    counts[2] += 1;
                }
            }
        }
    }
    assert_eq!(counts, [12, 8, 10]);
}
