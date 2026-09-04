# `crates/` — workspace view of the Uniswap V3 overlay

These crates exist so `cargo test --workspace --locked` at the repository root
compiles and runs the host-only Uniswap V3 reducers, and so continuous
integration can stage the buildable runtime trees without shell. Before them,
roughly 14,000 lines of overlay Rust and every one of its tests were reachable
only through `scripts/materialize-uniswap-v3-*.sh`, which build a temporary tree
outside the repository and drive it with `cargo +1.79.0 test`. This is issue
#111.

| Crate | What it is |
|---|---|
| `uniswap-v3-overlay-pb` | The protobuf bindings the reducers compile against |
| `uniswap-v3-reducers` | The eight overlay reducers and their five test harnesses |
| `uniswap-v3-runtime` | The materializer that stages every configured runtime tree |

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

## `uniswap-v3-runtime` — staging the buildable trees

`scripts/materialize-uniswap-v3-*.sh` built a runtime tree by piping
`git archive HEAD:uniswap-v3/source` into `tar`, applying one or two
`runtime.patch` files with `patch(1)`, and copying configs, manifests, fixtures
and loose reducer sources over the result. `uniswap-v3-runtime` performs the
same steps from Rust:

- `plan.rs` is one table entry per script, listing its steps in script order.
  It holds paths only, so no pinned byte is duplicated anywhere in the crate.
- `patch.rs` applies the overlay diffs. They are `git diff -U0` output, so the
  recorded line numbers are the whole of the addressing information and every
  hunk is placed exactly. Anything it cannot place exactly is an error, which is
  stricter than the `patch --forward --batch` the scripts ran.
- `lib.rs` runs the steps, and restores the modes `tar -x` would have produced
  by clearing the process umask from what `git archive` recorded. The frozen
  import's one executable file, `build.sh`, is what the import verifiers count.

`cargo xtask materialize-uniswap-v3 <target> <directory>` is the entry point,
and CI calls it wherever it used to call a shell script.

## Byte-identity with the shell scripts

All ten targets were staged both ways and compared, file contents and modes:
every tree is identical. The WASM the configured writer runtime builds is
identical too. Built with the pinned Rust 1.79.0, `--locked`,
`--target wasm32-unknown-unknown --release`, from a tree staged by
`scripts/materialize-uniswap-v3-writer-runtime.sh` and from a tree staged by
`cargo xtask materialize-uniswap-v3 writer-runtime`:

```
f8ab5cb02e5ebf52c8abdc89751c4d7d9a7dad0823a04277f4f56851ab719635  substreams_uniswap_v3.wasm
```

That digest is a property of one machine, not a constant to pin: the release
profile keeps `$HOME/.cargo/registry` paths in 68 panic locations, so a
different home directory yields different bytes. It is invariant under the build
directory, which is why staging the same tree somewhere else reproduces it.
The package name is load-bearing in the other direction — renaming the package
to `uniswap-v3-runtime` changes the digest, because the crate name appears in
the symbol names the WASM name section keeps. The staged package therefore
stays `substreams-uniswap-v3`, as the pinned manifests require, and this crate
is the materializer rather than the runtime package itself.

What holds that claim in place on every run, without the scripts:

- `tests/materialize.rs` stages the writer runtime and checks all fifteen
  per-file SHA-256 digests `uniswap-v3/writer-runtime/contract-v1.json` pins
  for a materialized tree, checks every copied file against the pinned overlay
  it came from, checks untouched files against the frozen import, and checks
  that staging twice is byte-identical.
- CI still builds the WASM from seven independently staged reducer trees and
  `cmp`s each against the writer runtime's.

## What the materialize scripts are still for

They stay in `scripts/`, unreferenced by the workflow files but not dead. The
Python verifiers pin them: `verify-uniswap-v3-npm-source-block.py` records a
`MATERIALIZER_SHA256` and asserts the script's executable mode, and four more
read a script's text to assert it chains to the script below it. Nine retained
unittests under `scripts/tests/` reference them and six run them end to end
through `bash`, and
`scripts/run-uniswap-v3-mainnet-chain-config-parity.sh` calls the chain-config
one. Deleting or editing any of them would mean editing pinned verifier files.
They are also the independent second implementation the byte-identity above was
measured against.
