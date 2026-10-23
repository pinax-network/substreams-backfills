//! Independent original-WASM oracle for seeded pool events. Every synthetic
//! mutation is retained with raw log bytes and checkpoint rows; no reducer imports.
use graph::prelude::{alloy, o, prost::Message as GraphMessage, slog, Logger};
use graph_chain_ethereum::codec;
use graph_mapping_host::{
    bundle::sha256_hex,
    checkpoint::CheckpointBoundary,
    runner::{SegmentHost, SegmentHostConfig},
    store_state::{StoreEntityId, StoreValue},
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
const FACTORY: &str = "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a";
const USDC: &str = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const USDBC: &str = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca";
const WETH: &str = "0x4200000000000000000000000000000000000006";
const OTHER: &str = "0x1111111111111111111111111111111111111111";
const ETH_USD_POOL: &str = "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59";
fn signed(n: i64) -> Vec<u8> {
    if n == 0 {
        return vec![];
    }
    let b = n.to_be_bytes();
    let mut i = 0;
    while i < 7 && ((b[i] == 0 && b[i + 1] < 128) || (b[i] == 255 && b[i + 1] >= 128)) {
        i += 1;
    }
    b[i..].to_vec()
}
fn integer(n: i64) -> StoreValue {
    StoreValue::BigInt {
        signed_be: signed(n),
    }
}
fn decimal(n: i64) -> StoreValue {
    StoreValue::BigDecimal {
        coefficient_signed_be: signed(n),
        scale: 0,
    }
}
fn set(row: &mut graph_mapping_host::checkpoint::CheckpointRow, key: &str, value: StoreValue) {
    if let Some((_, v)) = row.fields.iter_mut().find(|(f, _)| f == key) {
        *v = value;
    } else {
        row.fields.push((key.into(), value));
        row.fields.sort_by(|a, b| a.0.cmp(&b.0));
    }
}
#[test]
fn aerodrome_swap_corpus() {
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
    let initial = host
        .process_block((&original).try_into().unwrap())
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
    let tick_indexes = [
        -202, -201, -62, -61, -12, -11, -2, -1, 0, 1, 2, 11, 12, 61, 62, 100, 101, 201, 202,
    ];
    for (name, old_tick, new_tick, fee) in [
        ("invalid_fee_tier", 0, 2, 777),
        ("upward_duplicate_endpoint", 0, 2, 100),
        ("downward_duplicate_endpoint", 2, -2, 100),
        ("negative_remainder_walk", -3, -12, 500),
        ("spacing10_new_tick_remainder", 3, 12, 500),
        ("spacing60_new_tick_remainder", 3, 62, 3000),
        ("spacing200_new_tick_remainder", 3, 202, 10000),
        ("walk100_inclusive", 0, 100, 100),
        ("walk101_skips_loop", 0, 101, 100),
        ("negative_amounts", 0, 1, 100),
        ("version0_get_pool_copy_lost", 0, 1, 100),
        ("tracked_one", 0, 1, 100),
        ("tracked_both", 0, 1, 100),
        ("tracked_neither", 0, 1, 100),
        ("tracked_token1_only", 0, 1, 100),
        ("timestamp_overflow", 0, 1, 100),
        ("fee_growth_high_bit", 0, 1, 100),
        ("absent_pool_tick", 0, 1, 100),
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
        if name == "timestamp_overflow" {
            header.timestamp.as_mut().unwrap().seconds = 1 << 32;
        }
        let mut kept = None;
        for tx in &mut block.transaction_traces {
            if let Some(receipt) = &mut tx.receipt {
                for log in &mut receipt.logs {
                    if log.block_index != 176 {
                        log.address = vec![0; 20];
                        continue;
                    }
                    log.topics = vec![
                        alloy::primitives::keccak256(
                            b"Swap(address,address,int256,int256,uint160,uint128,int24)",
                        )
                        .to_vec(),
                        word(123),
                        word(456),
                    ];
                    let (amount0, amount1) = if name == "negative_amounts" {
                        (-3000000, -2000000)
                    } else {
                        (3000000, -2000000)
                    };
                    let mut q96 = vec![0; 32];
                    q96[19] = 1;
                    log.data = [
                        word(amount0),
                        word(amount1),
                        q96,
                        word(1000000),
                        word(new_tick),
                    ]
                    .concat();
                    kept = Some(log.clone());
                }
            }
        }
        let pool_id = format!("0x{}", hex::encode(&kept.as_ref().unwrap().address));
        let original_pool = seed
            .rows
            .iter()
            .find(|r| r.entity_type == "Pool")
            .unwrap()
            .clone();
        let original_tick = seed
            .rows
            .iter()
            .find(|r| r.entity_type == "Tick")
            .unwrap()
            .clone();
        let original_token = seed
            .rows
            .iter()
            .find(|r| r.entity_type == "Token")
            .unwrap()
            .clone();
        seed.rows.retain(|r| r.entity_type != "Tick");
        for tick in tick_indexes {
            let mut row = original_tick.clone();
            let id = format!("{pool_id}#{tick}");
            row.id = StoreEntityId::String(id.clone());
            set(&mut row, "id", StoreValue::String(id));
            set(&mut row, "tickIdx", integer(tick));
            seed.rows.push(row);
        }
        for row in &mut seed.rows {
            if row.entity_type == "Pool" {
                set(row, "tick", integer(old_tick));
                set(row, "feeTier", integer(fee));
                if name == "absent_pool_tick" {
                    row.fields.retain(|(f, _)| f != "tick");
                }
                if matches!(name, "tracked_both" | "tracked_token1_only") {
                    set(row, "token1", StoreValue::String(WETH.into()));
                }
                if matches!(name, "tracked_neither" | "tracked_token1_only") {
                    set(row, "token0", StoreValue::String(OTHER.into()));
                }
            }
            if row.entity_type == "Token" {
                if name != "version0_get_pool_copy_lost" {
                    set(row, "version", StoreValue::Int(2));
                }
                set(row, "derivedETH", decimal(2));
                if matches!(name, "tracked_both" | "tracked_token1_only")
                    && row.id == StoreEntityId::String(USDBC.into())
                {
                    row.id = StoreEntityId::String(WETH.into());
                    set(row, "id", StoreValue::String(WETH.into()));
                }
                if matches!(name, "tracked_neither" | "tracked_token1_only")
                    && row.id == StoreEntityId::String(USDC.into())
                {
                    row.id = StoreEntityId::String(OTHER.into());
                    set(row, "id", StoreValue::String(OTHER.into()));
                }
            }
            if row.entity_type == "Bundle" {
                set(row, "ethPriceUSD", decimal(17));
            }
        }
        // Explicit seeded ETH/USD pool makes the price refresh nonzero; this is
        // synthetic state, never claimed as a real historical pricing window.
        let mut price_pool = original_pool;
        price_pool.id = StoreEntityId::String(ETH_USD_POOL.into());
        set(
            &mut price_pool,
            "id",
            StoreValue::String(ETH_USD_POOL.into()),
        );
        set(&mut price_pool, "token0", StoreValue::String(WETH.into()));
        set(&mut price_pool, "token1", StoreValue::String(USDC.into()));
        set(&mut price_pool, "token1Price", decimal(17));
        set(&mut price_pool, "totalValueLockedToken0", decimal(1));
        seed.rows.push(price_pool);
        if !seed
            .rows
            .iter()
            .any(|r| r.entity_type == "Token" && r.id == StoreEntityId::String(WETH.into()))
        {
            let mut row = original_token.clone();
            row.id = StoreEntityId::String(WETH.into());
            set(&mut row, "id", StoreValue::String(WETH.into()));
            set(&mut row, "derivedETH", decimal(1));
            set(&mut row, "version", StoreValue::Int(2));
            set(&mut row, "whitelistPools", StoreValue::List(vec![]));
            seed.rows.push(row);
        }
        if !seed
            .rows
            .iter()
            .any(|r| r.entity_type == "Token" && r.id == StoreEntityId::String(USDC.into()))
        {
            let mut row = original_token;
            row.id = StoreEntityId::String(USDC.into());
            set(&mut row, "id", StoreValue::String(USDC.into()));
            set(&mut row, "derivedETH", decimal(2));
            set(&mut row, "version", StoreValue::Int(2));
            set(&mut row, "whitelistPools", StoreValue::List(vec![]));
            seed.rows.push(row);
        }
        seed.cached_absent.clear();
        let mut calls = cassette.clone();
        let mut extras = vec![];
        let make_call = |address: &str,
                         contract: &str,
                         function: &str,
                         args: Vec<u8>,
                         retval: Vec<u8>| {
            let mut calldata = alloy::primitives::keccak256(function.as_bytes())[..4].to_vec();
            calldata.extend(args);
            json!({"block_number":block.number,"block_hash":format!("0x{}",hex::encode(&block.hash)),"address":address,"contract":contract,"function":function,"calldata":format!("0x{}",hex::encode(calldata)),"retval":{"kind":"value","data":format!("0x{}",hex::encode(retval))}})
        };
        extras.push(make_call(
            &pool_id,
            "Pool",
            "feeGrowthGlobal0X128()",
            vec![],
            if name == "fee_growth_high_bit" {
                let mut v = vec![0; 32];
                v[0] = 128;
                v
            } else {
                word(101)
            },
        ));
        extras.push(make_call(
            &pool_id,
            "Pool",
            "feeGrowthGlobal1X128()",
            vec![],
            word(103),
        ));
        for tick in tick_indexes {
            // Full Slipstream tuple; deployed ABI's first eight words intentionally
            // bind stakedLiquidityNet to feeGrowthOutside0 and feeGrowthOutside0
            // to feeGrowthOutside1. Distinct signed values expose that mapping.
            let data = [
                word(100),
                word(1),
                word(-7),
                word(1000 + tick),
                word(2000 + tick),
                word(0),
                word(0),
                word(1),
                word(1),
                word(0),
            ]
            .concat();
            extras.push(make_call(
                &pool_id,
                "Pool",
                "ticks(int24)",
                word(tick),
                data,
            ));
        }
        if name == "version0_get_pool_copy_lost" {
            let address_word = |a: &str| {
                let mut w = vec![0; 12];
                w.extend(hex::decode(a.trim_start_matches("0x")).unwrap());
                w
            };
            for fee in [100, 500, 3000, 10000] {
                let args = [address_word(USDC), address_word(USDBC), word(fee)].concat();
                extras.push(make_call(
                    FACTORY,
                    "Factory",
                    "getPool(address,address,int24)",
                    args,
                    address_word(&pool_id),
                ));
            }
        }
        calls["entries"]
            .as_array_mut()
            .unwrap()
            .extend(extras.clone());
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
        assert_eq!(outcome.report.handler_groups.len(), 1, "{name}");
        let expected_abort = matches!(
            name,
            "invalid_fee_tier" | "absent_pool_tick" | "timestamp_overflow"
        );
        assert_eq!(
            !outcome.report.deterministic_errors.is_empty(),
            expected_abort,
            "{name}"
        );
        assert!(outcome.report.poi.is_some(), "{name}");
        if name == "invalid_fee_tier" {
            assert!(outcome.report.deterministic_errors[0].contains(
                "Mapping aborted at src/utils/tick.ts, line 57, column 3, with no message"
            ));
        }
        let tick_saves = changes
            .operations
            .iter()
            .filter_map(|op| {
                use backfill_common::pb::pinax::graph::backfill::v1::{
                    entity_id, entity_operation::Operation,
                };
                let Operation::Set(set) = op.operation.as_ref()? else {
                    return None;
                };
                let key = set.key.as_ref()?;
                if key.entity_type != "Tick" {
                    return None;
                }
                let entity_id::Value::String(id) = key.id.as_ref()?.value.as_ref()? else {
                    return None;
                };
                Some(id.rsplit_once('#').unwrap().1.parse::<i64>().unwrap())
            })
            .collect::<Vec<_>>();
        let expected_walk: &[i64] = match name {
            "invalid_fee_tier" | "absent_pool_tick" | "timestamp_overflow" => &[],
            "upward_duplicate_endpoint" => &[2, 1, 2],
            "downward_duplicate_endpoint" => &[-2, 2, 1, 0, -1, -2],
            "negative_remainder_walk" => &[-1, -11],
            "spacing10_new_tick_remainder" => &[11],
            "spacing60_new_tick_remainder" => &[61],
            "spacing200_new_tick_remainder" => &[201],
            "walk100_inclusive" => &[100, 1, 2, 11, 12, 61, 62, 100],
            "walk101_skips_loop" => &[101],
            _ => &[1, 1],
        };
        assert_eq!(tick_saves, expected_walk, "{name}");
        let modifications = &outcome.report.handler_groups[0].handlers[0].modifications;
        if let Some(expected) = match name {
            "tracked_one" => Some("102"),
            "tracked_token1_only" => Some("68"),
            "tracked_both" => Some("85"),
            "tracked_neither" => Some("0"),
            _ => None,
        } {
            let swap = modifications.iter().find(|m| m.entity == "Swap").unwrap();
            assert_eq!(swap.data.as_ref().unwrap()["amountUSD"]["data"], expected);
        }
        if name == "version0_get_pool_copy_lost" {
            let token = modifications
                .iter()
                .find(|m| m.entity == "Token" && m.id == USDBC)
                .unwrap();
            let data = token.data.as_ref().unwrap();
            assert_eq!(data["version"]["data"], 2);
            // All four nonzero getPool returns equal this already present pool;
            // pushes to getter copies do not append anything to the entity.
            assert_eq!(
                data["whitelistPools"]["data"],
                json!([{"type":"String","data":pool_id}])
            );
        }
        if name == "timestamp_overflow" {
            use backfill_common::pb::pinax::graph::backfill::v1::entity_operation::Operation;
            let saves = changes
                .operations
                .iter()
                .filter_map(|op| match op.operation.as_ref()? {
                    Operation::Set(set) => Some(set.key.as_ref().unwrap().entity_type.as_str()),
                    _ => None,
                })
                .collect::<Vec<_>>();
            assert_eq!(saves, ["Pool", "Bundle", "Transaction"]);
        }
        if name == "fee_growth_high_bit" {
            let pool = modifications
                .iter()
                .find(|m| m.entity == "Pool" && m.id == pool_id)
                .unwrap();
            assert_eq!(
                pool.data.as_ref().unwrap()["feeGrowthGlobal0X128"]["data"],
                "57896044618658097711785492504343953926634992332820282019728792003956564819968"
            );
        }
        let log = kept.unwrap();
        cases.push(json!({"name":name,"timestamp":block.header.as_ref().unwrap().timestamp.as_ref().unwrap().seconds,
            "log":{"address":hex::encode(log.address),"topics":log.topics.iter().map(hex::encode).collect::<Vec<_>>(),"data":hex::encode(log.data)},
            "seed_rows":seed_rows,"changes_hex":hex::encode(changes.encode_to_vec()),"report":outcome.report.handler_groups,"poi":outcome.report.poi,"raw_calls":extras,"tick_save_order":tick_saves}));
    }
    let value = json!({"schema":"aerodrome-swap-handlers-oracle/v1","graph_node_commit":"77823b5a7adc4eac4abf03202c8dd7cb00dea31d","raw_block_sha256":sha256_hex(&raw),"cassette_sha256":sha256_hex(&cassette_bytes),"seed_poi":initial.report.poi,"cases":cases});
    let path =
        root().join("crates/aerodrome-slipstream-reducer/fixtures/graph-node-swap-handlers.json");
    let mut bytes = serde_json::to_vec_pretty(&value).unwrap();
    bytes.push(b'\n');
    if std::env::var_os("UPDATE_AERODROME_SWAP_CORPUS").is_some() {
        std::fs::write(path, &bytes).unwrap();
    } else {
        assert_eq!(
            std::fs::read(path).unwrap(),
            bytes,
            "regenerate with UPDATE_AERODROME_SWAP_CORPUS=1"
        );
    }
}
