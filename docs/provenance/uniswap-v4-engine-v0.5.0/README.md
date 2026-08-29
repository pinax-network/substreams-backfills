# Uniswap V4 engine v0.5.0 pre-execution reference

This directory retains the smallest tagged evidence set needed to prepare GitHub
issue #26 without invoking Substreams, Kubernetes, a workflow, or PostgreSQL.
Every imported JSON byte comes from
`pinax-network/substreams-graph-node-backfill` tag `v0.5.0`, commit
`2b5ef82e2db987a5bfe861330aba0a222956122e`, tree
`d1f8c5973ee2177a3a4cdae75717efb939e5da95`. `closure.json` binds the source
paths, Git blobs, byte lengths, SHA-256 digests, engine identity, imported SPKG,
and retained cross-references.

The selected historical reference is Base blocks `32,374,155..32,474,154`,
seeded at block `32,374,154`. The retained evidence fixes the canonical seed
and end hashes, 86,342 event-bearing frames, payload-byte count, 20-table
parity inventory, checkpoint identity, PoI identity, and exact GraphQL digest.
The original certificate used the legacy Store-state package. The imported
sharded package is linked only by a later read-only overlap result, so this
capsule is deliberately not a v0.5.0 reproduction certificate.

The tagged source repository does not retain the selected range's runtime
checkpoint-manifest bytes, literal COPY spool filenames/digests, frame payload
bytes, or checkpoint bytes. Their summarized identities remain pinned, and
their absence is machine-readable in `closure.json`; they must not be
reconstructed or inferred.
The lifecycle fixture covers a separate 189-block legacy-candidate
continuation. It is supporting history, not execution evidence for v0.5.0.

Run the offline verifier and adversarial tests from the repository root:

```bash
python3 scripts/verify-uniswap-v4-engine-reference.py
python3 -m unittest scripts.tests.test_uniswap_v4_engine_reference
```

Passing those commands proves only repository closure for acceptance criterion
1 and partial pre-execution support for criterion 2. It does not name or
authorize a scratch target, prove zero writers, approve K3, submit a workflow,
touch a database, or establish readiness.
