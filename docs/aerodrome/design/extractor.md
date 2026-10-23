# Aerodrome Slipstream Base extractor Substreams: design

Date: 2026-10-20. This was a strictly read-only design pass: no commits, pushes, GitHub comments, kubectl writes or database writes. The only network activity was read-only Base RPC, Firehose and `gh api` probes, all listed in Appendix A.

Area: `substreams-backfills/aerodrome-slipstream-base/substreams/`, the parallel and cacheable **extractor** for Route A (decisions D1, D3, D4 and D5).

Target:
- Deployment `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`.
- Factory `0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a`, from block 13,843,704.
- NonfungiblePositionManager (NPM) `0x827922686190790b37229fd06084350e74485b72`, from block 13,843,719.
- spec 1.2.0, apiVersion 0.0.7, `nonFatalErrors`, a `Pool` template, no graft.

## Evidence labels

- **VERIFIED**: I read the code or bytes, or ran the probe myself in this pass. Probes are listed in Appendix A, and their values are recorded in §2.
- **REPORT-VERIFIED**: verified by a survey report, which is cited.
- **DOC**: documentation or a source comment says so; I did not trace the code.
- **ASSUMED**: a design assumption. Each one names the test or measurement that settles it.
- **ESTIMATE**: arithmetic on verified inputs.
- **OPEN**: needs a measurement or access that this pass did not have.

## Path abbreviations

- `SB/` is `/Users/denis/Github/substreams-backfills` at `bbe3783`.
- `V4/` is `scratchpad/ro/v4-subgraph`, the pinax-network/substreams-v4-subgraph snapshot.
- `ENG/` is `scratchpad/ro/engine` at `5c98b57`.
- `GN:` is graph-node `77823b5a` (v0.44.0), read with `git -C ~/.cargo/git/db/graph-node-40979021f9daae1a show 77823b5a:<path>`.
- `SLIP@37eead2c7e:` is aerodrome-finance/slipstream at commit `37eead2c7e5302a204dec78bfa0775bbb8ff48a2`, fetched with `gh api` into `scratchpad/slipstream-src/`.
- `SEC:` is `~/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/substreams-ethereum-core-0.11.1/src`.
- `SS7:` is `…/substreams-0.7.6/src`, and `SS/` is `~/Github/substreams` at v1.22.0.
- `FHETH:` is streamingfast/firehose-ethereum `main`. I read `substreams/rpccalls.go` (last commit `3858e8b14d`, 2026-10-02), `cmd/fireeth/tools_convert_to_v5_block.go` and `CHANGELOG.md` through `gh api` into `scratchpad/fheth-src/`.
- `ALLOY:` is alloy 2.0.5 crates, which are graph-node v0.44's lockfile versions, extracted from `~/.cargo/registry/cache` into `scratchpad/crates-src/`.
- `RED` is the companion reducer design, `scratchpad/design/reducer.md`. `SYN` is `scratchpad/survey/SYNTHESIS.md`. `TARGET` is `scratchpad/survey/aerodrome-target.md`.

---

## 0. Decisions on one page

1. **Role.** The extractor emits **facts**:
   - every candidate log that Graph Node v0.44 could turn into an Aerodrome trigger, raw and in Graph Node processing order `(wave, source_trigger_order)`;
   - the transactions those logs belong to;
   - the PoolCreated facts;
   - an end-of-block answer for every contract call the deployed mappings can make (C1–C9).

   The reducer (D3) applies every Graph Node semantic: ABI matching and decoding, host set, handlers and fallbacks. This matches the reducer's input contract field for field (RED §4.1). The extractor adds only extension fields at tags ≥ 10, and the reducer may ignore them (§6.1).
2. **Wave model.** Wave = 0 for the Factory, the NPM and pools created in an earlier block. Wave = 1 for logs of pools created **in this block**, including logs that precede their own `PoolCreated`.
   - This is VERIFIED against Graph Node and on chain. In block 13,899,663, `Initialize` (log 171) precedes `PoolCreated` (172) and the pool's `Mint` (176) is in wave 1 after the wave-0 NPM `Transfer` (177) and `IncreaseLiquidity` (178).
   - Wave 2 cannot occur: only the Factory mapping calls `dataSource.create`.
3. **Call answers come from storage, not RPC (D5).** End-of-block value = the **last non-reverted storage change in the block, else the carried value**. "Non-reverted" means a successful transaction and `call.state_reverted == false`. Storage keys are classified with Firehose `keccak_preimages`.
   - The CLPool, Tick.Info, NPM `_positions` / `_poolIdToPoolKey` and CLFactory `getPool` layouts are **pinned and VERIFIED** with `eth_getStorageAt` and `eth_call` on Base (§2.3–§2.6).
   - The derivation rule is VERIFIED against `eth_call` on 6 blocks across Firehose block versions 4 and 5. That includes:
     - a fee-growth write inside a reverted call of a successful tx (30,000,000);
     - mixed in-block/carried tick words (45,000,000 and 34,719,819);
     - carried NPM fee-growth (34,719,819);
     - mint-and-burn and burn-in-block reverts (52,800,000 and 34,719,819).
4. **Carry lives in Substreams Stores**, which are built once by the noop from 13,843,704, so both root replays and seeded runs see exact values. Store layout:
   - `store_pools`;
   - `store_pool_slots` (fee growth, NPM pool keys);
   - 8 tick shards;
   - 16 position shards.

   At head the largest family is positions, with 25.7 M live NFTs, about 3.6 GB in total and about 225 MB per shard (ESTIMATE §8.4). That is under the 3.5 GiB per-store limit with more than 10× headroom per shard.
5. **ERC20 metadata (C1–C4)** is the **only** `eth_call` in the package. It lives in its own binary (`rpc`) and module (`map_token_metadata`). It runs for both tokens of every `PoolCreated`, which is a superset: about 7.3 k tokens × 4 selectors over the whole history.
   - The output is raw `Null | Value(bytes)` with Graph Node's revert rules.
   - Send `X-substreams-acknowledge-non-deterministic: true`.
   - Audit every answer against an independent archive before the backfill (G6).
6. **C10 must be emitted.** The deployed `addMissingWhitelistedPools` calls `getPool(USDC, token, {100,500,3000,10000})` in that order for a zero-version token other than USDC. Although its getter-copy mutations are discarded, the host calls remain required input facts. The extractor supplies a conservative superset for both registered tokens on every decoded Swap, using end-of-block `store_pools`; only the reducer knows token version. Full M2 call coverage has no C10 exception. The old omission produced 44 missing calls in the retained 75,959-block live attempt despite frame parity, and is a qualification blocker.
7. **Toolchain** (VERIFIED in V4):
   - Rust 1.90.0, `substreams =0.7.6`, `substreams-ethereum =0.11.1`, `prost =0.13.5`, `ethabi =17.2.0`;
   - `getrandom =0.2.16` with `custom`, Substreams CLI v1.20.3 with sha256 `90c71d04…f8675`;
   - a standalone workspace excluded from the root workspace;
   - `build.rs` Abigen from `../reference/abis`, with the ABI sha256 values asserted against the CID-locked provenance;
   - Rust-only tooling through `cargo xtask aerodrome-substreams …`.
8. **Freeze.**
   - Five binaries keep the cache boundaries independent.
   - The build is reproducible with `--remap-path-prefix` and is checked twice in CI.
   - Release bytes are committed with a JSON lock and published as an immutable release `aerodrome-slipstream-base-extractor-vX.Y.Z`.
   - **Nothing is tagged until the G4 differential against the mapping-host oracle passes.**

---

## 1. Inputs read

| Input | What I took from it |
|---|---|
| `SYN` §0–§9, `TARGET` (all), `survey/{v4-substreams-pattern,substreams-reuse,engine-contract,v3-lane-state,token-api-noop-pattern}.md` | call kinds C1–C10, quirks, decisions, V4 pattern, engine transport |
| Engine audit `tasks/wathbfgwg.output` `.result.kept[]` (31 findings) | F6: `substreams-native` never requests final blocks only. F2/F3: legacy-v1 end-of-range proof. Both affect how the extractor's output is consumed (§10). |
| `RED` §0, §4, §5.5–5.6, §10, §14.5–§16 | the reducer's input proto, which this design adopts, plus its fixture names and coordination items |
| `V4/` `rust-toolchain.toml:1-5`, `Cargo.toml:11-32`, `buf.gen.yaml:1-10`, `build.rs:8-61`, `substreams.yaml:1-35`, `src/lib.rs:13-21`, `src/config.rs:25-127`, `src/extract.rs:8-60,137-181`, `src/metadata.rs:21-149`, `store-tick-shards/src/lib.rs:23-37`, `store-probe/src/lib.rs:221-222`, `.github/workflows/parity.yml:21-22` | pins, patterns, the 30-input limit, sharding |
| `SB/` `Cargo.toml:1-10`, `.cargo/config.toml`, `mapping-host/src/{runner.rs:1-37,822-998, block.rs:1-305, calls.rs:1-130}`, `uniswap-v3/source/src/storage/{utils.rs,uniswap_v3_pool.rs,position_manager.rs}`, `uniswap-v3/fixtures/blocks.lock.json`, `xtask/src/{main.rs,fixtures.rs}`, `aerodrome-slipstream-base/{README.md,QmasYjyp….yaml,reference/abis/*}`, `docs/provenance/aerodrome-slipstream-base-target.json` | repo conventions, oracle, fixture locks |
| `GN:` `core/src/subgraph/runner/mod.rs:914-995`, `chain/ethereum/src/{data_source.rs:440-475,690-835, codec.rs:97-133,146-470,475-620,622-700,863-876, trigger.rs:364-404,515-615, runtime/abi.rs:500-557, runtime/runtime_adapter.rs:298-410, ethereum_adapter.rs:596-702,1539-1568, call_helper.rs:17-145}` | trigger, wave, transaction and eth_call semantics |
| `ALLOY:` `alloy-eips-2.0.5/src/eip1559/helpers.rs:14-27`, `alloy-network-2.0.5/src/any/unknowns.rs:100-200`, `alloy-consensus-2.0.5/src/transaction/{legacy.rs:278,eip1559.rs:198}`, `alloy-rpc-types-eth-2.0.5/src/transaction/mod.rs:409` | effective gas price |
| `SLIP@37eead2c7e:` `contracts/core/{CLPool.sol,CLFactory.sol,libraries/Tick.sol,libraries/TickBitmap.sol}`, `contracts/periphery/{NonfungiblePositionManager.sol,libraries/PoolAddress.sol}`, `script/constants/output/DeployCL-Base.json` | storage layouts and the deployment map |
| `SEC:` `block_view.rs:7-10`, `rpc.rs:75-80`, `pb/sf.ethereum.type.v2.rs` (Call, StorageChange, TransactionTrace, DetailLevel) | Firehose model and the Substreams API |
| `SS7:` `store.rs:76-91,287-291,855-900` | store API: `get_last` / `get_first` semantics, `delete_prefix` |
| `FHETH:` `substreams/rpccalls.go:94-135,503-653`, `cmd/fireeth/tools_convert_to_v5_block.go:548-688`, `CHANGELOG.md` v2.24.0 | eth_call block ref and gas, `failed` classification, v5 preimage filter |
| `SS/` `ENVIRONMENT_VARIABLES.md:72-89`, `service/{utils.go:11-19,validate.go:107-128}`, `docs/release-notes/change-log.md:671` | eth_call determinism switches and the acknowledgement header |

---

## 2. Pinned facts (each with evidence)

### 2.1 Deployment identity

| Fact | Value | Evidence |
|---|---|---|
| Factory deployed in block | 13,843,704. `eth_getCode` returns `0x` at 13,843,703 and code at 13,843,704. | VERIFIED (P1) |
| NPM deployed in block | 13,843,719. `0x` at 13,843,718, code at 13,843,719. | VERIFIED (P1) |
| Consequence | Every storage write of the Factory, the NPM and every pool happens at or after the module `initialBlock` 13,843,704, so carried values start at the empty state. No storage seed is needed. | ESTIMATE from the above |
| Pool implementation | `0xec8e5342b19977b4ef8892e02d8daecfa1315831`. `Factory.poolImplementation()` and `DeployCL-Base.json` agree. | VERIFIED (P2) |
| Pools are EIP-1167 clones | Runtime code is `363d3d373d3d3d363d73ec8e5342…5af43d82803e903d91602b57fd5bf3` for pool `0x98c7a233…7bda97`. The creation frame (CREATE2, `call_type` 5) carries `code_changes[0].new_code` with these exact bytes. | VERIFIED (P2, P6) |
| First PoolCreated | Block 13,899,663, tx `0x76aeccc2…c257a7` (index 55), pool `0x98c7a2338336d2d354663246f64676009c7bda97`, USDC/USDbC, tickSpacing 1 | VERIFIED (P6) |
| Pools at head | `allPoolsLength()` = 3,660 at latest; 1,490 at 34,700,000 | VERIFIED (P3) |
| Enabled tick spacings (O9) | `tickSpacings()` = `[1,50,100,200,2000,10]`. `tickSpacingToFee`: 1→100, 10→500, 50→500, 100→500, 200→3000, 2000→10000. The constructor enables five (`CLFactory.sol:58-62`); spacing 10 was added later. | VERIFIED (P3) |
| NPM `_nextId` / live NFTs | 34,700,000: nextId 23,616,552, `totalSupply` 1,178,026, nextPoolId 1,472. 52,860,000: nextId 79,140,907, totalSupply 25,696,195, nextPoolId 3,081. Also @20M: 38,054 live; @30M: 444,639 live / 13,220,431 minted; @40M: 4,657,348 live. | VERIFIED (P4) |
| Hot-fix guard addresses | `0x8fe8d9bb…8248` and `0x9663f2ca…0454` have no code on Base, so they are never Aerodrome pools | VERIFIED (P5) |

### 2.2 Slipstream source pin

- **Pinned commit: `37eead2c7e5302a204dec78bfa0775bbb8ff48a2`**, "deploy: add base deployment addresses (#5)", 2024-05-04. It changes only `README.md` and `script/constants/output/DeployCL-Base.json`. That file records `PoolFactory 0x5e7B…809A`, `NonfungiblePositionManager 0x8279…5b72` and `PoolImplementation 0xeC8E…5831` (VERIFIED `gh api`).
- `contracts/core/CLPool.sol` last changed at `3c6f10b841` ("revert oracle changes", 2024-04-24).
  - The commits between that and `37eead2c7e` touch only `SugarHelper`, `TickLens`, `CLGauge` and docs (VERIFIED `gh api …/commits/<sha>` file lists).
  - The deployment (block 13,843,704, about 2024-04-30) therefore ran this exact core and periphery source, as far as git can show.
- Bytecode-level confirmation does not come from compiling. It comes from the storage-layout cross-checks in §2.3–§2.6, where every slot was read on chain and matched `eth_call`. That is the property the extractor depends on.
- **Invariant used:** every pool the Factory creates is a clone of the pinned implementation. `map_pools_created` checks the CREATE2 frame's `code_changes`, so a non-clone pool raises anomaly `POOL_NOT_PINNED_CLONE` (§8.8).

### 2.3 CLPool storage (`SLIP@37eead2c7e:contracts/core/CLPool.sol:41-116`)

Solidity 0.7.6 packing. Immutables do not apply because clones keep their constants in storage.

| Slot | Variable | Packing | Used by the extractor |
|---|---|---|---|
| 0 | `factory` | address | – |
| 1 | `token0` | address | – |
| 2 | `token1` | address | – |
| 3 | `gauge` | address | – |
| 4 | `nft` | address | – |
| 5 | `factoryRegistry` | address | – |
| 6 | `slot0` | sqrtPriceX96 [0,160) · tick int24 [160,184) · observationIndex [184,200) · cardinality [200,216) · cardinalityNext [216,232) · unlocked [232,240) | – |
| **7** | **`feeGrowthGlobal0X128`** | uint256 | **C5** |
| **8** | **`feeGrowthGlobal1X128`** | uint256 | **C5** |
| 9 | `rewardGrowthGlobalX128` | uint256 | – |
| 10 | `gaugeFees` | token0 uint128 low · token1 uint128 high | – |
| 11–14 | `rewardRate`, `rewardReserve`, `periodFinish`, `rollover` | uint256 each | – |
| 15 | `stakedLiquidity` uint128 [0,128) · `lastUpdated` uint32 [128,160) · `tickSpacing` int24 [160,184) | | – |
| 16 | `liquidity` uint128 low · `maxLiquidityPerTick` uint128 high | | – |
| **17** | **`ticks`** `mapping(int24 => Tick.Info)` | base = `keccak256(int256(tick) ‖ uint256(17))` | **C6/C7** |
| 18 | `tickBitmap` `mapping(int16 => uint256)` | | – |
| 19 | `positions` `mapping(bytes32 => Position.Info)` | 4 words | – |
| 20 … 20+65534 | `observations[65535]` | 1 word each | – |

Evidence (VERIFIED):
- **P6, block 13,899,663, pool `0x98c7…`.** The `initialize` storage writes hit slots 0, 1, 2, 5, 6, 15, 16 and 20. Slot 15 is `0x…0001 << 160`, so tickSpacing is 1 at bits [160,184). The tick-word preimages `a69f8edf…adb0` and `17bc176d…b552` decode as `int24(-1) ‖ 0x11` and `int24(1) ‖ 0x11`.
- **P7, block 30,000,000, pool `0xb2cc224c…dc59`.**
  - `eth_call feeGrowthGlobal0X128()` = 302006723195575536357211854799322975866331 = `eth_getStorageAt(slot 7)`.
  - `feeGrowthGlobal1X128()` = 776673960782178093312624643633125 = slot 8.
  - `slot0()` = (3841193488139233915095318, −198697, 808, 2000, 2000, true), which decodes from slot 6 with the packing above.
  - `tickSpacing()` = 100, from slot 15 bits [160,184).
  - `gaugeFees()` = (46246524944672395490, 112881782449), from slot 10 low and high.
- **Classification completeness (P10).** Every storage write by a pool address in blocks 13,899,663, 30,000,000 and 52,800,000 classified into exactly the rows above: fixed slots 0–16, observations, ticks m0–m5, bitmap m0 and positions m0–m3. There were **zero** unclassified pool writes.

### 2.4 `Tick.Info` packing (`SLIP@37eead2c7e:contracts/core/libraries/Tick.sol:17-44`)

| Word (base + k) | Contents | `ticks()` tuple index | Consumed by the mapping |
|---|---|---|---|
| 0 | liquidityGross uint128 [0,128) · liquidityNet int128 [128,256) | value0, value1 | no (handlers compute these from events) |
| **1** | **stakedLiquidityNet int128 [0,128)** (two's complement; bits [128,256) are zero) | **value2** | **yes**: mapping writes it to `Tick.feeGrowthOutside0X128` (quirk, TARGET §5.4) |
| **2** | **feeGrowthOutside0X128 uint256** | **value3** | **yes**: written to `Tick.feeGrowthOutside1X128` |
| 3 | feeGrowthOutside1X128 uint256 | value4 | no |
| 4 | rewardGrowthOutsideX128 uint256 | value5 | no |
| 5 | tickCumulativeOutside int56 [0,56) · secondsPerLiquidityOutsideX128 uint160 [56,216) · secondsOutside uint32 [216,248) · initialized bool [248,256) | value6..value9 | no |

- **VERIFIED (P7).** Pool `0xb2cc…`, tick −198700, block 30,000,000, base `0xb1a28025…4b20`. All 10 `ticks(int24)` outputs decoded exactly from words 0–5: gross 5893985654394835885, net −5850383973396166343, **staked −5842778663056454790**, **fgo0 132648128379994546467065667425488280877453**, fgo1, rgo, tickCumulative −2377977434424, splo, secondsOutside 1726573351, initialized true.
- A tick is "uninitialized" iff word 0 == 0. Clearing does `delete self[tick]` (`Tick.sol:212-214`), which zeroes all six words.
- Every initialized tick is a multiple of the pool's `tickSpacing`: `TickBitmap.flipTick` requires `tick % tickSpacing == 0` and runs on every initialization (`TickBitmap.sol:23-24`, `CLPool.sol:427-430`). VERIFIED by source.

### 2.5 NPM storage (`SLIP@37eead2c7e:contracts/periphery/NonfungiblePositionManager.sol:31-79`)

| Slot | Variable | Notes |
|---|---|---|
| 0–10 | ERC165/ERC721/ERC721Permit internals | Not classified. Slot 2 is the `_tokenOwners._entries` length and slot 10 changes inside txs. Both are ignored. |
| 11 | `_poolIds` `mapping(address => uint80)` | – |
| **12** | **`_poolIdToPoolKey` `mapping(uint80 => PoolKey{address token0; address token1; int24 tickSpacing})`** | word 0 = token0; word 1 = token1 [0,160) · tickSpacing int24 [160,184) |
| **13** | **`_positions` `mapping(uint256 => Position)`** | word 0 = nonce uint96 [0,96) · operator [96,256); **word 1 = poolId uint80 [0,80) · tickLower int24 [80,104) · tickUpper int24 [104,128) · liquidity uint128 [128,256)**; **word 2 = feeGrowthInside0LastX128**; **word 3 = feeGrowthInside1LastX128**; word 4 = tokensOwed0 low · tokensOwed1 high |
| 14 | `_nextId` uint176 [0,176) · `_nextPoolId` uint80 [176,256) | |
| 15, 16 | `owner`, `tokenDescriptor` | |

- `positions(tokenId)` reverts with `"ID"` iff `poolId == 0` (`:115`), and token0, token1 and tickSpacing come from `_poolIdToPoolKey[poolId]` (`:116`).
- Writers of words 2 and 3: `mint` (`:185-198`), `increaseLiquidity` (`:267-268`), `decreaseLiquidity` (`:329-330`) and `collect` (`:392-393`). Each emits its NPM event in the same frame. `burn` deletes the struct (`:423`).

Evidence (VERIFIED):
- **P6, block 13,899,663.** Keys `d421a518…8b5c` and `…8b5d` are `keccak(1,12)` + {0,1}: token0 = USDC, word 1 = `…01 ‖ d9aaec86…` (tickSpacing 1, USDbC). Key `fd54ff1e…93c6` is `keccak(1,13)+1`: poolId 1, tickLower `0xffffff` (−1), tickUpper 1, liquidity 199,994,998. `eth_call positions(1)` at 13,899,663 returns the same.
- **P8, block 30,000,000, tokenId 13220430.** Ticks 111000/111200 and fgi0/fgi1 1122863285023397868178891954602503 / 78478033439045865859981565402700459382 were derived from in-block writes and equal `eth_call`.
- **P8, block 52,800,000.** tokenIds 78901049, 78901050, 78901051, 69679819, 66565898, 73223729 and 76596028 have derived tick fragments equal to `eth_call`. tokenId **78901048** was minted and burned in the same block: the derived poolId is 0 and `eth_call` reverts.
- **P9, block 34,719,819.** tokenIds 23666543, 23372431 and 22397417 had no in-block write to words 2 or 3. `eth_call` fields 8 and 9 equal `eth_getStorageAt(B−1)`; 22397417's values are about 2^256, i.e. full uint256. tokenId **23665747** was burned in-block (tx `0xa8926ee2…a6e3`: Collect, Decrease, Collect, Transfer→0), so `eth_call` at B reverts `"ID"` and at B−1 returns a value.

### 2.6 CLFactory storage (`SLIP@37eead2c7e:contracts/core/CLFactory.sol:16-46`), used only for audits

| Slot | Variable |
|---|---|
| 0–3 | `owner`, `swapFeeManager`, `swapFeeModule`, `unstakedFeeManager` |
| 4 | `unstakedFeeModule` [0,160) · `defaultUnstakedFee` uint24 [160,184) |
| 5 | `tickSpacingToFee` |
| **6** | **`getPool` `mapping(address => mapping(address => mapping(int24 => address)))`**, written in both orders in `createPool` (`:91,93`) |
| 7 | `_isPool` |
| 8 | `allPools` (length; elements at `keccak(8)+i`) |
| 9 | `_tickSpacings` |

- VERIFIED (P6). Block 13,899,663 writes slot 8 (0→1), `keccak(8)` (pool), `keccak(pool,7)` (true), and both getPool slots computed with slot 6: `0x1dac6d56…`, `0x7d1b1c4b…`.
- VERIFIED (P11). `eth_call getPool(USDC, USDbC, 1)` and `getPool(USDbC, USDC, 1)` = `0x98c7…` at 13,899,663, the **creation block itself** (end-of-block semantics), and `0x0` at 13,899,662.
- The extractor answers `getPool` from the `PoolCreated` registry. This is D5, and it is exact: the only writer of `getPool` is `createPool`, which emits `PoolCreated` in the same frame. Storage slot 6 serves only as an audit cross-check in `map_slot_audit`.

### 2.7 Firehose Base data model

| Fact | Evidence |
|---|---|
| Blocks are `DETAILLEVEL_EXTENDED` (`detail_level` 0), carrying `calls[].storage_changes`, `keccak_preimages`, `state_reverted` and `code_changes` | VERIFIED (P6, P12). `SEC:pb/sf.ethereum.type.v2.rs:127-131` gives the enum. |
| **Block version boundary**: `ver = 4` for 13,843,704 … **45,903,999**; `ver = 5` from **45,904,000** | VERIFIED (P12, binary search with `firecore tools firehose-client`) |
| v5 keeps only preimages of ≤256 bytes that explain a storage slot written in the same transaction ("largest hash at or below the key, within 2^64"). Struct-member slots (base + k) therefore keep their base preimage. | VERIFIED: `FHETH:cmd/fireeth/tools_convert_to_v5_block.go:548-688`; `CHANGELOG.md` v2.24.0. Also checked empirically: the tick m1/m2 and position m1–m3 writes in v5 block 52,800,000 all classified (P10). |
| v5 removes storage changes whose old == new value | VERIFIED `CHANGELOG.md` v2.24.0. v4 tracer blocks also showed no no-op writes in P6 (`feeGrowthOutside` writes of 0 absent). The algorithm is indifferent either way (§8.3). |
| Receipt logs of **failed** txs are empty; their call logs are state-reverted | VERIFIED: 13,899,663 has 4 failed txs, 0 receipt logs and 12 reverted call logs; 52,800,000 likewise (P13) |
| A **successful** tx's receipt logs exclude logs of state-reverted inner calls | VERIFIED: 52,800,000 tx `0x3b879426…5d92` has 19 receipt logs = 19 non-reverted call logs; its 4 reverted-call logs have no `blockIndex` (P13) |
| `Log.blockIndex` of receipt logs is dense 0..n−1 and equals RPC `logIndex` | VERIFIED. 13,899,663: 209 logs, 0..208, and tx 55's logs are 171..178 = RPC `0xab..0xb2`. 52,800,000: 2,631 logs, 0..2630, and tx 22's logs are 104..122 = RPC `0x68..0x7a` (P13). |
| **`Log.index` (tx-local) counts reverted-call logs in v5**, so it skips numbers | VERIFIED: tx `0x3b87…` has indices 0,1,2,3,8,…,22 (P13). **Never use `Log.index`.** |
| Receipt log order within a tx is ordinal order; call-iteration order is not | VERIFIED (P13). Use `receipt.logs`, never `logs_with_calls()`. |
| In a clone's DELEGATECALL frame, `call.address` = implementation, `call.caller` = clone, and `storage_changes[].address` = clone | VERIFIED (P6: calls 5 and 10 of tx 55) |
| Deposit transactions have type 126, `gas_price` absent, gas_limit 1,000,000, from `0xdeaddead…0001`, to `0x4200…0015` | VERIFIED at 13,899,663 and 52,800,000, index 0 (P14) |
| Types seen: 0, 1, 2, 4, 126. For every type-2/4 tx in 5 blocks (1,565 txs), `trace.gas_price` == the alloy effective price computed from max fees and the header base fee. | VERIFIED (P14) |
| `block.system_calls` exists in v5 | VERIFIED (key list of 52,800,000). None touch Aerodrome contracts (ASSUMED; G2 asserts it). |

### 2.8 Graph Node v0.44 semantics the extractor reproduces

| Rule | Source (VERIFIED) |
|---|---|
| A log trigger's `log_index` is `Log.block_index`; `transaction_index` is `trace.index` | `GN:chain/ethereum/src/codec.rs:103-131` (`:124`) |
| Receipts come from **all** traces, and logs from `receipt.logs` | `GN:codec.rs:584-593, 622-680` |
| Logs are ordered by `log_index` | `GN:chain/ethereum/src/trigger.rs:364-404` (`:381-382`) |
| Dynamic data sources are created during a block. The **same block** is rescanned for the new hosts, and their triggers run in a later wave (breadth-first, in host creation order). | `GN:core/src/subgraph/runner/mod.rs:914-995`; reproduced in `SB/mapping-host/src/runner.rs:11-23, 873-917` |
| Data-source gate: the address must match, then `start_block > block.number` means no match. Dynamic sources start at their creation block. | `GN:chain/ethereum/src/data_source.rs:690-702` |
| ABI decode failure means "no handler", not an error | `GN:data_source.rs:745-774` |
| The event's transaction is found by hash in the block | `GN:data_source.rs:793-808` |
| Mapping-visible transaction fields: `hash, index, from, to, value, gasLimit, gasPrice, input, nonce` (`AscEthereumTransaction_0_0_6`). The mapping reads hash `d[0]`, from `d[2]` (origin), gasLimit `d[5]` (→ `Transaction.gasUsed`), gasPrice `d[6]`, block number `c[7]` and timestamp `c[10]`. | `GN:chain/ethereum/src/runtime/abi.rs:540-557`; `scratchpad/aero-wasm/Pool.annot.dcmp:3821-3913` |
| `gasPrice = tx.effective_gas_price(header.base_fee_per_gas)` | `GN:trigger.rs:556-558`; base fee from header `GN:codec.rs:494-497` |
| Known types {0,1,2,3,4} use alloy envelopes. Any other type, including **126 OP deposit**, becomes `UnknownTxEnvelope` with fields `gasPrice` = `trace.gas_price` or 0, `gas` = `trace.gas_limit`, `from`, `to`. Its effective price is the `gasPrice` field, i.e. **0 for deposits**. | `GN:codec.rs:177-253`; `ALLOY:alloy-network-2.0.5/src/any/unknowns.rs:163-177` |
| 1559/4844/7702: `calc_effective_gas_price(max_fee (or gas_price), max_prio (or 0), base_fee)`. Legacy/2930: `gas_price`. | `GN:codec.rs:259-271`; `ALLOY:alloy-eips-2.0.5/src/eip1559/helpers.rs:14-27`; `…/legacy.rs:278` |
| `to()` is None for contract creation (`trace.to` empty, or call[0] is CREATE) | `GN:codec.rs:863-876` |
| `eth_call` is pinned to the block **hash** (EIP-1898) | `GN:ethereum_adapter.rs:596-602, 664-704`; `runtime_adapter.rs:298-410` |
| Revert = RPC error matching the revert vocabulary, **or** an empty `0x`, **or** an output decode failure | `GN:call_helper.rs:43-119`; `ethereum_adapter.rs:1539-1568` |

---

## 3. Workspace, toolchain and build

### 3.1 Tree

```text
aerodrome-slipstream-base/substreams/            # standalone cargo workspace (excluded from SB root)
  Cargo.toml                                      # [workspace] members = ["crates/*"]; resolver = "2"
  Cargo.lock                                      # committed; every cargo call uses --locked
  rust-toolchain.toml                             # channel 1.90.0; clippy, rustfmt; wasm32-unknown-unknown; minimal
  buf.gen.yaml                                    # V4 plugins (neoeinstein-prost v0.4.0, prost-crate v0.4.1)
  substreams.yaml                                 # package aerodrome_slipstream_base_extractor v0.1.0 (§5.2)
  README.md, AGENTS.md                            # cache/freeze rules (§13), never-rebuild-between-noop-and-backfill
  proto/pinax/aerodrome/slipstream/base/v1/extractor.proto          # public output (§6.1)
  proto/pinax/aerodrome/slipstream/base/internal/v1/internal.proto  # inter-module + store values (§6.2)
  crates/
    pb/        aerodrome-extractor-pb      lib  prost =0.13.5 only; checked-in src/pinax.*.rs ("@generated", drift-checked)
    core/      aerodrome-extractor-core    lib  pure Rust: layout, classifier, carry ops, keys, shards, windows,
                                                calldata, gas price, raw decoders. deps: pb, tiny-keccak =2.0.2.
                                                NO substreams dep → also used by the reducer (D3) and xtask.
    extract/   aerodrome-extractor-extract cdylib+rlib  map_pools_created, map_candidates, map_storage_deltas
                                                build.rs Abigen (§4)
    stores/    aerodrome-extractor-stores  cdylib+rlib  store_pools, store_pool_slots, store_tick_slots_00..07,
                                                store_position_slots_00..15, store_pool_last_tick
    rpc/       aerodrome-extractor-rpc     cdylib+rlib  map_token_metadata (the ONLY crate importing rpc.eth_call)
    answers/   aerodrome-extractor-answers cdylib+rlib  map_tick_answers, map_position_answers, map_extractor_block
    audit/     aerodrome-extractor-audit   cdylib+rlib  map_slot_audit (oracle windows only; not an ancestor of
                                                map_extractor_block)
  fixtures/
    blocks.lock.json            # pinax.substreams-backfills.evidence-assets/v1, release tag block-fixtures-base-v1
                                # (shared with the mapping-host Aerodrome oracle bundle, PR-S2)
    carry/<block>.json          # carry seed at B−1 for every answer key (captured with eth_getStorageAt)
    oracle/<block>.json         # eth_call answers at B (block hash) for every answer key
    goldens/<block>.json        # canonical JSON of the expected ExtractorBlock
  packages/aerodrome-slipstream-base-extractor-vX.Y.Z.json   # release lock (added by the freeze PR only)
  release/vX.Y.Z/*.spkg                                         # committed certified bytes (freeze PR only)
```

Root-repo edits:
- `SB/Cargo.toml:10`: append `"aerodrome-slipstream-base/substreams"` to `exclude`. The root pins `substreams 0.6` / `substreams-ethereum 0.10` (`SB/Cargo.toml:18-19`), and mixing would break the build (VERIFIED).
- New subcommand `cargo xtask aerodrome-substreams …` (§11.6).
- New workflow `.github/workflows/ci-aerodrome-slipstream-base.yaml`, modelled on `ci-uniswap-v4.yaml`, with a `dorny/paths-filter` gate on `aerodrome-slipstream-base/**` and `xtask/**`.
- No `.py`, `.sh` or `.mjs` files are added (Rust-only policy).

### 3.2 Pins (VERIFIED against `V4/rust-toolchain.toml:1-5` and `V4/Cargo.toml:11-32`)

```toml
[workspace.dependencies]
prost = "=0.13.5"
prost-types = "=0.13.5"
substreams = "=0.7.6"
substreams-ethereum = "=0.11.1"
ethabi = "=17.2.0"
tiny-keccak = { version = "=2.0.2", features = ["keccak"] }
serde = { version = "=1.0.228", features = ["derive"] }
serde_json = { version = "=1.0.142", features = ["arbitrary_precision"] }
anyhow = "=1.0.98"            # build-dependency only
thiserror = "=2.0.12"

[target.'cfg(target_arch = "wasm32")'.dependencies]   # in each cdylib crate
getrandom = { version = "=0.2.16", features = ["custom"] }

[profile.release]
lto = true
codegen-units = 1
strip = true
panic = "abort"
```

- Substreams CLI v1.20.3 (`substreams_linux_x86_64.tar.gz`), sha256 `90c71d04a75490efdf0493254a8563c3555690e622b3c6ade5100c0c773f8675`. VERIFIED in `V4/.github/workflows/parity.yml:21-22`.
- `substreams-ethereum 0.12` / `substreams 0.8` / buffa must not be mixed in (`survey/substreams-reuse.md` §3.1).
- `pb` and `core` carry no `substreams*` dependency. The reducer (root workspace, `prost "0.13"` resolving to 0.13.5) can path-depend on them. Neither crate uses workspace inheritance, so a path dependency from the root workspace resolves cleanly.
- ASSUMED: settled by the PR-X1 CI job building `cargo check -p aerodrome-slipstream-reducer` against them.

### 3.3 Reproducible builds

- `cargo xtask aerodrome-substreams build` exports `RUSTFLAGS="--remap-path-prefix=$REPO=/src --remap-path-prefix=$CARGO_HOME=/cargo --remap-path-prefix=$RUSTUP_HOME=/rustup"`. It builds `--locked --release --target wasm32-unknown-unknown` and prints each `.wasm` sha256.
- `build --twice` copies the workspace into two different temporary roots, builds both, and **fails if any wasm sha256 differs**. This removes the "host builds embed paths" trap from `V4/AGENTS.md:56-59`.
- ASSUMED: settled by the PR-X1 CI step. If it fails, fall back to the V4 rule: only CI-built bytes are certified.

---

## 4. `build.rs` Abigen (crate `extract`)

```rust
// crates/extract/build.rs
const ABI_DIR: &str = "../../../reference/abis";
// sha256 pinned by docs/provenance/aerodrome-slipstream-base-target.json (VERIFIED: Factory 7dac7fd7…,
// Pool 46588c2f…, NonfungiblePositionManager 6109c87c…). The build fails on drift.
const ABIS: [(&str, &str, &str, &[&str]); 3] = [
    ("factory", "Factory.json", "7dac7fd7c4ff807498cb7dcbf503474d13b1207852bb8b2b3687a7e8cfb6d979", &["PoolCreated"]),
    ("pool", "Pool.json", "46588c2f4ad0b91f64e7b43b03190c5422d3f46f2759c53412a3f3279f816760",
        &["Initialize", "Swap", "Mint", "Burn", "Flash"]),
    ("npm", "NonfungiblePositionManager.json", "6109c87c3dfd051c5fa283e71463d29d4c31a40339223ea3015ea0bcdd602c00",
        &["IncreaseLiquidity", "DecreaseLiquidity", "Collect", "Transfer"]),
];
fn main() -> anyhow::Result<()>;                         // per entry: rerun-if-changed, sha256 check, filter, Abigen
fn sha256_hex(bytes: &[u8]) -> String;                   // hand-rolled or sha2 build-dep pinned =0.10.9
fn write_event_only_abi(src: &Path, dst: &Path, names: &[&str]) -> anyhow::Result<()>;
// V4/build.rs:41-61. Exact-count check: each named event must appear exactly once.
// Pool.json also has `Collect`, which is deliberately NOT selected.
```

- Event signatures (VERIFIED from the ABI JSON, and topic0 values with `cast keccak`):
  - `PoolCreated(indexed address,indexed address,indexed int24,address)`, `0xab0d57f0…9ac2`;
  - Pool `Initialize(uint160,int24)` `0x98636036…4c95`, `Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24)` `0xc42079f9…ca67`, `Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)` `0x7a53080b…0bde`, `Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)` `0x0c396cd9…982c`, `Flash(indexed address,indexed address,uint256,uint256,uint256,uint256)` `0xbdbdb71d…a633`;
  - NPM `IncreaseLiquidity(indexed uint256,uint128,uint256,uint256)` `0x3067048b…e35f`, `DecreaseLiquidity(…)` `0x26f6a048…77b4`, `Collect(indexed uint256,address,uint256,uint256)` `0x40d0efd1…8f01`, `Transfer(indexed address,indexed address,indexed uint256)` `0xddf252ad…b3ef`.
- The generated `TOPIC_ID` constants are the **only** topic0 source. A unit test asserts that they equal the `layout-profile-v1.json` handler topics.
- Function bindings are not generated. Calldata for the audit keys is built by `core::calls` (§9).
- Abigen decoding is used only for:
  - the `PoolCreated` registry, which decides what becomes a pool host;
  - an `abi_decoded` audit flag per candidate.

  Candidates are emitted raw whether or not they decode. Graph Node's own decoder lives in the reducer (`alloy-dyn-abi =1.7.2`, RED §0.5).

---

## 5. Params and the manifest

### 5.1 Params (one pinned string, exact-key refusal, `V4/src/config.rs:25-127` pattern)

```text
network=base;deployment=QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV;factory=0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a;factory_start=13843704;npm=0x827922686190790b37229fd06084350e74485b72;npm_start=13843719;pool_implementation=0xec8e5342b19977b4ef8892e02d8daecfa1315831;storage_layout=slipstream@37eead2c7e5302a204dec78bfa0775bbb8ff48a2;walk_spacing=1:1,50:10,100:10,200:60,*:200
```

```rust
// crates/core/src/config.rs
pub struct Config {
    pub factory: [u8; 20], pub factory_start: u64,
    pub npm: [u8; 20],     pub npm_start: u64,
    pub pool_implementation: [u8; 20],
    pub walk_spacing: WalkSpacing,          // ts → canonical walk spacing s (§8.6)
}
pub const EXPECTED_KEYS: [&str; 9] = ["network","deployment","factory","factory_start","npm","npm_start",
                                      "pool_implementation","storage_layout","walk_spacing"];
impl Config { pub fn parse(params: &str) -> Result<Config, ConfigError>; }
// Refuses: a missing, duplicate or unknown key, or any value != the compiled-in constant (addresses are
// compared case-insensitively, 0x optional). storage_layout must equal core::layout::LAYOUT_ID.
```

- `walk_spacing` is the composite of the mapping's Factory fee table (1→100, 50→500, 100→500, 200→3000, else→10000; `D:Factory.dcmp:3312`) and `feeTierToTickSpacing` (10000→200, 3000→60, 500→10, 100→1; `D:Pool.dcmp:8455-8485`), as recorded in TARGET §7.
- It appears in params so that the only mapping-derived constant in the extractor is visible in the module hash. Module hashes include params (`SS/manifest/signature.go:151-175`, per engine-contract §2.3).

### 5.2 Manifest (abridged; every module has `initialBlock: 13843704`)

```yaml
specVersion: v0.1.0
package: { name: aerodrome_slipstream_base_extractor, version: v0.1.0,
           url: https://github.com/pinax-network/substreams-backfills,
           description: Graph-Node-ordered candidates and end-of-block call answers for QmasYjyp… }
network: base
protobuf: { files: [pinax/aerodrome/slipstream/base/v1/extractor.proto,
                    pinax/aerodrome/slipstream/base/internal/v1/internal.proto],
            importPaths: [./proto], excludePaths: [sf/substreams, google] }
binaries:
  extract: { type: wasm/rust-v1, file: ./target/wasm32-unknown-unknown/release/aerodrome_extractor_extract.wasm }
  stores:  { type: wasm/rust-v1, file: ./target/wasm32-unknown-unknown/release/aerodrome_extractor_stores.wasm }
  rpc:     { type: wasm/rust-v1, file: ./target/wasm32-unknown-unknown/release/aerodrome_extractor_rpc.wasm }
  answers: { type: wasm/rust-v1, file: ./target/wasm32-unknown-unknown/release/aerodrome_extractor_answers.wasm }
  audit:   { type: wasm/rust-v1, file: ./target/wasm32-unknown-unknown/release/aerodrome_extractor_audit.wasm }
modules:
  - { name: map_pools_created, kind: map, binary: extract, initialBlock: 13843704,
      inputs: [{params: string}, {source: sf.ethereum.type.v2.Block}],
      output: {type: proto:pinax.aerodrome.slipstream.base.internal.v1.PoolsCreated} }
  - { name: store_pools, kind: store, binary: stores, initialBlock: 13843704,
      updatePolicy: set_if_not_exists, valueType: bytes, inputs: [{map: map_pools_created}] }
  - { name: map_candidates, kind: map, binary: extract, initialBlock: 13843704,
      inputs: [{params: string}, {source: sf.ethereum.type.v2.Block}, {store: store_pools, mode: get}],
      output: {type: proto:pinax.aerodrome.slipstream.base.v1.ExtractorBlock} }
  - { name: map_storage_deltas, kind: map, binary: extract, initialBlock: 13843704,
      inputs: [{params: string}, {source: sf.ethereum.type.v2.Block}, {store: store_pools, mode: get}],
      output: {type: proto:pinax.aerodrome.slipstream.base.internal.v1.StorageDeltas} }
  - { name: store_pool_slots, kind: store, binary: stores, initialBlock: 13843704,
      updatePolicy: set, valueType: bytes, inputs: [{map: map_storage_deltas}] }
  # store_tick_slots_00 … _07 (macro-generated handlers, V4/store-tick-shards/src/lib.rs:23-37 pattern)
  - { name: store_tick_slots_00, kind: store, binary: stores, initialBlock: 13843704,
      updatePolicy: set, valueType: bytes, inputs: [{map: map_storage_deltas}] }
  # store_position_slots_00 … _15
  - { name: store_position_slots_00, kind: store, binary: stores, initialBlock: 13843704,
      updatePolicy: set, valueType: bytes, inputs: [{map: map_storage_deltas}] }
  - { name: store_pool_last_tick, kind: store, binary: stores, initialBlock: 13843704,
      updatePolicy: set, valueType: int64, inputs: [{map: map_candidates}] }
  - { name: map_token_metadata, kind: map, binary: rpc, initialBlock: 13843704,
      inputs: [{map: map_pools_created}],
      output: {type: proto:pinax.aerodrome.slipstream.base.internal.v1.TokenMetadataAnswers} }
  - { name: map_tick_answers, kind: map, binary: answers, initialBlock: 13843704,
      inputs: [{params: string}, {map: map_candidates}, {store: store_pools, mode: get},
               {store: store_pool_last_tick, mode: get}, {store: store_tick_slots_00, mode: get}, … _07],
      output: {type: proto:pinax.aerodrome.slipstream.base.internal.v1.TickAnswers} }      # 12 inputs
  - { name: map_position_answers, kind: map, binary: answers, initialBlock: 13843704,
      inputs: [{map: map_candidates}, {store: store_pools, mode: get}, {store: store_pool_slots, mode: get},
               {store: store_position_slots_00, mode: get}, … _15],
      output: {type: proto:pinax.aerodrome.slipstream.base.internal.v1.PositionAnswers} }  # 19 inputs
  - { name: map_extractor_block, kind: map, binary: answers, initialBlock: 13843704,     # ← ENGINE/REDUCER OUTPUT
      inputs: [{map: map_candidates}, {map: map_storage_deltas}, {store: store_pool_slots, mode: get},
               {map: map_tick_answers}, {map: map_position_answers}, {map: map_token_metadata}],
      output: {type: proto:pinax.aerodrome.slipstream.base.v1.ExtractorBlock} }            # 6 inputs
  - { name: map_slot_audit, kind: map, binary: audit, initialBlock: 13843704, …audit only… }
params:
  map_pools_created: "<§5.1 string>"
  map_candidates: "<§5.1 string>"
  map_storage_deltas: "<§5.1 string>"
  map_tick_answers: "<§5.1 string>"
```

- There are 34 production modules plus 1 audit module, under the 100-module ceiling (CLAIM, `ENG/docs/substreams-stores.md:157-162`).
- The widest module has 19 inputs, under the 30-input limit (`V4/store-probe/src/lib.rs:221-222`).
- Store reads use `get_last` (end-of-block state including this block's writes) or `get_first` (start of block). DOC: `SS7:store.rs:886-896`.

### 5.3 Module graph

```text
sf.ethereum.type.v2.Block ─┬─► map_pools_created [extract] ─┬─► store_pools [stores, set_if_not_exists]
                           │                                └─► map_token_metadata [rpc; eth_call]
                           ├─► map_candidates [extract] (reads store_pools)  ─► store_pool_last_tick [stores]
                           └─► map_storage_deltas [extract] (reads store_pools)
                                   ├─► store_pool_slots [stores]
                                   ├─► store_tick_slots_00..07 [stores]
                                   └─► store_position_slots_00..15 [stores]
map_candidates + store_pools + store_pool_last_tick + tick shards        ─► map_tick_answers [answers]
map_candidates + store_pools + store_pool_slots + position shards        ─► map_position_answers [answers]
map_candidates + map_storage_deltas + store_pool_slots
              + map_tick_answers + map_position_answers + map_token_metadata ─► map_extractor_block [answers]
```

Cache boundaries:
- Editing `answers` changes only the 3 answer-module hashes.
- Editing `rpc` changes `map_token_metadata` and `map_extractor_block`.
- Editing `stores` changes every store and every answer module.
- Editing `extract` changes everything.

The `cache-boundary` xtask test asserts all of the above (§11.5).

---

## 6. Output proto (normative)

### 6.1 Public: `pinax.aerodrome.slipstream.base.v1`

Tags 1–10 of each message are **identical** to the reducer's proposal (RED §4.1). The extractor adds only tags ≥ 10 (or ≥ 11 where 10 is taken). prost ignores unknown fields, so the reducer may compile either version of the file. On any conflict, the file in `SB/aerodrome-slipstream-base/substreams/proto/` is the source of truth, and both crates use `aerodrome-extractor-pb`.

Encoding conventions:
- addresses are 20 bytes;
- hashes are 32 bytes;
- "U256-32" means 32-byte big-endian;
- "I128-16" means 16-byte two's complement;
- "minimal BE" means big-endian with no leading zeros, empty for 0;
- ticks are `sint32`.

```proto
syntax = "proto3";
package pinax.aerodrome.slipstream.base.v1;

// Exactly one per block in [requested start, stop). Never empty: number/hash/timestamp are always set,
// so production mode always delivers it and substreams-native emits an Observed frame (engine-contract §3.2).
message ExtractorBlock {
  uint64 number = 1;
  bytes  hash = 2;                         // 32; == Substreams clock id == BCF1 envelope hash
  bytes  parent_hash = 3;                  // 32
  uint64 timestamp = 4;                    // header.timestamp.seconds (Graph Node ethereum.Block.timestamp)
  optional uint64 base_fee_per_gas = 5;    // header.base_fee_per_gas truncated U256→u64 as Graph Node does (codec.rs:494-497)
  uint32 receipt_log_count = 6;            // number of logs over all receipts (successful txs; failed ones carry none)
  repeated Transaction transactions = 7;   // only txs referenced by candidates; ascending index; unique
  repeated CandidateLog candidates = 8;    // sorted by (wave, source_trigger_order); see §8.1
  CallAnswers calls = 9;                   // end-of-block answers (§8.5)
  repeated PoolCreatedFact pools_created = 10; // every Factory PoolCreated log in this block, log order
  // ---- extractor extensions ----
  uint32 firehose_block_version = 11;      // Block.ver: 4 (≤45,903,999) or 5 (≥45,904,000) on Base
  ExtractorAudit audit = 12;               // audit.anomalies MUST be empty; the reducer refuses otherwise
  string contract = 13;                    // "pinax.aerodrome.slipstream.base.extractor/v1"
}

message Transaction {
  bytes  hash = 1;                         // 32
  uint32 index = 2;                        // trace.index
  bytes  from = 3;                         // 20 (Graph Node transaction.from → Swap/Mint/Burn.origin)
  uint64 gas_limit = 4;                    // trace.gas_limit (Graph Node gasLimit → Transaction.gasUsed quirk)
  uint32 type = 5;                         // trace.type (0,1,2,3,4; 126 = OP deposit)
  optional bytes gas_price = 6;            // trace.gas_price minimal BE; ABSENT if unset (deposits)
  optional bytes max_fee_per_gas = 7;      // trace.max_fee_per_gas; absence matters (codec.rs:259-262)
  optional bytes max_priority_fee_per_gas = 8;
  // ---- extensions ----
  bytes  to = 10;                          // 20, or empty when Graph Node to() is None (codec.rs:863-876)
  bytes  graph_gas_price = 11;             // core::gas::graph_node_gas_price (§8.2), minimal BE; cross-check only
}

enum DataSourceKind {
  DATA_SOURCE_KIND_UNSPECIFIED = 0;
  DATA_SOURCE_KIND_FACTORY = 1;            // manifest data source #0
  DATA_SOURCE_KIND_POSITION_MANAGER = 2;   // manifest data source #1
  DATA_SOURCE_KIND_POOL = 3;               // template `Pool`
}

message CandidateLog {
  uint32 wave = 1;                         // 0 or 1 (§8.1)
  uint32 source_trigger_order = 2;         // rank among ALL receipt logs of the block by block_index (== block_index; VERIFIED dense)
  uint32 log_index = 3;                    // Log.block_index == Graph Node event.logIndex
  uint32 tx = 4;                           // index into ExtractorBlock.transactions
  bytes  address = 5;                      // 20
  repeated bytes topics = 6;               // raw
  bytes  data = 7;                         // raw
  // ---- extensions ----
  uint64 log_ordinal = 10;                 // Firehose Log.ordinal (provenance)
  DataSourceKind source = 11;
  uint64 host_order_key = 12;              // 0 Factory, 1 NPM, pool: 2 + created_block·2^24 + created_log_index
                                           // (Graph Node host creation order; informational: one host per log)
  bool   abi_decoded = 13;                 // extractor's Abigen decode succeeded (audit; the reducer decodes itself)
}

message CallAnswers {
  repeated Erc20Answer erc20 = 1;                  // C1–C4
  repeated FeeGrowthGlobalAnswer fee_growth = 2;   // C5
  repeated TickAnswer ticks = 3;                   // C6, C7
  repeated PositionAnswer positions = 4;           // C8
  repeated GetPoolAnswer get_pool = 5;             // C9
}

message RawRetval {                        // Graph Node Retval (ethereum_adapter.rs:1550-1566)
  oneof kind {
    Null  reverted = 1;                    // RpcResponse.failed OR empty "0x"
    bytes value = 2;                       // raw return bytes, never empty
  }
  message Null {}
}

message Erc20Answer {                      // eth_call at the block hash; one raw answer serves string AND bytes32 decodes
  bytes token = 1;
  RawRetval symbol = 2;                    // 0x95d89b41
  RawRetval name = 3;                      // 0x06fdde03
  RawRetval total_supply = 4;              // 0x18160ddd
  RawRetval decimals = 5;                  // 0x313ce567
  // ---- extensions (audit) ----
  uint32 rpc_failed_mask = 10;             // bit i = RpcResponse.failed for selector i (symbol,name,totalSupply,decimals)
  uint32 rpc_empty_mask = 11;              // bit i = !failed && raw.is_empty()
}

enum SlotSource {
  SLOT_SOURCE_UNSPECIFIED = 0;
  SLOT_SOURCE_IN_BLOCK = 1;                // last non-reverted write is in this block
  SLOT_SOURCE_CARRIED = 2;                 // last write in an earlier block (store value)
  SLOT_SOURCE_ZERO = 3;                    // never written, or cleared to zero (store key absent)
}
message SlotProvenance {
  SlotSource source = 1;
  uint64 last_change_block = 2;            // 0 when ZERO
  uint64 last_change_ordinal = 3;          // Firehose StorageChange.ordinal of that write; 0 when ZERO
}

message FeeGrowthGlobalAnswer {            // CLPool slots 7 and 8
  bytes pool = 1;
  bytes fee_growth_global0_x128 = 2;       // U256-32
  bytes fee_growth_global1_x128 = 3;       // U256-32
  SlotProvenance p0 = 10;
  SlotProvenance p1 = 11;
}

message TickAnswer {                       // ticks(int24): only value2/value3 (D:Pool:5398-5438)
  bytes  pool = 1;
  sint32 tick = 2;
  bytes  staked_liquidity_net = 3;         // I128-16 (Tick.Info word 1, low 128 bits)
  bytes  fee_growth_outside0_x128 = 4;     // U256-32 (Tick.Info word 2)
  SlotProvenance p_staked = 10;
  SlotProvenance p_fee0 = 11;
  uint32 reasons = 12;                     // bit0 MINT_BURN_BOUNDARY, bit1 SWAP_WALK_WINDOW
}

message PositionAnswer {                   // NPM positions(uint256)
  bytes token_id = 1;                      // minimal BE
  oneof result {
    RawRetval.Null reverted = 2;           // poolId == 0 at end of block ("ID")
    PositionValue value = 3;
  }
}
message PositionValue {                    // value2..value9 of the 12-tuple
  bytes  token0 = 1;                       // 20 (_poolIdToPoolKey word 0)
  bytes  token1 = 2;                       // 20 (word 1 [0,160))
  sint32 tick_spacing = 3;                 // int24 (word 1 [160,184))
  sint32 tick_lower = 4;                   // _positions word 1 [80,104)
  sint32 tick_upper = 5;                   // word 1 [104,128)
  bytes  fee_growth_inside0_last_x128 = 6; // U256-32 (word 2)
  bytes  fee_growth_inside1_last_x128 = 7; // U256-32 (word 3)
  uint64 pool_id = 10;                     // NPM-internal uint80 (audit)
  SlotProvenance p_key = 11;               // provenance of the poolId/ticks fragment
  SlotProvenance p_fee0 = 12;
  SlotProvenance p_fee1 = 13;
}

message GetPoolAnswer {                    // Factory getPool(address,address,int24): never reverts
  bytes  token_a = 1;
  bytes  token_b = 2;
  sint32 tick_spacing = 3;
  bytes  pool = 4;                         // 20; zero address when none at END of block
  uint64 created_block = 10;               // 0 when none (audit)
}

message PoolCreatedFact {
  bytes  pool = 1;
  bytes  token0 = 2;
  bytes  token1 = 3;
  sint32 tick_spacing = 4;
  uint32 log_index = 5;
  bytes  clone_implementation = 10;        // implementation decoded from the CREATE2 frame code_changes (§8.1)
  uint64 log_ordinal = 11;
}

enum AnomalyKind {
  ANOMALY_KIND_UNSPECIFIED = 0;
  ANOMALY_UNCLASSIFIED_POOL_SLOT = 1;      // pool write outside the pinned layout (§8.3)
  ANOMALY_ORDINAL_TIE = 2;                 // two writes to one slot share an ordinal
  ANOMALY_FAILED_TX_WITH_RECEIPT_LOGS = 3;
  ANOMALY_LOG_INDEX_NOT_DENSE = 4;         // receipt block_index not 0..n-1 / duplicate
  ANOMALY_MISSING_POOL_KEY = 5;            // position fragment present but _poolIdToPoolKey words absent
  ANOMALY_POOL_NOT_PINNED_CLONE = 6;       // PoolCreated pool's code is not the pinned EIP-1167 clone
  ANOMALY_SWAP_WITHOUT_PRIOR_TICK = 7;     // no Initialize/Swap tick known for a swapping pool
  ANOMALY_UNSUPPORTED_BLOCK_VERSION = 8;   // ver ∉ {4,5} or detail_level != EXTENDED
  ANOMALY_TICK_ALIGNMENT = 9;              // initialized tick not multiple of the pool's tickSpacing
  ANOMALY_SYSTEM_CALL_TOUCHED_TARGET = 10; // a v5 system call wrote Aerodrome storage
}
message Anomaly { AnomalyKind kind = 1; bytes address = 2; bytes key = 3; uint64 ordinal = 4; string detail = 5; }

message ExtractorAudit {
  uint32 relevant_storage_writes = 1;      // non-reverted writes to pool/NPM storage
  uint32 reverted_writes_skipped = 2;      // pool/NPM writes ignored (failed tx or state_reverted call)
  uint32 tick_candidates = 3;
  uint32 swap_walk_probes = 4;             // marker lookups performed by the walk window
  uint32 candidate_decode_failures = 5;    // candidates with abi_decoded = false
  repeated Anomaly anomalies = 6;
}
```

### 6.2 Internal: `pinax.aerodrome.slipstream.base.internal.v1`

```proto
syntax = "proto3";
package pinax.aerodrome.slipstream.base.internal.v1;
import "pinax/aerodrome/slipstream/base/v1/extractor.proto";

message PoolsCreated { repeated PoolCreatedRecord pools = 1; }
message PoolCreatedRecord {
  bytes pool = 1; bytes token0 = 2; bytes token1 = 3; sint32 tick_spacing = 4;
  uint32 log_index = 5; uint64 log_ordinal = 6; uint32 tx_index = 7;
  bytes clone_implementation = 8;           // empty when the CREATE2 code change is absent/unexpected
}

// store_pools values (raw bytes = prost encoding)
message PoolRecord { bytes token0 = 1; bytes token1 = 2; sint32 tick_spacing = 3;
                     uint64 created_block = 4; uint32 created_log_index = 5; }
message PoolRef { bytes pool = 1; uint64 created_block = 2; }   // value of getPool keys

// map_storage_deltas output: ONE entry per (address, slot) = the end-of-block value (§8.3)
message StorageDeltas {
  repeated FeeGrowthWrite fee_growth = 1;
  repeated TickWrite ticks = 2;
  repeated PositionWrite positions = 3;
  repeated PoolKeyWrite pool_keys = 4;
  uint32 relevant_writes = 5;
  uint32 reverted_writes_skipped = 6;
  repeated pinax.aerodrome.slipstream.base.v1.Anomaly anomalies = 7;
}
message SlotWrite { bytes word = 1;        // 32-byte end-of-block word
                    uint64 ordinal = 2; uint32 tx_index = 3; uint32 reverted_skipped = 4; }
message FeeGrowthWrite { bytes pool = 1; uint32 which = 2; SlotWrite write = 3; }      // which ∈ {0,1}
message TickWrite { bytes pool = 1; sint32 tick = 2; uint32 member = 3; SlotWrite write = 4; }
                    // member 0 = initialization marker (§8.4), 1 = staked word, 2 = fgo0 word
message PositionWrite { bytes token_id = 1; uint32 member = 2; SlotWrite write = 3; }
                    // member 1 = key fragment changed (poolId|tickLower|tickUpper), 2/3 = fgi words
message PoolKeyWrite { uint64 pool_id = 1; uint32 member = 2; SlotWrite write = 3; }   // member ∈ {0,1}

// carry store values
message SlotWord { bytes word = 1;         // minimal BE of the 32-byte word (never empty: zero ⇒ key deleted)
                   uint64 block = 2; uint64 ordinal = 3; }
message TickMarker { uint64 block = 1; uint64 ordinal = 2; }
message PositionKeyFragment { uint64 pool_id = 1; sint32 tick_lower = 2; sint32 tick_upper = 3;
                              uint64 block = 4; uint64 ordinal = 5; }

message TokenMetadataAnswers { repeated pinax.aerodrome.slipstream.base.v1.Erc20Answer erc20 = 1; }
message TickAnswers { repeated pinax.aerodrome.slipstream.base.v1.TickAnswer ticks = 1;
                      uint32 swap_walk_probes = 2;
                      repeated pinax.aerodrome.slipstream.base.v1.Anomaly anomalies = 3; }
message PositionAnswers { repeated pinax.aerodrome.slipstream.base.v1.PositionAnswer positions = 1;
                          repeated pinax.aerodrome.slipstream.base.v1.GetPoolAnswer get_pool = 2;
                          repeated pinax.aerodrome.slipstream.base.v1.Anomaly anomalies = 3; }
```

---

## 7. Store key schemas

Keys are ASCII and always end with `;`, so `delete_prefix(key)` deletes exactly one key. `delete_prefix` is in `SS7:store.rs:83-89`. Addresses are lowercase hex without `0x`. Ticks and IDs are decimal.

| Store | Policy | Key | Value | Written when | Deleted when |
|---|---|---|---|---|---|
| `store_pools` | set_if_not_exists, bytes | `p:{pool};` | `PoolRecord` | every PoolCreated (ordinal = log ordinal) | never |
| | | `g:{tokenA}:{tokenB}:{ts};` (both orders) | `PoolRef` | same | never |
| `store_pool_slots` | set, bytes | `f:{pool}:{0\|1};` | `SlotWord` | `FeeGrowthWrite` | never (fee growth never returns to 0) |
| | | `k:{poolId}:{0\|1};` | `SlotWord` | `PoolKeyWrite` | never |
| `store_tick_slots_NN` (N=8, shard §7.1) | set, bytes | `m:{pool}:{tick};` | `TickMarker` | `TickWrite{member:0}` | never (superset of "Tick entity exists") |
| | | `w:{pool}:{tick}:{1\|2};` | `SlotWord` | `TickWrite{member:1\|2}`, word ≠ 0 | word == 0 |
| `store_position_slots_NN` (N=16) | set, bytes | `f:{tokenId};` | `PositionKeyFragment` | `PositionWrite{member:1}`, poolId ≠ 0 | poolId == 0 (burn) |
| | | `w:{tokenId}:{2\|3};` | `SlotWord` | `PositionWrite{member:2\|3}`, word ≠ 0 | word == 0 |
| `store_pool_last_tick` | set, int64 | `{pool};` | tick | every candidate Initialize/Swap (ordinal = log ordinal) | never |

### 7.1 Shard functions (`core::shard`)

```rust
pub const TICK_SHARDS: u8 = 8;
pub const POSITION_SHARDS: u8 = 16;
pub fn tick_shard(pool: &[u8; 20], tick: i32) -> u8 {             // keccak256(pool ‖ tick.to_be_bytes())[0] % 8
    keccak256(&[pool.as_slice(), &tick.to_be_bytes()].concat())[0] % TICK_SHARDS
}
pub fn position_shard(token_id: &U256Bytes) -> u8 { (low_u64(token_id) % POSITION_SHARDS as u64) as u8 }
```

The shard counts are part of `storage_layout` semantics. Changing them changes the graph, so freeze them with the first release (§13).

---

## 8. Algorithms

### 8.1 Candidates, waves and transactions (`map_candidates`)

```rust
pub fn map_candidates(params: String, block: eth::Block, pools: StoreGetRaw) -> Result<pb::ExtractorBlock, Error>;
// core:
pub fn build_candidates(cfg: &Config, block: &eth::Block, registry: &impl PoolRegistry) -> pb::ExtractorBlock;
pub trait PoolRegistry { fn pool(&self, addr: &[u8; 20]) -> Option<PoolRecord>; }   // get_last("p:{addr};")
```

1. Fill the header fields 1–5, 11 and 13 from `block.header` and `block.ver`. Raise `UNSUPPORTED_BLOCK_VERSION` if `ver ∉ {4,5}` or `detail_level != EXTENDED`. If `block.number < cfg.factory_start`, stop: the message holds only the header, which is still non-empty.
2. Walk `block.transaction_traces` in vector order (ascending `index`).
   - If `status != SUCCEEDED (1)` and the receipt has logs, raise `FAILED_TX_WITH_RECEIPT_LOGS`, then skip the tx.
   - For each `receipt.logs[i]`, collect `(block_index, ordinal, tx_index, log)`.

   Set `receipt_log_count` to the total. Assert the `block_index` values are exactly `0..receipt_log_count-1` (`LOG_INDEX_NOT_DENSE`); this holds per §2.7. Set `source_trigger_order = block_index`.
3. Classify each log by the **address first**, as Graph Node does (`data_source.rs:696`):
   - `addr == factory && n >= factory_start && topic0 == PoolCreated::TOPIC_ID` → `FACTORY`, wave 0, `host_order_key` 0.
   - `addr == npm && n >= npm_start && topic0 ∈ {Increase, Decrease, Collect, Transfer}` → `POSITION_MANAGER`, wave 0, key 1.
   - `topic0 ∈ {Initialize, Swap, Mint, Burn, Flash}` and `registry.pool(addr) = Some(rec)` → `POOL`. Wave = 1 iff `rec.created_block == n`, else 0; `host_order_key = 2 + rec.created_block·2^24 + rec.created_log_index`.
     - `get_last` covers this block's creations, which is Graph Node's rescan.
     - Gating is by creation **block**, not ordinal (`data_source.rs:700`; `mapping-host/src/runner.rs:18-23`), so a pool log that precedes its `PoolCreated` is still included.
   - Anything else is not a candidate.
4. `abi_decoded` is the Abigen `match_and_decode(log).is_some()`. The candidate is emitted either way.
5. Sort by `(wave, source_trigger_order)`. The sort must be stable and explicit, never vector order (`V4/src/extract.rs:40-57`).
6. `transactions`: the unique referenced traces, ascending `index`, with fields 1–8 raw plus 10 `to` and 11 `graph_gas_price` (§8.2). `CandidateLog.tx` is the position in that list.
7. `pools_created`: the decoded `PoolCreated` candidates in log order, including `clone_implementation` (step 8).
8. Clone check. Find the `CALL_TYPE_CREATE2` frame in the same tx with a `code_changes` entry for `pool`. Expect `new_code == 363d3d373d3d3d363d73 ‖ impl ‖ 5af43d82803e903d91602b57fd5bf3` with `impl == cfg.pool_implementation`. Otherwise raise `POOL_NOT_PINNED_CLONE`. VERIFIED shape in P6, call 3.

Wave correctness rests on three facts:
- only the Factory creates hosts (TARGET §2 import inventory);
- `CLPool.initialize` is callable once (`CLPool.sol:156`, `require(factory == address(0) …)`), from `createPool` before `emit PoolCreated` (`CLFactory.sol:81` vs `:94`);
- the Graph Node wave loop.

A **superset** is emitted for hosts: every `PoolCreated` registers its pool, even one whose handler would fail non-fatally. The reducer owns host existence (RED §4.2).

### 8.2 Graph Node transaction gas price (`core::gas`)

```rust
/// Graph Node v0.44 `ethereum.Transaction.gasPrice` for a Firehose trace (§2.8). u128 like alloy.
pub fn graph_node_gas_price(tx: &eth::TransactionTrace, base_fee: Option<u64>) -> u128 {
    let gp = tx.gas_price.as_ref().map_or(0, big_to_u128);                       // codec.rs:177-180
    match tx.r#type {
        0 | 1 => gp,                                                                // legacy.rs:278, eip2930.rs:164
        2 | 3 | 4 => {
            let max_fee = tx.max_fee_per_gas.as_ref().map_or(gp, big_to_u128);    // codec.rs:259-262
            let prio = tx.max_priority_fee_per_gas.as_ref().map_or(0, big_to_u128);
            match base_fee {                                                       // alloy-eips helpers.rs:14-27
                None => max_fee,
                Some(b) => { let tip = max_fee.saturating_sub(b as u128);
                             if tip > prio { prio + b as u128 } else { max_fee } }
            }
        }
        _ => gp, // 126 deposit and any unknown type: UnknownTxEnvelope "gasPrice" field (unknowns.rs:163-166)
    }
}
```

- VERIFIED to equal `trace.gas_price` for all 1,565 type-2/4 txs in 5 blocks, and 0 for every deposit (P14).
- This is the same function as RED §5.6. Put it in `core` once, and have the reducer call it.

### 8.3 Storage classification and the end-of-block rule (`map_storage_deltas`)

```rust
pub fn map_storage_deltas(params: String, block: eth::Block, pools: StoreGetRaw)
    -> Result<internal::StorageDeltas, Error>;
// core:
pub fn storage_deltas(cfg: &Config, block: &eth::Block, registry: &impl PoolRegistry) -> internal::StorageDeltas;
pub enum Target { Pool([u8;20]), Npm }
pub enum PoolSlot { Fixed(u8 /*0..=16*/), Observation(u16), Tick { tick: i32, member: u8 }, Bitmap(i16), PoolPosition{ member: u8 } }
pub enum NpmSlot { Position { token_id: [u8;32], member: u8 }, PoolKey { pool_id: u128, member: u8 }, Other }
pub fn classify_pool_slot(key: &[u8;32], pre: &PreimageIndex) -> Option<PoolSlot>;     // None ⇒ anomaly
pub fn classify_npm_slot(key: &[u8;32], pre: &PreimageIndex) -> NpmSlot;
pub struct PreimageIndex(HashMap<[u8;32], [u8;64]>);   // only 64-byte preimages (value-type mapping keys)
impl PreimageIndex { pub fn from_block(block: &eth::Block) -> Self; pub fn base_of(&self, key: &[u8;32], max_off: u8) -> Option<(u8, [u8;32], u64 /*slot*/)>; }
```

**Step 1: preimage index.** Take the union over the whole block of every `call.keccak_preimages` (transactions and `block.system_calls`), hex-decoded, keeping entries whose preimage is exactly 64 bytes.
- The hash→preimage relation is a fact, so a block-level union is a safe superset of the per-transaction set that v5 guarantees (§2.7).
- `base_of(key, m)` returns the first `d ∈ 0..=m` with `key − d` in the index, plus the preimage's two words.

**Step 2: collect writes.** Iterate `transaction_traces` in order, each tx's `calls` in order, each call's `storage_changes` in order; then `block.system_calls`.
- The target is `Npm` if `sc.address == cfg.npm`. It is `Pool(a)` if `registry.pool(a).is_some()`, memoised per distinct address per block, with `get_last` covering pools created in this block.
- Otherwise skip.
- **Do not filter by call frame.** Correctness rests on `storage_change.address`. Delegatecall-into-the-implementation is only how the writes happen (§2.7). If they were made in an external-library frame instead, a frame filter would miss them.
- For each `(addr, key)` keep:
  - `first_old`: the `old_value` of the minimum-ordinal write among **all** writes, reverted or not. That is the start-of-block value.
  - `last`: the maximum-ordinal write among **non-reverted** writes, i.e. `tx.status == SUCCEEDED && !call.state_reverted`. System calls count as non-reverted.
  - `skipped`: the number of reverted writes.
  - Equal ordinals for one key raise `ORDINAL_TIE`.

  Firehose v4/v5 ordinals are block-global and monotonic (SEC docs; VERIFIED monotonic in P6).
- **Why `state_reverted`, and not `status_failed` or `status_reverted`.** `status_failed` and `status_reverted` describe the call's *own* execution. A call can succeed while an ancestor reverts; its writes are then rolled back, and only `state_reverted` is set (`SEC:pb/sf.ethereum.type.v2.rs:825-855`, field doc). A failed call always has `state_reverted = true`.
  - `tx.status != SUCCEEDED` is checked as well, as a belt-and-braces rule for failed transactions: every call of a failed transaction is state-reverted (same field doc).
  - VERIFIED in tx `0x09d08c55…167c` (block 30,000,000, a **successful** tx). Calls #390 and #412 have `status_failed = false` but `state_reverted = true`, and both have storage writes; only `state_reverted` excludes them. The Aerodrome writes in that tx are in call #394, where `status_failed`, `status_reverted` and `state_reverted` are all true. Across 30,000,000 and 52,800,000 there are 5 such "self-successful but rolled back" calls with writes.

**Step 3: end-of-block value.** If `last` exists, the end-of-block word = `last.new_value`, left-padded to 32 bytes. Otherwise the slot keeps its carried value and is **not** emitted.
- Reverted writes are discarded because EVM reverts restore the pre-frame value, and any later non-reverted write supersedes it.
- VERIFIED (P15). Block 30,000,000, pool `0x1d6aaa7ae38856fffc37e5e3c99d1c392631f450`: the only write to slot 7 (`new 0x…b88b5b37…`) is in reverted call #394 of successful tx `0x09d08c5568e82c6d64f2fb9a43574336c36bb5a01617a747bbe1fbb6bed8167c`. `eth_getStorageAt` and `eth_call feeGrowthGlobal0X128()` at 30,000,000 = `0x…b87560b3d8d54ef98b335f2827b54d` (957763325457588954411560741439518029), the value at 29,999,999.
- The same tx's 11 other reverted pool writes (slots 6, 9, 10, 12, 15, 16, 20 and four tick words) also matched `eth_getStorageAt(B)` = carried, 8 of 8 checked.

**Step 4: classify the slots that have a non-reverted last write.**

| Target | Classification | Emitted |
|---|---|---|
| Pool, `key ≤ 16` | `Fixed(k)` | `k ∈ {7,8}` → `FeeGrowthWrite{which: k−7}`; others are ignored but counted |
| Pool, `20 ≤ key < 20+65535` | `Observation` | ignored |
| Pool, `base_of(key,5)` with preimage slot word 17 | `Tick{tick = int24(word0), member = d}` | `d = 0`: `TickWrite{member:0}` iff some non-reverted write to that word in this block has `old_value == 0` (a tick initialization; uninitialized ⇔ word 0 == 0, §2.4). `d ∈ {1,2}`: `TickWrite{member:d}`. `d ∈ {3,4,5}`: ignored. Raise `TICK_ALIGNMENT` if `tick % rec.tick_spacing != 0`. |
| Pool, `base_of(key,0)` slot 18 / `base_of(key,3)` slot 19 | `Bitmap` / `PoolPosition` | ignored |
| Pool, anything else | — | **`UNCLASSIFIED_POOL_SLOT`** (layout drift alarm) |
| NPM, `base_of(key,4)` slot 13 | `Position{token_id = word0, member = d}` | `d = 1`: emit iff `frag(first_old) != frag(last.new)`, where `frag = bits[0,128)` (poolId and ticks; liquidity excluded). `d ∈ {2,3}`: emit. `d ∈ {0,4}`: ignored. |
| NPM, `base_of(key,1)` slot 12 | `PoolKey{pool_id = word0, member = d}` | emit |
| NPM, anything else | `Other` (ERC721 internals, `_poolIds`, counters) | ignored |

- Entries are emitted sorted by `last.ordinal`. Stores apply them in that order.
- The tick-marker rule needs "some non-reverted write had `old == 0`". Step 2 therefore also keeps a per-key boolean `saw_initialization`, set when a non-reverted write has `old_value == 0 && new_value != 0` on a d=0 tick word.
- Classification completeness was VERIFIED on 3 blocks across v4/v5 with zero unclassified pool writes (P10).

### 8.4 Carry stores: exact update rules (`core::carry`, shared with host tests)

```rust
pub enum StoreOp { Set { key: String, value: Vec<u8>, ordinal: u64 }, Delete { key: String, ordinal: u64 } }
pub fn pool_slot_ops(d: &StorageDeltas, block: u64) -> Vec<StoreOp>;
pub fn tick_slot_ops(d: &StorageDeltas, block: u64, shard: u8) -> Vec<StoreOp>;
pub fn position_slot_ops(d: &StorageDeltas, block: u64, shard: u8) -> Vec<StoreOp>;
pub fn registry_ops(p: &PoolsCreated, block: u64) -> Vec<StoreOp>;           // set_if_not_exists semantics
pub fn last_tick_ops(b: &ExtractorBlock) -> Vec<(String, i64, u64)>;       // decoded Initialize/Swap tick
pub struct InMemoryCarry { … }  impl InMemoryCarry { pub fn apply(&mut self, ops: &[StoreOp]); pub fn get(&self, key:&str) -> Option<&[u8]>; }
```

The Substreams store modules are thin loops: `for op in ops { match op { Set => store.set(ord, key, &value), Delete => store.delete_prefix(ord as i64, &key) } }`. Host tests run the same `ops` through `InMemoryCarry`, so the store semantics have a single source.

Rules:
- `FeeGrowthWrite` → `Set f:{pool}:{w};`.
- `TickWrite{0}` → `Set m:{pool}:{tick};`.
- `TickWrite{1|2}` → `Set w:…;`, or `Delete` when the word is zero.
- `PositionWrite{1}`: `frag.poolId == 0` → `Delete f:{id};`, else `Set` the `PositionKeyFragment`.
- `PositionWrite{2|3}` → `Set`, or `Delete` when zero.
- `PoolKeyWrite` → `Set k:{poolId}:{m};`.

Every value carries `(block, ordinal)` for provenance.

**Which stores carry what across blocks, and how big they get:**

| Store | Carries | Keys at 34.7M | Keys at head (52.87M) | Bytes/key | Total at head | Per shard at head |
|---|---|---|---|---|---|---|
| `store_pools` | registry | 1,490 × 3 (VERIFIED count) | 3,660 × 3 | ≈120 | ≈1.3 MB | 1 store |
| `store_pool_slots` | fee growth (C5), pool keys | ≈2×1,490 + 2×1,472 | ≈2×3,660 + 2×3,081 | ≈90 | ≈1.2 MB | 1 store |
| `store_pool_last_tick` | last event tick per pool | 1,490 | 3,660 | ≈60 | ≈0.2 MB | 1 store |
| `store_tick_slots_*` | markers + live staked/fgo0 words (C6/C7) | ESTIMATE 0.5–3 M markers | ESTIMATE 1–10 M markers + ≤2× live initialized ticks | ≈70–90 | **ESTIMATE 0.1–1.2 GB** | ≤150 MB (8 shards) |
| `store_position_slots_*` | key fragment + fgi words (C8) | 1.18 M live NFTs (VERIFIED) → ≈165 MB | **25.7 M live NFTs (VERIFIED)** × (fragment ≈40 B + 2 × ≈50 B) | ≈140/position | **ESTIMATE ≈3.6 GB** | **≈225 MB (16 shards)** |

- Limit: 3.5 GiB per store on Pinax prod (`KSS/apps/substreams-tier1/base/deployment.yaml:59`, SYN C8).
- Every shard stays below 7% of the limit at head. Growth was +21 M live positions over the last about 12.9 M blocks (VERIFIED P4), so 16 shards stay under 1 GiB each until roughly 200 M live positions.
- Tick counts are ESTIMATE, bounded above by 2 × all Mint events. G5 (§12) measures them.

### 8.5 Answers per call kind (C1–C9)

All answers are **end-of-block**, so there is one answer per distinct key per block. Graph Node keys its call cache by `(block hash, address, calldata)` (`SB/mapping-host/src/calls.rs:99-115`), so every handler in the block that asks for the same key gets the same answer.

| Kind | Key emitted when (superset rule) | Value | Proof sketch |
|---|---|---|---|
| **C1–C4** ERC20 | both tokens of **every** `PoolCreated` candidate in the block | `map_token_metadata` raw `eth_call` (§8.7) | The mapping calls metadata only for tokens with no `Token` entity, which is a subset of first sight in a `PoolCreated`. Calling at every `PoolCreated` covers handler failures that delay creation. About 3,660 pools × 2 × 4 calls lifetime. |
| **C5** `feeGrowthGlobal{0,1}X128()` | every pool with a Swap or Flash candidate | `store_pool_slots.get_last("f:{pool}:{0,1};")`; absent → 0 | slots 7/8 (§2.3); the store's end-of-block state = in-block last write, else carried |
| **C6** `ticks(tickLower/Upper)` | both ticks of every Mint and Burn candidate (decoded from topics 2/3) | `tick shard.get_last("w:{pool}:{tick}:{1,2};")`; absent → 0 | Tick.Info words 1/2 (§2.4) |
| **C7** `ticks(i)` (swap walk) | §8.6 window ∩ markers | same | §8.6 |
| **C8** `positions(tokenId)` | every NPM candidate's tokenId (`topics[1]`; Transfer `topics[3]`) | fragment `f:{id};` absent → `reverted`. Otherwise poolKey `k:{poolId}:{0,1};` gives token0, token1 and ts (absent → `MISSING_POOL_KEY`), and `w:{id}:{2,3};` gives fgi (absent → 0). | §2.5. `reverted` iff poolId == 0 at end of block (VERIFIED for mint+burn and burn-in-block cases, P8/P9). |
| **C9** `getPool(t0,t1,ts)` | each non-reverted C8 answer's `(token0, token1, tick_spacing)` | `store_pools.get_last("g:{t0}:{t1}:{ts};")`; absent → zero address | Only `createPool` writes `getPool`, together with `PoolCreated` (§2.6). End-of-block includes this block's creations (VERIFIED P11). |
| **C10** `getPool(USDC,token,tier)` | each decoded Swap, both registered pool tokens except USDC, literal third arguments 100/500/3000/10000; union/deduplicate with C9 | same end-of-block registry lookup as C9; absent → zero address | Exact deployed helper call keys; conservative superset because token version is reducer state. Getter-copy side effects being discarded does not exempt host-call evidence. |

- The answer value is computed with **`get_last`** on the carry store, which is the end-of-block state after this block's sets and deletes (`SS7:store.rs:886-890`).
- Provenance: `IN_BLOCK` when the stored `block == number`, `CARRIED` otherwise, `ZERO` when the key is absent.

VERIFIED mixed cases:
- Block 45,000,000, pool `0xb2cc…` ticks −198900/−198800 and pool `0x82321f3b…` tick 87000: word 1 in-block (gauge stake changes) and word 2 carried. `eth_call` value2/value3 equal the derived values (P9).
- Block 34,719,819, pool `0x4e962bb3…` ticks −70100/−70000: same pattern (P9).
- Block 34,719,819, Flash on pool `0x82321f3beb69f503380d6b233857d5c43562e2d0` (Factory `0x5e7b…`, ts 200): fg1 in-block `0x…55c96b63842be59be81c8bd1d7d6e5a64` equals `eth_call` at 34,719,819; fg0 carried `0x…6bd81b336252448b916e4a63f98eef` is identical at 34,719,818 and 34,719,819 (P16).

### 8.6 Swap-walk candidate window (C7), with proof

The mapping (TARGET §5.3; `D:Pool.dcmp:8455-8543`) uses:
- `s = walk_spacing(pool.tick_spacing)`;
- `modulo = new mod s`, with the sign following the dividend;
- `numIters = trunc(|old − new| / s)`.

It visits:
- `new` if `modulo == 0`;
- if `numIters ≤ 100` and `new > old`: `i = old + (s − modulo), i += s, while i ≤ new`;
- if `numIters ≤ 100` and `new < old`: `i = old − modulo, i −= s, while i ≥ new`.

It calls `ticks(i)` only where a `Tick` entity exists.

**Claim.** Every visited `i` satisfies `i = new` or `min(old,new) ≤ i ≤ max(old,new) + s − 1`, and the range part is non-empty only if `numIters ≤ 100`.

**Proof.** `modulo ∈ (−s, s)`.
- Upward, `first ∈ (old, old + 2s)` and the loop stops at `≤ new`, so `i ∈ (old, new]`.
- Downward, `first ∈ (old − s, old + s)` and the loop stops at `≥ new`, so `i ∈ [new, old + s − 1]`.

The union lies within `[min, max + s − 1] ∪ {new}`. ∎

```rust
pub fn walk_window(old: i32, new: i32, s: i32) -> (Option<RangeInclusive<i32>>, i32 /*new*/);
pub fn walk_candidates(pool: &[u8;20], old: i32, new: i32, ts: i32, s: i32,
                       marker: &impl Fn(&[u8;20], i32) -> bool) -> (Vec<i32>, u32 /*probes*/);
// Probe only multiples of the pool's real tickSpacing `ts` inside the range: initialized ticks are aligned
// (TickBitmap.flipTick, §2.4), and markers come only from initializations. Plus `new` if aligned.
```

- `old` is the mapping's `pool.tick` before this swap: the previous candidate `Initialize` or `Swap` tick of that pool in candidate order. Per pool, candidate order = log order, because all of a pool's logs in a block share one wave. If there is none in the block, use `store_pool_last_tick.get_first("{pool};")`. If neither exists, raise `SWAP_WITHOUT_PRIOR_TICK` and emit only the Mint/Burn ticks; the mapping would abort on `pool.tick!`.
- `new` is the event tick, decoded from the last data word.
- Probe bounds per swap, from `s` = walk spacing and `ts` = real spacing: ts=1/s=1 ≤ 103; ts=50/s=10 ≤ 21; ts=100/s=10 ≤ 11; ts=200/s=60 ≤ 32; ts=2000/s=200 ≤ 11; ts=10/s=200 ≤ 2,061 (only for |Δtick| near 20k, very rare).
- The marker superset holds because Mint ⇒ word-0 initialization (amount > 0) in a non-reverted frame, and `Tick` entities are created only by `handleMint` (TARGET §4).
- If the mapping's `oldTick` diverges from the event-derived one (a failed Swap handler under `nonFatalErrors`), the reducer raises `MissingCallAnswer` and stops. This is fail-closed, never silent (RED §4.3.5).

### 8.7 ERC20 metadata through `eth_call` (`map_token_metadata`, binary `rpc`)

```rust
#[substreams::handlers::map]
pub fn map_token_metadata(created: internal::PoolsCreated) -> Result<internal::TokenMetadataAnswers, Error>;
// core:
pub const ERC20_SELECTORS: [[u8; 4]; 4] = [[0x95,0xd8,0x9b,0x41],[0x06,0xfd,0xde,0x03],[0x18,0x16,0x0d,0xdd],[0x31,0x3c,0xe5,0x67]];
pub fn erc20_calls(tokens: &BTreeSet<[u8;20]>) -> RpcCalls;                     // 4 per token, sorted token order
pub fn erc20_answers(tokens: &BTreeSet<[u8;20]>, resp: &RpcResponses) -> Result<Vec<Erc20Answer>, CountMismatch>;
pub fn retval(r: &RpcResponse) -> RawRetval { if r.failed || r.raw.is_empty() { Null } else { Value(r.raw.clone()) } }
```

- The call batch is one `substreams_ethereum::rpc::eth_call(&RpcCalls)` per block that has a PoolCreated (`SEC:rpc.rs:75-80`), and none otherwise. A response count mismatch fails the block (`V4/src/metadata.rs:50-56`).
- **Raw only.** No string/bytes32/`unknown` or decimals fallbacks run in the extractor. They live in the reducer through alloy, Graph Node's decoder (RED §5.5).
- Server semantics:
  - FHETH `rpccalls.go:503-519`: the block ref is the block **hash** unless `ETH_CALL_USE_BLOCK_NUMBER_DURATION` or `ETH_CALL_FALLBACK_TO_LATEST_DURATION` is set.
  - Pinax prod sets neither (SYN C14, `git grep` empty).
  - Gas cap is 50,000,000 (`rpccalls.go:101`), equal to Graph Node's (`SB/mapping-host/src/calls.rs:71`).
  - `failed = true` is set for deterministic RPC errors (`rpccalls.go:632-653`). Non-deterministic errors retry forever (`:595-628`).
  - **Caveat:** "execution aborted (timeout)" is treated as deterministic (`:599-606`), while Graph Node would retry it. A false revert would then be cached. Mitigation: gate G6 audit, plus a reducer-side pinned override file if a mismatch is ever found. The frozen module is not rebuilt.
- **`X-substreams-acknowledge-non-deterministic: true`.**
  - The header is required only when the tier1 enables that check, since v1.17.7 (DOC `SS/docs/release-notes/change-log.md:671`). The `hasEthCall` scanner is `SS/service/validate.go:107-128`.
  - It is an acknowledgement, not a switch to non-deterministic behaviour. The non-deterministic switches are the two `ETH_CALL_*` server environment variables.
  - Rules:
    - (a) send the header on the noop and on the backfill requests;
    - (b) the noop preflight asserts that `KSS` tier1/tier2 manifests set no `ETH_CALL_*` variables;
    - (c) answers are cached forever with the module output, so G6 re-checks every `Erc20Answer` against an independent archive by block hash before the backfill.

### 8.8 Anomalies and fail-closed rules

- The extractor **never panics on data**. It records an `Anomaly` and carries on. Panics are reserved for impossible internal states (protobuf decode of its own store values).
- `map_extractor_block` merges the anomalies of `map_candidates`, `map_storage_deltas`, `map_tick_answers` and `map_position_answers` into `audit.anomalies`.
- Consumers:
  - the reducer refuses any block with anomalies;
  - `verify-live` and the noop evidence step count them and require 0.

---

## 9. `core` crate API (function signatures)

```rust
pub mod layout {            // §2.3–2.6, single source of truth
    pub const LAYOUT_ID: &str = "slipstream@37eead2c7e5302a204dec78bfa0775bbb8ff48a2";
    pub const POOL_FEE_GROWTH0: u64 = 7; pub const POOL_FEE_GROWTH1: u64 = 8; pub const POOL_TICKS: u64 = 17;
    pub const POOL_BITMAP: u64 = 18; pub const POOL_POSITIONS: u64 = 19; pub const POOL_OBSERVATIONS: u64 = 20;
    pub const NPM_POOL_KEYS: u64 = 12; pub const NPM_POSITIONS: u64 = 13; pub const FACTORY_GET_POOL: u64 = 6;
    pub const EIP1167_PREFIX: [u8; 10] = hex!("363d3d373d3d3d363d73"); pub const EIP1167_SUFFIX: [u8; 15] = hex!("5af43d82803e903d91602b57fd5bf3");
    pub fn tick_base(tick: i32) -> [u8; 32];                 // keccak256(int256(tick) ‖ u256(17))
    pub fn position_base(token_id: &[u8; 32]) -> [u8; 32];   // keccak256(token_id ‖ u256(13))
    pub fn pool_key_base(pool_id: u128) -> [u8; 32];         // keccak256(u256(pool_id) ‖ u256(12))
    pub fn decode_staked(word: &[u8; 32]) -> i128; pub fn decode_frag(word1: &[u8; 32]) -> (u128 /*poolId*/, i32, i32);
    pub fn decode_pool_key(w0: &[u8; 32], w1: &[u8; 32]) -> ([u8;20], [u8;20], i32);
}
pub mod config;   pub mod gas;   pub mod shard;   pub mod carry;   pub mod walk;
pub mod classify { /* §8.3 */ }
pub mod candidates { pub fn build_candidates(..); pub fn decode_pool_ticks(c: &CandidateLog) -> Option<PoolEvent>;
                     pub enum PoolEvent { Initialize{tick:i32}, Swap{tick:i32}, Mint{lo:i32,hi:i32}, Burn{lo:i32,hi:i32}, Flash } }
pub mod answers { pub fn tick_answers(..) -> TickAnswers; pub fn position_answers(..) -> PositionAnswers;
                  pub fn fee_growth_answers(..) -> Vec<FeeGrowthGlobalAnswer>; }
pub mod calls {   // canonical (address, calldata) for the differential (§11.4)
    pub enum CallKey { Erc20{token:[u8;20], selector:[u8;4]}, FeeGrowth{pool:[u8;20], which:u8},
                       Ticks{pool:[u8;20], tick:i32}, Positions{token_id:[u8;32]},
                       GetPool{a:[u8;20], b:[u8;20], ts:i32} }
    impl CallKey { pub fn address(&self, cfg:&Config) -> [u8;20]; pub fn calldata(&self) -> Vec<u8>; }
    // selectors (VERIFIED cast sig): ticks 0xf30dba93, positions 0x99fbab88, getPool 0x28af8d0b,
    // feeGrowthGlobal0X128 0xf3058399, feeGrowthGlobal1X128 0x46141319
    pub fn consumed_fields_equal(key: &CallKey, extractor: &CallAnswers, cassette_retval: &CassetteRetval) -> Result<(), Diff>;
}
pub mod json { pub fn canonical_json(b: &ExtractorBlock) -> String; }  // goldens; decimals rendered for readability
```

---

## 10. What the consumer may rely on

The contract with the reducer and the engine transport:

1. **Exactly one `ExtractorBlock` per block** in `[start, stop)`, with `number`/`hash` equal to the Substreams clock. Requests must use production mode and **final blocks only** (engine audit F6; the noop and backfill ranges stop at a finalized block).
2. `candidates` is a **superset** of Graph Node's Aerodrome triggers. It is ordered by `(wave, source_trigger_order)`, and `wave ∈ {0,1}`. A wave-1 address always appears in this block's `pools_created`.
3. `calls` is a **superset**:
   - every storage-derived value equals `eth_call` at the block hash on the consumed fields;
   - `reverted` for C8 is exact;
   - C1–C4 are raw RPC answers.

   A missing answer for a key the reducer needs is fatal in the reducer (`MissingCallAnswer`), never a revert.
4. `audit.anomalies` is empty. Otherwise the block is refused.
5. Never decoded or interpreted by the transport. `substreams-native` relays bytes (`ENG/AGENTS.md:105-106`).

---

## 11. Test plan

### 11.1 Unit tests (host, `cargo test --locked`, crate `core`; synthetic data)

- `config_*`: refusal of each missing, duplicate or unknown key and each wrong value (port of `V4/src/config.rs:129-157`).
- `layout_*`:
  - `tick_base(-1) == a69f8edf…adb0`, `tick_base(1) == 17bc176d…b552`, `position_base(1) == fd54ff1e…93c5`, `pool_key_base(1) == d421a518…8b5c` (P6);
  - decoders against the P7 words for tick −198700 (all 10 fields);
  - `decode_frag` on `0x…0bebae76000001ffffff00000000000000000001` → (1, −1, 1).
- `gas_*`: one case per type, including base fee None, tip clamp, missing `max_fee`, and type 126. Vectors include the 13,899,663 tx 55 values (max 296906355, prio 903800, base 98354726 → 99258526).
- `walk_*`:
  - property test: for random `(old, new, s ∈ {1,10,60,200})` the mapping's literal loop (ported verbatim in test code) ⊆ `walk_window`;
  - boundaries `numIters ∈ {99, 100, 101}`;
  - negative ticks with `mod` sign semantics;
  - `old == new`.
- `classify_*`:
  - fixed slots, observations, tick members 0–5, bitmap, pool positions, NPM position members 0–4, poolKey members 0–1, `Other`;
  - unknown slot → `None`;
  - nearest-base offset limits;
  - preimage of the wrong length ignored.
- `carry_*`:
  - `first_old` / `last` / `skipped` selection with reverted interleavings;
  - ordinal tie → anomaly;
  - marker only on `old == 0` initialization, including "initialized and cleared in the same block";
  - fragment change only when the low 128 bits change;
  - delete on zero;
  - `delete_prefix` exactness with `;` keys (`f:1;` must not delete `f:12;`).
- `shard_*`: distribution and stability (golden values).
- `erc20_*`: `failed` → Null, empty → Null, count mismatch → error.

### 11.2 Fixture blocks (`fixtures/blocks.lock.json`, `.pb` single-message Firehose blocks, `SB/mapping-host/src/block.rs:56-93` rules)

Each fixture has:
- `carry/<B>.json`: store state at B−1 for every answer key, from `eth_getStorageAt` at B−1, plus the registry and last-tick state;
- `oracle/<B>.json`: `eth_call` at B by block hash for every answer key;
- `goldens/<B>.json`.

| Name | Block | Why (all VERIFIED facts, §2) |
|---|---|---|
| **X-START** (≙ RED F-W1 neighbour) | 13,843,704 | factory deployment; zero candidates; NPM inactive; header-only message |
| X-NPM-START | 13,843,719 | NPM deployment block; gating of `npm_start` |
| **X-CREATE** (≙ RED F-W1) | 13,899,663 | first `PoolCreated`; Initialize(171) **before** PoolCreated(172); wave-0 = [172, 177 NPM Transfer, 178 IncreaseLiquidity], wave-1 = [171 Initialize, 176 Mint]; C9 same-block `getPool(USDC,USDbC,1)` = `0x98c7…`; C8 tokenId 1 from in-block writes; C1–C4 for USDC/USDbC; clone check; deposit tx at index 0; 4 failed txs with call logs but no receipt logs |
| X-GUARD | 14,317,993 | NPM block-guard block: no NPM candidates (TARGET §5.6) |
| X-FIRST-SWAP | 13,908,606 | first Swap of pool `0x98c7…` (tx `0xcf266230…ef82`, log 36): walk window from the Initialize tick via `get_first`; first-swap tokens (C10 required answers) |
| **X-REVERTED-WRITES** | 30,000,000 | reverted-call writes on pool `0x1d6aaa7a…f450` (tx `0x09d08c55…167c`, call 394) must not reach carry; fg0 carried (§8.3); tick m2 crossing on pool `0x3f0296bf…`; NPM tokenId 13220430 in-block |
| **X-DENSE-FLASH** | 34,719,819 | 222 candidates (20 Swap, 59 Burn, 58 NPM Collect, 51 Transfer, 27 Decrease, 3 Mint, 3 Increase, **1 Flash** on `0x82321f3b…` ts=200, fg1 in-block / fg0 carried); mixed tick words; carried NPM fgi (23666543, 23372431, 22397417 ≈2^256); **burn-in-block revert** tokenId 23665747 (tx `0xa8926ee2…a6e3`) |
| X-FLASH2 | 34,724,167 | second Flash, pool `0x0c1a09d5…8a3b` (Factory `0x5e7b…`, ts 1) |
| X-V4-LAST / X-V5-FIRST | 45,903,999 / 45,904,000 | block-version boundary |
| X-V4-SWAPS | 45,000,000 | 10 swaps; mixed tick words (gauge stake) |
| **X-V5-DENSE** | 52,800,000 | v5; 398 candidates; **mint+burn same block** tokenId 78901048 → `reverted`; successful tx with reverted-call logs (`0x3b879426…5d92`); type-4 tx; tick m1/m2, fee growth and position fragments all equal to `eth_call` (P8) |
| X-DEPOSIT-TRIGGER | OPEN | an Aerodrome candidate inside a type-126 tx. `find-fixtures` scans for one. If none exists in history, a synthetic test mutates X-V5-DENSE's tx type. |
| X-WALK-WIDE | OPEN | a swap with `numIters ∈ [95,101]` on a ts=1 or ts=10 pool (`find-fixtures` criterion) |

Golden tests (host):
- `build_candidates`, `storage_deltas`, `*_ops` → `InMemoryCarry` seeded from `carry/<B>.json` → `answers`. The result must equal `goldens/<B>.json` byte for byte (canonical JSON), and every answer must equal `oracle/<B>.json` on its consumed fields.
- `wave_order_x_create` asserts the exact sequence `[(0,172),(0,177),(0,178),(1,171),(1,176)]`.

### 11.3 Live bounded verification (`cargo xtask aerodrome-substreams verify-live`)

- Run `substreams run --production-mode --final-blocks-only -o jsonl -H X-substreams-acknowledge-non-deterministic:true` of `map_extractor_block` for each fixture block and for 1k-block windows around them, against `base.substreams.kan-prod-firehose-a.pinax.io:443` (fallback riv; never `kan-sst2`, SYN C5).
- Assertions:
  - one message per block;
  - clock and hash continuity;
  - output == golden on fixture blocks (WASM == host);
  - zero anomalies;
  - sorted candidates;
  - every wave-1 address is in `pools_created`;
  - and **RPC spot-check**: for N = 200 random storage-derived answers per window, `eth_call` at the block hash equals the consumed fields.

### 11.4 Differential against the mapping-host oracle (gate G4)

Windows:
- W1 = [13,899,600, 13,900,600);
- W2 = [34,719,300, 34,720,300);
- W3 = [52,799,500, 52,800,500);
- plus the RED windows.

Inputs:
- (a) the mapping-host Aerodrome bundle (PR-S2) in `--record` mode, giving a cassette `pinax.substreams-backfills.mapping-host.cassette/v1` (`SB/mapping-host/src/calls.rs:67,99-115`) and a run report;
- (b) the extractor JSONL for the same window;
- (c) RED's `reference_extractor` output (RED §4.4).

`cargo xtask aerodrome-substreams differential` checks:

1. **Coverage.** Every cassette key `(block_hash, address, calldata)` maps through `core::calls::CallKey` to an extractor answer. This includes every C10 key `getPool(USDC,·,{100,500,3000,10000})`; no query-key injection or audit-only substitution may repair an incomplete live output.
2. **Equality** on consumed fields:
   - ERC20: `Null ⇔ reverted`, `Value` bytes equal;
   - fee growth: full 32 bytes;
   - ticks: decoded value2 and value3;
   - positions: `Null ⇔ reverted`, else value2–value6, value8 and value9;
   - getPool: full word.
3. **Order parity.** The mapping-host's handler groups `(stage, source_trigger_order, tx hash, log index, address)` equal the extractor candidates whose decode the reducer accepts, in the same order.
4. **Superset accounting.** Extra extractor answers are listed and not failed.
5. Extractor output == `reference_extractor` output, ignoring superset answers (RED §4.4b).

### 11.5 Package and cache tests

- `pack`: `substreams pack`, then `substreams info --json`. Assert:
  - 35 modules;
  - output type of `map_extractor_block`;
  - every `initialBlock` = 13,843,704;
  - inputs ≤ 30;
  - params equal across modules;
  - binaries mapped as in §5.2.
- `cache-boundary` (port of `V4/scripts/test-store-cache-boundary.sh:22-72` to xtask):
  - append a WASM custom section to `answers`: store, extract and rpc hashes are unchanged, and the answer hashes change;
  - repeat for `rpc`;
  - and `stores`: extract and rpc hashes are unchanged.
- `protogen --check` (V4 `check-generated.sh` port): the generated `pb` matches the protos.
- `build --twice`: identical wasm sha256 (§3.3).

---

## 12. Acceptance gates

| Gate | Pass condition | Blocks |
|---|---|---|
| G0 build | fmt, clippy `-D warnings`, host tests, wasm build `--locked`, reproducible twice, `pack` + `info` graph checks, `protogen --check`, `cache-boundary` | every PR |
| G1 fixtures | all goldens equal; wave order test; zero anomalies | PR-X2+ |
| G2 derivation | 100% of storage-derived answers on all fixture blocks equal archive `eth_call` (consumed fields), covering IN_BLOCK, CARRIED, ZERO, mixed, reverted-write and burn cases | PR-X3+ |
| G3 live | `verify-live` green on all fixture windows on kan and riv tier1 | PR-X5 |
| G4 oracle | differential §11.4 on ≥3 windows (≥3,000 blocks incl. X-CREATE, X-DENSE-FLASH, X-V5-DENSE): 0 missing keys, 0 mismatches, 0 order diffs | **freeze** |
| G5 sizes | noop smoke over [52,000,000, 52,100,000) and [34,700,000, 34,800,000), production mode: per-store sizes from state-bucket listings / `SUBSTREAMS_LOG_TOTAL_STORE_SIZE` logs ≤ 25% of 3.5 GiB, extrapolated to target + 6 months ≤ 50%; tier2 segment wall time recorded | **freeze** |
| G6 ERC20 audit | every `Erc20Answer` in the smoke ranges (later: the full noop) equals an independent archive `eth_call` by block hash | backfill start |
| G7 freeze | CI-built SPKG committed + lock JSON + immutable tag; engine/reducer pin sha256 + `map_extractor_block` module hash | noop |

---

## 13. Release and freeze rules

1. **No tag before G4 and G5.** Before then, packages are "non-final" builds, used only for smoke and oracle runs and labelled as such in any evidence.
2. **Tag namespace** `aerodrome-slipstream-base-extractor-vX.Y.Z`. Asset `aerodrome-slipstream-base-extractor-vX.Y.Z.spkg`, package name `aerodrome_slipstream_base_extractor`.
   - The release workflow runs only on that tag pattern with a per-tag policy (`V4/.github/workflows/release.yml:25-57`).
   - It runs `gh release create --verify-tag`, with no `--clobber`, no sidecars, and immutable assets.
   - The repo is **internal**, so k8s workflows need a token, or the SPKG is vendored into the runtime image (decision D4 consequence; SYN §8 D4).
3. **Certified bytes are committed** under `release/vX.Y.Z/` with `packages/…-vX.Y.Z.json`. The lock holds:
   - sha256;
   - the module hash of all 35 modules;
   - the output type;
   - the initial block;
   - the params sha256;
   - the binaries' sha256 values;
   - the toolchain (Rust 1.90.0, CLI v1.20.3 sha256);
   - the layout ID;
   - the shard counts.

   The release job verifies the lock against the committed bytes and never rebuilds.
4. **The noop and the backfill use the same bytes and params, and the same output module `map_extractor_block`.**
   - Any edit to `extract`, `stores` or the params invalidates the whole cache.
   - An `answers`-only edit invalidates only about 3 modules' outputs (cache boundary). It still needs a new tag and a new noop for those modules.
5. Consumers pin `{repository, release, asset, sha256, package_version, module: map_extractor_block, module_hash, output_type, initial_block: 13843704}` in the reducer descriptor or adapter contract. The noop evidence records the SPKG sha, module hash, range and endpoint (SYN §6.1).

---

## 14. Performance and request shape (ESTIMATE; measured by G5)

- **Output size** at 34.7M density (58 triggers/block): candidates about 58 × 300 B, transactions about 30 × 120 B, answers about 12 fee growth + about 60 ticks + about 30 positions + about 25 getPool, roughly 8 KB. Total about **25 KB per block**, about 0.45 TB raw for the seeded range of 18.1M blocks (before tier2 compression).
  - Option to reduce it: drop `topics` and `data` for non-PoolCreated candidates in favour of typed payloads. **Not recommended**, because the reducer wants raw facts (RED §0.2).
- **Request shape.** One production-mode request per range (SYN C7):
  - root/oracle windows start at the window start;
  - the seeded backfill starts at `seed+1`;
  - stores always build from 13,843,704.

  Headers: `X-Substreams-Parallel-Workers` and `X-substreams-acknowledge-non-deterministic: true`.
- **RPC load** is about 29 k `eth_call`s over the whole history, versus about 1 B for a call-based design (SYN §3).
- **Store load.** Each answer-map segment job loads its shards' full KV snapshots. For the position family that is up to about 3.6 GB at head, and about 1.5 GB on average over the seeded range. ESTIMATE about 27 TB of snapshot reads for the 18.1M-block noop. This is the main noop cost; G5 measures it. See §15 Option R.

---

## 15. Options considered

| Option | Decision | Reason |
|---|---|---|
| **Position carry in Substreams Stores** (baseline) | **adopted** | Exact and independent of mapping state; works for root and seeded runs. VERIFIED layout. |
| **Option R**: no position fee-growth store; the reducer uses `Position.feeGrowthInside*` as the carried value when the extractor reports "not written in block" | fallback, only if G5 shows the position shards dominate segment time | Exact under the invariant "words 2/3 change only in blocks with an Increase/Decrease/Collect event for that tokenId, and the mapping stores the end-of-block value there" (`NonfungiblePositionManager.sol:185-198,267-268,329-330,392-393`). It **breaks** if any such NPM handler fails non-fatally (Graph Node would get the true value from RPC). Requires a reducer guard and changes the module graph, so it must be decided **before** the freeze. |
| Typed event payloads instead of raw logs | rejected | Puts Graph Node ABI semantics into the extractor, against RED §0.2 |
| `RpcBatch` decoded ERC20 values | rejected | `RpcBatch::decode` folds revert and decode failure into `None` (substreams-reuse §4.2.2); the raw form keeps Graph Node's rules in one place |
| A storage-derived `getPool` (factory slot 6) | audit only | The event registry is exact and cheaper (§2.6) |
| Omitting C10 | rejected after actual M2 failure | Getter-copy mutations are discarded but host calls must be present (§0.6); all-cassette coverage is mandatory. |
| Frame-based storage filter (delegatecall into the implementation) | rejected for correctness, allowed as a prefilter | §8.3 Step 2 |
| `Log.index` / call-iteration log order | rejected | v5 counts reverted logs; call order ≠ receipt order (§2.7) |

---

## 16. Risks and open items

1. **Fork-specific Firehose drift.** A tracer change could alter preimage retention or `state_reverted`. Mitigation: `UNCLASSIFIED_POOL_SLOT`, `ORDINAL_TIE`, `FAILED_TX_WITH_RECEIPT_LOGS` and `LOG_INDEX_NOT_DENSE` anomalies on every block, plus G2/G3 on both versions.
2. **Store snapshot cost** (§14). G5 decides between the baseline and Option R before the freeze.
3. **ERC20 false reverts** from an `execution aborted (timeout)` classified deterministic (`rpccalls.go:599-606`). Mitigation: G6 audit plus a reducer override file; the module is never rebuilt.
4. **Mapping-state divergence** (`oldTick` after a failed Swap handler; ERC20 for a token whose `Token` creation failed earlier). Covered by supersets where cheap. Otherwise the reducer fails closed with `MissingCallAnswer`. Live `sgd2` reported no indexing errors (SYN, v3-lane-state §3).
5. **Proto reconciliation with RED.** This document adopts RED §4.1 tags 1–10 verbatim and adds tags ≥10. Both teams must agree before PR-X2 lands. The single `.proto` lives in the extractor crate `pb`.
6. **Internal repo assets** (D4): k8s needs a token, or the SPKG is vendored into the image.
7. **OPEN**:
   - X-DEPOSIT-TRIGGER and X-WALK-WIDE fixtures;
   - G5 numbers;
   - whether `block.system_calls` ever touches the targets (anomaly kind reserved);
   - tier2's `--substreams-rpc-endpoints` forwarding (SYN C14 says V4 production evidence suggests yes).

---

## 17. Ordered PR slices (substreams-backfills; branch + PR each; nothing tagged until PR-X7)

| # | Slice | Contents | Gate | Depends on |
|---|---|---|---|---|
| **PR-X1** | Scaffold + core | Workspace and toolchain pins (§3), root `exclude`, protos (§6) + `pb` crate + `protogen --check`, `core` modules `layout`, `config`, `gas`, `shard`, `walk`, `classify`, `carry`, `calls` with all unit tests (§11.1); `cargo xtask aerodrome-substreams {check,protogen,build}`; CI workflow (fmt/clippy/test/wasm, reproducible twice). Reducer path-dep smoke check. | G0 | — |
| **PR-X2** | Candidates + registry | `extract` crate: `build.rs` Abigen with sha256 pins, `map_pools_created` (clone check), `map_candidates`; `stores::store_pools`; fixture lock `block-fixtures-base-v1` (shared with PR-S2) + X-START, X-NPM-START, X-CREATE, X-GUARD; goldens; wave-order test | G0, G1 (candidate part) | PR-X1; RED proto sign-off |
| **PR-X3** | Storage deltas + carry stores | `map_storage_deltas`, `store_pool_slots`, `store_tick_slots_00..07`, `store_position_slots_00..15`, `store_pool_last_tick`; `xtask … capture-fixture` (Firehose `.pb` + `carry/` + `oracle/` by block hash); fixtures X-REVERTED-WRITES, X-DENSE-FLASH, X-FLASH2, X-V4-SWAPS, X-V5-DENSE, X-V4-LAST/X-V5-FIRST | G1, **G2** | PR-X2 |
| **PR-X4** | Answers + RPC | `rpc::map_token_metadata`; `answers::{map_tick_answers, map_position_answers, map_extractor_block}`; X-FIRST-SWAP; full goldens; `pack` + `info` graph checks; `cache-boundary` | G0–G2 | PR-X3 |
| **PR-X5** | Live verify + differential tooling | `xtask … verify-live`, `differential` (cassette + reference extractor + order parity), `audit-erc20`, `find-fixtures`; `audit::map_slot_audit` (factory slot-6 cross-check; C10 must already be in public answers); run G3 on non-final builds | G3 | PR-X4; PR-S2 bundle for differential runs |
| **PR-X6** | Measurements (evidence only) | 1-block, then 100k-block noop smoke via the generic noop WorkflowTemplate (PR-K1) on kan/riv; G5 store sizes and timings; G6 ERC20 audit on smoke ranges; G4 on W1–W3; decide baseline vs Option R | G4, G5, G6 | PR-X5, PR-K1, PR-S2, RED R7 |
| **PR-X7** | Freeze + release | lock JSON, committed certified bytes, `release.yml` per-tag policy, tag `aerodrome-slipstream-base-extractor-v0.1.0`; consumer pin snippet for the reducer descriptor and k8s | G7 | G4 + G5 green; user go-ahead for the full-range noop |

ESTIMATE: PR-X1 3–4 days, PR-X2 3–4, PR-X3 5–7, PR-X4 4–5, PR-X5 4–5, PR-X6 3–5 (mostly waiting on runs), PR-X7 1–2. That is about 23–32 engineer-days and fits inside the SYN 5–8 week envelope, running in parallel with the reducer (RED R1–R6 do not need the extractor).

---

## Appendix A: probes run in this pass (read-only)

Scratch tools (scratchpad only; not repo sources) live in `scratchpad/xtools/`:
- `classify.py`: storage classification;
- `derive_check.py`: end-of-block derivation vs `eth_call`;
- `revert_check.py`: reverted writes vs `eth_getStorageAt`;
- `carry_check.py`: NPM carried fee growth;
- `tick_carry_check.py`: mixed tick words;
- `count_triggers.py`;
- `rpc.py`: JSON-RPC with backoff.

Firehose blocks are in `scratchpad/xprobe/` and `scratchpad/probe/`. RPC: `https://base.rpc.pinax.network/` (keyless, rate-limited; ≤1000-block `eth_getLogs` chunks with backoff through `scratchpad/aero-oracle/tools/scan_logs.sh`).

| ID | Probe | Result |
|---|---|---|
| P1 | `cast code --block {13843703,13843704}` Factory; `{13843718,13843719}` NPM | `0x` then code at both start blocks |
| P2 | `cast call Factory poolImplementation()`; `cast code` pool `0x98c7…` @13,899,663 | `0xeC8E…5831`; EIP-1167 clone of it (absent at 13,899,662) |
| P3 | `tickSpacings()`, `tickSpacingToFee(ts)`, `allPoolsLength()` @latest and @34,700,000 | `[1,50,100,200,2000,10]`; fees 100/500/500/500/3000/10000; 3,660 / 1,490 pools |
| P4 | NPM `totalSupply()` and `eth_getStorageAt(slot 14)` @20M/30M/34.7M/40M/52.86M | §2.1 table |
| P5 | `eth_getCode 0x8fe8…`, `0x9663…` | `0x` |
| P6 | `firecore tools firehose-client base.firehose.pinax.network:443 13899663:13899663 -o jsonl`; RPC receipt of `0x76aeccc2…` | log order 171..178; storage writes and preimages (§2.3, §2.5, §2.6); creation frame code_changes |
| P7 | @30,000,000 pool `0xb2cc…`: fee growth, `slot0`, `tickSpacing`, `gaugeFees` calls vs slots 7/8/6/15/10; `ticks(-198700)` vs words base+0..5 | all equal (§2.3–2.4) |
| P8 | `derive_check.py` on 52,800,000, 30,000,000, 13,899,663 | fg 3/3, ticks 9/9 (m1 and m2), positions 14/14 (incl. mint+burn revert) equal `eth_call` |
| P9 | `carry_check.py`, `tick_carry_check.py` on 34,719,819 and 45,000,000 | carried NPM fgi 3/3; mixed tick words 5/5 |
| P10 | `classify.py` on 13,899,663, 30,000,000, 52,800,000 | zero unclassified pool writes |
| P11 | `eth_call getPool(USDC,USDbC,1)` both orders @13,899,663 / @13,899,662; factory slot-6 keys | `0x98c7…` / `0x0`; keys `0x1dac6d56…`, `0x7d1b1c4b…` match the in-block writes |
| P12 | `firecore … {46,48,50,51,52}M`; binary search 45M–46M | v4 ≤ 45,903,999; v5 ≥ 45,904,000 |
| P13 | receipt vs call logs (13,899,663; 52,800,000); RPC receipt of `0x3b879426…` | §2.7 rows on logs |
| P14 | gas fields of all txs in 5 blocks | §2.7: types 0/1/2/4/126; formula = `gas_price` for 1,565 txs; deposits 0 |
| P15 | `revert_check.py` on 30,000,000; `cast storage` slot 7 @29,999,999/30,000,000 | reverted writes excluded; carried value exact |
| P16 | `eth_getLogs` Flash topic over [34.69M, 34.73M); `cast code` filter for clones; `factory()`/`tickSpacing()`; fee growth @34,719,818/819 | Flash pools `0x82321f3b…` (34,719,819) and `0x0c1a09d5…` (34,724,167), both Factory `0x5e7b…`; fg1 in-block, fg0 carried |
| P17 | `eth_getLogs` Swap on `0x98c7…` from 13,899,663 | first swap at 13,908,606, tx `0xcf266230…ef82` |
