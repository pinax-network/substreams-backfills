# Uniswap V3 Pool Mint TVL semantics v1

This additive supplement binds retained-WAT `Pool.handleMint` call-flow evidence
for `Pool.totalValueLockedToken0` and `Pool.totalValueLockedToken1` across all
eight retained Uniswap V3 Pool mappings. It consumes the digest-pinned Pool Burn
and segment-field v2 ledgers and, for every current WAT fixture, re-runs the
public modern or legacy Pool runtime capsule. It does not promote either field's
selected-handler projection because baseline dynamic-key and memory-alias effects
remain semantically unclassified.

For each mapping, the Mint-specific proof establishes that the handler:

1. converts the trigger address through the exact generation-specific
   `typeConversion.bytesToHex` import and uses that ID to load `Pool`;
2. reads Mint ABI parameters 5 and 6 as `amount0` and `amount1` through the
   capsule-proved EventParam array getter;
3. loads `Token[Pool.token0]` and `Token[Pool.token1]`, reads their `decimals`,
   and feeds each matching amount and decimals value to the retained decimal
   conversion flow;
4. computes old matching Pool TVL plus the converted amount, in that operand
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
the Mint verifier binds the modern inline BigDecimal Value layout.
Legacy allocation freshness is only intra-handler under the assumption that
imported hosts do not reenter exported `memory.reset`; modern freshness assumes
imported hosts do not write arbitrary linear memory.
Within those boundaries, the verifier connects two distinct wrapper allocation
triggers and two distinct selected BigDecimal Value creation triggers to the
same-WAT allocator proof. Cross-handler freshness remains false.

## Segment result

All eight retained profiles have a path that reaches the selected setters and
then Pool save. The two modern profiles place the update/save body behind a
two-token presence guard with no outer `else`; if either Token is missing, that
body is skipped on a normal return. The six legacy call-flow records are limited
to their normal-completion path and do not claim a missing-token no-op.

The verifier binds every function body reachable from `handleMint`, plus the
complete reachable direct-memory-write and TypedMap-set site inventories. Any
inventory drift therefore fails closed. The baseline inventories are not a
semantic absence proof: outside the two explicit selected setters, each modern
profile retains 172 TypedMap-set sites without selected receiver/key/value proof
and 584 direct writes without selected-payload alias proof; each legacy profile
retains 63 and 166 respectively. No-later-overwrite, general heap-alias, and
arbitrary selected-payload alias safety therefore remain explicitly false.

The verifier also records that `Pool.save` precedes the Mint entity write and
that both precede the non-try Tick contract calls. Because Graph rollback and
post-fatal behavior are not derived from WAT, this ordering is not a persistence
claim. It does not rederive the behavior of `bytesToHex`, numeric hosts, Graph
store hosts, Graph rollback, or execution after a fatal host result.

For modern mappings, the missing-Pool branch is an unconditional closed trap,
and each required Pool/Token schema getter proves that every missing/null path
traps while successful decoding requires a nonzero map value. Legacy generated
getters do not expose equivalent guards, so legacy missing-entity behavior is
explicitly unproved.

This adds 16 segment-field call-flow evidence records and 28 scoped diffs, but
does not change the cumulative ledger: the selected-handler field count remains
36 and the unresolved conditional field count remains 230. Selected TVL
persistence, complete Mint semantics, complete Pool history, parity, checkpoint,
backfill, production, and readiness gates all remain false.

```console
python3 scripts/verify-uniswap-v3-pool-mint.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_mint
```

Intentional deterministic regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-mint.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the retained artifact chain.
