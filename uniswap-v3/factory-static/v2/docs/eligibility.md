# Factory static v2 eligibility boundary

## What this certificate proves

The certificate proves the complete bounded static contract for
`Factory.handlePoolCreated` across all six unique retained Factory mappings
and all eight ancestry segments:

- all four legacy deployed artifacts reproduce exactly;
- all 44 reachable legacy static `TypedMap#set` sites are classified;
- all 78 expanded legacy handler invocations are classified by exact receiver,
  decoded key, Value kind, payload producer, and call target;
- all 60 schema fields are accounted as 59 written fields plus the required
  absence of `Pool.tick`;
- the legacy allocator/ArrayBuffer, Entity, Value, String, entry-array, and
  TypedMap mutation dependencies close structurally;
- normal-return and explicit trap-prefix effect order remains tied to the
  exact Factory-effects parent; and
- all eight segment projections and 28 pairwise semantic/provenance records
  reproduce.

“Complete static” is path-qualified. The handler has an excluded-pool return,
two null-decimals returns, conditional creation and whitelist branches, and
helpers or imports that can trap. The 78 ledger entries therefore describe
potential lexical paths rather than 78 writes for every event.

## What remains false

The following are deliberately false and fail closed in the contract:

- actual historic call outcomes and runtime population;
- imported host semantics and numeric meaning of
  `bigDecimal.fromString("0")`;
- safety of the legacy static-definition arrays;
- correct ERC20 `totalSupply` return-data decoding;
- Graph store persistence and handler rollback;
- complete Factory or Pool history;
- combined dynamic-data-source execution order and source-package identity;
- graft-boundary continuity, VID/PoI identity, oracle or differential parity;
- backfill, production, and readiness; and
- every acceptance checkbox in issues #37 and #38.

## Hard live-authority blockers

No offline follow-up can promote the operational gates. They require:

1. required-nonempty runtime population and CID/block-bound samples on both
   sides of each graft boundary, including a source that can serve Base's
   pruned history;
2. the exact target Graph Node deployment identity plus entity-count, VID, and
   PoI evidence; and
3. live repaired-versus-legacy parity and release evidence.

Until those authorities exist, `backfill_allowed`, `backfill_ready`,
`production_ready`, and `readiness_complete` remain false.
