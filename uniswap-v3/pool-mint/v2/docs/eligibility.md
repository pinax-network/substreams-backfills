# Eligibility boundary

Pool Mint schema-API matrix v2 is offline evidence only. It does not authorize
a stream, database mutation, package, deployment, checkpoint, backfill, or
production operation.

## Proved static scope

Across eight exact retained mappings, the certificate proves:

- a complete 8 × 299 = 2,392 path-qualified outcome matrix;
- the exact 1,136 / 368 / 104 / 784 category totals;
- two selected Pool old-plus-converted-Mint-amount setter paths per segment,
  included in the 142 stored-setter outcomes;
- 13 required Mint fields plus nullable `sender`, `amountUSD`, and `logIndex`,
  all with setter paths, and a zero required-absence overlay;
- 172 lexical field invocations, 176 site edges, 244 expanded setter paths,
  142 unique stored setter fields, 13 lexical Graph stores, 12 physical stores,
  and 17 expanded store paths per mapping;
- exact legacy 182 / 914 / 166 / 65 and modern 96 / 1,094 / 584 / 174
  function/call/direct-write/physical-map-set inventories;
- receiver context, field key, nullable alternatives, helper multiplicity,
  matching store target, and normal-continuation setter-before-store order;
- modern two-Token guards, conditional tick creation branches, and subsequent
  Tick update control; and
- all 28 recursive segment diffs with zero unclassified setter sites.

The 46 reachable-store/no-setter fields are not proved preserved or unchanged.
The 13 derived outcomes prove no direct Graph store transition; five static
child-association setter paths do not prove Graph query visibility.

## Gates that remain false

The machine-readable boundary retains these false gates:

- `numeric_semantics_complete`, `imported_numeric_semantics_complete`,
  `imported_comparator_semantics_complete`, and `imported_host_semantics_complete`;
- `direct_payload_alias_safety_complete`, `general_heap_alias_safety_complete`,
  `loaded_field_preservation_proven`, `field_value_unchanged_proven`, and
  `no_later_field_overwrites_proven`;
- `contract_call_value_semantics_complete`,
  `contract_call_error_semantics_complete`, and
  `contract_call_block_pointer_semantics_complete`;
- `graph_store_host_semantics_complete`,
  `graph_store_visibility_or_version_proven`,
  `graph_store_persistence_complete`, `graph_store_persistence_proven`,
  `graph_handler_rollback_proven`, and `post_fatal_execution_modeled`;
- `complete_mint_entity_history`, `complete_pool_entity_history`,
  `complete_entity_history`, and `all_manifest_handler_field_semantics_complete`;
- `scheduler_implemented`, `runtime_population_complete`, `output_implemented`,
  `store_implemented`, `package_implemented`,
  `writer_package_consumes_projection`, and `source_package_identity_proven`;
- `combined_handler_order_implemented`,
  `dynamic_datasource_stage_order_implemented`, `boundary_continuity_complete`,
  `logical_parity_complete`, `physical_parity_complete`, `poi_parity_complete`,
  and `graph_oracle_complete`;
- `checkpoint_authority`, `backfill_ready`, `deployment_ready`,
  `production_ready`, and `readiness_complete`; and
- `issue_37_acceptance_criterion_complete`,
  `issue_38_acceptance_criterion_complete`, and `issue_checkbox_completed`.

Every segment remains `execution_model: undecided` and
`backfill_allowed: false`. Issue #38 receives a reviewable Mint schema-API
slice, but no issue checkbox is complete.
