# Producer checkpoint contract

`common::producer_checkpoint` is the concrete shared codec for integrated plan
R-3. Its format is `pinax.backfill.producer-checkpoint/v1`; it replaces the
unimplemented family-specific example in reducer design section 13.4. This
change defines evidence bytes only. It does not enable durable reduction or
authorize an engine spool to load.

The canonical pretty-printed JSON ends with one newline and has a 1 MiB ceiling.
Unknown fields, duplicate fields, alternate encodings, invalid hashes, unsafe
evidence paths, zero observed boundaries, and inconsistent ancestry are refused.
The manifest binds the exact deployment, network, descriptor, extractor release
lock/package/module, reducer source commit and executable digest. The engine
must supply these pins independently, including the extractor lock SHA, instead
of accepting the manifest's claims as their own authority.

Each completed segment records its predecessor manifest SHA, start boundary,
undo-file pin, previous reducer lineage, resulting reducer lineage and engine
lineage before execution. The reducer lineage is SHA-256 of
`pinax.reducer-lineage/v1\0`, the 32 predecessor-lineage bytes, and the 32 undo
digest bytes. Initial lineage hashes the canonical binding/origin tuple with
the separate `pinax.reducer-origin/v1\0` domain. Verification of the manifest
does not verify the undo file; replay and recovery must also retain and verify
that file's actual bytes. The previous manifest is supplied by its consumer and
checked by hash, binding, origin, boundary and lineage.

Empty-root origin uses BCGSNAP1's `(start - 1, zero hash)` sentinel. An initial
manifest cannot seal a spool. Only the first root segment records a nonzero
`observed_root_parent_hash`, taken from its validated first input block; its
`transition.from` still equals the engine's root sentinel exactly. Every
completed boundary has an observed nonzero hash. Seeded and subsequent segments
reject a root-parent observation. Snapshot origins distinguish landing from
oracle provenance; oracle ancestry is never loadable.

Source count/order, failed host count/digest and retained entity counts are
recorded explicitly. The failed-host state matters because an aborted Factory
creation must remain unmatched after resume. Full logical state SHA is optional
and means a full scan was performed; absence makes no such claim. A physical
redb file hash is never a logical state digest. Consumers still check these
commitments against the actual store and source inventory.

Engine v3 publication retains `producer-checkpoint.json`, verifies its actual
canonical bytes against `producer_checkpoint.manifest_sha256`, and compares its
format/boundary/lineage to that tuple. It also verifies the external binding,
engine predecessor lineage and predecessor manifest. A regular completed spool
requires equal reducer and engine final boundaries and source commitments. A
stop-before-error spool may have reducer look-ahead; its producer checkpoint
still binds the fully consumed input range and cannot be relabeled as the
shorter engine boundary. Rewind must return both stores to the agreed boundary.

Validation includes exact bytes/binding, canonical-form refusals, undo/ancestry
mutation, empty-root consistency, oracle load refusal, invalid commitments and
the existing common-contract suite. These are codec checks, not crash recovery,
live Substreams, checkpoint resume, Docker, or production qualification.
