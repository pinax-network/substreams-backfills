# Uniswap V3 Factory Pool price initialization v1

This certificate proves a deliberately narrow legacy
`Factory.handlePoolCreated` call flow for two `Pool` fields:

```text
token0Price
token1Price
```

For four unique legacy Factory mappings, the event's pool address feeds one
generic-constructor result retained in `$l1`. Both direct `TypedMap#set` calls
receive `$l1`, the exact decoded field key, and `$g4` through
`Value.fromBigDecimal`. The certificate binds `$g4` only as the pointer returned by `bigDecimal.fromString("0")`
and uniquely stored by the constants initializer.
It does not derive the imported function's numeric semantics or
claim that the pointer is a proven numeric zero. `Value.fromBigDecimal` binds
kind tag `2`, the exact input pointer at payload offset 8, and the same returned
wrapper local. Both selected flows reach the same-receiver `Pool.save` call on
normal continuation.

The four mapping proofs project to six legacy deployment segments and 12
segment-field records. The verifier checksum-pins and reruns the canonical
Factory Pool BigInt initialization parent, including its transitive parents,
then composes four modern `ZERO_BD` records. The result is 16 records over
eight segments with all 28 scoped segment pairs retained.

After composing the fee-growth, BigInt, and price slices, the direct-site
accounting is **8/44** fully selected static `TypedMap#set` sites, leaving 36
unclassified. Expanded handler-level accounting is **9/78** selected
invocations, leaving 69 residual. The linker-shared `txCount` static site
remains residual because only its Pool invocation was selected by the parent.
Nine of 60 legacy Factory field initializers now have bounded call-flow
capsules, but all 60 complete legacy field contracts remain unproved.

This is legacy call-operand and pointer-provenance evidence, not proof of
BigDecimal numeric semantics, in-memory field mutation, persistence, or
complete-static behavior. Inner `TypedMap` search, entry construction, array
push/reallocation, Entity backing-array behavior, allocator behavior, fresh
`Value` allocation, Graph store behavior and rollback, later overwrites,
historic outcomes, runtime population, complete histories, parity, checkpoint,
backfill, deployment, production, and readiness remain false. The formal field
ledger remains 36 selected / 230 residual, and Factory closure remains 14/18.
This certificate completes no tracking-issue checkbox.

The exact base is canonical PR #73 merge
`19bbc277006cccaf960647dc0bb3c7344688a07f`. Its tree
`0afaf69b8446c84b5542453addb0810852387090` matches independently audited
candidate `0b29c6e53ef42ed98e3413a49ad79a9dcefdbb97`. The BigInt parent contract is
pinned by raw and canonical SHA-256 and rerun rather than trusted as opaque
JSON.

See [eligibility.md](docs/eligibility.md) for the exact claim and refusal
matrix and [provenance.md](docs/provenance.md) for immutable inputs,
normalization, and reproduction.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-factory-pool-price-init.py
python3 -m unittest scripts.tests.test_uniswap_v3_factory_pool_price_init
```
