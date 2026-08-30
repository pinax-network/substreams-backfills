# Uniswap V3 Pool Burn TVL semantics v1

This additive supplement binds retained-WAT `Pool.handleBurn` call-flow evidence
for `Pool.totalValueLockedToken0` and `Pool.totalValueLockedToken1` across all
eight retained Uniswap V3 Pool mappings. It consumes the immutable segment-field
v2 and Pool Initialize ledgers and, for every current WAT fixture, re-runs the
public modern or legacy Pool runtime capsule. It does not promote either field's
selected-handler projection because baseline dynamic-key and memory-alias effects
remain semantically unclassified.

For each mapping, the Burn-specific proof establishes that the handler:

1. converts the trigger address through the exact generation-specific
   `typeConversion.bytesToHex` import and uses that ID to load `Pool`;
2. reads Burn ABI parameters 4 and 5 as `amount0` and `amount1` through the
   capsule-proved EventParam array getter;
3. loads `Token[Pool.token0]` and `Token[Pool.token1]`, reads their `decimals`,
   and feeds each matching amount and decimals value to the retained decimal
   conversion flow;
4. computes old matching Pool TVL minus the converted amount, in that operand
   order;
5. passes the same loaded Pool, exact selected key, and BigDecimal Value to the
   capsule-proved TypedMap setter; and
6. calls the sole reachable `Pool.save` with that loaded Pool after both setters
   on the selected-update path.

The shared capsule supplies the collection/runtime facts that this supplement
does not duplicate: modern and legacy EventParam access and TypedMap get/set;
modern binds entry append/array growth and allocator return identity; legacy
additionally binds `getEntry`, Value/entry construction, and entry-array runtime.
Both capsules bind module start and complete ZERO/ONE global-writer inventories;
the Burn verifier binds the modern inline BigDecimal Value layout.
Legacy allocation freshness is only intra-handler under the assumption that
imported hosts do not reenter exported `memory.reset`; modern freshness assumes
imported hosts do not write arbitrary linear memory.

## Segment result

All eight retained profiles have a path that reaches the selected setters and
then Pool save. The two modern profiles place the update/save body behind a
two-token presence guard with no outer `else`; if either Token is missing, that
body is skipped on a normal return. The six legacy call-flow records are limited
to their normal-completion path and do not claim a missing-token no-op.

The verifier binds every function body reachable from `handleBurn`, plus the
complete reachable direct-memory-write and TypedMap-set site inventories. Any
inventory drift therefore fails closed. The baseline inventories are not a
semantic absence proof: outside the two explicit selected setters, each modern
profile retains 147 TypedMap-set sites without selected receiver/key/value proof
and 526 direct writes without selected-payload alias proof; each legacy profile
retains 52 and 166 respectively. No-later-overwrite, general heap-alias, and
arbitrary selected-payload alias safety therefore remain explicitly false.

The verifier also records non-try Tick contract calls between the selected
setters and `Pool.save`, followed by the Burn entity write. It does not rederive
the behavior of `bytesToHex`, numeric hosts, Graph store hosts, Graph rollback,
or execution after a fatal host result.

This adds 16 segment-field call-flow evidence records and 28 scoped diffs, but
does not change the cumulative ledger: the selected-handler field count remains
36 and the unresolved conditional field count remains 230. Selected TVL
persistence, complete Burn semantics, complete Pool history, parity, checkpoint,
backfill, production, and readiness gates all remain false.

```console
python3 scripts/verify-uniswap-v3-pool-burn.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_burn
```

Intentional deterministic regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-burn.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the retained artifact chain.
