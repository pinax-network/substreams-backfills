# Uniswap V3 lane and mapping-host: state on 2026-10-20, and what it means for Aerodrome

Survey date: 2026-10-20. Scope: `substreams-backfills` `main` (`bbe3783`), engine
`substreams-graph-node-backfill` `main` (`5c98b57`), `k8s-subgraphs` `main`
(read-only snapshot), graph-node v0.44 source at rev `77823b5a` (read from the
local cargo git db), and live VictoriaMetrics reads.

Labels used below:

- **VERIFIED**: I read the code or data, or ran a read-only query.
- **CLAIMED**: a doc, PR or issue says it, and I did not re-execute it.
- **ESTIMATE**: my own arithmetic from verified inputs. The assumptions are stated.

---

## 0. TL;DR

1. **The V3 lane has been idle since 2026-09-08.** VERIFIED with `gh api`:
   - the last backfills commit is `bbe3783` (#147, 2026-09-08 03:59Z);
   - the last engine commit is `5c98b57` (#84, 2026-09-07);
   - k8s-subgraphs has no V3 commit after #910 (2026-09-08).
   - The released all-Kubernetes "whole/split root pilot" was the declared next step. There is no evidence that it ever ran (issue #118's last comment is 2026-09-08 10:54Z).
2. **What is proven end to end** is a bounded root window and nothing larger. CLAIMED with receipts, live-tested on 2026-09-04: the deployed V3 root mapping (`Qme66ZN…`) replayed 1,053 blocks, then:
   - COPY loaded into a fresh Graph Node 0.44 DB;
   - all 22 tables and PoI matched an independent official Graph Node reference (non-VID history only);
   - **all 20 GraphQL types matched at head and history**;
   - a 100-block continuation, a no-op restart, and a rewind/replay all passed.

   No full segment, no graft transition, and no production sync has happened.
3. **#117 (`data_sources$`) is solved for bounded root scope, not for production.**
   - It was solved with a *companion artifact*. The BlockChanges v1 wire format was not changed.
   - v1 sidecar: producer #142 plus engine #81/#80. It covers at most 10,000 blocks and was live-proven.
   - v2 sealed resumable chunks: producer #144 plus engine #83 (BCGCKPT2) and #84 (atomic append loader). These are proven offline and in local PostgreSQL 16 only.
   - Issue #117 is still OPEN.
4. **The mapping-host is family-neutral in code and can run Aerodrome's WASM.** VERIFIED:
   - Aerodrome's three mappings import only `store.get/set`, `ethereum.call`, `dataSource.create`, `log.log` and the bigInt/bigDecimal/typeConversion functions. All of these are supported.
   - Aerodrome is log-handlers only, has no `store.remove`, and has no context.
   - Its declared calls (spec 1.2.0) are safe to skip: in graph-node v0.44 they only warm the call cache.
5. **The mapping-host cannot do Aerodrome's full history as built.** The cause is state size, not semantics. VERIFIED from live `pg_stat` on `sgd2`:
   - Aerodrome holds about 1.3 billion row versions.
   - At least about 385 million live write-once event entities (Transaction, Swap, Burn, Mint, PositionSnapshot).
   - The host keeps every live entity in an in-memory `BTreeMap`. Its checkpoints are full-store JSON (about 1.5 KB per row). Its `eth_call` cassette is one JSON file that is loaded whole and rewritten whole.
   - The engine's generic checkpoint is also a full in-memory store.
   - All four need disk-backed redesigns before Aerodrome is even attempted.
6. **Throughput: the host would beat graph-node by about 2× at most, and it cannot be split into parallel ranges.**
   - The only mapping-host throughput numbers are from V3 mainnet: 10.9, 5.5, 4.2 and 1.9 blocks/s, at 0.16 to 1.83 handler groups per block.
   - They were measured *before* #147 removed a per-block full-store deep copy, and while recording `eth_call` serially with 120 ms pacing. So they say nothing about Aerodrome.
   - Live graph-node metrics for Aerodrome show 2.02 blocks/s, 48.9 handler invocations per block, and 0.495 s per block. Of that time:

     | Share | Component |
     |---:|---|
     | 35% | in-WASM compute (unavoidable) |
     | 27% | `store.get` |
     | 15% | `eth_call` |
     | 3% | transact |

   - The mapping-host can only remove the I/O share. Its single-threaded ceiling is about 3.5–5.8 blocks/s before its own overheads, so about 1.7–2.9× graph-node.
   - It cannot be split by range, because every block reads the full prior state.
7. **Running the deployed WASM inside a Substreams module is not viable.** Substreams can usefully pre-extract triggers and pre-record the `eth_call` cassette in parallel, but that does not touch the dominant serial WASM cost. For Aerodrome, the realistic options are:
   - **(a)** a native Substreams port (parallelisable), differentially checked against the existing `sgd2` history, which already covers blocks 13.84M–34.7M; or
   - **(b)** seed from a `sgd2` stop-point dump and append the remaining about 18M blocks (the V4 recipe).

   The mapping-host is best reused as an exact **oracle and contract toolkit** (BlockChanges, PoI, descriptors), not as the production producer.

---

## 1. Snapshot provenance and lane activity

| Repo | Remote `main` head (gh api, 2026-10-20) | Last V3-relevant change |
|---|---|---|
| substreams-backfills | `bbe3783` 2026-09-08T03:59Z (#147) | same |
| substreams-graph-node-backfill | `5c98b57` 2026-09-07T17:13Z (#84) | same |
| k8s-subgraphs | `4da0b37` 2026-10-20 | `68ede00` #910 (2026-09-08) parked the V3 worker. Only #992 (V4 COPY, 2026-10-02) touched `subgraphs-operations/backfill` afterwards. |

- Commits since 2026-09-04 in backfills (VERIFIED, `git log --since=2026-09-04 --stat`): #142, #143, #146, #144, #147.
- PR #145 does not exist (the `gh pr view` GraphQL error was "Could not resolve").
- Engine #66–#72 issue `updatedAt` 2026-10-15 shows no new comments (#70 has 0 comments). It looks like board or metadata churn only.

---

## 2. Q1: What is proven end to end for V3, what is blocked, and how #117 was resolved

### 2.1 Proven (strongest evidence first)

| Claim | Evidence | Status |
|---|---|---|
| The deployed V3 root WASM (`Qme66ZN…`, segment 1) runs faithfully under our own host, built on graph-node v0.44 crates (`77823b5a`) | `mapping-host/README.md:11-23,1430-1455`; `src/runner.rs:1-37,822-988` | VERIFIED code; CLAIMED goldens |
| A per-save operation stream comes from a vendored `graph-runtime-wasm` with a 119-line recorder patch | `mapping-host/Cargo.toml` `[patch]`; `README.md:144-184` | VERIFIED |
| 1,053 contiguous blocks `[12369621,12370674)` replay with 167 handler groups, 1,362 ops, 0 deterministic errors and 18 dynamic sources. Rate was 4.2 blocks/s while recording. | `mapping-host/evidence/parity-window-12369621-12370674.json` (`totals`, `cassette`); `README.md:1245-1313,1140` | VERIFIED evidence file |
| Producer and engine agree independently: a 300-block BCF1 stream through the engine CLI reproduces 142 entities and graph-node's own `ethereum/mainnet` PoI byte for byte | `docs/v3-mainnet-handoff-2026-09-04.md:70-72`; engine `docs/block-changes-v1-input.md:244-268` | CLAIMED (engine tests) |
| **Live bounded root milestone (2026-09-04)**. See the detail list below the table. | k8s `docs/v3-mainnet-root-milestone-2026-09-04.md:6-41,126-144`; engine PR #80 body; backfills #118 comment 2026-09-04T20:46Z; #117 checkbox 3 ticked | CLAIMED with receipt hashes |
| Resume is faithful: chunked equals uninterrupted (frames, BCF1 bytes, store, PoI) | `tests/mapping_host/checkpoint_resume.rs`; `README.md:839-865` | CLAIMED (CI) |
| v2 source chunks: real 300 versus 200+100 split are byte-identical (BCF SHA `9db817b7…`); runs took 406.51 s, 378.75 s and 360.38 s | PR #144 and #147 bodies | CLAIMED (local, not hosted CI) |
| Engine #84 atomic fresh/append load: in local PG16, whole 300 versus 200+100 gives identical physical hashes including VIDs across 22 tables | engine PR #84 body; #117 comment 2026-09-07 | CLAIMED; metadata synthetic |
| Published runtimes (digest-pinned, independently audited). See the list below the table. | PR #146 and #147 bodies; engine PRs #81/#82/#84 | CLAIMED with audit receipts |

Detail of the live bounded root milestone (2026-09-04):

- The producer and the engine ran **locally**. PostgreSQL, the independent Graph Node 0.44 oracle and the continuation ran in Kan.
- Atomic COPY loaded 966 rows across 22 tables, including 18 `data_sources$` rows.
- Exact non-VID history, PoI, data-source creation order and a sequence audit all matched.
- **GraphQL matched all 20 entity types**: 433 rows at head 12,370,673 and 142 rows at 12,369,920.
- A 100-block continuation created the 19th data source and reached head 12,370,773 (1,003 history rows, 449 active entities plus PoI).
- No-op restart, rewind and replay all passed.
- VIDs are **not** byte-identical: the two sides use different allocation domains, and this is stated explicitly.

Published runtimes:

- Producer `ghcr.io/pinax-network/substreams-backfills@sha256:6e45c4a7…` (#147 successor; the earlier #146 image is `sha256:2e083f80…`).
- Engine clock image `sha256:e34aabcd…` (#80/#81). The later #84 Container clock is `sha256:49b9df14…`.
- Engine milestone tools `sha256:9a1e72f5…`.
- Engine native root loader `sha256:5c1e7fa0…`.

### 2.2 Throughput numbers that exist (all V3 mainnet segment 1, all CLAIMED)

| Measurement | Rate | Conditions | Source |
|---|---|---|---|
| Parity window | 4.2 blocks/s (252 s for 1,053 blocks) | `--record`, 120 ms RPC pacing, 0.16 groups/block | `README.md:1140`, `README.md:297` |
| First long recording run | 5.3 blocks/s; died at 6,317 blocks after 19m53s | recording; cassette grows 108 B/block | `README.md:881-888`; #116 comment 2026-09-04T14:04Z |
| Replay over a warm cassette | 10.9 blocks/s | early, low density | #118 comment 2026-09-04T16:52Z; handoff `:159-167` |
| Live recording past the cache | 5.5 falling to **1.9 blocks/s** at about 7,000 blocks in | density rose from 0.04 to 1.83 groups/block | same |
| Projections drawn from those rates | Full mainnet ancestry 749–1,971 h ("months"); Base adds 49.2M blocks | — | handoff `:159-167` |

Re-interpretation (VERIFIED code, ESTIMATE conclusion):

- **Every one of these numbers predates #147.** At `e7f1dd4`, `process_block` cloned the whole store each block (`git show e7f1dd4:mapping-host/src/store.rs:98-100`, runner `:815`). It also scanned every key for counts each block (`store.rs:135-143`). Both costs grow with live state.
- 1.9 blocks/s at 1.83 groups/block is about 0.29 s per handler group. That is about 40× graph-node's per-handler cost on Aerodrome (section 4.2). With 120 ms per-call pacing and about 3 new calls per group, the serial recorder alone explains roughly 0.66 s/block.
- So the "falling to 1.9" curve measures **recording latency plus O(N) bookkeeping**, not WASM replay speed.
- The handoff's "warm cassette is about 5× faster" (`docs/v3-mainnet-handoff-2026-09-04.md:141-146`) compares 10.9 blocks/s on low-density blocks with 1.9 blocks/s on high-density blocks. It is not like-for-like.
- **No throughput has been measured after #147.** PR #147 itself says "No measured Mainnet speedup … claim is made" (`docs/mapping-host-delta-rollback.md:28-34`).

### 2.3 Not proven, or blocked (as of the last evidence on 2026-09-08)

- **No parity against a deployed production subgraph.** Every comparison is either host versus engine, or engine-loaded candidate versus a fresh Graph Node reference over the same bounded root window (`docs/v3-mainnet-handoff-2026-09-04.md:81-90`). #114 (differential oracle against the deployed subgraph) has had no progress since 2026-09-02. It is blocked on dedicated credentials.
- **The all-Kubernetes pipeline was never executed live.**
  - The renderers, coordinators and RBAC plans were merged as k8s #886/#887/#891/#892/#914–#927.
  - The pilot was gated on access-owner and capacity receipts. The #118 comments on 2026-09-08 report dom153 at 51.855 of 56 CPU after parking idle workers, including the dedicated **Aerodrome** worker (k8s #929).
  - The k8s pipeline is hard-scoped to root `Qme66ZN…` `[12369621,12370674)`, maximum head 12,370,773 (k8s `docs/v3-root-kubernetes-pipeline.md:9-14`; `v3-mainnet-oracle/README.md:27-28`).
- **The engine root loader is hard-coded** (VERIFIED, `engine/src/v3_root_load.rs:20-25`):
  - `ROOT = Qme66ZN…`, `START = 12_369_621`, `MAX_BLOCKS = 1_153`, `MAX_BYTES = 256 MiB`;
  - plus pinned `PROFILE_SHA` and `DESCRIPTOR_SHA`;
  - plus `scripts/v3-milestone.py:25,163`, `scripts/v3-milestone-graphql.py:22,299,334`, and `runtime/v3-root-loader/contract.json:25`.
- **No production-selectable physical profile exists.** Every profile has `production_selectable: false`. A production load needs a profile captured from the live target's `pg_catalog` (engine `docs/block-changes-v1-input.md:490-497`).
- **Full-history scale is unsolved.** In-memory host state, cassette and checkpoint (`docs/data-sources-v2-chunks.md:16-23`; `docs/v3-mapping-host-runtime.md:83-90`). The engine's disk-backed state store, engine #70, is OPEN.
- Five more mainnet segments and five graft transitions, two Base segments, `handleFlash` never executed, and strict eligibility not recaptured (`docs/v3-mainnet-handoff-2026-09-04.md:81-90,150-155`).

### 2.4 The `data_sources$` gap (#117): resolved for bounded root scope, and how

- **The problem.** BlockChanges v1 has no data-source-creation event, so the engine could not reproduce `data_sources$` (engine `docs/block-changes-v1-input.md:445-471`). V3 writes one row per `PoolCreated`.
- **The choice: option 2, an out-of-band companion artifact.** The wire format is unchanged.
- **v1 sidecar** (`docs/data-sources-sidecar-v1.md`). VERIFIED doc, CLAIMED live:
  - JSON `pinax.graph.backfill.data-sources/v1`, from producer `--data-sources-out` (#142) to engine `--data-sources-sidecar` (#81).
  - Sources are taken from the *accepted runtime hosts* through graph-node's `as_stored_dynamic_data_source` (`mapping-host/src/runner.rs:378-413`), not inferred from Pool rows.
  - It binds the descriptor SHA, each block's number, hash and payload SHA, and the whole BCF1 SHA.
  - Limits: at most 10,000 blocks and 16 MiB, fresh contiguous root, onchain only, no checkpoint input, no graft, NULL context only, and **any deterministic indexing error refuses** (`:10-17,29-35`).
  - It was live-proven in the 2026-09-04 milestone: the 18 rows loaded in creation order, and continuation created row 19.
- **v2 sealed resumable chunks** (`docs/data-sources-v2-chunks.md`), producer #144 plus engine #83/#84:
  - Each chunk is at most 10,000 blocks and 16 MiB of metadata.
  - A `.ready` directory holds `blocks.bcf1`, `data-sources.json`, `host-checkpoint.json` (the **full** host checkpoint), `source-identities.bin`, `manifest.json` and `READY.json` (`:40-49`).
  - It uses a chained creation-order hash and a disk-backed sorted identity index.
  - It is proven offline: real 300 versus 200+100. Engine #84 loads with fresh/append atomic transactions in local PG16.
  - **Not** proven in Kubernetes or at scale. The doc itself says it "does not make the full host bounded-memory" (`:16-23`) and "does not establish an end-to-end production path" (`:116-122`).
- **Issue #117 is OPEN.** Its checkboxes 1, 2, 4 and 5 are unticked; only criterion 3 (the bounded scratch load plus GraphQL) is ticked.

---

## 3. Q2: Is the mapping-host generic enough to run Aerodrome's WASM?

### 3.1 Family-neutral pieces (VERIFIED by reading)

- **No Uniswap logic in the host.** `src/lib.rs:5-8`; `README.md:15-18`. Grepping `src/` for `Qme66|mainnet|uniswap` hits only test modules (`checkpoint.rs:837` `#[cfg(test)]`, `evidence.rs:674`, `source_chunk.rs:383`) and doc comments.
- **Manifest resolution** goes through graph-node's own `SubgraphManifest::resolve_from_raw`, `FileLinkResolver` and CID aliases (`README.md:76-88`).
- Bounds come from manifest start blocks and the graft (`runner.rs:283-303`). Network, spec version, features, error policy and PoI version are all read from the manifest (`runner.rs:210-215`).
- **Descriptor generation is generic** (`src/descriptor.rs` `write`). It covers deployment, artifacts, network, `ethereum/<network>` region, policy from `nonFatalErrors`, PoI version from spec, and schema entity types.
- **The wave scheduler, PoI and Fast/Legacy selection** are graph-node code or a documented copy (`poi.rs:17`: spec ≥ 0.0.6 uses Fast).
- **The trigger list mirrors graph-node** (`block.rs:197-218`). VERIFIED against graph-node `ethereum_adapter.rs:1932-1957`, which also emits every log once the filter is non-empty.

### 3.2 Hard-coded or limited pieces, and how each affects Aerodrome

| Constraint | Where | Aerodrome |
|---|---|---|
| Log triggers only; call and block handlers refused | `block.rs:234-246` | OK: all 10 handlers are `eventHandlers` (`aerodrome-slipstream-base/reference/deployment.yaml:24-26,57-76,113-143`) |
| Only `ethereum.call` host fn; `getBalance` and `hasCode` absent | `calls.rs:565-602` | OK: WASM imports VERIFIED with `wasm-objdump`. Factory imports `store.get/set`, `ethereum.call`, `dataSource.create`, `log.log`, bigInt/bigDecimal/typeConversion. NPM and Pool import the same minus `dataSource.create` and `log.log`. **No `store.remove`, no `createWithContext`, no ipfs or ens.** |
| Declared calls (spec ≥ 1.2.0 `calls:`) are not executed: the host never calls graph-node's `DecoderHook::after_decode` (grep found no hits) | `runner.rs:1017-1074` | Safe. VERIFIED in graph-node v0.44 `chain/ethereum/src/data_source.rs:1156-1191`: declared calls only prefetch into the call cache, and reverts are only logged ("Declared calls failed"). Handler-made calls hit the cassette with the same key. Aerodrome declares `positions(tokenId)`, `ticks(tickLower/Upper)` and `feeGrowthGlobal0X128/1X128` (`deployment.yaml:57-75,116-143`). |
| Onchain only; `source_causality_region = 0` | `blockchanges.rs:151`; v1/v2 sidecar refusals | OK |
| Fast PoI | `poi.rs` | Aerodrome is spec 1.2.0, so **Fast**. The host has the code but **no real-data Fast run** exists (all 8 V3 bundles are Legacy, `README.md:319-321`). The engine has graph-node-generated Fast fixtures (33 digests, engine `docs/block-changes-v1-input.md:222-233`). |
| `nonFatalErrors` | `runner.rs:213,1159-1167` | Aerodrome has `nonFatalErrors` (`deployment.yaml:88-90`). The non-fatal path is **untested on real data** (`README.md:1417-1420`). Both sidecars refuse any deterministic error anyway. Live `sgd2` reported no indexing errors on 2026-09-21 (k8s `docs/kan-postgres2-offload-2026-09-21.md:73-77`). |
| Engine: String IDs only, committed removes refused, immutable tables refused across resume | engine `docs/block-changes-v1-input.md:278-283,481-489` | OK: all 20 Aerodrome types are `id: ID!` and none is immutable (VERIFIED `reference/schema.graphql`); no `store.remove` import. |
| Host matching is O(logs × hosts) per wave: each trigger is matched against **all** stage hosts | `runner.rs:1017-1025` | graph-node indexes hosts by address (`core/src/subgraph/context/instance/hosts.rs:17-21,99-108`). Aerodrome has **1,501** `data_sources$` rows (VERIFIED `pg_stat`). Full Base blocks have hundreds to thousands of logs, so roughly 10⁵–10⁶ `match_and_decode` calls per block. Fixable (an address index that keeps insertion order). |
| No Firehose transforms: the full block is streamed | `source.rs:499-513` | Base blocks at 34M+ are large; per-block decode cost on Base is unmeasured. graph-node uses server-side filters. |
| Base blocks never executed by the host | `README.md:1404-1406` ("the Base pair needs Base block fixtures") | Risk: graph-node's `codec.rs` conversion of OP-stack deposit transactions (type 0x7e) inside this harness is unverified. |
| Runtime image bakes in the 8 V3 bundles; only `run` and `verify-bundle` are certified | `docs/v3-mapping-host-runtime.md:24-41` | Aerodrome needs a new committed bundle, which means a new image successor. |
| Packaging helper is Python (`mapping-host/runtime/package.py`, added in #143) despite the Rust-only policy | `docs/v3-mapping-host-runtime.md:10-17`; PR #146 | Policy note only. |

### 3.3 Scale blockers that make the current host unusable for Aerodrome's full history

Live Aerodrome storage, VERIFIED with `pg_stat_user_tables_n_live_tup{schemaname="sgd2"}` on 2026-10-20, Kan `subgraphshard_b`, head 34.73M. These counts are row *versions*, including history:

| Table | Row versions |
|---|---:|
| transaction | 131.8M |
| token | 109.9M |
| token_hour_data | 109.1M |
| token_day_data | 108.9M |
| pool_hour_data | 99.1M |
| pool_day_data | 99.0M |
| pool | 98.9M |
| tick_day_data | 92.0M |
| tick | 91.9M |
| burn | 85.7M |
| swap | 77.2M |
| position_snapshot | 61.7M |
| position | 61.3M |
| mint | 28.8M |
| poi2$ | 17.5M |
| uniswap_day_data | 17.5M |
| factory | 17.5M |
| bundle | 5.9M |
| data_sources$ | **1,501** |
| collect | 0 |
| flash | 0 |
| tick_hour_data | 0 |
| **Total** | **≈ 1.32 B** |

The k8s offload doc records about 1,145 GiB at 30.84M (`docs/kan-postgres2-offload-2026-09-21.md:9`).

The write-once types (Transaction, Swap, Burn, Mint, PositionSnapshot) give **≥ 385M live entities** at 34.7M, and the number is growing. Against that:

| Component | Current design | At Aerodrome scale (ESTIMATE) |
|---|---|---|
| Entity store | In-memory `BTreeMap<EntityKey, Entity>` (`store.rs:56-68`). There is no eviction, so write-once events stay forever. | Hundreds of GB of RAM. |
| Host checkpoint | Full store as JSON Lines, about 1.5 KB per row (`README.md:722-725`). `runner.checkpoint()` first clones the whole store (`runner.rs:465`). | About 0.6 TB per checkpoint. Every v2 chunk embeds one (`docs/data-sources-v2-chunks.md:44-48`), so 39M blocks / 10k is about 3,900 chunks of that size. Infeasible. |
| `eth_call` cassette | One JSON file, loaded whole (`calls.rs:146-169`) and rewritten whole on every save (`calls.rs:274-297`). Recording is serial and blocking, through `ureq` and a global pacer (`calls.rs:300-355,447-467`). | About 37.8 unique RPC calls per block (graph-node metric, section 4.2) × about 770 B per row (V3 cassette: 185,165 B for 240 rows) is about 29 KB/block, so **≈ 0.5 TB for the remaining 18M blocks**. The recording checkpoint's per-row fingerprints (about 130 B per row, `README.md:791-794`) add tens of GB. |
| Engine generic state and checkpoint | `GenericCheckpoint` "carries the complete generic store" (engine `docs/block-changes-v1-input.md:406-421`). Engine #70 (disk-backed state) is OPEN. | Same order as the host store. |

**Conclusion for Q2.** The host's *semantics* layer is generic enough. VERIFIED: no Aerodrome feature falls outside it. Its *state* layer is not generic enough for any deployment the size of Aerodrome. The project's own docs already list this as follow-up work: a disk-backed entity backend, a bounded cache, streaming checkpoint restore, and cassette storage (`docs/data-sources-v2-chunks.md:19-23`).

### 3.4 What Aerodrome would need on the mapping-host path (checklist)

1. **Segment bundle `segments/QmasYjyp…/`**:
   - manifest byte-identical to the IPFS object, schema, 6 ABIs, 3 mapping WASMs, and `bundle.lock.json`;
   - produced with `graph-mapping-host build-bundles --from <dir-of-cid-files>` and checked with `verify-bundle` (`README.md:108-113`);
   - the inputs already exist, content-addressed, in `aerodrome-slipstream-base/reference/` with a provenance lock (`aerodrome-slipstream-base/README.md:18-24`); they only need renaming to CIDs.
2. **Descriptor**: run `build-descriptors`. The result is Fast PoI, `non_fatal`, `ethereum/base`, and the 20 entity types.
3. **Base block fixtures** (single-message `.pb` files, `README.md:115-135`), at least:
   - the root 13,843,704;
   - the first `PoolCreated`, and the first NPM block 13,843,719;
   - a block with a `handleFlash` (about 20 per day now);
   - a dense recent block.
4. **Cassette recorded against a Base archive RPC.**
   - EIP-1898 `blockHash` with `requireCanonical` (`calls.rs:374-396`) must be supported by the Base RPC.
   - At scale this needs a redesign: sharded or binary KV, keyed by block range.
   - A parallel pre-recorder is feasible because the calls are almost entirely predictable from events (see section 5.2).
5. **Disk-backed or evicting entity store, plus a streaming checkpoint.** Without this, nothing beyond toy windows is possible.
6. **Firehose transforms or a pre-filtered block source**, and an address-indexed host matcher.
7. **Engine side:**
   - generalise `v3_root_load` (root, start, max blocks, byte budget, profile and descriptor SHA are constants, `src/v3_root_load.rs:20-25`);
   - an Aerodrome physical profile captured read-only from `sgd2`'s live catalog;
   - a disk-backed generic state (#70).
8. **k8s**: generalise the root pipeline renderer, which is hard-scoped to `Qme66ZN…` (k8s `docs/v3-root-kubernetes-pipeline.md:9-14`).
9. **Repo gates**:
   - strict eligibility evidence across both clusters (`README.md:28-40` of backfills; issue #86 acceptance);
   - resolve the unpublished Aerodrome source revision, or rely on a WASM-derived spec (`aerodrome-slipstream-base/README.md:34-42`).

---

## 4. Q3: Throughput of mapping-host replay versus Graph Node, and parallelism

### 4.1 Effect of #144 and #147

- **#147** (delta rollback plus incremental type counts):
  - removes the two O(live-state) per-block costs, the full-store deep copy and the full key scan (`docs/mapping-host-delta-rollback.md:1-34`; diff `runner.rs:851-931`);
  - for Aerodrome-size state this is mandatory: a per-block deep copy of hundreds of millions of entities would take minutes per block;
  - it does **not** change WASM cost, checkpoint or export cost, or memory (`:56-62`);
  - unmeasured: on real-300, 360.38 s after the change versus 378.75 s and 406.51 s before. These are test-harness times, not a benchmark.
- **#144** (sealed v2 chunks):
  - adds resumable *metadata* and per-chunk sealing;
  - adds per-chunk fsync and verification overhead, plus a **full host checkpoint per chunk**;
  - it is a correctness and resumability feature, not a speed feature, and at Aerodrome scale it makes per-chunk cost worse until the checkpoint becomes incremental.

### 4.2 What graph-node actually spends on Aerodrome

VERIFIED from VictoriaMetrics: Kan pod `graph-node-chain-base-0`, deployment `QmasYjyp…`, 3-day window ending 2026-10-16T12:00Z, steady state before the 10-16..19 pause.

| Metric | Value | Per block |
|---|---:|---:|
| Head advance | 523,116 blocks in 3 days | **2.02 blocks/s** |
| `block_processing_duration` | 257,466 s (99.3% of wall time) | 0.495 s |
| Handler invocations | 25.44M | **48.9** |
| Handler time | 196,141 s (7.71 ms per handler) | 0.377 s (76%) |
| host fn `store_get` | 350.4M calls, 68,524 s (0.196 ms each) | 674 calls; 0.132 s (27%) |
| host fn `ethereum_call` | 34.1M calls, 38,322 s | 65.5 calls; 0.074 s (15%) |
| RPC-level `eth_call_execution_time` | 19.65M calls, 61,818 s | 37.8 unique calls |
| `transact_block_operations` | 8,199 s | 0.016 s (3%) |
| **Handler time excluding store_get and ethereum_call** (WASM plus bigDecimal host fns) | 89,295 s (3.51 ms per handler) | **0.172 s (35%)** |

Other windows (VERIFIED):

| Window | Blocks/s | Handlers/block | Non-I/O compute |
|---|---:|---:|---|
| Ending 2026-09-26 (head about 31.0–31.4M) | 1.36 | 36.8 | 7.73 ms per handler, 0.285 s/block. CPU contention on the shared Base worker is likely. |
| Last 24 h (after the 10-16..19 failed/paused period) | 0.71 | — | Last 12 h about 1.16 blocks/s |

Handler mix over the last 24 h:

| Handler | Calls |
|---|---:|
| `handleTransfer` | 763k |
| `handleSwap` | 754k |
| `handleBurn` | 679k |
| `handleCollect` | 669k |
| `handleMint` | 224k |
| `handleIncreaseLiquidity` | 224k |
| `handleDecreaseLiquidity` | 222k |
| `handleFlash` | 20 |
| `handlePoolCreated` | 16 |
| `handleInitialize` | 16 |

The user's "about 2 blocks/s" is right for the steady state. Handler density is **≈ 27× the V3 mainnet root density** that the host was ever measured at (1.83 groups per block).

### 4.3 Mapping-host on Aerodrome: a ceiling, not a measurement (ESTIMATE)

The mapping-host executes the same WASM with the same wasmtime runtime. It also re-instantiates the module per trigger, exactly as graph-node does (`README.md:687-690`), and uses the same graph-node BigDecimal host fns. So the 0.172–0.285 s/block of non-I/O handler time **carries over unchanged**. What the host removes or adds:

- **Removed:**
  - `store.get` from Postgres (0.132 s/block); it becomes an in-memory map, which only works if state fits in RAM, see §3.3;
  - `eth_call` (0.074 s/block); only with a warm cassette;
  - transact (0.016 s/block).
- **Added:**
  - per-handler `BlockState`, `as_modifications` and recorder drain;
  - op projection with `convert_entity` (`runner.rs:1049-1100`);
  - per-frame canonical validate, encode and decode round trip (`README.md:395-398`);
  - O(logs × 1,503 hosts) matching (`runner.rs:1017-1025`);
  - full-block Firehose decode with no transforms (`source.rs:499-513`).

  On early, nearly empty V3 mainnet blocks the per-block fixed cost was already about 0.09–0.24 s (10.9 and 4.2 blocks/s at 0.16 groups per block).
- **Ceiling with zero added overhead:** 1/0.172 ≈ 5.8 blocks/s (Oct window) to 1/0.285 ≈ 3.5 blocks/s (Sept window).
- **Realistic, with fixed overhead added:** about 2–4 blocks/s, roughly **1–2× graph-node**, single-threaded.
- **Full replay from root 13,843,704.**
  - About 250M handler invocations up to 34.7M (proxy: the Swap + Burn + Mint + PositionSnapshot entity counts).
  - Plus about 18.1M × 49 ≈ 890M to today's head.
  - That is ≈ 1.1B handler invocations × 3.5–7.7 ms ≈ **45–100 days of pure WASM compute**, before any host overhead.
- **Graph-node from its current head:** 18.14M blocks behind. At 174.5k/day gross minus 43.2k/day chain growth, about 131k/day net, so an ETA of about **138 days**, if density does not keep rising.

So for Aerodrome:

- Full-history replay with the mapping-host is **not materially faster** than letting graph-node finish.
- Even a seeded host, started from a `sgd2` dump at about 34.7M, would at best halve the remaining time. It would first require loading about 400M live entities into the host, which is impossible today.

### 4.4 Can the work be split by block range?

**No, not for execution.** Every handler reads state that earlier blocks wrote: `Bundle.ethPriceUSD`, `Token.derivedETH` through whitelisted pools, `Pool` liquidity and ticks, `Position`. A range can only start from the exact state at its first block, and only a sequential replay, or an existing Graph Node DB, produces that.

The only parallelism available:

- **Pipeline parallelism.** Block fetch, decode and filter on one thread; WASM on another; frame encode and IO on a third.
- **Parallel `eth_call` pre-recording** (see §5.2).
- **Range-seeded replay only where a state seed exists.** For Aerodrome that is `sgd2` history at any block ≤ 34.7M, which is exactly the range that needs no backfill. The useful exception is *verification*: pick a sample of blocks, seed the host from `sgd2` at block B−1, and compare the host's output for block B against `sgd2` (an oracle use; it would need a Postgres-to-host-checkpoint seeder).

---

## 5. Q4: Mapping-host versus a Substreams path (honest assessment)

### 5.1 Could the deployed AssemblyScript WASM run inside a Substreams module? **No (not viable).**

- **State model mismatch.** The mapping is a sequential state machine with read-your-writes over a mutable entity store (`store.get` after earlier `store.set`, across blocks).
  - Substreams `map` modules are stateless per block.
  - `store` modules cannot read their own values while writing; downstream modules read them.
  - Store modules are computed per segment in parallel and merged under fixed merge policies (set, add, min/max…).
  - A Graph mapping's store cannot be expressed that way without rewriting its logic. That rewrite is the native port in §5.3, not "running the WASM".
- **Even if forced** (one linear module carrying all state), the result would be a single serial stream with none of Substreams' range parallelism. It would also need, inside a wasm32 module:
  - an AssemblyScript WASM interpreter;
  - re-implementations of graph-node's host functions (exact `BigDecimal`, `store` semantics, PoI);
  - all of this within tier2 memory and output limits.

  WASM-in-WASM interpretation costs 10–50× native wasmtime. It is strictly worse than the mapping-host.
- **Deployment identity.** Graph Node "substreams-powered subgraphs" change the deployment hash, so they cannot serve `QmasYjyp…` faithfully.

### 5.2 Could Substreams pre-extract triggers and the cassette in parallel to feed the mapping-host? **Yes, but it does not move the bottleneck.**

Feasible, with VERIFIED supporting facts:

- **Trigger and block slimming.**
  - A map module could emit a reduced `sf.ethereum.type.v2.Block` that keeps the header and only the transactions touching the factory (`0x5e7bb104…`), the NPM (`0x82792268…`) and pool addresses, with original `block_index` and log indices preserved.
  - Pool addresses come from `PoolCreated`; the dynamic-source set is small (1,501).
  - The output caches in tier2, which is the natural "noop warm-up".
  - Caveats:
    - `source_trigger_order` in frames changes with filtering. It is a frame field, not Graph state.
    - `event.transaction` and `event.block` fields must survive the reduction intact.
    - Firehose `transforms` (graph-node's own approach) would give most of the bandwidth win without Substreams.
- **Cassette pre-recording.**
  - Aerodrome's per-event calls are declared in the manifest and derive from event params alone: NPM `positions(tokenId)`, Pool `ticks(tickLower/Upper)`, `feeGrowthGlobal0X128/1X128` (`deployment.yaml:57-75,116-143`).
  - The remaining calls are derivable too: ERC20 `symbol/name/decimals/totalSupply` from `PoolCreated` token0/token1, and Factory `getPool(address,address,int24)` from the `positions()` output. Compare the V3 cassette's `rows_by_call` in the parity evidence JSON.
  - Pinax packages already do in-module `eth_call` through `substreams_ethereum::rpc::RpcBatch` (VERIFIED in `substreams-evm/erc20/balances/src/calls.rs`). Whether Base tier2 has an RPC configured is **unverified**.
  - The alternative is a parallel Rust job over a Substreams-extracted trigger list against a Base archive RPC.
  - The output must be written in the host's key shape: `(blockHash, address, calldata)` with graph-node's ABI encoding.

Why it does not move the bottleneck:

- On Aerodrome, `eth_call` is about 15% of graph-node's block time and RPC-level calls are about 37.8 per block.
- The serial WASM share (35% of graph-node time; 100% of a warm-cassette, in-memory host) is untouched.
- Pre-extraction makes the host's *recording* run as fast as its *replay* run. It does not make replay faster than §4.3's ceiling of about 2–4 blocks/s. It also does not solve the §3.3 state-size blockers.

### 5.3 What actually parallelises: a native Substreams port feeding the engine

This is the path the user is asking for and the one the engine's production lane already runs for V4. The mechanics:

- Rust store and map modules reproduce the mapping's entity semantics.
- Tier2 computes store segments in parallel; a "noop" run warms the caches.
- The engine reduces and writes Graph Node-native rows.

Known prior art and constraints from this lane:

- **The team abandoned hand-porting V3 on 2026-09-03 because semantics drifted** (#116 comment 2026-09-03T22:00Z). The frozen V3 Substreams port's `graph_out`:
  - emitted `TickHourData`, which no deployed V3 module writes;
  - coalesced writes per entity per block (`README.md:1368-1387`; `docs/v3-mainnet-handoff-2026-09-04.md:157-179` on per-segment Collect quirks).

  Aerodrome's mapping has its own quirks: `Token.version`, `addMissingWhitelistedPools`, Flash updates fee growth without a `Flash` row, and Collect profiles (`aerodrome-slipstream-base/README.md:61-66`). An Aerodrome port **must** be differentially validated.
- **The oracle already exists for 60% of the range.** `sgd2` holds full Graph Node history for blocks 13,843,704 → about 34.73M. Block-pinned SQL or GraphQL comparisons can certify a port over that whole span without building anything new.
- **Contract choice.**
  - BlockChanges v1 (exact per-save order and pre-merge `written_fields`) is required if PoI parity is a goal. The engine's framed mode folds PoI from frames (engine `docs/block-changes-v1-input.md:143-189`).
  - A port that emits only coalesced `EntityChanges` cannot reproduce graph-node's PoI (`README.md:1378`; engine `:292-297`).
  - The V4 lane made its own trade-off here; the V4-survey agent should confirm it.
- **The seed option (V4 recipe).** Engine `docs/production-backfill.md:1-80`: `graphman dump` of a stopped, healthy deployment, capture its active mutable state, then append contiguous Substreams segments. Applied to `sgd2` at about 34.7M, this cuts the work to about 18.1M blocks.
  - Caveat: every Aerodrome entity type is mutable, so "active mutable state" includes the write-once events.
  - Hundreds of millions of rows would need capturing unless the port or reducer proves those types are never re-saved.

### 5.4 Where the mapping-host is still valuable for Aerodrome

- **As an executable oracle and test generator for small windows from the Aerodrome root** (block 13,843,704 onward, where empty-state replay is legal):
  - exact BlockChanges frames, Fast PoI, and dynamic-source order;
  - it exercises the non-fatal and Fast-PoI code paths that V3 never reached.
- **For contracts and tooling**: descriptors, the BCF1 framing, the v1/v2 companion artifacts, and the engine's framed input, generic state and profile-driven COPY. All are family-neutral and directly reusable by a Substreams port that emits BlockChanges.

---

## 6. Live Aerodrome context relevant to the design (VERIFIED, VictoriaMetrics, 2026-10-20)

- `deployment_head` is 34,726,501 on `graph-node-chain-base-0-77c65b59d4-kc8dv`, shard `subgraphshard_b` (`sgd2`). The Base chain head is 52,867,632, so 18.14M blocks behind. `deployment_synced` = 0.
- `deployment_status` codes, VERIFIED in graph-node `graph/src/components/metrics/subgraph.rs:178-181`: 1 starting, 2 running, 3 stopped, 4 failed.
  - The source worker showed **4 (failed)** across about 10-16 to 10-19, which is the observed pause. It is back to 2 now.
  - The dedicated copy destination `aerodrome_a/sgd5311` on pod `graph-node-aerodrome-0-*` has reported **4 (failed) continuously since about 2026-09-24**.
  - The copy was started 2026-09-21 at checkpoint 30,843,266 (k8s `docs/kan-postgres2-offload-2026-09-21.md:103-113`). `sgd5311` row counts are about 64% of `sgd2`'s, for example transaction 84.7M versus 131.8M.
  - This matters to anyone choosing "which indexer to sync on".
- On 2026-09-08 the dedicated Aerodrome worker was parked 1→0 to free dom153 CPU, along with the UniV2 Base and Forsage workers (k8s #929; backfills #118 comment 2026-09-08T10:54Z).
- Eligibility snapshot (#86): Kan `sgd2` was at 27.55M on 2026-08-31 with a diagnostic ETA of about 149 days. Now about 138 days at the steady rate. That would pass the >28-day rule, but the formal two-cluster 24h/72h capture has not been recorded.

---

## 7. Open questions to verify before design commits

1. Does graph-node v0.44's Firehose codec conversion handle every Base transaction type, including OP deposit 0x7e, inside the host? Run 3–5 Base blocks through `graph-mapping-host run --blocks`.
2. Does the Base archive RPC support EIP-1898 `{blockHash, requireCanonical}` `eth_call` at 13.8M+?
3. Does Pinax's Base tier2 support `RpcBatch` (an `eth_call` intrinsic) for a cassette-prefetch module?
4. What is the real Firehose block size and decode time at Base 35M–52M, with and without transforms?
5. Does any Aerodrome mapping read Transaction, Swap, Mint, Burn or PositionSnapshot in a *later* block than the one that wrote it? This decides whether a write-once eviction policy (host) or an "exclude from active state" policy (engine seed) is semantics-preserving. It needs a WASM-level proof, as was done for V3's all-handlers certificates.
6. A post-#147 host throughput measurement on any dense range. None exists.
7. Is the failed `sgd5311` copy salvageable, and which copy is the intended serving or seed source?

---

## 8. Citation index (primary sources read)

### substreams-backfills (`/Users/denis/Github/substreams-backfills`, main `bbe3783`)

- `mapping-host/README.md`:

  | Lines | Topic |
  |---|---|
  | 11-23 | family-neutral |
  | 90-106 | segments |
  | 115-142 | block input |
  | 144-184 | recorder |
  | 220-226 | delta rollback |
  | 228-305 | cassette |
  | 319-325 | PoI version |
  | 395-398 | frame validation |
  | 517-604 | live mode |
  | 643-803 | checkpoints, cassette pin |
  | 876-892 | 20 h survival |
  | 1136-1146 | scale |
  | 1245-1313 | parity window |
  | 1368-1387 | Substreams port cross-ref |
  | 1402-1455 | open items and evidence boundary |

- `mapping-host/src/runner.rs`:

  | Lines | Topic |
  |---|---|
  | 1-37 | model |
  | 193-345 | load |
  | 378-413 | stored dynamic sources |
  | 459-532 | checkpoint (full snapshot at 465) |
  | 734-763 | host per module |
  | 822-988 | `process_block` |
  | 999-1170 | `run_group`, linear host match at 1017-1025 |

- `mapping-host/src/calls.rs`:

  | Lines | Topic |
  |---|---|
  | 1-40 | design |
  | 146-169 | whole-file load |
  | 274-297 | whole-file save |
  | 300-355 | serial record |
  | 374-430 | EIP-1898 and revert classification |
  | 565-602 | `ethereum.call` only |

- `mapping-host/src/block.rs:197-259`: every-log triggers; call and block handler refusal.
- `mapping-host/src/source.rs:457-530`: no transforms; `final_blocks_only`.
- `mapping-host/src/store.rs:56-68`: in-memory store.
- `mapping-host/src/descriptor.rs`: generic descriptor writer.
- Pre-#147 per-block O(N) bookkeeping: `git show e7f1dd4:mapping-host/src/store.rs` lines 98-100 and 135-143; `git show e7f1dd4:mapping-host/src/runner.rs` lines 815 and 923.
- `mapping-host/evidence/parity-window-12369621-12370674.json` (`totals`, `cassette.rows_by_call`).
- Docs:
  - `docs/v3-mapping-host-runtime.md:1-90`
  - `docs/data-sources-sidecar-v1.md:1-59`
  - `docs/data-sources-v2-chunks.md:1-152`
  - `docs/mapping-host-delta-rollback.md:1-67`
  - `docs/v3-mainnet-handoff-2026-09-04.md:66-111,136-191`
  - `docs/uniswap-v3-execution-model.md:28-41`
  - `crates/README.md`
- `aerodrome-slipstream-base/README.md:8-82`; `aerodrome-slipstream-base/reference/deployment.yaml` (spec 1.2.0, API 0.0.7, features, declared calls); `reference/schema.graphql` (20 types, all `ID!`, none immutable); `reference/mappings/*.wasm` (imports via `wasm-objdump -j Import`).
- GitHub (read with `gh`):
  - PRs #141–#144, #146, #147; #145 does not exist.
  - Issues #117 (body and 4 latest comments), #118 (30 comments, latest 2026-09-08), #116, #114, #10, #86, #88.

### Engine (read-only snapshot at `scratchpad/ro/engine`, main `5c98b57`)

- `src/v3_root_load.rs:1-60` (hard-coded root and limits).
- `docs/block-changes-v1-input.md:1-523`.
- `docs/production-backfill.md:1-80`.
- PRs #80–#84 bodies; issues #66 and #70.

### k8s-subgraphs (read-only snapshot at `scratchpad/ro/k8s-subgraphs`)

- `subgraphs-operations/backfill/v3-root-pipeline/README.md`, `v3-pipeline-fresh-target/README.md`, `v3-mainnet-oracle/README.md`.
- `.agents/skills/verify-disposable-v3-root/SKILL.md`.
- `docs/v3-root-kubernetes-pipeline.md:1-45`.
- `docs/v3-mainnet-root-milestone-2026-09-04.md:6-41,126-144`.
- `docs/kan-postgres2-offload-2026-09-21.md:7-113`.

### graph-node v0.44 (`~/.cargo/git/db/graph-node-40979021f9daae1a`, rev `77823b5a`, read with `git show` and `git grep`)

- `chain/ethereum/src/data_source.rs:690-702` (`match_and_decode` address and start-block gate) and `:960-1191` (`DecoderHook`: declared calls only warm the cache; reverts are logged).
- `chain/ethereum/src/ethereum_adapter.rs:1932-1957` (`parse_log_triggers`).
- `core/src/subgraph/context/instance/hosts.rs:17-21,99-108` (address-indexed hosts).
- `graph/src/components/metrics/subgraph.rs:178-181` (status codes).

### VictoriaMetrics (datasource `P4169E866C3094E38`)

- Queries:
  - `deployment_head`, `deployment_status`, `deployment_synced`;
  - `deployment_{blocks_processed_count, block_processing_duration, block_trigger_count, handler_execution_time, host_fn_execution_time, eth_call_execution_time, transact_block_operations_duration}`, for deployment `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`;
  - `pg_stat_user_tables_n_live_tup{schemaname=~"sgd2|sgd5311"}`.
- Windows: steady state 2026-10-13T12Z → 2026-10-16T12Z; 2026-09-23 → 2026-09-26; last 24 h.
