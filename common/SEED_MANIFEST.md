# Generic seed capture manifest

`seed_manifest` adds the portable `pinax.graph-node.generic-seed-manifest/v1`
contract without changing `BCGSNAP1`, its reader, or any earlier common contract.
It describes one capture transaction and pins the actual snapshot bytes. It is
not a database connection, capture implementation, loader, or operational approval.

The consumer supplies the manifest digest and full `Binding` independently.
The binding fixes deployment, network, descriptor, retention, entity inventory,
physical profile and catalog, stored schema and raw manifest, capture binary,
creating Graph Node identity, database/system identifier/site/schema, expected
boundary, start, and landing/oracle purpose. The creating Graph Node version is
the version referenced by the database's manifest, not an observation of the
current writer image. That current image and writer exclusion remain operational
run-binding checks.

`SeedSnapshotReader` owns the canonical snapshot reader. Its constructor checks
the manifest's external pin and binding and the actual stream header. Every row
remains provisional. Callers must consume every row and stage changes without
committing. Only `finish` checks snapshot checksum, EOF, actual full-file digest,
lineage, byte count and per-type row counts and returns `VerifiedSeed`. Finishing
early refuses; the wrapper never silently drains rows a consumer failed to import.
A diagnostic header check or deserialized `Manifest` is not a verified token.

Landing origin must equal the captured head and include the frozen snapshot VID
metadata. Oracle origin omits VID allocation metadata, can be earlier than the
captured head, and never passes `ReadPurpose::Loadable` or `require_loadable`.
Empty-root and compaction snapshots use their existing contracts, not this one.

A self-copy landing binds the separate exact `(deployment, copy block, copy hash)`
tuple and requires the seed head to follow that copy block. It leaves the deployed
manifest's graft absent. It cannot be relabeled as a cross-deployment graft.

Healthy/error-free observations and all three advisory lock results are mandatory
in the current capture contract. No accepted-error or handover override is exposed.
The transaction must be read-only repeatable read. Advisory locks alone do not
prove that a Graph Node worker was stopped. Captures must retain and separately
verify that operational evidence before deployment use.

History has two explicit states. `Unproven` records why the capture cannot establish
complete historical source/error coverage and permits only diagnostic landing
reads. Complete coverage requires the observed unlimited history setting, an
earliest block before deployment start, and the exact entity-table inventory of
observed prune markers, all absent or earlier than deployment start. A missing
`table_stats` row must not be relabeled as an observed SQL NULL marker by the
capture implementation. Changing `history_blocks` after pruning is insufficient.
Oracle capture also requires this complete coverage. Future copied/pruned-history
proofs require a separate reviewed contract; callers cannot replace them with a
boolean or an asserted `no failed hosts` string.

The observations must come from a trusted, externally pinned capture executable
and the exact database transaction. This codec validates their structure and
agreement, not their authenticity. Its token does not make a diagnostic physical
profile production-selectable and does not authorize a loader or live mutation.

Validation: `cargo test --locked -p backfill-common` and
`cargo clippy --locked -p backfill-common --all-targets -- -D warnings`.
