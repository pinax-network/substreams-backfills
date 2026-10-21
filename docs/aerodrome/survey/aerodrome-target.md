# Aerodrome Slipstream Base (`QmasYjyp…`): complete semantic inventory

Survey date: 2026-10-20. Scope: read-only. Nothing was pushed, commented or written outside the scratchpad.

Legend used throughout:

- **VERIFIED**: I read the code or bytes myself. That covers manifest and schema text, the WASM decompile/WAT, live Firehose blocks and live VictoriaMetrics series.
- **CLAIMED**: a statement made by a README, a doc, the memory notes or an issue that I did not re-derive.
- `D:<file>:<line>` cites decompiled output that I produced in the scratchpad. It is reproducible with the commands in Appendix A, and the line numbers are stable for the exact retained WASM bytes.

Scratchpad artifacts (all absolute):

- Decompiles: `/private/tmp/claude-501/-Users-denis-Github-substreams-backfills/6974ca53-b59e-4778-97ac-3643f910b626/scratchpad/aero-wasm/{Factory,NonfungiblePositionManager,Pool}.dcmp`. The `.wat` files sit next to them, along with string-annotated copies `Pool.annot.dcmp` and `NPM.annot.dcmp` (same line numbers).
- Extracted UTF-16 strings, with memory addresses: `…/aero-wasm/*.strings.txt`
- Throwaway extractors (Python, run with `-I`, scratchpad only): `…/scratchpad/tools/asstrings.py`, `asarrays.py`, `count_events.py`
- Upstream Uniswap/v3-subgraph sources at `c63cb39807` (2022-03-13): `…/aero-wasm/upstream_{core,npm,pricing}_c63cb39.ts`
- Deployed Uniswap V3 Base (`Qmb4VUcA…`) comparison extracts: `…/scratchpad/uv3base/`
- Base Firehose sample blocks: `…/scratchpad/probe/blk_*.jsonl`

---

## 0. Key findings (read this first)

1. **The target is a single segment with no graft** (VERIFIED). `reference/deployment.yaml` has no `graft:` block, and the profile records `"graft": null` (`aerodrome-slipstream-base/layout-profile-v1.json` line 18 in the pretty-printed form; README.md:16 "Concrete graft: none"). Spec `1.2.0`, apiVersion `0.0.7`, features `nonFatalErrors` and `grafting` (`deployment.yaml:88-95`). Three mappings, ten event handlers, no call handlers, no block handlers.
2. **The mapping is canonical Uniswap/v3-subgraph from about 2022–2023 with a small set of Slipstream and Base edits** (VERIFIED against upstream `c63cb39807`). Compared with the upstream code:
   - The Factory maps Slipstream `tickSpacing` to `feeTier` with a hard-coded table: 1→100, 50→500, 100→500, 200→3000, anything else→10000 (`D:Factory.dcmp:3312`, confirmed in the WAT).
   - `handleSwap` then turns `feeTier` back into a "tick spacing" through **canonical V3's** `feeTierToTickSpacing` (10000→200, 3000→60, 500→10, 100→1; `D:Pool.dcmp:8455-8485`). The tick-crossing loop therefore walks the **wrong spacing** for every Slipstream spacing except 1. It visits only ticks whose index is a multiple of the canonical spacing, which drives both which `Tick` rows are updated and which `ticks()` eth_calls are issued.
   - **`ticks()` field misbinding.** `updateTickFeeVarsAndSave` stores `ticks(i).value2` into `Tick.feeGrowthOutside0X128` and `value3` into `Tick.feeGrowthOutside1X128`. This was correct on canonical V3 (8-tuple). Under Slipstream's 10-tuple ABI, `value2` is **`stakedLiquidityNet` (int128, can be negative)** and `value3` is the real `feeGrowthOutside0X128`. Confirmed at the WAT struct level (`D:Pool.wat`, `updateTickFeeVarsAndSave`; struct offsets 8 and 12; see §5.4). Every Tick and TickDayData row carries this.
   - `Token.version` plus `addMissingWhitelistedPools`. On the first swap involving a token whose `version` is null or 0, the mapping sets `version = 2` and makes four **non-try** calls: `Factory.getPool(USDC, token, {100, 500, 3000, 10000})`. It pushes non-zero results into a **temporary copy** of `token.whitelistPools` and never writes that copy back. The net persisted effect is only `Token.version = 2`, plus four eth_calls (§5.3).
   - Pricing is rebound to Base. `WHITELIST_TOKENS = [WETH 0x4200…0006, USDC 0x8335…2913, AERO 0x9401…8631]`. There is no stable-coin branch. The ETH price comes from Slipstream pool `0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59` as `token1Price`, but only when `totalValueLockedToken0 > 0.01`. `MINIMUM_ETH_LOCKED = 0.01`. `findEthPerToken(token, otherToken)` takes two arguments and adds an exclusion rule (§5.5).
   - The NPM handlers are the newer "collectedToken" profile: `collectedFeesToken{0,1} = collectedToken{0,1} − withdrawnToken{0,1}`. `getPosition` calls `getPool(address,address,int24)` with the position's `tickSpacing`, which is correct for Slipstream.
   - **Flash**: the handler updates only `Pool.feeGrowthGlobal{0,1}X128` and never writes a `Flash` row. This is **identical to upstream `c63cb39`**, so it is not a Slipstream delta (VERIFIED, upstream `core.ts:492-501`).
3. **Three of the 20 entities are never written by any mapping**: `Collect`, `Flash`, `TickHourData` (VERIFIED by store.set target inventory, §4). Write-only entities that are never read back: `Swap`, `Mint`, `Burn`, `PositionSnapshot`, and the history rows of the day/hour tables.
4. **Inert mainnet hot fixes are still compiled in.** They are: pool `0x8fe8d9bb…` (Factory and NPM guards), pool `0x9663f2ca…` (Swap guard), and the NPM block guard `block.number == 14317993`. That block number **is** inside the Base range. I fetched Base block 14,317,993 from Firehose and found no Aerodrome NPM events in it, so the guard is inert in practice (VERIFIED, §5.6).
5. **eth_call load is the dominant cost.** Live graph-node metrics at subgraph head about 34.7M show roughly **45 RPC eth_calls per block** against about **58 handler invocations per block**. Over 6 hours: positions 374k, ticks 278k, feeGrowthGlobal 202k ×2, getPool 47k (VERIFIED, §9). My estimate for the whole history is **about 1.0–2.5 B handler invocations and about 0.8–2 B eth_calls** (order of magnitude only).
6. **Pinax Base Firehose serves EXTENDED blocks** (VERIFIED live). Block 30,000,000 has 5,922 call traces, 868 storage changes and 5,161 balance changes. Every call except ERC20 metadata can therefore in principle be derived from storage changes plus event-derived state, with no RPC. ERC20 metadata covers a few thousand tokens and is fetched once.
7. **Feasibility, in short (§10).**
   - Approach B (run the deployed WASM in `mapping-host`) needs the least semantic work, since all of the oddities above come for free. It is blocked by three things: (i) serial throughput, measured at 1.9–10.9 blocks/s on mainnet V3 at about 2 handler groups per block, while Aerodrome is about 58 per block; (ii) an in-memory store that would have to hold hundreds of millions of write-only rows; (iii) a cassette of about 1 B eth_calls.
   - Approach A (Substreams extraction plus a native Rust reducer, V4-style) scales. It means re-implementing the semantics in §5 exactly, including the bugs. Some pieces exist to reuse: the V3 storage-slot readers in `uniswap-v3/source/src/storage/`, the V3 NPM/Flash/Position/Transaction host reducers in `crates/uniswap-v3-reducers`, and the engine's generic BlockChanges, PoI and COPY path. None of these is a drop-in.
   - **Recommended hybrid**: use the mapping-host as the **semantic oracle and fixture generator** over short contiguous windows, and approach A as the production path.

---

## 1. Inputs read

| Input | Path | Notes |
|---|---|---|
| Target README | `/Users/denis/Github/substreams-backfills/aerodrome-slipstream-base/README.md` (82 lines) | static-baseline claims, lines 26-66 |
| Provenance lock | `…/aerodrome-slipstream-base/QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV.yaml` | all truth gates false; `market_snapshot` 962,722 q/24h, 1,154.657 GRT (lines 7-11) |
| Layout profile | `…/aerodrome-slipstream-base/layout-profile-v1.json` | handler topic0s, call injections, schema diff, constants |
| Manifest | `…/aerodrome-slipstream-base/reference/deployment.yaml` (151 lines) | |
| Schema | `…/aerodrome-slipstream-base/reference/schema.graphql` (658 lines) | |
| ABIs | `…/reference/abis/{ERC20,ERC20NameBytes,ERC20SymbolBytes,Factory,NonfungiblePositionManager,Pool}.json` | |
| WASMs | `…/reference/mappings/{Factory,NonfungiblePositionManager,Pool}.wasm` | 50,419 / 49,615 / 77,470 bytes |
| Issues | substreams-backfills #86, #88, #91, #83, #1 (`gh issue view`) | §11 |
| V3 comparison | `uniswap-v3/README.md`, `docs/uniswap-v3-execution-model.md`, `docs/v3-mapping-host-runtime.md`, `docs/v3-mainnet-handoff-2026-09-04.md`, `mapping-host/README.md`, `crates/README.md`, `uniswap-v3/source/src/{rpc.rs,storage/*}`, mapping-host bundle `segments/Qmb4VUcA…` | |
| Upstream | `Uniswap/v3-subgraph` @ `c63cb39807` (`gh api`) | `src/mappings/core.ts`, `position-manager.ts`, `src/utils/pricing.ts` |
| Engine | read-only snapshot `…/scratchpad/ro/engine` (README, docs/benchmark-100k.md, docs/direct-postgres.md) | |
| Live | VictoriaMetrics `P4169E866C3094E38`, Pinax Base Firehose `base.firehose.pinax.network:443` | under 10 min of probing |

Tools: `wasm-objdump`, `wasm2wat`, `wasm-decompile` (wabt, Homebrew) and `firecore tools firehose-client`. `wasm-tools` is not installed.

---

## 2. Data sources, templates, handlers (VERIFIED from `reference/deployment.yaml`)

| Component | Kind | Address | Start block | Mapping CID | ABIs bound |
|---|---|---|---|---|---|
| `Factory` | dataSource (`deployment.yaml:1-36`) | `0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a` | 13,843,704 | `QmZQVsukQt6nXKctyy2WSMWN5grVXKph5fR7ahxS11Uebs` | Factory, ERC20, ERC20SymbolBytes, ERC20NameBytes, Pool |
| `NonfungiblePositionManager` | dataSource (`:37-86`) | `0x827922686190790b37229fd06084350e74485b72` | 13,843,719 | `QmcoeFHridxYBRFnrZ33v3PRAgvqunBfxe9gsCPhJQB4dy` | NonfungiblePositionManager, Pool, Factory, ERC20 |
| `Pool` | template (`:96-151`), created by `Factory.handlePoolCreated` via `dataSource.create("Pool", [poolHex])` with no context (`D:Factory.dcmp:3553`) | dynamic | n/a | `QmQgC18iXqZc5Jp78KZs6wNpk2oZvgbe9TeMQnH9K7eMah` | Pool, Factory, ERC20 |

Block 13,843,704 falls around 2024-04-30 UTC, using Base genesis 1686789347 and 2 s blocks (my arithmetic).

### Event handlers (topic0s from `layout-profile-v1.json`; signatures from the manifest)

| Source | Handler | Event (indexed) | topic0 | Declared `calls:` (manifest) |
|---|---|---|---|---|
| Factory | `handlePoolCreated` | `PoolCreated(indexed address token0, indexed address token1, indexed int24 tickSpacing, address pool)` (`:25`) | `0xab0d57f0…9ac2` | none |
| NPM | `handleIncreaseLiquidity` | `IncreaseLiquidity(indexed uint256 tokenId, uint128 liquidity, uint256 amount0, uint256 amount1)` (`:60`) | `0x3067048b…e35f` | `positions: NPM[event.address].positions(tokenId)` (`:57-59`) |
| NPM | `handleDecreaseLiquidity` | `DecreaseLiquidity(indexed uint256, uint128, uint256, uint256)` (`:65`) | `0x26f6a048…77b4` | positions |
| NPM | `handleCollect` | `Collect(indexed uint256 tokenId, address recipient, uint256 amount0, uint256 amount1)` (`:70`) | `0x40d0efd1…8f01` | positions |
| NPM | `handleTransfer` | `Transfer(indexed address from, indexed address to, indexed uint256 tokenId)` (`:75`) | `0xddf252ad…b3ef` | positions |
| Pool | `handleInitialize` | `Initialize(uint160 sqrtPriceX96, int24 tick)` (`:114`) | `0x98636036…4c95` | none |
| Pool | `handleSwap` | `Swap(indexed address sender, indexed address recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)` (`:119-121`) | `0xc42079f9…ca67` | `feeGrowthGlobal0X128()`, `feeGrowthGlobal1X128()` (`:116-118`) |
| Pool | `handleMint` | `Mint(address sender, indexed address owner, indexed int24 tickLower, indexed int24 tickUpper, uint128 amount, uint256 amount0, uint256 amount1)` (`:127-128`) | `0x7a53080b…0bde` | `ticks(tickLower)`, `ticks(tickUpper)` (`:123-125`) |
| Pool | `handleBurn` | `Burn(indexed address owner, indexed int24 tickLower, indexed int24 tickUpper, uint128 amount, uint256 amount0, uint256 amount1)` (`:134-135`) | `0x0c396cd9…982c` | ticks(lower/upper) |
| Pool | `handleFlash` | `Flash(indexed address sender, indexed address recipient, uint256 amount0, uint256 amount1, uint256 paid0, uint256 paid1)` (`:141-142`) | `0xbdbdb71d…a633` | feeGrowthGlobal0/1 |

- **Call handlers: none. Block handlers: none** (VERIFIED: the manifest has only `eventHandlers`).
- Pool events that are present in the ABI but not subscribed: `Collect(…)` (pool-level), `CollectFees`, `IncreaseObservationCardinalityNext`, `SetFeeProtocol` (layout-profile `pool_specific_events_not_subscribed`; ABI listing VERIFIED).
- The NPM `Transfer` topic0 is the same as ERC20 Transfer. It only matches because the data source is address-filtered to the NPM.

### Graph Node execution facts that matter for any reimplementation

- **PoI**: spec `1.2.0` is ≥ `0.0.6`, so the **Fast** PoI is used. The mapping-host rule is at `mapping-host/README.md:319` and `mapping-host/src/poi.rs:17-51`. All eight V3 bundles are Legacy, so Fast has never been exercised by the V3 lane evidence (CLAIMED by `poi.rs:17-18`).
- **`nonFatalErrors`**: a deterministic handler error discards only that handler's ops (CLAIMED, mapping-host model at `mapping-host/README.md:386-390`).
- **Declared calls (`calls:`)** are a spec ≥ 1.2 feature. The mapping still issues the same `ethereum.call` explicitly, which I verified by finding the signature strings in the WASM, so declared calls only prefetch into the call cache. All V3 mapping-host bundles are spec 0.0.2/0.0.4 (`mapping-host/README.md:92-101`). **UNVERIFIED: whether the mapping-host executes or ignores `calls:` blocks correctly.** It is a risk only for approach B.
- **Dynamic data sources and waves.** In Slipstream's `createPool`, the pool's `initialize()` (which emits `Initialize`) runs **before** the factory emits `PoolCreated`. That is CLAIMED from my memory of the Slipstream source and not verified here. Graph Node processes a newly created template's triggers for the same block in a later wave, so `handleInitialize` runs **after** `handlePoolCreated` despite having the lower log index. Any reimplementation must reproduce the wave order (first wave: Factory, NPM and existing pools in log order; later waves: pools created in this block).
- **Host-function surface** (VERIFIED, `wasm-objdump -j Import`):
  - Factory: `store.get/set`, `ethereum.call`, `dataSource.create`, `log.log`, `bigInt.plus/pow`, `bigDecimal.fromString/toString`, `typeConversion.*`.
  - NPM: `store.get/set`, `ethereum.call`, `bigInt.plus/minus`, `bigDecimal.plus/minus/times/dividedBy/fromString/toString`.
  - Pool: the same plus `bigInt.times/dividedBy/mod/pow`.
  - **No `store.remove`** in any module, so no deletes. **No `dataSource.address/context`**, `crypto`, `ipfs` or `json`.

---

## 3. Contract ABIs: Slipstream-specific facts (VERIFIED from the ABI JSON and the WASM call-signature strings)

| Call | ABI signature used by the mapping (string in the WASM) | Slipstream difference vs canonical V3 |
|---|---|---|
| `Pool.ticks(int24)` | `ticks(int24):(uint128,int128,int128,uint256,uint256,uint256,int56,uint160,uint32,bool)` (`Pool.strings.txt` @15232) | 10-tuple: `liquidityGross, liquidityNet, stakedLiquidityNet, feeGrowthOutside0X128, feeGrowthOutside1X128, rewardGrowthOutsideX128, tickCumulativeOutside, secondsPerLiquidityOutsideX128, secondsOutside, initialized`. Canonical is an 8-tuple with no staked or reward fields. |
| `NPM.positions(uint256)` | `positions(uint256):(uint96,address,address,address,int24,int24,int24,uint128,uint256,uint256,uint128,uint128)` (NPM @2784) | slot 4 is `int24 tickSpacing` (canonical: `uint24 fee`) |
| `Factory.getPool(address,address,int24)` | `getPool(address,address,int24):(address)` (Pool @17104, NPM @3696) | int24 tickSpacing key (canonical: uint24 fee) |
| `Pool.feeGrowthGlobal{0,1}X128()` | `feeGrowthGlobal0X128():(uint256)` / `…1X128` (Pool @17904/18032) | same as V3 |
| ERC20 | `symbol():(string)`, `symbol():(bytes32)`, `name():(string)`, `name():(bytes32)`, `totalSupply():(uint256)`, `decimals():(uint8)` (Factory @8160…9520) | same as V3 |

The Factory ABI also contains `tickSpacingToFee`, `getSwapFee`, `getUnstakedFee`, `TickSpacingEnabled(int24,uint24)` and others. **The mapping never calls them**: those strings are absent from all three WASMs (VERIFIED). The real dynamic swap fee (fee module) is ignored, and `feeTier` comes only from the hard-coded tickSpacing table.

---

## 4. Entities (20 types, 302 fields, all mutable)

Counts are from `layout-profile-v1.json` `entity_layout` (`entity_count: 20`, `field_count: 302`, `all_entities_mutable: true`). VERIFIED: `schema.graphql` has no `immutable: true`.

**Store-access inventory** (VERIFIED: the entity-name constant passed to each `store.set` / `store.get` site, decoded from the data segment):

| WASM | `store.set` targets | `store.get` targets |
|---|---|---|
| Factory | Pool, Factory, Bundle, Token | Token (×2), Factory |
| NPM | Position, PositionSnapshot, Transaction | Position, Transaction, Token (×6) |
| Pool | Transaction, Tick, UniswapDayData, TokenDayData, TokenHourData, Mint, TickDayData, Burn, Swap, Factory, Pool, Token, Bundle, PoolDayData, PoolHourData | Pool, Token, Bundle, Factory, Tick, Transaction, UniswapDayData, PoolDayData, PoolHourData, TokenDayData, TokenHourData, TickDayData |

- **Never written by any handler**: `Collect`, `Flash`, `TickHourData`. Their entity-name strings do not occur in any WASM, so these tables stay empty.
- **Written but never read back (write-only)**: `Swap`, `Mint`, `Burn`, `PositionSnapshot`. `Transaction` is read, but every field is then overwritten from the event, so it needs only per-block state.
- **Day/hour entities are time-keyed.** Only the current period's row per key is ever re-read.

### Entity table

The ID scheme column comes from VERIFIED decompile: string concatenation and `bytesToHex`, which produces lowercase `0x…` hex.

| Entity | Fields | ID scheme | Written by | Notes |
|---|---:|---|---|---|
| `Factory` | 14 | constant `"0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a"` (Factory @1760) | Factory.PoolCreated (create on first pool, `poolCount+1`), Pool.Swap/Mint/Burn | `owner` = `0x000…000` at creation. The `*Untracked` TVL fields stay 0 forever. |
| `Bundle` | 2 | `"1"` | Factory.PoolCreated (create, `ethPriceUSD=0`), Pool.Initialize/Swap (`ethPriceUSD=getEthPriceInUSD()`) | |
| `Token` | 17 (+`tokenDayData` derived) | token address hex | Factory.PoolCreated (create), Pool.Initialize (derivedETH), Pool.Swap/Mint/Burn | **`version: Int` (nullable)**, set only by Swap. **`poolCount` is never incremented** (canonical bug). `whitelistPools` is appended only by the Factory. `totalSupply` is fixed at creation. `totalValueLockedUSDUntracked` stays 0. |
| `Pool` | 31 (+6 derived) | pool address hex | Factory.PoolCreated (create), Pool.Initialize/Swap/Mint/Burn/Flash | `tick` is null until Initialize. `feeTier` comes from the tickSpacing table. These fields stay 0: `observationIndex`, `collectedFees*`, `liquidityProviderCount`, `totalValueLockedUSDUntracked`. |
| `Tick` | 23 | `"{poolHex}#{tickIdx}"` (i32 decimal) | Pool.Mint (create), Pool.Mint/Burn (liquidity), Pool.Mint/Burn/Swap via `updateTickFeeVarsAndSave` | `feeGrowthOutside0X128 := ticks().stakedLiquidityNet` (**bug**). `feeGrowthOutside1X128 := ticks().feeGrowthOutside0X128`. `price0=1.0001^tick` (iterative), `price1=1/price0`. Volume, fee and LP-count fields stay 0. |
| `Position` | 20 | `tokenId.toString()` (decimal) | NPM (all 4 handlers; created by `getPosition`) | `owner` starts at `0x0` and is set on Transfer. `tickLower`/`tickUpper` reference the `"{pool}#{tick}"` Tick IDs. `collectedToken0/1` are **target-only fields**. |
| `PositionSnapshot` | 16 | `"{position.id}#{block.number}"` | NPM (all 4 handlers) | Last write in a block wins. Has no `collectedToken*`. |
| `Transaction` | 5 (+5 derived) | tx hash hex | `loadTransaction` in Pool (Swap/Mint/Burn) and NPM (getPosition on create, snapshot) | **`gasUsed := transaction.gasLimit`** (VERIFIED: graph-ts `Transaction` field index 5, `D:Pool.dcmp` loadTransaction). `gasPrice := transaction.gasPrice`. |
| `Mint` | 16 | `"{txHash}#{pool.txCount}"` (after increment) | Pool.Mint | `sender` is nullable. `origin` = tx.from. `logIndex` = event.logIndex. |
| `Burn` | 15 | `"{txHash}#{pool.txCount}"` | Pool.Burn | |
| `Swap` | 16 | `"{txHash}#{pool.txCount}"` | Pool.Swap | `amountUSD` = tracked USD / 2 |
| `Collect` | 11 | n/a | **never** | |
| `Flash` | 12 | n/a | **never** | |
| `UniswapDayData` | 8 | `"{dayID}"` (timestamp/86400) | Pool.Swap/Mint/Burn | `tvlUSD` and `txCount` are copied from the **stored** Factory |
| `PoolDayData` | 22 | `"{pool}-{dayID}"`, `date = dayID*86400` | Pool.Initialize/Swap/Mint/Burn | `close` is **never updated** after creation (canonical) |
| `PoolHourData` | 22 | `"{pool}-{hourIndex}"`, `periodStartUnix = hourIndex*3600` | same | `close` is updated |
| `TickHourData` | 12 | n/a | **never** | |
| `TickDayData` | 14 | `"{tick.id}-{dayID}"` | via `updateTickFeeVarsAndSave` | **`volumeToken1 := tick.volumeToken0`** (canonical bug). Fee-growth fields copied from Tick, so they carry the stakedLiquidityNet misbinding. |
| `TokenDayData` | 14 | `"{token}-{dayID}"` | Pool.Swap/Mint/Burn | `untrackedVolumeUSD += amountTotalUSDTracked` (canonical bug: tracked, not untracked) |
| `TokenHourData` | 14 | `"{token}-{hourIndex}"` | same | same bug |

**Schema delta vs the retained Qma8 Uniswap V3 schema** (layout-profile `qma8_static_gap`; CLAIMED by the profile, consistent with the schema text): the target adds only `Token.version: Int`, `Position.collectedToken0: BigDecimal!` and `Position.collectedToken1: BigDecimal!`.

---

## 5. Handler semantics (VERIFIED by decompile and WAT; pseudo-code in source order)

The canonical body is `Uniswap/v3-subgraph@c63cb39807`. Every deviation from it is marked **Δ**.

### 5.1 `Factory.handlePoolCreated` (`D:Factory.dcmp:2577-3575`)

```
if event.params.pool == 0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248: return   # inherited mainnet hot fix (:2586-2620)
factory = load Factory(FACTORY_ADDRESS)
if null: factory = new(... all zeros, owner=0x0…0); bundle = new Bundle("1", ethPriceUSD=0); bundle.save()  # Bundle saved immediately
factory.poolCount += 1
pool = new Pool(event.params.pool hex)
token0 = load Token(t0); token1 = load Token(t1)
for each missing token: new Token(id) with
    symbol = fetchTokenSymbol(addr)  name = fetchTokenName(addr)
    totalSupply = fetchTokenTotalSupply(addr)
    decimals = fetchTokenDecimals(addr)            # never null in practice, see below
    if decimals == null: log.debug("mybug the decimal on token 0 was null"); return   # dead code
    derivedETH=volume=volumeUSD=feesUSD=untrackedVolumeUSD=totalValueLocked=totalValueLockedUSD=totalValueLockedUSDUntracked=0
    txCount=poolCount=0; whitelistPools=[]          # version NOT set (null)
if WHITELIST.includes(token0.id): token1.whitelistPools.push(pool.id)   # persisted via setter (:3209-3215)
if WHITELIST.includes(token1.id): token0.whitelistPools.push(pool.id)   # (:3220-3226)
pool.token0, token1
Δ pool.feeTier = { tickSpacing==1:100, ==50:500, ==100:500, ==200:3000, else:10000 }   # (:3312; WAT-verified select order)
pool.createdAtTimestamp = block.timestamp; createdAtBlockNumber = block.number
pool.liquidityProviderCount=txCount=liquidity=sqrtPrice=feeGrowthGlobal0X128=feeGrowthGlobal1X128=0
pool.token0Price=token1Price=0; observationIndex=0; TVL*/volume*/fees*/collectedFees* = 0   # tick stays null
pool.save(); dataSource.create("Pool",[poolHex]); token0.save(); token1.save(); factory.save()
```

- `tickSpacing` goes through `toI32()` with an overflow abort ("overflow converting … to i32").
- **Token metadata fetchers** (`D:Factory.dcmp:1912-2450`). `StaticTokenDefinition.fromAddress` searches an **empty** static list (array length 0 at `:1912-1935`), so there are no static overrides on Base.
  - `symbol`/`name`: try `string`. On revert, try `bytes32`. If that succeeds and the hex is not `0x00…01`, use `bytesToString(bytes32)`. Otherwise use `"unknown"`.
  - `totalSupply`: try; 0 on revert.
  - `decimals`: try. On success the value is returned if `compare(value, 255) != 1`, i.e. value ≤ 255. **Upstream used `< 255`**; this is decompile-level only and the `uint8` decode makes it largely moot. On revert or out of range it returns `BigInt.fromI32(0)`, never null. VERIFIED: the WAT tail ends in `i32.const 0; call BigInt.fromI32`.
  - Graph Node decode semantics apply: an ABI decode failure counts as a revert (CLAIMED, `mapping-host/README.md:241-245`), and `bytesToString` is a host function.

### 5.2 `Pool.handleInitialize` (`D:Pool.dcmp:3576-3662`)

```
pool = load Pool(event.address)!     # abort if null
pool.sqrtPrice = event.sqrtPriceX96; pool.tick = event.tick; pool.save()
token0 = load!; token1 = load!; bundle = load!("1")
bundle.ethPriceUSD = getEthPriceInUSD(); bundle.save()
updatePoolDayData(event); updatePoolHourData(event)      # these re-load Pool from store
token0.derivedETH = findEthPerToken(token0, token1)   Δ 2-arg
token1.derivedETH = findEthPerToken(token1, token0)
token0.save(); token1.save()
```

Token prices (`token0Price`/`token1Price`) are **not** set on Initialize (canonical). The first Swap sets them.

### 5.3 `Pool.handleSwap` (`D:Pool.dcmp:7005-8543`)

```
bundle = load!("1"); factory = load!(FACTORY); pool = load!(event.address)
if pool.id == "0x9663f2ca0454accad3e094448ea6f77443880454": return          # inherited mainnet hot fix (:7028)
token0 = load!(pool.token0); token1 = load!(pool.token1)
Δ for t in [token0, token1]:                                                 # (:7044-7066)
      if t.version is null or 0:
          t.version = 2                                                      # Value kind Int, value 2
          addMissingWhitelistedPools(t)                                      # (:6737-6810)
oldTick = pool.tick!                                                         # abort if null
amount0 = amount0Raw / 10^dec0 ; amount1 = ...  (convertTokenToDecimal: if decimals==0 → raw.toBigDecimal())
amount0Abs = amount0<0 ? amount0 * "-1" : amount0 ; same for 1
amount0ETH = amount0Abs*token0.derivedETH; amount1ETH = ...
amount0USD = amount0ETH*bundle.ethPriceUSD; amount1USD = ...
amountTotalUSDTracked = getTrackedAmountUSD(amount0Abs, token0, amount1Abs, token1) / 2
amountTotalETHTracked = ethPriceUSD != 0 ? amountTotalUSDTracked/ethPriceUSD : 0
amountTotalUSDUntracked = (amount0USD+amount1USD)/2
feesETH = amountTotalETHTracked*feeTier/1000000 ; feesUSD = amountTotalUSDTracked*feeTier/1000000
factory: txCount+1, totalVolumeETH+=ETHTracked, totalVolumeUSD+=USDTracked, untrackedVolumeUSD+=untracked,
         totalFeesETH+=feesETH, totalFeesUSD+=feesUSD, totalValueLockedETH -= pool.totalValueLockedETH
pool: volumeToken0+=amount0Abs, volumeToken1+=amount1Abs, volumeUSD+=USDTracked, untrackedVolumeUSD+=untracked,
      feesUSD+=feesUSD, txCount+1, liquidity=event.liquidity, tick=event.tick, sqrtPrice=event.sqrtPriceX96,
      totalValueLockedToken0+=amount0, totalValueLockedToken1+=amount1
token0: volume+=amount0Abs, totalValueLocked+=amount0, volumeUSD+=USDTracked, untrackedVolumeUSD+=untracked, feesUSD+=feesUSD, txCount+1
token1: same with amount1
price1 = (sqrtPrice² / Q192) * 10^dec0 / 10^dec1 ; price0 = price1!=0 ? 1/price1 : 0   # Q192 = 2^192 exact BigInt→BigDecimal
pool.token0Price = price0; pool.token1Price = price1; pool.save()             # (save #1)
bundle.ethPriceUSD = getEthPriceInUSD(); bundle.save()
token0.derivedETH = findEthPerToken(token0, token1); token1.derivedETH = findEthPerToken(token1, token0)
pool.totalValueLockedETH = TVL0*derivedETH0 + TVL1*derivedETH1 ; pool.totalValueLockedUSD = TVLETH*ethPrice
factory.totalValueLockedETH += pool.totalValueLockedETH ; factory.totalValueLockedUSD = factory.TVLETH*ethPrice
token0.totalValueLockedUSD = token0.TVL*derivedETH0*ethPrice ; token1 same
tx = loadTransaction(event)                                                  # saves Transaction
swap = new Swap("{tx}#{pool.txCount}") { transaction, timestamp=tx.timestamp, pool, token0, token1,
       sender, recipient, origin=tx.from, amount0, amount1, amountUSD=USDTracked, tick, sqrtPriceX96, logIndex }
pool.feeGrowthGlobal0X128 = Pool(event.address).feeGrowthGlobal0X128()      # non-try ethereum.call
pool.feeGrowthGlobal1X128 = Pool(event.address).feeGrowthGlobal1X128()
uniswapDayData = updateUniswapDayData(e); poolDayData = updatePoolDayData(e); poolHourData = updatePoolHourData(e)
token0DayData, token1DayData, token0HourData, token1HourData = update…(token, e)
uniswapDayData: volumeETH+=ETHTracked, volumeUSD+=USDTracked, feesUSD+=feesUSD
poolDayData/HourData: volumeUSD+=USDTracked, volumeToken0+=amount0Abs, volumeToken1+=amount1Abs, feesUSD+=feesUSD
tokenDay/HourData: volume+=amountAbs, volumeUSD+=USDTracked, untrackedVolumeUSD+=USDTracked (bug), feesUSD+=feesUSD
save: Swap, TokenDayData×2, UniswapDayData, PoolDayData, TokenHourData×2, PoolHourData, Factory, Pool, Token0, Token1
# tick crossing (canonical algorithm, Δ effectively wrong spacing for Slipstream)
newTick = pool.tick!
tickSpacing = feeTierToTickSpacing(pool.feeTier)   # 10000→200, 3000→60, 500→10, 100→1, else abort (src/utils/tick.ts:57)
modulo = newTick mod tickSpacing                   # graph-node BigInt.mod (sign follows dividend)
if modulo == 0: loadTickUpdateFeeVarsAndSave(newTick)
if |oldTick-newTick| / tickSpacing <= 100:
   if newTick > oldTick: for i = oldTick + (tickSpacing - modulo); i <= newTick; i += tickSpacing: loadTickUpdateFeeVarsAndSave(i)
   elif newTick < oldTick: for i = oldTick - modulo; i >= newTick; i -= tickSpacing: loadTickUpdateFeeVarsAndSave(i)
loadTickUpdateFeeVarsAndSave(i): tick = load Tick("{event.address}#{i}"); if tick: updateTickFeeVarsAndSave(tick)
```

Read-after-save semantics that a reimplementation must reproduce. The interval helpers `store.get` the Pool and Factory, so they see the **last saved** version, not in-memory edits:

- In Swap, the first `pool.save()` happens before `totalValueLockedETH/USD` and before `feeGrowthGlobal*` are assigned. `PoolDayData.tvlUSD` and `feeGrowthGlobal*` therefore get the values from **before** those assignments.
- `UniswapDayData.tvlUSD` and `txCount` come from the **previously stored** Factory.

`addMissingWhitelistedPools(token)` (`D:Pool.dcmp:6737-6810`):

```
if token.id != USDC(0x833589fcd6edb6e08f4c7c32d4f71b54bda02913):
   p100   = Factory(0x5e7b…).getPool(USDC, token, 100)    # non-try; int24 arg; Slipstream tickSpacing semantics
   p500   = …getPool(USDC, token, 500)
   p3000  = …getPool(USDC, token, 3000)
   p10000 = …getPool(USDC, token, 10000)
   for p in [p100,p500,p3000,p10000]: if p != 0x0: token.whitelistPools /*getter copy*/.push(p.toHex())
```

**The push is lost.** `Token#get:whitelistPools` (`D:Pool.dcmp:3318`) builds a fresh array on every call, and the `whitelistPools` key (string @9760) is referenced only by that getter anywhere in `Pool.wasm`. No setter exists, which I VERIFIED by grepping `9760`. So the only persisted effect is `Token.version = 2`.

The calls still matter for parity in one way: a non-try revert would abort the handler. On Slipstream, `getPool` is a public-mapping getter and should never revert (CLAIMED from contract knowledge). Values 500, 3000 and 10000 are fee tiers misused as tick spacings, so those three lookups almost certainly return `0x0`.

### 5.4 `Pool.handleMint` / `handleBurn` / `updateTickFeeVarsAndSave`

**Mint** (`D:Pool.dcmp:5468-6083`):

```
bundle!, pool!, factory!, token0!, token1!
amount0/1 = convertTokenToDecimal(event.amount0/1, decimals)
amountUSD = amount0*derivedETH0*ethPrice + amount1*derivedETH1*ethPrice
factory.totalValueLockedETH -= pool.totalValueLockedETH; factory.txCount+1
token0: txCount+1, totalValueLocked+=amount0, totalValueLockedUSD = TVL*derivedETH*ethPrice ; token1 same
pool.txCount+1
if pool.tick != null && tickLower <= pool.tick && tickUpper > pool.tick: pool.liquidity += event.amount
pool.TVL0 += amount0; pool.TVL1 += amount1; pool.TVLETH = TVL0*dETH0+TVL1*dETH1; pool.TVLUSD = TVLETH*ethPrice
factory.TVLETH += pool.TVLETH; factory.TVLUSD = factory.TVLETH*ethPrice
tx = loadTransaction(e)
mint = new Mint("{tx}#{pool.txCount}") { …, owner=event.owner, sender=event.sender (nullable), origin=tx.from,
        amount, amount0, amount1, amountUSD, tickLower, tickUpper, logIndex }
lowerTick = load Tick("{pool}#{tickLower}") ?? createTick(id, tickLower, pool.id, e)   # not saved yet
upperTick = … ?? createTick(…)
lowerTick.liquidityGross += amount; lowerTick.liquidityNet += amount
upperTick.liquidityGross += amount; upperTick.liquidityNet -= amount
updateUniswapDayData, updatePoolDayData, updatePoolHourData, updateTokenDayData×2, updateTokenHourData×2   # each saves
token0.save(); token1.save(); pool.save(); factory.save(); mint.save()
updateTickFeeVarsAndSave(lowerTick); updateTickFeeVarsAndSave(upperTick)       # each: ticks() call, Tick.save, TickDayData
```

**Burn** (`D:Pool.dcmp:6084-6667`) is symmetric with subtraction. `Tick.load(...)!` **aborts if null** (`core.ts:245/246` per the abort args). Order: interval updates, then `updateTickFeeVarsAndSave(lower)`, then `(upper)`, then saves of token0, token1, pool, factory and burn.

**`updateTickFeeVarsAndSave(tick, e)`** (`D:Pool.dcmp:5311-5467`, WAT-verified):

```
r = Pool(e.address).ticks(tick.tickIdx.toI32())     # non-try; full 10-field decode (field 9 must decode as bool)
Δ tick.feeGrowthOutside0X128 = r.value2   # = stakedLiquidityNet (int128)   ← struct offset 8
Δ tick.feeGrowthOutside1X128 = r.value3   # = feeGrowthOutside0X128          ← struct offset 12
tick.save(); updateTickDayData(tick, e)
```

**`createTick`** (`D:Pool.dcmp:4009-4277`) is canonical:

- `price0 = 1.0001^tickIdx`, computed by an O(|tick|) loop of BigDecimal multiplications with Graph Node's decimal rounding at each step. For a negative tick the result is `1/x` (with a zero guard). `price1 = 1/price0`.
- `poolAddress = pool.id`. Created/timestamp fields come from the block. Everything else is 0.

### 5.5 Pricing helpers (Δ, Base-specific)

**`getEthPriceInUSD()`** (`D:Pool.dcmp:2407-2422`):

```
p = load Pool("0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59")      # Slipstream WETH/USDC (token0=WETH, token1=USDC)
return (p != null && p.totalValueLockedToken0 > MINIMUM_ETH_LOCKED(0.01)) ? p.token1Price : 0
```

Upstream returns `usdcPool.token0Price` with no TVL condition.

**`findEthPerToken(token, other)`** (`D:Pool.dcmp:3431-3546`):

```
if token.id == WETH(0x4200…0006): return 1
largest = 0; price = 0                        # NO stable-coin branch (upstream had STABLE_COINS → 1/ethPrice)
for poolId in token.whitelistPools:
   pool = load!(poolId)
   if pool.liquidity > 0:
      if pool.token0 == token.id && !(pool.token1 == other.id && WHITELIST.includes(pool.token0)):
          t1 = load!(pool.token1); ethLocked = pool.TVL1*t1.derivedETH
          if ethLocked > largest && ethLocked > 0.01: largest = ethLocked; price = pool.token1Price*t1.derivedETH
      if pool.token1 == token.id && !(pool.token0 == other.id && WHITELIST.includes(pool.token1)):
          t0 = load!(pool.token0); ethLocked = pool.TVL0*t0.derivedETH
          if ethLocked > largest && ethLocked > 0.01: largest = ethLocked; price = pool.token0Price*t0.derivedETH
return price
```

The new exclusion: when the priced token is itself whitelisted, pools pairing it with the counter-token of the current swap are skipped. `t0`/`t1` are loaded from the store, so same-handler unsaved edits are invisible.

**`getTrackedAmountUSD`** is canonical (VERIFIED inline in Swap, `D:Pool.dcmp:7130-7180`). With `WHITELIST=[WETH,USDC,AERO]`:

- both tokens whitelisted: `a0*p0 + a1*p1`
- only token0 whitelisted: `a0*p0*2`
- only token1 whitelisted: `a1*p1*2`
- neither: `0`

### 5.6 NPM handlers (`D:NonfungiblePositionManager.dcmp:2007-3640`)

`getPosition(e, tokenId)` (`:2114-2617`):

```
pos = load Position(tokenId.toString())
if null:
   r = NPM(e.address).try_positions(tokenId)                       # try; reverts if token burned by end of block
   if !r.reverted:
      pool = Factory(0x5e7b…).getPool(r.token0, r.token1, r.tickSpacing)   # NON-try ethereum.call (abort on revert)
      pos = new Position{ owner=0x0, pool=poolHex, token0=r.value2, token1=r.value3,
            tickLower="{pool}#{r.value5}", tickUpper="{pool}#{r.value6}", liquidity=0,
            deposited*=withdrawn*=collected*=collectedFees*=0,
            transaction = loadTransaction(e).id,                # saves Transaction
            feeGrowthInside0LastX128=r.value8, feeGrowthInside1LastX128=r.value9 }
return pos   # NOT saved here
```

`updateFeeVars(pos, e, tokenId)` (`:2703-2730`): `try_positions(tokenId)`. If it did not revert, set `feeGrowthInside0/1LastX128 = value8/value9`.

| Handler | Body |
|---|---|
| IncreaseLiquidity (`:3090-3202`) | `if block.number == 14317993: return`. Then pos = getPosition(e, tokenId); if null return; if `pos.pool == 0x8fe8d9bb…` return. Load token0! and token1! (abort if null). `liquidity += event.liquidity`; `depositedToken0/1 += amount/10^dec`; updateFeeVars; `pos.save()`; savePositionSnapshot. |
| DecreaseLiquidity (`:3203-3357`) | Same guards. `liquidity -= event.liquidity`; `withdrawnToken0/1 += amount`; updateFeeVars; save; snapshot. |
| Collect (`:3358-3469`) | **No block guard**; pool guard applies. `collectedToken0 += amount0`; `collectedToken1 += amount1`; `collectedFeesToken0 = collectedToken0 − withdrawnToken0`; `collectedFeesToken1 = collectedToken1 − withdrawnToken1`; updateFeeVars; save; snapshot. |
| Transfer (`:3470-…`) | pos = getPosition(e, tokenId = param 2); if null return; `owner = event.to`; save; snapshot. No pool guard and no updateFeeVars. |

`savePositionSnapshot` (`:2817-3089`) creates `id "{pos.id}#{block}"` and copies owner, pool, position, blockNumber, timestamp, liquidity, deposited/withdrawn, collectedFees, `transaction = loadTransaction(e).id`, and feeGrowthInside. Then it saves.

Guard checks (VERIFIED):

- Base block 14,317,993 is after the NPM start block (13,843,719), so the guard is live code.
- Firehose shows **zero NPM events** in Base block 14,317,993 (`count_events.py` → `{'anyV3.Swap': 8}`), so the guard is inert in practice.
- I did not verify whether `0x8fe8d9bb…` or `0x9663f2ca…` exist as Slipstream pools on Base. Both are mainnet Uniswap pools and are cryptographically unlikely to collide. Check them against the PoolCreated set in fixtures.

---

## 6. Every `ethereum.call` the mappings make (the hard part)

All calls are evaluated by Graph Node at the **post-block state** of the event's block (call at block hash; CLAIMED in `mapping-host/README.md:247-275`). Non-try calls abort the handler on revert or decode failure. Try calls yield `reverted`.

| # | Contract.function (int sig) | Handler(s) | Trigger condition | try? | Values consumed | Declared in manifest? | Live 6 h count (34.70M head)¹ |
|---|---|---|---|---|---|---|---|
| C1 | `ERC20(t).symbol():(string)`, then on revert `symbol():(bytes32)` | PoolCreated | each **new** token | try | string or bytes32→string | no | 7 / 6 h |
| C2 | `ERC20(t).name():(string)`, then on revert `name():(bytes32)` | PoolCreated | new token | try | same | no | 7 |
| C3 | `ERC20(t).totalSupply():(uint256)` | PoolCreated | new token | try | value, or 0 | no | 7 |
| C4 | `ERC20(t).decimals():(uint8)` | PoolCreated | new token | try | value ≤255, else 0 | no | 7 |
| C5 | `Pool(e.address).feeGrowthGlobal0X128()` and `…1X128()` | **Swap**, **Flash** | every event (Swap: after the pool guard) | **non-try** | full uint256 | yes | 202,045 each |
| C6 | `Pool(e.address).ticks(tickLower)` and `ticks(tickUpper)` | **Mint**, **Burn** | every event | **non-try** | value2 (stakedLiquidityNet), value3 (feeGrowthOutside0); full 10-field decode | yes | (with C7) 277,929 |
| C7 | `Pool(e.address).ticks(i)` | **Swap** (tick crossing) | for each `i` in the canonical-spacing walk **where a Tick entity exists** (≤101 per swap) | **non-try** | as C6 | **no** | (incl. above) |
| C8 | `NPM(e.address).positions(tokenId)` | Increase, Decrease, Collect (updateFeeVars, always); all 4 handlers when the Position is not yet stored (getPosition) | per event | try | revert flag; value2..6 at create, value8/9 for fee vars | yes (one per event) | 374,028 |
| C9 | `Factory(0x5e7b…).getPool(token0, token1, tickSpacing)` | NPM getPosition | Position not yet stored and C8 did not revert | **non-try** | pool address | no | (with C10) 46,991 |
| C10 | `Factory(0x5e7b…).getPool(USDC, token, {100,500,3000,10000})` | Swap | first swap per token with `version ∈ {null,0}` and token ≠ USDC, ×4 | **non-try** | discarded (lost push) | no | (incl. above) |

¹ `sum by (contract_name, method)(increase(deployment_eth_call_execution_time_count{deployment="QmasYjyp…"}[6h]))` on 2026-10-20. The window covered **24,584 blocks**. In the same window the handler counts were: Swap 305,554; Transfer 303,056; Burn 275,079; Collect 270,181; Decrease 90,339; Mint 90,072; Increase 90,063; PoolCreated 9; Initialize 9; Flash 3. The call metric undercounts logical calls: positions (374k) is below the number of Increase+Decrease+Collect events (450k), so cache and declared-call hits are not counted. **Treat it as RPC volume, not as mapping call volume.**

### Derivability without RPC (relevant to approach A)

| Call | Derivable from | Confidence / work |
|---|---|---|
| C1–C4 | Not from Firehose. Needs an archive RPC at the PoolCreated block, or Substreams `RpcBatch` (`substreams_ethereum::rpc`, used by `uniswap-v3/source/src/rpc.rs:1-90`). A few thousand tokens. | Easy, but Graph Node's decode-failure-is-revert and `bytesToString` semantics must be replicated. |
| C5 | Pool storage slots for `feeGrowthGlobal0X128`/`1X128`: last storage change at or before the block. Needs a store of the last value per pool, since a Flash or Swap always writes them, but carrying them is safer. | **Slipstream `CLPool` storage layout must be pinned.** Pools are EIP-1167 clones, so immutables become storage and the slot numbers differ from canonical V3's slot 1/2 (`uniswap-v3/source/src/storage/uniswap_v3_pool.rs:19-50`). |
| C6/C7 | `ticks` mapping slot `keccak(tick, ticksSlot) + k`. Candidate ticks are the `(pool, tick)` pairs ever named by a Mint (Tick entities are only created by Mint and never removed). Keep the last value of the `stakedLiquidityNet` word and the `feeGrowthOutside0X128` word per candidate tick. | Medium. Needs the Slipstream `Tick.Info` packing (stakedLiquidityNet is int128, signed and packed). Cleared ticks are zeroed via storage changes. |
| C8 | NPM `_positions[tokenId]` struct slots plus `_poolIdToPoolKey[poolId]` (token0, token1, tickSpacing). `reverted` means the position is absent at block end (poolId == 0 after a burn in the same block). | Medium. The V3 NPM storage reader (`uniswap-v3/source/src/storage/position_manager.rs:23-92`) is a template; the Slipstream layout differs (`int24 tickSpacing`). |
| C9/C10 | A PoolCreated store keyed `(t0,t1,ts)` with both orderings; post-block, so the current block's creations are included. | Easy and exact. C10's results are discarded, so only `Token.version = 2` matters (plus no-revert). |

---

## 7. Constants extracted from the WASM data segments (VERIFIED)

Addresses are AssemblyScript UTF-16 strings decoded with `asstrings.py`. The `@n` value is the memory address.

| Constant | Value | Where |
|---|---|---|
| `FACTORY_ADDRESS` | `0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a` | all 3 WASMs @1760; `factoryContract = Factory.bind(…)` in `start()` (`D:Pool.dcmp:9121-9152`) |
| `ADDRESS_ZERO` | `0x0000000000000000000000000000000000000000` | @1648 |
| `WETH_ADDRESS` | `0x4200000000000000000000000000000000000006` | Pool @2224 (`findEthPerToken`) |
| `USDC_WETH_POOL` (ETH price) | `0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59` | Pool @2336 (`getEthPriceInUSD`) |
| USDC (addMissing) | `0x833589fcd6edb6e08f4c7c32d4f71b54bda02913` | Pool @2448 |
| `WHITELIST_TOKENS` | `[0x4200…0006 (WETH), 0x833589fcd6edb6e08f4c7c32d4f71b54bda02913 (USDC), 0x940181a94a35a4569e4529a3cdfb74e38fd98631 (AERO)]` | static array @2704 in Factory **and** Pool (`asarrays.py`) |
| `STABLE_COINS` | **none** (no array, no branch) | n/a |
| `MINIMUM_ETH_LOCKED` | `"0.01"` | Pool @2752; `D:Pool.dcmp:9143` |
| `Q192` | `BigInt(2).pow(192).toBigDecimal()` (exact) | `D:Pool.dcmp:9145` |
| `ZERO_BD/ONE_BD` | `"0"`, `"1"` | |
| fee table (Factory) | ts 1→100, 50→500, 100→500, 200→3000, else→10000 | `D:Factory.dcmp:3312` + WAT |
| `feeTierToTickSpacing` (Pool) | 10000→200, 3000→60, 500→10, 100→1, else abort | `D:Pool.dcmp:8455-8485` |
| addMissing spacings | 100, 500, 3000, 10000 | `D:Pool.dcmp:6747-6767` |
| swap tick-loop cap | 100 iterations | `D:Pool.dcmp:8512` |
| `"1.0001"` tick base, `"1000000"` fee divisor, `"2"`, `"-1"`, `"10"` | | Pool @12592, @17424, @17344, @17312, @10496 |
| hot-fix pool (Factory, NPM) | `0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248` | Factory @3168, NPM @8928 |
| hot-fix pool (Swap) | `0x9663f2ca0454accad3e094448ea6f77443880454` | Pool @16896 |
| NPM block guard | `14317993` | `D:NonfungiblePositionManager.dcmp:3094, 3207` |
| `isNullEthValue` | `0x000…0001` (32 bytes) | Factory @8784 |
| static token definitions | empty list | `D:Factory.dcmp:1912-1935` |
| `Token.version` value written | `2` (Int) | `D:Pool.dcmp:7044-7066` |

For comparison, the deployed **Uniswap V3 Base** `Qmb4VUcA…` WASMs use (VERIFIED with the same extractor):

- `WHITELIST=[WETH, USDbC 0xd9aa…, DAI 0x50c5…, USDC 0x8335…]`
- `STABLE_COINS=[0xb97ef9ef…]` (an Avalanche USDC address, a copy artifact)
- ETH-price pool `0x4c36388b…`
- `MINIMUM_ETH_LOCKED="1"`
- single-argument `findEthPerToken`
- generated-schema module paths `generated_schema_*`, so it comes from a different source tree than Aerodrome's `src/types/schema/*`.

Upstream `c63cb39` used `MINIMUM_ETH_LOCKED=60`, a mainnet whitelist, and `Q192 = 2**192` as an f64 that is then stringified, which is inexact. Aerodrome's Q192 is exact.

---

## 8. Semantic deltas vs Uniswap V3

Comparison baselines: (U) upstream `Uniswap/v3-subgraph@c63cb39807`; (B) deployed Uniswap V3 Base `Qmb4VUcA…`; (R) the repository's V3 lane.

| Area | Aerodrome Slipstream (VERIFIED) | Uniswap V3 | Consequence for a backfill |
|---|---|---|---|
| PoolCreated ABI | `(t0,t1,int24 tickSpacing,pool)`, topic `0xab0d57f0…` | `(t0,t1,uint24 fee,int24 tickSpacing,pool)` | New decoder. The `substreams-evm` `dex/uniswap-v3` decoder does not fit (`aerodrome-slipstream-base/README.md:56-59`). |
| `Pool.feeTier` | tickSpacing table (1→100, 50/100→500, 200→3000, else→10000) | event `fee` | Ignores the dynamic fee module. Every `fees*` aggregate uses these synthetic tiers. |
| Tick-crossing spacing | `feeTierToTickSpacing(feeTier)` → canonical spacings 1/10/60/200 | real spacing | Walks the wrong grid. For ts=100 it visits multiples of 10, of which only multiples of 100 can exist; for ts=200, multiples of 60, so only multiples of 600 hit; for ts=2000, multiples of 200 (all hit). The ≤100-iteration cap is also computed with the wrong spacing. |
| `Tick.feeGrowthOutside0/1X128` | `ticks().value2/value3` = **stakedLiquidityNet / feeGrowthOutside0X128** | value2/value3 = feeGrowthOutside0/1 | Faithful output must store a signed int128 in `feeGrowthOutside0X128`. Same for TickDayData. |
| `getPool` signature | `getPool(address,address,int24)` | `uint24 fee` | NPM `getPosition` passes the position's tickSpacing, which is correct. |
| `positions()` slot 4 | `int24 tickSpacing` | `uint24 fee` | NPM storage adapter. |
| `Token.version` / `addMissingWhitelistedPools` | First swap per token sets `version=2` and makes 4 getPool calls whose results are discarded. | absent | Persisted effect is only `version`. The first-swap-per-token set is event-derivable, except for the hot-fix pool guard ordering (the guard returns before the version step). |
| ETH price | Pool `0xb2cc…` `token1Price` if `TVL0 > 0.01`, else 0 | U: `token0Price` of the mainnet pool, no TVL check. B: own pool and constants. | Different oracle rule. |
| `findEthPerToken` | 2-arg, no stable-coin branch, excludes pools pairing a whitelisted priced token with the swap counter-token | 1-arg, `STABLE_COINS → 1/ethPrice` | New pricing semantics. |
| `MINIMUM_ETH_LOCKED` | 0.01 | U: 60, B: 1 | |
| `Q192` | exact BigInt pow | U: f64 string (inexact); B: exact | U-based reducers would diverge on prices. |
| Position collected | `collectedToken*` added; `collectedFees* = collected − withdrawn` | U: `collectedFeesToken0 += amount0` and `collectedFeesToken1 += amount0` (U `position-manager.ts:161-162`). R: per-segment quirk (`docs/v3-mainnet-handoff-2026-09-04.md:174-179`). | Two extra fields, different math. |
| Flash | fee-growth only, no Flash row | **same in U** (`core.ts:492-501`); R's flash-reducer models the same | Not a Slipstream delta. Contrary to `aerodrome-slipstream-base/README.md:63-64`, it is canonical behaviour. |
| Pool-level Collect | not subscribed | U `c63cb39`: not subscribed either | `Collect` table empty. |
| TickHourData | never written | U: not written | empty. |
| Static token defs | empty | U: mainnet list | |
| fetchTokenDecimals | returns 0 on revert or out of range; the null check is dead code | U (newer): returns null and skips the pool | Pools with non-ERC20 tokens are created with decimals=0 rather than skipped. |
| Hot fixes | `0x8fe8…` (Factory/NPM), `0x9663…` (Swap), block 14317993 (NPM) | same in U | Inert on Base, Firehose-checked for the block guard. Keep them for fidelity. |
| Execution | 1 segment, no graft, spec 1.2.0, Fast PoI, declared calls | R: V3 mainnet has 6 segments and Base 2; spec ≤0.0.4, Legacy PoI (`uniswap-v3/README.md:18-30`) | No ancestry problem, but new PoI and spec features. |
| Factory→pool creation ordering | Initialize precedes PoolCreated in the tx; handled in wave 2 | Uniswap: factory `createPool` does not initialize, so Initialize comes in a later tx | The wave semantics matter in the first block of every Slipstream pool. |

---

## 9. Event volume estimate

**Live facts (VERIFIED, VictoriaMetrics 2026-10-20):**

- `deployment_head{deployment="QmasYjyp…"}` is 34,726,903 on `kan-subgraphs-a` / `graph-node-chain-base-0-77c65b59d4-kc8dv`, shard `subgraphshard_b`, worker_tier `steady`.
- It advanced 24,584 blocks in the last 6 h, about 98k/day gross.
- Head over the last 60 days at 5-day steps: 30,717,757 → 31,351,648 → 31,736,572 → 32,698,352 → 33,597,676 → 34,522,799 → 34,726,935.
- Handler invocations per processed block. These are 1-day windows divided by blocks per day, so the first point is partial.

| head ≈ | Swap | Transfer | Burn | Collect | Mint/Inc/Dec (each) |
|---|---:|---:|---:|---:|---:|
| 31.35M | 4.3 | 7.0 | 6.0 | 5.9 | ~2.0 |
| 31.74M | 5.4 | 9.4 | 7.9 | 7.8 | ~2.6 |
| 32.70M | 4.6 | 9.9 | 8.2 | 8.1 | ~2.75 |
| 33.60M | 6.5 | 9.6 | 8.3 | 8.2 | ~2.75 |
| 34.52M | 9.3 | 11.4 | 9.9 | 9.8 | ~3.3 |
| 34.70M (6 h exact) | 12.4 | 12.3 | 11.2 | 11.0 | ~3.66 |

- That works out to about **58 handler invocations and about 45 RPC eth_calls per block** at 34.7M. Flash runs at about 0.0003/block and PoolCreated/Initialize at about 0.0002/block.
- Handler wall time is about 0.82 s/s in total. Average cost: Swap ≈ 27 ms, Mint ≈ 21 ms, Burn ≈ 15 ms, including eth_call latency (from `rate(deployment_handler_execution_time_sum[6h])` divided by counts).

**Firehose spot samples (VERIFIED; 3 consecutive blocks each; exact NPM event counts):**

| height | NPM events/block | Notes |
|---|---|---|
| 14,317,993 | 0 | block-guard check |
| 15.0M | 0 | |
| 20.0M | 0, 0, 12 | |
| 25.0M | 36, 20, 12 | |
| 30.0M | 4 | |
| 45.0M | 21, 18, 23 | |
| 52.8M | 255, 51, 37 | the first is a burst |

From the metrics, NPM events are about 53% of all handler invocations (753,639 / 1,424,438).

**Estimate (CLAIMED, order of magnitude; my extrapolation):** NPM events per block of about 1 (13.8–17M), 4 (17–22M), 15 (22–32M), 25 (32–37M), 20 (37–47M) and 35 (47–52.9M). That gives about 0.7 B NPM events, so **about 1.3 B total handler invocations (plausible range 0.6–2.5 B)** over 13,843,704 → 52,867,396 (39.0M blocks). Using the observed ratio of 0.77 RPC calls per invocation, that is **about 1 B RPC-level eth_calls** (more logical calls).

Entity rows that follow from this:

- Swap rows: about 0.3–0.5 B.
- PositionSnapshot rows: up to the number of NPM events per (position, block), about 0.5 B.
- Mint+Burn rows: about 0.4 B.
- Transaction rows: distinct txs, about 0.3–0.6 B.
- Current-state entities are much smaller: Tokens about 10⁴, Pools about 10³–10⁴, Ticks about 10⁶, Positions about 10⁷.

**ETA for the live graph-node copy:** 18.14 M blocks remain to the Base head of 52,867,396.

- At the briefed about 140k blocks/day net: about **130 days**.
- At the last-6 h pace (98k/day gross, about 55k/day net once Base's about 43k/day growth is subtracted): about **330 days**.

This is diagnostic only and is not M0-admissible evidence (`docs/eligibility.md` policy).

---

## 10. Feasibility: approach A vs approach B

### 10.1 What exists today

| Capability | Exists for | Path | Reusable for Aerodrome? |
|---|---|---|---|
| Deployed-WASM executor (Graph Node v0.44 runtime, waves, PoI, per-save BlockChanges, BCF1, cassette, Firehose live source, checkpoints) | V3 (8 segments) | `mapping-host/` (README lines 11-23; `docs/v3-mapping-host-runtime.md`) | **Yes, family-neutral** (README:15-18). Needs: a bundle for `QmasYjyp…` (all 11 IPFS objects are already retained in `aerodrome-slipstream-base/reference/`; the manifest bytes must hash to the CID); a spec-1.2.0 manifest with declared calls (never exercised); Fast PoI (code path exists, never exercised in evidence); a Base cassette. |
| Engine framed-input mode, generic entity state, Fast/Legacy PoI with `GraphValue`, profile-driven COPY/Parquet, generic checkpoints | V3 handoff | engine PRs #74–#79 (`docs/v3-mainnet-handoff-2026-09-04.md` delivery table); engine `docs/block-changes-v1-input.md` | Yes, given BlockChanges frames from either approach. Open gap: `data_sources$` rows (issue #117) also apply to Aerodrome, since it creates one Pool per PoolCreated. |
| Native, family-specific reducer driven by Substreams Stores | V4 Base | engine `src/state.rs` (639 lines), `src/reducer.rs` (1,460), `src/store_fed.rs` (1,196); `substreams-v4-subgraph` | Architecture pattern only. The V4 entity semantics are different. |
| V3 Substreams that derives fee growth, ticks and NPM positions from **storage changes** | canonical V3 mainnet | `uniswap-v3/source/src/storage/{uniswap_v3_pool.rs,position_manager.rs,utils.rs}`; token metadata via `RpcBatch` (`src/rpc.rs`) | Slot-reading helpers (`calc_map_slot`, `calc_struct_slot`, `get_storage_change`) are reusable. Slot numbers and struct packing must be redone for Slipstream. |
| V3 host reducers for NPM Position/Snapshot/Transaction and Flash | V3 segments | `crates/uniswap-v3-reducers` (stages `uniswap-v3/{position-reducer,transaction-reducer,flash-reducer,npm-handler-reducer}`), graph-node v0.44 decimal precision model | Partially. The Aerodrome NPM profile (collectedToken, int24 getPool) is a new profile, but the handler-atomic discard, Token ordinal reads, block-scoped call caching and Transaction overwrite logic map closely. Flash is identical. |
| Pool Swap/Mint/Burn/Initialize/day-hour/pricing reducers | **none** in R (only static certificates under `uniswap-v3/pool-*`) | n/a | Must be written. |
| Event extractors | `substreams-evm/dex/uniswap-v3` (canonical V3 event map), `dex/aerodrome` (Solidly V2) | `…/ro/substreams-evm/dex/*` | The Swap/Mint/Burn/Flash/Initialize topics are identical to V3, so the Pool event decoders are reusable. Factory and NPM need new decoders. |
| Base extended Firehose | live | `base.firehose.pinax.network:443` | **Yes** (VERIFIED: block 30,000,000 has call traces and storage changes). |

### 10.2 Approach B: run the deployed WASM (mapping-host)

**Pros**

- Bit-faithful by construction. Every quirk in §5 (tick misbinding, wrong spacing walk, lost push, read-after-save, wave order, decimals rounding, nonFatal discard) is reproduced by the real mapping.
- Single segment, no graft, so none of V3's 8-segment ancestry work is needed.
- Semantic effort is small: bundle plus descriptor.

**Blockers and risks** (in order of severity)

1. **Serial throughput.** Measured mapping-host replay on V3 mainnet: 10.9 blocks/s with a cached cassette, 5.5 on first live blocks, and 1.9 about 7k blocks in at 1.83 handler groups per block (`docs/v3-mainnet-handoff-2026-09-04.md`, "Facts that must survive"). Aerodrome runs about 58 handler invocations per block over 39 M blocks, about 1.3 B handlers. Even at an optimistic 1 ms per handler that is about 15 days serial. At the observed V3 rates it is far worse than graph-node itself (about 12 ms per handler including RPC). An Aerodrome-density benchmark (for example 10k blocks at 34.7M with a warm cassette) is the go/no-go gate.
2. **Memory.** The host keeps every entity in an in-memory store, and checkpoints copy full state (`mapping-host/README.md:219-226`; `docs/v3-mapping-host-runtime.md:85-90`). Aerodrome would hold about 10⁹ write-only rows (Swap, Mint, Burn, PositionSnapshot, Transaction, history day/hour rows). This needs an eviction policy for write-only types. That policy is statically provable here: §4 shows these types are never `store.get` targets. It would need host work.
3. **eth_call cassette of about 1 B rows**, recorded serially today. The cheaper route is a parallel pre-recording pass. Calls are a deterministic function of (block hash, address, calldata), and the call set is predictable from the event stream plus small state (Tick existence from Mints; Position existence; first-swap-per-token). Alternatively, back `ethereum.call` with a storage-derived oracle (§6) instead of RPC.
4. Spec 1.2.0 declared `calls:` and the Fast PoI path are unexercised in the mapping-host.
5. The `data_sources$` gap (#117).

### 10.3 Approach A: Substreams extraction plus native Rust reducer (V4 style)

**Pros**

- Extraction is parallel and cacheable, and the reducer is native. For comparison, the V4 reducer ran at 2,268–2,596 blocks/s on low-density segments (engine `docs/benchmark-100k.md:59-61`), and direct-PostgreSQL end-to-end ran at 12.7–22 blocks/s on heavier ranges (engine `docs/direct-postgres.md:684-685`).
- No RPC except a few thousand ERC20 metadata calls.
- State can be bounded: write-only entities stream straight to COPY, and only Factory, Bundle, Token, Pool, Tick, Position and current-period day/hour rows are retained.

**Work required**

1. Substreams modules:
   - (a) Decode the Factory (Slipstream PoolCreated) and store the pool set.
   - (b) Decode Pool events for factory pools and NPM events, keeping Graph Node's per-block wave order.
   - (c) Storage-derived "call answers":
     - C5 feeGrowthGlobal per pool for each Swap/Flash.
     - C6/C7 tick words for the Mint/Burn ticks and the swap-walk ticks that exist.
     - C8 position struct, poolKey and the reverted flag.
     - C9 from the PoolCreated store.
   - (d) ERC20 metadata via `RpcBatch` (if the Pinax Base Substreams tier serves `eth_call`; UNVERIFIED) or a pre-recorded table.
   - (e) Event context: tx hash, from, gasLimit, gasPrice, logIndex, block number and timestamp, exactly as Graph Node converts Firehose to `ethereum.Event`.
2. A Rust reducer replicating §5 exactly, including:
   - Graph Node BigDecimal semantics (34-digit precision normalization per op; the repo already models "graph-node v0.44 decimal precision" in position-reducer).
   - BigInt `mod`/`div` sign rules and i32 overflow aborts.
   - Read-after-save (the store-visible state each helper sees).
   - Save order (for PoI event stream and VIDs).
   - `nonFatalErrors` discard; the iterative `1.0001^tick`; and all quirks.
3. Engine integration via BlockChanges v1 frames, plus the Fast PoI.

**Risk:** semantic drift. This is exactly why a differential oracle is mandatory: mapping-host on sampled contiguous windows, and the live graph-node copy at 34.7M via GraphQL or DB reads.

**How much of V3 is reusable for Aerodrome** (my judgement):

- About 60–70% of handler *logic* is canonical V3 (§8 lists the deltas). But the repo has no V3 Pool reducer to reuse; only static certificates and the NPM, Flash and Transaction host reducers exist.
- The engine's generic path (framed input, PoI, physical writers, checkpoints) is fully reusable.
- The V3 Substreams storage readers are about 30% reusable after re-slotting.

### 10.4 Recommendation for the design phase

1. Build the **mapping-host bundle for `QmasYjyp…`** first. It is cheap, and the artifacts are already retained. Use it as the semantic oracle and fixture generator, and run it over a short Base window around a pool's creation block plus a dense window near 34.7M. Record a cassette there. Measure blocks/s and memory at Aerodrome density. This also answers the declared-calls and Fast-PoI questions.
2. In parallel, pin the **Slipstream storage layouts**: `CLPool` (feeGrowthGlobal slots; `ticks` mapping slot; `Tick.Info` packing incl. `stakedLiquidityNet`) and `NonfungiblePositionManager` (`_positions`, `_poolIdToPoolKey`). Validate them by comparing storage-derived answers against cassette `eth_call` answers on the same windows.
3. Implement approach A (Substreams plus the "aerodrome-slipstream" family reducer) and check it frame-for-frame against the mapping-host's BlockChanges on those windows before any long run.
4. For "noop + backfill" workflows: the noop phase runs the Substreams extraction (with `--noop-mode` or a noop sink) over 13,843,704 → target, to warm tier-2 caches. This applies only to approach A. Approach B has no Substreams cache to warm, though its cassette pre-recording plays the analogous role.

---

## 11. Issues read (summary)

- **#86** `[M7] Reconfirm Aerodrome Slipstream Base eligibility and pin its exact target` (OPEN). Static baseline landed in PR #97 at canonical `5ec43dd5…`; only acceptance items 3, 4 and 6 are checked. Item 5 ("diff every entity, field, … mapping behavior against canonical Uniswap V3") is still open, and this report covers most of it. As of 2026-08-31, Kan `sgd2` was at 27,547,765 vs Base 50,704,626, a diagnostic ETA of about 149 days. M0 eligibility (≤28 days stops work) remains open.
- **#88** `[M7] Implement the Aerodrome Slipstream Graph backfill family` (OPEN, no comments). Acceptance requires exact entity, ID, order and failure parity, an ordered family contract for the M2 engine, fixtures for every handler class, and a pinned SPKG. It is blocked by #86, M2 (#4–#7) and the V3 truth gates (#38, #37, #12, #9).
- **#91** `[M7] Differentially certify and land … paused` (OPEN, no comments). Requires disposable-clone landing, physical parity (VIDs, block ranges, PoI) and lifecycle tests.
- **#83** (tracker). Aerodrome is the highest-value target: 962,722 q/24h and 1,154.657 GRT/24h as of 2026-08-31T17:20Z. M7 = #86/#88/#91.
- **#1** (master tracker). The strict eligibility rules and the executable-evidence tracker (#118).

These issues encode a strict fail-closed governance process (M0 ETA gates, truth gates). The user's current request (sync on an indexer, build a backfill Substreams, push k8s workflows) is the operator's own decision. The design phase should state explicitly which of those gates the user is choosing to bypass or refresh.

---

## 12. Open questions and verification TODOs for the design phase

1. Slipstream `CLPool` and NPM **storage layouts**: exact slots and packing. Required for approach A's no-RPC calls.
2. Which tick spacings were ever enabled (`TickSpacingEnabled` logs on factory `0x5e7b…`)? This determines which `feeTier` buckets and swap-walk grids actually occur. For example, spacing 10 or 2000 maps to the `else`→10000 bucket.
3. Does Pinax Base Substreams support `eth_call` (`RpcBatch`) for ERC20 metadata? If not, use a pre-recorded metadata table.
4. Does the mapping-host's graph-node v0.44 runtime path execute manifest `calls:` (declared calls) against its cassette adapter, or bypass them? Is Fast PoI parity correct?
5. Confirm Graph Node's Firehose→`ethereum.Transaction` mapping for Base type-2 and deposit (type 0x7e) transactions: `gasPrice`, `gasLimit`, `from`, `to`. These feed `Transaction.gasUsed`/`gasPrice` and `origin`.
6. Confirm the wave order in a pool-creation block (Initialize before PoolCreated in the same tx), using the mapping-host on a real creation block.
7. Confirm `0x8fe8…` and `0x9663…` are not Slipstream pools (PoolCreated set).
8. Get exact history volume from Firehose (topic counts over the full range) or from DB row counts on the live copy.

---

## Appendix A: reproduction commands

```sh
R=/Users/denis/Github/substreams-backfills/aerodrome-slipstream-base/reference/mappings
S=/private/tmp/claude-501/-Users-denis-Github-substreams-backfills/6974ca53-b59e-4778-97ac-3643f910b626/scratchpad
for f in Factory NonfungiblePositionManager Pool; do
  wasm-objdump -x -j Import -j Export $R/$f.wasm
  wasm-decompile $R/$f.wasm -o $S/aero-wasm/$f.dcmp
  wasm2wat $R/$f.wasm -o $S/aero-wasm/$f.wat
  python3 -I $S/tools/asstrings.py $R/$f.wasm   # UTF-16 strings with addresses
  python3 -I $S/tools/asarrays.py  $R/$f.wasm   # static string arrays (WHITELIST)
done
# Firehose sample (extended-block + event density check)
FIREHOSE_API_KEY="$SUBSTREAMS_API_KEY" firecore tools firehose-client base.firehose.pinax.network:443 30000000:30000000 \
  --api-key-env-var FIREHOSE_API_KEY -c "" -d ./fh -o jsonl > blk.jsonl
python3 -I $S/tools/count_events.py blk.jsonl
# Metrics (VictoriaMetrics uid P4169E866C3094E38)
#   sum by (handler)(increase(deployment_handler_execution_time_count{deployment="QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV"}[6h]))
#   sum by (contract_name,method)(increase(deployment_eth_call_execution_time_count{deployment="QmasYjyp…"}[6h]))
```
