//! Real full Firehose block, independently recorded call returns. This proves
//! the first-pool storage subset only, not seeded dense-block/full G2 coverage.
use aerodrome_extractor_core::{
    candidates::{build_candidates, pools_created},
    carry::{self, InMemoryCarry},
    config::{Config, PARAMS},
    layout,
    storage::storage_deltas,
    word, Address,
};
use aerodrome_extractor_extract::Decoder;
use aerodrome_extractor_pb::{eth, internal as i};
use prost::Message;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::Path};

fn raw_block() -> eth::Block {
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../fixtures/blocks/base/13899663.pb");
    let bytes =
        std::fs::read(path).expect("hydrate aerodrome-slipstream-base/fixtures/blocks.lock.json");
    assert_eq!(
        hex::encode(Sha256::digest(&bytes)),
        "5ac312712fef494a8c03f62c0987bba3339c5f693187e5f272467eee06af59ce"
    );
    eth::Block::decode(bytes.as_slice()).unwrap()
}
fn saved(carry: &InMemoryCarry, key: &str) -> [u8; 32] {
    carry
        .get(key)
        .map(|v| word(&i::SlotWord::decode(v).unwrap().word).unwrap())
        .unwrap_or([0; 32])
}

#[test]
fn real_first_pool_storage_matches_recorded_position_and_tick_calls() {
    let block = raw_block();
    let cfg = Config::parse(PARAMS).unwrap();
    let pools = pools_created(&cfg, &block, &Decoder);
    assert_eq!(pools.pools.len(), 1);
    let registry: BTreeMap<Address, i::PoolRecord> = pools
        .pools
        .iter()
        .map(|p| {
            (
                p.pool.as_slice().try_into().unwrap(),
                i::PoolRecord {
                    token0: p.token0.clone(),
                    token1: p.token1.clone(),
                    tick_spacing: p.tick_spacing,
                    created_block: block.number,
                    created_log_index: p.log_index,
                },
            )
        })
        .collect();
    let deltas = storage_deltas(&cfg, &block, &registry).unwrap();
    assert!(deltas.anomalies.is_empty(), "{:?}", deltas.anomalies);
    assert!(deltas.relevant_writes > 0);
    let mut carry = InMemoryCarry::default();
    carry.apply(&carry::pool_slot_ops(&deltas, block.number).unwrap());
    for shard in 0..8 {
        carry.apply(&carry::tick_slot_ops(&deltas, block.number, shard).unwrap());
    }
    for shard in 0..16 {
        carry.apply(&carry::position_slot_ops(&deltas, block.number, shard).unwrap());
    }
    let oracle: Value = serde_json::from_str(include_str!(
        "../../../fixtures/storage-13899663-oracle.json"
    ))
    .unwrap();
    let mut checked = 0;
    for call in oracle["entries"].as_array().unwrap() {
        assert_eq!(call["block_number"], block.number);
        assert_eq!(
            call["block_hash"],
            format!("0x{}", hex::encode(&block.hash))
        );
        let calldata =
            hex::decode(call["calldata"].as_str().unwrap().trim_start_matches("0x")).unwrap();
        let output = hex::decode(
            call["retval"]["data"]
                .as_str()
                .unwrap()
                .trim_start_matches("0x"),
        )
        .unwrap();
        let address = call["address"].as_str().unwrap().trim_start_matches("0x");
        let words: Vec<&[u8]> = output.chunks_exact(32).collect();
        match call["function"].as_str().unwrap() {
            "positions(uint256)" => {
                let token_id = carry::decimal(&word(&calldata[4..]).unwrap());
                let fragment =
                    i::PositionKeyFragment::decode(carry.get(&format!("f:{token_id};")).unwrap())
                        .unwrap();
                assert_eq!(fragment.pool_id, 1);
                assert_eq!(words[5], layout::int_word(fragment.tick_lower));
                assert_eq!(words[6], layout::int_word(fragment.tick_upper));
                let w0 = saved(&carry, &format!("k:{}:0;", fragment.pool_id));
                let w1 = saved(&carry, &format!("k:{}:1;", fragment.pool_id));
                let (token0, token1, spacing) = layout::decode_pool_key(&w0, &w1);
                assert_eq!(&words[2][12..], token0);
                assert_eq!(&words[3][12..], token1);
                assert_eq!(words[4], layout::int_word(spacing));
                assert_eq!(words[8], saved(&carry, &format!("w:{token_id}:2;")));
                assert_eq!(words[9], saved(&carry, &format!("w:{token_id}:3;")));
            }
            "ticks(int24)" => {
                let tick = layout::signed24(&calldata[33..36]);
                assert!(carry.get(&format!("m:{address}:{tick};")).is_some());
                let staked = saved(&carry, &format!("w:{address}:{tick}:1;"));
                assert_eq!(&words[2][16..], &staked[16..]);
                assert_eq!(words[3], saved(&carry, &format!("w:{address}:{tick}:2;")));
            }
            "getPool(address,address,int24)" => assert_eq!(&words[0][12..], pools.pools[0].pool),
            other => panic!("unexpected projected call {other}"),
        }
        checked += 1;
    }
    assert_eq!(checked, 4);
    let candidates = build_candidates(&cfg, &block, &registry, &Decoder).unwrap();
    let ticks = carry::last_tick_ops(&candidates).unwrap();
    assert_eq!(ticks.len(), 1);
    assert_eq!(ticks[0].1, 0);
}

#[test]
fn assembled_first_pool_answers_match_independent_oracle_returns() {
    use aerodrome_extractor_core::answers::{self, Store, StoreRead};
    use aerodrome_extractor_pb::v1 as p;
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
    let raw = raw_block();
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
    for shard in 0..8 {
        stores
            .0
            .entry(Store::Tick(shard))
            .or_default()
            .apply(&carry::tick_slot_ops(&deltas, raw.number, shard).unwrap());
    }
    for shard in 0..16 {
        stores
            .0
            .entry(Store::Position(shard))
            .or_default()
            .apply(&carry::position_slot_ops(&deltas, raw.number, shard).unwrap());
    }
    let ticks = answers::tick_answers(&candidates, &stores).unwrap();
    let positions = answers::position_answers(&candidates, &stores).unwrap();
    let output = answers::assemble(
        candidates,
        deltas,
        ticks,
        positions,
        i::TokenMetadataAnswers::default(),
        &stores,
    )
    .unwrap();
    assert!(output.audit.as_ref().unwrap().anomalies.is_empty());
    let calls = output.calls.unwrap();
    assert_eq!(calls.ticks.len(), 2);
    assert_eq!(calls.positions.len(), 1);
    assert_eq!(calls.get_pool.len(), 1);
    let oracle: Value = serde_json::from_str(include_str!(
        "../../../fixtures/storage-13899663-oracle.json"
    ))
    .unwrap();
    for call in oracle["entries"].as_array().unwrap() {
        let data = hex::decode(
            call["retval"]["data"]
                .as_str()
                .unwrap()
                .trim_start_matches("0x"),
        )
        .unwrap();
        let words: Vec<_> = data.chunks_exact(32).collect();
        match call["function"].as_str().unwrap() {
            "positions(uint256)" => {
                let Some(p::position_answer::Result::Value(position)) = &calls.positions[0].result
                else {
                    panic!("position reverted")
                };
                assert_eq!(&words[2][12..], position.token0);
                assert_eq!(&words[3][12..], position.token1);
                assert_eq!(words[4], layout::int_word(position.tick_spacing));
                assert_eq!(words[5], layout::int_word(position.tick_lower));
                assert_eq!(words[6], layout::int_word(position.tick_upper));
                assert_eq!(words[8], position.fee_growth_inside0_last_x128);
                assert_eq!(words[9], position.fee_growth_inside1_last_x128);
            }
            "ticks(int24)" => {
                let calldata =
                    hex::decode(call["calldata"].as_str().unwrap().trim_start_matches("0x"))
                        .unwrap();
                let tick = layout::signed24(&calldata[33..36]);
                let answer = calls.ticks.iter().find(|t| t.tick == tick).unwrap();
                assert_eq!(&words[2][16..], answer.staked_liquidity_net);
                assert_eq!(words[3], answer.fee_growth_outside0_x128);
            }
            "getPool(address,address,int24)" => assert_eq!(&words[0][12..], calls.get_pool[0].pool),
            other => panic!("unexpected call {other}"),
        }
    }
}
