# Messari V3 BSC + Base target baselines

This directory retains the exact deployed Graph artifacts for two related but
non-interchangeable targets:

- PancakeSwap V3 BSC `QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3`
- Uniswap V3 Base `QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh`

Both schemas contain 24 entities and 388 fields, but byte identity and the
writer contract differ. BSC uses Messari schema 4.0.0, a nine-argument Swap,
and `uint32` SetFeeProtocol inputs. Base uses schema 4.0.1, adds
`Network.BASE`, changes `PositionSnapshot` from `@regularPolling` to
`@hourlySnapshot`, uses a seven-argument Swap, and uses `uint8`
SetFeeProtocol inputs.

## Exact artifact boundary

`reference/` vendors every IPFS object reachable from both manifests: two
deployments, two schemas, fourteen target-local ABI references, and eight
mapping WASMs. Shared CIDs are intentionally retained under each target so
each closure is independently offline-verifiable. The provenance contract in
`docs/provenance/messari-v3-targets-v1.json` binds every path, CID, byte count,
SHA-256 digest, handler export, and manifest role.

The deployed BSC manifest contains a material handler mismatch. Its primary
Pool template declares `handleSetFeeProtocol`, but mapping `QmZ8ncas…` does
not export that function; only the separate `PancakeSwapPool` mapping
`QmZh9pwy…` does. Both targets also retain misspelled `LiqudityPool` template
entity metadata, plus duplicate `Token` entries in the primary Pool template.
The verifier must preserve these bytes and refuse attempts to normalize them.

Both manifests also retain nonexistent `mapping.entities` metadata. Factory
lists `_PricesUSD` and `_TokenTracker`; the primary Pool lists
`LiqudityPool`, `PoolDailySnapshot`, `_PricesUSD`, `_Account`,
`_DailyActiveAccount`, and `_TokenTracker`; and the fee-only template lists
`LiqudityPool`. `Protocol` is not in that missing set because it is a declared
schema interface. The machine contract binds the exact order, missing-name
inventory, and `Token: 2` multiplicity independently for BSC and Base.

## Source boundary

The strongest BSC source anchor is Messari commit `0c4618d…`; its fork-local
schema is byte-identical to the deployed v4.0.0 schema. The strongest Base
anchor is `2c60bd1…`; its fork-local schema is byte-identical and its Factory,
NPM, and Pool ABI files match after removing one repository trailing newline.

Neither anchor is a reproducible deployment workspace. The committed
templates say spec `0.0.2` while the deployed manifests say `0.0.4`, and both
Yarn/npm locks depend on the removed `edgeandnode/gluegun` repository at
`b34b900…`. Frozen installs fail. These commits are behavioral/source anchors,
not exact mapping-WASM reproduction claims.

## Readiness boundary

This is an immutable target/static-diff baseline only. Eligibility still
requires fresh same-pod 24-hour and 72-hour fastest-healthy-copy forecasts,
both greater than 28 days or non-converging. Implementation, runtime behavior,
Graph Store order, error behavior, logical/physical/VID/PoI parity, backfill,
deployment, production, and readiness remain false. Issues #85 and #94 stay
open.

Run the offline verifier and refusal suite with:

```console
python3 scripts/verify-messari-v3-targets.py
python3 -m unittest scripts.tests.test_messari_v3_targets
```
