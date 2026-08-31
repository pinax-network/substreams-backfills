# Pool Flash v2 eligibility boundary

This certificate is eligible to assert exactly one bounded result: the
complete normal-success-path-qualified static schema-API effect matrix for
`Pool.handleFlash` across the eight retained segments.

## Closed evidence

- 299 schema fields per segment and 2,392 outcomes total;
- 16 selected fee-growth setter-before-same-Pool-save outcomes;
- 216 other stored Pool outcomes for which no other reachable schema setter
  occurs before the same-Pool save, without a field-value claim;
- 56 Pool-derived outcomes with no direct Graph store transition;
- 2,104 outcomes outside the Pool-only Graph store closure;
- 96 explicit Flash required-absence outcomes; and
- all 28 recursive segment semantic/provenance diffs.

The normal-success order is limited to event-address Pool load/contract bind,
fee0 call/decode before fee1, both setters after both successful decodes, and
the same loaded Pool reaching the sole save. Either non-try null result traps
before the setters and save.

## Gates that remain false

The machine-readable contract keeps all of these boundaries false:

- `host_call_value_semantics_complete`
- `host_call_error_semantics_complete`
- `numeric_semantics_complete`
- `general_heap_alias_safety_complete`
- `graph_store_host_semantics_complete`
- `graph_store_persistence_proven`
- `graph_handler_rollback_proven`
- `post_fatal_execution_modeled`
- `complete_pool_entity_history`
- `complete_flash_entity_history`
- `complete_entity_history`
- `combined_handler_order_implemented`
- `dynamic_datasource_stage_order_implemented`
- `runtime_population_complete`
- `scheduler_implemented`
- `output_implemented`
- `store_implemented`
- `package_implemented`
- `writer_package_consumes_projection`
- `source_package_identity_proven`
- `boundary_continuity_complete`
- `graph_oracle_complete`
- `logical_parity_complete`
- `physical_parity_complete`
- `poi_parity_complete`
- `checkpoint_authority`
- `backfill_ready`
- `deployment_ready`
- `production_ready`
- `readiness_complete`
- `issue_37_acceptance_criterion_complete`
- `issue_38_acceptance_criterion_complete`
- `issue_checkbox_completed`

No issue checkbox is completed by this slice. The repository-wide 28-day
eligibility rule remains necessary but is not sufficient: this certificate
does not authorize a backfill or deployment.
