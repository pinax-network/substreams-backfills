# Uniswap V4 q8 declared replay metadata

This directory brings the prepared q8 replay lane into
`substreams-backfills` without claiming that the historical run can be
reproduced from repository bytes alone.

The eight JSON fixtures are copied byte-for-byte from
`pinax-network/substreams-graph-node-backfill` commit
`395c9fb0d5377cba058d506043b7891c2f2016a8`, tree
`c3568b472faf13e07618e14dc9551f9400551fa3`. Their exact source paths,
Git blobs, byte lengths, and SHA-256 digests are bound in `closure.json`.
`LICENSE.source` retains the Apache-2.0 license from that repository.

The locally recovered compact archive
`release-complete-q8-200k-20260815-r1-evidence-20260815.tar.gz` is also
retained exactly: 9,047 bytes, SHA-256
`3072f55bac5f0a1bcdff799642cf0b4deeb414381fb19e6a9d18322627ff34d1`.
Its ten data members are checksum-bound by the included `SHA256SUMS`.
The archive contains compute events, evidence, output, progress, parity,
performance metadata, and both manifest/READY pairs.

The two q8 segments are:

- certified: Base blocks `33,374,155..33,474,154`, seeded at
  `33,374,154`;
- restore: Base blocks `33,474,155..33,574,154`.

The retained manifests expose all 19 ordered COPY tables, literal row/clamp
filenames, byte counts, record counts, digests, file-set digests, PoI
identities, target hashes, and checkpoint identities. `data_sources$` is
seed-preserved rather than emitted as a twentieth COPY table.

## Deliberate non-claims

The archive is compact metadata, not the historical raw replay payload. It
does not contain:

- either raw frame stream or a frame-stream digest;
- any COPY row or clamp payload;
- the 11,093,835,518-byte seed checkpoint;
- the 13,589,557,635-byte certified checkpoint;
- the 15,996,029,671-byte restore checkpoint.

The historical `input_stream_exact: true` field compared only
`input_format`, `input_frames`, and `input_payload_bytes`. It therefore
means input-shape equality, not raw-byte identity. The source reference's
`availability: unavailable-in-this-certification-path` is stale with respect
to the recovered compact archive, while its `acceptance_role: none` remains
correct.

This capsule supports issue #26 acceptance criterion 2 but does not complete
it. A new, separately authorized replay must emit a frame-stream receipt
digest and produce fresh scratch, GraphQL, lifecycle, and payload evidence.
Nothing here authorizes K3, Kubernetes, a Workflow, PostgreSQL writes,
activation, production, or promotion.

Run the offline verifier and adversarial tests from the repository root:

```bash
python3 scripts/verify-uniswap-v4-q8-reference.py
python3 -m unittest scripts.tests.test_uniswap_v4_q8_reference
```
