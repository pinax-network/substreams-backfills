# Provenance

The generated [`contract.json`](../contract.json) is a deterministic offline
projection from exact retained artifacts. Its implementation base is sealed
local Pool Mint v2 candidate commit
`7fdcdc915ab683c1081df307ef867cfde1f1bebd`, tree
`976d7c858a3f111bd8ca2380ccf12bfdfa6e1ee7`.

## Semantic inputs

Only these inputs provide semantic authority:

| Evidence | Identity | Raw SHA-256 |
|---|---|---|
| Pool Swap core verifier | `scripts/verify-uniswap-v3-pool-swap-core.py` | `097047f6aac55b169c364cc0b4f51a1b4d655f103b77ed6dcc623a5daa3c77f8` |
| Pool Swap core contract | `uniswap-v3-pool-swap-core-semantics/v1` | `5437e87329ae98eaf26e273903e53078a05c068c8be52f19a9673ed41cf4dd8b` |
| Pool Swap fee-growth verifier | `scripts/verify-uniswap-v3-pool-swap-fee-growth.py` | `392fcebecd72abe912af34d256bbc01b42f1ddb4b9b04dab645d6c1669f42932` |
| Pool Swap fee-growth contract | `uniswap-v3-pool-swap-fee-growth-semantics/v1` | `28e12268ebd6ddf78c4d6e59805967793630c6475ca6f0b332fefcf46c5b6b9b` |
| Pool runtime verifier | `scripts/verify-uniswap-v3-pool-runtime.py` | `a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67` |
| Pool runtime contract | `uniswap-v3-pool-runtime/v1` | `66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53` |
| segment-field v2 verifier | `scripts/verify-uniswap-v3-segment-field-semantics-v2.py` | `e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec` |
| segment-field v2 contract | `uniswap-v3/segment-field-semantics/v2` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| direct GraphQL schema | `uniswap-v3/source/schema.graphql` | `f234a0e4dc88c923d6ad28a3fcd1ed6093351bd2221d7c18486f0cbde41bb52c` |

The direct schema is 18,883 bytes. Its 20 entities yield 299 identities: 286
stored and 13 derived. The verifier compares every `(entity, field)` identity,
type, directive, and storage class with the independently recomputed
segment-field catalog. It separately binds Swap's fourteen required fields and
nullable `logIndex`.

The contracts are not trusted as static JSON alone: every digest-pinned
verifier is rerun. The eight Pool WAT contexts are regenerated from retained
WASM with checksum-pinned WABT 1.0.35. The directly recomputed core contract is
also compared byte-for-byte with the fee-growth verifier's core dependency;
runtime and field-catalog dependencies must match both upstream certificates.

## Recomputed closure

The verifier starts at each exact numeric `handleSwap` export and closes all
reachable direct and indirect bodies. The aggregate closure is 1,404 functions,
9,968 calls, 2,368 direct writes, 754 physical map sets, 104 physical stores,
and two indirect calls. Profile-specific function/call/write/map-set/store/
indirect tuples are bound exactly; they are not collapsed into a false common
legacy or modern denominator.

Within every mapping it decodes 197 lexical field invocations, expands four
nullable setter alternatives to 201 site-to-invocation edges, and applies exact
helper fanout to obtain 259 paths. The independent Graph-store ledger yields
19/25, 22/28, or 23/29 lexical/expanded counts by profile while every retained
closure has the same 13 physical targets.

For every invocation, the verifier reconstructs the exact call operands from
the retained WAT stack, follows a named setter's receiver parameter (or a
constructor's internal map-set receiver to the immediately following terminal
`local.get` on normal fallthrough) to the physical `TypedMap#set`, and assigns a
time-scoped local value-origin set at each copy/definition. A finite worklist
propagates those sets through `if`/`else`/`block`/`loop`, every
`br`/`br_if`/`br_table` target, and loop backedges to a fixed point; `return`
and `unreachable` have no fallthrough. It independently decodes each
`store.set` target operand and follows the entity receiver through `#save` to
the physical store value operand. This closes 1,576 exact lexical setter flows,
1,608 physical receiver-flow edges, and 163 exact store target/receiver/value
flows. Direct-store records carry only their exact direct target/value operand
flag; `#save` records carry only the distinct
caller-to-save-parameter-to-store-value transit flag. Misleading deduplicated
schema symbols have no authority.

Setter/store classification uses a separate may-alias relation: lexical order
within the same retained function group plus non-empty intersection of the two
branch-merged receiver origin sets. Across 1,576 invocation classifications,
1,089 reference only equal-origin-set stores and 487 reference overlap-only
stores. The separately counted 1,720 setter-to-store edges comprise 1,233 equal
and 487 overlap-only edges. No classification or edge is represented as a
common execution, branch-correlated witness, or receiver must-alias. Five
legacy-mainnet profiles add 60 helper-return invocation classifications; those
reference 15 materialized stable-ID helper-internal-store → terminal-get →
handler-local authority records. Materialization requires equal store/get
receiver local names and origin sets plus immediate adjacency on normal fallthrough. It does not
prove that all helper invocations or control paths return the stored receiver.

Constructor evidence has the same narrow boundary: the internal map set must
immediately precede a direct terminal `local.get`, and both observations must
have equal receiver origins. Earlier successful returns or other control paths
are not closed, so the certificate does not claim that every constructor result
is the internal map-set receiver.

The generated contract normalizes this evidence: one stable setter-flow record
per lexical invocation and one store-authority record per lexical store, with
coverage, exact setter expansion, and receiver-origin-overlap ordering referring
to authority IDs and canonical full-evidence digests. It intentionally omits an
expanded setter/store relation projection because a setter expansion path does
not correlate a store branch. The verifier still rederives every operand and
flow before emitting those compact ledgers.

Physical and semantic ledgers must not be conflated. The modern duplicate
`PoolHourData` save is bound only by lexical call order and a shared exact
receiver operand local name. It has no common-execution, receiver-must-alias,
visibility, persistence, version, or last-writer interpretation.
The five legacy-mainnet post-store setter groups likewise do not imply
preservation, a common execution with a store, or value meaning.

## Test boundary

Tests reject drift in every scope denominator, all 201 site edges, nullable
alternatives, helper/store multiplicity, profile store shape, duplicate-save
order and receiver operand local name, key/store association, origin-set
equality versus overlap, helper store/return origin-set equality,
the explicit no-common-execution/no-must-alias/no-branch-correlation gates,
guards, schema shape and Swap nullability, category,
no-setter/persistence/last-writer false gates, all 28
diffs, and truth boundaries. Compile-valid WAT mutations exercise retained
authority. Receiver/store mutations first rebind the inherited whole-WAT and
handler digests, so their exact rejection messages come from the local operand,
receiver-flow, store-flow, or receiver-origin-overlap layer rather than an
inherited digest mismatch. A detached copy regenerates `contract.json`
byte-for-byte.

The certificate intentionally leaves value/numeric/import/contract-call
semantics, alias safety, preservation, Graph visibility/persistence/rollback,
post-fatal behavior, historical outcomes, complete histories,
scheduler/runtime/output/Store/package, continuity, parity, checkpoint,
backfill, deployment, production, and readiness false.
