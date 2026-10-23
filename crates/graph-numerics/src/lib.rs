//! Numeric primitives for Graph Node v0.44.0, commit
//! `77823b5a7adc4eac4abf03202c8dd7cb00dea31d`.
//!
//! Arithmetic uses the exact upstream bigdecimal 0.1.2 and num-bigint 0.2.6
//! dependencies. Decimal operations model the host result AND its next WASM
//! crossing; raw `BigInt.toBigDecimal()` and database reads normalize once.
//! These differ for some negative numbers. Checkpoint serialization preserves
//! that difference; BlockChanges v1 serialization refuses non-fixed points.
//! See the crate README for the boundary model and independent oracle checks.

pub mod bigint;
mod decimal;
mod error;
pub mod mapping;

pub use decimal::GraphDecimal;
pub use error::NumericError;
pub use graph_num_bigint::BigInt;

pub const GRAPH_NODE_COMMIT: &str = "77823b5a7adc4eac4abf03202c8dd7cb00dea31d";
