//! Aerodrome input, typed entity and transactional state foundations.
//! Authoritative scheduling for every deployed mapping handler, with bounded
//! memory replay and local transactional disk state. The live supervisor,
//! runtime/profile production qualification remain separate gates. BCGSNAP1
//! import has distinct development and typed capture-evidence paths.
//! Input validation and synthetic operation sealing do not certify a backfill.
pub mod abi;
pub mod calls;
pub mod differential;
pub mod durable;
pub mod entity;
pub mod handlers;
pub mod hosts;
pub mod identity;
pub mod input;
pub mod runner;
pub mod runtime;
pub mod state;
pub use aerodrome_extractor_core::{Address, Word};
pub use aerodrome_extractor_pb::v1 as pb;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReducerError(pub String);
impl std::fmt::Display for ReducerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}
impl std::error::Error for ReducerError {}
pub type Result<T> = std::result::Result<T, ReducerError>;
pub(crate) fn refuse(message: impl Into<String>) -> ReducerError {
    ReducerError(message.into())
}
pub(crate) fn require(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(refuse(message))
    }
}
pub(crate) fn address(bytes: &[u8]) -> Result<Address> {
    bytes
        .try_into()
        .map_err(|_| refuse("address must be 20 bytes"))
}
pub(crate) fn word(bytes: &[u8]) -> Result<Word> {
    bytes
        .try_into()
        .map_err(|_| refuse("word must be 32 bytes"))
}
pub(crate) fn int24(n: i32) -> Result<()> {
    require((-8388608..=8388607).contains(&n), "value exceeds int24")
}
pub(crate) fn unsigned(bytes: &[u8], max: usize) -> Result<()> {
    require(
        bytes.len() <= max && bytes.first() != Some(&0),
        "nonminimal or oversized unsigned integer",
    )
}
