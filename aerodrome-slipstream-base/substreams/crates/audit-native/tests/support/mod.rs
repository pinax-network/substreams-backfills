use aerodrome_extractor_core::{
    answers::{self, Store, StoreRead},
    candidates::{build_candidates, pools_created},
    carry::{self, InMemoryCarry},
    config::{Config, PARAMS},
    metadata,
    storage::storage_deltas,
    Address,
};
use aerodrome_extractor_extract::Decoder;
use aerodrome_extractor_pb::{eth, internal as i, v1 as p};
use prost::Message;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::Path};

pub fn oracle() -> Value {
    serde_json::from_str(include_str!(
        "../../../../fixtures/calls-13899663-oracle.json"
    ))
    .unwrap()
}
pub fn first_pool() -> p::ExtractorBlock {
    #[derive(Default)]
    struct Stores(BTreeMap<Store, InMemoryCarry>);
    impl StoreRead for Stores {
        fn get(&self, store: Store, key: &str) -> Result<Option<Vec<u8>>, String> {
            Ok(self.0.get(&store).and_then(|s| s.get(key)).map(Vec::from))
        }
        fn first_tick(&self, _: &Address) -> Result<Option<i64>, String> {
            Ok(None)
        }
    }
    let bytes = std::fs::read(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../fixtures/blocks/base/13899663.pb"),
    )
    .expect("hydrate blocks.lock.json");
    assert_eq!(
        hex::encode(Sha256::digest(&bytes)),
        "5ac312712fef494a8c03f62c0987bba3339c5f693187e5f272467eee06af59ce"
    );
    let raw = eth::Block::decode(bytes.as_slice()).unwrap();
    let cfg = Config::parse(PARAMS).unwrap();
    let created = pools_created(&cfg, &raw, &Decoder);
    let registry: BTreeMap<Address, i::PoolRecord> = created
        .pools
        .iter()
        .map(|p| {
            (
                p.pool.as_slice().try_into().unwrap(),
                i::PoolRecord {
                    token0: p.token0.clone(),
                    token1: p.token1.clone(),
                    tick_spacing: p.tick_spacing,
                    created_block: raw.number,
                    created_log_index: p.log_index,
                },
            )
        })
        .collect();
    let deltas = storage_deltas(&cfg, &raw, &registry).unwrap();
    let candidates = build_candidates(&cfg, &raw, &registry, &Decoder).unwrap();
    let mut stores = Stores::default();
    stores
        .0
        .entry(Store::Pools)
        .or_default()
        .apply(&carry::registry_ops(&created, raw.number).unwrap());
    stores
        .0
        .entry(Store::PoolSlots)
        .or_default()
        .apply(&carry::pool_slot_ops(&deltas, raw.number).unwrap());
    for n in 0..8 {
        stores
            .0
            .entry(Store::Tick(n))
            .or_default()
            .apply(&carry::tick_slot_ops(&deltas, raw.number, n).unwrap());
    }
    for n in 0..16 {
        stores
            .0
            .entry(Store::Position(n))
            .or_default()
            .apply(&carry::position_slot_ops(&deltas, raw.number, n).unwrap());
    }
    let tokens = metadata::tokens(&created).unwrap();
    let oracle = oracle();
    let responses = metadata::calls(&tokens)
        .into_iter()
        .map(|(token, selector)| {
            let entries = oracle["entries"].as_array().unwrap();
            let entry = entries
                .iter()
                .find(|e| {
                    e["address"] == format!("0x{}", hex::encode(token))
                        && e["calldata"] == format!("0x{}", hex::encode(selector))
                })
                .unwrap();
            assert_eq!(entry["block_hash"], format!("0x{}", hex::encode(&raw.hash)));
            metadata::Response {
                failed: false,
                raw: hex::decode(
                    entry["retval"]["data"]
                        .as_str()
                        .unwrap()
                        .strip_prefix("0x")
                        .unwrap(),
                )
                .unwrap(),
            }
        })
        .collect();
    let ticks = answers::tick_answers(&candidates, &stores).unwrap();
    let positions = answers::position_answers(&candidates, &stores).unwrap();
    answers::assemble(
        candidates,
        deltas,
        ticks,
        positions,
        metadata::answers(&tokens, responses).unwrap(),
        &stores,
    )
    .unwrap()
}
