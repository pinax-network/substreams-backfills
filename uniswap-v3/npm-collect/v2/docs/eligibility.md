# NPM Collect v2 eligibility

## Publishable claim

The certificate is independently publishable as a complete path-qualified
static retained-WAT/schema-API effect matrix for
`NonfungiblePositionManager.handleCollect` across eight ancestry bindings and
six unique NPM WASMs.

It is eligible because every direct retained input is digest-bound, all six
WASMs are regenerated with WABT 1.0.35, the entire reachable closure is
enumerated, all fixed and indirect targets are closed, each of the 299 schema
fields receives exactly one outcome per segment, and all 28 segment pairs have
recursive semantic and provenance diffs.

The narrow completion includes:

- all reachable functions, calls, memory writes, generic and named setters,
  store reads/writes/removes, unsets, contract calls and trap sites;
- exact handler and helper bodies, normalized bodies, instruction shapes and
  call sequences;
- profile-specific collected-fee setter keys and Token branches;
- existing/new, first-call revert, non-try fatal, excluded-pool, legacy missing-
  token, current token-null, fee-refresh revert and schema trap prefixes;
- all 38 Position, PositionSnapshot and Transaction stored field authorities;
- structural proof in all six retained helpers that Transaction ID is miss-only
  while four common setters and the Transaction save are on both hit and miss;
- nine relation/Transaction receiver, key, source and save paths;
- required absence of Collect, Flash and TickHourData fields in this closure.

## Ineligible claims

The following remain false and must fail closed if promoted:

- imported getter values, arithmetic, decimal conversion, formatting, address
  conversion and arbitrary alias semantics;
- contract-call returned values, block-pointer timing and error classification;
- Graph store read contents, same-handler visibility, event-ordinal behavior,
  persistence, rollback, post-fatal effects, VID and PoI;
- claims that a field without a path-local setter is preserved, unchanged,
  value-stable or persisted;
- complete Position, PositionSnapshot or Transaction histories and shared
  Transaction last-writer behavior;
- required-nonempty or runtime population certification;
- event interleaving, cumulative runtime behavior, package identity, scheduler,
  output or writer-package consumption;
- Graph oracle, graft-boundary continuity, logical/physical/PoI parity,
  checkpoint authority, backfill, deployment, production or readiness;
- completion of any issue #37 or #38 acceptance criterion or checkbox.

## Transaction caveat

The new Position route calls `loadTransaction` before returning from
`getPosition` and again while building the Snapshot. Each helper read has an
independently classified store-hit/store-miss result. The result changes only
the ID effect: a successful hit has the four common Transaction field effects,
while a successful miss first adds ID. Both successful paths then execute the
same Transaction save. Thus accepted existing and new paths have fixed store
orders, even though their field-effect counts differ by the number of misses.

The static WAT does not prove whether the first Transaction save is visible to
the second read, whether either save persists, or how rollback behaves. It also
does not give setter paths to the five derived Transaction fields (`mints`,
`burns`, `swaps`, `flashed`, and `collects`): only the five classified stored
Transaction identities have paths.

API 0.0.4 structurally routes the transaction gas-limit getter result to the
gasUsed setter. API 0.0.7 routes the result of `BigInt.fromI32(0)`. This is only
a source-call split, not a numeric-value conclusion.

## Issue effect

This slice adds one complete offline handler-by-segment matrix. It does not
complete the full multi-handler writer inventory or execution model in #38.
For #37, Increase, Decrease and Pool Flash work still remains, as do ordinal
application, cumulative/interleaved runtime fixtures, package identity and
baseline comparison. The required-absence checkbox was already complete and is
not re-checked here.
