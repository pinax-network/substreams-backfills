# BlockChanges descriptor v2

Descriptor v2 extends the `pinax.graph.backfill.block-changes/v1` frame contract
with typed capabilities. It does not change the raw-byte SHA-256 rule for the
frame compatibility ID. Descriptor v1 remains accepted with its previous
validation rules, golden bytes and IDs. `BlockChangesCompatibility::capabilities`
returns `None` for v1. A v1 consumer still refuses v2; engine adoption is a
separate change.

The additional required fields are `deployment`, `spec_version`, `start_block`,
`graph_node`, `storage_profile`, `data_sources`, `entity_retention`, and
`producer_contract`. The implementation is in `common/src/descriptor.rs`;
`common/tests/descriptor_v2.rs` is an executable example using synthetic pins.

The runtime is Graph Node 0.44.0 at commit
`77823b5a7adc4eac4abf03202c8dd7cb00dea31d`, with an explicit `fast` or `legacy`
PoI version. Entity types are sorted unique GraphQL names; their indexes are
stable u16 snapshot ordinals. Template names and manifest indexes are unique,
and templates are ordered by manifest index. Current template parameters use
`address20`. Templates require `in_band_v1` transport. This descriptor parser
declares the capability; the subsequent in-band wire implementation must still
validate each creation and its handler disposition.

The native producer identity pins the reducer repository/commit and extractor
SPKG SHA-256, module, module hash, output message and initial block. The initial
block equals the target start block. Pins are lowercase hex with exact lengths;
nested capability structures reject unknown fields and unsupported variants.
V2 also refuses duplicate JSON keys at every depth, including escaped spellings
of the same key, before validating the typed capabilities.
These checks do not replace verification of the pinned artifact bytes.

## Retention

All types default to persistent storage. An explicit policy may select:

- `persistent`: retain the entity and active version across blocks.
- `block_local`: the ID cannot be read or written by a later block. A
  `block_number_suffix` proof names the exact block; a
  `derived_from_transaction` proof requires independent semantic evidence and
  loader overlap checks, since the ID alone cannot establish membership.
- `period_scoped`: retain the current maximum unsigned decimal period, parsed
  from the whole ID or the suffix after the last separator. Engine monotonicity
  and loader overlap enforcement remain required; the parser does not evict
  anything itself.

Any non-persistent class requires checksum-pinned `store_get_inventory` and
`id_scheme_inventory` evidence references. The parser validates their shape;
release/certification must resolve and verify their contents. Undeclared entity
types, unknown classes and missing proof are refused.

`RetentionPolicy::canonical_bytes` sorts JSON object keys recursively and sorts
evidence by kind, emits compact UTF-8 JSON without a trailing newline, then
`sha256` hashes those bytes. Equivalent JSON whitespace, object-key order and
evidence ordering do not change the retention identity. Policy or evidence
changes do. The outer descriptor ID still binds its exact original bytes.

The shared [snapshot and transport contracts](generic-state-snapshot.md) bind
state to the descriptor and retention identities. No descriptor in this change
declares Aerodrome production readiness. Engine enforcement, mapping-host
in-band output, the reducer and loader must consume these contracts before the
lane can execute.
