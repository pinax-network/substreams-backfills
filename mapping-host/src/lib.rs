//! `graph-mapping-host` runs a *deployed* subgraph's mapping WASM under our own
//! Rust host, built on Graph Node v0.44.0's own crates (rev
//! `77823b5a7adc4eac4abf03202c8dd7cb00dea31d`).
//!
//! The crate is family-neutral: it knows about segment bundles, Firehose blocks,
//! an in-memory store, an `eth_call` cassette, and Graph Node's wave scheduler.
//! Nothing in it is Uniswap-specific; Uniswap V3 is simply the first family whose
//! bundles live under `segments/`.
//!
//! Blocks reach it through [`source::BlockSource`]: either the committed `.pb`
//! fixtures, or a live `sf.firehose.v2.Stream/Blocks` range. CI only ever uses
//! the fixtures; see `README.md`.

pub mod block;
pub mod blockchanges;
pub mod bundle;
pub mod calls;
pub mod checkpoint;
pub mod descriptor;
pub mod disk_oracle;
pub mod disk_store;
pub mod dynamic_sources;
pub mod env_pin;
pub mod evidence;
pub mod live;
pub mod outputs;
pub mod poi;
pub mod replay;
pub mod report;
pub mod runner;
pub mod source;
pub mod source_chunk;
pub mod store;
pub mod store_state;

pub use blockchanges::{bcf1_frame, BlockOpsBuilder, OpRecorder, RecordedOp};
pub use bundle::{BundleFile, BundleLock, SegmentBundle};
pub use calls::{
    Cassette, CassetteEntry, CassetteFingerprint, CassetteMode, CassetteRowFingerprint,
    CassetteRuntimeAdapter,
};
pub use checkpoint::{CassettePin, HostCheckpoint, CHECKPOINT_SCHEMA};
pub use evidence::{RunEvidence, EVIDENCE_SCHEMA, EVIDENCE_SCHEMA_V2};
pub use outputs::ResumePolicy;
pub use replay::{replay_range, CheckpointPolicy, ReplayOutputs, ReplayResult};
pub use report::{BlockReport, RunReport};
pub use runner::{SegmentHost, SegmentHostConfig};
pub use source::{
    BlockSource, CheckedSource, FirehoseConnector, FirehoseSource, FirehoseTarget, FixtureSource,
    Ordering, ReconnectingSource, RetryPolicy, StreamConnector, TransportFailure,
};
pub use store::MemoryStore;
pub use store_state::{StoreEntity, StoreState, StoreValue, STORE_STATE_SCHEMA};
