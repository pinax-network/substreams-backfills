//! Host-only integration harness for the disconnected Transaction reducer.
//!
//! Re-exporting the writer protobuf at this crate root lets the reducer source
//! retain the same paths it would use in the runtime library without linking
//! the reducer into that library or its WASM target.

pub use substreams_uniswap_v3::pb;

#[path = "../src/transaction_reducer.rs"]
mod transaction_reducer;
