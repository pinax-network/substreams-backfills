# Uniswap V3 mainnet and Base

The two target deployments share schema `Qma8a81T…` and now have a complete,
versioned configuration overlay for one shared runtime binary.

| Target | Chain | Factory | Start block | Value signal |
|---|---|---|---:|---:|
| `QmTZ8ejX…` | Ethereum mainnet | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | 12,369,621 | 11.3M queries/day |
| `Qmb4VUcA…` | Base | `0x33128a8fC17869897dcE68Ed026d694621f6FDfD` | 1,371,679 | 2.1M queries/day |

## Imported source

`source/` is an exact import of
`pinax-network/substreams-uniswap-v3` PR #1 at commit
`42c7b15345e6df80561b694e52a0eb622b374b96`. Its complete upstream history is
mirrored at `upstream/uniswap-v3-qma8a81t-parity`; it remains an independent
Rust 1.79 project with its own lockfile. The machine-readable provenance lock
points to a complete 75-file inventory containing every path, mode, Git blob,
size, and SHA-256 digest.

The import proves a narrower claim than a deployable backfill:

- its GraphQL entity, field, and type contract matches the 20-entity target
  schema after ignoring physical `@entity(immutable: true)` directives;
- it builds for `wasm32-unknown-unknown`, and its host-target tests run under
  the pinned toolchain;
- its tick-window output wiring and renamed output/store-key boundaries are
  guarded by an offline contract verifier;
- four deterministic contract fixtures execute the exact imported
  `TickDayData`/`TickHourData` create and update functions without modifying the
  imported tree;
- CI builds the WASM and inspects an evidence-only package structurally. Its
  environment-dependent bytes are not a production package pin.

The reviewed upstream tree is not `rustfmt`-clean and emits extensive
pre-existing Clippy warnings, primarily in generated ABI/protobuf files. Exact
import verification deliberately preserves those bytes; runnable tests,
logical contracts, the release WASM build, and package structure are the import
gates. Formatting or lint cleanup belongs in a later, explicitly reviewed
change rather than being smuggled into the canonical-source import.

The frozen import itself remains hard-coded for Ethereum mainnet. The sibling
[`chain-config/`](chain-config/README.md) overlay externalizes the complete
audited mainnet/Base contract without changing those source bytes. CI
materializes it separately, tests both pinned configurations, builds one WASM,
and proves the mainnet and Base diagnostic packages embed identical WASM bytes.
A factory-only parameter is still not a valid Base rebind.

The second sibling [`writer-runtime/`](writer-runtime/README.md) overlay adds a
raw, diagnostic-only NonfungiblePositionManager event map after ChainConfig.
It internally selects one of the eight digest-bound ancestry profiles, scans
successful receipt logs directly, and retains all Increase, Decrease, Collect,
and Transfer occurrences in global ordinal order. It also corrects the Base
runtime/Factory origin to 1,371,679 while keeping the direct NPM gate at
1,371,713. The evidence is the QmPW root manifest plus ancestry v2, not an
independent bytecode-creation proof. The new map has no consumer or transitive
path to `graph_out`; all promotion gates remain false.

The standalone [`npm-source-block/`](npm-source-block/README.md) package
composes that exact `map_writer_events` output with the Firehose block in a
second, provider-free WASM. It emits the block hash, parent hash, positive
whole-second timestamp, and gas-limit/gas-price metadata for the successful
transactions referenced by NPM events. Dedicated mainnet and Base manifests
contain exactly `map_writer_events` and `map_npm_source_block`; the original
writer manifests, WASM, 23-module graph, descriptors, and packages remain
byte-identical. The source protobuf carries no provider observations or
unresolved error classes,
and a successful projection is neither checkpoint authority nor Graph block
success. Host execution, provider resolution, Stores, `graph_out`, continuity,
parity, production, and backfill gates all remain outside this tranche and
false.

The third sibling [`position-reducer/`](position-reducer/README.md) overlay adds
a pure host-only sequential model for Position and PositionSnapshot transitions
after the diagnostic writer contract. It binds all eight segment boundaries and
five NPM profiles, including event-local discard versus the final fatal
Position/PositionSnapshot user-entity projection, ordinal Token reads,
block-scoped call caching, and graph-node v0.44 decimal precision. Fatal
outcomes are consumed-event prefixes with omitted counts; they do not model a
Graph execution stop or authorize block/checkpoint success. The reducer binds
the exact execution-order supplement for those limits.
It is excluded from the WASM target, so the writer WASM and 23-module packages
remain byte-identical. It does not implement Transaction entity side effects,
Substreams stores, live calls, `graph_out`, or any promotion gate.

The fourth sibling [`flash-reducer/`](flash-reducer/README.md) overlay models
only the reviewed Pool Flash state transition on the host. Its ordered
PoolCreated/Flash envelope and creation-ordinal membership are diagnostic input
conventions, not Graph Node dynamic-datasource stage order or block-scoped
activation. It makes no same-path or cross-component order claim. The reducer
performs the two exact fee-growth calls sequentially and emits one atomic Pool
update only after both uint256 results decode. Its fatal shortcut returns only
the final Pool user-entity baseline projection; diagnostic membership reset is
not persisted-data-source projection. Outcomes are prefixes with omitted
counts, and no Graph execution-trace or block/checkpoint success claim is made.
It produces no Flash, Transaction, or
aggregate rows and is excluded from the WASM target, so it cannot change either
diagnostic package. It binds the Graph Node v0.44 execution-order supplement,
while all implementation, runtime, continuity, parity, production, and
backfill gates remain false.

The sibling [`graft-ancestry/`](graft-ancestry/README.md) ancestry v2 contract
retains all eight mainnet/Base history segments and reuses the exact immutable
38-object v1 artifact closure. It makes the graft-block ownership rule
executable and numerically binds every registered manifest handler to its raw
WASM function export. The original v1 contracts remain retained history.
Complete artifact lineage does not prove inherited store-state continuity;
boundary continuity remains false, and the historical mapping differences
still forbid replaying the current writer from origin.

The sibling [`segment-writer-matrix/`](segment-writer-matrix/README.md)
contract projects those exact retained artifacts and writer-v3 observations
into eight segment-specific handler/entity/field matrices and all 28 pairwise
artifact, provenance, and reviewed-semantic diffs. It recomputes conservative
writer reachability for all 80 segment handlers, but does not promote named
setter candidates to complete field semantics. No entity is yet certified
required-nonempty, both possible execution models remain ineligible, and all
boundary, oracle, parity, backfill, and production gates stay false.

The sibling [`transaction-reducer/`](transaction-reducer/README.md) overlay is
a host-only, pure reducer for the NonfungiblePositionManager `Transaction`
side effects bound to those exact eight segments. It captures lowercase
transaction identity, unconditional helper overwrites, legacy transaction gas
limit versus current zero `gasUsed`, helper-call counts, normal-return orphans,
final entity-state discard on errors, block error policy, NPM-local event
interleaving, and Position/Snapshot transaction relations. Its ordering,
failure-channel, VID, and PoI caveats bind the sibling
[`execution-order/v1`](execution-order/README.md) supplement rather than
duplicating its Graph Node source evidence. It adds no Substreams module,
store, live call, or `graph_out` path. Pool writers of the shared `Transaction`
entity remain unaudited; new dynamic Pool triggers do not follow a raw global
cross-component log order, and final last-writer, VID, and PoI/error-stream
parity are uncertified. A fatal result is only the final NPM
Transaction/relation user-entity baseline projection plus a consumed-event
prefix and omitted count; it is not a Graph execution stop or block/checkpoint
success authority. Every readiness gate remains false.

The next sibling [`npm-handler-reducer/`](npm-handler-reducer/README.md)
overlay joins the reviewed NPM Transaction, Position, and PositionSnapshot
effects in one host-only event scratch. It derives identity, excluded-pool,
Token, and failure decisions from the same inputs; it does not merge the final
maps of the two standalone reducers. Its ordered diagnostic trace preserves
both identical Transaction saves for a new Position, Transaction-only normal
returns, Position-before-snapshot-helper ordering, handler-atomic nonfatal
discard, and the final persisted NPM user-entity baseline projection after a
fatal handler error. Fatal outcomes are consumed WriterEvents prefixes with an
exact omitted-suffix count; Graph continues outside this reducer, and no modeled
or fatal projection authorizes block/checkpoint success. All eight segments and
five profiles execute in adversarial tests. Flash, Stores, Substreams handlers,
dynamic-data-source stages, Pool Transaction writers, and `graph_out` remain
outside this tranche, and the writer WASM, descriptors, manifests, 23-module
graph, and packages stay byte-identical.

The following sibling [`npm-resolved-inputs/`](npm-resolved-inputs/README.md)
connects the complete validated `NpmSourceBlock` to the joint reducer through a
canonical host-only resolved-observation frame. It embeds the source frame,
binds calls to its exact hash or explicit block-number fallback, and serializes
only Position value/None, pool address (zero included)/None, and Token
Found(u8)/Missing results. A transient Resolved/PossibleReorg/Unknown gate is
not protobuf data; either unstable state aborts before frame construction.
Every supplied row is validated before the reducer runs, including rows after
a would-be fatal reducer prefix. The integrated engine, complete required-read
evaluation, post-fatal Graph execution, continuity, physical/PoI parity,
checkpoint authority, production, and backfill gates remain false. The writer
WASM, descriptors, manifests, module graph, and packages remain unchanged.

The versioned
[`segment-field-semantics/`](segment-field-semantics/README.md) supplement
then binds that joint NPM projection and the Flash projection back to every
retained mapping segment. It completes exact selected-handler rules for 34
conditional stored fields and the static no-writer proof for all 33 stored
fields on `Collect`, `Flash`, and `TickHourData`. Each of the eight segments
retains exact handler-body, export, store-target, profile, call, failure,
exclusion, ordering, gas, and deployed-quirk evidence; all 28 pairwise semantic
and provenance diffs are regenerated recursively. This does not complete the
omitted link fields, Factory or non-Flash Pool handlers, shared-field histories,
Graph execution order, runtime population, oracle/parity work, package wiring,
or backfill eligibility, so every broad gate remains false.

Its immutable
[`v2/`](segment-field-semantics/v2/README.md) supplement expands that boundary
to a complete offline inventory and proof-status ledger: all 299 stored fields,
80 segment handlers, six unique Factory mappings, eight unique Pool mappings,
and all 28 full evidence-surface pairwise diffs. The retained deployed WASM and
checksum-pinned WAT projection remain authority; source anchors are
corroboration only. The bounded retained-WAT analyzer closes exactly four of
the original 18 Factory proof gaps: the excluded-pool equality and early-return
direction for the four legacy binaries. Both modern guard paths, all six
effect-order/argument paths, and all six complete-static-handler paths remain
false. The upstream `totalSupply` models are retained as digest-bound
provenance, but their success/failure value dataflow is not promoted. Pool
calls/failures, Initialize persistence, pricing, fee spacing, hour resaves, and
TickDay relation evidence also remain explicit. V2 therefore leaves 232
conditional fields, full Factory/non-Flash Pool completeness, shared histories,
integrated scheduling, runtime/oracle/parity, package consumption, backfill,
and production gates false. It preserves the v1 and writer-compatibility v3
inputs byte-for-byte.

The additive [`factory-guard/v1`](factory-guard/v1/README.md) supplement then
closes only the two retained modern Factory excluded-pool guard paths. It pins
the exact v2 contract, modern Base/mainnet WASM and WAT, complete guard slices,
and helper bodies. A fresh bounded proof accounts for every structured-control
edge and mutable local, reconstructs the excluded address through its 20-byte
parser loop, and enumerates the length mismatch, twenty first-byte mismatch,
and all-equal return paths. Cumulative Factory closure is therefore six of 18,
with twelve paths still unresolved. Effect order and arguments, dynamic
template identity, rollback, `totalSupply`, complete static/initialized-field
semantics, runtime consumption, continuity, parity, backfill, and production
remain false.

The additive [`pool-initialize/v1/`](pool-initialize/v1/README.md) supplement
then closes the exact selected-handler persistence rule for `Pool.sqrtPrice`
and `Pool.tick`. Across all eight retained Pool mappings it proves the trigger
address-to-Pool load and both event-value/setter receiver flows. Current
mainnet, Base root, and current Base save that same Pool after both setters;
the five historical mainnet profiles have no Pool store anywhere in the
recomputed transitive Initialize call closure. Its adversarial fixtures must
round-trip through checksum-pinned `wat2wasm` before rejection. This raises the
cumulative selected-handler field count from 34 to 36, but Mint/Burn/Swap,
complete Pool histories, runtime/oracle/parity, package consumption, backfill,
and production remain false.

The following additive
[`factory-effects/v1`](factory-effects/v1/README.md) supplement closes only the
six retained Factory effect-order and exact-argument paths. A shared handler-
local CFG, SSA, heap-alias, and effect-trace engine plus a reachable persistent-
effect scan uses separate legacy and modern frontends. Every normal fallthrough
must invoke Pool save, the `Pool` template with `event.pool`, token0 save,
token1 save, and Factory save exactly once in that order; reviewed pre-effect
returns remain empty. Handler-local explicit traps and reviewed save-helper
pre-store trap boundaries may stop only at a prefix; complete interprocedural
trap projection is not claimed. Cumulative Factory closure is twelve of 18.
Graph rollback, `totalSupply`, the six complete-static-handler paths, runtime
consumption, continuity, parity, backfill, and production remain false.

The sibling [`factory-static/v1`](factory-static/v1/README.md) supplement
closes only the two retained modern Base/mainnet complete-static Factory paths.
For each mapping it accounts for all 60 stored-field contracts, continuously
binds every one of the 76 handler map writes through its exact entity receiver,
decoded key, Value kind, semantic payload source, final Value operand, and map
setter. Its complete direct/conservative-indirect closure admits only those 76
sites plus the certified Token-constructor ID write, so a setter hidden in a
reachable helper also fails. Structural certificates bind the collection,
Value-decoder, token-call, static-lookup, entry-local, and complete decimals
dataflows and prove `Pool.tick` absent. The four legacy static paths and every
runtime, continuity, parity, backfill, and production gate remain false.

The
[`factory-fee-growth-init/v1`](factory-fee-growth-init/v1/README.md)
certificate then isolates the two legacy Factory initialization setters for
`Pool.feeGrowthGlobal0X128` and `Pool.feeGrowthGlobal1X128`. It binds the
event-pool receiver, the native-start `$g2` pointer returned by
`ByteArray.fromI32(0)`, exact Value and
setter operands, uninterrupted same-receiver path, Pool-save ID/kind branches,
and complete reachable residual inventories for four unique legacy mappings.
Those proofs project to six legacy segments and compose with the recomputed
modern parent for 16 initialization records. This does not close the four
legacy complete-static paths or promote persistence, history, host/reset
semantics, parity, backfill, production, or readiness. Its base is the exact
canonical PR #71 squash merge `cf4d096304c09f150a7ee2ea85de5d479d5ec7ef`;
that merge tree matches the independently audited candidate tree.

The
[`factory-pool-bigint-init/v1`](factory-pool-bigint-init/v1/README.md)
certificate adds bounded legacy initialization call-flow evidence for
`Pool.liquidityProviderCount`, `Pool.txCount`, `Pool.liquidity`,
`Pool.sqrtPrice`, and `Pool.observationIndex`. Four writes are direct; the
`txCount` flow is one selected Pool invocation of a four-use linker-shared
helper. The helper's static set site remains residual. Six legacy and two
modern segments produce 40 records and 28 scoped pairwise diffs. After
composition, six direct sites are fully selected out of 44 reachable static
sites, and seven of 78 expanded invocations are selected; 38 static sites and
71 invocations remain residual.
The field ledger remains 36/230 and Factory closure remains 14/18. Mutation,
persistence, complete history, host/store semantics, parity, backfill,
production, and readiness remain false. Its exact base is canonical PR #72
squash merge `982dd6f049af265cfed4c7b8edce1a90c936f319`.

The sibling [`pool-runtime/v1`](pool-runtime/v1/README.md) supplement closes a
runtime-only structural capsule for all eight retained Pool artifacts. It
keeps separate modern exported-initializer and legacy native-start proofs. The
modern capsule binds its 77-line inline `TypedMap#set`, Entity and allocator
dependencies; the legacy capsule binds its arena/ArrayBuffer, EventParam,
Value, String, TypedMap/entry-array, native module-state, and allocator-floor
dependencies across four exact digest groups. Legacy `memory.reset` is
host-exported, so freshness is only intra-handler under an explicit
non-reentrant-host assumption. Every Pool handler, entity history, host and
low-level general semantics, cross-handler freshness, continuity,
oracle/parity, checkpoint, backfill, production, and readiness gate remains
false.

The additive [`pool-burn/v1`](pool-burn/v1/README.md) supplement then binds
`Pool.handleBurn` call-flow evidence for `Pool.totalValueLockedToken0` and
`Pool.totalValueLockedToken1` across all eight retained Pool mappings. Each
exact current WAT fixture re-runs the public modern or legacy Pool runtime
capsule before the Burn-specific verifier binds the trigger-address Pool
identity, ABI indices 4/5, matching Token decimals, decimal conversion,
old-minus-amount operands, explicit selected setters, and the same Pool save on
the selected-update path. Every reachable function body, direct memory-write
site, TypedMap set site, Graph store site, and indirect target is inventory-bound.
Baseline dynamic-key, receiver, value, and memory-alias effects are not
semantically closed, so selected-TVL persistence and field completeness remain
false alongside complete Pool history, parity, checkpoint, backfill, production,
and readiness.

The additive [`pool-mint/v1`](pool-mint/v1/README.md) supplement stacks on the
digest-pinned Burn contract while independently re-running each same-WAT Pool
runtime capsule. It binds the trigger-address Pool identity, Mint ABI indices
5/6, matching Token decimals, conversion and old-plus-amount operand order,
modern missing-entity trap dominance, intra-handler wrapper/Value freshness,
the two explicit selected setters, Pool/Mint save ordering, and exact reachable
effect inventories. Baseline receiver/key/value and direct-memory aliases remain
unclassified, so persistence, no-later-overwrite, field completeness, Pool
history, parity, checkpoint, backfill, production, and readiness stay false.

The [`pool-swap-core/v1`](pool-swap-core/v1/README.md) supplement
then digest-pins Mint plus the canonical Pool runtime and Initialize capsules.
Across all eight retained Pool mappings it binds `handleSwap` liquidity, tick,
and sqrtPrice assignments from ABI parameters 5, 6, and 4, exact decoded keys,
selected loaded-Pool receiver identity, modern required-entity traps and the
two-Token guard, the first Pool-save order, the second reachable Pool save, and
complete reachable mutation/store inventories. Legacy semantics come only from
decoded operands, keys, and call flow—not misleading deduplicated symbols.
Complete Swap, persistence, no-later-overwrite, alias, rollback, history,
parity, checkpoint, backfill, production, and readiness remain false. The slice
is based on exact Pool Mint squash merge `fa1c8d842712e53d363615062ecf1374e52bb854`.

The [`pool-flash/v1`](pool-flash/v1/README.md) certificate then
digest-pins and recomputes Swap plus Mint, Pool runtime, Initialize,
field-semantics v2, and the segment writer matrix. Across all eight retained
Pool mappings it proves the exact `feeGrowthGlobal0X128` non-try call,
result-zero BigInt decode, `feeGrowthGlobal1X128` non-try call, result-zero
BigInt decode, matching fee0 setter, fee1 setter, and same-receiver Pool save
order, plus null-result closed traps and exact reachable mutation and Pool-only
Graph store inventories. It
independently derives selectors `f3058399` and `46141319` and retains `Flash` as
a required-absent row. The candidate still disables Flash output; host call
semantics, persistence, complete history, parity, backfill, production, and
readiness remain false, and the ledger stays 36 selected / 230 residual. This
slice is based on exact canonical Pool Swap squash merge
`71d554fa9676d8c77437c0366a9859e13834e235`, with its merge tree verified
identical to the audited candidate before deterministic regeneration and full
revalidation.

The [`pool-swap-fee-growth/v1`](pool-swap-fee-growth/v1/README.md) certificate
reuses the audited Flash call model inside the full `handleSwap` body. It binds
the event-address Pool contract, ordered `feeGrowthGlobal0X128` and
`feeGrowthGlobal1X128` empty-argument calls, result-zero BigInt decodes,
uncrossed same-Pool setters, and the same-receiver second Pool save. Modern
required traps and the two-Token guard, legacy decoded helper operands, null
and invalid-kind traps, exact selected slices, and the full 13-target Swap
effect inventory are fail-closed. Persistence, later dynamic aliases, complete
Swap and Pool history, legacy Factory initialization, host semantics, parity,
backfill, production, and readiness remain false; the ledger stays 36 selected
/ 230 residual. Its exact canonical Flash base is PR #70 squash merge
`27dc439b150bbade46b6552d9e8611bc3c00da6f`, whose tree matches the
independently audited candidate tree.

The next sibling [`npm-observation-plan/`](npm-observation-plan/README.md)
closes the repository-only host request set before joint reduction. It first
enumerates every unique Position key from the complete event envelope, then,
after all Position rows resolve, derives Pool and ordinal-scoped Token keys
from the immutable block-start Position projection and the exact segment
profile. The plan includes the suffix after a would-be fatal reducer prefix;
sorted keys, reason masks, contributing ordinals, exact cached-key consumption
maxima, source digest, and planning-state digest are canonical. A gated call
scope must resolve before planning. Preflight requires exact equality between
planned and resolved key sets, rejects unstable rows before reduction, and
audits actual reducer consumption against the exact maxima. Provider failures
and resolution status are never serialized. This adds no integrated executor,
RPC, database, Graph call trace, Factory/Pool combined schedule, dynamic-stage
or BlockChanges model, checkpoint authority, continuity, parity, backfill, or
production gate. Writer code, manifests, descriptors, WASM, and packages stay
unchanged.

The sibling [`oracle/`](oracle/README.md) contract retains deployment-scoped
current-head responses and the asymmetric graft-boundary discovery result:
mainnet history was queryable without canonical block hashes, while Base
history was pruned. It is discovery evidence only; all authoritative parity and
production gates remain false.

This does **not** yet prove fixed-range mainnet output parity, Base Firehose and
authoritative-reference parity, exact physical history, save ordering, proof of
indexing, GraphQL parity, or a controlled production package pin.

See [PARITY.md](PARITY.md) for the evidence boundary and remaining order.

The deployment bindings stay beside the source import:

- `QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7.yaml`
- `Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP.yaml`
