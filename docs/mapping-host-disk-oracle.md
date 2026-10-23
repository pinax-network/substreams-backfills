# Bounded disk-seeded Aerodrome oracle

`graph-mapping-host disk-oracle --request REQUEST.json --request-sha256 SHA256`
executes the deployed Aerodrome mapping in the pinned Graph Node runtime against
an exact, complete BCGSNAP1 physical seed. It produces oracle comparison evidence,
not an engine READY spool, producer checkpoint, load approval or production
qualification. The existing memory oracle and its v1 fixtures remain unchanged.

The request is the typed `disk_oracle::Request` serialized with Rust's pretty
JSON serializer followed by LF. Its externally supplied digest binds every
path, seed binding, input pin, range and resource ceiling. The output directory
must be new; failed directories remain evidence and cannot be reused. `input`
is either `{"kind":"firehose"}` or `{"kind":"fixtures","blocks":[...]}`.
Every artifact has `path`, `bytes`, and `sha256`. The seed manifest, snapshot and
pre-recorded RPC cassette are mandatory. The request does not accept credentials.
Live Firehose uses the existing endpoint and credential environment contract;
fixture execution never opens a network connection.

The seed must contain every schema entity type with persistent retention,
including immutable and period entities, String IDs and causality region zero.
Its canonical manifest must prove complete, unpruned history. The independently
pinned binding is checked against the exact deployed schema, raw manifest,
specification and start block. `creating_graph_node` remains the exact original
deployment-creator provenance: it need not equal the separately pinned Graph Node
revision that executes this oracle. No creator compatibility is inferred from
that historical version field.

This oracle still executes Graph Node revision
`77823b5a7adc4eac4abf03202c8dd7cb00dea31d` (`v0.44.0`). It does not establish
equivalence to a live `v0.45.0` process. A bounded live qualification must separately
pin the native source's block hash and stored PoI region digest at the comparison
head, start from its exact earlier state and PoI, and require both replay results
to reach that digest. A physical self-copy must preserve the starting PoI bytes.
Public PoI comparisons additionally require the same deployment CID, block hash
and indexer argument; a different deployment's graft digest cannot be substituted.
Empty trailing blocks retain the last accumulated region digest. This remains
bounded execution evidence, not general runtime-version equivalence.
For a same-CID copy at C that natively advances to seed predecessor S before the
bounded replay to paused source head H, require source C versus Landing history C
PoI equality, source S versus Landing active S PoI equality, and both replays'
final accumulated digest versus the independently pinned source H digest. Pin
the PoI version, region and block hash as well. These external native comparisons
are live qualification prerequisites; the disk-oracle completion receipt alone
does not enforce or attest them.

Import streams one bounded row at a time into a newly created private redb
cache, with a 64 MiB database cache and commits after 32 MiB of encoded input.
A single row remains subject to the shared snapshot limit of 256 MiB. No usable
store escapes before the complete trailer, EOF, file digest, lineage, inventory
and history checks pass. An interrupted import leaves an unusable private file;
there is no API to reopen that file as an admitted seed. The entire seed must fit
on disk. This implementation does not claim that an arbitrary existing deployment
has already been captured or that a hundreds-of-millions-row import was measured.

Every row makes a lossless roundtrip through the pinned Graph Node entity types.
Raw BigDecimal coefficient/scale, explicit Null, IDs and VIDs must survive exactly.
A numeric tuple that Graph Node would normalize differently is refused; it is
never silently repaired. This retains the existing decimal-domain limitation.
The admitted negative production TVL `-1958.2627366648723548155211868460794` has an
exact regression, alongside a negative 35-digit normalization refusal.

Replay keeps one `SegmentHost`, its ordinary LFU and a bounded in-memory overlay
across the whole window and every output partition. The immutable base serves
all untouched rows. First-touch undo, including missing rows and VIDs, covers
fatal block rollback. Disk failures are errors, never absence. Overlay ceilings
refuse before a batch changes state; no arbitrary cache eviction changes mapping
behavior. The three exact deployed WASM modules import only `store.get` and
`store.set`. Disk mode explicitly refuses derived queries and eager full-store
exports instead of returning an incomplete overlay-only answer.

Admission permits 1–1,000 blocks, partitions of 1–500 blocks, at most 100,000
sources, one million LFU/overlay keys and 1 GiB encoded overlay bytes. The caller
must choose positive ceilings at or below those limits. `timeout_seconds` is
1–7,200 and bounds the replay window's connection, input, mapping and actual EOF
waits after seed import. It is not an arbitrary time limit on importing the full
historical seed. A raw block is at most 64 MiB, total raw window input at most
16 GiB, BCF1 payload at most 16 MiB (excluding its 52-byte header), and a cold
checkpoint/report line at most 4 MiB including its terminating LF. The locked cassette is at most 64 MiB and
100,000 unique entries. Any bound failure refuses completion.

The initial `seed.checkpoint.jsonl` uses the existing checkpoint/v2 format and
streams every entity plus the actual PoI row and ordered dynamic-source inventory.
All rows are cold (`cached:false`); present/absent cache and cassette-row inventories
are empty. Its exact cassette digest comes from the actual bytes loaded by the
host. No final full checkpoint is exported or required. Each `partition-NNN`
contains canonical `frames.bcf1`, the existing `report.jsonl`, and `input.fob1`:
`FOB1` followed by repeated big-endian u32 lengths and the original Ethereum block
protobuf bytes. This is a retained raw-input artifact, not a native Substreams
completion receipt. Live success requires final blocks, exact contiguous clocks,
parent linkage to the seed and actual server EOF after the requested range.

Only after all partitions finish, files are synced and the actual executable is
rehashed does a synced private partial completion file become `complete.json`
through an atomic no-replace hard link. Its directory is synced before removing
the partial name. A write failure cannot expose a partial completion marker, and
an existing marker cannot be overwritten. The receipt pins the compiled source
closure, actual executable, seed artifacts, retained descriptor/cassette/cold
checkpoint and every partition. An external supervisor must still attest the
actual successful process exit and bind these bytes into the engine's reviewed
`OracleExecution` witness. Fixtures are explicitly marked `fixture_only`.

Tests cover streamed multi-transaction import, exact scalar/VID preservation,
corrupt disk rows, all-or-nothing overlay admission, fatal undo, seed corruption,
full cold-checkpoint comparison, one continuous host across two partitions,
wrong-parent poisoning and a bad suffix with no completion. Public-command tests
cover wrong request pins, malformed requests and nonblocking FIFO/symlink refusal.
These are bounded hermetic proofs; actual Linux runtime and real physical-seed
witness execution remain separate gates.

The `mapping-host-runtime` PR job retains a usable `mapping-host-candidate-SHA`
Actions artifact after successful native execution. It contains the exact tested
Linux application archive, a separate full closed-source-context archive, runtime
and source inventories, installed-smoke evidence and a final digest receipt.
The receipt explicitly says `registry_published:false` and
`production_selectable:false`; its image configuration is an execution pin, not
a registry manifest digest. Canonical main publication remains a separate path.
The application archive preserves the installed executable's mode 0555 and bytes;
streamed archive creation checks every file against the sealed inventory before
publishing the receipt. The installed disk smoke is synthetic and does not
constitute a witness for any live physical seed.
