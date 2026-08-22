# Parity: pinax-network/substreams-uniswap-v3 (fork) vs target schema `Qma8a81T…`

Diffed 2026-08-21 (upstream `develop` schema vs the IPFS schema both targets pin).
Upstream: 17 entities. Target: 20. The fork needs FOUR classes of change:

## 1. Field renames (adapter-trivial)
| upstream | target |
|---|---|
| `PoolDayData.totalValueLockedUSD` | `tvlUSD` |
| `PoolHourData.totalValueLockedUSD` | `tvlUSD` |
| `UniswapDayData.totalValueLockedUSD` | `tvlUSD` |
| `TokenDayData.volumeUSDUntracked` | `untrackedVolumeUSD` |
| `TokenHourData.volumeUSDUntracked` | `untrackedVolumeUSD` |

## 2. Drop upstream-extra fields
- `Pool.totalValueLockedETHUntracked`

## 3. Immutability layout differences (ENGINE flag, not module logic)
Upstream emits `Transaction`, `Swap`, `Mint`, `Burn` as `@entity(immutable: true)`
(→ `block$` tables). The TARGET schema declares them **mutable** (→ `block_range`
tables). Data is still append-only; the engine must write mutable-layout rows
(upper-unbounded block_range, standard vids) for these four on this target.

## 4. The one real functional gap: tick aggregates
`TickHourData` + `TickDayData` are **commented out** upstream (never implemented).
Target has both, fully fielded (liquidityGross/Net, feeGrowthOutside{0,1}X128,
volumeToken0/1, volumeUSD, feesUSD). Implement in the fork mirroring the
TokenHourData/TokenDayData aggregation pattern keyed by (tick, period).

## STATUS 2026-08-22 — §1, §2 and §4 are DONE

[pinax-network/substreams-uniswap-v3#1](https://github.com/pinax-network/substreams-uniswap-v3/pull/1)
(branch `qma8a81t-parity`) implements all module-side work. **Schema parity is exact:
20/20 entities, zero field differences** against `Qma8a81T…`, verified programmatically.
Builds clean for `wasm32-unknown-unknown --release`.

- §1 renames — done, output field names only. The same strings also appear in
  `key_last_segment_*` **store-key filters**, which must NOT be renamed (they match keys
  written by the map modules; renaming silently stops the match and emits stale values).
- §2 `Pool.totalValueLockedETHUntracked` — dropped from the create row AND from the Pool
  tvl delta filter. Factory legitimately keeps the field.
- §4 tick aggregates — implemented (`db::tick_windows_create` +
  `db::liquidities_tick_windows`, wired into `graph_out`). `store_ticks_liquidities`
  already wrote `Tick{Day,Hour}Data:{time_id}:{pool}:{tick}:liquidity{Gross,Net}`; only
  the entity emission was missing. Window id = `0x{pool}#{tickIdx}-{time_id}`.
- §3 immutability — unchanged by design: a LOADER concern. The target stores
  Transaction/Swap/Mint/Burn as `block_range` (mutable) tables while this module emits them
  as immutable; the engine must write mutable-layout rows for those four on this target.

### Verification items to pin before any allocation
1. tick-window id format (`0x{pool}#{tickIdx}-{time_id}`) — inferred from this port's own
   `tick.id` convention, not yet confirmed against the subgraph's `intervalUpdates.ts`.
2. zero-volume / zero-feeGrowth tick windows — matches subgraph behaviour as understood;
   confirm against a reference indexer at pinned blocks.

## Remaining order of work (M2 = mainnet `QmTZ8ejX…` — highest QV)
1. ~~Fork builds~~ / ~~§1+§2 renames~~ / ~~§4 tick aggregates~~ — done, PR #1.
2. Run the module against mainnet firehose; spot-check entities vs the gateway at pinned
   blocks (this is where the two verification items above get pinned).
3. Engine run into a riv scratch schema with §3 layout flags; differential verify
   (sampled entities × pinned blocks vs incumbent responses); land paused → activate.
5. Base (`Qmb4VUcA…`) = same spkg, params factory `0x33128a…`, initialBlock 1371713.
6. Matic (`QmWqwrVt…`) = older 2-datasource manifest/schema — re-diff before reuse.
