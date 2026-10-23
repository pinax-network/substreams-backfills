use crate::{keccak, Address, Word};
pub const TICK_SHARDS: u8 = 8;
pub const POSITION_SHARDS: u8 = 16;
pub fn tick_shard(pool: &Address, tick: i32) -> u8 {
    let mut key = [0; 24];
    key[..20].copy_from_slice(pool);
    key[20..].copy_from_slice(&tick.to_be_bytes());
    keccak(&key)[0] % TICK_SHARDS
}
pub fn position_shard(id: &Word) -> u8 {
    id[31] % POSITION_SHARDS
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stable_partition() {
        let mut counts = [0; 8];
        for tick in -1000..1000 {
            counts[tick_shard(&[1; 20], tick) as usize] += 1;
        }
        assert!(counts.iter().all(|n| *n > 180));
        for n in 0..=255 {
            let mut id = [0; 32];
            id[31] = n;
            assert_eq!(position_shard(&id), n % 16);
        }
    }
}
