# Uniswap V3 Factory fee-growth initialization v1

This certificate proves a deliberately narrow legacy
`Factory.handlePoolCreated` call flow. Across four unique legacy Factory mappings,
the event's pool address feeds one generic-constructor result used as the
`Pool` setter/save receiver, both
`feeGrowthGlobal0X128` and `feeGrowthGlobal1X128` setter calls receive the
pointer returned by `ByteArray.fromI32(0)` and stored in native-start `$g2`
through `Value.fromBigInt`, and the same unreassigned receiver is passed to
`Pool.save` on normal continuation.

The four mapping proofs project to six legacy deployment segments and 12
segment-field records. The verifier also reruns the existing modern Factory
static parent and projects its two mappings, producing 16 total initialization
records over eight segments. All 28 pairwise scoped segment diffs are retained.

| Profile | Mapping CID | Segment projection |
|---|---|---|
| legacy mainnet root | `QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr` | 12,369,621–13,450,880 |
| legacy mainnet QmRv | `QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV` | 13,450,881–13,498,328 |
| legacy mainnet stable | `QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL` | 13,498,329–19,470,000 in three graft segments |
| legacy Base root | `QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj` | 1,371,679–19,852,000 |

For each retained legacy artifact, the verifier binds the complete module
surface and mutable-global writer inventory, native start, unique `$g2`
writer, event-pool receiver origin, two decoded field keys, exact
Value/`TypedMap#set` call operands, the setter-through-save region, `Pool.save`
ID/kind branches and
`store.set` operands, early-return guards, and every reachable function body,
direct memory write, `TypedMap#set`, and Graph store target. The four setter
slices and four setter-through-save regions normalize identically only after
decoding their profile-specific static string pointers.

This is call-operand evidence, not proof of legacy in-memory field mutation,
persistence, or complete-static semantics. The inner `TypedMap` search,
entry-constructor, entry-array push/reallocation, Entity construction/backing,
fresh Value allocation, ID lookup, and `Value#toString` semantics are retained-body
boundaries rather than rederived claims.
Fifty-eight other legacy stored-field contracts remain unproved. The legacy
static arrays still contain six leading holes, and the legacy `totalSupply`
helper still passes a call-result pointer to `ByteArray.fromI32` instead of
decoding ERC20 return data. Host/reset behavior, numeric-zero preservation
across lifecycle resets, Graph store semantics and rollback, later aliases or
overwrites, historic outcomes, population, complete histories, parity,
checkpoint, backfill, deployment, production, and readiness remain false.
The cumulative ledgers remain 36 selected / 230 residual fields and 14 of 18
Factory paths; this certificate completes no tracking-issue checkbox.

The exact base is canonical PR #71 squash merge
`cf4d096304c09f150a7ee2ea85de5d479d5ec7ef`. Its tree
`346c9ba3eb141ada18d4ee1589a725919b349351` matches the independently
audited candidate `4e173177089ae0781e389588d11dfe1a8d013391`; deterministic regeneration
and validation were rerun after retargeting.

See [eligibility.md](docs/eligibility.md) for the exact claim and refusal
matrix and [provenance.md](docs/provenance.md) for immutable inputs,
normalization, and reproduction.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-factory-fee-growth-init.py
python3 -m unittest scripts.tests.test_uniswap_v3_factory_fee_growth_init
```
