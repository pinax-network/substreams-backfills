# Continuous integration

CI is four workflows under `.github/workflows/`. `ci-core` always runs and is
the status check to require on `main`. The three family workflows always start
too, but on pull requests they run their heavy jobs only when a relevant path
changed; on every push to `main` they run in full. A skipped family job reports
success, so a required family check never sits pending on an unrelated PR while
a PR that touches that family cannot merge with the family job failing.

| Workflow | Jobs | Runs the heavy jobs when the PR touches |
|---|---|---|
| `ci-core.yaml` | `core` | always: `cargo fmt`, `cargo test --workspace --locked`, the BlockChanges v1 golden test, `cargo clippy -D warnings`, `cargo xtask verify-targets` (Rust eligibility library, market-snapshot locks) |
| `ci.yaml` (workflow name `ci`, Uniswap V3) | `changes`, `v3-evidence`, `v3-reference` | `uniswap-v3/**`, `common/**`, `xtask/**`, `Cargo.toml`, `Cargo.lock`, `.cargo/**`, `evidence-assets.lock.json`, `docs/provenance/uniswap-v3*`, `scripts/**`, `requirements-ci.txt`, the workflow file |
| `ci-uniswap-v4.yaml` | `changes`, `uniswap-v4-reference` | `uniswap-v4/**`, `artifacts/**`, `docs/provenance/uniswap-v4*`, `docs/provenance/uniswap-v4*/**`, `scripts/**`, `requirements-ci.txt`, the workflow file |
| `ci-targets.yaml` | `changes`, `target-baselines`, `uniswap-v3-matic-reference`, `uniswap-v2-base-reference`, `pancakeswap-infinity-cl-bsc-reference`, `exchange-v3-bsc-reference` | the seven pinned-family directories, `docs/provenance/**`, `eligibility/**`, `schemas/**`, `scripts/**`, the workflow file |

## Why nothing can evade its checks

- The Uniswap V3 workflow keeps the historical file name `.github/workflows/ci.yaml` and workflow name `ci`: seven retained unittests and the mainnet chain-config parity verifier read that path, and the all-handlers publication seal records that workflow identity. Renaming it would require editing pinned test and verifier files, which #109 must not do.

- `scripts/**` is in every family filter, because the remaining verifiers,
  materializers, and tests live there and shared modules (
  `uniswap_v3_wat_runtime.py`, the test bootstraps) are imported across families.
  `requirements-ci.txt` stays in the Uniswap V3 and V4 filters only; the
  pinned-target workflow is Python-free (`cargo xtask verify-target <family>`).
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
| Evidence assets (`cargo xtask evidence fetch`, unconditional in every job that reads externalized contracts: `v3-evidence`, `v3-reference`, `target-baselines`, `uniswap-v3-matic-reference`) | `evidence-assets-<sha256 of the lock>` | every blob re-hashed before promotion (`docs/evidence-assets.md`) |
| Block fixtures (`cargo xtask evidence fetch --lock uniswap-v3/fixtures/blocks.lock.json`, then `cargo xtask fixtures check`, in `v3-evidence`) | `block-fixtures-<sha256 of the lock>` | same content-addressed verification; release `block-fixtures-v1` (`uniswap-v3/fixtures/README.md`) |
| pip | `requirements-ci.txt` via `actions/setup-python` | `pip install --require-hashes` |

Toolchain pins are unchanged: WABT 1.0.35, Substreams v1.20.3, Rust 1.79 for
the frozen V3 import, Rust 1.90.0 for V4, Go 1.26.5 for the parity client
until #110 ports it, Node 18.18.0 / 24.13.1 / 14.21.3 for the exact deployed
source reproductions.

## Branch protection

Require `ci-core / core`. Optionally also require the three `changes` jobs;
they always complete on pull requests. Do not require `v3-evidence`,
`v3-reference`, `uniswap-v4-reference`, or the target jobs directly: a skipped
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
