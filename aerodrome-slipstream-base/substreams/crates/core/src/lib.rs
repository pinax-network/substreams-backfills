//! Deterministic extraction primitives, shared by native reducers and WASM adapters.
pub mod calls;
pub mod candidates;
pub mod carry;
pub mod classify;
pub mod config;
pub mod gas;
pub mod layout;
pub mod shard;
pub mod storage;
pub mod walk;
pub use aerodrome_extractor_pb as pb;
pub type Address = [u8; 20];
pub type Word = [u8; 32];
pub fn keccak(bytes: &[u8]) -> Word {
    use tiny_keccak::{Hasher, Keccak};
    let mut h = Keccak::v256();
    h.update(bytes);
    let mut out = [0; 32];
    h.finalize(&mut out);
    out
}
pub fn word(bytes: &[u8]) -> Result<Word, &'static str> {
    if bytes.len() > 32 {
        return Err("integer exceeds 256 bits");
    }
    let mut out = [0; 32];
    out[32 - bytes.len()..].copy_from_slice(bytes);
    Ok(out)
}
pub fn minimal(bytes: &[u8]) -> Vec<u8> {
    bytes.iter().skip_while(|x| **x == 0).copied().collect()
}
