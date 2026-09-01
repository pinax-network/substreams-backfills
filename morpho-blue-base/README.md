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

M0 remains monitoring-only. Fresh evidence must fully account for both required
clusters by inventorying every current copy or supplying fresh structural absence
proof. When viable healthy copies exist, independently select the minimum stable
same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all viable copies; the minima
may belong to different copies and must both exceed 28 days or be non-converging
before any backfill work starts. Either minimum at or below 28 days stops
implementation, compute, and load while native Graph Node syncing continues. With
no viable copy, eligibility requires fresh structural absence proof from both
clusters.
