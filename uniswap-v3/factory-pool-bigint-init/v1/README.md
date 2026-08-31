# Uniswap V3 Factory Pool bigint initialization v1

This certificate proves a deliberately narrow legacy
`Factory.handlePoolCreated` call flow for five `Pool` fields:

```text
liquidityProviderCount
txCount
liquidity
sqrtPrice
observationIndex
```

For four unique legacy Factory mappings, the event's pool address feeds one
generic-constructor result retained in `$l1`. Four fields use direct
`TypedMap#set` calls; each call receives `$l1`, the decoded field key, and the
pointer returned by `ByteArray.fromI32(0)` and stored in `$g2` through
`Value.fromBigInt`. `txCount` uses the same `$l1` and `$g2` as operands to a
linker-shared setter helper whose exact `txCount` key, `Value.fromBigInt`, and
outer `TypedMap#set` operands are bound. All five selected flows reach the
same-receiver `Pool.save` call on normal continuation.

The helper is named `Factory#set:txCount` in retained WAT, but that symbol is
not Pool entity authority. It has four handler invocations. Only the invocation
with the selected Pool receiver is certified here; the other three and the
helper's static set site remain residual.

The four mapping proofs project to six legacy deployment segments and 30
segment-field records. The verifier reruns the canonical Factory fee-growth
initialization parent, inherits its recomputed modern Factory static parent,
and projects ten modern records. The result is 40 records over eight segments
with all 28 scoped segment pairs retained.

After composing the two fee-growth fields with this slice, six of 44 static
`TypedMap#set` sites are fully selected and 38 remain unclassified. Seven of
78 expanded handler-level map-write invocations are selected and 71 remain
residual. The shared `txCount` static site is one of the 38 residual sites.
Seven of 60 legacy Factory field initializers now have bounded call-flow
capsules, but all 60 complete legacy field contracts remain unproved.

This is legacy call-operand evidence, not proof of in-memory field mutation,
persistence, numeric-zero preservation, or complete-static semantics. Inner
`TypedMap` search, entry construction, array push/reallocation, Entity
backing-array behavior, allocator behavior, fresh `Value` allocation, Graph
store behavior and rollback, later overwrites, historic outcomes, population,
complete histories, parity, checkpoint, backfill, deployment, production, and
readiness remain false. The formal field ledger remains 36 selected / 230
residual, and Factory closure remains 14/18. This certificate completes no
tracking-issue checkbox.

The exact base is canonical PR #72 squash merge
`982dd6f049af265cfed4c7b8edce1a90c936f319`. Its tree
`ffc1ef46913c94a6c7b5bc9738de2389dce38daf` matches independently audited
candidate `1c6d90f0cbf7bf80a47555f9f6242d8f7440975e`. The parent is pinned and
rerun rather than trusted as an opaque JSON input.

See [eligibility.md](docs/eligibility.md) for the exact claim and refusal
matrix and [provenance.md](docs/provenance.md) for immutable inputs,
normalization, and reproduction.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-factory-pool-bigint-init.py
python3 -m unittest scripts.tests.test_uniswap_v3_factory_pool_bigint_init
```
