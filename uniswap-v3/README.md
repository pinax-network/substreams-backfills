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
