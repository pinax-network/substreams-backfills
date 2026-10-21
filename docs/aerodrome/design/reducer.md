# Aerodrome Slipstream Base reducer: design

Date: 2026-10-20. Read-only design pass. Nothing was committed, pushed, or commented, and nothing was written outside the scratchpad.

Target: deployment `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` on Base.
- Factory `0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a`, starting at block 13,843,704.
- NonfungiblePositionManager (NPM) `0x827922686190790b37229fd06084350e74485b72`, starting at block 13,843,719.
- Spec 1.2.0 (Fast PoI), apiVersion 0.0.7, `nonFatalErrors`, a `Pool` template, no graft.

Scope: the native Rust reducer that runs in sequence. It consumes the Substreams extractor output and emits canonical `pinax.graph.backfill.v1.BlockChanges` in BCF1 clock-v1 frames. Decision D3 fixes its place: a crate in `substreams-backfills`, behind the BlockChanges boundary.

## Evidence labels

- **VERIFIED**: I read the code or bytes during this pass, or ran the probe myself (Appendix A).
- **REPORT-VERIFIED**: a survey report verified it, cited by section.
- **ASSUMED**: a design assumption. Each one names the check that settles it.
- **OPEN**: needs access or a measurement nobody has done yet.

## Path abbreviations

- `SB/` = `/Users/denis/Github/substreams-backfills` at `bbe3783`.
- `ENG/` = `scratchpad/ro/engine` (engine `5c98b57`).
- `GN:` = graph-node `77823b5a` (v0.44.0), read with `git -C ~/.cargo/git/db/graph-node-40979021f9daae1a show 77823b5a:<path>`.
- `D:Pool` = `scratchpad/aero-wasm/Pool.annot.dcmp`, `D:Factory` = `…/Factory.dcmp`, `D:NPM` = `…/NPM.annot.dcmp`. Line numbers are stable for the retained WASM bytes.
- `ALLOY:` = `~/.cargo/registry/src/index.crates.io-*/alloy-*` at the versions that `SB/mapping-host/Cargo.lock` pins.
- `TARGET` = `scratchpad/survey/aerodrome-target.md`. `SYN` = `scratchpad/survey/SYNTHESIS.md`.

---

## 0. Decisions on one page

1. **Two new crates in the root workspace.**
   - `crates/graph-numerics` (Graph Node v0.44 BigDecimal/BigInt semantics). It is a provenance-pinned port of `ENG/src/decimal.rs` and part of `ENG/src/math.rs`, extended with what the engine lacks (§5). The engine can later vendor it the way it already vendors `backfill-common`.
   - `crates/aerodrome-slipstream-reducer` (lib, plus binary `aerodrome-reducer`).
   - A third small change: the family-neutral `BlockOpsBuilder` moves out of `mapping-host` into `backfill-common`, so both producers share one implementation of materialized/disposition/redaction (§11.4).
2. **Input.** BCF1 clock-v1 frames from `substreams-native`. Each payload is one `pinax.aerodrome.slipstream.base.v1.ExtractorBlock` per block. It is never empty because the header is always set.
   - It carries **raw** candidate logs (topics and data) and the transactions they belong to.
   - It carries **typed** call answers derived from storage (C5–C9), plus **raw** ERC20 return bytes (C1–C4).
   - The reducer is authoritative for matching, host set, wave validation, ABI decoding and every mapping fallback (§4).
3. **Output.** BCF1 clock-v1 frames of canonical BlockChanges v1. The contract is unchanged. Policy is `NON_FATAL`, region `ethereum/base`. Pool-template creations are emitted as `pinax.graph.backfill.data-sources/v2` creations, with a *seeded-genesis* extension requested from the engine design (§12).
4. **Porting rule.** Reproduce AssemblyScript object lifetimes exactly.
   - Every `X.load(id)` in the decompile becomes `ctx.load::<X>(id)`, which returns an **owned copy** of the get-visible entity.
   - Every `.save()` becomes `ctx.save(&x)`. It emits exactly one `SetEntity` with `written_fields` equal to the AS field map at that moment, and updates a block overlay.
   - Read-after-save, stale-copy and "store.get sees only saved state" quirks then fall out of the code structure. They are not special cases.
5. **Numerics.**
   - Every host op is normalized twice (n∘n). `BigInt.toBigDecimal()` values and DB loads are normalized once (n).
   - Negative values may carry 35 significant digits, which depends on the Phase-0 BlockChanges fix.
   - ABI decodes use `alloy-dyn-abi =1.7.2`, Graph Node's own decoder.
   - `Transaction.gasPrice` uses Graph Node's per-type effective-gas-price formula, VERIFIED (§5.6).
6. **Errors.** No deterministic error can be reached from valid inputs (catalog in §11.6). The default mode is **FailClosed**: any abort stops the run with a diagnostic. **EmitNonFatal** mode reproduces Graph Node's non-fatal dispositions for completeness.
7. **State is bounded by class.**
   - *hot*: Factory, Bundle, Token, Pool.
   - *tiered*: Tick and Position, held in an LRU backed by `redb`.
   - *period-local*: day and hour rows.
   - *block-local*: Transaction, Swap, Mint, Burn, PositionSnapshot.
   - Positions are never dropped. Burned ones are demoted to cold storage.
8. **Seed.** A `graph-node-seed/v1` artifact captured at `S = B−1`, shared with the engine design. For oracle windows, a lazy read-through Postgres backend reads `block_range @> S` on demand (§13.6).
9. **Gates.**
   - G1: numerics corpus generated by graph-node itself.
   - G2: frame-for-frame equality with the mapping-host on root windows.
   - G3: time-travel SQL differential against `sgd2`.
   - G4: PoI equality.
   - G5: chunked run equals uninterrupted run.
   - G6: throughput and RSS.
   - G7: zero aborts across the full range.
10. **Plan.** Twelve PR slices, about 52–68 engineer-days to a certified candidate (§15). This is consistent with SYN's 5–8 weeks.

---

## 1. Inputs read, and probes run during this pass

**Read in full or in the relevant sections:**
- SYN.
- TARGET.
- `engine-contract.md`.
- The engine audit (`tasks/wathbfgwg.output`, 31 kept findings). These matter most here:
  - state-semantics F1: 35-digit negatives.
  - F2: Null stripping on insert.
  - F3: NUL removal.
  - GEN-3: in-memory generic store.
  - GEN-4: no non-fatal error writer.
- The decompiles of all three mappings: handler bodies, interval updaters, pricing, tick helpers, NPM helpers. Line ranges are cited in §8.
- The upstream `Uniswap/v3-subgraph@c63cb39` sources.
- `SB/common` (proto, validator, dynamic-sources v1/v2).
- `SB/mapping-host` (README, `runner.rs`, `block.rs`, `blockchanges.rs`).
- `ENG/src/decimal.rs`, `ENG/src/math.rs`.
- Graph Node source: `bigdecimal.rs`, `host_exports.rs`, `to_from/{mod,external}.rs`, `codec.rs`, `trigger.rs`, `data_source.rs`, `ethereum_adapter.rs`, `relational_queries.rs`, gas costs.
- alloy 1.7.2 / 2.4.1 decode and gas-price code.

**Read-only probes.** Base RPC `https://base.rpc.pinax.network/` and VictoriaMetrics `P4169E866C3094E38`. Commands are in Appendix A.

| # | Probe | Result | Label |
|---|---|---|---|
| P1 | `CLFactory.tickSpacings()` at 34,700,000 and at latest | `[1, 50, 100, 200, 2000, 10]` at both heights. Answers SYN O9. | VERIFIED |
| P2 | `allPoolsLength()` | 1,490 at 34,700,000; 3,660 at head (about 52.87M) | VERIFIED |
| P3 | NPM `totalSupply()` and latest minted tokenId | Live supply 1,178,026 at 34.7M and 25,721,261 at head. Max minted tokenId ≈ 23,616,555 at 34.7M and 79,175,226 at head. | VERIFIED |
| P4 | `ticks(int24)`, `positions(uint256)` | `ticks` returns 320 bytes (10 words). `positions(1)` reverts with `"ID"`. A live position returns 12 words, with uint256 `feeGrowthInside*` near 2^256. | VERIFIED |
| P5 | `eth_getCode` of the hot-fix pools `0x8fe8…`, `0x9663…` | `0x` (no code on Base), so every hot-fix guard is inert | VERIFIED |
| P6 | Receipt of the first `PoolCreated` tx `0x76aecc…` (block 13,899,663) | Logs: Initialize@171 < PoolCreated@172 < Mint@176 < NPM Transfer@177 < IncreaseLiquidity@178. Type-2 tx. | VERIFIED |
| P7 | `pg_stat_user_tables_n_live_tup{schemaname="sgd2"}` | `data_sources$` 1,502. Version counts: position 61.4M, tick 91.9M, pool 99.0M, token 109.9M | VERIFIED |
| P8 | Slipstream source `ce33300ac4` | `getPool` is a public mapping, set in both token orders. `feeGrowthGlobal0X128` is a public variable and `ticks` a public mapping. `positions` does `require(poolId != 0, "ID")`. | VERIFIED |

---

## 2. Where the reducer sits

```
Base Firehose (extended blocks)
  │
  ▼  Substreams extractor  map_events  (parallel; cache warmed by the noop workflow)
  │     one ExtractorBlock per block: header + candidate logs + txs + call answers
  ▼  substreams-native  --output-format clock-v1  (raw payload relay)
  │
  ▼  aerodrome-reducer run   ◄── seed (graph-node-seed/v1) or root
  │     sequential; Graph Node handler semantics; bounded state
  ├──► blocks.bcf1          canonical BlockChanges v1, one Observed frame per block
  ├──► data-sources chunk   pinax.graph.backfill.data-sources/v2 creations
  └──► reducer checkpoint   pinax.aerodrome-slipstream.reducer-checkpoint/v1
  │
  ▼  engine state-replay --input-format block-changes-v1-framed  →  spool  →  loader (stopped clone)

Oracles
  mapping-host (deployed WASM, Graph Node v0.44 runtime) ── same BlockChanges contract ──► G2 frame equality
  sgd2 time-travel SQL (block_range @> S) ──────────────────────────────────────────────► G3 row equality
```

---

## 3. Crate layout

### 3.1 `crates/graph-numerics` (new, shared, family-neutral)

```
crates/graph-numerics/
  Cargo.toml
  src/lib.rs           re-exports
  src/decimal.rs       GraphDecimal (port of ENG/src/decimal.rs:1-210, provenance header)
  src/bigint.rs        GraphBigInt helpers (div/mod truncation, 435,412-bit guard, to_i32 with overflow)
  src/wire.rs          GraphDecimal/BigInt <-> pinax.graph.backfill.v1 BigDecimalValue/BigIntValue
  src/mapping.rs       exponent_to_big_decimal, convert_token_to_decimal, safe_div,
                       sqrt_price_x96_to_token_prices (port of ENG/src/math.rs:7-47)
  src/string.rs        graph_store_string (strip all U+0000), bytes_to_string (lossy + trim trailing NUL)
  tests/corpus.rs      replays fixtures/graph-node-v0.44-numerics.jsonl
  tests/properties.rs  idempotence, wire round-trip, validator acceptance
  fixtures/graph-node-v0.44-numerics.jsonl   generated by mapping-host (links real graph), see §14.1
```

Dependencies:
- `graph-bigdecimal = { package = "bigdecimal", version = "=0.1.2" }` and `graph-num-bigint = { package = "num-bigint", version = "=0.2.6" }`. These are exactly the engine pins (`ENG/Cargo.toml`) and Graph Node's `old_bigdecimal`.
- `num-bigint` 0.4 (workspace), `num-traits`, `backfill-common` (for the `pb` wire types).

**Decision: port, do not depend on the engine.**
- The engine crate drags in arrow, parquet and stable-hash.
- `substreams-backfills` is already the upstream for shared contracts the engine vendors (`ENG/third_party/backfill-common`).
- Putting the numeric model upstream gives one source of truth. The engine can vendor `graph-numerics` the same way.
- `backfill-common` itself is not used for this. That would add bigdecimal 0.1.2 and num-bigint 0.2 to a crate meant to stay small and wasm-friendly.

### 3.2 `crates/aerodrome-slipstream-reducer` (new)

```
crates/aerodrome-slipstream-reducer/
  Cargo.toml
  build.rs                          prost-build for proto/ (input contract, consumer copy)
  proto/pinax/aerodrome/slipstream/base/v1/extractor.proto   (sha256-pinned copy of the extractor's proto)
  reference -> ../../aerodrome-slipstream-base/reference      (read at build/test time via include_bytes!; ABIs, schema, manifest)
  src/
    lib.rs
    constants.rs                    every WASM constant, with data-segment address provenance (§9 table K)
    error.rs                        ReducerError (fatal, infra/contract) vs Abort (mapping-level, deterministic)
    input/
      frame.rs                      BCF1 clock-v1 reader/writer (both directions), contiguity + parent-hash linkage
      block.rs                      ExtractorBlock -> BlockInput; validation rules §4.3
      decode.rs                     log decode via alloy-dyn-abi =1.7.2 + reference ABI events (Graph Node match rule)
      tx.rs                         graph_gas_price(): Graph Node v0.44 effective gas price per tx type (§5.6)
    calls/
      book.rs                       CallBook: fail-closed lookup by (kind, address, args) for this block
      erc20.rs                      fetch_token_{symbol,name,total_supply,decimals} on raw retvals (alloy decode)
    entity/
      mod.rs                        Entity trait, Presence<T>, FieldDef, EntityImage = Vec<pb::EntityField>
      macros.rs                     graph_entity! macro (typed struct + sorted field table + to/from fields)
      schema.rs                     the 20 declarations (§6)
    store/
      overlay.rs                    BlockOverlay (in-block get-visible images) + HandlerJournal (non-fatal rollback)
      state.rs                      PersistentState: hot maps + tiered stores + period maps
      tiered.rs                     TieredStore<E>: LRU + redb cold tier (Tick, Position)
      backend_mem.rs                MemoryBackend (tests, root windows)
      backend_redb.rs               RedbBackend (production)
      backend_pg.rs   [feature pg-oracle]  lazy read-through of a Graph Node schema at block S (§13.6)
    emit/
      ops.rs                        thin adapter over backfill_common::block_ops::BlockOpsBuilder
      seal.rs                       canonical encode + validate + BCF1 write
    mapping/
      ctx.rs                        HandlerCtx (load/save/calls/create_data_source), §7
      util.rs                       load_transaction, convert_token_to_decimal, exponent_to_big_decimal, ids
      factory.rs                    handle_pool_created + token metadata
      pool.rs                       handle_initialize/mint/burn/swap/flash
      pricing.rs                    get_eth_price_in_usd, find_eth_per_token, tracked_amount_usd, sqrt prices
      interval.rs                   update_{uniswap_day,pool_day,pool_hour,token_day,token_hour,tick_day}_data
      tick.rs                       create_tick, TickPowTable, update_tick_fee_vars_and_save, load_tick_update…, fee tables
      npm.rs                        get_position, update_fee_vars, save_position_snapshot, 4 handlers
    runner.rs                       per-block driver: host set, waves, handler groups, abort policy, frame build
    sources.rs                      data-source creations + v2 companion writer (+ seeded-genesis variant)
    checkpoint.rs                   checkpoint manifest, state digest, export/import (§13.4)
    seed.rs                         graph-node-seed/v1 import (§13.5)
    descriptor.rs                   compatibility descriptor builder (§11.7)
    report.rs                       per-block JSONL counters (handlers, ops, calls, evictions)
    reference_extractor.rs [feature reference-extractor]  Firehose block + mapping-host cassette -> ExtractorBlock (§4.4)
  src/bin/aerodrome-reducer.rs      CLI (§3.3)
  tests/reducer/main.rs             ONE test binary (mapping-host lesson: per-file test binaries blow up the linker)
    mod numerics; mod entity_schema; mod handlers; mod frames; mod oracle_frames; mod state; mod checkpoint; mod seed;
  fixtures/                         §14.5
```

Dependencies, all pinned:
- `backfill-common` (path)
- `graph-numerics` (path)
- `prost = "=0.13.5"`. The validator re-encodes with 0.13.5, so the producer must match.
- `alloy-dyn-abi = "=1.7.2"`, `alloy-json-abi = "=1.7.2"`, `alloy-primitives = "=1.7.2"`. These are the versions in `SB/mapping-host/Cargo.lock`, i.e. Graph Node v0.44's own decoder.
- `num-bigint`, `num-traits`, `sha2`, `hex`, `serde`, `serde_json`, `lru`, `redb` (exact pin, chosen in slice R8)
- `zstd` (optional, export only)
- Optional `postgres` (`pg-oracle` feature)

The root `Cargo.toml` `members` gains both crates. That is Rust only, in line with the policy. Tooling goes in `cargo xtask aerodrome …` (§3.3).

### 3.3 CLI and xtask surface

```
aerodrome-reducer run
    --descriptor PATH                 (+ PATH.sha256 sidecar)
    --extractor-lock PATH             JSON: spkg_sha256, module, module_hash, output_type
    --state-dir DIR                   redb + checkpoints
    (--root | --seed SEED.ready | --checkpoint CKPT_MANIFEST)
    --from N --to M                   inclusive; must equal checkpoint/seed boundary + 1
    --input PATH|-                    BCF1 clock-v1 extractor frames
    --output PATH|-                   BCF1 clock-v1 BlockChanges frames
    --sources-out DIR                 data-sources companion chunk(s) (≤10,000 blocks each)
    --checkpoint-every BLOCKS         default 100,000; aligned to engine segments
    --error-mode fail-closed|emit-non-fatal   (default fail-closed)
    --report PATH                     JSONL counters
aerodrome-reducer seed-import   --seed SEED.ready --state-dir DIR
aerodrome-reducer checkpoint    verify|digest|export --state-dir DIR [--out FILE]
aerodrome-reducer descriptor    build --reference DIR --extractor-lock PATH --out PATH
aerodrome-reducer diff-frames   A.bcf1 B.bcf1 [--mask compatibility_id] [--first-only]

cargo xtask aerodrome seed-capture  --pg-url URL --schema sgdN --block S --profile PROFILE --out SEED.ready   (read-only)
cargo xtask aerodrome timetravel-diff --pg-url URL --schema sgdN --from B --to B+N --frames OUT.bcf1         (read-only; §14.3)
cargo xtask aerodrome fixtures fetch|check                                                                   (content-addressed)
```

---

## 4. Input contract (what the reducer consumes)

This is the reducer-side contract. The extractor design (`design/extractor.md`, written by another agent) must match it field for field. The proto below is the reducer's proposal and must be reconciled before the extractor freezes. Principle: the extractor emits **facts**, and the reducer applies every **Graph Node semantic**.

### 4.1 Proto (full field lists)

```proto
syntax = "proto3";
package pinax.aerodrome.slipstream.base.v1;

// Exactly one per block in the requested range. Never empty: number/hash/timestamp are always set,
// so Substreams production mode always delivers it and substreams-native emits an Observed frame.
message ExtractorBlock {
  uint64 number = 1;
  bytes  hash = 2;                       // 32 bytes; must equal the BCF1 envelope hash
  bytes  parent_hash = 3;                // 32 bytes; reducer checks linkage
  uint64 timestamp = 4;                  // seconds (header.timestamp)
  optional uint64 base_fee_per_gas = 5;  // header.base_fee_per_gas as u64 (Graph Node truncates U256->u64)
  uint32 receipt_log_count = 6;          // number of logs over all receipts (bound for source_trigger_order)
  repeated Transaction transactions = 7; // only txs referenced by candidates; sorted by index; unique
  repeated CandidateLog candidates = 8;  // see §4.2; sorted by (wave, source_trigger_order)
  CallAnswers calls = 9;
  repeated PoolCreatedFact pools_created = 10; // every Factory PoolCreated log in this block (cross-check)
}

message Transaction {
  bytes  hash = 1;                       // 32
  uint32 index = 2;
  bytes  from = 3;                       // 20
  uint64 gas_limit = 4;                  // trace.gas_limit
  uint32 type = 5;                       // trace.type (0,1,2,3,4,126=OP deposit, …)
  optional bytes gas_price = 6;          // trace.gas_price, unsigned BE minimal; absent if unset
  optional bytes max_fee_per_gas = 7;    // trace.max_fee_per_gas; ABSENCE matters (§5.6)
  optional bytes max_priority_fee_per_gas = 8;
}

message CandidateLog {
  uint32 wave = 1;                       // 0: emitter is Factory, NPM, or a pool host existing at block start
                                         // 1: emitter is a pool created by a PoolCreated in THIS block
  uint32 source_trigger_order = 2;       // rank of this log among ALL receipt logs of the block sorted by block_index
                                         // (= Graph Node's sorted trigger index, GN: chain/ethereum/src/trigger.rs:381-382)
  uint32 log_index = 3;                  // Firehose log.block_index (= Graph Node event.logIndex, GN: codec.rs:124)
  uint32 tx = 4;                         // index into ExtractorBlock.transactions
  bytes  address = 5;                    // 20
  repeated bytes topics = 6;             // raw 32-byte topics
  bytes  data = 7;                       // raw log data
}

message CallAnswers {
  repeated Erc20Answer erc20 = 1;                 // C1–C4 (raw; eth_call at block hash)
  repeated FeeGrowthGlobalAnswer fee_growth = 2;  // C5 (storage-derived end-of-block)
  repeated TickAnswer ticks = 3;                  // C6/C7 (storage-derived end-of-block)
  repeated PositionAnswer positions = 4;          // C8 (storage-derived end-of-block)
  repeated GetPoolAnswer get_pool = 5;            // C9 (from the Factory PoolCreated store, post-block)
}

// Graph Node Retval: Null = revert OR empty "0x" (GN: chain/ethereum/src/ethereum_adapter.rs:1550-1566).
message RawRetval {
  oneof kind {
    Null reverted = 1;
    bytes value = 2;                     // raw ABI return bytes, never empty
  }
  message Null {}
}

// symbol():(string) and symbol():(bytes32) have identical calldata (0x95d89b41), so one retval serves
// both decodes (Graph Node's call cache key is (block hash, address, calldata)). Same for name().
message Erc20Answer {
  bytes token = 1;                       // 20
  RawRetval symbol = 2;                  // 0x95d89b41
  RawRetval name = 3;                    // 0x06fdde03
  RawRetval total_supply = 4;            // 0x18160ddd
  RawRetval decimals = 5;                // 0x313ce567
}

message FeeGrowthGlobalAnswer {
  bytes pool = 1;                        // 20
  bytes fee_growth_global0_x128 = 2;     // 32 bytes BE (uint256)
  bytes fee_growth_global1_x128 = 3;     // 32 bytes BE
}

// Only the two words the mapping consumes (value2, value3 of the 10-tuple, D:Pool:5398-5438).
message TickAnswer {
  bytes  pool = 1;
  sint32 tick = 2;
  bytes  staked_liquidity_net = 3;       // int128 as 16-byte two's-complement BE (value2)
  bytes  fee_growth_outside0_x128 = 4;   // 32 bytes BE (value3)
}

message PositionAnswer {
  bytes token_id = 1;                    // uint256 BE minimal
  oneof result {
    RawRetval.Null reverted = 2;         // NPM require(poolId != 0, "ID") at end of block
    PositionValue value = 3;
  }
}
message PositionValue {                  // value2..value9 of the 12-tuple (D:NPM:2114-2560, 2703-2746)
  bytes  token0 = 1;                     // 20
  bytes  token1 = 2;                     // 20
  sint32 tick_spacing = 3;               // int24
  sint32 tick_lower = 4;
  sint32 tick_upper = 5;
  bytes  fee_growth_inside0_last_x128 = 6;   // 32 bytes BE (uint256, may be ≈2^256)
  bytes  fee_growth_inside1_last_x128 = 7;
}

message GetPoolAnswer {
  bytes  token_a = 1;
  bytes  token_b = 2;
  sint32 tick_spacing = 3;
  bytes  pool = 4;                       // 20; zero address when no pool (never reverts, P8)
}

message PoolCreatedFact {                // Factory PoolCreated logs, in log order
  bytes  pool = 1;
  bytes  token0 = 2;
  bytes  token1 = 3;
  sint32 tick_spacing = 4;
  uint32 log_index = 5;
}
```

**Deliberately absent:** C10, the four `getPool(USDC, token, {100,500,3000,10000})` calls in `addMissingWhitelistedPools`.
- Their results are pushed into a getter copy and lost (D:Pool:6737-6810). VERIFIED: there is no `whitelistPools` setter in Pool.wasm (TARGET §5.3).
- `getPool` is a public mapping getter that cannot revert (P8). The non-try call therefore never aborts.
- The reducer needs no answers for these calls, and the extractor need not produce them.
- This simplifies SYN Q2/C10 (VERIFIED).

### 4.2 What a "candidate" is, and why the reducer re-matches

The extractor emits a log as a candidate when all of the following hold:
- the emitter is the Factory with topic0 `PoolCreated` and block ≥ 13,843,704; or the NPM with topic0 in {IncreaseLiquidity, DecreaseLiquidity, Collect, Transfer} and block ≥ 13,843,719; or a pool address in the extractor's pool set with topic0 in {Initialize, Swap, Mint, Burn, Flash};
- the log comes from a receipt in this block (Graph Node takes logs from `receipt.logs`, GN: `codec.rs:676-680`).

Graph Node's match rule is: address filter, then `start_block > block` → no match, then **ABI decode failure → no match** (GN: `chain/ethereum/src/data_source.rs:690-760`). The reducer applies that rule itself:
- decode with the reference ABI event via `alloy-dyn-abi =1.7.2`;
- treat a decode failure as "not a trigger": no handler group and no PoI region.

The reducer's **own host set** is authoritative. It holds pools created by *successful* `handlePoolCreated` runs plus seeded `data_sources$`.

| Case | FailClosed | EmitNonFatal |
|---|---|---|
| Pool candidate whose address is not in the reducer's host set | `ReducerError::UnknownPoolHost` | dropped as "not matched" |
| Wave-1 candidate whose pool was not created in this block by a successful wave-0 handler | refused | refused |

### 4.3 Validation (all fail closed → `ReducerError`)

1. Frame envelope: kind Observed. In production a Synthetic frame is refused, because companions require Observed frames (`engine-contract.md` §2.1).
2. `number` and `hash` equal the envelope. `parent_hash` equals the previous frame's hash. Block numbers are contiguous from the boundary.
3. `candidates` are sorted by `(wave, source_trigger_order)`. Within a wave, `source_trigger_order` strictly increases and is less than `receipt_log_count`. `wave ∈ {0,1}`. A wave-1 address appears in `pools_created` of this block.
4. Every `tx` index is in range, and `transactions` are unique by hash.
5. Missing call answer when a handler asks → `ReducerError::MissingCallAnswer{kind,key,block}`. Never a revert ("under-fetching is fatal", SYN §7.4). Unused answers are counted in the report and are not an error.
6. `pools_created` must equal the PoolCreated candidates that decode successfully (same order).

### 4.4 Reference extractor (test-only, unblocks the reducer before the Substreams extractor exists)

`reference_extractor.rs` is behind the `reference-extractor` feature and uses the `sf.ethereum.type.v2` prost bindings. It builds `ExtractorBlock` from inputs the mapping-host oracle already uses:
- a Firehose block fixture;
- the mapping-host `eth_call` cassette for the same window;
- the reducer's current host set.

The ticks/positions/feeGrowth retvals in the cassette are decoded into the typed answers above. The tuple layout is from TARGET §3 (VERIFIED: 320-byte ticks, 12-word positions).

This has two uses:
- (a) the reducer can be driven on real Base blocks against the mapping-host before PR-S1 lands;
- (b) later it becomes the **extractor gate**: on every oracle window, the real extractor output must equal the reference extractor output, ignoring superset answers.

---

## 5. Numeric and value semantics

### 5.1 BigDecimal model (VERIFIED)

Graph Node's `BigDecimal` is `bigdecimal 0.1.2` normalized with `with_prec(34)`, followed by trailing-zero stripping (GN: `graph/src/data/store/scalar/bigdecimal.rs`, `normalized()`). Normalization happens at these points:
- **host op**: `big_decimal_{plus,minus,times,divided_by}` return `Self::from(op)`, which is normalized (GN: `host_exports.rs:883-952`).
- **ABI crossing AS→host**: `FromAscObj<AscBigDecimal>` calls `BigDecimal::new(digits, exp)`, which normalizes again, then validates the exponent range (GN: `runtime/wasm/src/to_from/external.rs:105-135`).

So a host op result that is used again, or stored, is n∘n(op). A value made in AS by `BigInt.toBigDecimal()` crosses once and is n(raw).

`n` is not idempotent for negatives. bigdecimal 0.1.2 undercounts digits of negative coefficients, so up to 35 digits survive and rounding truncates (audit state-semantics F1, confirmed with a 35-digit production V4 value at `ENG/src/decimal.rs:200-209`). n∘n is a fixed point of n (audit F1 probe on 5,000 negatives; re-checked by property test P-2 in §14.1).

Division by zero is a deterministic host error, "attempted to divide BigDecimal … by zero" (GN: `host_exports.rs:943-948`). It is unreachable in these mappings (§11.6).

### 5.2 `graph-numerics` API (signatures)

```rust
/// Graph Node v0.44 BigDecimal as seen by the host after an ABI crossing.
#[derive(Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct GraphDecimal(graph_bigdecimal::BigDecimal);

impl GraphDecimal {
    pub fn zero() -> Self;                                     // canonical 0
    pub fn one() -> Self;
    /// `BigInt.toBigDecimal()` (AS-native, unnormalized) observed at its first crossing: n(raw).
    pub fn from_bigint(v: &num_bigint::BigInt) -> Self;
    /// `BigDecimal.fromString(s)` used afterwards: host returns n(parse), crossing adds n -> n∘n.
    pub fn host_from_string(s: &str) -> Result<Self, DecimalError>;
    /// A Postgres numeric loaded by Graph Node (`from_column_value` → `BigDecimal::from_str`): n.
    pub fn from_db_text(s: &str) -> Result<Self, DecimalError>;
    /// Host ops: n∘n. Division by zero returns Abort-able error (never panics).
    pub fn plus(&self, o: &Self) -> Self;
    pub fn minus(&self, o: &Self) -> Self;
    pub fn times(&self, o: &Self) -> Self;
    pub fn divided_by(&self, o: &Self) -> Result<Self, DecimalError /*DivideByZero*/>;
    /// graph-ts `BigDecimal.compare` = sign(minus(a,b)): identical to numeric Ord of the normalized inputs.
    pub fn compare(&self, o: &Self) -> std::cmp::Ordering;
    pub fn is_zero(&self) -> bool;
    pub fn exponent_in_range(&self) -> bool;                   // [-6143, 6144] check of FromAscObj
    pub fn to_wire(&self) -> pb::BigDecimalValue;              // (coefficient signed BE minimal, empty for 0; scale)
    pub fn from_wire(v: &pb::BigDecimalValue) -> Result<Self, DecimalError>; // n (mirror of ENG from_signed_coefficient)
}

pub mod bigint {
    pub fn to_wire(v: &BigInt) -> pb::BigIntValue;             // minimal two's complement BE, empty for 0
    pub fn from_wire(v: &pb::BigIntValue) -> BigInt;
    pub fn graph_div(a: &BigInt, b: &BigInt) -> Result<BigInt, Abort>;  // truncation; b==0 -> Abort
    pub fn graph_mod(a: &BigInt, b: &BigInt) -> Result<BigInt, Abort>;  // remainder sign follows dividend
    pub fn to_i32_checked(v: &BigInt) -> Result<i32, Abort>;            // "overflow converting … to i32"
    pub fn check_bits(v: &BigInt) -> Result<(), Abort>;                 // 435,412-bit Graph Node limit
}

pub mod mapping {
    /// Aerodrome Pool/NPM `exponentToBigDecimal`: fromString("1") then n times `.times(fromString("10"))`
    /// (D:Pool:3676-3693, D:NPM:2618-2652) == 1E+n exactly (positive powers of ten are exact under n∘n).
    pub fn exponent_to_big_decimal(decimals: &BigInt) -> GraphDecimal;
    /// D:Pool:3704-3716: decimals == 0 -> from_bigint(amount) (single n!), else from_bigint(amount) / 10^d.
    pub fn convert_token_to_decimal(amount: &BigInt, decimals: &BigInt) -> GraphDecimal;
    pub fn safe_div(a: &GraphDecimal, b: &GraphDecimal) -> GraphDecimal; // compare(b,0)!=0 ? a/b : ZERO
    /// D:Pool:7655-7700: price1 = ((from_bigint(s*s) / Q192) * 10^d0) / 10^d1; price0 = safe_div(ONE, price1)
    pub fn sqrt_price_x96_to_token_prices(sqrt: &BigInt, d0: &BigInt, d1: &BigInt) -> (GraphDecimal, GraphDecimal);
}

pub mod string {
    pub fn graph_store_string(s: &str) -> String;     // FromAscObj<AscString>: replace all U+0000 (GN: to_from/mod.rs:109-124)
    pub fn bytes_to_string(b: &[u8]) -> String;       // lossy UTF-8 + trim trailing U+0000 (GN: host_exports.rs:1273-1290)
}
```

**Gaps relative to the engine `GraphDecimal`.**
- The engine's `FromStr` normalizes once. Graph Node's `fromString` result is normalized twice.
- That changes nothing for the mapping constants (`"0"`, `"1"`, `"-1"`, `"2"`, `"10"`, `"1000000"`, `"0.01"`, `"1.0001"` are all short).
- Even so, `host_from_string` is exact, and `from_db_text` is kept distinct for the seed.

**Q192.** `BigInt.pow(2,192).toBigDecimal()` is raw in AS. When it first crosses, it is rounded to 34 significant digits: `6.277101735386680763835789423207666E+57`. TARGET §7 calls Q192 "exact", but that holds only on the AS side. The host sees the rounded value, and `from_bigint(2^192)` reproduces exactly that (VERIFIED by reading `from_asc_obj`).

### 5.3 BigInt

- Graph Node BigInt ops are exact.
- `div` truncates and `mod` follows the sign of the dividend (num-bigint semantics; GN: `host_exports.rs:724-768`).
- The AS `BigInt.compare` used everywhere is AS-native byte comparison, equal to numeric order.
- The 435,412-bit limit is unreachable here (inputs are at most 256-bit; `sqrt²` is at most 320 bits).
- `toI32` aborts on overflow. Only int24 ticks and i32 timestamps reach it, so it is unreachable before 2038.

### 5.4 The iterative tick price

`createTick` computes `price0 = 1.0001^tick` with an O(|tick|) loop of host multiplications (D:Pool:4113-4190):
- `b₁ = 0 + 1.0001` (plus);
- `b_k = b_{k−1} × 1.0001` (times), with each step n∘n;
- for a negative tick, `price0 = safeDiv(ONE_BD, b_|t|)`;
- `price1 = safeDiv(ONE_BD, price0)` (D:Pool:4194-4214).

`|tick|` can reach 887,272, so a naive port costs about 0.9M decimal multiplications per extreme tick.

The chain `b_k` does not depend on the pool, so:

```rust
/// Deterministic, lazily extended chain b_k; stores every 1,024th b_k (≈ 870 entries) and recomputes
/// ≤ 1,023 steps from the nearest checkpoint. Identical results to the naive loop by construction.
pub struct TickPowTable { checkpoints: Vec<GraphDecimal> /* b_0=1 (unused), b_1024, … */, max_k: u32 }
impl TickPowTable { pub fn b(&mut self, k: u32) -> GraphDecimal; }
pub fn bigdecimal_exponated_1_0001(power: i32, t: &mut TickPowTable) -> GraphDecimal; // ONE for 0
```

Graph Node gas cannot fire here, VERIFIED estimate:
- each loop step is about 3×10⁵ gas (`BIG_MATH_GAS_OP` base 100,000 + size + `HOST_EXPORT_GAS` 10,000, plus BigInt.plus);
- 2 × 887,272 steps ≈ 6×10¹¹;
- `GRAPH_MAX_GAS_PER_HANDLER` default is 10¹⁵ (GN: `graph/src/env/mod.rs:524`; `graph/src/runtime/gas/costs.rs:7-14,44-50`).

### 5.5 Strings and ABI decoding (VERIFIED)

- **Store strings.** Every string crossing AS→host is stripped of all U+0000 (GN: `runtime/wasm/src/to_from/mod.rs:116-123`). The reducer applies `graph_store_string` inside `Entity::to_fields` for every `String`/`ID` value. Only `Token.symbol` and `Token.name` can contain NUL (audit state-semantics F3).
- **`bytesToString(bytes32)`** is lossy UTF-8 plus trailing-NUL trim, then the store strips any remaining NULs.
- **`symbol():(string)` decode** uses alloy 1.7.2, where `String::from_utf8_lossy` is applied (ALLOY: `alloy-sol-types-1.7.2/src/types/data_type.rs:384-387`).
- **`uint8` decode** has **no range check** (ALLOY: `alloy-dyn-abi-1.7.2/src/dynamic/ty.rs:278-279`). `decimals()` returning 256 decodes to 256, and the mapping then maps that to 0 (§8.1).
- **Decode failure** counts as a revert. **Empty `0x`** counts as a revert (GN: `ethereum_adapter.rs:1550-1566`).
- The reducer calls `alloy_json_abi::Function::abi_decode_output` on the functions in `reference/abis/{ERC20,ERC20SymbolBytes,ERC20NameBytes}.json`, Graph Node's exact code path. It does not hand-decode.

### 5.6 Transaction gas price (VERIFIED, closes part of SYN Q2 and O6)

`event.transaction.gasPrice` = `EthereumTransactionData::gas_price()` = `tx.effective_gas_price(block.base_fee_per_gas)` (GN: `chain/ethereum/src/trigger.rs:556-558`). The tx is built from the Firehose trace in GN: `chain/ethereum/src/codec.rs:170-470`:

```rust
/// Graph Node v0.44 `Transaction.gasPrice` for a Firehose TransactionTrace.
pub fn graph_gas_price(tx: &Transaction, base_fee: Option<u64>) -> Result<u128, ReducerError> {
    let gas_price = tx.gas_price.as_ref().map_or(0, u256_to_u128_checked);          // codec.rs:177-180
    match tx.r#type {
        0 | 1 => Ok(gas_price),                                                     // Legacy/2930: gas_price
        2 | 3 | 4 => {                                                              // 1559/4844/7702
            let max_fee = tx.max_fee_per_gas.as_ref().map_or(gas_price, u256_to_u128_checked); // codec.rs:259-262
            let max_prio = tx.max_priority_fee_per_gas.as_ref().map_or(0, u256_to_u128_checked);
            Ok(match base_fee {                         // ALLOY: alloy-eips-2.4.1/src/eip1559/helpers.rs:14-29
                None => max_fee,
                Some(b) => { let tip = max_fee.saturating_sub(b as u128);
                             if tip > max_prio { max_prio + b as u128 } else { max_fee } }
            })
        }
        _ => Ok(gas_price),   // unknown types incl. 126 (OP deposit): UnknownTxEnvelope with "gasPrice"
                              // field = trace.gas_price → effective_gas_price returns it
                              // (codec.rs:198-247; ALLOY: alloy-network-2.4.1/src/any/unknowns.rs:163-177)
    }
}
```

- `Transaction.gasUsed` = `gas_limit` (quirk Q-T1).
- `Mint/Burn/Swap.origin` = `tx.from`.
- `logIndex` = Firehose `log.block_index` (GN: `codec.rs:124`).
- Fixture F-TX (§14.5) pins one transaction of each type against the mapping-host's `Transaction.gasPrice`.

---

## 6. Entity model (20 entities, 302 schema fields; 289 stored + 13 `@derivedFrom`)

These counts are VERIFIED by parsing `SB/aerodrome-slipstream-base/reference/schema.graphql`. They match `layout-profile-v1.json` (`entity_count 20`, `field_count 302`).

### 6.1 Declarations

Each entity is declared once with `graph_entity!`. The macro generates:
- a typed struct;
- `const TYPE: &str`;
- `const FIELDS: &[FieldDef]`, sorted by GraphQL name, with GraphQL type and nullability;
- `fn to_fields(&self) -> Vec<pb::EntityField>`, which is sorted, skips `Absent`, emits Null for `Presence::Null` and strips NUL from strings;
- `fn from_fields(&[pb::EntityField]) -> Result<Self, SchemaError>`, used by seed and checkpoint.

```rust
pub enum Presence<T> { Absent, Null, Set(T) }      // nullable fields only; mirrors the AS TypedMap entry

pub trait Entity: Clone {
    const TYPE: &'static str;
    const CLASS: EntityClass;                        // Hot | Tiered | PeriodDay | PeriodHour | BlockLocal | NeverWritten
    fn id(&self) -> &str;
    fn to_fields(&self) -> Vec<pb::EntityField>;
    fn from_fields(fields: &[pb::EntityField]) -> Result<Self, SchemaError>;
}

graph_entity! { Pool : Hot {
    id: Id, created_at_timestamp "createdAtTimestamp": BigInt, created_at_block_number "createdAtBlockNumber": BigInt,
    token0: Id, token1: Id, fee_tier "feeTier": BigInt, liquidity: BigInt, sqrt_price "sqrtPrice": BigInt,
    fee_growth_global0_x128 "feeGrowthGlobal0X128": BigInt, fee_growth_global1_x128 "feeGrowthGlobal1X128": BigInt,
    token0_price "token0Price": BigDecimal, token1_price "token1Price": BigDecimal, tick: ?BigInt,
    observation_index "observationIndex": BigInt, volume_token0 "volumeToken0": BigDecimal, … (29 stored fields)
} }
```

Values map as follows:
- `ID`/`String` → `String`.
- `BigInt` → `num_bigint::BigInt`.
- `BigDecimal` → `GraphDecimal`.
- `Bytes` → `Vec<u8>` (always 20-byte addresses here).
- `Int` → `i32`.
- `[Pool!]!` → `Vec<String>`.
- Relations (`Token!`, `Pool!`, `Tick!`, `Transaction!`, `Position!`) are stored as `String` IDs.

**Schema-conformance test** `entity_schema::matches_reference_schema`:
- parses `reference/schema.graphql` with `graphql-parser` (dev-dep);
- asserts that the macro tables equal the schema for every entity, field, type and nullability;
- asserts that the 13 derived fields are excluded;
- asserts that `Collect`, `Flash` and `TickHourData` are declared but carry `NeverWritten`. The emitter refuses any op targeting them.

### 6.2 The 20 entities

| Entity | Stored fields (nullable) | ID scheme (VERIFIED decompile) | `store.get` by mapping? | Class | Never-updated fields (stay at creation value) |
|---|---|---|---|---|---|
| Factory | 13 | constant `0x5e7bb104…809a` | yes | Hot (1 row) | `totalValueLockedUSDUntracked`, `totalValueLockedETHUntracked`; `owner="0x000…0"` (String) |
| Bundle | 2 | `"1"` | yes | Hot (1 row) | — |
| Token | 17 (`version?`) | token address hex | yes | Hot (≤ 2×pools; 3,660 pools at head, P2) | `poolCount=0`, `totalSupply`, `totalValueLockedUSDUntracked=0`, `symbol`, `name`, `decimals` |
| Pool | 29 (`tick?`) | pool address hex | yes | Hot (1,490 at 34.7M, 3,660 at head, P2) | `observationIndex`, `collectedFees*`, `liquidityProviderCount`, `totalValueLockedUSDUntracked`, `feeTier`, `createdAt*` |
| Tick | 21 (`poolAddress?`) | `"{poolHex}#{tickIdx}"` (i32 decimal) | yes (Mint/Burn/Swap walk) | Tiered (OPEN count, O8) | `volume*`, `untrackedVolumeUSD`, `feesUSD`, `collectedFees*`, `liquidityProviderCount`, `price0/1`, `createdAt*` |
| Position | 19 | `tokenId` decimal | yes | Tiered (≈23.6M ids at 34.7M, ≈79.2M at head; live 1.18M → 25.7M, P3) | `pool`, `token0/1`, `tickLower/Upper` |
| PositionSnapshot | 16 | `"{positionId}#{blockNumber}"` | **no** | BlockLocal | — |
| Transaction | 5 | tx hash hex | yes, same block only | BlockLocal | — |
| Mint | 16 (`sender?`, `amountUSD?`, `logIndex?`) | `"{txHash}#{pool.txCount}"` | **no** | BlockLocal | — |
| Burn | 15 (`owner?`, `amountUSD?`, `logIndex?`) | same | **no** | BlockLocal | — |
| Swap | 15 (`logIndex?`) | same | **no** | BlockLocal | — |
| Collect | 11 | — | — | NeverWritten | table stays empty |
| Flash | 12 | — | — | NeverWritten | table stays empty |
| UniswapDayData | 8 | `"{dayID}"` | yes | PeriodDay | `volumeUSDUntracked=0` |
| PoolDayData | 20 (`tick?`) | `"{poolHex}-{dayID}"` | yes | PeriodDay | `close` (Q-I2), `open` |
| PoolHourData | 20 (`tick?`) | `"{poolHex}-{hourIndex}"` | yes | PeriodHour | `open` |
| TickHourData | 10 | — | — | NeverWritten | table stays empty |
| TickDayData | 12 | `"{tickId}-{dayID}"` | yes | PeriodDay | `volumeToken1` copies `tick.volumeToken0` (Q-I4) |
| TokenDayData | 14 | `"{tokenId}-{dayID}"` | yes | PeriodDay | `open` |
| TokenHourData | 14 | `"{tokenId}-{hourIndex}"` | yes | PeriodHour | `open` |

`dayID = timestamp.toI32() / 86400` and `hourIndex = timestamp.toI32() / 3600`, using i32 division (D:Pool:2617-2630, 2972-2985). The interval rows store `date`/`periodStartUnix` as `Int`.

**Presence in practice** (VERIFIED by checking every setter call site):
- `Token.version` is Absent until a token's first non-hot-fix Swap, then `Set(2)` (Int).
- `Pool.tick` is Absent between `PoolCreated` (wave 0) and `Initialize` (wave 1) of the same block.
- Every other nullable field is always `Set`:
  - `Tick.poolAddress` = pool id;
  - `Mint.sender`, `Burn.owner` = event addresses;
  - `amountUSD` and `logIndex` are non-null values;
  - `PoolDay/HourData.tick` = `pool.tick`, which is set by then.
- The explicit-Null paths exist in the WASM but are unreachable:
  - `Pool#set:tick(null)` in the interval updaters, D:Pool:1904-1928;
  - `poolAddress` when the pool id is empty, D:Pool:4040-4058;
  - null `sender`/`owner`, D:Pool:5848-5864.

  They are still implemented (`Presence::Null`) and covered by synthetic tests, because the BlockChanges merge algebra treats a Null differently (audit F2).

**Written-field counts per save** follow directly. These are the numbers to assert in fixtures:

| Entity | Fields written |
|---|---|
| Factory | 13 |
| Bundle | 2 |
| Token | 16 before first swap, 17 after |
| Pool | 28 at creation, 29 after Initialize |
| Tick | 21 |
| Position | 19 |
| PositionSnapshot | 16 |
| Transaction | 5 |
| Mint | 16 |
| Burn | 15 |
| Swap | 15 |
| UniswapDayData | 8 |
| PoolDayData / PoolHourData | 20 |
| TickDayData | 12 |
| TokenDayData / TokenHourData | 14 |

---

## 7. Execution model (the AS object model, made explicit)

```rust
pub struct HandlerCtx<'b> {
    pub block: &'b BlockInput,          // number(i32), hash, timestamp(i32 + BigInt), base_fee
    pub event: &'b DecodedEvent,        // decoded params + address + log_index
    pub tx: &'b TxInput,                // hash, from, gas_limit, graph_gas_price
    store: &'b mut BlockStore,          // overlay over PersistentState
    calls: &'b CallBook,
    pow: &'b mut TickPowTable,
    ops: &'b mut Vec<RecordedSet>,      // this handler's saves, in call order
    created: &'b mut Vec<Address>,      // dataSource.create("Pool", [addr]) queue (this handler)
}

impl HandlerCtx<'_> {
    /// `X.load(id)`: owned copy of the get-visible entity (overlay, else persistent, else None).
    pub fn load<E: Entity>(&mut self, id: &str) -> Result<Option<E>, ReducerError>;
    /// `X.load(id)!` with the mapping's abort site ("unexpected null", file:line from the abort args).
    pub fn load_required<E: Entity>(&mut self, id: &str, site: AbortSite) -> Result<E, Step>;
    /// `x.save()`: written = x.to_fields(); records the op; overlay[key] = materialized (see §11.3).
    pub fn save<E: Entity>(&mut self, x: &E) -> Result<(), Step>;
    pub fn create_pool_source(&mut self, pool: Address);
    pub fn calls(&self) -> &CallBook;
}

pub enum Step { Abort(Abort), Fatal(ReducerError) }   // Abort = Graph Node deterministic error
```

Rules that make read-after-save exact:

1. **Overlay values are get-visible images** (`Vec<pb::EntityField>`) after each save, not AS objects. A later `load` decodes a fresh struct from the image. This is Graph Node's `EntityCache::get` layering updates over current.
2. **The persistent layer holds DB-equivalent images.** No top-level Nulls: Graph Node strips Nulls on insert (`entity_cache.rs` as_modifications, audit F2), and DB loads drop NULL columns (GN: `store/postgres/src/relational_queries.rs:563-575`). Block-end flush applies `remove_null_fields` for keys absent at block start, mirroring `as_modifications`.
3. **Handler journal.** On the first write per key in a handler, record the previous overlay value or absence. An `Abort` restores the journal, drops `created`, and marks the handler's recorded sets `DISCARDED` (EmitNonFatal only).
4. **No caching of loaded structs across calls.** A helper that the decompile shows calling `store.get` must call `ctx.load` again: `updatePoolDayData`, `getEthPriceInUSD`, `findEthPerToken`, `getTrackedAmountUSD`, `updateUniswapDayData`. A helper that receives an object must take `&T` from the caller: `updateTokenDayData(token)`, `updateTickDayData(tick)`, `findEthPerToken(token, other)`. This is the whole read-after-save model. Code review checks it line by line against §8.

---

## 8. Handler port plan

The notation is Rust-like pseudo-code. `⟨Sk⟩` marks the k-th `store.set` in the handler. Every arithmetic op is a `GraphDecimal` host op (n∘n) with the parenthesization shown. Association matters: it is VERIFIED from the decompile and differs between handlers (Q-N3). `AbortSite` values are the `(file, line)` arguments of the WASM `abort` call.

### 8.1 `Factory.handlePoolCreated` (D:Factory:2577-3575)

```rust
fn handle_pool_created(ctx, ev /* token0, token1, tick_spacing: i32, pool */) -> Result<(), Step> {
    if ev.pool == HOTFIX_POOL_8FE8 { return Ok(()) }                        // :2586-2647 (inert, P5)
    let mut factory = match ctx.load::<Factory>(FACTORY_ID)? {             // :2649
        Some(f) => f,
        None => {
            let f = Factory::zeroed(FACTORY_ID, owner = "0x0000000000000000000000000000000000000000");
            ctx.save(&Bundle { id: "1", eth_price_usd: ZERO_BD })?;        // ⟨S1, first pool ever only⟩ :2761-2797
            f
        }
    };
    factory.pool_count = factory.pool_count + 1;                           // BigInt.plus :2799-2817
    let mut pool = Pool::with_id(hex(ev.pool));                            // id only so far
    let t0 = ctx.load::<Token>(&hex(ev.token0))?;                          // both loads before any create
    let t1 = ctx.load::<Token>(&hex(ev.token1))?;
    let mut token0 = t0.map_or_else(|| new_token(ctx, ev.token0), Ok)?;   // :2865-3036
    let mut token1 = t1.map_or_else(|| new_token(ctx, ev.token1), Ok)?;   // :3037-3208
    if WHITELIST.contains(&token0.id) { token1.whitelist_pools.push(pool.id.clone()) }  // :3209-3219 (persisted)
    if WHITELIST.contains(&token1.id) { token0.whitelist_pools.push(pool.id.clone()) }  // :3220-3230
    pool.token0 = token0.id.clone(); pool.token1 = token1.id.clone();
    pool.fee_tier = BigInt::from(fee_tier_for_tick_spacing(ev.tick_spacing));          // :3312 (Q-F1)
    pool.created_at_timestamp = block.timestamp; pool.created_at_block_number = block.number;
    /* 0 for: liquidityProviderCount, txCount, liquidity, sqrtPrice, feeGrowthGlobal0/1X128, observationIndex (BigInt)
       ZERO_BD for: token0Price, token1Price, totalValueLockedToken0/1, totalValueLockedUSD, totalValueLockedETH,
       totalValueLockedUSDUntracked, volumeToken0/1, volumeUSD, feesUSD, untrackedVolumeUSD, collectedFeesToken0/1,
       collectedFeesUSD.  tick: Absent */                                            // :3320-3530 (28 fields)
    ctx.save(&pool)?;                                                      // ⟨Pool⟩ :3534
    ctx.create_pool_source(ev.pool);                                       // :3553 dataSource.create("Pool",[hex]); Token saves :3555-3556
    ctx.save(&token0)?;  ctx.save(&token1)?;                               // ⟨Token0⟩⟨Token1⟩
    ctx.save(&factory)?;                                                   // ⟨Factory⟩ :3578
}

fn new_token(ctx, addr) -> Result<Token, Step> {                           // Token(id) then setters
    let a = ctx.calls().erc20(addr)?;                                      // C1–C4 (fail closed if absent)
    Ok(Token { id: hex(addr),
        symbol: fetch_token_symbol(&a.symbol),  name: fetch_token_name(&a.name),
        total_supply: fetch_token_total_supply(&a.total_supply), decimals: fetch_token_decimals(&a.decimals),
        derived_eth: ZERO_BD, volume: ZERO_BD, volume_usd: ZERO_BD, fees_usd: ZERO_BD, untracked_volume_usd: ZERO_BD,
        total_value_locked: ZERO_BD, total_value_locked_usd: ZERO_BD, total_value_locked_usd_untracked: ZERO_BD,
        tx_count: 0, pool_count: 0, whitelist_pools: vec![], version: Presence::Absent })   // 16 fields
    // decimals-null early return (`log.debug("mybug…")`) is dead code: fetchTokenDecimals never returns null.
}
```

**ERC20 fallbacks** (D:Factory:2024-2450, VERIFIED). The static token list is empty (D:Factory:1912-1935).

| Field | Rule |
|---|---|
| `symbol` | decode the raw retval as `(string)`; if that is OK, use it. Otherwise decode the **same raw** as `(bytes32)`: if that is OK and `hex ≠ 0x00…01`, use `bytes_to_string(b32)`, else `"unknown"`. A revert on both gives `"unknown"`. |
| `name` | same as `symbol` |
| `totalSupply` | `(uint256)` value; on revert or decode error → `BigInt 0` |
| `decimals` | `(uint8)` value V (U256, no range check). If `V ≤ 255` (`compare(V,255) != 1`) use V, else 0. Revert or decode error → 0. |

Stored strings then pass `graph_store_string`.

`fee_tier_for_tick_spacing(ts)`: `1→100, 50→500, 100→500, 200→3000, _→10000`. On Base the `_` arm is reached by 2000 and 10 (P1).

### 8.2 `Pool.handleInitialize` (D:Pool:3576-3662)

```rust
let mut pool = ctx.load_required::<Pool>(&hex(ev.address), site("core.ts",27))?;
pool.sqrt_price = ev.sqrt_price_x96; pool.tick = Set(BigInt::from(ev.tick));
ctx.save(&pool)?;                                                          // ⟨Pool⟩
let mut token0 = ctx.load_required::<Token>(&pool.token0, site("core.ts",33))?;
let mut token1 = ctx.load_required::<Token>(&pool.token1, site("core.ts",34))?;
let mut bundle = ctx.load_required::<Bundle>("1", site("core.ts",37))?;
bundle.eth_price_usd = get_eth_price_in_usd(ctx)?;   ctx.save(&bundle)?;   // ⟨Bundle⟩
update_pool_day_data(ctx)?;                                                // ⟨PoolDayData⟩ (reloads pool: sees ⟨Pool⟩)
update_pool_hour_data(ctx)?;                                               // ⟨PoolHourData⟩
token0.derived_eth = find_eth_per_token(ctx, &token0, &token1)?;
token1.derived_eth = find_eth_per_token(ctx, &token1, &token0)?;          // uses other.id only
ctx.save(&token0)?; ctx.save(&token1)?;                                    // ⟨Token0⟩⟨Token1⟩
```

Token prices are not set at Initialize (Q-P4).

### 8.3 `Pool.handleMint` (D:Pool:5468-6083)

```rust
let bundle  = load_required Bundle "1"            site(core.ts,52)
let mut pool = load_required Pool hex(addr)       site(core.ts,54)
let mut factory = load_required Factory           site(core.ts,55)
let mut token0 = load_required Token pool.token0  site(core.ts,57);  token1 site(core.ts,58)
let amount0 = convert_token_to_decimal(&ev.amount0, &token0.decimals);   amount1 likewise
let amount_usd = amount0 * (token0.derived_eth * bundle.eth_price_usd)
               + amount1 * (token1.derived_eth * bundle.eth_price_usd);                    // Q-N3 association
factory.total_value_locked_eth = factory.total_value_locked_eth - pool.total_value_locked_eth;
factory.tx_count += 1;
token0.tx_count += 1; token0.total_value_locked = token0.total_value_locked + amount0;
token0.total_value_locked_usd = token0.total_value_locked * (token0.derived_eth * bundle.eth_price_usd);  // Q-N3
token1: same with amount1
pool.tx_count += 1;
if let Set(t) = &pool.tick { if BigInt(ev.tick_lower) <= *t && BigInt(ev.tick_upper) > *t {        // core.ts:89-90
    pool.liquidity = pool.liquidity + ev.amount } }
pool.tvl0 = pool.tvl0 + amount0; pool.tvl1 = pool.tvl1 + amount1;
pool.tvl_eth = pool.tvl0 * token0.derived_eth + pool.tvl1 * token1.derived_eth;
pool.tvl_usd = pool.tvl_eth * bundle.eth_price_usd;
factory.tvl_eth = factory.tvl_eth + pool.tvl_eth; factory.tvl_usd = factory.tvl_eth * bundle.eth_price_usd;
let tx = load_transaction(ctx)?;                                                            // ⟨S1 Transaction⟩
let mint = Mint { id: format!("{}#{}", tx.id, pool.tx_count), transaction: tx.id, timestamp: tx.timestamp,
    pool: pool.id, token0: pool.token0, token1: pool.token1, owner: ev.owner, sender: Set(ev.sender),
    origin: ctx.tx.from, amount: ev.amount, amount0, amount1, amount_usd: Set(amount_usd),
    tick_lower: BigInt(ev.tick_lower), tick_upper: BigInt(ev.tick_upper), log_index: Set(ev.log_index) };
let lower_id = format!("{}#{}", hex(addr), ev.tick_lower);  let upper_id = …;
let lo = ctx.load::<Tick>(&lower_id)?;  let up = ctx.load::<Tick>(&upper_id)?;            // both loads first
let mut lower = lo.unwrap_or_else(|| create_tick(ctx, lower_id, ev.tick_lower, &pool.id));  // not saved yet
let mut upper = up.unwrap_or_else(|| create_tick(ctx, upper_id, ev.tick_upper, &pool.id));
lower.liquidity_gross += ev.amount; lower.liquidity_net += ev.amount;
upper.liquidity_gross += ev.amount; upper.liquidity_net -= ev.amount;
update_uniswap_day_data(ctx)?;          // ⟨S2⟩  stored Factory (pre-Mint): tvlUSD, txCount  (Q-R2)
update_pool_day_data(ctx)?;             // ⟨S3⟩  stored Pool (pre-Mint)                       (Q-R1)
update_pool_hour_data(ctx)?;            // ⟨S4⟩
update_token_day_data(ctx, &token0)?;   // ⟨S5⟩  in-memory token (post-Mint TVL)
update_token_day_data(ctx, &token1)?;   // ⟨S6⟩
update_token_hour_data(ctx, &token0)?;  // ⟨S7⟩
update_token_hour_data(ctx, &token1)?;  // ⟨S8⟩
ctx.save(&token0)?; ctx.save(&token1)?; ctx.save(&pool)?; ctx.save(&factory)?; ctx.save(&mint)?;   // ⟨S9–S13⟩
update_tick_fee_vars_and_save(ctx, &mut lower)?;   // ⟨S14 Tick⟩⟨S15 TickDayData⟩
update_tick_fee_vars_and_save(ctx, &mut upper)?;   // ⟨S16⟩⟨S17⟩
```

### 8.4 `Pool.handleBurn` (D:Pool:6084-6667)

Same prelude with abort sites `core.ts` 171/173/174/176/177. The differences from Mint:
- Subtraction everywhere: `token.tvl - amount`, `pool.tvl* - amount*`. In range, `pool.liquidity - ev.amount` (sites 207/208).
- Burn fields: `owner: Set(ev.owner)`, no `sender`. Amounts are params 4/5 and the tick bounds params 1/2 (D:Pool:6105-6125, 6360-6445).
- Ticks are `load_required` (abort sites `core.ts:245`, `:246`). There is no `createTick`.
- Tick updates: `lower.gross -= amt; lower.net -= amt; upper.gross -= amt; upper.net += amt`.

Save order (D:Pool:6614-6661):
1. Transaction
2. UniswapDayData, PoolDayData, PoolHourData, TokenDayData×2, TokenHourData×2
3. `update_tick_fee_vars_and_save(lower)` (Tick, TickDayData), then `(upper)` (Tick, TickDayData)
4. Token0, Token1, Pool, Factory, **Burn**

That is 17 saves.

### 8.5 `Pool.handleSwap` (D:Pool:7005-8543), the densest handler (12.4 per block at 34.7M, TARGET §9)

```rust
let mut bundle  = load_required Bundle "1"   site(core.ts,271)
let mut factory = load_required Factory      site(core.ts,272)
let mut pool    = load_required Pool hex(addr) site(core.ts,273)
if pool.id == HOTFIX_POOL_9663 { return Ok(()) }                                  // :7028 (inert, P5)
let mut token0 = load_required Token pool.token0 site(core.ts,280); token1 site(core.ts,281)
for t in [&mut token0, &mut token1] {                                             // :7044-7066 (Q-W1)
    if t.version_or_zero() == 0 { t.version = Set(2); add_missing_whitelisted_pools(ctx, t)?; } }
let old_tick = pool.tick.required(site(core.ts,297))?;
let amount0 = convert_token_to_decimal(&ev.amount0 /*int256*/, &token0.decimals); amount1 likewise
let amount0_abs = if amount0.compare(&ZERO_BD) == Less { amount0 * MINUS_ONE } else { amount0 };  // "-1" via fromString
let amount1_abs = …;
let amount0_eth = amount0_abs * token0.derived_eth;  let amount1_eth = amount1_abs * token1.derived_eth;
let amount0_usd = amount0_eth * bundle.eth_price_usd; let amount1_usd = amount1_eth * bundle.eth_price_usd;
let tracked_usd = tracked_amount_usd(ctx, &amount0_abs, &token0, &amount1_abs, &token1)? / TWO;  // reloads Bundle
let tracked_eth = if !bundle.eth_price_usd.is_zero() { tracked_usd / bundle.eth_price_usd } else { ZERO_BD };
let untracked_usd = (amount0_usd + amount1_usd) / TWO;
let fees_eth = (tracked_eth * GraphDecimal::from_bigint(&pool.fee_tier)) / MILLION;
let fees_usd = (tracked_usd * GraphDecimal::from_bigint(&pool.fee_tier)) / MILLION;
factory.tx_count += 1; factory.total_volume_eth += tracked_eth; factory.total_volume_usd += tracked_usd;
factory.untracked_volume_usd += untracked_usd; factory.total_fees_eth += fees_eth; factory.total_fees_usd += fees_usd;
factory.tvl_eth = factory.tvl_eth - pool.tvl_eth;
pool.volume_token0 += amount0_abs; pool.volume_token1 += amount1_abs; pool.volume_usd += tracked_usd;
pool.untracked_volume_usd += untracked_usd; pool.fees_usd += fees_usd; pool.tx_count += 1;
pool.liquidity = ev.liquidity; pool.tick = Set(BigInt(ev.tick)); pool.sqrt_price = ev.sqrt_price_x96;
pool.tvl0 += amount0; pool.tvl1 += amount1;
token0.volume += amount0_abs; token0.tvl += amount0; token0.volume_usd += tracked_usd;
token0.untracked_volume_usd += untracked_usd; token0.fees_usd += fees_usd; token0.tx_count += 1;   token1 likewise
let (p0, p1) = sqrt_price_x96_to_token_prices(&pool.sqrt_price, &token0.decimals, &token1.decimals);
pool.token0_price = p0; pool.token1_price = p1;
ctx.save(&pool)?;                                                         // ⟨S1 Pool #1⟩ (before TVL-ETH & fees)
bundle.eth_price_usd = get_eth_price_in_usd(ctx)?;                       // may read ⟨S1⟩ if pool == 0xb2cc…
ctx.save(&bundle)?;                                                       // ⟨S2⟩
token0.derived_eth = find_eth_per_token(ctx, &token0, &token1)?;         // reads STORED tokens (Q-R4)
token1.derived_eth = find_eth_per_token(ctx, &token1, &token0)?;
pool.tvl_eth = pool.tvl0 * token0.derived_eth + pool.tvl1 * token1.derived_eth;
pool.tvl_usd = pool.tvl_eth * bundle.eth_price_usd;                       // NEW eth price
factory.tvl_eth = factory.tvl_eth + pool.tvl_eth; factory.tvl_usd = factory.tvl_eth * bundle.eth_price_usd;
token0.tvl_usd = (token0.tvl * token0.derived_eth) * bundle.eth_price_usd;   // Q-N3: differs from Mint
token1.tvl_usd = (token1.tvl * token1.derived_eth) * bundle.eth_price_usd;
let tx = load_transaction(ctx)?;                                          // ⟨S3⟩
let swap = Swap { id: format!("{}#{}", tx.id, pool.tx_count), transaction: tx.id, timestamp: tx.timestamp,
    pool: pool.id, token0: pool.token0, token1: pool.token1, sender: ev.sender, origin: ctx.tx.from,
    recipient: ev.recipient, amount0, amount1, amount_usd: tracked_usd, tick: BigInt(ev.tick),
    sqrt_price_x96: ev.sqrt_price_x96, log_index: Set(ev.log_index) };
let fg = ctx.calls().fee_growth_global(addr)?;                            // C5 (non-try)
pool.fee_growth_global0_x128 = fg.g0; pool.fee_growth_global1_x128 = fg.g1;
let mut udd = update_uniswap_day_data(ctx)?;          // ⟨S4⟩ stored Factory (pre-swap)
let mut pdd = update_pool_day_data(ctx)?;             // ⟨S5⟩ stored Pool = ⟨S1⟩ (old TVL/fee growth) (Q-R1)
let mut phd = update_pool_hour_data(ctx)?;            // ⟨S6⟩
let mut tdd0 = update_token_day_data(ctx, &token0)?;  // ⟨S7⟩
let mut tdd1 = update_token_day_data(ctx, &token1)?;  // ⟨S8⟩
let mut thd0 = update_token_hour_data(ctx, &token0)?; // ⟨S9⟩
let mut thd1 = update_token_hour_data(ctx, &token1)?; // ⟨S10⟩
udd.volume_eth += tracked_eth; udd.volume_usd += tracked_usd; udd.fees_usd += fees_usd;
pdd.volume_usd += tracked_usd; pdd.volume_token0 += amount0_abs; pdd.volume_token1 += amount1_abs; pdd.fees_usd += fees_usd;
phd: same as pdd
tdd0.volume += amount0_abs; tdd0.volume_usd += tracked_usd; tdd0.untracked_volume_usd += tracked_usd /*Q-I3*/;
tdd0.fees_usd += fees_usd;   thd0 same;   tdd1/thd1 with amount1_abs
ctx.save(&swap)?;                                                          // ⟨S11⟩
for e in [tdd0, tdd1] save; save(udd); save(pdd); save(thd0); save(thd1); save(phd);   // ⟨S12–S18⟩
ctx.save(&factory)?; ctx.save(&pool)?; ctx.save(&token0)?; ctx.save(&token1)?;         // ⟨S19–S22⟩
// tick crossing, canonical algorithm with Aerodrome's wrong spacing (Q-S2)       :8452-8540
let new_tick = pool.tick.required(site(core.ts,480))?;
let spacing = fee_tier_to_tick_spacing(&pool.fee_tier)?;   // 10000→200, 3000→60, 500→10, 100→1, else Abort(tick.ts,57)
let modulo = graph_mod(&new_tick, &spacing)?;
if modulo.is_zero() { load_tick_update_fee_vars_and_save(ctx, to_i32(&new_tick)?)?; }
let num_iters = graph_div(&(old_tick - &new_tick).abs(), &spacing)?;
if num_iters <= 100 {
    if new_tick > old_tick { let mut i = &old_tick + (&spacing - &modulo);
        while i <= new_tick { load_tick_update_fee_vars_and_save(ctx, to_i32(&i)?)?; i += &spacing; } }
    else if new_tick < old_tick { let mut i = &old_tick - &modulo;
        while i >= new_tick { load_tick_update_fee_vars_and_save(ctx, to_i32(&i)?)?; i -= &spacing; } }
}
```

`add_missing_whitelisted_pools(ctx, t)` (D:Pool:6737-6810):
- If `t.id == USDC`, return. The comparison is on H160 bytes.
- Otherwise there are four non-try `getPool` calls whose results are pushed to a getter copy that is lost.
- **Reducer body: `Ok(())`** (VERIFIED, §4.1). The only persisted effect is the caller's `version = 2`, which is also applied to USDC (Q-W1).

### 8.6 `Pool.handleFlash` (D:Pool:8544-8604)

```rust
let mut pool = load_required Pool hex(addr) site(core.ts,514);
let fg = ctx.calls().fee_growth_global(addr)?;              // C5
pool.fee_growth_global0_x128 = fg.g0; pool.fee_growth_global1_x128 = fg.g1;
ctx.save(&pool)?;                                            // the only save; no Flash row (Q-X1)
```

### 8.7 Interval updaters

- **`update_uniswap_day_data`** (D:Pool:4333-4450):
  - `factory = load_required(FACTORY_ID, intervalUpdates.ts:24)`;
  - load or create `UniswapDayData{id:"{day}", date: day*86400, volumeETH:0, volumeUSD:0, volumeUSDUntracked:0, feesUSD:0}`;
  - set `tvlUSD = factory.tvlUSD` and `txCount = factory.txCount`;
  - save, and return the object.
- **`update_pool_day_data`** (D:Pool:2614-2938):
  - `pool = load_required(hex(addr), intervalUpdates.ts:51)` (store view);
  - load or create `{id, date, pool:pool.id, volumeToken0/1:0, volumeUSD:0, feesUSD:0, txCount:0, feeGrowthGlobal0/1X128:0, open=high=low=close=pool.token0Price}`;
  - `if pool.token0Price > high {high=…}` and `if < low {low=…}` (compare);
  - copy `liquidity, sqrtPrice, feeGrowthGlobal0/1X128, token0Price, token1Price`, and set `tick = pool.tick` (Absent/Null → Null);
  - `tvlUSD = pool.totalValueLockedUSD`; `txCount += 1`;
  - save and return.
  - **`close` is not updated** (Q-I2).
- **`update_pool_hour_data`** (D:Pool:2969-3303): the same with `periodStartUnix`, site `intervalUpdates.ts:100`, and **`close = pool.token0Price` updated**.
- **`update_token_day_data(ctx, token: &Token)`** (D:Pool:4495-4727):
  - `bundle = load_required("1", intervalUpdates.ts:144)`;
  - `price = token.derivedETH * bundle.ethPriceUSD`;
  - load or create `{id:"{token}-{day}", date, token, volume:0, volumeUSD:0, feesUSD:0, untrackedVolumeUSD:0, open=high=low=close=price}`;
  - high/low by compare; `close = price`; `priceUSD = token.derivedETH * bundle.ethPriceUSD` (recomputed, same value);
  - `totalValueLocked = token.tvl`; `totalValueLockedUSD = token.tvlUSD`;
  - save and return.
- **`update_token_hour_data`** (D:Pool:4758-4989): the same with hour, site `intervalUpdates.ts:187`.
- **`update_tick_day_data(ctx, tick: &Tick)`** (D:Pool:5075-5310):
  - load or create `{id:"{tick.id}-{day}", date, pool: tick.pool, tick: tick.id}`;
  - copy `liquidityGross, liquidityNet, volumeToken0`, then **`volumeToken1 = tick.volumeToken0`** (Q-I4);
  - copy `volumeUSD, feesUSD, feeGrowthOutside0X128, feeGrowthOutside1X128`;
  - save.

### 8.8 Tick helpers (D:Pool:4009-4277, 5311-5467, 6992-7004)

```rust
fn create_tick(ctx, id: String, tick_idx: i32, pool_id: &str) -> Tick {   // NOT saved here
    let price0 = bigdecimal_exponated_1_0001(tick_idx, ctx.pow);
    let price1 = if !price0.is_zero() { ONE_BD / price0 } else { ZERO_BD };
    Tick { id, tick_idx: BigInt(tick_idx), pool: pool_id.into(),
           pool_address: if pool_id.is_empty() { Null } else { Set(pool_id.into()) },
           created_at_timestamp: block.timestamp, created_at_block_number: block.number,
           liquidity_gross: 0, liquidity_net: 0, liquidity_provider_count: 0, price0, price1,
           volume_token0: ZERO_BD, volume_token1: ZERO_BD, volume_usd: ZERO_BD, fees_usd: ZERO_BD,
           untracked_volume_usd: ZERO_BD, collected_fees_token0/1/usd: ZERO_BD,
           fee_growth_outside0_x128: 0, fee_growth_outside1_x128: 0 }            // 21 fields
}
fn update_tick_fee_vars_and_save(ctx, tick: &mut Tick) -> Result<(), Step> {
    let a = ctx.calls().ticks(ev.address, to_i32(&tick.tick_idx)?)?;          // C6/C7 non-try
    tick.fee_growth_outside0_x128 = a.staked_liquidity_net;     // value2 (Q-K1: int128, may be negative)
    tick.fee_growth_outside1_x128 = a.fee_growth_outside0_x128; // value3
    ctx.save(tick)?;                                            // ⟨Tick⟩
    update_tick_day_data(ctx, tick)                             // ⟨TickDayData⟩
}
fn load_tick_update_fee_vars_and_save(ctx, i: i32) -> Result<(), Step> {
    if let Some(mut t) = ctx.load::<Tick>(&format!("{}#{}", hex(ev.address), i))? {   // itoa32 decimal
        update_tick_fee_vars_and_save(ctx, &mut t)?; }
    Ok(())
}
```

### 8.9 Pricing (D:Pool:2407-2422, 3431-3546, 7120-7190)

```rust
fn get_eth_price_in_usd(ctx) -> Result<GraphDecimal, Step> {
    Ok(match ctx.load::<Pool>(USDC_WETH_POOL /*0xb2cc…dc59*/)? {
        Some(p) if p.total_value_locked_token0.compare(&MIN_ETH_LOCKED /*0.01*/) == Greater => p.token1_price,
        _ => ZERO_BD })
}
fn find_eth_per_token(ctx, token: &Token, other: &Token) -> Result<GraphDecimal, Step> {
    if token.id == WETH { return Ok(ONE_BD) }                                     // no stable-coin branch (Q-P2)
    let (mut largest, mut price) = (ZERO_BD, ZERO_BD);
    for pid in &token.whitelist_pools {                                           // in-memory token's list, in order
        let pool = ctx.load_required::<Pool>(pid, site("pricing.ts",73))?;
        if pool.liquidity > 0 {
            if pool.token0 == token.id && !(pool.token1 == other.id && WHITELIST.contains(&pool.token0)) {
                let t1 = ctx.load_required::<Token>(&pool.token1, site("pricing.ts",77))?;   // STORED token
                let eth_locked = pool.tvl1 * t1.derived_eth;
                if eth_locked > largest && eth_locked > MIN_ETH_LOCKED { largest = eth_locked; price = pool.token1_price * t1.derived_eth; } }
            if pool.token1 == token.id && !(pool.token0 == other.id && WHITELIST.contains(&pool.token1)) {
                let t0 = ctx.load_required::<Token>(&pool.token0, site("pricing.ts",87))?;
                let eth_locked = pool.tvl0 * t0.derived_eth;
                if eth_locked > largest && eth_locked > MIN_ETH_LOCKED { largest = eth_locked; price = pool.token0_price * t0.derived_eth; } }
        }
    }
    Ok(price)
}
fn tracked_amount_usd(ctx, a0: &GD, t0: &Token, a1: &GD, t1: &Token) -> Result<GD, Step> {      // inlined in Swap
    let b = ctx.load_required::<Bundle>("1", site("pricing.ts",113))?;
    let p0 = t0.derived_eth * b.eth_price_usd; let p1 = t1.derived_eth * b.eth_price_usd;
    Ok(match (WHITELIST.contains(&t0.id), WHITELIST.contains(&t1.id)) {
        (true, true)  => a0 * p0 + a1 * p1,
        (true, false) => (a0 * p0) * TWO,
        (false, true) => (a1 * p1) * TWO,
        _             => ZERO_BD })
}
```

All comparisons are `GraphDecimal::compare` (graph-ts `compare` = sign of `minus`).

### 8.10 NPM (D:NPM:2007-3501)

```rust
fn get_position(ctx, token_id: &U256) -> Result<Option<Position>, Step> {                       // :2114-2560
    let id = token_id.to_string();
    if let Some(p) = ctx.load::<Position>(&id)? { return Ok(Some(p)) }
    let r = match ctx.calls().positions(token_id)? { Reverted => return Ok(None), Value(v) => v };  // try_positions
    let pool = ctx.calls().get_pool(r.token0, r.token1, r.tick_spacing)?;                     // C9 non-try
    let tx = load_transaction(ctx)?;                                                            // ⟨Transaction⟩ (inside construction)
    Ok(Some(Position { id, owner: [0u8;20].into(), pool: hex(pool), token0: hex(r.token0), token1: hex(r.token1),
        tick_lower: format!("{}#{}", hex(pool), r.tick_lower), tick_upper: format!("{}#{}", hex(pool), r.tick_upper),
        liquidity: 0, deposited_token0/1: ZERO_BD, withdrawn_token0/1: ZERO_BD, collected_token0/1: ZERO_BD,
        collected_fees_token0/1: ZERO_BD, transaction: tx.id,
        fee_growth_inside0_last_x128: r.fgi0, fee_growth_inside1_last_x128: r.fgi1 }))          // 19 fields; NOT saved
}
fn update_fee_vars(ctx, pos: &mut Position, token_id) -> Result<(), Step> {                     // :2703-2746
    if let Value(r) = ctx.calls().positions(token_id)? { pos.fgi0 = r.fgi0; pos.fgi1 = r.fgi1; } Ok(())
}
fn save_position_snapshot(ctx, pos: &Position) -> Result<(), Step> {                            // :2817-3089
    let tx = load_transaction(ctx)?;                                                            // ⟨Transaction⟩ first
    ctx.save(&PositionSnapshot { id: format!("{}#{}", pos.id, block.number), owner: pos.owner, pool: pos.pool,
        position: pos.id, block_number: block.number, timestamp: block.timestamp, liquidity: pos.liquidity,
        deposited_token0/1, withdrawn_token0/1, collected_fees_token0/1, transaction: tx.id, fgi0, fgi1 })  // ⟨Snapshot⟩
}
handle_increase_liquidity:                                                                       // :3090-3202
    if block.number == 14_317_993 { return }                                                    // Q-H3 (inert on Base)
    let Some(mut pos) = get_position(ctx, &ev.token_id)? else { return };
    if h160(pos.pool) == HOTFIX_POOL_8FE8 { return }
    let t0 = load_required Token pos.token0 site(position-manager.ts,102); t1 site(…,103)
    let a0 = convert_token_to_decimal(&ev.amount0, &t0.decimals); a1 likewise                   // NPM inline variant, same value
    pos.liquidity += ev.liquidity; pos.deposited_token0 += a0; pos.deposited_token1 += a1;
    update_fee_vars(ctx, &mut pos, &ev.token_id)?; ctx.save(&pos)?; save_position_snapshot(ctx, &pos)?;
handle_decrease_liquidity:                                                                       // :3203-3320
    same guards, sites 137/138; pos.liquidity = pos.liquidity - ev.liquidity; withdrawn_token0/1 += a0/a1; rest same
handle_collect:                                                                                  // :3358-3469 (NO block guard)
    pool guard, sites 164/165; collected_token0 += a0; collected_token1 += a1;
    collected_fees_token0 = collected_token0 - withdrawn_token0; collected_fees_token1 = collected_token1 - withdrawn_token1;  // Q-M2
    update_fee_vars; save; snapshot
handle_transfer:                                                                                 // :3470-3501 (no guards, no fee vars)
    let Some(mut pos) = get_position(ctx, &ev.token_id /*param 2*/)? else { return };
    pos.owner = ev.to; ctx.save(&pos)?; save_position_snapshot(ctx, &pos)?;
    if ev.to == ZERO_ADDRESS { ctx.mark_burned(&pos.id) }                                       // state tiering hint only (§13.2)
```

NPM save shapes:
- An existing position writes [Position, Transaction, PositionSnapshot].
- A new position writes [Transaction, Position, Transaction, PositionSnapshot].

### 8.11 `loadTransaction` (D:Pool:3821-3913; D:NPM:2007-2100)

```rust
fn load_transaction(ctx) -> Result<Transaction, Step> {
    let id = hex(ctx.tx.hash);
    let mut t = ctx.load::<Transaction>(&id)?.unwrap_or_else(|| Transaction::with_id(id));
    t.block_number = block.number; t.timestamp = block.timestamp;
    t.gas_used = BigInt::from(ctx.tx.gas_limit);            // Q-T1 (graph-ts Transaction field 5 = gasLimit)
    t.gas_price = BigInt::from(ctx.tx.graph_gas_price);     // §5.6
    ctx.save(&t)?; Ok(t)                                    // ⟨Transaction⟩ (5 fields) every call
}
```

---

## 9. Quirks register (each needs a named test)

Every row is VERIFIED from the decompile unless marked. "Test" names a fixture or synthetic test from §14.

| ID | Quirk | Evidence | Test |
|---|---|---|---|
| Q-F1 | `feeTier` from tickSpacing: 1→100, 50/100→500, 200→3000, else→10000. On Base the else arm covers 2000 and 10. | D:Factory:3312; P1 | `factory_fee_table_all_six_spacings` |
| Q-F2 | Whitelist push in Factory is persisted for the counter-token only (`token1` if `token0∈WL`, and vice versa) | D:Factory:3209-3230 | `factory_whitelist_push_both_ways` |
| Q-F3 | Bundle `"1"` is created and saved **before** the Pool in the first-ever PoolCreated | D:Factory:2761-2797 | F-W1 golden block 13,899,663 |
| Q-F4 | `Token.poolCount` is never incremented. `totalSupply` is fixed at creation. `version` is Absent at creation. | D:Factory:2865-3208 | schema counts |
| Q-F5 | ERC20 fallbacks: string→bytes32→"unknown"; `0x00…01` → "unknown"; decimals ≤255 else 0; revert → 0; static list empty | D:Factory:1912-2450 | F-ERC20 cases |
| Q-F6 | Strings are NUL-stripped at store.set (all U+0000), after `bytesToString`'s trailing trim | GN `to_from/mod.rs:116-123` | F-ERC20 `nul_padded`, `interior_nul` |
| Q-W1 | First swap per token sets `version=2` (Int), applied to both tokens, including USDC. It happens after the hot-fix return and before `pool.tick!`. | D:Pool:7044-7066 | `swap_sets_version_once` |
| Q-W2 | `addMissingWhitelistedPools` pushes to a getter copy, so nothing is persisted | D:Pool:3318, 6737-6810 | covered by Q-W1 (no `whitelistPools` change) |
| Q-S1 | Tick walk uses canonical spacing (10000→200, 3000→60, 500→10, 100→1), applied to Slipstream feeTiers | D:Pool:8455-8485 | `swap_walk_ts{1,50,100,200,2000,10}` |
| Q-S2 | Walk start uses `modulo` of **newTick** for oldTick (canonical bug). At most 100 iterations of the wrong spacing. When `modulo==0`, newTick is updated before the loop and possibly again inside it (double save). | D:Pool:8486-8540 | `swap_walk_double_update`, `swap_walk_num_iters_101` |
| Q-K1 | `Tick.feeGrowthOutside0X128 := stakedLiquidityNet` (int128, may be negative). `feeGrowthOutside1X128 := feeGrowthOutside0X128`. The same values are copied into TickDayData. | D:Pool:5398-5438 | `tick_fee_vars_misbinding_negative` |
| Q-K2 | `createTick` price is the iterative `1.0001^|t|` with n∘n per step. Negative ticks use `1/x` with a zero guard; `price1 = 1/price0`. | D:Pool:4113-4214 | F-POW table, `create_tick_extreme_887272` |
| Q-R1 | Interval updaters reload the **stored** Pool. In Mint/Burn they see the pre-handler pool. In Swap they see save #1 (new volume/price/tick, old TVL-ETH/USD and old feeGrowthGlobal). In Initialize they see the new tick and sqrtPrice. | D:Pool:2631-2638 | golden frames |
| Q-R2 | `UniswapDayData.tvlUSD/txCount` come from the **stored** Factory, i.e. the pre-handler values | D:Pool:4336-4340, 4410-4447 | golden frames |
| Q-R3 | `TokenDay/HourData` use the **in-memory** token (post-handler TVL, new derivedETH) and the **stored** Bundle | D:Pool:4495-4500 | golden frames |
| Q-R4 | `findEthPerToken` loads pools and counter-tokens from the store, so the same handler's unsaved derivedETH is invisible | D:Pool:3443-3533 | `find_eth_reads_stored_counter_token` |
| Q-R5 | In Swap, `getEthPriceInUSD` may read the swap pool's own save #1 when the pool is `0xb2cc…` | D:Pool:7705-7714 | window fixture with a WETH/USDC swap |
| Q-P1 | ETH price comes from pool `0xb2cc…` `token1Price` if `TVL0 > 0.01` (strictly), else 0 | D:Pool:2407-2422 | `eth_price_threshold` |
| Q-P2 | `findEthPerToken(token, other)` has 2 arguments and no stable-coin branch. It excludes pools pairing a whitelisted priced token with the swap counter-token. `MIN_ETH_LOCKED = 0.01`. | D:Pool:3431-3546 | `find_eth_exclusion_rule` |
| Q-P3 | Tracked USD uses `WHITELIST=[WETH, USDC, AERO]`, with ×2 for one-sided pairs, then `/2` in Swap | D:Pool:7120-7190 | `tracked_usd_four_cases` |
| Q-P4 | Initialize does not set token prices; the first Swap does | D:Pool:3576-3662 | golden |
| Q-N1 | Q192 is rounded to 34 significant digits at its first ABI crossing (not exact) | §5.2 | F-NUM corpus |
| Q-N2 | `convertTokenToDecimal` with `decimals == 0` returns the raw `toBigDecimal()`, normalized once (not twice) | D:Pool:3704-3716 | F-NUM `raw_bigint_crossing_negative_36_digits` |
| Q-N3 | Association differs. Mint/Burn: `amount*(dETH*ethPrice)` and `tvl*(dETH*ethPrice)`. Swap: `(tvl*dETH)*ethPrice` and `(amountAbs*dETH)*ethPrice`. | D:Pool:5505-5590 (Mint) vs 7775-7800 (Swap) | `association_mint_vs_swap` |
| Q-N4 | Negative BigDecimals may carry 35 significant digits (bigdecimal 0.1.2 undercount) | audit F1; ENG `decimal.rs:200-209` | F-NUM, validator acceptance |
| Q-I1 | `PoolDayData/HourData.tick = pool.tick` (Null if Absent; unreachable) | D:Pool:2898, 3263 | `interval_tick_null_synthetic` |
| Q-I2 | `PoolDayData.close` is never updated after creation. `PoolHourData.close` is updated. | D:Pool:2773 (set only at creation) vs 3255 (hour close updated) | golden |
| Q-I3 | `TokenDay/HourData.untrackedVolumeUSD += amountTotalUSDTracked` (tracked, not untracked) | D:Pool:8260-8405 | golden |
| Q-I4 | `TickDayData.volumeToken1 := tick.volumeToken0` (both 0 in practice) | D:Pool:5171-5185 | schema/golden |
| Q-I5 | `UniswapDayData.volumeUSDUntracked` is never updated | D:Pool:8006-8060 | golden |
| Q-M1 | Mint `pool.liquidity += amount` iff `tickLower ≤ tick < tickUpper` and tick is set. Burn mirrors it. | D:Pool:5640-5700 | golden |
| Q-M2 | `collectedFeesToken* = collectedToken* − withdrawnToken*` (may go negative) | D:NPM:3420-3455 | `collect_fees_negative` |
| Q-M3 | Burn uses `Tick.load(...)!`, so a missing tick aborts. Mint creates. | D:Pool:6565-6574 | `burn_missing_tick_aborts` (EmitNonFatal) |
| Q-T1 | `Transaction.gasUsed := gasLimit`. `gasPrice := effective gas price` per §5.6. | D:Pool:3866-3872 | F-TX |
| Q-T2 | Transaction is saved on **every** `loadTransaction` call: one or two times per NPM handler, once per Pool Mint/Burn/Swap | §8.10-8.11 | golden counts |
| Q-H1 | Hot-fix pool `0x8fe8…` in Factory and NPM guards (no code on Base) | D:Factory:2586; D:NPM:3111, 3373; P5 | `hotfix_guards_present` |
| Q-H2 | Hot-fix pool `0x9663…` in the Swap guard, returning before the version step | D:Pool:7028 | same |
| Q-H3 | NPM Increase/Decrease skip block 14,317,993; Collect/Transfer do not. Inert on Base. | D:NPM:3094, 3207; TARGET §5.6 | `npm_block_guard` |
| Q-X1 | Flash updates only fee growth; no Flash row. Collect, Flash, TickHourData are never written. | D:Pool:8544-8604; TARGET §4 | NeverWritten assertion |
| Q-ID1 | `{tx}#{pool.txCount}` collides across pools in one tx (same txCount), so a later Swap/Mint/Burn overwrites an earlier one in the same block | canonical v3 | `swap_id_collision_same_block` |
| Q-ID2 | Position IDs are decimal `tokenId`. Tick IDs use `itoa32` (signed decimal). | D:NPM:2120; D:Pool:5940-5990 | ids test |
| Q-WV1 | Graph Node waves: a pool's `Initialize` (log 171) and `Mint` (176) run in wave 1, **after** wave-0 NPM `Transfer`/`IncreaseLiquidity` (177/178) of the same tx | P6; `SB/mapping-host/src/runner.rs:11-23` | F-W1 (block 13,899,663) |
| Q-E1 | A decode failure of a candidate log means no trigger, no group, no PoI region | GN `data_source.rs:744-764` | `undecodable_candidate_not_triggered` |

---

## 10. Call answers consumed

| Call (TARGET §6) | Reducer use | Source | Missing answer | Revert semantics |
|---|---|---|---|---|
| C1–C4 ERC20 | `new_token` only (a token's first PoolCreated) | raw eth_call at block hash (extractor RpcBatch) | `MissingCallAnswer` | `RawRetval.reverted` = revert or `0x`; decode failure = revert |
| C5 `feeGrowthGlobal{0,1}X128()` | Swap, Flash | storage-derived end-of-block | fatal | cannot revert (public var, P8) |
| C6/C7 `ticks(i)` | `update_tick_fee_vars_and_save` (Mint/Burn ticks, swap walk ticks that exist as entities) | storage-derived | fatal | cannot revert (public mapping, P8) |
| C8 `positions(tokenId)` | `get_position` (new) and `update_fee_vars` | storage-derived; `reverted` iff `poolId == 0` at block end | fatal | try call: `reverted` handled |
| C9 `getPool(t0,t1,ts)` | `get_position` (new) | Factory PoolCreated store, post-block | fatal | cannot revert; a zero address yields `pool = "0x000…0"` |
| C10 `getPool(USDC,token,{…})` | none (§4.1) | not requested | n/a | cannot revert |

**`CallBook` API** (one per block):

```rust
pub struct CallBook { erc20: HashMap<Address, Erc20Answer>, fee_growth: HashMap<Address, (BigInt, BigInt)>,
                      ticks: HashMap<(Address, i32), TickWords>, positions: HashMap<U256, PositionResult>,
                      get_pool: HashMap<(Address, Address, i32), Address>, used: RefCell<UsedCounters> }
impl CallBook {
    pub fn from_block(b: &ExtractorBlock) -> Result<Self, ReducerError>;   // duplicate keys refused
    pub fn erc20(&self, a: Address) -> Result<&Erc20Answer, Step>;
    pub fn fee_growth_global(&self, pool: Address) -> Result<FeeGrowth, Step>;
    pub fn ticks(&self, pool: Address, tick: i32) -> Result<TickWords, Step>;
    pub fn positions(&self, id: &U256) -> Result<PositionResult, Step>;
    pub fn get_pool(&self, a: Address, b: Address, ts: i32) -> Result<Address, Step>;
}
```

---

## 11. BlockChanges emission

### 11.1 Per block

The reducer emits exactly one canonical message per block in `[from, to]`, including blocks with no trigger:

| Field | Value |
|---|---|
| `contract` | `"pinax.graph.backfill.block-changes/v1"` (`SB/common/src/block_changes.rs:12`) |
| `compatibility_id` | SHA-256 of the reducer descriptor (§11.7), stamped by the reducer. Client-side stamping avoids the circularity in `engine-contract.md` §2.3. |
| `block_number`, `block_hash` | from the input; must equal the envelope |
| `mapping_triggered` | true iff at least one handler group ran in the block, **including groups whose handler returned early with no saves** (for example NPM events for a position burned in this block). That matches Graph Node's `start_handler` behaviour and the "empty-but-triggered" PoI stream (`block_changes.proto:19-28`). |
| `triggered_poi_causality_regions` | `["ethereum/base"]` iff `mapping_triggered` |
| `deterministic_error_policy` | `NON_FATAL` (manifest `nonFatalErrors`) |
| `operations` | see below |

### 11.2 Ordering

The runner reproduces `SB/mapping-host/src/runner.rs:872-917`:
- **Stage 0**: hosts at block start (Factory if `block ≥ 13,843,704`, NPM if `≥ 13,843,719`, plus every pool host). Candidates with `wave = 0` run in `source_trigger_order`.
- After stage 0, the pools created by **successful** PoolCreated handlers become hosts, in creation order.
- **Stage 1**: `wave = 1` candidates run, re-using their block-wide `source_trigger_order`. No stage 2 exists, because only Factory creates sources and Factory is a stage-0 host.

| Op field | Value |
|---|---|
| `handler_group_order` | a counter incremented once per matched trigger, in execution order across stages. Groups with zero saves leave gaps, which are allowed. |
| `source_trigger_order` | the candidate's block-wide rank. It regresses in stage 1, which is allowed (`block_changes.proto:56-59`). |
| `handler_order` | always 0: a log matches at most one host, because the Factory, NPM and pool addresses are distinct and Graph Node deduplicates template instances. |
| `operation_index` | dense, zero-based across the block |
| `source_causality_region` | 0 |
| `poi_causality_region` | `Some("ethereum/base")` |

### 11.3 Per save

| `SetEntity` field | Value |
|---|---|
| `key` | `EntityKey{entity_type: E::TYPE, id: EntityId::String(id), storage_causality_region: 0}` |
| `poi_entity_type`, `poi_entity_id` | same type and id |
| `written_fields` | `x.to_fields()`: the AS field map at `save()`, schema-filtered, no `vid`, sorted by name, NUL-stripped strings, Absent omitted, Null emitted. Graph Node itself adds `id` if missing; every Aerodrome constructor sets it. |
| `materialized` | handler-local `CacheOperation` accumulate, then `apply_to(baseline)`. The baseline is the get-visible image before this handler (overlay or persistent). This is exactly the mapping-host algorithm (`SB/mapping-host/src/blockchanges.rs:404-470`) and the validator's merge algebra (`SB/common/src/block_changes.rs:1218-1245, 1547-1561`). |
| `store_disposition` | `COMMITTED`. In EmitNonFatal, an aborted handler's sets become `DISCARDED`. |
| `failure_stage` | `UNSPECIFIED` (materialized always present) |

For Aerodrome, `materialized == written_fields` for every reachable save, VERIFIED reasoning:
- loaded entities carry all stored fields;
- new objects that overwrite an in-block entity set the full field set: PositionSnapshot repeat, Q-ID1 collisions, Transaction.

The general algorithm is still used, so Null and partial cases (synthetic tests) stay exact.

### 11.4 Shared builder (refactor slice R3a)

`SB/mapping-host/src/blockchanges.rs:372-560` (`BlockOpsBuilder`: `push_handler`, `push_deterministic_error`, `finish`) is family-neutral apart from one parameter. That parameter is the graph `EntityKey` passed into `visible_before`.

Proposal:
- Move it into `backfill-common` as `block_ops::{BlockOpsBuilder, RecordedSet}`, keyed by `pb::EntityKey` / `MaterializedKey`.
- The mapping-host keeps a thin adapter, and its goldens stay byte-identical (gate).
- The reducer uses the same builder.

This follows the crate's own rule (`SB/common/src/lib.rs:1-7`, `block_changes.rs:150-153`): "two implementations of these semantics is the failure mode this contract exists to prevent."

### 11.5 Sealing

Every frame goes through `backfill_common::encode_canonical_block_changes` (validate, then prost 0.13.5 encode) and a `decode_canonical_block_changes` round trip in debug/test builds. It is then written as BCF1 clock-v1: magic `BCF1`, kind 1, block number u64 BE, hash, payload length u32 BE, payload (`engine-contract.md` §2.1).

**Hard dependency.** Phase 0 must merge the 35-digit negative BigDecimal fix (audit state-semantics F1; `SB/common/src/block_changes.rs:1840-1870` limits to 34). Without it, the first negative 35-digit TVL value refuses the frame.

### 11.6 Deterministic-error catalog (what can abort in these mappings)

| Abort source | Sites | Reachable on valid input? | Reason |
|---|---|---|---|
| `load!` "unexpected null" for Pool/Token/Bundle/Factory | `core.ts` 27,33,34,37,52-58,171-177,271-281,514; `intervalUpdates.ts` 24,51,100,144,187; `pricing.ts` 73,77,87,113; `position-manager.ts` 102,103,137,138,164,165 | no | Factory/Bundle exist from the first PoolCreated. Pools exist for every host. Tokens are created with their pool. |
| `Tick.load!` in Burn | `core.ts` 245,246 | no | every burned range was minted, which created both ticks |
| `pool.tick!` | `core.ts` 297, 480 | no | Initialize runs inside `createPool` before any Swap (P6) |
| Non-try `ethereum.call` revert or empty | feeGrowthGlobal, ticks, getPool | no | public getters cannot revert (P8). Storage-derived answers are never empty. |
| `feeTierToTickSpacing` unknown | `tick.ts:57` | no | feeTier ∈ {100,500,3000,10000} by Q-F1 |
| BigDecimal division by zero | every `.div` | no | divisors are 10^d (≥1), constants, or guarded by `compare != 0` |
| BigInt div/mod by zero | swap walk | no | spacing ∈ {1,10,60,200} |
| `toI32` overflow | ticks, timestamps | no | int24; timestamps < 2³¹ |
| BigDecimal exponent out of ±6143/6144 | any crossing | no | decimals ≤255 → 10^±255; 1.0001^±887272 ≈ 10^±38.5 |
| Gas limit | createTick loop | no | ≈6×10¹¹ ≪ 10¹⁵ (§5.4) |
| Required-field getter on a loaded entity ("Cannot return null for a required field") | all getters | no on valid state | only a corrupt seed or checkpoint could cause it, so it is classed as `ReducerError::StateCorrupt` |
| `store.set` validation (missing required field) | all saves | no | every constructor sets every non-null field (§6.2) |

Consequence: **any Abort is evidence of divergence**, so FailClosed is the default.

Historical cross-check: the Aerodrome copy `sgd5311` holds 0 `subgraph_error` rows (`engine-contract.md` §7, LIVE). `sgd2`'s health for 30.84M–34.7M is OPEN; check `indexingStatuses{health, nonFatalErrors}` read-only.

EmitNonFatal mode reproduces Graph Node, so the frame is still exact if an abort ever were legitimate:
- the handler's sets become `DISCARDED`;
- a `DeterministicError{redacted_events = group's PoI events so far}` op closes the group;
- the journal restores the overlay;
- `dataSource.create` is dropped;
- the block's other handlers stay `COMMITTED` (validator rule `block_changes.rs:1030-1046`).

The engine then still needs a `subgraph_error`/health writer (audit GEN-4), and the v2 companion refuses errors. So production must stay FailClosed.

### 11.7 Reducer compatibility descriptor

`descriptor build` generates it. The shape follows `ENG/fixtures/mapping-host-v3-stream/block-changes-descriptor.json` plus a producer section:

```json
{ "contract": "pinax.graph.backfill.block-changes/v1", "descriptor_version": 1,
  "deterministic_error_policy": "non_fatal", "network": "base", "expected_poi_causality_region": "ethereum/base",
  "graph_node": { "version": "v0.44.0", "commit": "77823b5a7adc4eac4abf03202c8dd7cb00dea31d", "poi_version": "fast" },
  "deployment": "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV", "spec_version": "1.2.0",
  "manifest_features": ["grafting", "nonFatalErrors"],
  "artifacts": { "manifest": {cid, sha256}, "schema": {cid, sha256}, "mappings": [...], "abis": [...] },
  "block_changes_proto": { "sha256": "..." }, "prost_binding": { "sha256": "..." },
  "storage_profile": { "entity_types": [20 sorted names] },
  "producer": { "name": "aerodrome-slipstream-reducer", "version": "...", "source_commit": "<40 hex>",
                "numerics": "graph-numerics <version>",
                "extractor": { "spkg_sha256": "...", "module": "map_events", "module_hash": "...",
                               "output_type": "proto:pinax.aerodrome.slipstream.base.v1.ExtractorBlock" } },
  "producer_contract": { "module": "map_events", "module_hash": "...", "output_type": "..." } }
```

The `.sha256` sidecar sits beside it. Because the descriptor differs from the mapping-host's Aerodrome descriptor, G2 compares frames with `compatibility_id` masked.

---

## 12. `data_sources$` for the Pool template: decision

**Decision: emit creations in the existing `pinax.graph.backfill.data-sources/v2` companion format, and do not extend BlockChanges.** Request one generic extension from the engine design: a *seeded genesis* for chunk chains.

**What is emitted.** Per block, the ordered list of accepted creations, as `dynamic_sources_v2::Creation{ordinal, source: DataSource{…}}` (`SB/common/src/dynamic_sources_v2.rs:140-145`; `dynamic_sources.rs:12-22`). The `DataSource` fields are:
- `creation_block = block`;
- `manifest_idx = 2`: the dataSources Factory(0) and NPM(1) come before the template Pool(2), the same layout as V3 where the engine loader allows "only manifest index 2". The reducer computes this from `reference/deployment.yaml` and asserts 2;
- `causality_region = 0`;
- `param` = pool address as lowercase hex without `0x`;
- `context = None`, `done_at = None`.

Ordinals are global and contiguous. The `SourceOrder` commitment chains across chunks.

**Why not a CreateDataSource op in BlockChanges:**
1. It would change the canonical proto, the fail-closed validator, every pinned `block_changes_proto` digest, and the engine PoI path, for an event Graph Node does **not** hash into PoI.
2. The mapping-host oracle and every existing golden would have to change in lockstep.
3. v2 already provides what is needed: creation-order commitment, identity dedup, per-frame payload binding (`verify_frame`), a sealed six-file chunk, and an engine consumer (`--data-sources-chunk`).

**Gaps v2 has today, to be raised with the engine design:**

| Gap | Today | Request |
|---|---|---|
| Genesis | `parent: None` requires `from == root_start_block` and `before == SourceState::empty()` (`dynamic_sources_v2.rs:205-211`). A seeded start at 34.7M with 1,502 existing sources (P7) cannot be expressed. | Add `genesis: Seed { seed_manifest_sha256, block, hash, before: SourceState }`. `before` is computed from the seed's `data_sources$` rows ordered by `(lower(block_range), vid)` and checked by the engine against the clone. |
| Chunk length | 10,000 blocks, so about 1,810 chunks for 18.1M seeded blocks and 3,900 from root | Keep v2 limits per chunk. The reducer seals a chunk every 10,000 blocks. |
| `host-checkpoint.json` must be inside every chunk | The reducer's state is GB-sized | Make the reducer's file a small JSON *pointer* that pins the reducer checkpoint manifest by sha256 (§13.4). The engine treats it as opaque, so this needs no engine change. |

Errors are refused by v2. That is consistent with FailClosed.

---

## 13. State management

### 13.1 Classes and bounds

| Class | Entities | Lifetime | Bound at 34.7M → head |
|---|---|---|---|
| Hot | Factory, Bundle, Token, Pool | forever, in memory | ≤ 7.3k tokens + 3.7k pools (P2), a few MB |
| Tiered | Tick | forever: LRU (default 2M) over redb | OPEN (O8). Tick versions number 91.9M (P7); active ticks ASSUMED 1–5M. |
| Tiered | Position | forever: LRU (default 4M) over redb. Burned positions are demoted to cold only. | ≈23.6M ids → ≈79.2M ids; live 1.18M → 25.7M (P3). About 350 B per canonical record ≈ 28 GB cold at head (ESTIMATE). |
| PeriodDay | UniswapDayData, PoolDayData, TokenDayData, TickDayData | until `dayID(block) > dayID(row)` | rows touched in one UTC day |
| PeriodHour | PoolHourData, TokenHourData | until hour rollover | rows touched in one hour |
| BlockLocal | Transaction, Swap, Mint, Burn, PositionSnapshot | overlay only; dropped at block end | rows of one block |
| NeverWritten | Collect, Flash, TickHourData | — | 0 |

**Why write-once eviction is safe (proof sketch, VERIFIED inputs):**
1. The mapping's `store.get` targets never include Swap, Mint, Burn or PositionSnapshot (TARGET §4 store-access inventory).
2. Transaction is only got by `hex(event.transaction.hash)`, and a tx belongs to exactly one block.
3. Swap/Mint/Burn IDs embed the tx hash. PositionSnapshot IDs embed the block number.
4. Day/hour IDs embed `timestamp/86400` or `/3600`, Base timestamps strictly increase, and handlers only compute the current block's period.

So no later block can read or overwrite these keys. In-block overwrites (Q-ID1, repeated snapshots) are handled by the overlay.

**Burned positions.** NPM `burn` emits `Transfer(owner, 0, id)`. TokenIds are never reused (`_nextId++`). NPM events reference live ids only. So a burned Position is never loaded again, but it is **kept** in cold storage anyway: there is no correctness bet on that reasoning, and the cost is disk only.

### 13.2 Backends

```rust
pub trait EntityBackend {
    fn get(&self, ty: &'static str, id: &str) -> Result<Option<Vec<pb::EntityField>>, ReducerError>;
    fn put_batch(&mut self, rows: impl Iterator<Item = (&'static str, String, Vec<pb::EntityField>)>) -> Result<(), ReducerError>;
    fn commit(&mut self, boundary: Boundary) -> Result<(), ReducerError>;     // durable at a block boundary
    fn scan_sorted(&self, ty: &'static str) -> Box<dyn Iterator<Item = (String, Vec<u8>)> + '_>;  // for digests/exports
}
```

| Backend | Use |
|---|---|
| `MemoryBackend` | tests and root oracle windows |
| `RedbBackend` | production. One table per persistent entity type: key = id UTF-8, value = canonical prost `EntityFields` bytes. Commit every `--commit-every` blocks (default 1,000) and at every checkpoint. |
| `PgOracleBackend` (feature `pg-oracle`) | read-only lazy loads at a fixed `S` (§13.6) |

`redb` is pure Rust and ACID. The exact version is chosen and benchmarked in R8. That choice is ASSUMED adequate at about 50 random Position reads per block.

### 13.3 Block lifecycle

1. Period rollover: drop period maps whose period is older than the block's period.
2. Run stage 0 and stage 1. Saves go to the overlay through `HandlerCtx`.
3. Seal the frame.
4. Flush overlay entries of Hot/Tiered/Period classes into state, stripping top-level Nulls for keys absent at block start (`as_modifications` parity). Drop BlockLocal entries.
5. Apply data-source creations to the host set.
6. Write the report line.
7. Every N blocks: backend commit. At checkpoint cadence: checkpoint (§13.4).

### 13.4 Checkpoint format `pinax.aerodrome-slipstream.reducer-checkpoint/v1`

Layout: `state.redb` committed at the boundary, plus `checkpoint-<block>.json`:

```json
{ "format": "pinax.aerodrome-slipstream.reducer-checkpoint/v1",
  "deployment": "QmasYjyp…", "descriptor_sha256": "…",
  "extractor": { "spkg_sha256": "…", "module": "map_events", "module_hash": "…" },
  "reducer": { "version": "…", "source_commit": "…", "graph_numerics": "…" },
  "origin": { "kind": "root" } | { "kind": "graph_node_seed", "seed_manifest_sha256": "…", "block": S, "hash": "…" },
  "boundary": { "block": N, "hash": "…", "timestamp": T },
  "periods": { "day": D, "hour": H },
  "sources": { "count": 1502, "order_sha256": "…" },
  "tables": [ { "entity": "Bundle", "rows": 1, "sha256": "…" }, … one per non-BlockLocal type … ],
  "state_sha256": "<sha256 over the table digests in fixed order>",
  "backend": { "kind": "redb", "file": "state.redb", "file_sha256": "…" } }
```

- **Table digest.** SHA-256 over `(len(id) ‖ id ‖ len(value) ‖ value)` for rows in key order. A full scan is about 1 min at 80M rows (ESTIMATE). The checkpoint is written to `.building`, fsynced, then renamed.
- **`checkpoint export`** writes a portable stream: magic `ARCKPT1\0`, then the manifest, then sections of length-delimited canonical records (optional zstd). **`checkpoint import`** rebuilds redb and re-verifies `state_sha256`.
- **Gate G5:** checkpoint at block k and resume must produce byte-identical frames, sources and final `state_sha256` compared with an uninterrupted run.

### 13.5 Seed from a Graph Node schema at `S = B−1`

**Artifact `pinax.graph-node.seed/v1`.** This is proposed as family-neutral and engine-owned (D3 "seed from a Graph Node schema"). The reducer is a consumer. Layout:

```
seed.ready/
  manifest.json   { format, deployment, network, shard, schema, block:{number,hash}, graph_node:{version,commit},
                    profile_sha256, isolation:"repeatable read read only", head_check:{writer_stopped:bool},
                    tables:[{entity, physical_table, selection, rows, max_vid, file, sha256}],
                    poi:{ id:"ethereum/base", digest_hex, vid, lower }, data_sources:{file, rows, sha256} }
  <Entity>.rows        length-delimited SeedRow{ string id; int64 vid; int32 lower; EntityFields fields } sorted by id
  data_sources.rows    length-delimited SeedSource{ int64 vid; int32 lower; int32 manifest_idx; bytes param;
                                                    optional string context_json; optional int32 done_at; int32 causality_region }
  READY.json
```

**Selection per table (reducer policy):**

| Tables | Selection |
|---|---|
| Factory, Bundle, Token, Pool, Tick, Position | `block_range @> S` (all active rows) |
| UniswapDayData, PoolDayData, TokenDayData, TickDayData | `block_range @> S AND date = (ts(S)/86400)*86400` |
| PoolHourData, TokenHourData | `block_range @> S AND "period_start_unix" = (ts(S)/3600)*3600` |
| Transaction, Swap, Mint, Burn, PositionSnapshot, Collect, Flash, TickHourData | `max(vid)` only (engine) |
| `data_sources$` | all rows `lower(block_range) <= S` ordered by `(lower(block_range), vid)` |
| `poi2$` | row with `id='ethereum/base' AND block_range @> S` (engine PoI continuation; the reducer only records it in its checkpoint binding) |

**Reading** (`cargo xtask aerodrome seed-capture`, Rust `postgres` crate):
- `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`.
- Verify `subgraphs.deployment`/`head` identity, `S ≤ head`, and health.
- For a stopped clone, require `head == S` and record the writer-stopped attestation. For time-travel windows on live `sgd2`, require `S < head − finality margin`.
- Columns are mapped through the physical profile's `logical_physical_bindings` (field ↔ column). `numeric` is read as `::text`, then `GraphDecimal::from_db_text` (n, the same as Graph Node's `from_column_value`) or `BigInt::from_str`. `bytea` → bytes, `text[]` → `Vec<String>`, `int4` → `i32`.
- **NULL columns are omitted** (Graph Node `deserialize_with_layout`, GN: `relational_queries.rs:563-575`).
- The resulting `EntityFields` are exactly the get-visible images Graph Node would load, so `written_fields` of the first post-seed saves match.

**`seed-import`:**
- Hot tables go to memory and Tiered tables to redb.
- Period rows are loaded into the period maps.
- `data_sources$` builds the host set and `SourceOrder` (v2 `identity()`), which become the seeded-genesis `before` state (§12).
- `checkpoint-<S>.json` is written with `origin.kind = graph_node_seed`.

**PoI continuation** is engine-side. The engine seeds its Fast PoI accumulator with the `poi2$` digest at S. The reducer's frames carry no digest; G4 checks the result.

### 13.6 Lazy oracle backend (`pg-oracle`) for time-travel windows

For a window `[B, B+N]` on `sgd2`, the reducer runs with `PgOracleBackend{S = B−1}`:
- the first `get(ty, id)` runs `SELECT … FROM "sgd2".<table> WHERE id = $1 AND block_range @> $S` and caches the result;
- day/hour rows are loaded the same way.

This is exact for first touches. An entity first touched at block b > B has, at b−1, the state it had at S *unless something modified it in [B, b)*, and such a modification is precisely what the differential's completeness check detects (§14.3). It avoids capturing 61M/92M-version tables for a 1,000-block window.

---

## 14. Verification plan

### 14.1 G1: numerics against Graph Node's own implementation

- **Corpus generator.** A test-only module in `SB/mapping-host/tests/mapping_host/numerics_corpus.rs`. The mapping-host already links `graph` at `77823b5a`, so this adds no new dependency weight. Regenerate with `UPDATE_GOLDENS=1 cargo test --test mapping_host numerics_corpus`.
  - It writes `crates/graph-numerics/fixtures/graph-node-v0.44-numerics.jsonl`. Each line is `{op, a, b, result, crossings}`.
  - Results are computed with `graph::data::store::scalar::BigDecimal` ops, followed by the `BigDecimal::new(digits, exp)` crossing (the `from_asc_obj` path).
  - Cases: 200k random ops over + − × ÷, with operands drawn from the domains seen in the mappings (34/35-digit negatives, tiny and huge exponents, powers of ten); `fromString` of all mapping constants; BigInt `/` and `%` sign cases; Q192.
- **`TickPowTable` oracle.** The same harness emits `b_k` for k ≡ 0 (mod 1024) up to 887,272, plus `k ∈ {1,2,3,…,64, 887,271, 887,272}`, written to `fixtures/tickpow-v0.44.json` with a sha256.
- **Property tests** (graph-numerics):
  - P-1: corpus equality.
  - P-2: `n(n(n(x))) == n(n(x))` for 10⁶ random negatives with 36–80 digits.
  - P-3: `from_wire(to_wire(x)) == x`, and `validate_block_changes` accepts every corpus result. This needs the Phase-0 35-digit fix.
  - P-4: `exponent_to_big_decimal(d) == 10^d` for d ∈ 0..=255.
  - P-5: `compare` equals sign of `minus` for all corpus pairs.
- **Gate G1:** 100% equality, with zero tolerance.

### 14.2 G2: frame-for-frame equality against the mapping-host (root windows)

- **Producer A:** mapping-host with the Aerodrome bundle (PR-S2, another agent), running over Firehose fixtures with a recorded cassette.
- **Producer B:** this reducer, fed by `reference_extractor` (§4.4) from the same blocks and cassette. Later it is fed by the real extractor output; the extractor gate is that the two `ExtractorBlock` streams are equal modulo superset answers.
- **Comparison:** `aerodrome-reducer diff-frames A.bcf1 B.bcf1 --mask compatibility_id`. It is byte-equal per frame, and on a mismatch prints the first differing op/field.
- **Windows** (all from root, because the mapping-host needs full prior state):

| ID | Range | Why |
|---|---|---|
| W1 | `[13,843,704, 13,900,663]` | Root through the first PoolCreated at 13,899,663 (P6): Q-WV1, Q-F3, first NPM, about 56k untriggered blocks (`mapping_triggered=false`) |
| W2 | `[13,900,664, 13,960,000]` | Early activity: first swaps (Q-W1 version), first Collect/Decrease, first burns-in-block, whitelist pushes |
| W3 | windows around edge-case blocks, found by `cargo xtask aerodrome scan` (eth_getLogs ≤1,000-block chunks or a Substreams map) | First Flash; first bytes32-symbol token; decimals-revert token; deposit-tx (type 126) carrying an Aerodrome event; Q-ID1 collision; createTick with \|tick\| ≥ 800,000; a swap with `numIters > 100`; `modulo == 0` double update; position minted and burned in one block |

- **Gate G2:** zero differing frames over W1–W3. The engine replay of B's frames gives Fast PoI digests equal to the mapping-host's reported PoI on every triggered block.

### 14.3 G3: time-travel SQL differential against `sgd2` (13.8M–34.7M)

Prerequisites: D8 read-only SQL, and O4 (`sgd2` not history-pruned over the windows).

Per window `[B, B+N]`:
1. Run the reducer with `PgOracleBackend{S=B−1}`, fed by extractor output for the range. The noop cache covers it. Before the extractor exists, use the reference extractor plus an RPC-recorded cassette.
2. Per block b and per key the reducer saved in b, compute `end_image(b)` (overlay after the block) and `start_image(b)`.
   - `changed = end_image != start_image` (Graph Node writes a version only on change; engine `sink.rs:2238` parity).
3. **Row equality:** `changed` ⇒ `SELECT … WHERE id=$1 AND lower(block_range)=b` equals `end_image`, with all columns via profile bindings and NULL ⇔ absent. Not changed ⇒ no row with `lower(block_range)=b` for that id.
4. **Completeness:** per table, `SELECT id, lower(block_range) FROM t WHERE lower(block_range) BETWEEN B AND B+N` equals the reducer's `changed` set, exactly. This catches missing triggers and handlers.
5. `data_sources$` rows with `lower ∈ [B, B+N]` equal the reducer creations (address, manifest_idx, order).

Windows: 20 windows × 1,000 blocks stratified over 13.9M–34.6M by density (TARGET §9 table); one 10,000-block window ending at 34.7M; one window that straddles a UTC day rollover and many hour rollovers.

**Gate G3:** zero mismatching rows and zero completeness differences.

### 14.4 G4–G7

- **G4 (PoI):** on G3 windows, the engine seeded from `sgd2` at S folds our frames. The Fast PoI digest at every triggered block equals `sgd2` `poi2$` digest versions in the window. This needs the engine seed and continuation (engine design).
- **G5 (lifecycle):**
  - 100k-block run: uninterrupted vs chunked at {10k, 37,123, 99,999} → identical frames, sources and `state_sha256`.
  - Kill -9 mid-commit → resume from the last checkpoint → identical.
  - `seed-import` twice → identical `state_sha256`.
- **G6 (performance):** reducer-only ≥ 100 blocks/s at 34.7M density on the production node class (ASSUMED target; measured in R10). RSS ≤ 16 GiB with default LRUs. Cold store ≤ 40 GB at head.
- **G7 (full range):** zero Aborts and zero `MissingCallAnswer` over `[seed+1, target]`. Per-handler counts per 100k blocks agree within 0 with Graph Node's `deployment_handler_execution_time_count` deltas where metrics cover the range. Use them as a statistical cross-check only; counts are exact on our side.

### 14.5 Named fixtures

All content-addressed through `cargo xtask aerodrome fixtures fetch|check` (the repo's evidence-asset pattern).

| Name | Content |
|---|---|
| F-NUM | `graph-node-v0.44-numerics.jsonl` (§14.1) |
| F-POW | `tickpow-v0.44.json` |
| F-W1 | Firehose block 13,899,663 + cassette rows + mapping-host golden frame + reference `ExtractorBlock` |
| F-W1W2 | BCF1 windows W1/W2: extractor stream, golden BlockChanges stream, golden v2 creations |
| F-W3-* | one directory per edge case |
| F-ERC20 | synthetic raw retvals: string; bytes32 (MKR-style); `0x00…01`; revert; `0x`; NUL-padded bytes32; interior NUL; invalid UTF-8; decimals 18/255/256/revert; totalSupply revert. Expected values come from running the mapping-host on a synthetic block. |
| F-TX | five real Base txs (types 0, 1, 2, 4 if present, 126), with expected `Transaction.gasPrice` from the mapping-host |
| F-SEED-SMALL | a hermetic Postgres dump (generated) of a 3-pool deployment state, for seed-import and PgOracle tests |
| S-* | synthetic scenario tests (reducer-only), each asserting the exact op list: `swap_id_collision_same_block`, `swap_walk_double_update`, `swap_walk_num_iters_101`, `burn_missing_tick_aborts`, `npm_burned_in_block_returns_early_but_triggers`, `interval_tick_null_synthetic`, `transfer_to_zero_demotes_position`, `period_rollover_evicts`, `hotfix_guards_present` |

---

## 15. PR slices (ordered), with estimates

Estimates are engineer-days for one implementer at the intensity of the V4 lane (ESTIMATE).

| # | Slice | Contents | Depends on | Est. |
|---|---|---|---|---|
| R0 | (Phase 0, not reducer-owned) BlockChanges 35-digit negative fix | already in flight elsewhere | — | — |
| R1 | `crates/graph-numerics` | port `decimal.rs` + math subset; `host_from_string`, `from_db_text`, wire, string helpers; mapping-host corpus generator + committed corpus; P-1…P-5 | R0 for P-3 | 3–4 |
| R2 | Reducer skeleton + input | crate, consumer proto, BCF1 in/out, block validation §4.3, `graph_gas_price`, alloy log decode + Graph Node match rule, `CallBook`, ERC20 semantics, descriptor builder | R1 | 5 |
| R3a | Shared `BlockOpsBuilder` in `backfill-common` | move from mapping-host; mapping-host goldens byte-identical | — | 2 |
| R3 | Entity model + store + emit | `graph_entity!` + 20 declarations + schema-conformance test (302/289/13); overlay + journal + MemoryBackend; frame sealing | R2, R3a | 4–5 |
| R4 | Port part 1 | Factory handler + token metadata; NPM (`get_position`, fee vars, snapshot, 4 handlers); Flash; `load_transaction`; S-tests | R3 | 4–5 |
| R5 | Port part 2 | pricing; 6 interval updaters; `create_tick` + `TickPowTable` (F-POW); `update_tick_fee_vars_and_save`; Initialize/Mint/Burn/Swap incl. walk; S-tests | R4 | 7–9 |
| R6 | Runner | host set, waves, handler groups, `mapping_triggered`, FailClosed/EmitNonFatal, v2 creations (root genesis), JSONL report | R5 | 3–4 |
| R7 | Reference extractor + G2 | `reference_extractor` feature, F-W1/F-W1W2/F-W3 fixtures (needs the PR-S2 bundle and cassettes), `diff-frames`; iterate to zero diffs | R6, PR-S2 | 6–9 |
| R8 | State tiering + checkpoints | RedbBackend, LRUs, period eviction, burned demotion, checkpoint manifest/digest/export/import, G5 | R6 | 5–6 |
| R9 | Seed + time-travel | `graph-node-seed/v1` consumer; xtask `seed-capture` (read-only SQL); `PgOracleBackend`; xtask `timetravel-diff`; G3 | R8, D8 access, O4 | 6–8 |
| R10 | Performance | 3-stage pipeline (decode/calls ‖ handlers ‖ encode+validate+write); profiling; G6 | R8 | 3–4 |
| R11 | Engine integration | seeded-genesis v2 chunks, descriptor/profile binding, end-to-end through `state-replay`, G4; full-range dry run | R9, engine generic scaling | 4–6 |

**Total: about 52–68 engineer-days.** R1–R6 (24–30 days) can run before the extractor exists. R7 needs the mapping-host Aerodrome bundle. R9 needs SQL access. R11 needs the engine work.

---

## 16. Risks, open items, and coordination

**Risks:**
1. **Extractor completeness and wave correctness.** The reducer cannot see logs that are not candidates. Mitigation: the G2 extractor gate against `reference_extractor`; G3 completeness against `sgd2`; `receipt_log_count` and `pools_created` cross-checks.
2. **35-digit negative BigDecimal.** Hard dependency on R0. Every frame with a negative TVL product can trip it.
3. **Position state size.** Up to 79M ids at head (P3). The redb cold tier is sized at about 28 GB at head (ESTIMATE). It needs local NVMe on the reducer pod (D6).
4. **Engine generic scaling.** Seeded data-source genesis, a bounded generic state for 80M positions, a loader into a stopped clone, and PoI seed continuation. All are prerequisites for G4 and the production run (D3).
5. **`sgd2` history pruning (O4)** would remove G3 windows. Fallback: G2 on longer root windows plus seam-only G3.
6. **Unverified tx-type coverage on Base.** Types 3/4 and deposit `gas_price` presence in Firehose traces. F-TX settles it.
7. **Fee-on-transfer and rebasing tokens** drive negative TVL. That is covered by numerics, not semantics; G3 windows should include known cases.
8. **The "hand port drifts" history** (V3 lane, backfills #116). The difference here is two full oracles plus literal object-lifetime porting. No slice may merge with a G2 diff.

**Coordination items:**
- extractor design: proto §4.1, the C10 drop, `receipt_log_count`;
- engine design: seeded v2 genesis, generic seed artifact ownership, PoI continuation, non-fatal writer not required while FailClosed;
- mapping-host oracle agent: Aerodrome bundle, cassette recording for W1–W3, numerics corpus module, `BlockOpsBuilder` move.

---

## Appendix A: probe commands (read-only)

```sh
RPC=https://base.rpc.pinax.network/
call(){ curl -s -X POST -H 'content-type: application/json' --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"$1\",\"data\":\"$2\"},\"$3\"]}" $RPC; }
F=0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a; NPM=0x827922686190790b37229fd06084350e74485b72
call $F 0x9cbbbe86 0x2117760                 # tickSpacings() @34,700,000 -> [1,50,100,200,2000,10]  (P1)
call $F 0xefde4e64 0x2117760                 # allPoolsLength() -> 0x5d2 = 1,490                      (P2)
call $NPM 0x18160ddd 0x2117760               # totalSupply() -> 0x11f9aa = 1,178,026                  (P3)
call 0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59 0xf30dba93$(printf '%064x' 0) 0x2117760   # ticks(0): 320 bytes (P4)
call $NPM 0x99fbab88$(printf '%064x' 1) 0x2117760   # positions(1): "execution reverted: ID"                 (P4)
# eth_getCode 0x8fe8d9bb…/0x9663f2ca… -> "0x" (P5); eth_getTransactionReceipt 0x76aeccc2… -> log order (P6)
# eth_getLogs NPM Transfer(from=0) over the last ~200 blocks -> max tokenId 79,175,226 (P3)
# VictoriaMetrics P4169E866C3094E38:
#   max by (relname)(pg_stat_user_tables_n_live_tup{schemaname="sgd2",job="postgres-exporter-shard-b"})   (P7)
gh api 'repos/aerodrome-finance/slipstream/contents/contracts/core/CLFactory.sol?ref=ce33300ac4' --jq .content | base64 -d   (P8)
```

Selectors were computed with a scratch keccak helper at `scratchpad/reducer-probe/sel.py`.
