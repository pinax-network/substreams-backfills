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

## Order of work (M2 = mainnet `QmTZ8ejX…` first — highest QV)
1. Fork builds + runs as-is against mainnet firehose; spot-check upstream entities
   vs the gateway at pinned blocks (pre-adaptation baseline).
2. Apply §1/§2 renames in the fork's graph_out.
3. Implement §4 tick aggregates.
4. Engine run into a riv scratch schema with §3 layout flags; differential verify
   (sampled entities × pinned blocks vs incumbent responses); land paused → activate.
5. Base (`Qmb4VUcA…`) = same spkg, params factory `0x33128a…`, initialBlock 1371713.
6. Matic (`QmWqwrVt…`) = older 2-datasource manifest/schema — re-diff before reuse.
