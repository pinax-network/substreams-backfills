# Provenance

The generated [`contract.json`](../contract.json) is a deterministic offline
projection from exact retained artifacts. Its implementation base is sealed
local Pool Burn v2 candidate commit
`54bfab587a55a7c81204a166990c03cb659ae113`, tree
`29616314b951850d0a8f5003c819e7e29baf216c`.

## Semantic inputs

Only these inputs provide semantic authority:

| Evidence | Identity | Raw SHA-256 |
|---|---|---|
| Pool Mint v1 verifier | `scripts/verify-uniswap-v3-pool-mint.py` | `a84e24fbff7449ca3ebbe94ef93ee1c6ab2d81ab4b9085c441108f587604be9d` |
| Pool Mint v1 contract | `uniswap-v3-pool-mint-semantics/v1` | `1040c821093b4f5afff3e99df58aa0e4b8021c643226d42dabd1255587fbf14c` |
| Pool runtime verifier | `scripts/verify-uniswap-v3-pool-runtime.py` | `a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67` |
| Pool runtime contract | `uniswap-v3-pool-runtime/v1` | `66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53` |
| segment-field v2 verifier | `scripts/verify-uniswap-v3-segment-field-semantics-v2.py` | `e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec` |
| segment-field v2 contract | `uniswap-v3-segment-field-semantics/v2` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| direct GraphQL schema | `uniswap-v3/source/schema.graphql` | `f234a0e4dc88c923d6ad28a3fcd1ed6093351bd2221d7c18486f0cbde41bb52c` |

The direct schema is 18,883 bytes. Its 20 entities yield 299 field identities:
286 stored and 13 derived. The verifier compares every `(entity, field)`
identity, type, directive, and storage class with the independently recomputed
segment-field catalog. It separately binds Mint's 13 required and three
nullable fields.

Pool Mint v1, Pool runtime v1, and segment-field v2 are not trusted as static
JSON alone: each digest-pinned verifier is rerun. The eight Pool WAT contexts
are regenerated from retained WASM with checksum-pinned WABT 1.0.35. Burn v2,
Flash v2, Factory static v2, and Initialize v2 are ordering references only and
are neither loaded nor composed as semantic inputs.

## Recomputed closure

The verifier starts at each exact numeric `handleMint` export and closes all
reachable direct and indirect function bodies. Each legacy mapping reproduces
182 functions, 914 calls, 166 direct writes, and 65 physical map sets; each
modern mapping reproduces 96, 1,094, 584, and 174. Totals are 1,284 functions,
7,672 calls, 2,164 writes, and 738 physical map sets.

Within that closure it decodes 172 lexical field invocations per mapping,
expands four nullable setter alternatives to 176 site edges, and applies exact
helper fanout—including both `createTick` calls—to obtain 244 handler paths.
The independent Graph-store ledger binds 13 lexical store invocations, 12
physical host sites/targets, and 17 expanded paths. Eight-map totals are 1,376
lexical invocations, 1,408 edges, 1,952 setter paths, 104 lexical stores, 96
physical stores, and 136 expanded stores.

Physical and semantic ledgers must not be conflated. The 65/174 physical map
set counts, 172 lexical invocations, 176 edges, 244 expanded paths, and 142
unique stored fields are separate fail-closed denominators. Deduplicated WAT
symbols are not entity authority; exact caller, receiver, key, and store paths
provide the association.

## Test boundary

Tests reject drift in every denominator, inventory edge, nullable alternative,
helper/store multiplicity, receiver/key/store association, guard, schema shape
and Mint nullability, category, false truth gate, and recursive diff.
Compile-valid WAT mutations exercise retained authority, and a detached copy
regenerates `contract.json` byte-for-byte.

The certificate intentionally leaves value/numeric/import/contract-call
semantics, alias safety, preservation, Graph store visibility/persistence/
rollback, post-fatal behavior, historical outcomes, complete histories,
scheduler/runtime/output/Store/package, continuity, parity, checkpoint,
backfill, deployment, production, and readiness false.
