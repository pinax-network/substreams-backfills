# BlockChanges v1 handoff — 2026-09-02

This snapshot hands the BlockChanges v1 and executable-evidence program to the
next agent. [Issue #118](https://github.com/pinax-network/substreams-backfills/issues/118)
is the live sequencing authority; this document retains the technical state and
the evidence boundaries learned while delivering the first engine slices.

## Authority boundaries

- Repository-only work does not authorize Kubernetes, production database,
  allocation, activation, compute, or load actions.
- Recheck the strict two-cluster eligibility contract immediately before
  implementation and again before compute or load. Independently select the
  minimum stable same-pod 24-hour ETA and 72-hour ETA across every viable copy;
  both minima must exceed 28 days or be non-converging.
- Do not run a strict live recapture before approximately
  `2026-09-03T16:14Z`; the Kan pods observed on 2026-08-31 had not yet supplied
  an admissible 72-hour same-pod window.
- The engine repository's `AGENTS.md` is authoritative for database and release
  safety. The reusable release gate is summarized in
  [the repository skill](../.agents/skills/certify-backfill-successor/SKILL.md).

## Delivery snapshot

| Slice | State at handoff | Authority |
|---|---|---|
| Canonical family-neutral BlockChanges v1 contract | Merged as backfills PR [#107](https://github.com/pinax-network/substreams-backfills/pull/107), canonical commit `a94f3c84f3c152bf281e626461311b9311ed6cf6` | Contract and validator only; no runtime or parity claim |
| Dated handoff and reusable release skill | Merged as backfills PR [#119](https://github.com/pinax-network/substreams-backfills/pull/119), canonical commit `5755fc2cc15d1cb30c3b478d067eee6b26237bac` | Candidate [run 33597126707](https://github.com/pinax-network/substreams-backfills/actions/runs/33597126707) and canonical [run 33597296279](https://github.com/pinax-network/substreams-backfills/actions/runs/33597296279) passed 7/7 jobs and 193/193 steps at the same tree |
| V4 shadow adapter | Merged as engine PR [#62](https://github.com/pinax-network/substreams-graph-node-backfill/pull/62), canonical commit `2e0c95b93d2760ef05b9aa4a319e45dceb7e5f87` | Default-off adapter; not a family-neutral input mode |
| Clock-v1 native framing | Merged as engine PR [#64](https://github.com/pinax-network/substreams-graph-node-backfill/pull/64), canonical commit `b1432f866e4ce8f819c84c81ade485e3e24fc647` | Canonical CI, Container publication, runtime digest, referrer, and retained archive independently verified |
| Deterministic-error inventory | Merged as engine PR [#65](https://github.com/pinax-network/substreams-graph-node-backfill/pull/65), canonical commit `5799d638cbc35a40f0498109e28a0b3e1e311fdb` | Candidate [run 33596247637](https://github.com/pinax-network/substreams-graph-node-backfill/actions/runs/33596247637) passed 27/27 steps; candidate and canonical trees match at `d53239dca027f057ea50f0e09cda41c20fe69cc2`; canonical [CI 33597292072](https://github.com/pinax-network/substreams-graph-node-backfill/actions/runs/33597292072) and [Container 33597292102](https://github.com/pinax-network/substreams-graph-node-backfill/actions/runs/33597292102) passed |
| Physical-profile Phase A | Preserved on remote branch `codex/physical-profile-phase-a-v1` at `2b65c69be96d4d53738efdd9349a4442e326ef7a`; not merge-ready | Rebuild from canonical #65 rather than rebasing the descriptor generations; issue [#5](https://github.com/pinax-network/substreams-backfills/issues/5) records the source-built-fixture and independent-registry requirements |
| V4 q8 reproduction | Still open under [#26](https://github.com/pinax-network/substreams-backfills/issues/26) | Retained historical q8 evidence is not a fresh authorized reproduction; k8s PR [#836](https://github.com/pinax-network/k8s-subgraphs/pull/836) remains draft and behind |

The first PR #65 candidate failed only after its real Linux certification image
had passed the source, collector, permission, and semantic suites. The final
filesystem comparison correctly detected that the evidence-only overlay had
copied a newer `load-postgres-spool.sh` over the frozen reviewed wrapper. The
repaired candidate inherits both frozen execution wrappers and adds regression
coverage that refuses future source copies in the certification stage.

Canonical Container run
[33597292102](https://github.com/pinax-network/substreams-graph-node-backfill/actions/runs/33597292102)
published and independently verified the exact merge revision:

- Clock tag
  `ghcr.io/pinax-network/substreams-graph-node-backfill:block-changes-clock-v1-sha-5799d638cbc35a40f0498109e28a0b3e1e311fdb`,
  subject `sha256:f88d426ee9c78bba694feeddc3c80d6fc93fc71f055b47881623a968665a7c27`,
  evidence attachment `sha256:e966e3a11db17ae7155b11ad80129599035f9c1818408f7f5711c6c0af00a9e8`,
  archive `sha256:62cb9d24c313e3485979affe52256375c9001b7f8afb0ba8b12f39eb6a2e9869`,
  and runtime JSON `sha256:0bd1ec5b989d349e7535198a8d0489a699d15a446dc55bc115a0e1543edcb9c3`;
- certification tag
  `ghcr.io/pinax-network/substreams-graph-node-backfill:production-certification-sha-5799d638cbc35a40f0498109e28a0b3e1e311fdb`,
  subject `sha256:b59685f7812b7a06b9b6ea6f386c44ea3fef3bfffa7ea920c6f5721bf12aaa65`,
  identity referrer `sha256:73dc9170f884921e206b8ab7d0497793e4547b13d53ddcf908957a2f5145e196`,
  and V4 build referrer `sha256:5c2c427ccd80e2d9fffb2caa0ea4bdc0e7e99b1f29e1a4249fc6482db3f43cbf`.

Both live referrer payloads matched the retained Actions artifacts byte for
byte, all 27 runtime file hashes passed, and the frozen loader remained
`997e3f03b3756a13b74c0262eace7a3e53fdcc38bfe4e82a38bbe4150b564581`.
The hosted CI script reports its real-PostgreSQL predicate as skipped when
`initdb` is unavailable; do not mislabel that as hosted PostgreSQL coverage.
The exact candidate's same predicate passed locally on 2026-09-02.

Do not use `gh pr merge --auto` as a waiting mechanism in these repositories
without first proving that branch protection requires the intended checks. On
2026-09-02 it merged #65 and handoff-doc PR #119 immediately while their checks
were still running. The reviewed heads and canonical trees matched, but the
merges had to be treated as provisional until both candidate and canonical
workflows finished. Wait for terminal exact-head success first, then issue the
exact-head-guarded merge command.

One dirty local worktree is intentionally not a deliverable:
`substreams-backfills-v3-pool-mint-v1`, branch
`codex/uniswap-v3-pool-mint-v1` at `208447e339dd40787e55ba33f5f57189a6766b28`.
It is a rejected precursor superseded by canonical PRs
[#68](https://github.com/pinax-network/substreams-backfills/pull/68) and
[#81](https://github.com/pinax-network/substreams-backfills/pull/81). It pins
obsolete Pool Burn identities, lacks the canonical runtime-capsule checks, and
overstates field completeness despite unresolved aliases and dynamic writes.
Do not commit, push, resume, or cherry-pick it. Preserve it until cleanup is
explicitly authorized.

## Ordered continuation

1. Start Phase A from canonical engine commit
   `5799d638cbc35a40f0498109e28a0b3e1e311fdb`; squash-merge the existing
   profile work rather than resolving three descriptor generations one by one.
   Use the inventory descriptor as the base, add only the physical-profile
   pins, preserve Clock and inventory fields, and reseal once.
2. Copy `fixtures/physical-profiles/` into every source-built OCI builder that
   compiles Rust using `include_bytes!`. A host build does not prove the release
   build context is complete.
3. In the profile docs and evidence, keep shard identity
   (`subgraphs.deployment` plus `subgraphs.head`) separate from independently
   captured primary-registry placement. Shard-local `deployment_schemas` is not
   primary-registry evidence.
4. Criterion 4 is now canonical; keep criteria 5–8 open. Complete #5 and #6,
   then feed their profile, loader, parity, lifecycle, and CI evidence plus the
   eventual q8 result back into #4 before it closes.

## Evidence semantics that must survive

- Standard `EntityChanges` coalesces writes and cannot preserve every
  intermediate save, empty-but-triggered handler, or operation order needed for
  exact proof-of-indexing parity. BlockChanges is the ordered boundary.
- Clock-v1 represents every processed block, including observed empty blocks,
  and binds block number/hash at both producer and consumer boundaries.
- A deterministic-error inventory is a retained-row, point-in-time observation.
  It is not immutable error history or proof of the Graph Node binary that
  processed the range.
- Inventory identity includes deployment, exact half-open range, endpoint/fork
  hashes, shard deployment/head evidence, and independent primary-registry
  evidence. Null, unbounded, negative-lower-bound, and hash-bearing unversioned
  overlapping ranges count conservatively.
- Preflight every segment inventory and complete sealed artifact before any
  output, index change, write-capable connection, or earlier segment commit.
- An evidence-only OCI overlay may update evidence collectors and verifiers but
  must inherit frozen execution wrappers. Never widen an identity allowlist to
  hide accidental execution drift.
- A tested candidate is not yet canonical, a canonical merge is not yet a
  published runtime, and a published runtime is not operational authorization.

## Open questions and verified status

### 9274F V3 seed

No retained evidence proves that a Uniswap V3 dump was created or landed.
[`k8s-subgraphs#420`](https://github.com/pinax-network/k8s-subgraphs/issues/420)
described running fresh-sync roots and a future dump plan; [PR
#419](https://github.com/pinax-network/k8s-subgraphs/pull/419) created empty
landing zones. [PR #637](https://github.com/pinax-network/k8s-subgraphs/pull/637)
later classified the giant-sync Mainnet root for removal, and [issue
#583](https://github.com/pinax-network/k8s-subgraphs/issues/583) records that
the appliance and volumes were emptied by 2026-08-18. No repository, issue,
PR, or release records a V3 dump path, dump digest, head block/hash, restore
receipt, or landing date.

The exact intended targets are canonical Uniswap V3 Mainnet
`QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7` and canonical Uniswap V3
Base `Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP`. They are not the
Messari V3 Base target `QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh`
tracked separately by #83. An off-repository archive may exist, but #115
cannot select seed mode until operations supplies its path, digest, head/hash,
Graph Node identity, and restore evidence.

The V3 landing-zone headers also contain stale navigation metadata: they cite
bare `#10`, which is an unrelated estimator PR in `k8s-subgraphs`, and refer to
`core/prod/...` although the current files live under `core/kan/...`. Treat
those comments as historical plans, not seed evidence, and repair them in a
separate k8s metadata change.

### Argo WorkflowTemplates and access

Current `k8s-subgraphs/main` owns the templates under:

- `subgraphs-operations/backfill/base/workflow-template.yaml`;
- `subgraphs-operations/backfill/kan/compute-only-workflow-template.yaml`;
- `subgraphs-operations/backfill/kan/overlap-replay-workflow-template.yaml`;
- `subgraphs-operations/backfill/kan/production-workflow-template.yaml`;
- `subgraphs-operations/backfill/kan/replay-workflow-template.yaml`;
- `subgraphs-operations/backfill/kan/terminal-certification-workflow-template.yaml`;
- `subgraphs-operations/backfill/kan/v4-reference-replay-workflow-template.yaml`.

Flux enters through `deploy/kan/backfill.yaml`. GitOps contains no operator
RoleBinding for `denis-cli` in `subgraphs-backfill`; the observed `Forbidden`
response is therefore consistent with the repository. PR #836 adds V4
runner/collector permissions, not general operator access. Current GitOps uses
the `subgraphs-transplant:denis-cli` ServiceAccount while an older access doc
still names `kube-system:denis-cli`; confirm the kubeconfig identity before any
new binding instead of copying that stale subject. Until access is separately
granted, inspect definitions in Git and live progress through the approved
metrics only; do not describe that as a live Workflow inspection.

### Nightly V3 credentials

On 2026-09-02, `eth-substreams-tier1-prod.kan-sst2.pinax.io:443` was reachable
and its gRPC health endpoint returned `SERVING` with a locally supplied bearer
token. Do not copy that credential into GitHub, an issue, or retained evidence.
The backfills repository has no repository-level Actions secrets or variables;
inherited organization secrets could not be verified. There is no nightly V3
differential workflow yet.

The nightly path needs a credential-free endpoint variable, exactly one
Substreams token/key secret, and a dedicated Graph gateway analysis key (or a
Pinax Graph Node oracle). The prior exploratory Lodestar proxy observations are
not authoritative and do not pin an indexer or production revision. Do not
reuse the exhausted shared/free-tier gateway key documented in the operations
repository.

### Large static contracts

Externalization is agreed and tracked by [#108](https://github.com/pinax-network/substreams-backfills/issues/108).
There are 39 tracked `contract.json`/`contract-v1.json` files totaling
97,388,376 bytes (92.88 MiB); 11 files over 1 MiB account for 86.64 MiB.
Prefer content-addressed release assets for the first migration because Git LFS
is not installed in the current toolchain. Keep a small in-tree SHA-256/byte
lock, a fail-closed resolver, and cached CI retrieval. This shrinks future
working trees and stops growth; removing existing blobs from clone history
would require a separate, explicit history-rewrite decision.

## Restart checklist

- Read #118, #4, #5, #6, #26, #108, #114, #115, and #117 before changing code.
- Refresh both repositories and inspect all worktrees and open PRs before
  choosing a branch.
- Start new engine work from canonical #65 commit
  `5799d638cbc35a40f0498109e28a0b3e1e311fdb`; treat the Phase A branch only as
  squash-source material and the dirty Pool Mint v1 worktree as rejected.
- Do not reuse a descriptor from an earlier branch generation; merge the fields
  deliberately and reseal after the source tree is final.
- Wait for exact-head checks to finish before invoking the merge command; do not
  assume `--auto` will queue behind checks.
- Keep issue checkboxes unchanged until the stated canonical or evidence gate is
  actually satisfied.
