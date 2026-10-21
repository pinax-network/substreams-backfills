use aerodrome_extractor_core::config::{Config, CONTRACT, DEPLOYMENT, INITIAL_BLOCK, PARAMS};
use aerodrome_slipstream_reducer::{
    abi::Abis,
    calls::{graph_store_string, token_metadata, CallBook},
    identity::{entity_types, InputBinding, OUTPUT_MODULE, OUTPUT_TYPE},
    input::{validate_block, InputStream},
    pb,
};
use alloy_dyn_abi::DynSolValue;
use backfill_common::{
    clock::{write_frame, Frame, FrameKind},
    descriptor::ExtractorIdentity,
};
use prost::Message;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::Cursor;
fn bytes(v: &Value) -> Vec<u8> {
    hex::decode(v.as_str().unwrap_or("")).unwrap()
}
fn n(v: &Value) -> u64 {
    v.as_u64().unwrap_or(0)
}
fn raw(value: Vec<u8>) -> pb::RawRetval {
    pb::RawRetval {
        kind: Some(pb::raw_retval::Kind::Value(value)),
    }
}
fn reverted() -> pb::RawRetval {
    pb::RawRetval {
        kind: Some(pb::raw_retval::Kind::Reverted(pb::raw_retval::Null {})),
    }
}
fn value_word(value: u64) -> Vec<u8> {
    let mut out = vec![0; 32];
    out[24..].copy_from_slice(&value.to_be_bytes());
    out
}
fn empty(number: u64, hash: u8, parent: u8) -> pb::ExtractorBlock {
    pb::ExtractorBlock {
        number,
        hash: vec![hash; 32],
        parent_hash: vec![parent; 32],
        timestamp: 1700000000 + number,
        contract: CONTRACT.into(),
        firehose_block_version: 4,
        audit: Some(pb::ExtractorAudit::default()),
        calls: Some(pb::CallAnswers::default()),
        ..Default::default()
    }
}
fn frame(b: &pb::ExtractorBlock) -> Frame {
    Frame {
        kind: FrameKind::Observed,
        block_number: b.number,
        block_hash: b.hash.clone().try_into().unwrap(),
        payload: b.encode_to_vec(),
    }
}
fn validate(
    b: &pb::ExtractorBlock,
) -> aerodrome_slipstream_reducer::Result<aerodrome_slipstream_reducer::input::BlockInput> {
    validate_block(&frame(b), b.parent_hash.clone().try_into().unwrap())
}
fn descriptor() -> (Value, ExtractorIdentity) {
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    (
        json!({"contract":"pinax.graph.backfill.block-changes/v1","descriptor_version":2,"deterministic_error_policy":"non_fatal","network":"base","expected_poi_causality_region":"ethereum/base","deployment":DEPLOYMENT,"spec_version":"1.2.0","manifest_features":["nonFatalErrors","grafting"],"start_block":INITIAL_BLOCK,"graph_node":{"version":"0.44.0","commit":graph_numerics::GRAPH_NODE_COMMIT,"poi_version":"fast"},"storage_profile":{"entity_types":entity_types()},"data_sources":{"transport":"in_band_v1","templates":[{"name":"Pool","manifest_idx":2,"param":"address20"}]},"entity_retention":{"version":1,"default":"persistent","types":{},"evidence":[]},"producer_contract":{"kind":"native_block_changes_reducer","reducer":{"repository":"pinax-network/substreams-backfills","commit":"33".repeat(20)},"extractor":extractor}}),
        extractor,
    )
}
fn bind(v: Value, e: &ExtractorIdentity) -> aerodrome_slipstream_reducer::Result<InputBinding> {
    let bytes = serde_json::to_vec(&v).unwrap();
    InputBinding::new(&bytes, Sha256::digest(&bytes).into(), e)
}
fn binding() -> InputBinding {
    let (v, e) = descriptor();
    bind(v, &e).unwrap()
}
// Actual first-pool log projection, with an explicitly SYNTHETIC empty answer
// book. This fixture validates transport/order/ABI only, never handler parity.
fn first_pool() -> pb::ExtractorBlock {
    let v: Value = serde_json::from_slice(include_bytes!(
        "../../../aerodrome-slipstream-base/substreams/fixtures/candidates-13899663.json"
    ))
    .unwrap();
    let cfg = Config::parse(PARAMS).unwrap();
    let t = &v["transactions"][55];
    let block = n(&v["number"]);
    let tx = pb::Transaction {
        hash: bytes(&t["hash"]),
        index: 55,
        from: bytes(&t["from"]),
        to: bytes(&t["to"]),
        gas_limit: n(&t["gas_limit"]),
        r#type: n(&t["type"]) as u32,
        gas_price: Some(bytes(&t["gas_price"]["bytes"])),
        max_fee_per_gas: Some(bytes(&t["max_fee_per_gas"]["bytes"])),
        max_priority_fee_per_gas: Some(bytes(&t["max_priority_fee_per_gas"]["bytes"])),
        graph_gas_price: hex::decode("05ea909e").unwrap(),
    };
    let logs = t["logs"].as_array().unwrap();
    let creation = logs.iter().find(|l| n(&l["blockIndex"]) == 172).unwrap();
    let data = bytes(&creation["data"]);
    let fact = pb::PoolCreatedFact {
        pool: data[12..32].to_vec(),
        token0: bytes(&creation["topics"][1])[12..].to_vec(),
        token1: bytes(&creation["topics"][2])[12..].to_vec(),
        tick_spacing: 1,
        log_index: 172,
        clone_implementation: cfg.pool_implementation.to_vec(),
        log_ordinal: n(&creation["ordinal"]),
    };
    let candidates = [(0, 172), (0, 177), (0, 178), (1, 171), (1, 176)]
        .iter()
        .map(|&(wave, index)| {
            let l = logs.iter().find(|l| n(&l["blockIndex"]) == index).unwrap();
            pb::CandidateLog {
                wave,
                source_trigger_order: index as u32,
                log_index: index as u32,
                tx: 0,
                address: bytes(&l["address"]),
                topics: l["topics"].as_array().unwrap().iter().map(bytes).collect(),
                data: bytes(&l["data"]),
                log_ordinal: n(&l["ordinal"]),
                source: if index == 172 {
                    1
                } else if wave == 0 {
                    2
                } else {
                    3
                },
                host_order_key: if index == 172 {
                    0
                } else if wave == 0 {
                    1
                } else {
                    2 + block * (1 << 24) + 172
                },
                abi_decoded: true,
            }
        })
        .collect();
    pb::ExtractorBlock {
        number: block,
        hash: bytes(&v["hash"]),
        parent_hash: bytes(&v["header"]["parent_hash"]),
        timestamp: n(&v["header"]["timestamp"]["seconds"]),
        base_fee_per_gas: Some(98354726),
        receipt_log_count: 209,
        transactions: vec![tx],
        candidates,
        pools_created: vec![fact],
        calls: Some(pb::CallAnswers::default()),
        firehose_block_version: 4,
        audit: Some(pb::ExtractorAudit::default()),
        contract: CONTRACT.into(),
    }
}
#[test]
fn actual_first_pool_order_is_rematched_with_graph_nodes_abi() {
    let b = first_pool();
    let input = validate(&b).unwrap();
    assert_eq!(
        input
            .decoded()
            .iter()
            .map(|e| e.as_ref().unwrap().name.as_str())
            .collect::<Vec<_>>(),
        vec![
            "PoolCreated",
            "Transfer",
            "IncreaseLiquidity",
            "Initialize",
            "Mint"
        ]
    );
    assert_eq!(input.gas_prices(), vec![99258526]);
    assert!(input
        .calls()
        .position(&[0; 32])
        .unwrap_err()
        .0
        .contains("MissingCallAnswer"));
    let mut candidate_only = b;
    candidate_only.calls = None;
    assert!(validate(&candidate_only)
        .unwrap_err()
        .0
        .contains("candidate-only"));
}
#[test]
fn malformed_event_data_is_not_a_trigger_or_a_missing_candidate() {
    let mut b = first_pool();
    b.candidates[4].data.clear();
    b.candidates[4].abi_decoded = false;
    b.audit.as_mut().unwrap().candidate_decode_failures = 1;
    let out = validate(&b).unwrap();
    assert!(out.decoded()[4].is_none());
    assert_eq!(out.block().candidates.len(), 5);
    // Graph Node's alloy accepts excess trailing data; the extractor's ABI flag
    // is only audit information and must not decide whether a handler matches.
    b.candidates[4] = first_pool().candidates[4].clone();
    b.candidates[4].data.extend([0; 32]);
    b.candidates[4].abi_decoded = false;
    assert!(validate(&b).unwrap().decoded()[4].is_some());
}
#[test]
fn candidate_and_header_corruption_are_refused() {
    let b = first_pool();
    type Mutation = Box<dyn Fn(&mut pb::ExtractorBlock)>;
    let mutations: Vec<Mutation> = vec![
        Box::new(|b| b.contract.push('x')),
        Box::new(|b| b.firehose_block_version = 6),
        Box::new(|b| b.audit = None),
        Box::new(|b| {
            b.audit
                .as_mut()
                .unwrap()
                .anomalies
                .push(pb::Anomaly::default())
        }),
        Box::new(|b| b.candidates.swap(0, 1)),
        Box::new(|b| b.candidates[3].wave = 0),
        Box::new(|b| b.candidates[3].host_order_key = 2),
        Box::new(|b| b.candidates[0].log_index = 171),
        Box::new(|b| b.candidates[0].tx = 1),
        Box::new(|b| b.candidates[0].topics[0][0] ^= 1),
        Box::new(|b| b.candidates[0].address[0] ^= 1),
        Box::new(|b| b.candidates[0].source = 99),
        Box::new(|b| b.candidates[0].log_ordinal = 0),
        Box::new(|b| b.candidates[1].source = 3),
        Box::new(|b| b.pools_created[0].tick_spacing = 2),
        Box::new(|b| b.pools_created[0].clone_implementation[0] ^= 1),
        Box::new(|b| b.pools_created.clear()),
        Box::new(|b| b.transactions[0].graph_gas_price = vec![1]),
        Box::new(|b| b.transactions[0].max_fee_per_gas = Some(vec![0, 1])),
        Box::new(|b| b.transactions.push(b.transactions[0].clone())),
    ];
    for (i, mutation) in mutations.iter().enumerate() {
        let mut changed = b.clone();
        mutation(&mut changed);
        assert!(validate(&changed).is_err(), "mutation {i}");
    }
    let f = frame(&b);
    assert!(validate_block(&f, [1; 32]).is_err());
    let mut bad = f.clone();
    bad.block_number += 1;
    assert!(validate_block(&bad, b.parent_hash.clone().try_into().unwrap()).is_err());
    let mut bad = f;
    bad.payload.extend([0xa0, 0x06, 1]);
    assert!(validate_block(&bad, b.parent_hash.try_into().unwrap()).is_err());
}
#[test]
fn range_requires_complete_observed_eof_and_poisoning_is_permanent() {
    let a = empty(INITIAL_BLOCK, 1, 9);
    let b = empty(INITIAL_BLOCK + 1, 2, 1);
    let mut bytes = Vec::new();
    write_frame(&mut bytes, &frame(&a)).unwrap();
    write_frame(&mut bytes, &frame(&b)).unwrap();
    let mut stream =
        InputStream::new(Cursor::new(&bytes), binding(), a.number, b.number, [9; 32]).unwrap();
    assert!(stream.next_block().unwrap().is_some());
    assert!(stream.next_block().unwrap().is_some());
    assert!(stream.next_block().unwrap().is_none());
    assert_eq!(stream.finish().unwrap(), [2; 32]);
    for end in [0, 1, 51, bytes.len() - 1] {
        let mut s = InputStream::new(
            Cursor::new(&bytes[..end]),
            binding(),
            a.number,
            b.number,
            [9; 32],
        )
        .unwrap();
        while matches!(s.next_block(), Ok(Some(_))) {}
        assert!(s.finish().is_err(), "cut {end}");
    }
    let mut s =
        InputStream::new(Cursor::new(&bytes), binding(), a.number, a.number, [9; 32]).unwrap();
    s.next_block().unwrap();
    assert!(s.next_block().is_err());
    assert!(s.next_block().is_err());
    assert!(s.finish().is_err());
    let s = InputStream::new(Cursor::new(&bytes), binding(), a.number, b.number, [9; 32]).unwrap();
    assert!(s.finish().is_err());
    let synthetic = Frame {
        kind: FrameKind::SyntheticRangeFill,
        block_number: a.number,
        block_hash: [0; 32],
        payload: vec![],
    };
    let mut bytes = Vec::new();
    write_frame(&mut bytes, &synthetic).unwrap();
    let mut s =
        InputStream::new(Cursor::new(bytes), binding(), a.number, a.number, [9; 32]).unwrap();
    assert!(s.next_block().is_err());
}
#[test]
fn identity_is_bound_to_exact_descriptor_and_final_module() {
    let (v, e) = descriptor();
    assert_eq!(entity_types().len(), 20);
    assert!(bind(v.clone(), &e).is_ok());
    for (field, value) in [
        ("module", json!("map_candidates")),
        ("output_type", json!("proto:wrong.Type")),
        ("spkg_sha256", json!("aa".repeat(32))),
        ("module_hash", json!("bb".repeat(20))),
    ] {
        let mut x = v.clone();
        x["producer_contract"]["extractor"][field] = value;
        assert!(bind(x, &e).is_err());
    }
    let mut wrong = v.clone();
    wrong["deployment"] = json!("wrong");
    assert!(bind(wrong, &e).is_err());
    let mut wrong = v.clone();
    wrong["storage_profile"]["entity_types"] = json!(["Pool"]);
    assert!(bind(wrong, &e).is_err());
    for field in ["graft", "concrete_graft"] {
        let mut explicit_null = v.clone();
        explicit_null[field] = Value::Null;
        assert!(bind(explicit_null, &e).is_ok());
        for graft in [json!({"base":"other", "block":INITIAL_BLOCK}), json!(false)] {
            let mut wrong = v.clone();
            wrong[field] = graft;
            assert!(bind(wrong, &e).is_err());
        }
    }
    let mut wrong = v.clone();
    wrong["graph_node"]["poi_version"] = json!("legacy");
    assert!(bind(wrong, &e).is_err());
    let mut wrong = v.clone();
    wrong["network"] = json!("mainnet");
    assert!(bind(wrong.clone(), &e).is_err());
    wrong["expected_poi_causality_region"] = json!("ethereum/mainnet");
    assert!(bind(wrong, &e).is_err());
    let bytes = serde_json::to_vec(&v).unwrap();
    assert!(InputBinding::new(&bytes, [0; 32], &e).is_err());
}
fn erc20() -> pb::Erc20Answer {
    pb::Erc20Answer {
        token: vec![7; 20],
        symbol: Some(raw(DynSolValue::String("SYMBOL".into()).abi_encode())),
        name: Some(raw(DynSolValue::String("Name".into()).abi_encode())),
        total_supply: Some(raw(value_word(100))),
        decimals: Some(raw(value_word(18))),
        ..Default::default()
    }
}
#[test]
fn erc20_uses_same_raw_return_for_string_and_bytes32_fallback() {
    let mut a = erc20();
    let m = token_metadata(&a).unwrap();
    assert_eq!(m.symbol, "SYMBOL");
    assert_eq!(m.name, "Name");
    assert_eq!(m.decimals, 18);
    assert_eq!(m.total_supply.to_string(), "100");
    let mut b = vec![0; 32];
    b[..5].copy_from_slice(b"M\0KR!");
    a.symbol = Some(raw(b));
    assert_eq!(token_metadata(&a).unwrap().symbol, "M\0KR!");
    assert_eq!(
        graph_store_string(&token_metadata(&a).unwrap().symbol),
        "MKR!"
    );
    a.symbol = Some(raw(value_word(1)));
    assert_eq!(token_metadata(&a).unwrap().symbol, "unknown");
    a.symbol = Some(raw(vec![0; 32]));
    assert_eq!(token_metadata(&a).unwrap().symbol, "");
    a.symbol = Some(raw(vec![0xff; 32]));
    assert_eq!(token_metadata(&a).unwrap().symbol, "�".repeat(32));
    for (v, want) in [(0, 0), (18, 18), (255, 255), (256, 0), (u64::MAX, 0)] {
        a.decimals = Some(raw(value_word(v)));
        assert_eq!(token_metadata(&a).unwrap().decimals, want);
    }
    a.name = Some(reverted());
    a.total_supply = Some(reverted());
    a.rpc_failed_mask = 2;
    a.rpc_empty_mask = 4;
    let m = token_metadata(&a).unwrap();
    assert_eq!(m.name, "unknown");
    assert_eq!(m.total_supply.to_string(), "0");
    a.total_supply = Some(raw(vec![1]));
    a.rpc_empty_mask = 0;
    assert_eq!(token_metadata(&a).unwrap().total_supply.to_string(), "0");
}
#[test]
fn callbook_missing_duplicate_width_and_provenance_never_become_reverts() {
    let mut b = empty(INITIAL_BLOCK, 1, 9);
    b.calls.as_mut().unwrap().erc20.push(erc20());
    let book = CallBook::from_block(&b).unwrap();
    assert_eq!(book.unused_answer_count(), 1);
    assert!(book
        .erc20(&[8; 20])
        .unwrap_err()
        .0
        .contains("MissingCallAnswer"));
    book.erc20(&[7; 20]).unwrap();
    book.erc20(&[7; 20]).unwrap();
    assert_eq!(book.unused_answer_count(), 0);
    let a = b.calls.as_ref().unwrap().erc20[0].clone();
    b.calls.as_mut().unwrap().erc20.push(a);
    assert!(CallBook::from_block(&b).is_err());
    b.calls.as_mut().unwrap().erc20.pop();
    for mutate in [0, 1, 2, 3] {
        let mut x = b.clone();
        let a = &mut x.calls.as_mut().unwrap().erc20[0];
        match mutate {
            0 => a.symbol = None,
            1 => a.symbol = Some(raw(vec![])),
            2 => a.rpc_failed_mask = 1,
            _ => a.rpc_failed_mask = 16,
        };
        assert!(CallBook::from_block(&x).is_err());
    }
    let zero = Some(pb::SlotProvenance {
        source: pb::SlotSource::Zero as i32,
        ..Default::default()
    });
    b.calls
        .as_mut()
        .unwrap()
        .fee_growth
        .push(pb::FeeGrowthGlobalAnswer {
            pool: vec![5; 20],
            fee_growth_global0_x128: vec![0; 32],
            fee_growth_global1_x128: vec![0; 32],
            p0: zero,
            p1: zero,
        });
    assert!(CallBook::from_block(&b).is_ok());
    b.calls.as_mut().unwrap().fee_growth[0].fee_growth_global0_x128[0] = 1;
    assert!(CallBook::from_block(&b).is_err());
    b.calls.as_mut().unwrap().fee_growth.clear();
    b.calls
        .as_mut()
        .unwrap()
        .positions
        .push(pb::PositionAnswer {
            token_id: vec![1],
            result: Some(pb::position_answer::Result::Reverted(
                pb::raw_retval::Null {},
            )),
        });
    let book = CallBook::from_block(&b).unwrap();
    let mut id = [0; 32];
    id[31] = 1;
    assert!(matches!(
        book.position(&id).unwrap().result,
        Some(pb::position_answer::Result::Reverted(_))
    ));
    b.calls.as_mut().unwrap().positions[0].token_id = vec![0, 1];
    assert!(CallBook::from_block(&b).is_err());
}
#[test]
fn exact_decoder_retains_field_order_and_signed_values() {
    let input = validate(&first_pool()).unwrap();
    let mint = input.decoded()[4].as_ref().unwrap();
    assert_eq!(
        mint.params.iter().map(|p| p.0.as_str()).collect::<Vec<_>>(),
        vec![
            "sender",
            "owner",
            "tickLower",
            "tickUpper",
            "amount",
            "amount0",
            "amount1"
        ]
    );
    assert_eq!(
        mint.param("tickLower")
            .unwrap()
            .as_int()
            .unwrap()
            .0
            .to_string(),
        "-1"
    );
    assert!(Abis::locked().event(99, &[0; 32]).is_none());
}

#[test]
fn host_creation_is_authoritative_and_aborted_creation_is_an_explicit_explanation() {
    use aerodrome_slipstream_reducer::hosts::HostSet;
    let input = validate(&first_pool()).unwrap();
    let pool = input.block().pools_created[0]
        .pool
        .as_slice()
        .try_into()
        .unwrap();
    let mut hosts = HostSet::default();
    assert!(hosts.match_candidate(&input, 0).unwrap().is_some());
    assert!(hosts
        .match_candidate(&input, 3)
        .unwrap_err()
        .0
        .contains("UnknownPoolHost"));
    hosts.record_creation_outcome(&input, pool, true).unwrap();
    assert!(hosts.match_candidate(&input, 3).unwrap().is_some());
    assert!(hosts.record_creation_outcome(&input, pool, true).is_err());
    let mut failed = HostSet::default();
    failed.record_creation_outcome(&input, pool, false).unwrap();
    assert!(failed.match_candidate(&input, 3).unwrap().is_none());
    assert!(failed
        .seed(pool, INITIAL_BLOCK, input.block().number)
        .is_err());
    let mut old = HostSet::default();
    old.seed(pool, input.block().number - 1, input.block().number - 1)
        .unwrap();
    assert!(old.match_candidate(&input, 3).is_err());
}

#[test]
fn typed_call_answers_keep_exact_signed_words_and_refuse_malformed_provenance() {
    let mut b = empty(INITIAL_BLOCK + 5, 1, 9);
    let zero = Some(pb::SlotProvenance {
        source: pb::SlotSource::Zero as i32,
        ..Default::default()
    });
    let current = Some(pb::SlotProvenance {
        source: pb::SlotSource::InBlock as i32,
        last_change_block: b.number,
        last_change_ordinal: 99,
    });
    let carried = Some(pb::SlotProvenance {
        source: pb::SlotSource::Carried as i32,
        last_change_block: b.number - 1,
        last_change_ordinal: 77,
    });
    let calls = b.calls.as_mut().unwrap();
    calls.ticks.push(pb::TickAnswer {
        pool: vec![5; 20],
        tick: -1,
        staked_liquidity_net: vec![255; 16],
        fee_growth_outside0_x128: value_word(8),
        p_staked: current,
        p_fee0: carried,
        reasons: 3,
    });
    calls.positions.push(pb::PositionAnswer {
        token_id: vec![1],
        result: Some(pb::position_answer::Result::Value(pb::PositionValue {
            token0: vec![2; 20],
            token1: vec![3; 20],
            tick_spacing: 1,
            tick_lower: -1,
            tick_upper: 1,
            fee_growth_inside0_last_x128: vec![0; 32],
            fee_growth_inside1_last_x128: value_word(6),
            pool_id: 2,
            p_key: current,
            p_fee0: zero,
            p_fee1: carried,
        })),
    });
    calls.get_pool.push(pb::GetPoolAnswer {
        token_a: vec![2; 20],
        token_b: vec![3; 20],
        tick_spacing: 1,
        pool: vec![5; 20],
        created_block: INITIAL_BLOCK,
    });
    let book = CallBook::from_block(&b).unwrap();
    assert_eq!(
        book.tick(&[5; 20], -1).unwrap().staked_liquidity_net,
        vec![255; 16]
    );
    assert_eq!(book.pool(&[2; 20], &[3; 20], 1).unwrap().pool, vec![5; 20]);
    assert!(book.pool(&[3; 20], &[2; 20], 1).is_err());
    for kind in 0..8 {
        let mut changed = b.clone();
        let calls = changed.calls.as_mut().unwrap();
        match kind {
            0 => calls.ticks[0]
                .staked_liquidity_net
                .pop()
                .map(|_| ())
                .unwrap(),
            1 => calls.ticks[0].p_staked.as_mut().unwrap().last_change_block -= 1,
            2 => calls.ticks[0].p_fee0.as_mut().unwrap().last_change_block += 1,
            3 => calls.ticks[0].reasons = 4,
            4 => calls.ticks.push(calls.ticks[0].clone()),
            5 => calls.positions[0].result = None,
            6 => calls.get_pool[0].created_block = b.number + 1,
            _ => calls.get_pool[0].pool = vec![0; 20],
        }
        assert!(
            CallBook::from_block(&changed).is_err(),
            "typed mutation {kind}"
        );
    }
}

#[test]
fn dynamic_invalid_utf8_and_nuls_follow_graph_node_string_decoding() {
    let mut a = erc20();
    let mut encoded = DynSolValue::String("abc".into()).abi_encode();
    encoded[64] = 255;
    a.symbol = Some(raw(encoded));
    assert_eq!(token_metadata(&a).unwrap().symbol, "�bc");
    a.name = Some(raw(DynSolValue::String("N\0a\0me\0".into()).abi_encode()));
    let name = token_metadata(&a).unwrap().name;
    assert_eq!(name, "N\0a\0me\0");
    assert_eq!(graph_store_string(&name), "Name");
    a.decimals = Some(raw(vec![255; 32]));
    assert_eq!(token_metadata(&a).unwrap().decimals, 0);
}

#[test]
fn descriptor_builder_requires_real_shaped_pins_and_uses_conservative_retention() {
    use aerodrome_slipstream_reducer::identity::build_descriptor;
    let (_, e) = descriptor();
    let bytes = build_descriptor(&e, &"ab".repeat(20), true).unwrap();
    let binding = InputBinding::new(&bytes, Sha256::digest(&bytes).into(), &e).unwrap();
    assert_eq!(
        binding
            .compatibility()
            .capabilities()
            .unwrap()
            .entity_retention
            .types
            .len(),
        0
    );
    assert!(build_descriptor(&e, "unpublished", true).is_err());
    let mut wrong = e;
    wrong.module = "map_candidates".into();
    assert!(build_descriptor(&wrong, &"ab".repeat(20), true).is_err());
}

#[test]
fn validator_cli_reports_complete_input_and_never_success_after_truncation() {
    use std::{fs, process::Command};
    let dir = tempfile::tempdir().unwrap();
    let (v, identity) = descriptor();
    let descriptor = serde_json::to_vec(&v).unwrap();
    let digest = hex::encode(Sha256::digest(&descriptor));
    fs::write(dir.path().join("descriptor.json"), descriptor).unwrap();
    fs::write(
        dir.path().join("identity.json"),
        serde_json::to_vec(&identity).unwrap(),
    )
    .unwrap();
    let mut frames = Vec::new();
    for b in [empty(INITIAL_BLOCK, 1, 9), empty(INITIAL_BLOCK + 1, 2, 1)] {
        write_frame(&mut frames, &frame(&b)).unwrap();
    }
    fs::write(dir.path().join("input.bcf1"), &frames).unwrap();
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_aerodrome-reducer"))
            .current_dir(dir.path())
            .args([
                "validate-input",
                "--input",
                "input.bcf1",
                "--descriptor",
                "descriptor.json",
                "--descriptor-sha256",
                &digest,
                "--extractor-identity",
                "identity.json",
                "--from",
                &INITIAL_BLOCK.to_string(),
                "--to",
                &(INITIAL_BLOCK + 1).to_string(),
                "--expected-parent-hash",
                &"09".repeat(32),
            ])
            .output()
            .unwrap()
    };
    let result = run();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let report: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(report["blocks"], 2);
    assert_eq!(report["handlers_executed"], 0);
    assert_eq!(report["production_qualified"], false);
    fs::write(dir.path().join("input.bcf1"), &frames[..frames.len() - 1]).unwrap();
    let result = run();
    assert_eq!(result.status.code(), Some(4));
    assert!(result.stdout.is_empty());
}

#[test]
fn raw_decoding_matches_independent_graph_node_corpus() {
    let fixture: Value = serde_json::from_slice(
        &std::fs::read(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("fixtures/graph-node-input-abi.json"),
        )
        .expect("regenerate the real Graph Node ABI corpus"),
    )
    .unwrap();
    assert_eq!(
        fixture["graph_node_commit"],
        graph_numerics::GRAPH_NODE_COMMIT
    );
    assert_eq!(fixture["alloy_dyn_abi"], "1.7.2");
    assert_eq!(fixture["events"].as_array().unwrap().len(), 54);
    assert_eq!(fixture["functions"].as_array().unwrap().len(), 78);
    for row in fixture["events"].as_array().unwrap() {
        let c = pb::CandidateLog {
            source: row["source"].as_i64().unwrap() as i32,
            topics: row["topics"]
                .as_array()
                .unwrap()
                .iter()
                .map(bytes)
                .collect(),
            data: bytes(&row["data"]),
            ..Default::default()
        };
        let result = Abis::locked().decode(&c).unwrap().map(|e| {
            e.params
                .into_iter()
                .map(|(name, value)| json!({"name":name,"value":format!("{value:?}")}))
                .collect::<Vec<_>>()
        });
        assert_eq!(
            json!(result),
            row["result"],
            "event {} mutation {}",
            row["event"],
            row["mutation"]
        );
    }
    for row in fixture["functions"].as_array().unwrap() {
        let result = Abis::locked()
            .erc20_output(
                row["function"].as_str().unwrap(),
                row["bytes32"].as_bool().unwrap(),
                &bytes(&row["raw"]),
            )
            .map(|value| vec![format!("{value:?}")]);
        assert_eq!(
            json!(result),
            row["result"],
            "function {} raw {}",
            row["function"],
            row["raw"]
        );
    }
}
