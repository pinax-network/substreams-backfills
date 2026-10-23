# Engine scaling design: generic BlockChanges families at full scale

Area: GENERIC engine scaling in `pinax-network/substreams-graph-node-backfill` so that a
`BlockChanges` family (Aerodrome Slipstream Base first, then Uniswap V3 mainnet) can be
backfilled from a seed at full scale and landed into a stopped Graph Node clone.

Date: 2026-10-20. Strictly read-only work: no commits, pushes, comments, kubectl writes or DB
writes. Read-only probes: Base RPC (`eth_blockNumber`, `eth_getLogs` ≤1000 blocks,
`eth_getBlockByNumber`), VictoriaMetrics, crates.io API.

Decisions this design implements (user, 2026-10-20, not relitigated): D1 route A+C; D3 reducer
placement = `BlockChanges` boundary (reducer in `substreams-backfills`, engine stays
family-neutral with generic scaling); D4 extractor in `substreams-backfills`; D5 call answers from
storage changes; seed = graphman copy of live `sgd2` at about 34.7M into a dedicated stopped store;
a root replay must remain possible for oracle windows.

## Labels and abbreviations

- **VERIFIED**: I read the code/data or ran the read-only query in this pass. File:line given.
- **REPORT-VERIFIED**: verified by a survey/audit agent (`survey/*.md`, audit `wathbfgwg.output`), cited.
- **ASSUMED**: design assumption not proven here; every ASSUMED item has a gate in §9.
- **ESTIMATE**: arithmetic from verified inputs.
- `ENG/` = engine snapshot `scratchpad/ro/engine` (origin/main `5c98b57`).
- `CMN/` = `ENG/third_party/backfill-common` (byte-identical to `SB/common` on `bbe3783`, REPORT-VERIFIED audit coverage notes).
- `SB/` = `/Users/denis/Github/substreams-backfills` (`bbe3783`).
- `GN:` = graph-node `77823b5a` (v0.44.0), read with `git show` from `~/.cargo/git/db/graph-node-40979021f9daae1a`.
- Audit IDs: `F1/transport`, `F1/state`, `F1/writers` … disambiguate the audit's reused IDs by dimension.

---

## 0. Decisions in one page

1. **Bounded state = declared retention classes + a disk store.** The descriptor (v2) declares, per
   entity type, `persistent`, `block_local` or `period_scoped`. The engine evicts `block_local`
   keys after each block and old periods of `period_scoped` keys, and enforces both claims with
   cheap exact guards (in-segment digest set, block-number-suffix proof, period monotonicity) plus
   an exact SQL overlap guard in the loader that also covers seed rows. Persistent entities live in
   a `redb` store (pure Rust, MIT/Apache-2.0) with **one write transaction per segment**,
   **reversible per-segment deltas** and **periodic deterministic snapshots**. Checkpoints shrink
   to a lineage reference (`BCGCKPT3`).
2. **Seed = `generic-seed-capture`**, a read-only Rust tool that writes a deterministic
   `BCGSNAP1` snapshot (format lives in `backfill-common`, so the reducer and the engine seed from
   the same bytes). Modes: `landing` (stopped clone at its exact head; per-table max VID with empty
   = −1; `Poi$` digest; all `data_sources$`), `oracle` (time travel at block B−1 on any non-pruned
   deployment, never loadable), `catalog` (live-catalog capture for a `production_selectable`
   profile).
3. **`data_sources$` = in-band.** `BlockChanges` gains `repeated CreatedDataSource
   created_data_sources = 9`, gated by a descriptor-v2 capability. No per-block companion, no
   10,000-block cap, works from a seed and through a pipe. The v1/v2 companions stay for the
   mapping-host root windows.
4. **Loader = `block-changes-load`**, native Rust over the PostgreSQL wire protocol (`postgres`
   crate, `COPY … FROM STDIN` via CopyIn, never a psql script). Identity comes from a reviewed
   per-family pin plus an operator-approved run binding. One atomic, range-bound, lock-guarded
   transaction per segment; a durable local journal; read-only recovery from a bounded
   fingerprint.
5. **Errors = stop before the first deterministic error and hand over to Graph Node.** The engine
   never fabricates `subgraph_error` rows: Graph Node error ids hash the exact message and handler
   (`GN:store/postgres/src/deployment.rs:901-937`), and `deployment.non_fatal_errors` is
   overwritten with the errors of the *write batch*, whose block span depends on Graph Node
   batching (`GN:store/postgres/src/deployment_store.rs:1166-1197`,
   `GN:graph/src/components/store/write.rs:839-856`, `GN:store/postgres/src/writable.rs:851-852`).
   Both VERIFIED. Stopping at N−1 lets Graph Node itself produce block N exactly, for fatal and
   non-fatal policies alike.
6. **Binding = descriptor v2 must declare deployment, spec version, start block and PoI version;
   the profile must agree**, PoI version must follow the spec rule (spec ≥ 0.0.6 → fast,
   `GN:core/src/subgraph/instance_manager.rs:487`, VERIFIED). Template-declaring profiles compile
   without the test-only acknowledgement; `data_sources$` is enforced at spool time instead.
7. **Performance:** engine compute target ≥ 150 blocks/s at Aerodrome density. The PostgreSQL load
   is the real bottleneck: V4 measured about 2,252 rows/s with all indexes (ESTIMATE from
   `ENG/docs/direct-postgres.md:130-133,149`), which is about 10 blocks/s for Aerodrome's ~220 row
   writes per block. A deferred-secondary-index slice targets ≥ 30–40 blocks/s.

---

## 1. Baseline facts this design builds on (all VERIFIED unless marked)

| # | Fact | Source |
|---|---|---|
| B1 | `GenericState.entities` is an in-memory `BTreeMap<MaterializedKey, Vec<EntityField>>` with no eviction | `ENG/src/generic_state.rs:379-390` |
| B2 | The baseline for every `SetEntity` re-merge is read from that map | `ENG/src/generic_state.rs:774-784` |
| B3 | Block-end persistence writes every persisted key into the map and records block-start originals | `ENG/src/generic_state.rs:591-602` |
| B4 | `entities()` clones the whole store; the spool seal calls it and serializes everything into `GenericCheckpoint` | `ENG/src/generic_state.rs:460-465`; `ENG/src/bin/state-replay.rs:2707`; `ENG/src/generic_checkpoint.rs:204-213` |
| B5 | The writer keeps every live version's `(vid, block_start)` in another in-memory map, and refuses a "new" entity whose key is still active | `ENG/src/sink.rs:1534`, `:2211-2296` |
| B6 | Fresh framed spools need the all-zero expected hash; resume only from own checkpoints | `ENG/src/bin/state-replay.rs:2466-2478` |
| B7 | v2 checkpoint validation requires contiguous error-free root history | `ENG/src/generic_checkpoint_v2.rs:41-58` |
| B8 | v2 source chunks are capped at 10,000 blocks and list every block | `CMN/src/dynamic_sources_v2.rs:14,194-204` |
| B9 | Deterministic errors are refused only when a sidecar/chunk is present; committed removes are always refused | `ENG/src/bin/state-replay.rs:2628-2647` |
| B10 | Template profiles are refused by `compile` without the test-only flag; that flag also unlocks hermetic profiles | `ENG/src/physical_writer.rs:519-555,583-590` |
| B11 | `DescriptorBinding` has no PoI or spec version; absent fields make no claim | `ENG/src/physical_writer.rs:476-488,695-712`; `ENG/src/bin/state-replay.rs:393-433` |
| B12 | Profile runtime binaries must be exactly `postgres-spool-load`, `state-replay`, `substreams-native` | `ENG/src/physical_profile.rs:19-20,772-783` |
| B13 | The only generic loader is the V3 root pilot (pinned root, 1,153 blocks, 256 MiB, Kan API server, embedded Python helper) | `ENG/src/v3_root_load.rs:20-25`; `ENG/src/bin/v3-root-load.rs:24-27` |
| B14 | The root pilot's SQL already has the right shapes: `IS DISTINCT FROM` guards, typed staging, range guard, explicit `data_sources$` VIDs, `ALTER SEQUENCE … RESTART`, head update clearing the cursor | `ENG/src/v3_root_load/transaction.rs:36-49,294-359,383` |
| B15 | The V4 seed capture writes `coalesce(max(vid), 0)` and hard-codes V4 tables | `ENG/scripts/capture-direct-postgres-seed.sh:27,83-121` |
| B16 | V4 already treats write-once types as block-local in its family reducer | `ENG/src/state.rs:250-265` |
| B17 | Descriptor `descriptor_version` must equal 1 | `CMN/src/block_changes.rs:58-64` |
| B18 | `BlockChanges` uses fields 1–8; `EntityOperation.operation` oneof uses 7–9 | `CMN/proto/block_changes.proto:8-36,76-80` |
| B19 | The V4 shadow descriptor pins the source bytes of ~60 engine files (generic_state.rs, state-replay.rs, sink.rs, Cargo.lock …) | `ENG/src/block_changes_descriptor.rs:46-130` |
| B20 | Graph Node uses advisory locks `(1, site)` copy, `(2, site)` write, `(3, site)` prune | `GN:store/postgres/src/advisory_lock.rs:10-13,76-78` |
| B21 | Graph Node `transact_block` pre-reads the head then updates it with no block filter | `GN:store/postgres/src/deployment.rs:469-535` |
| B22 | Graph Node normalizes BigDecimal on construction and on parse | `GN:graph/src/data/store/scalar/bigdecimal.rs:31-35,121-126` |
| B23 | PoI resume: `PoiAccumulator::resumed(region, version, Some(digest))`; the writer clamps the active `Poi$` version | `ENG/src/poi.rs:158-164`; `ENG/src/sink.rs:2090-2128` |
| B24 | Registry/assignment tables on the primary: `deployment_schemas(name, shard, active)`, `subgraph_deployment_assignment(node_id, paused_at)` | `GN:store/postgres/src/primary.rs:105-145` |
| B25 | Engine deps have no KV store; `rmp-serde`, `memmap2`, `sha2`, `stable-hash-legacy` present; toolchain 1.90.0; license Apache-2.0 | `ENG/Cargo.toml:5,15-49`; `ENG/rust-toolchain.toml` |

Live numbers (VERIFIED this pass, 2026-10-20):

- Base head `0x326b81a` = 52,869,146 (Pinax Base RPC `eth_blockNumber`).
- Aerodrome NPM mint `Transfer(from=0)` logs: blocks 34,727,000–34,727,999: **2,385 mints, max tokenId 23,689,709**; blocks 52,867,000–52,867,999: **4,027 mints, max tokenId 79,171,592** (`eth_getLogs`, NPM `0x8279…5b72`).
- Block 34,728,090: timestamp 1,756,245,527 (day 20,326, hour 487,845). Block 13,843,704: timestamp 1,714,476,755.
- `pg_deployment_status_failed{schema="sgd2",health="healthy"} = 0`, `pg_deployment_status_head_block{schema="sgd2"} = 34,730,219`, `deployment_head = 34,730,290`, `deployment_status = 2` on `graph-node-chain-base-0` (VictoriaMetrics `P4169E866C3094E38`). So `sgd2` has **no recorded deterministic errors** over 13.84M–34.73M.

---

## 2. Bounded generic state (design item 1)

### 2.1 Why the current store cannot scale (ESTIMATE from VERIFIED inputs)

- `sgd2` holds about 1.32B row versions; the write-once types (Transaction, Swap, Mint, Burn,
  PositionSnapshot) are ≥ 385M live entities (REPORT-VERIFIED `survey/v3-lane-state.md` §3.3).
  The generic store keeps them all (B1) and rewrites them into every checkpoint (B4).
- Even after eviction, **Position dominates**: the NPM had minted up to tokenId 23,689,709 by
  the seed and 79,171,592 by head (VERIFIED above). Positions are never removed and can be
  touched at any later block, so they are genuinely persistent. Upper bound: about 24M persistent
  Position entities at the seed and about 79M at the target. (Positions minted and burned in the
  same block never become entities, because `try_positions` reverts at block end,
  REPORT-VERIFIED `survey/aerodrome-target.md` §5.6.) A memory-only store is therefore wrong even
  for the evicted design; a disk store is required.

### 2.2 Retention classes (descriptor v2 section `entity_retention`)

The producer declares the classes; the engine enforces them. The section lives in the descriptor
because it is a claim about mapping semantics, and the descriptor SHA-256 is the frame
`compatibility_id`, so changing a class changes the frame identity.

```json
"entity_retention": {
  "version": 1,
  "default": "persistent",
  "types": {
    "Transaction":      {"class": "block_local",   "proof": {"kind": "derived_from_transaction"}},
    "Swap":             {"class": "block_local",   "proof": {"kind": "derived_from_transaction"}},
    "Mint":             {"class": "block_local",   "proof": {"kind": "derived_from_transaction"}},
    "Burn":             {"class": "block_local",   "proof": {"kind": "derived_from_transaction"}},
    "PositionSnapshot": {"class": "block_local",   "proof": {"kind": "block_number_suffix", "separator": "#"}},
    "UniswapDayData":   {"class": "period_scoped", "period_id": {"kind": "whole_id"}},
    "PoolDayData":      {"class": "period_scoped", "period_id": {"kind": "suffix_after_last", "separator": "-"}},
    "PoolHourData":     {"class": "period_scoped", "period_id": {"kind": "suffix_after_last", "separator": "-"}},
    "TokenDayData":     {"class": "period_scoped", "period_id": {"kind": "suffix_after_last", "separator": "-"}},
    "TokenHourData":    {"class": "period_scoped", "period_id": {"kind": "suffix_after_last", "separator": "-"}},
    "TickDayData":      {"class": "period_scoped", "period_id": {"kind": "suffix_after_last", "separator": "-"}}
  },
  "evidence": [
    {"kind": "store_get_inventory", "reference": "SB/aerodrome-slipstream-base/evidence/store-access-inventory.json", "sha256": "<hex>"},
    {"kind": "id_scheme_inventory", "reference": "SB/aerodrome-slipstream-base/evidence/id-schemes.json", "sha256": "<hex>"}
  ]
}
```

Semantics (normative):

- **`persistent`** (default): image plus active `(vid, block_range_start)` are kept in the store.
- **`block_local`**: the key may be saved any number of times within one block and is **never
  read or written in a later block**. After the block, the engine drops the image and does not
  register the version as active; its row stays open forever, as Graph Node leaves it.
  - `derived_from_transaction`: the ID is derived from a transaction hash (tx hash, or
    `{tx}#{n}`). The engine cannot verify membership; it relies on guards G1/G3 below.
  - `block_number_suffix{separator}`: the ID must end with `{separator}{block_number}` in decimal.
    **Verified exactly** on every Set.
- **`period_scoped{period_id}`**: the ID carries an unsigned decimal period. The period of every
  write of the type is a non-decreasing function of the block (it is computed from the block
  timestamp, and Base timestamps increase). Only keys at the type's current maximum period are
  retained; older periods are evicted at block end. `suffix_after_last{sep}` = digits after the
  last `sep` (handles `{pool}#{-tick}-{day}`); `whole_id` = the whole ID is the period.

Aerodrome assignment and evidence (REPORT-VERIFIED `survey/aerodrome-target.md` §4 store-access
inventory and ID-scheme table; decompile citations there):

| Type | ID scheme | Read back in a later block? | Class |
|---|---|---|---|
| Transaction | tx hash | `store.get` only by `loadTransaction` for the current event's tx | block_local (tx) |
| Swap / Mint / Burn | `{tx}#{pool.txCount}` | never a `store.get` target | block_local (tx) |
| PositionSnapshot | `{pos}#{block}` | never | block_local (block suffix `#`) |
| UniswapDayData | `{dayID}` | only current day | period_scoped (whole_id) |
| Pool/Token Day/Hour, TickDayData | `{x}-{period}` | only current period | period_scoped (`-`) |
| Factory, Bundle, Token, Pool, Tick, Position | stable | yes | persistent |
| Collect, Flash, TickHourData | never written | n/a | persistent (default, empty) |

A Swap/Mint/Burn ID can repeat *within* one block (two pools with the same `txCount` in one tx);
that is a same-block overwrite, coalesced like any in-block save, and does not break the claim.

### 2.3 Enforcement (no silent false negatives)

| Guard | Where | Cost | Catches |
|---|---|---|---|
| G1 in-segment digest set | engine, per Set of a `block_local` key not already in the current block overlay | one SHA-256 (truncated to 128 bits) per key; ≤ ~0.5 GiB per 100k-block segment (ESTIMATE 15M keys × 32 B) | re-save of a block-local key in a later block of the same segment |
| G2 block-suffix proof | engine, per Set of a `block_number_suffix` type | string compare | IDs not scoped to the block (exact) |
| G3 overlap guard | loader, inside the segment transaction | one index probe per inserted row on the `attr_*_id` btree | any two overlapping versions of one ID across seed, earlier segments and this segment (exact) |
| G4 period monotonicity | engine | parse + compare | write to an evicted (older) period, unparsable period |
| G5 materialized cross-check (existing) | engine, `GenericState` re-merge | already paid | a producer that *reads* an evicted key and writes a partial update: the engine baseline is absent, so `materialized` mismatches (B2) |
| G6 terminal duplicate audit (optional) | certification SQL over full tables | one pass per table | belt and braces |

What is not caught: a producer that *reads* a block-local key from an earlier block and uses it
without writing it. That is reducer semantics, covered by the oracle gates (§9 G-ORACLE).

Why not a Bloom filter or an on-disk ID index in the engine: the cross-segment key set is about
18.1M blocks × ~90 block-local rows ≈ 1.6B keys for the seeded range (ESTIMATE), i.e. ~2–4 GiB of
Bloom bits at 1e-2…1e-4 false-positive rates, or ~26 GiB for an exact 128-bit index that must be
merged every segment. Neither covers the **seed's** ~400M existing block-local rows, which the
engine never sees. The loader's guard G3 is exact, covers seed rows and earlier segments, and
costs one btree probe per inserted row inside a transaction that already pays far more for index
maintenance. The engine keeps only the cheap in-segment set (G1) for early, precise failure.

Refusal types (new `GenericStateError` variants): `BlockLocalRewrite { block, entity_type, id }`,
`BlockLocalProofViolation { block, entity_type, id, separator }`, `PeriodRegression { block,
entity_type, id, period, current_max }`, `UnparsablePeriod { block, entity_type, id }`.

### 2.4 Disk store

**Choice: `redb = "=4.3.0"`** (VERIFIED crates.io: published 2026-09-15, MIT OR Apache-2.0,
`rust_version` 1.90 = engine toolchain). Pure Rust, single file, ACID, MVCC, crash-safe commits,
no C/C++ toolchain in the x86-64-v3 Docker stages.

| Candidate | License (VERIFIED crates.io) | Why not |
|---|---|---|
| `rocksdb =0.25.0` | Apache-2.0 | C++ build in every Docker stage and CI lane; the engine CI already runs ~15 OCI variants (memory note) |
| `fjall =3.1.12` | MIT OR Apache-2.0 | LSM, fine, but the workload is random point reads + in-place updates; no advantage |
| `heed =0.22.1` (LMDB) | MIT (LMDB C) | C dependency, fixed map size |
| `sled 1.0.0-alpha` | MIT OR Apache-2.0 | alpha since 2024 |

The redb file is a **cache, not evidence**: its page layout is not deterministic, so nothing pins
its bytes. Evidence is the deterministic snapshot and delta files (§2.6), and the store can always
be rebuilt from them.

**Tables:**

| redb table | Key | Value |
|---|---|---|
| `entities` | `StoreKey` bytes | `StoredEntity` bytes |
| `period_index` | `u16 type ordinal ‖ u64 period BE ‖ id` | `()` (lets eviction and restart find a period's keys by range scan) |
| `sources` | `u32 manifest_idx BE ‖ param bytes ‖ context_sha256?` | `u64 creation ordinal ‖ i32 creation_block ‖ i32 vid` |
| `meta` | `&str` | MessagePack (see below) |

Encodings (normative, deterministic):

```rust
/// Key bytes: [type_ordinal: u16 BE][causality_region: i32 BE ^ 0x8000_0000][id kind: u8][id bytes]
/// type_ordinal = index in the descriptor's sorted `storage_profile.entity_types`.
/// id kind 0 = String (UTF-8), 1 = Bytes, 2 = Int8 (i64 BE ^ sign bit).
pub struct StoreKey(pub SmallVec<[u8; 64]>);

/// Value bytes: [format: u8 = 1][vid: i64 BE][block_range_start: i32 BE][EntityFields prost bytes]
/// The EntityFields bytes are exactly `encode_canonical` of the materialized field list, so the
/// image round-trips byte-for-byte with frames (reuses CMN prost bindings).
pub struct StoredEntity {
    pub vid: i64,
    pub block_range_start: i32,
    pub fields: Vec<EntityField>,
}
```

`meta` keys: `format` = `"pinax.graph-node.generic-state-store/v1"`, `binding`
(`GenericCheckpointBinding` + `retention_sha256` + `type_ordinals`), `boundary` `{block, hash}`,
`lineage` (32 bytes), `base_snapshot` (`SnapshotRef`), `deltas_since_base` (`Vec<FilePin>`),
`totals` (`GenericCheckpointTotals`), `poi` (`GenericPoiState`), `table_max_vids`
(`BTreeMap<String, i64>`), `sources` (`SourceCommitment`), `period_max` (`BTreeMap<String, u64>`).

**Cache:** `Builder::set_cache_size(BACKFILL_STATE_CACHE_BYTES)` (default 16 GiB) plus a small
decoded hot cache (CLOCK, default 1M entries) of `Arc<StoredEntity>` for singletons and hot
Pools/Tokens. ASSUMED: redb keeps the memory of a large write transaction bounded by its cache
settings by spilling dirty pages to the file. Gate G-STORE-4 measures it; the fallback is a
smaller segment size.

### 2.5 Segment protocol (one write transaction per segment)

```
open store; require meta.lineage == predecessor.state.lineage_after   (else §2.7 recovery)
txn = store.begin_write()
for each frame:
    persisted = GenericState::apply_block(frame)            // baselines via txn reads + hot cache
    guards G1/G2/G4                                          // refuse before any write
    versions  = writer.apply_generic_block(block, &persisted) // rows, clamps, new vids
    for each persisted persistent/period key k:
        if first touch of k in this segment: undo.append(k, txn.get(k))   // before-image spill
        txn.put(k, StoredEntity{vid, start, fields}) or txn.delete(k)
    period eviction: for each type whose max period advanced: delete keys of older periods
                     (undo.append before delete); maintain period_index
    in-band sources (§4): txn.sources.insert(identity) (refuse duplicate); writer.data_sources_row
    PoI: writer.apply_poi(...)
end of stream:
    range.finish()                                           // clock-v1 completeness (existing)
    delta = write_delta(sorted touched keys: (key, before from undo spill, after from txn))
    fsync delta into state/deltas/<to_block>-<sha>.bcgdelt; fsync dir
    write BCGCKPT3 + manifest (v3) into <out>.building; seal spool READY (existing publish)
    txn.meta := {lineage_after, boundary, totals, poi, vids, sources, period_max, deltas+=delta}
    txn.commit(Durability::Immediate)
```

Crash matrix (all VERIFIED-by-construction from the ordering above; redb atomicity ASSUMED as a
documented redb property, gate G-STORE-2):

| Crash point | Store lineage | Spool | Recovery |
|---|---|---|---|
| before delta fsync | L(k−1) | absent | recompute segment k |
| after delta, before READY | L(k−1) | `.building` | delete `.building` and the unreferenced delta; recompute (deterministic, same bytes) |
| after READY, before commit | L(k−1) | READY k | **roll forward**: apply delta k redo after checking every before-image equals the store |
| after commit | L(k) | READY k | resume at k+1 |

Writes for `block_local` keys never touch the store. Delta size ESTIMATE for Aerodrome: about
1–2M distinct persistent keys per 100k blocks × ~1.6 KB (before+after) ≈ 2–3 GiB.

### 2.6 Deterministic files and lineage

All three formats are MessagePack with struct maps behind an 8-byte magic, like
`GenericCheckpoint` (`ENG/src/generic_checkpoint.rs:1-30`). Record streams are sorted by key bytes,
so two replays of the same range produce byte-identical files.

**`BCGSNAP1` snapshot** (format and reader/writer in `CMN/src/state_snapshot.rs`, shared with the
reducer):

```rust
pub struct SnapshotHeader {
    pub format: String,              // "pinax.graph-node.generic-state-snapshot"
    pub version: u32,                // 1
    pub binding: SnapshotBinding,    // deployment, network, descriptor_sha256, retention_sha256,
                                     // type_ordinals: Vec<String>, entity_id_policy
    pub boundary: Boundary,          // block_number u64, block_hash [u8;32] (zeros for an empty root)
    pub origin: SnapshotOrigin,      // EmptyRoot{start_block} | Landing(SeedOrigin) |
                                     // Oracle(SeedOrigin) | Compaction{base_lineage, through_lineage}
    pub vid: Option<VidState>,       // None for Oracle (VIDs not meaningful)
    pub poi: GenericPoiState,        // region digest + active Poi$ version (vid, start, id, digest)
    pub sources: SourceSnapshot,     // count, order_sha256, max_vid, rows: Vec<SnapshotSource>
    pub period_max: BTreeMap<String, u64>,
    pub entity_count: Option<i64>,   // subgraphs.head.entity_count at the seed
    pub records: u64,                // number of entity records that follow
}
pub struct SeedOrigin {
    pub schema: String, pub site_id: i32, pub database: String,
    pub system_identifier: String, pub server_version_num: u32,
    pub capture_tool_sha256: String, pub profile_sha256: String,
    pub head: Boundary, pub health: String, pub non_fatal_errors: Vec<String>,
}
pub struct VidState { pub tables: Vec<TableVid> }
pub struct TableVid {
    pub entity_type: String, pub postgres_table: String,
    pub max_vid: i64,                 // coalesce(max(vid), -1)
    pub sequence_last_value: i64, pub sequence_is_called: bool,
    pub active_rows: Option<u64>,     // when --verify-entity-count
}
pub struct SnapshotSource {          // one data_sources$ row
    pub vid: i32, pub creation_block: i32, pub manifest_idx: i32, pub param: Vec<u8>,
}
// body: `records` × (key: StoreKey bytes, value: StoredEntity bytes), sorted by key
// trailer: b"BCGSEND1" ‖ records u64 BE ‖ sha256(all preceding bytes)
```

**`BCGDELT1` delta** (engine-only, `ENG/src/state_store/delta.rs`):

```rust
pub struct DeltaHeader {
    pub format: String,              // "pinax.graph-node.generic-state-delta"
    pub version: u32,                // 1
    pub binding_sha256: String,      // sha256 of canonical SnapshotBinding
    pub from: Boundary, pub to: Boundary,
    pub lineage_before: [u8; 32],
    pub meta_before: StoreMeta, pub meta_after: StoreMeta,   // totals, poi, vids, sources, period_max
    pub sources_added: Vec<SnapshotSource>,
    pub records: u64,
}
// body: sorted (key, before: Option<StoredEntity>, after: Option<StoredEntity>)
```

**Lineage:** `L0 = sha256("pinax.generic-state-lineage/v1\0" ‖ [0;32] ‖ sha256(snapshot file))`;
`Lk = sha256("pinax.generic-state-lineage/v1\0" ‖ L(k−1) ‖ sha256(delta_k file))`. A compaction
snapshot taken at Lk carries `origin = Compaction{base_lineage, through_lineage = Lk}` and does
not restart the chain: `Lk` stays the identity, the snapshot is just a faster way to reach it.

**`BCGCKPT3` checkpoint** (the spool's `checkpoint.generic.pending`, small, `ENG/src/generic_checkpoint_v3.rs`):

```rust
pub struct GenericCheckpointV3 {
    pub format: String,                       // "pinax.graph-node.block-changes-checkpoint"
    pub version: u32,                         // 3
    pub binding: GenericCheckpointBinding,    // + retention_sha256: Option<String>, start_block: Option<u64>
    pub boundary: GenericCheckpointBoundary,
    pub totals: GenericCheckpointTotals,
    pub poi: GenericPoiState,
    pub table_max_vids: BTreeMap<String, i64>,
    pub sources: SourceCommitment,            // count u64, order_sha256, max_vid i32
    pub state: StateLineage,
    pub period_max: BTreeMap<String, u64>,
    pub stop: Option<StopBeforeError>,        // §5.7
}
pub struct StateLineage {
    pub base: SnapshotRef,                    // lineage + FilePin of the snapshot the chain starts at
    pub lineage_before: String, pub lineage_after: String,
    pub delta: FilePin,
    pub retained_entities: u64,
    pub retained_by_type: BTreeMap<String, u64>,
}
pub struct SourceCommitment { pub count: u64, pub order_sha256: String, pub max_vid: i32 }
```

The spool manifest becomes version 3 (`BLOCK_CHANGES_SPOOL_FORMAT`, `ENG/src/sink.rs:1317`) and
adds `state: StateLineage`, `data_sources_in_band: Option<InBandSourceProvenance { rows,
before: SourceCommitment, after: SourceCommitment }>`, `stop: Option<StopBeforeError>` and
`producer_identity: Option<GenericProducerIdentity>` (§5.8). Versions 1 and 2 are unchanged.

### 2.7 Resume, rollback and rebuild

`generic-state` (new bin) owns the store; `state-replay` only opens it.

| Situation at open | Action |
|---|---|
| `meta.lineage == predecessor.lineage_after` | resume |
| `meta.lineage == predecessor.lineage_before` and READY predecessor with its delta present | `generic-state roll-forward` (redo, verifying before-images), then resume |
| `meta.lineage` is a *later* lineage whose spools are not loaded (journal says so) | `generic-state rewind --to <lineage>` (undo deltas newest first, verifying after-images) |
| store missing/corrupt, or `generic-state verify` fails | `generic-state rebuild --snapshot <latest ≤ target> --deltas …` |
| anything else | refuse; the operator decides |

The driver never rewinds below the database head recorded in the load journal (§5.5).
`generic-state snapshot` writes a compaction snapshot every `--snapshot-every` segments (default
10) and garbage-collects deltas older than the newest snapshot that precedes the journal's
committed head.

`generic-state verify` recomputes a logical digest over the whole store
(`sha256` over sorted `(key, value)`) and compares it with a full snapshot written at the same
lineage; it is an expensive certification step, not per segment.

### 2.8 Code changes and signatures

New engine modules:

```
src/state_store/mod.rs        trait EntityStore, StoreKey, StoredEntity, StoreError
src/state_store/memory.rs     MemoryEntityStore (tests, state-only mode, small families)
src/state_store/redb.rs       RedbEntityStore, SegmentTxn
src/state_store/delta.rs      BCGDELT1 writer/reader, undo spill
src/state_store/retention.rs  RetentionGuard (G1/G2/G4), period bookkeeping
src/generic_checkpoint_v3.rs  BCGCKPT3
src/bin/generic-state.rs      init | roll-forward | rewind | snapshot | rebuild | verify | stats
```

```rust
pub trait EntityStore {
    /// Block-start image and active version of an onchain key.
    fn get(&mut self, key: &MaterializedKey) -> Result<Option<Arc<StoredEntity>>, StoreError>;
    fn put(&mut self, key: &MaterializedKey, value: StoredEntity) -> Result<(), StoreError>;
    fn delete(&mut self, key: &MaterializedKey) -> Result<(), StoreError>;
    fn keys_in_period(&mut self, entity_type: &str, period: u64)
        -> Result<Vec<MaterializedKey>, StoreError>;
    fn source_exists(&mut self, identity: &SourceIdentity) -> Result<bool, StoreError>;
    fn insert_source(&mut self, identity: SourceIdentity, row: SourceRow) -> Result<(), StoreError>;
}

pub struct GenericState<S: EntityStore> { id_policy: EntityIdPolicy, store: S,
    retention: Arc<RetentionPolicy>, guard: RetentionGuard, last_block: Option<u64> }

pub struct PersistedKey {
    pub key: MaterializedKey,
    pub class: RetentionClass,
    pub original: Option<Arc<StoredEntity>>,     // block-start, with the active vid
    pub final_fields: Option<Vec<EntityField>>,  // None = committed remove (still refused by the writer)
}
pub struct BlockApply {
    pub outcome: BlockOutcome,
    pub committed: Vec<CommittedSet>,            // unchanged
    pub persisted: Vec<PersistedKey>,            // replaces block_originals
    pub created_sources: Vec<CreatedDataSource>, // §4
    pub first_deterministic_error: Option<u64>,  // operation index, for §5.7
}
impl<S: EntityStore> GenericState<S> {
    pub fn apply_block(&mut self, changes: &BlockChanges) -> Result<BlockApply, GenericStateError>;
    pub fn commit_block(&mut self, block: u64, persisted: Vec<PersistedKey>,
                        versions: &[VersionOutcome]) -> Result<(), GenericStateError>;
}

// ENG/src/sink.rs
pub enum VersionOutcome { Unchanged, NewVersion { vid: i64, block_start: i32 } }
impl StreamingDumpBuilder {
    /// Generic path without the in-memory `active` map: the current vid comes from
    /// `PersistedKey::original`. Block-local keys are written and never registered.
    pub fn apply_generic_block(&mut self, block: i32, persisted: &[PersistedKey])
        -> Result<Vec<VersionOutcome>, SinkError>;
    pub fn new_with_profile_store(profile: Arc<SelectedPhysicalProfile>, spool_dir: &Path,
        table_max_vids: BTreeMap<String, i64>, poi_seed: Option<PoiVersion>,
        sources_max_vid: i32) -> Result<Self, SinkError>;
}
```

Also in this area (closing audit `F2/state`): when a key absent at block start is persisted,
strip top-level `Null` fields from the stored image (mirror Graph Node's `as_modifications`;
REPORT-VERIFIED `GN:graph/src/components/store/entity_cache.rs:486-490` in the audit), keeping
in-block visibility unchanged.

`state-replay` flags (all require `--input-format block-changes-v1-framed --postgres-spool-output`):

- `--state-store <dir>`: enables the v3 path; refuses `--input-generic-checkpoint`,
  `--data-sources-sidecar`, `--data-sources-chunk`.
- `--seed-snapshot <file.bcgsnap>`: first segment; the store must be `init`-ed from it
  (`meta.lineage == L0(snapshot)`), and `--expected-head-block/hash` must equal its boundary.
- `--input-generic-spool <prev.ready>`: subsequent segments (v3 predecessor).
- `--on-deterministic-error refuse|stop-before` (default `refuse`).

### 2.9 Sizing for Aerodrome (ESTIMATE)

| Item | At seed (~34.7M) | At target (~52.9M) |
|---|---|---|
| Persistent entities | ~25–28M (Positions ≤ 23.7M, Ticks ~1–3M, Pools 1,501, Tokens ~3k, current-period rows ≤ ~0.2M) | ~80–85M |
| redb file | ~25–35 GiB | ~85–110 GiB |
| Snapshot file | ~20–25 GiB | — |
| Delta per 100k blocks | — | ~2–3 GiB |
| COPY spool per 100k blocks | — | ~9–12 GiB (≈150 rows/block × ~600 B) |

Work PVC: ≥ 500 GiB NVMe (store + 10 deltas + 1 snapshot + 2 spools + headroom).

---

## 3. Seed capture from a Graph Node schema (design item 2)

### 3.1 Tool

`generic-seed-capture` (new Rust bin, `ENG/src/bin/generic-seed-capture.rs`, library in
`ENG/src/seed_capture/`). It uses the `postgres` crate (`=0.19.14`, VERIFIED crates.io:
2026-06-12, MIT OR Apache-2.0, `rust_version` 1.85; `Client::copy_out` / `copy_in` /
`transaction` VERIFIED in `postgres-0.19.12/src/client.rs:407,435,515` from the local cargo cache).
No TLS feature (in-cluster plaintext, matching the existing `PGHOST` usage). Connection from
`PG*` environment variables, never argv.

```
generic-seed-capture landing --descriptor D --profile P --schema sgdN \
    --expected-head-block B --expected-head-hash H --output seed.bcgsnap [--verify-entity-count]
generic-seed-capture oracle  --descriptor D --profile P --schema sgdM \
    --at-block B --at-block-hash H --output oracle-B.bcgsnap
generic-seed-capture catalog --profile-template P0 --schema sgdN --output catalog.json
```

### 3.2 Exact SQL (landing mode)

Everything runs in **one** session and one snapshot (unlike the V4 per-page transactions,
`ENG/scripts/export-active-seed-page.sql:6`):

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '6h';
SET LOCAL lock_timeout = '5s';
SET LOCAL search_path = pg_catalog;
SET LOCAL bytea_output = 'hex';
SET LOCAL "DateStyle" = 'ISO, YMD';
SET LOCAL "TimeZone" = 'UTC';
SET LOCAL extra_float_digits = 3;

-- Q0 identity + writer exclusion for the whole capture (held to COMMIT)
SELECT current_database(),
       (SELECT system_identifier::text FROM pg_control_system()),
       current_setting('server_version_num')::int,
       pg_try_advisory_xact_lock(2, $site) AS write_lock,
       pg_try_advisory_xact_lock(1, $site) AS copy_lock,
       pg_try_advisory_xact_lock(3, $site) AS prune_lock;
-- refuse unless all three are true

-- Q1 deployment metadata
SELECT d.id, d.subgraph, d.health::text, d.failed, d.fatal_error, d.non_fatal_errors,
       d.graft_base, d.graft_block_number, encode(d.graft_block_hash, 'hex'),
       d.earliest_block_number, d.reorg_count, d.current_reorg_depth,
       d.synced_at IS NOT NULL, d.postponed_indexes_created,
       h.block_number, encode(h.block_hash, 'hex'), h.entity_count, h.firehose_cursor IS NOT NULL,
       m.spec_version, m.features, m.start_block_number, encode(m.start_block_hash, 'hex'),
       m.history_blocks, m.use_bytea_prefix, m.entities_with_causality_region,
       encode(sha256(convert_to(m.schema, 'UTF8')), 'hex'),
       encode(sha256(convert_to(coalesce(m.raw_yaml, ''), 'UTF8')), 'hex'),
       v.crate_version, v.git_commit_hash
  FROM subgraphs.deployment d
  JOIN subgraphs.head h ON h.id = d.id
  JOIN subgraphs.subgraph_manifest m ON m.id = d.id
  LEFT JOIN subgraphs.graph_node_versions v ON v.id = m.graph_node_version_id
 WHERE d.id = $site;
SELECT count(*) FROM subgraphs.subgraph_error WHERE subgraph_id = $deployment;
SELECT count(*) FROM pg_namespace WHERE nspname = 'sgd' || $site::text;
```

Refusals after Q1: subgraph ≠ pinned deployment; `(h.block_number, h.block_hash)` IS DISTINCT
FROM `(B, H)` (a NULL head is refused, closing the DB-6 class for seeds); `failed`; `health` not
`healthy` unless `--accept-health unhealthy --accept-non-fatal-errors <ids>` (used only after a
§5.7 handover); graft fields ≠ profile; `spec_version` ≠ profile; `start_block_number` ≠
`descriptor.start_block − 1`; subgraph_error count ≠ the accepted count. `history_blocks` and the
creating Graph Node version are recorded as evidence.

```sql
-- Q2 catalog (port of ENG/scripts/v3-milestone.py:397-432 to Rust, same projection), then
--    PhysicalSchemaProfile::validate_observed_catalog (ENG/src/physical_profile.rs:829-850).

-- Q3 per profile table T (entity, poi2$, data_sources$):
SELECT coalesce(max(vid), -1) FROM "sgdN"."T";                -- PK index, O(log n); empty = -1
SELECT last_value, is_called FROM "sgdN"."T_vid_seq";          -- data_sources$_vid_seq included
-- with --verify-entity-count (full scan, one time):
SELECT count(*) FROM "sgdN"."T" WHERE upper_inf(block_range);

-- Q4 persistent entity table T (columns = profile copy columns in physical order):
COPY (SELECT vid, lower(block_range), <c1>, …, <cn>
        FROM "sgdN"."T" WHERE upper_inf(block_range)) TO STDOUT WITH (FORMAT csv, NULL '\N');

-- Q5 period_scoped table T, suffix rule (whole_id uses '^([0-9]+)$'):
SELECT count(*) FROM "sgdN"."T"
 WHERE upper_inf(block_range) AND substring(id FROM '-([0-9]+)$') IS NULL;   -- must be 0
COPY (WITH a AS (SELECT t.*, substring(t.id FROM '-([0-9]+)$')::numeric AS p
                   FROM "sgdN"."T" t WHERE upper_inf(t.block_range))
      SELECT vid, lower(block_range), <c1>, …, <cn> FROM a
       WHERE p = (SELECT max(p) FROM a)) TO STDOUT WITH (FORMAT csv, NULL '\N');

-- Q6 Poi$
SELECT vid, lower(block_range), id, encode(digest, 'hex')
  FROM "sgdN"."poi2$" WHERE upper_inf(block_range);           -- 0 rows, or 1 row with id = region

-- Q7 data_sources$
SELECT vid, lower(block_range), upper_inf(block_range), causality_region, manifest_idx,
       parent, id IS NULL, encode(param, 'hex'), context IS NULL, done_at
  FROM "sgdN"."data_sources$" ORDER BY lower(block_range), vid;
COMMIT;
```

`block_local` tables get only Q3. Q7 refusals: any row with `causality_region ≠ 0`, `parent`,
`id`, `context` or `done_at` non-NULL, not `upper_inf`, `octet_length(param) ≠ 20`, or a
`manifest_idx` that is not a descriptor template (Aerodrome: `Pool` = 2, ASSUMED from manifest
order Factory, NPM, Pool, the same shape the V3 root pins at `ENG/src/v3_root_load/transaction.rs:353`;
Q7 verifies it on real rows).

**Oracle mode** replaces every `upper_inf(block_range)` with `block_range @> $B`, adds
`lower(block_range) <= $B` to Q7, skips the head and VID/sequence guards, sets `vid = None` and
`origin = Oracle`. The loader refuses an oracle snapshot by origin. Oracle mode needs a
non-pruned source (`history_blocks = 2147483647`; for `sgd2` this is OPEN item O4).

### 3.3 Decoding rows into images, with a round-trip proof

For each Q4/Q5 row: column text → typed cell by the profile's `value_kind` and GraphQL type →
`GraphValue` → `EntityField` list (NULL columns omitted, `id` included, as Graph Node loads them,
REPORT-VERIFIED audit F2/state). BigDecimal is re-normalized with the engine's bigdecimal 0.1.2
model (`ENG/src/decimal.rs`), matching B22.

Proof per row (fail closed): re-encode the decoded image with `SelectedPhysicalProfile::encode`
(`ENG/src/physical_writer.rs`, `encode`) and compare **typed cells** with the parsed PostgreSQL
cells: timestamps as microseconds, bytea as bytes, arrays element-wise, and numeric **textually**:
the stored text must already equal the canonical rendering of the normalized value (Graph Node
writes normalized values, B22). A stored non-normalized numeric is refused rather than normalized
away, honouring "do not weaken equality checks by … normalizing decimals" (`ENG/AGENTS.md:65-66`).
A mismatch names table, VID and column. This proves the image is a faithful inverse of exactly what
Graph Node stored, for every column kind present.

### 3.4 Output

`seed.bcgsnap` (§2.6) plus `seed.json`:

```json
{"format": "pinax.graph-node.generic-seed-receipt", "version": 1,
 "snapshot": {"file": "seed.bcgsnap", "bytes": 0, "sha256": "…", "lineage": "…"},
 "deployment": "Qm…", "schema": "sgdN", "site_id": 0, "database": "graph",
 "system_identifier": "…", "head": {"block": 0, "hash": "…"}, "entity_count": 0,
 "tables": [{"entity_type": "Position", "class": "persistent", "max_vid": 0,
             "sequence": {"last_value": 0, "is_called": true}, "captured_rows": 0}],
 "poi": {"vid": 0, "block_range_start": 0, "digest": "…"},
 "data_sources": {"rows": 1501, "max_vid": 0, "order_sha256": "…"},
 "catalog_sha256": "…", "profile_sha256": "…", "descriptor_sha256": "…",
 "durations_ms": {"q4_position": 0}}
```

Then `generic-state init --snapshot seed.bcgsnap --state-store <dir>` builds the redb store. The
reducer seeds from the same file (§12).

V4 one-line fix in the same slice: `ENG/scripts/capture-direct-postgres-seed.sh:113-114`
`coalesce(max(vid), 0)` → `-1`, with an empty-table case in `test-capture-direct-postgres-seed.sh`
(closes POI-VID-3 / DB-5 for V4 too).

---

## 4. `data_sources$` beyond 10,000 blocks: in-band creations (design item 3)

### 4.1 Decision

Carry creations **in the frame**. Rejected alternatives:

- **Extend companion v2 to arbitrary lengths.** It lists every block with its hash and payload
  digest (B8), so a 100k-block segment needs ≥ 100k JSON records; it must be complete before the
  engine reads the stream, which forbids `reducer | state-replay` pipelining; it is root-only
  (B7).
- **Streaming companion v3** (only creations + a stream digest). Removes the per-block cost but
  still needs two synchronized artifacts and a second output from the reducer.

In-band is one artifact, ordered, bounded by the frame size limit, and natural for Graph Node:
`dynds::insert` persists `Batch::data_sources` in order in the same transaction as entities
(`GN:store/postgres/src/deployment_store.rs:1166`, VERIFIED).

### 4.2 Proto (in `CMN/proto/block_changes.proto`)

```proto
message BlockChanges {
  // fields 1-8 unchanged
  // Onchain dynamic data sources Graph Node persisted for this block (Batch::data_sources),
  // in persistence order, after deduplication and after discarding sources created by
  // handlers that failed deterministically. Allowed only when the descriptor declares
  // `data_sources.transport = "in_band_v1"`; otherwise it must be empty.
  repeated CreatedDataSource created_data_sources = 9;
}

message CreatedDataSource {
  // Dense, zero-based within this block; equals persistence order.
  uint32 ordinal = 1;
  // Graph Node manifest index of the declaring template.
  uint32 manifest_idx = 2;
  // Template name; must equal the descriptor's template at manifest_idx.
  string template = 3;
  // handler_group_order of the invocation that called dataSource.create (audit trail).
  uint64 handler_group_order = 4;
  // Exact data_sources$.param bytes (onchain Ethereum: the 20-byte address).
  bytes param = 5;
  // Reserved for a later version: Graph Node serde JSON of DataSourceContext. v1 requires unset.
  optional string context_json = 6;
}
```

Implicit columns (normative): `block_range = [block_number, ∞)`, `causality_region = 0`,
`parent = NULL`, `id = NULL`, `done_at = NULL`. Old consumers refuse frames with field 9: prost
drops the unknown field and the canonical byte comparison fails
(`CMN/src/block_changes.rs:757-768`), so the change fails closed.

### 4.3 Descriptor v2

`descriptor_version: 2` (CMN accepts 1 and 2; B17). v2 is v1 plus these required keys:

```json
"descriptor_version": 2,
"deployment": "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",
"spec_version": "1.2.0",
"start_block": 13843704,
"graph_node": {"version": "0.44.0", "commit": "77823b5a7adc4eac4abf03202c8dd7cb00dea31d", "poi_version": "fast"},
"storage_profile": {"entity_types": ["Bundle", "Burn", "…"]},
"data_sources": {"transport": "in_band_v1",
                 "templates": [{"name": "Pool", "manifest_idx": 2, "param": "address20"}]},
"entity_retention": { "…": "§2.2" },
"producer_contract": {"kind": "native_block_changes_reducer",
                      "reducer": {"repository": "pinax-network/substreams-backfills", "commit": "<40 hex>"},
                      "extractor": {"spkg_sha256": "…", "module": "map_events", "module_hash": "…",
                                    "output_type": "proto:…", "initial_block": 13843704}}
```

No circularity (engine-contract §2.3 hazard): the extractor never stamps `compatibility_id`; the
native reducer reads the descriptor at run time and stamps its SHA-256, so pinning the extractor
module hash in the descriptor is safe.

### 4.4 Validator rules (in `validate_block_changes`)

- Non-empty only when the compatibility declares `in_band_v1`; then `mapping_triggered` must be
  true.
- `ordinal` dense from 0; `manifest_idx`/`template` match a declared template; `param.len() == 20`
  for `address20`; `context_json` unset; no duplicate `(manifest_idx, param)` within the block.
- Under `NON_FATAL`, no creation may name a `handler_group_order` whose group ends with a
  `DeterministicError`. Under `FATAL` with a `BLOCK_DISCARDED` block, the list must be empty.
- With `in_band_v1`, synthetic BCF1 frames are refused (every block is Observed and has a hash).

### 4.5 Engine handling

- `GenericState::apply_block` returns `created_sources` (§2.8).
- Cross-block uniqueness: `EntityStore::source_exists` on identity `manifest_idx ‖ param`
  (‖ `sha256(context)` later). A duplicate is refused; the producer emits only creations Graph
  Node accepted.
- Writer: existing `apply_created_data_source` (`ENG/src/sink.rs:2298`) emits the row; the spool
  carries rows in order, and the loader assigns `vid = seed_max_vid + ordinal` (generalizing
  `ENG/src/v3_root_load/transaction.rs:323`), because Graph Node loads templates by
  `(lower(block_range), vid)`.
- `SourceCommitment.order_sha256` reuses the chained creation-order hash of
  `CMN/src/dynamic_sources_v2.rs:58-75`, seeded from the snapshot's `sources.order_sha256`.
- The 10,000-block cap does not apply to in-band streams; v1/v2 companions keep their caps.

### 4.6 Producer obligations (coordination with the reducer design)

The Aerodrome reducer must emit one `CreatedDataSource { manifest_idx: 2, template: "Pool",
param: <pool address> }` for each `handlePoolCreated` that committed and called
`dataSource.create` (not for the hot-fix pool `0x8fe8…`, whose handler returns first,
REPORT-VERIFIED `survey/aerodrome-target.md` §5.1), in trigger order. The mapping-host oracle gains
a matching `--data-sources-in-band` option in a separate `substreams-backfills` slice so frames
can be compared byte for byte.

---

## 5. Generic loader, error policy and Graph Node resume (design item 4)

### 5.1 Inputs

**Family pin** (`adapters/<family>/landing.json`, reviewed, committed; never baked into the runtime
image because the profile pins that image's digest):

```json
{"format": "pinax.graph-node.landing-pin", "version": 1,
 "family": "aerodrome-slipstream-base",
 "deployment": "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV", "network": "base",
 "spec_version": "1.2.0", "poi_version": "fast", "start_block": 13843704,
 "descriptor": {"path": "adapters/aerodrome-slipstream-base/block-changes-v2.json", "sha256": "…"},
 "profile":    {"path": "adapters/aerodrome-slipstream-base/physical-profile.json", "sha256": "…",
                "production_selectable": true},
 "segment": {"max_blocks": 50000, "max_spool_bytes": 21474836480},
 "error_policy": "stop_before_first_error",
 "load_critical_indexes": ["pkey", "attr_*_id", "brin_*"],
 "registry": {"target_shard": "aerodrome_b", "parked_node_id": "index_node_aerodrome_backfill_0",
              "forbid_active": true}}
```

**Run binding** (`run-binding.json`, produced by `block-changes-load preflight`, read-only, then
approved at the Argo suspend; immutable; every later command takes `--run-binding-sha256`):

```json
{"format": "pinax.graph-node.landing-run-binding", "version": 1,
 "family_pin": {"bytes": 0, "sha256": "…"},
 "target": {"database": "graph", "system_identifier": "…", "server_version_num": 160011,
            "schema": "sgdN", "site_id": 0, "catalog_sha256": "…",
            "registry": {"shard": "aerodrome_b", "active": false, "node_id": "index_node_aerodrome_backfill_0",
                         "paused": true, "active_copy": {"schema": "sgd2", "shard": "subgraphshard_b"}}},
 "seed": {"snapshot": {"bytes": 0, "sha256": "…"}, "lineage": "…", "block": 0, "hash": "…",
          "entity_count": 0, "firehose_cursor_null": false, "health": "healthy",
          "non_fatal_errors": [], "subgraph_errors": 0},
 "target_head": {"block": 0, "hash": "…", "finalized_margin_blocks": 0},
 "runtime": {"image": "ghcr.io/…@sha256:…", "binaries": [{"name": "block-changes-load", "sha256": "…"}]},
 "continuation_graph_node_image": "ghcr.io/…@sha256:…"}
```

Preflight primary read (registry/assignment, B24), refusing unless exactly one *other* schema is
active and the target is inactive, on the pinned shard, assigned to the parked node and paused:

```sql
SELECT ds.id, ds.name, ds.shard, ds.active, a.node_id, a.paused_at IS NOT NULL
  FROM public.deployment_schemas ds
  LEFT JOIN subgraphs.subgraph_deployment_assignment a ON a.id = ds.id
 WHERE ds.subgraph = $deployment ORDER BY ds.id;
```

This replaces the `sgd1246` literal and the `ds.active` guard (DB-7): identity comes from data,
and the active copy is refused by observation, not by name. Inside the shard the loader binds
`sgd<site>` only to `subgraphs.deployment.id` and `subgraphs.head`, because a fresh Graphman v0.44
copy may have no shard-local `deployment_schemas` row (`ENG/AGENTS.md:59-62`, VERIFIED); registry,
assignment and pause state come only from the primary read above, re-run by the driver before
every segment.

### 5.2 Transport

`postgres` crate CopyIn for every COPY: data goes as CopyData messages, never through psql's
line-based `\.` detection (the cause of DB-1/F2-writers, REPORT-VERIFIED audit reproduction on
PG 14). No `graphman-target-psql` awk wrapper (DB-4): the loader renders the shard-native guard
itself. Spool files stream through `VerifiedSpoolFile` (existing hash-while-reading,
`ENG/src/sink.rs`) so the bytes sent are the bytes pinned. ASSUMED: the server-side CSV parser does
not treat a `\.` line inside a quoted field as end-of-data; gate G-LOAD-1 loads such a value.

### 5.3 The segment transaction (exact order)

```sql
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '4h';
SET LOCAL idle_in_transaction_session_timeout = '15min';
SET LOCAL search_path = pg_catalog;
SET LOCAL standard_conforming_strings = on;
SET LOCAL synchronous_commit = on;

-- L1 identity and exclusion (refuse on any false/NULL: IS DISTINCT FROM TRUE)
SELECT current_database() = $db
   AND (SELECT system_identifier::text FROM pg_control_system()) = $sysid
   AND pg_try_advisory_xact_lock(2, $site)          -- Graph Node write scope (B20)
   AND pg_try_advisory_xact_lock(1, $site)          -- copy scope
   AND pg_try_advisory_xact_lock(3, $site)          -- prune scope
   AND pg_try_advisory_xact_lock(hashtext('pinax.block-changes-load'), $site);  -- other loaders

-- L2 metadata rows locked and checked exactly
SELECT d.subgraph, d.health::text, d.failed, d.fatal_error, d.non_fatal_errors,
       d.graft_base, d.graft_block_number,
       h.block_number, encode(h.block_hash, 'hex'), h.entity_count, h.firehose_cursor IS NULL
  FROM subgraphs.deployment d JOIN subgraphs.head h ON h.id = d.id
 WHERE d.id = $site FOR UPDATE OF d, h;
-- guard: every column IS NOT DISTINCT FROM the predecessor fingerprint (head = expected block/hash,
-- entity_count = expected, health/errors unchanged, graft as pinned)
SELECT count(*) = $expected_errors FROM subgraphs.subgraph_error WHERE subgraph_id = $deployment;
SELECT count(*) = 1 FROM pg_namespace WHERE nspname = $schema;
-- catalog guard: Q2 observed catalog sha == run binding catalog_sha256

-- L3 per table T: seed VID domain
SELECT coalesce(max(vid), -1) = $seed_max_vid_T FROM "sgdN"."T";

-- L4 per table T with rows: COPY via CopyIn
COPY "sgdN"."T" (vid, block_range, <cols>) FROM STDIN WITH (FORMAT csv, NULL '\N');
-- data_sources$: COPY into a typed temp table, then
INSERT INTO "sgdN"."data_sources$" (vid, block_range, causality_region, manifest_idx, parent, id, param, context, done_at)
SELECT $sources_seed_max_vid + _ordinal, … FROM pg_temp._ds ORDER BY _ordinal;

-- L5 range guard on new rows (PK range scan over new rows only)
SELECT count(*) = $rows_T
   AND bool_and(lower(block_range) BETWEEN $from AND $to)
   AND bool_and(upper_inf(block_range) OR upper(block_range) BETWEEN $from + 1 AND $to)
  FROM "sgdN"."T" WHERE vid > $seed_max_vid_T;

-- L6 clamps
CREATE TEMP TABLE _c (vid bigint PRIMARY KEY, block_end integer NOT NULL) ON COMMIT DROP;
COPY _c FROM STDIN WITH (FORMAT csv);
UPDATE "sgdN"."T" t SET block_range = int4range(lower(t.block_range), c.block_end, '[)')
  FROM _c c
 WHERE t.vid = c.vid AND upper_inf(t.block_range)
   AND lower(t.block_range) < c.block_end AND c.block_end BETWEEN $from AND $to;
-- guard: rows affected == clamp count (client checks the command tag)
DROP TABLE _c;

-- L7 overlap guard (G3), every entity table with new rows
SELECT NOT EXISTS (
  SELECT 1 FROM "sgdN"."T" n
    JOIN "sgdN"."T" o ON o.id = n.id AND o.vid <> n.vid AND o.block_range && n.block_range
   WHERE n.vid > $seed_max_vid_T);

-- L8 sequences (B14 precedent)
ALTER SEQUENCE "sgdN"."T_vid_seq" RESTART WITH greatest($target_max_vid_T + 1, 1);
-- then: SELECT coalesce(max(vid), -1) = $target_max_vid_T FROM "sgdN"."T";

-- L9 head (filtered, rowcount = 1)
UPDATE subgraphs.head
   SET block_number = $to, block_hash = decode($to_hash, 'hex'),
       entity_count = entity_count + $new_entities, firehose_cursor = NULL
 WHERE id = $site AND block_number = $expected AND block_hash = decode($expected_hash, 'hex');

-- L10 staged fingerprint (§5.4) returned to the client; client fsyncs staged.json and
--     commit-sent.json, re-runs the external guard hook, then:
COMMIT;
```

`subgraphs.deployment` is not modified (health, errors, reorg counters, `earliest_block_number`,
`synced_at`, `postponed_indexes_created` stay as Graph Node left them). `poi2$` rows are ordinary
COPY rows and clamps. Every guard uses `IS DISTINCT FROM TRUE` (B14), so a NULL head refuses
(DB-6).

### 5.4 Durable journal and recovery

Bounded fingerprint (no full-table hashes, unlike the pilot's snapshot,
`ENG/src/v3_root_load/transaction.rs:100-125`, which cannot scale to 1.3B rows):

```rust
pub struct LandingFingerprint {
    pub head: HeadRow,                       // block, hash, entity_count, cursor_is_null
    pub deployment: DeploymentRow,           // health, failed, fatal_error, non_fatal_errors, graft
    pub subgraph_errors: u64,
    pub tables: Vec<TableFingerprint>,       // per table: max_vid, seq last_value, seq is_called,
                                             // rows_above(seed_max_vid)
    pub catalog_sha256: String,
}
```

Journal directory per segment (`<work>/journal/<to_block>/`, files created with `O_EXCL`, fsynced
with their directory): `intent.json` (spool pins, predecessor pins, before-fingerprint),
`staged.json` (fingerprint read inside the open transaction), `commit-sent.json`, then
`committed.json` (fresh fingerprint after commit equals staged). Plus one line per committed
segment in `<work>/postgres-backfill-progress.jsonl` in the existing exporter's shape
(`K8S/docs/substreams-backfill-metrics.md:84-116`: phases, inserted/clamped rows, new entities,
durations, schema, block, hash).

`block-changes-load recover` (read-only transaction) classifies:

| Observed fingerprint | Journal | Result |
|---|---|---|
| = before | no `commit-sent` | `unchanged`, safe to retry |
| = before | `commit-sent` | `rolled-back`, safe to retry |
| = staged | `staged` + `commit-sent` | `committed`, write `committed.json` without replay |
| anything else | any | refuse; operator |

The writer exclusion makes the transaction atomic with respect to these columns, so a match on the
bounded fingerprint is decisive (ASSUMED that nothing else writes the clone; guarded by L1 locks,
the registry check and replicas = 0 in the workflow).

### 5.5 Graph Node resume

After the last segment the clone has `head = (target, hash)`, `firehose_cursor = NULL`, exact
`entity_count`, `data_sources$` rows for every pool, sequences at `max + 1`, and untouched
deployment health. Graph Node resumes from the block pointer when the cursor is NULL; this is the
proven V4 and V3-milestone behaviour (REPORT-VERIFIED `survey/v3-lane-state.md` §2.1: continuation,
restart, rewind, replay passed). The target must be final: the driver refuses a target above
`finalized_head − finalized_margin_blocks`, and the extractor/reducer stream runs final-blocks-only
(audit F6/transport). Graph Node runs its whole write path, including the head pre-read and the
unfiltered head update (B21), inside `deployment::with_lock`, which takes the `(2, site)` advisory
lock (retrying with backoff) before the transaction (`GN:store/postgres/src/deployment_store.rs:1150-1206`,
`GN:store/postgres/src/deployment.rs:1504-1519`, VERIFIED). The
loader's `pg_try_advisory_xact_lock(2, site)` therefore excludes that path for the whole segment
transaction: either the loader refuses (Graph Node holds it) or Graph Node waits and then sees the
new head and fails with `DuplicateBlockProcessing` for any stale batch. This closes the DB-3 race
by construction rather than by the `application_name` probes.

### 5.6 Driver

`block-changes-backfill` (new Rust bin) replaces the shell drivers for the generic path:

```
block-changes-backfill run --family-pin P --run-binding R --run-binding-sha256 S \
    --work-dir W --state-store W/state --producer-argv-template T --until <target>
```

Per segment: spawn the producer pipeline and `state-replay` in one process group with
`--on-deterministic-error stop-before`; wait for **both** exit statuses (no READY spool is loaded
unless both exit 0; covers the F3/writers class on this path even though clock-v1 completeness
already refuses truncated ranges); load with `block-changes-load load`; audit sequences; append the
journal line; one segment of look-ahead compute. Exit codes: `0` target reached, `3` stopped before
a deterministic error (handover receipt written), `64` refusal needing a human, `75` retryable.
Signals go to the whole process group.

### 5.7 Deterministic errors: stop before, then hand over

`--on-deterministic-error stop-before`: before applying frame N, if it contains a
`DeterministicError` operation (or `BLOCK_DISCARDED`), state-replay applies nothing for N, keeps
reading and canonically decoding frames to the declared target (so range completeness is still
proven), and seals a spool whose real target is N−1 with N−1's envelope hash. The manifest and
checkpoint carry:

```rust
pub struct StopBeforeError { pub first_error_block: u64, pub first_error_hash: String,
    pub deterministic_errors: u64, pub block_discarded: bool, pub policy: String }
```

The driver loads it, writes `handover.json` (`{deployment, schema, head: N−1, first_error_block: N}`)
and exits 3. The operator resumes Graph Node on the clone; it processes N exactly (writing the PoI,
`subgraph_error`, health and, for `nonFatalErrors` before sync, pausing itself,
`GN:core/src/subgraph/runner/mod.rs:727-818`, VERIFIED). To continue the backfill afterwards,
capture a new seed above N with `--accept-health unhealthy --accept-non-fatal-errors <ids>`; the
loader then guards those columns unchanged.

`refuse` (default) fails the segment at N; with no flag a framed spool never seals through an
error. This closes GEN-4, GEN-6, F4/state and POI-VID-2 for every family.

Not built: an engine-side `subgraph_error` writer. It would need the exact Graph Node message and
handler (error id = `hex(stable_hash_legacy(SubgraphError))`, `GN:…/deployment.rs:901-937`) and
would still disagree with Graph Node on `non_fatal_errors`, which depends on write batching (§0.5).
If ever required, it is a contract extension (`DeterministicError.subgraph_error {message,
handler}` produced only by the mapping-host) plus `insert_subgraph_error` /
`update_deployment_status` SQL mirrors; it is out of the slices below.

### 5.8 Producer identity (audit F4/transport, generic path)

`state-replay` records, from environment, `GenericProducerIdentity { producer_image_digest,
reducer_binary_sha256, reducer_commit, extractor_spkg_sha256, extractor_module,
extractor_module_hash, substreams_native_sha256 }` in the v3 manifest and refuses a mismatch with
`descriptor.producer_contract`. The loader refuses a spool whose identity differs from the run
binding. This also fixes the `copy_spool_producer(false,false)` provenance gap
(`ENG/src/bin/state-replay.rs:2823`, engine-contract §1.3).

### 5.9 Optional: deferred secondary indexes (performance)

Rust port of the V4 plan semantics (`ENG/docs/direct-postgres.md:720-770`): before the first
segment, record and drop every index of the profile catalog not in `load_critical_indexes`
(keep PK, `attr_*_id` btrees needed by L7, BRIN); the catalog guard then compares against
`profile catalog − dropped set`; after the last segment rebuild them (`CREATE INDEX` with the
recorded definitions, bounded parallelism) and require the full profile catalog before handover.
Durable plan file; an unfinished plan blocks any normal run.

---

## 6. Descriptor ↔ profile binding and `production_selectable` (design item 5)

### 6.1 Binding rules (extend `DescriptorBinding`, B11)

```rust
pub struct DescriptorBinding {
    // existing fields …
    pub descriptor_version: u32,
    pub spec_version: Option<String>,   // required when descriptor_version >= 2
    pub poi_version: Option<String>,    // "fast" | "legacy", from graph_node.poi_version
    pub start_block: Option<u64>,       // required when descriptor_version >= 2
    pub templates: Vec<(String, u32)>,  // data_sources.templates
}
```

Refusals in `bind_descriptor` (`ENG/src/physical_writer.rs:558-659`):

- spool mode requires descriptor `deployment` (GEN-7);
- `poi_version` must equal `profile.metadata.poi.version` and must equal the spec rule
  (`spec ≥ 0.0.6 ⇒ fast`, VERIFIED `GN:…/instance_manager.rs:487`); `spec_version` must equal
  `profile.deployment.spec_version`, which becomes required when the descriptor declares it;
- descriptor templates must equal the profile mapping inventory's `template` declarations
  (ordinal and name);
- a fresh root (no checkpoint, no seed snapshot) requires `expected_head_block + 1 ==
  start_block` (POI-VID-4).

### 6.2 Template families become production-selectable

- Delete the `TemplateInstantiatedRows` refusal in `compile` (`ENG/src/physical_writer.rs:531-539`);
  the spool already refuses a written `data_sources$` without a source transport
  (`ENG/src/bin/state-replay.rs:2365-2383`), and v3 additionally requires `in_band_v1` or a
  companion. `--allow-test-only-physical-profile` then means only "non-production profile" (GEN-2).
- Accept a second runtime binary set: optional `runtime.loader: "block-changes-load"` selects
  `{block-changes-backfill, block-changes-load, generic-seed-capture, generic-state, state-replay,
  substreams-native}`; absent keeps the legacy exact set (B12), so existing profile bytes stay
  valid.
- Live-catalog flow (once per landing clone):
  1. infra: graphman copy of `sgd2` into the dedicated store, reassign to the parked node, pause;
  2. `generic-seed-capture catalog` on the stopped clone → `catalog.json` (canonical
     `CatalogSnapshot` with the `$schema` marker and schema-relative names, normalization ported
     from `ENG/scripts/v3-milestone.py:434-480`);
  3. build `adapters/<family>/physical-profile.json` with `evidence.kind = live_catalog`,
     `provenance` all `captured_and_retained` (catalog from step 2; deployment artifacts =
     the retained IPFS bytes in `SB/aerodrome-slipstream-base/reference/`; producer and runtime =
     released digests), `production_selectable: true`; validate with
     `validate_observed_catalog`; PR review;
  4. two-phase pin: runtime image first, then profile/pin PR.

The capture in step 2 must be on the same clone that will be loaded; Graphman copies renumber VIDs
(`ENG/AGENTS.md:53-58`, REPORT-VERIFIED engine-contract §5.1), and the catalog includes the clone's
real index set.

---

## 7. Performance targets and measurement (design item 6)

### 7.1 Inputs

| Quantity | Value | Label |
|---|---|---|
| Handler invocations per block | 48.9 (3-day window) to 58 (6 h at 34.70M) | REPORT-VERIFIED `v3-lane-state` §4.2, `aerodrome-target` §9 |
| Row versions inserted per block | 140–160 now, rising | REPORT-VERIFIED SYNTHESIS §3 Q7 |
| Clamps per block | ~60–80 (one per persistent-entity update) | ESTIMATE |
| SetEntity operations per block | ~350–600 | ESTIMATE (Swap ≈ 12 saves + ticks; NPM ≈ 3; Mint/Burn ≈ 12) |
| Distinct persistent keys per block | ~60–120 | ESTIMATE |
| V4 COPY throughput, all indexes | 5,081,926 rows in ~2,257 s ≈ 2,252 rows/s | ESTIMATE from `ENG/docs/direct-postgres.md:130-133,149` |
| V4 first 100k segment with 253 indexes | 6,158 s in the PostgreSQL transaction | `ENG/docs/direct-postgres.md:762-765` (VERIFIED doc) |
| V4 reducer only, low density | 2,268–2,596 blocks/s | `ENG/docs/benchmark-100k.md` stage table (VERIFIED doc) |

### 7.2 Targets

| ID | Target | Rationale |
|---|---|---|
| T1 | `state-replay --state-store` from a local BCF1 file: **≥ 150 blocks/s** at 34.7M–52.9M density (budget ≈ 6.7 ms/block: decode+validate ≤ 1.5, apply+cross-check ≤ 1.5, PoI fast fold ≤ 1.0, spool encode ≤ 1.0, store I/O ≤ 1.5) | keeps compute far ahead of load |
| T2 | segment boundary (delta + checkpoint + commit) ≤ 120 s per 100k blocks | < 10% overhead |
| T3 | loader with all indexes ≥ 3,000 row-writes/s | ≈ 13 blocks/s at ~220 writes/block |
| T4 | loader with deferred secondary indexes ≥ 15,000 row-writes/s | ≈ 65 blocks/s |
| T5 | end-to-end pipelined ≥ 10 blocks/s with indexes (18.1M blocks ≤ 21 days), ≥ 30 blocks/s deferred (≤ 7 days + index rebuild) | vs Graph Node ≈ 1–2 blocks/s |
| T6 | engine RSS ≤ cache + 4 GiB; loader RSS ≤ 1 GiB | bounded |
| T7 | landing seed capture ≤ 2 h for ~28M captured rows | one-time |

### 7.3 How to measure

- **M1 synthetic engine bench.** `tools/bench-generic-state` (new workspace tool like
  `tools/nul-audit-report`): `generate --spec fixtures/bench/aerodrome-34m.json --blocks N --seed S`
  writes deterministic Aerodrome-shaped BCF1 frames (Zipf-distributed Position keys over 24M IDs,
  per-block handler mix from the VERIFIED metrics, retention classes from the descriptor);
  `run` feeds `state-replay` with `BACKFILL_HOT_PATH_TELEMETRY=1`. Report: blocks/s, per-phase ns
  (existing `PhaseReporter` phases plus new `store_get_ns`, `store_put_ns`, `store_cache_hits`,
  `store_cache_misses`, `delta_bytes`, `store_commit_ms`), peak RSS (`getrusage`).
  CI runs 20k blocks for correctness only; the 1M-block run is manual on a dom153 node.
- **M2 real frames.** Once the reducer exists: [seed + 1, seed + 100,000] from the Kan noop cache.
- **M3 loader bench.** On a disposable graphman copy (scratch store): 3 segments × 25k blocks, all
  indexes vs deferred; record rows/s, `pg_stat_wal` deltas, transaction time.
- **M4 production run.** Exporter metrics (`backfill_job_rate_blocks_per_second`,
  `backfill_job_last_segment_rows_written_per_second`, `backfill_job_phase_elapsed_seconds_total`)
  from the journal format of §5.4.

---

## 8. Test plan (named fixtures and tests)

Fixtures (engine, unless stated):

| Fixture | Content |
|---|---|
| `fixtures/generic-state/aerodrome-descriptor-v2.json` + `.sha256` | `fixture_only: true`, retention §2.2, `in_band_v1` |
| `fixtures/generic-state/aerodrome-hermetic-profile.json` + `.sha256` | from `uniswap-v3-mainnet-hermetic.json` with Aerodrome's 3 extra fields, spec 1.2.0, fast |
| `fixtures/generic-state/violations/*.bcf1` | `block-local-rewrite`, `block-suffix-mismatch`, `period-regression`, `period-unparsable`, `evicted-partial-update`, `duplicate-source` (tiny, generated in-test) |
| `fixtures/bench/aerodrome-34m.json` | workload spec for M1 |
| `CMN/fixtures/block-changes-v1/in-band-data-sources-*.pb` | canonical golden frames with field 9 (substreams-backfills) |
| `fixtures/mapping-host-v3-stream/` (existing) | 300-block real stream for equivalence |
| `fixtures/landing/landing-pin.fixture.json` | fixture family pin |

Tests:

- `generic_state::tests::created_null_is_stripped_at_persist`,
  `…::next_block_materialized_omits_stripped_null` (F2/state).
- `state_store::tests::memory_and_redb_produce_identical_spools` (300-block stream, retention none
  and synthetic 20k with retention): identical COPY file sets, PoI, lineage.
- `state_store::tests::chunked_equals_uninterrupted` (1×20k vs 4×5k vs 20×1k).
- `state_store::tests::crash_points_recover` (inject failure at each §2.5 row; recovery yields the
  same lineage and spool bytes).
- `state_store::tests::rewind_then_replay_is_identity`.
- `retention::tests::*` for each violation fixture (exact refusal variant and block).
- `block_changes::tests::in_band_sources_*` (CMN): canonical round trip; refused without capability;
  refused under a discarded handler; duplicate within block; synthetic frame refused.
- `state_replay::tests::stop_before_seals_previous_block` and `…::refuse_is_default`.
- `physical_writer::tests::live_catalog_template_profile_compiles_without_test_ack` (the audit probe),
  `…::bind_refuses_poi_version_mismatch`, `…::bind_refuses_spec_mismatch`,
  `…::fresh_root_requires_start_block`.
- `tests/generic_seed_resume.rs::postgres16_seed_capture_resume_equals_whole_run` (`#[ignore]`, CI
  slow lane, Docker PG16 like the existing `source_chunks_v2` PG16 tests): load the 300-block real
  stream as 200 blocks, capture a landing seed at block 200, init a store, replay the last 100
  blocks with `--state-store`, load with `block-changes-load`, and require physical table hashes
  equal to the whole 300-block load (non-VID columns and VIDs).
- `tests/block_changes_load.rs::postgres16_*` (`#[ignore]`): fresh-from-seed load, append, lost
  COMMIT ack + `recover`, and refusals: wrong site, head mismatch, NULL head, a session holding
  `pg_advisory_lock(2, site)`, catalog drift, overlap (seed row with same block-local ID), range
  violation, and successful loads of a `\.`-line string and a string containing
  `deployment_schemas`.
- `tests/seed_capture.rs::postgres16_*`: empty table → −1; every column kind round-trips; period
  filter; oracle mode refuses loading.

---

## 9. Acceptance gates

| Gate | Pass condition | Where |
|---|---|---|
| G-E0 | `cargo test --locked --all-targets`, clippy, fmt green; V4 byte-identical (`offline-parity-ci.sh`, `verify-spkg`) | every slice |
| G-STORE-1 | memory vs redb byte-identical spools/PoI/lineage on all fixtures | E3 |
| G-STORE-2 | chunked == uninterrupted; every crash point recovers to the same bytes | E3 |
| G-STORE-3 | rewind/replay identity | E3 |
| G-STORE-4 | M1, 1M synthetic blocks over an 80M-entity store: T1 rate and T6 RSS met (validates the redb large-transaction ASSUMPTION) | E3/E9 |
| G-RET-1 | every violation fixture refused with the exact variant; loader L7 catches a seed-row collision | E2/E6 |
| G-SEED-1 | PG16: round trip on every row and column kind; −1 VIDs; NULL head refused | E5 |
| G-SEED-2 | live read-only landing capture on the stopped Aerodrome clone: Σ active rows = `head.entity_count`; `data_sources$` = 1,501+ rows, all `manifest_idx = 2`; snapshot re-read verifies | E5 + infra |
| G-ORACLE | oracle seed from `sgd2` at B−1 for ≥ 3 sampled windows (100–1,000 blocks each, including a dense recent window): engine `Poi$` digests equal `sgd2.poi2$` digests at every region-opening block (**first real-data Fast PoI gate**), and all non-VID rows written in the window equal `sgd2` rows by time travel | E5 + reducer + O4 |
| G-LOAD-1 | PG16 matrix of §8 passes | E6 |
| G-LOAD-2 | disposable clone: 3 segments loaded, then Graph Node continuation 1,000 blocks, restart, rewind, replay pass; GraphQL parity on all 20 types at head and one historical block | E6 + infra |
| G-PERF | T1–T7 measured and recorded in `docs/benchmark-generic.md`; T3/T5 decide whether §5.9 is required | E9 |
| G-CUTOVER | final segment: catalog = profile catalog, sequences audited, no deterministic-error stop, handover receipt, independent certification (PoI at target equals the Option C node if it has reached the target) | run |

---

## 10. Ordered PR slices

Cross-repo slices in `substreams-backfills` (`common/` is the contract crate the engine vendors)
are prefixed C; engine slices E. Each engine slice regenerates the V4 shadow descriptor source pins
(`adapters/uniswap-v4-base/block-changes-v1.json` + `.sha256`, B19) because it touches pinned
files; V4 behaviour stays byte-identical (G-E0).

| # | Slice | Depends on | Content | Closes (audit) |
|---|---|---|---|---|
| C1a | common: descriptor v2 + retention + snapshot format | BigDecimal fix (Phase 0) merged first | `from_descriptor` accepts v2 with typed `DescriptorCapabilities {spec_version, start_block, templates, entity_retention, producer_contract}`; `RetentionPolicy` + validation + canonical `retention_sha256`; `state_snapshot.rs` (BCGSNAP1 reader/writer, lineage fns); tests | — (enabler) |
| E0 | engine: generic-path hardening | — | Null strip at persist; framed spool refuses any deterministic error or `BLOCK_DISCARDED` in every source mode (interim until E7); fsync `building/spool` in the v1 BlockChanges seal; refuse U+0000 in String values on the generic path; doc and refusal-text truth (README:845-855, block-changes-v1-input.md:445-497, physical_writer.rs:78-80, physical_profile.rs:1-5, generic_state.rs:38-40) | F2/state, F4/state, POI-VID-2, GEN-6 (interim), F5/writers, GEN-8, F3/state (generic path) |
| E1 | engine: binding + template profiles | C1a (for v2 fields; v1 rules land without it) | §6.1 rules; drop the template refusal in `compile`; second runtime-binary set; fresh-root start-block binding | GEN-2, GEN-7, POI-VID-4 |
| E2 | engine: retention-aware GenericState (memory backend) | C1a, E0 | `EntityStore` trait + `MemoryEntityStore`; `PersistedKey` seam; G1/G2/G4; writer `apply_generic_block` (no `active` for block-local); period eviction; binding gains `retention_sha256` (Option, v1 bytes unchanged without it) | GEN-3 (write-once part) |
| E3 | engine: redb store, deltas, BCGCKPT3, `generic-state` bin | E2 | §2.4–2.8; `--state-store`, `--seed-snapshot`, v3 predecessor; spool manifest v3; `redb =4.3.0` | GEN-3 (rest), engine #70 for the generic path |
| C1b | common: in-band data sources | C1a | proto field 9 + `CreatedDataSource`; validator rules §4.4; golden fixtures; mapping-host `--data-sources-in-band` follows separately | — (enabler) |
| E4 | engine: in-band `data_sources$` | C1b, E3 | vendor C1b; store `sources` table; writer rows; v3 manifest provenance; re-pin `COMMON_COMMIT`/`SOURCE_V2_COMMON_COMMIT` to main commits | GEN-3 (10k cap), ENG-BUILD-02 |
| E5 | engine: `generic-seed-capture` | E3 (+C1a) | landing/oracle/catalog modes, §3 SQL, round-trip proof; V4 capture `-1` fix | POI-VID-3, DB-5, part of ENG-BUILD-01/GEN-1/F1-writers (no seed tool), GEN-2 completion (live catalog) |
| E6 | engine: `block-changes-load` | E4 (v3 spools), E5 (seed receipts) | family pin, run binding, preflight, §5.3 transaction over CopyIn, journal, recover, verify; `postgres =0.19.14` | ENG-BUILD-01, POI-VID-1, F1/writers, DB-2, GEN-1, DB-1 + F2/writers (generic path), DB-3, DB-4 (generic path), DB-6, DB-7 |
| E7 | engine: stop-before policy | E3 | §5.7; replaces the E0 interim refusal for v3 spools; handover receipt | GEN-4, GEN-6, F4/state, POI-VID-2 (final) |
| E8 | engine: `block-changes-backfill` driver + producer identity | E6, E7 | §5.6, §5.8; exporter-compatible journal; finalized-target check | F4/transport (generic), F3/writers (generic path), F6/transport (driver check) |
| E9 | engine: performance | E8 | `tools/bench-generic-state`, store telemetry, optional deferred-index plan §5.9, `docs/benchmark-generic.md` | part of engine #71 |
| E10 | engine: graft-transition checkpoint (V3 mainnet only) | E5 | seed a graft child from the base's state at the graft block (E5 oracle-style capture of the base at `graft_block`, or the base run's own store), re-bind deployment/descriptor/profile through a reviewed graft map, VIDs reallocated per `GraftVidPolicy::ReallocatedByDestination` | F4/writers |

Not in this area (other Phase-0 work, listed so nothing is dropped): F1/transport and
F2/transport and the legacy-v1 parts of F3/writers (stream-completeness fixes); F1/state
(BigDecimal 35 digits); V4-path variants of DB-1, DB-4, DB-6, DB-7 (recommended separate V4
hardening PR: `IS DISTINCT FROM` at `ENG/src/sink.rs:2777,3453`, `pg_try_advisory_xact_lock(2, site)`
in both V4 writers; this changes certified V4 SQL bytes, so it needs its own certification).

Critical path to an Aerodrome run: C1a → E0 ‖ E1 → E2 → E3 → C1b → E4 → E5 → E6 → E7 → E8, with
E9 measurements from E3 onward. E5 and the E6 library can be developed in parallel against
fixtures once E3's formats are fixed.

---

## 11. Audit coverage matrix (31 kept findings + 2 build findings)

| Finding | Severity (verified) | Slice | Note |
|---|---|---|---|
| F1/transport | critical | Phase 0 | generic path is clock-v1 only (state-replay.rs:4206-4208) |
| F2/transport | medium | Phase 0 | same |
| F4/transport | low | E8 | generic producer identity |
| F6/transport | low | E8 + reducer | finalized target + final-blocks-only |
| F1/state | high | Phase 0 | BigDecimal |
| F2/state | medium | E0 | Null strip |
| F3/state | low | E0 (generic) | V4 unchanged |
| F4/state | medium | E0 → E7 | |
| POI-VID-1 | high | E6 | |
| POI-VID-2 | low | E0 → E7 | |
| POI-VID-3 | medium | E5 | |
| POI-VID-4 | low | E1 | |
| F1/writers | high | E5 + E6 | |
| F2/writers | medium | E6 (generic) | V4: separate PR |
| F3/writers | high | Phase 0 + E8 | |
| F4/writers | medium | E10 | V3 mainnet only |
| F5/writers | low | E0 | |
| DB-1 | medium | E6 (generic) | V4: separate PR |
| DB-2 | high | E6 | |
| DB-3 | low | E6 | advisory scopes 1/2/3 + filtered head update |
| DB-4 | medium | E6 (generic) | no awk wrapper on this path |
| DB-5 | low | E5 | |
| DB-6 | low | E6 | `IS DISTINCT FROM` everywhere |
| DB-7 | low | E6 | identity from pin + registry observation |
| GEN-1 | high | E6 | |
| GEN-2 | medium | E1 + E5 | |
| GEN-3 | high | E2 + E3 + E4 | |
| GEN-4 | medium | E7 | stop-before, no writer |
| GEN-6 | medium | E0 → E7 | |
| GEN-7 | low | E1 | |
| GEN-8 | low | E0 | |
| ENG-BUILD-01 | high | E5 + E6 | |
| ENG-BUILD-02 | low | E4 | re-pin COMMON commits |

---

## 12. Coordination interfaces

Exposed by this design (others must produce or consume them):

1. **Descriptor v2** (`descriptor_version: 2`, §4.3): `spec_version`, `start_block`,
   `graph_node.poi_version`, `storage_profile.entity_types`, `data_sources {transport: in_band_v1,
   templates}`, `entity_retention` (§2.2), `producer_contract` (reducer commit, extractor SPKG
   sha256/module/module hash/output type/initial block). The reducer team writes it; the engine
   pins it in `adapters/<family>/`.
2. **`BlockChanges.created_data_sources` (field 9)** and `CreatedDataSource` (§4.2); validator
   rules §4.4.
3. **Frame stream contract for native producers:** BCF1 clock-v1, one Observed frame per block from
   `expected_head + 1` to the target (untriggered blocks are `mapping_triggered = false` messages),
   envelope hash = Firehose block hash, final blocks only, no synthetic frames with `in_band_v1`.
4. **`BCGSNAP1` seed snapshot** (`CMN/src/state_snapshot.rs`): the reducer must seed its own state
   from the same file and refuse to start unless the engine store's `meta.lineage` equals the
   snapshot's L0 (first segment) or the predecessor spool's `lineage_after`.
5. **Retention obligations for the reducer:** a block-local or period-scoped entity must never be
   read or written outside its block/period; the reducer evicts the same keys.
6. **Deterministic errors:** the reducer must emit frame N with `DeterministicError` operations
   wherever Graph Node would fail (non-try call reverts, i32 overflow aborts, `load!` of a missing
   entity). A missed error is caught only by the oracle gates.
7. **CLIs and files:** `generic-seed-capture`, `generic-state`, `block-changes-load`,
   `block-changes-backfill`, family pin (§5.1), run binding (§5.1), journal (§5.4), handover receipt
   (§5.7), exit codes (§5.6). The k8s generic backfill WorkflowTemplate (PR-K2) maps its parameters
   (`deployment`, `target-schema`, `expected-seed-block`, `target-block`, `runtime-image-digest`,
   `target-shard`, `target-postgres-host`, `primary-postgres-host`, `parked-node-id`,
   `expected-seed-hash`, `target-hash`, `segment-size`, `adapter`, `work-pvc`, SYNTHESIS §6.2)
   onto these.

Consumed:

- Extractor SPKG release pins (sha256, module hash) from the extractor slice; the noop cache.
- Reducer binary/image and its frames; mapping-host oracle frames with in-band sources.
- Phase-0 fixes: BigDecimal 35-digit negatives (C1a must rebase on it); stream-completeness
  (substreams-native cancel → non-zero).
- Infra: stopped graphman clone, read-only SQL to it, to `sgd2` and to the primary; PVC.

---

## 13. Risks and open questions

| Risk | Mitigation |
|---|---|
| R1 redb memory/latency under one large write transaction per segment (ASSUMED bounded) | G-STORE-4 early (E3); fallback: smaller segments (≥ 10k blocks) or per-N-block non-durable commits with the undo spill made authoritative |
| R2 store size: ~79M Positions at target → ~100 GiB file | NVMe PVC ≥ 500 GiB; optional ordinal-coded field encoding (format byte 2) halves image size |
| R3 load throughput with full indexes ≈ 10 blocks/s (ESTIMATE) → ~21 days | §5.9 deferred indexes (measured in M3 before the run) |
| R4 retention claims depend on reducer semantics | engine guards G1–G5 + loader G3 catch every rewrite; oracle gates catch reads |
| R5 Fast PoI never exercised on real data by the engine | G-ORACLE compares `poi2$` digests on `sgd2` windows before any long run |
| R6 seed decode must exactly match Graph Node's load view for every column kind | per-row typed round trip (§3.3) is fail-closed |
| R7 time-travel oracle needs unpruned `sgd2` (O4 OPEN) | check `subgraph_manifest.history_blocks` read-only first |
| R8 continuation runs on Graph Node v0.45 while semantics are pinned to v0.44 | record `continuation_graph_node_image` in the run binding; certification compares PoI after continuation |
| R9 contract churn: descriptor v2 + field 9 touch mapping-host, common, engine | gate behind descriptor capability; v1 frames and descriptors unchanged byte for byte |
| R10 every engine slice must regenerate the V4 shadow descriptor pins (B19) | documented step per slice; G-E0 |
| R11 the reducer misses a Graph Node deterministic error | oracle gates; `sgd2` health is `healthy` over 13.84M–34.73M (VERIFIED), so the risk is confined to the backfilled range |
| R12 adapters must not be baked into the image they pin | deliver `adapters/<family>/` as a sha-pinned workflow artifact |
