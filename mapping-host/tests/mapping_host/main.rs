//! Every integration test, in one binary.
//!
//! Cargo builds one test executable per file directly under `tests/`, and each
//! one statically links this crate's whole dependency tree — `graph`,
//! `graph-chain-ethereum`, `graph-runtime-wasm` and wasmtime beneath them, 577
//! crates. At six files that was six ~140 MB links per `cargo test`, which a
//! GitHub-hosted runner does not survive: the linker died with a bus error
//! partway through the last one.
//!
//! So the suites are modules of a single target instead. Nothing about the
//! tests changed — every function, its assertions and its name are as they
//! were, and each file still owns its own fixtures and helpers. The only
//! visible difference is that a test now reports as
//! `<suite>::<name>` rather than `<name>`, because it lives in a module.
//!
//! Each suite is documented at the top of its own file:
//!
//! * `block_changes_qme66zn` — canonical `BlockChanges` frames and their goldens
//! * `block_source` — ordering, gap and fork refusals over a fake block source
//! * `checkpoint_resume` — `--checkpoint-out`/`--checkpoint-in`, and the proof
//!   that a chunked replay equals an uninterrupted one
//! * `live_cli` — the CLI's live-mode refusals, all of which stop before a socket
//! * `long_run` — `--checkpoint-every`, `--continue-outputs` and the
//!   reconnecting source: what a replay too long for one process or one
//!   connection recovers from, and what it refuses
//! * `parity_window_evidence` — the committed 1,053-block run summary
//! * `segment_aerodrome` — the Aerodrome Slipstream Base bundle, its identity
//!   and descriptor, and two real Base blocks from its locked fixtures: one
//!   compared with the live run's frame, one pinning the non-fatal path
//! * `aerodrome_root_window_evidence` — the committed Aerodrome root-window run
//!   summaries, re-derived from their locked reports
//! * `segment_qme66zn` — the segment bundle, wave scheduling and handler groups
//! * `store_state_qme66zn` — `--store-out`, the final store a consumer is
//!   compared against
//!
//! Adding another file here costs nothing; adding another file to `tests/`
//! costs another full link, so put new suites in `tests/mapping_host/`.

mod aerodrome_root_window_evidence;
mod block_changes_qme66zn;
mod block_source;
mod checkpoint_resume;
mod dynamic_sources;
mod live_cli;
mod long_run;
mod parity_window_evidence;
mod segment_aerodrome;
mod segment_qme66zn;
mod source_chunks;
mod store_state_qme66zn;
