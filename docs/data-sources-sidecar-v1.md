# Dynamic-source companion for a bounded V3 root run

`pinax.graph.backfill.data-sources/v1` explicitly complements **unchanged**
BlockChanges v1. It is a JSON sidecar, selected with producer
`--data-sources-out sources.json` and consumer
`--data-sources-sidecar sources.json`. Without it, the engine still refuses a
faithful spool requiring `data_sources$`; `--allow-omitted-data-sources` still
produces only `INCOMPLETE.json`.

This milestone is a fresh, contiguous, onchain Ethereum root replay, at most
10,000 blocks / 16 MiB of sidecar. No checkpoint input, grafted manifest,
synthetic frame, offchain source, or deterministic indexing error is accepted.
It does not certify production, full ancestry, or continuation of a backfill
checkpoint. The existing host checkpoint remains usable for diagnostic replay;
a seed-bound metadata continuation protocol is future work.

The producer takes sources from actual accepted, deduplicated runtime hosts,
using Graph Node v0.44's `as_stored_dynamic_data_source`, **not** from final Pool
entities or a count of attempted template creations. The sidecar covers every
frame, including blocks with no creations, and binds descriptor SHA-256,
per-block number/hash/payload SHA-256 and complete BCF1 stream SHA-256.
Records stay in host creation order and retain creation block, template
manifest index, raw Ethereum address, and exact Graph Node JSON context.
The consumer checks template indices against the selected physical profile.

Graph Node's source identity ignores creation block but includes manifest index,
address and context (plus manifest-bound mapping attributes). Failed-handler
creations are discarded by the runtime before `drain_created_data_sources`.
**Fatal block errors do not discard already accepted source metadata:** v0.44
passes `persisted_data_sources` to its transaction while retaining only PoI
entity modifications, then stops. This sidecar refuses *all* indexing-error
runs because complete indexing-error/status metadata is not carried.

The engine writes the existing profile-defined COPY columns in order:
`block_range, causality_region, manifest_idx, parent, id, param, context, done_at`.
PostgreSQL allocates the identity VID; parent/id/done_at are NULL for this
onchain scope. `param` is bytea, context is JSONB (NULL remains distinct from an
empty object), ranges open at creation and are never clamped. Sources do not
contribute to schema entity counts. Creation order therefore survives database
VID allocation, Graph Node's `(creation_block, vid)` load order and reverts.

A successful spool retains optional `manifest.data_sources` provenance:
`format`, sidecar `sha256`, `stream_sha256`, `blocks`, and `rows`. The ordinary
COPY inventory and READY digest cover the physical rows. A mismatch may leave
an unsealed `.building` directory but must never produce READY.

To use a Pinax Firehose gateway, `FIREHOSE_API_KEY` sets `x-api-key` independently
of bearer-token variables. Never put credentials in artifacts or command logs;
RPC transport failures report only status/class, not signed URLs.

Authoritative semantics: Graph Node commit
`77823b5a7adc4eac4abf03202c8dd7cb00dea31d`,
`chain/ethereum/src/data_source.rs` (identity/stored serialization),
`core/src/subgraph/runner/mod.rs` (accepted sources and fatal transaction),
`store/postgres/src/dynds/private.rs` (insert/load/revert).
