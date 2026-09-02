---
name: certify-backfill-successor
description: Verify, merge, and canonically publish a digest-pinned Substreams Graph Node backfill successor or evidence-only OCI overlay. Use when changing engine Docker targets, runtime identity allowlists, descriptor pins, release archives, or GHCR attachments.
---

# Certify a backfill successor

Read the engine repository's `AGENTS.md` before acting. Use the dated
[handoff](../../../docs/blockchanges-v1-handoff-2026-09-02.md) for current
project state; keep mutable SHAs and run results out of this reusable skill.

## Classify the target

First classify the image as one of:

- an execution successor, which intentionally replaces loader or replay code;
- an evidence-only overlay, which certifies a frozen execution runtime.

An evidence-only overlay must inherit the frozen loader and replay wrappers.
It may replace only its declared evidence collectors, verifiers, fixtures, and
metadata. If filesystem identity finds an unexpected execution-file change,
remove the change; never widen the allowlist merely to make the comparison pass.

## Close the source-built identity

Audit the actual Docker build context, not only the host checkout. Include every
compile-time input, including files referenced by Rust `include_bytes!` or
`include_str!`. Require the source-built/release image to contain the same
validated binary and policy bytes that the descriptor pins.

After the source tree is final:

1. recompute direct source and Dockerfile hashes;
2. update the compatibility descriptor;
3. compute its raw-byte digest and matching sidecar once;
4. run negative tests that alter each important pin or forbidden overlay copy.

Do not reseal repeatedly while other source files are still changing.

## Validate the exact candidate

Run the repository-required focused tests and the complete validation ladder,
including:

```bash
make validate
SKIP_LIVE_SMOKE=1 make verify-spkg
git diff --check
```

Build and inspect the exact Linux/amd64 OCI target. Compare its filesystem to
the frozen base with explicit replacement and addition allowlists, and exercise
the installed entrypoints. An Apple-arm64 Docker emulation crash is
inconclusive; native hosted Linux remains the executable-image authority.

Record the candidate head, sole parent, tree, descriptor digest, image digest,
and exact CI run. Preserve the first failing run and its precise identity diff
in the PR description when a repair changes the candidate.

## Merge and prove canonical publication

- Require hosted CI success at the exact reviewed head.
- Do not use `gh pr merge --auto` as a check queue unless branch protection has
  been verified to require those checks. Without that gate GitHub may merge
  immediately. Poll the exact candidate to terminal success before invoking a
  merge command.
- Re-read the remote head immediately before merging and use the GitHub
  exact-head merge guard; abort if it changed.
- After squash merge, compare the canonical commit's tree to the tested
  candidate tree. Equal source content must be proved, not inferred.
- Require exact canonical push CI and the Container publication workflow.
- Independently verify the published GHCR subject digest, immutable labels,
  expected OCI referrers, attachment bytes, release archive digest, and retained
  evidence hashes.

Only then update tracking issues. State the lifecycle precisely: candidate
tested, merged canonically, published, or operationally authorized. None of
these states implies the next one, and repository delivery never grants live
Kubernetes or database mutation authority.
