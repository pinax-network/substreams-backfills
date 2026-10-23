# Generic state snapshots and clock-v1 transport

`backfill-common::state_snapshot` owns the BCGSNAP1 encoding used by the planned
generic engine and family reducers. This is a shared codec, not a seed-capture
tool or authorization to load a database. The consumer must independently
validate the physical profile, template membership, retention evidence, source
provenance and writer exclusivity.

## Snapshot identity and completion

A snapshot contains the eight bytes `BCGSNAP1`, a big-endian u32 header length,
a canonical MessagePack header, and the declared number of records. Each
record has a big-endian u32 length and a canonical MessagePack map with binary
`key` and `value` fields. The trailer contains `BCGSEND1`, a big-endian u64
record count, and the SHA-256 of all preceding bytes, including the trailer
magic and count. Bytes after this digest are refused.

The header binds deployment, network, descriptor SHA-256, retention SHA-256,
sorted entity type ordinals, entity-ID policy, boundary, provenance, VID state,
PoI state, complete dynamic sources and period maxima. Canonical MessagePack
uses named struct maps in declaration order, minimal integer encodings and
sorted BTreeMap entries. Decoding followed by re-encoding must reproduce the
exact bytes. Unknown fields, duplicate fields, alternate encodings and trailing
bytes are refused. The complete-file identity includes the checksum itself.

`SnapshotReader::new` requires the caller's expected binding and an explicit
`ReadPurpose`. A loadable reader refuses oracle snapshots. `next_record`
returns provisional data; reaching the declared row count is not proof of
completion. Only `finish`, after checking the trailer and EOF, returns the
opaque `VerifiedSnapshot`. Stage all changes until this succeeds. Read and
write errors poison their respective objects, preventing a later successful
finish after an ignored error. A successful writer flush does not replace
filesystem fsync and atomic publication, which belong to the consumer.

The default encoded-header ceiling is 64 MiB and the encoded-record ceiling is
256 MiB. Consumers may lower these limits. All dynamic sources must fit in the
header; overflow is an error, never truncation. Readers retain one record and
the previous key rather than collecting the entity table in memory.

## Records and lineage

Keys sort bytewise as `[type ordinal: u16 BE] [causality region: sign-flipped
i32 BE] [ID kind: u8] [ID bytes]`. ID kinds are 0 for UTF-8 strings, 1 for bytes,
and 2 for sign-flipped i64 BE integers. The current storage contract refuses
negative causality regions. Values contain version byte 1, an i64 BE VID, an
i32 BE range start, and canonical prost `EntityFields`. The shared BlockChanges
validator checks exact scalar values and the ID field; numeric values are not
normalized during snapshot round trips. Records must be strictly sorted and
unique, start no later than the boundary, and fit the table's recorded VID
maximum when VID state is present.

Dynamic sources reuse the exact v2 `SourceOrder` hash domain and include every
row in `(creation_block, vid)` order. Duplicate identities and VIDs are refused.
Empty roots have no state and an explicit start block. Landing snapshots bind
the physical seed head to their boundary. Oracle snapshots carry no allocator
VID state and are only comparison inputs. Compaction snapshots preserve the
existing `through_lineage`.

For root, landing and oracle snapshots, the initial lineage is
`SHA256("pinax.generic-state-lineage/v1\0" || zero32 || snapshot_file_sha256)`.
Each delta advances it using the same domain, the previous lineage and the
delta file SHA-256. Compaction does not advance or reset this lineage. A valid
checksum proves integrity against the expected artifact identity, not that
the capture tool observed the correct source database.

## BCF1 clock-v1

`backfill-common::clock` shares the existing engine's 52-byte envelope:
`BCF1`, kind byte (1 observed, 2 synthetic range fill), three zero reserved
bytes, u64 BE block number, 32-byte hash, u32 BE payload length, then opaque
payload bytes. Observed hashes must be nonzero. Synthetic frames must have a
zero hash and empty payload. Block numbers fit signed int32; payloads are
limited to 256 MiB before allocation, with an optional lower consumer limit.

`read_frame` distinguishes clean EOF from truncated headers and payloads,
handles interrupted reads and leaves the next frame unread. Empty observed
payloads remain valid at the transport layer. The reducer must separately
require its nonempty extractor message and validate the payload's block hash,
parent linkage, contract and anomaly fields.

`ObservedRange` checks one observed frame per block over a required half-open
range. It refuses gaps, duplicates, synthetic fill, extra blocks and premature
completion; any refusal poisons the range. Call `finish` only after stream EOF.
The supervising driver must also verify the producer process succeeded: valid
frame bytes alone cannot prove a successful producer exit. The mapping-host
and engine migration to this shared codec is a separate integration step.
