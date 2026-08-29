# Eligibility boundary

The v1 supplement certifies exactly two new paths:

```text
$.excluded_pool_guard_observation.event_pool_to_comparison_to_early_return_machine_proven
```

They belong to the retained `modern-base` and `modern-mainnet` Factory mapping
artifacts. Together with the four legacy guard paths certified by
field-semantics v2, the cumulative Factory status is:

- total upstream Factory proof paths: 18;
- previously closed: 4;
- newly closed here: 2;
- cumulative closed: 6; and
- residual: 12.

For both modern binaries, an early return is now machine-proven to occur only
when the address at PoolCreated parameter index 4 has length 20 and every byte
equals `0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248`. A length mismatch or the
first mismatch at any of the twenty byte positions yields result zero and
continues normally. No persistent Graph store or data-source effect precedes
the guard return.

This does not establish any of the following:

- the identity, arguments, dominance, or rollback semantics of the normal-path
  Pool, Token, Factory, or template effects;
- the successful or failed `totalSupply` value flow;
- a complete static Factory handler contract or all initialized field values;
- complete Factory entity history across other handlers;
- Graph Node dynamic-data-source stage order or post-fatal execution;
- runtime consumption, target population, or checkpoint authority;
- boundary continuity or logical, physical, proof-of-indexing, and GraphQL
  parity; or
- backfill or production readiness.

All those gates remain strict JSON `false` values in the contract. This
supplement alone does not satisfy a full Factory-semantics or backfill issue.
