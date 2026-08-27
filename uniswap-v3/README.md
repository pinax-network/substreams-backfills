# Uniswap V3 mainnet and Base

The two target deployments share schema `Qma8a81T…`, but they do not yet share a
safe runtime configuration.

| Target | Chain | Factory | Start block | Value signal |
|---|---|---|---:|---:|
| `QmTZ8ejX…` | Ethereum mainnet | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | 12,369,621 | 11.3M queries/day |
| `Qmb4VUcA…` | Base | `0x33128a8fC17869897dcE68Ed026d694621f6FDfD` | 1,371,713 | 2.1M queries/day |

## Imported source

`source/` is an exact import of
`pinax-network/substreams-uniswap-v3` PR #1 at commit
`42c7b15345e6df80561b694e52a0eb622b374b96`. Its complete upstream history is
mirrored at `upstream/uniswap-v3-qma8a81t-parity`; it remains an independent
Rust 1.79 project with its own lockfile.

The import proves a narrower claim than a deployable backfill:

- its GraphQL entity, field, and type contract matches the 20-entity target
  schema after ignoring physical `@entity(immutable: true)` directives;
- it builds for `wasm32-unknown-unknown`, and its host-target tests run under
  the pinned toolchain;
- its tick-window output wiring and renamed output/store-key boundaries are
  guarded by an offline contract verifier.

It does **not** prove exact physical history, save ordering, proof of indexing,
GraphQL parity, or Base compatibility. The imported module is hard-coded for
Ethereum mainnet across its factory, position manager, start blocks, wrapped
native token, reference-price pool, stablecoins, and whitelist. A factory-only
parameter is not a valid Base rebind.

See [PARITY.md](PARITY.md) for the evidence boundary and remaining order.

The deployment bindings stay beside the source import:

- `QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7.yaml`
- `Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP.yaml`
