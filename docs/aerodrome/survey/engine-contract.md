# Engine integration contract for a new subgraph family

Survey of `pinax-network/substreams-graph-node-backfill` (the "engine") for the
Aerodrome Slipstream Base effort (deployment
`QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`) and for a generic
"make any subgraph backfillable" procedure.

- Snapshot read: `scratchpad/ro/engine` (detached worktree of origin/main; its
  `.git` pointer is dangling, so git commands do not work there). Main is
  `5c98b572` (#84, merged 2026-09-07 17:13 UTC). `gh api .../commits` confirms
  no commits since then. The latest tagged release is `v0.5.0`
  (2026-08-18).
- Paths below are relative to the engine root unless prefixed. `file:N` means
  a line number in that snapshot.
- **VERIFIED** means I read the code. **DOC** means only documentation says it.
  **LIVE** means a VictoriaMetrics/GitHub read on 2026-10-20.

---

## 0. Executive summary

1. **Two ways in, and only one is family-neutral.** Four of the five
   `state-replay --input-format` modes decode Uniswap-v4 protobufs and drive a
   hand-written V4 reducer. Only `block-changes-v1-framed` is family-neutral.
   It reads `pinax.graph.backfill.v1.BlockChanges` messages, each wrapped in a
   52-byte `BCF1` "clock-v1" frame header (VERIFIED,
   `src/bin/state-replay.rs:3540-3549, 3649-3662, 487-489`).
2. **The neutral path works end to end, but only for a small bounded test.**
   It goes BCF1 stream → generic state → PoI → profile-driven COPY spool →
   generic checkpoint → disposable loader. Every piece is pinned to the
   Uniswap-V3 Mainnet root deployment, or blocked by a test-only gate:
   - every physical profile is `production_selectable:false`;
   - the loader hard-codes `Qme66…`, start 12,369,621, at most 1,153 blocks,
     a 256 MiB cap, exact profile and descriptor digests, and the Kan API
     server (`src/v3_root_load.rs:20-25`, `src/bin/v3-root-load.rs:24`);
   - dynamic-source companions are root-only and limited to 10,000 blocks per
     chunk;
   - committed removes, immutable tables, grafts, Bytes/Int8 IDs and
     deterministic errors (when a data-source sidecar is used) are all refused.
3. **The neutral path can only start a deployment from empty state.** A framed
   spool with no generic checkpoint must declare the all-zero expected head
   hash (`state-replay.rs:2467-2479`). No tool turns a running Graph Node
   deployment (for example Aerodrome at about 34.7M) into a
   `GenericCheckpoint`. Continuing after an existing head is supported **only
   on the V4 path**, via `capture-direct-postgres-seed.sh`, which hard-codes
   the 20 V4 tables (`scripts/capture-direct-postgres-seed.sh:27, 81-104`).
4. **A Substreams module cannot realistically emit a complete `BlockChanges`
   stream for a stateful AMM mapping.** The format technically allows it: the
   engine treats the payload as opaque bytes per frame, and `substreams-native`
   relays raw map output. But the content does not fit:
   - every `SetEntity` must carry the full post-save `materialized` image;
   - the engine re-merges each save against its own baseline and refuses any
     mismatch;
   - PoI requires exact per-save `written_fields` in Graph Node order.

   Recurrent state (`Token.derivedETH`, Decimal128 accumulators, the PoI
   chain) cannot be expressed as cacheable Substreams Stores (DOC,
   `docs/substreams-stores.md:5-19, 120, 198-199`). In the V4 design,
   Substreams does parallel extraction plus mergeable Stores, and the engine
   does the ordered reduction. Today's only real `BlockChanges` producer is the
   sequential Rust "mapping-host" in `substreams-backfills`, which runs the
   deployed WASM over Firehose blocks and an `eth_call` cassette.
5. **Aerodrome's shape fits the generic writer; its scale does not.** Verified
   against `substreams-backfills/aerodrome-slipstream-base/reference/`:
   - manifest `specVersion` is 1.2.0, so VIDs come from sequences and profile
     format v1 can represent it;
   - 20 entity types, all mutable, all with `ID!` (String) IDs;
   - the mapping WASM imports `store.get` and `store.set` but no
     `store.remove`;
   - it has a `Pool` template, so `data_sources$` rows are required;
   - it uses `ethereum.call` and declares `nonFatalErrors`.

   Because every entity is mutable, every Swap, Transaction, Mint and so on
   stays a live entity in the generic in-memory store. A database that is
   probably an Aerodrome copy (`postgres-exporter-aerodrome`, schema
   `sgd5311`) shows about 810M row versions (LIVE). The generic store and its
   full MessagePack checkpoint are not designed for that. Engine issue #70
   (disk-backed state) is open, scoped to V4, and unstarted.
6. **The V4 production shape is "seed at a checkpoint, then write forward".**
   - Make an inactive physical copy of the same deployment ID.
   - Stop its writer at a healthy head.
   - Capture the seed from that exact target schema.
   - Stream Substreams output, reduce it, COPY it, and atomically advance
     `subgraphs.head` in 100k-block segments.
   - Certify, then activate in a separately approved step.

   The live source stays in service throughout. Seed was 32,374,183 and target
   49,477,581 (DOC, `docs/direct-postgres.md:1114-1141`, `README.md:110-124`).
7. **Packaging is digest-pinned throughout.**
   - SPKGs are immutable GitHub release assets of the *Substreams source* repo,
     pinned by SHA-256 and module hash in
     `adapters/<family>/compatibility.json`.
   - Runtime images are published to GHCR under commit-qualified tags, with an
     ORAS-attached archive and runtime JSON.
   - The release contract is pinned in two phases (push the image first, then
     pin its digest and four binary hashes in the contract).
   - Kubernetes must pin `@sha256:`.

---

## 1. Input formats accepted by `state-replay`

### 1.1 The five modes (VERIFIED)

| `--input-format` | Payload proto | Framing | Reducer | Family | Outputs allowed |
| --- | --- | --- | --- | --- | --- |
| `jsonl` (default) | JSON of `pinax.uniswap.v4.base.v1.Events` (from `substreams run -o jsonl`) | newline JSON, `@seed` lines | `src/reducer.rs` | **V4-hardcoded** | snapshot, `--append-output` (Parquet), `--postgres-schema`, `--postgres-spool-output` |
| `protobuf-framed` | `pinax.uniswap.v4.base.v1.Events` (`proto/events.proto`) | legacy-v1 12-byte header or clock-v1 BCF1 | `src/reducer.rs` | **V4-hardcoded** | same as above |
| `store-fed-protobuf-framed` | `pinax.uniswap.v4.base.store.v1.ReducerInputs` (`proto/reducer_inputs.proto`) | legacy-v1 or clock-v1 | `src/store_fed.rs` and `src/reducer.rs` | **V4-hardcoded** | `--postgres-schema` / `--postgres-spool-output` / `--postgres-spool-plan` only (`state-replay.rs:3909-3917`) |
| `store-state-protobuf-framed` | same `ReducerInputs`, state_version 3 | legacy-v1 or clock-v1 | `src/store_fed.rs` and `src/reducer.rs` | **V4-hardcoded**; the direct-COPY default | same; also the only mode allowed with `--postgres-spool-plan` (`:3778-3783`) and `BACKFILL_BLOCK_CHANGES_SHADOW=1` (`:4119-4124`) |
| `block-changes-v1-framed` | `pinax.graph.backfill.v1.BlockChanges` (`third_party/backfill-common/proto/block_changes.proto`) | **clock-v1 only** (`:4206-4208`) | generic (`src/generic_state.rs` and `src/block_changes_input.rs`) | **family-neutral** | `--state-only-output` **or** `--postgres-spool-output` (with `--physical-profile`); nothing else (`:4161-4255`) |

Supporting code:

- Parser: `state-replay.rs:3649-3662`. Enum: `:3540-3549`. The enum's doc
  comment still says "State-only until #67/#68", which is stale.
- Dispatch: `main()` selects the physical profile before anything else
  (`:483`), then `--postgres-spool-plan` (`:484-486`), then the
  `BlockChangesV1Framed` path (`:487-489`). Everything else falls through to
  the V4 code (`:490-1300`).
- Note: `README.md:845-855` still says the `BlockChanges` mode refuses every
  PostgreSQL target. That is stale: PR #79 added `--postgres-spool-output`.
  Trust `docs/block-changes-v1-input.md` and the code.

### 1.2 Full CLI flag inventory (VERIFIED, `state-replay.rs:3589-3717`)

- **Boolean flags:**
  - `--quiet`
  - `--allow-postgres-write`
  - `--allow-fixture-descriptor` (tests only)
  - `--allow-non-string-entity-ids` (tests only)
  - `--allow-omitted-data-sources`
  - `--allow-test-only-physical-profile`
- **Flags that take a value:**
  - `--input-format {jsonl|protobuf-framed|store-fed-protobuf-framed|store-state-protobuf-framed|block-changes-v1-framed}`
  - `--native-frame-format {legacy-v1|clock-v1}` (default `legacy-v1`; clock-v1 is refused with `jsonl`, `:3906`)
  - `--snapshot`, `--input-snapshot`, `--supplement-seeds` (V4 `ReplaySnapshot`)
  - `--append-output` (V4 Parquet dump)
  - `--postgres-schema` (direct psql, V4)
  - `--postgres-spool-output DIR.ready`
  - `--postgres-spool-plan` (long-lived V4)
  - `--subgraph-error-inventory`
  - `--expected-head-block`, `--expected-head-hash`, `--head-block`, `--head-hash`
  - `--checkpoint`
  - `--block-changes-descriptor`
  - `--state-only-output`
  - `--physical-profile`
  - `--input-generic-checkpoint`
  - `--data-sources-sidecar` (v1)
  - `--data-sources-chunk` (v2)
  - `--input-generic-spool` (v2 predecessor)
  - `--stop-after-tables`
- **Special single-purpose invocations** (`:437-478`):
  - `state-replay --validate-block-changes-descriptor` validates **only the
    pinned V4** descriptor (`V4BlockChangesShadowAdapter::from_pinned_descriptor`).
  - `state-replay --validate-subgraph-error-inventory <path> <eb> <eh> <tb> <th>`.

Rules specific to the `BlockChanges` mode (`:3719-3755, 4161-4255`):

- It requires clock-v1, a descriptor, and exactly one of `--state-only-output`
  or `--postgres-spool-output`.
- A spool requires `--physical-profile`.
- It refuses `--append-output`, `--postgres-schema`, `--postgres-spool-plan`,
  `--snapshot`, `--input-snapshot`, `--supplement-seeds` and
  `--subgraph-error-inventory`.
- `--data-sources-sidecar` requires a fresh spool: no
  `--input-generic-checkpoint` and no omission allowance.
- `--data-sources-chunk` and `--input-generic-spool` require the v2 spool and
  exclude the v1 sidecar, the raw checkpoint and omissions.
- Spool output rules (shared with V4, `:3851-3889`):
  `--expected-head-block`, `--expected-head-hash`, `--head-block` and
  `--head-hash` are all required; the path must end in `.ready`; `--checkpoint`
  and `--allow-postgres-write` are refused.

### 1.3 Environment variables read by the Rust binaries (VERIFIED)

| Variable | Where | Applies to |
| --- | --- | --- |
| `BACKFILL_SOURCE_COMMIT` (40 lowercase hex) | `state-replay.rs:4529, 4541-4549` | **every sealed spool**, including BlockChanges |
| `BACKFILL_RUNTIME_IMAGE_DIGEST` (`sha256:<64hex>`) | `:4530, 4550-4552` | every sealed spool |
| `BACKFILL_STATE_REPLAY_SHA256` | `:4531` | every sealed spool |
| `BACKFILL_SPKG_SHA256` | `:4537, 4050` | every sealed spool |
| `BACKFILL_COMPATIBILITY_CONTRACT_SHA256` | `:4539, 4052` | every sealed spool |
| `BACKFILL_SPKG_MODULE` | `:4538` | optional; enforced only with shadow |
| `BACKFILL_SUBSTREAMS_NATIVE_SHA256` | `:4532-4536, 4574-4579` | **must be unset** for the BlockChanges spool. `copy_spool_producer(false,false)` is called at `:2823`, so the code treats native transport as unused even when frames came from `substreams-native`. That is a provenance gap worth fixing. |
| `BACKFILL_POI_WORKERS`, `BACKFILL_POI_BATCH_SIZE` | `:557, 565` | V4 PoI worker pool only |
| `BACKFILL_WAL_COMPRESSION`, `BACKFILL_CLAMP_LOAD_MODE`, `BACKFILL_TABLE_LOCK_MODE` | `:3918-3962` | V4 direct psql |
| `BACKFILL_WORKING_CHECKPOINT` | `:3963`; refused for BlockChanges at `:2314-2319` | V4 |
| `BACKFILL_PROTOBUF_DECODE_AHEAD` | `:3976`; Store modes only, `:4030-4040` | V4 |
| `BACKFILL_HOT_PATH_TELEMETRY` | `:3989` | all |
| `BACKFILL_BLOCK_CHANGES_SHADOW` | `:4002`; store-state, clock-v1, exact only, `:4113-4137` | V4 |
| `BACKFILL_COMPATIBILITY_PROFILE` (`graph-node-exact` / `postgres-nul-truncate-v1`) | `:4015` | V4 |
| `BACKFILL_ASYNC_SPOOL_WRITERS`, `BACKFILL_ASYNC_SPOOL_QUEUE_BUFFERS` | `src/sink.rs:2893, 2902` | spool writer |
| `BACKFILL_EXPECTED_BLOCK_CHANGES_SHADOW_POLICY`, `BACKFILL_POSTGRES_WORK_MEM_MB` | `src/bin/postgres-spool-load.rs:112, 1193` | V4 loader |

The shell drivers add their own variables, all V4-oriented (DOC and VERIFIED in
`scripts/compute-postgres-segment.sh:25-73`):

- `SUBSTREAMS_INPUT_MODE`, `SUBSTREAMS_NATIVE_FRAME_FORMAT`;
- `DIRECT_POSTGRES_SPKG`, `DIRECT_POSTGRES_MODULE`,
  `DIRECT_POSTGRES_COMPATIBILITY_CONTRACT`;
- `ENDPOINT` (default `base-substreams-tier1-prod.kan-sst2.pinax.io:443`);
- `SUBSTREAMS_PARALLEL_WORKERS` (default 500);
- `SUBSTREAMS_LIMIT_PROCESSED_BLOCKS`;
- `BACKFILL_PREWARM_SUBSTREAMS`, `BACKFILL_PREWARM_ATTEMPTS`,
  `BACKFILL_PREWARM_RETRY_SECONDS`;
- `GRAPH_NODE_WRITER_STOPPED=1`;
- `PG*`;
- `BACKFILL_LONG_LIVED`, `BACKFILL_ROLLING_RETENTION`,
  `BACKFILL_DEFER_SECONDARY_INDEXES`, `BACKFILL_SEGMENT_PREFLIGHT_BIN`.

No shell driver invokes the `BlockChanges` mode. Only `scripts/v3-milestone.py`
touches the generic artifacts (`grep` over `scripts/`).

---

## 2. What a producer must supply on the family-neutral path

### 2.1 Wire envelope: BCF1 "clock-v1" (VERIFIED)

Writer: `cmd/substreams-native/main.go:450-476`. Reader:
`src/bin/state-replay.rs:3417-3473`. All integers are big-endian.

| Bytes | Field | Rule |
| --- | --- | --- |
| 0..4 | magic `BCF1` | otherwise "unknown magic" |
| 4 | kind | `1` = Observed, `2` = SyntheticRangeFill; anything else is refused |
| 5..8 | reserved | must be `00 00 00` |
| 8..16 | block number (u64) | must be ≤ `i32::MAX` (`:3143, 3439-3444`) |
| 16..48 | block hash (32 bytes) | Observed: non-zero. Synthetic: all zero |
| 48..52 | payload length (u32) | ≤ 256 MiB (`:3142`). Synthetic frames must have length 0 |
| 52.. | payload | exactly one canonical `BlockChanges` message |

Stream and range rules for a spool (`ClockV1SingleOutputRange`,
`state-replay.rs:3176-3245`):

- frames must be contiguous from `--expected-head-block + 1` to `--head-block`;
- no frame may pass the target;
- the target block must be an **Observed** frame whose envelope hash equals
  `--head-hash`.

Rules in `BlockChanges` mode (`src/block_changes_input.rs:494-548`):

- **An Observed frame with an empty payload is refused**
  (`EmptyObservedFrame`, `:525-529`).
- A synthetic frame must be empty. It counts as an untriggered block: no PoI,
  no `Poi$` version.
- The message's `block_number` and `block_hash` must equal the envelope's.
- When a v1 sidecar or v2 chunk is used, synthetic frames are refused
  altogether (`state-replay.rs:2555-2557, 2582-2584`). Every block must then
  be an Observed frame carrying a payload.

### 2.2 Payload: `pinax.graph.backfill.v1.BlockChanges` (VERIFIED)

Schema: `third_party/backfill-common/proto/block_changes.proto:1-215`.
Validator: `third_party/backfill-common/src/block_changes.rs`, vendored from
`substreams-backfills/common` and pinned in the V4 descriptor's
`block_changes_contract` section.

Decoding (`decode_canonical_block_changes`, `block_changes.rs:757-768`)
re-encodes the message with prost 0.13.5 and **byte-compares** it. Any
non-canonical encoding is refused.

The producer must:

- set `contract = "pinax.graph.backfill.block-changes/v1"` (`block_changes.rs:12, 774-776`);
- set `compatibility_id` to the 32-byte **SHA-256 of the exact descriptor
  bytes**. It must be non-zero and match (`:777-787`; computed in
  `from_descriptor`, `:84-86`);
- set `deterministic_error_policy` to FATAL or NON_FATAL, equal to the
  descriptor's value (`:788-800`). Aerodrome declares `nonFatalErrors`, so it
  is NON_FATAL;
- set `block_number` ≤ `i32::MAX` and a 32-byte `block_hash` (`:801-810`);
- set `mapping_triggered`. False requires no operations and no regions
  (`:1070-1075`). An untriggered block is therefore a valid, non-empty message,
  which matters for §3;
- set `triggered_poi_causality_regions` to a sorted, unique list that is empty
  or exactly `["ethereum/<network>"]` (`:811-818, 1077-1087`);
- order `operations` with:
  - a dense zero-based `operation_index`;
  - non-decreasing `handler_group_order`;
  - `source_trigger_order`;
  - `handler_order`;
  - `source_causality_region`, where 0 means onchain and emits PoI;
  - `poi_causality_region`, present exactly when the operation emits a PoI
    event.

  Handler-group consistency, deterministic-error redaction counts, disposition
  linkage and terminal-failure ordering are all checked (`:820-1067`);
- for `SetEntity`, supply:
  - the typed `EntityKey`;
  - `poi_entity_type` and `poi_entity_id`, which must equal the key's type and
    canonical ID;
  - `written_fields`: the exact schema-filtered entity Graph Node hashed,
    before merge;
  - `materialized`: the full get-visible entity after the save. It is
    **required** for committed saves (`:1139`);
  - `store_disposition`;
  - `failure_stage`.

  Field lists must be strictly sorted by name, valid GraphQL names, never
  `vid`, and nested at most 32 deep (`:1632-1669, 21`);
- use canonical values:
  - BigInt as minimal two's-complement big-endian, at most 435,412 bits;
  - BigDecimal as a normalized coefficient plus scale: at most 34 significant
    digits, scale in [-6144, 6143], canonical zero (`:14-17, 1804-1890`);
  - timestamps in microseconds;
  - String IDs only, unless the test-only `--allow-non-string-entity-ids` is
    passed (`docs/block-changes-v1-input.md:304-310`);
- know that the engine replays every committed `SetEntity` against **its own
  known baseline** and refuses a `materialized` mismatch
  (`src/generic_state.rs:18-25`, doc `block-changes-v1-input.md:126-129`).

PoI is folded from the frame's own operations (`src/poi_events.rs` and
`src/poi.rs`). A Set hashes `written_fields` as an unordered set, a Remove
hashes the caller's type and ID, and a `DeterministicError` hashes
`redacted_events`. Only blocks that open the region advance the digest
(`block-changes-v1-input.md:143-220`). Fast and legacy folds are selected by
the descriptor. Thirty-three Graph Node–generated digests back the encodings
(`tests/poi_graph_value.rs`).

### 2.3 Compatibility descriptor plus `.sha256` sidecar (VERIFIED)

Load path: `BlockChangesInput::load` (`src/block_changes_input.rs:195-288`)
and `BlockChangesCompatibility::from_descriptor` (`block_changes.rs:42-92`).

- **Sidecar.** `<descriptor>.sha256` sits beside the file. It is computed with
  `with_extension("sha256")`, so `foo.json` maps to `foo.sha256`. It holds a
  bare 64-hex digest that must equal SHA-256 of the descriptor bytes
  (`:402-430`).
- **Required JSON fields:**
  - `"contract": "pinax.graph.backfill.block-changes/v1"`;
  - `"descriptor_version": 1`;
  - `"deterministic_error_policy": "fatal" | "non_fatal"`;
  - non-empty `"network"`;
  - `"expected_poi_causality_region": "ethereum/<network>"`, which must equal
    `ethereum/` plus the network (`:80-82`);
  - `"graph_node": {"poi_version": "fast" | "legacy"}`. No default exists; an
    unknown value is refused (`block_changes_input.rs:258-271`).
- **Read when present:**
  - `fixture_only` (true is refused without `--allow-fixture-descriptor`,
    `:230-238`);
  - `adapter` and `deployment` (copied into the manifest and checkpoint
    binding).
- **Cross-checked against the physical profile when present**
  (`state-replay.rs:393-433`, `src/physical_writer.rs:476-488, 558-659`):
  - `deployment`, `network`;
  - `graph_node.version`, `graph_node.commit`, `graph_node.dump_format`;
  - `graft_base`, `graft_block`;
  - `producer_contract.module`, `producer_contract.module_hash`,
    `producer_contract.output_type`.

  A field present in only one document "makes no claim". A live-catalog
  profile refuses a `fixture_only` descriptor. A hermetic profile binds only
  under `--allow-test-only-physical-profile`.
- **Example generic descriptor:**
  `fixtures/mapping-host-v3-stream/block-changes-descriptor.json`. It is
  produced by the mapping-host. It pins ABIs, manifest, mappings and schema
  (each with CID and sha256), the `block_changes_proto` and `prost_binding`
  hashes, `spec_version`, `storage_profile.entity_types`,
  `manifest_features` and `producer`. It does **not** carry
  `producer_contract`.
- **V4 descriptor:** `adapters/uniswap-v4-base/block-changes-v1.json` (shadow
  only). It additionally pins about 60 engine source and script hashes,
  `producer_contract` (SPKG, module, module hash) and the deployment
  artifacts.
- **Circularity hazard (inferred from the code).** If a *Substreams module*
  writes `compatibility_id` into each message, the descriptor SHA must reach
  the WASM, as a constant or a param. Substreams module hashes include param
  values (`~/Github/substreams/manifest/signature.go:151-175`). So a
  descriptor that also pins `producer_contract.module_hash` would be circular.
  Possible breaks:
  - pin the module hash only in the physical profile and spool receipts, not
    in the descriptor;
  - stamp `compatibility_id` in a client-side re-framer. Note that
    `substreams-native` is forbidden to touch payloads (`AGENTS.md:105-106`).

### 2.4 Physical schema profile plus `.sha256` sidecar (VERIFIED)

Grammar: `src/physical_profile.rs`. Runtime: `src/physical_writer.rs`.
Documentation: `docs/physical-schema-profiles.md`. Selection:
`SelectedPhysicalProfile::load` (`physical_writer.rs:496-515`) checks the
sidecar and then `validate()`. `compile()` (`:519-555`) refuses:

- `metadata.data_sources.write_policy == template_instantiated_rows` without
  the test-only acknowledgement (`:532-539`). Aerodrome has a template, so it
  needs the acknowledgement. The refusal is driven by the old "no
  data-source event" assumption; the sidecar and chunk path now supplies those
  rows;
- `evidence.production_selectable == false` without the acknowledgement
  (`:540-544`).

Top-level shape (`physical_profile.rs:50-68`, `deny_unknown_fields`
everywhere):

- `format = "pinax.graph-node.physical-profile"`, `format_version = 1`,
  `profile_id`.
- `evidence`:
  - `kind` is `hermetic_fixture` or `live_catalog`;
  - `production_selectable`;
  - `target_authorization: separate_hashed_receipt`.

  A hermetic fixture can never be selectable (`:696-701`). A `live_catalog`
  profile must declare `provenance` with every section
  `captured_and_retained` (`:702-710`).
- `deployment`: `deployment`, `network`, `spec_version`, `graft` as
  `{base, block}` or null.
- `graph_node`: `version`, `commit` (40 hex), `dump_format`.
- `artifacts`:
  - `schema` (path and sha256);
  - `schema_inventory` (sha256 and enums);
  - `logical_physical_bindings` (evidence path and sha256);
  - `manifest`;
  - `mapping_inventory`, a list of declarations with `ordinal`, `source_kind`
    (`data_source` or `template`), `source_name`, `api_version`, `language`
    and `wasm_path`;
  - `wasm[]`. The declared WASM set must equal the pinned set (`:742-758`).
- `producer`: `spkg` (path and sha256), `module`, `module_hash` (40 or 64
  hex), `output_type`, `protocol` (path and sha256), `compatibility_profile`
  (name and sha256) (`:269-276, 759-771`).
- `runtime`: `image` as a digest reference, and `binaries` equal to
  **exactly** `postgres-spool-load`, `state-replay` and `substreams-native`
  (`:774-783`). A profile must pin a `substreams-native` hash even when the
  producer is not `substreams-native`.
- `metadata`:
  - `head: exact_block_and_hash`;
  - `health: healthy_and_not_failed`;
  - `graft: match_pinned_or_absent`;
  - `registry: separate_audited_gate`;
  - `poi` as `{version, write_policy: versioned_entity_cache}`;
  - `data_sources.write_policy`;
  - `vid` as `{allocation, graft_copy}`. It must agree with `spec_version`
    (`:796-827`).
- `catalog`: `sha256`, `canonicalization`, and a `snapshot` of tables,
  columns, sequences, indexes and constraints. The schema is normalized to
  `$schema`; the canonical JSON is hashed (`:1386`; doc `:132-186`).
- `tables[]`:
  - `ordinal`, `logical_entity`, `physical_table`;
  - `role` (`entity`, `poi` or `data_sources`);
  - `layout` (`mutable_block_range` or `immutable_block`);
  - `load_policy` (`append_versions_and_clamp`, `append_immutable`,
    `seed_preserved` or `append_dynamic_data_source_rows`);
  - `entity_count` (`active_entity_delta` or `none`);
  - `has_causality_region`, `vid_sequence`;
  - `fields[]` of `{graphql_field, graphql_type, physical_column, value_kind
    (scalar | relation{target_entity} | enum{postgres_name})}`
    (`:578-660`).

Hard constraints that matter for a new family:

- **specVersion ≥ 1.3.0 is not representable.** Graph Node then emits
  `vid bigint` with no sequence, and format v1 refuses any entity or PoI table
  that claims a sequence (`physical_profile.rs:1046-1056`, doc `:188-222`).
  Aerodrome is 1.2.0, which is fine. Many newer subgraphs use 1.3.0 or later
  and would need a profile format bump.
- **No immutable tables in the generic spool.**
  `StreamingDumpBuilder::new_with_profile_generic` refuses any immutable table
  up front, because the checkpoint carries no immutable-ID set
  (`src/sink.rs:1812-1832`). Aerodrome has none (all 20 `@entity` without
  `immutable: true`, verified in `reference/schema.graphql`).
- **Committed removes are refused per block**
  (`state-replay.rs:2628-2638`). The Aerodrome WASMs import no `store.remove`
  (verified by string scan of `reference/mappings/*.wasm`).
- Only `uniswap-v3-mainnet-ancestry-hermetic.json` has a `.sha256` sidecar
  among the fixtures. Any new profile needs its own sidecar.
- **Template for Aerodrome:**
  `fixtures/physical-profiles/uniswap-v3-mainnet-hermetic.json` (22 tables:
  20 entities, `poi2$` and `data_sources$`, all `block_range`, 286 columns).
  Its `producer` section is placeholders: `module: map_block_changes`,
  `output_type: proto:pinax.graph.backfill.v1.BlockChanges`, all-zero-ish
  digests. The intended design was a Substreams-like `map_block_changes`
  producer, but it was never resolved.
- **Production selectability needs** (doc `:540-565`):
  - a live catalog captured from a disposable scratch deployment of the same
    manifest;
  - resolved producer and runtime pins;
  - writable removes and immutable tables;
  - a certified range.

### 2.5 Dynamic-source companion (`data_sources$`) (VERIFIED)

`BlockChanges` v1 itself carries **no** data-source-creation event. Without a
companion, a profile with a written `data_sources$` is refused, or sealed as
`INCOMPLETE.json` under `--allow-omitted-data-sources`
(`state-replay.rs:2365-2383, 2856-2893`).

**v1 sidecar** (`--data-sources-sidecar`): contract
`pinax.graph.backfill.data-sources/v1`
(`third_party/backfill-common/src/dynamic_sources.rs:7-114`). It is JSON:

```json
{
  "contract": "...",
  "descriptor_sha256": "...",
  "stream_sha256": "...",
  "root_start_block": "...",
  "blocks": [
    {
      "block_number": "...",
      "block_hash": "...",
      "payload_sha256": "...",
      "sources": [
        {
          "creation_block": "...",
          "manifest_idx": "...",
          "causality_region": 0,
          "param": "<40-hex address>",
          "context": null,
          "done_at": null
        }
      ]
    }
  ]
}
```

Limits and rules:

- 1 to 10,000 blocks and at most 16 MiB;
- it covers **every** frame, contiguous from the root start;
- it carries a per-frame payload digest plus a whole-stream digest
  (`state-replay.rs:2571-2580, 2675-2681`);
- it refuses checkpoint input, grafted profiles, synthetic frames, unknown
  template indices, duplicate identities, non-NULL context, and any
  deterministic error (`state-replay.rs:2340-2364, 2640-2647`).

The root start must be `expected_head_block + 1` with a zero expected hash. It
is therefore **root-only**.

**v2 chunks** (`--data-sources-chunk` plus `--input-generic-spool`,
`docs/data-sources-chunks-v2.md`):

- The producer seals a `.ready` directory with exactly six files: `blocks.bcf1`,
  `data-sources.json`, `host-checkpoint.json` (opaque to the engine; only its
  hash is pinned), `source-identities.bin` (`BCDSIDX2`), `manifest.json` and
  `READY.json` (`dynamic_sources_v2/seal.rs:14-21`).
- Each chunk is at most 10,000 blocks and 16 MiB
  (`dynamic_sources_v2.rs:13-15`).
- Continuation needs the immediately preceding **engine** spool; the producer
  parent witness must match it.
- The output is manifest v2 plus a `BCGCKPT2` checkpoint.
- It is still ungrafted root lineage only. It refuses removes, grafts, errors
  and non-NULL context.
- Doc `:1-5`: "offline generation capability, not production certification or
  a database loader."

Aerodrome arithmetic: 13,843,704 → about 52.87M is about 39M blocks, so about
**3,900 chunks**. Each chunk re-reads and re-writes the full `BCGCKPT2`
(complete generic store).

### 2.6 Heads, checkpoints and resume (VERIFIED)

- **Without a checkpoint** the replay starts from an empty store, VIDs start
  at 0, and `--expected-head-hash` **must be 64 zeros**
  (`state-replay.rs:2467-2479`). PoI is unseeded, matching Graph Node's
  `pause(None)` (`block_changes_input.rs:324-345`).
- **Resume** goes through `--input-generic-checkpoint` (`BCGCKPT1`) or the
  `--input-generic-spool` predecessor (`BCGCKPT2`). The binding must match
  exactly: deployment, network, descriptor sha, profile id, profile sha, ID
  policy, PoI version and region (`state-replay.rs:2385-2395, 2435-2466`;
  `src/generic_checkpoint.rs:204-244`).
- `GenericCheckpoint` is deterministic MessagePack behind the magic
  `BCGCKPT1`. It holds the **complete generic store**, active versions as
  (table, id, VID, range start), per-table max VIDs, the PoI digest, the live
  `Poi$` version, totals, and the boundary block and hash
  (`docs/block-changes-v1-input.md:406-443`).
- **There is no tool that builds a `GenericCheckpoint` from an existing
  Graph Node schema.** The only seed capture,
  `scripts/capture-direct-postgres-seed.sh`, defaults `DEPLOYMENT_ID` to the
  V4 deployment and hard-codes the V4 entity and table list (`:27, 81-104`).
  It emits a V4 `ReplaySnapshot`.

### 2.7 Spool output (VERIFIED, `state-replay.rs:2493-2933`; doc `:342-404`)

A spool is built in `<out>.building` and atomically renamed to `<out>.ready`.
It contains:

- `spool/<table>.rows.csv` and `spool/<table>.clamps.csv` in profile catalog
  order;
- `checkpoint.generic.pending`;
- `manifest.json` with format `pinax.graph-node.block-changes-copy-spool`,
  version 1, or 2 with chunks;
- `READY.json` when the spool is faithful, or `INCOMPLETE.json` otherwise.

The certified V4 loader `postgres-spool-load` **refuses** this manifest format
(`src/bin/postgres-spool-load.rs:756-782`). Only the V3 milestone loaders
consume it.

### 2.8 Loaders for generic spools (#80, #84) (VERIFIED)

- **`scripts/v3-milestone.py`** (#80, Python). Packaged as image
  `ghcr.io/pinax-network/substreams-graph-node-backfill@sha256:9a1e72f5…`
  (#82).
  - Fresh-only: the target head must be NULL with zero entities.
  - Pins the single ancestry profile digest.
  - Requires real dynamic-source rows; allows only manifest index 2 (Pool)
    with NULL context.
  - Requires Kubernetes labels `backfills.pinax.network/disposable: "true"`
    and `app.kubernetes.io/part-of: v3-mainnet-milestone`, and all Graph Node
    workloads stopped.
  - Root-capped at 1,153 blocks.
  - (DOC: `docs/v3-disposable-milestone.md:1-151`.)
- **`v3-root-load`** (#84, native Rust; image
  `…@sha256:5c1e7fa016a46411f039c2e97dacf5df9ba1c24bc871dc510c02aae1000469e0`,
  tag `v3-root-loader-sha-5c98b572…`). Flags:
  - `--artifact`, `--predecessor`, `--previous-result`, `--journal`;
  - `--profile`, `--descriptor`;
  - `--kubeconfig`, `--namespace`, `--control-namespace`, `--run-id`,
    `--control-uid`;
  - `--postgres-statefulset`, `--postgres-pod`, `--postgres-pvc`;
  - `--statefulset-uid`, `--pod-uid`, `--pvc-uid`;
  - `--candidate-schema`, `--reference-schema`;
  - `--output`, `--allow-disposable-load`.

  Modes are `load` and `recover` (`src/bin/v3-root-load.rs:125-151, 805-855`).
  **Hard pins:**
  - `ROOT=Qme66…`, `START=12,369,621`, `MAX_BLOCKS=1,153`, 256 MiB and 48
    files;
  - exact `PROFILE_SHA` and `DESCRIPTOR_SHA` (`src/v3_root_load.rs:20-25,
    37-76`);
  - Kubernetes server `https://kan-subgraphs-a.kube.pinax.io/`
    (`v3-root-load.rs:24`);
  - target `subgraphs.deployment.subgraph == ROOT`, graft fields NULL,
    healthy, no non-fatal errors (`src/v3_root_load/transaction.rs:147-161`);
  - a fresh load requires a NULL head and `entity_count = 0` (`:221-223`).

  SQL behavior: VIDs come from the spool, sequences are set with
  `ALTER SEQUENCE … RESTART`, and the head update clears `firehose_cursor`
  (`:346, 383`). It uses a two-phase durable journal plus read-only recovery
  (DOC `docs/v3-root-load-operator.md:75-121`). The doc states it is "not
  invoked by the current Kubernetes pipeline … not certified" (`:1-8`).

**Bottom line:** both generic loaders are Uniswap-V3-root-specific and must be
generalized (parameterize deployment, profile and descriptor pins, block and
byte budgets, and the API server) before any Aerodrome use.

---

## 3. Can a Substreams module emit `BlockChanges` directly, and what is the transport?

### 3.1 Transport that exists today (VERIFIED)

- **`cmd/substreams-native`** (Go, `main.go:1-616`) uses the official
  `streamingfast/substreams/sink`:
  - `sink.IgnoreOutputModuleType` (`:114`), so **any** module output type is
    accepted;
  - `SubstreamsModeProduction` (`:124`);
  - flags `--limit-processed-blocks`, `--include-empty-frames` and
    `--output-format legacy-v1|clock-v1` (`:86-100`), plus standard sink flags
    (`-e`, `-s`, `-t`, `-H`, cursor).

  It writes `MapOutput.Value` bytes **unchanged** into frames
  (`:310-316, 393-416`). In clock-v1 it cross-checks the cursor against the
  Clock (`:297-309`) and fills skipped blocks with Synthetic frames when
  `--include-empty-frames` is set (`:335-340`). It holds and re-emits the
  target block as Observed after the range-completion cursor
  (`:341-347, 521-556`). It refuses undo signals (`:604-616`). Policy: it
  "must never decode, reorder, merge, or reinterpret the SPKG protobuf
  payload" (`AGENTS.md:105-106`).
- **The pipe.** Production is
  `substreams-native -e $ENDPOINT $SPKG $MODULE -s start -t end+1
  -H X-Substreams-Parallel-Workers:500 --limit-processed-blocks …
  [--output-format clock-v1 --include-empty-frames] | state-replay …`
  (`scripts/compute-postgres-segment.sh:160-169, 202-213`).
- **Prewarm** (`BACKFILL_PREWARM_SUBSTREAMS=1`) runs the same command into
  `/dev/null` with retries (`:179-200`). It does **not** use Substreams
  `noop_mode`, even though the request field exists
  (`~/Github/substreams/pb/sf/substreams/rpc/v2/service.pb.go:129-133`, "prepares
  the stores and caches on the server without sending any module output") and
  the CLI has `substreams sink noop` (`cmd/substreams/sink_noop.go`). A noop
  warm-up workflow could use either.
- **SPKG handling.** SPKGs are downloaded by Makefile targets
  (`download-spkg`, `download-runtime-spkgs`, `Makefile:127-152`) from
  `pinax-network/substreams-v4-subgraph` GitHub releases with
  checksum verification. They are checked against
  `adapters/uniswap-v4-base/compatibility.json` by
  `scripts/check-compatibility-contract.sh` and
  `verify-spkg-compatibility.sh`, which checks package name, version, network,
  module, module hash, output type and initial block. They are baked into OCI
  images. There is no SPKG building in this repo (`AGENTS.md:21-23, 156-159`).
- There is no Rust gRPC Substreams client and no file-based BCF1 replay tool
  beyond `cat file | state-replay` (tests do exactly this:
  `tests/mapping_host_stream.rs`).

### 3.2 Would the engine accept a Substreams stream of `BlockChanges`? (format: yes; semantics: see below)

Mechanically, yes: a module whose output type is
`proto:pinax.graph.backfill.v1.BlockChanges`, streamed by `substreams-native
--output-format clock-v1 --include-empty-frames`, piped into `state-replay
--input-format block-changes-v1-framed`. The obligations are:

1. **Never emit empty output.**
   - Production mode can skip empty map outputs (tier-2 streaming,
     `~/Github/substreams/pipeline/process_block.go:634-656`); those become
     Synthetic frames, which is acceptable without a sidecar.
   - Any *delivered* empty output, including live, development, or tier-1
     linear segments, and the always-Observed target block when it has no
     output, becomes an **Observed empty frame, which the engine refuses**
     (`block_changes_input.rs:525-529`).
   - With a data-source sidecar or chunk, Synthetic frames are refused
     altogether.
   - **Rule:** emit a non-empty `BlockChanges` for every block. Untriggered
     blocks get `mapping_triggered=false` and no operations.
2. Put the correct `compatibility_id` in every message (see the circularity
   note in §2.3).
3. Produce prost-canonical bytes. Compiling the vendored `backfill-common`
   into the module and calling `encode_canonical_block_changes` and
   `validate_block_changes` is the obvious route. Its dependencies are
   `prost`, `num-bigint`, `chrono`, `sha2`, `serde_json` and `hex`; `rustix`
   is gated to linux and macOS (`third_party/backfill-common/Cargo.toml`), so
   it probably compiles to `wasm32`. **Not verified.**
4. Emit dynamic-source creations as a companion artifact. That requires a
   second output (another module, or a client that builds the sidecar or v2
   chunk from the stream).

**The real blocker is semantic, not transport.** The producer must emit, per
save:

- the full post-save `materialized` entity;
- the exact `written_fields`;
- Graph Node's handler and trigger ordering, including re-processing a block's
  triggers for a data source created earlier in the same block
  (`block_changes.proto:49-59`);
- `eth_call` results at the block;
- Decimal128 arithmetic.

For an AMM mapping, entity state is recurrent:

- `Token.derivedETH` reads persisted peer state;
- volume and TVL accumulators round after every operation;
- a store writer cannot read the store it writes.

The engine's own feasibility study concludes Stores are "not, by themselves, a
complete replacement for the Graph mapping reducer". It keeps `derivedETH`,
Decimal accumulators and PoI in an **ordered** reducer
(`docs/substreams-stores.md:5-19, 120, 192-200`). A parallel and cacheable
Substreams module therefore cannot produce Aerodrome `BlockChanges`. Whatever
emits `BlockChanges` must run sequentially with full state.

### 3.3 What exists elsewhere, and what is missing

- **Existing `BlockChanges` producer:** `substreams-backfills/mapping-host`
  (out of the engine repo).
  - A hermetic Rust host running **deployed** mapping WASM under graph-node
    v0.44 runtime crates.
  - Reads Firehose `sf.ethereum.type.v2.Block` (live or fixtures) plus a
    fail-closed `eth_call` cassette.
  - Seals one canonical `BlockChanges` per block, plus v1 and v2 source
    companions (`mapping-host/README.md:1-90`, `src/calls.rs:1-67`).
  - Reads no Substreams modules (grep: only token environment variables).
  - The engine's V3 work (#78–#84) consumes exactly this producer.
- **Missing for the Substreams route:**
  - a `map_block_changes` module design that solves the recurrent-state
    problem. In practice that means running the whole mapping inside
    Substreams sequentially, which defeats the point;
  - or a hybrid in which Substreams pre-extracts triggers and `eth_call`
    results in parallel and a sequential host turns them into `BlockChanges`.
    No such input adapter exists in the mapping-host or the engine;
  - a client-side sidecar or chunk builder from a Substreams stream;
  - `substreams-native` provenance in generic spools (§1.3);
  - `noop_mode` warm-up.

---

## 4. How the V4 family plugs in, and what a new family must rewrite

### 4.1 Layout (VERIFIED)

- **Substreams source** lives in a separate repo
  (`pinax-network/substreams-v4-subgraph`). Manifests: `substreams.yaml`
  (`map_events` with params for deployment, graft and contract addresses),
  `substreams-stores.yaml`, `substreams-store-fed.yaml`,
  `substreams-store-state.yaml` (Stores including 64 tick-liquidity shards plus
  `map_store_state_inputs`). Rust source `src/*.rs` is 856 lines. It uses
  `substreams_ethereum::rpc::eth_call` for ERC-20 metadata
  (`src/metadata.rs:7, 48`). Release metadata is in `packages/*.json`, with
  CI `release.yml` and `parity.yml`.
- **Engine adapter directory** `adapters/uniswap-v4-base/`:
  - `compatibility.json` is the machine-readable authority: SPKG repo,
    release, asset, sha256, package name and version, module and hash, output
    type, initial block; store and store-state packages with imported module
    hashes and shard lists; `direct_postgres` defaults; `runtime` (image
    digest and four `binary_sha256`); `graph_node` (version, commit,
    dump_format).
  - `store-state-v0.5.0.json` is the candidate producer lock.
  - `block-changes-v1.json` and `.sha256` are the shadow descriptor.
  - `production-resume-q8.json` and `production-compatibility-nul-v1.json`
    are certificate trust roots.
- **Other V4 pieces:**
  - `artifacts/deployment/<cid>/` holds IPFS bytes plus the Graphman v0.44
    normalized copies.
  - `fixtures/*.json` holds ranges and certificates.
  - `proto/events.proto` and `proto/reducer_inputs.proto` are consumer copies.
  - `src/pb/pinax.uniswap.v4.base.*.rs`.

### 4.2 V4-specific Rust vs reusable (VERIFIED line counts)

| File | Lines | Status for a new family |
| --- | ---: | --- |
| `src/reducer.rs` | 1,460 (about 360 tests) | **Rewrite.** Exact mapping handlers, save order, pricing (`initialize`, `swap_impl`, `modify_liquidity_impl`, interval updates, `find_native_per_token` …, `:64-1088`) |
| `src/state.rs` | 639 | **Rewrite** the `EntityState` with 18 named maps (`:88-266`). `EntityBody::{V4, Generic}` and `EntityChange` are shared (`:28-74`) |
| `src/entities.rs` | 334 | **Rewrite.** 18 entity structs and the closed `EntityRecord` enum (`:8-334`) |
| `src/store_fed.rs` | 1,196 | **Rewrite** if a Store-state design is used |
| `src/snapshot.rs` | 262 | V4 `ReplaySnapshot` (compact Tick). Rewrite, or use the generic checkpoint |
| `src/bin/state-replay.rs` | 6,996 | JSON decoders `record()`, `event()` and `payload()` (`:4663-5150`, about 500 lines) and the V4 main loop are V4. Framing, spool sealing and producer identity are reusable |
| `src/sink.rs` | 6,087 | Static `V4_CATALOG` (`:308`) and `entity_cells` (`:757`) are V4. Profile-driven catalog, generic block apply (`:1812-2300`), COPY, clamps, VIDs and journals are reusable |
| `src/poi.rs` | 2,241 | `entity_data()` 18-arm match is V4. Fast and legacy folds, worker pool and `PoiValue` union are reusable |
| `src/decimal.rs`, `src/math.rs` | 210 + 216 | **Reusable**: Graph Decimal128 and bigdecimal 0.1.2 semantics. Uniswap tick math is probably reusable for Slipstream (V3-style CL) |
| `src/compatibility.rs` | 89 | V4 NUL-truncation profile (Token symbol and name) |
| `src/block_changes_shadow.rs` | 683 | V4 → `BlockChanges` projection; a pattern to copy |
| Generic: `generic_state.rs` 1,393, `block_changes_input.rs` 1,750, `generic_checkpoint*.rs` 808, `physical_profile.rs` 4,399, `physical_writer.rs` 988, `poi_events.rs` 189, `source_chunk.rs` 586, `v3_root_load*` 1,283 | about 11.4k | **Reusable as is** for the family-neutral path |
| `scripts/*.sh` | about 45 drivers | Mostly V4-coupled (table lists, deployment default, input modes). Reusable skeleton: compute, load, pipelined driver, VID audit, secondary-index manager |

### 4.3 Size estimate for Aerodrome

**Route A: V4-style.** A family Substreams `map_events` plus optional Stores,
and a family reducer in the engine.

- Substreams module: decode Factory, NPM and Pool logs across about 30M Pool
  instances; reproduce the mapping's `eth_call` set (ERC-20
  symbol/name/decimals/totalSupply, NPM `positions`, any Pool calls); emit
  ordered events. Estimate **1.0–1.5k Rust lines** (V4 is 856), plus
  manifests and CI.
- Engine reducer, state and entities for 20 Slipstream entities, ported from
  the deployed AssemblyScript (the Uniswap-V3-subgraph lineage). Estimate
  **3–5k Rust lines** plus tests.
- Plus entity-cell or profile wiring and a PoI projection. The PoI projection
  can be avoided by emitting `BlockChanges` from the reducer, as
  `block_changes_shadow.rs` does, and reusing the generic PoI, spool and
  checkpoint.
- Plus a seed capture for the 20 tables and adapter, fixtures and
  certification.
- Proven at Base scale for V4 (about 3.5 blocks/s end to end recorded in
  memory notes; 20.19 blocks/s for a 100k segment, `README.md:1085-1097`).
- It supports continuing from an existing Graph Node head (§5.3).

**Route B: generic `BlockChanges`.** Producer = mapping-host (exists) or a new
producer. Engine work:

- generalize `v3-root-load` and `v3-milestone` pins;
- a generic seed capture, only if continuing from 34.7M;
- profile authoring plus live catalog capture;
- a disk-backed generic store and checkpoint (#70 generalized);
- longer chunk support.

Estimate **2–4k lines** of engine changes, plus the open question of
mapping-host throughput, which this survey did not measure.

---

## 5. PoI, VIDs, `block_range`, `data_sources$`, landing, and "same logical deployment"

### 5.1 Physical semantics (VERIFIED unless marked)

- **block_range and clamps.** For a mutable table the writer opens a new
  version `[b, ∞)` and clamps the prior version's upper bound by VID. For an
  immutable table it writes `block$`. Within a block, saves are coalesced to
  the block-final image, compared with the block-start original, and spooled
  per block (no segment-wide vectors) (`docs/direct-postgres.md:70-126`;
  generic: `sink.rs:2135-2300`, `state-replay.rs:2639, 2663`).
- **VIDs.** Below spec 1.3.0, every layout table is `bigserial`. The writer
  allocates `max_vid + 1…` from the checkpoint's table maxima, and the loader
  resets sequences: V4 in its transaction, generic via `ALTER SEQUENCE …
  RESTART` (`transaction.rs:346`). `data_sources$` uses
  `integer generated by default as identity`; PostgreSQL assigns it in
  creation order (`physical-schema-profiles.md:224-256, 471-474`). Rules
  (`AGENTS.md:53-58`):
  - never resume from a fresh SQL export, because VID allocation domains
    differ;
  - the first direct segment must use a seed captured from the exact target
    schema, because Graphman restore renumbers VIDs.
- **PoI.** `poi2$` (logical `Poi$`, id `ethereum/<network>`) gets a new
  versioned digest row for each block that opened the region. The legacy or
  fast fold is per the descriptor. A grafted or continued deployment must seed
  the digest from the parent and live `Poi$` version, not zero. V4 does this
  with `export-active-poi-seed.sql`; the generic path only via its own prior
  checkpoint.
- **`entity_count`.** It is the signed active delta per table; `data_sources$`
  is excluded (`physical-schema-profiles.md:279-295`). The head update also
  clears `firehose_cursor` (`transaction.rs:383`; V4 algorithm step 8,
  `direct-postgres.md:118`).
- **`data_sources$`.** Rows are `(block_range=[creation,∞), causality_region=0,
  manifest_idx, parent NULL, id NULL, param=address bytea, context NULL,
  done_at NULL)` (`data-sources-sidecar-v1.md:39-46`;
  `sink.rs:290-299, 2298`). Order must survive because Graph Node loads
  templates by `(lower(block_range), vid)`.

### 5.2 Landing modes (VERIFIED and DOC)

- **Direct COPY into a stopped physical clone.** This is the fast path, V4
  only in production. It needs `GRAPH_NODE_WRITER_STOPPED=1` (operator
  attestation) and zero Graph Node replicas, and refuses `sgd1246`
  (`AGENTS.md:27-41`). The transaction:
  1. take an advisory lock;
  2. verify identity, health and the seed head/hash;
  3. verify table max VIDs;
  4. COPY versions;
  5. clamp via temporary tables;
  6. advance sequences;
  7. advance head and `entity_count`;
  8. commit, then promote the checkpoint (`direct-postgres.md:107-126`).
- **Sealed-spool two-stage** (`compute-postgres-segment.sh` →
  `load-postgres-spool.sh`): compute needs no database credentials.
- **Graph Node–native Parquet plus `graphman restore`.** This is the
  rollback and interchange path. It is V4 only: "Parquet output remains
  Uniswap v4-only" (`block-changes-v1-input.md:17`). It was 11.5× slower than
  direct COPY (`README.md:1085-1090`).
- **Generic spools** load only through the V3 milestone loaders into a fresh
  NULL-head target (§2.8).

### 5.3 "Same logical deployment" and continuation vs root

- **Definition (DOC, `README.md:1-6, 110-124`; `production-backfill.md:7-23`).**
  The output is the database history of the *existing deployment ID*. It lands
  in a physical copy of its own `sgd` schema; Graph Node later serves and
  continues it under the same ID. It is not a new deployment and not a graft
  child with a new ID. Production replacement is a separately approved
  cutover. Graph Node and the engine must never advance the same deployment
  concurrently.
- **V4 production shape (DOC and LIVE memory note).**
  1. Make an inactive physical copy of `Qmbsc6…` on Kan (`sgd5303`) while the
     original stays in service.
  2. Pause the copy at a healthy head (seed 32,374,183).
  3. Capture the seed from that exact copy (`capture-direct-postgres-seed.sh`:
     active mutable rows paged by VID, table max VIDs, active PoI).
  4. Run 100k-block segments direct COPY through a pipelined driver to the
     fixed target 49,477,581.
  5. Certify against an independent oracle (20 tables, PoI, GraphQL,
     continuation, restart, rewind, replay).
  6. Activate only via an approved cutover (`direct-postgres.md:1114-1141`).

  The original V4 deployment is itself a **graft child**; its seed carries the
  parent's retained history. "Never construct the production seed by replaying
  the child from empty state" (`README.md:121-124`).
- **Can the engine append history after an existing head?**
  - **V4 path: yes.** That is its main mode (seed at any healthy checkpoint,
    write the child range).
  - **Generic path: no, not today.** It requires either deployment start
    (all-zero expected hash, empty store, empty target with NULL head) or its
    own predecessor checkpoint or spool. There is no `GenericCheckpoint` seed
    capture. The v1 sidecar and v2 chunks refuse checkpoint or graft starts.
    The loaders require `graft_base` NULL and a fresh NULL head for the first
    load (`state-replay.rs:2467-2479, 2340-2349`;
    `transaction.rs:147-161, 221-223`).
- **Implications for Aerodrome at about 34.7M.**
  1. *Continue from 34.7M (V4 shape).* Requires a family seed capture: the
     V4-style script adapted to 20 tables, or a new generic seed tool that
     must export the *entire live store*, since every Aerodrome entity is
     mutable. It also requires a producer able to start from that state: a
     Route-A reducer seeded from the checkpoint, or the mapping-host's store
     loaded from the database.
  2. *Replay from root 13,843,704 into a fresh NULL-head copy of the same
     deployment ID.* This is what the generic path supports in principle.
     Requirements: a full-history producer, about 3,900 v2 chunks, generalized
     loaders, and a bounded-memory store.
- **Scale warning (LIVE, VictoriaMetrics `pg_stat_user_tables_n_live_tup`).**
  - Database `postgres-exporter-aerodrome` on kan-subgraphs-a holds one
    deployment schema, `sgd5311`, with `subgraphs.copy_state` and
    `public.active_copies` each at 1 row. That looks like an in-progress
    Graph Node copy of the Aerodrome deployment, but **identity not verified**.
  - Live row estimates: transaction 84.7M, token 77.2M versions, token
    hour/day data about 75.7M each, pool hour/day data about 66.3M each, tick
    and tick_day_data about 59M each, swap 52.4M, position and
    position_snapshot about 38.9M each, pool 32.7M, burn 24.2M, mint 17.7M,
    `poi2$` 13.7M, factory 13.6M. Total about 810M rows (flat over the last
    20 days).
  - The generic store holds every *live* entity in RAM, and all Aerodrome
    entities stay live. Swaps, Mints, Burns, Transactions and Snapshots alone
    are about 200M+ entities. The `GenericCheckpoint` serializes the whole
    store per segment or chunk. **This is the main engine blocker for a
    generic Aerodrome backfill.** #70 (disk-backed keyed store) is open,
    targets V4's `ReplaySnapshot`, and has no comments.
- **Live sync facts (LIVE).**
  - `deployment_head` is 34,726,689 (2026-10-20) on pod
    `graph-node-chain-base-0`, shard `subgraphshard_b`, worker_tier `steady`.
  - Daily advance over the last 12 days: 142k–210k blocks per day, then 0 for
    3 days (paused), then about 61.5k in the latest (partial) day.
  - Graph Node triggers per processed block rose from about 128 to about 253
    over the last 30 days. This increase is why Graph Node slows as it nears
    head.

---

## 6. Release and packaging (VERIFIED)

- **SPKGs.** These are immutable release assets of the *Substreams source
  repo*. V4 example: `pinax-network/substreams-v4-subgraph` releases
  v0.1.0/v0.4.0/v0.5.0, assets such as
  `uniswap-v4-base-store-state-reducer-v0.5.0.spkg`.
  - Pinned in `adapters/<family>/compatibility.json` by sha256, module, module
    hash, output type and initial block.
  - Downloaded and checksum-verified by Makefile and scripts; never rebuilt
    locally ("never recreate a package locally and copy its hash",
    `AGENTS.md:156-159, 281-286`).
  - The engine repo publishes **no** standalone SPKG (`AGENTS.md:193-197`).
  - A new family should follow the same split: Substreams source and releases
    in their own repo, and the engine pins bytes.
- **Runtime images** (`Dockerfile`, 660 lines, about 35 stages).
  - Almost every stage `FROM`s an immutable digest and overlays specific files
    with identity verifiers.
  - Generic or `latest` aliases are frozen retags of the certified v0.5
    runtime `sha256:dbb88e45…`.
  - The `BlockChanges`-capable binaries ship only in
    `block-changes-clock-v1-runtime` (`Dockerfile:392-420`): it is built from
    source on top of `dbb88e45`, requires `RUST_TARGET_CPU=x86-64-v3`
    (`:395`), and is published as tag `block-changes-clock-v1-sha-<commit>`
    (`.github/workflows/container.yml:62-93`). Current main:
    `sha256:49b9df1497d39a2d7187c33c7068349beb3951fd7569a3f1ce003d8c1194cec4`
    (LIVE GHCR listing; PR #84 audit). Kubernetes nodes must advertise
    x86-64-v3.
  - Separate images: `v3-milestone-tools-sha-<c>` (`9a1e72f5…`) and
    `v3-root-loader-sha-<c>` (`5c1e7fa0…`), each with an ORAS-attached
    deterministic archive and `runtime.json` (`container.yml:157-189`,
    `docs/v3-root-loader-image.md`, `docs/v3-milestone-tool-runtime.md`).
- **Release contract** (`AGENTS.md:174-205`, `release.yml:26-73`). It is
  pinned in two phases:
  1. Push the immutable OCI candidate.
  2. In a later PR, pin its digest and the four binary sha256s
     (`state-replay`, `parquet-backfill`, `postgres-spool-load`,
     `substreams-native`) in `compatibility.json`.
  3. A `v*` tag then **pulls** that digest (no rebuild), packages
     `dist/*.tar.gz` and `*-runtime.json` with an internal
     `runtime-sha256.txt`, runs `verify-release-runtime.sh` (archive equals
     image byte for byte), and publishes the GitHub release plus an immutable
     OCI tag.

  Pull-request candidates may set `REQUIRE_CERTIFIED_RUNTIME_BINARIES=0`;
  tags never do. "Kubernetes manifests must pin the resulting digest, not a
  mutable tag" (`README.md:1004-1007`).
- **Profile and descriptor pinning.** Binary hashes are recorded in spool
  manifests from environment variables (§1.3). Physical profiles additionally
  pin the image digest and three binary hashes (§2.4).

---

## 7. Aerodrome fit matrix against the engine's generic gates

| Gate | Aerodrome (verified in `substreams-backfills/aerodrome-slipstream-base/reference/`) | Engine status |
| --- | --- | --- |
| specVersion < 1.3.0 (sequence VIDs) | 1.2.0 (`deployment.yaml:95`) | OK |
| Immutable tables | none (20 × `@entity`) | OK (would be refused otherwise) |
| `store.remove` | not imported by Factory, NPM or Pool WASM | OK (would be refused otherwise) |
| Entity IDs | all `ID!` (String) | OK |
| Templates → `data_sources$` | `templates: Pool` (`:96-148`); Factory imports `dataSource.create` | Needs v1 sidecar (≤10k blocks, root only) or v2 chunks; profile needs the test-only acknowledgement |
| Graft | `graft: null`; `features` includes `grafting` | Root replay possible; continuation unsupported (generic) |
| `nonFatalErrors` | declared | Descriptor `non_fatal`. Any deterministic error is refused with a sidecar or chunk. Must prove zero `subgraph_error` over the range (the aerodrome copy database shows 0 live rows, LIVE) |
| `ethereum.call` | imported by all three WASMs | Producer must reproduce call results at the block (mapping-host cassette or Substreams RPC) |
| Profile | `layout-profile-v1.json` is a static behavior profile, **not** an engine `pinax.graph-node.physical-profile` | Must author a new engine profile (copy the V3 hermetic template), bindings, sidecar, and later a live catalog |
| Scale | about 810M physical rows (if `sgd5311` is Aerodrome); trigger density about 250 per block now | Generic in-memory store and checkpoint do not scale; #70-style store needed |

---

## 8. Doc vs code discrepancies noticed

- `README.md:845-855` says `BlockChanges` refuses PostgreSQL targets; the code
  supports `--postgres-spool-output` (`state-replay.rs:2294`).
- The `InputFormat::BlockChangesV1Framed` doc comment (`:3547`) still says
  "State-only until #67/#68".
- `generic_state.rs:38-40` says "Not writable yet … until engine issue #68",
  but the writer exists.
- `physical-schema-profiles.md:531-538` and the `compile()` refusal
  (`physical_writer.rs:529-539`) still describe `data_sources$` as having "no
  input", but sidecar and chunk inputs now exist (#81, #83).
- Engine issues #66–#69 remain open although their PRs merged (comments
  record the merges). #70–#72 are open with no comments. All of #66–#72 show
  `updatedAt` 2026-10-15, apparently a bulk edit.
- BlockChanges spool provenance requires `BACKFILL_SUBSTREAMS_NATIVE_SHA256`
  to be unset (`copy_spool_producer(false,false)` at `state-replay.rs:2823`),
  even when frames came via `substreams-native`.
