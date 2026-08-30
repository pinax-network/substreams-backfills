# Eligibility boundary

The v1 supplement certifies exactly six new upstream paths, one for each
retained Factory mapping:

```text
$.pool_created_effect_order_observation.same_path_or_dataflow_machine_proven
```

Together with the four legacy and two modern guard paths already certified,
the cumulative Factory status is:

- total upstream Factory proof paths: 18;
- previously closed: 6;
- newly closed here: 6;
- cumulative closed: 12; and
- residual: 6.

For each exact binary, the selected effect projection on every handler-local
normal exit is either empty at a reviewed pre-effect return or exactly Pool
save, Pool dynamic data-source creation, token0 save, token1 save, and Factory
save once in that order. Handler-local explicit traps and reviewed save-helper
pre-store trap boundaries may contain only an ordered prefix. This is not a
complete interprocedural trap projection. Every alternative reaching
definition of each call receiver is bound to the exact Pool, token0, token1,
or immutable Factory ID. Constructor alternatives include body-level proofs
that the same input ID is written under `id` on the fresh entity returned to
the handler. The active template name is `Pool`, and its sole argument is the
lowercase hexadecimal address from `PoolCreated.event.pool`.

This does not establish any of the following:

- Graph Node rollback of earlier host calls after a later trap;
- trap behavior of every reachable helper and imported host call;
- every initialized Factory, Bundle, Token, or Pool field value;
- successful or failed `totalSupply` value flow;
- a complete static Factory handler contract;
- complete Factory entity history across other handlers;
- Graph Node dynamic-data-source stage order or post-fatal execution;
- runtime consumption, population, checkpoint authority, or target identity;
- boundary continuity or logical, physical, proof-of-indexing, and GraphQL
  parity; or
- backfill or production readiness.

Those gates remain strict JSON `false` values. This supplement alone does not
satisfy a full Factory-semantics or backfill issue.
