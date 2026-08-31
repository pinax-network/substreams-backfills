# Provenance

The generated [`contract.json`](../contract.json) is a deterministic offline
projection from exact retained artifacts. Its implementation base is canonical
main commit `796aa3ebd50a56a7b36a588a70fb0aa7fa092818`, tree
`638f8ee61b71111eebeb4a6d7901311e5c9e4018`.

## Semantic inputs

Only these inputs provide semantic authority:

| Evidence | Identity | Raw SHA-256 |
|---|---|---|
| Pool Burn v1 verifier | `scripts/verify-uniswap-v3-pool-burn.py` | `09faaa2e95808ef53b19d3bd1dfddcf5431df4e8d33ac9b0a62dc954888c21e6` |
| Pool Burn v1 contract | `uniswap-v3-pool-burn-semantics/v1` | `54c309fa1e55ad6645f93ceab21b2c579ca55ba9b6a167fa563f1e782eb5d1b7` |
| Pool runtime verifier | `scripts/verify-uniswap-v3-pool-runtime.py` | `a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67` |
| Pool runtime contract | `uniswap-v3-pool-runtime/v1` | `66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53` |
| segment-field v2 verifier | `scripts/verify-uniswap-v3-segment-field-semantics-v2.py` | `e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec` |
| segment-field v2 contract | `uniswap-v3-segment-field-semantics/v2` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| direct GraphQL schema | `uniswap-v3/source/schema.graphql` | `f234a0e4dc88c923d6ad28a3fcd1ed6093351bd2221d7c18486f0cbde41bb52c` |

The direct schema is 18,883 bytes. Its 20 entity definitions produce 299 field
identities: 286 stored and 13 derived. The segment-field catalog uses a
different deterministic record order, so the verifier compares every
`(entity, field)` identity, type, directive, and storage class rather than
promoting order to schema semantics; the order match is recorded as false.

Pool Burn v1, Pool runtime v1, and segment-field v2 are not trusted as static
JSON alone: each verifier is digest-pinned and rerun. The eight Pool WAT
contexts are regenerated from retained WASM using checksum-pinned WABT 1.0.35.
Factory static v2, Pool Initialize v2, and Pool Flash v2 were ordering patterns
only during review; they are neither loaded nor composed as semantic inputs.

## Recomputed closure

The verifier begins at the exact numeric `handleBurn` export for each mapping,
closes all reachable direct and indirect function bodies, and inventories every
direct call, direct memory write, physical `TypedMap#set`, and Graph store.
It then decodes 147 lexical schema-field invocations per mapping, expands the
four nullable branch alternatives to 151 site edges, and applies exact helper
fanout to obtain 195 handler paths. The Graph-store ledger independently
expands 12 physical sites to 17 handler paths.

The eight-map totals are 1,240 reachable functions, 7,084 direct calls, 2,048
direct memory writes, 622 physical `TypedMap#set` sites, 1,176 lexical
invocations, 1,208 site edges, 1,560 expanded setter paths, 96 physical stores,
and 136 expanded store paths. The 124 unique setter-field identities and 12
store targets are recomputed separately for every mapping.

This physical inventory is not a field-semantic oracle. Modern Pool Burn v1
records 147 residual physical setter sites and legacy records 52; those counts
must not be confused with the independent 147 lexical schema-field invocation
denominator. Deduplicated WAT function names are not entity authority.

## Test boundary

Tests reject drift in every scope denominator, lexical/site/expanded ledger,
nullable alternative, helper multiplicity, receiver/key association, store
target, modern guard, schema identity and shape, category, false truth gate,
and recursive diff. Compile-valid WAT mutations exercise retained authority,
and a detached repository copy regenerates `contract.json` byte-for-byte.

The certificate intentionally does not derive imported numeric/comparator or
contract-call meaning, memory alias safety, loaded-field preservation, Graph
store visibility/persistence/rollback, post-fatal behavior, historical branch
outcomes, complete entity histories, scheduler/runtime/output/Store/package,
continuity, parity, checkpoint, backfill, deployment, production, or readiness.
