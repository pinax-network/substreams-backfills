# Uniswap V3 Pool Flash semantics v2

This additive offline certificate composes the exact retained-WAT Pool Flash
v1 proof with the exact 299-field schema catalog. It produces a complete
normal-success-path-qualified static schema-API effect matrix for all eight
mainnet and Base ancestry segments: 2,392 field outcomes and all 28 recursive
semantic/provenance diffs.

## Exact field matrix

Each segment has four mutually exclusive categories:

| Category | Per segment | All segments | Exact claim |
| --- | ---: | ---: | --- |
| selected stored Pool fields | 2 | 16 | the fee-growth setter occurs before the same loaded Pool's sole save |
| other stored Pool fields | 27 | 216 | no other reachable schema setter for the field occurs before that save |
| Pool `@derivedFrom` fields | 7 | 56 | no direct Graph store transition exists in this handler's Pool-only store closure |
| fields outside Pool | 263 | 2,104 | the field's entity is outside the sole reachable `Pool` store target |

The fourth category includes all 12 `Flash` fields in every segment: 96 exact
required-absent outcomes. The retained handler has no reachable `Flash` store
target and does not synthesize a `Flash` row.

The 27-field category is intentionally limited. It does not characterize a
field's input value, in-memory value, saved value, or value after the handler.
The proof only closes the schema setter inventory: the two fee-growth setters
are the only reachable `TypedMap#set` sites before the same loaded Pool reaches
the sole save.

## Normal-success ordering

Across all eight exact mapping binaries, retained WAT proves this bounded
normal-success order:

1. use the event address to load `Pool` and bind the Pool contract;
2. call and decode result element zero from `feeGrowthGlobal0X128()`;
3. only after that call/decode completes, call and decode result element zero
   from `feeGrowthGlobal1X128()`;
4. only after both decodes succeed, invoke the two matching setters; and
5. pass that same loaded Pool to the sole Pool save.

The modern mappings inline both call/decode sequences. The legacy mappings use
synchronous getter wrappers, so each wrapper must return its decoded result
before the next handler instruction can execute. The legacy generated setter
symbols are deduplicated and misleading; decoded keys, operands, receiver
identity, exact helper bodies, and the retained handler are authority.

Both calls use the generated non-try `SmartContract#call` helper. Either null
result follows its closed abort/unreachable branch before control can reach a
setter or the save. This proves structural control flow only. Imported host
return values, error classes, block pointers, numeric meaning, arbitrary heap
aliases, Graph store behavior, persistence, rollback, and post-fatal behavior
remain unproved.

## Boundary

“Complete” means only the path-qualified static Flash schema-API matrix above.
Complete Pool/Flash history, other-handler semantics, combined handler and
dynamic-data-source order, runtime population, scheduler, output, Store,
package consumption and identity, continuity, oracle/parity, checkpoint
authority, backfill, deployment, production, and readiness all remain false.
This slice completes no issue checkbox.

Pool Flash v1 and the field catalog are recomputed directly. Factory static v2
is not an input.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-pool-flash-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_flash_v2
```

Intentional deterministic regeneration uses:

```bash
python3 scripts/verify-uniswap-v3-pool-flash-v2.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for exact inputs and reproduction.
