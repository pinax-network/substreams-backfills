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
| V4 shadow adapter | Merged as engine PR [#62](https://github.com/pinax-network/substreams-graph-node-backfill/pull/62), canonical commit `2e0c95b93d2760ef05b9aa4a319e45dceb7e5f87` | Default-off adapter; not a family-neutral input mode |
| Clock-v1 native framing | Merged as engine PR [#64](https://github.com/pinax-network/substreams-graph-node-backfill/pull/64), canonical commit `b1432f866e4ce8f819c84c81ade485e3e24fc647` | Canonical CI, Container publication, runtime digest, referrer, and retained archive independently verified |
| Deterministic-error inventory | Engine PR [#65](https://github.com/pinax-network/substreams-graph-node-backfill/pull/65), candidate `6e9f3ea012f470c1fc85500c4dd18db0a6ec455e`, exact-head CI in progress at handoff | Full local validation passed; do not advance #4 until exact-head and canonical gates finish |
| Physical-profile Phase A | Not landed | Integrate only after #65 is canonical; issue [#5](https://github.com/pinax-network/substreams-backfills/issues/5) records the source-built-fixture and independent-registry requirements |
| V4 q8 reproduction | Still open under [#26](https://github.com/pinax-network/substreams-backfills/issues/26) | Retained historical q8 evidence is not a fresh authorized reproduction; k8s PR [#836](https://github.com/pinax-network/k8s-subgraphs/pull/836) remains draft and behind |

The first PR #65 candidate failed only after its real Linux certification image
had passed the source, collector, permission, and semantic suites. The final
filesystem comparison correctly detected that the evidence-only overlay had
copied a newer `load-postgres-spool.sh` over the frozen reviewed wrapper. The
repaired candidate inherits both frozen execution wrappers and adds regression
coverage that refuses future source copies in the certification stage.

## Ordered continuation

1. Finish engine PR #65 on its exact candidate head. After squash merge, prove
   candidate/canonical tree equality and require canonical CI and Container
   publication before updating #4 or #83.
2. Start Phase A from that canonical engine `main`; squash-merge the existing
   profile work rather than resolving three descriptor generations one by one.
   Use the inventory descriptor as the base, add only the physical-profile
   pins, preserve Clock and inventory fields, and reseal once.
3. Copy `fixtures/physical-profiles/` into every source-built OCI builder that
   compiles Rust using `include_bytes!`. A host build does not prove the release
   build context is complete.
4. In the profile docs and evidence, keep shard identity
   (`subgraphs.deployment` plus `subgraphs.head`) separate from independently
   captured primary-registry placement. Shard-local `deployment_schemas` is not
   primary-registry evidence.
5. Complete #4 criteria 1–4 before advancing a #5 acceptance checkbox; then
   complete #5 and #6. Feed #5/#6 and the eventual q8 result back into #4
   criteria 5–8 before #4 closes.

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
- Verify PR #65's exact head, CI conclusion, merge state, and canonical outcome.
- Do not reuse a descriptor from an earlier branch generation; merge the fields
  deliberately and reseal after the source tree is final.
- Keep issue checkboxes unchanged until the stated canonical or evidence gate is
  actually satisfied.
