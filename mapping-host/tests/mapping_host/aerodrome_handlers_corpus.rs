//! Independent first-handler oracle. Executes the pinned deployed WASM through
//! actual Graph Node, without importing the native reducer or its helpers.
//! The first case is the untouched actual block. Further cases explicitly
//! mutate its raw receipt logs/metadata and suppress NPM/Mint matches; these
//! prove mapping behavior on synthetic inputs, not additional live history.
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
    for entry in std::fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        let target = target.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), target).unwrap();
        }
    }
}
fn word(n: u64) -> Vec<u8> {
    let mut b = vec![0; 32];
    b[24..].copy_from_slice(&n.to_be_bytes());
    b
}
fn hexword(n: u64) -> String {
    format!("0x{}", hex::encode(word(n)))
}
#[test]
fn aerodrome_handlers_corpus() {
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
    let cassette_path = root().join(format!("mapping-host/fixtures/cassettes/{SEGMENT}.json"));
    let cassette_bytes = std::fs::read(cassette_path).unwrap();
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
        "real_first_pool",
        "isolated_original",
        "spacing_50",
        "spacing_100",
        "spacing_200",
        "spacing_10",
        "excluded_pool",
        "metadata_reverted",
        "metadata_bytes32",
        "metadata_sentinel",
        "metadata_invalid",
        "tick_wrap_positive",
        "tick_wrap_negative",
        "tick_overflow",
        "timestamp_wrap",
        "timestamp_overflow",
        "cached_tokens",
        "repeated_initialize",
    ] {
        let mut block = <codec::Block as GraphMessage>::decode(raw.as_slice()).unwrap();
        let mut calls = cassette.clone();
        if name != "real_first_pool" {
            for tx in &mut block.transaction_traces {
                if let Some(receipt) = &mut tx.receipt {
                    for log in &mut receipt.logs {
                        if [176, 177, 178].contains(&log.block_index) {
                            log.address = vec![0; 20];
                        }
                        if log.block_index == 172 {
                            if let Some(n) = name.strip_prefix("spacing_") {
                                log.topics[3] = word(n.parse().unwrap());
                            }
                            if name == "excluded_pool" {
                                log.data[12..32].copy_from_slice(
                                    &hex::decode("8fe8d9bb8eeba3ed688069c3d6b556c9ca258248")
                                        .unwrap(),
                                );
                            }
                        }
                        if log.block_index == 171 {
                            let tick = match name {
                                "tick_wrap_positive" => Some(word(1 << 31)),
                                "tick_wrap_negative" => {
                                    let mut b = vec![255; 32];
                                    b[28..].copy_from_slice(&(-2147483649_i64).to_be_bytes()[4..]);
                                    Some(b)
                                }
                                "tick_overflow" => Some(word(1 << 32)),
                                _ => None,
                            };
                            if let Some(tick) = tick {
                                log.data[32..64].copy_from_slice(&tick);
                            }
                        }
                    }
                }
            }
            if name == "timestamp_wrap" {
                block
                    .header
                    .as_mut()
                    .unwrap()
                    .timestamp
                    .as_mut()
                    .unwrap()
                    .seconds = 1 << 31;
            }
            if name == "timestamp_overflow" {
                block
                    .header
                    .as_mut()
                    .unwrap()
                    .timestamp
                    .as_mut()
                    .unwrap()
                    .seconds = 1 << 32;
            }
            for entry in calls["entries"].as_array_mut().unwrap() {
                if entry["block_number"] != 13899663 {
                    continue;
                }
                let f = entry["function"].as_str().unwrap();
                if !["symbol()", "name()", "totalSupply()", "decimals()"].contains(&f) {
                    continue;
                }
                entry["retval"] = match name {
                    "metadata_reverted" => json!({"kind":"null"}),
                    "metadata_bytes32" if f == "symbol()" || f == "name()" => {
                        let mut b = vec![0; 32];
                        b[..5].copy_from_slice(b"A\0B\xffC");
                        json!({"kind":"value","data":format!("0x{}",hex::encode(b))})
                    }
                    "metadata_sentinel" if f == "symbol()" || f == "name()" => {
                        json!({"kind":"value","data":hexword(1)})
                    }
                    "metadata_invalid" if f == "decimals()" => {
                        json!({"kind":"value","data":hexword(256)})
                    }
                    "metadata_invalid" => json!({"kind":"value","data":"0xab"}),
                    _ => entry["retval"].clone(),
                };
            }
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
        if matches!(name, "cached_tokens" | "repeated_initialize") {
            host.process_block((&block).try_into().unwrap())
                .await
                .unwrap();
            let fingerprint = host
                .cassette()
                .fingerprint(sha256_hex(&std::fs::read(&path).unwrap()))
                .unwrap();
            let mut seed = host
                .checkpoint(
                    &fingerprint,
                    graph_mapping_host::checkpoint::CheckpointBoundary {
                        block: block.number as i32,
                        block_hash: format!("0x{}", hex::encode(&block.hash)),
                        source: "synthetic first-handlers oracle".into(),
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
            if name == "repeated_initialize" {
                for row in &mut seed.rows {
                    if row.entity_type == "Pool" {
                        for (field, value) in &mut row.fields {
                            if field == "token0Price" {
                                *value = graph_mapping_host::store_state::StoreValue::BigDecimal {
                                    coefficient_signed_be: vec![5],
                                    scale: 0,
                                };
                            }
                        }
                    }
                }
            }
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
            let mut restored = SegmentHost::load_in_band(SegmentHostConfig {
                bundle_dir: &bundle,
                cassette_path: &path,
                record: false,
            })
            .await
            .unwrap();
            restored.restore_checkpoint(&seed, &fingerprint).unwrap();
            host = restored;
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
                        if (name == "cached_tokens" && log.block_index == 171)
                            || (name == "repeated_initialize" && log.block_index == 172)
                        {
                            log.address = vec![0; 20];
                        }
                    }
                }
            }
        }
        let outcome = host
            .process_block((&block).try_into().unwrap())
            .await
            .unwrap();
        // Compatibility binds source closure and differs with local changes.
        // Its independent descriptor tests own that identity; this corpus
        // binds every mapping operation and accepted source field instead.
        let mut changes = outcome.changes;
        changes.compatibility_id.clear();
        cases.push(json!({"name":name,"changes_hex":hex::encode(changes.encode_to_vec()),"report":outcome.report.handler_groups,"seed_rows":seed_rows}));
    }
    let value = json!({"schema":"aerodrome-first-handlers-oracle/v1","graph_node_commit":"77823b5a7adc4eac4abf03202c8dd7cb00dea31d","raw_block_sha256":sha256_hex(&raw),"cassette_sha256":sha256_hex(&cassette_bytes),"cases":cases});
    let path =
        root().join("crates/aerodrome-slipstream-reducer/fixtures/graph-node-first-handlers.json");
    let mut expected = serde_json::to_vec_pretty(&value).unwrap();
    expected.push(b'\n');
    if std::env::var_os("UPDATE_AERODROME_HANDLER_CORPUS").is_some() {
        std::fs::write(path, &expected).unwrap();
    } else {
        assert_eq!(
            std::fs::read(path).unwrap(),
            expected,
            "regenerate using UPDATE_AERODROME_HANDLER_CORPUS=1"
        );
    }
}
