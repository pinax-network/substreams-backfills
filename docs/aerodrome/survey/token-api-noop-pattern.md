# Token API "noop + backfill" Argo pattern, and how to port it to subgraph backfills on Kan

Survey date: 2026-10-20. Read-only. Every claim below is labelled:

- **VERIFIED**: I read the code or config, or observed it live (kubectl get, VictoriaMetrics, DNS, TLS, GHCR registry).
- **CLAIM**: a doc or skill says so and I did not confirm it independently.
- **INFERRED**: my reasoning from verified facts.

## Snapshots read

| Source | Path | Revision |
|---|---|---|
| k8s-token-api-workflows | `scratchpad/ro/k8s-token-api-workflows` | `3f06707` (2026-10-17, shallow, single commit) |
| k8s-subgraphs | `scratchpad/ro/k8s-subgraphs` | `4da0b37` (2026-10-19) |
| engine (substreams-graph-node-backfill) | `scratchpad/ro/engine` | detached worktree. Its `.git` points at a missing worktree, so it has no SHA |
| pinax-skills | `~/Github/pinax-skills` | `main` `d456ab2` |
| streamingfast/substreams | `~/Github/substreams` | `v1.22.0` (`be35ad36`) |
| k8s-substreams | `~/Github/k8s-substreams` | read only through `git show/grep origin/main` (`26c36a8`, 2026-10-19). The working tree is on a stale branch and was ignored |

The rest of this report gives paths relative to these roots, with `file:line`.

> **Secrets found in plaintext (values redacted here):** `k8s-token-api-workflows/AGENTS.md:78` holds a Grafana
> service-account bearer token (`glsa_…`). `workflows/templates/token-noop.yaml:108,111` and
> `workflows/templates/base/token-backfill/token-backfill.yaml:164,167` hold Discord and Slack webhook URLs as parameter
> defaults. Do **not** copy any of them into k8s-subgraphs. Someone should rotate them. That is outside this survey's scope.

---

## TL;DR

1. **`token-noop` is one long-lived Substreams request, not a fan-out.** It is a namespaced `WorkflowTemplate`
   (`workflows/templates/token-noop.yaml`) with three sequential steps: start notifications → one `noop-sink` pod → success notifications.
   That pod runs `ghcr.io/pinax-network/substreams-sink-noop:v1.5.2 … <start>:<stop> --noop-mode -H "X-Substreams-Parallel-Workers: N"`.
   All parallelism happens **on the server** (tier1 schedules tier2 jobs). No sub-ranges are generated. Operators get
   concurrency by hand: they submit several token-noop workflows over adjacent ranges. **VERIFIED** in the YAML and in live
   metrics, e.g. Base 0–10M, 10–20M, …, 46–52.72M, each at 10 workers, all on `base.substreams.riv-prod-firehose-a.pinax.io:80`.
2. **`--noop-mode` + production mode is what fills the cache.** In production mode tier1 plans
   `BuildStores` from the lowest store initial block and `WriteExecOut` for the output module.
   `--noop-mode` swaps the output handler for a `NoopHandler`, sends one message per 1,000-block bundle, and turns off
   the scheduler's 1.5×-workers look-ahead throttle. **VERIFIED** in substreams source. Development mode writes *no*
   execout cache (`orchestrator/plan/requestplan.go:97-101`). `substreams run --noop-mode` without `--production-mode`
   prints a warning for exactly this reason (`cmd/substreams/run.go:78-79`).
3. **`token-backfill-*` fans out.** `generate-subranges/split-range-clickhouse` computes the gaps not yet recorded in
   `<prefix>_processed_ranges` and splits them into `blocks-per-job` chunks (default 100,000).
   `backfill-range` then runs per chunk: create cursor table → `substreams-sink-sql run … <start>:<stop> --final-blocks-only` → insert
   processed range → drop cursor table. Argo `parallelism` caps concurrency (5 in dev, 10 in prod-a/b/c).
4. **What "noop first" guarantees:** every module in the output module's graph is computed once over the range (store
   partials and snapshots, plus execout for the output module) and cached in the state store, keyed by **module hash**. Any
   deterministic WASM panic or store-size overflow surfaces as gRPC `InvalidArgument` ("new deterministic error"), which
   the sink treats as fatal. **VERIFIED**: `service/error.go:224-225`, `sink/sinker.go:608-609`. It guarantees nothing
   about data correctness. Cache reuse also requires the same spkg module graph, the same params, the same network/`VERSION`
   state bucket, and production mode.
5. **Where things run.** Token API runs on **`riv-dev1`**, namespace `token-api-workflows`: Argo controller in
   `argo-workflows`, with Argo Dock and the Argo Server UI. Only `deploy/dev` includes the workflows Kustomization.
   Subgraph backfills run on **`kan-subgraphs-a`**, namespace `subgraphs-backfill`, under a controller-only Argo
   **v4.0.7** (no UI) that watches only `subgraphs-backfill`, `subgraphs-transplant` and `subgraphs-fullsync`.
   **VERIFIED** (git + live kubectl).
6. **The token-api building blocks are `ClusterWorkflowTemplate`s, but cluster-scoped means one Kubernetes cluster.** They
   exist only on riv-dev1 and cannot be referenced from Kan. k8s-subgraphs has **no** CWTs today. Port by **vendoring**
   a namespaced `WorkflowTemplate` into `subgraphs-operations/backfill/kan/`. **VERIFIED.**
7. **Kan has no RWX storage.** Its only storage classes are `local-storage` and `parquet-local-retain` (both TopoLVM, RWO).
   The token-api `noop-sink-pvc` (RWX `ceph-filesystem`) pattern does not port. Drop the cursor PVC. A retry re-requests
   from `start-block`, and the segments already cached are skipped server-side. **VERIFIED** (`kubectl get storageclass`).
8. **Base endpoint:** use **`base.substreams.kan-prod-firehose-a.pinax.io:443`** (TLS + `SUBSTREAMS_API_TOKEN` from
   the existing `backfill-credentials` Secret). The same-DC private route resolves to 172.20.114.2 and has a valid
   `*.substreams.kan-prod-firehose-a.pinax.io` certificate.
   Fallback: `base.substreams.riv-prod-firehose-a.pinax.io:443`, which k8s-subgraphs already uses
   (`terminal-certification-workflow-template.yaml:737`). Both prod tier1s write the **same** river-Ceph state store,
   so a cache warmed through either is reused by the other. **VERIFIED** in k8s-substreams `origin/main`.
   **Never** use the engine scripts' default `base-substreams-tier1-prod.kan-sst2.pinax.io:443`: it is **NXDOMAIN** on
   2026-10-20, and the skill says the `kan-sst2` cluster is gone.
9. **Image for the Kan noop:** `ghcr.io/pinax-network/substreams-sink-noop:v1.5.2@sha256:c9936eb7bb78d1334d97b32e78a8f0bd3f7d8a8ba2e5cbfabb7749d35f9c5e89`
   (proven in 324 task runs over 30 days. Ubuntu with curl/jq/bash). Alternative: upstream
   `ghcr.io/streamingfast/substreams:v1.25.0@sha256:87d14bef4c6f0748b835393a2994b0d86987c45b545a9406693fcc61fb39a5fb`
   (`substreams sink noop`). That image has no curl, so it cannot verify the spkg checksum in-pod. Size the pod small:
   the token-noop container peaked at **123 MiB** and **0.044 CPU** over 30 days.
10. **Defects not to copy:** a deterministic panic is retried 100× at 5-minute backoff (~8 h) before failing.
    Noop failures send no notification (no `onExit`). The discord start step calls the slack template.
    Webhooks live in parameters. Shell-interpolated `other-args`. A placeholder default endpoint (`test.substreams…`) that does not
    resolve. A skill/alert doc mismatch (`BackfillErrorRate` is commented out).

---

## 1. Exactly how `token-noop` works

### 1.1 Objects

| Object | Kind / scope | File | Notes |
|---|---|---|---|
| `token-noop` | `WorkflowTemplate`, ns `token-api-workflows` | `workflows/templates/token-noop.yaml:1-8` | launchable |
| `noop-sink` | `ClusterWorkflowTemplate` | `workflows/templates/cluster/substreams-sink-noop.yaml:1-5` | two templates: `run-substreams-sink` (used) and `run-substreams-noop` (unused) |
| `notifications` | `ClusterWorkflowTemplate` | `workflows/templates/cluster/notifications.yaml` | `discord`, `slack` |
| `generate-subranges` | `ClusterWorkflowTemplate` | `workflows/templates/cluster/generate-subranges.yaml` | **not used by token-noop**. `split-range` and `split-range-generic` are identical and referenced nowhere (grep) |
| `noop-sink-pvc` | PVC 10Mi RWX `ceph-filesystem` | `workflows/pvc-noop.yaml:1-11` | cursor state |
| `workflow-runner` SA + `workflow-executor` ClusterRole | | `workflows/service-account.yaml:1-41` | pods, logs, secrets, configmaps, workflows, workflowtaskresults |
| `token-api-pod-scrape` | `VMPodScrape` | `workflows/pod-scrape.yaml:1-14` | scrapes `:9102/metrics` of any pod labelled `job: token-api` in **any** namespace |
| `workflow-quota` | ResourceQuota | `workflows/quota.yaml:11` | `count/pods: "400"` (counts Failed pods too) |
| Flux `workflows` Kustomization | | `deploy/dev/workflows.yaml:1-25` | only `deploy/dev/kustomization.yaml:4-5` includes it. `deploy/prod/kustomization.yaml:3-4` and `deploy/stage` include only `../base`. **The workflows exist only on the dev cluster (riv-dev1).** |

### 1.2 Inputs (VERIFIED, `token-noop.yaml:86-112`)

| Parameter | Default | Meaning |
|---|---|---|
| `range-start` | `"0"` | start block |
| `range-stop` | `"10000000"` | stop block (exclusive, Substreams semantics) |
| `endpoint` | `test.substreams.riv-prod-firehose-a.pinax.io:443` | placeholder. `test.substreams.riv-prod-firehose-a.pinax.io` does **not** resolve (dig, 2026-10-20). Operators override it |
| `spkg` | `https://files.token-api.riv-dev1.pinax.io/clickhouse-evm-transfers-v0.2.1.spkg` | package URL, passed straight to the sink |
| `module` | `db_out` | output module. It must equal the module the backfill consumes |
| `substreams-workers` | `"50"` | sent as the `X-Substreams-Parallel-Workers` header |
| `other-args` | `""` | raw extra CLI args, shell-interpolated |
| `discord-webhook`, `slack-webhook` | literal URLs (redacted) | notifications. "can't have secret here yet: argo-workflows#5506" (`token-backfill.yaml:162`) |

There is **no chunk-size parameter** and no sub-range generation. `parallelism: 3` (`token-noop.yaml:12`) caps
concurrent pods across the whole workflow. In practice it only lets the two notification pods run side by side.

Live evidence (VictoriaMetrics, `argo_workflows_workflow_duration{cluster="riv-dev1",name="token-noop"}` joined with
`argo_workflows_workflow_result_count`, last 30 days): operators run **several token-noop workflows at once over
adjacent ranges**, each a single request, and always set the endpoint to the **private plaintext route on port 80**.
The Base runs (`workers=10`, `module` not shown) were:

| Range | Status | Duration (s) | ≈ blocks/s |
|---|---|---:|---:|
| 0 – 10,000,000 | Succeeded ×2 | 8,673 / 8,602 | ~1,160 |
| 10,000,000 – 20,000,000 | Succeeded ×2 | 23,577 / 24,208 | ~420 |
| 20,000,000 – 30,000,000 | Succeeded ×2 | 57,527 / 54,113 | ~180 |
| 30,000,000 – 38,000,000 | Succeeded ×2 | 59,238 / 55,215 | ~140 |
| 38,000,000 – 46,000,000 | Succeeded ×2 | 56,402 / 60,292 | ~137 |
| 46,000,000 – 52,720,000 | Succeeded ×1, Failed ×1 | 32,052 / 39,947 | ~210 |

The endpoint label is `base.substreams.riv-prod-firehose-a.pinax.io:80`. A `:80` endpoint needs `--plaintext`, so it was
presumably passed through `other-args`. **INFERRED**: the flag is not exported as a metric label. These packages
(Token API transfers/balances `db_out`) differ from a subgraph-compatible package, so the rates are only an order-of-magnitude reference.

Thirty-day totals across all chains: 214 Succeeded and 110 Failed token-noop workflows. At task level,
`run-noop-sink` had 212 Succeeded and 432 Failed results, which include hand stops and retries. **VERIFIED.**

### 1.3 Workflow spec (VERIFIED, quoted)

```yaml
# workflows/templates/token-noop.yaml:9-44
spec:
  serviceAccountName: workflow-runner
  parallelism: 3
  podMetadata:
    labels:
      job: token-api            # makes VMPodScrape pick up :9102
  ttlStrategy:
    secondsAfterCompletion: 432000  # 5 days
    secondsAfterFailure: 432000
    secondsAfterSuccess: 432000
  podGC:
    deleteDelayDuration: 5m
    strategy: OnPodSuccess          # failed pods are KEPT (panic logs survive)
  retryStrategy:                    # spec-level => default for EVERY template, notifications included
    limit: "100"
    retryPolicy: Always
    backoff:
      duration: "5m"
      factor: "1"
      # maxDuration: "24h"          # commented out
```

Steps (`token-noop.yaml:114-232`): (1) Discord and Slack "Started" notifications in parallel, each with
`continueOn: {succeeded: true, failed: true}` and `when: webhook != ''`. (2) `noop-sink` (`templateRef: {name: noop-sink,
template: run-substreams-sink, clusterScope: true}`). (3) Discord and Slack "Completed" notifications. **There is no
`onExit`, no failure notification and no `activeDeadlineSeconds`** (grep for `onExit|hooks:|activeDeadlineSeconds|synchronization`
finds nothing in `workflows/`).

```yaml
# workflows/templates/token-noop.yaml:166-190
        - - name: noop-sink
            templateRef:
              name: noop-sink
              template: run-substreams-sink
              clusterScope: true
            arguments:
              parameters:
                - name: endpoint
                  value: "{{workflow.parameters.endpoint}}"
                - name: substreams-api-token
                  value: ""                      # keyless: relies on private-route IP allowlist
                - name: spkg
                  value: "{{workflow.parameters.spkg}}"
                - name: module
                  value: "{{workflow.parameters.module}}"
                - name: start
                  value: "{{workflow.parameters.range-start}}"
                - name: stop
                  value: "{{workflow.parameters.range-stop}}"
                - name: substreams-workers
                  value: "{{workflow.parameters.substreams-workers}}"
                - name: other-args
                  value: "{{workflow.parameters.other-args}}"
                - name: pvc-name
                  value: noop-sink-pvc
```

### 1.4 The noop container (VERIFIED, quoted)

```yaml
# workflows/templates/cluster/substreams-sink-noop.yaml:51-79  (template run-substreams-sink, the one token-noop uses)
      volumes:
        - name: state-volume
          persistentVolumeClaim:
            claimName: "{{inputs.parameters.pvc-name}}"
      container:
        image: ghcr.io/pinax-network/substreams-sink-noop:v1.5.2
        env:
          - name: SUBSTREAMS_API_TOKEN
            value: "{{inputs.parameters.substreams-api-token}}"
        volumeMounts:
          - name: state-volume
            subPath: "{{workflow.name}}-{{inputs.parameters.start}}-{{inputs.parameters.stop}}"
            mountPath: "/state"
        ports:
        - name: metrics
          containerPort: 9102
        command: [sh, -c]
        args:
          - |
            substreams-sink-noop \
              {{inputs.parameters.endpoint}} \
              {{inputs.parameters.spkg}} \
              {{inputs.parameters.module}} \
              {{inputs.parameters.start}}:{{inputs.parameters.stop}} \
              {{inputs.parameters.other-args}} \
              --metrics-listen-addr 0.0.0.0:9102 \
              --state-store /state/state.yaml \
              -H "X-Substreams-Parallel-Workers: {{inputs.parameters.substreams-workers}}" \
              --noop-mode
```

The second, **unused** variant, `run-substreams-noop` (`substreams-sink-noop.yaml:80-151`), uses the upstream CLI:

```yaml
        image: ghcr.io/streamingfast/substreams:v1.18.2
        ...
            /app/substreams sink noop \
              {{inputs.parameters.spkg}} \
              {{inputs.parameters.module}} \
              -e {{inputs.parameters.endpoint}} \
              -s {{inputs.parameters.start}} \
              -t {{inputs.parameters.stop}} \
              {{inputs.parameters.other-args}} \
              --prometheus-addr 0.0.0.0:9102 \
              --state-file /state/state.cursor \
              -H "X-Substreams-Parallel-Workers: {{inputs.parameters.substreams-workers}}"
```

Neither template sets resource requests or limits. The CWT's `spec.serviceAccountName: argo-workflows`
(`substreams-sink-noop.yaml:6`) is ignored when the CWT is used through `templateRef`. The calling workflow's
`workflow-runner` SA applies.

**About the images (VERIFIED, GHCR registry API and GitHub API):**

- `pinax-network/substreams-sink-noop` is a fork of `streamingfast/substreams-sink-noop`, whose README now reads
  "⚠️ DEPRECATED … use `substreams sink noop`". The Pinax releases are v1.5.0 ("support foundational stores"), v1.5.1,
  and v1.5.2 ("drift only when live"), all published 2026-03-24. v1.5.2 builds against `github.com/streamingfast/substreams v1.18.2`
  (fork `go.mod:19`). The image is `ubuntu:24.04` with `ca-certificates curl jq`, entrypoint `/app/substreams-sink-noop`.
  CLI usage: `substreams-sink-noop <endpoint> <manifest> <module> [<start>:<stop>]`. Flags include `--state-store`
  (empty means no cursor persistence), `--clean`, `--metrics-listen-addr :9102`, `--api-listen-addr :8080`, plus the standard sink
  flags (`--noop-mode`, `-H`, `--plaintext`, production mode by default) via `sink.AddFlagsToSet` (fork
  `cmd/substreams-sink-noop/main.go:34-64`).
- Digests resolved 2026-10-20:
  - `ghcr.io/pinax-network/substreams-sink-noop:v1.5.2` → `sha256:c9936eb7bb78d1334d97b32e78a8f0bd3f7d8a8ba2e5cbfabb7749d35f9c5e89`
  - `ghcr.io/streamingfast/substreams:v1.18.2` → `sha256:418fc555f2a1567623836deac9d4337f58afee5171dc404b0cd285fda52682ab`
  - `ghcr.io/streamingfast/substreams:v1.22.0` → `sha256:8b3cc7e2bac7f9f09d2fe213589d362f5044ce382774d1de03dc1a6e766fee4a`
  - `ghcr.io/streamingfast/substreams:v1.25.0` (released 2026-10-08) → `sha256:87d14bef4c6f0748b835393a2994b0d86987c45b545a9406693fcc61fb39a5fb`
- The upstream substreams image is `ubuntu:24.04` with only `ca-certificates libssl3` and `/app/substreams` as entrypoint
  (`~/Github/substreams/Dockerfile`). It has no curl.

**What `--noop-mode` actually does (VERIFIED, `~/Github/substreams` v1.22.0):**

- `substreams sink noop` forces `sinkerConfig.NoopMode = true` (`cmd/substreams/sink_noop.go:56`) and excludes the
  `--development-mode` flag (`:15-22`), so it always runs in **production mode**. Its cursor flag is `--state-file`
  (default `./state.cursor`, empty disables it) (`:24`).
- `substreams run --noop-mode` without `--production-mode` logs "noop-mode used without production-mode: server will
  execute in development mode without sending the data, this is probably not what you want" (`cmd/substreams/run.go:78-79`).
- Request plan: production mode → `BuildStores = [lowestStoreInitialBlock, linearHandoff)` and
  `WriteExecOut = [segment(start), linearHandoff)`. Development mode → `WriteExecOut = nil`
  (`orchestrator/plan/requestplan.go:73-101`). **Stores are built from the module's initial block whatever the
  requested start block is.**
- Tier1 swaps in a `NoopHandler` that produces no outputs (`service/tier1.go:1007-1012`). The execout walker sends a
  single message per bundle (`orchestrator/execout/execout_walker.go:307-316`).
- The scheduler normally refuses to schedule more than 1.5× `MaxParallelJobs` segments ahead of the client. That cap is
  **disabled in noop mode** ("noop mode is used by operators to prepare cached output, we don't want to slow down
  anything", `orchestrator/scheduler/scheduler.go:165`).
- The segment/state bundle is 1,000 blocks (`app/tier1.go:60`, `StateBundleSize: 1000`).

### 1.5 Endpoint and auth

- **VERIFIED:** token-noop passes `substreams-api-token: ""`, so `SUBSTREAMS_API_TOKEN` is set to an empty string
  (`token-noop.yaml:175-176`, `substreams-sink-noop.yaml:57-59`). `substreams-sink-sql` in the backfill sets **no** token at all
  (`substreams-sink-sql.yaml:63-73` only sets ClickHouse USERNAME/PASSWORD).
- **CLAIM** (`pinax-skills/.agents/skills/operate-firehose-substreams/SKILL.md:126,133-134`): the private prod route is
  `<chain>.substreams.<cluster>.pinax.io:80` with `--plaintext`, behind `private-gateway`. Keyless access is granted by
  source IP through the authenticator sidecar's allowlist. `operate-token-api-sinks/SKILL.md:256-258` repeats this for live sinks.
  This matches the live `:80` endpoints in §1.2.
- Auth env-var names in the sink library: `--api-token-envvar` defaults to `SUBSTREAMS_API_TOKEN` and `--api-key-envvar`
  to `SUBSTREAMS_API_KEY` (`sink/sinker_viper.go:233-237`). **VERIFIED.**

### 1.6 Sub-ranges

- **token-noop does not generate sub-ranges** (VERIFIED: `token-noop.yaml` never references `generate-subranges`).
  Operators split ranges by hand into concurrent workflows (§1.2).
- `generate-subranges` provides `split-range` and `split-range-generic`: identical Python loops in `python:alpine3.6`
  (`generate-subranges.yaml:7-26,104-123`). It also provides `split-range-clickhouse`, which queries
  `"<db>".<prefix>_processed_ranges ORDER BY block_start` and emits only the gaps, chunked by `blocks-per-job`
  (`:28-102`). Only the backfill uses the ClickHouse variant (`token-backfill.yaml:333-359`).

### 1.7 Retries, TTL, pod GC

- Spec-level `retryStrategy` with limit 100, `Always`, 5 m backoff, factor 1, no `maxDuration` (`token-noop.yaml:38-44`).
  Because it is spec-level it also applies to the notification steps.
  **INFERRED consequence:** a deterministic WASM panic fails each attempt quickly. On retry the server may answer from its
  deterministic-error path, but the workflow still takes about 100 × 5 m ≈ 8 h 20 m before it gives up.
- Inside the pod, the sink library retries transient gRPC errors up to `--max-retries` (default 3, `-1` = infinite;
  the counter resets on data). It treats `InvalidArgument`, `Unauthenticated`/`PermissionDenied`, `FailedPrecondition`
  and `ResourceExhausted` "quota exceeded" as fatal (`sink/sinker.go:605-615`, `sink/sinker_viper.go:221`). **VERIFIED** (upstream v1.22.0.
  The fork builds against v1.18.2, so assume the same behaviour but this is unverified for v1.18.2.)
- TTL is 5 days (`:27-30`). `podGC: OnPodSuccess` with a 5 m delay keeps **failed** pods for inspection
  (`:33-35`). The backfill uses `OnPodCompletion` with a 2 m delay instead (`token-backfill.yaml:39-41`). The skill explains the split:
  noop panic logs must survive (`operate-token-api-sinks/SKILL.md:239-242`).

### 1.8 PVC and cursor state

- `noop-sink-pvc`: 10 Mi, `ReadWriteMany`, `ceph-filesystem` (`workflows/pvc-noop.yaml:1-11`). It is mounted at `/state` with
  `subPath: {{workflow.name}}-{{start}}-{{stop}}` and the sink writes `--state-store /state/state.yaml`. **VERIFIED.**
- Purpose: when Argo retries the pod after a failure, the new pod resumes from the last bundle cursor instead of `range-start`.
  A *new* workflow gets a new subPath and starts fresh. The workflows README shows how to inspect it with a busybox
  pod (`workflows/README.md:88-112`).
- RWX means no node affinity between noop pods (`operate-token-api-sinks/SKILL.md:233-238`).

### 1.9 Notifications (VERIFIED)

- `notifications` CWT: `curlimages/curl:8.12.1` builds a JSON payload in a heredoc and POSTs it to the webhook URL.
  Discord uses an embed with a colour per status. Slack uses blocks (`notifications.yaml:7-60`, `:62-143`).
- Defects:
  - Webhook URLs are plaintext parameter defaults.
  - `send-discord-start-notification` in token-backfill references `template: slack` (`token-backfill.yaml:226-230`).
  - Messages are interpolated into JSON unescaped.
  - No failure path.

### 1.10 Metrics, scrape, dashboards, alerts (VERIFIED)

- Workflow-level Argo custom metrics (`token-noop.yaml:46-84`):
  - `workflow_result_count{name=token-noop,workflow,status}` counter.
  - `workflow_duration{…,endpoint,start,stop,workers,spkg,module}` realtime gauge.
- Task-level metrics in the CWT (`substreams-sink-noop.yaml:9-39`): `task_result_count{name=run-noop-sink,…}` and
  `task_duration{…}`.
- These are exported by the riv-dev1 controller as `argo_workflows_*{cluster="riv-dev1", namespace="argo-workflows"}`
  (live query).
- Sink metrics on `:9102`, scraped through `VMPodScrape` (`job: token-api`). The fork exposes
  `head_block_number`, `head_block_time_drift`, `substreams_sink_progress_message_last_contiguous_block{stage}`,
  `…_running_jobs{stage}`, `…_total_processed_blocks`, `substreams_sink_error`, `substreams_sink_data_message`,
  `substreams_sink_noop_chain_head_block_number`, `substreams_sink_noop_head_block_reached`, and
  `substreams_sink_noop_backprocessing_completion` (live metric-name listing for `pod=~"token-noop-.*"`).
- Dashboard: `deploy/monitor/dashboards/dashboard-backfill.json`, uid `token-api-backfill-sinks-2` ("Backfill Sinks").
  Panels derive the workflow from the pod name with `label_replace(..., "^(.*?)-run-.*$")`. Progress comes from `head_block_number`,
  tier2 rate from `substreams_sink_progress_message_total_processed_blocks`, and running jobs from
  `substreams_sink_progress_message_running_jobs`.
- Alerts (`deploy/monitor/alerts/backfill.yaml`):

  ```yaml
  # backfill.yaml:8-15 (comment, abridged): token-noop-* are interactive; a hand-stopped task is status="Failed"
  # (exit 143); INC-33745 fired on 15 deliberate stops + 1 real panic; noop runs need no alert.
  - alert: BackfillErrorRecorded
    expr: sum(increase(argo_workflows_task_result_count{cluster="riv-dev1", workflow=~"token-backfill-.*", status=~"Failed|Error"}[30m])) > 0
  # BackfillErrorRate is COMMENTED OUT (backfill.yaml:29-37)
  - alert: BackfillTooManyFailedPods
    expr: sum(kube_pod_status_phase{cluster="riv-dev1", namespace="token-api-workflows", phase="Failed"}) > 50
  ```

  Doc drift: `operate-token-api-sinks/SKILL.md:219` lists `BackfillErrorRate` as active. The skill also says noop runs
  "announce their own outcome" (`:228-230`), but only start and success are announced. Its panic signature
  "`wasm execution panicked`" (`:231`) does not match the substreams error strings
  `wasm execution failed deterministically` and `panic in the wasm:` (`wasm/call.go:29`, `wasm/utils.go:15`).

### 1.11 Measured footprint (VictoriaMetrics, riv-dev1, last 30 days, `pod=~"token-noop-.*", container="main"`)

- Peak `container_memory_working_set_bytes`: **129,191,936 B (≈123 MiB)**.
- Peak 5 m CPU rate: **0.044 cores**.

The client is trivially light. All the cost is on tier1 and tier2.

---

## 2. How `token-backfill` consumes the warm cache

### 2.1 Template instantiation (VERIFIED)

There is one base `WorkflowTemplate`, `workflows/templates/base/token-backfill/token-backfill.yaml`, with `${…}` placeholders.
`token-backfill-{dev,prod-a,prod-b,prod-c}.yaml` are **Flux Kustomizations**, not Argo objects. They render that base with
`postBuild.substitute`: `CLICKHOUSE_TARGET_LABEL`, `CLICKHOUSE_HOSTNAME`, `CLICKHOUSE_CLUSTER`, and `PARALLELISM`
(5 for dev, 10 for prod-a/b/c) (`token-backfill-dev.yaml:13-18`, `token-backfill-prod-a.yaml:13-18`). AGENTS.md:27-31
describes the pattern.

### 2.2 Flow (VERIFIED, `token-backfill.yaml:207-510`)

1. `validate-parameters`: a Bun script (`oven/bun:1.1.38-alpine`). It checks `range-start < range-stop` and that the endpoint
   chain prefix matches the `ch-database` chain, with aliases `eth→mainnet`, `arbone→arbitrum-one`, `tronevm→tron`
   (`:512-567`).
2. Start notifications.
3. `setup-db` (create database plus `<prefix>_processed_ranges` ReplicatedReplacingMergeTree, `clickhouse.yaml:7-57`) and
   `setup-sink` (`substreams-sink-sql setup … --ignore-duplicate-table-errors`, `substreams-sink-sql.yaml:96-128`). Both are
   skippable through `skip-db-setup`.
4. `generate-filtered-subranges` → `split-range-clickhouse`: gaps only, chunked by `blocks-per-job` (default 100,000).
5. `backfill-subrange` fans out with `withParam: "{{steps.generate-filtered-subranges.outputs.result}}"` (`:362-403`).
   Concurrency is bounded by `spec.parallelism: ${PARALLELISM}` (`:16`).
6. `get-table-stats` → `deploy-live-sink` (opens a PR in k8s-token-api-services, live sink starting at `range-stop`) →
   completion notifications → optional `optimize-tables`.

Per sub-range (`cluster/backfill-range.yaml:11-136`):

```yaml
        - - name: create-cursor-table   # CREATE TABLE IF NOT EXISTS "<db>".<prefix>_<start> ON CLUSTER ... ReplicatedReplacingMergeTree(block_num)
        - - name: backfill              # templateRef sql-sink/run-sql-sink
        - - name: update-processed-ranges   # INSERT INTO "<db>".<prefix>_processed_ranges (block_start, block_end) VALUES (<start>, <stop>)
        - - name: drop-cursor-table
```

The sink pod (`cluster/substreams-sink-sql.yaml:60-94`):

```yaml
    podSpecPatch: '{"containers":[{"name":"main","resources":{"requests":{"cpu":"500m", "memory":"1Gi"},"limits":{{inputs.parameters.sink-resources-limits}}}}]}'
    container:
      image: "{{inputs.parameters.image}}"   # ghcr.io/pinax-network/substreams-sink-sql:v4.13.0@sha256:b2bf19f8...e8 (token-backfill.yaml:138-141)
      ...
          /app/substreams-sink-sql run \
            clickhouse://$(USERNAME):$(PASSWORD)@{{inputs.parameters.ch-hostname}}:9000/{{inputs.parameters.ch-database}} \
            {{inputs.parameters.spkg}} \
            {{inputs.parameters.start}}:{{inputs.parameters.stop}} \
            --endpoint={{inputs.parameters.endpoint}} \
            --cursors-table={{inputs.parameters.table-prefix}}_{{inputs.parameters.start}} \
            -H "X-Substreams-Parallel-Workers: {{inputs.parameters.substreams-workers}}" \
            --batch-row-flush-interval {{inputs.parameters.batch-row-flush-interval}} \
            --batch-block-flush-interval {{inputs.parameters.batch-block-flush-interval}} \
            --metrics-listen-addr 0.0.0.0:9102 \
            --delay-before-start=5s \
            --final-blocks-only \
            --on-module-hash-mistmatch error \
            --undo-buffer-size 1 \
            {{inputs.parameters.other-args}}
```

Defaults: `substreams-workers` 10 (`:149-151`), `sink-resources-limits` `{"cpu":"3000m","memory":"20Gi"}` (`:158-160`),
`batch-row-flush-interval` 400000 (`:106-108`), `batch-block-flush-interval` hard-coded to 100000 (`:384`). The workflow's
retry policy is 100× `Always` with 5 m backoff and **`maxDuration: 72h`** (`:44-50`).

Idempotency: a rerun recomputes the gaps from `processed_ranges`. A chunk that died mid-way resumes from its own
`<prefix>_<start>` cursor table. A completed chunk is recorded and then its cursor table is dropped.

### 2.3 What "noop first" guarantees, and what it does not

Guaranteed (**VERIFIED** from substreams source, §1.4):

- **Cache filled for the whole graph.** One production-mode noop over `[start, stop)` makes tier2 compute and persist,
  per 1,000-block segment, the store partials and full snapshots from the lowest store initial block, and the execout of
  the output module from `segment(start)`. Each sink-sql chunk then starts mid-range. Its tier1 finds the store snapshot at
  the chunk's segment boundary and the execout files already present, so it **streams from cache** instead of
  re-backprocessing stores from the module's initial block in N parallel chunks.
- **Load profile.** The noop runs at full server parallelism with no client back-pressure (the 1.5× look-ahead cap is
  off), while the subsequent sink-sql pods mostly read files. The sink-sql workers default to 10 because most of their
  work is already cached.
- **No deterministic WASM failure in range.** `wasm.ErrWasmDeterministicExec` and `store.ErrStoreAboveMaxSize` become
  `codes.InvalidArgument "(new deterministic error)"` (`service/error.go:224-225`). The sink treats that as fatal
  "stream invalid" (`sink/sinker.go:608-609`), so the noop pod exits non-zero. A clean noop therefore proves every
  module ran over the range without a panic or store overflow. The skill describes the same intent (`operate-token-api-sinks/SKILL.md:66-67,228-232`).

Preconditions for reuse (**INFERRED** from the cache design and VERIFIED config):

- Same module graph and hashes. The hash covers the WASM binary, initial block and params; engine
  `docs/substreams-stores.md:267-271` says "changing the map invalidates the Store hashes and forces a full Store
  rebuild".
- Same output module.
- The backfill range lies inside the noop'd range.
- Same state-store bucket (`${NETWORK}-sf-${VERSION}-substreams-state`).
- Production mode on both sides.

Not guaranteed:

- Output correctness or parity.
- That later chunks will not hit transient tier2 or RPC failures.
- Live-tail freshness: the noop stops at `range-stop`.
- Cache retention, if the state store has expiry. **Not checked.**

### 2.4 How this differs for a Graph Node (engine) backfill

**VERIFIED** in k8s-subgraphs and engine:

- **The engine consumes sequentially.** Unlike ClickHouse rows, Graph Node state is an ordered reducer with checkpoints,
  VIDs and POI. Kan production runs 100,000-block segments one after another under a mutex
  (`production-workflow-template.yaml:13-16,38`) on a dom153-pinned node (`:19-21`). So "backfill" for subgraphs is
  **sequential consumption**, not token-api's parallel sub-range fan-out. The noop half ports directly. The backfill
  half stays the engine's own production template.
- **The engine already has an in-pod "noop" (prewarm).** `BACKFILL_PREWARM_SUBSTREAMS=1` makes
  `compute-postgres-segment.sh` first run the exact segment request to `/dev/null`, retrying up to
  `BACKFILL_PREWARM_ATTEMPTS`, and only then pipe a second, cache-hitting request into `state-replay`
  (`engine/scripts/compute-postgres-segment.sh:147-193`, `engine/docs/direct-postgres.md:884-899`). Kan production sets
  `BACKFILL_PREWARM_SUBSTREAMS=1`, `ATTEMPTS=128`, `SUBSTREAMS_PARALLEL_WORKERS=500`, and
  `SUBSTREAMS_LIMIT_PROCESSED_BLOCKS=50000000` (`production-workflow-template.yaml:452-464`).
  That prewarm covers one segment at a time. A separate up-front noop over the whole range is still worth it because
  stores are built from the module initial block on the **first** request. That is the expensive cold part, and the
  noop does it once at full parallelism and flushes out panics before any PostgreSQL work.
- **A cache contract already exists.** Kan production takes `cache-last-block` (`:37`) and refuses
  `target_block > cache_last` (`:143`, `(( target_block > seed_block && target_block <= cache_last ))`). The
  `backfill-subgraph` skill's preflight asks for the "cached stop block" (`k8s-subgraphs/.agents/skills/backfill-subgraph/SKILL.md:16-17`).
  **The noop workflow should be the thing that produces `cache-last-block`.** Precedent: the V4 README records
  "The production `sink noop` cache build completed successfully for `[25,350,988, 49,477,582)` using the released
  package and 500 parallel workers" (`substreams-backfills/uniswap-v4/README.md:153-156`). That run was done outside any
  committed Argo template (grep finds no noop template in k8s-subgraphs).
- The engine's `substreams-native` forces production mode ("Production mode is forced by the native binary",
  `engine/docs/native-protobuf.md:172`). It reuses `sink.AddFlagsToSet` with development mode excluded
  (`engine/cmd/substreams-native/main.go:81-85`), so it is cache-compatible with a production noop.

---

## 3. Where these run, and whether the templates are reusable cross-namespace

| | Token API | Subgraph backfills |
|---|---|---|
| Cluster | `riv-dev1` (AGENTS.md:69-72. Only `deploy/dev` includes `workflows`) | `kan-subgraphs-a` (`deploy/kan/backfill.yaml:1-28`, path `subgraphs-operations/backfill/kan`) |
| Namespace | `token-api-workflows` | `subgraphs-backfill` (`subgraphs-operations/backfill/base/namespace.yaml`) |
| Argo controller | in `argo-workflows` ns (metric label `namespace="argo-workflows"`, `cluster="riv-dev1"`) | `quay.io/argoproj/workflow-controller:v4.0.7` in `argo-workflows` (live `kubectl get deploy`). Helm chart 1.0.19 (`platform/argo/kan/release.yaml:9-13`) |
| UI | Argo Dock `argo.riv-dev1.pinax.io` + Argo Server (`workflows/README.md:7`) | **none**: `server.enabled: false` (`platform/argo/kan/values.yaml:23-24`). Submit with argo CLI v4.0.7 or `kubectl create`. A version mismatch has corrupted workflows before (`subgraphs-alerts/base/argo-workflows.yaml:1-6,129`) |
| Watched namespaces | n/a | `subgraphs-backfill`, `subgraphs-transplant`, `subgraphs-fullsync` only (`values.yaml:8-11`) |
| CWTs | 7 building blocks (`workflows/templates/cluster/kustomization.yaml:4-11`) | **none in git** (grep `ClusterWorkflowTemplate|clusterScope` finds nothing). Live listing is forbidden for `denis-cli` |
| RWX storage | `ceph-filesystem` | **none**: `local-storage` (default) and `parquet-local-retain`, both TopoLVM RWO, `WaitForFirstConsumer` (live) |
| Runner SA | `workflow-runner` (ClusterRole-bound) | `substreams-backfill-runner`: `workflowtaskresults` create/patch, `pods` list, `deployments` get on two names (`backfill/base/rbac.yaml:1-41`) |
| Substreams auth | keyless (IP allowlist), private `:80` | `SUBSTREAMS_API_TOKEN` from Secret `backfill-credentials` (`backfill/base/credentials.example.yaml:6-13`, e.g. `production-workflow-template.yaml:843-845`) |
| Metrics path | VMPodScrape `job: token-api` | `VMServiceScrape` objects in ns `subgraphs` selecting Services in `subgraphs-backfill` (`subgraphs-metrics/kan/backfill.yaml:1-17`). vmagent adds `cluster="kan-subgraphs-a"`. The controller's metrics are scraped (`argo_workflows_gauge{cluster="kan-subgraphs-a"}` exists live) |
| Operator RBAC (`denis-cli`, live `kubectl auth can-i`) | n/a | create `workflows`: **yes**. Create `workflowtemplates`: **no** (goes through Flux/git). Get `secrets/backfill-credentials`: **no**. Get `pods/log`: yes |

Live Kan `subgraphs-backfill` state (2026-10-20): 8 WorkflowTemplates. They include
`uniswap-v4-base-sgd2-overlap-replay-candidate`, which is **not in git**. There are 0 Workflows and no NetworkPolicies. PVCs:
`pgdata-substreams-backfill-postgres-0` (1 Ti), `substreams-backfill-production-work` (2 Ti),
`substreams-backfill-work` (1536 Gi).

**Are the WorkflowTemplates reusable cross-namespace?** Within riv-dev1, yes: the building blocks are
`ClusterWorkflowTemplate`s used with `templateRef … clusterScope: true`. `token-noop` itself is a namespaced
`WorkflowTemplate`. **Across clusters, no.** A CWT is a cluster-scoped object of one API server, so Kan cannot
`templateRef` riv-dev1's `noop-sink`. Porting means copying the logic into a Kan `WorkflowTemplate`, or into a Kan CWT
if more namespaces need it. Only `subgraphs-backfill` does today, so a namespaced template is the minimal choice.

**Stopgap (INFERRED, worth knowing):** the tier2 cache is server-side, keyed by module hash, and shared by both prod
DCs (§4.2). An operator could therefore warm the Aerodrome package cache today with the existing riv-dev1 `token-noop`
by passing `spkg=<GitHub release URL>`, `module=<engine output module>`,
`endpoint=base.substreams.riv-prod-firehose-a.pinax.io:80` and `other-args=--plaintext`. That needs no new code. It runs
in the Token API team's namespace, so it is a coordination call rather than the requested k8s-subgraphs workflow.

---

## 4. Minimal generic "substreams noop" WorkflowTemplate for k8s-subgraphs (Kan)

### 4.1 Design decisions

| Decision | Choice | Why |
|---|---|---|
| Kind and location | namespaced `WorkflowTemplate` `substreams-noop` in `subgraphs-backfill`. File `subgraphs-operations/backfill/kan/substreams-noop-workflow-template.yaml`, listed in `backfill/kan/kustomization.yaml` resources | only namespace that needs it. No CWT exists yet. Flux `subgraphs-backfill` already reconciles that path |
| Shape | **one long request** over `[start, stop)`, as in token-noop and the V4 500-worker cache build | stores are built from the initial block on every cold request (`requestplan.go:73-79`). Concurrent chunks would each schedule the same store segments. Server parallelism comes from the workers header |
| Cursor PVC | **none** (`--state-store ""`) | Kan has no RWX class. A local-storage RWO PVC would pin the pod to one node and needs the dom157 placement rule (`AGENTS.md:84-87`). A retry restarts at `start-block`, and the cached segments are found and skipped server-side (INFERRED: the walker still reads one item per cached bundle, which costs minutes, not hours) |
| Retries | per-template, k8s-subgraphs convention: `retryPolicy: Always` + `expression: "lastRetry.status == 'Error' \|\| asInt(lastRetry.exitCode) == 75"` (`subgraphs-operations/fullsync/base/workflow-template.yaml:133-137`). A wrapper maps deterministic and auth failures to exit 1 (no retry) and anything else to exit 75 | avoids token-noop's ~8 h retry storm on a panic |
| Pod GC | `OnPodSuccess` (keep failed pods) | panic logs are the development signal (token-noop lesson) |
| Deadline | `activeDeadlineSeconds` (e.g. 14 d) | token-noop has none |
| Notifications | none by default. Use metrics + VMRule in `subgraphs-alerts` style | k8s-subgraphs alerting is VMRule → incident.io (`subgraphs-alerts/base/argo-workflows.yaml:7-55`), not webhooks in parameters |
| Auth | `SUBSTREAMS_API_TOKEN` from `backfill-credentials` | the existing Kan backfill templates do this (`production-workflow-template.yaml:843-845`, `terminal-certification-workflow-template.yaml:752-754`) |
| Integrity | download the spkg with curl, check `sha256sum -c`, run against the local file | matches k8s-subgraphs' digest-pinning culture (`production-workflow-template.yaml:89-94,441-443`) |

### 4.2 Base Substreams endpoint (VERIFIED 2026-10-20 from the operator workstation)

| Endpoint | DNS | TLS / port | Verdict |
|---|---|---|---|
| `base.substreams.kan-prod-firehose-a.pinax.io:443` | 172.20.114.2 (public DNS, private IP) | LE cert `*.kan-prod-firehose-a.pinax.io`, SAN `*.substreams.kan-prod-firehose-a.pinax.io`, ALPN h2 | **primary**: same DC as kan-subgraphs-a. Use with token |
| `base.substreams.kan-prod-firehose-a.pinax.io:80` | same | TCP open | plaintext. Keyless only if the Kan subgraphs pod CIDR is allowlisted (**unknown**) |
| `base.substreams.riv-prod-firehose-a.pinax.io:443` | 172.19.114.2 | LE cert `*.riv-prod-firehose-a.pinax.io`, h2 | **fallback**. Already used from Kan by `terminal-certification-workflow-template.yaml:737,980` with the token |
| `base.substreams.riv-prod-firehose-a.pinax.io:80` | same | TCP open | what token-noop uses from riv-dev1 (keyless) |
| `base.substreams.pinax.network:443` | 209.249.216.149, 64.203.83.85 | SAN includes `*.substreams.pinax.network` | public, DNS failover between DCs, metered, internet-gateway circuit breaker. Avoid for bulk noop |
| `base-kan.substreams.pinax.network` / `base-riv.…` | 209.249.216.149 / 64.203.83.85 | | public, pinned to one DC (CLAIM: skill `:125`) |
| `base-substreams-tier1-prod.kan-sst2.pinax.io:443` | **NXDOMAIN** (1.1.1.1 and local resolver) | | **dead**. It is still the default in engine `Makefile:1` and `scripts/{compute-postgres-segment,compute-postgres-plan,load-postgres-segment,verify-*,append-parquet-segment,build-resumable-parquet-fixture}.sh`, and in `uniswap-v4/README.md:105`. The skill says "The old `kan-sst2` cluster is gone" (`operate-firehose-substreams/SKILL.md:108`) |

**Cache locality (VERIFIED in k8s-substreams `origin/main` 26c36a8):** every prod tier1 gets
`--substreams-state-store-url=s3://ceph-gw.service.river.consul.eosn.io:7480/${NETWORK}-sf-${VERSION}-substreams-state`
and the matching quicksave store from `apps/substreams-tier1/base/deployment.yaml:52-53`. No cluster overrides it
(`git grep substreams-state-store-url origin/main` returns only that line). So a noop through the riv route and a
backfill through the kan route share one cache bucket for Base v2. **CLAIM** (`operate-firehose-substreams/SKILL.md:222-226`):
riv tier1 also sends its tier2 work to kan's tier2 pool. Tier1 admission: `--substreams-tier1-active-requests-hard-limit=35`
per pod (`deployment.yaml:55`). The gateway circuit breaker allows 350 parallel requests (`apps/substreams-tier1/base/gateway.yaml:58`).
Base tier1 calls RPC through `http://${NETWORK}.rpcx.${CLUSTER_ZONE}-prod-rpc-a.pinax.io/v1/…`
(`chains/base/v2/prod/substreams-tier1/kustomization.yaml:34`). This matters if the Aerodrome package uses `eth_call`s:
the target layout records contract-call inputs (`substreams-backfills/aerodrome-slipstream-base/README.md:55-57`).

**Not verified:** egress from kan-subgraphs-a pods to 172.20.114.2:443. Run a 1-block smoke workflow first.

### 4.3 Parameters

| Name | Example (Aerodrome) | Validation |
|---|---|---|
| `deployment` | `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` | `^Qm[1-9A-HJ-NP-Za-km-z]{44}$` (label only) |
| `network` | `base` | must equal the spkg `network` |
| `spkg-url` | `https://github.com/pinax-network/substreams-backfills/releases/download/<tag>/<pkg>.spkg` | https only |
| `spkg-sha256` | 64 hex | `sha256sum -c` |
| `module` | the exact module the engine requests (V4: `map_store_state_inputs`) | `^[a-z0-9_]+$` |
| `start-block` | `13843704` (Factory start, `aerodrome-slipstream-base/README.md:12`) | positive int |
| `stop-block` | a **finalized** Base block, exclusive (e.g. head − 1,000) | `> start-block` |
| `endpoint` | `base.substreams.kan-prod-firehose-a.pinax.io:443` | allowlist regex `^[a-z0-9-]+\.substreams\.(kan\|riv)-prod-firehose-a\.pinax\.io:(443\|80)$` |
| `parallel-workers` | `100`–`500` (V4 used 500. Token API uses 10–50) | int ≤ 500 |

Leave out a free-form `other-args`. It is a shell-injection and footgun vector in token-noop.

### 4.4 Draft YAML (design sketch, not yet linted against Argo v4.0.7)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: WorkflowTemplate
metadata:
  name: substreams-noop
  namespace: subgraphs-backfill
  labels:
    app.kubernetes.io/name: substreams-noop
    app.kubernetes.io/part-of: subgraphs-backfill
spec:
  entrypoint: noop
  serviceAccountName: substreams-backfill-runner
  parallelism: 1
  activeDeadlineSeconds: 1209600            # 14 d hard stop (token-noop has none)
  ttlStrategy:
    secondsAfterCompletion: 604800          # 7 d, fullsync convention
  podGC:
    strategy: OnPodSuccess                  # keep failed pods: panic logs
    deleteDelayDuration: 10m
  podMetadata:
    labels:
      app.kubernetes.io/name: substreams-noop
      app.kubernetes.io/part-of: subgraphs-backfill
  metrics:
    prometheus:
      - name: substreams_noop_workflow_info
        help: "Substreams noop cache build (value is elapsed seconds)"
        labels:
          - { key: workflow,    value: "{{workflow.name}}" }
          - { key: deployment,  value: "{{workflow.parameters.deployment}}" }
          - { key: network,     value: "{{workflow.parameters.network}}" }
          - { key: module,      value: "{{workflow.parameters.module}}" }
          - { key: start_block, value: "{{workflow.parameters.start-block}}" }
          - { key: stop_block,  value: "{{workflow.parameters.stop-block}}" }
          - { key: workers,     value: "{{workflow.parameters.parallel-workers}}" }
          - { key: wf_status,   value: "{{workflow.status}}" }
        gauge: { realtime: true, value: "{{workflow.duration}}" }
  arguments:
    parameters:
      - { name: deployment,       value: QmReplaceMe }
      - { name: network,          value: base }
      - { name: spkg-url,         value: replace-me }
      - { name: spkg-sha256,      value: replace-with-64-hex }
      - { name: module,           value: replace-me }
      - { name: start-block,      value: "0" }
      - { name: stop-block,       value: "0" }
      - { name: endpoint,         value: base.substreams.kan-prod-firehose-a.pinax.io:443 }
      - { name: parallel-workers, value: "100" }
  templates:
    - name: noop
      steps:
        - - name: run
            template: run-noop
    - name: run-noop
      retryStrategy:
        limit: "20"
        retryPolicy: Always
        expression: "lastRetry.status == 'Error' || asInt(lastRetry.exitCode) == 75"
        backoff: { duration: 1m, factor: "2", maxDuration: 24h }
      metrics:
        prometheus:
          - name: substreams_noop_task_result_count
            help: "Noop task results by status"
            labels:
              - { key: workflow, value: "{{workflow.name}}" }
              - { key: status,   value: "{{status}}" }
            counter: { value: "1" }
      container:
        image: ghcr.io/pinax-network/substreams-sink-noop:v1.5.2@sha256:c9936eb7bb78d1334d97b32e78a8f0bd3f7d8a8ba2e5cbfabb7749d35f9c5e89
        command: [bash, -c]
        args:
          - |
            set -uo pipefail
            deployment='{{workflow.parameters.deployment}}'
            network='{{workflow.parameters.network}}'
            spkg_url='{{workflow.parameters.spkg-url}}'
            spkg_sha='{{workflow.parameters.spkg-sha256}}'
            module='{{workflow.parameters.module}}'
            start='{{workflow.parameters.start-block}}'
            stop='{{workflow.parameters.stop-block}}'
            endpoint='{{workflow.parameters.endpoint}}'
            workers='{{workflow.parameters.parallel-workers}}'
            [[ "$deployment" =~ ^Qm[1-9A-HJ-NP-Za-km-z]{44}$ ]] || exit 1
            [[ "$spkg_url" =~ ^https:// ]] && [[ "$spkg_sha" =~ ^[0-9a-f]{64}$ ]] || exit 1
            [[ "$module" =~ ^[a-z0-9_]+$ ]] || exit 1
            [[ "$start" =~ ^[0-9]+$ && "$stop" =~ ^[1-9][0-9]*$ ]] && (( stop > start )) || exit 1
            [[ "$endpoint" =~ ^[a-z0-9-]+\.substreams\.(kan|riv)-prod-firehose-a\.pinax\.io:443$ ]] || exit 1
            [[ "$workers" =~ ^[1-9][0-9]*$ ]] && (( workers <= 500 )) || exit 1
            curl -fsSL --retry 5 -o /tmp/package.spkg "$spkg_url" || exit 75
            echo "$spkg_sha  /tmp/package.spkg" | sha256sum -c - || exit 1
            substreams-sink-noop "$endpoint" /tmp/package.spkg "$module" "${start}:${stop}" \
              --noop-mode \
              --state-store "" \
              --metrics-listen-addr 0.0.0.0:9102 \
              --api-listen-addr 127.0.0.1:8080 \
              -H "X-Substreams-Parallel-Workers: ${workers}" 2>&1 | tee /tmp/noop.log
            rc=${PIPESTATUS[0]}
            (( rc == 0 )) && exit 0
            if grep -qE 'stream invalid|deterministic|panic in the wasm|stream auth failure|quota exceeded' /tmp/noop.log; then
              echo "non-retryable Substreams failure (rc=$rc)" >&2; exit 1
            fi
            exit 75
        env:
          - name: SUBSTREAMS_API_TOKEN
            valueFrom: { secretKeyRef: { name: backfill-credentials, key: SUBSTREAMS_API_TOKEN } }
        ports:
          - { name: metrics, containerPort: 9102 }
        resources:
          requests: { cpu: 100m, memory: 256Mi }
          limits:   { cpu: "1",  memory: 1Gi }
```

Supporting objects for scraping, following the existing k8s-subgraphs pattern (`backfill/kan/exporter.yaml`,
`subgraphs-metrics/kan/backfill.yaml`):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: substreams-noop-metrics
  namespace: subgraphs-backfill
  labels: { app.kubernetes.io/name: substreams-noop, app.kubernetes.io/part-of: subgraphs-backfill }
spec:
  clusterIP: None
  publishNotReadyAddresses: true
  selector: { app.kubernetes.io/name: substreams-noop }
  ports: [{ name: metrics, port: 9102, targetPort: 9102 }]
---
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMServiceScrape
metadata:
  name: subgraphs-substreams-noop-metrics
  namespace: subgraphs
  labels: { app.kubernetes.io/part-of: subgraphs-metrics }
spec:
  namespaceSelector: { matchNames: [subgraphs-backfill] }
  selector: { matchLabels: { app.kubernetes.io/name: substreams-noop } }
  endpoints:
    - { port: metrics, path: /metrics, interval: 30s, scrapeTimeout: 25s }
```

Alert ideas, in `subgraphs-alerts` VMRule style with `${CLUSTER_NAME}`:

- **Stalled noop:** `max by (pod) (substreams_sink_progress_message_last_contiguous_block{namespace="subgraphs-backfill"})`
  unchanged for 2 h while `substreams_noop_workflow_info{wf_status="Running"}` exists.
- **Deterministic failure:** `increase(argo_workflows_substreams_noop_task_result_count{status="Failed"}[1h]) > 0`,
  aware that a hand stop also reads as Failed (INC-33745 lesson, `token-api-workflows deploy/monitor/alerts/backfill.yaml:8-15`).
  To tell them apart, have the wrapper emit the failure class: an exit-1 deterministic failure is distinguishable from a
  SIGTERM (143).

Alternative image (upstream, newer, no curl):

```yaml
        image: ghcr.io/streamingfast/substreams:v1.25.0@sha256:87d14bef4c6f0748b835393a2994b0d86987c45b545a9406693fcc61fb39a5fb
        command: [/app/substreams]
        args: [sink, noop, "{{workflow.parameters.spkg-url}}", "{{workflow.parameters.module}}",
               -e, "{{workflow.parameters.endpoint}}", -s, "{{workflow.parameters.start-block}}",
               -t, "{{workflow.parameters.stop-block}}", --state-file, "", --prometheus-addr, "0.0.0.0:9102",
               -H, "X-Substreams-Parallel-Workers: {{workflow.parameters.parallel-workers}}"]
```

The upstream image can load an https spkg URL directly. Checksum verification would need an initContainer, for example
`curlimages/curl` writing to an `emptyDir`. Its `--max-retries -1` gives in-process infinite retry on transient errors
(`sink/sinker_viper.go:221`). Upstream is v1.25.0, the substreams library in the fork is v1.18.2, and the engine pins
substreams v1.18.4 (`engine/go.mod:8`). Pick one deliberately.

### 4.5 Resource sizing

- **Client pod:** requests 100m / 256Mi, limits 1 CPU / 1Gi. That is more than 8× the measured peak of 123 MiB and
  0.044 CPU. No nodeSelector is needed: no volumes, and the pod is lightweight. If a placement policy applies, keep it
  off dom153 (the production backfill host) and dom157 (no new volumes).
- **Server side** is the real cost: tier2 pods are shared across chains (CLAIM: skill `:27-30`). The workers header is
  the knob. Start at 100–200. The V4 cache build used 500, and Kan production uses 500 (`production-workflow-template.yaml:452`).
- **Expected duration (order of magnitude only):** Aerodrome is 13,843,704 → ~52.87M, about **39.0M blocks**. The Token
  API Base noops at 10 workers ran ~140–420 blocks/s per chunk above block 10M (§1.2). A store-heavy, call-heavy
  subgraph package will be slower per worker. No Aerodrome measurement exists. Measure on a 100k-block smoke first:
  `substreams_sink_progress_message_last_contiguous_block` gives per-stage progress.

### 4.6 Composing "noop + backfill" for subgraphs

1. Submit `substreams-noop` with `[start-block, stop-block)` set to the backfill range. The stop must be ≤ a finalized
   block and ≥ the engine's `target-block + 1`.
2. On success, record evidence: spkg sha256, module, start, stop, endpoint, workflow name, and module hash (from
   `substreams info` if the upstream image is used). The current runner SA cannot create ConfigMaps. Either have the
   operator copy `stop-block − 1` into the engine's `cache-last-block` parameter (the existing gate at
   `production-workflow-template.yaml:143`), or grant a narrow ConfigMap write and read it in the engine preflight.
3. Run the engine production backfill. `BACKFILL_PREWARM_SUBSTREAMS=1` can stay as a cheap per-segment cache-hit check.
4. Optionally, for a live tail: re-run the noop over `[old stop, new finalized)` before the final continuation segment
   (the runbook calls for "extend the Store cache and run a continuation to a recent finalized Base block",
   `k8s-subgraphs/docs/substreams-graph-node-backfill.md:1472-1474`).

---

## 5. Notes for the generic pinax-skills procedure (inputs for the skill update)

- A noop must be **production mode**. Use `substreams sink noop`, or `substreams run --production-mode --noop-mode
  --limit-processed-blocks 0`. Without production mode the output module is not cached (`requestplan.go:97-101`).
  The warm-cache *RPC* recovery in `operate-token-api-sinks/SKILL.md:291-305` deliberately omits `--production-mode`.
  It serves a different purpose (tip RPC cache), and the two should not be conflated in a generic skill.
- Noop exactly the **output module the backfill consumes**, from the **same released spkg** (same hashes, params and
  network). Splitting stable store writers from experimental maps into separate WASMs, or importing a released
  stores spkg, keeps the expensive caches valid across downstream changes (engine `docs/substreams-stores.md:267-288`).
- For packages with stores, use **one request over the whole range** with a high workers header. Parallel chunked
  noops each rebuild stores from the initial block.
- Use a DC-pinned private route. Never use `kan-sst2`. The cache is shared across DCs through river Ceph.
- Classify failures: `InvalidArgument` or "deterministic" means a code bug, so do not retry. Everything else is
  transient.
- Fix the skill's panic string. Upstream prints `wasm execution failed deterministically` / `panic in the wasm:`.

---

## 6. Risks and blockers

1. **Engine default endpoint is dead.** `base-substreams-tier1-prod.kan-sst2.pinax.io` is NXDOMAIN. The engine scripts
   default to it, and the Kan production template sets no `ENDPOINT`. A noop through a live route followed by an engine
   run against a dead default fails on DNS. The design must pass `ENDPOINT` explicitly to the engine too. **VERIFIED.**
2. **Egress and auth from kan-subgraphs-a to the private tier1 route are untested here.** `backfill-credentials` cannot
   be read with the operator SA. Token validity and expiry are unknown, which matters for a multi-day noop. Mitigation:
   1-block smoke first.
3. **No RWX storage on Kan**, so the cursor PVC cannot be used. Accepted (re-request is cheap once cached).
4. **Argo v4.0.7 and CLI version skew** has corrupted workflows before. Submit with CLI v4.0.7. Lint the template against v4.
5. **Server load.** A single noop at 500 workers competes with all Base users for shared kan tier2 (95–200 replicas,
   CLAIM). Coordinate the workers value.
6. **Module hash drift.** Any rebuild of the Aerodrome package that changes a store's WASM invalidates the warmed cache.
   Pin the release asset sha256 in both noop and engine.
7. **Secrets in the token-api repo** (Grafana SA token, webhooks). Do not replicate them. Rotation is the owners' job.
8. Kan has a live WorkflowTemplate not in git (`uniswap-v4-base-sgd2-overlap-replay-candidate`). With `prune: true` on
   `subgraphs-backfill` it is either unmanaged or will be pruned. Unrelated to the noop, but surprising.

## 7. Decisions needed

1. Image: `pinax-network/substreams-sink-noop:v1.5.2` (proven, has curl, deprecated upstream) or upstream
   `streamingfast/substreams:v1.25.0` plus a checksum initContainer.
2. Endpoint: Kan private `:443` with the token (recommended), or `:80` plaintext keyless if the Kan subgraphs CIDR is in
   the authenticator allowlist.
3. Workers per noop (100 / 200 / 500), and whether to serialize noops cluster-wide with a mutex.
4. How the noop's verified stop block reaches the engine's `cache-last-block`: manual copy, a ConfigMap, or a parent DAG
   that runs noop and then the backfill.
5. Whether to bootstrap the first Aerodrome cache with the existing riv-dev1 `token-noop` while the Kan template lands.
6. Whether to send notifications at all on Kan (default: no. VMRule plus incident.io instead).

## Appendix: read-only verification commands used

- `dig +short` and `dig @1.1.1.1` for each Base hostname. `openssl s_client -connect <host>:443 -servername <host> -alpn h2`,
  plus SAN extraction. `nc -z` on :80.
- GHCR anonymous token + `HEAD /v2/<repo>/manifests/<tag>` → `docker-content-digest`.
- `gh api repos/pinax-network/substreams-sink-noop/{releases,contents/go.mod,contents/Dockerfile,contents/cmd/substreams-sink-noop/main.go}?ref=v1.5.2`.
  `gh api repos/streamingfast/substreams/releases`.
- `KUBECONFIG=~/.kube/kan-subgraphs-a-sa.yaml kubectl -n subgraphs-backfill get workflowtemplates|workflows|pvc|networkpolicies|configmap`.
  `kubectl get storageclass`. `kubectl -n argo-workflows get deploy -o wide`. `kubectl auth can-i …`.
- VictoriaMetrics (Grafana datasource `P4169E866C3094E38`):
  - `argo_workflows_task_result_count`, `argo_workflows_workflow_duration`, `argo_workflows_workflow_result_count` for `cluster="riv-dev1"`.
  - `container_memory_working_set_bytes` / `container_cpu_usage_seconds_total` for `pod=~"token-noop-.*"`.
  - `argo_workflows_gauge` by cluster.
