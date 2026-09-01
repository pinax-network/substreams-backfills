# BlockChanges v1 golden fixture

`compatibility.json` is the exact fixture-only producer descriptor. Its file
bytes are SHA-256 hashed into the frame's `compatibility_id`; it is not a
deployment compatibility profile. It binds the exact synthetic
`schema.graphql`, BlockChanges protobuf, checked-in prost binding, pinned Graph
Node/Chrono behavior, empty `initial-state.json`, adapter name, non-fatal error
policy, PoI mode, network, and expected deployment PoI region.
`BlockChangesCompatibility::from_descriptor` derives the digest and profile
from these exact bytes; callers cannot supply an unrelated policy or region for
the same ID.

`golden.pb.hex` is the canonical protobuf encoding exercised by
`common/tests/block_changes_v1.rs`. It deliberately retains two saves to the
same String-ID entity, a partial update, explicit written Null versus absent
predecessor state with retained get-visible Null, every Graph value kind, Bytes
and Int8 IDs, committed and
discarded operations, an invalid pre-key Remove PoI event, deterministic-error
redaction, handler/source-trigger grouping, separate storage/PoI causality
fields, and the sole source-faithful `ethereum/base` onchain region. Adversarial
tests beside the fixture additionally cover a separate empty-but-triggered
frame, fresh-`EmptyStore` offchain isolation, fatal/non-fatal policy and
block-wide discard, profile-region mismatch, Set failure-stage side effects,
four-handler Null removal/reintroduction, scalar endpoints, and
dynamic-data-source source-trigger replay.

The fixture is a protocol regression, not V4 q8 evidence and not permission to
write to a live Graph Node deployment.
