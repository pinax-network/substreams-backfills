# uniswap-v3-matic — `QmWqwrVt…` (5.5M q/day)

Same subgraph source as the mainnet/base pair (https://github.com/Uniswap/uniswap-v3-subgraph)
but an older 2-datasource manifest (`Factory` + `Pool`, no PositionManager) with its own schema —
kept as a separate family until schema diff against `Qma8a81T…` says otherwise.

Factory `0x1F98431c8aD98523631AE4a59f267346ea31F984` @ 22,757,547 (matic).

Context: our only copy (kan sgd3) died disk-full ~34M blocks behind; revival is backfill-only.
Reference implementation: streamingfast/substreams-uniswap-v3 (see ../uniswap-v3/README.md).
