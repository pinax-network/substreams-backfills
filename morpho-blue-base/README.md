# morpho-blue-base — `QmWSfh5q…`

Morpho Blue lending on Base. 7 datasources: `MorphoBlue`
`0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` @ 13,977,148, MetaMorpho factories (v1.0/v1.1),
public allocator, etc. Schema `QmWL6kvHgo…`, spec 0.0.5.

- Manifest has NO `repository` field; the source is almost certainly the Morpho org's
  subgraph repo (github.com/morpho-org) — confirm the exact repo + commit before implementing.
- Lending accounting (shares/assets rounding) must match the subgraph's BigDecimal math
  exactly — highest divergence risk of the set; differential verification is non-negotiable.
- The original 3.4M queries/day and 670 GRT figures lacked a retained QoS
  payload timestamp and mixed Gateway query fees with on-chain signal. They
  remain historical intake context only and are intentionally absent from the
  target binding. Recapture exact QoS before making a current market claim.
- The 2026-08-21 intake recorded ordinary Riv/Kan syncing, but live placement
  and progress must be rechecked rather than inferred from that snapshot.
