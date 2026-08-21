# morpho-blue-base — `QmWSfh5q…` (3.4M q/day, ellipfra-only)

Morpho Blue lending on Base. 7 datasources: `MorphoBlue`
`0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` @ 13,977,148, MetaMorpho factories (v1.0/v1.1),
public allocator, etc. Schema `QmWL6kvHgo…`, spec 0.0.5.

- Manifest has NO `repository` field; the source is almost certainly the Morpho org's
  subgraph repo (github.com/morpho-org) — confirm the exact repo + commit before implementing.
- Lending accounting (shares/assets rounding) must match the subgraph's BigDecimal math
  exactly — highest divergence risk of the set; differential verification is non-negotiable.
- Offchain sync also running (riv sgd5284 / kan sgd5307); tiny signal (670 GRT) means
  query-fees-only economics.
