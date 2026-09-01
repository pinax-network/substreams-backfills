# BlockChanges v1 contract

`pinax.graph.backfill.block-changes/v1` is the family-neutral boundary between
a source-specific mapping/reducer adapter and the Graph Node compatibility
engine. Its protobuf schema is
[`common/proto/block_changes.proto`](../common/proto/block_changes.proto), and
the fail-closed Rust validator is
[`common/src/block_changes.rs`](../common/src/block_changes.rs).

This contract is deliberately not `sf.substreams.sink.entity.v1.EntityChanges`.
Table-oriented EntityChanges coalesces writes by entity. Graph Node hashes each
Set and Remove in mapping execution order before the entity cache merges
partial updates, so a coalesced or reordered stream cannot prove equivalent
entity history or proof of indexing.

## Envelope and compatibility binding

Every message contains:

- the exact `pinax.graph.backfill.block-changes/v1` contract string;
- a nonzero 32-byte `compatibility_id` equal to the SHA-256 of the checked-in
  producer compatibility descriptor expected by the consumer;
- a block number in Graph Node's signed 32-bit domain and an exact 32-byte EVM
  block hash;
- `mapping_triggered` plus the deployment's PoI causality region when Graph
  Node called an onchain `start_handler` (empty for untriggered or
  offchain-only frames); and
- dense, zero-based block-local operations in nondecreasing
  `handler_group_order`; and
- the manifest's fatal or non-fatal deterministic-error policy.

Callers construct `BlockChangesCompatibility` from the exact descriptor bytes;
the constructor computes their SHA-256 and parses and cross-checks the contract,
descriptor version, deterministic-error policy, network, and deployment PoI
causality region. Encode, decode, and validation then require that derived
profile. There is no public constructor that can pair a digest with arbitrary
policy or region sidecars. Length-only validation is intentionally
insufficient: a structurally valid frame from a different producer/profile is
refused. Graph
Node v0.44 uses one onchain PoI region per deployment, `ethereum/{network}`;
applicable frames therefore contain either no region or exactly the one bound
by the compatibility profile. Multiple onchain regions are rejected even
though protobuf represents the field as repeated.

Graph Node creates the deployment-region `BlockEventStream` when
`start_handler` runs,
even if the handler emits no entity event, and `pause` still hashes the empty
event-vector length. The region list therefore carries information that a
bare `mapping_triggered = true` cannot. Repeated starts for the same region
without intervening events do not change the final per-block stream, so the
canonical envelope stores the sorted unique region set.

Source: Graph Node v0.44.0 commit
[`77823b5`](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/components/subgraph/proof_of_indexing/online.rs#L107-L252).

## Ordered operations and handler failure

Each `EntityOperation` has a dense `operation_index`, a block-local
`handler_group_order` for one Graph Node `start_handler` invocation, a
stage-local `source_trigger_order`, a hosted `handler_order`, source storage
causality, optional string PoI causality, and exactly one Set, Remove, or
DeterministicError payload. Dynamic-data-source rounds can reprocess an earlier
source trigger, so `source_trigger_order` may repeat or regress while
`handler_group_order` remains monotonic. All records in a handler group carry
the same source trigger, source causality, and PoI participation/region.

Source storage causality and string PoI causality are distinct. Source region
zero is onchain and requires the profile-bound PoI region; a positive source
region is offchain and has no PoI region. When an operation has a typed
`EntityKey`, its integer storage region equals the source region. Graph Node
executes each offchain trigger against a fresh `EmptyStore`, so offchain
materialization is isolated by handler group and cannot inherit state from an
earlier offchain trigger or the onchain entity cache.

Set and Remove PoI events carry `STORE_DISPOSITION_COMMITTED` when their
handler cache changes survive, or `STORE_DISPOSITION_DISCARDED` when a
deterministic handler failure rolls them back. Under fatal policy, otherwise
successful handler effects in an error-containing block use
`STORE_DISPOSITION_BLOCK_DISCARDED`: they were visible to later handlers but
Graph Node drops every non-PoI modification at the final transaction. Under
non-fatal policy those same effects remain committed. Every handler-discarded
event requires a DeterministicError that terminates the same handler group. Its
`redacted_events` is the count of all preceding Set/Remove PoI events since
that group's `start_handler`—not merely the discarded events. The error's
`handler_order` identifies the failed hosted mapping; later hosted mappings in
the group may have completed before Graph Node appends the error, so that value
need not equal the last effect's handler order. All effects from the failed
handler are discarded; the block policy determines the fate of every otherwise
successful effect.

`DeterministicError` is the ordered PoI/rollback record: it carries the redacted
event count while the surrounding operation identifies the failed hosted
mapping. It does not claim to carry the complete persisted `SubgraphError`
record, notably the formatted message and handler name. A deployment profile
whose certified range contains deterministic indexing errors must supply and
verify that database/status metadata separately in #5/#6; absence of that
evidence is a physical-parity refusal.

An absent Set `materialized` boundary or absent Remove key means the host call
emitted its PoI event and then trapped. It must be the last Set/Remove call in
that failed handler. Offchain deterministic errors are promoted to
non-deterministic block failures by Graph Node and cannot appear in an
applicable BlockChanges frame.

Graph Node retains the failed handler's PoI events, clears its entity-cache
updates, and then appends `DeterministicError { redacted_events }`:

- [trigger processing and deterministic-error emission](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/core/src/subgraph/trigger_processor.rs#L24-L78)
- [handler rollback](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/runtime/wasm/src/module/instance.rs#L164-L244)
- [PoI event variants](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/components/subgraph/proof_of_indexing/event.rs#L9-L58)

## Set and Remove payloads

A Set retains four different facts:

1. the typed storage key and integer storage causality region;
2. the matching GraphQL/storage typename and canonical typed ID string hashed
   for PoI;
3. `written_fields`, the schema-filtered Entity after auto-ID and timeseries
   timestamp injection but before partial-update merging; and
4. the complete schema-level EntityCache/get-visible `materialized` state after
   this individual `EntityCache::set` succeeds.

`written_fields` is not the raw AssemblyScript object. Graph Node injects and
checks the ID, injects a timeseries timestamp, filters non-schema fields,
constructs the Entity, hashes it for PoI, and only then passes it to the entity
cache. [The v0.44 host export preserves that exact
order.](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/runtime/wasm/src/host_exports.rs#L240-L340)

Graph Node emits the Set PoI event before `EntityCache::set`; write-capacity or
merged-entity validation can then fail deterministically. `materialized` is
therefore absent only on a discarded Set for which no successful save boundary
exists. A committed Set must have it. `failure_stage` then records whether the
failure happened before any cache side effect or after write-capacity decrement
and VID-sequence consumption, because handler rollback does not restore those
block-global counters. A Set with `materialized` present has no failure stage.

When present, every non-Null written field has the same value in materialized
state. A written top-level Null removes that field when the fresh handler-local
`Update` is applied to an existing entity, but EntityCache retains it when the
entity was absent or a preceding Remove made that local operation an
`Overwrite`. At handler exit Graph Node raw-merges the handler operation into
the block's main operation. That accumulation can reintroduce Null into a main
`Overwrite` even when the just-observed handler boundary omitted it, so a later
handler can inherit the Null again. The validator replays this main plus
fresh-handler algebra rather than carrying one block-global Null mode. The
physical profile must separately prove the persistence/SQL normalization and
VID consequences.

A Remove retains the exact caller-supplied type and ID strings because Graph
Node hashes them before resolving the schema or parsing the typed key. A
discarded invalid Remove may consequently have no `EntityKey`; a committed
Remove must have one. When a key exists, the raw ID must parse to that typed
key. [Set and Remove differ at the host-export
boundary.](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/runtime/wasm/src/host_exports.rs#L324-L376)

The validator exactly replays materialized boundaries once an entity's state is
established in the frame by a Set or Remove, including per-handler rollback.
For a first-touch partial Set whose predecessor is outside the frame, local
validation can prove only the written-field projection and internal
consistency. The consumer must load the deployment-profile baseline, recompute
the complete boundary, and compare exact field names and values before trusting
the frame as Graph-Node-faithful.

Entity mutability is not trusted from this wire. Mutable `block_range` versus
immutable `block$`, VID assignment, columns, nullability, and table identity are
derived and revalidated from the deployment-pinned physical profile tracked by
issue #5.

## Graph values and canonical scalar encoding

The value union covers String, Int, Int8, Timestamp, BigDecimal, Bool, List,
Null, Bytes, and BigInt. Entity IDs cover String, Bytes, and Int8.

- String Set IDs use the string unchanged. Bytes Set IDs use lowercase `0x`
  hex. Int8 Set IDs use canonical decimal. Remove IDs retain their raw spelling
  but must parse to the typed key when one exists.
- BigInt and BigDecimal coefficients use minimal two's-complement signed
  big-endian bytes. Empty is the sole zero representation; `[00]`, redundant
  positive sign extension, and redundant negative sign extension are refused.
- BigInt uses Graph Node's `bits + 1 <= 435,412` limit.
- BigDecimal is the normalized `(coefficient, scale)` tuple where
  `value = coefficient * 10^-scale`. Zero is `(empty, 0)`, nonzero
  coefficients have at most 34 decimal digits and no base-10 trailing zero,
  and scale is `-6144..=6143` (Graph exponent `-6143..=6144`).
- Timestamp validation reproduces Graph Node v0.44.0/Chrono 0.4.44's
  `from_microseconds_since_epoch` domain exactly, including its rejection of
  negative fractional-second microsecond values.
- In `written_fields`, absence means unchanged and explicit top-level Null means
  remove/unset. In get-visible `materialized`, that Null is absent for an
  update against an existing entity but retained for an absent/Overwrite path;
  a later partial Set can inherit it. Nested List Null is always a valid Graph
  value. The persistence profile must certify its final SQL normalization.
- List nesting is bounded at 32 levels so every accepted value remains below
  prost 0.13's fixed protobuf decode-recursion limit and round-trips.

Source contracts:

- [typed ID parse/display](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/data/store/id.rs#L32-L218)
- [Bytes parse/display](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/data/store/scalar/bytes.rs#L16-L52)
- [BigInt limit](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/data/store/scalar/bigint.rs#L36-L52)
- [BigDecimal normalization](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/data/store/scalar/bigdecimal.rs#L20-L106)
- [BigDecimal host range](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/runtime/wasm/src/to_from/external.rs#L89-L132)
- [Timestamp domain](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/data/store/scalar/timestamp.rs#L28-L76)
- [Null removal during materialization](https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/data/store/mod.rs#L1013-L1055)

## Canonical wire and regression fixture

Fields and triggered regions are strictly sorted where the contract declares
canonical sets. Operations remain in execution order. `encode_*` validates
before encoding. `decode_*` validates against the full expected compatibility
profile derived from the exact descriptor bytes—descriptor ID, error policy,
and PoI region—re-encodes, and requires byte equality; this rejects unknown
fields, duplicate or reordered singular fields, nonminimal varints, explicit
protobuf defaults, and other alternate encodings of the same decoded message.
Normative canonical protobuf uses ascending field-tag order, one occurrence of
each singular field, minimal varints, and omission of implicit defaults; nested
messages obey the same rules.

The schema and checked-in prost bindings have pinned SHA-256 regressions. The
canonical [`golden.pb.hex`](../common/fixtures/block-changes-v1/golden.pb.hex)
fixture covers uncoalesced duplicate saves, a partial update, Null versus unset,
every Graph value kind, all three ID kinds, noncanonical raw Remove spelling,
committed/discarded effects, deterministic error redaction, separate storage
and PoI causality fields, and handler/source-trigger grouping. Separate
adversarial frames cover an empty-but-triggered region, offchain isolation, and
fatal block-wide discard. The fixture-only compatibility descriptor hashes the
checked-in synthetic GraphQL schema, protocol schema, binding bytes, and empty
initial state while binding the expected Base PoI region and non-fatal policy. Production
descriptors must instead bind the exact deployment schema, manifest, ABIs,
WASM, adapter/profile revisions, Graph Node version, and PoI mode. Run:

```sh
cargo test -p backfill-common --test block_changes_v1 --locked
cargo clippy -p backfill-common --all-targets --all-features --locked -- -D warnings
```

## Delivery boundary

This repository-only contract and fixture do not switch any family to the new
engine, reproduce the retained V4 q8 range, open PostgreSQL, or authorize a
Kubernetes/live write. The next M2 step is a shadow-only V4 adapter at the
existing post-reduction/pre-sink boundary. It must construct, validate,
canonical-encode/decode, and compare BlockChanges while forwarding the legacy
V4 output unchanged. Because an empty V4 `ReducerInputs` frame does not carry a
block number/hash, that adapter must also accept an explicit Clock/block-header
input rather than inventing block identity. Engine promotion remains gated by
the pinned V4 golden range and separately authorized disposable lifecycle
evidence.
