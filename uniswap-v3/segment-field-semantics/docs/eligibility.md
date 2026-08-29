# Eligibility boundary

This supplement does not make any segment eligible for backfill. Every segment
continues to carry `execution_model: undecided` and `backfill_allowed: false`.

The true gates certify only the scoped evidence contract: eight segment
records, 28 exact pairwise diffs, 34 selected conditional field effects, 33
required-absent fields, and the selected handlers' call, failure, exclusion,
ordering, and deployed-quirk rules under the host projection.

The remaining blockers are explicit and fail closed:

- exact field semantics for `Factory.handlePoolCreated` and Pool Initialize,
  Swap, Mint, and Burn;
- exact Graph-serialized values for the omitted Position and PositionSnapshot
  link fields;
- full histories for shared `Transaction` and `Pool` fields, including their
  other writers and last-writer order;
- Graph Node dynamic-data-source and cross-component scheduling, plus
  post-fatal continuation, retryable failures, persisted data sources, VID,
  proof-of-indexing, and error streams;
- runtime population, required-nonempty evidence, graft-boundary continuity,
  authoritative oracle comparison, logical and physical parity, target runtime
  identity, writer/package integration, and execution-model selection.

Until those blockers are closed, `backfill_ready`, `production_ready`, all
parity gates, runtime-population gates, and writer-consumption gates must remain
false.
