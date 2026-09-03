//! A workspace view of the host-only Uniswap V3 overlay reducers.
//!
//! Every module here is the unmodified content of one
//! `uniswap-v3/<overlay>/src/*.rs` file. `build.rs` stages those files into the
//! materialized directory layout they expect, and the generated module list it
//! writes alongside them declares each as an out-of-line module. Nothing under
//! `uniswap-v3/` is added to or changed, so the SHA-256 digests the overlay
//! sources, `contract-v1.json` documents, and verifiers pin all stay
//! authoritative. The crate root supplies the same `crate::pb`,
//! `crate::npm_inputs_pb`, and `crate::npm_plan_pb` paths the reducers resolve
//! against once materialized on top of the writer runtime.
//!
//! The reducers are host-only by construction: the overlay patch that declares
//! each one gates it `#[cfg(not(target_arch = "wasm32"))]`, and the generated
//! module list repeats that. This crate is a host-target library and is never
//! built for wasm32; `scripts/materialize-uniswap-v3-*.sh` remain the only
//! supported way to build the WASM runtime. See `crates/README.md`.

pub use substreams_uniswap_v3::pb;
pub use substreams_uniswap_v3::uniswap::npm::inputs::v1 as npm_inputs_pb;
pub use substreams_uniswap_v3::uniswap::npm::plan::v1 as npm_plan_pb;

// position_reducer, flash_reducer, transaction_reducer, npm_source_block,
// npm_handler_reducer, npm_resolved_inputs, npm_observation_plan and
// npm_provider_executor, from `REDUCER_MODULES` in build.rs.
include!(concat!(env!("OUT_DIR"), "/overlay/src/reducers.rs"));
