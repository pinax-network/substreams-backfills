//! Independent NPM/Flash checkpoint oracle, executing the original deployed
//! WASM under actual Graph Node. All cases here mutate a locked real raw block
//! and are synthetic semantic probes, not additional historical evidence.
use graph::prelude::alloy::primitives::keccak256;
use graph::prelude::prost::Message as GraphMessage;
use graph::prelude::{o, slog, Logger};
use graph_chain_ethereum::codec;
use graph_mapping_host::{
    bundle::sha256_hex,
    runner::{SegmentHost, SegmentHostConfig},
};
use prost::Message;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
const SEGMENT: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}
fn copy_dir(source: &Path, target: &Path) {
    std::fs::create_dir_all(target).unwrap();
    for e in std::fs::read_dir(source).unwrap() {
        let e = e.unwrap();
        if e.file_type().unwrap().is_dir() {
            copy_dir(&e.path(), &target.join(e.file_name()));
        } else {
            std::fs::copy(e.path(), target.join(e.file_name())).unwrap();
        }
    }
}
fn word(n: u64) -> Vec<u8> {
    let mut b = vec![0; 32];
    b[24..].copy_from_slice(&n.to_be_bytes());
    b
}
fn signature(s: &str) -> Vec<u8> {
    keccak256(s).to_vec()
}
#[test]
fn aerodrome_npm_corpus() {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(generate());
}
async fn generate() {
    let raw =
        std::fs::read(root().join("aerodrome-slipstream-base/fixtures/blocks/base/13899663.pb"))
            .unwrap();
    assert_eq!(
        sha256_hex(&raw),
        "5ac312712fef494a8c03f62c0987bba3339c5f693187e5f272467eee06af59ce"
    );
    let cassette_bytes =
        std::fs::read(root().join(format!("mapping-host/fixtures/cassettes/{SEGMENT}.json")))
            .unwrap();
    let cassette: Value = serde_json::from_slice(&cassette_bytes).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let bundle = temp.path().join(SEGMENT);
    copy_dir(
        &root().join(format!("mapping-host/segments/{SEGMENT}")),
        &bundle,
    );
    graph_mapping_host::descriptor::write_in_band(
        &bundle,
        &root(),
        &Logger::root(slog::Discard, o!()),
    )
    .await
    .unwrap();
    let mut cases = vec![];
    for name in [
        "baseline",
        "decrease",
        "collect",
        "negative_collect_fees",
        "transfer_burn",
        "positions_reverted",
        "get_pool_zero",
        "pool_guard",
        "new_increase",
        "block_guard",
        "flash",
        "missing_tokens",
        "existing_transfer_no_calls",
        "existing_fee_reverted",
    ] {
        let mut block = <codec::Block as GraphMessage>::decode(raw.as_slice()).unwrap();
        let mut calls = cassette.clone();
        let increase = block
            .transaction_traces
            .iter()
            .flat_map(|tx| tx.receipt.iter().flat_map(|r| &r.logs))
            .find(|l| l.block_index == 178)
            .unwrap()
            .clone();
        let pool = block
            .transaction_traces
            .iter()
            .flat_map(|tx| tx.receipt.iter().flat_map(|r| &r.logs))
            .find(|l| l.block_index == 171)
            .unwrap()
            .address
            .clone();
        for tx in &mut block.transaction_traces {
            if let Some(receipt) = &mut tx.receipt {
                for log in &mut receipt.logs {
                    if log.block_index == 176 {
                        if name == "flash" {
                            log.topics = vec![
                                signature("Flash(address,address,uint256,uint256,uint256,uint256)"),
                                word(7),
                                word(8),
                            ];
                            log.data = vec![0; 128];
                        } else {
                            log.address = vec![0; 20];
                        }
                    }
                    if log.block_index == 178 {
                        if name == "decrease" {
                            log.topics[0] =
                                signature("DecreaseLiquidity(uint256,uint128,uint256,uint256)");
                        }
                        if name == "collect" || name == "negative_collect_fees" {
                            log.topics[0] = signature("Collect(uint256,address,uint256,uint256)");
                            log.data[..32].copy_from_slice(&word(9));
                            if name == "negative_collect_fees" {
                                log.data[32..].fill(0);
                            }
                        }
                    }
                    if log.block_index == 177 {
                        if name == "transfer_burn" {
                            log.topics[2] = word(0);
                        }
                        if name == "new_increase" {
                            log.address = vec![0; 20];
                        }
                        if name == "negative_collect_fees" {
                            log.topics = increase.topics.clone();
                            log.topics[0] =
                                signature("DecreaseLiquidity(uint256,uint128,uint256,uint256)");
                            log.data = increase.data.clone();
                        }
                    }
                    if name == "missing_tokens" && log.block_index == 172 {
                        log.address = vec![0; 20];
                    }
                }
            }
        }
        if name == "block_guard" {
            block.number = 14_317_993;
            block.header.as_mut().unwrap().number = block.number;
        }
        for entry in calls["entries"].as_array_mut().unwrap() {
            if entry["block_number"] != 13899663 {
                continue;
            }
            if name == "block_guard" {
                entry["block_number"] = json!(block.number);
            }
            let function = entry["function"].as_str().unwrap().to_owned();
            if name == "positions_reverted" && function == "positions(uint256)" {
                entry["retval"] = json!({"kind":"null"});
            }
            if function == "getPool(address,address,int24)"
                && matches!(name, "get_pool_zero" | "pool_guard")
            {
                let mut v = word(0);
                if name == "pool_guard" {
                    v[12..].copy_from_slice(
                        &hex::decode("8fe8d9bb8eeba3ed688069c3d6b556c9ca258248").unwrap(),
                    );
                }
                entry["retval"] = json!({"kind":"value","data":format!("0x{}",hex::encode(v))});
            }
        }
        if name == "flash" {
            for (name, value) in [
                ("feeGrowthGlobal0X128", word(123)),
                ("feeGrowthGlobal1X128", vec![255; 32]),
            ] {
                let function = format!("{name}()");
                let selector = keccak256(function.as_bytes());
                calls["entries"].as_array_mut().unwrap().push(json!({"block_number":block.number,"block_hash":format!("0x{}",hex::encode(&block.hash)),"address":format!("0x{}",hex::encode(&pool)),"calldata":format!("0x{}",hex::encode(&selector[..4])),"contract":"Pool","function":function,"retval":{"kind":"value","data":format!("0x{}",hex::encode(value))}}));
            }
        }
        if name == "existing_fee_reverted" {
            let mut reply = calls["entries"]
                .as_array()
                .unwrap()
                .iter()
                .find(|entry| {
                    entry["block_number"] == 13899663 && entry["function"] == "positions(uint256)"
                })
                .unwrap()
                .clone();
            reply["block_number"] = json!(13899664);
            reply["block_hash"] = json!(format!("0x{}", hex::encode([68; 32])));
            reply["retval"] = json!({"kind":"null"});
            calls["entries"].as_array_mut().unwrap().push(reply);
        }
        let path = temp.path().join("calls.json");
        std::fs::write(&path, serde_json::to_vec(&calls).unwrap()).unwrap();
        let mut host = SegmentHost::load_in_band(SegmentHostConfig {
            bundle_dir: &bundle,
            cassette_path: &path,
            record: false,
        })
        .await
        .unwrap();
        let mut seed_rows = vec![];
        if name.starts_with("existing_") {
            host.process_block((&block).try_into().unwrap())
                .await
                .unwrap();
            let fingerprint = host
                .cassette()
                .fingerprint(sha256_hex(&std::fs::read(&path).unwrap()))
                .unwrap();
            let seed = host
                .checkpoint(
                    &fingerprint,
                    graph_mapping_host::checkpoint::CheckpointBoundary {
                        block: block.number as i32,
                        block_hash: format!("0x{}", hex::encode(&block.hash)),
                        source: "synthetic NPM oracle".into(),
                        chunk_from: None,
                        chunk_to: None,
                        blocks_in_chunk: 1,
                        blocks_total: 1,
                        chunk_index: 0,
                        previous_checkpoint_sha256: None,
                    },
                    None,
                )
                .unwrap();
            for row in &seed.rows {
                if row.entity_type == "Poi$" {
                    continue;
                }
                let image = backfill_common::pb::pinax::graph::backfill::v1::SetEntity {
                    key: Some(row.key().to_wire()),
                    written_fields: row.wire_fields(),
                    ..Default::default()
                };
                seed_rows.push(hex::encode(image.encode_to_vec()));
            }
            block.header.as_mut().unwrap().parent_hash = block.hash.clone();
            block.number += 1;
            block.header.as_mut().unwrap().number = block.number;
            block.hash = vec![68; 32];
            block.header.as_mut().unwrap().hash = block.hash.clone();
            block
                .header
                .as_mut()
                .unwrap()
                .timestamp
                .as_mut()
                .unwrap()
                .seconds += 1;
            for tx in &mut block.transaction_traces {
                if let Some(receipt) = &mut tx.receipt {
                    for log in &mut receipt.logs {
                        let keep = if name == "existing_transfer_no_calls" {
                            177
                        } else {
                            178
                        };
                        if log.block_index != keep {
                            log.address = vec![0; 20];
                        }
                    }
                }
            }
            // Continue the actual running host. Seed rows initialize only the
            // native differential; future answers were installed up front.
        }
        let outcome = host
            .process_block((&block).try_into().unwrap())
            .await
            .unwrap();
        let mut changes = outcome.changes;
        changes.compatibility_id.clear();
        cases.push(json!({"name":name,"changes_hex":hex::encode(changes.encode_to_vec()),"report":outcome.report.handler_groups,"seed_rows":seed_rows}));
    }
    let value = json!({"schema":"aerodrome-npm-flash-oracle/v1","graph_node_commit":"77823b5a7adc4eac4abf03202c8dd7cb00dea31d","raw_block_sha256":sha256_hex(&raw),"cassette_sha256":sha256_hex(&cassette_bytes),"cases":cases});
    let mut bytes = serde_json::to_vec_pretty(&value).unwrap();
    bytes.push(b'\n');
    let path =
        root().join("crates/aerodrome-slipstream-reducer/fixtures/graph-node-npm-flash.json");
    if std::env::var_os("UPDATE_AERODROME_NPM_CORPUS").is_some() {
        std::fs::write(path, bytes).unwrap();
    } else {
        assert_eq!(std::fs::read(path).unwrap(), bytes);
    }
}
