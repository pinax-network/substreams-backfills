//! End-of-block call answers. Store reads are explicit so native fixtures and
//! WASM adapters execute the same derivation code.
use crate::{
    carry::decimal,
    config::Config,
    events::{self, Event},
    layout, minimal,
    pb::{internal as i, v1 as p},
    shard, word, Address, Word,
};
use prost::Message;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Store {
    Pools,
    PoolSlots,
    Tick(u8),
    Position(u8),
}

pub trait StoreRead {
    /// Always end-of-block state (Substreams get_last).
    fn get(&self, store: Store, key: &str) -> Result<Option<Vec<u8>>, String>;
    /// State before this block (Substreams get_first), never get_last.
    fn first_tick(&self, pool: &Address) -> Result<Option<i64>, String>;
}

fn read<M: Message + Default>(
    stores: &impl StoreRead,
    store: Store,
    key: &str,
) -> Result<Option<M>, String> {
    stores
        .get(store, key)?
        .map(|bytes| M::decode(bytes.as_slice()).map_err(|e| format!("corrupt carry {key}: {e}")))
        .transpose()
}
fn provenance(changed: u64, ordinal: u64, block: u64) -> Result<p::SlotProvenance, String> {
    if changed > block {
        return Err("carry record comes from a future block".into());
    }
    Ok(p::SlotProvenance {
        source: if changed == block {
            p::SlotSource::InBlock
        } else {
            p::SlotSource::Carried
        } as i32,
        last_change_block: changed,
        last_change_ordinal: ordinal,
    })
}
fn slot(
    stores: &impl StoreRead,
    store: Store,
    key: &str,
    block: u64,
) -> Result<(Word, p::SlotProvenance), String> {
    match read::<i::SlotWord>(stores, store, key)? {
        Some(value) => {
            if value.word.is_empty() || value.word[0] == 0 {
                return Err(format!("noncanonical carry word {key}"));
            }
            Ok((
                word(&value.word)?,
                provenance(value.block, value.ordinal, block)?,
            ))
        }
        None => Ok((
            [0; 32],
            p::SlotProvenance {
                source: p::SlotSource::Zero as i32,
                last_change_block: 0,
                last_change_ordinal: 0,
            },
        )),
    }
}
fn address(bytes: &[u8]) -> Result<Address, String> {
    bytes
        .try_into()
        .map_err(|_| "address must be 20 bytes".into())
}
fn checked_tick(value: i64) -> Result<i32, String> {
    if !(-8_388_608..=8_388_607).contains(&value) {
        return Err("carry tick exceeds int24".into());
    }
    Ok(value as i32)
}
fn pool_record(
    stores: &impl StoreRead,
    pool: &Address,
    block: u64,
) -> Result<i::PoolRecord, String> {
    let record: i::PoolRecord =
        read(stores, Store::Pools, &format!("p:{};", hex::encode(pool)))?
            .ok_or("candidate pool is missing from the end-of-block registry")?;
    if record.created_block > block || !(1..=8_388_607).contains(&record.tick_spacing) {
        return Err("invalid pool registry record".into());
    }
    address(&record.token0)?;
    address(&record.token1)?;
    Ok(record)
}

pub fn fee_growth_answers(
    block: &p::ExtractorBlock,
    stores: &impl StoreRead,
) -> Result<Vec<p::FeeGrowthGlobalAnswer>, String> {
    let mut pools = BTreeSet::new();
    for candidate in &block.candidates {
        if matches!(
            events::decode(candidate)?,
            Some(Event::Swap { .. } | Event::Flash)
        ) {
            pools.insert(address(&candidate.address)?);
        }
    }
    pools
        .into_iter()
        .map(|pool| {
            pool_record(stores, &pool, block.number)?;
            let key = hex::encode(pool);
            let (w0, p0) = slot(
                stores,
                Store::PoolSlots,
                &format!("f:{key}:0;"),
                block.number,
            )?;
            let (w1, p1) = slot(
                stores,
                Store::PoolSlots,
                &format!("f:{key}:1;"),
                block.number,
            )?;
            Ok(p::FeeGrowthGlobalAnswer {
                pool: pool.to_vec(),
                fee_growth_global0_x128: w0.to_vec(),
                fee_growth_global1_x128: w1.to_vec(),
                p0: Some(p0),
                p1: Some(p1),
            })
        })
        .collect()
}

pub fn tick_answers(
    block: &p::ExtractorBlock,
    stores: &impl StoreRead,
) -> Result<i::TickAnswers, String> {
    let mut result = i::TickAnswers::default();
    let mut ticks = BTreeMap::<(Address, i32), u32>::new();
    let mut previous = BTreeMap::<Address, i32>::new();
    for candidate in &block.candidates {
        let Some(event) = events::decode(candidate)? else {
            continue;
        };
        let pool = address(&candidate.address)?;
        match event {
            Event::Mint { lower, upper } | Event::Burn { lower, upper } => {
                for tick in [lower, upper] {
                    *ticks.entry((pool, tick)).or_default() |= 1;
                }
            }
            Event::Initialize { tick } => {
                previous.insert(pool, tick);
            }
            Event::Swap { tick } => {
                let record = pool_record(stores, &pool, block.number)?;
                let old = match previous.get(&pool) {
                    Some(tick) => Some(*tick),
                    None => stores.first_tick(&pool)?.map(checked_tick).transpose()?,
                };
                previous.insert(pool, tick);
                let Some(old) = old else {
                    result.anomalies.push(p::Anomaly {
                        kind: p::AnomalyKind::AnomalySwapWithoutPriorTick as i32,
                        address: pool.to_vec(),
                        key: vec![],
                        ordinal: candidate.log_ordinal,
                        detail: "no Initialize/Swap tick before this candidate".into(),
                    });
                    continue;
                };
                let (probes, count) = crate::walk::walk_candidates(
                    &pool,
                    old,
                    tick,
                    record.tick_spacing,
                    Config::walk_spacing(record.tick_spacing),
                    &|_, _| true,
                );
                result.swap_walk_probes = result
                    .swap_walk_probes
                    .checked_add(count)
                    .ok_or("swap probe count overflow")?;
                for candidate_tick in probes {
                    // The walk's conservative upper bound may exceed int24;
                    // such a position cannot have an initialized tick marker.
                    if !(-8_388_608..=8_388_607).contains(&candidate_tick) {
                        continue;
                    }
                    let store = Store::Tick(shard::tick_shard(&pool, candidate_tick));
                    if let Some(marker) = read::<i::TickMarker>(
                        stores,
                        store,
                        &format!("m:{}:{candidate_tick};", hex::encode(pool)),
                    )? {
                        provenance(marker.block, marker.ordinal, block.number)?;
                        *ticks.entry((pool, candidate_tick)).or_default() |= 2;
                    }
                }
            }
            Event::Flash | Event::Position { .. } | Event::PoolCreated { .. } => {}
        }
    }
    for ((pool, tick), reasons) in ticks {
        let store = Store::Tick(shard::tick_shard(&pool, tick));
        let key = format!("w:{}:{tick}", hex::encode(pool));
        let (staked, p_staked) = slot(stores, store, &format!("{key}:1;"), block.number)?;
        let (fee, p_fee0) = slot(stores, store, &format!("{key}:2;"), block.number)?;
        result.ticks.push(p::TickAnswer {
            pool: pool.to_vec(),
            tick,
            staked_liquidity_net: layout::decode_staked(&staked).to_be_bytes().to_vec(),
            fee_growth_outside0_x128: fee.to_vec(),
            p_staked: Some(p_staked),
            p_fee0: Some(p_fee0),
            reasons,
        });
    }
    Ok(result)
}

pub fn position_answers(
    block: &p::ExtractorBlock,
    stores: &impl StoreRead,
) -> Result<i::PositionAnswers, String> {
    let mut result = i::PositionAnswers::default();
    let mut ids = BTreeSet::new();
    let mut pool_keys = BTreeSet::new();
    for candidate in &block.candidates {
        match events::decode(candidate)? {
            Some(Event::Position { token_id }) => {
                ids.insert(token_id);
            }
            Some(Event::Swap { .. }) => {
                let pool = address(&candidate.address)?;
                let record = pool_record(stores, &pool, block.number)?;
                for token in [address(&record.token0)?, address(&record.token1)?] {
                    pool_keys.extend(crate::mapping_probes::missing_whitelist_pool_probes(token));
                }
            }
            _ => {}
        }
    }
    for id in ids {
        let store = Store::Position(shard::position_shard(&id));
        let key = decimal(&id);
        let Some(fragment) = read::<i::PositionKeyFragment>(stores, store, &format!("f:{key};"))?
        else {
            result.positions.push(p::PositionAnswer {
                token_id: minimal(&id),
                result: Some(p::position_answer::Result::Reverted(p::raw_retval::Null {})),
            });
            continue;
        };
        if fragment.pool_id == 0 {
            return Err("zero pool ID must delete position fragment".into());
        }
        checked_tick(i64::from(fragment.tick_lower))?;
        checked_tick(i64::from(fragment.tick_upper))?;
        let p_key = provenance(fragment.block, fragment.ordinal, block.number)?;
        let pool_key = format!("k:{}", fragment.pool_id);
        let (w0, p0) = slot(
            stores,
            Store::PoolSlots,
            &format!("{pool_key}:0;"),
            block.number,
        )?;
        let (w1, p1) = slot(
            stores,
            Store::PoolSlots,
            &format!("{pool_key}:1;"),
            block.number,
        )?;
        if p0.source == p::SlotSource::Zero as i32 || p1.source == p::SlotSource::Zero as i32 {
            result.anomalies.push(p::Anomaly {
                kind: p::AnomalyKind::AnomalyMissingPoolKey as i32,
                address: Config::parse(crate::config::PARAMS)
                    .expect("constant config")
                    .npm
                    .to_vec(),
                key: id.to_vec(),
                ordinal: fragment.ordinal,
                detail: format!(
                    "position {key} references missing pool key {}",
                    fragment.pool_id
                ),
            });
            continue;
        }
        let (token0, token1, spacing) = layout::decode_pool_key(&w0, &w1);
        if spacing <= 0 {
            return Err("position pool key has nonpositive spacing".into());
        }
        let (fee0, pf0) = slot(stores, store, &format!("w:{key}:2;"), block.number)?;
        let (fee1, pf1) = slot(stores, store, &format!("w:{key}:3;"), block.number)?;
        pool_keys.insert((token0, token1, spacing));
        result.positions.push(p::PositionAnswer {
            token_id: minimal(&id),
            result: Some(p::position_answer::Result::Value(p::PositionValue {
                token0: token0.to_vec(),
                token1: token1.to_vec(),
                tick_spacing: spacing,
                tick_lower: fragment.tick_lower,
                tick_upper: fragment.tick_upper,
                fee_growth_inside0_last_x128: fee0.to_vec(),
                fee_growth_inside1_last_x128: fee1.to_vec(),
                pool_id: fragment.pool_id,
                p_key: Some(p_key),
                p_fee0: Some(pf0),
                p_fee1: Some(pf1),
            })),
        });
    }
    for (a, b, spacing) in pool_keys {
        let reference = read::<i::PoolRef>(
            stores,
            Store::Pools,
            &format!("g:{}:{}:{spacing};", hex::encode(a), hex::encode(b)),
        )?;
        let (pool, created_block) = match reference {
            Some(value) => {
                let pool = address(&value.pool)?;
                if value.created_block > block.number {
                    return Err("getPool record comes from a future block".into());
                }
                (pool, value.created_block)
            }
            None => ([0; 20], 0),
        };
        result.get_pool.push(p::GetPoolAnswer {
            token_a: a.to_vec(),
            token_b: b.to_vec(),
            tick_spacing: spacing,
            pool: pool.to_vec(),
            created_block,
        });
    }
    Ok(result)
}

pub fn assemble(
    mut block: p::ExtractorBlock,
    deltas: i::StorageDeltas,
    ticks: i::TickAnswers,
    positions: i::PositionAnswers,
    metadata: i::TokenMetadataAnswers,
    stores: &impl StoreRead,
) -> Result<p::ExtractorBlock, String> {
    if block.calls.is_some() {
        return Err("candidate block already contains answers".into());
    }
    let fee_growth = fee_growth_answers(&block, stores)?;
    let audit = block.audit.as_mut().ok_or("candidate block has no audit")?;
    audit.relevant_storage_writes = deltas.relevant_writes;
    audit.reverted_writes_skipped = deltas.reverted_writes_skipped;
    audit.tick_candidates =
        u32::try_from(ticks.ticks.len()).map_err(|_| "too many tick answers")?;
    audit.swap_walk_probes = ticks.swap_walk_probes;
    audit.anomalies.extend(deltas.anomalies);
    audit.anomalies.extend(ticks.anomalies);
    audit.anomalies.extend(positions.anomalies);
    block.calls = Some(p::CallAnswers {
        erc20: metadata.erc20,
        fee_growth,
        ticks: ticks.ticks,
        positions: positions.positions,
        get_pool: positions.get_pool,
    });
    Ok(block)
}
