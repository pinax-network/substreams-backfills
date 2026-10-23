# Survey: reusable Substreams building blocks for an engine-compatible Aerodrome Slipstream (Base) Substreams

Date: 2026-10-20. Scope: read-only survey. Target deployment `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` (Base, Factory start 13,843,704).

Path abbreviations used below:

| Alias | Path | Revision read |
|---|---|---|
| `EVM/` | `scratchpad/ro/substreams-evm` | origin/main `333e8c8` (2026-09-22) |
| `V4/` | `scratchpad/ro/v4-subgraph` (pinax-network/substreams-v4-subgraph) | origin/main snapshot |
| `ENG/` | `scratchpad/ro/engine` (pinax-network/substreams-graph-node-backfill) | origin/main snapshot |
| `BF/` | `/Users/denis/Github/substreams-backfills` | main `bbe3783` |
| `ABIS/` | `/Users/denis/Github/substreams-abis` | HEAD `9914005` = tree of origin/main `6d4dd57` (merge of #55), tags v1.5.0, v1.6.0, v2.0.0 read via `git show` |
| `SKL/` | `/Users/denis/Github/substreams-skills` | local `develop` is 95 commits behind; facts below are from `origin/develop` `568b1f2` (v1.7.0) via `git show` |
| `SS/` | `/Users/denis/Github/substreams` (streamingfast) | `be35ad3` (v1.22.0 merge) |
| `PLUG/` | `~/.claude/plugins/marketplaces/streamingfast-substreams/skills` | installed plugin skill v1.0.0 |

`(V)` = verified by reading code or by running a command. `(D)` = documentation claim, not verified in code.

---

## 0. Key findings (TL;DR)

1. **No existing crate decodes the Aerodrome Slipstream Factory or NonfungiblePositionManager (NPM).** Pool events
   (Initialize/Mint/Burn/Swap/Flash/Collect) share topic0 with canonical Uniswap V3 (V, `cast keccak`), so the
   `substreams-abis` Uniswap V3 pool bindings decode them. Slipstream `PoolCreated(address,address,int24,address)`
   (topic0 `0xab0d57f0…`) and `CollectFees` (`0x205860e6…`) have **no binding anywhere** in substreams-abis, substreams-evm or
   v4-subgraph. NPM events exist only in the frozen StreamingFast Uniswap V3 port in `BF/uniswap-v3/source/src/abi/positionmanager.rs`, which uses substreams 0.5 and substreams-ethereum 0.9.
   `substreams-abis::dex::aerodrome` and `EVM/dex/aerodrome` are **Solidly V2**, not CL.
2. **Call outputs differ from canonical V3, but selectors match.** `ticks(int24)` returns 10 fields on Slipstream versus 8 on V3.
   `positions(uint256)` slot 5 is `int24 tickSpacing`, where V3 has `uint24 fee`. `getPool` takes `int24`, selector
   `0x28af8d0b`; the V3 form takes `uint24`, selector `0x1698ee82`. Do not reuse the substreams-abis V3 `Ticks`/`Positions` decoders.
   **Generate bindings from the deployed ABIs** that are already frozen in `BF/aerodrome-slipstream-base/reference/abis/`,
   with a `build.rs` Abigen step (V4 pattern, `V4/build.rs:8-61`).
3. **What counts as "engine-compatible" has two shapes today** (V):
   - (A) a family-specific Substreams event/store package plus a hand-written native reducer in the engine (Uniswap V4 path).
   - (B) the family-neutral `pinax.graph.backfill.v1.BlockChanges` path. Here `BF/mapping-host` executes the **deployed mapping WASM** over
     Firehose blocks plus an `eth_call` cassette, and the engine consumes it with `--input-format block-changes-v1-framed`.
   For (B), the highest-leverage Substreams contribution is a **parallel, cacheable eth_call cassette producer**. The V3
   handoff names "recording the eth_call cassette ahead of time and in parallel" as the largest throughput lever
   (`BF/docs/v3-mainnet-handoff-2026-09-04.md:142-146`).
4. **Toolchain to pin for engine-facing packages:** Rust 1.90.0, `substreams =0.7.6`, `substreams-ethereum =0.11.1`,
   `prost =0.13.5`, `ethabi =17.2.0`, Substreams CLI **v1.20.3** (sha256 `90c71d04…`). This is the certified V4 stack and matches
   the engine's `prost =0.13.5`. The ecosystem has since moved to `substreams 0.8 / substreams-ethereum 0.12 / buffa`
   (substreams-abis v2.0.0, substreams-skills v1.7.0). Mixing the two stacks breaks builds.
5. **No Pinax token-metadata foundational store exists.** The only foundational store holds `tokens[]` and `factory` per pool.
   Token metadata in Pinax Substreams is fetched with in-module `eth_call` at the block hash (`V4/src/metadata.rs`). That is
   deterministic only to the extent that the RPC archive node is correct. Answers are cached forever, and tier1 may require
   `X-substreams-acknowledge-non-deterministic: true`.
6. **Recommended home:** a standalone, root-excluded cargo workspace inside `substreams-backfills`, at
   `aerodrome-slipstream-base/substreams/`. It follows the `uniswap-v4/`, `uniswap-v3/source` and `mapping-host` precedent, has its own
   toolchain and lockfile, uses `cargo xtask` for tooling (Rust-only policy) and its own tag namespace for the SPKG release.
   Optionally upstream generic Slipstream ABIs to `substreams-abis` later, and add a generic CL decoder to `substreams-evm`.
   See §6. Caveat: `substreams-backfills` is an **internal** repo, so pulling release assets needs a GitHub token. V4's package repo is public.

---

## 1. What "compatible with substreams-graph-node-backfill" means (context for every later section)

| Path | Producer | Consumer | Evidence |
|---|---|---|---|
| (A) Family reducer | Substreams `map_events` + Store packages + `map_store_state_inputs` (V4) | Engine `state-replay`, with a Uniswap-v4-specific reducer (`src/state.rs`, `src/reducer.rs`) | `ENG/README.md:16-33,128-145`; `ENG/adapters/uniswap-v4-base/compatibility.json` pins repo/release/asset/sha256/package/module/module_hash/output_type/initial_block (V) |
| (B) Generic BlockChanges | `BF/mapping-host` runs the deployed subgraph WASM with graph-node v0.44 runtime crates, Firehose blocks and an eth_call cassette, and seals one `BlockChanges` frame per block | Engine `state-replay --input-format block-changes-v1-framed`, which needs a descriptor and a physical profile for the COPY spool | `ENG/docs/block-changes-v1-input.md:1-60`; `BF/mapping-host/README.md:1-60` (V) |

Implications for a Slipstream Substreams:

- Path (A) needs an Aerodrome reducer in the engine. Without the exact source, that means re-implementing about 20 entities and 302 fields
  of AssemblyScript semantics. The source is still unresolved (`BF/aerodrome-slipstream-base/README.md` "No public commit was found…";
  `layout-profile-v1.json` `source_provenance`). The Substreams side would then mirror V4: events plus Stores plus compact reducer inputs.
- Path (B) needs no Substreams to run the mapping: mapping-host reads Firehose directly (`BF/mapping-host/src/source.rs`, token vars at line 80).
  Substreams is the right tool to **pre-compute every eth_call answer in parallel** and to cache them in tier2:
  - cassette key is `(block_hash, address, calldata)` → `Null | Value(hex)` (`BF/mapping-host/src/calls.rs:67-115`);
  - replay fails closed on a miss (`calls.rs:300-335`);
  - record mode serves cassette hits first and records only misses (`calls.rs:314-335`, V), so a Substreams-produced bulk cassette plus mapping-host
    `--record` for the remainder is a workable hybrid.
- For the V3 family, the measured call mix per triggered block was ERC20 `symbol/name/decimals/totalSupply`,
  `Factory.getPool`, `NPM.positions`, `Pool.ticks`, and `feeGrowthGlobal0/1` (`BF/mapping-host/README.md:281-285`, V).
  Slipstream needs the same set, with `getPool(address,address,int24)`.
- Unresolved cassette design item: the cassette is one JSON `BTreeMap` loaded in memory, and "cassette storage remain[s]
  separate follow-up work" (`BF/docs/data-sources-v2-chunks.md:18-23`). A ~39M-block Base range needs a chunked or streamed
  cassette format.

---

## 2. Q1: which crates and modules decode what Aerodrome Slipstream needs

### 2.1 Exact target surface (deployed manifest)

From `BF/aerodrome-slipstream-base/reference/deployment.yaml` (V):

| Data source | Address / start | Handlers (line) | Declared `calls:` |
|---|---|---|---|
| Factory | `0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a` @ 13,843,704 (`:35-36`) | `PoolCreated(indexed address,indexed address,indexed int24,address)` → `handlePoolCreated` (`:25-26`) | none. Handler-internal calls: ERC20 symbol/name/decimals/totalSupply plus bytes32 variants; `StaticTokenDefinition` (layout profile `retained_wasm_static_behavior.Factory`) |
| NonfungiblePositionManager | `0x827922686190790b37229fd06084350e74485b72` @ 13,843,719 (`:85-86`) | IncreaseLiquidity, DecreaseLiquidity, Collect(uint256,address,uint256,uint256), Transfer(ERC721) (`:57-76`) | `positions(event.params.tokenId)` on all four; handler-internal `Factory.getPool` (V3 cassette precedent) |
| Pool (template) | dynamic | Initialize, Swap, Mint, Burn, Flash (`:114-143`) | Swap/Flash: `feeGrowthGlobal0X128()`, `feeGrowthGlobal1X128()`. Mint/Burn: `ticks(tickLower)`, `ticks(tickUpper)` |

Not subscribed in this deployment: Pool `Collect`, `CollectFees`, `IncreaseObservationCardinalityNext`, `SetFeeProtocol`
(`layout-profile-v1.json:251`). Pool `Collect`/`CollectFees` decoders are therefore optional for parity. The Flash handler
writes only Pool fee-growth fields and creates no `Flash` row (`layout-profile-v1.json:326`).

### 2.2 Topic0 / selector table (V, computed with `~/.foundry/bin/cast`)

| Item | Slipstream | Canonical V3 | Same? |
|---|---|---|---|
| Factory PoolCreated | `PoolCreated(address,address,int24,address)` `0xab0d57f0df537bb25e80245ef7748fa62353808c54d6e528a9dd20887aed9ac2` | `PoolCreated(address,address,uint24,int24,address)` `0x783cca1c…7118` | **No** |
| Pool Swap / Mint / Burn / Initialize / Flash | `0xc42079f9…ca67` / `0x7a53080b…0bde` / `0x0c396cd9…982c` / `0x98636036…4c95` / `0xbdbdb71d…a633` | identical | Yes |
| Pool Collect | `0x70935338…a9c0` | identical | Yes |
| Pool CollectFees | `CollectFees(address,uint128,uint128)` `0x205860e6…b4a3` | V3 has `CollectProtocol` `0x596b5739…b151` | **No** |
| NPM IncreaseLiquidity / DecreaseLiquidity / Collect / Transfer | `0x3067048b…` / `0x26f6a048…` / `0x40d0efd1…` / `0xddf252ad…` | identical to Uniswap NPM | Yes |
| `ticks(int24)` | `0xf30dba93`, **10 outputs** (adds `stakedLiquidityNet`, `rewardGrowthOutsideX128`) | `0xf30dba93`, 8 outputs | selector yes, **decode no** |
| `positions(uint256)` | `0x99fbab88`, slot 5 `int24 tickSpacing` (`layout-profile-v1.json:249`) | `0x99fbab88`, slot 5 `uint24 fee` | selector yes, **decode no** (sign) |
| `getPool` | `getPool(address,address,int24)` `0x28af8d0b` | `getPool(address,address,uint24)` `0x1698ee82` | **No** |
| `feeGrowthGlobal0X128()` / `1X128()` | `0xf3058399` / `0x46141319` | identical | Yes |
| ERC20 `symbol/name/decimals/totalSupply` | `0x95d89b41` / `0x06fdde03` / `0x313ce567` / `0x18160ddd` | identical | Yes. bytes32 variants share the selector, so one cassette row serves both the string and the bytes32 decode |

Full ABI event lists (V, parsed from `reference/abis/*.json`):
- Pool: Burn, Collect, CollectFees, Flash, IncreaseObservationCardinalityNext, Initialize, Mint, SetFeeProtocol, Swap.
- Factory: DefaultUnstakedFeeChanged, OwnerChanged, PoolCreated, SwapFeeManagerChanged, SwapFeeModuleChanged, TickSpacingEnabled(int24,uint24), UnstakedFeeManagerChanged, UnstakedFeeModuleChanged.
- NPM: Approval, ApprovalForAll, BatchMetadataUpdate, Collect, DecreaseLiquidity, IncreaseLiquidity, MetadataUpdate, TokenDescriptorChanged, Transfer, TransferOwnership.

### 2.3 Inventory of existing decoders

| Crate / module (version) | Path | Covers | Usable for Slipstream? |
|---|---|---|---|
| `substreams-abis` v1.5.0 / v1.6.0 (substreams 0.7.6, substreams-ethereum 0.11.1, ethabi 17.2.0) and v2.0.0 (substreams 0.8.0, substreams-ethereum 0.12.0) | `ABIS/src/dex/uniswap/v3/{pool,factory,swaprouter}.rs`; ABIs in `ABIS/abi/dex/uniswap/v3/` | V3 Pool events (Burn, Collect, CollectProtocol, Flash, IncreaseObservationCardinalityNext, Initialize, Mint, SetFeeProtocol, Swap) and functions incl. `Ticks`, `Positions(bytes32)`, `FeeGrowthGlobal0/1X128`; Factory `PoolCreated` with `fee` + `tick_spacing` (`git show v1.6.0:src/dex/uniswap/v3/factory.rs` ~L1034-1040) | **Pool events: yes** (identical topic0; caller must address-filter). Factory PoolCreated: **no**. `Ticks` output: **no** (8-field decode, `pool.rs` ~L3330-3420 in v1.6.0) |
| `substreams-abis` `dex::aerodrome` / `dex::velodrome` | `ABIS/src/dex/aerodrome/{pool,poolfactory,router}.rs`; README lists Router `0xcF77…` and PoolFactory `0x420D…` (`ABIS/abi/dex/aerodrome/README.md`) | Solidly V2 pools (Sync/Fees/Claim, `GetReserves`, `GetPool1/2`) | **No** (V2, not CL) |
| `substreams-abis` NPM | none; `grep -rl 'NonfungiblePositionManager\|IncreaseLiquidity' ABIS/abi ABIS/src` returns nothing (V) | none | n/a |
| `substreams-abis` ERC20 | `ABIS/src/standard/erc20.rs` (Decimals L366, Name L707, Symbol L787, TotalSupply L867 in v1.6.0); bytes32 example `ABIS/src/tokens/erc20/mkr.rs` (`MKR.json` symbol/name = `bytes32`, V) | metadata calls | Yes for selectors and string decode. For bytes32 use the deployed `ERC20SymbolBytes.json` / `ERC20NameBytes.json` |
| `substreams-evm` `dex/uniswap-v3` crate `uniswap-v3` 0.6.0, spkg `uniswap_v3` v0.6.0 | `EVM/dex/uniswap-v3/src/lib.rs`; proto `EVM/proto/v1/dex/uniswap-v3.proto` | `map_events`: all V3 Pool + Factory events, **no address filter** (`lib.rs:35-181`); PoolCreated expects `fee` (`:151-161`) | Partially. It *will* emit Slipstream Pool logs (same topic0), labelled as V3, but never Slipstream `PoolCreated`, NPM, or calls. Groups by transaction. Uses `logs_with_calls()` when calls exist (`:27-31`), which can differ from block-global log order. `tick` errors become 0 (`unwrap_or_default`). Not deployment-pinned. **Not suitable as engine input**; fine as a reference |
| `substreams-evm` `dex/aerodrome` crate `aerodrome` 0.6.0 | `EVM/dex/aerodrome/src/lib.rs:28-109`, network `base` | Solidly V2 Swap/Sync/Mint/Burn/Fees/Claim/PoolCreated(`stable`) | **No** |
| `substreams-evm` `common` | `EVM/common/src/create.rs` | `CreateLog` / `CreateTransaction` helpers | Low value. `create_transaction` clones the whole `TransactionTrace` twice (`create.rs:97-98`) and records `cumulative_gas_used` as `gas_used` (`:107`) |
| `substreams-evm` `dex-swaps-pools-foundational-store` v0.6.0 | `EVM/dex-swaps-pools-foundational-store/substreams.yaml:1-56`; proto `EVM/proto/v1/dex/foundational-store.proto:7-21` | Pool to `{tokens[], factory}` from the generic V2/V3/V4/Solidly event maps | **No**: Slipstream pools never enter it, because the V3 PoolCreated decoder cannot match. No token metadata |
| StreamingFast Uniswap V3 port (`substreams-uniswap-v3` 0.1.0; substreams 0.5.13, substreams-ethereum 0.9.9, prost 0.11, Rust 1.79) | `BF/uniswap-v3/source/src/abi/{factory,pool,positionmanager,erc20}.rs` (generated from `source/abis/*.json` by `build.rs`); `src/lib.rs:43-101` (`map_pools_created` + RPC token metadata); `src/rpc.rs:8-98`; `src/storage/{uniswap_v3_pool,position_manager}.rs`; module graph `source/substreams.yaml:30-311` | Full V3 entity pipeline (`graph_out` EntityChanges), NPM events, storage-slot readers | Design reference only. **Frozen import** (do not edit, `BF/uniswap-v3/README.md` "Imported source"). Canonical-V3 hard-codes: pool parsed from `log.data()[44..64]` (`lib.rs:63`, wrong for Slipstream whose data holds only `pool`, i.e. bytes 12..32); storage slots 1/2/4/5 (`storage/uniswap_v3_pool.rs:20,41,62,87-90`), which do not match the Slipstream CLPool layout; known divergences from deployed mappings (`BF/mapping-host/README.md:1368-1388`) |
| V4 Base Substreams (Rust 1.90.0, substreams =0.7.6, substreams-ethereum =0.11.1, prost =0.13.5) | `V4/build.rs:8-61` (event-only Abigen from **deployed** ABIs); `V4/src/config.rs:25-127` (pinned-params validation); `V4/src/extract.rs:8-60,137-181` (address+start gating, Graph trigger order, block/tx/log refs); `V4/src/metadata.rs` (batched ERC20 metadata with mapping fallbacks) | Uniswap V4 singleton | **Pattern template, highest reuse.** Copy the structure, not the ABIs |

**Recommendation for Q1:** write a new crate whose `build.rs` runs `substreams_ethereum::Abigen` over
`aerodrome-slipstream-base/reference/abis/{Factory,Pool,NonfungiblePositionManager,ERC20,ERC20SymbolBytes,ERC20NameBytes}.json`,
filtered to the needed events and functions (V4 `write_event_only_abi` pattern, `V4/build.rs:41-61`, extended to keep the `function` entries:
`ticks`, `positions`, `getPool`, `feeGrowthGlobal0X128/1X128`, `symbol`, `name`, `decimals`, `totalSupply`). This keeps the
deployed, CID-locked ABIs as the single source of truth. It also avoids coupling to substreams-abis release lines (v1.x on 0.7, v2.x on 0.8).
Upstreaming `dex/aerodrome/slipstream/{CLFactory,CLPool,NonfungiblePositionManager}` to substreams-abis for token-api use is
optional and non-blocking.

---

## 3. Q2: toolchain, versions, build and release conventions

### 3.1 Version matrix (V, from Cargo.toml / Cargo.lock / rust-toolchain.toml)

| Repo | Rust | substreams | substreams-ethereum | prost | other |
|---|---|---|---|---|---|
| substreams-evm (workspace) | 1.88 (`EVM/rust-toolchain.toml:2`) | `0.7.0` req, lock 0.7.6 (`EVM/Cargo.toml:77`) | 0.11.1 (`:79`) | 0.13 (lock 0.13.5) | substreams-abis git tag v1.5.0 (`:78`); substreams-database-change 3.0.0 |
| substreams-v4-subgraph | 1.90.0 (`V4/rust-toolchain.toml:2`) | `=0.7.6` (`V4/Cargo.toml:17`) | `=0.11.1` (`:18`) | `=0.13.5` (`:13`) | ethabi `=17.2.0`, getrandom `=0.2.16` custom (`:27`), `substreams_ethereum::init!()` (`V4/src/lib.rs:13`); release profile `lto, codegen-units=1, strip` |
| engine (consumer) | 1.90.0 | n/a | n/a | `=0.13.5` (`ENG/Cargo.toml:40`) | Substreams CLI v1.20.3 in image (`ENG/Dockerfile:585`) |
| substreams-backfills root workspace | stable | 0.6 (`BF/Cargo.toml:18`) | 0.10 (`:19`) | 0.13 | substreams-entity-change 2; host-only overlay crates |
| `BF/uniswap-v3/source` (frozen) | 1.79 | 0.5.13 | 0.9.9 | 0.11 | substreams-entity-change 1.3.2 |
| `BF/mapping-host` (own workspace) | 1.98.0 | n/a | n/a | n/a | graph-node v0.44.0 crates |
| substreams-abis | 1.85 | v1.5.0/v1.6.0: 0.7.6; **v2.0.0: 0.8.0** | v1.x: 0.11.1; **v2.0.0: 0.12.0** | v2 uses buffa for the block model | `ABIS/RELEASE_NOTES.md` v2.0.0 "Breaking Changes" |
| StreamingFast substreams-skills v1.7.0 | n/a | documents **0.8.0** + buffa 0.9 | **0.12.0** | buffa | `SKL origin/develop:CHANGELOG.md` 1.7.0; `skills/substreams-ethereum/SKILL.md:152-180` |
| Substreams CLI | n/a | v1.20.3 is pinned with sha256 `90c71d04a75490efdf0493254a8563c3555690e622b3c6ade5100c0c773f8675` in `V4/.github/workflows/{parity,release}.yml:19-23`, `BF/.github/workflows/ci-uniswap-v4.yaml:64-77`, `BF/.github/workflows/ci.yaml:207-218` | | | local dev CLI is `dev be35ad3`; local `substreams-sink-noop` dev `eede626` (2024) |

**Recommended pins for the Aerodrome package:** exactly the V4 stack: Rust 1.90.0, substreams `=0.7.6`,
substreams-ethereum `=0.11.1`, prost/prost-types `=0.13.5`, ethabi `=17.2.0`, getrandom `=0.2.16` with `features=["custom"]`,
`init!()`, Substreams CLI v1.20.3 with checksum. Reasons:
- the stack is certified against the engine;
- protobuf codegen with `buf.gen.yaml` neoeinstein-prost v0.4.0 + prost-crate v0.4.1 (`V4/buf.gen.yaml`) yields prost 0.13 types the engine decodes;
- substreams-abis 2.x and the substreams-skills 1.7.0 guidance (no `ethabi`, no `getrandom`, buffa) are for the 0.8 stack and **must not be mixed in**.
A later move to 0.8/buffa keeps the same wire format, but it is a separate, explicit decision.

### 3.2 Build, pack and release conventions observed

**substreams-evm (generic packages):**
- `Makefile` targets `build` = `cargo build --target wasm32-unknown-unknown --release`, `pack` = `substreams pack -o ../../spkg/{spkgDefaultName}`, `noop` = `substreams-sink-noop $(ENDPOINT) substreams.yaml map_events -H "X-Substreams-Parallel-Workers: $(PARALLEL_JOBS)" 0:` (`EVM/dex/uniswap-v3/Makefile:1-24`).
- Release convention (`EVM/.github/skills/release-conventions/SKILL.md:17-102`):
  - tag `<chain>-<type>-v<version>`, release name `<chain>-<type> v<version>`;
  - SPKG names `<chain>-<type>-vX.spkg`, `<chain>-clickhouse-<type>-vX.spkg` and `<chain>-postgres-<type>-vX.spkg`;
  - package names use underscores;
  - SPKGs go both into `./spkg/` and onto the GitHub release.
- Releases are manual; CI only runs `cargo test` and `cargo check` for wasm32 (`EVM/.github/workflows/ci.yml`).
- Recent tags include `evm-dex-v0.8.0` (2026-06-01) (`gh release list`, V).

**substreams-v4-subgraph (engine-facing, the precedent to follow):**
- Versioned packages: `uniswap-v4-base-backfill-v0.1.0.spkg`, `uniswap-v4-base-state-stores-v0.1.0.spkg`,
  `uniswap-v4-base-store-fed-reducer-v0.1.0.spkg` and `uniswap-v4-base-store-state-reducer-v0.5.0.spkg`. Package names are `uniswap_v4_base_backfill`, and so on.
  Repo tags are plain `vX.Y.Z` (v0.1.0, v0.4.0, v0.4.1, v0.5.0).
- `release.yml` (`V4/.github/workflows/release.yml:1-57`) runs on tag `v*`. It uses a **per-tag case policy**, fails on any unknown tag,
  and publishes with `gh release create --verify-tag`. There is no `--clobber`, and assets are immutable (`V4/docs/store-packages.md` "Release and consumer rules").
- The consumer pins repository, release, asset filename, sha256, package version, module name, module hash, output type and initial block.
  The pins live in `ENG/adapters/uniswap-v4-base/compatibility.json`; the engine's `make verify-spkg` rejects drift (`ENG/README.md:147-162`).
- Host-built SPKGs are **not** treated as production-identical, because Rust WASM embeds build paths. Certified bytes are retained under
  `release/vX/` (`V4/AGENTS.md:54-59`).
- **Cache boundary:**
  - each Store writer gets its own WASM binary through named `binaries:` and `binary:` per module (`V4/substreams-store-state.yaml:24-60`);
  - imported modules are reused with `use:` so module hashes survive;
  - `scripts/test-*-cache-boundary.sh` enforce this (`V4/Makefile:107-116`).
- **2 GiB per-Store server ceiling:** the Tick store hit it on Base at block 39,596,133, and the fix was 16 then 64 deterministic shards keyed on the first byte of the pool id
  (`V4/docs/store-packages.md` "Tick Store sharding"; `V4/README.md:153-158`).
- **Pinned params:**
  - `params: map_events: "network=base;deployment=…;…_start=…"` (`V4/substreams.yaml:32-33`);
  - module code rejects any key or value drift (`V4/src/config.rs:25-127`);
  - `initialBlock` is set on every module.

**substreams-backfills CI conventions:**
- One workflow per family, with a `dorny/paths-filter` gate.
- The V4 import job builds in its own workspace with `dtolnay/rust-toolchain@1.90.0` and caches several workspaces (`BF/.github/workflows/ci-uniswap-v4.yaml:10-57`).
- `cargo xtask` is the tool entry point (`BF/.cargo/config.toml` alias).
- Evidence assets are hydrated by `cargo xtask evidence fetch` from content-addressed GitHub releases (`block-fixtures-v2`, `evidence-assets-v1`).

---

## 4. Q3: token metadata without RPC; eth_call in Substreams and determinism

### 4.1 What exists

| Mechanism | Where | Notes |
|---|---|---|
| **Foundational store for token metadata** | none (V). `EVM/dex-swaps-pools-foundational-store` stores only `Pool { repeated bytes tokens; bytes factory; }` (`EVM/proto/v1/dex/foundational-store.proto:7-10`). `~/Github/substreams-foundational-store` is the generic Go service, `develop` 2025-12 | Not an option for symbol/name/decimals |
| **In-module eth_call (raw `RpcCalls`)** | `V4/src/metadata.rs:16-72` | Four raw selectors per token, one batched `rpc::eth_call` per block for the unique tokens, response count checked (`:50-56`). Fallbacks match the deployed V4 mapping: string, then bytes32 truncated at first NUL, `NULL_ETH_VALUE` (`0x…01`) → unknown, decimals only if `< 255`, zero address → ETH/Ethereum/18 (`:74-134`). Unit tests at `:151-178` |
| **In-module eth_call (`RpcBatch`)** | `substreams-ethereum-core-0.11.1/src/rpc.rs:10-80` (V): `RpcBatch::add(F: Function, address)`, `execute()`, `decode::<R,T>()` returns `None` on `failed` or on decode error, and logs. `eth_call` panics if response decode fails (`:75-80`) | Used in `EVM/erc20/supply/src/calls.rs:9-32` (totalSupply) and `EVM/erc20/balances/src/calls.rs`; `eth_get_balance` with an explicit block in `EVM/native/balances/src/calls.rs:11-35` |
| **StreamingFast port metadata** | `BF/uniswap-v3/source/src/rpc.rs:8-98` | RpcBatch decimals/name/symbol, then a static-token fallback. That fallback looks up `token_address.encode_to_vec()`, the protobuf encoding of the hex String (`rpc.rs:31`), which almost certainly never matches. Drops the pool when decimals ≥ 255 or fail. Has known divergences; reference only |
| **Storage-change derivation (no RPC)** | `BF/uniswap-v3/source/src/storage/*.rs` | Reads `call.storage_changes`. **Base Firehose blocks are extended** (V: `firecore tools firehose-client base.firehose.pinax.network:443 13843704:13843705` returned 48 txs, 490 calls and 368 storage changes; probe in `scratchpad/survey/probe/b.json`). Not usable for token metadata, which is written at deployment, not per block. Tick and fee-growth values from storage changes are **intra-transaction** values, while graph-node `eth_call` returns **end-of-block** state, so a parity reducer cannot substitute one for the other. Slot indices are canonical-V3 specific |
| StreamingFast skill guidance | `SKL origin/develop:skills/substreams-ethereum/references/rpc-and-tokens.md:51-189` | Map, then `set_if_not_exists` store cache, then consume. Its failure table says "call reverts → skip; a later block will populate the store" (`:186`) and "default decimals 18" (`:185`). **Both break Graph Node parity**: graph-node writes `unknown` / `null` at that block and never retries. Do not follow these defaults for backfills |

### 4.2 Determinism caveats (for any eth_call inside Substreams)

1. **Block state.** The Substreams docs claim eth_call executes "at the **specific block hash** being processed"
   (`SS/docs/how-to-guides/develop-your-own-substreams/evm/eth-calls.md:16`, D). Graph Node also calls at the block pointer,
   and mapping-host records with EIP-1898 block hash (`BF/mapping-host/README.md:268-272`, V). Both give **end-of-block** state, which is
   the right semantics to reproduce declared calls. It is *not* the state at the log's position.
2. **Revert classification.** `RpcResponse { raw, failed }`. Map `failed=true` to graph-node `Null`. Also map empty `raw`
   ("returned `0x`") to `Null`, and a decode failure to a revert. This follows `calls.rs:1-40` and `:76-84`, which treat all three as a revert (V).
   `RpcBatch::decode` silently folds both into `None`. For cassette fidelity, emit raw bytes plus a `failed` flag, not the decoded value.
3. **Tier1 acknowledgement.** Modules importing `rpc.eth_call` can be rejected unless the request carries
   `X-substreams-acknowledge-non-deterministic: true`. This applies when the server enables the check (`SS/docs/release-notes/change-log.md:671`;
   detection is the WASM import scan in `SS/service/validate.go:112-128`, V). Workflows should always send the header.
4. **Answers are cached permanently** in tier2 module outputs. A wrong answer from a lagging, pruned or buggy archive node becomes part of
   the cache and of every replay. Pin the RPC backend and spot-check a sample against an independent archive.
   Pinax Base tier1 uses `--substreams-rpc-endpoints=http://${NETWORK}.rpcx.${CLUSTER_ZONE}-prod-rpc-a.pinax.io/v1/…`
   (`~/Github/k8s-substreams/chains/base/v2/prod/substreams-tier1/kustomization.yaml:30-37`, V).
5. **Timeouts and retries.** A per-block execution timeout of 3 min is the default. An eth_call against an unreachable endpoint retries for minutes.
   Segments with thousands of eth_calls per block used to be killed at 60 min (fixed by the stall timeout)
   (`SS/docs/release-notes/change-log.md:376,392,1346`, D). Batch per block and dedupe within the block.
6. **Gas cap.** Graph Node and mapping-host use 50,000,000 gas (`calls.rs:71`, V). The Substreams eth_call gas cap is not verified (open).
7. **Mapping-specific fallbacks must be copied exactly, not "sensibly".** Examples:
   - `StaticTokenDefinition.fromAddress` (present in the Slipstream WASM, `layout-profile-v1.json` `retained_wasm_static_behavior.Factory`);
   - string → bytes32 → `unknown`;
   - the `isNullEthValue` check;
   - the `decimals` bail-out, which in V3-family mappings skips `PoolTemplate.create`, so that pool's events never trigger. This behaviour is
     from Uniswap V3 subgraph prior art; for this deployment it is **not verified** without source.
   NUL bytes in bytes32 symbols need an explicit Postgres policy. V4 needed a NUL-audit package and a `postgres-nul-truncate-v1` exception (`V4/README.md:66-78`).
8. **Path (B) reduces this risk.** Substreams only records raw `(block_hash, address, calldata) → Null|Value` rows, and the deployed WASM
   performs its own decoding and fallbacks in mapping-host. Path (A) must re-implement the fallbacks.

---

## 5. Concrete building blocks for the Aerodrome package (design input)

Suggested module graph (names indicative):

```text
sf.ethereum.type.v2.Block
  └─ map_pools_created(params)              Factory 0x5e7b… only, block >= 13,843,704; decode Slipstream PoolCreated
       │                                    (+ RpcBatch ERC20 symbol/name/decimals/totalSupply raw responses for token0/1)
       └─ store_pools  (set_if_not_exists)   key pool addr → {token0, token1, tickSpacing, created_block, created_block_index}
sf.ethereum.type.v2.Block + store_pools(get)
  └─ map_events(params)                     NPM 0x8279… (>= 13,843,719) + Pool template (store-gated) events,
                                            ordered as Graph Node orders triggers; BlockRef/TxRef/LogRef as V4 extract.rs
  └─ map_call_answers / map_eth_call_cassette
                                            per event: declared calls + known handler-internal calls via eth_call at block hash
```

Specific rules to carry over:

- **Address and start gating.** Use the V4 pattern of `block.number >= START && log.address == ADDR` (`V4/src/extract.rs:16-36`).
  Gate Pool-template events by `store_pools` membership. A store read in `get` mode sees writes from the same block, which matches Graph Node
  creating the data source in that block (`D`, standard Substreams store semantics).
- **Graph Node trigger order.** Sort by block-global `log.block_index` (`V4/src/extract.rs:40-57`). For dynamic sources, Graph Node uses a **wave model**.
  Triggers of pools created in block N run *after* all stage-0 triggers of block N, by a re-scan of the same block. That includes a Pool log whose
  index is lower than the creating `PoolCreated`, because the gate is the creation *block*, not the ordinal
  (`BF/mapping-host/src/runner.rs:11-23`, V, citing graph-node `data_source.rs:700`). So emit `(wave, block_index)` and do not rely on `block_index` alone.
- **Successful transactions only.** `Block::transactions()` filters `status == 1`
  (`substreams-ethereum-core-0.11.1/src/block_view.rs:8-10`, V). Use receipt logs, not `logs_with_calls()`, when order matters.
- **Calls per event.** These have constant calldata or calldata derivable from the event:
  - Swap/Flash → `feeGrowthGlobal0X128()` and `feeGrowthGlobal1X128()` on `log.address`;
  - Mint/Burn → `ticks(tickLower)` and `ticks(tickUpper)`;
  - NPM events → `positions(tokenId)` on the NPM; then **chained** `Factory.getPool(token0, token1, tickSpacing)` computed from the positions result, in a second batch in the same block;
  - PoolCreated → ERC20 metadata for both tokens (superset is fine; unused cassette rows are harmless).
  **Not derivable from events:** whatever `addMissingWhitelistedPools` / `Factory#getPool` in the Pool template calls with state-derived arguments
  (`layout-profile-v1.json` `retained_wasm_static_behavior.Pool`). Cover that by mapping-host `--record` on miss, or by WASM analysis.
- **Cassette row encoding.** A cassette row must exactly match `CassetteEntry` (`calls.rs:99-115`; example `BF/mapping-host/README.md:247-261`):
  - `block_number`;
  - `block_hash` as lowercase `0x` hex;
  - `address` as lowercase `0x` hex;
  - `calldata` as lowercase `0x` hex;
  - `contract` as the manifest ABI name (`ERC20`, `Pool`, `Factory`, `NonfungiblePositionManager`);
  - `function` as the signature;
  - `retval` as `{"kind":"null"}` or `{"kind":"value","data":"0x…"}`, schema `pinax.substreams-backfills.mapping-host.cassette/v1`.
  The Substreams map should emit a compact protobuf. A Rust converter (an xtask or mapping-host subcommand) can then build chunked cassette files.
- **Store sizing.** Pools and tokens on Base are small. Avoid per-tokenId position stores unless sharded; positions answers are per block anyway.
  Remember the 2 GiB per-store ceiling and per-store binaries if path (A) grows Tick or liquidity stores.
- **noop warm-up.** Run the final map with `substreams-sink-noop` (or `substreams run --production-mode` with
  `-H X-Substreams-Parallel-Workers`) over `[13,843,704, head)`. This executes every eth_call exactly once and caches it in tier2. The backfill
  stage then streams cached outputs. The token-api noop template is `scratchpad/ro/k8s-token-api-workflows/workflows/templates/token-noop.yaml`.

---

## 6. Q4: where the Aerodrome engine-compatible Substreams source should live

| Option | Fit | Problems |
|---|---|---|
| **A. `substreams-backfills/aerodrome-slipstream-base/substreams/` as a standalone workspace, excluded from the root (recommended)** | The repo's stated purpose is "Per-subgraph Substreams modules that materialize graph-node deployments" (`BF/README.md:3-4`). The frozen target (manifest, ABIs, WASMs, provenance lock, layout profile, `cargo xtask verify-target aerodrome-slipstream-base` at `xtask/src/main.rs:644`) already lives next door, so `build.rs` can Abigen straight from `../reference/abis/` with no copy. mapping-host (path B), the evidence tooling and the family CI precedents are here. It is Rust, so it satisfies the Rust-only policy (memory `rust-only-policy.md`: no `.py/.go/.sh`; tooling via `cargo xtask`) | The root workspace pins substreams 0.6 / substreams-ethereum 0.10 (`BF/Cargo.toml:18-19`), so the crate **must** be added to `exclude` (like `mapping-host`, `uniswap-v3/source`, `uniswap-v4`, `BF/Cargo.toml:10`) with its own `rust-toolchain.toml` (1.90.0) and `Cargo.lock`. V4-style `scripts/*.sh` / `*.mjs` cannot be copied in; port them to xtask. The repo is **internal** (`gh api`, V), so SPKG downloads by k8s workflows or engine image builds need a token, or the SPKG must be vendored into the OCI image (the engine already embeds verified SPKGs, `ENG/README.md:183-191`). Release tags need a namespace (for example `aerodrome-slipstream-base-substreams-v0.1.0`) so they do not collide with `block-fixtures-v*` / `evidence-assets-v*` |
| B. New public repo `pinax-network/substreams-aerodrome-slipstream-subgraph` (mirror of substreams-v4-subgraph) | Same ownership split V4 uses: Substreams repo publishes immutable public SPKGs, engine is the internal consumer, k8s-subgraphs pins (`V4/AGENTS.md:7-17`). Public assets can be fetched without auth | Duplicates repo scaffolding. The frozen reference artifacts would need a copy or a second provenance lock. Splits Aerodrome work across repos. V4's repo carries non-Rust scripts, which is fine there but should not be cloned as policy |
| C. `substreams-evm` (`dex/aerodrome-slipstream`) | Good home for a **generic** CL event decoder for token-api and ClickHouse | Generic, not deployment-pinned. Workspace is Rust 1.88 / substreams 0.7.0. Release naming is ClickHouse/Postgres-sink oriented. AGENTS says ABIs belong in substreams-abis and pool-state lives in substreams-evm-extended (`EVM/AGENTS.md`; `EVM/dex/uniswap-v3/README.md:5-11`). Engine packages need frozen module hashes and their own release policy |
| D. Inside `substreams-v4-subgraph` | Same toolchain | Single-deployment repo with an immutable release and cache contract (`V4/AGENTS.md:19-43`). Mixing families would muddy release locks |

**Recommendation:** option A. Layout sketch:

```text
aerodrome-slipstream-base/substreams/
  Cargo.toml / Cargo.lock / rust-toolchain.toml (1.90.0)
  build.rs                      # Abigen from ../reference/abis/*.json (events + needed functions)
  buf.gen.yaml + proto/         # prost 0.13 bindings, checked in, drift-checked by xtask
  src/{config,extract,calls,metadata,lib}.rs
  substreams.yaml               # params pinned: network=base;deployment=QmasYjyp…;factory=0x5e7b…;factory_start=13843704;npm=0x8279…;npm_start=13843719
```

Wiring:
- new workflow `ci-aerodrome-slipstream-base.yaml` modelled on `ci-uniswap-v4.yaml`: checksum-pinned CLI v1.20.3, fmt, clippy `-D warnings`, host tests, wasm32 build, `substreams pack`, `substreams info … --json`;
- release through a tag-namespaced `gh release create --verify-tag` with no clobber;
- consumer pins repository, release, asset, sha256, module hash and output type.
Optional later work: upstream generic Slipstream ABIs to substreams-abis (v1.x line for the 0.7 stack, v2.x for 0.8), and a generic CL map to substreams-evm.

---

## 7. Generic recipe: making any subgraph backfillable via Substreams (input for the skills update)

1. Freeze the deployed target: manifest, schema, ABIs and WASMs by CID with a sha256 lock (as `BF/<family>/reference` + `xtask verify-target`).
2. Generate Rust bindings **from the deployed ABIs**, not from a generic ABI library, because forks change event arity and call outputs.
3. Pin every data source address and start block as validated `params`, and set `initialBlock` on every module.
4. Reproduce Graph Node's trigger set and order:
   - successful-tx receipt logs;
   - block-global log index;
   - templates gated by creation **block**;
   - the same-block wave re-scan for new data sources.
5. Enumerate every `eth_call` the mapping makes: manifest `calls:` plus handler-internal `try_*` and bound-contract calls, from WASM imports and names.
   Execute them at the block hash in batched RpcBatch calls. Emit raw `Null|Value` answers and keep Graph's revert semantics. Send the
   non-deterministic acknowledgement header.
6. Pick the consumption path: (A) a family reducer in the engine with V4-style event, store and reducer-input packages, or (B) mapping-host executing
   the deployed WASM to BlockChanges, with Substreams pre-recording the cassette.
7. Toolchain: the V4 stack, with the 0.7 and 0.8 crates never mixed. Keep separate binaries per Store for cache stability, and shard any Store
   that can approach 2 GiB.
8. Release immutable SPKGs and pin repo, release, asset, sha256, module hash, output type and initial block in the consumer contract. Run noop first to
   warm tier2, then backfill from cache.

---

## 8. Open questions and risks

- Exact Slipstream mapping semantics are unknown because there is no source: token-metadata fallbacks, `StaticTokenDefinition` contents, `Token.version`,
  the arguments `addMissingWhitelistedPools` passes to `getPool`, and whether there is a decimals bail-out. This limits path (A) and limits how complete a
  pre-recorded cassette can be in path (B).
- The cassette format does not scale to the full range (an in-memory JSON BTreeMap). It needs chunked or disk-backed storage first.
- Substreams eth_call gas cap compared with graph-node's 50M is not verified.
- Whether Pinax Base tier1 enforces `X-substreams-acknowledge-non-deterministic` is not verified from the cluster config. Send it regardless.
- `substreams-backfills` is internal, which affects asset fetching in k8s workflows.
- Local `~/Github/substreams-skills` is 95 commits behind origin, and the installed plugin skill (v1.0.0) still teaches prost-era and
  `streamingfast/substreams-abis` `evm::…` paths that do not match the pinax crate (`PLUG/substreams-dev/SKILL.md:404-457`). Skill updates should say which stack applies.
