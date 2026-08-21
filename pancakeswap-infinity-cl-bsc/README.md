# pancakeswap-infinity-cl-bsc — `QmVjXU7y…` (2.6M q/day, ellipfra-only)

PancakeSwap Infinity concentrated-liquidity (v4-style singleton architecture).

- Subgraph source: https://github.com/NgoKimPhu/infinity-cl-subgraph
- Datasources: `PoolManager` `0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b` + `PositionManager`,
  bsc @ 47,214,308 — startBlock is recent (2025), so this one may ALSO be reachable by the
  ordinary offchain sync already running (riv sgd5283 / kan sgd5304); backfill only if the
  sync proves slow. Schema `QmcWb81VRk…`, spec 0.0.4.
- Closest prior art: our own uniswap-v4 module (singleton PoolManager pattern, ../uniswap-v4/).
