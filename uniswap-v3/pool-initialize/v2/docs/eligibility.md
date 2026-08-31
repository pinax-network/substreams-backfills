# Eligibility boundary

Pool Initialize v2 is offline, path-qualified static evidence. It authorizes no
stream, deployment, database mutation, package, checkpoint, backfill, or
production operation.

## Newly true

The certificate proves only that, for all eight exact retained mapping modules:

- the complete reachable WAT body and call closure is digest-bound;
- all reachable setter, save, fixed store-target, helper, remove, direct-write,
  and closed indirect-target sites are accounted for;
- the exact three-save/five-no-Pool-save profile split is preserved;
- the Pool-save call presence or absence, both subsequent helper calls, and each
  helper's exact Pool `store.get` path are bound without promoting the returned
  store version;
- missing-row high/low setters, separate comparator-return-controlled setters,
  and the exact `BigInt#plus` result write are structurally bound without
  assigning imported numeric meaning;
- all 20 catalog fields for each interval entity are classified as 19 non-null
  fields plus nullable `tick`, including its non-null and null/unset branches;
- all Bundle, Pool, PoolDayData, PoolHourData, and Token stored writes,
  preservation rules, and `@derivedFrom` no-direct-store outcomes have
  path-qualified static ledgers;
- every one of 299 schema fields has one outcome in each segment, for 2,392
  outcomes total; and
- all 28 pairwise recursive semantic/provenance diffs are present.

The verifier binds only handler/helper call order: three profiles invoke
`Pool.save` before both interval helpers, five have no reachable Pool save, and
each helper subsequently reaches an exact Pool `store.get`. It does not prove
which Pool version that read returns. Graph store read-after-write, persistence,
and host semantics remain false, so no stored-version visibility is claimed.
Modern Token transitions are conditional on both Token
loads; the legacy claim is limited to the successful non-null path.
Creating a missing interval child can conditionally extend the derived
`Pool.poolDayData` or `Pool.poolHourData` query collection even though neither
derived field is directly serialized in a Pool save.

For each day and hour entity, all 20 catalog fields have classified effects:
19 fields are non-null and `tick` is nullable, with exact generated non-null and
null/unset setter branches. Missing-row creation writes both high and low;
separate later setters are controlled only by exact comparator return shapes.
The imported comparator meaning is not proved. Likewise, the certificate binds
the write of the result of
`BigInt#plus(existing-or-zero txCount, ONE_BI)`; imported BigInt numeric
semantics are unproved.

## Required false gates

The generated truth boundary keeps each of these false:

- `imported_numeric_semantics_complete`
- `imported_big_decimal_comparator_semantics_complete`
- `imported_big_int_plus_numeric_semantics_complete`
- `graph_store_host_semantics_complete`
- `window_helper_pool_store_get_return_visibility_or_version_proven`
- `imported_graph_store_read_after_write_semantics_complete`
- `graph_store_persistence_complete`
- `graph_handler_rollback_proven`
- `actual_historic_handler_outcomes_bound`
- every complete Bundle, Pool, Token, and interval entity-history gate
- `all_manifest_handler_field_semantics_complete`
- integrated handler and dynamic-data-source ordering
- `runtime_population_complete`
- `boundary_continuity_complete`
- `graph_oracle_complete`
- `logical_parity_complete`
- `physical_parity_complete`
- `poi_parity_complete`
- writer-package consumption and checkpoint authority
- `backfill_ready`
- `production_ready`
- `issue_37_acceptance_criterion_complete`
- `issue_38_acceptance_criterion_complete`
- `all_twenty_interval_fields_non_null_or_required`

Accordingly, this slice completes no checkbox in issue #37 or issue #38.
Every segment remains `execution_model: undecided` and
`backfill_allowed: false`.
