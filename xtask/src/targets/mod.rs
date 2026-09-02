//! Rust ports of the pinned-target baseline verifiers (#110), one module per
//! family. Each exposes `verify(root, lock, exact_source_root) -> Result<String, String>`
//! with fail-closed semantics identical to the retired Python verifier.

pub mod aerodrome_slipstream_base;
pub mod exchange_v3_bsc;
pub mod messari_v3;
pub mod pancakeswap_infinity_cl_bsc;
pub mod uniswap_v2_base;
pub mod uniswap_v3_matic;
