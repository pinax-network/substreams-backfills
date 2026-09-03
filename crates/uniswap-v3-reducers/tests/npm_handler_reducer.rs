//! Runs `uniswap-v3/npm-handler-reducer/tests/npm_handler_reducer.rs` unmodified.
//!
//! The harness is itself a test-crate root, so it is included rather than
//! declared as a module: `crate::` inside it has to mean this test binary.
//! `build.rs` stages it, and everything it reaches through `../src/`, into
//! `OUT_DIR` first. See `crates/README.md`.

// The overlay is linted against the pinned 1.79.0 toolchain, which predates
// this lint. Allowed here rather than by editing a pinned source.
#![allow(clippy::unnecessary_map_or)]

include!(concat!(
    env!("OUT_DIR"),
    "/overlay/tests/npm_handler_reducer.rs"
));
