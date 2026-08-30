# Pool Flash eligibility

## Proved

For all eight retained Pool mappings, the v1 certificate proves the exact
generation-specific `handleFlash` flow from the trigger-address Pool load and
contract bind through the fee0 non-try call, result-zero decode, fee1 non-try
call, result-zero decode, fee0 setter, fee1 setter, and one same-receiver Pool
save, in that exact order.

The two signatures derive selectors `f3058399` and `46141319`. Modern required
Pool absence is a closed trap. Both call-null paths are closed
abort-and-`unreachable` branches in the shared call helper. Every reachable
mutation and Graph store site is inventory-bound, the exact Graph store target
set is only `Pool`, and the segment writer matrix retains `Flash` as
required-absent with no synthesized row.

The upstream segment-field ledger already selected both fields. This
certificate strengthens their same-path and effect-closure evidence without
adding a field, so the cumulative ledger remains 36 selected and 230 residual.

## Not eligible

This certificate does not implement candidate Flash extraction, RPC calls, or
`graph_out` output. It does not prove imported host call values, block-pointer
selection, error classification, Graph store semantics, rollback, post-fatal
execution, selected-value persistence, absence of later overwrites, general
heap alias safety, complete `handleFlash`, complete Pool history, combined
handler or dynamic data-source order, runtime population, package identity,
boundary continuity, oracle or parity results, checkpoint authority, backfill,
production readiness, or issue completion.

Every segment therefore keeps `execution_model: undecided` and
`backfill_allowed: false`. Issue #37's Flash implementation checkbox remains
unchecked.

## Retarget gate satisfied

The component is based on exact canonical Pool Swap squash merge
`71d554fa9676d8c77437c0366a9859e13834e235`. Its merge tree was verified
identical to the audited candidate before deterministic contract regeneration
and focused plus full validation reruns, satisfying the source-base gate only.
