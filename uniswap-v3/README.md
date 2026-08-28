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

The third sibling [`position-reducer/`](position-reducer/README.md) overlay adds
a pure host-only sequential model for Position and PositionSnapshot transitions
after the diagnostic writer contract. It binds all eight segment boundaries and
five NPM profiles, including event-local versus block-fatal rollback, ordinal
Token reads, block-scoped call caching, and graph-node v0.44 decimal precision.
It is excluded from the WASM target, so the writer WASM and 23-module packages
remain byte-identical. It does not implement Transaction entity side effects,
Substreams stores, live calls, `graph_out`, or any promotion gate.

The fourth sibling [`flash-reducer/`](flash-reducer/README.md) overlay models
only the reviewed Pool Flash state transition on the host. Its ordered
PoolCreated/Flash envelope and creation-ordinal membership are diagnostic input
conventions, not Graph Node dynamic-datasource stage order or block-scoped
activation. It makes no same-path or cross-component order claim. The reducer
performs the two exact fee-growth calls sequentially and emits one atomic Pool
update only after both uint256 results decode. Its fatal rollback covers only
diagnostic Pool/membership state, not VID, PoI, persisted data sources, error
streams, or physical transactions. It produces no Flash, Transaction, or
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
