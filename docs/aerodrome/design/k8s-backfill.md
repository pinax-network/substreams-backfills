# Design: generic Substreams → Graph Node backfill WorkflowTemplate (k8s-subgraphs, BlockChanges path)

Date: 2026-10-20. Strictly read-only design; nothing was committed, pushed, applied or written to a database.
Area: the k8s-subgraphs **backfill** WorkflowTemplate for the family-neutral BlockChanges path, placed in the new tree
`subgraphs-operations/backfill-substreams/` that the parallel noop work (PR-K1) creates. First target: Aerodrome
Slipstream Base `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`.

User decisions this design implements (2026-10-20, not relitigated): D1 route A + C; D3 reducer emits canonical
`pinax.graph.backfill.v1.BlockChanges` in BCF1 clock-v1 frames, engine stays family-neutral; D4 extractor lives in
substreams-backfills, SPKG pinned by sha256 + module hash; D5 call answers from storage changes; seed = graphman copy
of live `sgd2` at ~34.7M into a dedicated stopped store; root replay must stay possible for oracle windows.

## Evidence labels

- **VERIFIED**: read in code/config, or ran a probe, during this pass. Cited `file:line`.
- **REPORT-VERIFIED**: verified by a survey report (`scratchpad/survey/*.md`), cited by report + section.
- **ASSUMED**: a design assumption that needs a named check before it is relied on.
- **ESTIMATE**: arithmetic from verified inputs.
- **PROPOSED**: a new interface or decision introduced by this design.

Source roots: `K8S/` = `scratchpad/ro/k8s-subgraphs` (origin/main `4da0b37`); `ENG/` = `scratchpad/ro/engine`
(origin/main `5c98b57`); `SB/` = `/Users/denis/Github/substreams-backfills` (`bbe3783`); `ARGO/` =
`scratchpad/ext/argo-workflows` (tag `v4.0.7`, read-only); `SS/` = `~/Github/substreams` (`v1.22.0`);
`GN/` = graph-node `77823b5a` (cargo bare repo, `git show`).

---

## 0. Decisions on one page

1. **Three GitOps objects per target, one shared library.** (PROPOSED)
   - `WorkflowTemplate/substreams-graph-node-backfill`: a *library* of templates (`backfill` DAG, steps, sidecar).
     Its own entrypoint refuses direct submission (exit 2). It holds no PVC, no mutex, no identity.
   - `WorkflowTemplate/<target-id>-substreams-backfill` (Aerodrome: `aerodrome-slipstream-base-substreams-backfill`):
     a thin wrapper that pins the spec-level settings Argo does **not** inherit through `templateRef` (mutex,
     volumes, node placement, SA, TTL, deadline) and the argument defaults, and calls
     `templateRef: {name: substreams-graph-node-backfill, template: backfill}`.
   - `ConfigMap/substreams-backfill-target-<target-id>-<hash>` carrying `target.json`
     (`pinax.backfill.target/v1`): the reviewed identity pins. The first DAG step refuses any submitted parameter
     that disagrees with it. This replaces V4's in-script constants
     (`K8S/subgraphs-operations/backfill/kan/production-workflow-template.yaml:130-146`) with data.
2. **The segment pipeline belongs to the engine's generic driver; the template wraps it with V4 safety.**
   Per segment: `substreams-native` (clock-v1, bounded `[s, e]`) → family producer (the Aerodrome reducer, BCF1
   BlockChanges out) → `state-replay --input-format block-changes-v1-framed --postgres-spool-output` → generic
   loader into the stopped clone. The template calls the driver through a versioned contract
   (`pinax.backfill.generic-driver/v1`, §4.3) discovered from a manifest inside the engine image.
3. **Cache-hit check = static coverage + a server-enforced budget, no prewarm.** Every segment must lie inside the
   sealed noop-evidence coverage (k8s segment preflight), and every request carries
   `--limit-processed-blocks = cache-miss-tolerance-blocks` (default 10,000). The Pinax Base tier1 counts that budget
   against **uncached** segments only and refuses an over-budget request with `FailedPrecondition` before doing any
   work; the sink treats that code as non-retryable (VERIFIED §2 rows F7–F9). A cold or evicted cache therefore fails
   the segment in seconds with exit 3, instead of silently rebuilding Stores from 13.84M.
4. **The reducer ships as its own image from substreams-backfills, staged into the engine pod.**
   `ghcr.io/pinax-network/substreams-backfills@sha256:<digest>` (tag `<family>-producer-sha-<commit>`) carries
   `/opt/producer/bin/producer`, `runtime.json`, the family contract, BlockChanges descriptor, physical profile and
   the extractor SPKG. An initContainer runs `producer stage --dest /opt/staged-producer` into an `emptyDir`; the
   engine container verifies every hash before exec. The engine image stays family-neutral. Both digests are pinned
   in `target.json` and appear as parameters (the exporter reads `runtime-image-digest`).
5. **Fails closed four independent ways until the engine generic loader and the reducer exist** (§10):
   `target.json.status = "inert"`; placeholder digests refused by the parameter validator (a pinned Python image, so
   no engine pod is ever created); the engine image must expose `/opt/backfill/generic-runtime.json` with driver
   contract v1 and every required capability (no released engine image has it today); the producer runtime must be
   `production_selectable: true` and its family contract must accept that engine contract.
6. **Noop evidence is consumed by value and proven live once** (§7). The noop workflow publishes
   `noop-evidence` + `noop-evidence-sha256` as Argo **global** outputs (`globalName`). The operator passes them as
   parameters. At first binding the preflight re-reads the noop Workflow (Succeeded, matching UID, byte-equal value,
   matching sha) and the prepare-seed step seals a byte-exact copy into the run root. Later resumes need only the
   sealed copy, so Workflow TTL expiry cannot strand a run. Coverage is the union of a contiguous evidence ledger, so
   a later noop can extend the target.
7. **The existing exporter is reused unchanged.** Same `RUN_MODE=production`, same run root
   `/work/production-<schema>-<seed>`, same journal shapes, same template names `production-*`, same
   `app.kubernetes.io/name=substreams-backfill-exporter` label, so the existing Service and `VMServiceScrape` pick it
   up. One optional exporter slice removes the hard-coded `display_name` "Uniswap v4 Base" (§14).
8. **Safety upgrades over V4** (all PROPOSED, each motivated by a VERIFIED gap):
   - writer exclusion probes Graph Node's real advisory-lock keyspace `(1|2|3, site_id)` in `pg_locks`, because the
     V4 `application_name LIKE 'index_node_%'` probe can never fire (engine audit DB-3);
   - parameters reach scripts only through environment variables, never interpolated into script text;
   - `eth_chainId` check, target ≤ RPC `finalized`, `status.replicas == 0` as well as `spec.replicas == 0`;
   - capacity uses the 70 % fill gate from `K8S/docs/pre-wave-capacity-gate.md` §2, plus a work-PVC free-space floor;
   - the pod proves it actually mounts the PVC named by the parameter before the "other live pods" guard trusts it;
   - no `maxDuration` in retry strategies (fullsync lesson, `K8S/subgraphs-operations/fullsync/base/scripts/test_fullsync_workflow_contract.py:9-17`).

---

## 1. Inputs read

- SYNTHESIS §0–§9, `k8s-backfill-stack.md`, `token-api-noop-pattern.md`, `engine-contract.md` (all), and the
  k8s-relevant parts of `aerodrome-target.md`, `v3-lane-state.md`, `v4-substreams-pattern.md`, `substreams-reuse.md`.
- Engine audit `tasks/wathbfgwg.output` `.result.kept[]` (31 findings). Those that shape this template:
  F1 (state-replay commits on clean EOF), F2/F3 (legacy-v1 cancel exits 0), F4 (stream not bound to SPKG digest or
  module hash), BigDecimal 35-digit refusal, DB-1/F2 (`\.` line ends COPY), DB-3 (advisory lock does not exclude
  Graph Node; `application_name` probe dead), DB-6 (NULL head passes seed guard), POI-VID-3 (empty-table max VID 0
  vs −1), GEN-1/POI-VID-1/DB-2 (no generic loader beyond the 1,153-block V3 pilot), GEN-2 (template profiles never
  selectable), GEN-3 (unbounded generic state), GEN-4 (no `subgraph_error`/health writer).
- The V4 production DAG `K8S/subgraphs-operations/backfill/kan/production-workflow-template.yaml` (all 1,062 lines),
  `backfill_exporter.py` (1,726 lines, the parts listed in §14), `exporter.yaml`, `exporter-rbac.yaml`,
  `production-storage.yaml`, `base/rbac.yaml`, `deploy/kan/backfill.yaml`, `.github/workflows/ci.yaml`,
  `subgraphs-metrics/kan/backfill.yaml`, the fullsync template and its contract test.
- Engine drivers `ENG/scripts/run-pipelined-postgres-backfill.sh`, `ENG/scripts/compute-postgres-segment.sh`,
  `ENG/cmd/substreams-native/main.go`, `ENG/src/bin/state-replay.rs` (generic spool manifest),
  `ENG/src/sink.rs:1259-1318`, `ENG/Dockerfile`.
- `SB/.github/workflows/mapping-host-runtime.yml`, `SB/mapping-host/runtime/Dockerfile` (runtime-image precedent).
- Argo v4.0.7 controller source (`ARGO/`), Substreams client v1.18.4 and server commit `5ed941ac91dc`.
- The parallel noop worktree `~/Github/.worktrees/k8s-subgraphs-substreams-noop` (branch
  `claude/substreams-noop-workflow`) has **no commits yet** (VERIFIED `git log`, 2026-10-20), so the noop evidence
  contract in §7 is specified from the consumer side and must be aligned in PR-K1 review.

---

## 2. Facts this design depends on

| # | Fact | Label | Source |
|---|---|---|---|
| F1 | V4 production DAG is preflight → suspend → prepare-seed → load (exporter sidecar) → verify, mutex, dom153, 30 d deadline, `OnWorkflowSuccess` pod GC | VERIFIED | `K8S/…/kan/production-workflow-template.yaml:10-66` |
| F2 | V4 identity is asserted in script: deployment, shard, digest, registry tuple, active source, 8 TiB capacity, segment 100,000, SPKG path | VERIFIED | same file `:130-146, :191-203, :211-223, :812-817` |
| F3 | V4 safety: writer replicas 0 (`:157-161`), stale-lock quarantine with owner regex + no other live pod on the same PVC (`:495-538`), committed-progress-gap reconstruction (`:540-676`), incomplete-compute quarantine (`:678-702`), runtime identity file `cmp` (`:709-730`), per-segment preflight (`:752-802`), no-op resume rerun (`:829-834`), VID audit (`:835`), verify checks 20 sequences and file hygiene (`:1024-1033`), evidence JSON (`:1035-1053`) | VERIFIED | same file |
| F4 | The "other live pod" guard hard-codes `claimName == "substreams-backfill-production-work"` | VERIFIED | same file `:504-505` |
| F5 | Exporter reads workflow parameters by name, overrides first then `storedWorkflowTemplateSpec` defaults | VERIFIED | `backfill_exporter.py:296-314` |
| F6 | Exporter phase comes from active template-name substrings (`production-load` → loading, …) | VERIFIED | `backfill_exporter.py:316-359` |
| F7 | Substreams server counts `limit_processed_blocks` against *effective* blocks, i.e. only segments whose state is still pending or scheduled | VERIFIED | `SS/pipeline/pipeline.go:667`, `SS/orchestrator/stage/stages.go:848-880`, `SS/reqctx/request.go:38-46` (v1.22.0) |
| F8 | Pinax Base tier1 runs `firehose-ethereum v2.24.1`, which pins Substreams `v1.25.1-0.20261019180455-5ed941ac91dc`; that commit has the same effective-block assertion | VERIFIED | `KSS origin/main:chains/base/v2/prod/substreams-tier1/kustomization.yaml:8-9`; `gh api` go.mod; `pipeline/pipeline.go:723`, `orchestrator/stage/stages.go:991-1024` at `5ed941ac91dc` |
| F9 | The sink library treats `FailedPrecondition` ("ex: related to limit-processed-blocks") as non-retryable | VERIFIED | `~/go/pkg/mod/github.com/streamingfast/substreams@v1.18.4/sink/sinker.go:609` |
| F10 | `substreams-native` exposes `--limit-processed-blocks`; the engine driver honours `SUBSTREAMS_LIMIT_PROCESSED_BLOCKS` | VERIFIED | `ENG/cmd/substreams-native/main.go:86-90`; `ENG/scripts/compute-postgres-segment.sh:142,167` |
| F11 | Engine default endpoint `base-substreams-tier1-prod.kan-sst2.pinax.io:443` is dead; the V4 template never sets `ENDPOINT` | VERIFIED (code) / REPORT-VERIFIED (DNS) | `ENG/scripts/compute-postgres-segment.sh:25`; SYNTHESIS §1 C5 |
| F12 | Graph Node v0.44 advisory locks: `(1, id)` copy, `(2, id)` write (session lock, `pg_try_advisory_lock`), `(3, id)` prune | VERIFIED | `GN/store/postgres/src/advisory_lock.rs` (header comment, `COPY`/`WRITE`/`PRUNE` scopes, `lock_deployment_session`) and `deployment.rs:1504-1517` |
| F13 | Argo v4.0.7 substitutes workflow parameters into workflow-level `synchronization` and `volumes`, and into the whole pod spec | VERIFIED | `ARGO/workflow/controller/operator.go:4358, 4510-4530`; `ARGO/workflow/controller/workflowpod.go:380` |
| F14 | Workflow-level `status.outputs.parameters` exist only for output parameters declared with `globalName` | VERIFIED | `ARGO/workflow/controller/operator.go:3666-3679` |
| F15 | Argo escapes substituted values with `strconv.Quote` inside the JSON template, so a JSON-valued parameter arrives byte-exact in an env value, but raw inside script text | VERIFIED | `ARGO/util/template/simple_template.go:69-73` |
| F16 | `argo lint --offline --strict` (v4.0.7) accepts: `templateRef` to another WorkflowTemplate in the same invocation, templated mutex names at workflow and template level, templated `claimName`, `podSpecPatch` with parameters, `asInt(lastRetry.exitCode) in [75, 137, 143]`, template-level `volumes`. It **fails** a dangling `templateRef` when the library is not in the same invocation | VERIFIED (local lint of prototypes in `scratchpad/design/lint-proto/` and `scratchpad/design/kustomize-proto/`) | `argo v4.0.7+9aeb47c` |
| F17 | kustomize v5.8.1 rewrites hashed, `immutable: true`, prune-disabled ConfigMap names inside `spec.volumes` and `spec.templates[].volumes` of WorkflowTemplates, including from a sibling sub-kustomization, when each kustomization root carries a `nameReference` config (the config file must sit inside each root: load restrictor) | VERIFIED (local build) | `scratchpad/design/kustomize-proto/` |
| F18 | Exporter Role grants `workflows get/list/watch` to `substreams-backfill-runner` | VERIFIED | `K8S/…/kan/exporter-rbac.yaml:1-23` |
| F19 | The exporter Service selects `app.kubernetes.io/name: substreams-backfill-exporter` in the namespace and the VMServiceScrape scrapes it | VERIFIED | `K8S/…/kan/exporter.yaml:1-21`; `K8S/subgraphs-metrics/kan/backfill.yaml:1-17` |
| F20 | `backfill-credentials` keys `PINAX_API_KEY`, `SUBSTREAMS_API_TOKEN`, `POSTGRES_PASSWORD`; private image pull via `ghcr-cred`; operator SA cannot read Secrets, so existence is unverified | REPORT-VERIFIED | `k8s-backfill-stack.md` §1.4 |
| F21 | All Graph Node stores use user `graph` with the shared `POSTGRES_PASSWORD` | VERIFIED | `K8S/core/kan/graph-node-config.yaml:22-33, 82-84, 137-139` |
| F22 | dom153: AMD family 25, AVX2 + FMA3 (x86-64-v3 capable), 56 CPU / ~991 GiB allocatable, containerd 1.7.30, labels `infra.pinax.network/compute-tier=fast`, `storage-local-ssd=true`, `storage-vg-nvme01=true` | VERIFIED (`kubectl get/describe node dom153`) | live 2026-10-20 |
| F23 | dom153 currently has 22.83 CPU and 186 GiB memory requested by Running/Pending pods | VERIFIED (VictoriaMetrics) | `kube_pod_container_resource_requests{node="dom153"}` |
| F24 | Base: `latest` 52,869,158, `finalized` 52,868,710 (448 blocks ≈ 15 min behind), `eth_chainId` 0x2105 = 8453 | VERIFIED (public RPC probe) | `https://mainnet.base.org`, 2026-10-20 |
| F25 | NPM at block 34,701,056: `totalSupply()` 1,178,303 outstanding; `tokenByIndex(last)` returns token id 23,619,224, so up to ~23.6M positions minted by the seed | VERIFIED (public RPC `eth_call`) | NPM `0x8279…5b72` |
| F26 | Generic spool manifest: format `pinax.graph-node.block-changes-copy-spool`, versions 1/2, carries descriptor sha, profile sha + `production_selectable`, heads, `totals.deterministic_errors`, `removes_committed`, `completeness.faithful`, `producer{source_commit,image_digest,state_replay_sha256,substreams_native_sha256?,spkg_sha256,spkg_module?,compatibility_contract_sha256}` | VERIFIED | `ENG/src/bin/state-replay.rs:2753-2830`; `ENG/src/sink.rs:1259-1318` |
| F27 | Index-node parked for V4 (`index_node_basegiant_0`) **is** in `INDEXER_AGENT_INDEX_NODE_IDS`; V4 relied on zero replicas only | VERIFIED | `K8S/subgraphs-indexers/pinax2/kan/kustomization.yaml:88` |
| F28 | The engine image tooling (`bash curl jq postgresql-client kubectl`) and bookworm base | VERIFIED | `ENG/Dockerfile:582-609` |
| F29 | mapping-host runtime precedent: image `ghcr.io/pinax-network/substreams-backfills:mapping-host-sha-<commit>`, bookworm, `runtime.json` + `source.json`, ORAS-attached archive, `production_selectable:false` | VERIFIED | `SB/.github/workflows/mapping-host-runtime.yml`; `SB/mapping-host/runtime/Dockerfile` |

---

## 3. Layout

### 3.1 File tree (new tree shared with PR-K1)

```
subgraphs-operations/backfill-substreams/
  README.md                                    # K1 creates; K2-1 adds the backfill section
  base/
    kustomization.yaml                         # K1 creates; K2-1 adds the resources below
    kustomizeconfig.yaml                       # nameReference for WorkflowTemplate ConfigMap volumes (§3.3)
    substreams-noop-workflow-template.yaml     # K1 (not this design)
    graph-node-backfill-workflow-template.yaml # K2-1: WorkflowTemplate substreams-graph-node-backfill (library)
    graph-node-backfill-rbac.yaml              # K2-1: SA + Role + RoleBinding in subgraphs-backfill
    lib/
      backfill-lib.sh                          # K2-1: bash library sourced by every engine-image step
      segment-preflight.sh                     # K2-1: BACKFILL_SEGMENT_PREFLIGHT_BIN (sources backfill-lib.sh)
      validate_params.py                       # K2-1: stdlib-only validator (pinned python image)
      noop_evidence.py                         # K2-1: stdlib-only evidence parser + coverage ledger
  kan/
    kustomization.yaml                         # K1 creates; K2-2 adds targets/aerodrome-slipstream-base
    kustomizeconfig.yaml                       # same nameReference config (load restrictor needs a copy per root)
    targets/
      aerodrome-slipstream-base/
        kustomization.yaml                     # configMapGenerator for target.json (hashed, immutable, prune disabled)
        target.json                            # pinax.backfill.target/v1, status "inert" until activation
        backfill-workflow-template.yaml        # WorkflowTemplate aerodrome-slipstream-base-substreams-backfill
        work-pvc.yaml                          # PVC substreams-backfill-aerodrome-slipstream-base-work (prune disabled)
        writers-rbac.yaml                      # Role/RoleBinding in `subgraphs`: deployments get on the writer names
  examples/                                    # NOT in Flux (repo convention, k8s-backfill-stack §4.3)
    submit-aerodrome-slipstream-base-backfill.yaml
  tests/
    test_backfill_contract.py                  # rendered-overlay contract (JSON from yq)
    test_validate_params.py
    test_noop_evidence.py
    test-backfill-lib.sh                       # bash unit tests with PATH stubs
    stubs/{kubectl,psql,curl,df}               # scenario-driven fakes
    fixtures/…                                 # named in §18.2
```

Flux: PR-K1 adds `deploy/kan/backfill-substreams.yaml` (Kustomization on `subgraphs-operations/backfill-substreams/kan`,
`dependsOn: subgraphs-backfill`, `prune: true`, `wait: false`) per SYNTHESIS §5 PR-K1. The backfill slices only add
resources under that path, so no new Flux object is needed. `wait: false` matters because the work PVC is
`WaitForFirstConsumer` and stays Pending until the first pod (same reason as `K8S/deploy/kan/backfill.yaml:17-19`).

Why not `backfill/kan`: its contract test counts strings over the whole rendered overlay and pins RBAC strings
(SYNTHESIS §1 C6, VERIFIED there). Nothing in this design edits `subgraphs-operations/backfill/**` except the optional
exporter slice K2-3.

### 3.2 How the three objects compose (PROPOSED)

```
argo submit --from workflowtemplate/aerodrome-slipstream-base-substreams-backfill -p … (run-specific only)
   │  wrapper spec: SA, mutex (fixed name), dom153+AVX2 nodeSelector, volumes {work PVC, target CM,
   │  exporter CM, producer emptyDir}, 30 d deadline, TTL, podGC, argument defaults == target.json
   └─ steps: [[ templateRef substreams-graph-node-backfill/backfill ]]
          library DAG (template names chosen for the exporter's phase map, F6):
          production-preflight-parameters → production-preflight → production-approval (suspend)
            → production-prepare-seed → production-load (+exporter sidecar) → production-verify
          outputs.parameters: production-evidence (globalName)
```

`templateRef` does not carry spec-level fields of the referenced template into the run, which is why the wrapper owns
them. The library's templates declare their own lib ConfigMap volume at template level so the library stays
self-contained (F16, F17).

### 3.3 kustomize config (identical copy in `base/` and `kan/`)

```yaml
# kustomizeconfig.yaml
nameReference:
  - kind: ConfigMap
    version: v1
    fieldSpecs:
      - { group: argoproj.io, kind: WorkflowTemplate, path: spec/volumes/configMap/name }
      - { group: argoproj.io, kind: WorkflowTemplate, path: spec/templates/volumes/configMap/name }
```

Generated ConfigMaps (`substreams-graph-node-backfill-lib`, `substreams-backfill-target-<id>`) use
`options: {immutable: true, annotations: {kustomize.toolkit.fluxcd.io/prune: disabled}}` and keep the hash suffix
(F17). Effect: a running Workflow's stored spec keeps pointing at the exact script and target versions it started
with; a GitOps merge mid-run creates new objects and never mutates or prunes the old ones. Old versions accumulate
(a few KB each); the README documents a manual cleanup of names not referenced by any retained Workflow.

The exporter is the one exception: the wrapper mounts the existing unhashed `ConfigMap/substreams-backfill-exporter`
owned by `subgraphs-backfill` (`K8S/…/kan/kustomization.yaml:20-24`), so V4 and generic lanes share one metrics
contract and its hot-reload behaviour (`backfill_exporter.py:1239-1260`).

---

## 4. Segment pipeline, ownership, run root

### 4.1 Data flow per segment `[s, e]` (s = previous head + 1)

```
substreams-native  -e $ENDPOINT  $SPKG  $MODULE  -s s  -t e+1
    -H "X-Substreams-Parallel-Workers: $N"  -H "X-substreams-acknowledge-non-deterministic: true"
    --output-format clock-v1 --include-empty-frames
    --limit-processed-blocks $CACHE_MISS_TOLERANCE_BLOCKS            # server-side cache tripwire (F7-F9)
 │ stdout: clock-v1 frames of extractor output (raw map bytes)
 ▼
env -i PATH=… /opt/staged-producer/bin/producer reduce              # scrubbed env: no tokens, no PG password
    --state-in  <prev producer state>  --state-out <seg>.building/producer-state.pending
    --expected-head-block s-1 --expected-head-hash H(s-1) --head-block e --head-hash H(e)
    --family-contract /opt/staged-producer/contract/compatibility.json
 │ stdout: BCF1 clock-v1 frames, one non-empty canonical BlockChanges per block
 │ (data-source companion written where the engine's D3 data_sources$ stream expects it)
 ▼
state-replay --input-format block-changes-v1-framed --native-frame-format clock-v1
    --block-changes-descriptor D --physical-profile P --input-generic-checkpoint C(s-1)
    --postgres-spool-output <seg>.ready --expected-head-block s-1 --expected-head-hash H(s-1)
    --head-block e --head-hash H(e)  [+ D3 data-source stream flags]
 ▼
generic loader (engine D3) → one atomic transaction into the stopped clone sgdN; head → (e, H(e))
```

Ownership:

| Piece | Owner | Notes |
|---|---|---|
| The three-stage pipe, look-ahead overlap, checkpoint/producer-state chaining, spool sealing, loader, committed-gap reconciliation, journal | engine generic driver (D3) | contract §4.3 |
| Reducer semantics, BCF1 output, producer state format, `stage`/`seed`/`reduce` subcommands | substreams-backfills family producer | contract §9.3 |
| Identity pins, writer exclusion, registry, capacity, noop coverage, stale-lock and incomplete-artifact quarantine, runtime-identity file, approval, evidence | this template | §8 |

The V4 template does crash reconciliation in bash because the V4 driver lacked it (`:540-676`). The generic driver
must own it (it alone knows its receipt format); the template keeps the two layout-only guards (stale lock and
`.building` quarantine) that need nothing but names.

### 4.2 Run root (exporter-compatible, F5/F6)

```
/work/production-<target-schema>-<expected-seed-block>/         # = exporter run_root (backfill_exporter.py:1406)
  run-contract.json                    # template; immutable binding (§15.3)
  run-contract-amendments.jsonl        # template; append-only, each with approval-reference
  seed-contract.json                   # template; V4-compatible subset {deployment,target_shard,target_schema,seed_block,seed_hash}
  noop-evidence/<sha256>.json          # template; byte-exact sealed evidence ledger (§7)
  noop-evidence/<sha256>.proof.json    # template; trimmed live Workflow proof at bind time
  seed/                                # engine seed capture + producer seed (prepare-seed)
    seed-capture.json                  #   engine report (§8.4)
    <engine checkpoint artefact>(+.sha256)
    producer-state-<B>.bin(+.sha256)
  runtime/
    runtime-identity-<engine12>-<producer12>.txt   # template; sha256sum list, compared on every load attempt
    runtime-history.jsonl              # template; one line per attempt: lib CM name/sha, pod, node
  postgres-pipeline-progress.jsonl     # engine; exporter progress journal (§14.3)
  driver-events.jsonl                  # template tee of driver stderr; exporter phase events
  driver-output.jsonl                  # template tee of driver stdout; exporter row totals
  driver-resume-gate.json              # template; output of the no-op resume rerun (renamed from V4 driver-noop.json, SYNTHESIS §6.3)
  sequence-audit.json, error-audit.json, production-evidence.json
  quarantine/…                         # template moves, never deletes
  .postgres-pipeline.lock/owner        # engine; "pid=<n> schema=<sgdN> target=<T>"
  spools/segment-<a>-<b>.{building,ready}   # engine
  checkpoints/…  producer/…            # engine-owned layout
```

### 4.3 Engine driver contract `pinax.backfill.generic-driver/v1` (CONSUMED; PROPOSED for engine Phase 2)

Discovered from `/opt/backfill/generic-runtime.json` (§9.2). Entrypoints are argv arrays so the engine may ship one
binary with subcommands or several binaries.

`entrypoints.pipelined_backfill` (the `load` step) — arguments:

```
--deployment Qm… --schema sgdN --network base --chain-id 8453
--seed-dir <run_root>/seed --seed-block B --seed-hash H --target-block T --target-hash TH
--run-root <run_root> --segment-size S
--producer-dir /opt/staged-producer --family-contract /opt/staged-producer/contract/compatibility.json
--endpoint <host:443> --parallel-workers N --cache-miss-tolerance-blocks K
--segment-preflight <path> --landing stopped-clone|none
```

Environment it may read: `SUBSTREAMS_API_TOKEN`, `PG{HOST,USER,DATABASE,PASSWORD}`, `CHAIN_RPC_URL`,
`GRAPH_NODE_WRITER_STOPPED=1`, `BACKFILL_RUNTIME_IMAGE_DIGEST`, `BACKFILL_POI_WORKERS`, `BACKFILL_POI_BATCH_SIZE`,
`BACKFILL_ROLLING_RETENTION=1`. It must exec the producer with a scrubbed environment.

Obligations the template relies on:

1. **Journal.** One line per committed segment to `postgres-pipeline-progress.jsonl`:
   `{status:"committed", schema, start_block, end_block, end_hash, artifact, checkpoint, compute_seconds≥1,
   compute_reused, load_seconds≥1, load_started_epoch, load_finished_epoch, rolling_retention, lookahead:{…}}`
   with `load_finished_epoch − load_started_epoch == load_seconds` and strictly increasing finishes
   (`backfill_exporter.py:465-532` raises otherwise). `compute_seconds` must be clamped to ≥ 1 even when a ready
   artefact is reused.
2. **Phase events** on stderr, one JSON object per line:
   `{event:"backfill_phase", phase ∈ {checkpoint_load, builder_initialization, stream_reduce_spool, poi_drain,
   checkpoint_write, postgres_copy_commit, finalize}, schema (or "unbound"), target_head_block, target_head_hash,
   elapsed_milliseconds, …}`; `finalize` carries `total_elapsed_milliseconds>0` and `input_format`;
   `stream_reduce_spool` carries `input_frames`, `input_payload_bytes`; `postgres_copy_commit` carries
   `inserted_rows`, `clamped_rows`, `new_entities` (`backfill_exporter.py:876-969`). Extra events
   (`backfill_producer`, `backfill_cache_check`) are allowed and ignored by the exporter.
3. **Stdout summaries**: per load `{pipeline:"postgres-copy", head_block, inserted_rows, clamped_rows, new_entities}`
   (row totals, `:1157-1172`); a final `{status:"complete", pipeline:"block-changes-copy-spool", schema, head_block,
   head_hash, checkpoint:{sha256,bytes}, poi:{region,digest}, data_sources:{rows,max_creation_block},
   deterministic_errors, segments}`. A rerun at the target prints the same `complete` object without writing
   (the no-op resume gate).
4. **Layout names** used by template guards: lock dir `.postgres-pipeline.lock/owner` with exactly
   `pid=<n> schema=<sgdN> target=<T>`; in-progress compute `spools/segment-<s>-<e>.building`; sealed
   `spools/segment-<s>-<e>.ready` holding the F26 manifest plus new provenance fields
   `producer.family_producer_sha256`, `producer.family_contract_sha256`, `producer.module_hash`,
   `producer.substreams_native_sha256` (closes audit F4 and the `copy_spool_producer(false,false)` gap).
5. **Segment preflight hook**: before every atomic load, exec
   `<segment-preflight> <schema> <expected_block> <expected_hash> <target_block> <target_hash> <artifact>` (the V4
   argument contract, `ENG/scripts/run-pipelined-postgres-backfill.sh:170-175`); non-zero aborts with that code.
6. **Exit codes** (§15.1): 0, 2, 3, 4, 5, 75. Cache-budget refusal (`FailedPrecondition` mentioning
   `limit-processed-blocks`) → 3. Never exit 0 on a short stream (audit F1/F2; clock-v1 range completion).
7. **Recovery**: on start it reconciles a database head that is exactly one segment ahead of the journal from its
   own sealed receipt, or exits 5. It never trusts an unsealed artefact.

Other entrypoints: `seed_capture` (§8.4), `audit_sequences` (profile-driven; JSON lines
`{table, sequence, max_vid, last_value, is_called, ok}`), `verify_run` (`{status, head_block, head_hash,
checkpoint{sha256,bytes}, journal_contiguous, files_clean, poi{…}, data_sources{…}}`).

---

## 5. Parameters

Rules: every parameter reaches scripts as an environment variable `BF_<UPPER_SNAKE>` (F15). "Pinned" means the
validator requires equality with `target.json`; "run" means operator-supplied per submission within bounds.
"Exporter" marks names the exporter reads (§14.1) and that therefore must not be renamed.

| Parameter | Kind | Exporter | Validation | Aerodrome value |
|---|---|---|---|---|
| `target-id` | pinned | | `^[a-z0-9]([a-z0-9-]{0,48}[a-z0-9])?$` | `aerodrome-slipstream-base` |
| `family` | pinned | | same regex; == producer `runtime.json.family` | `aerodrome-slipstream-base` |
| `deployment` | pinned | yes (label, lane key) | `^Qm[1-9A-HJ-NP-Za-km-z]{44}$` | `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` |
| `network` | pinned | | `^[a-z0-9-]+$` | `base` |
| `chain-id` | pinned | | int; == `eth_chainId` | `8453` |
| `rpc-url-template` | pinned | | `^https://[a-z0-9.-]+/v1/\$\{PINAX_API_KEY\}/$` | `https://base.rpc.pinax.network/v1/${PINAX_API_KEY}/` |
| `substreams-endpoint` | pinned, no default in library | | `^<network>\.substreams\.(kan\|riv)-prod-firehose-a\.pinax\.io:443$` | `base.substreams.kan-prod-firehose-a.pinax.io:443` |
| `substreams-parallel-workers` | run | yes (label) | 1 ≤ n ≤ `target.substreams.parallel_workers_max` | `64` |
| `cache-miss-tolerance-blocks` | pinned | | 1,000 ≤ k ≤ 100,000 | `10000` |
| `target-shard` | pinned | yes | `^[a-z0-9_]+$` | `aerodrome_b` |
| `target-postgres-host` | pinned | | `^[a-z0-9-]+-0\.[a-z0-9-]+\.subgraphs\.svc\.cluster\.local$` | `aerodrome-backfill-postgres-0.aerodrome-backfill-postgres.subgraphs.svc.cluster.local` |
| `primary-postgres-host` | pinned | | same form | `postgres-0.postgres.subgraphs.svc.cluster.local` |
| `parked-node-id` | pinned | | `^index_node_[a-z0-9_]+$` | `index_node_aerodrome_backfill_0` |
| `writer-deployments` | pinned | | space list of `^graph-node-[a-z0-9-]+$` | `graph-node-aerodrome-backfill-0` |
| `active-source-shard` / `active-source-schema` | pinned | | shard regex / `^sgd[0-9]+$` | `subgraphshard_b` / `sgd2` |
| `target-schema` | run | yes | `^sgd[0-9]+$`, ≠ active source schema | set after graphman copy |
| `expected-seed-block` | run | yes (seed, run root) | positive int | copy head (~34.7M) |
| `expected-seed-hash` | run | | 64 hex | from `subgraphs.head` |
| `target-block` | run | yes | int > seed, ≤ RPC `finalized`, ≤ noop coverage stop − 1 | fixed finalized target |
| `target-hash` | run | | 64 hex, == RPC | |
| `segment-size` | pinned | yes | ∈ {10000, 25000, 50000, 100000} | `50000` (ESTIMATE §12.3) |
| `runtime-image-digest` | pinned | yes (label `runtime_digest`) | 64 hex; image is `ghcr.io/pinax-network/substreams-graph-node-backfill@sha256:{{…}}` | engine Phase 2 release |
| `engine-runtime-sha256` | pinned | | 64 hex == sha256 of `/opt/backfill/generic-runtime.json` | |
| `producer-image-digest` | pinned | | 64 hex; image `ghcr.io/pinax-network/substreams-backfills@sha256:{{…}}` | |
| `producer-runtime-sha256` | pinned | | 64 hex == sha256 of staged `runtime.json` | |
| `family-contract-sha256` | pinned | | 64 hex == sha256 of staged contract | |
| `noop-workflow` | run | | `^[a-z0-9][a-z0-9.-]{0,252}$` | name of the Succeeded noop Workflow |
| `noop-evidence` | run | | JSON (§7.2), ≤ 16 KiB | copied verbatim from the noop's global output |
| `noop-evidence-sha256` | run | | 64 hex | copied from the noop's global output |
| `target-capacity-bytes` / `target-max-pg-bytes` / `target-reserve-bytes` | pinned | | capacity − max == reserve; max ≤ 0.70 × capacity | after landing approval |
| `segment-growth-allowance-bytes` | pinned | | > 0 | first-segment headroom |
| `work-pvc` | pinned | | == wrapper `claimName` and == the pod's own mount (§8.2) | `substreams-backfill-aerodrome-slipstream-base-work` |
| `work-min-free-bytes` | pinned | | > 0 | `161061273600` (150 GiB) |
| `load-cpu-request` / `load-cpu-limit` / `load-memory-request` / `load-memory-limit` | run, bounded by target | | k8s quantity; within `target.resources.load.max_*` | 8 / 16 / 128Gi / 384Gi |
| `poi-workers` / `poi-batch-size` | run | yes (labels) | 1–64 / 1–64 | 16 / 16 |
| `compatibility-profile` | pinned | yes (label) | must be `graph-node-exact` (the V4 NUL-truncation profile does not apply to the generic path) | `graph-node-exact` |
| `approval-reference` | run | | `^[A-Za-z0-9#:/._-]{3,128}$`, not a placeholder | issue/PR reference |
| `amend-run-contract` | run | | `none` or an approval reference | `none` |
| `landing` | pinned per entry template | | `stopped-clone` (backfill) / `none` (oracle-window, §17) | `stopped-clone` |

Removed from the SYNTHESIS §6.2 list, with reasons:

- `cache-last-block`: derived from the sealed noop-evidence ledger (one source of truth). The old gate
  `target_block ≤ cache_last` (`production-workflow-template.yaml:143`) becomes `target_block + 1 ≤ coverage.stop`.
- `adapter`, `spkg`, `module`, `input-mode`: folded into the family contract pinned by `family-contract-sha256`.
  The input mode is fixed to `block-changes-v1-framed`.
- `expected-registry`: derived as `<target-shard>|f|<parked-node-id>|t` (V4 also accepts the `false`/`true`
  spelling, `:197-198`), so it cannot disagree with its parts.
- `seed-mode`: implied by the entry template (`backfill` = checkpoint seed from the stopped clone; `oracle-window` =
  root, §17).

---

## 6. `target.json` (`pinax.backfill.target/v1`, PROPOSED)

Full field list (all required unless marked optional):

```json
{
  "schema": "pinax.backfill.target/v1",
  "status": "inert",
  "inert_reasons": ["engine generic driver v1 unreleased", "producer image unreleased",
                    "landing store aerodrome_b not approved (D6)", "graphman copy not taken"],
  "target_id": "aerodrome-slipstream-base",
  "family": "aerodrome-slipstream-base",
  "display_name": "Aerodrome Slipstream CL Base",
  "deployment": "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",
  "network": "base",
  "chain_id": 8453,
  "rpc_url_template": "https://base.rpc.pinax.network/v1/${PINAX_API_KEY}/",
  "substreams": {
    "endpoint": "base.substreams.kan-prod-firehose-a.pinax.io:443",
    "cache_endpoint_equivalence": "shared-state-store",
    "equivalent_endpoints": ["base.substreams.kan-prod-firehose-a.pinax.io:443",
                             "base.substreams.riv-prod-firehose-a.pinax.io:443"],
    "parallel_workers_max": 200,
    "cache_miss_tolerance_blocks": 10000,
    "noop_templates": ["substreams-noop", "aerodrome-slipstream-base-substreams-noop"]
  },
  "landing": {
    "mode": "stopped-clone",
    "target_shard": "aerodrome_b",
    "target_postgres_host": "aerodrome-backfill-postgres-0.aerodrome-backfill-postgres.subgraphs.svc.cluster.local",
    "primary_postgres_host": "postgres-0.postgres.subgraphs.svc.cluster.local",
    "parked_node_id": "index_node_aerodrome_backfill_0",
    "writer_deployments": ["graph-node-aerodrome-backfill-0"],
    "active_source": {"shard": "subgraphshard_b", "schema": "sgd2"},
    "graft": null,
    "capacity": {"capacity_bytes": "replace-after-landing-approval",
                 "max_pg_bytes": "replace-after-landing-approval",
                 "reserve_bytes": "replace-after-landing-approval",
                 "fill_gate_ratio": 0.70,
                 "segment_growth_allowance_bytes": "replace-after-first-measurement"},
    "allow_non_fatal_errors": false
  },
  "runtime": {
    "engine_image": "ghcr.io/pinax-network/substreams-graph-node-backfill",
    "engine_image_digest": "replace-with-engine-generic-runtime-digest",
    "engine_runtime_sha256": "replace-with-64-hex",
    "producer_image": "ghcr.io/pinax-network/substreams-backfills",
    "producer_image_digest": "replace-with-producer-digest",
    "producer_runtime_sha256": "replace-with-64-hex",
    "family_contract_sha256": "replace-with-64-hex"
  },
  "work": {"pvc": "substreams-backfill-aerodrome-slipstream-base-work", "node": "dom153",
           "min_free_bytes": 161061273600},
  "segment_size": 50000,
  "resources": {
    "load": {"cpu_request": "8", "cpu_limit": "16", "memory_request": "128Gi", "memory_limit": "384Gi",
             "max_memory_limit": "640Gi", "max_cpu_limit": "24"},
    "seed": {"cpu_request": "4", "cpu_limit": "16", "memory_request": "32Gi", "memory_limit": "256Gi"}
  },
  "workflow": {"wrapper_template": "aerodrome-slipstream-base-substreams-backfill",
               "mutex": "substreams-graph-node-backfill-aerodrome-slipstream-base"}
}
```

Landing values are the SYNTHESIS §5 Phase-3 proposal (`aerodrome_b` on dom153, parking worker
`graph-node-aerodrome-backfill-0` / `index_node_aerodrome_backfill_0`, active source `subgraphshard_b/sgd2`); they
are ASSUMED until the core/kan landing PR exists. `status` flips to `"active"` only in the activation slice K2-6.

---

## 7. Noop evidence: contract and consumption

### 7.1 What the noop workflow must publish (CONSUMED; to align in PR-K1)

- The run template declares output parameters with `globalName` so they reach `.status.outputs.parameters` (F14),
  following the fullsync precedent `globalName: fullsync-evidence`
  (`K8S/subgraphs-operations/fullsync/base/workflow-template.yaml:129`):
  - `noop-evidence`: the canonical evidence bytes, i.e. `jq -cS .` output with no trailing newline;
  - `noop-evidence-sha256`: lowercase hex sha256 of exactly those bytes.
- The Workflow carries label `workflows.argoproj.io/workflow-template=<noop template>` (set by Argo on
  `submit --from`) with a value listed in `target.substreams.noop_templates`.

### 7.2 Evidence schema `pinax.substreams-noop.evidence/v1` (PROPOSED field list; extra fields allowed)

| Field | Type | Rule enforced by the backfill |
|---|---|---|
| `schema` | string | == `pinax.substreams-noop.evidence/v1` |
| `status` | string | == `complete` (stream reached `range.stop_block`) |
| `workflow.{namespace,name,uid,template}` | strings | `namespace == subgraphs-backfill`; `name == noop-workflow`; `uid` == live `.metadata.uid` at bind time |
| `target_id`, `deployment`, `network` | strings | equal the target |
| `endpoint` | string | equal `substreams-endpoint`, or both in `equivalent_endpoints` when equivalence is `shared-state-store` (both prod tier1s write one Ceph state bucket, SYNTHESIS §1 C5) |
| `spkg.{url,sha256,bytes}` | | `sha256` == family contract `extractor.spkg_sha256` |
| `module` | string | == family contract `extractor.module` |
| `module_hash` | string or null | == contract `extractor.module_hash`; null accepted only when `params == []` (hash is then a pure function of the SPKG bytes and module) |
| `output_type` | string or null | when present, == contract |
| `params` | list | == contract `extractor.params` (module hashes include param values, `engine-contract.md` §2.3) |
| `initial_block` | int | == contract `extractor.initial_block` (13,843,704) |
| `range.{start_block,stop_block}` | ints | `[start, stop)`; stop finalized at noop time |
| `mode.{production,noop}` | bools | both true (development mode writes no execout cache, `token-api-noop-pattern.md` §1.4) |
| `client.{image,tool,version}` | strings | recorded only |
| `parallel_workers`, `headers`, `started_at`, `finished_at`, `elapsed_seconds` | | recorded only |

### 7.3 Consumption algorithm (PROPOSED; `lib/noop_evidence.py`, stdlib only)

Inputs: `BF_NOOP_WORKFLOW`, `BF_NOOP_EVIDENCE` (env, byte-exact by F15), `BF_NOOP_EVIDENCE_SHA256`, the family
contract, `target.json`, the run root (may not exist), seed and target blocks.

1. `sha256(BF_NOOP_EVIDENCE.encode()) == BF_NOOP_EVIDENCE_SHA256`, else exit 2.
2. Parse; require `json.dumps(obj, sort_keys=True, separators=(",",":")) == BF_NOOP_EVIDENCE` (canonical form),
   else exit 2. Apply every rule of §7.2, else exit 2 (`identity`) or 3 (`coverage`).
3. Ledger: `L = {sealed evidences in <run_root>/noop-evidence/*.json}` (empty before prepare-seed). Each sealed file
   must still hash to its file name; all members must agree on the identity fields of §7.2.
4. **Live proof**, required when the submitted sha is not already in `L`:
   `kubectl -n subgraphs-backfill get workflow "$BF_NOOP_WORKFLOW" -o json`, then require
   `.status.phase == "Succeeded"`, `.metadata.uid == evidence.workflow.uid`, the template label in the allow-list,
   and `.status.outputs.parameters[] | select(.name=="noop-evidence") | .value` byte-equal to `BF_NOOP_EVIDENCE` and
   the `noop-evidence-sha256` output equal to the parameter. Fallback when the global output is absent: exactly one
   Succeeded node whose `outputs.parameters` holds `noop-evidence`. Write the trimmed proof
   `{name, uid, creationTimestamp, finishedAt, phase, template, evidence_sha256}`. A missing Workflow here exits 2
   with "noop workflow not found; it must exist when its evidence is first bound".
5. Coverage: merge `L ∪ {submitted}` ranges; they must form one contiguous interval `[C0, C1)` (touching or
   overlapping). Require `C0 ≤ seed_block + 1` and `target_block + 1 ≤ C1`, else exit 3.
6. Binding: `production-prepare-seed` (after approval) writes `noop-evidence/<sha>.json` (bytes),
   `<sha>.proof.json`, and, at first run, `run-contract.json` with `noop_evidence: [<sha>]`. Later runs append new
   shas through `run-contract-amendments.jsonl` (an extension is an amendment with its own approval reference).
7. Every segment preflight re-reads only the sealed ledger (no API call) and checks `[expected+1, target] ⊆ [C0, C1)`.

Why by value plus one live proof: Argo has no artifact repository on Kan (`k8s-backfill-stack.md` §3.1), the runner
SA cannot create ConfigMaps, and noop Workflows expire by TTL. The value is self-certifying by sha, the live proof
binds it to a real Succeeded Workflow in the namespace once, and the sealed copy makes later resumes independent of
TTL. The riv-dev1 `token-noop` stopgap (`token-api-noop-pattern.md` §3) produces no such evidence and is therefore
not accepted; it may still warm the cache, which the dynamic tripwire (§4.1) would then confirm.

Operator command (example, documented in the README):

```sh
ev=$(kubectl -n subgraphs-backfill get wf "$NOOP" -o json | jq -r '.status.outputs.parameters[]|select(.name=="noop-evidence").value')
sha=$(kubectl -n subgraphs-backfill get wf "$NOOP" -o json | jq -r '.status.outputs.parameters[]|select(.name=="noop-evidence-sha256").value')
argo -n subgraphs-backfill submit --from workflowtemplate/aerodrome-slipstream-base-substreams-backfill \
  -p noop-workflow="$NOOP" -p noop-evidence="$ev" -p noop-evidence-sha256="$sha" -p target-schema=sgdNNNN …
```

---

## 8. DAG and step specifications

### 8.1 `production-preflight-parameters` (pinned Python image, no secrets, no network)

- Image `python:3.13.5-alpine3.22@sha256:f1a962d8ffa50b2006b72b4713a09a89e57def2d28ac28a36900bc070a00db61`
  (already digest-pinned in `K8S/…/kan/compute-only-workflow-template.yaml:520`).
- Runs `python3 -B /backfill-lib/validate_params.py --target /target/target.json --out /tmp/validated.json`.
- Checks: every regex of §5; pinned parameters equal `target.json`; `target.json.status == "active"` (else exit 2
  listing `inert_reasons`); no value contains `replace`/`placeholder`; resource quantities within target maxima;
  `noop_evidence.py --parse-only` (steps 1–2 of §7.3).
- `activeDeadlineSeconds: 300`; no retries. Output parameter `validated` (the JSON).
- Purpose: an inert or mistyped submission fails here with exit 2, before any engine or producer image is pulled.

### 8.2 `production-preflight` (engine image, producer staged; no retries; `activeDeadlineSeconds: 3600`)

```
initContainer stage-producer: image ghcr.io/pinax-network/substreams-backfills@sha256:$producer_digest
    command [/opt/producer/bin/producer, stage, --dest, /opt/staged-producer]
main (engine image @sha256:$runtime_digest):
  source /backfill-lib/backfill-lib.sh
  bf_verify_engine_runtime        # §9.2 manifest, capabilities, binary sha256s, tools; exit 2 if absent
  bf_verify_producer_runtime      # §9.3 runtime.json sha, file hashes, `producer version --json`, family contract
  bf_verify_self_placement        # NODE_NAME == target.work.node; own pod mounts claim $BF_WORK_PVC at /work
  bf_verify_chain                 # eth_chainId; target ≤ finalized; target hash == RPC
  bf_verify_noop_evidence         # §7.3 steps 1-5 (live proof if not yet sealed)
  bf_verify_writer_exclusion      # §8.6
  bf_verify_target_identity       # deployment, health, failed, graft NULL, head in [seed,target], head hash == RPC
  bf_verify_registry              # derived tuple; exactly one active source row
  bf_verify_capacity              # §12.2
  bf_verify_resume_consistency    # run-contract equality or (no run root and head == seed)
  emit /tmp/preflight.json        # output parameter, shown at the approval suspend
```

### 8.3 `production-approval`

`suspend: {}` (no duration). The operator inspects `argo get` (preflight.json) and runs `argo resume`.

### 8.4 `production-prepare-seed` (engine image, producer staged; retries 3, `Always`, expression as §15.2)

1. Re-run writer exclusion, registry and target identity; require head == seed block and hash.
2. Create the run root; write `run-contract.json` and `seed-contract.json` atomically (`.pending` + `mv`);
   seal the noop evidence (§7.3 step 6).
3. If `seed/seed-capture.json` exists, verify every sealed sha and skip. Otherwise run
   `entrypoints.seed_capture --schema $S --deployment $D --seed-block $B --seed-hash $H --profile P --descriptor D
   --out-dir <run_root>/seed` with `PGOPTIONS='-c default_transaction_read_only=on'`. Required report fields:
   `{format, block, hash, tables:{<table>:{active_rows,max_vid}}, poi:{digest,vid}, data_sources:{rows,max_vid},
   checkpoint:{path,sha256,bytes}, producer_export:{path,format,sha256}}`. Empty tables must report
   `max_vid = -1` (audit POI-VID-3).
4. `producer seed --from <producer_export.path> --out seed/producer-state-$B.bin` (scrubbed env); seal sha.
5. Re-check head == seed (no writer moved it during capture) and writer exclusion.

### 8.5 `production-load` (engine image + producer staged + exporter sidecar; retries §15.2)

```
labels: app.kubernetes.io/name=substreams-backfill-exporter, …/component=exporter, …/part-of=subgraphs-backfill
podSpecPatch: '{"containers":[{"name":"main","resources":{"requests":{"cpu":"{{workflow.parameters.load-cpu-request}}","memory":"{{workflow.parameters.load-memory-request}}"},"limits":{"cpu":"{{workflow.parameters.load-cpu-limit}}","memory":"{{workflow.parameters.load-memory-limit}}"}}}]}'
main:
  bf_verify_engine_runtime; bf_verify_producer_runtime; bf_verify_self_placement
  bf_verify_run_contract                       # §15.3 (amendments only with amend-run-contract)
  bf_write_runtime_identity                    # sha256sum of engine bins, generic-runtime.json, staged producer
                                               # files, lib files → runtime/runtime-identity-<e12>-<p12>.txt;
                                               # cmp with an existing file of the same name; append runtime-history.jsonl
  bf_verify_writer_exclusion; bf_verify_registry; bf_verify_capacity
  bf_recover_stale_pipeline_lock               # V4 :509-538 semantics, PVC from $BF_WORK_PVC
  bf_quarantine_incomplete_compute_artifact    # V4 :678-702 semantics
  export GRAPH_NODE_WRITER_STOPPED=1 CHAIN_RPC_URL=… BACKFILL_RUNTIME_IMAGE_DIGEST=sha256:$digest …
  entrypoints.pipelined_backfill <args §4.3> 2> >(tee -a driver-events.jsonl >&2) | tee -a driver-output.jsonl
  bf_verify_writer_exclusion
  entrypoints.pipelined_backfill <same args> … | tee driver-resume-gate.json   # must print status complete, no writes
  entrypoints.audit_sequences … > sequence-audit.json
  bf_error_audit > error-audit.json            # §8.7
sidecar exporter: as V4 :854-889, env RUN_MODE=production, WORK_ROOT=/work, WORKFLOW_NAME={{workflow.name}},
  WORKFLOW_TEMPLATE={{workflow.parameters.target-id}}-substreams-backfill, NETWORK={{workflow.parameters.network}},
  PIPELINE=substreams-block-changes-copy; mounts /work read-only and the exporter ConfigMap
```

### 8.6 Writer exclusion (`bf_verify_writer_exclusion`, used by every DB-touching step and the segment preflight)

1. For each `writer-deployments` name: `kubectl -n subgraphs get deployment <name> -o json`;
   require `.spec.replicas == 0` and `(.status.replicas // 0) == 0` (V4 checks only spec, `:157-161`).
   A `Forbidden` means the per-target Role is missing that name: exit 5.
2. Advisory-lock probe on the target database (F12):
   ```sql
   SELECT count(*) FROM pg_locks
    WHERE locktype = 'advisory' AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND objsubid = 2 AND classid IN (1, 2, 3) AND objid = <site id from sgdN>;
   ```
   Must be 0: no Graph Node copy (1), write (2) or prune (3) in progress for this site.
3. Defence in depth, documented as weak: V4's `application_name LIKE 'index_node_%'` count (`:205-209`), plus a head
   stability read (head unchanged across two reads 5 s apart).
4. Engine requirement (not k8s): the generic loader must take `pg_try_advisory_xact_lock(2, <site id>)` inside its
   transaction and abort when it is held, which closes the gap described by audit DB-3 for the duration of each
   commit.

### 8.7 `production-verify` (engine image; no retries)

- Writer exclusion; registry; target identity with `head == (target-block, target-hash)`.
- `entrypoints.verify_run` → require `status == "complete"`, `journal_contiguous`, `files_clean`; its checkpoint sha
  equals the driver's final summary.
- Journal check identical to V4 (`:1012-1022`): first `start_block ≥ seed+1`, last `end_block == target`, all
  committed, contiguous.
- `driver-resume-gate.json` has `status == "complete"` and `head_block == target`.
- `sequence-audit.json`: one OK row per profile table with a VID sequence (count from the profile's
  `tables[] | select(.vid_sequence != null)`), replacing V4's literal 20 (`:1032-1033`).
- `error-audit.json` from SQL on the target: `subgraphs.deployment.{health, failed, fatal_error, non_fatal_errors}`
  and `count(*) FROM subgraphs.subgraph_error WHERE subgraph_id = $D`. With `allow_non_fatal_errors=false` require
  healthy, not failed, zero errors; otherwise require equality with the driver's `deterministic_errors` ledger.
- PoI: the latest `poi2$` row for region `ethereum/<network>` equals the driver's final `poi.digest`.
- `data_sources$`: row count and `max(lower(block_range))` equal the driver's summary, and the count is ≥ the seed's.
- No `*.pending`, `*.building` or lock outside `quarantine/` (V4 `:1024-1029`).
- Writes `production-evidence.json` (§16) and exposes it as output `production-evidence` (`globalName`).

### 8.8 Segment preflight (`lib/segment-preflight.sh`, exec'd by the driver before every commit)

Arguments `schema expected_block expected_hash target_block target_hash artifact` (V4 contract). Checks, in order:
argument formats; `schema == BF_TARGET_SCHEMA`; writer exclusion; registry; database head == (expected, hash);
capacity with growth allowance (§12.2); work-PVC free ≥ `work-min-free-bytes`; sealed-ledger coverage of
`[expected+1, target]`; artefact manifest: `format == "pinax.graph-node.block-changes-copy-spool"`, version in the
driver's allowed set, `READY.json` present and `INCOMPLETE.json` absent, `deployment`, `network`, descriptor sha,
profile sha, `physical_profile.production_selectable == true`, heads equal the arguments,
`totals.removes_committed == 0`, `completeness.faithful == true`, `totals.deterministic_errors == 0` unless allowed,
and producer provenance equal to the pins (`spkg_sha256`, `spkg_module`, `module_hash`, `image_digest`,
`state_replay_sha256`, `substreams_native_sha256`, `family_producer_sha256`, `family_contract_sha256`).
Exit 5 on a failed guard, 3 on a coverage gap, 75 on a transient API/DB error.

### 8.9 Library function signatures (`lib/backfill-lib.sh`, PROPOSED)

```bash
bf_die <code> <reason>                 # prints {"event":"backfill_guard_failed","code":…,"reason":…} to stderr, exits <code>
bf_transient <reason>                  # bf_die 75
bf_require_env <NAME>…                 # exits 2 if unset or empty
bf_target <jq-filter>                  # jq -er over /target/target.json
bf_rpc <method> <params-json>          # curl -fsS --retry 3 to the expanded rpc-url-template; 75 on transport error
bf_canonical_hash <block>              # lowercase 64-hex, no 0x
bf_finalized_block                     # eth_getBlockByNumber("finalized")
bf_psql_target_ro <sql>                # PGOPTIONS read-only, statement_timeout=30s, -AtX ON_ERROR_STOP
bf_psql_primary_ro <sql>
bf_site_id                             # ${BF_TARGET_SCHEMA#sgd}
bf_verify_engine_runtime               # §9.2
bf_verify_producer_runtime             # §9.3
bf_verify_self_placement
bf_verify_chain
bf_verify_noop_evidence <mode: bind|sealed>   # wraps noop_evidence.py
bf_verify_writer_exclusion             # §8.6
bf_verify_target_identity <min_block> <max_block>   # sets BF_HEAD_BLOCK, BF_HEAD_HASH
bf_verify_registry
bf_verify_capacity [growth_bytes]
bf_verify_resume_consistency
bf_verify_run_contract
bf_write_runtime_identity
bf_count_other_live_pipeline_pods      # V4 :495-507 with claimName == $BF_WORK_PVC
bf_recover_stale_pipeline_lock         # V4 :509-538; owner regex ^pid=[0-9]+ schema=$S target=$T$
bf_quarantine_incomplete_compute_artifact   # V4 :678-702; next boundary from segment-size
bf_error_audit
```

---

## 9. Images and how the reducer ships

### 9.1 Recommendation (PROPOSED): separate producer image, staged by an initContainer

| Option | Verdict |
|---|---|
| **A. Separate producer image from substreams-backfills, staged into the engine pod** | **Chosen.** Engine image remains a family-neutral runtime (D3); producer releases at its own cadence while it is iterated against the oracles; the exporter's `runtime_digest` label keeps meaning "engine"; A/B of two producer versions against one engine needs no engine rebuild; engine and producer are both bookworm/glibc 2.36 (F28, F29) and dom153 is x86-64-v3 capable (F22). |
| B. Combined overlay image (`FROM engine@sha256 … COPY producer`) built in substreams-backfills | Fallback if staging proves awkward. One digest, but every engine or producer change rebuilds and re-pins a multi-GB image, and the engine digest disappears from the exporter label. |
| C. Producer baked into the engine repo image | Rejected: breaks D3 family neutrality. |
| D. Two containers joined by FIFOs on an `emptyDir` | Rejected: failure propagation and exit codes across containers are fragile; the driver's pipe and `pipefail` semantics are lost. |
| E. Kubernetes image volumes | Not available: dom153 runs containerd 1.7.30 (F22), image volumes need containerd ≥ 2.1 (ASSUMED from upstream KEP-4639 notes). |

Staging (PROPOSED for the producer): `/opt/producer/bin/producer stage --dest <dir>` copies itself, `runtime.json`,
`source.json`, `contract/*`, `spkg/*` with mode 0555/0444 and prints a JSON receipt. A Rust subcommand avoids relying
on `sh`/`cp` in the producer image and keeps substreams-backfills Rust-only. The emptyDir is `sizeLimit: 2Gi`
(SPKG plus binary are expected well under 200 MB; ESTIMATE).

Digest pinning: both images are referenced only as `<repo>@sha256:{{workflow.parameters.<digest>}}` (F13 makes the
image field substitutable); `target.json` pins the same digests; the validator refuses a mismatch; the in-image
manifests are then hash-checked file by file. Tags are never used in Kubernetes (engine rule, `engine-contract.md` §6).

### 9.2 Engine manifest `/opt/backfill/generic-runtime.json` (`pinax.backfill.generic-runtime/v1`, CONSUMED/PROPOSED)

```json
{
  "schema": "pinax.backfill.generic-runtime/v1",
  "release": "v0.6.0", "source_commit": "<40 hex>", "platform": "linux/amd64", "rust_target_cpu": "x86-64-v3",
  "driver_contract": "pinax.backfill.generic-driver/v1",
  "capabilities": {
    "block_changes_v1_framed": 1, "clock_v1_range_completion": 1, "native_cancel_nonzero": 1,
    "bounded_generic_state": 1, "generic_seed_capture": 1, "data_sources_stream": 1,
    "generic_spool_loader": 1, "graph_node_write_lock": 1, "copy_framing_safe": 1,
    "subgraph_error_writer": 1, "spool_producer_provenance": 1, "profile_driven_sequence_audit": 1,
    "graph_decimal_negative_35_digits": 1, "template_profile_selectable": 1
  },
  "entrypoints": {
    "seed_capture": ["/opt/backfill/bin/graph-backfill", "seed-capture"],
    "pipelined_backfill": ["/opt/backfill/bin/graph-backfill", "run"],
    "audit_sequences": ["/opt/backfill/bin/graph-backfill", "audit-sequences"],
    "verify_run": ["/opt/backfill/bin/graph-backfill", "verify-run"]
  },
  "binary_sha256": {"state-replay": "…", "substreams-native": "…", "postgres-spool-load": "…", "graph-backfill": "…"},
  "tools": ["bash", "jq", "psql", "kubectl", "curl", "sha256sum", "df"]
}
```

Capability → reason (all REPORT-VERIFIED gaps from the engine audit or survey):

| Capability | Closes |
|---|---|
| `clock_v1_range_completion`, `native_cancel_nonzero` | F1 (commit on clean EOF), F2/F3 (legacy-v1 cancel exits 0); Phase-0 stream-completeness fixes |
| `bounded_generic_state` | GEN-3 (whole store in RAM, rewritten per checkpoint) |
| `generic_seed_capture` | no tool turns a Graph Node schema into a generic seed (`engine-contract.md` §2.6) |
| `data_sources_stream` | 10,000-block companion cap, root-only sidecar (§2.5 there; GEN-3) |
| `generic_spool_loader` | GEN-1 / POI-VID-1 / DB-2 (only the 1,153-block V3 pilot loads generic spools) |
| `graph_node_write_lock` | DB-3 |
| `copy_framing_safe` | DB-1 / F2 (`\.` line ends psql COPY) |
| `subgraph_error_writer` | GEN-4 |
| `spool_producer_provenance` | F4 and the `copy_spool_producer(false,false)` gap (`engine-contract.md` §1.3) |
| `graph_decimal_negative_35_digits` | BigDecimal 35-digit refusal (Phase-0 fix) |
| `template_profile_selectable` | GEN-2 (template deployments can never use a selectable profile) |

Preflight rule: the file exists, is not a symlink, hashes to `engine-runtime-sha256`, names
`driver_contract == "pinax.backfill.generic-driver/v1"`, has every capability above at version ≥ 1, every listed
binary hashes as declared, and every tool resolves on `PATH`. No V4 or `block-changes-clock-v1-runtime` image carries
this file today (VERIFIED by absence in `ENG/Dockerfile`), so the template is inert against every existing digest.

### 9.3 Producer manifests (CONSUMED/PROPOSED for substreams-backfills)

`/opt/producer/runtime.json` (`pinax.backfill.producer-runtime/v1`):

```json
{
  "schema": "pinax.backfill.producer-runtime/v1",
  "family": "aerodrome-slipstream-base",
  "source_repository": "pinax-network/substreams-backfills", "source_commit": "<40 hex>",
  "production_selectable": true,
  "producer_protocol": "pinax.backfill.producer/v1",
  "executable": "bin/producer",
  "files": {"bin/producer": "<sha256>", "source.json": "<sha256>",
            "contract/compatibility.json": "<sha256>",
            "contract/block-changes-descriptor.json": "<sha256>", "contract/block-changes-descriptor.sha256": "<sha256>",
            "contract/physical-profile.json": "<sha256>", "contract/physical-profile.sha256": "<sha256>",
            "spkg/aerodrome-slipstream-base-extractor-v0.1.0.spkg": "<sha256>"},
  "build": {"base_image": "debian:bookworm-slim@sha256:…", "rust_toolchain": "…", "target": "x86_64-unknown-linux-gnu"}
}
```

`/opt/producer/contract/compatibility.json` (`pinax.backfill.family-contract/v1`):

```json
{
  "schema": "pinax.backfill.family-contract/v1",
  "family": "aerodrome-slipstream-base", "deployment": "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",
  "network": "base", "chain_id": 8453, "spec_version": "1.2.0", "api_version": "0.0.7", "graft": null,
  "poi_version": "fast", "deterministic_error_policy": "non_fatal", "start_block": 13843704,
  "extractor": {"repository": "pinax-network/substreams-backfills",
                "release": "aerodrome-slipstream-base-substreams-v0.1.0",
                "asset": "aerodrome-slipstream-base-extractor-v0.1.0.spkg",
                "spkg_path": "spkg/aerodrome-slipstream-base-extractor-v0.1.0.spkg",
                "spkg_sha256": "…", "package_name": "…", "package_version": "…",
                "module": "…", "module_hash": "…", "output_type": "proto:…",
                "initial_block": 13843704, "params": [],
                "headers": ["X-substreams-acknowledge-non-deterministic: true"]},
  "descriptor": {"path": "contract/block-changes-descriptor.json", "sha256": "…"},
  "physical_profile": {"path": "contract/physical-profile.json", "sha256": "…", "profile_id": "…",
                       "evidence_kind": "live_catalog", "production_selectable": true},
  "engine_requirements": {"driver_contract": "pinax.backfill.generic-driver/v1",
                          "capabilities": ["…the §9.2 list…"]}
}
```

The family contract names engine *requirements*, not an engine digest; exact digests are pinned once, in
`target.json` (single reviewed place, no forced producer rebuild per engine release).

Producer CLI surface the template uses: `producer stage --dest DIR`, `producer version --json` (must echo
`runtime.json` identity), `producer seed --from PATH --out PATH`, `producer seed --empty --start-block N --out PATH`
(oracle mode), `producer reduce …` (invoked by the engine driver). Exit codes as §15.1.

Release plumbing (substreams-backfills, PROPOSED, Rust-only): `cargo xtask producer-runtime context|smoke|archive|
verify-discovery --family <f>` replacing the Python `package.py` pattern of `mapping-host-runtime.yml`; workflow
`producer-runtime.yml` builds, smoke-tests against committed fixture frames with no network, pushes
`<family>-producer-sha-<commit>`, ORAS-attaches the archive plus `runtime.json` (same discovery contract as #146).

---

## 10. The fail-closed preflight (why the template can merge now and stay inert)

| Lock | Where | Opens when |
|---|---|---|
| L1 `target.json.status == "active"` | `production-preflight-parameters` (Python, no engine pod) | activation slice K2-6, reviewed in git |
| L2 no placeholder, digests match `target.json` | same | real digests exist and are pinned |
| L3 engine `generic-runtime.json`: driver contract v1 + all capabilities + hashes | `production-preflight` | engine Phase 2 release exists and is pinned |
| L4 producer `runtime.json`: `production_selectable`, hashes, family contract accepts the engine contract, profile `live_catalog` + selectable | `production-preflight` | Aerodrome producer certified and released; live-catalog profile captured from the landing schema |

Plus the human gate `production-approval` before any write. The library's own entrypoint
`refuse-direct-submission` exits 2, and the Aerodrome wrapper ships with L1–L2 closed. A contract test runs the
validator over the rendered wrapper defaults and asserts exit 2 with the `inert_reasons` (§18.1 T-INERT).

---

## 11. Secrets, RBAC, network

Secrets (CONSUMED, existence ASSUMED, F20):

| Secret / key | Used by | Not given to |
|---|---|---|
| `backfill-credentials/PINAX_API_KEY` | preflight, prepare-seed, load, verify (RPC) | producer (scrubbed env), validator |
| `backfill-credentials/SUBSTREAMS_API_TOKEN` | load only (driver → substreams-native) | everything else |
| `backfill-credentials/POSTGRES_PASSWORD` | preflight, prepare-seed, load, verify | validator, producer |
| `ghcr-cred` (pull) | engine image and producer image | — |

Open: whether `ghcr-cred` can pull the private `substreams-backfills` package (O-IMG in §21).

RBAC (PROPOSED, new objects only; V4 `base/rbac.yaml` untouched):

```yaml
# base/graph-node-backfill-rbac.yaml (namespace subgraphs-backfill)
ServiceAccount: substreams-graph-node-backfill-runner
Role substreams-graph-node-backfill-runner:
  - {apiGroups: [argoproj.io], resources: [workflowtaskresults], verbs: [create, patch]}   # emissary
  - {apiGroups: [argoproj.io], resources: [workflows], verbs: [get, list, watch]}         # exporter + noop proof
  - {apiGroups: [""], resources: [pods], verbs: [get, list]}                              # live-pod guard + self check
RoleBinding substreams-graph-node-backfill-runner → SA above
# kan/targets/<id>/writers-rbac.yaml (namespace subgraphs)
Role substreams-graph-node-backfill-<id>-writers:
  - {apiGroups: [apps], resources: [deployments], resourceNames: [graph-node-aerodrome-backfill-0], verbs: [get]}
RoleBinding → subgraphs-backfill:substreams-graph-node-backfill-runner
```

No `pods/exec`, no Secret access, no scale/update/delete/patch verbs on anything (the generic path reaches
PostgreSQL over the network as V4 production does, `K8S/…/production-workflow-template.yaml:163`). `automountServiceAccountToken`
stays on (exporter and kubectl need it).

Network: `subgraphs-backfill` has no NetworkPolicies today (`k8s-backfill-stack.md` §3.3). Required egress: tier1
`172.20.114.2:443` (kan) or `172.19.114.2:443` (riv), `base.rpc.pinax.network:443`, PostgreSQL 5432 in `subgraphs`,
the API server, DNS. Kan pod egress to the tier1 VIP is unverified (O3); the oracle-window smoke (§17) is the first
proof. A NetworkPolicy per lane is a follow-up, not part of the first slices (V4 parity).

---

## 12. Storage, placement, resources

### 12.1 Work PVC (per target)

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: substreams-backfill-aerodrome-slipstream-base-work
  namespace: subgraphs-backfill
  labels: {app.kubernetes.io/name: substreams-graph-node-backfill, backfills.pinax.network/target-id: aerodrome-slipstream-base}
  annotations: {kustomize.toolkit.fluxcd.io/prune: disabled}
spec: {accessModes: [ReadWriteOnce], storageClassName: local-storage, resources: {requests: {storage: 1Ti}}}
```

Sizing (ESTIMATE): Positions up to ~23.6M at the seed (F25; fewer because same-block mint-and-burn positions never
become entities), Ticks ~10⁶, Tokens ~10⁴, Pools ~1.5×10³ (`aerodrome-target.md` §9). At 0.5–1 KB per entity the
engine seed artefact is ~10–25 GB and the producer state similar, so one checkpoint generation is ~20–50 GB. Rolling
retention keeps seed + last committed + in-flight look-ahead (≈ 4 generations ≈ 80–200 GB) plus two spools of
50,000 blocks × 150–250 rows × ~0.7 KB ≈ 5–9 GB each, plus logs and compacted quarantine. Working set ≈ 100–250 GB;
1 Ti stays under the 70 % fill gate with ~3× headroom and `local-storage` expands online. The PVC binds on first
use (`WaitForFirstConsumer`), so it consumes dom153 allowance only when the first pod starts; the capacity gate
(`K8S/docs/pre-wave-capacity-gate.md` §2) is recorded in the activation PR.

### 12.2 Capacity checks (landing store)

Preflight and every segment: `pg_tablespace_size('pg_default') + growth ≤ max_pg_bytes`, where `growth` is
`max(1.5 × last segment growth, segment-growth-allowance-bytes)` (last growth from `bf_capacity_history`, a JSON line
appended after each commit by the segment preflight); `capacity − max == reserve` (V4 invariant, `:215-219`); and
`max ≤ 0.70 × capacity` (fill gate). Work PVC: `df -B1 /work` available ≥ `work-min-free-bytes`.
Landing store size itself (8–12 Ti on dom153) is SYNTHESIS §3 Q7 and decision D6.

### 12.3 Placement and resources

- Wrapper `nodeSelector: {kubernetes.io/hostname: dom153, infra.pinax.network/compute-tier: fast,
  feature.node.kubernetes.io/cpu-cpuid.AVX2: "true"}` for every pod (all mount the PVC). dom157 is excluded by the
  hostname pin (`K8S/AGENTS.md:84-87`).
- Resources (ESTIMATE; tune from the first segments):

| Step | Request | Limit |
|---|---|---|
| validate | 50m / 64Mi | 500m / 256Mi |
| preflight, verify | 1 / 1Gi | 2 / 4Gi |
| prepare-seed | 4 / 32Gi | 16 / 256Gi |
| load (podSpecPatch) | 8 / 128Gi | 16 / 384Gi |
| exporter sidecar | 25m / 64Mi | 100m / 128Mi (V4 `:887-889`) |
| stage-producer init | 100m / 64Mi | 1 / 256Mi |

  The load limit reflects look-ahead overlap: two producer states and two generic states can be live at once.
  dom153 has ~800 GiB of memory unrequested (F23), so 128Gi/384Gi fits beside a dormant V4 lane.
- Segment size 50,000 (ESTIMATE): Aerodrome writes ~150–250 rows per block (SYNTHESIS §3 Q7), so one atomic
  transaction holds ~7.5–12.5M inserted rows plus clamps, similar to a V4 100k segment at its density. The landing
  store needs `max_wal_size` sized to at least twice one segment's WAL (core/kan concern).

---

## 13. Concurrency

- Workflow-level mutex in the wrapper with a **fixed** name `substreams-graph-node-backfill-<target-id>`. Templated
  names lint and are substituted at runtime (F13, F16), but a fixed per-target name keeps the guarantee independent
  of parameter overrides.
- `parallelism: 1` on the wrapper.
- PVC isolation per target makes `bf_count_other_live_pipeline_pods` exact; it counts only pods mounting
  `$BF_WORK_PVC` with the exporter label, so V4 and generic lanes never block each other (F4).
- No noop mutex is needed: the backfill consumes completed noop evidence only; a concurrent noop extending the
  range does not alter cached segments.
- A future generic certification template for the same target must take the same mutex.

---

## 14. Observability and exporter compatibility

### 14.1 What the exporter reads (VERIFIED, `backfill_exporter.py`)

| Source | Names | Use |
|---|---|---|
| env (`:1206-1238`) | `NAMESPACE`, `WORKFLOW_TEMPLATE`, `WORKFLOW_NAME`, `RUN_MODE` (must be one of six, `:1213-1219`), `WORK_ROOT`, `NETWORK`, `PIPELINE`, `POLL_INTERVAL_SECONDS`, `EXPORTER_SOURCE_PATH` | with `WORKFLOW_NAME` set it GETs only that Workflow (`:1273-1281`) |
| parameters, production mode (`:1401-1411`) | `target-schema`, `target-shard`, `expected-seed-block` | schema, shard, seed, run root `/work/production-<schema>-<seed>` |
| parameters, all modes | `deployment`, `target-block`, `segment-size`, `runtime-image-digest`, `compatibility-profile`, `substreams-parallel-workers`, `poi-workers`, `poi-batch-size` | labels, target, receipt boundary |
| parameters with defaults if absent | `performance-experiment`, `experiment-id`, `wal-compression`, `clamp-load-mode`, `asynchronous-spool-writers`, `asynchronous-spool-queue-buffers`, `protobuf-decode-ahead`, `allocator`, `postgres-work-mem-mb`, `defer-secondary-indexes`, `index-build-workers`, `index-maintenance-work-mem-mb`, `index-parallel-maintenance-workers`, `source-experiment-id` | labels and the lane key (`:362-407`) |
| files under run root | `postgres-pipeline-progress.jsonl`, `postgres-backfill-progress.jsonl` (legacy, absent here), `driver-output.jsonl`, `driver-events.jsonl`, `backfill-performance.jsonl` (optional WAL stats), `checkpoints/checkpoint-<head>.json` + `.manifest.json` + `.load-receipt.json` with `pipeline: postgres-copy-spool-load` lines (receipt view, `:773-856`) | progress, rate, ETA, phases, rows |
| template names | `production-preflight*`, `production-approval`, `production-prepare-seed`, `production-load`, `production-verify` | phase gauge (`:316-359`) |

Compatibility decisions: keep every parameter name above; keep the run root; keep the template names; the generic
driver emits the §4.3 journal and events. The receipt view stays inert for the generic lane (its loader summaries use
a different `pipeline` value), so the database head metric equals the journal head; this is safe, only slightly
lagging. Label `pipeline` becomes `substreams-block-changes-copy` (env), and `run_mode` stays `production`.

### 14.2 Optional exporter slice K2-3 (in `subgraphs-operations/backfill/kan`, PROPOSED)

- `DISPLAY_NAME` env, default `f"Uniswap v4 Base {schema}"` (unchanged V4 behaviour); the generic sidecar sets
  `"{{workflow.parameters.target-id}} {{workflow.parameters.target-schema}}"`. Fixes the hard-coded label at `:1421`.
- Accept `pipeline: block-changes-spool-load` receipts with generic checkpoint names (`checkpoint-<head>.<ext>` from
  env `CHECKPOINT_SUFFIX`, default `.json`), so the receipt view also works for the generic lane.
- Tests in `test_backfill_exporter.py`; `EXPORTER_CONTRACT_VERSION` stays `"5"` because metric names and default
  labels are unchanged.

### 14.3 Metrics and alerts

- Existing `backfill_job_*` series flow through the existing Service and `VMServiceScrape` (F19); `workflow` label
  separates lanes.
- Wrapper-level Argo metric (fullsync pattern, `K8S/subgraphs-operations/fullsync/base/workflow-template.yaml:24-39`):
  `substreams_graph_node_backfill_workflow_info{workflow,target_id,deployment,wf_status}` realtime gauge of
  `{{workflow.duration}}`.
- Alerts (slice K2-5, VMRule + test in the fullsync style): stalled commits (`backfill_job_phase{phase="loading"}==1`
  and no change of `backfill_job_database_committed_head_block` for 3 × expected segment time); exporter down;
  `backfill_job_journal_readable == 0` while loading; workflow Failed. Flip
  `subgraphs-alerts/base/backfill-flags.yaml` Aerodrome entry to value 2 and fix its `protocol: uniswap-v3` label
  (SYNTHESIS PR-K3) in the activation PR.

---

## 15. Failure and resume semantics

### 15.1 Exit-code classes (template steps, segment preflight, engine driver, producer)

| Code | Class | Retried | Operator action |
|---|---|---|---|
| 0 | success | — | — |
| 2 | invalid parameters, inert target, contract/manifest refusal | no | fix submission or release |
| 3 | cache miss (server budget refusal) or noop coverage gap | no | run or extend the noop; resubmit |
| 4 | deterministic data error (producer, state-replay materialized mismatch, unexpected subgraph error) | no | investigate; oracle diff |
| 5 | safety guard: writer exclusion, registry, head/identity, capacity, lock ownership, run-contract drift | no | investigate infra state |
| 75 | transient: network, API, PG connect, retryable Substreams | yes | none |
| 137 / 143 | OOM kill / SIGTERM (node drain) | yes | raise memory if repeated |
| other | bug | no | file engine/template issue |

### 15.2 Retry strategies

- `production-preflight-parameters`, `production-preflight`, `production-verify`: none.
- `production-prepare-seed`: `limit: "3"`, `retryPolicy: Always`,
  `expression: "lastRetry.status == 'Error' || asInt(lastRetry.exitCode) in [75, 137, 143]"`, `backoff: {duration: 1m, factor: "2"}`.
- `production-load`: same expression, `limit: "20"` (V4 `:389-391`), `backoff: {duration: 2m, factor: "1"}`.
- No `maxDuration` anywhere (it bounds total retry-node time, fullsync contract test `:9-17`).

### 15.3 Run contract and resume

`run-contract.json` (`pinax.substreams-graph-node-backfill.run-contract/v1`):
`{target_id, family, deployment, network, chain_id, target_shard, target_schema, seed:{block,hash},
landing:{postgres_host, parked_node_id, active_source}, runtime:{engine_image_digest, engine_runtime_sha256,
producer_image_digest, producer_runtime_sha256, family_contract_sha256}, extractor:{spkg_sha256, module, module_hash},
descriptor_sha256, profile_sha256, segment_size, endpoint, noop_evidence:[sha…], created_by:{workflow, uid},
approval_reference, created_at}`.

- Immutable: everything except `runtime.*`, `endpoint` and `noop_evidence`. A mismatch exits 5.
- `runtime.*` may change only when `amend-run-contract=<approval reference>`; the change is appended to
  `run-contract-amendments.jsonl` and listed in the evidence (certification decides whether the change was
  output-neutral).
- `endpoint` may move within `equivalent_endpoints`; recorded in `runtime-history.jsonl`.
- `noop_evidence` grows by amendment (§7.3 step 6).

Resume = submit a new Workflow with the same `target-schema` and `expected-seed-block`: same run root, the driver
continues from the database head. Extending `target-block` is a new lane key for the exporter (`:362-407`) but the
same run root.

### 15.4 Crash scenarios

| Scenario | Detection | Recovery |
|---|---|---|
| OOM/SIGKILL during compute | `.building` dir left | `bf_quarantine_incomplete_compute_artifact` moves it to `quarantine/` (after writer exclusion and zero other live pods); driver recomputes |
| Kill after COMMIT, before journal append | DB head one segment ahead of journal | driver reconciles from its sealed receipt (§4.3 item 7) or exits 5 |
| Stale lock after SIGKILL | `.postgres-pipeline.lock/owner` exists | `bf_recover_stale_pipeline_lock` quarantines it only if the owner regex matches this schema/target, writers are stopped and no other live pod mounts the PVC |
| Substreams stream cut short | clock-v1 completion check in state-replay; native cancel non-zero | no READY; driver exits 75; retried |
| Cache evicted or wrong module hash | server budget refusal | exit 3, terminal, no partial work |
| Graph Node writer comes back (agent, manual scale) | replicas / advisory-lock / registry checks at the next segment | exit 5 before the next commit; the in-flight commit itself is protected by the loader's write lock (engine) |
| Node drain | 143 / pod Error | retried on dom153 (PVC is node-local; the pod can only land there) |
| Approval never given | Workflow suspended | 30 d deadline; nothing written |
| Deadline expiry mid-run | Workflow Failed | resubmit; resumes from DB head |

---

## 16. Evidence (`production-evidence.json`, `pinax.substreams-graph-node-backfill.evidence/v1`)

```json
{
  "schema": "pinax.substreams-graph-node-backfill.evidence/v1",
  "status": "candidate-ready", "activation_performed": false, "active_source_retained": true,
  "workflow": {"name": "…", "uid": "…"}, "approval_reference": "…",
  "target_id": "…", "family": "…", "deployment": "…", "network": "base", "chain_id": 8453,
  "landing": {"shard": "…", "schema": "sgdN", "postgres_host": "…", "parked_node_id": "…", "registry": "aerodrome_b|f|index_node_aerodrome_backfill_0|t"},
  "seed": {"block": 0, "hash": "…", "seed_capture_sha256": "…", "producer_state_sha256": "…"},
  "head": {"block": 0, "hash": "…"},
  "runtime": {"engine_image": "…@sha256:…", "engine_runtime_sha256": "…", "engine_source_commit": "…",
              "producer_image": "…@sha256:…", "producer_runtime_sha256": "…", "producer_source_commit": "…",
              "family_contract_sha256": "…", "descriptor_sha256": "…", "profile_sha256": "…",
              "spkg_sha256": "…", "module": "…", "module_hash": "…", "runtime_identity_sha256": "…",
              "amendments": []},
  "substreams": {"endpoint": "…", "noop_evidence": ["<sha>"], "coverage": {"start_block": 0, "stop_block": 0},
                 "cache_miss_tolerance_blocks": 10000},
  "progress": {"segments": 0, "progress_sha256": "…", "segment_size": 50000},
  "checkpoint": {"sha256": "…", "bytes": 0},
  "poi": {"region": "ethereum/base", "digest": "…", "matches_database": true},
  "data_sources": {"rows": 0, "max_creation_block": 0},
  "errors": {"health": "healthy", "failed": false, "non_fatal_errors": 0, "subgraph_error_rows": 0},
  "sequence_audit": {"tables": 0, "all_ok": true, "sha256": "…"},
  "target_database_bytes": 0, "completed_at": "RFC3339"
}
```

Also exposed as the global output `production-evidence` for a later certification Workflow.

---

## 17. Root replay for oracle windows (`oracle-window`, slice K2-4)

Required by the decisions ("a root replay 13.84M→ must remain possible for oracle windows"). Shape (PROPOSED):

- Entry template `oracle-window` in the library and a wrapper `<target-id>-substreams-oracle-window`.
- Parameters: `window-start-block` (≥ contract `start_block`; 13,843,704 for root), `window-end-block`,
  `window-end-hash`, the runtime and noop parameters, no landing parameters.
- DAG: `production-preflight-parameters` (landing `none`) → `oracle-preflight` (L3, L4 without the
  `production_selectable` requirement, noop coverage from `window-start-block`) → `oracle-compute` (driver with
  `--landing none`, producer `seed --empty --start-block <window-start>`, generic seed empty with the all-zero
  expected hash, the only form today's state-replay accepts for a fresh root, `engine-contract.md` §2.6) →
  `oracle-verify` (BCF1 frame digest, per-block payload sha list, spool manifests; optional `oracle-frames-sha256`
  parameter compared with the mapping-host's frames for the same window).
- No database, no approval, no exporter sidecar (exporter `RUN_MODE=compute` is pinned to V4 blocks,
  `backfill_exporter.py:1390-1400`). Run root `/work/oracle-<start>-<end>-<workflow uid>/`.
- First use is also the egress smoke (O3) and the cache-tripwire proof (gate A4).

---

## 18. Tests, CI, acceptance gates

### 18.1 Contract tests over the rendered tree (`tests/test_backfill_contract.py`, Python stdlib)

CI renders `kustomize build subgraphs-operations/backfill-substreams/kan > /tmp/bs.yaml` and converts with
`docker run --rm -v /tmp:/m mikefarah/yq:4.45.4 ea -o=json '[.]' /m/bs.yaml > /tmp/bs.json` (image already used by
fullsync). Tests read `BACKFILL_SUBSTREAMS_RENDERED_JSON`.

| Test | Asserts |
|---|---|
| T-LIB-REFUSE | library entrypoint is `refuse-direct-submission`; library has no spec-level volumes, mutex or identity defaults |
| T-NAMES | template names `production-preflight-parameters`, `production-preflight`, `production-approval`, `production-prepare-seed`, `production-load`, `production-verify` exist (exporter phase map) |
| T-IMAGES | every engine-image container is `ghcr.io/pinax-network/substreams-graph-node-backfill@sha256:{{workflow.parameters.runtime-image-digest}}`; producer init is `ghcr.io/pinax-network/substreams-backfills@sha256:{{workflow.parameters.producer-image-digest}}`; no tag-only image anywhere |
| T-NO-INTERPOLATION | no `{{workflow.parameters.` inside any `args`/`script.source` text; parameters only in `env[].value`, image, podSpecPatch, metrics labels |
| T-RETRY | retry expressions exactly as §15.2; no `maxDuration`; preflight/verify have no retryStrategy |
| T-EXPORTER | load template has the exporter labels, sidecar env `RUN_MODE=production`, `WORK_ROOT=/work`, `WORKFLOW_NAME={{workflow.name}}`, read-only `/work`, port 9090, non-root security context |
| T-SECRETS | `SUBSTREAMS_API_TOKEN` only in `production-load`; no Secret in validate or the producer init container |
| T-WRAPPER | each wrapper: fixed mutex == `target.json.workflow.mutex`; `parallelism: 1`; nodeSelector hostname dom153 + AVX2; volume `production-work` claim == `target.json.work.pvc`; SA `substreams-graph-node-backfill-runner`; `imagePullSecrets: ghcr-cred`; single step `templateRef … backfill` |
| T-DEFAULTS-PINNED | every pinned parameter default in a wrapper equals `target.json` |
| T-INERT | running `validate_params.py` on the rendered wrapper defaults exits 2 and prints every `inert_reasons` entry while `status == "inert"` |
| T-CM | generated ConfigMaps are `immutable: true`, prune-disabled, hash-suffixed, and referenced by the rewritten names |
| T-PVC | work PVC `local-storage`, RWO, prune disabled, one per target, name unique across targets |
| T-RBAC | no `secrets`, `pods/exec`, `create`/`update`/`patch`/`delete` on apps or core resources; per-target Role `resourceNames` == `writer_deployments` |
| T-AGENT | `parked_node_id` never appears in `INDEXER_AGENT_INDEX_NODE_IDS` (`K8S/subgraphs-indexers/pinax2/kan/kustomization.yaml:88`) |
| T-LANDING (active targets only) | `core/kan` renders a StatefulSet whose service host equals `target_postgres_host`, a `[store.<target_shard>]` in `core/kan/graph-node-config.yaml`, and writer Deployments with `replicas: 0` |
| T-V4-UNTOUCHED | `subgraphs-operations/backfill/**` is not modified by K2-1/K2-2 (git diff in CI), and the existing V4 `test-contract.sh` still passes |

### 18.2 Library and helper unit tests

`tests/test_validate_params.py`: `test_refuses_placeholders`, `test_refuses_override_of_pinned_field`,
`test_inert_target_lists_reasons`, `test_endpoint_allowlist_and_network_prefix`, `test_segment_size_allowlist`,
`test_parallel_workers_bounds`, `test_resource_bounds`, `test_capacity_invariants_and_fill_gate`,
`test_target_after_seed`.

`tests/test_noop_evidence.py` (fixtures under `tests/fixtures/noop-evidence/` and `tests/fixtures/workflow/`):
`valid.json`, `sha-mismatch` (param), `non-canonical.json`, `dev-mode.json`, `wrong-spkg.json`,
`wrong-module.json`, `module-hash-null-with-params.json`, `range-starts-after-seed.json`,
`range-short-of-target.json`, `endpoint-riv-shared.json`, `endpoint-public.json`;
workflow fixtures `noop-succeeded.json`, `noop-failed.json`, `noop-uid-mismatch.json`,
`noop-output-differs.json`, `noop-no-globalname-one-node.json`, `noop-no-globalname-two-nodes.json`.
Tests: `test_accepts_exact_evidence`, `test_refuses_sha_mismatch`, `test_refuses_non_canonical_bytes`,
`test_refuses_non_production_or_non_noop`, `test_refuses_identity_mismatch`, `test_null_module_hash_only_without_params`,
`test_coverage_must_include_seed_plus_one_and_target`, `test_shared_state_store_equivalence`,
`test_ledger_union_must_be_contiguous`, `test_live_proof_required_at_first_bind`,
`test_sealed_copy_suffices_after_ttl_expiry`, `test_node_output_fallback_requires_exactly_one`.

`tests/test-backfill-lib.sh` with stubs `tests/stubs/{kubectl,psql,curl,df}` driven by `BF_STUB_SCENARIO` and
fixtures under `tests/fixtures/{kube,psql,rpc}/`:
`writer_spec_zero_status_one_fails`, `writer_forbidden_is_guard_failure`, `advisory_write_lock_held_fails`,
`advisory_copy_lock_held_fails`, `registry_active_target_fails`, `registry_two_active_sources_fails`,
`head_null_fails` (audit DB-6), `head_hash_not_canonical_fails`, `capacity_fill_gate_fails`,
`capacity_growth_allowance_fails`, `work_pvc_low_space_fails`, `stale_lock_wrong_owner_kept`,
`stale_lock_other_live_pod_kept`, `stale_lock_quarantined`, `building_quarantined_and_compacted`,
`runtime_identity_changed_without_amendment_fails`, `segment_manifest_unfaithful_fails`,
`segment_manifest_wrong_spkg_fails`, `segment_outside_coverage_exit_3`, `transient_psql_connect_exit_75`,
`engine_manifest_missing_exit_2`, `engine_capability_missing_exit_2`, `producer_not_selectable_exit_2`.

### 18.3 CI additions (`.github/workflows/ci.yaml`)

New step after "Lint Argo Substreams backfill workflow" (`:67-75`):

```yaml
- name: Lint generic Substreams backfill workflows
  run: |
    kustomize build subgraphs-operations/backfill-substreams/kan > /tmp/backfill-substreams.yaml
    docker run --rm -v /tmp:/manifests:ro quay.io/argoproj/argocli:v4.0.7 \
      lint --offline --strict /manifests/backfill-substreams.yaml      # one invocation: wrappers + library (F16)
    docker run --rm -v /tmp:/m mikefarah/yq:4.45.4 ea -o=json '[.]' /m/backfill-substreams.yaml > /tmp/backfill-substreams.json
    BACKFILL_SUBSTREAMS_RENDERED_JSON=/tmp/backfill-substreams.json \
      python3 -B -m unittest discover -s subgraphs-operations/backfill-substreams/tests -p 'test_*.py' -v
    bash subgraphs-operations/backfill-substreams/tests/test-backfill-lib.sh
    bash -n subgraphs-operations/backfill-substreams/base/lib/backfill-lib.sh
    bash -n subgraphs-operations/backfill-substreams/base/lib/segment-preflight.sh
```

Add `subgraphs-operations/backfill-substreams/base` and `subgraphs-operations/backfill-substreams/kan` to the
"Build every overlay" list (`:153`). If PR-K1 already added a step for the tree, extend that step instead.

### 18.4 Acceptance gates

| Gate | When | Pass condition |
|---|---|---|
| A1 | K2-1/K2-2 merge | render, strict lint, all §18.1–18.2 tests green; V4 tests unchanged and green |
| A2 inert proof | after K2-2 is reconciled (optional live check) | submitting the Aerodrome wrapper with defaults fails in `production-preflight-parameters` with exit 2 listing the inert reasons; no engine or producer pod is created; the PVC stays Pending |
| A3 smoke | engine + producer pre-releases exist | `oracle-window` over ~1,000 root blocks from 13,843,704 completes; frame digest equals a local producer run; egress to the chosen tier1 proven |
| A4 tripwire | with A3 | warm window passes with `cache-miss-tolerance-blocks=10000`; a deliberately un-nooped window fails in seconds with exit 3 and the `limit-processed-blocks` message |
| A5 first segments | landing approved, clone taken, noop complete | load two segments to `seed + 2 × segment-size`; read-only differential of the clone against live `sgd2` at that block (entity rows without VID, `poi2$` digest); needs O4 (no pruning) |
| A6 lifecycle drills | during A5 | delete the load pod mid-compute and mid-COPY; stale lock and `.building` are quarantined; no duplicate versions; resume gate prints `complete` with no writes; sequence audit OK |
| A7 run | full target | `production-evidence.json` `candidate-ready`; certification and cutover remain separate approved steps |

---

## 19. PR-sized slices (ordered)

| # | Repo | Slice | Depends on | Inert? |
|---|---|---|---|---|
| K2-1 | k8s-subgraphs | Library `WorkflowTemplate/substreams-graph-node-backfill`, `base/lib/*`, kustomize nameReference config, runner SA/Role/RoleBinding, contract + validator + evidence + lib tests, CI step, README section | PR-K1 merged (tree + Flux) | yes (refuses direct submission) |
| K2-2 | k8s-subgraphs | Aerodrome target: `target.json` (`status: inert`), wrapper, work PVC (prune disabled), writers Role, example submission, docs | K2-1 | yes (L1, L2) |
| K2-3 | k8s-subgraphs | Exporter `DISPLAY_NAME` + generic receipt support + tests (in `backfill/kan`) | none | n/a |
| K2-4 | k8s-subgraphs | `oracle-window` entry template + Aerodrome wrapper + tests | K2-2 | L3/L4 until releases |
| K2-5 | k8s-subgraphs | VMRule alerts + tests, `docs/` runbook, `operate-subgraph-backfill-workflows` skill section, backfill-flag label fix | K2-2 | n/a |
| K2-6 | k8s-subgraphs | Activation: real digests and landing values in `target.json`, `status: active`, capacity-gate evidence; needs explicit user approval | engine E-G*, producer S-R1, landing core/kan, graphman copy, noop evidence | opens L1/L2 only; approval suspend remains |
| E-G1 | engine | `generic-runtime.json` + driver contract v1 (journal, events, exit codes, lock/building names, segment-preflight hook) | Phase-0 engine fixes | — |
| E-G2… | engine | D3 capabilities of §9.2 (bounded state, seed capture, data-source stream, loader with write lock and safe COPY, error writer, provenance) | — | — |
| S-R1 | substreams-backfills | Producer runtime image + `producer stage/version/seed` + `cargo xtask producer-runtime …` + `producer-runtime.yml` | reducer crate | — |
| K1 | k8s-subgraphs (parallel agent) | Noop `globalName` outputs `noop-evidence`, `noop-evidence-sha256` with the §7.2 schema | — | — |

K2-1 through K2-5 can merge before any engine or producer release and stay inert.

---

## 20. Interfaces

Exposed by this design:

- `WorkflowTemplate/substreams-graph-node-backfill` with entry templates `backfill` (and `oracle-window`, K2-4);
  per-target wrapper naming `<target-id>-substreams-backfill`; parameter contract §5.
- `pinax.backfill.target/v1` (`target.json`, §6) delivered as an immutable hashed ConfigMap.
- Segment preflight executable contract (V4 argument order) and exit-code classes §15.1.
- Run-root layout §4.2; run contract `pinax.substreams-graph-node-backfill.run-contract/v1`; evidence
  `pinax.substreams-graph-node-backfill.evidence/v1` as global output `production-evidence`.
- Exporter-compatible metrics (`backfill_job_*` via the existing sidecar) and
  `substreams_graph_node_backfill_workflow_info`.

Consumed:

- PR-K1 noop: global outputs `noop-evidence` / `noop-evidence-sha256`, schema `pinax.substreams-noop.evidence/v1`.
- Engine: `/opt/backfill/generic-runtime.json` (`pinax.backfill.generic-runtime/v1`) and
  `pinax.backfill.generic-driver/v1` (entrypoints `seed_capture`, `pipelined_backfill`, `audit_sequences`,
  `verify_run`; journal/events/stdout shapes; exit codes; lock/building names; generic spool manifest provenance).
- Producer: `/opt/producer/runtime.json` (`pinax.backfill.producer-runtime/v1`), family contract
  `pinax.backfill.family-contract/v1`, CLI `stage`, `version --json`, `seed`, `reduce`.
- Existing k8s objects: `backfill-credentials` keys, `ghcr-cred`, `ConfigMap/substreams-backfill-exporter`,
  `Service/substreams-backfill-exporter`, `VMServiceScrape/subgraphs-backfill-metrics`.
- Graph Node catalog: `subgraphs.deployment`, `subgraphs.head`, `public.deployment_schemas`,
  `subgraphs.subgraph_deployment_assignment`, `subgraphs.subgraph_error`, `pg_locks` advisory keyspace (F12).
- Substreams server semantics: effective-block `limit_processed_blocks` (F7, F8) and fatal `FailedPrecondition` (F9).

---

## 21. Risks, open items, needs

Risks:

1. **Interface drift with parallel designs.** Driver contract, producer CLI and noop evidence are specified here from
   the consumer side; the engine, reducer and noop designs may name things differently. Mitigation: everything is
   discovered through versioned manifests; only §4.3/§9 mappings change.
2. **Tripwire semantics on the exact Pinax deployment.** Verified in source at the server commit, not by a request.
   An uncached partial bundle at segment edges, counted per stage, could approach the tolerance for many-stage
   graphs. Gate A4 measures it; the tolerance is a pinned target value.
3. **Cache retention.** If the tier2 state bucket expires objects, a long run can hit exit 3 mid-way. Recovery is a
   noop extension over the evicted range, then resume; nothing partial is committed.
4. **Memory sizing** for producer + generic state with look-ahead is an ESTIMATE until bounded state lands; the
   first segments must be watched (`container_memory_working_set_bytes`).
5. **Exporter receipt view** stays inert for the generic lane until K2-3; database-head metrics lag by one segment
   at most.
6. **Advisory-lock probe** only sees locks held at probe time; the loader-side `(2, site)` transaction lock (engine)
   is what actually excludes a concurrent Graph Node write during a commit.
7. **Hashed immutable ConfigMaps accumulate** under prune-disabled; harmless, needs occasional manual cleanup.
8. **Indexer agent** could reassign the active deployment; the parked node is kept out of
   `INDEXER_AGENT_INDEX_NODE_IDS` (T-AGENT) and the registry tuple is re-checked before every commit.

Open (verification needed; owner in parentheses):

- O-SECRETS: `backfill-credentials` and `ghcr-cred` exist and the token is accepted by the chosen tier1 (operator
  with Secret read; SYNTHESIS O2).
- O-IMG: `ghcr-cred` can pull the private `ghcr.io/pinax-network/substreams-backfills` package (operator).
- O-EGRESS: Kan pod egress to `172.20.114.2:443` / `172.19.114.2:443` (gate A3; SYNTHESIS O3).
- O-FINALIZED: the Pinax Base RPC answers `eth_getBlockByNumber("finalized")` (public RPC does, F24).
- O-ROWS: active-row counts at the seed per table (read-only SQL; SYNTHESIS O8) to replace the §12.1 ESTIMATE.
- O-PRUNE: `sgd2` history not pruned (needed for gate A5 differential; SYNTHESIS O4).
- O-K1: PR-K1 adopts `globalName` outputs and the §7.2 field names.

Needs user or infra decisions:

- D6 landing store `aerodrome_b` on dom153 (8–12 Ti), parking worker `graph-node-aerodrome-backfill-0` at 0 replicas
  and outside the agent allow-list, Graphman copy of `sgd2` (pause ~46 s).
- Approval to create the 1 Ti work PVC on dom153 (capacity gate evidence in K2-6).
- Endpoint choice for noop and backfill (kan same-DC preferred; riv equivalent via the shared bucket) and the tier2
  worker budget.
- Activation PR K2-6 and every run's approval resume are explicit human steps.

---

## Appendix A. YAML skeletons

### A.1 Library (abbreviated; scripts live in `base/lib/`)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: WorkflowTemplate
metadata:
  name: substreams-graph-node-backfill
  namespace: subgraphs-backfill
  labels:
    app.kubernetes.io/name: substreams-graph-node-backfill
    app.kubernetes.io/part-of: subgraphs-backfill
    backfills.pinax.network/role: generic-library
spec:
  entrypoint: refuse-direct-submission
  serviceAccountName: substreams-graph-node-backfill-runner
  templates:
    - name: refuse-direct-submission
      container:
        image: python:3.13.5-alpine3.22@sha256:f1a962d8ffa50b2006b72b4713a09a89e57def2d28ac28a36900bc070a00db61
        command: [python3, -c, "import sys; print('submit a per-target wrapper WorkflowTemplate'); sys.exit(2)"]
    - name: backfill
      dag:
        tasks:
          - { name: validate-parameters, template: production-preflight-parameters }
          - { name: preflight, dependencies: [validate-parameters], template: production-preflight }
          - { name: approve-production-write, dependencies: [preflight], template: production-approval }
          - { name: prepare-seed, dependencies: [approve-production-write], template: production-prepare-seed }
          - { name: load, dependencies: [prepare-seed], template: production-load }
          - { name: verify, dependencies: [load], template: production-verify }
      outputs:
        parameters:
          - name: production-evidence
            globalName: production-evidence
            valueFrom: { parameter: "{{tasks.verify.outputs.parameters.production-evidence}}" }
    - name: production-approval
      suspend: {}
    - name: production-preflight-parameters
      activeDeadlineSeconds: 300
      volumes:
        - { name: backfill-lib, configMap: { name: substreams-graph-node-backfill-lib, defaultMode: 0555 } }
      container:
        image: python:3.13.5-alpine3.22@sha256:f1a962d8ffa50b2006b72b4713a09a89e57def2d28ac28a36900bc070a00db61
        command: [python3, -B, /backfill-lib/validate_params.py, --target, /target/target.json, --out, /tmp/validated.json]
        env:
          - { name: BF_TARGET_ID, value: "{{workflow.parameters.target-id}}" }
          - { name: BF_DEPLOYMENT, value: "{{workflow.parameters.deployment}}" }
          - { name: BF_NOOP_EVIDENCE, value: "{{workflow.parameters.noop-evidence}}" }
          # … one BF_* per §5 parameter
        volumeMounts:
          - { name: backfill-lib, mountPath: /backfill-lib, readOnly: true }
          - { name: target, mountPath: /target, readOnly: true }        # wrapper volume
        resources: { requests: { cpu: 50m, memory: 64Mi }, limits: { cpu: 500m, memory: 256Mi } }
      outputs:
        parameters: [ { name: validated, valueFrom: { path: /tmp/validated.json } } ]
    - name: production-load
      metadata:
        labels:
          app.kubernetes.io/name: substreams-backfill-exporter
          app.kubernetes.io/component: exporter
          app.kubernetes.io/part-of: subgraphs-backfill
      retryStrategy:
        limit: "20"
        retryPolicy: Always
        expression: "lastRetry.status == 'Error' || asInt(lastRetry.exitCode) in [75, 137, 143]"
        backoff: { duration: 2m, factor: "1" }
      podSpecPatch: '{"containers":[{"name":"main","resources":{"requests":{"cpu":"{{workflow.parameters.load-cpu-request}}","memory":"{{workflow.parameters.load-memory-request}}"},"limits":{"cpu":"{{workflow.parameters.load-cpu-limit}}","memory":"{{workflow.parameters.load-memory-limit}}"}}}]}'
      volumes:
        - { name: backfill-lib, configMap: { name: substreams-graph-node-backfill-lib, defaultMode: 0555 } }
      initContainers:
        - name: stage-producer
          image: "ghcr.io/pinax-network/substreams-backfills@sha256:{{workflow.parameters.producer-image-digest}}"
          command: [/opt/producer/bin/producer, stage, --dest, /opt/staged-producer]
          volumeMounts: [ { name: staged-producer, mountPath: /opt/staged-producer } ]   # wrapper emptyDir
      container:
        image: "ghcr.io/pinax-network/substreams-graph-node-backfill@sha256:{{workflow.parameters.runtime-image-digest}}"
        command: [bash, -ec, "source /backfill-lib/backfill-lib.sh && bf_step_load"]
        env:
          - { name: BACKFILL_POD_NAME, valueFrom: { fieldRef: { fieldPath: metadata.name } } }
          - { name: NODE_NAME, valueFrom: { fieldRef: { fieldPath: spec.nodeName } } }
          - { name: PINAX_API_KEY, valueFrom: { secretKeyRef: { name: backfill-credentials, key: PINAX_API_KEY } } }
          - { name: SUBSTREAMS_API_TOKEN, valueFrom: { secretKeyRef: { name: backfill-credentials, key: SUBSTREAMS_API_TOKEN } } }
          - { name: POSTGRES_PASSWORD, valueFrom: { secretKeyRef: { name: backfill-credentials, key: POSTGRES_PASSWORD } } }
          # BF_* parameters as env, as above
        volumeMounts:
          - { name: production-work, mountPath: /work }
          - { name: staged-producer, mountPath: /opt/staged-producer, readOnly: true }
          - { name: backfill-lib, mountPath: /backfill-lib, readOnly: true }
          - { name: target, mountPath: /target, readOnly: true }
      sidecars:
        - name: exporter
          image: python:3.13.5-alpine3.22@sha256:f1a962d8ffa50b2006b72b4713a09a89e57def2d28ac28a36900bc070a00db61
          command: [python, -B, /app/backfill_exporter.py]
          env:
            - { name: NAMESPACE, valueFrom: { fieldRef: { fieldPath: metadata.namespace } } }
            - { name: WORKFLOW_TEMPLATE, value: "{{workflow.parameters.target-id}}-substreams-backfill" }
            - { name: WORKFLOW_NAME, value: "{{workflow.name}}" }
            - { name: RUN_MODE, value: production }
            - { name: WORK_ROOT, value: /work }
            - { name: NETWORK, value: "{{workflow.parameters.network}}" }
            - { name: PIPELINE, value: substreams-block-changes-copy }
            - { name: POLL_INTERVAL_SECONDS, value: "30" }
          ports: [ { containerPort: 9090, name: metrics } ]
          volumeMounts:
            - { name: backfill-exporter-source, mountPath: /app, readOnly: true }
            - { name: production-work, mountPath: /work, readOnly: true }
          # probes, securityContext and resources as V4 :873-889
    # production-preflight, production-prepare-seed, production-verify follow the same pattern (§8)
```

### A.2 Aerodrome wrapper

```yaml
apiVersion: argoproj.io/v1alpha1
kind: WorkflowTemplate
metadata:
  name: aerodrome-slipstream-base-substreams-backfill
  namespace: subgraphs-backfill
  labels:
    app.kubernetes.io/name: aerodrome-slipstream-base-substreams-backfill
    app.kubernetes.io/part-of: subgraphs-backfill
    backfills.pinax.network/target-id: aerodrome-slipstream-base
    subgraphs/backfill-role: inactive-production-copy
spec:
  entrypoint: main
  serviceAccountName: substreams-graph-node-backfill-runner
  parallelism: 1
  synchronization:
    mutexes: [ { name: substreams-graph-node-backfill-aerodrome-slipstream-base } ]
  imagePullSecrets: [ { name: ghcr-cred } ]
  nodeSelector:
    kubernetes.io/hostname: dom153
    infra.pinax.network/compute-tier: fast
    feature.node.kubernetes.io/cpu-cpuid.AVX2: "true"
  activeDeadlineSeconds: 2592000
  ttlStrategy: { secondsAfterCompletion: 2592000 }
  podGC: { strategy: OnWorkflowSuccess, deleteDelayDuration: 24h }
  metrics:
    prometheus:
      - name: substreams_graph_node_backfill_workflow_info
        help: "Generic Substreams Graph Node backfill (value is elapsed seconds)"
        labels:
          - { key: workflow, value: "{{workflow.name}}" }
          - { key: target_id, value: "{{workflow.parameters.target-id}}" }
          - { key: deployment, value: "{{workflow.parameters.deployment}}" }
          - { key: wf_status, value: "{{workflow.status}}" }
        gauge: { realtime: true, value: "{{workflow.duration}}" }
  arguments:
    parameters:
      - { name: target-id, value: aerodrome-slipstream-base }
      - { name: family, value: aerodrome-slipstream-base }
      - { name: deployment, value: QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV }
      - { name: network, value: base }
      - { name: chain-id, value: "8453" }
      - { name: substreams-endpoint, value: base.substreams.kan-prod-firehose-a.pinax.io:443 }
      - { name: target-shard, value: aerodrome_b }
      - { name: target-schema, value: replace-after-graphman-copy }
      - { name: expected-seed-block, value: "0" }
      - { name: expected-seed-hash, value: replace-with-64-hex-seed-hash }
      - { name: target-block, value: "0" }
      - { name: target-hash, value: replace-with-64-hex-target-hash }
      - { name: segment-size, value: "50000" }
      - { name: runtime-image-digest, value: replace-with-engine-generic-runtime-digest }
      - { name: producer-image-digest, value: replace-with-producer-digest }
      - { name: noop-workflow, value: replace-with-succeeded-noop-workflow }
      - { name: noop-evidence, value: "{}" }
      - { name: noop-evidence-sha256, value: replace-with-64-hex }
      - { name: approval-reference, value: replace-with-issue-reference }
      # … every §5 parameter, defaults equal to target.json (T-DEFAULTS-PINNED)
  volumes:
    - { name: production-work, persistentVolumeClaim: { claimName: substreams-backfill-aerodrome-slipstream-base-work } }
    - { name: target, configMap: { name: substreams-backfill-target-aerodrome-slipstream-base } }   # hashed by kustomize
    - { name: backfill-exporter-source, configMap: { name: substreams-backfill-exporter, defaultMode: 0555 } }
    - { name: staged-producer, emptyDir: { sizeLimit: 2Gi } }
  templates:
    - name: main
      steps:
        - - name: backfill
            templateRef: { name: substreams-graph-node-backfill, template: backfill }
```

---

## Appendix B. Read-only verification performed for this design

- Read the files cited in §1–§2; `git log` on the noop worktree (no commits).
- `KUBECONFIG=~/.kube/kan-subgraphs-a-sa.yaml kubectl get node dom153 -o json` and `kubectl describe node dom153`
  (pod listing is Forbidden for this SA).
- VictoriaMetrics `P4169E866C3094E38`: dom153 request sums and top pods; `kubelet_volume_stats_capacity_bytes` in
  `subgraphs-backfill`.
- Public Base RPC: `eth_chainId`; `eth_getBlockByNumber` for `latest`, `safe`, `finalized`; NPM `totalSupply()` and
  `tokenByIndex(last)` at `0x2117f00` (34,701,056).
- `gh api` of `streamingfast/firehose-ethereum` go.mod at `v2.24.1` and `streamingfast/substreams` sources at
  `5ed941ac91dc`; local `git grep` in `~/Github/substreams` (v1.22.0) and the Go module cache (v1.18.4).
- Argo v4.0.7 controller source in `scratchpad/ext/argo-workflows` (read-only).
- Local `argo lint --offline --strict` (v4.0.7) on prototypes in `scratchpad/design/lint-proto/` and
  `scratchpad/design/kustomize-proto/`; local `kustomize build` (v5.8.1) of the nameReference prototype.
