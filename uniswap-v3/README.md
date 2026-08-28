# Uniswap V3 mainnet and Base

The two target deployments share schema `Qma8a81T…` and now have a complete,
versioned configuration overlay for one shared runtime binary.

| Target | Chain | Factory | Start block | Value signal |
|---|---|---|---:|---:|
| `QmTZ8ejX…` | Ethereum mainnet | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | 12,369,621 | 11.3M queries/day |
| `Qmb4VUcA…` | Base | `0x33128a8fC17869897dcE68Ed026d694621f6FDfD` | 1,371,713 | 2.1M queries/day |

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

The sibling [`graft-ancestry/`](graft-ancestry/README.md) ancestry v2 contract
retains all eight mainnet/Base history segments and reuses the exact immutable
38-object v1 artifact closure. It makes the graft-block ownership rule
executable and numerically binds every registered manifest handler to its raw
WASM function export. The original v1 contracts remain retained history.
Complete artifact lineage does not prove inherited store-state continuity;
boundary continuity remains false, and the historical mapping differences
still forbid replaying the current writer from origin.

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
