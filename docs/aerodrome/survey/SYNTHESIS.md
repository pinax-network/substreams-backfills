# Synthesis: backfilling Aerodrome Slipstream Base with Substreams and the engine

Date: 2026-10-20. Strictly read-only. This document cross-checks the eight survey reports in this directory, settles their contradictions against primary sources, and turns them into an architecture decision, a phased plan with deliverables per repository, and the list of decisions that belong to the user.

Target: deployment `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV` on Base. Factory `0x5e7b…809a` starts at 13,843,704 and the NonfungiblePositionManager (NPM) `0x8279…5b72` at 13,843,719. There is no graft. Spec 1.2.0 (Fast PoI), `nonFatalErrors`, and a `Pool` template.

Evidence labels:

- **VERIFIED**: I read the code, config or data myself during this pass, or re-ran the query.
- **REPORT-VERIFIED**: a survey agent verified it and I have no reason to doubt it. Its report and line are cited.
- **DOC**: documentation says so.
- **ESTIMATE**: arithmetic from verified inputs.
- **OPEN**: needs access or a measurement that nobody has done.

Short names used for source locations:

- `ENG/` is `scratchpad/ro/engine` (engine `main` `5c98b57`).
- `K8S/` is `scratchpad/ro/k8s-subgraphs` (`4da0b37`).
- `V4/` is `scratchpad/ro/v4-subgraph`.
- `SB/` is `/Users/denis/Github/substreams-backfills` (`bbe3783`).
- `KSS/` is `~/Github/k8s-substreams` at `origin/main` `26c36a8`, read with `git show`.
- `SS/` is `~/Github/substreams` at `v1.22.0`.
- `GN:` is graph-node `77823b5a` (v0.44), read with `git show` from the cargo bare repo.

---

## 0. Bottom line

1. **A Substreams package alone cannot backfill Aerodrome.** Every engine-compatible design has a *sequential* reducer that holds Graph entity state. Aerodrome's pricing (`Token.derivedETH`, Decimal128 accumulators that round after each step, read-after-save helpers) and the PoI chain are recurrent. Substreams Stores cannot express them (VERIFIED `ENG/docs/substreams-stores.md:5-19,192-200`). The engine also re-merges every `SetEntity` against its own baseline (VERIFIED `ENG/src/generic_state.rs:18-25`).
   - So the "engine-compatible Substreams" is an **extractor**. It emits Graph-Node-ordered triggers plus the answers to every `eth_call`, and optionally mergeable Stores.
   - A **family reducer** turns that extractor output into Graph Node rows and PoI. The V4 lane works the same way (VERIFIED `ENG/src/state.rs`, `ENG/src/reducer.rs`).
2. **Engine changes are unavoidable on every route.**
   - The only production loader path is hard-wired to Uniswap V4. Evidence: `ENG/scripts/check-compatibility-contract.sh:7-9` pins the V4 adapter, deployment and graft base, and `ENG/scripts/compute-postgres-segment.sh:30` defaults to the V4 contract (VERIFIED).
   - The family-neutral `block-changes-v1-framed` path can only start from empty state. Its only loaders are pinned to the V3 root, it has 1,153-block budgets, and it holds the entire entity store in RAM (VERIFIED `ENG/src/generic_state.rs:379-381`; REPORT-VERIFIED `ENG/src/v3_root_load.rs:20-25`).
3. **The "hundreds of millions of live entities" worry applies only to the generic path, not to a family reducer.**
   - V4's reducer drops write-once event entities after each block (`discard_streamed_block_history`, VERIFIED `ENG/src/state.rs:250-265`). Its seed capture records only the max VID for those tables (VERIFIED `ENG/scripts/capture-direct-postgres-seed.sh:83-105`).
   - Aerodrome's ID schemes make the same thing provable:
     - Swap, Mint and Burn are `{tx}#{pool.txCount}`;
     - PositionSnapshot is `{pos}#{block}`;
     - Transaction is the tx hash;
     - day/hour IDs embed the period (REPORT-VERIFIED `aerodrome-target.md` §4).
   - A seeded Aerodrome reducer therefore needs only Factory, Bundle, Token, Pool (≈1,501, = `data_sources$` rows), Tick, Position and current-period day/hour rows.
4. **The wave-ordering trap is real on the deployed contract lineage.** Slipstream `CLFactory.createPool` calls `CLPool.initialize` (which emits `Initialize`) *before* it emits `PoolCreated`.
   - VERIFIED via `gh api` on `aerodrome-finance/slipstream`: `CLFactory.sol:81` vs `:94` at the 2024-04-05 Base commit `ce33300ac4`, and `:88` vs `:101` on `main`, plus `CLPool.sol:178`.
   - Graph Node runs `handleInitialize` in a later wave of the same block (REPORT-VERIFIED `GN:core/src/subgraph/runner/mod.rs:914-990`; VERIFIED `SB/mapping-host/src/runner.rs:11-23`).
   - The extractor must emit `(wave, block_index, host_order)`, not `block_index` alone.
5. **The mapping-host (deployed WASM) is not a production path for Aerodrome.**
   - Its ceiling is set by single-threaded WASM compute: about 0.17–0.29 s/block, i.e. 3.5–5.8 blocks/s, realistically 2–4 (REPORT-VERIFIED and ESTIMATE, `v3-lane-state.md` §4.3).
   - It cannot be range-parallelised.
   - Use it as the **exact oracle** for windows starting at the root, and as the generic route for low-density subgraphs.
6. **Native Graph Node is slow and getting slower.**
   - Head is 34,728,090 against Base 52,868,270 (VERIFIED 2026-10-20). The current 6 h pace is 1.14 blocks/s gross (VERIFIED) and the steady state was 2.02 blocks/s (REPORT-VERIFIED).
   - Base grows at 0.5 blocks/s, so the ETA is about 138 days at steady state and about 330 days at today's pace (ESTIMATE).
   - Trigger density per block roughly doubled in 30 days. The dedicated copy `aerodrome_a/sgd5311` reports `deployment_status=4` (failed) (VERIFIED).
7. **Recommended architecture: Option A** (Substreams extractor plus a native Aerodrome reducer that emits canonical `BlockChanges` per block), seeded from a fresh Graphman copy of the live `sgd2` at about 34.7M.
   - The mapping-host and `sgd2` time-travel queries serve as differential oracles.
   - Option C (dedicated fast native worker) should run in parallel as the zero-risk baseline and as the post-cutover continuation.
8. **What can start now without user decisions:**
   - the generic k8s **noop** WorkflowTemplate in its own tree;
   - the pinax-skills generic skill and the k8s runbook skill;
   - the Aerodrome extractor scaffold with fixtures and the wave test;
   - the mapping-host Aerodrome bundle plus Base fixtures (oracle);
   - pinning the Slipstream storage layouts.
9. **What cannot run yet:**
   - the backfill workflow (needs an engine family release);
   - the full-range noop (needs a *frozen* extractor SPKG, because any rebuild changes module hashes and discards the cache);
   - the landing store (needs approval and capacity; about 5–8 TB at head, ESTIMATE §3 Q7).

---

## 1. Contradictions between reports and how they resolve

| # | Topic | Claims | Primary-source check | Resolution |
|---|---|---|---|---|
| C1 | Initialize before PoolCreated | `v4-substreams-pattern` says VERIFIED on `velodrome-finance/slipstream` main. `aerodrome-target` §2 says "CLAIMED from memory". | `gh api` on **aerodrome-finance**/slipstream: `CLFactory.sol` at `ce33300ac4` (2024-04-05, "optimism -> base") lines 81 (`CLPool(pool).initialize`) and 94 (`emit PoolCreated`). On `main`, lines 88 and 101. `CLPool.sol:178` `emit Initialize`. | **True** for the Base source lineage. Not compared to deployed bytecode; a fixture on a real pool-creation block must confirm it. Note that `main` added a `legacyCLFactory` path (commit `41340ed237`, 2025-10-14), which suggests a newer CL factory exists. Its pools are not indexed by this deployment, which pins `0x5e7b…`. |
| C2 | Live-entity volume blocks a seeded build | `engine-contract` says 200M+ live entities make the generic store infeasible. `v3-lane-state` says the V4 seed recipe would include about 385M event rows. | `ENG/src/state.rs:250-265` (`discard_streamed_block_history`: "These six entity types are immutable … A later block cannot legally reference the same identifier"). `ENG/scripts/capture-direct-postgres-seed.sh:83-105`: `tables` (active rows captured) excludes Transaction, Swap and similar; `all_tables` adds them for **max VID only**. `ENG/src/generic_state.rs:379-381` keeps every entity in a `BTreeMap`. | **Both are right about the generic path. Both are wrong for a family reducer.** A family reducer can treat write-once types as block-local, as V4 does. Aerodrome's write-once property follows from its ID schemes (`aerodrome-target.md` §4 entity table). The generic `GenericState` and `GenericCheckpoint` do need eviction or a disk-backed store (#70) before any large family. |
| C3 | `sgd5311` completeness | `v3-lane-state` says "holds about 64% of `sgd2`'s rows". `k8s-backfill-stack` says completeness unverified. | VictoriaMetrics `pg_stat_user_tables_n_live_tup` (2-day max): `sgd2` (job `postgres-exporter-shard-b`) was 744–800M rows on 09-21..27, and is 1.314B now. `sgd5311` (job `postgres-exporter-aerodrome`) is 787M–810M. `deployment_status{pod=graph-node-aerodrome-0…}` = 4. | The "64%" compares against **today's** `sgd2`. `sgd5311`'s row count matches `sgd2` **at copy time** (checkpoint 30,843,266, `K8S/docs/kan-postgres2-offload-2026-09-21.md:103-114`). The data copy plausibly completed, and the deployment then failed (INFERENCE; registry and copy state remain OPEN). Note that `riv-subgraphs-a` has an unrelated `sgd5311`, so always filter by `cluster` and `job`. |
| C4 | Dedicated Aerodrome worker state | `v3-lane-state`: parked 1→0 on 09-08 (k8s #929). `k8s-backfill-stack`: replicas 1, idle. | `K8S/core/kan/graph-node-aerodrome.yaml:15` `replicas: 1`. `git log`: `e3f422b` #929 (09-08) parked it, then `87ccffb` #1044 (09-21, postgres-2 offload) re-enabled it for the copy. Live: status 4 for `QmasYjyp` on `graph-node-aerodrome-0`. | Worker is **running (1 replica)** and its only assignment (`sgd5311`) is **failed**. The CPU reasoning behind the #929 parking still applies to dom153. |
| C5 | Substreams endpoint | `k8s-backfill-stack`: `base.substreams.riv-prod-firehose-a.pinax.io:443`. `token-api-noop-pattern`: `base.substreams.kan-prod-firehose-a.pinax.io:443`. | `dig`: kan → 172.20.114.2, riv → 172.19.114.2, `kan-sst2` → NXDOMAIN. `KSS/apps/substreams-tier1/base/deployment.yaml:52`: one state-store URL (`…river.consul…/${NETWORK}-sf-${VERSION}-substreams-state`), with no per-cluster override (REPORT-VERIFIED `git grep`). | **Both work cache-wise**, because both write the same Ceph bucket. Prefer the **same-DC kan** route. Fall back to **riv**, which terminal certification already uses from Kan. Pass `ENDPOINT` explicitly to *both* noop and engine, since the engine default `kan-sst2` is dead (VERIFIED `ENG/scripts/compute-postgres-segment.sh:25`). Egress from Kan pods to 172.20.114.2:443 is OPEN, so smoke-test with 1 block first. |
| C6 | Where the noop template lives | `token-api-noop-pattern` §4.1: inside `subgraphs-operations/backfill/kan/`. `k8s-backfill-stack` §5.1: separate tree. | `K8S/subgraphs-operations/backfill/tests/test-contract.sh` uses **global** `grep -Fc` counts over the rendered overlay: `:155` `WORKFLOW_NAME`=9, `:238` `memory: 256Gi`=8, `:300` graph-node image=19. CI lints only explicit overlays (`K8S/.github/workflows/ci.yaml:67-75`). Flux `subgraphs-backfill` is `prune: true` on that path (`K8S/deploy/kan/backfill.yaml:16,28`). | A noop that avoids those strings would pass in `backfill/kan`, but a production-backfill clone would not. **Use a separate tree** with its own Flux Kustomization, contract test and CI lint. This also keeps the out-of-band live template (`uniswap-v4-base-sgd2-overlap-replay-candidate`) isolated from new prune scopes. |
| C7 | Noop fan-out | `k8s-backfill-stack` §5.2: `withParam` sub-range fan-out with a semaphore. `token-api-noop-pattern`: one long request. | `SS/orchestrator/plan/requestplan.go:73-79`: in production mode **every** request plans `BuildStores` from the lowest store `initialBlock`, whatever its start block. | For any package with Stores (template tracking needs one), run **one full-range request** with a high workers header. Fan out only for a map-only package, or after Stores are warm. |
| C8 | Per-store size limit | Reports say 2 GiB (V4 history). | `KSS/apps/substreams-tier1/base/deployment.yaml:59` `--substreams-tier1-store-size-limit=3758096384`, raised to 3.5 GiB by `6cbc0f4` (#61, 2026-10-02). | Pinax prod is now **3.5 GiB per Store**. Still shard any per-pool, per-tick or per-position Store, and keep headroom. |
| C9 | Mapping-host throughput | `aerodrome-target`: 1.9–10.9 blocks/s measured on V3, "far worse than graph-node". `skills-conventions` outline: mapping-host is "segment-parallel". `v3-lane-state`: those numbers predate #147 and measure recording latency; ceiling 3.5–5.8 blocks/s; no range parallelism. | `SB/mapping-host/src/runner.rs:11-23` (wave model, full prior state). `v3-lane-state` re-derived the pre-#147 per-block deep copy (`git show e7f1dd4:mapping-host/src/store.rs:98-100,135-143`). | `v3-lane-state` is right. The mapping-host is **not** range-parallel without a per-range state seed. Its realistic rate is about 1–2× Graph Node. The skill must not say "segment-parallel". |
| C10 | Can a Substreams module emit `BlockChanges`? | `skills-conventions` §3.1 lists "Substreams map emitting BlockChanges" as producer option (a). `engine-contract` §3.2: format yes, semantics no. | `ENG/docs/substreams-stores.md:192-200` (derivedETH recurrence, Decimal128 accumulators "unsafe as add bigdecimal", PoI "inherently sequential fold"). `ENG/src/generic_state.rs:18-25` (materialized re-merge). | Only for **stateless or mergeable-only** mappings. For any AMM or pricing subgraph, `BlockChanges` must come from a sequential reducer: in-engine, a native producer, or the mapping-host. The skill must state this decision rule. |
| C11 | eth_call for `addMissingWhitelistedPools` | `substreams-reuse` §5: "not derivable from events". `aerodrome-target` §5.3/§6 C10: `getPool(USDC, token, {100,500,3000,10000})` on the first swap per token whose version is null or 0. | Decompile (REPORT-VERIFIED `D:Pool.dcmp:6737-6810,7044-7066`). | **Derivable.** The arguments are constants plus the swap's tokens. A superset (once per token, or per swap) is safe, because `eth_call` at a fixed block hash is pure. Only `Token.version=2` persists. |
| C12 | Storage-change derivation | `substreams-reuse`: storage changes are intra-transaction values, so they cannot replace end-of-block `eth_call`. `aerodrome-target`: everything except ERC20 can be derived. | Graph Node pins calls to the block **hash** (post-block state) (REPORT-VERIFIED `GN:runtime_adapter.rs:335`; VERIFIED the `block_ptr` in `ContractCall`). | Both are partly right. End-of-block slot value = the **last non-reverted** storage change in the block, or else the carried value. That needs a per-slot "last value" Store from the contract's creation onward. It is feasible, but the Slipstream `CLPool` and NPM layouts must be pinned (pools are EIP-1167 clones), and changes inside reverted calls must be excluded. |
| C13 | Handler density | 58 per block (`aerodrome-target`, 6 h at 34.70M) vs 48.9 (`v3-lane-state`, 10-13..16). | Different windows. | Consistent. Density is rising (36.8 → 48.9 → 58). |
| C14 | eth_call config on Base tiers | Reports list `RpcBatch` on Base tier2 and `ETH_CALL_*` overrides as unverified. | `KSS/chains/base/v2/prod/substreams-tier1/kustomization.yaml:34` sets `--substreams-rpc-endpoints`. `git grep ETH_CALL_FALLBACK_TO_LATEST\|ETH_CALL_USE_BLOCK_NUMBER origin/main` is empty. V4 `map_events` calls `rpc::eth_call` (`V4/src/metadata.rs:35-49`), and its production cache build ran on Pinax Base. | eth_call is configured, with **no non-deterministic overrides**. Tier2-side forwarding is not re-read, but V4 production is strong evidence that it works. The archive-RPC capacity to serve ~0.7–1B calls is OPEN. |

---

## 2. What "compatible with substreams-graph-node-backfill" means (precise contract)

All items below are VERIFIED unless marked.

**Engine input formats.** `state-replay --input-format` has five modes. Four decode `pinax.uniswap.v4.base.*` and drive the V4 reducer. Only `block-changes-v1-framed` is family-neutral (REPORT-VERIFIED `ENG/src/bin/state-replay.rs:3540-3549,3649-3662,487-489`). A new family therefore either:

- **(i)** adds a family input format plus reducer to the engine (the V4 precedent), or
- **(ii)** supplies canonical `pinax.graph.backfill.v1.BlockChanges` in BCF1 clock-v1 frames from a sequential producer.

Requirements for route (ii):

- one non-empty message per Observed block;
- `compatibility_id` = SHA-256 of the descriptor;
- prost-canonical bytes;
- per-save `written_fields` plus `materialized`;
- Graph-Node operation order;
- region `ethereum/base`;
- the `deterministic_error_policy` must equal the descriptor's. For Aerodrome it is `non_fatal`, and any deterministic error is refused when a data-source companion is used.

Sources: `engine-contract.md` §2.1–2.3; `ENG/src/block_changes_input.rs:494-548`.

**Transport.** `cmd/substreams-native` relays raw map output into frames in production mode, for any output type (REPORT-VERIFIED `ENG/cmd/substreams-native/main.go:114,124`). It is cache-compatible with a production-mode noop (`ENG/docs/native-protobuf.md:172`).

**Physical landing.** Required:

- a physical profile with a `.sha256` sidecar; spec < 1.3.0 (Aerodrome 1.2.0 is fine);
- no immutable tables and no committed removes (Aerodrome has none);
- String IDs only (Aerodrome complies);
- a `data_sources$` companion, needed for the `Pool` template.

No profile is `production_selectable`. A live-catalog capture from the target schema is required (`engine-contract.md` §2.4–2.5).

**Release identity.**

- Immutable SPKG release assets, pinned by SHA-256, module hash, output type and initial block in `adapters/<family>/compatibility.json`.
- Runtime image pinned by digest, with binary SHA-256s.
- Kubernetes pins `@sha256:` (`engine-contract.md` §6).
- Host-built SPKGs are never production-identical (`V4/AGENTS.md:56-59`).

---

## 3. Critical questions and answers

### Answered from primary sources

**Q1. Can we make "a Substreams that is compatible with the engine" for Aerodrome without engine changes?**
No. See §0.1–0.2. Either the engine gains an Aerodrome family, or the generic path is scaled up. In both cases engine work is needed (VERIFIED `check-compatibility-contract.sh:7-9`, `generic_state.rs:379-381`).

**Q2. What must the Substreams emit?** A deployment-pinned, Graph-Node-ordered trigger stream plus the answers to every call. In detail:

- *Triggers*:
  - Factory `PoolCreated` (Slipstream topic `0xab0d57f0…`) at or after 13,843,704;
  - NPM `IncreaseLiquidity`, `DecreaseLiquidity`, `Collect` and `Transfer` at or after 13,843,719;
  - Pool-template `Initialize`, `Swap`, `Mint`, `Burn` and `Flash` gated by "the pool was created in this block or earlier" (creation-**block** gate, not ordinal; `SB/mapping-host/src/runner.rs:18-21`).
- *Order key*: `(wave, block_log_index, host_order)`. Wave 0 covers hosts that existed at block start. Wave k+1 covers hosts created in wave k, re-scanning the whole block. Order is trigger-major and host-minor.
  - Aerodrome's same-block cases are `Initialize` for a new pool (always wave 1), and any `Mint` or `Swap` of a pool created in the same block, for example through an NPM multicall that creates and initializes the pool. Those land in wave 1 *after* the wave-0 NPM `IncreaseLiquidity` and `Transfer`. The NPM-multicall case is ESTIMATE: it is from contract knowledge and needs a fixture.
- *Successful-transaction receipt logs*, with these transaction fields carried as Graph Node exposes them: hash, index, from, to, `gasLimit` (the mapping writes it into `Transaction.gasUsed`), `gasPrice`, plus block number, hash and timestamp (REPORT-VERIFIED `aerodrome-target.md` §4). OP deposit-tx (0x7e) conversion is OPEN.
- *Call answers*, as raw `(address, calldata) → value | revert` at the block hash, covering the ten call kinds C1–C10 (`aerodrome-target.md` §6):
  - ERC20 `symbol`, `name`, `totalSupply` and `decimals` per new token on `PoolCreated`. The bytes32 variants share selectors, so one raw retval serves both decodes.
  - `feeGrowthGlobal0/1X128` per Swap and Flash.
  - `ticks(lower/upper)` per Mint and Burn.
  - Swap-walk `ticks(i)` for a **superset** of candidate ticks: canonical-spacing grid from `feeTierToTickSpacing(feeTier)`, ticks ever minted, at most 101 per swap.
  - `positions(tokenId)` per NPM event.
  - Chained `getPool(t0,t1,int24)` from the positions result.
  - `getPool(USDC,token,{100,500,3000,10000})` per swap token (superset).

  Emitting raw values keeps the mapping's fallbacks (string → bytes32 → `"unknown"`; decimals to 0 on revert) in the reducer, where they are tested against the decompile (`aerodrome-target.md` §5.1).

**Q3. Does Aerodrome need a seed, and how large is it?** Not semantically: there is no graft, so a root replay is legal (`SB/aerodrome-slipstream-base/README.md:16`). Seeding at about 34.7M saves about 21M of the 39M blocks. With a family reducer the seed is small: the active rows of Factory, Bundle, Token, Pool, Tick, Position and current-period interval rows, plus max VIDs and the PoI digest (V4 recipe, VERIFIED §1 C2). The exact active-row counts are OPEN and need read-only SQL.

**Q4. Is the wave trap present on Base?** Yes (§1 C1).

**Q5. Is Substreams `eth_call` deterministic on Pinax Base?** It is block-hash pinned by default, with no overrides configured (§1 C14). Caveats:

- tier2 caches answers forever, so a bad archive answer persists;
- reverts, empty `0x` and decode failure must all map to Graph's revert/Null (`SB/mapping-host/src/calls.rs:1-40`);
- send `X-substreams-acknowledge-non-deterministic: true` on both noop and backfill requests. It is harmless if not enforced (DOC `SS/docs/release-notes/change-log.md:671`).

**Q6. Can the noop be a separate Argo workflow whose cache the engine reuses?** Yes, under four conditions:

- production mode (`substreams sink noop` forces it, `SS/cmd/substreams/sink_noop.go:56`);
- the same SPKG bytes, params and output module;
- the same state bucket (both DCs share one, §1 C5);
- one request per range for a package with Stores (§1 C7).

The engine's per-segment prewarm (`BACKFILL_PREWARM_SUBSTREAMS=1`, `K8S/subgraphs-operations/backfill/kan/production-workflow-template.yaml:455`) then becomes a cheap cache-hit check. The existing gate `target_block <= cache_last` (`…production-workflow-template.yaml:143`) is the hand-off.

**Q7. How big is the landing database at head?** ESTIMATE:

- `aerodrome_a` holds 810M rows in about 1.076 TB, so about 1.33 KB per row including indexes (row count VERIFIED, size REPORT-VERIFIED).
- `sgd2` grew by about 242M rows between 10-05 and 10-17 (VERIFIED), about 140–160 rows per block now, and rising with density.
- The remaining 18.1M blocks × 150–250 rows ≈ 2.7–4.5B rows, so 4.0–5.8B rows in total, about **5.3–7.7 TB**.
- With the 70% fill gate, the store should be **8–12 Ti**.
- The k8s report's "3.5 TB-class" (a claim in `aerodrome-postgres.yaml`) is too low.
- dom153 has 51.8 TiB free in its thin pool (REPORT-VERIFIED). dom157 forbids new volumes (`K8S/AGENTS.md:84-87`).

**Q8. Which Graph Node is syncing it now, and how fast?** VERIFIED 2026-10-20:

- Only Kan `graph-node-chain-base-0` (shard `subgraphshard_b`, `sgd2`) reports a head: 34,728,090.
- Base head is 52,868,270.
- The last 6 h ran at 1.14 blocks/s.
- No riv series exists. That is not structural absence proof for eligibility.

**Q9. Is the engine moving?** No. Engine `main` has been `5c98b57` since 2026-09-07. There are no open PRs on the engine or substreams-backfills, and issues #66–#72 are all OPEN (VERIFIED `gh`).

**Q10. Does the per-store limit constrain an Aerodrome extractor?** Only if the extractor keeps per-tick, per-position or per-slot Stores. The limit is 3.5 GiB now (§1 C8). A pool-set Store (about 1.5k pools) and a minted-tick Store (about 10⁶) are small. A storage-slot "last value" Store for NPM positions (about 10⁷ × 5 slots) must be sharded.

### Partially answered

- **Throughput of Option A on Aerodrome.** V4 measured 2,268–2,596 blocks/s for the reducer alone on low-density data and 12.7–22 blocks/s end to end on heavier ranges (DOC `ENG/docs/benchmark-100k.md:59-61`, `ENG/docs/direct-postgres.md:684-685`). Aerodrome writes about 150 rows per block. ESTIMATE: 10–50 blocks/s end to end, so 18.1M blocks take about 4–21 days.
- **Noop duration.** Token API Base noops ran at 140–1,160 blocks/s per chunk with 10 workers (REPORT-VERIFIED). Aerodrome's extractor with about 0.7–1B `eth_call`s is RPC-bound. At 1–5k calls/s that is about 2–12 days (ESTIMATE). Storage derivation would remove most of the RPC load.
- **Effort calibration.** The V4 engine repo was created 2026-08-03 and shipped its production-runtime release v0.5.0 on 2026-08-18; the V4 Substreams repo was created 2026-08-02 (VERIFIED `gh api`). Aerodrome's semantic surface is about 2–3× larger (templates and waves, 10 call kinds, decompile-only spec). ESTIMATE: **5–8 weeks** to a differentially certified candidate at similar intensity.

### Open (needs access or measurement)

| ID | Question | Who/what can answer |
|---|---|---|
| O1 | Registry and copy state of `sgd5311` (complete? why failed?) | read-only SQL on Kan primary, or `graphman copy status` (exec was blocked for the survey) |
| O2 | Do `backfill-credentials` and `ghcr-cred` exist in `subgraphs-backfill`? Is the token valid on the kan or riv tier1? | operator with Secret read |
| O3 | Egress from Kan pods to 172.20.114.2:443 or 172.19.114.2:443 | 1-block noop smoke workflow |
| O4 | Is `sgd2` history-pruned (`history_blocks`)? This is needed for time-travel oracle queries | read-only SQL |
| O5 | Slipstream `CLPool` and NPM storage layouts (slots and packing, including `stakedLiquidityNet`) | can start now from the public source plus storage-change fixtures |
| O6 | Mapping-host throughput after #147 at Aerodrome density; Fast PoI and `nonFatalErrors` on real data; Base deposit-tx conversion | run the bundle on Base windows |
| O7 | Archive-RPC capacity for about 1B `eth_call`s at the block hash (EIP-1898) from 13.8M | RPC owners / small benchmark |
| O8 | Exact active-row counts per table at a seed block | read-only SQL |
| O9 | Which tick spacings were ever enabled (`TickSpacingEnabled`) | Firehose or Substreams scan; drives feeTier buckets and the walk grid |

---

## 4. Architecture options for Aerodrome

### Option A: Substreams extractor plus a native Aerodrome reducer emitting `BlockChanges` (recommended for production)

**Shape**

- **Substreams** (new package): `map_pools_created`, then `store_pools`, then `map_events`.
  - `map_events` emits a pinned-params, wave-ordered trigger stream with raw call answers.
  - Options: Stores for derived storage slots; the RpcBatch eth_call path for ERC20 metadata.
- **Reducer**: a Rust port of the decompiled handlers (Factory, NPM, Pool, pricing) that reproduces the quirks below. It keeps only mutable, re-readable state and treats write-once types as block-local (V4 precedent).
  - **Quirks to reproduce:**
    - the feeTier table and the wrong-spacing walk;
    - `Tick.feeGrowthOutside0X128 := stakedLiquidityNet`;
    - the lost whitelist push and `version=2`;
    - read-after-save views;
    - `gasUsed := gasLimit`;
    - `TokenDayData.untrackedVolumeUSD += tracked`;
    - `PoolDayData.close` never updated.
- **Output**: one canonical `BlockChanges` per block. This reuses `backfill-common` validation, the Fast PoI fold (`ENG/src/poi_events.rs:147`), and the profile-driven writer (`ENG/src/sink.rs:1812,2135`, which takes `EntityChange` plus block-local originals and does not need `GenericState`). `data_sources$` rows are emitted for successful `PoolCreated`.
- **Placement** (design decision, see §6 decision D3):
  - *A-engine*: an `adapters/aerodrome-slipstream-base/` input mode inside the engine. Faster to production, because it reuses the parameterized V4 seed capture, pipelined driver, loader and k8s DAG.
  - *A-producer*: a native producer crate that emits BCF1 frames into the engine's generic path. The engine stays family-neutral, but the generic path needs its own scale work: bounded state, a Graph-Node-to-checkpoint seed, a `data_sources$` stream companion beyond 10k-block chunks, and a generalized loader.

**Evidence**

- *Effort (ESTIMATE)*: Substreams about 1–1.5k Rust lines (V4 `map_events` is 856). Reducer about 3–5k lines. Engine family plumbing about 1–3k. Calendar 5–8 weeks to a certified candidate (§3).
- *Throughput*: extraction is parallel and cached by the noop. The reducer is native. ESTIMATE 10–50 blocks/s end to end, so about 4–21 days for 18.1M blocks (seeded) or 9–45 days for 39M (root).
- *Faithfulness and PoI risk*: **high**. This is a hand port of a 302-field mapping whose source is unpublished; the decompile is the specification. Mitigations:
  - (a) frame-for-frame comparison of `BlockChanges` against the mapping-host on root windows (both emit the same contract);
  - (b) time-travel differential against `sgd2` for 13.8M–34.7M: capture a seed at block B−1 with `block_range @> B−1`, replay [B, B+N], and diff non-VID rows (needs O4 and SQL access);
  - (c) Gate A/B, lifecycle and GraphQL as V4 did.
  - The V3 lane abandoned hand-porting because of drift (backfills #116). The difference here is that a full oracle exists for 60% of the range.
- *Reuse*:
  - V4 `build.rs`, `config.rs`, `extract.rs` and `metadata.rs` patterns;
  - engine `decimal.rs` and `math.rs`;
  - `backfill-common`, physical profile and writer, PoI, `poi_events`;
  - substreams-abis V3 Pool event decoders (same topic0);
  - V3 storage-slot helpers (re-slotted);
  - `crates/uniswap-v3-reducers` NPM, Flash and Transaction logic (partial).
- *Blockers*:
  - O5 or O7 (call-answer source);
  - engine family plumbing;
  - landing store;
  - no `production_selectable` profile (needs a live-catalog capture of the landing schema).

### Option B: deployed WASM in the mapping-host, with Substreams as cassette and trigger pre-extractor

**Shape**

- The mapping-host runs the three deployed WASMs over Firehose and emits `BlockChanges`.
- A Substreams module pre-records the `eth_call` cassette (`(block_hash, address, calldata) → Null | Value`, `SB/mapping-host/src/calls.rs:67-115`) and optionally slims blocks.
- The noop warms that cassette module.

**Evidence**

- *Effort*: no semantic port; the bundle and descriptor are cheap (`v3-lane-state.md` §3.4). However, the state layer needs a redesign before Aerodrome:
  - in-memory `BTreeMap` store (`SB/mapping-host/src/store.rs:56-68`);
  - full-JSON checkpoints of about 0.6 TB;
  - a whole-file JSON cassette of about 0.5 TB;
  - O(logs × 1,501 hosts) matching;
  - engine `GenericState` and checkpoint (#70);
  - the v2 data-source chunk loader at about 3,900 chunks;
  - generalized loaders.
- *Throughput*: about 3.5–5.8 blocks/s ceiling, realistically 2–4, single-threaded and not range-parallel (§1 C9). A full replay from root takes about 110–200 days. A seeded run would also need a Postgres-to-host seeder that does not exist.
- *Faithfulness*: highest. It is the deployed bytes. Unexercised so far: Fast PoI, `nonFatalErrors`, Base blocks.
- *Verdict*: **not faster than native Graph Node** for Aerodrome. Keep it as the oracle and as the generic route for low-density subgraphs.

### Option C: native acceleration (baseline, runs in parallel)

**Shape**

- Run `QmasYjyp` on a dedicated fast-tier worker, backed by a dedicated store on fast NVMe.
- Today it runs on the shared `graph-node-chain-base-0`: dom152, Zen 2, about 127–141 assignments, 2 CPU requested and 6 CPU limit (REPORT-VERIFIED `k8s-backfill-stack.md` §3.4).

**Evidence**

- Graph Node block time splits as 35% WASM, 27% `store_get`, 15% `eth_call` and 3% transact (REPORT-VERIFIED `v3-lane-state.md` §4.2).
- The WASM-only ceiling is about 3.5–5.8 blocks/s. A realistic gain is maybe 1.3–2×, to about 2.5–3 blocks/s gross, giving an ETA of about 85–105 days, and worse as density rises (ESTIMATE).
- No semantic risk.
- The copy `sgd5311` (30.84M) already sits on the dedicated store and worker, but it is on dom157, where the volume cannot grow, and its status is failed.
- *Verdict*: worth doing anyway. It is also the continuation that takes over after an Option A cutover. It needs placement and capacity approval.

### Rejected

- **A Substreams-powered subgraph (new deployment hash).** It cannot serve `QmasYjyp` queries or allocations (`v3-lane-state.md` §5.1).
- **Deployed WASM inside a Substreams module.** Not viable: stateless maps, write-only Stores, WASM-in-WASM (`v3-lane-state.md` §5.1).
- **A parallel Substreams emitting `BlockChanges` directly.** It cannot compute the recurrent state (§1 C10).

### Comparison

| | A (extractor + native reducer) | B (mapping-host) | C (native acceleration) |
|---|---|---|---|
| Time to first useful output | 5–8 weeks engineering (ESTIMATE) | 3–6 weeks of state redesign (ESTIMATE) | days (GitOps plus a Graphman copy) |
| Run time for remaining 18.1M blocks | about 4–21 days (ESTIMATE) | ≥ 50–100 days, plus a seeder | about 85–105 days, then the tail |
| PoI/parity risk | high, mitigated by two oracles | lowest | none |
| Generic value for "any subgraph" | reusable extractor recipe, `BlockChanges` reducer pattern, generic writer | reusable for low-density subgraphs | ops-only |
| Uses Substreams | yes (core) | yes (cassette accelerator) | no |

---

## 5. Recommended phased plan with deliverables

### Phase 0: now (no user decision needed; reversible, read-only toward production)

**k8s-subgraphs** (the user authorized pushing noop and backfill workflows):

- **PR-K1, generic noop.** New tree `subgraphs-operations/backfill-substreams/` (or `backfill/generic/`):
  - `base/substreams-noop-workflow-template.yaml` (spec in §6.1);
  - `kan/kustomization.yaml`;
  - `tests/test-contract.sh` with no global-count coupling to V4;
  - `examples/submit-noop.yaml`, outside Flux;
  - `deploy/kan/backfill-substreams.yaml` Flux Kustomization (`dependsOn: subgraphs-backfill`, `prune: true`), listed in `deploy/kan/kustomization.yaml`;
  - CI: `kustomize build` plus `argocli:v4.0.7 lint --offline --strict` plus the contract test in `.github/workflows/ci.yaml`;
  - a headless Service plus `VMServiceScrape` in `subgraphs-metrics/kan/`;
  - `docs/subgraph-substreams-backfill-workflows.md`;
  - the skill `.agents/skills/operate-subgraph-backfill-workflows/SKILL.md`;
  - a `## Skills` entry in `AGENTS.md`.
- **PR-K2, generic backfill template.** A parameterized clone of the V4 production DAG (preflight, approval suspend, prepare-seed, pipelined load with exporter sidecar, verify, evidence). Parameters are in §6.2.
  - Preflight **fails closed** unless the runtime image contains the named adapter and contract. Until engine Phase 2 ships, this template is lint-only.
  - Keep it in the same new tree, never in `backfill/kan` (§1 C6).
- **PR-K3, hygiene:**
  - fix `subgraphs-alerts/base/backfill-flags.yaml:59-61` (`protocol: uniswap-v3` → `aerodrome-slipstream`, and the comment);
  - rescope `.agents/skills/backfill-subgraph/SKILL.md` to the "Uniswap V4 Base production lane" with a pointer to the generic skill;
  - add "Use when" to the three skills that lack it, and list `verify-disposable-v3-root` in `AGENTS.md`.

**pinax-skills:**

- **PR-P1.** New `.agents/skills/develop-subgraph-backfill-substreams/SKILL.md` plus `references/{target-inventory.md,engine-producer-contract.md}` and an optional `agents/openai.yaml`. Index it in `AGENTS.md` (routing row after `:68`, registry rows) and in `README.md` (Subgraphs).
- Add cross-links in:
  - `subgraphs-onboard-deployment` (path 4);
  - `subgraphs-fleet-health` (ETA over 28 days);
  - `backfill-firehose-merged-blocks:76-79`;
  - `architect-k8s-substreams:105`.
- Hygiene:
  - registry "8 repo-local skills" → current count;
  - an exception clause in `README.md:20-22` for the backfill contract.
- Required content corrections are listed in §7. Validate with `python3 scripts/audit-skills.py` and `python3 -m unittest discover -s scripts/tests -v`.
- Single-line descriptions with no `<`, `>` or `: ` (`skills-conventions.md` §1.2).

**substreams-backfills.** Branch and PR, Rust-only, tooling via `cargo xtask`:

- **PR-S1, extractor scaffold** at `aerodrome-slipstream-base/substreams/`:
  - a standalone workspace added to the root `exclude`;
  - V4 toolchain pins (Rust 1.90.0, substreams `=0.7.6`, substreams-ethereum `=0.11.1`, prost `=0.13.5`, CLI v1.20.3 sha256 `90c71d04…`);
  - `build.rs` Abigen from `../reference/abis`;
  - pinned params (network, deployment, factory and start, npm and start);
  - `map_pools_created`, `store_pools`, `map_events` with the wave order key and raw call answers;
  - offline fixture tests: a pool-creation block (wave), a dense block, a Flash block, NPM burn-and-positions-revert in the same block, and a deposit tx;
  - a `ci-aerodrome-slipstream-base.yaml`.
  - Do **not** tag a release yet; module hashes must freeze only after oracle comparison.
  - The alternative home is a new public repo (decision D4).
- **PR-S2, oracle bundle.** `mapping-host/segments/QmasYjyp…` built from `aerodrome-slipstream-base/reference/`, plus Base fixtures (root 13,843,704; first `PoolCreated`; NPM start; a Flash block; a dense recent block). Local runs only. Record per-window blocks/s, memory, Fast PoI and the non-fatal path (answers O6).
- **PR-S3, pin the Slipstream storage layouts** (O5): `CLPool` slots for `feeGrowthGlobal*`, the `ticks` mapping, `Tick.Info` packing; NPM `_positions` and `_poolIdToPoolKey`. Validate against cassette `eth_call` answers on the PR-S2 windows.

**Measurements (read-only):**

- a 1-block, then 100k-block noop smoke of the PR-S1 build against kan and riv endpoints (O3), labelled non-final;
- `TickSpacingEnabled` scan (O9);
- trigger counts per range for sizing.

### Phase 1: after decisions D1–D5 (§8)

- Freeze the extractor once mapping-host frames and the extractor-plus-reducer prototype agree on root windows. Release an immutable SPKG with a tag namespace such as `aerodrome-slipstream-base-substreams-v0.1.0`, pinned by SHA-256 and module hash.
- **Full-range noop**: `[13,843,704, finalized stop)` in one request via the PR-K1 workflow. Record the evidence (SPKG SHA, module hash, range, endpoint) and copy `stop−1` into the backfill's `cache-last-block`.
- Eligibility evidence refresh or explicit override for backfills #86, recorded in `SB/aerodrome-slipstream-base/QmasYjyp….yaml` truth gates (decision D7).

### Phase 2: engine (needs D3)

Deliverables:

- `adapters/aerodrome-slipstream-base/`:
  - `compatibility.json` (SPKG, module, hash, output type, initial block, runtime);
  - the descriptor plus `.sha256`, with `non_fatal`, `fast` PoI and `ethereum/base`;
  - a hermetic physical profile derived from `fixtures/physical-profiles/uniswap-v3-mainnet-hermetic.json`;
  - later, a live-catalog profile captured from the landing schema.
- Reducer (A-engine or A-producer).
- Family-parameterized scripts:
  - contract selection replacing `check-compatibility-contract.sh:7-9`;
  - seed capture with an adapter-provided table split (active vs max-VID-only);
  - `ENDPOINT` default fixed or removed.
- `data_sources$` append for new pools.
- Runtime image release (two-phase pin).
- Gates:
  - frame parity against the mapping-host on root windows;
  - time-travel differential against `sgd2` on sampled windows in 13.8M–34.7M;
  - Gate B physical parity;
  - lifecycle (continuation, restart, rewind, replay).

### Phase 3: infra and run (needs D2, D6 and approvals)

1. **Landing.** `core/kan/aerodrome-backfill-postgres.yaml`:
   - dom153, 8–12 Ti `local-storage`, prune disabled;
   - `[store.aerodrome_b]` in `core/kan/graph-node-config.yaml`;
   - `core/kan/tests/primary-store-baseline.json`;
   - a zero-replica parking worker `graph-node-aerodrome-backfill-0`, **not** in `INDEXER_AGENT_INDEX_NODE_IDS`;
   - roll the serving and status nodes one at a time (#105 invariant).
2. **Copy.** `graphman copy create` of `sgd2` into `aerodrome_b` (S3), then reassign it to the parking node and pause. Seed head about 34.7M+.
3. **Run.** Backfill from the seed to a fixed finalized target via PR-K2 (approval suspend). Then terminal certification, a paused landing, and an approved `graphman copy activate` cutover. Graph Node then continues to the head (Option C worker).

---

## 6. Workflow designs (noop + backfill)

### 6.1 `substreams-noop` (generic WorkflowTemplate, runnable once an SPKG exists)

**Parameters**

| Parameter | Notes |
|---|---|
| `target-id` | label and mutex suffix |
| `deployment` | label; regex `^Qm…{44}$` |
| `network` | |
| `spkg-url` | https only |
| `spkg-sha256` | |
| `expected-module-hash` | optional; checked with `substreams info --json` when the image allows |
| `module` | exact engine-consumed module |
| `start-block` | lowest module `initialBlock`; 13,843,704 for Aerodrome |
| `stop-block` | exclusive, finalized |
| `endpoint` | allowlist `^base\.substreams\.(kan\|riv)-prod-firehose-a\.pinax\.io:443$`; never `kan-sst2` |
| `parallel-workers` | 100–500, capped; coordinate with the tier2 owners |

**Runtime**

- One pod, one production-mode `--noop-mode` request.
- Headers: `X-Substreams-Parallel-Workers` and `X-substreams-acknowledge-non-deterministic: true`.
- `SUBSTREAMS_API_TOKEN` from `backfill-credentials`.
- No PVC: Kan has no RWX storage, and cursor-less retries hit cache.

**Image**

- `ghcr.io/pinax-network/substreams-sink-noop:v1.5.2@sha256:c9936eb7…` (has curl for the in-pod `sha256sum -c`), or
- `ghcr.io/streamingfast/substreams:v1.25.0@sha256:87d14bef…` with a checksum initContainer.
- Both digests are REPORT-VERIFIED (`token-api-noop-pattern.md` §1.4). This is a design choice, not a user decision.

**Reliability**

- Retry policy `Always` with expression `lastRetry.status == 'Error' || asInt(lastRetry.exitCode) == 75` (k8s convention, `K8S/subgraphs-operations/fullsync/base/workflow-template.yaml:133-137`).
- The wrapper maps `stream invalid|deterministic|panic in the wasm|stream auth failure|quota exceeded` to exit 1, so those are not retried.
- `podGC: OnPodSuccess`, which keeps panic logs.
- `activeDeadlineSeconds` 14 d.
- Requests 100m/256Mi, limits 1/1Gi (the measured peak was 123 MiB).

**Observability**

- Argo `metrics.prometheus` gauge plus a task counter.
- A `VMServiceScrape` on `:9102`.
- No webhooks in parameters.

**Concurrency and evidence**

- Mutex per target. Note that Argo v4.0.7 support for templated mutex names is unverified; if lint rejects it, use a fixed name in a per-target wrapper.
- Evidence JSON on stdout. The backfill preflight later asserts `cache-last-block < stop-block` with the same SPKG SHA and endpoint.

### 6.2 `substreams-graph-node-backfill` (generic WorkflowTemplate; runnable only after the engine family ships)

**Parameters.** The first five names are read by the existing exporter, so keep them unchanged:

- `deployment`, `target-schema`, `expected-seed-block`, `target-block`, `runtime-image-digest`;
- plus `target-id`, `network`, `chain-id`, `rpc-url-template`, `substreams-endpoint` (no default), `target-shard`, `target-postgres-host`, `primary-postgres-host`, `parked-node-id`, `writer-deployments`, `expected-registry`, `active-source-shard`, `active-source-schema`, `seed-mode` (`checkpoint`; `empty` reserved), `expected-seed-hash`, `target-hash`, `cache-last-block`, `segment-size`, `adapter`, `spkg`, `module`, `input-mode`, `max-pg-bytes`, `reserve-bytes`, `work-pvc`.

**Wiring**

- Run root `/work/production-<schema>-<seed>`; exporter `RUN_MODE=production`.
- Mutex per target; dom153 node selector; a per-target work PVC.
- The exporter-label PVC guard is parameterized (the V4 version hard-codes the PVC name at `…production-workflow-template.yaml:495-507`).
- Explicit `ENDPOINT`.
- `BACKFILL_PREWARM_SUBSTREAMS=1` kept as a cache-hit check.

**Safety mechanics.** All V4 safety mechanics are kept: writer replicas = 0, registry tuple, capacity rechecked per segment, stale-lock quarantine, no-op resume, sequence audit, evidence JSON.

### 6.3 Vocabulary to fix everywhere

- **Noop warm-up**: Substreams cache build.
- **No-op resume gate**: certification rerun (`direct-load-noop.json`).

The two must never be conflated (`skills-conventions.md` §2.5).

---

## 7. What the generic skill must say (corrections to the survey drafts)

1. **Decision rule for the producer.**
   - Compute the WASM-only ceiling from Graph Node metrics: `deployment_handler_execution_time` minus `deployment_host_fn_execution_time{store_get,ethereum_call}`, per block.
   - If the ceiling is not much higher than Graph Node's current rate, the deployed-WASM route (mapping-host) cannot help. A native family producer is the only accelerating route.
   - Otherwise the mapping-host is the generic, faithful choice.
   - A Substreams module can emit `BlockChanges` directly only for stateless or mergeable-only mappings (§1 C10).
2. The mapping-host is **not** range-parallel (§1 C9).
3. **Template subgraphs need wave ordering** `(wave, block_log_index, host_order)` with creation-block gating. Factories that initialize before emitting creation (Slipstream) put the child's first trigger in wave 1.
4. **Call answers:**
   - emit raw `(address, calldata) → value | revert` at the block hash; do not decode with "sensible" defaults;
   - over-fetching is safe and under-fetching is fatal;
   - send the non-deterministic acknowledgement header;
   - tier2 caches answers forever.
5. **Write-once entity types** (IDs derived from tx, log or block) can be block-local in a family reducer and max-VID-only in a seed. Prove this from ID schemes and `store.get` inventories. The generic engine store does not do this yet.
6. **Noop rules:**
   - production mode;
   - the same SPKG bytes, params and module;
   - one request for packages with Stores;
   - private DC route, never `kan-sst2`;
   - the cache bucket is shared across DCs;
   - the per-store limit is 3.5 GiB on Pinax prod (since 2026-10-02), but still shard.
7. **Re-check engine `main`** for the current blockers (`data_sources$`, removes, immutable resume, `production_selectable`, generic loader scope). Do not hard-code them.
8. Keep target IDs, digests, dates and ETAs out of the pinax-skills skill (portability rules, `skills-conventions.md` §1.4).
9. **Landing capacity**: size the landing store from rows/block × the remaining range at about 1.3–1.5 KB per row, under the 70% fill gate.

---

## 8. Decisions that belong to the user

- **D1. Production route for Aerodrome.**
  - Choices: Option A (recommended), Option B, or Option C alone.
  - Whether to run C in parallel as the baseline.
  - Whether the mapping-host stays as the oracle.
- **D2. Seed strategy.**
  - S3: a fresh `graphman copy` of live `sgd2` (about 34.7M) into a new dom153 `aerodrome_b` (recommended).
  - S2: reuse `aerodrome_a/sgd5311` (30.84M, failed status, dom157 cannot grow).
  - S1: a root replay into an empty same-hash site (needs an unproven empty-copy trick plus 39M blocks).
- **D3. Reducer placement.**
  - A-engine: a family adapter inside `substreams-graph-node-backfill`. Faster, reuses V4 plumbing.
  - A-producer: a native `BlockChanges` producer in `substreams-backfills`, with generic engine scaling. More generic, more engine work.
- **D4. Home of the Aerodrome Substreams source.**
  - `substreams-backfills/aerodrome-slipstream-base/substreams/`: internal repo, so k8s needs a token to fetch assets or the SPKG must be vendored into the image.
  - A new public repo mirroring `substreams-v4-subgraph`.
  - Also the release tag and SPKG naming.
- **D5. Source of call answers.**
  - Archive-RPC `eth_call` in Substreams: about 0.7–1B calls, permanently cached. Needs agreement from the RPC and Substreams capacity owners.
  - Storage-change derivation: needs pinned layouts; near-zero RPC.
  - Or a hybrid.
- **D6. Infrastructure approvals.**
  - The dom153 landing store size (8–12 Ti) and parking worker.
  - Graphman copy and `sgd2` pause for the copy (about 46 s last time).
  - The fate of `aerodrome_a`/`sgd5311` and `graph-node-aerodrome-0` (repair, reuse as Option C, or retire).
  - tier2 worker budget for a 39M-block noop on the shared Base tier2 (riv also depends on Kan tier2).
  - The endpoint choice.
- **D7. Governance.** Refresh the backfills #86 two-cluster eligibility evidence (riv has no series, so structural absence proof is needed), or explicitly override the truth gates for this user-directed effort.
- **D8. Read-only SQL access** to Kan primary and `postgres-2` for:
  - `sgd5311` status (O1);
  - pruning (O4);
  - active-row counts (O8);
  - the live-catalog profile capture;
  - time-travel oracle queries.
- **D9. Skill names and scope.** pinax-skills `develop-subgraph-backfill-substreams`; k8s-subgraphs `operate-subgraph-backfill-workflows`; rescope (not fold) `backfill-subgraph`; whether to include the read-only ETA helper script in pinax-skills.
- **D10. PR footer conflict.** Repo skills want `🤖 Created by Claude (<model> <effort>)`; the harness wants the "Generated with Claude Code" footer. Choose per repository.

---

## 9. Top risks

1. **Semantic drift in the reducer port**, given a decompile-only specification and 302 fields of quirks. Mitigation: the two oracles (§4 A) before any long run.
2. **Wave ordering and creation gating** silently drop or misorder each pool's `Initialize` if done naively (§1 C1).
3. **Module-hash churn** discards the noop cache. Freeze the extractor bytes, built in CI, only after oracle agreement.
4. **RPC and tier2 load** for the noop with about 1B `eth_call`s, shared with Token API and riv.
5. **Capacity**: about 5–8 TB at head (ESTIMATE). dom157 is excluded; dom153 CPU was tight in September (#929).
6. **The engine has been idle since 2026-09-07.** Docs are stale in places (`ENG/README.md:845-855`, the `generic_state.rs:38-40` comment, `AGENTS.md` mission). Trust code over docs.
7. **Infrastructure assumptions**: the dead `kan-sst2` default endpoint, unverified Secrets, untested egress (O2, O3).
8. **Native Graph Node keeps slowing** as density rises. Every timeline comparison must use a rate-versus-density model, not one ETA.

---

## 10. Appendix: live numbers and verification commands (this pass)

All queries ran against VictoriaMetrics `P4169E866C3094E38` on 2026-10-20.

| Query | Result |
|---|---|
| `max by (pod,shard)(deployment_head{deployment="QmasYjyp…"})` | `graph-node-chain-base-0-77c65b59d4-kc8dv` / `subgraphshard_b` = 34,728,090 |
| `max by (pod)(deployment_status{deployment="QmasYjyp…"})` | `graph-node-chain-base-0…` = 2 (running); `graph-node-aerodrome-0-84c4495f8d-pbqbk` = 4 (failed) |
| `max(ethereum_chain_head_number{network="base"})` | 52,868,270 |
| `max(delta(deployment_head{…}[6h]))/21600` | 1.14 blocks/s |
| `sum by (job,schemaname,cluster)(pg_stat_user_tables_n_live_tup{schemaname=~"sgd2\|sgd5311"})` | `sgd2` (kan, shard-b) 1,314,019,692; `sgd5311` (kan, aerodrome) 810,019,888; `sgd5311` (riv, unrelated) 88.8M |
| `sgd2` 2-day-max series | 744M (09-21) → 800M (09-27) → 1,066.7M (10-05) → 1,308.5M (10-17) |

Other read-only checks:

- `gh api repos/aerodrome-finance/slipstream/contents/contracts/core/CLFactory.sol?ref=ce33300ac4` and `…/CLPool.sol` (ordering).
- `dig +short` for the four endpoints.
- `git show origin/main:` in `KSS` for the tier1 flags; `git grep` for `ETH_CALL_*` (none).
- `gh issue view` for engine #66–#72 and backfills #86/#88/#91/#114/#117/#118 (all OPEN); `gh pr list` (none open).
- `gh api` repo `created_at` values for effort calibration.

Scratch helper: `/private/tmp/claude-501/-Users-denis-Github-substreams-backfills/6974ca53-b59e-4778-97ac-3643f910b626/scratchpad/synth-tools/logorder.py`. It is a Firehose JSON log-order dumper. Block 13,843,704 holds the factory *deployment*, not a `PoolCreated`, so a real pool-creation fixture is still needed.

The source reports are all in `/private/tmp/claude-501/-Users-denis-Github-substreams-backfills/6974ca53-b59e-4778-97ac-3643f910b626/scratchpad/survey/`:

- `engine-contract.md`
- `v4-substreams-pattern.md`
- `aerodrome-target.md`
- `v3-lane-state.md`
- `k8s-backfill-stack.md`
- `token-api-noop-pattern.md`
- `substreams-reuse.md`
- `skills-conventions.md`
