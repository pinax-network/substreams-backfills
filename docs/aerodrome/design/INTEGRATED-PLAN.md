# Integrated interface plan: Aerodrome Slipstream Base backfill (Route A + C)

Date: 2026-10-20. Interface and consistency critique of the five design docs, and the single ordered plan.
Scope: `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` (Base). User decisions 2026-10-20 apply: route A
(Substreams extractor + native Rust reducer emitting canonical `BlockChanges`; engine stays family-neutral with
generic scaling) and C (dedicated fast Graph Node worker) in parallel; extractor source in substreams-backfills;
call answers from storage changes plus ERC20 `eth_call` only; mapping-host is the exact oracle.

This pass was read-only. No repository file was changed and nothing was committed, pushed or commented. The only
file written is this document.

Inputs (all read in full): `design/extractor.md` (EXT), `design/reducer.md` (RED), `design/engine-scaling.md` (ENGD),
`design/k8s-backfill.md` (K8SD), `design/option-c.md` (OPTC), `survey/SYNTHESIS.md` (SYN), engine audit
`tasks/wathbfgwg.output` `.result.kept[]`, Phase 0 state `phase0/*.json`.

Evidence labels: **VERIFIED** (I read the code/data in this pass; §5 lists the commands), **DOC-CLAIM** (stated by a
design doc, not re-checked), **ESTIMATE**, **OPEN**.

Short paths: `SB/` = `/Users/denis/Github/substreams-backfills` (`bbe3783`); `ENG/` = `scratchpad/ro/engine`
(`5c98b57`); `K8S/` = `scratchpad/ro/k8s-subgraphs` (`4da0b37`); `GN:` = graph-node `77823b5a`; worktrees:
`WT-NOOP` = `~/Github/.worktrees/k8s-subgraphs-substreams-noop`, `WT-SC` = `~/Github/.worktrees/engine-fix-stream-completeness`,
`WT-DEC` = `~/Github/.worktrees/substreams-backfills-feat-bigdecimal-negative-precision`,
`WT-ORA` = `~/Github/.worktrees/substreams-backfills-feat-aerodrome-oracle`.

---

## 0. Summary

**Blocking mismatches (would break the first real run or land wrong/refused data):**

1. **`data_sources$` transport.** RED §12 emits v2 companion chunks and asks for a "seeded genesis"; ENGD §4 puts
   creations **in-band** as `BlockChanges.created_data_sources = 9` under descriptor v2. Resolved: in-band.
2. **Seed format.** RED §13.5 defines its own `pinax.graph-node.seed/v1` directory and an xtask capture; ENGD §3 defines
   `BCGSNAP1` in backfill-common, captured by `generic-seed-capture`, consumed by both. Resolved: BCGSNAP1 only.
3. **Error disposition.** RED defaults to FailClosed (abort ⇒ no frame N); ENGD §5.7 stop-before needs frame N
   *with* `DeterministicError` to seal N−1 and hand over. Resolved: production reducer runs `emit-non-fatal`; engine
   `stop-before`; new exit class 6 (handover).
4. **Graft fields on the Graphman copy.** VERIFIED: `GN:store/postgres/src/subgraph_store.rs` `copy_deployment` writes
   `graft_base = src.deployment` (QmasYjyp itself) and `graft_block = copy point`, and they persist
   (`GN:store/postgres/src/deployment.rs:232-282`). K8SD §8.2 requires "graft NULL"; ENGD §3.2/§5.3 refuse
   "graft ≠ profile". Both would refuse the Option C seed. Resolved: a pinned *self-copy* graft tuple.
5. **Driver ↔ workflow contract.** ENGD §5.6 `block-changes-backfill run --family-pin …` with exit codes 0/3/64/75
   versus K8SD §4.3 `pinax.backfill.generic-driver/v1` with 0/2/3/4/5/75. Exit code **3 collides** (handover vs
   cache-miss). Resolved: one entrypoint manifest, one exit-code table.
6. **Producer completion receipt (Phase 0, WT-SC).** state-replay now honours `BACKFILL_PRODUCER_RECEIPT`, but the
   receipt is the literal `producer_exit_status=0\n` (VERIFIED `WT-SC src/bin/state-replay.rs:3280-3283`), not bound
   to the run, and the generic pipe has *two* upstream processes. Resolved: receipt v2, written by the driver after
   both exit 0, mandatory with `--state-store`.

**Major mismatches:** extractor module name (`map_events` in RED/ENGD vs `map_extractor_block` in EXT); oracle
windows W2/W3 in EXT §11.4 cannot use the mapping-host cassette (root-only oracle); checkpoint cadence and rewind
(reducer 100k/no rewind vs engine 50k segments with undo deltas); descriptor v1 vs v2; BigDecimal domain (Phase 0
accepts only Graph Node fixed points, so once-normalized raw negatives on 0-decimal-token swaps still refuse);
noop-evidence names, schema and coverage end (`cache_last_block`, not `stop−1`); SPKG on an INTERNAL repo vs
credential-less noop download; physical profile inside the producer image (circular pin); exporter journal file
name; capability names (`subgraph_error_writer` will not exist); segment-preflight probe would see the loader's own
advisory locks.

**Slices (ids, §3):** Wave 0 `P0-1…P0-5` (in flight) → Wave 1 contracts `S-C1 S-C2 S-C3` → extractor `S-X1…S-X7` ‖
reducer `S-R1…S-R12` ‖ engine `E-VEND1 E0 E1 E2 E4a E3 E4b E5 E6 E7 E8 E9 E-REL` ‖ k8s `K2-1…K2-6`, Option C
`C-1…C-9`, `K-CAT`.

**First real E2E (milestone M2):** live Substreams extractor (non-final SPKG from `S-X4`) over the root window
`[13,843,704, 13,919,663)` → `substreams-native --output-format clock-v1 --include-empty-frames --final-blocks-only`
→ reducer (`S-R6`) → `diff-frames` (`S-R7a`) against the mapping-host oracle frames for the same window (P0-4
evidence, regenerated with field 9 by `S-C2`), plus cassette coverage of the extractor answers. It needs `S-C1–C3`,
`S-X1–X4`, `S-R1–R6`, `S-R7a`. No engine change, no k8s change, no infra approval (only a Substreams API token and
tier2 budget for ~76k root blocks). ESTIMATE: ≈ week 6–7 with one implementer per track (reducer R1–R6 is the long
pole, 24–30 engineer-days per RED §15). M3 (same window folded by the engine, Fast PoI equal) follows after
`E-VEND1 → E1 → E2 → E4a`.

---

## 1. Mismatches and resolutions

Severity: **BLOCKER** (wrong data, or the first real run cannot happen), **MAJOR** (fail-closed refusal or rework),
**MINOR** (naming, docs, small gaps).

### 1.1 Extractor output proto → reducer input

| ID | Sev | Producer says / consumer says | Verified fact | Resolution | Docs to change |
|---|---|---|---|---|---|
| X-1 | MAJOR | RED §2, §11.7, §13.4 and ENGD §4.3 pin extractor module `map_events`; EXT §5.2/§13 freezes `map_extractor_block` | EXT is the producer and owns the manifest | `map_extractor_block` everywhere (descriptor `producer_contract.extractor.module`, reducer checkpoint, profile `producer.module`, family contract, noop `module`) | RED §2/§11.7/§13.4; ENGD §4.3; K8SD §9.3 example |
| X-2 | MAJOR | RED §3.2: reducer keeps a sha256-pinned *copy* of the proto and runs prost-build; EXT §6.1: one proto in `aerodrome-extractor-pb`, reducer path-depends | Root workspace pins `prost = "0.13"` (→0.13.5) and lists explicit members (VERIFIED `SB/Cargo.toml:1-22`); EXT crates pin `prost =0.13.5` | One proto: `aerodrome-slipstream-base/substreams/proto/`. Reducer path-depends on `aerodrome-extractor-pb`; root `exclude += "aerodrome-slipstream-base/substreams"`; no reducer build.rs. CI in both workspaces runs `cargo check -p aerodrome-slipstream-reducer` | RED §3.2; EXT §3.2 (turn ASSUMED into the S-X1 gate) |
| X-3 | MAJOR | EXT §10.4: "audit.anomalies empty, otherwise the block is refused" by the reducer; RED §4.1 proto stops at tag 10 and §4.3 never checks anomalies | prost drops unknown tags, so a reducer compiled from RED §4.1 cannot see tags 11–13 | Reducer validation adds: `contract == "pinax.aerodrome.slipstream.base.extractor/v1"`, `firehose_block_version ∈ {4,5}`, `audit.anomalies` empty ⇒ else `ReducerError::ExtractorAnomaly` (exit 4) | RED §4.3 |
| X-4 | MINOR | EXT §8.2: "put `graph_node_gas_price` in core; the reducer calls it", but its signature takes `eth::TransactionTrace` and `core` has no substreams dependency (EXT §3.1); RED §5.6 has its own `graph_gas_price(&Transaction)` with checked u256→u128. EXT cites alloy 2.0.5, RED alloy 2.4.1 | `SB/mapping-host/Cargo.lock` pins alloy-eips/network/consensus **2.4.1**, alloy-dyn-abi **1.7.2** (VERIFIED) | `core::gas::graph_node_gas_price(tx_type: u32, gas_price: Option<&[u8]>, max_fee: Option<&[u8]>, max_prio: Option<&[u8]>, base_fee: Option<u64>) -> Result<u128, GasOverflow>` (checked). Extractor and reducer both call it. F-TX fixtures are judged against the mapping-host (alloy 2.4.1) | EXT §8.2/§9; RED §5.6 |
| X-5 | MINOR | EXT §9 `build_candidates(&eth::Block)` in a substreams-free `core`; RED §4.4 reference extractor needs `sf.ethereum.type.v2` bindings with no stated source | — | `aerodrome-extractor-pb` also generates `sf.ethereum.type.v2` (prost 0.13.5). `core` and the reducer's `reference-extractor` feature both use it | EXT §3.1; RED §3.2 |
| X-6 | MINOR | EXT §8.1 registers *every* PoolCreated as a host (superset); RED §4.2 FailClosed raises `UnknownPoolHost` for a pool candidate outside its host set | Graph Node simply does not match a non-host log. The hot-fix pool `0x8fe8…` has no code on Base (EXT P5, RED P5), so this is inert today | Reducer: a pool candidate whose pool is in the extractor registry but not a host is "not matched" only when explained by a reviewed rule (hot-fix list, or an aborted PoolCreated under emit-non-fatal); otherwise refuse | RED §4.2 |
| X-7 | MAJOR | EXT §11.4 runs gate G4 (cassette differential, the freeze gate) on W2 `[34,719,300, 34,720,300)` and W3 `[52,799,500, 52,800,500)` using the mapping-host in `--record` mode | The mapping-host needs full prior state from the root and has no seeder (SYN C9, RED §14.2). Measured ≈31 ms CPU per handler group, ≈0.5 blocks/s at head density (P0-4 summary). At 34.7M its handlers would abort on `Bundle.load("1")!` and record no calls | **G4 (cassette)** on root windows only: R0 `[13,843,704, 13,899,663)` and R1 `[13,899,663, 13,919,663)` (the P0-4 evidence windows), extendable while root replay is affordable. **G4′** for W2/W3: 100 % of emitted storage-derived answers equal archive `eth_call` at the block hash (not a 200-sample), and coverage (zero `MissingCallAnswer`) proven by reducer runs seeded from engine oracle snapshots (M4, needs D8). RED W3 edge cases beyond replay reach move to G3 | EXT §11.4, §12 (G4 → G4/G4′); RED §14.2 W3 |
| X-8 | MINOR | EXT: `substreams/fixtures/blocks.lock.json`, tag `block-fixtures-base-v1`; P0-4 proposes `aerodrome-base-block-fixtures-v1` at `aerodrome-slipstream-base/fixtures/blocks/base/` with real sha256s | — | One family-level lock `aerodrome-slipstream-base/fixtures/blocks.lock.json`, tag `aerodrome-base-block-fixtures-v1`, shared by extractor, reducer and mapping-host | EXT §3.1, §11.2; RED §14.5 |
| X-9 | MINOR | RED `--extractor-lock` (4 fields) vs EXT release lock `packages/…-vX.Y.Z.json` (all module hashes, params sha, toolchain…) | — | Reducer reads the EXT release lock file itself and pins its sha256 in the checkpoint | RED §3.3 |
| X-10 | — | Ordering keys: RED/EXT `source_trigger_order` = rank among **all** receipt logs = `Log.block_index`; `handler_order` = 0 | VERIFIED consistent with the oracle: `SB/mapping-host/src/block.rs:199-222` builds a trigger for *every* receipt log, and `runner.rs:887` enumerates them per stage (rank restarts each stage, so it regresses in wave 1) | No change. Make it normative text in `SB/docs/block-changes-v1.md` because EXT relies on `source_trigger_order == block_index` | common docs |

### 1.2 Reducer output → engine input (frames, `data_sources$`, seeds, checkpoints)

| ID | Sev | Producer says / consumer says | Verified fact | Resolution | Docs to change |
|---|---|---|---|---|---|
| R-1 | BLOCKER | RED §12: creations in `pinax.graph.backfill.data-sources/v2` companion chunks (10k blocks, sealed six-file chunk with `host-checkpoint.json` pointer), plus a seeded-genesis extension; ENGD §4: in-band field 9 under descriptor v2 `data_sources.transport = in_band_v1`, companions stay root-only | v2 chunks are capped at 10k blocks, list every block, and need `parent: None ⇒ from == root` (ENGD B7/B8; RED §12 table) | **In-band.** Reducer emits per block `CreatedDataSource{ordinal (dense from 0), manifest_idx 2, template "Pool", handler_group_order, param = 20-byte pool}` for each committed `dataSource.create`, in creation order; none for an aborted handler or the hot-fix pool. Drop `--sources-out` and the seeded-genesis request. The mapping-host gains `--data-sources-in-band` (S-C2) so G2 stays byte-for-byte | RED §2, §3.3, §12, slice R6 |
| R-2 | BLOCKER | RED §13.5: `pinax.graph-node.seed/v1` directory of `.rows` files + `cargo xtask aerodrome seed-capture`; ENGD §2.6/§3: `BCGSNAP1` in `CMN/src/state_snapshot.rs`, written by `generic-seed-capture landing|oracle|catalog`, read by both | Two producers of the same state would drift; ENGD also round-trip-proves every row against Postgres (§3.3) | **BCGSNAP1 only.** Reducer `seed --from seed.bcgsnap` (backfill-common reader); delete the reducer seed format and xtask capture. Keep RED's lazy `PgOracleBackend` as a test-only G3 tool. Note: ENGD Q5 keeps each period table's *max* period, RED selected S's own period; the reducer accepts ENGD's (superset, harmless: Base timestamps increase) | RED §0.8, §3.3, §13.5; K8SD §8.4 (`producer_export` = the snapshot) |
| R-3 | MAJOR | RED §13: checkpoint every 100,000 blocks, redb commit every 1,000 blocks, no rewind; ENGD §2.5–2.7: one write txn per segment, BCGDELT1 undo/redo, lineage, `rewind`; family pin `segment.max_blocks 50000`; K8SD §4.1: per-segment producer-state chaining | A reducer that commits mid-segment cannot be put back to a segment boundary after a crash; a reducer ahead of the engine (look-ahead) cannot follow an engine `rewind` | Reducer checkpoints exactly at driver segment boundaries (`reduce --from s --to e`). One redb write txn per segment (crash ⇒ previous boundary). Per-segment undo file and reducer lineage `Lr_k = sha256("pinax.reducer-lineage/v1\0" ‖ Lr_{k−1} ‖ sha256(undo_k))`; `rewind --to <block,hash>`. Checkpoint manifest binds `{boundary, reducer_lineage, engine_lineage_before, descriptor_sha256, extractor lock sha}`. Engine spool manifest v3 gains `producer_checkpoint {format, block, hash, lineage, manifest_sha256}`. Reducer refuses to start unless its boundary equals `--expected-head-block/hash`. Full-table `state_sha256` only every N segments and at certification | RED §3.3, §13.2–13.4; ENGD §2.6, §5.8; K8SD §4.1, §12.1 |
| R-4 | BLOCKER | RED §0.6/§11.6: default FailClosed; EmitNonFatal "for completeness", "production must stay FailClosed"; ENGD §5.7/§12.6: producer must emit frame N with `DeterministicError`; engine `stop-before` seals N−1, writes `handover.json`, exit 3 | Under FailClosed the reducer emits no frame N, the clock-v1 range is incomplete, state-replay refuses the whole segment: no seal of N−1 and no handover receipt | Production reducer runs `--error-mode emit-non-fatal`: frame N exact (aborted handler's sets `DISCARDED`, `DeterministicError{redacted_events}` closing the group, its creations dropped, other groups `COMMITTED`), then continues to `--to` (Graph Node non-fatal semantics) and exits 0. Engine `--on-deterministic-error stop-before`, driver exit **6**. Contract/infra faults (`MissingCallAnswer`, extractor anomaly, contract mismatch, `StateCorrupt`, input truncation) stay fatal (exit 4/75). FailClosed remains the default for oracle and test runs | RED §0.6, §11.6; ENGD §5.6/§5.7 (exit code); K8SD §15.1 |
| R-5 | MAJOR | RED §11.7: descriptor v1 with a `producer` *object*, `graph_node.version "v0.44.0"`; ENGD §4.3: descriptor v2 (`deployment, spec_version, start_block, graph_node{version, commit, poi_version}, storage_profile, data_sources, entity_retention, producer_contract{kind, reducer{repository, commit}, extractor{…}}`) | `SB/common/src/block_changes.rs:56-61` accepts only `descriptor_version == 1` (VERIFIED). The mapping-host Aerodrome descriptor uses `graph_node.version "0.44.0"` and `producer` as a **string** (VERIFIED `WT-ORA mapping-host/segments/QmasYjyp…/block-changes-descriptor.json`) | Reducer emits v2 after S-C1, via a backfill-common builder: `producer: "pinax-network/substreams-backfills"` (string), details in `producer_contract`; `graph_node.version "0.44.0"`; `manifest_features` as deployed (`nonFatalErrors`, `grafting`) | RED §11.7 |
| R-6 | MINOR | RED classes {Hot, Tiered, PeriodDay, PeriodHour, BlockLocal, NeverWritten}; ENGD {persistent, block_local, period_scoped} with evidence files `evidence/store-access-inventory.json`, `evidence/id-schemes.json` that no slice produces | — | Mapping: Hot/Tiered/NeverWritten → `persistent`; PeriodDay/PeriodHour → `period_scoped` (`whole_id` for UniswapDayData, `suffix_after_last "-"` otherwise); BlockLocal → `block_local` (`derived_from_transaction` for Transaction/Swap/Mint/Burn, `block_number_suffix "#"` for PositionSnapshot). S-R6 writes the two evidence files from the decompile inventory | RED §13.1; ENGD §2.2 (evidence owner) |
| R-7 | MAJOR | RED §0.5/§11.5/§16.2: "negative values may carry 35 digits; hard dependency on the Phase-0 fix"; P-3 "validator accepts every corpus result" | Phase 0 `WT-DEC` (10732f4) accepts exactly Graph Node v0.44 fixed points: positive ≤ 34 digits, negative ≤ 116 bits; once-normalized raw negatives in (2^116, 10^35) still refuse. Its review names the reachable Aerodrome path: `convertTokenToDecimal` with `decimals == 0` returns raw `toBigDecimal()` (RED Q-N2), stored once-normalized in `Swap.amount0/1` (the negative side) | Split P-3: n∘n results accepted; n-once raw crossings classified. Add a **Q-N2 reachability scan**: read-only SQL on `sgd2` for Swap amounts with negative coefficients ≥ 2^116 (history ≤ seed), plus an extractor-output scan of 0-decimal tokens' swap amounts over the backfill range. If any exist: a v1.x carve-out in lockstep (common validator, engine `physical_writer::bigdecimal_to_numeric` must stop re-normalizing, mapping-host `value_from_wire`). Fail-closed until then | RED §0.5, §5, §14.1, §16; ENGD §10 (open item); SB common docs |
| R-8 | MINOR | RED §11.5: "magic BCF1, kind 1, block u64 BE, hash, payload len u32 BE" | Engine clock-v1 header is 52 bytes: `BCF1`, kind u8 (1 Observed, 2 SyntheticRangeFill), **3 reserved zero bytes**, block u64 BE, hash[32], len u32 BE (VERIFIED `ENG/src/bin/state-replay.rs:3139-3141`, `ENG/src/block_changes_input.rs:880-887`) | Move the BCF1 clock-v1 codec into backfill-common with the BlockOpsBuilder (S-C3); every producer and consumer uses it | RED §11.5 |
| R-9 | MAJOR | RED §4.3 refuses Synthetic frames; K8SD §4.1 passes `--include-empty-frames`; ENGD §12.3 "final blocks only, no synthetic frames"; driver flags unspecified | Without `--include-empty-frames`, clock-v1 `finish()` returns nil and proves nothing (VERIFIED `ENG/cmd/substreams-native/main.go:520-523`); with it, gaps become kind-2 Synthetic frames (`:320-345`). `--final-blocks-only` is a stock sink flag already exposed (VERIFIED `substreams@v1.18.4/sink/sinker_viper.go:216-217`; engine `go.mod` pins v1.18.4) | Driver always runs `substreams-native --output-format clock-v1 --include-empty-frames --final-blocks-only --limit-processed-blocks K -H X-substreams-acknowledge-non-deterministic:true`. Because `ExtractorBlock` is never empty, a Synthetic frame means a server gap: reducer refuses (exit 4). Reducer also refuses EOF before `--to` and any hash-linkage break | ENGD §5.6; K8SD §4.1; RED §4.3 |

### 1.3 Engine loader/driver → k8s workflow

| ID | Sev | Producer says / consumer says | Verified fact | Resolution | Docs to change |
|---|---|---|---|---|---|
| K-1 | BLOCKER | ENGD §5.6: `block-changes-backfill run --family-pin P --run-binding R --run-binding-sha256 S --work-dir W --state-store W/state --producer-argv-template T --until <target>`; K8SD §4.3/§9.2: discovers `/opt/backfill/generic-runtime.json` (`pinax.backfill.generic-driver/v1`), entrypoints `seed_capture`, `pipelined_backfill`, `audit_sequences`, `verify_run`, with K8SD args (`--run-root`, `--seed-dir`, `--producer-dir`, `--segment-preflight`, …) | — | Engine E8 ships `generic-runtime.json` in the K8SD schema. `pipelined_backfill` = `block-changes-backfill run`, accepting the K8SD args plus `--family-pin <run_root>/family-pin.json` and `--run-binding <run_root>/run-binding.json`. The producer is launched from the staged `runtime.json` (`producer_protocol pinax.backfill.producer/v1`), not an argv template. `seed_capture` = `generic-seed-capture landing`; `audit_sequences`/`verify_run` = `block-changes-load audit|verify` | ENGD §5.6, §12.7; K8SD §4.3 |
| K-2 | BLOCKER | ENGD exit codes 0 target / 3 stopped-before-error / 64 refusal / 75 retryable; K8SD 0/2 params/3 cache-miss-or-coverage/4 data error/5 guard/75/137/143 | 3 means opposite things; 64 is not in K8SD's retry expression | One table, §2.3 below. Handover = **6** (not retried) | ENGD §5.6; K8SD §15.1 |
| K-3 | MAJOR | ENGD §5.4: one line per segment in `<work>/postgres-backfill-progress.jsonl`; K8SD §4.3: `postgres-pipeline-progress.jsonl` at the run root, plus `backfill_phase` stderr events | Exporter production mode reads `run_root / "postgres-pipeline-progress.jsonl"` (VERIFIED `K8S/…/backfill_exporter.py:1407`); `postgres-backfill-progress.jsonl` is the legacy non-pipelined name | Engine writes K8SD §4.3 items 1–3 (journal shape, phase events, stdout summaries) to `postgres-pipeline-progress.jsonl`; its per-segment `journal/<to_block>/` stays as the internal recovery journal | ENGD §5.4 |
| K-4 | MAJOR | K8SD §9.2 capabilities require `subgraph_error_writer`, `data_sources_stream`, `graph_decimal_negative_35_digits` | ENGD §5.7: "Not built: an engine-side `subgraph_error` writer"; in-band, not a stream; Phase 0 rule is fixed-point, not "35 digits" | Capabilities: `deterministic_error_stop_before`, `data_sources_in_band_v1`, `graph_decimal_v044_fixed_point`, `producer_completion_receipt_v2`, `final_blocks_only`, `graft_self_copy_landing`, plus the unchanged ones | K8SD §9.2 |
| K-5 | MAJOR | K8SD §4.1 wires `state-replay --input-generic-checkpoint C(s-1)` and a data-source companion | ENGD §2.8: `--state-store` refuses `--input-generic-checkpoint`, `--data-sources-sidecar`, `--data-sources-chunk`; uses `--seed-snapshot` / `--input-generic-spool` | K8SD defers the pipe to the driver; §4.1 rewritten to the v3 flags | K8SD §4.1 |
| K-6 | BLOCKER | Phase 0 WT-SC: `BACKFILL_PRODUCER_RECEIPT` = exact `producer_exit_status=0\n` (VERIFIED `WT-SC src/bin/state-replay.rs:3280-3283`), checked before COMMIT/append/seal (`:2700`, `:912`); the review notes it is not bound to the run and that `--postgres-spool-output` still seals on bare EOF when unset. Neither ENGD nor K8SD uses it | The generic pipe has two upstream processes (substreams-native, reducer); clock-v1 in-band proof covers truncation only if the reducer never fabricates frames | **Receipt v2** `pinax.backfill.producer-receipt/v2` JSON: `{start, stop_exclusive, head_hash, spkg_sha256, module_hash, chain:[{name:"substreams-native", sha256, exit:0}, {name:"producer", sha256, exit:0}]}`, written atomically by the driver only after both exit 0. state-replay validates it against `--expected-head-block/--head-block/--head-hash`, **requires** it with `--state-store`, and records its sha in the spool manifest (`completeness.producer_receipt_sha256`). K8SD segment preflight requires that field. `generic-runtime.json` pins the substreams-native sha, so a pre-fix binary (which exits 0 on cancel) cannot be paired | ENGD §5.6, §5.8; K8SD §4.3, §8.8, §9.2 |
| K-7 | MAJOR | K8SD §8.6: probe `pg_locks` advisory `classid IN (1,2,3) AND objid = site AND objsubid = 2` must be 0, inside the segment-preflight hook; ENGD §5.3 L1 takes `pg_try_advisory_xact_lock(1|2|3, site)` in the open txn and "re-runs the external guard hook" before COMMIT | Two-key advisory locks appear as `classid=key1, objid=key2, objsubid=2`: the hook would count the loader's own locks and refuse every commit | Hook runs with `BF_SEGMENT_PREFLIGHT_PHASE=pre-begin` (full probe) and `pre-commit` with `BF_LOADER_BACKEND_PID`; the probe excludes that pid | ENGD §5.3; K8SD §8.6, §8.8 |
| K-8 | BLOCKER | K8SD §8.2 `bf_verify_target_identity` requires graft NULL; ENGD §3.2 refuses "graft fields ≠ profile", §5.3 L2 "graft as pinned" (generalized from the V3 root loader, which requires NULL, VERIFIED `ENG/src/v3_root_load/transaction.rs:157-159`) | VERIFIED: a Graphman copy has `graft_base = QmasYjyp…` and `graft_block = copy checkpoint` (see §0 item 4) | Landing identity carries a **self-copy graft tuple** `{kind: "self_copy", base: deployment, block: C, hash: H(C)}` from the Option C seed evidence. Guards require exactly that tuple (and `head > C` so `graft_pending` is false). Deployment manifest/profile `graft: null` stays (the deployed manifest has no graft) | K8SD §6, §8.2; ENGD §3.2, §5.1, §5.3; OPTC §5.6 |
| K-9 | MAJOR | K8SD §9.3: `contract/physical-profile.json` inside the producer image | The profile pins `runtime.image` (engine digest), runtime binaries and the producer SPKG (VERIFIED `ENG/src/physical_profile.rs:759-783`) and is captured from the landing clone (ENGD §6.2): inside the producer image it forces a producer rebuild per engine release and makes the two-phase pin circular. ENGD R12: adapters must not be baked into the image they pin | Producer image carries: reducer binary, descriptor v2 (+`.sha256`), extractor SPKG (+ release lock), `runtime.json`, family contract (engine *requirements* only). The physical profile and the landing pin travel in the target ConfigMap (hashed, immutable, prune-disabled), pinned by sha in `target.json` | K8SD §9.3, §6 |
| K-10 | MINOR | Spool provenance names differ: ENGD `GenericProducerIdentity{producer_image_digest, reducer_binary_sha256, reducer_commit, extractor_spkg_sha256, extractor_module, extractor_module_hash, substreams_native_sha256}`; K8SD §8.8 checks `spkg_sha256, spkg_module, module_hash, image_digest, state_replay_sha256, substreams_native_sha256, family_producer_sha256, family_contract_sha256` | — | One list (§2.1) | ENGD §5.8; K8SD §4.3, §8.8 |
| K-11 | MINOR | Identity files overlap: ENGD family pin `adapters/<family>/landing.json` + run binding; K8SD `target.json` + `run-contract.json` | — | `target.json` is the single reviewed landing identity. The engine family pin is rendered from it + the producer contract during preflight and sealed in the run root; `block-changes-load preflight` writes `run-binding.json`, its sha is shown at the approval suspend and recorded in `run-contract.json` | ENGD §5.1; K8SD §6, §15.3 |
| K-12 | MINOR | RED CLI `aerodrome-reducer run|seed-import|checkpoint|descriptor|diff-frames`; K8SD `producer stage|version --json|seed|reduce` | — | The binary implements `pinax.backfill.producer/v1`: `stage`, `version --json`, `seed --from <BCGSNAP1>` / `seed --empty --start-block 13843704`, `reduce`, `rewind`; developer subcommands stay | RED §3.3; K8SD §9.3 |
| K-13 | MINOR | K8SD §15.3 allows `runtime.*` amendments mid-run, including the producer digest | A reducer source change changes `producer_contract.reducer.commit` ⇒ descriptor ⇒ `compatibility_id`; the engine binding refuses continuation | Producer amendments only when the descriptor sha is unchanged (rebuilds); otherwise a new lineage from a fresh seed | K8SD §15.3 |
| K-14 | MINOR | K8SD §12.1 sizes 4 generations of producer state | With in-place redb + undo files (R-3), ESTIMATE: engine store 85–110 GiB + reducer 30–40 GiB + deltas/snapshot + two 50k spools ≈ 300–400 GiB at target | 1 Ti stays; rewrite the rationale | K8SD §12.1 |
| K-15 | MINOR | K8SD §17 `oracle-window`: any `window-start ≥ start_block` with `producer seed --empty` | An empty seed is wrong state for any window above the root; ENGD E1 refuses a fresh root unless `expected_head + 1 == start_block` | Empty seed only for `window-start = 13,843,704`; later windows take an engine **oracle** BCGSNAP1 at B−1 (E5, needs D8 and O4) for both engine and producer | K8SD §17 |

### 1.4 Noop evidence → backfill preflight

The noop branch (`WT-NOOP`, `claude/substreams-noop-workflow`, commits 7de1e08, f857943, 756da15, abe96e4 plus
uncommitted review fixes) already exists; K8SD §1 says "no commits yet" and specified the consumer side blind.

| ID | Sev | Backfill expects (K8SD §7) | Noop produces (VERIFIED `WT-NOOP`) | Resolution |
|---|---|---|---|---|
| N-1 | MAJOR | global outputs `noop-evidence` + `noop-evidence-sha256`; `schema == pinax.substreams-noop.evidence/v1`; canonical `jq -cS` bytes | outputs `substreams-noop-evidence` and `substreams-noop-cache-last-block` (`base/substreams-noop-workflow-template.yaml:253-259`); `{"format_version":1,"producer":"substreams-noop-evidence-v1",…}` built with printf (`base/scripts/noop-run.sh:112-170`); no sha output | Backfill adopts the noop contract: reads `substreams-noop-evidence`, computes sha256 over the exact value it was given, drops the canonical-form rule, accepts `producer == "substreams-noop-evidence-v1" && format_version == 1` |
| N-2 | MAJOR | coverage end `range.stop_block` (`target + 1 ≤ stop`) | `result.cache_last_block`: `stop−1` only when stop is bundle-aligned and below the server head, else the end of the last complete bundle, `null` for smokes (`noop-run.sh:96-110`, review finding 3) | Coverage `[start, cache_last_block]`; `null` ⇒ no coverage. Gate `target_block ≤ cache_last_block` and `seed + 1 ≥ start` |
| N-3 | MINOR | `workflow.{namespace,name,uid,template}` | `workflow` = name only, plus `attempt` | uid/template come from the live Workflow at bind time (K8SD §7.3 step 4 already reads it) and are sealed in the proof file |
| N-4 | MAJOR | `spkg.url` fetched by the noop | the noop downloads over HTTPS **without credentials** (P0-3 open issue); `pinax-network/substreams-backfills` is **INTERNAL** (VERIFIED `gh repo view`; the V4 substreams repo is PUBLIC) | User decision D-A (§4) |
| N-5 | MINOR | `module_hash` may be null when `params == []` | always present: `package.module_hash` from `substreams info` (40-hex), refused if it differs from `expected-module-hash` (`noop-assert-package.py:50-56`) | Require non-null equality. Params are baked into the SPKG (EXT §5.2), so runtime `params` is `[]` in noop, family contract and driver |
| N-6 | MINOR | field names `spkg.{url,sha256,bytes}`, `module`, `output_type`, `initial_block`, `mode.*` | `package.{spkg_url, spkg_sha256, spkg_bytes, module, module_hash, module_output_type, module_initial_block, lowest_store_initial_block, params, used_modules}`, `request.{production_mode, noop_mode, final_blocks_only, start_block, stop_block_exclusive, acknowledge_non_deterministic, limit_processed_blocks}`, `endpoint`, `endpoint_dc` (`noop-assert-package.py:98-116`) | Mapping table in K2-1's `noop_evidence.py` |
| N-7 | MINOR | release `aerodrome-slipstream-base-substreams-v0.1.0` (K8SD §9.3, SYN §5) | EXT §13: tag `aerodrome-slipstream-base-extractor-vX.Y.Z`, asset `…-extractor-vX.Y.Z.spkg` | Use EXT's names |
| N-8 | MINOR | SYN §6.2 / ENG `BACKFILL_PREWARM_SUBSTREAMS=1` prewarm | K8SD: no prewarm, `--limit-processed-blocks = cache-miss-tolerance` tripwire | K8SD approach. E8 passes the flag and maps substreams-native's `FailedPrecondition … limit-processed-blocks` (it exits 1 on any error) to exit 3 |

### 1.5 Option C seed → engine seed capture

| ID | Sev | Issue | Resolution |
|---|---|---|---|
| C-S1 | BLOCKER | Self-copy graft fields (K-8) | OPTC §5.6 seed evidence already records `checkpoint {number, hash, offset}`; it becomes the landing graft tuple in `target.json` and the family pin |
| C-S2 | MAJOR | SYN C3 ("sgd5311 data copy plausibly completed") is wrong: OPTC §2.1 VERIFIED from the worker log the copy is 89.63 % and never finished | Seed strategy S2 is dead; S3 (fresh Graphman copy on dom153) only. Correct SYN C3 and D2 |
| C-S3 | MINOR | OPTC: S = head − 1,000, but the copy keeps indexing until paused, so the seed head is ≥ S; the graft block C (= S) ≠ seed head | `expected-seed-block/hash` = post-pause `subgraphs.head`; C recorded separately |
| C-S4 | MINOR | `generic-seed-capture landing` needs all three advisory locks free and head == expected | Order: copy finished → postponed indexes → pause → worker replicas 0 (C-7) → `catalog` capture on the same clone (K-CAT) → profile → `landing` capture inside the approved workflow |
| C-S5 | MINOR | OPTC O8.c uses `coalesce(max(vid), 0)`; engine uses −1 for empty | Evidence only; align to −1 |
| C-S6 | MINOR | Kan runs graph-node **v0.45.0** (OPTC aliases); oracle, reducer and descriptor are pinned to v0.44 `77823b5a`. `sgd2` rows since the v0.45 rollout and the C0/C3 continuation are v0.45 output | Read-only diff v0.44→v0.45 of `runtime/wasm`, `chain/ethereum` codec, BigDecimal and the store write path (OPEN); G3/G-ORACLE windows must include post-v0.45 blocks; run binding records `continuation_graph_node_image` (ENGD already) |
| C-S7 | MINOR | OPTC §5.7 asks to assert the C0 worker (`index_node_aerodrome_0`) has no assignment on `aerodrome_b`; K8SD registry checks lack it | Add to `bf_verify_registry` (registry query, not replicas) |

### 1.6 Cross-cutting observations (no doc conflict, but they change plans or risk)

- **Wave correctness** is consistent across EXT §8.1, RED §11.2 and the oracle (trigger-major, host-minor; new hosts
  only in stage 1; gating by creation block). VERIFIED in `SB/mapping-host/src/runner.rs:1-37, 872-917`.
- **Per-save ops** in the oracle come from a patched op recorder (`SB/mapping-host/src/blockchanges.rs:44, 76-130`),
  so RED's one-`SetEntity`-per-`save()` model is comparable byte for byte. The header comment at
  `runner.rs:28-32` ("one ordered modification set per handler") is stale.
- **Declared calls.** The deployed manifest declares `positions`, `ticks`, `feeGrowthGlobal*` calls (VERIFIED
  `SB/aerodrome-slipstream-base/reference/deployment.yaml`). Graph Node only pre-warms them (P0-4), so the
  handlers' own calls are what EXT/RED must answer. No interface change.
- **`sgd2` logs ≈12 "Contract call reverted, reason: empty response" per block** (1,689 in a 2-minute window, all
  `sgd: 2`, beside 394 `execution reverted: ID` and "Declared calls failed, failures: [positions …]"; VERIFIED in
  `scratchpad/optc/base-cur.log`). Most plausibly the runtime-path `try_positions` reverts for tokens burned in the
  block, but this is not attributed (OPEN). If any were RPC-induced false reverts for live tokens, Graph Node's
  history would contain values a storage-derived extractor cannot reproduce. G3 must cover dense NPM windows;
  attribution is a read-only task under D8.
- **SPKG params** are baked into the package (EXT §5.2), so nothing passes `-p` at run time.

### 1.7 Errata by document (what each doc must change)

- **EXT**: X-2/X-4/X-5 (crate APIs), X-7 (G4 → G4 + G4′, freeze gate), X-8 (fixture lock), §10.1 add "requests use
  `--include-empty-frames --final-blocks-only`", consumer pin list uses §2.1 names, release hosting per D-A.
- **RED**: X-1, X-2, X-3, X-6, X-9, R-1…R-8, K-12; §14.2 windows (root-only for G2); §15 slice list per §3 here.
- **ENGD**: X-1 (example), R-3 (`producer_checkpoint`), K-1…K-4, K-6, K-7, K-8, K-11; split E4 into E4a/E4b; E1
  binding must accept the self-copy graft tuple; E8 owns receipt v2, exit table, journal/events, flags.
- **K8SD**: K-1…K-9, K-13…K-15, N-1…N-8, C-S7; §1 note about the noop branch is stale.
- **OPTC**: C-S5 (−1), record graft tuple and post-pause head explicitly in `pinax.aerodrome.seed-copy/v1`.
- **SYN**: C3 and D2 corrected (C-S2); release tag naming (N-7); prewarm (N-8).

---

## 2. Canonical contracts after reconciliation (normative)

### 2.1 Identity pins and their names in each artifact

| Value | Extractor release lock | Descriptor v2 `producer_contract` | Physical profile | Family contract (producer image) | Noop evidence | Spool manifest v3 `producer` | Reducer checkpoint |
|---|---|---|---|---|---|---|---|
| SPKG sha256 | `spkg_sha256` | `extractor.spkg_sha256` | `producer.spkg.sha256` | `extractor.spkg_sha256` | `package.spkg_sha256` | `spkg_sha256` | `extractor.spkg_sha256` |
| module | `module` = `map_extractor_block` | `extractor.module` | `producer.module` | `extractor.module` | `package.module` | `spkg_module` | `extractor.module` |
| module hash (40-hex) | `module_hash` | `extractor.module_hash` | `producer.module_hash` | `extractor.module_hash` | `package.module_hash` | `module_hash` | `extractor.module_hash` |
| output type | `output_type` | `extractor.output_type` | `producer.output_type` | `extractor.output_type` | `package.module_output_type` | — | — |
| initial block | `initial_block` 13,843,704 | `extractor.initial_block` | — | `extractor.initial_block` | `package.module_initial_block` | — | — |
| runtime params | none (baked) | — | — | `extractor.params: []` | `package.params: []` | — | — |
| reducer source | — | `reducer.{repository, commit}` | — | `source_commit` (runtime.json) | — | `reducer_commit` | `reducer.source_commit` |
| reducer binary | — | — | — | `files["bin/producer"]` | — | `family_producer_sha256` | `reducer.binary_sha256` |
| producer image | — | — | — | — | — | `producer_image_digest` | — |
| family contract | — | — | — | itself | — | `family_contract_sha256` | — |
| descriptor | — | sha256 = `compatibility_id` | binding | `descriptor.sha256` | — | `descriptor_sha256` | `descriptor_sha256` |
| engine image + binaries | — | — | `runtime.image`, `runtime.binaries` | `engine_requirements` only | — | `image_digest`, `state_replay_sha256`, `substreams_native_sha256` | — |
| completion receipt | — | — | — | — | — | `completeness.producer_receipt_sha256` | — |

Exact digests (engine image, producer image, profile sha, landing pin sha) are pinned once, in `target.json`.

### 2.2 Range conventions

| Artifact | Convention |
|---|---|
| Noop request | `[start_block, stop_block_exclusive)`; guaranteed cache `[start, result.cache_last_block]` |
| substreams-native | `-s s -t e+1` (exclusive stop) |
| Reducer `reduce` | `--from s --to e` inclusive; `s = boundary + 1` |
| state-replay | `--expected-head-block s−1 --expected-head-hash H(s−1) --head-block e --head-hash H(e)` |
| Loader | moves `subgraphs.head` from `(s−1, H)` to `(e, H(e))`; cursor NULL |
| k8s | `target-block` inclusive, `≤ RPC finalized`, `≤ cache_last_block`; segment `[head+1, min(head+50,000, target)]` |
| BCGSNAP1 | boundary = state **after** block B; first frame is B+1 |
| Graphman copy | graft block C (copy checkpoint); seed head ≥ C (post-pause) |
| Oracle windows (mapping-host evidence) | R0 `[13,843,704, 13,899,663)`, R1 `[13,899,663, 13,919,663)` |

### 2.3 Exit codes (driver, segment preflight, producer, template steps)

| Code | Meaning | Retried by Argo | Raised by |
|---|---|---|---|
| 0 | success / target reached | — | all |
| 2 | invalid parameters, inert target, contract or manifest refusal | no | validator, preflight, driver |
| 3 | cache miss (`FailedPrecondition` on `limit-processed-blocks`) or noop coverage gap | no | driver (mapped from substreams-native), segment preflight |
| 4 | deterministic data or contract error: reducer refusal (`MissingCallAnswer`, extractor anomaly, synthetic frame, contract/identity mismatch, `StateCorrupt`), state-replay materialized mismatch | no | producer, state-replay, driver |
| 5 | safety guard: writer exclusion, registry, head/identity/graft, capacity, lock ownership, run-contract drift | no | template, segment preflight, loader |
| 6 | stopped before a deterministic error; N−1 loaded; `handover.json` written | no | driver (from `--on-deterministic-error stop-before`) |
| 75 | transient (network, API, PG connect, retryable Substreams, truncated input with a failed upstream) | yes | all |
| 137 / 143 | OOM / SIGTERM | yes | kernel / kubelet |

### 2.4 Frame and stream contract (extractor → reducer → engine)

- One `ExtractorBlock` per block, never empty; clock-v1 Observed frames only; envelope hash = `ExtractorBlock.hash`.
- One canonical `BlockChanges` (descriptor v2, `NON_FATAL`, region `ethereum/base`) per block, including untriggered
  blocks; field 9 only under `in_band_v1`; per-save ops in call order; `handler_order = 0`;
  `source_trigger_order = Log.block_index`.
- Receipt v2 gates every seal (K-6). Final blocks only. No Synthetic frames anywhere on this path.

### 2.5 Seeds, checkpoints, lineage

- Seed: `generic-seed-capture landing` → `seed.bcgsnap` + `seed.json`. Engine `generic-state init` and
  `producer seed --from seed.bcgsnap` both start from it; the reducer refuses unless the engine L0 lineage matches.
- Per segment: engine BCGCKPT3 + BCGDELT1 + spool v3 (with `producer_checkpoint` and receipt); reducer checkpoint
  manifest + undo file. Rewind: engine `generic-state rewind` and `producer rewind` to the same `(block, hash)`.
- Oracle: `generic-seed-capture oracle` at B−1 (never loadable) feeds both for M4 windows.

---

## 3. Implementation plan: ordered PR-sized slices

Repos: SB = substreams-backfills (Rust-only, `cargo xtask`), ENG = substreams-graph-node-backfill, K8S =
k8s-subgraphs, PSK = pinax-skills. Estimates are the design docs' own (engineer-days, ESTIMATE). "Gate" is the
acceptance condition for merging the slice.

### Wave 0: in flight (finish, review, merge; merging needs the user to push)

| ID | Repo / branch | Status | Remaining gate |
|---|---|---|---|
| P0-1 | SB `feat/block-changes-negative-decimal-precision` (10732f4) | review: ship (2 minor doc notes) | add the Aerodrome Q-N2 note; `cargo test --workspace --locked`, clippy, fmt, `cargo xtask verify-all` (already green per state) |
| P0-2 | ENG `fix/stream-completeness` (e0524a9, 103b54a) | review: fix-then-ship | fix the major (successor image lacks `append-parquet-segment.sh`); PIPESTATUS/SIGPIPE quarantine; CLI test for the spool receipt; `make validate` |
| P0-3 | K8S `claude/substreams-noop-workflow` | review: fix-then-ship; fixes in progress (3 commits + WIP) | finish review items; freeze the evidence fields of §1.4 as the documented contract; contract test + `argo lint --offline --strict` |
| P0-4 | SB `feat/aerodrome-mapping-host-oracle` (85c99bd, f0a4f24, 93c4ca9) | not yet reviewed | review; publish fixture lock `aerodrome-base-block-fixtures-v1` (approval) and un-ignore the segment test |
| P0-5 | PSK `feat/develop-subgraph-backfill-substreams` | drafted | independent; fold in the decision rules confirmed here (root-only oracle, fixed-point decimals, in-band sources) |

### Wave 1: shared contracts in SB `common/` (small, unblock every track)

| ID | Content | Depends | Gate | Est. |
|---|---|---|---|---|
| S-C1 | Descriptor v2 (`DescriptorCapabilities`, retention policy + canonical `retention_sha256`), `state_snapshot.rs` (BCGSNAP1 reader/writer, trailer sha, lineage fns) | P0-1 merged | `cargo test -p backfill-common --locked`; v1 descriptors and goldens byte-identical; BCGSNAP1 round-trip and truncation refusals; `cargo xtask verify-all` | 3–4 |
| S-C2 | `BlockChanges.created_data_sources = 9` + validator rules (ENGD §4.4) + golden frames; mapping-host `--data-sources-in-band`; regenerate R0/R1 oracle frames with field 9 | S-C1, P0-4 merged | refusal tests (no capability, discarded group, duplicate, synthetic); V3 mapping-host goldens unchanged; R1 field-9 creations == the v2 chunk's 13 pool creations | 2–3 |
| S-C3 | Move `BlockOpsBuilder` and the BCF1 clock-v1 codec (52-byte header) into backfill-common; mapping-host adapter | P0-4 merged | mapping-host goldens byte-identical; BCF1 bytes equal the engine fixture (`block_changes_input.rs:880-887` layout) | 2 |

### Wave 2: extractor (SB `aerodrome-slipstream-base/substreams/`), parallel with Wave 3

| ID | Content (EXT §17, amended) | Depends | Gate | Est. |
|---|---|---|---|---|
| S-X1 | Workspace, pins, protos, `pb` (+ `sf.ethereum.type.v2`), `core` (layout, config, raw-field gas fn, shard, walk, classify, carry, calls), xtask build/protogen, CI; root `exclude`; reducer path-dep smoke | — | G0 | 3–4 |
| S-X2 | Abigen + `map_pools_created`, `map_candidates`, `store_pools`; family fixture lock; X-START/X-NPM-START/X-CREATE/X-GUARD goldens | S-X1 | G1 (wave order `[(0,172),(0,177),(0,178),(1,171),(1,176)]`) | 3–4 |
| S-X3 | `map_storage_deltas`, carry stores, capture-fixture | S-X2 | G2 | 5–7 |
| S-X4 | `map_token_metadata`, answer modules, `map_extractor_block`; pack/info; cache-boundary | S-X3 | G0–G2 complete goldens; **non-final SPKG usable for M2** | 4–5 |
| S-X5 | `verify-live`, cassette `differential` (root windows), full `eth_call` audit of every emitted answer (G4′), `audit-erc20`, `find-fixtures`, Q-N2 swap-amount scan, `map_slot_audit` | S-X4 | G3 on non-final builds | 4–5 |
| S-X6 | Measurements: 1-block then 100k-block noop smokes through P0-3 (kan, then riv); G5 store sizes; G6 ERC20 audit; G4 (root cassette) + G4′ (W2/W3); baseline vs Option R decision | S-X5, P0-3 merged, D-F | G4, G4′, G5, G6 | 3–5 |
| S-X7 | Freeze: lock JSON, committed bytes, `release.yml`, tag `aerodrome-slipstream-base-extractor-v0.1.0`, hosting per D-A | S-X6, M2 green, D-A | G7 | 1–2 |

### Wave 3: reducer (SB root workspace `crates/`), parallel with Wave 2

| ID | Content (RED §15, amended) | Depends | Gate | Est. |
|---|---|---|---|---|
| S-R1 | `crates/graph-numerics`; corpus from the mapping-host; P-3 split into fixed-point vs once-normalized | P0-1 | G1 numerics 100 % | 3–4 |
| S-R2 | Skeleton + input: path-dep `aerodrome-extractor-pb`; BCF1 via common; validation incl. anomalies/contract/version, Synthetic refusal, EOF-before-`--to` refusal; core gas fn; alloy decode; `CallBook`; ERC20 semantics | S-R1, S-X1, S-C3 | unit + synthetic input tests | 5 |
| S-R3 | Entity model (302/289/13), overlay + journal, MemoryBackend, sealing through `encode_canonical_block_changes` | S-R2, S-C3 | schema-conformance test | 4–5 |
| S-R4 | Port 1: Factory + token metadata, NPM, Flash, `load_transaction` | S-R3 | S-tests | 4–5 |
| S-R5 | Port 2: pricing, interval updaters, ticks + `TickPowTable`, Initialize/Mint/Burn/Swap + walk | S-R4 | S-tests, F-POW | 7–9 |
| S-R6 | Runner: waves, handler groups, `mapping_triggered`, fail-closed and **emit-non-fatal**, in-band creations, descriptor v2 builder, retention evidence files, JSONL report | S-R5, S-C1, S-C2 | synthetic frame tests incl. abort → `DISCARDED` + `DeterministicError` + dropped creation | 3–4 |
| S-R7a | `diff-frames` + oracle window fixtures (R0/R1 frames, cassettes, field 9) | S-R6, S-C2 | diff tool self-tests; **used by M1/M2** | 2–3 |
| S-R7b | `reference-extractor` feature + G2 on root-reachable windows (W1/W2 + reachable edge cases) | S-R7a | **G2 zero diffs** (M1) | 4–6 |
| S-R8 | RedbBackend + LRU tiers, one write txn per segment, undo + reducer lineage, checkpoint manifest bound to engine lineage, `rewind` | S-R6 | G5 lifecycle (chunked == uninterrupted, kill −9, rewind/replay identity) | 5–6 |
| S-R9 | `seed --from BCGSNAP1`; `PgOracleBackend` (test-only); `timetravel-diff` | S-R8, S-C1 (+D8, O4 for live G3) | G3 on ≥ 20 windows (when D8 lands) | 6–8 |
| S-R10 | 3-stage pipeline, profiling | S-R8 | G6 ≥ 100 blocks/s, RSS ≤ 16 GiB | 3–4 |
| S-R11 | Producer runtime image: `pinax.backfill.producer/v1` CLI (`stage`, `version --json`, `seed`, `reduce`, `rewind`), `runtime.json`, family contract (no profile), `cargo xtask producer-runtime …`, `producer-runtime.yml` (ORAS discovery like #146) | S-R8, S-R9; final SPKG from S-X7 (pre-release images carry a labelled non-final SPKG) | offline smoke on committed fixture frames; discovery verify | 3–4 |
| S-R12 | Engine integration: G4 PoI on oracle windows; full-range dry run | E5, E8, M4 | G-ORACLE PoI equal | 4–6 |

### Wave 4: engine (ENG)

| ID | Content (ENGD §10, amended) | Depends | Gate | Est. |
|---|---|---|---|---|
| E-VEND1 | Re-vendor `third_party/backfill-common` at P0-1's merge (block_changes.rs sha `8d376775…`), re-pin `COMMON_COMMIT`, regenerate V4 shadow descriptor (its compatibility_id changes); regression test for `-1958.2627366648723548155211868460794` | P0-1 merged, P0-2 merged | `make validate`; V4 offline parity | 1–2 |
| E0 | Generic-path hardening (Null strip, refusals, fsync, NUL, doc truth) | P0-2 | G-E0 | 3 |
| E1 | Descriptor v2 binding (vendors S-C1), template profiles selectable, second runtime-binary set, fresh-root start-block binding, **self-copy graft binding** | S-C1, E0 | G-E0 + binding tests | 3–4 |
| E2 | Retention-aware `GenericState` on `MemoryEntityStore`, G1/G2/G4 guards | E1 | G-RET-1 | 4–5 |
| E4a | In-band sources on the memory store (vendors S-C2): `created_sources`, writer rows, source commitment (split from ENGD E4 so M3 does not wait for redb) | E2, S-C2 | in-band tests; M3 | 2–3 |
| E3 | redb store, BCGDELT1, BCGCKPT3, spool v3 (+`producer_checkpoint`, receipt sha), `generic-state` bin | E2 | G-STORE-1…4 | 6–8 |
| E4b | In-band sources in the redb store; v3 provenance; re-pin COMMON commits | E3, E4a | G-STORE-1 with sources | 2 |
| E5 | `generic-seed-capture` landing/oracle/catalog; −1 VIDs; self-copy graft accepted; V4 −1 fix | E3 | G-SEED-1 (PG16); G-SEED-2 needs the clone | 5–7 |
| E6 | `block-changes-load` over CopyIn; preflight → run-binding; pre-begin/pre-commit hook phases; journal + recover | E4b, E5 | G-LOAD-1 (PG16 matrix) | 6–8 |
| E7 | `stop-before` + handover receipt, exit 6 | E3 | stop-before tests | 2–3 |
| E8 | `block-changes-backfill` driver; `generic-runtime.json` (K8SD schema, §1.3 capabilities); producer protocol; receipt v2; `--include-empty-frames --final-blocks-only --limit-processed-blocks`; FailedPrecondition → 3; journal/events/stdout per K8SD §4.3; §2.3 exit table | E6, E7 | driver tests; exporter-compat journal fixtures | 5–6 |
| E9 | Benchmarks, deferred-index plan | E8 | G-PERF | 4–5 |
| E-REL | Release image (e.g. v0.6.0) with digest and binary shas | E8 (+E9 decision) | release verify; two-phase pin | 1 |

### Wave 5: k8s-subgraphs and Option C

| ID | Content | Depends | Gate / approval |
|---|---|---|---|
| C-1 | OPTC C0: pin `graph-node-aerodrome-0` to dom153, docs; live pause `sgd5311`, move `sgd2` | — | approvals L1–L3; G-C0.1–C0.7 |
| C-2 | OPTC C0b alerts (`SubgraphsDeploymentFailedInWorkerOnly`, head-stalled) + tests | — | L4; alert tests |
| C-3 / C-4 | Entity cache; Base RPC override | C-1 + 72 h; RPC owners | L5 / L6 |
| K2-1 | Generic library WorkflowTemplate with every §1.3/§1.4 resolution (noop mapping, cache_last_block coverage, exit table, capabilities, receipt, hook phases, self-copy graft, profile in ConfigMap, C0-assignment check) | P0-3 merged | A1 (render, strict lint, contract/unit tests; V4 untouched) |
| K2-2 | Aerodrome target, inert (`target.json`, wrapper, work PVC prune-disabled, writers Role) | K2-1 | A1, A2 (inert proof) |
| K2-3 | Exporter `DISPLAY_NAME` + generic receipt view | — | exporter tests |
| K2-4 | `oracle-window` (empty seed only at root; oracle-snapshot mode) | K2-2 | inert until E-REL + S-R11 |
| K2-5 | VMRule alerts, runbook, skill section, backfill-flag label fix | K2-2 | alert tests |
| C-5 | Landing store `aerodrome_b` 12 TiB on dom153, `aerodrome-backfill-postgres`, seed worker, store config, baseline | D6 | L7; G-S0, G-S1 |
| C-6 | Graphman copy of `sgd2` (live) + seed evidence (with graft tuple and post-pause head) | C-5, C-1 | L8; G-S2–G-S4 |
| C-7 | Park the seed (pause, worker replicas 0) | C-6 | L9; G-S5–G-S8 |
| K-CAT | `generic-seed-capture catalog` on the parked clone → live-catalog profile → target ConfigMap PR | C-7, E5 | profile `validate_observed_catalog`; review |
| K2-6 | Activation: real digests, landing values, profile/pin shas, `status: active` | E-REL, S-R11 release, K-CAT, full noop evidence (S-X7 + noop) | explicit user approval; A3–A5 |
| C-8 | Retire `aerodrome_a`/`sgd5311` | C-7, D6 | L11 |
| C-9 | Cutover after certification (G-X at F = `sgd2` head) | M8 | L10 |

### Parallel groups

- **G-A (now):** P0-1…P0-5 to merge; S-C3; S-X1; S-R1; C-1/C-2 if approved; K2-1 drafting against §1.3/§1.4.
- **G-B:** S-C1 → S-C2; S-X2…S-X4; S-R2…S-R6; E-VEND1, E0, E1, E2; K2-2, K2-3, K2-5.
- **G-C:** M1/M2; S-X5, S-X6; S-R7…S-R10; E4a, E3, E4b, E5; K2-4; C-5 (if D6 approved).
- **G-D:** S-X7 freeze → full noop; E6, E7, E8, E9, E-REL; S-R11; C-6, C-7, K-CAT.
- **G-E:** K2-6 activation, first landing segments, full run, certification, C-9 cutover, C-8.

### Milestones and the earliest end-to-end run

| M | What runs | Needs | Earliest (ESTIMATE) |
|---|---|---|---|
| M1 | Reducer vs oracle on R0+R1 with the **reference** extractor (Firehose fixtures + cassette) | S-R6, S-R7a/b, S-C1–C3, P0-4 | ≈ week 6 |
| **M2 (first real E2E)** | Live Substreams extractor (non-final SPKG, `S-X4`) over `[13,843,704, 13,919,663)` → substreams-native clock-v1 (`--include-empty-frames --final-blocks-only`) → reducer (fail-closed) → `diff-frames` == oracle frames (compatibility_id masked, field 9 included) and extractor answers ⊇ cassette keys (G4 root) | S-X1–X4, S-R1–R6, S-R7a, S-C1–C3; Substreams token + tier2 budget (~76k blocks, stores build from the root so the cost ≈ the window) | ≈ week 6–7 (reducer R1–R6 is the long pole: 24–30 days; extractor X1–X4 is 15–20) |
| M3 | M2 frames folded by `state-replay` (memory store, fresh root, in-band sources): per-block Fast PoI == the mapping-host's, spool seals with receipt v2 | M2, E-VEND1, E0, E1, E2, E4a | ≈ week 8–9 |
| M4 | Seeded windows on `sgd2`: engine oracle BCGSNAP1 at B−1 → reducer + engine → G3 rows, G-ORACLE `poi2$` digests; extractor G4′ coverage | D8, O4, E5 (oracle), S-R9 | after D8 |
| M5 | Extractor frozen; full-range noop `[13,843,704, finalized)` with evidence | S-X6 (G4, G4′, G5, G6), S-X7, D-A, D-F | ≈ week 9–11 |
| M6 | Cluster smoke: `oracle-window` on Kan at the root (A3) and the cache tripwire (A4) | E-REL (pre-release), S-R11, K2-4 | after E8 |
| M7 | First two landing segments on the parked clone + read-only differential vs `sgd2` (A5), lifecycle drills (A6) | D6, C-5…C-7, K-CAT, E6…E8, K2-6 | after infra approvals |
| M8 | Full run to a fixed finalized target; certification (G-X at F); cutover (C-9) | M7 | ESTIMATE run time 7–21 days (ENGD T5) |

**Critical path to production:** P0-1 → S-C1 → S-C2 → E-VEND1 → E1 → E2 → E3 → E4b → E5 → E6 → E7 → E8 →
E-REL → K2-6, joined by the extractor (S-X* → freeze → full noop), the reducer (S-R* → S-R11) and infra
(D6 → C-5 → C-6 → C-7 → K-CAT). Postgres-2 fill (68.97 %, OPTC §0.6) independently forces C-5…C-7 within about
30–45 days.

---

## 4. Remaining user decisions and infra approvals

| ID | Decision / approval | Recommendation | Blocks |
|---|---|---|---|
| D-A | Where the frozen SPKG is fetched from. The noop downloads with no credentials; `substreams-backfills` is INTERNAL. Options: (a) public release asset in a public repo (V4 precedent: public `substreams-v4-subgraph`); (b) token-bearing fetch (new Secret); (c) noop sources the SPKG from the digest-pinned producer image via `ghcr-cred` | (c) keeps one artifact and no new Secret, but couples the noop to a producer image; (a) is simplest operationally. User choice | S-X7, M5 |
| D-B | Confirm seed S3 only (S2 impossible: `sgd5311` copy never finished) | S3 | C-5…C-7 |
| D-C (D6) | Landing `aerodrome_b` 12 TiB on dom153; `aerodrome-backfill-postgres`; seed worker `graph-node-aerodrome-backfill-0` (outside the agent allow-list); Graphman copy of `sgd2` (pause/drain); 1 Ti work PVC; fate of `aerodrome_a`/`sgd5311` (retire after C-7) | approve as OPTC §5 | M7 |
| D-D | Option C live actions L1–L4 (pin, pause `sgd5311`, move `sgd2`, alerts) | approve; reversible | C-1, C-2 |
| D-E (D8) | Read-only SQL on Kan primary, `postgres-2`, `aerodrome-postgres`: O1, O4 (`history_blocks`), O8, Q-N2 scan, "empty response" attribution, G3/G-ORACLE time travel | approve | M4, R-7 decision |
| D-F | Substreams budget and endpoint: M2 dev runs (~76k root blocks), G5 smokes (2 × 100k), full noop (~39M blocks, ~27 TB snapshot reads ESTIMATE EXT §14); kan vs riv | kan, riv as fallback; coordinate with tier2 owners | M2, M5 |
| D-G | Pushing and publishing: PRs for P0-1…P0-5 and every slice; release assets (fixture lock, oracle cassettes/frames); extractor tag after G4/G4′/G5; engine release (two-phase pin) | per slice | everything past Wave 0 |
| D-H | Production error policy: stop before the first deterministic error and hand over to Graph Node (no engine `subgraph_error` writer) | accept | E7, K2-1 |
| D-I | BigDecimal carve-out (v1.x) only if the Q-N2 scan finds reachable values | decide after the scan | R-7 |
| D-J (D7) | Backfills #86 eligibility: refresh two-cluster evidence or record an explicit override for this user-directed lane | record the override (P0-4 also asks) | governance |
| D-K (D10) | PR footer conflict per repository | per repo | PRs |

Open verifications (no decision, but owners needed): O-SECRETS (`backfill-credentials`, token valid on kan/riv
tier1), O-IMG (`ghcr-cred` can pull private `substreams-backfills` packages), O-EGRESS (Kan pods → tier1 VIPs; first
noop smoke), O4 (`sgd2` not pruned), v0.44 → v0.45 graph-node semantic diff (C-S6), archive RPC for the G6 ERC20
audit.

---

## 5. Verification log (read-only, this pass)

| Claim checked | Command / location | Result |
|---|---|---|
| Oracle `source_trigger_order` semantics | `SB/mapping-host/src/block.rs:199-259`, `runner.rs:872-923` | every receipt log is a trigger; rank per stage; group only when matched ⇒ EXT/RED semantics hold |
| Oracle per-save ops | `SB/mapping-host/src/blockchanges.rs:44,76-130,409-470` | op recorder per save |
| Descriptor version accepted | `SB/common/src/block_changes.rs:42-95` | only `descriptor_version == 1`; checks contract, policy, network, region |
| Oracle descriptor shape | `WT-ORA …/QmasYjyp…/block-changes-descriptor.json` | `graph_node.version "0.44.0"`, `producer` string, v1 |
| BCF1 header | `ENG/src/bin/state-replay.rs:3139-3176`; `ENG/src/block_changes_input.rs:880-887` | 52 bytes incl. 3 reserved; kinds Observed/Synthetic |
| substreams-native flags and completion | `ENG/cmd/substreams-native/main.go:73-180, 320-345, 520-565`; `~/go/pkg/mod/…/substreams@v1.18.4/sink/sinker_viper.go:29,216-217`; `ENG/go.mod` | `--final-blocks-only` available; completion proof only with `--include-empty-frames`; gaps ⇒ Synthetic |
| Driver default endpoint and args | `ENG/scripts/compute-postgres-segment.sh:25,164-165` | `kan-sst2` default; `-s start -t end+1` |
| Exporter journal name | `K8S/subgraphs-operations/backfill/kan/backfill_exporter.py:1351-1407,1478,1580` | production mode reads `postgres-pipeline-progress.jsonl` |
| Profile pins runtime | `ENG/src/physical_profile.rs:15-20, 759-783` | `runtime.image`, exact binaries, `producer.spkg/module/module_hash` |
| Graphman copy graft fields | `git -C ~/.cargo/git/db/graph-node-40979021f9daae1a show 77823b5a:store/postgres/src/subgraph_store.rs` (copy_deployment) and `…:store/postgres/src/deployment.rs:232-282` | `graft_base = src.deployment`, `graft_block = Some(block)`; persisted; pending only while head NULL |
| V3 root loader graft rule | `ENG/src/v3_root_load/transaction.rs:157-159` | requires graft NULL |
| Phase 0 receipt contract | `WT-SC src/bin/state-replay.rs:2700, 3275-3360, 4089` | env var, literal contents, optional for clock-v1 spool |
| Noop evidence contract | `WT-NOOP …/base/substreams-noop-workflow-template.yaml:253-259`; `base/scripts/noop-run.sh:60-170`; `base/scripts/noop-assert-package.py:39-116` | names, fields and `cache_last_block` as in §1.4 |
| Repo visibility | `gh repo view pinax-network/substreams-backfills` / `…/substreams-graph-node-backfill` / `…/substreams-v4-subgraph` | INTERNAL / INTERNAL / PUBLIC |
| Root workspace + alloy pins | `SB/Cargo.toml:1-40`; `SB/mapping-host/Cargo.lock` | explicit members, prost 0.13; alloy 2.4.1, dyn-abi 1.7.2 |
| Declared calls | `SB/aerodrome-slipstream-base/reference/deployment.yaml` | positions / ticks / feeGrowthGlobal* declared; `features: nonFatalErrors, grafting` |
| "empty response" reverts | `scratchpad/optc/base-cur.log` (grep by `sgd: 2`) | 1,689 empty-response + 394 `ID` reverts in 2 minutes, plus "Declared calls failed: positions" |
| Phase 0 states | `scratchpad/phase0/*.json` | as summarized in §3 Wave 0 |

Checks run: none of the repositories was modified, so no repository check applies; every command above is a
read-only read, grep, `git show` or `gh repo view`.
