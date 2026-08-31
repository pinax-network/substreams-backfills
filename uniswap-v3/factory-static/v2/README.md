# Uniswap V3 Factory static semantics v2

This additive offline certificate closes the four retained legacy
`Factory.handlePoolCreated` complete-static paths and composes them with the
two already-complete modern paths from
[`factory-static/v1`](../v1/README.md). The scope is path-qualified static
behavior, not a statement that every historical event reached the final save.

For each of the four unique legacy Factory mappings, the verifier recomputes
the exact retained WASM and WAT authority inherited through
[`factory-pool-price-init/v1`](../../factory-pool-price-init/v1/README.md),
then proves a Factory-specific allocator, Value, String, entry-array, Entity,
and `TypedMap` mutation capsule. It classifies all 44 reachable static
`TypedMap#set` sites: 27 direct handler sites and 17 helper sites. It also
classifies all 78 expanded handler invocations by exact entity receiver,
decoded key, Value kind, payload producer, and call target. Every reviewed
operand slice is independently digest-bound within the exact complete handler
and reachable-function body inventory inherited from the Factory effect
closure. Factory/Bundle/owner literals are decoded, and both initial whitelist
payload objects are separately proved to have zero length before their kind-4
Value wrapping.

The resulting field contract matches modern v1 exactly:

| Entity | Stored-field contracts | Written | Required absence |
|---|---:|---:|---:|
| Factory | 13 | 13 | 0 |
| Bundle | 2 | 2 | 0 |
| Token | 16 | 16 | 0 |
| Pool | 29 | 28 | 1 (`Pool.tick`) |
| **Total** | **60** | **59** | **1** |

The 78 invocations are potential lexical paths, not simultaneous writes.
Factory creation, Bundle creation, token creation, whitelist updates, the
excluded-pool return, null-decimals returns, helper traps, and imported-host
outcomes remain conditional. Normal-return and explicit trap-prefix effect
ordering comes from the exact bound `factory-effects/v1` proof.

Two deployed legacy quirks are intentionally preserved:

- Base creates six leading empty static-definition slots and appends no
  definitions; mainnet creates the same six leading empty slots and appends
  six definitions. `static_array_safe` remains false.
- `fetchTokenTotalSupply` passes the outer `CallResult` pointer to
  `ByteArray.fromI32` on success and zero on revert. It does not decode the
  returned ERC20 integer, so `total_supply_erc20_result_data_decoded` remains
  false.

This moves scoped Factory static closure from 14/18 to 18/18. It does not
prove imported host or numeric semantics, Graph store persistence or rollback,
historical entity populations, complete Factory or Pool history, integrated
execution order, source-package identity, graft-boundary continuity, parity,
backfill safety, production safety, or readiness. It completes no checkbox in
issues #37 or #38.

See [eligibility.md](docs/eligibility.md) for the exact claim boundary and
[provenance.md](docs/provenance.md) for immutable inputs and validation.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-factory-static-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_factory_static_v2
```
