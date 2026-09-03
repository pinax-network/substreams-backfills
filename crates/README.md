# `crates/` — workspace view of the Uniswap V3 overlay

These crates exist so `cargo test --workspace --locked` at the repository root
compiles and runs the host-only Uniswap V3 reducers. Before them, roughly 14,000
lines of overlay Rust and every one of its tests were reachable only through
`scripts/materialize-uniswap-v3-*.sh`, which build a temporary tree outside the
repository and drive it with `cargo +1.79.0 test`. This is the first slice of
issue #111.

| Crate | What it is |
|---|---|
| `uniswap-v3-overlay-pb` | The protobuf bindings the reducers compile against |
| `uniswap-v3-reducers` | The eight overlay reducers and their five test harnesses |

## Nothing under `uniswap-v3/` changes

The overlay files stay the single source of truth. No file was added, moved, or
edited under `uniswap-v3/` or `scripts/`, so every SHA-256 the overlay sources,
the `contract-v1.json` documents, and the Python verifiers pin stays
authoritative, and `cargo xtask verify-import uniswap-v3` still passes.

Two anti-drift tests hold that claim in place:

- `uniswap-v3-overlay-pb/tests/writer_bindings.rs` hashes the reconstructed
  `uniswap.writer.v1` bindings and compares against the digest
  `uniswap-v3/writer-runtime/contract-v1.json` already records for
  `src/pb/uniswap.writer.v1.rs` in a materialized tree.
- `uniswap-v3-reducers/tests/staging.rs` re-reads both sides of every staged
  file and asserts the copy is byte-exact.

## How the sources are reached

`uniswap.writer.v1` is checked in only as added lines of
`uniswap-v3/writer-runtime/runtime.patch`. `uniswap-v3-overlay-pb/build.rs`
reconstructs the file from that hunk into `OUT_DIR`, which is what applying the
patch does, so there is no second copy to drift. The `npm.source`, `npm.inputs`,
and `npm.plan` bindings are checked in as ordinary files and are `include!`d
where they lie. The module layout is fixed by the generated code, which refers
across packages with `super::` paths.

The reducers and harnesses are written against the directory layout the
materialize scripts build: reducer sources and bindings in `src/`, contract
documents in a sibling `configs/`, harnesses in `tests/`. They cross it with
relative `include_str!("../configs/…")`, `include!("../src/…")` and
`#[path = "../src/…"]`, so they cannot compile where they are checked in —
`uniswap-v3/position-reducer/` has no `configs/` directory, and
`uniswap-v3/npm-observation-plan/src/` has no `npm_handler_reducer.rs`.
`uniswap-v3-reducers/build.rs` performs exactly the copies the scripts perform,
into `OUT_DIR` instead of a temporary tree. The table is `overlay_manifest.rs`,
shared by the build script and the staging test.

One staged byte differs from its overlay, and only in a comment. A harness is
its own crate root, because `crate::` inside it has to mean the test binary, so
this crate reaches it with `include!` rather than a module declaration — and
rustc rejects an inner doc comment arriving through a macro expansion (E0753).
Staging therefore rewrites a harness's leading `//!` block to `//`.
`tests/staging.rs` asserts that is the only difference. Reducer sources keep
their inner doc comments because they are declared as out-of-line modules.

## Lints and toolchain

These crates build on stable, not on the 1.79.0 the materialized overlay pins.
Two lints that postdate 1.79.0 fire on the overlay sources, and both are allowed
at this crate's own declaration sites rather than by editing a pinned source:
`clippy::unnecessary_map_or`, and `dead_code` for the one planner helper that
only a harness calls.

## What this slice does not do

The materialize scripts remain the only supported way to build the WASM runtime
and pack the diagnostic packages, and CI still runs them along with the twelve
Python verifiers. This slice adds host test coverage to the workspace; it
removes nothing. Retiring the scripts, moving the chain-config and
writer-runtime patches into a real runtime crate, and proving WASM digest
equality are the remaining parts of #111.
