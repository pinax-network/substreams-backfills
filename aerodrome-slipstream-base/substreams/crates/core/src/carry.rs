use crate::{layout, minimal, pb::internal as i, shard, word};
use prost::Message;
use std::collections::BTreeMap;
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StoreOp {
    Set {
        key: String,
        value: Vec<u8>,
        ordinal: u64,
    },
    Delete {
        key: String,
        ordinal: u64,
    },
}
impl StoreOp {
    pub fn ordinal(&self) -> u64 {
        match self {
            Self::Set { ordinal, .. } | Self::Delete { ordinal, .. } => *ordinal,
        }
    }
}
#[derive(Default)]
pub struct InMemoryCarry(BTreeMap<String, Vec<u8>>);
impl InMemoryCarry {
    pub fn apply(&mut self, ops: &[StoreOp]) {
        for op in ops {
            match op {
                StoreOp::Set { key, value, .. } => {
                    self.0.insert(key.clone(), value.clone());
                }
                StoreOp::Delete { key, .. } => self.0.retain(|k, _| !k.starts_with(key)),
            }
        }
    }
    pub fn get(&self, key: &str) -> Option<&[u8]> {
        self.0.get(key).map(Vec::as_slice)
    }
}
fn set(key: String, value: impl Message, ordinal: u64) -> StoreOp {
    StoreOp::Set {
        key,
        value: value.encode_to_vec(),
        ordinal,
    }
}
fn slot(key: String, w: &Option<i::SlotWrite>, block: u64) -> Result<StoreOp, &'static str> {
    let w = w.as_ref().ok_or("missing slot write")?;
    let bytes = minimal(&word(&w.word)?);
    if bytes.is_empty() {
        Ok(StoreOp::Delete {
            key,
            ordinal: w.ordinal,
        })
    } else {
        Ok(set(
            key,
            i::SlotWord {
                word: bytes,
                block,
                ordinal: w.ordinal,
            },
            w.ordinal,
        ))
    }
}
pub fn registry_ops(created: &i::PoolsCreated, block: u64) -> Result<Vec<StoreOp>, &'static str> {
    let mut out = vec![];
    for p in &created.pools {
        if p.pool.len() != 20 || p.token0.len() != 20 || p.token1.len() != 20 {
            return Err("registry address must be 20 bytes");
        }
        let pool = hex::encode(&p.pool);
        let a = hex::encode(&p.token0);
        let b = hex::encode(&p.token1);
        out.push(set(
            format!("p:{pool};"),
            i::PoolRecord {
                token0: p.token0.clone(),
                token1: p.token1.clone(),
                tick_spacing: p.tick_spacing,
                created_block: block,
                created_log_index: p.log_index,
            },
            p.log_ordinal,
        ));
        for (a, b) in [(&a, &b), (&b, &a)] {
            out.push(set(
                format!("g:{a}:{b}:{};", p.tick_spacing),
                i::PoolRef {
                    pool: p.pool.clone(),
                    created_block: block,
                },
                p.log_ordinal,
            ));
        }
    }
    out.sort_by_key(StoreOp::ordinal);
    Ok(out)
}
pub fn pool_slot_ops(d: &i::StorageDeltas, block: u64) -> Result<Vec<StoreOp>, &'static str> {
    clean_deltas(d)?;
    let mut out = vec![];
    for w in &d.fee_growth {
        if w.pool.len() != 20 || w.which > 1 {
            return Err("invalid fee-growth key");
        }
        out.push(slot(
            format!("f:{}:{};", hex::encode(&w.pool), w.which),
            &w.write,
            block,
        )?);
    }
    for w in &d.pool_keys {
        if w.member > 1 {
            return Err("invalid pool-key member");
        }
        out.push(slot(
            format!("k:{}:{};", w.pool_id, w.member),
            &w.write,
            block,
        )?);
    }
    out.sort_by_key(StoreOp::ordinal);
    Ok(out)
}
pub fn tick_slot_ops(
    d: &i::StorageDeltas,
    block: u64,
    partition: u8,
) -> Result<Vec<StoreOp>, &'static str> {
    clean_deltas(d)?;
    if partition >= shard::TICK_SHARDS {
        return Err("invalid tick shard");
    }
    let mut out = vec![];
    for t in &d.ticks {
        let pool = t
            .pool
            .as_slice()
            .try_into()
            .map_err(|_| "pool address must be 20 bytes")?;
        if shard::tick_shard(pool, t.tick) != partition {
            continue;
        }
        let address = hex::encode(pool);
        if t.member == 0 {
            let ordinal = t.write.as_ref().ok_or("missing tick write")?.ordinal;
            out.push(set(
                format!("m:{address}:{};", t.tick),
                i::TickMarker { block, ordinal },
                ordinal,
            ));
        } else if t.member <= 2 {
            out.push(slot(
                format!("w:{address}:{}:{};", t.tick, t.member),
                &t.write,
                block,
            )?);
        } else {
            return Err("invalid tick member");
        }
    }
    out.sort_by_key(StoreOp::ordinal);
    Ok(out)
}
pub fn position_slot_ops(
    d: &i::StorageDeltas,
    block: u64,
    partition: u8,
) -> Result<Vec<StoreOp>, &'static str> {
    clean_deltas(d)?;
    if partition >= shard::POSITION_SHARDS {
        return Err("invalid position shard");
    }
    let mut out = vec![];
    for p in &d.positions {
        let id = word(&p.token_id)?;
        if shard::position_shard(&id) != partition {
            continue;
        }
        let id = decimal(&id);
        let w = p.write.as_ref().ok_or("missing position write")?;
        match p.member {
            1 => {
                let (pool_id, tick_lower, tick_upper) = layout::decode_frag(&word(&w.word)?);
                let pool_id =
                    u64::try_from(pool_id).map_err(|_| "uint80 pool ID exceeds wire uint64")?;
                let key = format!("f:{id};");
                out.push(if pool_id == 0 {
                    StoreOp::Delete {
                        key,
                        ordinal: w.ordinal,
                    }
                } else {
                    set(
                        key,
                        i::PositionKeyFragment {
                            pool_id,
                            tick_lower,
                            tick_upper,
                            block,
                            ordinal: w.ordinal,
                        },
                        w.ordinal,
                    )
                });
            }
            2 | 3 => out.push(slot(format!("w:{id}:{};", p.member), &p.write, block)?),
            _ => return Err("invalid position member"),
        }
    }
    out.sort_by_key(StoreOp::ordinal);
    Ok(out)
}
fn clean_deltas(d: &i::StorageDeltas) -> Result<(), &'static str> {
    if !d.anomalies.is_empty() {
        return Err("refusing anomalous storage deltas before carry writes");
    }
    Ok(())
}

/// Carry ticks using Graph Node's exact ABI decoder. The extractor's Abigen
/// flag is diagnostic: it can disagree on trailing data and must not suppress
/// a tick that Graph Node would accept.
pub fn last_tick_ops(
    block: &crate::pb::v1::ExtractorBlock,
) -> Result<Vec<(String, i64, u64)>, &'static str> {
    if block
        .audit
        .as_ref()
        .is_none_or(|audit| !audit.anomalies.is_empty())
    {
        return Err("refusing unaudited or anomalous candidates before tick carry writes");
    }
    let mut ops = Vec::new();
    for candidate in &block.candidates {
        let tick = match crate::events::decode(candidate)? {
            Some(
                crate::events::Event::Initialize { tick } | crate::events::Event::Swap { tick },
            ) => tick,
            _ => continue,
        };
        ops.push((
            format!("t:{};", hex::encode(&candidate.address)),
            i64::from(tick),
            candidate.log_ordinal,
        ));
    }
    ops.sort_by_key(|(_, _, ordinal)| *ordinal);
    Ok(ops)
}
/// Decimal u256 key without a big-integer/runtime dependency.
pub fn decimal(value: &[u8; 32]) -> String {
    let mut n = *value;
    let mut digits = vec![];
    while n.iter().any(|x| *x != 0) {
        let mut rem = 0u16;
        for b in &mut n {
            let v = (rem << 8) | u16::from(*b);
            *b = (v / 10) as u8;
            rem = v % 10;
        }
        digits.push(b'0' + rem as u8);
    }
    if digits.is_empty() {
        digits.push(b'0');
    }
    digits.reverse();
    String::from_utf8(digits).unwrap()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn zero_deletes_only_exact_key() {
        let w = |value: u8| {
            Some(i::SlotWrite {
                word: vec![value],
                ordinal: 3,
                ..Default::default()
            })
        };
        let d = i::StorageDeltas {
            positions: vec![
                i::PositionWrite {
                    token_id: vec![1],
                    member: 2,
                    write: w(5),
                },
                i::PositionWrite {
                    token_id: vec![17],
                    member: 2,
                    write: w(6),
                },
            ],
            ..Default::default()
        };
        let mut c = InMemoryCarry::default();
        c.apply(&position_slot_ops(&d, 1, 1).unwrap());
        let mut clear = d.clone();
        clear.positions.truncate(1);
        clear.positions[0].write = w(0);
        c.apply(&position_slot_ops(&clear, 2, 1).unwrap());
        assert!(c.get("w:1:2;").is_none());
        assert!(c.get("w:17:2;").is_some());
    }
    #[test]
    fn full_width_decimal() {
        assert_eq!(
            decimal(&[255; 32]),
            "115792089237316195423570985008687907853269984665640564039457584007913129639935"
        );
    }
    #[test]
    fn burn_clears_fragment_and_rejects_truncation() {
        let mut w = layout::uint_word(1);
        let mut d = i::StorageDeltas {
            positions: vec![i::PositionWrite {
                token_id: vec![1],
                member: 1,
                write: Some(i::SlotWrite {
                    word: w.to_vec(),
                    ordinal: 1,
                    ..Default::default()
                }),
            }],
            ..Default::default()
        };
        assert!(matches!(
            position_slot_ops(&d, 1, 1).unwrap()[0],
            StoreOp::Set { .. }
        ));
        w[22] = 1;
        d.positions[0].write.as_mut().unwrap().word = w.to_vec();
        assert!(position_slot_ops(&d, 1, 1).is_err());
        d.positions[0].write.as_mut().unwrap().word = vec![0];
        assert!(matches!(
            position_slot_ops(&d, 1, 1).unwrap()[0],
            StoreOp::Delete { .. }
        ));
    }
}
