# Eligibility boundary

Pool Burn TVL semantics v1 is offline evidence only. It does not select an
execution model or authorize a stream, database write, deployment, package,
checkpoint, backfill, or production operation.

## Newly proved scope

The true gates certify only selected retained-WAT call-flow evidence for
`Pool.handleBurn`:

- the shared Pool ABI fixes `amount0: uint256` and `amount1: uint256` at
  indices 4 and 5;
- all eight mapping identities and exact numeric handler exports are pinned;
- every Burn fixture re-runs its generation-specific Pool runtime capsule,
  including EventParam get and TypedMap get/set; legacy additionally binds
  `getEntry` and Value/entry construction; modern binds entry append/array
  growth and allocator identity, while the Burn verifier binds its inline
  BigDecimal Value layout; both capsules bind start state and complete ZERO/ONE
  writer closure;
- the trigger address is passed to the exact modern or legacy `bytesToHex`
  import and its result identifies the loaded Pool; Pool token IDs identify the
  Token entities supplying decimals;
- the handler passes the exact amount and matching decimals through the
  retained conversion flow, then passes old matching TVL and converted amount
  to `BigDecimal.minus` in left-minus-right order;
- the resulting BigDecimal Value, exact selected key, same loaded Pool setter
  receiver, and same loaded Pool save receiver are connected by WAT dataflow on
  the selected-update path;
- both modern mappings skip the entire selected update/save body if either
  Token is absent on a normal-return path; and
- every reachable Burn function body, direct memory-write site, TypedMap-set
  site, Graph store site, and indirect target is inventory-bound, so inventory
  drift is rejected.

Across eight segments this yields 16 selected-handler call-flow evidence records
and 28 scoped pairwise diffs. It does not promote field completeness: the
cumulative selected-field count remains 36 and the cumulative residual count
remains 230.

## Assumptions and false claims

The following are deliberately not promoted:

- `bytesToHex`, BigInt/BigDecimal, and Graph store host semantics are not
  rederived; only their exact imported identities and WAT operand/call flows are
  bound;
- modern imported hosts are assumed not to write arbitrary linear memory;
- legacy imported hosts are assumed not to reenter exported `memory.reset`
  during a handler, and cross-handler allocation freshness remains false;
- the reachable-body inventory is not a general heap-alias proof, so arbitrary
  direct selected-payload alias safety remains false;
- baseline effects outside the two explicit selected setters are not completely
  classified by receiver, key, value, or memory alias. Each modern profile has
  147 residual TypedMap-set sites and 526 residual direct-memory-write sites;
  each legacy profile has 52 and 166. No-later-selected-field-overwrite and
  selected-TVL-persistence gates remain false;
- complete Burn semantics, including tx counts, liquidity, derived pricing,
  Tick effects, and all other entity writes;
- complete Pool Mint, Swap, Flash, aggregate non-Flash, or entity-history
  semantics;
- contract-call result semantics, Graph rollback, or post-fatal execution;
- combined handler ordering, dynamic data-source stages, runtime population,
  graft-boundary continuity, Graph oracle, logical/physical/POI parity,
  writer-package consumption, checkpoint authority, backfill readiness,
  production readiness, or overall readiness.

Every segment remains `execution_model: undecided` and
`backfill_allowed: false`.
