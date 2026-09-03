//! `graph-mapping-host` runs a *deployed* subgraph's mapping WASM under our own
//! Rust host, built on Graph Node v0.44.0's own crates (rev
//! `77823b5a7adc4eac4abf03202c8dd7cb00dea31d`).
//!
//! The crate is family-neutral: it knows about segment bundles, Firehose blocks,
//! an in-memory store, an `eth_call` cassette, and Graph Node's wave scheduler.
//! Nothing in it is Uniswap-specific; Uniswap V3 is simply the first family whose
//! bundles live under `segments/`.
//!
//! Phase 1 scope is hermetic execution plus a deterministic JSON report. Emitting
//! `BlockChanges` v1 frames is phase 2; see `README.md`.

pub mod block;
pub mod blockchanges;
pub mod bundle;
pub mod calls;
pub mod descriptor;
pub mod env_pin;
pub mod poi;
pub mod report;
pub mod runner;
pub mod store;

pub use blockchanges::{bcf1_frame, BlockOpsBuilder, OpRecorder, RecordedOp};
pub use bundle::{BundleFile, BundleLock, SegmentBundle};
pub use calls::{Cassette, CassetteEntry, CassetteMode, CassetteRuntimeAdapter};
pub use report::{BlockReport, RunReport};
pub use runner::{SegmentHost, SegmentHostConfig};
pub use store::MemoryStore;
