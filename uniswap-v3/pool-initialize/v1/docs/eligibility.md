# Eligibility boundary

Pool Initialize semantics v1 is offline evidence only. It neither selects an
execution model nor authorizes a stream, database write, deployment, package,
checkpoint, backfill, or production operation.

## Newly proved scope

The true gates certify only the selected `Pool.handleInitialize` projection:

- the shared retained Pool ABI has exactly
  `Initialize(uint160 sqrtPriceX96, int24 tick)`;
- all eight mapping WASM and WAT identities and exact numeric handler exports
  are pinned;
- every handler loads `Pool` by trigger address and routes the two event values
  to the same loaded entity's `sqrtPrice` and `tick` setters;
- the current mainnet, Base root, and current Base profiles save that same Pool
  after both setters, with that handler call and its generated write proved to
  be the sole reachable Pool persistence path; and
- the five historical mainnet profiles have no direct, dormant, dynamic,
  indirect-unclosed, helper-reachable, or delete-style Pool mutation in the
  recomputed Initialize call closure; the Graph store host-import surface is
  also closed to the exact retained `store.get` and `store.set` pair.

This closes eight upstream
`initialize_persistence_observation.same_path_machine_proven` gaps. Across the
eight segments it produces 16 exact selected-handler field projections and 28
scoped pairwise semantic/provenance diffs. The cumulative selected-field count
is 36 and the cumulative residual count is 230.

## Explicitly ineligible scope

The following remain false and must not be inferred from this supplement:

- complete Pool non-Flash handler semantics;
- Mint, Burn, and Swap formulas, helper effects, contract-call failures, and
  ordering;
- complete histories for `Pool.sqrtPrice`, `Pool.tick`, or any Pool entity;
- combined Factory/NPM/Pool scheduling and dynamic-data-source stages;
- Graph handler rollback and post-fatal execution as retained-WAT facts;
- runtime population and authoritative graft-boundary continuity;
- logical, physical, proof-of-indexing, or GraphQL parity;
- writer/package consumption and checkpoint authority; and
- backfill or production readiness.

Every segment remains `execution_model: undecided` and
`backfill_allowed: false`. This supplement advances the segment writer matrix
and diff evidence, but makes no complete issue-checklist claim.
