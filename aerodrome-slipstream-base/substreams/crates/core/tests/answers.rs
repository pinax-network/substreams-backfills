use aerodrome_extractor_core::{
    answers::{self, Store, StoreRead},
    config::Config,
    layout, metadata,
    pb::{internal as i, v1 as p},
    shard, Address,
};
use prost::Message;
use std::collections::{BTreeMap, BTreeSet};

const POOL: Address = [7; 20];
#[derive(Default)]
struct Stores {
    values: BTreeMap<(Store, String), Vec<u8>>,
    first: BTreeMap<Address, i64>,
}
impl StoreRead for Stores {
    fn get(&self, store: Store, key: &str) -> Result<Option<Vec<u8>>, String> {
        Ok(self.values.get(&(store, key.into())).cloned())
    }
    fn first_tick(&self, pool: &Address) -> Result<Option<i64>, String> {
        Ok(self.first.get(pool).copied())
    }
}
impl Stores {
    fn put(&mut self, store: Store, key: String, value: impl Message) {
        self.values.insert((store, key), value.encode_to_vec());
    }
    fn slot(&mut self, store: Store, key: String, word: Vec<u8>, block: u64) {
        self.put(
            store,
            key,
            i::SlotWord {
                word,
                block,
                ordinal: 42,
            },
        );
    }
    fn pool(&mut self, spacing: i32) {
        self.put(
            Store::Pools,
            format!("p:{};", hex::encode(POOL)),
            i::PoolRecord {
                token0: vec![1; 20],
                token1: vec![2; 20],
                tick_spacing: spacing,
                created_block: 1,
                created_log_index: 0,
            },
        );
    }
}
fn event(name: &str, value: i32) -> p::CandidateLog {
    let pool_event = ["Initialize", "Swap", "Mint", "Burn", "Flash"].contains(&name);
    let abi: alloy_json_abi::JsonAbi = serde_json::from_slice(if pool_event {
        include_bytes!("../../../../reference/abis/Pool.json").as_slice()
    } else {
        include_bytes!("../../../../reference/abis/NonfungiblePositionManager.json").as_slice()
    })
    .unwrap();
    let event = &abi.events[name][0];
    let mut topics = vec![event.selector().to_vec()];
    let mut data = vec![];
    for input in &event.inputs {
        let word = match input.name.as_str() {
            "tick" | "tickLower" => layout::int_word(value),
            "tickUpper" => layout::int_word(value + 1),
            "tokenId" => layout::uint_word(1),
            _ => [0; 32],
        };
        if input.indexed {
            topics.push(word.to_vec());
        } else {
            data.extend(word);
        }
    }
    p::CandidateLog {
        address: POOL.to_vec(),
        source: if pool_event {
            p::DataSourceKind::Pool
        } else {
            p::DataSourceKind::PositionManager
        } as i32,
        topics,
        data,
        ..Default::default()
    }
}
fn block(candidates: Vec<p::CandidateLog>) -> p::ExtractorBlock {
    p::ExtractorBlock {
        number: 100,
        candidates,
        audit: Some(p::ExtractorAudit::default()),
        ..Default::default()
    }
}

#[test]
fn mixed_tick_sources_and_combined_reasons_use_end_state_and_previous_tick() {
    let mut stores = Stores::default();
    stores.pool(1);
    stores.first.insert(POOL, 0);
    for tick in [0, 1] {
        let shard = Store::Tick(shard::tick_shard(&POOL, tick));
        stores.put(
            shard,
            format!("m:{}:{tick};", hex::encode(POOL)),
            i::TickMarker {
                block: 99,
                ordinal: 2,
            },
        );
    }
    let key = format!("w:{}:1", hex::encode(POOL));
    let shard = Store::Tick(shard::tick_shard(&POOL, 1));
    stores.slot(shard, format!("{key}:1;"), vec![255; 32], 100);
    stores.slot(shard, format!("{key}:2;"), vec![3], 99);
    let result =
        answers::tick_answers(&block(vec![event("Mint", 1), event("Swap", 1)]), &stores).unwrap();
    assert!(result.anomalies.is_empty());
    assert_eq!(result.swap_walk_probes, 2);
    let tick = result.ticks.iter().find(|t| t.tick == 1).unwrap();
    assert_eq!(tick.reasons, 3);
    assert_eq!(tick.staked_liquidity_net, vec![255; 16]);
    assert_eq!(tick.fee_growth_outside0_x128, layout::uint_word(3));
    assert_eq!(
        tick.p_staked.as_ref().unwrap().source,
        p::SlotSource::InBlock as i32
    );
    assert_eq!(
        tick.p_fee0.as_ref().unwrap().source,
        p::SlotSource::Carried as i32
    );
    let zero = result.ticks.iter().find(|t| t.tick == 2).unwrap();
    assert_eq!(
        zero.p_staked.as_ref().unwrap().source,
        p::SlotSource::Zero as i32
    );
    assert_eq!(zero.staked_liquidity_net, vec![0; 16]);
}

#[test]
fn in_block_initialization_precedes_swap_and_missing_history_is_anomalous() {
    let mut stores = Stores::default();
    stores.pool(1);
    let missing = answers::tick_answers(&block(vec![event("Swap", 1)]), &stores).unwrap();
    assert_eq!(
        missing.anomalies[0].kind,
        p::AnomalyKind::AnomalySwapWithoutPriorTick as i32
    );
    let initialized = answers::tick_answers(
        &block(vec![event("Initialize", 0), event("Swap", 1)]),
        &stores,
    )
    .unwrap();
    assert!(initialized.anomalies.is_empty());
    assert_eq!(initialized.swap_walk_probes, 2);
    // Long swaps still probe the endpoint rather than walking an unbounded interval.
    let long = answers::tick_answers(
        &block(vec![event("Initialize", 0), event("Swap", 1000)]),
        &stores,
    )
    .unwrap();
    assert_eq!(long.swap_walk_probes, 1);
}

#[test]
fn fee_growth_is_unique_per_pool_and_preserves_zero_and_carried_provenance() {
    let mut stores = Stores::default();
    stores.pool(50);
    stores.slot(
        Store::PoolSlots,
        format!("f:{}:1;", hex::encode(POOL)),
        vec![9],
        99,
    );
    let result =
        answers::fee_growth_answers(&block(vec![event("Swap", 0), event("Flash", 0)]), &stores)
            .unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].fee_growth_global0_x128, vec![0; 32]);
    assert_eq!(result[0].fee_growth_global1_x128, layout::uint_word(9));
    assert_eq!(
        result[0].p0.as_ref().unwrap().source,
        p::SlotSource::Zero as i32
    );
    assert_eq!(
        result[0].p1.as_ref().unwrap().source,
        p::SlotSource::Carried as i32
    );
}

#[test]
fn position_absence_reverts_but_missing_pool_keys_are_not_invented() {
    let mut stores = Stores::default();
    let b = block(vec![event("IncreaseLiquidity", 0), event("Transfer", 0)]);
    let absent = answers::position_answers(&b, &stores).unwrap();
    assert_eq!(absent.positions.len(), 1);
    assert!(matches!(
        absent.positions[0].result,
        Some(p::position_answer::Result::Reverted(_))
    ));
    let store = Store::Position(shard::position_shard(&layout::uint_word(1)));
    stores.put(
        store,
        "f:1;".into(),
        i::PositionKeyFragment {
            pool_id: 1,
            tick_lower: -1,
            tick_upper: 1,
            block: 100,
            ordinal: 4,
        },
    );
    let missing = answers::position_answers(&b, &stores).unwrap();
    assert!(missing.positions.is_empty());
    assert_eq!(missing.anomalies.len(), 1);
    assert_eq!(
        missing.anomalies[0].kind,
        p::AnomalyKind::AnomalyMissingPoolKey as i32
    );
    let mut w1 = [0; 32];
    w1[12..].fill(2);
    w1[11] = 1;
    stores.slot(Store::PoolSlots, "k:1:0;".into(), vec![1; 20], 99);
    stores.slot(Store::PoolSlots, "k:1:1;".into(), w1[11..].to_vec(), 99);
    let value = answers::position_answers(&b, &stores).unwrap();
    assert!(value.anomalies.is_empty());
    let Some(p::position_answer::Result::Value(position)) = &value.positions[0].result else {
        panic!("expected position")
    };
    assert_eq!(position.token0, vec![1; 20]);
    assert_eq!(position.token1, vec![2; 20]);
    assert_eq!(
        (
            position.tick_lower,
            position.tick_upper,
            position.tick_spacing
        ),
        (-1, 1, 1)
    );
    assert_eq!(position.fee_growth_inside0_last_x128, vec![0; 32]);
    assert_eq!(value.get_pool[0].pool, vec![0; 20]);
    stores.put(
        Store::Pools,
        format!("g:{}:{}:1;", hex::encode([1; 20]), hex::encode([2; 20])),
        i::PoolRef {
            pool: POOL.to_vec(),
            created_block: 100,
        },
    );
    assert_eq!(
        answers::position_answers(&b, &stores).unwrap().get_pool[0].pool,
        POOL
    );
}

#[test]
fn swap_supplies_version_upgrade_calls_once_from_end_of_block_registry() {
    use aerodrome_extractor_core::mapping_probes::USDC;
    let mut stores = Stores::default();
    stores.pool(1);
    let b = block(vec![event("Swap", 0), event("Swap", 1)]);
    let keys = answers::position_answers(&b, &stores).unwrap();
    assert!(keys.positions.is_empty());
    assert_eq!(keys.get_pool.len(), 8);
    assert!(keys.get_pool.iter().all(|answer| {
        answer.token_a == USDC && answer.pool == [0; 20] && answer.created_block == 0
    }));
    let key = format!("g:{}:{}:100;", hex::encode(USDC), hex::encode([1; 20]));
    stores.put(
        Store::Pools,
        key.clone(),
        i::PoolRef {
            pool: vec![9; 20],
            created_block: b.number,
        },
    );
    let calls = answers::position_answers(&b, &stores).unwrap().get_pool;
    let found = calls
        .iter()
        .find(|a| a.token_b == [1; 20] && a.tick_spacing == 100)
        .unwrap();
    assert_eq!(
        (found.pool.as_slice(), found.created_block),
        ([9; 20].as_slice(), b.number)
    );
    stores.put(
        Store::Pools,
        key,
        i::PoolRef {
            pool: vec![9; 20],
            created_block: b.number + 1,
        },
    );
    assert!(answers::position_answers(&b, &stores)
        .unwrap_err()
        .contains("future"));

    // USDC never probes itself; registry token argument order is not canonicalized.
    stores.pool(1);
    stores.put(
        Store::Pools,
        format!("p:{};", hex::encode(POOL)),
        i::PoolRecord {
            token0: USDC.to_vec(),
            token1: vec![2; 20],
            tick_spacing: 1,
            created_block: 1,
            created_log_index: 0,
        },
    );
    let calls = answers::position_answers(&b, &stores).unwrap().get_pool;
    assert_eq!(calls.len(), 4);
    assert!(calls
        .iter()
        .all(|a| a.token_a == USDC && a.token_b == [2; 20]));
    assert!(answers::position_answers(
        &block(vec![event("Initialize", 0), event("Flash", 0)]),
        &stores
    )
    .unwrap()
    .get_pool
    .is_empty());
    assert!(answers::position_answers(&b, &Stores::default()).is_err());
}

#[test]
fn all_44_missing_historical_wasm_calls_match_the_independent_cassette() {
    let corpus: serde_json::Value =
        serde_json::from_slice(include_bytes!("../../../fixtures/swap-upgrade-calls.json"))
            .unwrap();
    let entries = corpus["entries"].as_array().unwrap();
    assert_eq!(entries.len(), 44);
    for entry in entries {
        let calldata =
            hex::decode(entry["calldata"].as_str().unwrap().trim_start_matches("0x")).unwrap();
        let a = calldata[16..36].to_vec();
        let b = calldata[48..68].to_vec();
        let spacing = i32::from_be_bytes(calldata[96..100].try_into().unwrap());
        let mut stores = Stores::default();
        let number = entry["block_number"].as_u64().unwrap();
        for created in corpus["pool_created_candidates"].as_array().unwrap() {
            let created_block = created["block_number"].as_u64().unwrap();
            if created_block > number {
                continue;
            }
            let raw = hex::decode(created["candidate_protobuf_hex"].as_str().unwrap()).unwrap();
            let candidate = p::CandidateLog::decode(raw.as_slice()).unwrap();
            let Some(aerodrome_extractor_core::events::Event::PoolCreated {
                pool,
                token0,
                token1,
                spacing,
            }) = aerodrome_extractor_core::events::decode(&candidate).unwrap()
            else {
                panic!("expected actual PoolCreated")
            };
            let created = i::PoolsCreated {
                pools: vec![i::PoolCreatedRecord {
                    pool: pool.to_vec(),
                    token0: token0.to_vec(),
                    token1: token1.to_vec(),
                    tick_spacing: spacing,
                    log_index: candidate.log_index,
                    log_ordinal: candidate.log_ordinal,
                    ..Default::default()
                }],
            };
            for op in
                aerodrome_extractor_core::carry::registry_ops(&created, created_block).unwrap()
            {
                match op {
                    aerodrome_extractor_core::carry::StoreOp::Set { key, value, .. } => {
                        stores.values.insert((Store::Pools, key), value);
                    }
                    _ => panic!("registry must only set"),
                }
            }
        }
        stores.put(
            Store::Pools,
            format!("p:{};", hex::encode(POOL)),
            i::PoolRecord {
                token0: a.clone(),
                token1: b.clone(),
                tick_spacing: 1,
                created_block: 1,
                created_log_index: 0,
            },
        );
        let mut block = block(vec![event("Swap", 0)]);
        block.number = number;
        let output = answers::position_answers(&block, &stores).unwrap();
        let answer = output
            .get_pool
            .iter()
            .find(|p| p.token_a == a && p.token_b == b && p.tick_spacing == spacing)
            .expect("every independent mapping host call must have an answer");
        assert_eq!(entry["retval"]["kind"], "value");
        let expected = hex::decode(
            entry["retval"]["data"]
                .as_str()
                .unwrap()
                .trim_start_matches("0x"),
        )
        .unwrap();
        assert_eq!(expected.len(), 32);
        assert_eq!(answer.pool, expected[12..]);
    }
}

#[test]
fn future_or_noncanonical_carry_is_refused_and_anomalies_survive_assembly() {
    let mut stores = Stores::default();
    stores.pool(1);
    let key = format!("f:{}:0;", hex::encode(POOL));
    stores.slot(Store::PoolSlots, key.clone(), vec![1], 101);
    assert!(
        answers::fee_growth_answers(&block(vec![event("Flash", 0)]), &stores)
            .unwrap_err()
            .contains("future")
    );
    stores.slot(Store::PoolSlots, key, vec![0, 1], 100);
    assert!(
        answers::fee_growth_answers(&block(vec![event("Flash", 0)]), &stores)
            .unwrap_err()
            .contains("noncanonical")
    );
    let anomaly = p::Anomaly {
        kind: p::AnomalyKind::AnomalyOrdinalTie as i32,
        ..Default::default()
    };
    let output = answers::assemble(
        block(vec![]),
        i::StorageDeltas {
            relevant_writes: 3,
            reverted_writes_skipped: 2,
            anomalies: vec![anomaly.clone()],
            ..Default::default()
        },
        i::TickAnswers {
            anomalies: vec![anomaly.clone()],
            ..Default::default()
        },
        i::PositionAnswers {
            anomalies: vec![anomaly],
            ..Default::default()
        },
        i::TokenMetadataAnswers::default(),
        &stores,
    )
    .unwrap();
    assert_eq!(output.audit.as_ref().unwrap().anomalies.len(), 3);
    assert_eq!(output.audit.as_ref().unwrap().relevant_storage_writes, 3);
    assert!(output.calls.is_some());
}

#[test]
fn erc20_batch_is_sorted_deduplicated_raw_and_exactly_counted() {
    let created = i::PoolsCreated {
        pools: vec![
            i::PoolCreatedRecord {
                token0: vec![2; 20],
                token1: vec![1; 20],
                ..Default::default()
            },
            i::PoolCreatedRecord {
                token0: vec![1; 20],
                token1: vec![2; 20],
                ..Default::default()
            },
        ],
    };
    let tokens = metadata::tokens(&created).unwrap();
    assert_eq!(tokens.len(), 2);
    let calls = metadata::calls(&tokens);
    assert_eq!(calls.len(), 8);
    assert_eq!(calls[0].0, [1; 20]);
    assert_eq!(calls[4].0, [2; 20]);
    assert!(metadata::answers(&tokens, vec![]).is_err());
    let output = metadata::answers(
        &tokens,
        (0..8)
            .map(|n| metadata::Response {
                failed: n == 1,
                raw: if n == 2 { vec![] } else { vec![n as u8] },
            })
            .collect(),
    )
    .unwrap();
    assert_eq!(output.erc20[0].rpc_failed_mask, 2);
    assert_eq!(output.erc20[0].rpc_empty_mask, 4);
    assert_eq!(
        output.erc20[0].symbol.as_ref().unwrap().kind,
        Some(p::raw_retval::Kind::Value(vec![0]))
    );
    assert!(matches!(
        output.erc20[0].name.as_ref().unwrap().kind,
        Some(p::raw_retval::Kind::Reverted(_))
    ));
    assert!(metadata::answers(&BTreeSet::new(), vec![])
        .unwrap()
        .erc20
        .is_empty());
    assert_eq!(Config::walk_spacing(10), 200);
}
