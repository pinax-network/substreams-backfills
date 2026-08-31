# Uniswap V3 NPM Liquidity v2 certificate

This directory contains two complete, independent, path-qualified static
schema-API effect certificates for
`NonfungiblePositionManager.handleIncreaseLiquidity` and
`NonfungiblePositionManager.handleDecreaseLiquidity`. It covers all eight
retained mainnet and Base ancestry bindings and their six unique NPM WASMs. A
third view is the derived set union of those two proofs; it is not an event
sequence or a combined execution path.

The certificate is offline. It proves retained-WAT functions, direct calls,
memory writes, constructors/setters, fixed store targets, Ethereum calls,
indirect-table closure, trap sites and branch-prefix order. It does not prove
imported values, arithmetic meaning, store contents or visibility,
persistence, rollback, entity history, handler event ordering, runtime parity,
backfill or production readiness.

## Exact scope

- 8 segment bindings and 6 unique NPM WASMs;
- for each handler, 299 outcomes per segment partitioned as 38 classified
  stored targets, 0 saved-without-setter, 13 derived and 248 stored outside
  the closure;
- 4,784 independent handler outcomes and 528 required-absence overlays;
- a derived paired union of 2,392 outcomes and 264 overlays;
- 33 required-absence outcomes per handler and segment: Collect 11, Flash 12
  and TickHourData 10;
- all 28 segment-pair axes, each with separate Increase, Decrease and union
  recursive semantic/provenance diffs, plus 8 within-segment handler diffs;
- exactly three store targets: Position, PositionSnapshot and Transaction;
- 43 lexical field invocations per handler, with maximum expanded accepted
  paths of 26 for an existing Position and 48 for a new Position;
- a 46-site lexical set union and 86 handler-attributed lexical invocations,
  with no sequential-composition claim;
- nine relationship/Transaction identity paths.

The six-WASM physical totals are:

| Proof | Functions | Calls | Targets | Writes | Generic | Named | Gets | Sets | Eth calls | Indirect | Aborts | Unreachable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Increase | 559 | 2,555 | 625 | 1,328 | 174 | 132 | 20 | 18 | 12 | 2 | 222 | 262 |
| Decrease | 559 | 2,557 | 631 | 1,328 | 174 | 132 | 20 | 18 | 12 | 2 | 224 | 264 |
| set union | 565 | 2,789 | 631 | 1,360 | 180 | 144 | 24 | 18 | 12 | 2 | 224 | 264 |

Weighted across eight bindings, those rows are respectively
`771/3379/859/1682/218/198/26/24/16/2/280/338`,
`771/3381/867/1682/218/198/26/24/16/2/282/340`, and
`779/3683/867/1714/224/216/30/24/16/2/282/340` in the same column order.
Store removes and schema unsets are zero in every row. Physical sites are kept
separate from semantic invocations.

## Independent handler ledgers

Both handlers expand the same shared helpers: getPosition classifies 17
Position fields on a missing-Position path, updateFeeVars can classify two
fee-growth fields, and savePositionSnapshot classifies 16 Snapshot fields.
Every completed loadTransaction invocation classifies blockNumber, timestamp,
gasUsed and gasPrice and saves Transaction; a store miss additionally
classifies id inside the constructor branch. Each handler adds three local
Position setter paths:

- Increase: liquidity, depositedToken0, depositedToken1;
- Decrease: liquidity, withdrawnToken0, withdrawnToken1.

The retained calls route the result of `BigInt#plus` to Increase liquidity and
the result of `bigInt.minus` to Decrease liquidity; BigDecimal-plus results
reach the corresponding token setters. This is call/setter flow only. No
arithmetic result, sign, overflow or imported numeric meaning is certified.

Legacy Decrease physically uses generated `IncreaseLiquidity__Params` symbols.
That alias is recorded exactly and is not promoted to a source-language type
or value-semantics conclusion. Current Decrease has an explicit abort branch
before minus and all three setters when its liquidity input is null; Increase
and legacy Decrease do not have that explicit handler abort site.

## Guards and path prefixes

The three earliest legacy mappings have no historical block guard. The Base
legacy mapping uses the old-codegen equality model at block 14,317,993. Both
current mappings use the modern compare-equals-zero model at the same block.
When present, the guard returns before contract, schema or store effects.

After getPosition, the excluded-pool check compares Position.pool with
`0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248`. It precedes Token reads, local
setters, fee refresh, Position.save and Snapshot construction. An existing
excluded Position has no certified schema/store effect. A newly built excluded
Position has 21 effects on a first loadTransaction hit or 22 on a miss; either
completed branch has already saved Transaction.

Legacy handlers use two generated Token.load calls; a missing Token is a fatal
prefix before all three local setters, fee refresh and saves. Current handlers
use two direct store reads; either null result returns normally at the same
prefix. Existing paths then have zero schema effects, while a new path already
has 21 or 22 effects and one Transaction store. Returned Token contents,
aliases and persistence are unproved.

On a missing Position, getPosition makes a generated try_positions call. A
revert returns without schema or store effects. After a successful try call,
the non-try Factory getPool fatal prefix has made two contract calls but has no
schema/store effect. Post-fatal execution and rollback are not modeled.

An updateFeeVars try_positions revert reaches neither fee-growth setter, but
the caller continues to Position.save and Snapshot. Position-save,
Transaction-save and Snapshot getter/save trap prefixes are recorded for both
hit and miss helper branches without claiming rollback or post-fatal effects.

## Store and relationship boundary

An accepted existing path has 25 effects on a Transaction hit or 26 on a miss;
when fee refresh reverts those counts are 23 or 24. A new path has 46, 47 or 48
effects for zero, one or two independently classified Transaction misses; the
fee-refresh-revert alternatives are 44, 45 or 46.

The accepted existing store order is
`Position, Transaction, PositionSnapshot`; the accepted new order is
`Transaction, Position, Transaction, PositionSnapshot`. Hit versus miss changes
only whether id is classified: the four common setters and Transaction save are
unconditional after the store-null branch. The two new-path loadTransaction
reads remain independent branch classifications because static WAT does not
prove whether the first save is visible to the second read.

The exact new-position field order is the first 14 Position effects, the first
Transaction helper and save, the final three Position effects, the local and
fee-refresh setters, and Position save. Snapshot then emits its first 13
effects, the second Transaction helper and save, its final three effects, and
the PositionSnapshot save.

The nine bound relations are Position.pool, token0, token1, tickLower,
tickUpper and transaction, plus PositionSnapshot.pool, position and
transaction. Receiver, decoded key, source-call path and matching save target
are bound; conversion results, aliases, persisted references, complete history
and last-writer behavior are not.

## Authority and use

The implementation base is commit
`5ad75eca9857176e9a9ecdfa6aeff6dd2a763312`, tree
`78ae066e45d0175f9efd858969c1d8dd8c968ac3`. Retained semantic artifacts remain
anchored to commit `42c6d01f2e719993e41fca9db51be55d33da734c`, tree
`ba8531df0e102ba71fd30b4df2af2977355dabf3`.

Transfer and Collect v2 supplied only repository layout and CI ordering
patterns. Their verifier modules, contracts, outputs and semantic claims are
not loaded as Liquidity authority.

Run:

```bash
python3 scripts/verify-uniswap-v3-npm-liquidity-v2.py --wasm2wat /path/to/wasm2wat
python3 -m unittest scripts.tests.test_uniswap_v3_npm_liquidity_v2
```

No issue #37 or #38 checkbox is completed by this certificate. See
[eligibility](docs/eligibility.md) for the claim boundary and
[provenance](docs/provenance.md) for direct inputs and regeneration authority.
