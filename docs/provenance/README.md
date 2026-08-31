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
indeterminate and fail-closed under the both-cluster 24-hour/72-hour greater-than-28-day
rule.

The
[`uniswap-v4-engine-v0.5.0`](uniswap-v4-engine-v0.5.0/README.md)
directory is a closed, repository-only pre-execution capsule. Its copied JSON
files remain byte-identical to the engine's `v0.5.0` tag; `closure.json`
records the explicit evidence gaps and all-false operational gates.

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
