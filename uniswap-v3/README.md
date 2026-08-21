# uniswap-v3 — mainnet + Base (shared schema `Qma8a81T…`)

| Target | Display name | Chain | Factory | startBlock | q/day |
|---|---|---|---|---|---|
| `QmTZ8ejX…` | Uniswap-V3 | mainnet | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | 12,369,621 | 11.3M |
| `Qmb4VUcA…` | Uniswap V3 Base | base | `0x33128a8fC17869897dcE68Ed026d694621f6FDfD` | 1,371,713 | 2.1M |

Datasources: `Factory`, `NonfungiblePositionManager`, `Pool` (template).
Both graft (mainnet's chain reaches 2021) — ordinary deploys never resolve; see repo README.

## References

- Subgraph source: https://github.com/Uniswap/uniswap-v3-subgraph (both manifests' `repository`)
- **StreamingFast `substreams-uniswap-v3`**: https://github.com/streamingfast/substreams-uniswap-v3 —
  the canonical Substreams port of this exact subgraph, built for entity parity with the
  graph-out format. Our module starts as an adaptation of its entity mapping (chain
  parameterized, schema pinned to `Qma8a81T…`), NOT a from-scratch rewrite.
- Differential reference endpoints for verification: the incumbent indexers on each chain
  via the gateway.

## Plan (M2 = base first)

1. `map_entities` emits `EntityChanges` (substreams-entity-change) for the full entity set:
   Factory, Bundle, Pool, Token, Tick, Position, PositionSnapshot, Transaction, Mint, Burn,
   Swap, Collect, Flash, plus Uniswap/Pool/Token Day/Hour aggregates.
2. Engine (`substreams-graph-node-backfill`) loads them into the target schema, lands paused.
3. Differential verify (sampled entities at pinned blocks vs reference) → activate → 200 GRT.
