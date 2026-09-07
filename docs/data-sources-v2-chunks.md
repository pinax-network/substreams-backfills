# Resumable onchain source metadata: v2 producer chunks

This is a new producer capability, not a migration of
`pinax.graph.backfill.data-sources/v1`. Existing v1 root-only CLI and consumer
guards remain unchanged. A sealed producer chunk is not an engine COPY spool,
a load authorization, a graft seed, or production certification.

## Scope and limits

Chunks cover every block of a contiguous range of one unchanged root deployment,
including empty blocks. Each chunk is limited to 10,000 blocks and 16 MiB of
metadata. Grafts, non-NULL contexts, nonzero causality regions, done-at values,
and every deterministic indexing error are refused. Error-bearing runs cannot
be promoted to READY.

Index merge and predecessor identity lookup are disk-backed with 64 KiB buffers.
Only the current bounded chunk's metadata and new creations are additionally
retained in memory. This **does not make the full host bounded-memory**: its
MemoryStore, LFU cache, active runtime hosts, loaded cassette and checkpoint
vectors still grow with state. Fixture mode eagerly decodes its requested raw
blocks. A disk-backed entity backend, bounded cache, streaming checkpoint
restoration and cassette storage remain separate follow-up work. Raising chunk
limits does not replace that work.

## Invocation and artifact lifecycle

Use `--source-chunk-out output/chunk-000.ready` with the usual segment, cassette
and contiguous `--from`/`--to` or `--blocks` arguments. For a successor add
`--source-chunk-in output/chunk-000.ready` and choose a new output path. The next
range must start at exactly the preceding chunk's exclusive end.

This mode owns its output files. Independent checkpoint, BCF, v1 sidecar, store,
frame and report destinations are refused; reports go to stdout and can be
retained outside the chunk. A bare diagnostic checkpoint never authorizes v2
continuation. Checkpoint-every and continue-outputs are refused. Interruption
leaves an unsealed `.building` directory; recovery reruns the bounded chunk
from the last immutable predecessor into a fresh path. Nothing repairs or
deletes existing output paths for the caller.

A completed directory contains exactly:

| File | Purpose |
| --- | --- |
| `blocks.bcf1` | Unchanged observed BCF1/BlockChanges v1 wire stream |
| `data-sources.json` | Explicit `pinax.graph.backfill.data-sources/v2` metadata |
| `host-checkpoint.json` | Existing host checkpoint/v2 JSON Lines state |
| `source-identities.bin` | Cumulative sorted unique source identities |
| `manifest.json` | Raw byte length and SHA-256 of all four artifacts |
| `READY.json` | Canonical manifest byte length and SHA-256 seal |

The producer verifies and `sync_all`s every existing stream, checkpoint and
index payload before writing/syncing metadata, manifest and READY. A payload
sync failure cannot create READY. It then syncs the staging directory and uses
atomic no-replace rename from `.building` to `.ready`, followed by a parent
directory sync. Linux and macOS are supported; unsupported platforms/filesystems
fail closed without a plain-rename fallback. The output parent
must exist. Existing output/staging targets, symlinks, extra files, truncations
and changed pins are refusals. An empty destination directory created after an
absence check is preserved, not overwritten. A READY file inside a leftover building path is
not promotion of the requested ready path. Workflows must exclusively own
building paths and treat completed paths as immutable.

A basename output such as `--source-chunk-out chunk-000.ready` is supported:
the current directory is synced after promotion, just as an explicit parent
directory is. Regression coverage uses an isolated subprocess working directory
and verifies both successful completion and the exact sealed output inventory.

## Cross-chunk contract

Every block binds its number, canonical hash and exact payload SHA-256. The
companion additionally binds the full raw BCF1 stream and closing host
checkpoint. The producer canonical-decodes all frames, checks exact coverage,
and refuses error operations. v2 input requires a valid parent hash on every
non-genesis block and linked adjacent hashes, including the first block after
checkpoint restoration.

Creations come from Graph Node's actually accepted runtime hosts, never inferred
pool rows. Unsigned global zero-based `ordinal` values are contiguous. Runtime
creation order is preserved across restart, not sorted by address. Rejected
duplicate hosts do not enter the inventory. Pinned Graph Node handler and
rollback semantics remain unchanged; error metadata is outside v2 scope.

`before` and `after` contain `SourceState { order: { count, sha256 }, identities:
{ bytes, sha256 } }`. The order commitment initially hashes the UTF-8 string
`pinax.graph.backfill.data-sources/v2/creation-order` plus a zero byte. Every
append hashes that domain, the previous 32-byte hash, unsigned ordinal in
big-endian 8 bytes, nonnegative creation block in big-endian 4 bytes, and the
24-byte identity. Thus final semantic state is independent of chunk boundaries
and paths.

The index is `BCDSIDX2` followed by strictly sorted unique 24-byte records:
nonnegative manifest index in big-endian 4 bytes, then the 20-byte Ethereum
parameter/address. NULL context and causal region zero are mandatory, so no
omitted field distinguishes identities in this version. Historical keys are
binary-searched on disk, and a streaming merge rejects cross-chunk duplicates
while rehashing the consumed predecessor. Index count equals source count.

`parent` binds the predecessor boundary and exact `seal`, `manifest`, `stream`,
`metadata`, and `checkpoint` file pins. `before` must equal its `after`;
deployment, network, descriptor and root start cannot change. Host checkpoint
restore separately validates its existing identity/cassette rules, exact
boundary/range/total counts and previous checkpoint link. Every restored source
must match the cumulative ordered commitment and disk index before output
creation. Predecessors are checked again before output preparation and promotion.

## Trust boundary and consumer integration

The independently verified, immutable **direct predecessor** is the trust
boundary. A digest seal detects mutation; it is not an authority signature and
does not prove an arbitrary self-consistent artifact came from an approved
producer. Orchestration must retain and approve exact receipts and source/runtime
provenance. Retain all ancestor receipts for later offline chain audit. Each
continuation verifies its immediate predecessor without recursively rehashing
all history on every chunk.

The consumer requires a separately reviewed explicit BCGCKPT2 path: independently
verified producer and engine predecessor receipts, independently merged source
index, and global COPY creation order. BCGCKPT1's omission boolean is not source
provenance. Semantic consumer checkpoints must remain independent of chunk
boundaries; raw producer/engine provenance belongs in manifests. Until that
consumer and loader path is complete, these producer chunks do not establish
an end-to-end production path.

## Tests and evidence

`common/tests/dynamic_sources_v2.rs` is explicitly synthetic contract/storage
coverage: split parity, empty chunks, same-block order, cross-chunk duplicates,
unsupported fields, exact predecessor mutation, torn/reordered indices, and
10,000 fixed-width identities. It is not host or database parity evidence.

`mapping-host/tests/mapping_host/source_chunks.rs` checks the real root fixture
through the CLI, exact inventory, overwrite/checkpoint bypass refusals, changed
predecessors before network/output setup, sampled gaps and torn staging. A
separately ignored real-300 test requires a locally verified raw Firehose corpus
and existing pinned historical cassette; the test itself never uses a network:

```sh
V3_SOURCE_CHUNK_CORPUS=/absolute/path/blocks \
V3_SOURCE_CHUNK_CASSETTE=/absolute/path/cassette.json \
V3_SOURCE_CHUNK_EVIDENCE=/absolute/path/fresh-evidence-directory \
cargo test --manifest-path mapping-host/Cargo.toml --locked \
  source_chunks::real_300 -- --ignored --nocapture
```

It compares real 300-block output against the preexisting engine BCF fixture
SHA-256 and a real 200+100 restart. Every BCF byte, per-block creation, final
index and semantic source state must match exactly. The final host checkpoint
is compared in full after excluding only explicit chunk-boundary provenance:
identity, cassette, PoI, totals, ordered sources, every row/field and cache key
remain equal. The split begins on a real creation. Optional evidence output
retains all chunks and a comparison receipt. Raw corpus publication and fixture
locking require separate review.
