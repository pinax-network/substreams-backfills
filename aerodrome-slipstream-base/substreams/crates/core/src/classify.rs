use crate::{keccak, layout, pb::eth, Word};
use std::collections::BTreeMap;
#[derive(Debug, Default)]
pub struct PreimageIndex(BTreeMap<Word, [u8; 64]>);
impl PreimageIndex {
    pub fn insert(&mut self, hash: Word, preimage: &[u8]) -> Result<(), &'static str> {
        if preimage.len() != 64 {
            return Ok(());
        }
        if keccak(preimage) != hash {
            return Err("keccak preimage hash mismatch");
        }
        self.0.insert(hash, preimage.try_into().unwrap());
        Ok(())
    }
    pub fn from_block(block: &eth::Block) -> Result<Self, String> {
        let mut out = Self::default();
        for call in block
            .transaction_traces
            .iter()
            .flat_map(|t| t.calls.iter())
            .chain(block.system_calls.iter())
        {
            for (key, value) in &call.keccak_preimages {
                let key = hex::decode(key.strip_prefix("0x").unwrap_or(key))
                    .map_err(|_| "invalid preimage key")?;
                let value = hex::decode(value.strip_prefix("0x").unwrap_or(value))
                    .map_err(|_| "invalid preimage bytes")?;
                let key = key
                    .try_into()
                    .map_err(|_| "preimage hash must be 32 bytes")?;
                out.insert(key, &value)?;
            }
        }
        Ok(out)
    }
    pub fn base_of(&self, key: &Word, max_off: u8) -> Option<(u8, Word, u64)> {
        let mut base = *key;
        for offset in 0..=max_off {
            if let Some(pre) = self.0.get(&base) {
                if pre[32..56].iter().all(|b| *b == 0) {
                    return Some((
                        offset,
                        pre[..32].try_into().unwrap(),
                        u64::from_be_bytes(pre[56..].try_into().unwrap()),
                    ));
                }
            }
            if !subtract_one(&mut base) {
                break;
            }
        }
        None
    }
}
fn subtract_one(word: &mut Word) -> bool {
    for b in word.iter_mut().rev() {
        let (next, borrow) = b.overflowing_sub(1);
        *b = next;
        if !borrow {
            return true;
        }
    }
    false
}
#[derive(Debug, PartialEq, Eq)]
pub enum PoolSlot {
    Fixed(u8),
    Observation(u16),
    Tick { tick: i32, member: u8 },
    Bitmap(i16),
    PoolPosition { member: u8 },
}
#[derive(Debug, PartialEq, Eq)]
pub enum NpmSlot {
    Position { token_id: Word, member: u8 },
    PoolKey { pool_id: u128, member: u8 },
    Other,
}
fn small(key: &Word) -> Option<u64> {
    key[..24]
        .iter()
        .all(|b| *b == 0)
        .then(|| u64::from_be_bytes(key[24..].try_into().unwrap()))
}
fn canonical_int24(word: &Word) -> Option<i32> {
    let n = layout::signed24(&word[29..]);
    (layout::int_word(n) == *word).then_some(n)
}
pub fn classify_pool_slot(key: &Word, pre: &PreimageIndex) -> Option<PoolSlot> {
    if let Some(n) = small(key) {
        if n <= 16 {
            return Some(PoolSlot::Fixed(n as u8));
        }
        if (20..20 + 65535).contains(&n) {
            return Some(PoolSlot::Observation((n - 20) as u16));
        }
    }
    let (member, k, slot) = pre.base_of(key, 5)?;
    match slot {
        17 => Some(PoolSlot::Tick {
            tick: canonical_int24(&k)?,
            member,
        }),
        18 if member == 0 => {
            let n = canonical_int24(&k)?;
            Some(PoolSlot::Bitmap(i16::try_from(n).ok()?))
        }
        19 if member <= 3 => Some(PoolSlot::PoolPosition { member }),
        _ => None,
    }
}
pub fn classify_npm_slot(key: &Word, pre: &PreimageIndex) -> NpmSlot {
    match pre.base_of(key, 4) {
        Some((member, token_id, 13)) => NpmSlot::Position { token_id, member },
        Some((member, id, 12)) if member <= 1 && id[..22].iter().all(|b| *b == 0) => {
            NpmSlot::PoolKey {
                pool_id: u128::from_be_bytes(id[16..].try_into().unwrap()),
                member,
            }
        }
        _ => NpmSlot::Other,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn insert(pre: &mut PreimageIndex, key: Word, slot: u64) -> Word {
        let mut data = [0; 64];
        data[..32].copy_from_slice(&key);
        data[56..].copy_from_slice(&slot.to_be_bytes());
        let base = keccak(&data);
        pre.insert(base, &data).unwrap();
        base
    }
    fn plus(mut word: Word, n: u8) -> Word {
        for _ in 0..n {
            for b in word.iter_mut().rev() {
                let (v, carry) = b.overflowing_add(1);
                *b = v;
                if !carry {
                    break;
                }
            }
        }
        word
    }
    #[test]
    fn pinned_mapping_layouts() {
        let mut p = PreimageIndex::default();
        let tick = insert(&mut p, layout::int_word(-198700), 17);
        for member in 0..6 {
            assert_eq!(
                classify_pool_slot(&plus(tick, member), &p),
                Some(PoolSlot::Tick {
                    tick: -198700,
                    member
                })
            );
        }
        assert_eq!(classify_pool_slot(&plus(tick, 6), &p), None);
        let id = layout::uint_word(1);
        let pos = insert(&mut p, id, 13);
        for member in 0..5 {
            assert_eq!(
                classify_npm_slot(&plus(pos, member), &p),
                NpmSlot::Position {
                    token_id: id,
                    member
                }
            );
        }
        let pk = insert(&mut p, id, 12);
        assert_eq!(
            classify_npm_slot(&plus(pk, 1), &p),
            NpmSlot::PoolKey {
                pool_id: 1,
                member: 1
            }
        );
        assert_eq!(
            classify_pool_slot(&layout::uint_word(7), &p),
            Some(PoolSlot::Fixed(7))
        );
        assert_eq!(
            classify_pool_slot(&layout::uint_word(65554), &p),
            Some(PoolSlot::Observation(65534))
        );
        assert_eq!(classify_pool_slot(&layout::uint_word(65555), &p), None);
        assert!(p.insert([0; 32], &[0; 64]).is_err());
        p.insert([0; 32], &[0; 63]).unwrap();
    }
}
