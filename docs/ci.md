# Continuous integration

CI is five workflows under `.github/workflows/`. `ci-core` always runs and is
the status check to require on `main`. The four other workflows always start
too, but on pull requests they run their heavy jobs only when a relevant path
changed; on every push to `main` they run in full. A skipped family job reports
success, so a required family check never sits pending on an unrelated PR while
a PR that touches that family cannot merge with the family job failing.

| Workflow | Jobs | Runs the heavy jobs when the PR touches |
|---|---|---|
| `ci-core.yaml` | `core` | always: `cargo fmt`, `cargo test --workspace --locked`, the BlockChanges v1 golden test, `cargo clippy -D warnings`, `cargo xtask verify-targets` (Rust eligibility library, market-snapshot locks) |
| `ci.yaml` (workflow name `ci`, Uniswap V3) | `changes`, `v3-evidence`, `v3-reference` | `uniswap-v3/**`, `common/**`, `xtask/**`, `Cargo.toml`, `Cargo.lock`, `.cargo/**`, `evidence-assets.lock.json`, `docs/provenance/uniswap-v3*`, `scripts/**`, `requirements-ci.txt`, the workflow file |
| `ci-uniswap-v4.yaml` | `changes`, `uniswap-v4-reference` | `uniswap-v4/**`, `artifacts/**`, `docs/provenance/uniswap-v4*`, `docs/provenance/uniswap-v4*/**`, `scripts/**`, `requirements-ci.txt`, the workflow file |
| `ci-mapping-host.yaml` | `changes`, `mapping-host` | `mapping-host/**`, `common/**`, `uniswap-v3/fixtures/blocks.lock.json`, root `Cargo.toml`, the workflow file |
| `ci-targets.yaml` | `changes`, `target-baselines`, `uniswap-v3-matic-reference`, `uniswap-v2-base-reference`, `pancakeswap-infinity-cl-bsc-reference`, `exchange-v3-bsc-reference` | the seven pinned-family directories, `docs/provenance/**`, `eligibility/**`, `schemas/**`, `scripts/**`, the workflow file |

## Why nothing can evade its checks

- The Uniswap V3 workflow keeps the historical file name `.github/workflows/ci.yaml` and workflow name `ci`: seven retained unittests and the mainnet chain-config parity verifier read that path, and the all-handlers publication seal records that workflow identity. Renaming it would require editing pinned test and verifier files, which #109 must not do.

- `scripts/**` is in every family filter, because the remaining verifiers,
  materializers, and tests live there and shared modules (
  `uniswap_v3_wat_runtime.py`, the test bootstraps) are imported across families.
  `requirements-ci.txt` stays in the Uniswap V3 and V4 filters only; the
  pinned-target workflow is Python-free (`cargo xtask verify-target <family>`).
- `mapping-host/` is its own cargo workspace, excluded from the root one
  (`Cargo.toml` `exclude`), because `graph` pulls diesel, libpq and tonic — 577
  crates and about ninety seconds of clean build — which must not slow the
  `cargo test --workspace` in `ci-core`. Its workflow therefore pins its own
  toolchain (1.98.0), installs `libpq-dev` and `protobuf-compiler`, and runs
  `cargo` with `working-directory: mapping-host`. Root `Cargo.toml` is in its
  filter because that is where the exclusion lives, and `common/**` because the
  crate depends on `backfill-common` by path for the BlockChanges v1 contract:
  the canonical validator, codec and merge algebra its frames are sealed with.
- Each workflow lists its own file, so editing a workflow re-runs it.
- Root Cargo files, `common/`, `xtask/`, and the evidence lock are in the V3
  filter because the V3 evidence job builds the workspace and fetches assets
  through `cargo xtask`. `ci-core` builds and tests the workspace on every PR
  regardless.
- Pushes to `main` bypass the gate entirely (`github.event_name != 'pull_request'`),
  so the merged tree is always fully validated even if a filter were too narrow.
- `workflow_dispatch` runs any workflow in full on demand.
- README, `docs/*.md` outside `docs/provenance/`, target bindings, and issue
  templates run only `ci-core`. Those files are read by no verifier.

The `changes` job uses `dorny/paths-filter` pinned to a commit. The heavy jobs
use `if: !cancelled() && (github.event_name != 'pull_request' || needs.changes.outputs.run == 'true')`.

## Caches

Every cache is keyed by the exact content it protects and is re-verified after
restore, so a stale or poisoned cache can only fail, never bypass a check:

| Cache | Key | Re-verification |
|---|---|---|
| WABT 1.0.35 archive | `wabt-1.0.35-<sha256>` | `sha256sum -c` on the archive, `wasm2wat --version` |
| Substreams CLI v1.20.3 archive | `substreams-v1.20.3-<sha256>` | `sha256sum -c` on the archive |
| Cargo registry, git db, and `target/` (root workspace, V4 crates) | `Swatinem/rust-cache` keyed on lockfiles and toolchain | `cargo … --locked` |
| Cargo registry for the frozen Rust 1.79 imports | `hashFiles` of the V3 lockfiles | `cargo … --locked` |
| Evidence assets (`cargo xtask evidence fetch`, unconditional in every job that reads externalized contracts: `core` (the Matic target tests copy two externalized retained contracts), `v3-evidence`, `v3-reference`, `target-baselines`, `uniswap-v3-matic-reference`) | `evidence-assets-<sha256 of the lock>` | every blob re-hashed before promotion (`docs/evidence-assets.md`) |
| Block fixtures (`cargo xtask evidence fetch --lock uniswap-v3/fixtures/blocks.lock.json`, then `cargo xtask fixtures check`, in `v3-evidence` and `mapping-host`) | `block-fixtures-<sha256 of the lock>` | same content-addressed verification; release `block-fixtures-v2` (`uniswap-v3/fixtures/README.md`) |
| Cargo registry, git db, and `target/` for the `mapping-host` workspace | `Swatinem/rust-cache` with `workspaces: mapping-host` | `cargo … --locked`; the git dependencies are pinned by revision in `mapping-host/Cargo.lock` |
| pip | `requirements-ci.txt` via `actions/setup-python` | `pip install --require-hashes` |

Toolchain pins are unchanged: WABT 1.0.35, Substreams v1.20.3, Rust 1.79 for
the frozen V3 import, Rust 1.90.0 for V4, Go 1.26.5 for the parity client
until #110 ports it, Node 18.18.0 / 24.13.1 / 14.21.3 for the exact deployed
source reproductions.

## Branch protection

Require `ci-core / core`. Optionally also require the four `changes` jobs;
they always complete on pull requests. Do not require `v3-evidence`,
`v3-reference`, `uniswap-v4-reference`, `mapping-host`, or the target jobs
directly: a skipped
job counts as success for the workflow but a required job that never ran blocks
the merge. Changing branch protection is an operator action outside this
repository's pull requests.

## Verifier driver

`cargo xtask verify-all [--list] [--family core|targets|uniswap-v3|uniswap-v4] [--keep-going]`
is the single driver for retained checks. Its registry names each check, its
family, its requirements (hydrated evidence blobs), and the exact command;
entries are replaced by native Rust implementations as #110 ports them. The
29 Uniswap V3 static-certificate verifiers and their tests were retired under
#110 (tag `static-verifiers-retired-v1`), which removed 29 steps and about 50
minutes from `v3-evidence`; their contract outputs remain digest-locked.
