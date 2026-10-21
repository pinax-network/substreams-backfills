//! End-of-block storage selection. Call frames identify rollback, while each
//! storage change's address identifies the account (including DELEGATECALL).
use crate::{
    candidates::PoolRegistry,
    classify::{classify_npm_slot, classify_pool_slot, NpmSlot, PoolSlot, PreimageIndex},
    config::Config,
    pb::{eth, internal as i, v1 as p},
    word, Address, Word,
};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy)]
enum Target {
    Pool { spacing: i32 },
    Npm,
}
struct Slot {
    target: Target,
    first: (u64, Word),
    last: Option<i::SlotWrite>,
    ordinals: BTreeSet<u64>,
    skipped: u32,
    initialized: bool,
    tied: bool,
}
fn anomaly(kind: p::AnomalyKind, address: Address, key: Word, ordinal: u64) -> p::Anomaly {
    p::Anomaly {
        kind: kind as i32,
        address: address.to_vec(),
        key: key.to_vec(),
        ordinal,
        detail: kind.as_str_name().to_owned(),
    }
}
fn count(counter: &mut u32) -> Result<(), String> {
    *counter = counter
        .checked_add(1)
        .ok_or("storage write count overflow")?;
    Ok(())
}

/// Registry lookups must expose end-of-block values, including new pools whose
/// Initialize storage writes precede PoolCreated. No missing slot is invented.
pub fn storage_deltas(
    cfg: &Config,
    block: &eth::Block,
    registry: &impl PoolRegistry,
) -> Result<i::StorageDeltas, String> {
    let mut output = i::StorageDeltas::default();
    if !matches!(block.ver, 4 | 5) || block.detail_level != 0 {
        output.anomalies.push(anomaly(
            p::AnomalyKind::AnomalyUnsupportedBlockVersion,
            [0; 20],
            [0; 32],
            0,
        ));
        return Ok(output);
    }
    let preimages = PreimageIndex::from_block(block)?;
    let mut targets = BTreeMap::<Address, Option<Target>>::new();
    let mut slots = BTreeMap::<(Address, Word), Slot>::new();
    let calls = block
        .transaction_traces
        .iter()
        .flat_map(|tx| {
            tx.calls
                .iter()
                .map(move |call| (tx.index, tx.status == 1, false, call))
        })
        .chain(
            block
                .system_calls
                .iter()
                .map(|call| (u32::MAX, true, true, call)),
        );
    for (tx_index, succeeded, system, call) in calls {
        for change in &call.storage_changes {
            let Ok(address) = <Address>::try_from(change.address.as_slice()) else {
                return Err("storage change address must be 20 bytes".into());
            };
            let target = if let Some(target) = targets.get(&address) {
                *target
            } else {
                let target = if address == cfg.npm && block.number >= cfg.npm_start {
                    Some(Target::Npm)
                } else if block.number >= cfg.factory_start {
                    match registry.pool(&address)? {
                        Some(pool) => {
                            if pool.tick_spacing <= 0 || pool.created_block > block.number {
                                return Err("invalid end-of-block pool registry record".into());
                            }
                            Some(Target::Pool {
                                spacing: pool.tick_spacing,
                            })
                        }
                        None => None,
                    }
                } else {
                    None
                };
                targets.insert(address, target);
                target
            };
            let Some(target) = target else { continue };
            let key = word(&change.key)?;
            let old = word(&change.old_value)?;
            let new = word(&change.new_value)?;
            if system {
                output.anomalies.push(anomaly(
                    p::AnomalyKind::AnomalySystemCallTouchedTarget,
                    address,
                    key,
                    change.ordinal,
                ));
            }
            let slot = slots.entry((address, key)).or_insert_with(|| Slot {
                target,
                first: (change.ordinal, old),
                last: None,
                ordinals: BTreeSet::new(),
                skipped: 0,
                initialized: false,
                tied: false,
            });
            if !slot.ordinals.insert(change.ordinal) {
                slot.tied = true;
                output.anomalies.push(anomaly(
                    p::AnomalyKind::AnomalyOrdinalTie,
                    address,
                    key,
                    change.ordinal,
                ));
            }
            if change.ordinal < slot.first.0 {
                slot.first = (change.ordinal, old);
            }
            if !succeeded || call.state_reverted {
                count(&mut slot.skipped)?;
                count(&mut output.reverted_writes_skipped)?;
                continue;
            }
            count(&mut output.relevant_writes)?;
            slot.initialized |= old == [0; 32] && new != [0; 32];
            if slot
                .last
                .as_ref()
                .is_none_or(|last| change.ordinal > last.ordinal)
            {
                slot.last = Some(i::SlotWrite {
                    word: new.to_vec(),
                    ordinal: change.ordinal,
                    tx_index,
                    reverted_skipped: 0,
                });
            }
        }
    }
    for ((address, key), slot) in slots {
        // Tied ordinals have no authoritative last write. The anomaly is fatal
        // to the final consumer; avoid selecting an arbitrary value even here.
        if slot.tied {
            continue;
        }
        let Some(mut write) = slot.last else { continue };
        write.reverted_skipped = slot.skipped;
        match slot.target {
            Target::Pool { spacing } => match classify_pool_slot(&key, &preimages) {
                Some(PoolSlot::Fixed(which @ 7..=8)) => output.fee_growth.push(i::FeeGrowthWrite {
                    pool: address.to_vec(),
                    which: u32::from(which - 7),
                    write: Some(write),
                }),
                Some(PoolSlot::Tick { tick, member }) => {
                    if tick % spacing != 0 {
                        output.anomalies.push(anomaly(
                            p::AnomalyKind::AnomalyTickAlignment,
                            address,
                            key,
                            write.ordinal,
                        ));
                        continue;
                    }
                    if (member == 0 && slot.initialized) || matches!(member, 1 | 2) {
                        output.ticks.push(i::TickWrite {
                            pool: address.to_vec(),
                            tick,
                            member: u32::from(member),
                            write: Some(write),
                        });
                    }
                }
                Some(_) => {}
                None => output.anomalies.push(anomaly(
                    p::AnomalyKind::AnomalyUnclassifiedPoolSlot,
                    address,
                    key,
                    write.ordinal,
                )),
            },
            Target::Npm => match classify_npm_slot(&key, &preimages) {
                NpmSlot::Position { token_id, member } => {
                    if matches!(member, 2 | 3)
                        || (member == 1 && slot.first.1[16..] != write.word[16..])
                    {
                        output.positions.push(i::PositionWrite {
                            token_id: token_id.to_vec(),
                            member: u32::from(member),
                            write: Some(write),
                        });
                    }
                }
                NpmSlot::PoolKey { pool_id, member } => output.pool_keys.push(i::PoolKeyWrite {
                    pool_id: u64::try_from(pool_id)
                        .map_err(|_| "uint80 pool ID exceeds wire uint64")?,
                    member: u32::from(member),
                    write: Some(write),
                }),
                NpmSlot::Other => {}
            },
        }
    }
    output
        .fee_growth
        .sort_by_key(|v| v.write.as_ref().unwrap().ordinal);
    output
        .ticks
        .sort_by_key(|v| v.write.as_ref().unwrap().ordinal);
    output
        .positions
        .sort_by_key(|v| v.write.as_ref().unwrap().ordinal);
    output
        .pool_keys
        .sort_by_key(|v| v.write.as_ref().unwrap().ordinal);
    output.anomalies.sort_by(|a, b| {
        (a.ordinal, &a.address, &a.key, a.kind).cmp(&(b.ordinal, &b.address, &b.key, b.kind))
    });
    Ok(output)
}
