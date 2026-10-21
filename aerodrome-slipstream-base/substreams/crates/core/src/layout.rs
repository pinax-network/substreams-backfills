use crate::{keccak, Address, Word};
pub const LAYOUT_ID: &str = "slipstream@37eead2c7e5302a204dec78bfa0775bbb8ff48a2";
pub const POOL_FEE_GROWTH0: u64 = 7;
pub const POOL_FEE_GROWTH1: u64 = 8;
pub const POOL_TICKS: u64 = 17;
pub const POOL_BITMAP: u64 = 18;
pub const POOL_POSITIONS: u64 = 19;
pub const POOL_OBSERVATIONS: u64 = 20;
pub const NPM_POOL_KEYS: u64 = 12;
pub const NPM_POSITIONS: u64 = 13;
pub const FACTORY_GET_POOL: u64 = 6;
pub const EIP1167_PREFIX: [u8; 10] = [0x36, 0x3d, 0x3d, 0x37, 0x3d, 0x3d, 0x3d, 0x36, 0x3d, 0x73];
pub const EIP1167_SUFFIX: [u8; 15] = [
    0x5a, 0xf4, 0x3d, 0x82, 0x80, 0x3e, 0x90, 0x3d, 0x91, 0x60, 0x2b, 0x57, 0xfd, 0x5b, 0xf3,
];
pub fn uint_word(value: u128) -> Word {
    let mut out = [0; 32];
    out[16..].copy_from_slice(&value.to_be_bytes());
    out
}
pub fn int_word(value: i32) -> Word {
    let mut out = if value < 0 { [255; 32] } else { [0; 32] };
    out[28..].copy_from_slice(&value.to_be_bytes());
    out
}
pub fn mapping_base(key: &Word, slot: u64) -> Word {
    let mut data = [0; 64];
    data[..32].copy_from_slice(key);
    data[56..].copy_from_slice(&slot.to_be_bytes());
    keccak(&data)
}
pub fn tick_base(tick: i32) -> Word {
    mapping_base(&int_word(tick), POOL_TICKS)
}
pub fn position_base(id: &Word) -> Word {
    mapping_base(id, NPM_POSITIONS)
}
pub fn pool_key_base(id: u128) -> Word {
    mapping_base(&uint_word(id), NPM_POOL_KEYS)
}
pub fn signed24(bytes: &[u8]) -> i32 {
    let mut out = if bytes[0] & 128 != 0 {
        [255; 4]
    } else {
        [0; 4]
    };
    out[1..].copy_from_slice(bytes);
    i32::from_be_bytes(out)
}
pub fn decode_staked(word: &Word) -> i128 {
    i128::from_be_bytes(word[16..].try_into().unwrap())
}
pub fn decode_frag(word: &Word) -> (u128, i32, i32) {
    let mut id = [0; 16];
    id[6..].copy_from_slice(&word[22..]);
    (
        u128::from_be_bytes(id),
        signed24(&word[19..22]),
        signed24(&word[16..19]),
    )
}
pub fn decode_pool_key(w0: &Word, w1: &Word) -> (Address, Address, i32) {
    (
        w0[12..].try_into().unwrap(),
        w1[12..].try_into().unwrap(),
        signed24(&w1[9..12]),
    )
}
pub fn clone_implementation(code: &[u8]) -> Option<Address> {
    if code.len() != 45 || code[..10] != EIP1167_PREFIX || code[30..] != EIP1167_SUFFIX {
        return None;
    }
    Some(code[10..30].try_into().unwrap())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn packed_signed_fields() {
        let mut w = [0; 32];
        w[22..].copy_from_slice(&[0, 0, 0, 0, 0, 0, 0, 0, 0, 1]);
        w[19..22].fill(255);
        w[18] = 1;
        w[0] = 9;
        assert_eq!(decode_frag(&w), (1, -1, 1));
        assert_eq!(decode_staked(&[255; 32]), -1);
        w[16] = 128;
        assert_eq!(decode_frag(&w).2, -8388607);
    }
    #[test]
    fn mapping_slots_and_clone() {
        assert_eq!(&hex::encode(tick_base(-1))[..8], "a69f8edf");
        assert_eq!(&hex::encode(tick_base(1))[..8], "17bc176d");
        assert_eq!(&hex::encode(position_base(&uint_word(1)))[..8], "fd54ff1e");
        assert_eq!(&hex::encode(pool_key_base(1))[..8], "d421a518");
        let mut c = EIP1167_PREFIX.to_vec();
        c.extend([3; 20]);
        c.extend(EIP1167_SUFFIX);
        assert_eq!(clone_implementation(&c), Some([3; 20]));
        c.push(0);
        assert_eq!(clone_implementation(&c), None);
    }
}
