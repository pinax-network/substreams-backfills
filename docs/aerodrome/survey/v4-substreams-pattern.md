# How the Uniswap V4 Substreams was made engine-compatible, and a generic recipe

Survey date: 2026-10-20. Scope: the read-only snapshots of
`pinax-network/substreams-v4-subgraph` (below `V4/`) and
`pinax-network/substreams-graph-node-backfill` (below `ENGINE/`), plus the
Graph Node v0.44 source they target, the `substreams-backfills` main checkout
(below `SB/`) and the Aerodrome target closure that is already pinned there.

Path prefixes:

- `V4/` = `.../scratchpad/ro/v4-subgraph` (head `6ebfaea`, "expand Base Tick Store to 64 shards (#24)")
- `ENGINE/` = `.../scratchpad/ro/engine`. Its `.git` file points at a pruned worktree, so the commit cannot be printed. The files are the origin/main snapshot the orchestrator supplied.
- `SB/` = `/Users/denis/Github/substreams-backfills` (main, head `bbe3783`)
- `GN:` = Graph Node commit `77823b5a7adc4eac4abf03202c8dd7cb00dea31d` (v0.44.0), read with `git show` from the local cargo bare repo `~/.cargo/git/db/graph-node-40979021f9daae1a`. Nothing was checked out.
- `SEC:` = `~/.cargo/registry/src/index.crates.io-*/substreams-ethereum-core-0.11.1`

Evidence labels: **VERIFIED** means I read the code or data, or a read-only
`gh api` call confirmed it. **CLAIM** means a document says it and I did not
re-derive it.

---

## 0. Executive summary

1. **The V4 "engine-compatible Substreams" is not a generic Graph Node
   emulator. It has two halves:**
   - A thin, deterministic **trigger extractor**, `map_events`. It decodes only the deployed data-source addresses and handled events, attaches block, transaction and log identity plus a Graph-Node trigger-order key, and enriches with historical `eth_call` results. The relevant code is `V4/src/lib.rs:15-21`, `V4/src/extract.rs:8-60` and `V4/src/metadata.rs:21-72`.
   - **Optional, cache-isolated Store packages** that precompute only *algebraically mergeable* primitive state and event-local math. They are fed to a compact assembler map, `map_store_state_inputs`. The relevant files are `V4/substreams-store-state.yaml` and `V4/store-probe/src/lib.rs:223-360`.

   The **entity semantics are a hand-written native Rust port of the deployed mapping inside the engine**: `ENGINE/src/reducer.rs` (1,460 lines), `src/entities.rs`, `src/decimal.rs` and `src/math.rs`, plus `src/sink.rs` with the static 20-table catalog. Save order, Decimal128, `derivedETH`, the POI and VIDs stay there. This split is explicit in `ENGINE/docs/state-reducer.md:3-39` and `ENGINE/docs/substreams-stores.md:9-18`.
2. **Ordering contract (VERIFIED).** V4 sets `graph_node_trigger_order = log.block_index` (`V4/src/extract.rs:176`) and sorts the events by `(trigger_order, tx_index, tx_log_index)` (`extract.rs:43-57`). This equals Graph Node's log ordering: `GN:chain/ethereum/src/codec.rs:124` sets `log_index = block_index`, and `GN:chain/ethereum/src/trigger.rs:364-404` orders logs by that index. **This is only sufficient because V4 has no templates, call handlers or block handlers.** For any template-based subgraph, Graph Node processes triggers of data sources created in the same block in later *waves* (`GN:core/src/subgraph/runner/mod.rs:914-990`). The order key must then become `(wave, block_log_index, host_order)`.
3. **The Aerodrome template trap (VERIFIED against public Slipstream `main` @ `193a6b85`; the deployed bytecode was not compared).** `CLFactory.createPool` calls `CLPool.initialize`, which emits `Initialize`, *before* it emits `PoolCreated`. Graph Node therefore runs `handlePoolCreated` in wave 1 and `handleInitialize` in wave 2, even though Initialize has the lower log index. A V4-style "sort by log index and filter by the known-pool Store at that ordinal" would either drop or misorder every pool's Initialize.
4. **`eth_call`.** V4 calls `substreams_ethereum::rpc::eth_call` inside `map_events` and batches by block (`V4/src/metadata.rs:35-49`).
   - **VERIFIED:** Graph Node pins calls to the block hash (`GN:chain/ethereum/src/runtime/runtime_adapter.rs:335`, `ethereum_adapter.rs:600`).
   - **CLAIM, from the server-side env docs:** Substreams also uses the block hash unless `ETH_CALL_USE_BLOCK_NUMBER_DURATION` or `ETH_CALL_FALLBACK_TO_LATEST_DURATION` is set (`~/Github/substreams/ENVIRONMENT_VARIABLES.md:74-88`).
   - V4 embeds the mapping's fallback logic (string, then bytes32, then "unknown", and decimals `<255`) into the Substreams output. That is mapping semantics leaking into the extractor. A generic design should prefer raw `(block_hash, to, calldata) -> retval|revert` tuples, i.e. the mapping-host "cassette" (`SB/mapping-host/README.md:228-288`).
5. **Dynamic data sources.** V4 has **none**. Uniswap V4 is a singleton PoolManager, and pool existence is reducer-owned state (`ENGINE/docs/substreams-stores.md:207-212`). V4 offers *no precedent* for template tracking. The engine's generic `data_sources$` support is a separate BlockChanges sidecar or chunk contract (`ENGINE/docs/data-sources-sidecar-v1.md`, `ENGINE/docs/data-sources-chunks-v2.md`), and it is not production-ready.
6. **Release and pinning (VERIFIED).**
   - **Build pins:** Rust 1.90.0, `substreams` 0.7.6, `substreams-ethereum` 0.11.1, and the Substreams CLI v1.20.3 by tarball sha256.
   - **Distribution:** SPKGs are **GitHub release assets** on `pinax-network/substreams-v4-subgraph`. CI publishes *committed, previously certified bytes* (`V4/release/v0.4.0/*.spkg`) rather than rebuilding them, because Rust WASM can embed build paths (`V4/AGENTS.md:56-59`). No ORAS or GHCR is used for SPKGs.
   - **Pinning in the engine:** `adapters/uniswap-v4-base/compatibility.json` pins the repo, release, asset, sha256, package name and version, module hash, output type and initial block. Every SPKG is downloaded with `gh release download` and its sha256 is checked. The Dockerfile then vendors it under `/opt/backfill/spkg/` with `sha256sum -c`. The k8s workflows re-check those sha256 values.
7. **Two architectures now exist for "make subgraph X backfillable". This is the key design decision.**
   - **(A) V4-style:** a bespoke Substreams for extraction and Stores, plus a **bespoke native reducer and adapter in the engine**. It is certified for V4 only, and the engine's sink and Parquet path is V4-shaped.
   - **(B) Generic BlockChanges:** run the **deployed mapping WASM** under Graph Node's own runtime crates (`SB/mapping-host`). It emits `pinax.graph.backfill.v1.BlockChanges` frames, and the engine replays them generically (`ENGINE/docs/block-changes-v1-input.md`). Path B needs no hand-port, but it reads Firehose blocks directly. Today it is sequential (about 4 blocks/s in the measured run, `SB/mapping-host/README.md:1408`). It also has open production blockers: `data_sources$` is solved only by the v1 sidecar and v2 chunks, removes and immutables are refused, and no physical profile is production-selectable.
   - In path B, the natural **"engine-compatible Substreams"** is a *parallel `eth_call` cassette and trigger precompute*, not an entity reducer. That is a proposal; none exists yet.

---

## 1. Module graph, inputs, outputs, initial blocks, naming and versions

### 1.1 Package inventory (VERIFIED)

| Package (asset) | `package.name` / version | Manifest | Output module → type | Purpose |
|---|---|---|---|---|
| `uniswap-v4-base-backfill-v0.1.0.spkg` (release v0.1.0; sha256 `75b810d1…9048453`, module hash `8fbf7c14…ed26`) | `uniswap_v4_base_backfill` v0.1.0. The source tree is now v0.1.1 (`V4/substreams.yaml:2-6`), which only removed the runtime from the crate (`V4/README.md:122-125`). | `V4/substreams.yaml` | `map_events` → `proto:pinax.uniswap.v4.base.v1.Events` (`V4/substreams.yaml:22-30`) | raw deployed-trigger stream |
| `uniswap-v4-base-state-stores-v0.1.0.spkg` (release v0.4.0/v0.5.0; sha256 `ac3b2955…a440`) | `uniswap_v4_base_state_stores` v0.1.0 | `V4/substreams-stores.yaml` | 4 Stores + `map_store_probe` → `StoreProbe` | primitive Pool/Tick state |
| `uniswap-v4-base-store-fed-reducer-v0.1.0.spkg` (sha256 `7cf06bb4…58f3`) | `uniswap_v4_base_store_fed_reducer` v0.1.0 | `V4/substreams-store-fed.yaml` | `map_reducer_inputs` → `ReducerInputs` (state_version 0) | v0.3 Tick-only control |
| `uniswap-v4-base-store-state-reducer-v0.5.0.spkg` (sha256 `bac23d47…7df`, module hash `03b7b01f…18ad`) | `uniswap_v4_base_store_state_reducer` v0.5.0 | `V4/substreams-store-state.yaml` | `map_store_state_inputs` → `ReducerInputs` (state_version 3) | **production default** for direct COPY |
| `uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg` (release v0.4.1) | `uniswap_v4_base_nul_metadata_audit` v0.1.0 | `V4/substreams-nul-audit.yaml` | `map_nul_metadata_audit` → `NulMetadataAudit` | evidence-only audit |

The digests come from `V4/packages/base-uniswap-v4-v0.5.0.json:9-124` and
`ENGINE/adapters/uniswap-v4-base/compatibility.json:7-19`. I re-confirmed them
read-only with `gh api repos/pinax-network/substreams-v4-subgraph/releases/tags/{v0.1.0,v0.5.0}`.
The GitHub `digest` fields equal the locked sha256 values, and v0.1.0 carries
only the `.spkg` asset.

**Naming convention (VERIFIED).**
- `substreams pack ... -o $(SPKG_DIR)/{spkgDefaultName}` (`V4/Makefile:35-38`) produces `<package.name with _→->-<version>.spkg`, for example `uniswap-v4-base-backfill-v0.1.1.spkg` (`V4/README.md:92-94`).
- Store packages are packed with explicit `--output-file` names (`V4/Makefile:102-105`).
- Package names follow `<protocol>_<chain>_<role>`. Proto packages follow `pinax.<protocol>.<version>.<chain>.v1` (`V4/proto/events.proto:3`) and `pinax.uniswap.v4.base.store.v1` (`V4/stores/proto/reducer_inputs.proto:3`).

**Network and initial block (VERIFIED).** Every manifest has `network: base`.
Every module, including all Stores and maps, has `initialBlock: 25350988`,
which is the PoolManager start block (`V4/substreams.yaml:25,35`,
`V4/substreams-stores.yaml:32-78`, `V4/substreams-store-state.yaml:50-848`).
They share one initial block so the cache segments align. The graft block
(26,990,278) is **not** the module start. Stores must replay from the module's
initial block, because "Standard Stores cannot import the arbitrary JSON graft
checkpoint" (`ENGINE/docs/substreams-stores.md:572-576`). The engine starts
consuming at the first child block, 26,990,279 (`V4/fixtures/base-ranges.json:6-13`).

### 1.2 `map_events` (the raw contract)

**Inputs (VERIFIED, `V4/substreams.yaml:26-28`).**
- `params: string`, and `source: sf.ethereum.type.v2.Block`.
- The params string pins the network, deployment, graft base and graft block, plus every data-source address and start block (`V4/substreams.yaml:32-33`).
- `Config::parse` *refuses* a missing, duplicate, unknown or differing value. It requires exactly 10 keys (`V4/src/config.rs:26-92`, with the `EXPECTED_KEYS` check at line 62). Addresses compare case-insensitively with an optional `0x` (`config.rs:107-120`).
- Why: params are part of the module hash in Substreams, so pinning them makes the cache identity and the deployment identity the same thing. The refusals stop an operator from silently overriding them.

**Logic (VERIFIED, `V4/src/extract.rs:8-60`).**
- It iterates `block.transactions()`, which yields **successful transactions only** (`SEC:src/block_view.rs:7-10` filters `status == 1`), and then the receipt logs (`extract.rs:11-16`).
- Each data source is gated by `block.number >= <DS>_START` **and** an exact address match (`extract.rs:17-32`).
- Decoders come from `build.rs` Abigen over the **deployed** ABI JSON, filtered to the handled events only (`V4/build.rs:10-36,41-61`). `build.rs` fails if a selected event name is missing.
- `match_and_decode` returns `None` for a malformed log, so malformed logs and wrong-address logs are ignored. Tests cover this at `extract.rs:284-296`.

**Output, `pinax.uniswap.v4.base.v1.Events` (VERIFIED, `V4/proto/events.proto`).**
- `Events { repeated Event events }` (5-7).
- `Event` (9-24) carries:
  - `BlockRef`: number, hash, parent_hash, ts seconds and nanos (26-32);
  - `TransactionRef`: index, hash, origin=`from`, to, gas_price as a decimal string (34-40);
  - `LogRef`: `transaction_log_index`, `block_log_index`, Firehose `ordinal`, address, `graph_node_trigger_order` (42-48);
  - a `DataSource` enum, one value per manifest data source (50-55);
  - a payload `oneof`, one message per handled event (15-23).
- Integer ABI values are carried as **decimal strings**. This covers int24, int128, uint160, uint256 and similar (57-119, populated at `extract.rs:62-135`), which avoids precision loss.
- `Initialize` carries `TokenMetadata token0/1_metadata`. The proto comment says these are "the final values produced by the deployed mapping's string/bytes32 ERC-20 fallback sequence. A missing decimals value means the handler bails out" (`events.proto:70-77`).
- Why it exists: this is the single, minimal, deterministic stream that every downstream Store and the engine consume. `V4/README.md:32-48` lists the guarantees.

### 1.3 Stores and assemblers (VERIFIED)

```text
events:map_events (WASM: substreams_v4_subgraph.wasm)
  ├── store_pool_tick               set bigint      (stores/src/lib.rs:24-32)        [imported from state-stores v0.1.0]
  ├── store_pool_transaction_count  add bigint      (stores/src/lib.rs:34-42)        [imported]
  ├── store_pool_liquidity          set_sum bigint  (stores/src/lib.rs:51-86; reads store_pool_tick.get_at(ord)) [imported]
  ├── store_tick_liquidity          add bigint      (stores/src/lib.rs:44-49) — legacy, NOT used by v0.5.0 (crossed 2 GiB)
  ├── store_tick_liquidity_00..63   add bigint      (store-tick-shards/src/lib.rs:23-121; shard = pool_id[0] % 64)
  ├── store_pool_sqrt_price         set bigint      (store-state/src/lib.rs:23-40)
  ├── store_token_decimals          set bigint      (store-metadata/src/lib.rs:27-46)
  └── store_pool_token_decimals     set bigint      (store-metadata/src/lib.rs:51-74; reads store_token_decimals)
        │
        ├── map_store_state_inputs_00..03  (store-probe/src/lib.rs:223-327; 16 Tick shards each, deltas mode)
        └── map_store_state_inputs         (store-probe/src/lib.rs:331-366; reassembles in decoder order, state_version=3)
```

Manifest wiring is in `V4/substreams-store-state.yaml`:
- imports at lines 12-13;
- `use:` of the 3 imported Stores at lines 39-46;
- shards at lines 48-623;
- the metadata Stores at lines 625-651;
- the partition maps at lines 653-835;
- the final assembler at lines 837-848.

Why each design choice exists:

- **Separate WASM binaries per role (VERIFIED).**
  - The binaries are `primitives` and `probe` in `substreams-stores.yaml:20-26`, and `state_v2`, `pool_metadata`, `reducer_inputs` and `tick_shards` in `substreams-store-state.yaml:25-37`. Each is built from its own crate: `stores/`, `store-probe/`, `store-state/`, `store-metadata/` and `store-tick-shards/`.
  - Reason: the module hash includes the binary. Changing an assembler must not invalidate the expensive Store cache (`ENGINE/docs/substreams-stores.md:267-284`, `V4/AGENTS.md:34-43`).
- **`imports:` of released SPKGs plus `use:` (VERIFIED).**
  - `substreams-store-state.yaml:12-13` imports the *released* state-stores SPKG and reuses three of its Store modules unchanged. This keeps their hashes and their production cache.
  - `scripts/test-store-cache-boundary.sh:22-72` proves it. It appends a WASM custom section to the downstream binary only, then asserts that the Store hashes are unchanged while the downstream hash changes.
- **64 Tick shards (VERIFIED).**
  - The per-Store server limit is 2 GiB. `store_tick_liquidity_03` crossed it at block 39,596,133 under 16 shards (`V4/docs/store-packages.md:104-116`, `V4/README.md:153-158`), and the legacy unsharded Store crossed it earlier (`ENGINE/docs/substreams-stores.md:462-469`).
  - The four partition maps exist because of the **30-input module limit** (`store-probe/src/lib.rs:221-222`).
  - The final map reassembles events in the original decoder order and asserts that it emitted exactly one output per event (`store-probe/src/lib.rs:331-366`).
- **Store values as signed big-endian bytes; decimals as normalized strings** (`reducer_inputs.proto:27-66`). This avoids text conversion in WASM and in the reducer.
- **Graph Decimal128 inside the Substreams.** `store-probe` links `bigdecimal =0.1.2` and `num-bigint =0.2.6`, the exact crates Graph Node v0.44 uses (`V4/store-probe/Cargo.toml`), and normalizes to 34 significant digits (`V4/store-probe/src/decimal.rs:15,36-55`). This lets event-local amounts and prices be cached as exact Graph values. Recursive `derivedETH` and accumulators stay in the engine (`ENGINE/docs/substreams-stores.md:458-500`).
- **before/after values** come from `get_at(ordinal-1)` and `get_at(ordinal)` (`store-probe/src/lib.rs:470-479`). Tick deltas come from `deltas` mode keyed by `(ordinal, key)` (`store-probe/src/lib.rs:565-592`). The engine *validates* every supplied value against its own reducer state; it does not trust them (§3.3).

Measured value (CLAIM, `ENGINE/docs/substreams-stores.md:513-536`): the v3
Store-state path cuts reducer time by about 14% and end-to-end time by about
8.5%, with SQL and checkpoints byte-identical. Store-fed v0.3 alone gave no
speedup (`substreams-stores.md:432-449`). Stores are an **optimization, not a
prerequisite**. The legacy `map_events` paths remain supported fallbacks
(`ENGINE/README.md:30-33`, `ENGINE/AGENTS.md:100-104`).

---

## 2. Ordering and determinism guarantees

### 2.1 What Graph Node v0.44 actually does (VERIFIED from source)

| Rule | Source |
|---|---|
| Log triggers carry `log_index = log.block_index` (block-global) and `transaction_index = trace.index` | `GN:chain/ethereum/src/codec.rs:103-131` (line 124) |
| Receipts come from every transaction trace. Call triggers come from calls that are `!status_reverted && !status_failed`. | `GN:chain/ethereum/src/codec.rs:584-616` |
| `parse_log_triggers` emits a trigger for every receipt log once a log filter exists. Address and topic matching happen later in `DataSource::match_and_decode`. | `GN:chain/ethereum/src/ethereum_adapter.rs:1932-1962`; also `SB/mapping-host/README.md:136-142` |
| Trigger sort: block `Start` triggers first, other block triggers last, logs by `log_index`, calls by tx index, and logs before calls within the same tx | `GN:chain/ethereum/src/trigger.rs:364-404` |
| Block trigger types: `once` → `Start`; polling → `End`; every-block pushes `Start` and `End`; `WithCallTo` for call-filtered block handlers | `GN:chain/ethereum/src/ethereum_adapter.rs:2005-2070` |
| Triggers are sorted, then **deduplicated** | `GN:graph/src/blockchain/block_stream.rs:248-262` |
| Data sources created during a block: the block is **rescanned** for the new data sources, and their triggers are processed in a later **wave** (breadth-first), each trigger across hosts in creation order | `GN:core/src/subgraph/runner/mod.rs:914-990` (comments at 922, 970, 985) |
| A dynamic data source matches only from its `start_block` (its creation block) | `GN:chain/ethereum/src/data_source.rs:690-700` |
| `eth_call` is pinned to the current block **hash**, i.e. post-block state | `GN:chain/ethereum/src/runtime/runtime_adapter.rs:335`; `GN:chain/ethereum/src/ethereum_adapter.rs:600` |

### 2.2 What `map_events` guarantees (VERIFIED)

- **Trigger order key.** `graph_node_trigger_order = u64::from(log.block_index)` (`V4/src/extract.rs:176`). Events are explicitly sorted by `(graph_node_trigger_order, tx.index, transaction_log_index)`. The code comment explains why: it does not trust upstream vector order (`extract.rs:40-57`). The offline test asserts strictly increasing order and order == block_index (`extract.rs:257-268`). The live verifier asserts the same for every block of every fixture range (`V4/scripts/verify-substreams-events.mjs:68-96`).
- **Failed transactions excluded.** `block.transactions()` filters to succeeded transactions (`SEC:block_view.rs:7-10`). Graph Node instead includes receipts from all traces (`codec.rs:584-591`). The two agree only if Firehose receipts of reverted transactions carry no logs. That is a CLAIM I did not verify, and it is worth a fixture assertion in any new package.
- **Firehose ordinal** is carried separately (`LogRef.ordinal`, `extract.rs:174`) and used as the **Store ordinal** (`stores/src/lib.rs:146-148`, `store-tick-shards/src/lib.rs:111`). Within a block it increases monotonically in the same order as `block_index` for successful-transaction logs. Trigger order and store ordinal are therefore distinct fields with distinct jobs.
- **Save clock.** The original `Event` is embedded in every `ReducerEvent` and acts as the authoritative save clock. Store deltas are not POI events (`ENGINE/docs/substreams-stores.md:58-74,243-246`). The engine re-sorts by `(graph_node_trigger_order, block_log_index)` if the input is not monotonic (`ENGINE/src/store_fed.rs:118-127,307-314`).
- **Logical save ordinals** (`event_sequence * SAVE_STRIDE + mapping_save_slot`) are *documented* as the way to order multiple saves per handler across Stores (`ENGINE/docs/substreams-stores.md:214-233`). They are **not implemented in V4**: Stores use the raw log ordinal.
- **No call handlers, block handlers or templates in V4** (`V4/artifacts/deployment/Qmbsc6…/subgraph.yaml:1-103`: three `ethereum/contract` data sources, event handlers only, no `templates:`). This is why `block_index` alone reproduces Graph Node's order. **It does not generalize** (§2.3).
- **Graft boundary.** The graft-block logs are seed input, not child handlers. The first child block is graft+1 (`V4/fixtures/base-ranges.json:6-13`, `ENGINE/docs/parity-contract.md:143-156`).
- **Transport determinism.** The engine's `clock-v1` framing carries the Clock number and hash for every observed block, including empty ones. It refuses undo signals and duplicate or decreasing blocks, checks every embedded `BlockRef` against the envelope, and binds completion to the exclusive stop cursor (`ENGINE/docs/native-protobuf.md:23-102`). For any new package this means each `Event.block.{number,hash}` must equal the Clock, and the stream must run in **final-blocks-only / production mode** (`native-protobuf.md:172-173`).

### 2.3 Generalization: the order key a template subgraph needs

For a subgraph with templates, call handlers or block handlers, the order key
must reproduce §2.1:

```
order = (wave, kind_rank, position, host_order)
  wave       = 0 for triggers of data sources that existed before this block;
               k+1 for data sources created while processing wave k of this block
  kind_rank  = 0 block-Start, 1 log/call, 2 block-End/polling/WithCallTo
  position   = for logs: block_index; for calls: (tx_index, after-all-logs-of-that-tx)
  host_order = static data sources in manifest order, then dynamic ones in creation order
```

**Aerodrome concretely (VERIFIED from the manifest and public Slipstream source; still to be confirmed on chain fixtures).**
- In `SB/aerodrome-slipstream-base/reference/deployment.yaml`, Factory has `handlePoolCreated` only (lines 22-36). NPM has four handlers with `calls:` (lines 55-86). The `Pool` template has Initialize, Swap, Mint, Burn and Flash (lines 96-145).
- The `features` are `nonFatalErrors` and `grafting`, with no graft. `specVersion` is 1.2.0 (lines 88-95).
- Slipstream `CLFactory.createPool` calls `CLPool(pool).initialize(...)`, which does `emit Initialize`, and only then `emit PoolCreated` (velodrome-finance/slipstream `main` @ `193a6b85`, `contracts/core/CLFactory.sol:82-110`, `CLPool.sol:148-178`).
- Under Graph Node, `handlePoolCreated` runs in wave 0. The rescan then finds the *earlier* Initialize log for the new Pool data source and runs `handleInitialize` in wave 1, **after every other wave-0 trigger in the block**. Any Mint or Swap of the new pool in the same block (for example an NPM mint that creates the pool) also lands in wave 1, after the NPM `IncreaseLiquidity` and `Transfer` handlers of wave 0.
- A V4-style per-ordinal Store filter would *drop* Initialize, because the pool is not in the Store at that ordinal. A plain log-index sort would *misorder* it.

---

## 3. `eth_call`-dependent data

### 3.1 How V4 does it (VERIFIED)

- `metadata::enrich` collects every non-zero `currency0` and `currency1` from **every** `Initialize` in the block and dedupes them into a `BTreeSet`. It then issues one batched `rpc::eth_call` with four calls per address: `symbol`, `name`, `totalSupply` and `decimals`, using raw selectors (`V4/src/metadata.rs:16-49`).
- If the response count does not match, the **block fails** rather than degrading (`metadata.rs:50-56`).
- It emulates the deployed fallbacks:
  - a reverted or failed call becomes `unknown`, `"0"`, or `decimals=None` (`metadata.rs:94-107`);
  - string decoding falls back to `bytes32` truncated at the first NUL, and the `0x…01` "null eth value" sentinel is treated as absent (`metadata.rs:109-134`);
  - decimals are accepted only when `< 255` (`metadata.rs:104`);
  - the zero address is native ETH with 18 decimals (`metadata.rs:74-85`).
- **Superset fetching is intentional.** The deployed mapping only calls metadata for tokens it has not seen (`ENGINE/src/reducer.rs:98-122`). `map_events` calls for every Initialize, because Substreams cannot know mapping state. That is safe because `eth_call` at a fixed block hash is a pure function. A *missing* call would be fatal; an *extra* one is free apart from its cost.
- **Block semantics.** Graph Node pins calls to the block hash (VERIFIED, §2.1). For Substreams, the server documents the block-hash default plus two opt-in non-deterministic overrides (CLAIM, `~/Github/substreams/ENVIRONMENT_VARIABLES.md:74-88`). Neither the backfill workflows nor the local `k8s-substreams` clone mention them. The Base tier1 sends `eth_call` to `--substreams-rpc-endpoints=http://${NETWORK}.rpcx.${CLUSTER_ZONE}-prod-rpc-a.pinax.io/...` (`~/Github/k8s-substreams/chains/base/v2/prod/substreams-tier1/kustomization.yaml:34`, from a local clone that may be stale). Modules that import `eth_call` may require `X-substreams-acknowledge-non-deterministic` when the server enables that check (CLAIM, `~/Github/substreams/docs/release-notes/change-log.md:671`).
- **Caching consequence.** Because `eth_call` lives in `map_events`, the RPC results are cached with the module output. A noop warm-up pays the archive-RPC cost exactly once, and every later consumer is RPC-free.

### 3.2 Host-call inventory as a contract (VERIFIED, documented)

`ENGINE/docs/parity-contract.md:71-95` lists every `ethereum.call` that each
deployed WASM imports. Only PoolManager calls ERC-20 metadata; PositionManager
and Arrakis import no `ethereum.call`. It also lists the deployed fallback
semantics, including that "A successful ABI string call may legitimately return
an empty symbol" (`parity-contract.md:88-91`).

### 3.3 How the engine validates it (VERIFIED)

- A missing `TokenMetadata` raises `StateError::MissingMetadata`. A missing `decimals` makes the Initialize handler return early without creating the Pool, which reproduces the mapping bail (`ENGINE/src/reducer.rs:216-233`, consumed at 104-122).
- **Pool existence stays reducer-owned.** A false-positive Store entry, for example from a rejected Initialize, never makes later handlers run (`ENGINE/docs/substreams-stores.md:207-212`; `ENGINE/src/store_fed.rs:141-160`, test at `store_fed.rs:1042`).
- Store-state version 3 refuses missing or mismatched Pool before/after state, prices, token amounts or Tick state **before PostgreSQL is opened** (`ENGINE/AGENTS.md:161-165`, `ENGINE/src/store_fed.rs:97-99,334-361`).
- NUL bytes in metadata cannot be stored in PostgreSQL. The explicit `postgres-nul-truncate-v1` profile handles them (`ENGINE/docs/parity-contract.md:116-141`, `ENGINE/adapters/uniswap-v4-base/compatibility.json:122-155`). A separate audit SPKG proves where the profile applies (`V4/docs/nul-metadata-audit.md`).
- Gate A logical parity compares the final entity values against a paused Graph Node. It does not compare raw `eth_call` results directly (§5).

### 3.4 The generic alternative: an `eth_call` cassette (VERIFIED in `SB/mapping-host`)

- The mapping-host reimplements Graph Node's `ethereum.call`. The lookup key is `(block hash, address, calldata)`. The value is `Null` for a revert (a decode failure is also treated as a revert) or the return data (`SB/mapping-host/README.md:228-264`).
- Replay is the default and **fails closed** on a missing key. Recording pins the call by EIP-1898 block hash (`README.md:266-275`).
- This keeps the **mapping's own fallback code** authoritative. V4 had to re-implement the fallbacks in `metadata.rs`; the cassette does not.

**For Aerodrome the `eth_call` volume is a first-order cost (VERIFIED manifest, CLAIM on cost).**
- Declared calls run per event: `positions(tokenId)` on every NPM event; `ticks(lower)` and `ticks(upper)` on every Mint and Burn; `feeGrowthGlobal0X128` and `feeGrowthGlobal1X128` on **every Swap** and Flash (`reference/deployment.yaml:55-76,116-143`).
- There are also mapping-internal calls: ERC-20 metadata in `handlePoolCreated` and `Factory.getPool` from the Pool mapping (`SB/aerodrome-slipstream-base/layout-profile-v1.json`, `retained_wasm_static_behavior`).
- Options:
  - Substreams batched `eth_call` per block (V4 style, cached once);
  - deriving end-of-block slot values from Firehose `storage_changes`, if Pinax Base blocks are extended (unverified);
  - a Substreams module that emits the cassette rows themselves.

  All three need the exact calldata, which is mechanically derivable for *declared* calls and requires WASM analysis for *undeclared* ones.

---

## 4. Dynamic data sources (templates)

### 4.1 V4: not applicable (VERIFIED)

- The V4 manifest has no `templates` (`V4/artifacts/deployment/Qmbsc6…/subgraph.yaml`). Pools are rows keyed by `pool_id` under a singleton PoolManager. `LogCreatePrivateHook` is just an event that creates an `ArrakisHook` entity (`V4/src/extract.rs:127-135`).
- The Stores track pools as keys (`stores/src/lib.rs:24-86`), not as data sources. The reducer decides existence (§3.3).
- The engine's V4 path keeps the seed's `data_sources$` table as-is; the q8 evidence mentions a "seed-preserved `data_sources$`" (`SB/README.md`, Uniswap V4 import section). Gate B physical parity includes `data_sources$` (`ENGINE/docs/differential-validation.md:64-66`).

### 4.2 Engine support for templates (VERIFIED docs, generic path only)

- **BlockChanges v1 carries no data-source creation event.** A faithful spool for a template deployment is refused unless a sidecar is supplied, tracked as `substreams-backfills#117` (`ENGINE/docs/block-changes-v1-input.md:445-471`).
- **`pinax.graph.backfill.data-sources/v1` JSON sidecar** (`ENGINE/docs/data-sources-sidecar-v1.md:1-46`):
  - records come from *accepted, deduplicated runtime hosts* (`as_stored_dynamic_data_source`), in host creation order, with creation block, template `manifest_idx`, raw address and NULL context;
  - failed-handler creations are discarded;
  - limits: root-only, at most 10,000 blocks / 16 MiB, NULL context only, and no runs with indexing errors.
- **v2 resumable chunks** (`ENGINE/docs/data-sources-chunks-v2.md`): identity `(manifest_idx, address)`, a sorted `BCDSIDX2` index, and an immediate-predecessor trust boundary. It is an offline capability only, not a loader.
- **COPY columns** for `data_sources$`: `block_range, causality_region, manifest_idx, parent, id, param, context, done_at` (`data-sources-sidecar-v1.md:39-46`).

### 4.3 How a Substreams should track template instances (proposal, derived from §2.1)

1. `store_<template>_instances`: `set_if_not_exists` keyed by the instance address. The value is `(creation_block, creation_ordinal, manifest_idx, creating_log_block_index)`. It is written from the factory event of **every** candidate creation; this is a superset, the same pattern as V4's metadata Store (`store-metadata/src/lib.rs:23-26`). It must start at the factory's start block (13,843,704 for Aerodrome), because Stores cannot be seeded (`ENGINE/docs/substreams-stores.md:572-576`).
2. The extraction map reads that Store in **get mode with `get_last`**, which includes this block's creations. It includes *all* of the instance's logs in its creation block, regardless of ordinal, which matches Graph Node's rescan (`runner/mod.rs:970-976`). It assigns `wave = 1` to logs of instances created in this block and `wave = 0` otherwise.
3. Because a creation can be **mapping-conditional** (an early return, or a deterministic error under `nonFatalErrors` that discards the creation), the consumer must own actual existence. This is exactly V4's "reducer-owned Pool existence" rule. The Substreams must *never* drop a log because it guesses the mapping would not create the source.
4. Ordering inside a wave follows `(log index, host creation order)`. Nested creation (wave 2+) is breadth-first.

---

## 5. Testing and validation strategy

### 5.1 In the Substreams repo (VERIFIED)

| Layer | What | Where |
|---|---|---|
| Artifact pinning | IPFS objects are locked by CID, SHA-256 and length. The verifier recomputes CIDv0 offline and checks all 18 entity declarations and the WASM headers. | `V4/artifacts/deployment/*/artifacts.lock.json`; `V4/docs/deployed-artifacts.md:1-33`; `scripts/verify-pinned-artifacts.sh` |
| Source provenance | The upstream commit is classified "reconstructed, not byte-verified". **The deployed WASM is the executable oracle.** | `V4/docs/deployed-artifacts.md:47-66` |
| Canonical fixtures | Real Base receipts for pinned ranges, captured via `eth_getLogs` and receipts and committed. A re-verifier checks they are still canonical. | `V4/fixtures/base-ranges.json:23-111`; `V4/fixtures/event-logs.json`; `scripts/capture-event-fixtures.mjs:59-80`; `scripts/verify-base-fixtures.mjs` |
| Offline unit tests | All 7 event kinds from fixtures; multiple events per tx; malformed and wrong-address logs; int24/int128 boundaries; trigger order; params pinning; metadata fallbacks; shard routing; tick key encoding | `V4/src/extract.rs:227-324`; `V4/src/config.rs:129-157`; `V4/src/metadata.rs:151-178`; `V4/store-tick-shards/src/lib.rs:134-166`; `V4/store-probe/src/lib.rs:793-858` |
| Live bounded run | `make verify-live` runs `substreams run ... -o jsonl --final-blocks-only` per fixture range. It asserts counts, start and end hashes, anchor tx/log, source address per `DataSource`, origin format, and strictly increasing trigger order. | `V4/Makefile:44-46`; `V4/scripts/verify-substreams-events.mjs:34-126`; results in `V4/docs/event-decoder-validation.md:40-56` |
| Refactor differential | Old and new packages are run over the same ranges, and the JSONL is compared byte-for-byte (162 blocks, identical). | `V4/docs/event-decoder-validation.md:58-73` |
| Cache boundary | Mutate only a downstream binary, then assert the Store hashes are unchanged and the downstream hash changed. Also check the import hashes. | `V4/scripts/test-store-cache-boundary.sh:22-72`; `test-store-state-cache-boundary.sh`; `test-nul-audit-cache-boundary.sh` |
| Generated code | `substreams protogen` followed by a `git status` cleanliness check | `V4/scripts/check-generated.sh:5-11` |
| Release verification | sha256, name, version, module hash, output type, shard count and input graph against the JSON lock | `V4/scripts/verify-release-packages.sh:25-85`; `scripts/verify-store-state-package.sh` |
| CI | `parity.yml` runs offline tests, fmt, clippy `-D warnings`, `stores-validate`, locked release staging and the NUL candidate, and uploads a JSON report | `V4/.github/workflows/parity.yml:11-56`; `scripts/offline-parity-ci.sh:28-45` |

### 5.2 In the engine (VERIFIED docs; the numbers are CLAIMs)

- **Gate A, logical.** The engine exports the active state before each range from a *paused* Graph Node (zero replicas required), replays the Substreams events, and fails on any field difference, missing or extra write, write-order difference or final POI difference. The certified result is 1,561/1,561 writes with 0 differences over 270 blocks (`ENGINE/docs/differential-validation.md:8-51`). The canonical comparison format must never sort by entity type or ID (`ENGINE/docs/parity-contract.md:11-42`).
- **Gate B, physical.** A Parquet dump is restored into Graph Node v0.44, and all 20 tables are compared via PostgreSQL `jsonb`. `vid` is the only excluded column (`differential-validation.md:53-84`).
- **Lifecycle.** Unmodified Graph Node continues, restarts, rewinds and replays from the restored state (`differential-validation.md:121-126`).
- **Transport differential.** The JSONL path and the native frame path must give byte-identical spools and POI (`ENGINE/docs/native-protobuf.md:175-191`).
- **SPKG identity.** `make verify-spkg` checks sha256, name, version, network, module kind, hash, output type and initial block, then runs a live smoke (`ENGINE/scripts/verify-spkg-compatibility.sh:25-71`).
- **POI vectors.** 33 Graph Node-generated digests cover every `GraphValue` kind (`ENGINE/docs/block-changes-v1-input.md:222-233`).
- **Full canary and certificates:** `ENGINE/AGENTS.md:252-279`.

### 5.3 Generic path (VERIFIED docs)

- The mapping-host replays four committed fixture blocks and one contiguous 1,053-block window. It reports per-block frame sha256 and public PoI, and it makes **no parity claim against an indexer** (`SB/mapping-host/README.md:1245-1366,1430-1460`).
- `tests/mapping_host_stream.rs` pipes 300 frames into the engine's `state-replay` binary and requires that the final state equals the producer's store and that the PoI chain equals Graph Node's (`ENGINE/docs/block-changes-v1-input.md:244-268`).

---

## 6. Build and release

### 6.1 Toolchain (VERIFIED)

- **Rust and targets:** Rust `1.90.0`, with clippy, rustfmt, `wasm32-unknown-unknown` and the minimal profile (`V4/rust-toolchain.toml:1-5`).
- **Exact crate pins** (`V4/Cargo.toml:11-27`): `substreams =0.7.6`, `substreams-ethereum =0.11.1`, `prost =0.13.5`, `ethabi =17.2.0`, `serde_json =1.0.142` with `arbitrary_precision`, and `getrandom =0.2.16` with `custom` for wasm.
- **Release profile:** `lto=true`, `codegen-units=1`, `strip=true` (`Cargo.toml:29-32`).
- **Protobuf generation:** `buf.build/community/neoeinstein-prost:v0.4.0` and `-prost-crate:v0.4.1`, invoked through `substreams protogen` (`V4/buf.gen.yaml:1-10`, `Makefile:14-16`). The generated `src/pb` is committed and drift-checked.
- **ABI bindings:** `build.rs` generates them from the deployed ABIs (`V4/build.rs`).
- **Substreams CLI:** `v1.20.3`, installed from the GitHub tarball with a pinned sha256 of `90c71d04…f8675`, both in CI (`V4/.github/workflows/release.yml:20-24`, `parity.yml:19-23`) and in the engine image (`ENGINE/Dockerfile:585-602`).
- **Engine Go module:** `cmd/substreams-native` uses `github.com/streamingfast/substreams v1.18.4` as its sink client (`ENGINE/go.mod:8`).
- **Commands:** `make validate` = check-generated + test + lint + pack + stores-validate (`V4/Makefile:134-135`). `make run` streams the first-child range from `base-substreams-tier1-prod.kan-sst2.pinax.io:443` (`Makefile:1-3,40-42`).

### 6.2 Release (VERIFIED)

- **Trigger and toolchain:** a tag push `v*` runs `release.yml` with Rust 1.90.0 and CLI v1.20.3 (`V4/.github/workflows/release.yml:3-24`).
- **Per-tag policy** (`release.yml:25-50`):
  - `v0.4.0` and `v0.5.0` copy **committed certified bytes** from `release/v0.4.0/` and `release/v0.5.0/` and verify them against the JSON lock (`Makefile:118-132`);
  - `v0.4.1` builds the evidence-only NUL audit;
  - any other tag is refused.
- **Publish:** `gh release create <tag> *.spkg --verify-tag` (`release.yml:51-57`). The rules are: no `--clobber`, never replace an asset, no checksum sidecars (commit `b750a51`), and GitHub's asset digest is the published checksum (`V4/docs/store-packages.md:92-102`, `ENGINE/AGENTS.md:193-197`).
- **Why committed bytes:** "Never call a host-built SPKG production-identical. Rust WASM can embed build paths" (`V4/AGENTS.md:56-59`). The engine's own event-decoder doc records a *host* build with sha `c604051c…` and module hash `c26aa7a6…`, which differ from the certified release `75b810d1…`/`8fbf7c14…` (`ENGINE/docs/event-decoder-validation.md:9-19`). Module hashes are therefore **not reproducible across hosts**. Certify the bytes CI built, then freeze them.
- **Not used for SPKGs:** no ORAS and no GHCR. ORAS appears only in the mapping-host image discovery contract (`SB/docs/v3-mapping-host-runtime.md:60`). The engine runtime is an OCI image pinned by digest (`ENGINE/adapters/uniswap-v4-base/compatibility.json:158-168`).

### 6.3 How the engine pins the SPKG (VERIFIED)

1. **Contract.** `compatibility.json` records `repository`, `release`, `asset`, `sha256`, `package_name`, `package_version`, `network`, `module`, `module_hash`, `output_type` and `initial_block` for each package. It also records the imported Store hashes and shard hashes (`ENGINE/adapters/uniswap-v4-base/compatibility.json:7-111`). The production contract is `adapters/uniswap-v4-base/store-state-v0.5.0.json`.
2. **Download.** `scripts/download-uniswap-v4-spkg.sh:7-44` runs `gh release download` and then compares the sha256, refusing a mismatch. Make targets: `download-spkg` and `download-runtime-spkgs` (`ENGINE/Makefile:126-152`).
3. **Identity check.** `scripts/verify-spkg-compatibility.sh:25-47` checks the sha256, then runs `substreams info --json` and asserts name, version, network, kind=map, module hash, output type and initial block.
4. **Image vendoring.** The image copies the SPKGs into `/opt/backfill/spkg/` and runs `sha256sum -c` (`ENGINE/Dockerfile:616-623`, and 376/401 for v0.5.0).
5. **Workflow re-checks.** The k8s workflows re-assert the sha256 and the runtime identity before running:
   - `k8s-subgraphs/subgraphs-operations/backfill/kan/compute-only-workflow-template.yaml:203` checks the Store-state v0.4.0 sha;
   - `production-workflow-template.yaml:100-118` verifies `store-state-v0.5.0.json` and then copies it over `compatibility.json`;
   - `terminal-certification-workflow-template.yaml:53,472` pins the NUL-audit release URL.
6. **Changing an SPKG** requires changing the contract and rerunning every gate; swapping the file alone is unsupported (`ENGINE/README.md:147-162`, `ENGINE/AGENTS.md:147-159`).

---

## 7. Generic recipe: from a deployed subgraph to an engine-compatible Substreams

Labels: **[M]** mechanical or automatable from artifacts; **[R]** requires
reverse-engineering the mapping's semantics; **[O]** operational or evidence work.

### Phase 0. Decide the architecture first [O]

| | A: V4-style (bespoke Substreams + native reducer) | B: Generic BlockChanges (deployed WASM) |
|---|---|---|
| Substreams scope | `map_events` + optional Stores + assembler | none required today; optional parallel `eth_call`/trigger precompute (proposal) |
| Entity semantics | **hand-ported Rust reducer in the engine** [R, large: V4 reducer 1,460 LOC plus entities, decimal, math and a static 20-table sink] | executed by the deployed AssemblyScript under Graph Node's runtime (`SB/mapping-host/README.md:1-23`) |
| Ordering and waves | must be re-implemented (§2.3) | inherited from Graph Node's own `BlockWithTriggers` and runner (`SB/mapping-host/README.md:136-142`) |
| `eth_call` | Substreams `eth_call` with emulated fallbacks | cassette; the mapping's own fallbacks apply |
| Parallelism | extraction and Stores parallel and cached; reducer sequential | currently sequential end to end (~4 blocks/s measured, `SB/mapping-host/README.md:1408`) |
| Templates / `data_sources$` | not supported by V4 code; would need new engine work | v1 sidecar / v2 chunks exist but are not production loaders (§4.2) |
| Engine readiness | certified for V4 only | blocked: removes, immutables, no production-selectable profile, `data_sources$` (`ENGINE/docs/block-changes-v1-input.md:473-497`) |

For Aerodrome, which has templates, declared calls, `nonFatalErrors`, and a
302-field schema with no public source (`SB/aerodrome-slipstream-base/README.md`):
path A needs a full reducer port of an unsourced WASM, while path B needs the
generic engine blockers closed. **This is the decision the design phase must make.**

### Phase 1. Pin the target [M/O]

1. **[M]** Fetch the deployment closure from IPFS: manifest, schema, ABIs and every mapping WASM. Write `artifacts.lock.json` with the CID, sha256 and byte length of each object, and verify CIDv0 offline. Prior art: `V4/artifacts/deployment/*/artifacts.lock.json`, `V4/docs/deployed-artifacts.md`, `SB` `cargo xtask verify-target <family>`. **Aerodrome is already pinned** in `SB/aerodrome-slipstream-base/reference/` and `docs/provenance/aerodrome-slipstream-base-target.json`.
2. **[O]** Classify the source provenance as byte-reproduced, reconstructed or unresolved. The deployed WASM stays the oracle (`V4/docs/deployed-artifacts.md:47-66`). Aerodrome's source revision is **unresolved** (`SB/aerodrome-slipstream-base/README.md:28-42`).
3. **[O]** Run the eligibility gate (`SB/README.md`, "Backfill eligibility gate"). Every Aerodrome truth gate, including eligibility, is still `false` (`SB/aerodrome-slipstream-base/QmasYjyp….yaml`).

### Phase 2. Static manifest and WASM inventory [M, then R]

4. **[M]** From the manifest, enumerate:
   - data sources and templates, with name, address, start block and ABI;
   - every handler kind (event, call, block with filter) and its signature, including the `indexed` flags;
   - declared `calls:`;
   - `features` (nonFatalErrors decides the deterministic-error policy);
   - graft base and block;
   - `specVersion` and `apiVersion`. These select the PoI fold: spec ≥ 0.0.6 → Fast, otherwise Legacy (`SB/mapping-host/README.md:319`). Aerodrome at 1.2.0 → Fast; V4 at 0.0.4 → Legacy.
5. **[M]** From each WASM, inventory the imports and exports: `ethereum.call`, `dataSource.create`, `store.get/set/remove`, `ipfs.*` and so on. Prior art: `layout-profile-v1.json` `retained_wasm_static_behavior` and `ENGINE/docs/parity-contract.md:71-95`.
6. **[R]** For each `ethereum.call` site, determine the target, function, args provenance and revert or decode fallback. Declared calls are [M]. Undeclared helpers, such as ERC-20 metadata with bytes32 fallbacks and static token tables, are [R].
7. **[R]** For each `dataSource.create` site, determine which event creates which template, under what conditions, and whether any context is passed.

### Phase 3. Proto design [M]

8. **[M]** Use one envelope `Events { repeated Event }`, one `Event` per Graph Node trigger, carrying:
   - `BlockRef`: number, hash, parent_hash, timestamp;
   - `TransactionRef`: index, hash, from, to, gas_price, plus any other `event.transaction` field the mapping reads;
   - `LogRef`: tx log index, **block log index**, Firehose ordinal, address, **trigger order**, plus **`wave`** and **`host_order`** for template subgraphs;
   - a `DataSource` enum with one value per data source **and template**;
   - for template instances, the instance address and creation identity;
   - a payload `oneof` with one message per handled event or call.

   Carry ABI integers as decimal strings and keep raw bytes, as in `V4/proto/events.proto`. Also carry everything the mapping reads from `event.*`; for example `event.transaction.gasPrice` is used for fee accounting (`V4/src/extract.rs:157-170`).
9. **[M/R]** Choose the `eth_call` representation:
   - (a) mapping-final values, as V4 does. This is [R] because the fallbacks are re-implemented.
   - (b) **raw call results** `{to, calldata, retval|reverted}` per call, attached to the event or per block. This is [M] once the call inventory exists, and the consumer applies the mapping's own logic. **Recommended for any new family.** It keeps the Substreams free of mapping semantics and maps directly onto the mapping-host cassette schema (`SB/mapping-host/README.md:247-261`).

### Phase 4. Implement `map_events` [mostly M]

10. **[M]** Scaffold:
    - Cargo workspace with exact pins (V4 set or newer, frozen in `Cargo.lock`) and `rust-toolchain.toml`;
    - `build.rs` with `Abigen` over the deployed ABI JSON, filtered to handled events, failing when an expected event is missing (`V4/build.rs`);
    - `substreams.yaml` with `params` pinning network, deployment, graft and every address and start block;
    - `Config::parse` with exact-key refusal (`V4/src/config.rs`).
11. **[M]** Extract from successful-transaction receipt logs: gate by `block >= start` and exact address for static sources, and by Store membership for template instances (§4.3). Decode with `match_and_decode`, so malformed logs are dropped. Fill the identity fields. **Sort explicitly** by the full order key (§2.3), and never rely on vector order.
12. **[M/R]** For call handlers and block handlers, use `transaction_traces[].calls` filtered `!status_reverted && !status_failed` (`GN:codec.rs:605-614`). Block triggers follow `GN:ethereum_adapter.rs:2005-2070`.
13. **[M]** Batch every `eth_call` per block: dedupe and preserve request order. **Fail the block** on a response-count mismatch (`V4/src/metadata.rs:45-56`). Over-fetch: call for every candidate, whether or not the mapping would actually call.
14. **[M]** Emit a message for every block, even empty ones, and stream with `clock-v1` framing in production mode (`ENGINE/docs/native-protobuf.md:35-66`).

### Phase 5. Tests and evidence [M/O]

15. **[M]** Choose canonical fixture ranges that together cover every handler and template creation, the first block and the graft boundary, multiple events per tx and block, and same-block creation plus use (the wave case). Capture receipts, pin the block hashes and commit them (`V4/fixtures/base-ranges.json`, `scripts/capture-event-fixtures.mjs`).
16. **[M]** Write offline Rust tests for:
    - every event kind;
    - wrong address and malformed logs;
    - numeric boundaries;
    - order invariants;
    - param refusal;
    - `eth_call` fallback decoding;
    - **wave ordering for same-block template creation** (new; not in V4).
17. **[M]** Add a live bounded verify over the pinned ranges (`substreams run -o jsonl --final-blocks-only`) asserting counts, boundary hashes, anchors and order. For any refactor, byte-diff the JSONL of the old and new packages (`V4/docs/event-decoder-validation.md:40-73`).
18. **[O]** Run a logical parity Gate A against a paused Graph Node copy and its seed before any engine work is called complete (`ENGINE/docs/differential-validation.md:8-51`).

### Phase 6. Optional Store acceleration [R]

19. **[R]** Move a field into a Store only after proving that its update policy is an exact merge. Use `set` for absolute values, `add` for integer counters, `set_sum` for set-plus-relative, and `set_if_not_exists` for immutable metadata. **Never** put Decimal128 accumulators or recursive pricing in a Store (`ENGINE/docs/substreams-stores.md:145-205`).
20. **[M]** Packaging rules:
    - one crate and binary per Store family, separate from the maps;
    - `imports:` plus `use:` for released Stores;
    - shard any Store that may exceed the 2 GiB per-Store server limit, using a deterministic key prefix;
    - at most 30 inputs per module;
    - the 100-module package ceiling (CLAIM, `ENGINE/docs/substreams-stores.md:157-162`);
    - a cache-boundary test (`V4/scripts/test-store-cache-boundary.sh`).
21. **[R]** Downstream assembler maps emit before and after values with signed big-endian integers. The engine must validate them against its own state; Store values are inputs, never authority (`ENGINE/AGENTS.md:161-165`).

### Phase 7. Release and pin [M]

22. **[M]** Tag `vX.Y.Z` in the Substreams repo. CI builds with the pinned Rust and CLI, verifies the result against a JSON release lock (sha256, module hashes, output type, graph shape), then runs `gh release create` with no clobber and no sidecars. Freeze certified bytes under `release/` if later rebuilds must not replace them.
23. **[M]** Add an adapter contract on the engine side (`adapters/<family>/compatibility.json`), a download script with sha256 verification, a `verify-spkg` identity check, and image vendoring with `sha256sum -c`. Add the matching sha256 re-check in the k8s WorkflowTemplates.

### Phase 8. Engine consumption [R for path A / O for path B]

24. **Path A [R, large]:** add a family adapter to the engine: proto copy, reducer port, entity types, physical table catalog, POI integration, then Gates A and B, lifecycle and the full canary.
25. **Path B [O]:**
    - bundle the deployment under `SB/mapping-host/segments/<cid>/`;
    - generate the descriptor;
    - record or produce the `eth_call` cassette (a Substreams precompute could replace live recording; proposal);
    - emit BCF1 frames and the `data_sources` sidecar or chunks;
    - replay with `state-replay --input-format block-changes-v1-framed`;
    - close the production blockers.

### What a "noop + backfill" workflow means for either path (VERIFIED mechanics, CLAIM numbers)

- **noop / warm-up:** request the final output module over the range in production mode with high parallelism (`X-Substreams-Parallel-Workers: 500`, `--limit-processed-blocks` = the range length), and discard the output. This populates the tier2 module and Store caches; `eth_call` results are cached inside the module output.
- **backfill:** re-request the same module hashes; they are served from cache.
- **Measured on V4 (CLAIM):** 100,000 blocks took 127.66 s cold versus 20.79 s cached (`ENGINE/docs/benchmark-100k.md:57-58`). The Store chain over 1.64M blocks prepared in 432 s, and the cached repeat took 2.83 s (`ENGINE/docs/substreams-stores.md:389-395`).
- **Prerequisite:** this only works if module hashes stay stable between the noop and the backfill. Use the same SPKG bytes and the same params, and isolate binaries.

---

## 8. Aerodrome deltas versus V4 (what the V4 pattern does not cover)

| Aspect | V4 | Aerodrome `QmasYjyp…` | Consequence |
|---|---|---|---|
| Data sources | 3 static | 2 static (Factory, NPM) + **Pool template** | template Store + wave ordering (§2.3, §4.3) |
| Same-block creation | n/a | Initialize is emitted **before** PoolCreated in the same tx (verified on public source) | wave-1 handling mandatory |
| `eth_call` | ERC-20 metadata on Initialize only | declared calls on every NPM event, Mint/Burn (ticks) and **Swap**/Flash (feeGrowth); ERC-20 metadata; `Factory.getPool` | orders of magnitude more archive-RPC load; choose the representation (§3.4) |
| Spec / PoI | 0.0.4 / Legacy | 1.2.0 / Fast (rule from `SB/mapping-host/README.md:319`) | engine supports both folds (`ENGINE/docs/block-changes-v1-input.md:143-209`) |
| Graft | child of a graft | `features: grafting` but **no graft** (`reference/deployment.yaml:88-90`) | replay from 13,843,704 with an empty seed, or seed from a dump of the existing partial Kan deployment |
| Error policy | nonFatalErrors | nonFatalErrors | failed-handler effects and template creations are discarded; only the mapping knows |
| Source | reconstructed from Uniswap commit | **unresolved** | path A needs a full WASM-derived port |
| Schema | 18 entities (V4 child) | 20 entities, 302 fields, all mutable (`SB/aerodrome-slipstream-base/README.md:47-51`) | |
| Existing decoders | n/a | `substreams-evm/dex/aerodrome` is Solidly V2; `dex/uniswap-v3` has the wrong PoolCreated shape (`SB/aerodrome-slipstream-base/README.md:53-62`); `substreams-abis/abi/dex/aerodrome` holds Solidly ABIs | use the **deployed ABIs** via `build.rs` (V4 pattern) |

---

## 9. Discrepancies and stale documentation found

- `V4/README.md:113-120` says release v0.1.0 contains "its SHA-256 checksum". The live release has only the `.spkg` asset, per `gh api` and commit `b750a51`, "Publish SPKGs without checksum sidecars".
- `V4/AGENTS.md:37-39` says "Preserve all 16 Tick-liquidity shards", while v0.5.0 has 64 (`V4/README.md:127-140`, `packages/base-uniswap-v4-v0.5.0.json:47-50`). `V4/AGENTS.md:21` still names the v0.4.0 lock as authoritative.
- `ENGINE/AGENTS.md:152-153,281-282` and `compatibility.json:47-58` still point at Store-state **v0.4.0** (16 shards, `bc8a841d…`). The production runtime and Kan workflow use **v0.5.0** (`ENGINE/Dockerfile:376-421`, `adapters/uniswap-v4-base/store-state-v0.5.0.json`, `k8s-subgraphs/.../production-workflow-template.yaml:100-118`), and the workflow copies the v0.5.0 contract over `compatibility.json` at runtime.
- `ENGINE/docs/substreams-stores.md:378-381` says Store SPKGs are released "and checksum separately", which is stale (sidecars removed).
- `ENGINE/docs/event-decoder-validation.md:14-19` quotes host-build hashes (`c604051c…`/`c26aa7a6…`) that differ from the certified release. This is not wrong (it documents a host build), but it is an easy trap for copy-paste pinning.
- My memory note says the k8s-subgraphs repo has no Argo backfill templates. The snapshot does have `subgraphs-operations/backfill/{kan,base}/*-workflow-template.yaml`.
- The V4 Substreams repo uses `.sh` and `.mjs` tooling. The `substreams-backfills` repo has a **Rust-only** policy, so new tooling goes into `cargo xtask` (user memory, issue #110). A new family package hosted in `SB/` must follow that policy, not the V4 script style. The imported `SB/uniswap-v4/` is frozen and source-identical.

---

## 10. Risks and blockers for the design phase

1. **Architecture choice (A vs B)** decides whether an Aerodrome "Substreams" is the main artifact (path A) or an accelerator (path B). Path A for an unsourced 302-field mapping is a very large [R] effort. Path B has engine production gates open.
2. **Wave ordering for templates** is unimplemented in any Pinax Substreams. It must be fixture-proven on a real Aerodrome pool-creation block, including the NPM-mint-creates-pool case.
3. **`eth_call` volume on Base Slipstream:** 2 calls per Swap, 2 per Mint/Burn and 1+ per NPM event, over about 39M blocks (13.84M → 52.87M head). Tier2 archive-RPC throughput, cost and determinism (block-hash pinning, no fallback-to-latest) must be confirmed on the Pinax Base tier2 config.
4. **Store size limits.** Any per-pool or per-tick Store over Aerodrome history must be sharded from day one (lesson of V4 v0.4 → v0.5).
5. **Module-hash stability between noop and backfill:** host builds differ, so pin and freeze CI-built bytes before warming the cache.
6. **Same-hash fidelity:** the backfilled deployment must be indistinguishable from native sync (`SB/README.md`, "Deployment-hash fidelity"). No engine path yet certifies a template-based deployment's `data_sources$` in production.
7. **Failed-tx log semantics.** V4 uses `transactions()` (succeeded only) while Graph Node uses all receipts. Their equivalence rests on Firehose's empty-logs-for-reverted-tx behaviour (unverified). Add a fixture assertion.

---

## 11. Reusable assets (paths)

- `V4/src/config.rs`: pinned-params parser pattern with exact-key refusal.
- `V4/build.rs`: event-filtered Abigen from deployed ABIs.
- `V4/src/extract.rs`: identity envelope, explicit order sort, fixture-driven tests.
- `V4/src/metadata.rs`: batched per-block `eth_call` with count check and ERC-20 fallback decoding.
- `V4/proto/events.proto`: envelope schema template.
- `V4/store-tick-shards/src/lib.rs` + `V4/store-probe/src/lib.rs:223-366`: deterministic sharding, partitioned assembler, and order-preserving reassembly with assertions.
- `V4/store-probe/src/decimal.rs`: Graph Node v0.44 Decimal128 in WASM (`bigdecimal 0.1.2`).
- `V4/scripts/test-store-cache-boundary.sh`, `verify-release-packages.sh`, `verify-store-state-package.sh`, `packages/*.json`: cache-boundary and release-lock patterns, to be ported to `cargo xtask` in `SB/`.
- `V4/.github/workflows/release.yml`, `parity.yml`: tag-gated immutable release with a pinned CLI sha256.
- `ENGINE/scripts/download-uniswap-v4-spkg.sh`, `verify-spkg-compatibility.sh`, `adapters/uniswap-v4-base/compatibility.json`: consumer pinning pattern.
- `ENGINE/cmd/substreams-native` (`clock-v1`, `--include-empty-frames`): production-mode framed transport.
- `SB/mapping-host/` (cassette schema, BlockChanges producer, Firehose live source) and `SB/common/proto/block_changes.proto`: the generic path.
- `SB/aerodrome-slipstream-base/reference/*` + `layout-profile-v1.json`: pinned Aerodrome closure and static call and handler inventory.
- `GN:` bare repo at `~/.cargo/git/db/graph-node-40979021f9daae1a` (`git show 77823b5a:<path>`): authoritative Graph Node v0.44 semantics without a checkout.
