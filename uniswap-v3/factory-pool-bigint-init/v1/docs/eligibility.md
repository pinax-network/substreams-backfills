# Eligibility boundary

This certificate adds conditional legacy Factory initialization call-flow
evidence for five fields only:

```text
Pool.liquidityProviderCount
Pool.txCount
Pool.liquidity
Pool.sqrtPrice
Pool.observationIndex
```

For each of four unique legacy mappings, it proves the inherited event-pool
origin of `$l1`; the decoded direct field keys; `$g2` as the pointer returned
by `ByteArray.fromI32(0)`; exact `Value.fromBigInt` and outer `TypedMap#set`
call operands for four direct fields; the selected `$l1`/`$g2` invocation of
the shared `txCount` helper; that helper's exact key/wrapper/set operands; and
the uninterrupted same-receiver path to `Pool.save`. The path is conditional
on normal continuation past the excluded-pool return, both token-decimals
returns, and every helper or import trap.

The retained helper symbol `Factory#set:txCount` is a linker-selected name,
not semantic authority that its receiver is a Factory or a Pool. Authority for
the selected flow is the exact decoded `txCount` key, exact helper body, exact
call operands, the independently bound event-pool receiver origin, and the
same-receiver save path.

Legacy selected field mutation remains false. The proof binds only outer call
operands. It does not rederive `TypedMap#getEntry`, string or index traversal,
entry construction, entry-array push/reallocation, Entity construction or
backing arrays, allocator behavior, or fresh `Value` allocation.

## Projection

| Generation | Unique mappings | Segments | Selected field records |
|---|---:|---:|---:|
| legacy | 4 | 6 | 30 |
| modern parent | 2 | 2 | 10 |
| **total** | **6** | **8** | **40** |

All 28 unordered segment pairs receive deterministic scoped semantic and
provenance diffs. They compare only this initialization surface, not complete
writer semantics, boundary state, or a Graph oracle.

## Static-site and expanded-invocation accounting

The retained legacy reachability inventory has 44 static `TypedMap#set` sites
and 78 expanded handler-level map-write invocations.

After composing the fee-growth parent and this slice:

- six direct static sites are fully selected;
- 38 static sites remain unclassified;
- seven expanded invocations are selected;
- 71 expanded invocations remain residual; and
- the shared `txCount` static site remains among the 38 residual sites.

The shared helper is invoked four times at relative handler lines 60, 168,
242, and 330. Only line 330, whose receiver is the selected Pool `$l1`, is in
scope. Selecting one expanded invocation does not fully classify the shared
static site or its other three invocations.

Seven of 60 legacy Factory field initializers now have bounded call-flow
capsules. Fifty-three lack such capsules. All 60 complete legacy field
contracts nevertheless remain unproved because legacy mutation, persistence,
and complete history remain false.

The formal cumulative field ledger remains **36 selected / 230 residual**.
Factory closure remains **14/18**, with the same four legacy
`complete_static_handler_contract` paths unresolved. No tracking issue gains a
completed acceptance criterion from this certificate.

## Strict false gates

The following remain strict JSON `false` values:

- all four legacy complete-static Factory contracts and all 60 complete legacy
  stored-field contracts;
- the shared `txCount` static site being fully selected, all four helper
  invocations being selected, and the helper symbol name being entity
  authority;
- safety of the legacy static arrays and correct ERC20 `totalSupply` result
  decoding;
- imported host, numeric, memory-reset, bytes-to-hex, and Graph store
  semantics;
- fresh `Value` allocation, inner `TypedMap`/entry/array semantics, Entity
  construction/backing, general heap aliases, and actual legacy field mutation;
- numeric-zero preservation across reset/lifecycle behavior and cross-handler
  allocator freshness;
- selected persistence, later semantic overwrite exclusion, Graph rollback,
  runtime population, historic outcomes, and complete Factory or Pool history;
- integrated scheduling, package consumption, configured package identity,
  post-fatal execution, boundary continuity, checkpoint, and oracle/parity;
- logical, physical, and proof-of-indexing parity; and
- issue #37 or #38 acceptance, backfill, deployment, production, or readiness.
