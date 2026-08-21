# exchange-v3-bsc — `QmY67iZD…` (1.9M q/day, ellipfra + one straggler)

PancakeSwap V3 (exchange-v3) on BSC — a Uniswap-V3 fork with fee/protocol tweaks.

- Subgraph source: https://github.com/pancakeswap/pancake-subgraph
- Datasources: `Factory` `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865` @ 26,956,207,
  `NonfungiblePositionManager`, `Pool` template. Schema `QmP9xqULGJ…`, spec 0.0.2
  (oldest in the fleet — verify engine min-spec handling).
- Implementation: fork of the uniswap-v3 family module with PancakeSwap's fee-tier and
  protocol-fee differences applied; offchain sync also running (riv sgd5281 / kan sgd5305).
