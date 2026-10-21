//! Independent original-WASM oracle for seeded pool events. Every synthetic
//! mutation is retained with raw log bytes and checkpoint rows; no reducer imports.
use graph::prelude::{alloy, o, prost::Message as GraphMessage, slog, Logger};
use graph_chain_ethereum::codec;
use graph_mapping_host::{
    bundle::sha256_hex,
    checkpoint::CheckpointBoundary,
    runner::{SegmentHost, SegmentHostConfig},
    store_state::StoreValue,
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
fn word(n: i64) -> Vec<u8> {
    let mut b = vec![if n < 0 { 255 } else { 0 }; 32];
    b[24..].copy_from_slice(&n.to_be_bytes());
    b
}
#[test]
fn aerodrome_pool_corpus() {
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
    let original = <codec::Block as GraphMessage>::decode(raw.as_slice()).unwrap();
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
    let path = temp.path().join("calls.json");
    std::fs::write(&path, &cassette_bytes).unwrap();
    let mut host = SegmentHost::load_in_band(SegmentHostConfig {
        bundle_dir: &bundle,
        cassette_path: &path,
        record: false,
    })
    .await
    .unwrap();
    host.process_block((&original).try_into().unwrap())
        .await
        .unwrap();
    let fingerprint = host
        .cassette()
        .fingerprint(sha256_hex(&cassette_bytes))
        .unwrap();
    let checkpoint = host
        .checkpoint(
            &fingerprint,
            CheckpointBoundary {
                block: original.number as i32,
                block_hash: format!("0x{}", hex::encode(&original.hash)),
                source: "synthetic pool oracle seed from actual first block".into(),
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
    let mut cases = vec![];
    for name in [
        "mint_again",
        "burn",
        "mint_outside",
        "burn_outside",
        "mint_absent_tick",
        "burn_null_tick",
        "burn_missing_tick",
        "tick_misbinding_negative",
        "interval_seed_values",
        "mint_timestamp_overflow",
        "mint_absent_tick_overflow",
    ] {
        let mut seed = checkpoint.clone();
        let mut block = original.clone();
        block.number += 1;
        block.hash = vec![68; 32];
        let header = block.header.as_mut().unwrap();
        header.parent_hash = original.hash.clone();
        header.number = block.number;
        header.hash = block.hash.clone();
        header.timestamp.as_mut().unwrap().seconds += 1;
        if name == "mint_timestamp_overflow" {
            header.timestamp.as_mut().unwrap().seconds = 1 << 32;
        }
        let burn = name.starts_with("burn");
        let mut kept = None;
        for tx in &mut block.transaction_traces {
            if let Some(receipt) = &mut tx.receipt {
                for log in &mut receipt.logs {
                    if log.block_index != 176 {
                        log.address = vec![0; 20];
                        continue;
                    }
                    if burn {
                        log.topics[0] = alloy::primitives::keccak256(
                            b"Burn(address,int24,int24,uint128,uint256,uint256)",
                        )
                        .to_vec();
                        log.data = log.data[32..].to_vec();
                    }
                    if name == "mint_absent_tick_overflow" {
                        log.topics[2] = word(1 << 32);
                    }
                    kept = Some(log.clone());
                }
            }
        }
        if name == "burn_missing_tick" {
            seed.rows.retain(|r| r.entity_type != "Tick");
        }
        for row in &mut seed.rows {
            if row.entity_type == "Pool" {
                if name == "mint_absent_tick" || name == "mint_absent_tick_overflow" {
                    row.fields.retain(|(f, _)| f != "tick");
                }
                for (field, value) in &mut row.fields {
                    if field == "tick" && name.ends_with("outside") {
                        *value = StoreValue::BigInt { signed_be: vec![2] };
                    }
                    if field == "tick" && name == "burn_null_tick" {
                        *value = StoreValue::Null;
                    }
                }
            }
            if name == "interval_seed_values" {
                for (field, value) in &mut row.fields {
                    let n = match (row.entity_type.as_str(), field.as_str()) {
                        ("Bundle", "ethPriceUSD") => Some(17),
                        ("Token", "derivedETH") => Some(2),
                        ("Pool", "token0Price") => Some(5),
                        ("Pool", "totalValueLockedUSD") => Some(13),
                        ("Factory", "totalValueLockedUSD") => Some(19),
                        ("Tick", "volumeToken0") => Some(7),
                        ("Tick", "volumeToken1") => Some(9),
                        _ => None,
                    };
                    if let Some(n) = n {
                        *value = StoreValue::BigDecimal {
                            coefficient_signed_be: vec![n],
                            scale: 0,
                        };
                    }
                }
            }
        }
        let mut calls = cassette.clone();
        let mut extras = vec![];
        for entry in calls["entries"].as_array().unwrap() {
            if entry["block_number"] != original.number {
                continue;
            }
            let mut entry = entry.clone();
            entry["block_number"] = json!(block.number);
            entry["block_hash"] = json!(format!("0x{}", hex::encode(&block.hash)));
            if name == "tick_misbinding_negative" && entry["function"] == "ticks(int24)" {
                let mut data = hex::decode(
                    entry["retval"]["data"]
                        .as_str()
                        .unwrap()
                        .trim_start_matches("0x"),
                )
                .unwrap();
                data[64..96].copy_from_slice(&word(-7));
                data[96..128].copy_from_slice(&word(11));
                entry["retval"]["data"] = json!(format!("0x{}", hex::encode(data)));
            }
            extras.push(entry);
        }
        calls["entries"].as_array_mut().unwrap().extend(extras);
        std::fs::write(&path, serde_json::to_vec(&calls).unwrap()).unwrap();
        let mut restored = SegmentHost::load_in_band(SegmentHostConfig {
            bundle_dir: &bundle,
            cassette_path: &path,
            record: false,
        })
        .await
        .unwrap();
        let fingerprint = restored
            .cassette()
            .fingerprint(sha256_hex(&std::fs::read(&path).unwrap()))
            .unwrap();
        // Synthetic construction rebinds the added independent replies and
        // recomputes row counts after explicit state mutations.
        seed = graph_mapping_host::checkpoint::HostCheckpoint::new(
            seed.header.identity,
            &fingerprint,
            seed.header.boundary,
            seed.header.poi,
            "Poi$",
            seed.data_sources,
            seed.rows,
            seed.cached_absent,
        );
        restored.restore_checkpoint(&seed, &fingerprint).unwrap();
        let seed_rows = seed
            .rows
            .iter()
            .filter(|r| r.entity_type != "Poi$")
            .map(|r| {
                let image = backfill_common::pb::pinax::graph::backfill::v1::SetEntity {
                    key: Some(r.key().to_wire()),
                    written_fields: r.wire_fields(),
                    ..Default::default()
                };
                hex::encode(image.encode_to_vec())
            })
            .collect::<Vec<_>>();
        let outcome = restored
            .process_block((&block).try_into().unwrap())
            .await
            .unwrap();
        let mut changes = outcome.changes;
        changes.compatibility_id.clear();
        let log = kept.unwrap();
        cases.push(json!({"name":name,"timestamp":block.header.as_ref().unwrap().timestamp.as_ref().unwrap().seconds,
            "log":{"address":hex::encode(log.address),"topics":log.topics.iter().map(hex::encode).collect::<Vec<_>>(),"data":hex::encode(log.data)},
            "seed_rows":seed_rows,"changes_hex":hex::encode(changes.encode_to_vec()),"report":outcome.report.handler_groups}));
    }
    let value = json!({"schema":"aerodrome-pool-handlers-oracle/v1","graph_node_commit":"77823b5a7adc4eac4abf03202c8dd7cb00dea31d","raw_block_sha256":sha256_hex(&raw),"cassette_sha256":sha256_hex(&cassette_bytes),"cases":cases});
    let path =
        root().join("crates/aerodrome-slipstream-reducer/fixtures/graph-node-pool-handlers.json");
    let mut bytes = serde_json::to_vec_pretty(&value).unwrap();
    bytes.push(b'\n');
    if std::env::var_os("UPDATE_AERODROME_POOL_CORPUS").is_some() {
        std::fs::write(path, &bytes).unwrap();
    } else {
        assert_eq!(
            std::fs::read(path).unwrap(),
            bytes,
            "regenerate with UPDATE_AERODROME_POOL_CORPUS=1"
        );
    }
}
