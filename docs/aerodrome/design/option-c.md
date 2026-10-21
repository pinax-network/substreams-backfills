# Design: Option C (dedicated fast Graph Node worker for `QmasYjyp…`) and the Option A seed plan

Date: 2026-10-20. Author area: Option C + Option A seed. Strictly read-only investigation: no commits, no
kubectl writes, no graphman, no DB writes. Every live action below is a **proposal that needs explicit approval**
(§4.9).

Target: Aerodrome Slipstream Base, deployment `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` (spec 1.2.0, Fast PoI,
`nonFatalErrors`, no graft). Active site `subgraphshard_b/sgd2` (Postgres `postgres-2`, Kan). Inactive copy
`aerodrome_a/sgd5311` (Postgres `aerodrome-postgres`, Kan).

## Evidence labels and sources

- **VERIFIED**: read in code/config, or observed live this pass (VictoriaMetrics `P4169E866C3094E38`, read-only
  `kubectl get/logs` with `~/.kube/kan-subgraphs-a-sa.yaml`, read-only Base RPC `eth_getLogs`/`eth_call`).
- **INFERENCE**: reasoned from VERIFIED facts; the mechanism is not directly observed.
- **ESTIMATE**: arithmetic from VERIFIED inputs (assumptions stated).
- **ASSUMED**: design assumption that an implementation step must verify.
- **OPEN**: needs access/measurement nobody has done.

Path aliases: `K8S/` = `scratchpad/ro/k8s-subgraphs` (`4da0b37`, 2026-10-19); `GN:` = graph-node `77823b5a`
(v0.44 source; Kan runs v0.45.0, `K8S/core/kan/kustomization.yaml:123-130` says v0.45.0 has no DB migrations; that
graphman/command semantics are unchanged in v0.45 is ASSUMED); `SB/` = `/Users/denis/Github/substreams-backfills`
(`bbe3783`); `SURVEY/` = `scratchpad/survey/`. Scratch evidence written this pass:
`scratchpad/optc/aero-pod.log` (worker log), `scratchpad/optc/base-cur.log` (2-minute chain-base log window),
`scratchpad/optc/density/{samples.tsv,dense.tsv,eta.awk}` (density samples and ETA model).

---

## 0. Bottom line

1. **`sgd5311` is not a finished copy that later failed. The copy itself never finished.** It is 89.63 % done
   (VERIFIED from the worker's own log on 2026-10-16: `Pool` 48.93 %, `Burn` 43.38 %, "89.63% of overall data").
   It went to `deployment_status=4` twice, each time when a Postgres it depends on disappeared mid-copy:
   - 2026-09-23 12–15 Z: `postgres-2` container restart 12→13;
   - 2026-10-16 17:33 Z: the dom157 reboot took `postgres-0`/`postgres-2`/`aerodrome-postgres` down. The worker
     logged `copy worker had an error: database unavailable` and then
     `Failed to start subgraph, code: SubgraphStartFailure, error: store error: connection closed`.
   Graph Node does not retry a failed start, and the database still says `healthy`, so neither graph-node nor the
   janitor ever retried. SYNTHESIS C3 ("data copy plausibly completed") is **wrong** and is corrected here.
2. **The 2026-10-16→10-20 stall on the live `sgd2` has the same root cause.**
   - A rolling kernel reboot of all three Kan nodes happened on 10-16. Node boot times: dom152 16:19 Z, dom153
     16:34 Z, dom157 17:43 Z (VERIFIED `node_boot_time_seconds`; kernel is now 6.12.113).
   - It moved the unpinned `graph-node-chain-base-0` from dom153 to dom152.
   - Then the dom157 outage at 17:33 Z failed `sgd2` (status 4) and two other catch-up deployments
     (`QmQmz5…`, `QmcBa4…`) in the worker only.
   - Head stayed flat at 34,665,179 for 3.5 days. It recovered only because the shared worker was
     **OOMKilled** at 2026-10-20 04:49:44 Z (32 Gi limit) and its restart re-started every assignment.
   - This failure class is already documented (`K8S/docs/pg-tuning-2026-10-04.md:263-286`). It has **no alert**,
     and the janitor cannot see it.
3. **Where the time goes.** I measured Graph Node per section with `deployment_sync_secs`. Its exclusive sections
   sum to `deployment_block_processing_duration` within 0.01 % (VERIFIED). In-process **CPU is 46 %** of block time
   on dom153 and **59 %** on dom152. The other components:

   | Component | dom153 (shared) | dom152 (shared) |
   |---|---:|---:|
   | Store reads | 24.5 % | 19.3 % |
   | eth_call | 25.4 % | 18.0 % |
   | transact | 3.2 % | 3.4 % |
   | block stream | 0.6 % | 0.15 % |

   Natural experiment: the same pod spec ran on dom153 (2026-09-29 → 10-16) and on dom152 (before and after).
   - CPU-bound sections cost **1.91× more per handler on dom152**: Zen 2 with SMT, versus Zen 3 with SMT off.
     The 6-core limit was throttled in 33 % vs 11 % of periods.
   - I/O sections are unchanged (store read 0.194 vs 0.180 ms per `store_get`; eth_call 1.96 vs 1.92 ms per call).
4. **Option C is worth doing, but it is a baseline and continuation, not a fix.**
   - A dedicated, Guaranteed 4-CPU worker pinned to dom153 gives **≈1.46× per block** at today's density: about
     0.59 s/block, 1.65–1.7 blocks/s, versus 1.15 now.
   - It also removes co-tenant crashes (143 `chain-base-0` restarts in 30 days; 19.5 % of 10-minute intervals had
     no Aerodrome progress).
   - But trigger density **rises 3–4×** in Base blocks 39M–45M: NPM events are 126–135/block there, versus 30/block
     at 34.0M (VERIFIED by sampling).
   - Density-adjusted ETA to head: **≈300–410 days** with Option C, versus **≈690–1,085 days** for the status quo
     (ESTIMATE, §3.7).
   - So Option A is still required. Option C buys three things:
     - a safety net;
     - a moving oracle frontier for A's differential checks (to about 39M in about 33 days);
     - a worker able to stay at head after cutover. On dom153 it needs only 38–45 % of real time at head density.
5. **Recommended plan (each step needs approval):**
   - **C0.** Re-purpose `graph-node-aerodrome-0`, which is already in the agent allow-list and already Guaranteed
     4 CPU / 32 Gi. Pin it to dom153. Pause the incomplete `sgd5311` on it. Then move the live `sgd2` to it with
     pause → drain → reassign → resume. Add two alerts.
   - **C1.** Tune the entity cache, then optionally qualify a low-latency Base RPC.
   - **C2.** The Option A seed: a new 12 TiB `aerodrome_b` on dom153 and a `graphman copy` of `sgd2`, taken from
     the dedicated worker, which makes the drain simple. Then park the seed at a stopped, paused site.
   - **C3.** After A certifies, activate `aerodrome_b` and continue it on the C0 worker. Retire `sgd2` and the
     `aerodrome_a`/`sgd5311` remnants.
6. **Capacity pressure forces C2/C3 regardless of A.**
   - `pgdata-postgres-2` is at **68.97 % fill** (12.13 of 17.59 TB) and grows about 82–96 GB/day.
   - dom157 has only 0.62 TiB of allocation allowance, so postgres-2 cannot be expanded.
   - During the stall (Aerodrome plus two other catch-ups halted), postgres-2 grew only about 12.5 GB/day.
   - Aerodrome alone grows 25–35 GB/day at C0 speed. It must leave postgres-2 within about 30–45 days, whatever the
     fate of Option A.

---

## 1. Live state snapshot (2026-10-20 ≈20:10 Z, VERIFIED)

| Item | Value | Source |
|---|---|---|
| `sgd2` head (`graph-node-chain-base-0-77c65b59d4-kc8dv`, `subgraphshard_b`) | 34,729,546; status 2 | `deployment_head`, `deployment_status` |
| `sgd5311` status (`graph-node-aerodrome-0-84c4495f8d-pbqbk`) | 4 (failed), no head series | `deployment_status` |
| Base head | 52,869,171 (RPC `eth_blockNumber` 0x326b833) | `https://base.rpc.pinax.network/` |
| Gap | ≈18.14M blocks | ESTIMATE |
| Last 30 days of `sgd2` | +4,007,858 blocks; 835 of 4,279 ten-minute intervals with no head progress (19.5 %) | PromQL in Appendix A |
| `chain-base-0` restarts in 30 days | 143 container restarts | `kube_pod_container_status_restarts_total` |
| Pod placement now | Both graph-node pods on **dom152**. `aerodrome-postgres-0`, `postgres-0` and `postgres-2` on dom157 | `kubectl get pods -o wide` |
| `chain-base-0` placement history | dom152 until 2026-09-29 12 Z; **dom153 2026-09-29 18 Z → 2026-10-16 12 Z** (pods `qbsmk`, `cg2nf`, `d8sfj`, `bgtvq`); dom152 since 10-16 16:28 Z (`kc8dv`) | `kube_pod_info{node}` |
| `chain-base-0` CPU | 4.8 cores used and 11.4 % CFS-throttled on dom153 (W_A); 5.3–5.4 cores used and 32.7 % throttled on dom152 (W_C). Limit 6 (`K8S/core/kan/kustomization.yaml:194-195`) | cAdvisor bridge job |
| Assignments on `chain-base-0` | 122 (120 on `subgraphshard_b`, 1 `subgraphshard_a`, 1 `subgraphshard_hot`) | `count by (shard)(deployment_head{pod=…kc8dv})` |
| dom153 | CPU requested 22.83 of 56; **CPU used ≈1.5 cores** (3-day 1 h rate); memory requested ≈200 GB of ≈1 TiB; thin pool 7.33 % used (55.85 TiB pool); allocation allowance 83.2 TB (75.7 TiB) | node metrics, `capacity.topolvm.io/thin` |
| dom157 | allowance 0.683 TB (0.62 TiB); pool 63.23 % | same |
| `sgd2` size | 1.863 TB (`sum pg_stat_user_tables_size_bytes`); ≈1.314B row versions (`n_live_tup`) | exporter `*shard-b*` |
| `sgd5311` size | 1.076 TB; 810.0M row versions (flat at 786.9M from 10-06 to 10-16, then +23.1M during the 1 h resume on 10-16) | `postgres-exporter-aerodrome` |
| `pgdata-postgres-2` | 12.132 / 17.590 TB = **68.97 %**; 10-05→10-15 +0.964 TB (≈96 GB/day); 10-17→10-19 +25 GB (stall) | `kubelet_volume_stats_*` |
| `pgdata-aerodrome-postgres-0` | 1.140 / 4.396 TB (25.9 %) | same |

---

## 2. Root causes

### 2.1 Why `sgd5311` (`aerodrome_a`) reports `deployment_status=4`

| When (UTC) | Event | Evidence |
|---|---|---|
| 2026-09-21 16:45:21 | `graphman copy create` of `sgd2` into `aerodrome_a`: checkpoint 30,843,266, offset 1343, `on-sync=none`, node `index_node_aerodrome_0`. The worker is unpinned, 2 batch workers, `pool_size` forced to 4 | `K8S/docs/kan-postgres2-offload-2026-09-21.md:103-114`; `K8S/core/kan/graph-node-aerodrome.yaml:52,74`; `K8S/fleet/kan-postgres2-offload-start-2026-09-21.json` |
| 2026-09-21 16:52 | 1.07 % (9,391,503 / 876,712,411 VIDs) | offload doc `:125-127` |
| 2026-09-23 12:00–15:00 | `postgres-2` (source shard) container restart count 12→13. `sgd5311` status 1→4 in the same 3 h bucket, and stays 4 | VERIFIED: `kube_pod_container_status_restarts_total{pod="postgres-2"}`; `deployment_status{pod=~"graph-node-aerodrome.*"}` |
| 2026-09-29 | Aerodrome worker pod recreated (`cd4kq`, still dom152). `postgres-2` pod recreated in the same window. Status 4 from the first sample | VERIFIED (`kube_pod_info`, restarts reset 16→0). INFERENCE: the same start failure |
| 2026-10-05 | Stack review: "Unstick the Aerodrome copy (sgd5311, stalled at 90% since Sep 29)" | `K8S/docs/stack-tuning-review-2026-10-04.md:57` |
| 2026-10-06→10-16 | `sgd5311` live rows flat at 786,905,497 | VERIFIED `pg_stat_user_tables_n_live_tup{job="postgres-exporter-aerodrome"}` |
| 2026-10-16 16:28:12 | Node reboot; new worker pod `pbqbk` on dom152 | `kubectl get pod … creationTimestamp` |
| 16:29:16–17:30:18 | Copy resumes: `Initializing graft by copying data from sgd2 to sgd5311`. `Pool` goes from 27,406,742 to 32,467,042 of 66,357,694 versions (≈1,560 rows/s); `Burn` from 15,364,984 to 22,703,850 of 52,333,053 (≈3,050 rows/s); overall 89.05 % → 89.63 % | `scratchpad/optc/aero-pod.log` (VERIFIED) |
| 17:33:27 | `ERRO copy worker had an error: database unavailable` | same log |
| 17:33:33 | `ERRO Failed to start subgraph, code: SubgraphStartFailure, error: store error: connection closed` | same log |
| 17:43 / 17:45 | dom157 boots; `aerodrome-postgres-0` starts 17:45:06; `postgres-2` starts 17:45:49 | `node_boot_time_seconds`; pod `startTime` |
| After that | No further subgraph activity. Only 2-hourly `CRIT Error receiving message … NotificationListener`, which is consistent with `idle_session_timeout=7200000` on the shared `postgres` StatefulSet (`K8S/core/kan/kustomization.yaml:359`; INFERENCE) | same log |

Root cause (VERIFIED effect, INFERENCE mechanism):

- A start or copy failure caused by a lost database connection is final for that process. graph-node logs
  `SubgraphStartFailure` and never retries.
- The deployment row stays `healthy/failed=false`, because the failure could not be written while the database was
  away (`K8S/docs/pg-tuning-2026-10-04.md:265-274`; `K8S/.agents/skills/restart-parked-deployment/SKILL.md:24-33`).
- The janitor classifies by database health, so it never restarts it.
- The worker was also unpinned and on the Zen 2 "cold" node, and it shared the dom157 failure domain with both of
  the copy's databases.

Remaining copy work (ESTIMATE): `Pool` 33.9M versions at about 1.56k/s is about 6 h. `Burn` 29.6M at about 3.05k/s
is about 2.7 h. Other tables are about 27M rows. So roughly 8–10 h with 2 workers, then creation of the postponed
indexes (`GN:store/postgres/src/copy.rs:302-340`).

### 2.2 Why the live `sgd2` stalled from 2026-10-16 17:33 Z to 2026-10-20 04:50 Z

| When (UTC) | Event | Evidence |
|---|---|---|
| ≤ 10-16 12:00 | `chain-base-0` on **dom153**, 2.02 blocks/s | `kube_pod_info`; head deltas |
| 10-16 16:19–16:34 | dom152 and dom153 reboot. The worker is rescheduled to **dom152** (`kc8dv`, created 16:28:17) because `graph-node-chain-base-0` has no node pin (`K8S/core/base/graph-node-pool.yaml:475-554`; the Kan patch only sets resources, `K8S/core/kan/kustomization.yaml:174-195`) | VERIFIED |
| 10-16 17:30–17:40 | `sgd2` status 2→4, together with `QmQmz5…` (UniV2 Base, head 24.57M) and `QmcBa4…` (head 38.98M). All three are catch-up deployments on `subgraphshard_b`; the other 119 recovered | VERIFIED `deployment_status`; `max_over_time(…[1h])==4` at 10-18 12:00 |
| 10-16 18:00 → 10-20 04:00 | head flat at **34,665,179** (≈3.46 days, ≈344k blocks of lost progress at 1.15 blocks/s) | `deployment_head` (2 h step) |
| 10-20 04:49:44 | `chain-base-0` container `OOMKilled`, exit 137 (32 Gi limit, `K8S/core/kan/kustomization.yaml:186-195`). On restart `sgd2` status is 2 again by 04:50–05:00 and head advances (34,670,191 at 06:00) | VERIFIED pod `lastState`; `deployment_status`; `deployment_head` |

Root cause:

- **This is an unrecorded transient failure in the worker**, the same class as §2.1. The database restart
  (dom157 reboot) failed the three heavy catch-ups.
- INFERENCE: they hold the largest batched write transactions, so they were the deployments most likely to be
  mid-write and leave a poisoned writer, as on 2026-09-21 (offload doc `:150-155`).
- Recovery was accidental, through an OOM.
- Contributing factors:
  - no alert on `deployment_status==4` or a flat head (`grep deployment_status K8S/subgraphs-alerts/` finds none);
  - the janitor reads database health;
  - a shared worker whose OOM and restart behaviour is coupled to 121 other deployments;
  - no node pin, so a reboot can silently move Aerodrome to the slow node and cost about 43 % of its throughput.
- INFERENCE (unverified): a janitor `graphman restart QmasYjyp…` by bare hash would fail anyway while two sites
  exist, because `locate_unique` refuses ambiguous hashes (`GN:node/src/manager/deployment.rs:177-191`). Every
  graphman command in this design therefore uses `sgd2` / `sgd5311`.

### 2.3 Corrections to the survey

| Survey claim | Correction |
|---|---|
| SYNTHESIS C3: `sgd5311` "data copy plausibly completed, then the deployment failed" | **False.** The copy is 89.63 % done and has never finished. Row-count agreement was a coincidence of copy-time sizes. |
| SYNTHESIS C4 / k8s survey: worker "running but idle" | It is running, unpinned on **dom152**, and holds `sgd5311` failed in memory. "Idle" is the symptom of §2.1. |
| v3-lane §4.2 "35 % WASM, 27 % store_get, 15 % eth_call, 3 % transact" | The 27 % "store_get" contains `store_get_asc_new` (10.9 %), which is CPU (entity → AssemblyScript conversion). eth_call is 25.4 % once declared calls (10.5 %) are counted. The corrected split on dom153 is: CPU 46.3 %, store reads 24.5 %, eth_call 25.4 %, transact 3.2 %, stream 0.6 %. The mapping-host CPU ceiling at that density is therefore about 1/0.228 s ≈ 4.4 blocks/s, not 5.8. |
| SYNTHESIS §7 decision rule uses `deployment_host_fn_execution_time{store_get,ethereum_call}` | The label is `host_fn_name`. Prefer `deployment_sync_secs` sections (§3.1), which are exclusive and complete. |

---

## 3. Timing decomposition: where Graph Node spends time on Aerodrome

### 3.1 Method (VERIFIED)

`deployment_sync_secs{deployment,stage,section}` is graph-node's section stopwatch. For W_A, the process-stage
sections summed to **257,495 s**, against **257,466 s** for `deployment_block_processing_duration_sum`. So the
sections are exclusive and complete. Further identities:

- `host_fn store_get` time (68,524 s) equals `host_export_store_get` (40,645) plus `store_get_asc_new` (27,939);
- `host_fn ethereum_call` (38,322 s) equals `host_export_ethereum_call` (38,332).

The writer stage (`stage="writer"`) runs concurrently and is reported separately. PromQL is in Appendix A.

Windows:

- **W_A**: dom153, shared pod `bgtvq`, 2026-10-13T12 → 10-16T12 (3 days).
- **W_B**: dom152, shared `lw5vx`, 2026-09-26T12 → 09-29T12.
- **W_C**: dom152, shared `kc8dv`, 2026-10-20T08 → 20T20 (12 h).

### 3.2 Per-block decomposition (VERIFIED raw seconds; ms/block and % are ESTIMATE)

| | W_A dom153 | W_C dom152 |
|---|---:|---:|
| Blocks / wall | 523,116 / 259,200 s (**2.02 blocks/s**) | 49,828 / 43,200 s (**1.153 blocks/s**) |
| `block_processing_duration` | 257,466 s (99.3 % of wall); **492 ms/block** | 43,132 s (99.8 %); **866 ms/block** |
| Handlers per block | 48.63 | 56.96 |
| `store_get` calls per block | 669.9 | 853.6 |
| `ethereum_call` host calls per block | 65.1 | 79.0 |
| RPC- or DB-observed eth_calls per block | 37.6 | 44.9 |

Sections per block:

| Section (process stage) | W_A ms/block | W_A % | W_C ms/block | W_C % |
|---|---:|---:|---:|---:|
| `run_handler` (pure WASM) | 51.2 | 10.4 | 107.5 | 12.4 |
| `host_export_other` (BigDecimal/BigInt/typeconv/crypto) | 65.3 | 13.3 | 150.9 | 17.5 |
| `store_get_asc_new` (entity→AS heap, CPU) | 53.4 | 10.9 | 127.9 | 14.8 |
| `host_export_store_set` (CPU) | 37.1 | 7.5 | 86.6 | 10.0 |
| `module_init` | 8.0 | 1.6 | 11.8 | 1.4 |
| other CPU (`process_triggers`, `match_and_decode`, `as_modifications`, PoI set, …) | 12.7 | 2.6 | 24.7 | 2.9 |
| **CPU-bound subtotal** | **227.7** | **46.3** | **509.5** | **59.2** |
| `host_export_store_get` (entity cache / DB) | 77.7 | 15.8 | 111.6 | 12.9 |
| `as_modifications_load` (DB) | 42.9 | 8.7 | 54.1 | 6.3 |
| **Store-read subtotal** | **120.6** | **24.5** | **165.7** | **19.3** |
| `host_export_ethereum_call` | 73.3 | 14.9 | 98.0 | 11.3 |
| `declared_ethereum_call` | 51.8 | 10.5 | 56.7 | 6.5 |
| **eth_call subtotal** | **125.1** | **25.4** | **154.7** | **18.0** |
| `transact_block` (hand-off to writer) | 15.7 | 3.2 | 29.5 | 3.4 |
| `scan_blocks` (Firehose wait) | 3.2 | 0.6 | 1.3 | 0.15 |

Writer stage, W_A: `insert_modification_insert_query` 105,070 s plus `delete_modification_clamp_range_query`
19,493 s. That is about 0.24 s/block, and the writer is busy about 48 % of wall time (`queue_idle` 134,207 s). It
hides behind processing. `queue_push_blocked` is ≈0 (VERIFIED).

W_B (Sept, dom152, crash-looping) is the extreme case:

- 123,639 blocks in 3 days, **0.48 blocks/s**;
- block processing ran only 39.4 % of wall time;
- CPU per handler 10.3 ms.

This confirms that availability, not only speed, dominated September.

### 3.3 Per-unit costs: the dom153 vs dom152 natural experiment (VERIFIED raw; ratios ESTIMATE)

| Unit | W_A dom153 | W_C dom152 | Ratio |
|---|---:|---:|---:|
| CPU sections per handler | 4.68 ms | 8.94 ms | **1.91×** |
| Store read per `store_get` call | 0.180 ms | 0.194 ms | 1.08× |
| eth_call sections per host call | 1.92 ms | 1.96 ms | 1.02× |

Per handler type (handler time only), W_A → W_C:

| Handler | W_A | W_C | Ratio |
|---|---:|---:|---:|
| Swap | 16.6 ms | 26.6 ms | 1.60× |
| Mint | 14.7 ms | 21.5 ms | 1.46× |
| Burn | 8.78 ms | 14.5 ms | 1.65× |
| Transfer | 5.58 ms | 6.41 ms | 1.15× |
| Collect | 2.22 ms | 3.91 ms | 1.76× |
| Increase | 2.18 ms | 3.84 ms | 1.76× |
| Decrease | 2.12 ms | 3.78 ms | 1.78× |

Hardware:

- dom153 is 2× EPYC 7453 (Zen 3, SMT off).
- dom152 is 2× EPYC 7452 (Zen 2, 2 threads/core), per `K8S/docs/HARDWARE.md:44-46` and
  `K8S/docs/kan-idle-worker-capacity-2026-09-08.md:59-66`.

Conclusion (VERIFIED raw / INFERENCE cause): the whole dom153 advantage is in CPU-bound sections. The 1.91× is
larger than the microarchitecture difference alone; CFS throttling (33 % vs 11 % of periods) and SMT-sibling
contention on dom152 plausibly explain the rest. **No faster CPU exists on Kan.** dom157 has the same silicon as
dom153 but forbids new volumes and is about 62 % CPU-requested.

### 3.4 eth_call detail (W_A, VERIFIED)

| Method | Calls/block | Mean ms (RPC or DB) | ms/block |
|---|---:|---:|---:|
| Factory `getPool` (C9/C10; not declared, serial inside the handler) | 1.72 | **27.4** | **47.1** |
| Pool `ticks` | 9.47 | 3.81 | 36.1 |
| Pool `feeGrowthGlobal{0,1}X128` | 12.6 | 1.81 | 22.9 |
| NPM `positions` | 13.7 | 0.88 | 12.1 |
| ERC20 ×4 | ≈0 | | ≈0 |

- Metric semantics: `deployment_eth_call_execution_time` counts only calls whose source is RPC or Store, not the
  in-memory declared-call prefetch (`GN:chain/ethereum/src/runtime/runtime_adapter.rs:380`,
  `GN:graph/src/data/store/ethereum.rs:85-87`). 34.08M host calls against 19.65M observed means about 42 % were
  served from the declared prefetch.
- Reverts and empty results are **never cached** (`GN:store/postgres/src/chain_store.rs:3732-3733`), so every
  revert is an RPC round trip. In a 2-minute log window, `sgd2` logged 1,689 `Contract call reverted, reason: empty
  response` and 394 `execution reverted: ID` (`scratchpad/optc/base-cur.log`, VERIFIED). That is about 12 uncacheable
  reverting calls per block.
- Histogram buckets are coarse (0.1/0.5/1/10/100 s). For `getPool`, 99.43 % of calls were under 100 ms. The mean
  is driven by a tail: 5.1k calls between 0.1 and 0.5 s, 262 over 0.5 s, 18 over 10 s.
- Provider: `[chains.base]` uses Firehose for blocks and `https://base.rpc.pinax.network/v1/${PINAX_API_KEY}/` for
  calls (`K8S/core/kan/graph-node-config.yaml:260-264`). Unlike Arbitrum and Matic (#815,
  `K8S/core/kan/graph-node-config.yaml:256-257,294-296`), there is no same-DC direct archive provider.

### 3.5 Trigger density ahead (VERIFIED samples, ESTIMATE averages)

Method:

- `eth_getLogs` on NPM `0x8279…5b72`, topics IncreaseLiquidity, DecreaseLiquidity, Collect and Transfer
  ("NPM4", the events of 4 of the 7 high-volume handlers);
- 100-block windows, 3 per million blocks from 31M to 52.67M;
- plus 10 windows per million in four regions;
- public RPC, at most 200 blocks per request, with backoff (`scratchpad/optc/density/samples.tsv`, `dense.tsv`).

| Region | NPM4 events per block |
|---|---:|
| 31M–34.7M | 25.3 (systematic mean) |
| **34.0M dense** | **30.2** (10 windows: 22–35) |
| 34.7M–39M | 33.6 |
| **40.0M dense** | **126.4** (96–166) |
| **43.0M dense** | **134.6** (107–178) |
| 39M–45M (systematic) | 94.1 |
| 45M–52.9M | 31.5 |
| **52.0M dense** | **44.2** (35–50) |
| **Remaining range mean (34.67M → 52.67M)** | **52.5** |

Calibration (VERIFIED, W_C):

- Graph Node saw 30.0 NPM4 events per block, against my samples of about 30 at 34.0M.
- Total handlers ≈ 1.48 × NPM4 + Swap, because Mint ≈ Increase and Burn ≈ Collect.
- Swap is 12.5 per block now. Its future scaling is unknown, so it is bounded between "flat" and "proportional to
  NPM4".

Cross-check (VERIFIED, read-only `eth_call`):

- NPM `totalSupply()`: 591,264 at 30,843,266; 1,184,710 at 34,729,000; 25,509,844 at 52,800,000.
- The largest minted `tokenId` in IncreaseLiquidity logs: 23,692,610 at 34.729M and 78,901,545 at 52.8M.
- Position churn (mint, then burn) is the density driver. It matches the `sgd2` sizes (Position has 61.35M row
  versions).

### 3.6 Which levers help (answers to the brief)

Each lever lists its share of block time on dom153, its expected effect, and the evidence label.

- **Faster CPU / dedicated worker on dom153.**
  - Share: 46 % of time on dom153; 59 % on dom152.
  - Effect: **1.46× per block** versus today's dom152 shared worker at equal density.
  - Label: ESTIMATE from VERIFIED per-unit costs (§3.3). Model at W_C density: 56.96 × 4.68 + 853.6 × 0.180
    + 79.0 × 1.92 + 18.4 + 3.2 ≈ 594 ms/block, so 1.68 blocks/s.
- **Dedicated (not shared) worker.**
  - Share: availability.
  - Effect: removes 143 restarts in 30 days, the OOM blast radius and CFS throttling. Availability goes from about
    80.5 % (30-day, including the stall) or about 91 % (excluding it) to about 97 % or more with the alert.
  - Label: ESTIMATE / ASSUMED (97 %).
- **Larger entity cache** (`GRAPH_ENTITY_CACHE_SIZE`, per deployment, in KB; default 10,000, which is what
  `chain-base-0` runs, `GN:graph/src/env/mappings.rs:14-19,176`; the Aerodrome worker already sets 512,000).
  - Share: store reads, 24.5 %.
  - Effect: −20 to −40 % of store-read time, so 5–10 % per block. It is only possible on a dedicated worker,
    because 121 co-tenants make the shared worker OOM already.
  - Label: ASSUMED. Precedent: `K8S/core/kan/kustomization.yaml:408-412` says the 10 MB default "cuts the measured
    catch-up rate roughly in half" for uniswap-v4-bnb.
- **Low-latency Base RPC** (same-DC archive, render-config override per worker, precedent
  `K8S/core/kan/graph-node-arbitrum-rpc.yaml`, `K8S/docs/kan-arbitrum-main-rpc.md:8-25`).
  - Share: eth_call, 25.4 %, of which `getPool` alone is 9.6 % of block time.
  - Effect: −25 to −50 % of eth_call, so 6–13 % per block.
  - Label: ASSUMED. OPEN whether a Kan-local Base archive exists.
- **Pre-populating Graph Node's call cache** from A's extractor.
  - Share: eth_call; reverts are not cacheable.
  - Effect: up to about 15–20 %, technically possible. Key = blake3(encoded_call ‖ address ‖ block_hash)
    (`GN:store/postgres/src/chain_store.rs:3767-3773`).
  - Label: **Not recommended.** It writes into the shared chain store, and it only helps before A cuts over.
- **Move the store off postgres-2** (C2/C3).
  - Share: store reads plus writer.
  - Effect: 0–10 % speed. The main value is capacity (§0.6).
  - Label: ASSUMED.
- **Firehose / block stream.**
  - Share: 0.6 %.
  - Effect: none.
  - Label: VERIFIED.

### 3.7 Expected speed and ETA (ESTIMATE; model `scratchpad/optc/density/eta.awk`)

Per-block model:

    t = OH × (NPM4 × c_npm + Swap × c_swap)

Calibrated values:

| Setup | OH | c_npm (ms per NPM4 event, including its Mint/Burn) | c_swap (ms) | Fit |
|---|---:|---:|---:|---|
| dom153 | 1.312 | 8.48 | 16.6 | W_A, 492 ms |
| dom152 | 1.213 | 12.70 | 26.6 | W_C, 865 ms |

Model inputs:

- NPM4 per block from the 66 systematic samples;
- Swap bounded between flat (12.47 per block) and proportional;
- head density 44.2 NPM4 per block;
- chain growth 0.5 blocks/s;
- `ETA = Σt / (1 − 0.5·t_head) / availability`.

| Setup | Mean t over the remaining range | Pure processing time for 18.14M blocks | t at head density | **ETA to head** |
|---|---:|---:|---:|---:|
| Status quo: shared, dom152, availability 0.805 | 1.21–1.51 s (0.66–0.83 blocks/s) | 254–317 days | 1.08–1.27 s | **≈690–1,085 days** |
| **C0**: dedicated dom153, availability 0.97 | 0.86–1.06 s (0.94–1.17 blocks/s) | 180–222 days | 0.76–0.89 s | **≈300–410 days** |
| C0 + C1 levers (−15–25 %, ASSUMED) | 0.66–0.90 s | 135–190 days | 0.6–0.76 s | **≈220–340 days** |

Milestones for C0:

- 34.73M → 39M takes about **33 days** (1.55 blocks/s at NPM4 ≈ 34; status quo about 56 days).
- 39M → 45M then runs at **0.53–0.76 blocks/s** (1.32–1.89 s/block).

Uncertainty is about ±30 %: the samples are 100-block windows, and per-type costs are assumed constant.

This keeps the A eligibility gate valid (`SB/aerodrome-slipstream-base/README.md:68-79`): the minimum stable ETA is
≫ 28 days. A dedicated pod also makes a "stable same-pod 72-hour" window measurable for #86/D7. That is not
achievable on `chain-base-0`, which restarted every 5 h on average over 30 days.

---

## 4. Option C plan

### 4.1 Topology over time

```
NOW         chain-base-0 (dom152, shared 122) ──► sgd2 @ postgres-2 (dom157)      [active]
            aerodrome-0  (dom152)             ──► sgd5311 @ aerodrome-postgres (dom157) [inactive, 89.6% copy, failed]

C0          aerodrome-0  (dom153, Guaranteed 4 CPU) ──► sgd2 @ postgres-2         [active, running]
                                                    └─► sgd5311                    [inactive, PAUSED]
            chain-base-0 (121 deployments, -1 heavy tenant)

C2 (A seed) aerodrome-backfill-0 (dom153, copy runner, replicas 1→0) ──► aerodrome_b/sgdNNNN
            copy of sgd2 at S≈head; then PAUSED, assigned to index_node_aerodrome_backfill_0 (no running pod)
            Option A engine loads S+1..T into aerodrome_b (stopped clone)

C3 cutover  graphman copy activate → aerodrome_b active; aerodrome-0 continues aerodrome_b T→head
            sgd2 paused (rollback window), then retired; aerodrome_a/sgd5311 retired (D6)
```

### 4.2 C0 GitOps change (k8s-subgraphs, one small PR)

File `K8S/core/kan/graph-node-aerodrome.yaml`:

| Lines | Today | Change |
|---|---|---|
| 1-3 | comment "Dedicated worker for the approved postgres-2 offload…" | Rewrite: "Dedicated indexing worker for the ACTIVE Aerodrome site `subgraphshard_b/sgd2`, pinned to dom153 (Zen 3, SMT off). `aerodrome_a/sgd5311` stays assigned here but PAUSED (incomplete 89.6 % copy; never resume it on this node). See `docs/aerodrome-dedicated-worker.md`." |
| after 29 (`spec:` of the pod template) | no placement | add `nodeSelector: { kubernetes.io/hostname: dom153 }`. This is the worker half of the hot-store pairing, `K8S/docs/pre-wave-capacity-gate.md:19-25`. No volume is created, so the dom157 rule does not apply. |
| 74 | `GRAPH_STORE_BATCH_WORKERS: "2"` | keep (copy-only knob) |
| 75 | `GRAPH_ENTITY_CACHE_SIZE: "512000"` | keep in C0 (baseline). C1 changes it. |
| 97-98 | requests = limits = 4 CPU / 32 Gi (Guaranteed) | keep. About 1–1.5 cores are needed: one WASM thread plus the writer. |
| 52 | `pool_size = 4` forced for every store | keep in C0. C1 may raise it only if `store_connection_wait_time_ms` shows waits. |

Rationale for re-using this Deployment instead of adding a new one (VERIFIED):

- its node ID `index_node_aerodrome_0` is already in `INDEXER_AGENT_INDEX_NODE_IDS`
  (`K8S/subgraphs-indexers/pinax2/kan/kustomization.yaml:88`), so the agent keeps the assignment;
- it is already Guaranteed QoS;
- its only assignment is `sgd5311` ("Started all assigned subgraphs … count: 1", `aero-pod.log`);
- `K8S/core/kan/kustomization.yaml:103-104` already lists it.

Docs, in the same PR (`K8S/AGENTS.md:92-93`):

- new `docs/aerodrome-dedicated-worker.md` containing the runbook in §4.3, the rollback and the PromQL;
- a status addendum in `docs/kan-postgres2-offload-2026-09-21.md` (copy 89.63 %, failed 09-23 and 10-16, paused);
- a link at `README.md:115`.

CI: `kustomize-build`; `shard-config-drift` is unaffected because no store changes.

### 4.3 C0 live runbook (operator; every step marked ⚠ needs explicit approval)

Run graphman from the Aerodrome worker pod:

    kubectl -n subgraphs exec deploy/graph-node-aerodrome-0 -c graph-node -- graphman --config /config/config.toml …

(`GRAPH_NODE_CONFIG`, `K8S/core/kan/graph-node-aerodrome.yaml:68`.) **Always address sites as `sgd2` / `sgd5311`.**
A bare hash fails with "Found 2 deployments" (`GN:node/src/manager/deployment.rs:177-191`).

0. **Read-only preflight.**
   - SQL O1.a, O1.b and O4 (§6).
   - `graphman info sgd2`, `graphman info sgd5311`.
   - `deployment_status` for both pods.
   - dom153 CPU requests (`subgraphs:node_cpu_requests:ratio`; need 4 free).
   - Record the 621-ish registry tuples, as the offload did (`K8S/docs/kan-postgres2-offload-2026-09-21.md:24-27`).
1. ⚠ `graphman pause sgd5311`. This only sets `paused_at`; the runner is already dead.
   - Paused sites are not started (`GN:store/postgres/src/primary.rs:635-643`).
   - Verify O1.a: `sgd5311 | aerodrome_a | active=f | index_node_aerodrome_0 | paused_at NOT NULL`.
2. ⚠ Merge the §4.2 PR. Flux recreates the pod (`strategy: Recreate`) on dom153.
   - Verify the pod is on `dom153`.
   - No `Initializing graft by copying` line in its log; no `deployment_status` series for `QmasYjyp` on the new pod.
3. ⚠ **Move `sgd2`** (pause → drain → reassign → resume):
   1. `graphman pause sgd2`.
   2. **Drain.** Poll every ≤3 s (SQL D.1/D.2 in §6) until all of these hold:
      - the persisted head is unchanged for ≥15 s;
      - there are 0 write locks on schema `sgd2`;
      - `chain-base-0` logged the stop of `sgd: 2`.

      The rule exists because the 2026-09-21 premature resume overlapped the old async writer (`Tick range error`,
      poisoned writer, `K8S/docs/kan-postgres2-offload-2026-09-21.md:33-46,150-155`). Abort and `resume` in place
      if the drain is not clean within 5 min.
   3. `graphman reassign sgd2 index_node_aerodrome_0`. `reassign` updates only `node_id` and preserves `paused_at`
      (`GN:store/postgres/src/primary.rs:1193-1215`; `GN:node/src/manager/commands/assign.rs:32-77`).
   4. Verify O1.a: `sgd2 | subgraphshard_b | active=t | index_node_aerodrome_0 | paused`.
   5. `graphman resume sgd2`.
4. **Verify.** These are the G-C0 gates, §7.
   - `deployment_status{deployment="QmasYjyp…",pod=~"graph-node-aerodrome-0.*"} == 2` within 10 min.
   - Head advancing; no `sgd: 2` lines on `chain-base-0`.
   - `subgraph_error` has no new rows; O1.e DB health `healthy`.
5. **Observe 24–72 h.** Rerun the §3 queries scoped to the new pod. Expect CPU per handler ≤ 5.2 ms and ≥1.5
   blocks/s at ≤60 handlers per block.

**Rollback.** Same pause/drain, then `graphman reassign sgd2 index_node_chain_base_0`, then `resume`. Revert the PR
only after that. The indexer agent cannot fight either state: both node IDs are in its list.

Expected live impact:

- Aerodrome indexing pauses for about 2–5 min (startup with 1,502 data sources).
- `chain-base-0` loses its heaviest tenant: at least one core at 99.8 % processing duty (VERIFIED W_C), and less
  OOM pressure.
- Query serving is unchanged: the store stays on postgres-2, and query nodes read stores, not workers.

### 4.4 C0b: alerts (k8s-subgraphs `subgraphs-alerts`, one PR)

New `subgraphs-alerts/base/indexing-worker.yaml` (VMRule), listed in `subgraphs-alerts/base/kustomization.yaml:6-18`.
It reuses the label policy of `subgraphs-alerts/base/pod-hygiene.yaml` and goes with tests
`subgraphs-alerts/tests/indexing-worker.test.yaml` + `test-indexing-worker.sh`, a CI step next to
`.github/workflows/ci.yaml:132`, and a `docs/alert-policy.md` entry.

```yaml
- alert: SubgraphsDeploymentFailedInWorkerOnly        # the documented sweep, pg-tuning-2026-10-04.md:279-283
  expr: |
    (max by (deployment, pod) (deployment_status{cluster="${CLUSTER_NAME}"}) == 4)
      unless on (deployment)
    (max by (deployment) (deployment_status{cluster="${CLUSTER_NAME}"} offset 3h) == 4)
  for: 20m
  labels: { severity: warning, alert_family: SubgraphsDeploymentFailedInWorkerOnly }   # + policy labels
  annotations:
    summary: "{{ $labels.deployment }} failed in worker {{ $labels.pod }} (DB may still say healthy)"
    runbook_url: ".../.agents/skills/restart-parked-deployment/SKILL.md"
- alert: SubgraphsBackfillCriticalHeadStalled          # generic for every deployment_backfill_only target
  expr: |
    (max by (deployment) (deployment_head{cluster="${CLUSTER_NAME}"})
       - max by (deployment) (deployment_head{cluster="${CLUSTER_NAME}"} offset 30m)) <= 0
    and on (deployment) (max by (deployment) (deployment_synced{cluster="${CLUSTER_NAME}"}) == 0)
    and on (deployment) subgraphs:deployment_backfill_only
  for: 15m
```

`subgraphs:deployment_backfill_only` already lists `QmasYjyp…` (`K8S/subgraphs-alerts/base/backfill-flags.yaml:55-61`;
its protocol label fix belongs to SYNTHESIS PR-K3 and is not duplicated here). Test fixtures:

- `stall_10_16`: status 4 for 3 days with a flat head. It must fire both alerts.
- `normal_restart_37min`: status 1 then 2, head flat for 37 min, then advancing. It must not fire the first alert;
  the second fires only if the flatness lasts beyond `for`. Choose `for: 45m` if fixtures show restart noise.
- `deterministic_failed_for_days`: status 4 already 3 h ago. The first alert is suppressed by `unless offset 3h`.

### 4.5 C1: tuning (after ≥72 h of C0 baseline; each is a separate approved PR plus measurement)

- **C1.a entity cache.**
  - Change: `GRAPH_ENTITY_CACHE_SIZE` "512000" → "2000000" (2 GB per deployment; memory limit 32 Gi stays).
  - Gate: `host_export_store_get` + `as_modifications_load` ms/block falls ≥15 % at equal density, and there is no
    OOM.
  - Revert if not.
- **C1.b RPC.**
  - Owners name a Kan-local Base archive endpoint (OPEN).
  - Qualify it as in `K8S/docs/kan-arbitrum-main-rpc.md` (EIP-1898 by-hash with `requireCanonical:true`, head
    freshness, ≥4 historical calls including `getPool`, `ticks` and `positions` at ≈34.7M).
  - Override only this worker's rendered `[chains.base]` provider via `render-config` sed, following
    `K8S/core/kan/graph-node-arbitrum-rpc.yaml`. Keep the shared ConfigMap unchanged.
  - Gate: eth_call ms/block −25 %, and no new `PossibleReorg`/timeout errors.
- **C1.c `pool_size`.** Raise the sed at line 52 to 8 only if `store_connection_wait_time_ms` for
  `subgraphshard_b` on this pod is above 5 % of block time.
- Not recommended: call-cache pre-population (§3.6), or any change to the shared `[chains.base]`.

### 4.6 C3: post-cutover continuation (after A certifies, ⚠ every step)

1. Preconditions:
   - A's landing on `aerodrome_b` is certified at target T, and T ≥ the `sgd2` head;
   - every serve/status node has `[store.aerodrome_b]` (it does since C2);
   - overlap gate **G-X** passed: at F = the `sgd2` head (S < F ≤ T), state at F equals between `sgd2` and
     `aerodrome_b` for every table (non-VID columns), and the `poi2$` digest at F is equal (SQL X.1/X.2, §6).

   Option C is what provides F > S.
2. `graphman pause sgd2`, drain (as §4.3).
3. `graphman copy activate QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV aerodrome_b`
   (`GN:node/src/bin/manager.rs:504-516`: "only copies that have progressed at least as far as the original should
   be activated").
4. `graphman reassign <seed-sgd> index_node_aerodrome_0` (still paused), then `graphman resume <seed-sgd>`. The C0
   worker continues from T to head; at head density it needs 0.76–0.89 s per 2 s block.
5. `graphman reassign sgd2 index_node_aerodrome_backfill_0` (parked node, 0 replicas). Keep it paused as the rollback
   asset for an agreed window.
   - Rollback: `graphman copy activate QmasYjyp… subgraphshard_b` plus the reverse reassignments.
6. Later (⚠ data deletion): retire `sgd2` (unassign, `graphman unused record`/`remove`). This frees about 2+ TB on
   postgres-2.

### 4.7 Fate of `aerodrome_a`/`sgd5311` (input to user decision D6)

The recommendation is to **retire after C2 exists**. `sgd5311` covers only history up to 30.84M, which both `sgd2`
and the C2 seed copy contain. Retiring it then frees two things on dom157, the scarcest resource:

- the 4 TiB PVC allocation, raising allowance 0.62 → 4.6 TiB, which is room for the `postgres-2` expansion;
- 1.14 TB of physical space.

Retirement steps:

1. `graphman unassign sgd5311`. An unassigned, inactive site becomes "unused" (`GN:store/postgres/src/primary.rs:1814-1823`).
2. `graphman unused record`, then `graphman unused list` (read-only check), then `graphman unused remove`.
3. A GitOps PR removes `aerodrome-postgres`, its exporter and `[store.aerodrome_a]`, rolling serve/status nodes in
   #105 order. It also updates `K8S/core/kan/tests/primary-store-baseline.json:47,79` and the worker's
   `wait-postgres` (`K8S/core/kan/graph-node-aerodrome.yaml:39`).

Alternative: finish the copy (about 8–10 h, §2.1) and keep it as an isolated oracle up to 30.84M. Not recommended,
because the C2 seed is a better isolated oracle on dom153.

### 4.8 Risks (Option C)

| # | Risk | Mitigation |
|---|---|---|
| R1 | Old async writer overlaps the new runner during reassign (poisoned writer, nondeterministic Tick range error; happened 09-21) | Strict drain (§4.3 step 3); abort and resume in place; single reassign |
| R2 | Indexer agent resumes `sgd2` during the pause window (`K8S/subgraphs-alerts/base/backfill-flags.yaml:14-23` says pauses are undone "within minutes" by the agent's reconcile loop) | Window under 2 min; verify the assignment and who reports `deployment_head` before resume; repeat the drain if the old node restarted it. VERIFIED limits on the agent's reach: its admin `subgraph_resume` resolves only the **active** site (`GN:core/src/subgraph/registrar.rs:396-404`), so pauses on `sgd5311` and the seed are durable against it. A redeploy never moves an existing assignment ("Create a subgraph assignment if there isn't one already", `GN:store/postgres/src/primary.rs:1064-1075`), and `remove_unused_assignments` keys on the deployment hash (`:855-873`), so every Aerodrome site keeps its node |
| R3 | DB restarts keep leaving deployments failed in the worker only | C0b alerts; runbook = `restart-parked-deployment` skill with `sgd2`; consider a janitor enhancement to read `deployment_status` (issue in k8s-subgraphs) |
| R4 | `postgres-2` fill (68.97 %, about 96 GB/day; Aerodrome 25–35 GB/day at C0) | C2/C3 within about 30–45 days; coordinate with stack-tuning #19/#20 (`stack-tuning-review-2026-10-04.md:57-58`) |
| R5 | Density wall at 39M–45M (3–4×) | Expectation set in §3.7; Option A remains the production route |
| R6 | Writer becomes the bottleneck once processing is faster (writer about 0.24 s/block at W_A density; busy 48 %) | Watch `transact_block` and `queue_push_blocked` sections; the store move (C3) relieves it |
| R7 | dom153 becomes the failure domain for the Aerodrome worker, ingestor, query, V4 stores and `aerodrome_b` | Acceptable: placement rule; restart is about 2–5 min; alerts |
| R8 | Kernel-reboot campaigns repeat the 10-16 pattern | Post-maintenance checklist: run the `deployment_status==4` sweep after any node or DB restart |
| R9 | `graphman` by bare hash is ambiguous with 2 or 3 sites | Always use `sgdN` or `Qm…:shard` |

### 4.9 Live actions that need explicit approval

| # | Action | Kind | Blast radius |
|---|---|---|---|
| L1 | Merge the C0 PR (pin plus comments) | GitOps; restarts `graph-node-aerodrome-0` | Aerodrome worker only |
| L2 | `graphman pause sgd5311` | registry write | inactive copy |
| L3 | `graphman pause sgd2` → drain → `reassign sgd2 index_node_aerodrome_0` → `resume sgd2` | registry writes; live indexing move | Aerodrome indexing (minutes); `chain-base-0` relief |
| L4 | Alert PR (C0b) | GitOps; vmalert | notifications only |
| L5 | C1.a entity cache PR | GitOps; worker restart | Aerodrome only |
| L6 | C1.b RPC endpoint plus credential (manual Secret per `kan-arbitrum-main-rpc.md` pattern) | Secret plus GitOps | Aerodrome only |
| L7 | C2 infrastructure PR: new dom153 PVC 12 Ti, Postgres, store, seed worker | GitOps; capacity gate; #105 rollout | cluster config |
| L8 | `graphman chain ingest base S`; pause/drain `sgd2`; `graphman copy create …`; `resume` | block-cache write plus registry | Aerodrome; postgres-2 read load |
| L9 | Park the seed: `pause <seed>`; PR to set the seed worker to 0 replicas | registry plus GitOps | seed only |
| L10 | C3 cutover: `copy activate`, reassignments; later `sgd2` retirement | serving switch; data deletion | Aerodrome serving |
| L11 | Retire `aerodrome_a`/`sgd5311` (D6) | data deletion; store removal; #105 roll | cluster config |
| — | SQL in §6 (read-only sessions), `kubectl logs/get`, PromQL | **read-only** | none (the operator still needs `pods/exec` for `psql`) |

---

## 5. Seed plan for Option A (S3: fresh `graphman copy` of `sgd2` into a dedicated dom153 store)

### 5.1 Why S3, and why after C0

- **S2 (`sgd5311`) is ruled out:** incomplete (89.6 %), at 30.84M, on dom157 4 TiB, which cannot grow.
- **S1 (root replay into an empty same-hash site)** stays possible for oracle windows only. It is the k8s-backfill
  design's `oracle-window`; it is not my area.
- **S3 after C0 is materially safer.**
  - The source pause/drain is confined to the dedicated worker.
  - The seed block S is about the C0 head at copy time, which is ≥34.73M and growing about 140k blocks/day.
  - The shared Base worker is never stopped. The 09-21 offload required "never stop the shared Base worker",
    `K8S/docs/kan-postgres2-offload-2026-09-21.md:45-46`; after C0 that worker holds no Aerodrome at all.

### 5.2 Capacity (VERIFIED now; ESTIMATE at head)

| Quantity | Value | Basis |
|---|---|---|
| `sgd2` bytes now (34.73M) | **1.863 TB** (tables plus indexes) | `sum pg_stat_user_tables_size_bytes{schemaname="sgd2"}` |
| `sgd2` row versions now | **≈1.314B** (`transaction` 131.9M, `token` 109.9M, `token_hour_data` 109.1M, `token_day_data` 109.0M, `pool_hour_data` 99.1M, `pool_day_data` 99.1M, `pool` 99.0M, `tick_day_data` 92.1M, `tick` 91.9M, `burn` 85.7M, `swap` 77.3M, `position_snapshot` 61.7M, `position` 61.4M, `mint` 28.8M, `poi2$` 17.5M, `uniswap_day_data` 17.5M, `factory` 17.5M, `bundle` 5.9M, `data_sources$` 1,502) | `pg_stat_user_tables_n_live_tup` |
| Largest tables (bytes) | `pool` 215.5 GB, `pool_hour_data` 172.9 GB, `pool_day_data` 170.8 GB, `token_hour_data` 147.0 GB, `token_day_data` 145.1 GB, `position` 138.6 GB, `burn` 135.9 GB, `token` 130.6 GB, `swap` 129.9 GB, `tick` 129.1 GB, `tick_day_data` 108.5 GB | same |
| Growth per block | 161.7 KB (09-22 → 10-16), **179.6 KB** (10-12 → 10-16), at about 49–57 handlers per block, so ≈3.16 KB per handler | size against head series |
| Projected bytes S → current head (18.1M blocks) | mean handlers ≈ 1.48 × 52.5 + (12.5 … 21.8) = 90–100 per block, so 285–315 KB/block → **+5.2–5.7 TB** | ESTIMATE ±30 % (§3.5) |
| **Total at today's head** | **≈7.0–7.6 TB** | ESTIMATE |
| Growth after head | about 44 NPM4 → 80–85 handlers × 3.16 KB × 43,200 blocks/day ≈ **11 GB/day (≈4 TB/yr)** | ESTIMATE |
| Working set at the seed (for A's reducer) | positions ever minted ≈23.7M (largest `tokenId` 23,692,610); unburned 1,184,710 (`totalSupply` at 34,729,000); at head 78.9M minted / 25.5M unburned | VERIFIED (RPC). Exact per-table active counts are OPEN (O8) |

**PVC sizing for `aerodrome_b`: 12 TiB** (13,194,139,533,312 bytes), expandable online (`local-storage`).

- At the 70 % fill gate that gives about 8.4 TiB (9.24 TB) usable. It covers 7.6 TB at head plus about 5 months
  of continuation; expand later (dom153 allowance 75.7 TiB).
- Values to hand to `target.json` `landing.capacity` (k8s-backfill design §6):

  | Field | Value |
  |---|---|
  | `capacity_bytes` | 13194139533312 |
  | `fill_gate_ratio` | 0.70 |
  | `max_pg_bytes` | 9235897673318 |
  | `reserve_bytes` | 1099511627776 (1 TiB) |

**dom153 headroom after C2** (ESTIMATE):

| Resource | Now | Added | After |
|---|---|---|---|
| Physical pool | 4.09 TiB (7.33 %) | +1.7 TiB (seed) → +6.9 TiB (at head) | 11.0 TiB (**19.7 %**) at head; well under 70 % |
| Allocation allowance | 75.7 TiB | 12 TiB PVC | 63.7 TiB |
| CPU requested | 22.83 / 56 | C0 worker 4 (moved from dom152) + `aerodrome-backfill-postgres` 2 + seed worker 8 (temporary) | 36.8 during the copy, then **28.8 (51 %)** (V4 load pods are separate, k8s-backfill §12.3) |
| CPU used | ≈1.5 | about 1.5 (C0) + copy I/O | low |
| Memory requested | ≈200 GB | 32 Gi + 64 Gi + 32 Gi (temporary) | ≈330 GB of ≈1 TiB |

### 5.3 Manifests (k8s-subgraphs `core/kan`, one PR, ⚠ L7, mirroring V4)

| File | Content | Precedent |
|---|---|---|
| `core/kan/aerodrome-backfill-postgres.yaml` (new) | Service plus StatefulSet `aerodrome-backfill-postgres`. Labels `subgraphs/backfill-role: inactive-target`. `nodeSelector`: `kubernetes.io/hostname: dom153`, `infra.pinax.network/storage-local-ssd: "true"`, `infra.pinax.network/storage-vg-nvme01: "true"`. `postgres:16`; `shared_buffers=24GB`, `effective_cache_size=64GB`, `maintenance_work_mem=4GB` (index builds after copy), `max_wal_size=64GB`, `checkpoint_timeout=15min`, `wal_compression=on`, `track_io_timing=on`. Requests 2 CPU / 48 Gi, limits 16 / 64 Gi. Liveness grace as `aerodrome-postgres.yaml:82-93`. PVC 12 Ti `local-storage` with annotation `kustomize.toolkit.fluxcd.io/prune: disabled` | `K8S/core/kan/univ4base-backfill-postgres.yaml:58-118`; `K8S/core/kan/postgres-shard-a-replica-dom153.yaml` (storage labels) |
| `core/kan/graph-node-aerodrome-backfill.yaml` (new) | Deployment `graph-node-aerodrome-backfill-0`, **replicas 1 only for the copy, then 0**, `strategy: Recreate`, dom153. `node_id=index_node_aerodrome_backfill_0`; `GRAPH_STORE_BATCH_WORKERS=4` (raise to 8 only if postgres-2 p95 holds); `render-config` sed `pool_size = 12` (needs batch workers + 2). Requests 8 CPU / 32 Gi, limits 16 / 64 Gi. Init waits for `postgres-0/2/3` and `aerodrome-backfill-postgres-0`. **Not** added to `INDEXER_AGENT_INDEX_NODE_IDS`; V4's parked node is in the list but relied on 0 replicas (k8s-backfill F27) | `K8S/core/kan/graph-node-univ4base-copy.yaml:1-21,86,107-109` |
| `core/kan/graph-node-config.yaml` | Insert after `:139`: `[store.aerodrome_b]` → `postgresql://graph:${POSTGRES_PASSWORD}@aerodrome-backfill-postgres-0.aerodrome-backfill-postgres:5432/graph`, `pool_size = 30`. **No `[[deployment.rule]]`** | `:82-84` (`univ4base_b`) |
| `core/kan/tests/primary-store-baseline.json` | Add `aerodrome_b` to the stores list and its connection digest | `:47,79` |
| `core/kan/kustomization.yaml` | Add both resources after `:104` | `:103-104` |
| `core/kan/postgres-exporter-dedicated.yaml` | Add a `postgres-exporter-aerodrome-backfill` block | `:20-55` |
| `docs/aerodrome-seed-copy.md` (new) | §5.4 runbook and the evidence schema | `docs/substreams-graph-node-backfill.md:1356-1405` |

Rollout:

- Pass the capacity gate first (`K8S/docs/pre-wave-capacity-gate.md:33-41`).
- Merge, then wait until the DB and the seed worker are Ready on dom153.
- **Before any site is created on `aerodrome_b`, roll every serve/status runtime sequentially and verify full
  `indexingStatuses` enumeration between rolls.** This is the #105 invariant (`K8S/AGENTS.md:73-77`), and the
  stricter order follows `K8S/docs/kan-postgres2-offload-2026-09-21.md:28-32`.

### 5.4 Seed copy runbook (⚠ L8/L9; run graphman from `graph-node-aerodrome-backfill-0`, which has the new config)

1. Read-only preflight:
   - O1.a / O1.b: `sgd5311` is paused or retired;
   - `graphman copy list` shows no heavy copy running;
   - postgres-2 query p95 baseline;
   - O4: `history_blocks` and `earliest_block_number`.
2. Choose the seed block S = (the current `sgd2` head) − 1,000.
   - Check `graphman chain info base` and RPC that S is final.
   - ⚠ `graphman chain ingest base <S>`, then verify `block_hashes_by_block_number(S)` is exactly one hash, equal to
     RPC `eth_getBlockByNumber(S).hash`. `copy create` requires exactly one cached hash at head − offset
     (`GN:node/src/manager/commands/copy.rs:134-160`).
3. ⚠ `graphman pause sgd2`, then drain (SQL D.1/D.2: ≥15 s stable head, 0 write locks). Re-read head H. Then:

       graphman copy create --offset $((H - S)) sgd2 aerodrome_b index_node_aerodrome_backfill_0

   - `on_sync` stays `None` (no `--activate`/`--replace`), `GN:node/src/bin/manager.rs:487-503`.
   - ⚠ `graphman resume sgd2` immediately after.
   - Record the printed `created deployment … [NNNN]` receipt once. On an uncertain completion, inspect O1.a/O1.b
     before any retry.
4. Monitor about 1–3 days (ESTIMATE):
   - data at an expected 10–20k rows/s with 4 workers (09-21 achieved about 4.9k rows/s average with 2 workers
     dom157→dom157), then postponed indexes (`postponed_indexes_created`);
   - `graphman copy status sgdNNNN` and SQL C.1/C.2 on `aerodrome-backfill-postgres-0`;
   - postgres-2 read latency and Kan gateway QoS.

   **Brake:** scale the seed worker to 0. Copies resume from `next_vid` (VERIFIED: `sgd5311` resumed at 89.05 % on
   10-16).
5. Completion (G-S4): `copy_state.finished_at IS NOT NULL`; every `copy_table_state.finished_at IS NOT NULL`;
   `subgraphs.deployment.postponed_indexes_created = true`. Then:
   - ⚠ `graphman pause sgdNNNN`, drain (D.1/D.2 on the new schema);
   - ⚠ a GitOps PR sets `graph-node-aerodrome-backfill-0` to **replicas 0**; wait for the pod to exit;
   - verify registry tuple `aerodrome_b | f | index_node_aerodrome_backfill_0 | t` (O1.a) and no non-idle Graph Node
     sessions on the target (`pg_stat_activity`).
6. Record the seed: schema `sgdNNNN`, `head.block_number` (≥ S; a few blocks may have been indexed before the pause)
   and `head.block_hash`, checked against RPC. Run O8.a–O8.d on the **stopped seed** (§6). Run G-S7 parity. Write
   `fleet/aerodrome-seed-copy-<date>.json` (§5.6).

### 5.5 Seed acceptance gates

| Gate | Check | Pass |
|---|---|---|
| G-S0 | Capacity gate on dom153 (post-wave pool under 70 %, allowance at least 12 TiB plus reserve, CPU and memory requests fit) | all true |
| G-S1 | Store staged in every serve/status runtime; `indexingStatuses` OK after each roll | no failure |
| G-S2 | Block S cached exactly once and equal to RPC | equal |
| G-S3 | Drain evidence before `copy create`; source resumed; exactly one create receipt | recorded |
| G-S4 | Copy finished; postponed indexes created; no `cancelled_at` | true |
| G-S5 | Parked: registry tuple; seed worker 0 replicas; no non-idle sessions | true |
| G-S6 | Seed head and hash canonical (RPC), head ≥ S | true |
| G-S7 | Time-travel parity at S between `sgd2` and the seed. **SQL X.1 (per-table digest at S) is the gate for the singleton/small tables** (`factory`, `bundle`, `pool`, `token`, `data_sources$`). Large tables are checked by `count(*) WHERE block_range @> S` plus a 1 % id-hash sample. `poi2$` digest at S equal (X.2) | equal |
| G-S8 | O8 counts and write-once proofs recorded (§6) | recorded |

### 5.6 Seed evidence JSON (`pinax.aerodrome.seed-copy/v1`, PROPOSED; consumed by the k8s-backfill `target.json` and engine prepare-seed)

```json
{
  "schema": "pinax.aerodrome.seed-copy/v1",
  "deployment": "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",
  "source": {"site_id": 2, "schema": "sgd2", "shard": "subgraphshard_b", "head_at_create": 0},
  "target": {"site_id": 0, "schema": "sgdNNNN", "shard": "aerodrome_b",
             "node_id": "index_node_aerodrome_backfill_0", "active": false, "paused": true},
  "checkpoint": {"number": 0, "hash": "64-hex", "offset": 0, "ingested_header": true},
  "seed_head": {"number": 0, "hash": "64-hex", "rpc_hash_match": true},
  "copy": {"created_at": "RFC3339", "finished_at": "RFC3339", "postponed_indexes_created": true,
           "batch_workers": 4, "tables": [{"entity_type": "Pool", "target_vid": 0, "duration_ms": 0}]},
  "history": {"history_blocks": 2147483647, "earliest_block_number": 13843704},
  "counts": [{"table": "pool", "versions": 0, "active_at_head": 0, "max_vid": 0, "write_once_proved": false}],
  "parity_at_seed": {"tables_compared": [], "poi2_digest_equal": true},
  "receipts": {"graphman_create_stdout_sha256": "64-hex"},
  "sha256": "of this document with this field empty"
}
```

### 5.7 Handed to the generic backfill template (k8s-backfill PR-K2)

| Parameter | Value |
|---|---|
| `target-shard` | `aerodrome_b` |
| `target-postgres-host` | `aerodrome-backfill-postgres-0.aerodrome-backfill-postgres.subgraphs.svc.cluster.local` |
| `parked-node-id` | `index_node_aerodrome_backfill_0` |
| `writer-deployments` | `graph-node-aerodrome-backfill-0` |
| `expected-registry` | `aerodrome_b\|f\|index_node_aerodrome_backfill_0\|t` |
| `active-source-shard` / `active-source-schema` | `subgraphshard_b` / `sgd2` |
| `expected-seed-block` / `expected-seed-hash` | from §5.4 step 6 |
| Capacity | §5.2 |

Additional preflight (PROPOSED for PR-K2): **assert that the C0 worker (`index_node_aerodrome_0`) has no assignment
on `aerodrome_b`** until C3. Do this with a registry query, not a replica count, because the C0 worker legitimately
runs.

---

## 6. Read-only SQL (operator runs; exact queries)

Session preamble for every query:

```sql
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
SET lock_timeout = '1s';
```

Run with `kubectl -n subgraphs exec <pod> -c postgres -- psql -U graph -d graph -X -v ON_ERROR_STOP=1`.

Table definitions are VERIFIED in `GN:store/postgres/src/primary.rs:104-147`, `GN:store/postgres/src/deployment.rs:126-214`,
`GN:store/postgres/src/copy.rs:69-97` and `GN:store/postgres/src/relational/prune.rs:612-626`.

### O1: registry and copy state of `sgd5311` (and the C0/C2 registry checks)

On the **primary**, `postgres-0`:

```sql
-- O1.a sites, activeness, assignment, pause  (expect sgd2 active=t; sgd5311 active=f)
SELECT ds.id, ds.name AS schema, ds.shard, ds.active, ds.created_at,
       a.node_id, a.paused_at, a.assigned_at
FROM public.deployment_schemas ds
LEFT JOIN subgraphs.subgraph_deployment_assignment a ON a.id = ds.id
WHERE ds.subgraph = 'QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV'
ORDER BY ds.id;

-- O1.b in-flight copies touching any Aerodrome site (expect src=2,dst=5311 while unfinished)
SELECT ac.src, ac.dst, ac.queued_at, ac.cancelled_at
FROM public.active_copies ac
WHERE ac.src IN (SELECT id FROM public.deployment_schemas WHERE subgraph = 'QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV')
   OR ac.dst IN (SELECT id FROM public.deployment_schemas WHERE subgraph = 'QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV');

-- O1.c everything else assigned to the worker node ids used here (expect only Aerodrome rows)
SELECT a.node_id, ds.name, ds.subgraph, ds.shard, ds.active, a.paused_at
FROM subgraphs.subgraph_deployment_assignment a JOIN public.deployment_schemas ds ON ds.id = a.id
WHERE a.node_id IN ('index_node_aerodrome_0','index_node_aerodrome_backfill_0')
ORDER BY a.node_id, ds.id;

-- O1.d never recorded as unused (expect 0 rows unless D6 retirement ran)
SELECT id, deployment, namespace, shard, unused_at, removed_at
FROM public.unused_deployments WHERE deployment = 'QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV';
```

On **`aerodrome-postgres-0`** (shard `aerodrome_a`):

```sql
-- O1.e copy job (expect finished_at NULL, target_block_number 30843266)
SELECT src, dst, target_block_number, encode(target_block_hash, 'hex') AS target_hash,
       started_at, finished_at, cancelled_at
FROM subgraphs.copy_state WHERE dst = 5311;

-- O1.f per-table progress (expect Pool ~49%, Burn ~43% unfinished; others finished or pending)
SELECT entity_type, next_vid, target_vid,
       round(100.0 * greatest(next_vid, 0) / nullif(target_vid + 1, 0), 2) AS pct,
       batch_size, started_at, finished_at, duration_ms / 1000 AS work_s
FROM subgraphs.copy_table_state WHERE dst = 5311
ORDER BY finished_at NULLS FIRST, entity_type;

-- O1.g DB-side health (expect health='healthy', failed=false: the "unrecorded transient" class)
SELECT d.id, d.health, d.failed, d.fatal_error, d.earliest_block_number, d.postponed_indexes_created,
       h.block_number AS head, encode(h.block_hash, 'hex') AS head_hash, h.entity_count
FROM subgraphs.deployment d LEFT JOIN subgraphs.head h USING (id) WHERE d.id = 5311;

SELECT id, deterministic, block_range, created_at, left(message, 300) AS message
FROM subgraphs.subgraph_error
WHERE subgraph_id = 'QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV'
ORDER BY vid DESC LIMIT 10;   -- run the same on postgres-2 for sgd2's errors
```

### O4: is `sgd2` history-pruned? (on `postgres-2`)

```sql
-- O4.a expect history_blocks = 2147483647 (unlimited) and earliest_block_number = 13843704
SELECT m.id, m.history_blocks, d.earliest_block_number, d.graft_base, d.health, d.failed,
       h.block_number AS head, encode(h.block_hash, 'hex') AS head_hash, d.synced_at
FROM subgraphs.subgraph_manifest m
JOIN subgraphs.deployment d USING (id)
LEFT JOIN subgraphs.head h USING (id)
WHERE m.id = 2;

-- O4.b any prune ever run (expect 0 rows)
SELECT id, run, first_block, final_block, latest_block, history_blocks, started_at, finished_at, errored_at
FROM subgraphs.prune_state WHERE id = 2 ORDER BY run DESC LIMIT 5;

-- O4.c per-table last pruned block (expect NULL everywhere)
SELECT table_name, is_account_like, last_pruned_block
FROM subgraphs.table_stats WHERE deployment = 2 ORDER BY table_name;
```

### O8: active-row counts per table at a seed block

**O8.a: cheap planner estimate**, safe on the hot `postgres-2` (catalog only). This is the same query as
`graphman stats`, `GN:store/postgres/src/catalog.rs:347-370`.

```sql
SELECT c.relname AS tablename,
       CASE WHEN s.n_distinct < 0 THEN (-s.n_distinct * c.reltuples)::int8 ELSE s.n_distinct::int8 END AS entities_est,
       c.reltuples::int8 AS versions_est,
       CASE WHEN c.reltuples = 0 THEN 0::float8
            WHEN s.n_distinct < 0 THEN (-s.n_distinct)::float8
            ELSE greatest(s.n_distinct, 1)::float8 / c.reltuples::float8 END AS ratio
FROM pg_namespace n
JOIN pg_class c ON c.relnamespace = n.oid
JOIN pg_stats s ON s.schemaname = n.nspname AND s.tablename = c.relname AND s.attname = 'id'
WHERE n.nspname = 'sgd2' AND c.relkind = 'r'
ORDER BY versions_est DESC;

SELECT h.entity_count FROM subgraphs.head h WHERE h.id = 2;   -- total current entities, all types
```

**O8.b: write-once proofs.** These are cheap on `postgres-2`: each uses the partial index
`<table>_block_range_closed` (`GN:store/postgres/src/relational/ddl.rs:203-220`; predicate
`GN:store/postgres/src/relational/index.rs:286,298`). Expect **false** for every row. False supports "max-VID-only"
seed tables.

```sql
SELECT t AS table_name,
       (xpath('/row/c/text()', query_to_xml(format(
          'SELECT EXISTS (SELECT 1 FROM sgd2.%I WHERE coalesce(upper(block_range), 2147483647) < 2147483647) AS c', t),
          false, true, '')))[1]::text::boolean AS has_closed_versions
FROM unnest(ARRAY['transaction','swap','mint','burn','position_snapshot','collect','flash']) AS t;
```

**O8.c: exact active counts at the seed head.** Run on the **stopped seed `sgdNNNN` on `aerodrome-backfill-postgres-0`
only**, never on `postgres-2`. Use `SET statement_timeout = 0`. `upper_inf` means "current at head", which equals
the seed block once parked.

```sql
SELECT t AS table_name,
       (xpath('/row/n/text()', query_to_xml(format(
          'SELECT count(*) AS n FROM sgdNNNN.%I WHERE upper_inf(block_range)', t), false, true, '')))[1]::text::int8 AS active_at_head,
       (xpath('/row/v/text()', query_to_xml(format(
          'SELECT coalesce(max(vid), 0) AS v FROM sgdNNNN.%I', t), false, true, '')))[1]::text::int8 AS max_vid
FROM unnest(ARRAY['factory','bundle','token','pool','tick','position','pool_day_data','pool_hour_data',
                  'token_day_data','token_hour_data','tick_day_data','tick_hour_data','uniswap_day_data',
                  'transaction','swap','mint','burn','position_snapshot','collect','flash','poi2$','data_sources$']) AS t;
-- data_sources$ has no block_range upper bound semantics; read its count(*) and max(vid) only.
```

**O8.d: reducer working-set refinements** (on the stopped seed). These are for the A reducer/engine bounded-state
designs, not gates.

```sql
-- burned (evictable) positions vs live ones at the seed
SELECT count(*) FILTER (WHERE owner = '\x0000000000000000000000000000000000000000'::bytea) AS burned,
       count(*) AS all_current
FROM sgdNNNN.position WHERE upper_inf(block_range);

-- current-period interval rows (IDs embed the period; only these are re-readable)
SELECT 'pool_day_data' AS t, count(*) FROM sgdNNNN.pool_day_data
 WHERE upper_inf(block_range) AND date >= (SELECT max(date) FROM sgdNNNN.pool_day_data)
UNION ALL
SELECT 'pool_hour_data', count(*) FROM sgdNNNN.pool_hour_data
 WHERE upper_inf(block_range) AND period_start_unix >= (SELECT max(period_start_unix) FROM sgdNNNN.pool_hour_data);
-- repeat the pattern for token_day_data(date), token_hour_data(period_start_unix), tick_day_data(date), uniswap_day_data(date)
```

The column names (`owner`, `date`, `period_start_unix`) follow `SB/aerodrome-slipstream-base/reference/schema.graphql`
and Graph Node's snake_case. They are ASSUMED until `\d sgdNNNN.pool_hour_data` confirms them.

### D: drain checks (used in §4.3 and §5.4; on the shard that holds `<schema>`)

```sql
-- D.1 persisted head (poll every <=3 s; need >=15 s unchanged)
SELECT h.block_number, encode(h.block_hash, 'hex') FROM subgraphs.head h WHERE h.id = <site_id>;
-- D.2 granted write locks on the deployment schema (need 0)
SELECT count(*) AS write_locks
FROM pg_locks l JOIN pg_class c ON c.oid = l.relation JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = '<schema>' AND l.granted
  AND l.mode IN ('RowExclusiveLock','ShareRowExclusiveLock','ExclusiveLock','AccessExclusiveLock');
```

### C: seed copy progress (on `aerodrome-backfill-postgres-0`)

```sql
-- C.1
SELECT src, dst, target_block_number, started_at, finished_at, cancelled_at FROM subgraphs.copy_state;
-- C.2
SELECT entity_type, next_vid, target_vid, round(100.0*greatest(next_vid,0)/nullif(target_vid+1,0),2) AS pct,
       finished_at, duration_ms/1000 AS work_s
FROM subgraphs.copy_table_state ORDER BY finished_at NULLS FIRST, pct;
```

### X: overlap parity (G-S7 at S, and G-X at F before cutover)

Run the same query on both stores. Compare outputs.

```sql
-- X.1 per-table state digest at block :b (example: pool; list columns explicitly, excluding vid and block_range)
SELECT count(*) AS n,
       md5(string_agg(md5(row(id, token_0, token_1, liquidity, sqrt_price, tick, fee_growth_global_0x128,
                              fee_growth_global_1x128, total_value_locked_usd)::text), '' ORDER BY id)) AS digest
FROM <schema>.pool WHERE block_range @> :b;
-- X.2 Fast PoI digest at block :b (one row per causality region)
SELECT id, encode(digest, 'hex') AS digest FROM <schema>."poi2$" WHERE block_range @> :b ORDER BY id;
```

The X.1 column names are illustrative (ASSUMED snake_case). Generate the real lists from `information_schema.columns`
(all columns except `vid` and `block_range`). Large
tables use the `count(*)` plus 1 % `abs(hashtext(id)) % 100 = 0` sample variant. `block_range @> :b` uses the GiST
index `(id, block_range)` (`GN:store/postgres/src/relational/ddl.rs:443-454`). The `poi2$` digest column name is
ASSUMED; confirm it with `\d`.

---

## 7. Test plan and acceptance gates for Option C

| Gate | Fixture or measurement | Pass condition |
|---|---|---|
| G-C0.1 placement | `kube_pod_info{pod=~"graph-node-aerodrome-0.*"}` | `node="dom153"` |
| G-C0.2 assignment | O1.a / O1.c | `sgd2 → index_node_aerodrome_0, unpaused`; `sgd5311 → index_node_aerodrome_0, paused` |
| G-C0.3 liveness | `deployment_status`, head delta | status 2 on the new pod within 10 min; head advancing; no `sgd: 2` on `chain-base-0` |
| G-C0.4 correctness | `subgraph_error` (O1.g on postgres-2); `deployment_synced` / `health` | no new errors since the move; health `healthy` |
| G-C0.5 speed (24 h) | Appendix A queries on the new pod | CPU sections ≤ 5.2 ms per handler; ≥ 1.5 blocks/s while handlers per block ≤ 60; throttled periods ≤ 2 % |
| G-C0.6 neighbour relief | `chain-base-0` CPU and memory; restarts | CPU −≥0.8 cores; no new OOM attributable |
| G-C0.7 serving | `indexingStatuses` via the serve pool; the Gateway QoS row for `QmasYjyp` if allocated | unchanged |
| G-C0b alerts | `subgraphs-alerts/tests/indexing-worker.test.yaml` fixtures `stall_10_16`, `normal_restart_37min`, `deterministic_failed_for_days` | as specified in §4.4 |
| G-C1.a cache | before and after Appendix A at equal density (±10 % handlers per block) | store-read ms/block −≥15 %; memory under 80 % of the limit |
| G-C1.b RPC | qualification receipt (as `kan-arbitrum-main-rpc.md`) plus eth_call ms/block | all calls equal by-hash and by-number; −≥25 % eth_call |
| G-S0…G-S8 | §5.5 | all |
| G-X (C3) | X.1/X.2 at F on `sgd2` and `aerodrome_b` | all tables equal; PoI equal |

---

## 8. PR-sized slices (ordered)

| # | Repository | Slice | Depends on | Approval |
|---|---|---|---|---|
| C-1 | k8s-subgraphs | **C0 worker pin and doc**: `core/kan/graph-node-aerodrome.yaml` (nodeSelector, comments), `docs/aerodrome-dedicated-worker.md` (runbook §4.3, rollback, PromQL), `docs/kan-postgres2-offload-2026-09-21.md` addendum, `README.md:115` link | — | L1, then live L2/L3 |
| C-2 | k8s-subgraphs | **Alerts**: `subgraphs-alerts/base/indexing-worker.yaml`, kustomization, tests, CI step, `docs/alert-policy.md` | — | L4 |
| C-3 | k8s-subgraphs | **C1.a entity cache** with before/after evidence in the doc | C-1 plus 72 h | L5 |
| C-4 | k8s-subgraphs | **C1.b RPC override** (render-config, Secret instructions, qualification receipt `fleet/kan-base-rpc-<date>.json`) | an RPC endpoint from the owners | L6 |
| C-5 | k8s-subgraphs | **Landing store and seed worker**: §5.3 files, `docs/aerodrome-seed-copy.md` | D6 / infra approval; C-1 | L7 |
| C-6 | (live) | Seed copy per §5.4; evidence `fleet/aerodrome-seed-copy-<date>.json` | C-5 | L8 |
| C-7 | k8s-subgraphs | **Park the seed**: worker replicas 0; record the seed in the doc | C-6 | L9 |
| C-8 | k8s-subgraphs | **Retire `aerodrome_a`/`sgd5311`** (§4.7) | C-7, D6 | L11 |
| C-9 | k8s-subgraphs | **C3 cutover record** and `sgd2` retirement doc | Option A certified, G-X | L10 |
| C-10 (optional) | pinax-skills | Generic procedure "decompose Graph Node block time with `deployment_sync_secs` and project ETA from trigger density" for the generic skill (section exclusivity, `host_fn_name` label, NPM4-style density sampling). No IDs or dates (`skills-conventions` portability) | — | none |

Not duplicated here: the `backfill-flags` protocol label (SYNTHESIS PR-K3), the generic noop and backfill templates
(PR-K1/K2), and engine work.

---

## 9. Open items and what needs the user or infra

- **Approvals L1–L11** (§4.9). C0 (L1–L4) can start immediately and is reversible.
- **D6:**
  - landing store `aerodrome_b` 12 TiB on dom153;
  - seed worker;
  - fate of `aerodrome_a`/`sgd5311` (recommended: retire after C2);
  - timing relative to the postgres-2 fill (about 30–45 days).
- **OPEN:**
  - Does a Kan-local Base archive RPC exist for C1.b? (RPC owners.)
  - Exact O1/O4/O8 results (operator SQL in §6).
  - Whether graphman command semantics are identical in v0.45.0 (cited source is v0.44 `77823b5a`).
  - `poi2$` and interval-table column names.
  - Copy throughput into dom153 with 4 to 8 workers.
- **Infra:** dom153 CPU must keep at least 4 free cores for C0 now (VERIFIED 33 free), plus about 10 during C2.
- **Governance (D7):** after C0, record the #86 24 h/72 h same-pod ETA windows from the dedicated pod. They are
  measurable there and not on `chain-base-0`.

---

## Appendix A: PromQL used (VictoriaMetrics `P4169E866C3094E38`; replace `<pod>` and `<W>`)

```
# section decomposition (exclusive; process stage sums to block_processing_duration)
sort_desc(sum by (stage,section)(increase(deployment_sync_secs{deployment="QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",pod=~"<pod>.*"}[<W>])))
# blocks, handlers, triggers, block time, transact
max(max_over_time(deployment_head{deployment="QmasYjyp…",shard="subgraphshard_b"}[5m])) - max(max_over_time(deployment_head{…}[5m] offset <W>))
sum(increase(deployment_handler_execution_time_count{deployment="QmasYjyp…",pod=~"<pod>.*"}[<W>]))      # and _sum; by (handler)
sum(increase(deployment_block_processing_duration_sum{…}[<W>]))                                         # and _count
sum by (host_fn_name)(increase(deployment_host_fn_execution_time_count{…}[<W>]))                       # and _sum
sum by (contract_name,method)(increase(deployment_eth_call_execution_time_count{…}[<W>]))               # and _sum, _bucket
# throttling and CPU
sum by (pod)(rate(container_cpu_cfs_throttled_periods_total{cluster="kan-subgraphs-a",namespace="subgraphs",pod=~"<pod>.*",container="graph-node"}[<W>]))
  / sum by (pod)(rate(container_cpu_cfs_periods_total{…}[<W>]))
# availability (flat 10-min intervals in 30 d)
count_over_time((max(deployment_head{deployment="QmasYjyp…",shard="subgraphshard_b"}) - max(deployment_head{…} offset 10m) <= 0)[30d:10m])
# placement history
max by (pod,node)(kube_pod_info{cluster="kan-subgraphs-a",namespace="subgraphs",pod=~"graph-node-chain-base-0.*|graph-node-aerodrome-0.*"})
# sizes
sum(pg_stat_user_tables_size_bytes{cluster="kan-subgraphs-a",schemaname="sgd2",job=~".*shard-b.*"})
max(kubelet_volume_stats_used_bytes{cluster="kan-subgraphs-a",namespace="subgraphs",persistentvolumeclaim="pgdata-postgres-2"})
```

## Appendix B: raw window numbers (VERIFIED)

| Window | Blocks | Handlers | `store_get` calls | Host `eth_call` | `block_processing_duration` sum |
|---|---:|---:|---:|---:|---:|
| W_A, end 2026-10-16T12Z, 3 days | 523,116 | 25,437,246 | 350,430,396 | 34,078,449 | 257,466 s |
| W_C, end 2026-10-20T20Z, 12 h | 49,828 | 2,838,421 | 42,534,534 | 3,934,917 | 43,132 s |
| W_B, end 2026-09-29T12Z, 3 days | 123,639 | 5,203,611 | | | 102,078 s |

Per handler (W_A, `_sum`/`_count`):

| Handler | Count | Seconds |
|---|---:|---:|
| Swap | 4,608,370 | 76,498 |
| Burn | 5,031,053 | 44,185 |
| Mint | 1,690,383 | 24,873 |
| Transfer | 5,805,839 | 32,393 |
| Collect | 4,992,295 | 11,071 |
| Increase | 1,690,230 | 3,681 |
| Decrease | 1,618,727 | 3,433 |
| PoolCreated | 91 | 6.7 |
| Initialize | 91 | 1.0 |
| Flash | 167 | 0.2 |

eth_call (W_A):

| Method | Calls | Seconds |
|---|---:|---:|
| `getPool` | 900,782 | 24,660 |
| `positions` | 7,183,898 | 6,311 |
| `feeGrowthGlobal0X128` | 3,303,922 | 5,982 |
| `feeGrowthGlobal1X128` | 3,303,922 | 5,982 |
| `ticks` | 4,955,679 | 18,878 |
| ERC20, 4 methods | 57 each | |
