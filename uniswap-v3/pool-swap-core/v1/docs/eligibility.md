# Pool Swap core-state eligibility

## Proved

The v1 certificate proves, for all eight retained Pool mappings, the exact
generation-specific call flows for liquidity from parameter 5, tick from
parameter 6, and sqrt price from parameter 4. It binds decoded keys, operand
order, loaded-Pool receiver identity, selected Value/setter flow, the first
Pool-save order, both reachable Pool-save calls, modern required-entity traps,
the modern two-Token guard, and exact reachable mutation and Graph store
inventories.

Modern selected execution requires nonzero Bundle, Factory, and Pool entities,
is skipped for the excluded Pool, and requires both Token loads. Legacy evidence
is limited to the normal-completion path. Deduplicated legacy symbol names are
recorded only as provenance; they do not establish semantics.

## Not eligible

This certificate does not prove complete `handleSwap` semantics, selected-value
persistence, absence of later selected-field overwrites, arbitrary memory alias
safety, Graph rollback, post-fatal execution, complete Pool history, combined
handler or dynamic data-source order, runtime population, continuity, oracle or
parity results, package consumption, checkpoint authority, backfill readiness,
production readiness, or issue completion.

The cumulative ledger therefore remains 36 selected fields and 230 residual
fields. Every segment keeps `execution_model: undecided` and
`backfill_allowed: false`.

## Retarget gate satisfied

This slice is based on exact Pool Mint squash merge
`fa1c8d842712e53d363615062ecf1374e52bb854`. Its contract was regenerated and
the verifier, all 40 focused tests, and the repository-wide suite were rerun.
This satisfies only the source-base retarget gate; every execution and readiness
gate above remains false.
