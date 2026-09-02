# Provenance records

This directory holds immutable, machine-readable records for imported source,
deployment targets, and parity inputs. Verifiers consume the JSON files by
their repository-relative paths and fail closed when a recorded file, digest,
or identity no longer matches.

Update a provenance record only as part of a reviewed source or target change.
Do not rewrite a record merely to match unexpected local output.

`uniswap-v2-base-target.json` pins the exact Uniswap V2 Base IPFS target and a bounded
non-reproducible source search. Its adjacent source note explains why the behavioral source
candidate and generic event decoder are evidence inputs rather than an exact source,
implementation, or readiness claim. M8 orders #87, #89, and #93; M0 eligibility remains
indeterminate and fail-closed until both required clusters are fully accounted for and the
independently selected minimum stable same-pod 24-hour and 72-hour ETAs across all viable
healthy copies both exceed 28 days or are non-converging. The minima may belong to
different copies, and either minimum at or below 28 days stops implementation, compute,
and load. With no viable copy, eligibility requires fresh structural absence proof from
both clusters.

The
[`uniswap-v4-engine-v0.5.0`](uniswap-v4-engine-v0.5.0/README.md)
directory keeps two ranges separate. Its root capsule is the older,
repository-only pre-execution reference whose copied JSON files remain
byte-identical to the engine's `v0.5.0` tag. Its
[`q8/`](uniswap-v4-engine-v0.5.0/q8/README.md) child pins the canonical
prepared q8 manifests, topology contracts, and recovered compact metadata
archive. The q8 closure records that no raw frame digest or payload,
COPY payload, or checkpoint bytes are retained and keeps criterion 2 plus
every operational gate false.

`uniswap-v4-release-assets-v1.json` locks the two historical V4 packages that were release
assets rather than tracked files in the imported source tree. The corresponding bytes live
under `artifacts/releases/uniswap-v4/`; mirroring them does not transfer future-release
authority or make the old releases disposable.

`aerodrome-slipstream-base-target.json` locks the complete deployed IPFS
closure and static target profile for Aerodrome Slipstream CL on Base. Its
manifest repository field is treated as metadata lineage only: no exact public
Slipstream source revision or reproducible build toolchain was found. The
record and verifier therefore keep source, runtime, parity, backfill,
production, readiness, and issue-completion gates false.

[`messari-v3-targets-v1.json`](messari-v3-targets-v1.json) is the combined M9
target contract for PancakeSwap V3 BSC and Uniswap V3 Base. It locks all 26
deployed artifacts, exact manifest/schema/ABI/WASM structure, cross-target
differences, and all-false operational gates. Its ordered top-level `issues`
list is exhaustive for M9; the per-target bindings retain distinct BSC and Base
traceability associations, not independently executable chains. The dependency
DAG is `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared
implementation, and BSC certification precedes Base certification. The accompanying
[`messari-v3-source.md`](messari-v3-source.md) records the nearest pinned source
anchors, matching malformed manifest metadata, unreproducible deleted gluegun
dependency, and the strict source-to-WASM refusal boundary.

## Retired static-certificate verifiers (2026-09-02, #110)

Twenty-nine Uniswap V3 retained-WAT / schema-API certificate verifiers, their
twenty-nine adversarial unittest modules, the shared `uniswap_v3_wat_runtime.py`
analyzer, and its test (60 files, 73,549 lines) were removed from `scripts/`
under the Rust-only policy (#110). Their outputs, the `contract.json` files
under `uniswap-v3/*/v1|v2/`, remain the retained evidence: the sixteen large
ones as immutable release assets and the twelve smaller ones as tracked
in-tree pins, all bound by length and SHA-256 in `evidence-assets.lock.json`
and checked by `cargo xtask evidence check` in every family workflow.

The retired verifier and test sources are preserved verbatim at tag
`static-verifiers-retired-v1`, which points at the last `main` commit that
contained them. Nothing about the certificates' claims changed: every
readiness, parity, backfill, and production gate they recorded as false is
still false, and no #37/#38 checkbox moved. What is gone is only the CI
recomputation of artifact identity that the digest lock now performs at a
fraction of the cost.

Kept because live tooling still imports or runs them: `verify-uniswap-v3-segment-field-semantics.py`
(imported by the NPM provider-executor verifier) and every overlay runtime
verifier (`writer-runtime`, `position-reducer`, `flash-reducer`,
`transaction-reducer`, `npm-*`); those move with #111.
