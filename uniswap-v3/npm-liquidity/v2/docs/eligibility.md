# NPM Liquidity v2 eligibility

## Publishable claim

This paired certificate is independently publishable as two complete,
path-qualified static retained-WAT/schema-API effect matrices for
`handleIncreaseLiquidity` and `handleDecreaseLiquidity`, plus a derived set
union. It covers eight retained ancestry bindings and six unique NPM WASMs.

The narrow completion includes:

- exact direct contract, verifier, schema and retained-WASM roots;
- direct WABT 1.0.35 regeneration of all six WAT artifacts;
- separate Increase and Decrease reachable function, call, target, memory
  write, generic/named setter, store get/set/remove, unset, Ethereum call,
  indirect-table, abort and unreachable inventories;
- separate 43-invocation lexical ledgers and 26/48 maximum accepted-path
  expansions for each handler;
- a 46-site physical/lexical set union, explicitly not a sequential path;
- existing/new Position, first try-call revert, non-try Factory fatal,
  excluded pool, legacy Token-load fatal, current Token-null return,
  current Decrease null-liquidity fatal, fee-refresh revert and trap prefixes;
- old-codegen, modern and absent historical block-guard profiles;
- exact Position, PositionSnapshot and Transaction setter/save order, including
  the single unconditional-write store order for each accepted path;
- all 38 stored field authorities, nine relation/Transaction receiver-key
  paths and the 33-field required-absence overlay;
- 299 outcomes per handler and segment, a derived 299-outcome union per
  segment, 28 cross-segment axes carrying handler and union diffs, and eight
  within-segment Increase-versus-Decrease diffs.

## Fail-closed boundary

The following remain false:

- imported getter, numeric, arithmetic, decimal, string, address and alias
  semantics, including the meaning of plus/minus and legacy Params symbols;
- contract-call return values, temporal meaning and complete error classes;
- Graph store read contents, ordinal visibility, same-handler visibility,
  persistence, rollback, post-fatal behavior, VID and PoI;
- any claim that a no-setter field is preserved, unchanged, stable or
  persisted;
- complete Position, PositionSnapshot or Transaction history, relation
  persistence, shared Transaction last-writer behavior or cross-handler
  ordering;
- sequential composition of Increase and Decrease or an aggregate paired
  maximum execution path;
- required-nonempty or runtime population, package identity, scheduler,
  output, writer-package consumption or checkpoint authority;
- Graph oracle, graft continuity, logical/physical/PoI parity, backfill,
  deployment, production or readiness;
- completion of an issue #37 or #38 criterion or checkbox.

## Transaction and store caveat

A new Position path invokes loadTransaction during construction and again
during Snapshot construction. Each read is classified independently as a store
hit or miss because the static retained WAT does not prove that the first
invocation's store is visible to the second invocation's read. A hit performs
four common field effects; a miss adds id. Both completed branches then save
Transaction. Consequently the accepted existing store order is
`Position, Transaction, PositionSnapshot`, and the accepted new order is
`Transaction, Position, Transaction, PositionSnapshot`. These are static call
orders, not persistence or rollback claims.

API 0.0.4 routes the event gas-limit getter result to the gasUsed setter. API
0.0.7 routes the result of `BigInt.fromI32(0)`. Only those structural sources
are certified; numeric equality or runtime contents are not.

## Paired-union caveat

The paired union answers which sites and field authorities are present in
either independently certified handler. It does not say that the handlers run
in any order, share visible state, both occur, or form one execution trace. The
4,784/528 independent totals are the acceptance denominator; the 2,392/264
union totals are a derived projection and are reported separately.

## Issue effect

This adds the final paired offline NPM liquidity-handler matrices to the
prospective writer-provenance inventory. It does not complete #37 runtime
fixtures, ordinal application, interleaving, package identity or parity work.
It also does not by itself complete #38's full cross-handler matrix or execute
its acceptance suite, so no checkbox is changed.
