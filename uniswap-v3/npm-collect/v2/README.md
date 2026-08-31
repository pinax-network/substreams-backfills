# Uniswap V3 NPM Collect v2 certificate

This directory contains the complete path-qualified static schema-API effect
certificate for `NonfungiblePositionManager.handleCollect` across the eight
retained mainnet and Base ancestry segments and their six unique NPM WASMs.

The certificate is intentionally offline. It proves reachable retained-WAT
functions, direct calls, memory writes, schema constructor/setter sites, fixed
store targets, contract-call sites, traps, branch prefixes and segment diffs.
It does not prove imported values, arithmetic meaning, Graph store visibility
or persistence, rollback, entity histories, runtime parity, backfill or
production readiness.

## Exact scope

- 8 segment bindings and 6 unique retained NPM WASMs
- 299 schema outcomes per segment, 2,392 total
- 38 classified stored targets, 0 saved-no-setter fields, 13 derived query
  fields and 248 stored fields outside the Collect closure per segment
- 33 required-absence outcomes per segment: Collect 11, Flash 12 and
  TickHourData 10
- all 28 unordered segment-pair recursive diffs
- exactly three store targets: Position, PositionSnapshot and Transaction
- 40 lexical semantic constructor/setter effects for the no-amount profile and
  42 for each other profile
- maximum expanded new-path effects of 45 or 47 depending on profile
- nine relationship and Transaction identity paths
- exactly 304 path-bearing classified outcomes across all eight segments; all
  104 derived and 1,984 outside-closure outcomes have no setter path

The physical six-WASM totals are 539 reachable functions, 2,424 calls, 600
summed per-WASM distinct targets, 1,312 memory writes, 172 generic mapsets, 126
named setters, 17 store reads, 18 store writes, 12 `ethereum.call` sites, two
indirect calls, 220 abort callsites and 259 unreachable instructions. Weighted
over eight bindings, the corresponding totals are 725, 3,128, 798, 1,658, 216,
186, 21, 24, 16, two, 278 and 333.

Physical symbols are not semantic authority. Legacy compiler deduplication can
label Snapshot or Transaction operations with another schema class name;
current mappings use generic mapsets. Receiver flow, decoded field key, fixed
entity target and save path establish the field authority.

## Profile-specific handler edges

- `mainnet-root-correct-collect`: handler setter keys are
  `collectedFeesToken0`, then `collectedFeesToken1`; the visible call chains use
  amount0/token0 and amount1/token1 respectively.
- `mainnet-second-fee0-overwrite`: both handler setter sites target
  `collectedFeesToken0`; the second source chain still contains the fee1 getter
  and amount1/token1 conversion.
- `mainnet-no-collect-amounts`: the handler has no Token read and no collected-
  fee setter.
- `base-root-amount0-to-both`: both fee-field setter paths use the visible
  amount0/token0 conversion call chain.
- `current-amount0-to-both`: a non-null token0 store result reaches both
  setter paths; a null result skips both and continues.

These statements bind source/call/setter structure only. They do not claim that
`BigDecimal#plus`, decimal conversion or imported getters have any particular
numeric result.

## Prefix and helper order

The handler calls `getPosition`, returns on null, then compares Position.pool to
`0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248`. The excluded-pool return precedes
all handler fee setters, fee refresh, Position save and Snapshot construction.
Collect has no historical block guard.

On a missing Position, `getPosition` calls `try_positions`; a reverted result
returns null. A successful result is followed by the non-try Factory `getPool`
call. Its fatal branch occurs before any Position constructor, setter or store.
The accepted new path classifies all 17 Position fields and invokes
`loadTransaction` before Position.transaction.

`updateFeeVars` makes a second `try_positions` call. Its non-reverted branch
reaches feeGrowthInside0LastX128 then feeGrowthInside1LastX128 setters. Its
reverted branch reaches neither, but the caller continues to Position.save and
Snapshot construction.

The Snapshot order is ID, owner, pool, position, block number, timestamp,
liquidity, deposited0/1, withdrawn0/1, collected0/1, transaction,
feeGrowth0/1, then save. Its `loadTransaction` call precedes Snapshot.transaction
and both fee-growth fields.

`loadTransaction` first reads by the transaction-hash-derived key. Only the ID
initializer is inside the null/store-miss branch. On both a hit and a miss, the
helper then sets block number, timestamp, gasUsed and gasPrice and attempts the
Transaction save. A successful hit therefore has four field effects; a
successful miss has five. The six retained helper bodies are structurally
checked for this exact branch boundary, field order and save placement.

The new Position path can invoke this helper twice. The certificate independently
classifies each read as hit or miss; it does not infer that the first
`store.set` is visible to the second `store.get`. That uncertainty changes each
invocation's field-effect count by one, but not its successful store order.
Consequently, an accepted existing path always has
`Position, Transaction, PositionSnapshot` store order. A new path always has
`Transaction, Position, Transaction, PositionSnapshot`.

Within new `getPosition`, the first 14 Position effects precede the first
Transaction helper and its save; Position.transaction and the two fee-growth
effects follow it. Snapshot construction similarly places its first 13 effects
before the second Transaction helper and its save, then sets Snapshot.transaction
and the two fee-growth fields before the Snapshot save. The excluded-pool and
legacy missing-Token new-position prefixes therefore already contain 21 effects
on a Transaction hit or 22 on a miss, with one completed Transaction store call.
Trap-prefix records distinguish failures before and after each Transaction save;
they do not claim persistence or rollback behavior.

## Relationship boundary

The certificate binds Position.pool, token0, token1, tickLower, tickUpper and
transaction, plus PositionSnapshot.pool, position and transaction. It binds
receiver, key, source-call path and matching save target, not address/string
conversion results, aliases, persisted references or last-writer behavior.

## Authority and use

The implementation is based on local commit
`0398e6184dc07fe848fcfef4ecd04ac0b64e8ece`, tree
`ca82557bd179527369f527c1c114a2d3d5ae252e`. The retained semantic roots remain
anchored to canonical commit `42c6d01f2e719993e41fca9db51be55d33da734c`, tree
`ba8531df0e102ba71fd30b4df2af2977355dabf3`.

The preceding Transfer v2 slice supplied repository layout and CI ordering
only. No Transfer verifier, contract, generated output or semantic claim is a
Collect authority input.

Run:

```bash
python3 scripts/verify-uniswap-v3-npm-collect-v2.py --wasm2wat /path/to/wasm2wat
python3 -m unittest scripts.tests.test_uniswap_v3_npm_collect_v2
```

The committed contract is generated deterministically from retained artifacts.
No issue #37 or #38 checkbox is completed by this certificate.

See [eligibility](docs/eligibility.md) for the claim boundary and
[provenance](docs/provenance.md) for exact inputs and regeneration authority.
