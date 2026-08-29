# Eligibility boundary

Segment field-semantics v2 is offline evidence only. It does not make any
segment eligible for backfill, and every segment remains
`execution_model: undecided` with `backfill_allowed: false`.

The true gates certify only exact static facts:

- retained deployed WASM was recomputed through the pinned WAT projection;
- all 20 entities, 299 fields, eight segments, 80 handlers, six Factory
  mappings, eight Pool mappings, and 28 evidence-surface pairs are present;
- source artifacts are bound by raw bytes and remain non-authoritative
  corroboration;
- the immutable v1 67-field certification is preserved, including the full
  required-absence closure for `Collect`, `Flash`, and `TickHourData`; and
- the four legacy Factory mappings prove the excluded-pool equality and
  non-inverted early-return path; and
- exactly four of the original 18 Factory proof gaps are closed, while both
  modern guard paths, all six effect-order/argument paths, all six
  complete-static-handler paths, and all remaining 232 conditional fields stay
  fail-closed.

The following evidence does not yet exist and must not be inferred:

- both modern excluded-pool guard paths, whose mutable-local and
  structured-control dataflow requires a more general analyzer;
- same-path dominance, exact entity arguments, dynamic-template identity, and
  rollback for the reviewed Factory effect order in all six mappings;
- complete Factory initialized-field values and all symbol/name/decimals,
  `totalSupply`, success, revert, bytes32, null-sentinel, and static-definition
  branches; upstream `totalSupply` models remain provenance rather than a v2
  success/failure dataflow proof;
- Factory handler rollback as a retained-WAT fact: the upstream profile records
  lexical calls and reviewed order, while v2 does not prove same-path suffix
  execution or atomic rollback; the latter remains bound to the pinned Graph
  Node source model;
- complete Initialize/Mint/Burn/Swap value formulas, direct-call failure paths,
  helper side effects, and handler rollback across all eight Pool profiles;
- uniform proof for Initialize persistence, Swap TickDay relation values, hour
  resave reachability, pricing/static profiles, and every fee-spacing branch;
- exact deployed Graph serialization of `Position.pool`, `Position.token0`,
  `Position.token1`, `Position.tickLower`, `Position.tickUpper`, and
  `PositionSnapshot.pool`;
- complete shared `Transaction` and `Pool` contributions and last-writer order;
- breadth-first Graph Node dynamic-data-source stages, post-fatal trigger
  continuation, retryable failures, persisted data sources, VID, PoI, and
  deterministic-error streams; and
- runtime population, boundary continuity, authoritative oracle comparison,
  logical/physical/PoI parity, target runtime identity, writer/package
  consumption, checkpoint authority, and production operation.

Accordingly, full Factory/Pool completion, combined-schedule,
runtime/oracle/parity, `backfill_ready`, and `production_ready` gates remain
strictly false.
