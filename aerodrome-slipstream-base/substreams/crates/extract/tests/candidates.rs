use aerodrome_extractor_core::{
    candidates::{build_candidates, pools_created},
    carry::{registry_ops, StoreOp},
    config::{Config, PARAMS},
    Address,
};
use aerodrome_extractor_extract::Decoder;
use aerodrome_extractor_pb::{eth, internal as i, v1 as p};
use prost::Message;
use serde_json::Value;
use std::collections::BTreeMap;
fn bytes(v: &Value) -> Vec<u8> {
    hex::decode(v.as_str().unwrap_or("")).unwrap()
}
fn num(v: &Value) -> u64 {
    v.as_u64().unwrap_or(0)
}
fn fixture() -> eth::Block {
    let b: Value =
        serde_json::from_str(include_str!("../../../fixtures/candidates-13899663.json")).unwrap();
    let big = |v: &Value| {
        (!v.is_null()).then(|| eth::BigInt {
            bytes: bytes(&v["bytes"]),
        })
    };
    eth::Block {
        number: num(&b["number"]),
        hash: bytes(&b["hash"]),
        ver: num(&b["ver"]) as i32,
        header: Some(eth::BlockHeader {
            parent_hash: bytes(&b["header"]["parent_hash"]),
            timestamp: Some(prost_types::Timestamp {
                seconds: num(&b["header"]["timestamp"]["seconds"]) as i64,
                nanos: 0,
            }),
            base_fee_per_gas: big(&b["header"]["base_fee_per_gas"]),
            ..Default::default()
        }),
        transaction_traces: b["transactions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|tx| eth::TransactionTrace {
                index: num(&tx["index"]) as u32,
                hash: bytes(&tx["hash"]),
                from: bytes(&tx["from"]),
                to: bytes(&tx["to"]),
                r#type: num(&tx["type"]) as i32,
                gas_limit: num(&tx["gas_limit"]),
                gas_price: big(&tx["gas_price"]),
                max_fee_per_gas: big(&tx["max_fee_per_gas"]),
                max_priority_fee_per_gas: big(&tx["max_priority_fee_per_gas"]),
                status: num(&tx["status"]) as i32,
                receipt: Some(eth::TransactionReceipt {
                    logs: tx["logs"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|log| eth::Log {
                            address: bytes(&log["address"]),
                            data: bytes(&log["data"]),
                            topics: log["topics"]
                                .as_array()
                                .unwrap()
                                .iter()
                                .map(bytes)
                                .collect(),
                            index: num(&log["index"]) as u32,
                            block_index: num(&log["blockIndex"]) as u32,
                            ordinal: num(&log["ordinal"]),
                        })
                        .collect(),
                    ..Default::default()
                }),
                calls: tx["calls"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|call| eth::Call {
                        call_type: num(&call["call_type"]) as i32,
                        state_reverted: call["state_reverted"].as_bool().unwrap_or(false),
                        code_changes: call["code_changes"]
                            .as_array()
                            .map(|cs| {
                                cs.iter()
                                    .map(|c| eth::CodeChange {
                                        address: bytes(&c["address"]),
                                        new_code: bytes(&c["new_code"]),
                                        ordinal: num(&c["ordinal"]),
                                        ..Default::default()
                                    })
                                    .collect()
                            })
                            .unwrap_or_default(),
                        ..Default::default()
                    })
                    .collect(),
                ..Default::default()
            })
            .collect(),
        ..Default::default()
    }
}
fn registry(b: &eth::Block) -> BTreeMap<Address, i::PoolRecord> {
    let cfg = Config::parse(PARAMS).unwrap();
    let created = pools_created(&cfg, b, &Decoder);
    registry_ops(&created, b.number)
        .unwrap()
        .iter()
        .filter_map(|op| match op {
            StoreOp::Set { key, value, .. } if key.starts_with("p:") => Some((
                hex::decode(&key[2..key.len() - 1])
                    .unwrap()
                    .try_into()
                    .unwrap(),
                i::PoolRecord::decode(value.as_slice()).unwrap(),
            )),
            _ => None,
        })
        .collect()
}
#[test]
fn actual_first_pool_wave_order_and_gas() {
    let b = fixture();
    let cfg = Config::parse(PARAMS).unwrap();
    let output = build_candidates(&cfg, &b, &registry(&b), &Decoder).unwrap();
    assert_eq!(output.receipt_log_count, 209);
    assert_eq!(
        output
            .candidates
            .iter()
            .map(|c| (c.wave, c.source_trigger_order))
            .collect::<Vec<_>>(),
        vec![(0, 172), (0, 177), (0, 178), (1, 171), (1, 176)]
    );
    assert!(output.audit.as_ref().unwrap().anomalies.is_empty());
    assert!(output.candidates.iter().all(|c| c.abi_decoded && c.tx == 0));
    assert_eq!(output.transactions[0].index, 55);
    assert_eq!(output.transactions[0].to, cfg.npm);
    assert_eq!(
        output.transactions[0].graph_gas_price,
        hex::decode("05ea909e").unwrap()
    );
    assert_eq!(output.pools_created.len(), 1);
    assert_eq!(
        output.pools_created[0].clone_implementation,
        cfg.pool_implementation
    );
    assert_eq!(output.pools_created[0].tick_spacing, 1);
    assert_eq!(
        p::ExtractorBlock::decode(output.encode_to_vec().as_slice()).unwrap(),
        output
    );
}

#[test]
fn factory_trailing_data_keeps_registry_metadata_and_precreation_pool_logs() {
    let cfg = Config::parse(PARAMS).unwrap();
    let mut b = fixture();
    for tx in &mut b.transaction_traces {
        for log in &mut tx.receipt.as_mut().unwrap().logs {
            if log.address == cfg.factory {
                log.data.extend([0; 32]);
            }
        }
    }
    let created = pools_created(&cfg, &b, &Decoder);
    assert_eq!(created.pools.len(), 1);
    assert_eq!(
        aerodrome_extractor_core::metadata::tokens(&created)
            .unwrap()
            .len(),
        2
    );
    let output = build_candidates(&cfg, &b, &registry(&b), &Decoder).unwrap();
    assert!(output.audit.as_ref().unwrap().anomalies.is_empty());
    assert_eq!(output.pools_created.len(), 1);
    let factory = output
        .candidates
        .iter()
        .find(|c| c.source == p::DataSourceKind::Factory as i32)
        .unwrap();
    assert!(!factory.abi_decoded, "Abigen flag is diagnostic only");
    assert_eq!(
        output
            .candidates
            .iter()
            .map(|c| (c.wave, c.source_trigger_order))
            .collect::<Vec<_>>(),
        vec![(0, 172), (0, 177), (0, 178), (1, 171), (1, 176)]
    );
}
#[test]
fn start_gates_and_prior_host() {
    let mut b = fixture();
    let cfg = Config::parse(PARAMS).unwrap();
    b.number = cfg.factory_start - 1;
    assert!(build_candidates(&cfg, &b, &BTreeMap::new(), &Decoder)
        .unwrap()
        .candidates
        .is_empty());
    b.number = cfg.npm_start - 1;
    let o = build_candidates(&cfg, &b, &registry(&b), &Decoder).unwrap();
    assert!(o
        .candidates
        .iter()
        .all(|c| c.source != p::DataSourceKind::PositionManager as i32));
    let mut r = registry(&b);
    b.number += 1;
    for v in r.values_mut() {
        v.created_block = b.number - 1;
    }
    assert!(build_candidates(&cfg, &b, &r, &Decoder)
        .unwrap()
        .candidates
        .iter()
        .all(|c| c.wave == 0));
}
#[test]
fn malformed_candidate_is_retained_and_clone_drift_is_anomaly() {
    let mut b = fixture();
    let r = registry(&b);
    let cfg = Config::parse(PARAMS).unwrap();
    b.transaction_traces[55].receipt.as_mut().unwrap().logs[7]
        .data
        .clear();
    for call in &mut b.transaction_traces[55].calls {
        call.code_changes.clear();
    }
    let o = build_candidates(&cfg, &b, &r, &Decoder).unwrap();
    assert_eq!(o.candidates.len(), 5);
    assert_eq!(o.audit.as_ref().unwrap().candidate_decode_failures, 1);
    assert!(o
        .audit
        .unwrap()
        .anomalies
        .iter()
        .any(|a| a.kind == p::AnomalyKind::AnomalyPoolNotPinnedClone as i32));
}
#[test]
fn failed_receipts_duplicate_log_index_and_unsupported_version_refuse() {
    let mut b = fixture();
    let r = registry(&b);
    b.ver = 6;
    b.transaction_traces[55].status = 2;
    let cfg = Config::parse(PARAMS).unwrap();
    let o = build_candidates(&cfg, &b, &r, &Decoder).unwrap();
    assert!(o.candidates.is_empty());
    for kind in [
        p::AnomalyKind::AnomalyUnsupportedBlockVersion,
        p::AnomalyKind::AnomalyFailedTxWithReceiptLogs,
        p::AnomalyKind::AnomalyLogIndexNotDense,
    ] {
        assert!(o
            .audit
            .as_ref()
            .unwrap()
            .anomalies
            .iter()
            .any(|a| a.kind == kind as i32));
    }
}
#[test]
fn receipt_order_and_block_index_win_over_call_and_tx_index() {
    let mut b = fixture();
    let r = registry(&b);
    for t in &mut b.transaction_traces {
        if let Some(receipt) = &mut t.receipt {
            receipt.logs.reverse();
            for l in &mut receipt.logs {
                l.index = 999;
            }
        }
    }
    b.transaction_traces.reverse();
    let o = build_candidates(&Config::parse(PARAMS).unwrap(), &b, &r, &Decoder).unwrap();
    assert_eq!(
        o.candidates
            .iter()
            .map(|c| (c.wave, c.log_index))
            .collect::<Vec<_>>(),
        vec![(0, 172), (0, 177), (0, 178), (1, 171), (1, 176)]
    );
    assert!(o.audit.unwrap().anomalies.is_empty());
}

#[test]
fn transaction_references_are_compact_and_creation_has_no_recipient() {
    let mut b = fixture();
    let r = registry(&b);
    // Split the same valid receipt across two transactions without changing the
    // block-wide log order. Candidates must point into the compact output table.
    let mut first = b.transaction_traces[55].clone();
    first.index = 2;
    first.hash[0] ^= 1;
    first.calls[0].call_type = 5;
    first
        .receipt
        .as_mut()
        .unwrap()
        .logs
        .retain(|l| l.block_index < 177);
    b.transaction_traces[55]
        .receipt
        .as_mut()
        .unwrap()
        .logs
        .retain(|l| l.block_index >= 177);
    b.transaction_traces.retain(|t| t.index != 2);
    b.transaction_traces.push(first);
    let o = build_candidates(&Config::parse(PARAMS).unwrap(), &b, &r, &Decoder).unwrap();
    assert_eq!(
        o.transactions.iter().map(|t| t.index).collect::<Vec<_>>(),
        vec![2, 55]
    );
    assert!(o.transactions[0].to.is_empty());
    assert_eq!(
        o.candidates.iter().map(|c| c.tx).collect::<Vec<_>>(),
        vec![0, 1, 1, 0, 0]
    );
}
