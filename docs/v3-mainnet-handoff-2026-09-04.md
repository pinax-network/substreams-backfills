# Uniswap V3 mainnet handoff — 2026-09-04

This snapshot hands the Uniswap V3 mainnet lane to the next agent. It follows
[the BlockChanges v1 handoff of 2026-09-02](blockchanges-v1-handoff-2026-09-02.md),
whose authority boundaries still apply except where this document supersedes
them. [Issue #118](https://github.com/pinax-network/substreams-backfills/issues/118)
remains the live sequencing authority.

The producer and the consumer now both exist and agree. What blocks a real
backfill is no longer code.

## Authority boundaries

- Repository-only work does not authorize Kubernetes, production database,
  allocation, activation, or load actions. The engine repository's `AGENTS.md`
  is authoritative for database and release safety.
- Read-only Firehose and archive-RPC access is in scope and was used: replays
  stream blocks and record `eth_call` results. Nothing else reaches a network.
- The strict eligibility recapture window opened `2026-09-03T16:14Z`, but the
  recapture itself is still **not runnable from a repository session**: neither
  V3 deployment reports a `deployment_head` series in either cluster, so the
  gate needs structural absence proof from the status API plus a read-only
  `deployment_schemas` inventory. Both bindings still read
  `decision: indeterminate`, and neither V3 binding has a `truth_gates` block.
- Do not resume worktree `substreams-backfills-v3-pool-mint-v1`
  (`codex/uniswap-v3-pool-mint-v1`); it remains a rejected precursor.
- `uniswap-v3/source`, `uniswap-v4/`, and every digest-pinned file under
  `uniswap-v3/` and `scripts/` stay untouched. `docs/uniswap-v3-execution-model.md`
  and `uniswap-v3/README.md` arrived with PR #121, now merged, and were left
  unedited here. The throughput measurement below prices what the execution
  model deliberately declined to price; amending that document is a separate
  decision, not a correction to make in passing.

## Delivery snapshot

Engine, `pinax-network/substreams-graph-node-backfill`, all merged with green
canonical main CI:

| Slice | Canonical commit | What it is |
|---|---|---|
| PR #74, issue #66 — framed input mode | `42922c3` | `--input-format block-changes-v1-framed`, generic entity state, `EntityBody::{V4, Generic}` at the `Vec<EntityChange>` seam; V4 byte-identical |
| PR #75, issue #67 — proof of indexing | `a05126a` | Full `GraphValue` union, Remove and DeterministicError, 33 reference digests generated from graph-node itself |
| PR #76, issue #69 — physical profile grammar | `fac7618` | Grammar admits the real v0.44 `data_sources$`; V3 mainnet profile fixture, 22 tables, 286 columns |
| PR #77, issue #68 — profile-driven writers | `560c0ec` | COPY and Parquet from the profile; numeric/bytea/timestamp encoders |
| PR #78 — end-to-end handoff proof | `86958e1` | Replays a real 300-block `BCF1` stream through the CLI |
| PR #79 — framed spool | `9a6d84d` | `GenericCheckpoint` (`BCGCKPT1`) and a sealed COPY spool from framed input |

Backfills, `pinax-network/substreams-backfills`, all merged with green canonical
main CI:

| Slice | Canonical commit | What it is |
|---|---|---|
| PR #129 — workspace crates | `df69444` | The eight overlay reducers compile and test in the workspace, 137 overlay tests |
| PR #130 — merge algebra | `a339e14` | `EntityCache` merge semantics exported for consumers |
| PR #131 — fixture re-cut | `29568c7` | `block-fixtures-v2`; every v1 `.pb` held two concatenated blocks |
| PR #132 — mapping host | `d2c6821` | Executes each segment's **deployed mapping WASM** under Graph Node v0.44 crates |
| PR #133 — per-save stream | `5f88698` | Vendored `graph-runtime-wasm` + 119-line recorder patch; canonical BlockChanges frames |
| PR #134 — live source | `aa28cb2` | Contiguous Firehose ranges, no new dependency |
| PR #135 — parity evidence | `4be4e0d` | The 1,053-block window committed as verifiable evidence |
| PR #136 — store dump | `fdaac04` | `--store-out`, the comparison target for the engine |
| PR #137 — Rust materializer | `255e776` | `cargo xtask materialize-uniswap-v3`; no workflow calls a shell materializer |
| PR #138 — checkpoint/resume | `ffbb7b4` | `--checkpoint-out` / `--checkpoint-in`, chunked equals uninterrupted |
| PR #139 — long-run resilience | `e7f1dd4` | `--checkpoint-every`, `--continue-outputs`, stream reconnection |
| PR #140 — cassette row pin | `699bac0` | A recording run can resume; checkpoint `v2` |

## What is proven, and what is not

Proven, by execution rather than assertion:

- **Producer and consumer agree independently.** A 300-block `BCF1` stream from
  the host, replayed through the engine's real CLI, reproduces 142 entities byte
  for byte and Graph Node's own `ethereum/mainnet` proof-of-indexing digest.
- **1,053 contiguous blocks replay cleanly**: 167 handler groups, 1,362
  operations, 50 proof-of-indexing blocks, zero deterministic errors. Evidence at
  `mapping-host/evidence/parity-window-12369621-12370674.json`.
- **A loadable spool exists**: 948 inserted and 514 clamp rows across 18 tables
  with real `block_range` versions, sealed from the parity window.
- **Resume is faithful**: chunked replay equals an uninterrupted one byte for
  byte, on both sides, with negative controls proving the tests bite.

Not proven, and must not be claimed:

- No parity against the deployed subgraph. Every comparison so far is host
  against engine, or host against its own earlier run.
- No readiness, eligibility, or promotion gate has moved. All remain false.
- `handleFlash` has never executed. `dataSource.context` is implemented but
  unexercised. Segments 2 through 8 have bundles and descriptors but no run.
- Engine issue #68's V4 byte-equality is proven on a hermetic replay, **not** the certified
  100k range; that box is deliberately unchecked on the issue.

## The three blockers, none of which is code

1. **The `data_sources$` contract gap** ([#117](https://github.com/pinax-network/substreams-backfills/issues/117)).
   BlockChanges v1 carries no data-source-creation event, so a replay cannot
   reproduce that table, and Uniswap V3 writes one row per `PoolCreated`. The
   spool refuses by default and only seals with `--allow-omitted-data-sources`,
   which marks the manifest `completeness.faithful: false` and writes
   `INCOMPLETE.json`. Three options are on the issue: add a `CreateDataSource`
   operation to the contract, deliver the table out of band per segment, or
   require a graft base that already holds the rows, which cannot work for the
   graft-free root. **This is an interface decision, not an implementation task.**
2. **No live catalog capture.** The V3 physical profile is a hermetic fixture
   with `production_selectable: false`. Making it selectable needs a disposable
   scratch schema deployed from the same manifest, to capture the physical
   namespace, `deployment_schemas.version`, sequence positions, index names as
   the server records them, `access_method`, `replica_identity`, and whether the
   server offers `int4_minmax_multi_ops`.
3. **Credentials and a database** for [#114](https://github.com/pinax-network/substreams-backfills/issues/114)
   (an authoritative oracle endpoint; the gateway answers but does not pre-pin
   the serving indexer) and [#10](https://github.com/pinax-network/substreams-backfills/issues/10)
   (a scratch Postgres and a paused Graph Node to land into).

## How to scope the next piece of work

Ask three questions in order. They are cheap and they have repeatedly changed
what was worth doing.

1. **Is it blocked on a decision or on infrastructure?** If yes, do not start it.
   Write the options down on the issue with their consequences and move on. Three
   items above are in this state and no amount of code advances them.
2. **What does it cost to run, measured rather than estimated?** This lane's
   biggest finding came from measuring a replay instead of assuming it. Throughput
   falls as activity grows, so any "replay from the root" task must be priced at
   the block height it actually reaches, not at the rate of the first thousand
   blocks.
3. **Will the result be evidence or an assertion?** Prefer work whose output is
   a digest, a byte comparison, or a refusal that fires. Every finding worth
   keeping in this lane came from executing the deployed artifact and comparing,
   never from reading it.

A useful pattern to repeat: when a capability lands, **use it for its real
purpose immediately**. Doing that found the concatenated-block fixtures, the
serde tagging that silently emptied every state dump, and the cassette pin that
made recording runs unresumable. None of the three had a failing test.

## Ordered continuation

1. **Put the `data_sources$` decision to the owner** and implement whichever
   option comes back. Until then, no V3 spool can be faithful, so #10 and #11
   cannot start. This is the only item on the critical path.
2. **Reduce replay cost before attempting any long run.** The measured curve is
   in the next section. The largest lever is recording the `eth_call` cassette
   ahead of time and in parallel: replay against a warm cassette runs about five
   times faster than recording, and recording is serial only because it is
   interleaved. A cassette pre-recorded by block range would turn a months-long
   ancestry replay into a parallel job plus a fast serial pass.
3. **Capture a live catalog** once a disposable scratch schema exists, then make
   the V3 profile production-selectable and re-run the spool as a faithful one.
4. **Then, and only then**, #10's scratch-schema load, #9's logical parity, and
   #114's differential oracle, in that order; #11 and #13 are the paused-landing
   issues behind them.
5. **Opportunistic, unblocked, low value per hour**: exercise `handleFlash` by
   resuming a replay to block 12,764,397; record cassettes for segments 2 through
   8; extend #111 by retiring the `scripts/` unittests that still shell out to the
   materializers, which needs editing pinned files and so needs its own decision.

## Facts that must survive

- **Replay throughput falls with block height.** Measured on segment 1: 10.9
  blocks/s over a cassette-cached span, 5.5 blocks/s on first live blocks, 1.9
  blocks/s about 7,000 blocks in and still falling. Handler density rose from
  0.04 to 1.83 handler groups per block between 12,372,621 and 12,376,621 as
  pools accumulated. Consequences at 1.9 and 5 blocks/s: first `Flash` 58 h or
  22 h; full segment 1 158 h or 60 h; **full mainnet ancestry 1,971 h or 749 h**.
  Base adds 49.2M blocks. `docs/uniswap-v3-execution-model.md` priced ancestry
  replay in blocks and explicitly refused a duration; the duration is now
  measured, and it is months.
- **The first `Flash` on mainnet is block 12,764,397**, on pool
  `0x1d42064fc4beb5f8aaf85f4617ae8b3b5b8bd801`, the first pool ever created.
  Established by an exhaustive `eth_getLogs` scan of topic0
  `0xbdbdb71d7860376ba52b25a5028beea23581364a40522f6bcfb86bb1f2dca633` in
  1,000-block ranges over 12,369,621 → 12,764,620, with every rate-limited chunk
  re-queried until it resolved.
- **The Collect quirk is per segment.** Segment 1 wrote
  `collectedFeesToken0 = 4.737020364940845353` and
  `collectedFeesToken1 = 0.000457721123056046` — different values, so token0
  receives amount0 and token1 receives amount1. The "amount0 added to both"
  behaviour belongs to segments 6, 7 and 8. #37 states it as a blanket fact and
  should be qualified.
- **#111's criterion 2 is unreachable as written.** `cargo build -p
  uniswap-v3-runtime --target wasm32-unknown-unknown --release` cannot produce
  the pinned digest: the crate name appears in the mangled symbols the WASM name
  section retains, so renaming the package changes the digest. The intent is met
  by the Rust materializer; the wording needs correcting.
- **The runtime WASM digest is machine-scoped.** The release profile embeds
  absolute `$HOME/.cargo/registry` paths in 68 panic locations, so it differs
  across home directories while staying invariant under the build directory. No
  expectation can be checked in.
- **Both V3 targets are missing from cluster metrics.** Neither reports
  `deployment_head`, `deployment_synced`, or `deployment_status` in either
  cluster, so eligibility needs structural absence proof rather than a query.

## Operational notes that cost time to learn

- The root workspace fails 18 `targets::uniswap_v3_matic` tests on a fresh
  worktree until `cargo xtask evidence fetch` hydrates the externalized
  contracts. It is not a regression.
- Each file under `mapping-host/tests/` becomes its own ~140 MB binary; six of
  them made the CI linker die with a bus error. New suites go in the
  `tests/mapping_host/` module tree. `[profile.dev]`/`[profile.test]` carry
  `debug = 0` and `strip = "debuginfo"`.
- `eth.rpc.pinax.network` caps `eth_getLogs` at about 1,000 blocks and rate
  limits hard; the recorder paces with `ETHEREUM_RPC_MIN_INTERVAL_MS` and retries
  429 and 5xx with backoff. A 429 is retried, never treated as a revert.
- The Firehose stream drops on long replays. Reconnection is inside the
  contiguity checker, so a reconnect that skipped, repeated or forked is refused;
  parent-hash linkage catches a fork at the same height.
- Write `gh issue comment` bodies to a file. Backticks in a shell heredoc get
  command-substituted and silently delete words.
- The mapping host needs `cargo +1.98.0`; graph-node's own 1.94.0 pin is only
  valid with graph-node's lockfile. `graphql-tools` must be held at 0.5.1.

## Retained artifacts

In-repository and durable: `mapping-host/segments/` (all eight deployment
bundles, digest-locked), `mapping-host/fixtures/` (cassette, goldens, frames,
BCF1 stream), `mapping-host/evidence/parity-window-12369621-12370674.json` with
its per-block digests, and the engine's `fixtures/mapping-host-v3-stream/` and
`fixtures/poi-graph-value/`.

**Session-local and lost when the session ends**: the partial Flash replay
(`scratchpad/flash-run3/`, a `checkpoint/v2` at boundary 12,375,620 with a 2 MB
cassette) and the demonstration spool. Restarting the Flash replay from the root
costs about an hour of the total; nothing important dies with them.

## Restart checklist

- Read #118, then #117, #116, #37, #38, #10, and this document.
- `git fetch` both repositories and check open PRs and worktrees before choosing
  a branch. Both mains were clean at handoff with no open PRs.
- Run `cargo xtask evidence fetch` before trusting a workspace test run.
- One PR at a time per repository. Merge only at a green exact head with
  `--match-head-commit`, never `--auto`, then verify canonical main CI and post
  the run IDs on the issue.
- Read every workflow's conclusion before claiming CI is green. A `Container`
  failure was once reported as success in this lane and had to be corrected.
- When a capability lands, use it for its real purpose before declaring it done.
