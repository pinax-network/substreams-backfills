# k8s-subgraphs backfill deployment stack — survey for an Aerodrome Slipstream Base noop + backfill

Survey date: 2026-10-20. Read-only.

Sources:
- `k8s-subgraphs`: detached snapshot at `origin/main` `4da0b37cb9edf80fd3badd752ceade8fb09424dc`
  (`scratchpad/ro/k8s-subgraphs`). Paths below are relative to that repo unless prefixed.
- `engine` = `pinax-network/substreams-graph-node-backfill` snapshot (`scratchpad/ro/engine`).
- `token-api` = `k8s-token-api-workflows` snapshot (`scratchpad/ro/k8s-token-api-workflows`).
- Live reads: `kubectl` with `~/.kube/kan-subgraphs-a-sa.yaml` (get/list/logs only) and
  VictoriaMetrics `P4169E866C3094E38`. One `kubectl exec … psql SELECT` against the Kan
  primary was refused by the permission classifier. The registry state of the Aerodrome copy
  therefore stays **unverified** (see §3.6).

Labels used throughout:
- **VERIFIED**: I read the code or manifest, or observed it live.
- **CLAIM**: a doc or comment says it, and I did not independently prove it.

---

## 0. Executive summary

1. **No existing WorkflowTemplate can serve Aerodrome without edits.** All 7 Kan backfill
   WorkflowTemplates are Uniswap V4 Base specific. The V4 identity is either asserted in shell
   (`test "$deployment" = Qmbsc6X…`, shard `univ4base_b`, source `sgd1246`, writer Deployments
   `graph-node-basegiant-0` / `graph-node-univ4base-copy-0`) or baked into paths
   (`/opt/backfill/spkg/uniswap-v4-base-store-state-reducer-v0.5.0.spkg`,
   `adapters/uniswap-v4-base/…`). Only the outer *shape* is reusable: preflight → approval →
   prepare-seed → pipelined load (with exporter sidecar) → verify, plus mutexes, retries and
   evidence sealing.
2. **There is no "noop" today.** The closest equivalents are:
   - the in-pod `BACKFILL_PREWARM_SUBSTREAMS=1` per-segment prewarm, which runs the identical
     `substreams-native` request into `/dev/null`;
   - the `cache-last-block` guard parameter, which only *asserts* that the cache is warm.

   The token-api repo has a proven, generic Argo noop pattern: `substreams sink noop` or
   `substreams-sink-noop --noop-mode`, with sub-range fan-out through `withParam`. It can be
   ported.
3. **The engine's default Substreams endpoint is dead.** The engine default
   `base-substreams-tier1-prod.kan-sst2.pinax.io:443` no longer resolves in DNS (VERIFIED).
   k8s PR #879 moved certification to `base.substreams.riv-prod-firehose-a.pinax.io:443`. The
   production template never sets `ENDPOINT`, so any new template **must** pass the endpoint
   explicitly.
4. **The Aerodrome deployment today:**
   - `QmasYjyp…` is active on `subgraphshard_b/sgd2` (Postgres `postgres-2`, 12.1 TB used),
     indexed by `graph-node-chain-base-0` (node `index_node_chain_base_0`).
   - Its head is 34,726,435 against Base head 52,867,735 (VERIFIED, VM 2026-10-20).
   - A dedicated store `aerodrome_a` (`aerodrome-postgres`, 4 Ti on **dom157**) holds an
     *inactive native copy* `sgd5311` created 2026-09-21 at checkpoint 30,843,266 (CLAIM, doc).
     That DB is static at ~1.08 TB for 30 days (VERIFIED, metrics), and the dedicated worker
     `graph-node-aerodrome-0` is running but idle (VERIFIED, logs). Whether the copy is
     complete is unverified.
5. **Adding Aerodrome templates to the existing `subgraphs-operations/backfill/kan` overlay will
   break CI.** `subgraphs-operations/backfill/tests/test-contract.sh` asserts *global string
   counts* over the whole rendered overlay. Examples: graph-node image ×19, `memory: 256Gi` ×8,
   `name: WORKFLOW_NAME` ×9, `RUST_LOG` ×5. It also asserts exact strings in `base/rbac.yaml`.
   Put the generic and Aerodrome work in a **separate kustomize tree + Flux Kustomization**, or
   update the V4 contract counts deliberately.
6. **The landing store has to be on dom153.** Kan policy forbids new or replacement volumes on
   dom157, and dom157 has 0.62 TiB of allocation allowance left. The existing `aerodrome_a`
   (dom157, 4 Ti) cannot hold a ~3.5 TB-class head dataset under the 70% fill gate. The V4
   pattern to copy is: a new dom153 store (`[store.aerodrome_b]`) plus a zero-replica parking
   or copy worker on dom153.
7. **Engine prerequisites block the backfill template but not the noop.**
   - `engine:scripts/check-compatibility-contract.sh:7` hardcodes the
     `adapters/uniswap-v4-base/compatibility.json` contract.
   - `capture-direct-postgres-seed.sh:27` defaults `DEPLOYMENT_ID` to V4.
   - Only one adapter (`uniswap-v4-base`) exists.

   The noop WorkflowTemplate is runnable as soon as an Aerodrome SPKG URL and SHA-256 exist.
   The backfill WorkflowTemplate can be written now, but can only run after an engine release
   carries an Aerodrome adapter.

---

## 1. Inventory of WorkflowTemplates (namespace `subgraphs-backfill`, Kan)

### 1.1 Overview

Rendered from `subgraphs-operations/backfill/kan`. The live cluster has the same 7 plus one
out-of-band template, `uniswap-v4-base-sgd2-overlap-replay-candidate`, which is not in git
(VERIFIED `kubectl get workflowtemplates`). There have been no Workflows in the last 30 days:
`backfill_job_committed_head_block` returns no series in 30d, and no `Workflow` objects exist.
The V4 lane is idle.

| WorkflowTemplate (file) | Purpose | Entrypoint / DAG | SA | Mutexes | Node | PVC | Approval gates | V4-hardcoded? |
|---|---|---|---|---|---|---|---|---|
| `uniswap-v4-base-substreams-backfill` (`base/workflow-template.yaml`) | Original disposable scratch proof: graphman dump of paused `sgd1246`, restore into isolated scratch PG, direct COPY or Parquet fallback | `direct-backfill`: preflight>approve-dump>dump>clone>approve-scratch-restore>migrate-scratch>initialize-scratch-chain>restore>capture-direct-seed>direct-load>verify. Also `backfill` (Parquet) | `substreams-backfill-runner` | `uniswap-v4-base-substreams-backfill` | `compute-tier=fast` + kan patch `hostname=dom157` | `substreams-backfill-work` (1536Gi dom157) | 2× `approval` (suspend) | **Yes**: preflight asserts `graph-node-basegiant-0` replicas 0 (`base/workflow-template.yaml:197-199`), execs into `univ4base-postgres-0` (`:202`), Base RPC (`:190`), chain id 8453 and genesis (`:801-802`), V4 SPKG path (`:494`), `pools`/`tokens` GraphQL (`:550`) |
| `uniswap-v4-base-substreams-production-backfill` (`kan/production-workflow-template.yaml`) | Advances the **inactive, paused** Graphman copy `univ4base_b/sgd5303` with pipelined Store-state COPY | preflight>approve-production-write>prepare-seed>load>verify | runner | `uniswap-v4-base-substreams-production-backfill` | `fast` + `dom153` | `substreams-backfill-production-work` (2Ti, PV on dom153) | `production-approval` | **Yes, heavily**: deployment and shard asserted (`:130-131`), digest (`:140`), registry tuple `univ4base_b\|f\|index_node_basegiant_0\|t` (`:197-198`), active source `univ4base_a/sgd1246` (`:199-203`), PGHOST (`:163`), 8 TiB capacity contract (`:215-223`), SPKG and adapter paths (`:112-116`, `:816`) |
| `uniswap-v4-base-compute-only` (`kan/compute-only-workflow-template.yaml`) | DB-free compute benchmark: seed checkpoint → 2×100K sealed COPY spools | preflight>compute>compare (`when` control≠none) | runner | `uniswap-v4-base-substreams-compute-only` | `dom157` | `substreams-backfill-work` | none | **Yes**: allow-listed digests (`:100-193`), fixed seed and blocks 33,374,154–33,574,154 (`:204-206`, `:374-430`), fixed checkpoint hashes (`:454`) |
| `uniswap-v4-base-sgd2-performance-replay` (`kan/replay-workflow-template.yaml`) | Destructive replay on disposable scratch `sgd2` | preflight>approve-sgd2-rewind>guard-after-approval>rewind-and-pause>prepare-output>load>verify | runner | shares `uniswap-v4-base-substreams-backfill` | `dom157` | work | `replay-approval` | Yes (sgd2, seeds, hashes in params `:30-61`) |
| `uniswap-v4-base-sgd2-overlap-replay` (`kan/overlap-replay-workflow-template.yaml`) | Overlapped compute+COPY and sealed-spool SQL replay experiments | `overlap-experiment` and `sql-replay-experiment`; `onExit: restore-postgres-maintenance` | runner | shares scratch mutex | `dom157` | work | `approval` | Yes |
| `uniswap-v4-base-terminal-certification` (`kan/terminal-certification-workflow-template.yaml`) | Terminal acceptance bundle: exact-prefix oracle, physical parity, NUL audit, lifecycle (continuation/restart/rewind/replay), certificate | 50+ step DAG; `onExit: terminal-cleanup` | runner | 3 mutexes (terminal, scratch, production) | `fast` + `dom153` | production-work | none after preflight (needs `operator-approval-reference` param) | Yes |
| `uniswap-v4-base-v4-reference-replay` (`kan/v4-reference-replay-workflow-template.yaml`) | Pending-publication reference replay | `reference-replay`; `onExit: restore-scratch` | `substreams-backfill-v4-runner` (**the SA's RBAC file is intentionally not in the kustomization**, `kan/v4-reference-replay-rbac.yaml:1-2`) | compute + scratch mutexes | `dom157` | work | `approve-sgd2-rewind` | Yes |

### 1.2 Parameter lists (verbatim defaults)

**Scratch `uniswap-v4-base-substreams-backfill`** (`base/workflow-template.yaml:25-44`). The Kan
overlay replaces the whole list (`kan/kustomization.yaml:60-83`):

```
deployment=Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB  source-schema=sgd1246
expected-source-block="0"(kan:"32374154")  expected-source-hash  target-block  target-hash
runtime-image-digest  cache-last-block="49477581"  segment-size="100000"
performance-experiment="false"  experiment-id=none  wal-compression=inherit
substreams-parallel-workers="500"  poi-workers="32"  poi-batch-size="4"
subgraph-name=prototype/uniswap-v4-base-substreams(-kan)
```

**Production** (`kan/production-workflow-template.yaml:28-40`):

```
deployment=Qmbsc6X…  target-shard=univ4base_b  target-schema=replace-after-graphman-copy
expected-seed-block="0"  expected-seed-hash  target-block="49477581"  target-hash=9d2c…bd7f
cache-last-block="49477581"  segment-size="100000"  compatibility-profile=graph-node-exact
runtime-image-digest=dce46853…c8afd
```

**Compute-only** (`kan/compute-only-workflow-template.yaml:29-41`):

```
experiment-id  control-experiment-id  runtime-image-digest  poi-workers  poi-batch-size
working-checkpoint  long-lived  asynchronous-spool-writers  asynchronous-spool-queue-buffers
protobuf-decode-ahead  allocator
```

**Terminal certification** (`kan/terminal-certification-workflow-template.yaml:31-58`) includes
the only **URL + SHA pinned SPKG** pattern in the repo:

```
audit-spkg-url=https://github.com/pinax-network/substreams-v4-subgraph/releases/download/v0.4.1/uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg
audit-spkg-sha256=c2470ab8…  audit-module-hash=c58cac15…
```

The template fetches it with `curl -fsSL --retry 5` and checks it with `sha256sum -c`
(`:974-977`).

### 1.3 Images (VERIFIED in the templates)

- **Runtime:** `ghcr.io/pinax-network/substreams-graph-node-backfill@sha256:<digest>`. The
  image is private and needs `imagePullSecrets: ghcr-cred`
  (`base/workflow-template.yaml:16-17`). Production pins
  `dce46853dcde556c5d8a73c02737e01820739a0f0aa67f8b75505425834c8afd` and also re-verifies 5
  in-image file SHA-256s (`kan/production-workflow-template.yaml:85-91`).
- **Graph Node / graphman:** `graphprotocol/graph-node:v0.44.0@sha256:c14c6d8e…` (scratch
  lanes). The cluster itself runs **v0.45.0** (`core/kan/kustomization.yaml` images transformer,
  lines ~123-130: "v0.45.0 carries no DB migrations").
- **Others:** `postgres:16.11-alpine@sha256:4327b9fd…`, `busybox:1.36` (sometimes
  digest-pinned), and the exporter sidecar `python:3.13.5-alpine3.22` (digest-pinned in
  compute-only).

### 1.4 Secrets

`backfill-credentials` keys: `PINAX_API_KEY`, `SUBSTREAMS_API_TOKEN`, `POSTGRES_PASSWORD`
(`base/credentials.example.yaml:11-13`).

- The docs say the stream token must differ from the RPC key
  (`docs/substreams-graph-node-backfill.md:88-95`, PR #654). CLAIM.
- `ghcr-cred` is the image pull secret.
- Neither is committed. The operator SA cannot list Secrets in `subgraphs-backfill`
  (VERIFIED Forbidden), so their **current existence is unverified**. They existed when V4 ran
  in Aug–Sep (runs succeeded).

### 1.5 PVCs (VERIFIED live)

| PVC | Size | Node | Claim |
|---|---|---|---|
| `substreams-backfill-work` | 1536Gi | dom157 | scratch, compute and replay |
| `substreams-backfill-production-work` | 2Ti | dom153 | V4 production checkpoints and evidence; prune disabled |
| `pgdata-substreams-backfill-postgres-0` | 1Ti | dom157 | 597 GB used |

All use `local-storage` (TopoLVM, WaitForFirstConsumer, expandable).

### 1.6 Mutexes and parallelism

- Every template sets `parallelism: 1` and one or more named mutexes.
- The V4 production `load` additionally refuses to recover a stale lock while any *other* live
  pod with label `app.kubernetes.io/name=substreams-backfill-exporter` mounts
  `substreams-backfill-production-work` (`kan/production-workflow-template.yaml:495-507`).
- **A new target must use its own PVC** so it neither trips nor weakens that guard.

### 1.7 RBAC

`base/rbac.yaml`:
- **Runner SA** `substreams-backfill-runner`, Role in `subgraphs-backfill`:
  - `workflowtaskresults` create/patch;
  - `pods` list;
  - `deployments` get on `uniswap-v4-fastpath-indexer|query`.
- **Source-reader Role in `subgraphs`:**
  - `deployments` get on `graph-node-basegiant-0, graph-node-univ4base-copy-0` (line 54);
  - `pods` get and `pods/exec` create on `univ4base-postgres-0` only (lines 56-63).
- **Exporter Role:** `workflows` get/list/watch (`kan/exporter-rbac.yaml`).
- **Contract test pins:**
  - the exact `resourceNames:` strings (`tests/test-contract.sh:1523-1524`);
  - exactly one `patch` verb (`:1525`);
  - no update/delete verbs.

---

## 2. V4 production flow end to end

### 2.1 Cache / prewarm (closest thing to "noop")

- **No separate cache workflow exists.** Templates carry `cache-last-block` and preflight only
  asserts `target ≤ cache_last` (`base/workflow-template.yaml:157`,
  `kan/production-workflow-template.yaml:143`).
- **Production `load` sets** (`kan/production-workflow-template.yaml:452-464`):
  - `BACKFILL_PREWARM_SUBSTREAMS=1`
  - `BACKFILL_PREWARM_ATTEMPTS=128`
  - `BACKFILL_PREWARM_RETRY_SECONDS=5`
  - `SUBSTREAMS_LIMIT_PROCESSED_BLOCKS=50000000`
  - `SUBSTREAMS_PARALLEL_WORKERS=500`
- **The engine** (`engine:scripts/compute-postgres-segment.sh:147-193`) then runs the identical
  `substreams-native -e $endpoint $spkg $module -s start -t end+1 -H X-Substreams-Parallel-Workers:N`
  into `/dev/null` until it succeeds, before the real reducer run (`:195-205`).
- **Why it was added** (PR #847, CLAIM): cold 64-shard Store graphs surfaced missing immutable
  Store objects one by one and burned all 20 outer Argo retries.
- **So in V4, cache warming is per segment and serialized with loading.** A dedicated
  parallel noop run would remove this from the critical path.

### 2.2 Compute-only

`uniswap-v4-base-compute-only` mounts the seed read-only, gets **only**
`SUBSTREAMS_API_TOKEN` (`kan/compute-only-workflow-template.yaml:502-503`), and runs
`scripts/compute-postgres-segment.sh` / `compute-postgres-plan.sh` to sealed
`segment-*.ready/` spools. There are no PG credentials. It is a benchmarking lane, not part of
production.

### 2.3 Spool + load into the stopped clone (production)

**Landing preparation** — GitOps plus manual graphman (`docs/substreams-graph-node-backfill.md:1360-1422`):

1. Dedicated store `univ4base-backfill-postgres` (dom153, 8 Ti,
   `core/kan/univ4base-backfill-postgres.yaml:58-59`), `[store.univ4base_b]`
   (`core/kan/graph-node-config.yaml:82-84`).
2. Copy worker `graph-node-univ4base-copy-0` (dom153, `GRAPH_STORE_BATCH_WORKERS=8`), currently
   at replicas 0 (VERIFIED live).
3. `graphman copy create --offset 0 … univ4base_b index_node_univ4base_copy_0`.
4. Then `graphman reassign … index_node_basegiant_0` (a zero-replica node) and `graphman pause`.
5. GitOps scales the copy worker to 0.

**Workflow `production-preflight`** (`:71-295`) checks:
- the runtime binary SHAs;
- the compatibility contract and `verify-store-state-package.sh`;
- the target hash via Base RPC;
- `kubectl get deployment` replicas = 0 for both writers;
- head/health on the target;
- the primary registry tuple and that the active source is untouched;
- `pg_tablespace_size ≤ 7 TiB`;
- resume consistency.

**`production-approval` (suspend), then `production-prepare-seed`** (`:297-381`, retries 3):
- `capture-direct-postgres-seed.sh` captures the active-state checkpoint from the **stopped
  target**;
- the result is SHA-256 sealed.

**`production-load`** (`:383-889`, retries 20, 256Gi request / 640Gi limit):
- quarantine and stale-lock recovery;
- a per-segment preflight script that re-asserts writer exclusion, registry and capacity
  (`:752-802`);
- `run-pipelined-postgres-backfill.sh` (lookahead compute overlapped with atomic 100K-block
  COPY transactions, `BACKFILL_ASYNC_SPOOL_WRITERS=1`, rolling checkpoint retention);
- a second no-op resume run, then `audit-vid-sequences.sh` (`:823-835`);
- an exporter sidecar reading `/work` read-only (`:854-889`).

**`production-verify`** (`:891-1062`): head/hash, checkpoint SHA and size, contiguous journal,
no-op resume, 20 sequences. It then writes `production-evidence.json`
(`status:"candidate-ready", activation_performed:false`).

### 2.4 Certification

`uniswap-v4-base-terminal-certification` (`docs/substreams-graph-node-backfill.md:1476-1570`)
covers:
- an exact-prefix oracle on disposable `sgd2`;
- physical/POI parity;
- a NUL audit over the full range using a separately released audit SPKG fetched by URL and
  SHA-256;
- GraphQL;
- continuation, restart, rewind and replay lifecycle;
- a format-v2 acceptance bundle, re-verified by a separate container.

### 2.5 Landing

Landing is **not automated**. Activation is a manual `graphman copy activate` after
certification; rollback is `graphman copy activate <dep> univ4base_a`
(`docs/substreams-graph-node-backfill.md:1566-1570`). Serving nodes must be rolled one at a
time to load the new store before activation (`:1360-1368`).

### 2.6 Substreams endpoint, auth and SPKG pinning (VERIFIED)

**Auth**
- Env `SUBSTREAMS_API_TOKEN` from `backfill-credentials`. Every engine script requires it
  (`engine:scripts/compute-postgres-segment.sh:15`, `run-pipelined-postgres-backfill.sh:12`).

**Endpoint**
- No k8s template sets `ENDPOINT` for production, so the engine default
  `base-substreams-tier1-prod.kan-sst2.pinax.io:443` applies (`engine:…/compute-postgres-segment.sh:25`
  and 6 other scripts).
- That hostname **no longer resolves** (dig, 2026-10-20).
- PR #879 says tier1 moved to `base.substreams.riv-prod-firehose-a.pinax.io:443`. That host
  resolves to private `172.19.114.2`, and terminal certification hardcodes it
  (`kan/terminal-certification-workflow-template.yaml:737,980`).
- The public `base.substreams.pinax.network` also resolves.
- **Cache-sharing note (inference, standard Substreams behaviour):** caches are per tier2
  state store. The noop must hit the same endpoint, and therefore the same cache, that the
  backfill will use.

**Parallel workers**
- Header `X-Substreams-Parallel-Workers:500` (`SUBSTREAMS_PARALLEL_WORKERS`, default 500 in
  `compute-postgres-segment.sh:26`).
- The scratch template asserts it equals 500 (`base/workflow-template.yaml:154`).

**SPKG**
- Baked into the runtime image at `/opt/backfill/spkg/…`.
- Bound by `adapters/uniswap-v4-base/compatibility.json` / `store-state-v0.5.0.json`, via
  `check-compatibility-contract.sh` and `verify-store-state-package.sh`
  (`kan/production-workflow-template.yaml:92-116`).
- The engine accepts overrides `DIRECT_POSTGRES_SPKG` / `STORE_STATE_SPKG`,
  `DIRECT_POSTGRES_MODULE`, `SUBSTREAMS_INPUT_MODE` and `DIRECT_POSTGRES_COMPATIBILITY_CONTRACT`
  (`engine:scripts/compute-postgres-segment.sh:27-35`).
- But `check-compatibility-contract.sh:7` hardcodes the V4 contract, so the overrides are not
  usable end to end yet.

---

## 3. Kan cluster specifics

### 3.1 Namespace and GitOps wiring (VERIFIED)

**Namespace `subgraphs-backfill`** (`subgraphs-operations/backfill/base/namespace.yaml`) is
created by Flux Kustomization `subgraphs-backfill` (`deploy/kan/backfill.yaml:1-28`):
- `path: subgraphs-operations/backfill/kan`
- `dependsOn: subgraphs-core`
- `prune: true`
- `wait: false`
- health check only on the scratch PG StatefulSet

It is listed in `deploy/kan/kustomization.yaml:15`. The fleet tenant selects `deploy/kan`
(header comment `:1-6`).

**Argo** (`platform/argo/kan/`, Flux Kustomization `subgraphs-argo`, `deploy/kan/argo.yaml`):
- HelmRelease `argo-workflows` chart `1.0.19` (`release.yaml:13`); controller image
  `quay.io/argoproj/workflow-controller:v4.0.7` (VERIFIED live);
- **controller-only**: `server.enabled: false`, no archive and no artifact repository
  (`values.yaml:1-31`), so **Argo artifacts cannot pass the SPKG between steps**;
- `workflowNamespaces: [subgraphs-backfill, subgraphs-transplant, subgraphs-fullsync]`;
- metrics plus ServiceMonitor enabled; `--qps=40 --burst=60`.

**Operator access** (VERIFIED with `kubectl auth can-i`, SA `denis-cli`, namespace `subgraphs-backfill`):

| Action | Allowed |
|---|---|
| create/patch `workflows` (submit, resume suspends) | yes |
| get `pods/log` | yes |
| list `pods` | yes |
| create `workflowtemplates` | **no** → templates must arrive through GitOps |
| create `pods/exec` | no |
| list Secrets, SA, Role | **no** |

### 3.2 Nodes and storage (VERIFIED live, plus `docs/HARDWARE.md:84-100` from 2026-10-06)

| Node | Tier label | Allocatable | Thin pool used | Notes |
|---|---|---|---|---|
| dom152 | `compute-tier=slow` | 128 CPU / 511 GiB | 1.36% | Zen 2; cold stores only; no head-critical work (`docs/pre-wave-capacity-gate.md`) |
| dom153 | `compute-tier=fast` | 56 CPU / ~1 TiB | 7.33% (51.8 TiB free) | V4 production lane, hot stores + their workers |
| dom157 | `compute-tier=fast` | 56 CPU / ~1 TiB | 63.35%, **0.622 TiB allowance** | **No new or replacement volumes** (`AGENTS.md:84-87`, `docs/pre-wave-capacity-gate.md:13-18`); ~99% CPU requested (scratch uses 10m requests) |

- All three nodes are labelled `infra.pinax.network/storage-local-ssd=true` and have no taints.
- StorageClasses: `local-storage` (default; TopoLVM; Delete; WaitForFirstConsumer; expandable)
  and `parquet-local-retain` (Retain).
- **The capacity gate applies to "a backfill target"** (`docs/pre-wave-capacity-gate.md:3-5`):
  post-wave pool <70% and volume fill <70%.

### 3.3 Postgres for landing

- **Scratch:** `substreams-backfill-postgres` StatefulSet in `subgraphs-backfill`
  (`base/postgres.yaml`). PG 16.11, databases `graph` (isolated primary) and `graph_backfill`
  (shard `backfill_a`), 1 Ti, pinned to dom157 via kan patch (`kan/kustomization.yaml:46-59`).
  It is wired only to an isolated scratch Graph Node config (`base/graph-node-config.yaml:38-72`).
- **Production pattern:** a *dedicated* StatefulSet in namespace `subgraphs` that is a real
  Graph Node shard in the shared primary (`[store.univ4base_b]`). This forces:
  1. the #105 invariant: every serve/status node must list the store
     (`scripts/shard-config-drift.sh` Check B fails a `*postgres*` StatefulSet without a store);
  2. `core/kan/tests/primary-store-baseline.json` must list the new store
     (`core/kan/tests/test-single-copy-query.cjs:39-40`);
  3. a prune-disabled PVC;
  4. a dom153 pin.
- **No NetworkPolicies** exist in `core/` or `subgraphs-backfill`. Workflow pods reach
  `*.subgraphs.svc` Postgres directly, as V4 does (`PGHOST=univ4base-backfill-postgres-0…`).

### 3.4 Base chain stack and `subgraphshard_b` (VERIFIED)

- **`[chains.base]`:** shard `blockcacheshard_a`; Firehose
  `https://base.firehose.pinax.network:443` plus web3 `https://base.rpc.pinax.network/v1/${PINAX_API_KEY}/`
  (`core/kan/graph-node-config.yaml:260-264`). Ingestor `index_node_ingestor_0`.
- **`[store.subgraphshard_b]`** → `postgres-2.postgres` (`:31-33`); live PVC 12.1 TB used.
- **Placement rule** `network = "base"` → shard `subgraphshard_b`, indexer
  `index_node_chain_base_0` (`:221-224`).
- **`graph-node-chain-base-0`** is defined in `core/base/graph-node-pool.yaml:475-528`
  (node_id `index_node_chain_base_0`, base image v0.44 overridden to v0.45). The Kan patch sets
  request 2 CPU / 10Gi and limit 6 / 32Gi, and its comment says it carries ~127–141 assignments
  (`core/kan/kustomization.yaml` patch at `target graph-node-chain-base-0`). Live pod on
  **dom152**, image v0.45.0.

### 3.5 Where Aerodrome lives now

**Active copy (VERIFIED)**
- `deployment_head{deployment="QmasYjyp…"}`: only one series, `shard=subgraphshard_b`, pod
  `graph-node-chain-base-0-…`, value **34,726,435**.
- Base head 52,867,735 (2026-10-20).
- Registry `subgraphshard_b/sgd2`, node `index_node_chain_base_0` (`fleet/observed-2026-09-08.json:799`).
- **ETA estimate:** with the task's measured ~140k blocks/day net, closing 18.14M blocks takes
  **~130 days**.

**Dedicated landing (`core/kan/kustomization.yaml:103-104`)**
- `aerodrome-postgres` (`core/kan/aerodrome-postgres.yaml`): PG16, 16GB shared_buffers, 4Ti
  `local-storage`, no node pin. It is live on **dom157**. 1.14 TB used per kubelet; `graph` DB
  1.076 TB, flat for 30 days.
- `[store.aerodrome_a]` (`core/kan/graph-node-config.yaml:137-139`).
- Worker `graph-node-aerodrome-0` (`core/kan/graph-node-aerodrome.yaml`): `node_id
  index_node_aerodrome_0`, 4 CPU / 32Gi, `GRAPH_STORE_BATCH_WORKERS=2`, pool_size forced to 4.
  Replicas 1, live on dom152. Logs since 2026-10-16 show no subgraph activity; the worker is
  idle.

**Copy history** (`docs/kan-postgres2-offload-2026-09-21.md:103-114`, CLAIM)
- Inactive native copy `aerodrome_a/sgd5311` was created 2026-09-21 with copy checkpoint
  30,843,266, offset 1343, `on-sync=none`, assigned to `index_node_aerodrome_0`.
- The doc also says Aerodrome is an "incomplete index: successful physical copy does not mean
  chain-head catch-up" (`:53-55`).

**Indexer agent**
- `index_node_aerodrome_0` and `index_node_chain_base_0` are both in
  `INDEXER_AGENT_INDEX_NODE_IDS` (`subgraphs-indexers/pinax2/kan/kustomization.yaml:88`).
- The agent runs default **auto** deployment management (no `INDEXER_AGENT_DEPLOYMENT_MANAGEMENT`
  set on pinax2/kan).
- `subgraphs-alerts/base/backfill-flags.yaml:14-23` (CLAIM, verified 2026-08-31 by its author):
  `graphman pause` is undone by indexer-agent within minutes. A durable stop needs a
  zero-replica dedicated worker.

**Backfill flag**
- `subgraphs:deployment_backfill_only` already lists `QmasYjyp…` with value 1, **but labels it
  `protocol: uniswap-v3`, "Uniswap V3 (base) — 285k/day, ETA ~180d"**
  (`subgraphs-alerts/base/backfill-flags.yaml:55-61`).
- That label/comment is wrong for Aerodrome Slipstream (a V3 fork) and should be corrected.
  Set it to 2 ("Backfilling") during the run.

**Deployment identity** (`/Users/denis/Github/substreams-backfills/aerodrome-slipstream-base/README.md:10-17`):
- Factory `0x5e7b…809a` from 13,843,704;
- NonfungiblePositionManager `0x8279…5b72` from 13,843,719;
- **no graft**.

So a from-start build without a Graph Node seed is semantically possible. The V4 "seed from an
existing copy" rule exists because V4 was graft-derived (`docs/substreams-graph-node-backfill.md:28-33`).

### 3.6 Unverified, and how to verify

**Is the `sgd5311` copy complete, and what is its registry state?** Run these read-only SQL
queries on `postgres-0` (primary):

```sql
SELECT d.id, d.name, d.shard, d.active, a.node_id, a.paused_at IS NOT NULL
FROM public.deployment_schemas d
LEFT JOIN subgraphs.subgraph_deployment_assignment a USING (id)
WHERE d.subgraph = 'QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV';

SELECT * FROM active_copies;
```

Or run `graphman copy status sgd5311` from a Graph Node pod. My exec attempt was blocked by the
permission classifier.

**Do `backfill-credentials` and `ghcr-cred` still exist in `subgraphs-backfill`, and is
`SUBSTREAMS_API_TOKEN` accepted by `riv-prod-firehose-a`?** These need an operator with
Secret-read access.

**Is `172.19.114.2` (riv-prod-firehose-a Substreams) reachable from Kan pods?** PR #879 implies
yes, but it is untested today.

---

## 4. Repo conventions for adding workflows

### 4.1 Layout

Operations live under `subgraphs-operations/<area>/{base,kan,riv,tests,examples}`
(`subgraphs-operations/README.md`). Each Flux entrypoint is one `deploy/kan/<name>.yaml`
Kustomization CR plus a line in `deploy/kan/kustomization.yaml`.

### 4.2 Generators

The Kan backfill overlay uses:
- `configMapGenerator` with `disableNameSuffixHash: true` for the exporter scripts
  (`kan/kustomization.yaml:20-35`);
- JSON6902 patches that address **templates by numeric index**
  (`/spec/templates/2…14/…`, `:91-225`).

Comments in the base template warn to keep new templates at the end
(`base/workflow-template.yaml:722-723, 851-854`). This is fragile. Never insert into the base
template.

### 4.3 Examples

The repo convention for "live Workflow objects" is **never commit a live Workflow**:
- `argo submit --from workflowtemplate/<name>` (`docs/substreams-graph-node-backfill.md:220-228`);
- or `examples/` that are not in the Flux path (`subgraphs-operations/fullsync/examples/fresh.yaml:1-2`).

### 4.4 Generic-template precedents

| Template | Pattern |
|---|---|
| `subgraphs-operations/fullsync/base/workflow-template.yaml` | `fullsync-subgraph`; params `deployment`, `network`, `start-block`, …; `podMetadata` labels; Prometheus `metrics` gauge; `require-*-approval` booleans |
| `subgraphs-operations/transplants/base/workflow-template.yaml` | Semaphore from ConfigMap `transplant-sync` instead of a hard mutex (`:26-33`) |

The fullsync runtime is dormant (all replicas 0; `docs/fullsync-platform.md`), and it is
Graph Node WASM, not Substreams.

### 4.5 Tests

`subgraphs-operations/backfill/tests/` holds 9 scripts. CI runs only:
- `python3 -m unittest kan/test_backfill_exporter.py`;
- `bash tests/test-contract.sh`, which internally calls `test-replay-postgres-evidence.sh`,
  `test-compare-compute-performance.sh`, `test-validate-compute-request.sh`,
  `test-render-compute-workflow.sh`, `test-render-sql-replay-workflow.sh` and
  `test-v4-reference-replay-contract.sh` (`test-contract.sh:475,1082-1086`);
- `argo lint --offline --strict` via `quay.io/argoproj/argocli:v4.0.7` on the rendered Kan
  overlay (`.github/workflows/ci.yaml:67-75`).

`test-contract.sh` is a V4 safety contract. It asserts on the full rendered overlay, including
**global counts**:

| Line | Assertion |
|---|---|
| `:121` | `[[ "$failed" = f…` ×5 |
| `:154` | `value: scratch` ×2 |
| `:155` | `WORKFLOW_NAME` ×9 |
| `:214`, `:216` | `migrate-scratch` / `initialize-scratch-chain` ×3 |
| `:237` | `memory: 128Gi` ×3 |
| `:238` | `memory: 256Gi` ×8 |
| `:247` | `default_transaction_read_only%3Don` ×7 |
| `:300` | v0.44 graph-node image ×19 |
| `:306-309` | `RUST_LOG` / `GRAPH_LOG` ×5 |

It also asserts exact strings in `base/rbac.yaml` (`:1523-1525`), `deploy/kan/backfill.yaml`
(`:1517-1520`) and `core/kan/univ4base-*` (`:1501-1515`).

**Any resource added to `subgraphs-operations/backfill/kan` that reuses those strings fails CI.**

### 4.6 CI gates

Required checks: `shard-config-drift` and `kustomize-build` (`docs/ci.md:45-72`).

`kustomize-build` builds an **explicit overlay list** (`.github/workflows/ci.yaml:153`). A new
overlay is not validated unless it is added there. Add a lint step like the existing
"Lint Argo Substreams backfill workflow".

### 4.7 PRs (`.agents/skills/create-pull-request/SKILL.md`)

- Work in a worktree from `origin/main`; never commit on `main`; squash merge after green CI.
- Title: `🤖 [claude] <imperative summary>`.
- Body: Summary / Live status / Test plan (include CI) / footer
  `🤖 Created by Claude (<model> <effort>)`.
- Use `Refs #…`, not closing keywords; negated closing keywords still auto-closed issue #956.
- "Docs move with the change": README/`docs/` must be updated in the same PR (`AGENTS.md:92-93`).
- New recurring procedure → `.agents/skills/<verb-first>/SKILL.md` (`AGENTS.md:132-134`).

### 4.8 Open work

- Open k8s PRs: only #1137 (VMAlert, unrelated).
- Open issues touching backfill: #779 (onboard top-QV / ellipfra-monopoly backfill
  candidates), #420, #933, #815.
- **No issue tracks Aerodrome backfill.** substreams-backfills#83 is referenced by
  `backfill-flags.yaml:31-32`.
- No backfill alert rules or committed Grafana dashboard exist: grep finds no `backfill_job` in
  `subgraphs-alerts/` or `subgraphs-grafana/`. Dashboard `k8s-graph-backfills` lives outside
  GitOps (memory note).

---

## 5. Concrete proposal

### 5.1 Placement decision: new tree, not the V4 overlay

Recommended layout:

```
subgraphs-operations/backfill/generic/
  base/
    kustomization.yaml                  # namespace: subgraphs-backfill
    substreams-noop-workflow-template.yaml          # WorkflowTemplate substreams-noop (generic)
    substreams-graph-node-backfill-workflow-template.yaml  # WorkflowTemplate (generic production load)
    sync-config.yaml                    # ConfigMap semaphore: substreams-noop: "8"
  kan/
    kustomization.yaml                  # ../base + targets/*
    aerodrome-slipstream-base/
      kustomization.yaml
      work-pvc.yaml                     # substreams-backfill-aerodrome-base-work, prune: disabled, bound via dom153 consumer
      rbac.yaml                         # Role in `subgraphs`: deployments get on the aerodrome parking/copy worker names only
      noop-workflow-template.yaml       # aerodrome-slipstream-base-substreams-noop: thin wrapper (templateRef → substreams-noop) with pinned defaults
      backfill-workflow-template.yaml   # aerodrome-slipstream-base-substreams-backfill: thin wrapper with pinned identity defaults
  examples/                             # NOT in Flux: submit-noop.yaml / submit-backfill.yaml with every placeholder
  tests/test-generic-contract.sh        # own contract (no global-count coupling with V4)
deploy/kan/backfill-generic.yaml        # Flux Kustomization, dependsOn: [subgraphs-backfill], wait: false, prune: true
deploy/kan/kustomization.yaml           # + ./backfill-generic.yaml
.github/workflows/ci.yaml               # + kustomize build generic/kan, argo lint --strict, run tests/test-generic-contract.sh
```

Why a separate tree:
- it avoids every V4 global-count and RBAC string assertion;
- it avoids the index-based patch fragility;
- it keeps a V4 mistake from blocking an Aerodrome change (and vice versa) under `prune: true`.

The namespace object stays owned by `subgraphs-backfill`. That is why the new tree needs
`dependsOn`.

### 5.2 (a) Generic noop WorkflowTemplate `substreams-noop`

**Pattern source:** token-api `workflows/templates/token-noop.yaml:86-112, 166-190`,
`workflows/templates/cluster/substreams-sink-noop.yaml:55-79,127-151` and
`generate-subranges.yaml:1-26`.

**Semantics (VERIFIED):** `substreams sink noop` forces `NoopMode=true`
(`/Users/denis/Github/substreams/cmd/substreams/sink_noop.go:56`) on the production-mode sink.
The server runs and caches the module graph but streams no data.

**Parameters** (generic; the Aerodrome wrapper pins the values):

| Param | Aerodrome value | Notes |
|---|---|---|
| `target-id` | `aerodrome-slipstream-base` | label + mutex suffix |
| `deployment` | `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` | label only |
| `network` | `base` | label; selects RPC host for "finalized" resolution |
| `endpoint` | `base.substreams.riv-prod-firehose-a.pinax.io:443` | **must equal the backfill's endpoint** (cache locality); never rely on the engine default |
| `spkg-url` / `spkg-sha256` | release URL + 64-hex | curl + `sha256sum -c`, like terminal-cert `:974-977` |
| `module` | Aerodrome output module (e.g. the engine-input map) | must be the exact module the backfill consumes, so its outputs are cached |
| `params` | `""` | `-p` overrides change module hashes, so they must match the backfill |
| `range-start` | `13843704` | module initial block; stores need history from here regardless of seed |
| `range-stop` | integer or `finalized` | preflight resolves `finalized` via `eth_getBlockByNumber` on `https://base.rpc.pinax.network/v1/${PINAX_API_KEY}/` |
| `blocks-per-job` | `1000000` | align to Substreams segment and bundle multiples (e.g. 1,000 / 10,000) |
| `substreams-workers` | `64`–`200` | `X-Substreams-Parallel-Workers`; coordinate tier2 capacity with token-api users of riv-prod-firehose-a |
| `substreams-image` | `ghcr.io/streamingfast/substreams@sha256:<pinned>` (token-api uses tag `v1.18.2`) | digest-pin per repo norm |

**DAG**
1. `preflight` (busybox/curl+jq image, or the runtime image):
   - download the SPKG and verify its SHA;
   - `substreams info` → record module hashes and the initial block in an output JSON;
   - resolve `range-stop`;
   - emit sub-ranges JSON as an output parameter.
2. `noop-range` with `withParam`, gated by semaphore `substreams-noop`:
   - an initContainer re-downloads and verifies the SPKG into an `emptyDir`. Each pod has to
     re-fetch because **there is no artifact repo** (§3.1).
   - the container runs
     `substreams sink noop /spkg/x.spkg $module -e $endpoint -s $start -t $stop -H "X-Substreams-Parallel-Workers: N" --state-file ""`;
   - env `SUBSTREAMS_API_TOKEN` from `backfill-credentials`;
   - `retryStrategy: {limit: 20, retryPolicy: Always, backoff: {duration: 2m}}`;
   - podMetadata labels `app.kubernetes.io/name: substreams-noop`,
     `backfill.pinax.network/target: <id>`.
3. `verify`:
   - optionally one fast full-range noop pass (should be cache hits);
   - emit `noop-evidence.json` to stdout: endpoint, SPKG SHA, module hashes, range, per-range
     status, workflow name.
   - The backfill preflight later asserts `cache-last-block ≤ noop range-stop` with the same
     SPKG SHA and endpoint.

**Scheduling, metrics and gates**
- No PVC, no PG credentials, no `ghcr-cred` (the CLI image is public).
- `nodeSelector` / `NotIn [dom157]`: the client is light; tier2 does the work.
- **Metrics:** do not reuse `backfill_exporter.py`. It raises on unknown `RUN_MODE`
  (`kan/backfill_exporter.py` Exporter `__init__`, values
  `production|scratch|replay|overlap|sql-replay|compute`). Expose the CLI's Prometheus port and
  add a `VMPodScrape` in `subgraphs-metrics/kan/` selecting `app.kubernetes.io/name=substreams-noop`.
  Also add an Argo workflow-level `metrics.prometheus` gauge like fullsync
  (`fullsync/base/workflow-template.yaml:24-39`).
- **No approval gate needed:** the noop is read-only and DB-free, like the compute-only lane.
- Mutex `substreams-noop-{{workflow.parameters.target-id}}` prevents two concurrent noops of the
  same package. Verify with `argo lint --strict` that a templated mutex name is accepted on
  v4.0.7. Otherwise use a fixed wrapper-level mutex name.

**Store-heavy package caveat** (design consideration, standard Substreams behaviour, not code-verified):
- Every sub-range request needs store state from the module initial block.
- Launching all sub-ranges at once on a cold cache makes tier1 schedule overlapping store work.
- **Recommendation:** run the first wave as one full-range noop (tier1 already parallelizes
  stores across segments), or run sub-ranges in ascending waves. Rely on fan-out mainly for the
  output-module map caches and retry isolation.

### 5.3 (b) Generic backfill WorkflowTemplate `substreams-graph-node-backfill`

Clone `kan/production-workflow-template.yaml` and turn every asserted identity into a
parameter. Keep all safety mechanics:
- approval suspend;
- per-segment preflight script;
- stale-lock quarantine;
- progress-gap recovery;
- runtime-identity hash file;
- the no-op resume run;
- the sequence audit;
- the evidence JSON.

**Parameters that keep the exporter working without code changes**

`deployment`, `target-schema`, `expected-seed-block`, `target-block` and `runtime-image-digest`
are read by name by the exporter (`backfill_exporter.py` ~lines 1302-1416). Keep the run root as
`/work/production-${target-schema}-${expected-seed-block}`, and use sidecar env
`RUN_MODE=production`, `WORKFLOW_TEMPLATE=<new name>`, `NETWORK=base`.

**New parameters**

| Group | Parameters |
|---|---|
| Target identity | `target-id`, `network`, `chain-id`, `rpc-url-template`, `substreams-endpoint` (no default to kan-sst2) |
| Landing | `target-shard`, `target-postgres-host`, `primary-postgres-host` (`postgres-0.postgres.subgraphs.svc.cluster.local`) |
| Writer exclusion | `parked-node-id`, `writer-deployments` (space list for the replicas==0 loop), `expected-registry` (`<shard>\|f\|<parked-node>\|t`) |
| Blue/green guard | `active-source-shard`, `active-source-schema` (for the active-copy-untouched check, or `none` for a non-blue/green fresh target) |
| Seed and range | `seed-mode` (`checkpoint` \| `empty` — needs engine support), `expected-seed-hash`, `target-hash`, `cache-last-block`, `segment-size`, `compatibility-profile` |
| Package | `adapter` (engine contract path), `spkg` (in-image path or URL+SHA), `module`, `input-mode` |
| Capacity | `max-pg-bytes`, `reserve-bytes` (replace the 8 TiB contract constants at `:215-217`) |
| Storage | `work-pvc` (parameterized `claimName`; confirm with argo lint, otherwise put the PVC name in the per-target wrapper's `volumes`) |

**Wiring**
- Mutex `substreams-backfill-{{target-id}}`.
- nodeSelector `kubernetes.io/hostname: dom153` (from the wrapper).
- Env:
  - `ENDPOINT={{substreams-endpoint}}`
  - `BASE_RPC_URL` from `rpc-url-template`
  - `DIRECT_POSTGRES_SPKG`
  - `DIRECT_POSTGRES_MODULE`
  - `SUBSTREAMS_INPUT_MODE`
  - `DIRECT_POSTGRES_COMPATIBILITY_CONTRACT`
  - `DEPLOYMENT_ID`
  - `BACKFILL_PREWARM_SUBSTREAMS=1` (cheap when noop has warmed the cache; keeps the retry safety)
- **Rename** the exporter-label PVC guard to use `{{work-pvc}}` (`:495-507` hardcodes
  `substreams-backfill-production-work`).

**Engine blockers** (cross-repo; must land before the Aerodrome backfill can run):
1. Contract selection: `check-compatibility-contract.sh:7` is hardcoded to the V4 adapter.
2. An Aerodrome adapter / compatibility descriptor plus SPKG.
3. Empty-seed / fresh-start support, if Aerodrome is built from 13,843,704 without a Graph Node
   copy.
4. A runtime image digest containing them.

The k8s preflight should fail closed until `adapter != uniswap-v4-base` is supported.

### 5.4 Aerodrome landing (core/kan, separate PR, needs approval)

Mirror V4:

| File | Content |
|---|---|
| `core/kan/aerodrome-backfill-postgres.yaml` | StatefulSet + Service `aerodrome-backfill-postgres`, `nodeSelector: kubernetes.io/hostname: dom153` (+ storage labels per `docs/pre-wave-capacity-gate.md:19-25`), PVC 6–8 Ti `local-storage`, prune disabled |
| `core/kan/graph-node-aerodrome-backfill.yaml` | Deployment `graph-node-aerodrome-backfill-0`, `replicas: 0`, dom153, `node_id index_node_aerodrome_backfill_0`, `GRAPH_STORE_BATCH_WORKERS` 4–8. It is the copy runner, and its zero-replica node id is the parking assignment. **Do not** add it to `INDEXER_AGENT_INDEX_NODE_IDS` until cutover. |
| `core/kan/graph-node-config.yaml` | `[store.aerodrome_b]` → `aerodrome-backfill-postgres-0.aerodrome-backfill-postgres:5432/graph` |
| `core/kan/tests/primary-store-baseline.json` | add the store and its digest |
| `core/kan/kustomization.yaml` | resources |
| `core/kan/postgres-exporter-dedicated.yaml` | exporter (optional) |

**Rollout:** roll the serving and status nodes sequentially before any registration on
`aerodrome_b` (the #105 invariant, `docs/substreams-graph-node-backfill.md:1360-1368`).

**Seed options** (decision): see "Decisions needed".

### 5.5 Telemetry, alerts, docs and skills (same or follow-up PRs)

- **Scrape:** `subgraphs-metrics/kan/` VMPodScrape for `substreams-noop`. The backfill load
  sidecar is already covered by `subgraphs-metrics/kan/backfill.yaml:11-17`, through label
  selection in namespace `subgraphs-backfill`.
- **Alerts:** `subgraphs-alerts/kan/backfill.yaml` with stalled-commit rules, exporter down and
  workflow-failed. Copy the fullsync shapes plus their tests (`subgraphs-alerts/kan/fullsync.yaml`,
  `subgraphs-alerts/tests/test-fullsync.sh`), wired into CI.
- **Backfill flag:** `subgraphs-alerts/base/backfill-flags.yaml:55-61`. Fix the protocol label
  (`aerodrome-slipstream`) and comment, and flip to `2` when loading.
- **Docs:** `docs/substreams-backfill-generic.md` (or a new section in
  `docs/substreams-graph-node-backfill.md`), plus the README and AGENTS skills list.
- **Skill:** `.agents/skills/backfill-subgraph/SKILL.md`. Its steps 9-10 and the footer are V4
  specific (`:37-44,62-64`). Generalize them: target-agnostic gates, plus a noop → backfill →
  certify → land order with links to the Aerodrome example.

### 5.6 What is generic and what is per subgraph

**Generic (one copy, reused):**
- the noop template (SPKG URL+SHA, module, endpoint, range, fan-out);
- the backfill template body (preflight / approval / seed / pipelined load / verify / evidence);
- the semaphore ConfigMap;
- the exporter sidecar;
- the VMPodScrape;
- the alert rules;
- the CI contract test shape.

**Per subgraph:**
- the wrapper WorkflowTemplates (pinned defaults);
- the work PVC (sized from checkpoint size);
- the `subgraphs` Role with resourceNames for that target's writer Deployments;
- the landing store, parking worker and `[store.*]` (in `core/kan`);
- the backfill-flag entry;
- the engine adapter + SPKG + runtime digest (engine repo).

---

## Appendix A — Key verified numbers (2026-10-20)

| Quantity | Value |
|---|---|
| Base head (Kan VM) | 52,867,735 |
| Aerodrome active head (`subgraphshard_b`) | 34,726,435 |
| Range to warm for Aerodrome stores | [13,843,704, ~52.87M] = ~39.0M blocks |
| Range left for Graph Node | ~18.1M blocks |
| `aerodrome-postgres` PVC | 4Ti; 1.14 TB used; dom157 |
| `univ4base-backfill-postgres` PVC | 8Ti; 2.95 TB used; dom153 |
| `postgres-2` PVC | 12.1 TB used |

Argo controller and CLI version: v4.0.7. Operator rights in `subgraphs-backfill`: create/patch
workflows, read logs; no WorkflowTemplate create, no exec, no Secret read.

## Appendix B — Decisions needed

1. **Seed strategy for Aerodrome.**
   - (S1) Fresh build from 13,843,704 into an empty, inactive and paused site on
     `aerodrome_b`. This needs engine empty-seed support and a way to register a
     same-hash second site. One option to validate: `graphman copy create` with an offset
     that lands at block 13,843,703, which needs that header in the block cache.
   - (S2) Seed from the existing inactive `aerodrome_a/sgd5311` at ~30.84M. This is the
     V4-identical path, but it sits on dom157 4Ti and fails the 70% fill gate at head.
     Completion is also unverified.
   - (S3) A new `graphman copy` of live `sgd2` (~34.7M) into a new dom153 `aerodrome_b`,
     using the V4 copy-worker pattern.
2. **Landing volume.** A new dom153 store (recommended) versus expanding or reusing
   `aerodrome_a` on dom157 (blocked by policy).
3. **Placement of new templates.** A separate `generic/` tree plus its own Flux Kustomization
   (recommended) versus the V4 `backfill/kan` overlay with updated `test-contract.sh` counts.
4. **Substreams endpoint.**
   - Options: `base.substreams.riv-prod-firehose-a.pinax.io:443` (private, cross-DC, used by
     terminal certification) or the public `base.substreams.pinax.network:443`.
   - Noop and backfill must use the same one.
   - Capacity coordination with token-api users of riv-prod-firehose-a is needed.
5. **How the SPKG is delivered to the backfill.** Baked into the runtime image (V4 model,
   strongest identity) or URL+SHA at runtime (terminal-cert and noop model).
6. **Durable stop for the landing writer.** Park on the zero-replica node
   `index_node_aerodrome_backfill_0`, with no agent allow-list entry, versus agent manual
   management.
7. **PR attribution footer.** The repo skill wants `🤖 Created by Claude (<model> <effort>)`;
   the harness reminder wants "Generated with Claude Code". The repo rule should win.

## Appendix C — Risks / blockers

- The engine default endpoint (kan-sst2) is dead. Any template that omits `ENDPOINT` fails at
  the first Substreams call.
- The engine has a single adapter (`uniswap-v4-base`) and a hardcoded contract path. The
  Aerodrome backfill cannot run until an engine release exists.
- `test-contract.sh` global counts and RBAC string asserts mean edits to the V4 overlay or
  `base/rbac.yaml` fail CI.
- A new `[store.*]` triggers the #105 invariant, `shard-config-drift` Check B, the
  `primary-store-baseline.json` CI test, and a sequential serving-node roll before
  registration.
- dom157 placement prohibition and the capacity gate. A ~3.5 TB-class Aerodrome needs dom153
  6–8 Ti.
- indexer-agent auto management reverses `graphman pause`.
- Secrets and image-pull credentials in `subgraphs-backfill` are unverifiable with the
  operator SA.
- WorkflowTemplates can only arrive through GitOps; the operator SA cannot create them.
- Argo has no artifact repository, so each fan-out pod must re-fetch and verify the SPKG.
- An out-of-band live template (`uniswap-v4-base-sgd2-overlap-replay-candidate`) is not in git.
- `token-noop.yaml` commits Slack and Discord webhook URLs in plaintext (`:107-112`). Do not
  copy that pattern.
