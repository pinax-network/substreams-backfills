use backfill_common::pb::pinax::graph::backfill::v1::{
    entity_id, entity_operation, graph_value, BigDecimalValue, BigIntValue, BlockChanges,
    DeterministicError, DeterministicErrorPolicy, EntityField, EntityFields, EntityId, EntityKey,
    EntityOperation, GraphValue, ListValue, NullValue, RemoveEntity, SetEntity, SetFailureStage,
    StoreDisposition,
};
use backfill_common::{
    decode_canonical_block_changes, encode_canonical_block_changes, validate_block_changes,
    BlockChangesCompatibility, CompatibilityDescriptorError, ValidationError,
    BLOCK_CHANGES_V1_CONTRACT,
};
use num_bigint::BigInt;
use prost::Message;
use sha2::{Digest, Sha256};
use std::sync::LazyLock;
use substreams_entity_change::pb::entity::{entity_change, EntityChange, EntityChanges};

static COMPATIBILITY_ID: LazyLock<BlockChangesCompatibility> = LazyLock::new(|| {
    BlockChangesCompatibility::from_descriptor(include_bytes!(
        "../fixtures/block-changes-v1/compatibility.json"
    ))
    .expect("checked-in compatibility descriptor")
});
const DESCRIPTOR_SHA256: &str = "e64c176c43a2490a19f1d4996b2721c637050d16362816785c3e80892e699099";
const PROTO_SHA256: &str = "7f9888a44138d7917d2addf332e5f04cf7980c6d3f51fa10248f6ecbab07fdee";
const BINDINGS_SHA256: &str = "6cbb2a3b1dadb90c5898a69b3feeb886e3fc3ca31edc7716ed545892d5ce3f0e";
const SCHEMA_SHA256: &str = "54562538cbce53b2f8f04d6474c417e35cc30c1c793234500dbcb88d461e2592";
const INITIAL_STATE_SHA256: &str =
    "4d82de655dc63ffd7f9f58228ed1d0ecc131c9655355c1b263972740fb930e28";
const GOLDEN_SHA256: &str = "2cde005750368f5dfa3c4286afbb46bfa3daa23d5b59d6ffda7e9be65b7839ea";

fn test_compatibility(
    policy: &str,
    network: &str,
    expected_region: &str,
) -> Result<BlockChangesCompatibility, CompatibilityDescriptorError> {
    let descriptor = format!(
        "{{\"contract\":\"{BLOCK_CHANGES_V1_CONTRACT}\",\"descriptor_version\":1,\"deterministic_error_policy\":\"{policy}\",\"network\":\"{network}\",\"expected_poi_causality_region\":\"{expected_region}\"}}"
    );
    BlockChangesCompatibility::from_descriptor(descriptor.as_bytes())
}

fn graph_value(kind: graph_value::Kind) -> GraphValue {
    GraphValue { kind: Some(kind) }
}

fn field(name: &str, kind: graph_value::Kind) -> EntityField {
    EntityField {
        name: name.to_owned(),
        value: Some(graph_value(kind)),
    }
}

fn field_is_null_for_test(field: &EntityField) -> bool {
    matches!(
        field.value.as_ref().and_then(|value| value.kind.as_ref()),
        Some(graph_value::Kind::Null(_))
    )
}

fn string_key(entity_type: &str, id: &str, storage_region: i32) -> EntityKey {
    EntityKey {
        entity_type: entity_type.to_owned(),
        id: Some(EntityId {
            value: Some(entity_id::Value::String(id.to_owned())),
        }),
        storage_causality_region: storage_region,
    }
}

fn bytes_key(entity_type: &str, id: &[u8], storage_region: i32) -> EntityKey {
    EntityKey {
        entity_type: entity_type.to_owned(),
        id: Some(EntityId {
            value: Some(entity_id::Value::Bytes(id.to_vec())),
        }),
        storage_causality_region: storage_region,
    }
}

fn int8_key(entity_type: &str, id: i64, storage_region: i32) -> EntityKey {
    EntityKey {
        entity_type: entity_type.to_owned(),
        id: Some(EntityId {
            value: Some(entity_id::Value::Int8(id)),
        }),
        storage_causality_region: storage_region,
    }
}

fn operation(
    operation_index: u64,
    handler_group_order: u64,
    handler_order: u64,
    region: &str,
    operation: entity_operation::Operation,
) -> EntityOperation {
    EntityOperation {
        operation_index,
        handler_group_order,
        source_trigger_order: handler_group_order,
        poi_causality_region: Some(region.to_owned()),
        handler_order,
        source_causality_region: 0,
        operation: Some(operation),
    }
}

fn full_written_fields(int_value: i32) -> Vec<EntityField> {
    vec![
        field("active", graph_value::Kind::Bool(true)),
        field(
            "bigDecimal",
            graph_value::Kind::BigDecimal(BigDecimalValue {
                coefficient_signed_be: vec![0x01, 0x2d],
                scale: 2,
            }),
        ),
        field(
            "bigInt",
            graph_value::Kind::BigInt(BigIntValue {
                signed_be: vec![0x00, 0x80],
            }),
        ),
        field("bytes", graph_value::Kind::Bytes(vec![0xde, 0xad])),
        field("id", graph_value::Kind::String("pool-1".to_owned())),
        field("int", graph_value::Kind::Int(int_value)),
        field("int8", graph_value::Kind::Int8(9_223_372_036_854_775)),
        field(
            "list",
            graph_value::Kind::List(ListValue {
                values: vec![
                    graph_value(graph_value::Kind::String("nested".to_owned())),
                    graph_value(graph_value::Kind::Null(NullValue {})),
                    graph_value(graph_value::Kind::Bytes(vec![0x01, 0x02])),
                ],
            }),
        ),
        field("nullable", graph_value::Kind::Null(NullValue {})),
        field(
            "timestamp",
            graph_value::Kind::TimestampMicros(1_725_000_000_123_456),
        ),
    ]
}

fn full_materialized_fields(int_value: i32) -> Vec<EntityField> {
    full_written_fields(int_value)
}

fn golden_changes() -> BlockChanges {
    let ethereum = "ethereum/base";
    BlockChanges {
        contract: BLOCK_CHANGES_V1_CONTRACT.to_owned(),
        compatibility_id: COMPATIBILITY_ID.to_vec(),
        block_number: 42,
        block_hash: vec![0xab; 32],
        mapping_triggered: true,
        triggered_poi_causality_regions: vec![ethereum.to_owned()],
        operations: vec![
            operation(
                0,
                3,
                0,
                ethereum,
                entity_operation::Operation::Set(SetEntity {
                    key: Some(string_key("Pool", "pool-1", 0)),
                    poi_entity_type: "Pool".to_owned(),
                    poi_entity_id: "pool-1".to_owned(),
                    written_fields: full_written_fields(7),
                    materialized: Some(EntityFields {
                        fields: full_materialized_fields(7),
                    }),
                    store_disposition: StoreDisposition::Committed as i32,
                    failure_stage: SetFailureStage::Unspecified as i32,
                }),
            ),
            operation(
                1,
                3,
                0,
                ethereum,
                entity_operation::Operation::Set(SetEntity {
                    key: Some(string_key("Pool", "pool-1", 0)),
                    poi_entity_type: "Pool".to_owned(),
                    poi_entity_id: "pool-1".to_owned(),
                    written_fields: vec![
                        field("id", graph_value::Kind::String("pool-1".to_owned())),
                        field("int", graph_value::Kind::Int(8)),
                    ],
                    materialized: Some(EntityFields {
                        fields: full_materialized_fields(8),
                    }),
                    store_disposition: StoreDisposition::Committed as i32,
                    failure_stage: SetFailureStage::Unspecified as i32,
                }),
            ),
            operation(
                2,
                4,
                0,
                ethereum,
                entity_operation::Operation::Remove(RemoveEntity {
                    key: Some(string_key("Pool", "pool-1", 0)),
                    poi_entity_type: "Pool".to_owned(),
                    poi_entity_id: "pool-1".to_owned(),
                    store_disposition: StoreDisposition::Committed as i32,
                }),
            ),
            operation(
                3,
                5,
                0,
                ethereum,
                entity_operation::Operation::Set(SetEntity {
                    key: Some(bytes_key("BytesEntity", &[0x00, 0xff], 0)),
                    poi_entity_type: "BytesEntity".to_owned(),
                    poi_entity_id: "0x00ff".to_owned(),
                    written_fields: vec![field("id", graph_value::Kind::Bytes(vec![0x00, 0xff]))],
                    materialized: Some(EntityFields {
                        fields: vec![field("id", graph_value::Kind::Bytes(vec![0x00, 0xff]))],
                    }),
                    store_disposition: StoreDisposition::Committed as i32,
                    failure_stage: SetFailureStage::Unspecified as i32,
                }),
            ),
            operation(
                4,
                6,
                0,
                ethereum,
                entity_operation::Operation::Remove(RemoveEntity {
                    key: Some(bytes_key("BytesEntity", &[0x00, 0xff], 0)),
                    poi_entity_type: "BytesEntity".to_owned(),
                    poi_entity_id: "00FF".to_owned(),
                    store_disposition: StoreDisposition::Committed as i32,
                }),
            ),
            operation(
                5,
                7,
                1,
                ethereum,
                entity_operation::Operation::Set(SetEntity {
                    key: Some(int8_key("Counter", 7, 0)),
                    poi_entity_type: "Counter".to_owned(),
                    poi_entity_id: "7".to_owned(),
                    written_fields: vec![
                        field("id", graph_value::Kind::Int8(7)),
                        field("value", graph_value::Kind::Int(1)),
                    ],
                    materialized: Some(EntityFields {
                        fields: vec![
                            field("id", graph_value::Kind::Int8(7)),
                            field("value", graph_value::Kind::Int(1)),
                        ],
                    }),
                    store_disposition: StoreDisposition::Discarded as i32,
                    failure_stage: SetFailureStage::Unspecified as i32,
                }),
            ),
            operation(
                6,
                7,
                1,
                ethereum,
                entity_operation::Operation::DeterministicError(DeterministicError {
                    redacted_events: 1,
                }),
            ),
            operation(
                7,
                8,
                2,
                ethereum,
                entity_operation::Operation::Remove(RemoveEntity {
                    key: None,
                    poi_entity_type: String::new(),
                    poi_entity_id: String::new(),
                    store_disposition: StoreDisposition::Discarded as i32,
                }),
            ),
            operation(
                8,
                8,
                2,
                ethereum,
                entity_operation::Operation::DeterministicError(DeterministicError {
                    redacted_events: 1,
                }),
            ),
        ],
        deterministic_error_policy: DeterministicErrorPolicy::NonFatal as i32,
    }
}

fn set_mut(changes: &mut BlockChanges, index: usize) -> &mut SetEntity {
    match changes.operations[index].operation.as_mut().unwrap() {
        entity_operation::Operation::Set(set) => set,
        _ => panic!("operation {index} is not a set"),
    }
}

fn remove_mut(changes: &mut BlockChanges, index: usize) -> &mut RemoveEntity {
    match changes.operations[index].operation.as_mut().unwrap() {
        entity_operation::Operation::Remove(remove) => remove,
        _ => panic!("operation {index} is not a remove"),
    }
}

fn disposition_mut(operation: &mut EntityOperation) -> Option<&mut i32> {
    match operation.operation.as_mut().unwrap() {
        entity_operation::Operation::Set(set) => Some(&mut set.store_disposition),
        entity_operation::Operation::Remove(remove) => Some(&mut remove.store_disposition),
        entity_operation::Operation::DeterministicError(_) => None,
    }
}

fn reindex(changes: &mut BlockChanges) {
    for (index, operation) in changes.operations.iter_mut().enumerate() {
        operation.operation_index = index as u64;
    }
}

fn written_value_mut<'a>(set: &'a mut SetEntity, name: &str) -> &'a mut GraphValue {
    set.written_fields
        .iter_mut()
        .find(|field| field.name == name)
        .unwrap()
        .value
        .as_mut()
        .unwrap()
}

fn set_first_boundary_value(changes: &mut BlockChanges, name: &str, kind: graph_value::Kind) {
    written_value_mut(set_mut(changes, 0), name).kind = Some(kind.clone());
    set_mut(changes, 0)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .iter_mut()
        .find(|field| field.name == name)
        .unwrap()
        .value = Some(graph_value(kind));
    changes.operations.truncate(1);
}

fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn fixture_bytes() -> Vec<u8> {
    let compact: String = include_str!("../fixtures/block-changes-v1/golden.pb.hex")
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    if compact == "GENERATE" {
        panic!(
            "golden fixture bytes: {}",
            hex::encode(golden_changes().encode_to_vec())
        );
    }
    hex::decode(compact).unwrap()
}

#[test]
fn compatibility_descriptor_binds_fixture_artifacts() {
    let descriptor = include_bytes!("../fixtures/block-changes-v1/compatibility.json");
    assert_eq!(sha256_hex(descriptor), DESCRIPTOR_SHA256);
    assert_eq!(hex::encode(COMPATIBILITY_ID.id()), DESCRIPTOR_SHA256);
    assert_eq!(
        sha256_hex(include_bytes!(
            "../fixtures/block-changes-v1/schema.graphql"
        )),
        SCHEMA_SHA256
    );
    assert_eq!(
        sha256_hex(include_bytes!(
            "../fixtures/block-changes-v1/initial-state.json"
        )),
        INITIAL_STATE_SHA256
    );

    let descriptor = std::str::from_utf8(descriptor).unwrap();
    for digest in [
        PROTO_SHA256,
        BINDINGS_SHA256,
        SCHEMA_SHA256,
        INITIAL_STATE_SHA256,
    ] {
        assert!(descriptor.contains(digest));
    }
    assert!(descriptor.contains("\"deterministic_error_policy\": \"non_fatal\""));
    assert!(descriptor.contains("\"expected_poi_causality_region\": \"ethereum/base\""));
}

#[test]
fn checked_in_binding_uses_the_proto_field_tags() {
    let operation = EntityOperation {
        operation_index: 1,
        handler_group_order: 2,
        source_trigger_order: 3,
        poi_causality_region: Some("r".to_owned()),
        handler_order: 4,
        source_causality_region: 5,
        operation: Some(entity_operation::Operation::DeterministicError(
            DeterministicError { redacted_events: 6 },
        )),
    };
    assert_eq!(
        operation.encode_to_vec(),
        [
            0x08, 0x01, 0x10, 0x02, 0x18, 0x03, 0x22, 0x01, b'r', 0x28, 0x04, 0x30, 0x0a, 0x4a,
            0x02, 0x08, 0x06,
        ]
    );

    let set = SetEntity {
        key: None,
        poi_entity_type: String::new(),
        poi_entity_id: String::new(),
        written_fields: Vec::new(),
        materialized: None,
        store_disposition: StoreDisposition::Unspecified as i32,
        failure_stage: SetFailureStage::AfterCapacityAndVid as i32,
    };
    assert_eq!(set.encode_to_vec(), [0x38, 0x02]);
}

#[test]
fn schema_bindings_and_golden_wire_are_locked() {
    assert_eq!(
        sha256_hex(include_bytes!("../proto/block_changes.proto")),
        PROTO_SHA256
    );
    assert_eq!(
        sha256_hex(include_bytes!("../src/pb/pinax.graph.backfill.v1.rs")),
        BINDINGS_SHA256
    );

    let changes = golden_changes();
    let encoded = encode_canonical_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
    assert_eq!(encoded, fixture_bytes());
    assert_eq!(sha256_hex(&encoded), GOLDEN_SHA256);
    let decoded = decode_canonical_block_changes(&encoded, &COMPATIBILITY_ID).unwrap();
    assert_eq!(decoded.encode_to_vec(), encoded);
}

#[test]
fn golden_preserves_uncoalesced_saves_nulls_values_and_typed_ids() {
    let changes = golden_changes();
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
    assert_eq!(changes.operations.len(), 9);

    let first = match changes.operations[0].operation.as_ref().unwrap() {
        entity_operation::Operation::Set(set) => set,
        _ => unreachable!(),
    };
    let second = match changes.operations[1].operation.as_ref().unwrap() {
        entity_operation::Operation::Set(set) => set,
        _ => unreachable!(),
    };
    assert_eq!(first.poi_entity_id, second.poi_entity_id);
    assert_eq!(first.written_fields.len(), 10);
    assert_eq!(second.written_fields.len(), 2);
    assert!(first.written_fields.iter().any(|field| {
        field.name == "nullable"
            && matches!(
                field.value.as_ref().and_then(|value| value.kind.as_ref()),
                Some(graph_value::Kind::Null(_))
            )
    }));
    assert!(first
        .materialized
        .as_ref()
        .unwrap()
        .fields
        .iter()
        .any(|field| field.name == "nullable" && field_is_null_for_test(field)));
    assert_eq!(changes.triggered_poi_causality_regions, ["ethereum/base"]);

    let bytes_remove = match changes.operations[4].operation.as_ref().unwrap() {
        entity_operation::Operation::Remove(remove) => remove,
        _ => unreachable!(),
    };
    assert_eq!(bytes_remove.poi_entity_id, "00FF");
    let int8_set = match changes.operations[5].operation.as_ref().unwrap() {
        entity_operation::Operation::Set(set) => set,
        _ => unreachable!(),
    };
    assert_eq!(int8_set.poi_entity_id, "7");
}

#[test]
fn accepts_triggered_empty_and_untriggered_empty_blocks() {
    let mut changes = golden_changes();
    changes.operations.clear();
    changes.triggered_poi_causality_regions = vec!["ethereum/base".to_owned()];
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    changes.mapping_triggered = false;
    changes.triggered_poi_causality_regions.clear();
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    changes.mapping_triggered = true;
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
}

#[test]
fn accepts_offchain_store_effects_without_inventing_poi() {
    let mut changes = golden_changes();
    changes.triggered_poi_causality_regions.clear();
    changes.operations = vec![operation(
        0,
        0,
        0,
        "placeholder",
        entity_operation::Operation::Set(SetEntity {
            key: Some(string_key("OffchainEntity", "file-1", 1)),
            poi_entity_type: "OffchainEntity".to_owned(),
            poi_entity_id: "file-1".to_owned(),
            written_fields: vec![field("id", graph_value::Kind::String("file-1".to_owned()))],
            materialized: Some(EntityFields {
                fields: vec![field("id", graph_value::Kind::String("file-1".to_owned()))],
            }),
            store_disposition: StoreDisposition::Committed as i32,
            failure_stage: SetFailureStage::Unspecified as i32,
        }),
    )];
    changes.operations[0].poi_causality_region = None;
    changes.operations[0].source_causality_region = 1;
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    let mut fresh = golden_changes();
    fresh.triggered_poi_causality_regions.clear();
    fresh.operations = vec![
        operation(
            0,
            0,
            0,
            "placeholder",
            entity_operation::Operation::Set(SetEntity {
                key: Some(string_key("Pool", "pool-1", 1)),
                poi_entity_type: "Pool".to_owned(),
                poi_entity_id: "pool-1".to_owned(),
                written_fields: vec![
                    field("active", graph_value::Kind::Bool(true)),
                    field("id", graph_value::Kind::String("pool-1".to_owned())),
                ],
                materialized: Some(EntityFields {
                    fields: vec![
                        field("active", graph_value::Kind::Bool(true)),
                        field("id", graph_value::Kind::String("pool-1".to_owned())),
                    ],
                }),
                store_disposition: StoreDisposition::Committed as i32,
                failure_stage: SetFailureStage::Unspecified as i32,
            }),
        ),
        operation(
            1,
            1,
            0,
            "placeholder",
            entity_operation::Operation::Set(SetEntity {
                key: Some(string_key("Pool", "pool-1", 1)),
                poi_entity_type: "Pool".to_owned(),
                poi_entity_id: "pool-1".to_owned(),
                written_fields: vec![field("id", graph_value::Kind::String("pool-1".to_owned()))],
                materialized: Some(EntityFields {
                    fields: vec![field("id", graph_value::Kind::String("pool-1".to_owned()))],
                }),
                store_disposition: StoreDisposition::Committed as i32,
                failure_stage: SetFailureStage::Unspecified as i32,
            }),
        ),
    ];
    for operation in &mut fresh.operations {
        operation.poi_causality_region = None;
        operation.source_causality_region = 1;
    }
    validate_block_changes(&fresh, &COMPATIBILITY_ID).unwrap();

    set_mut(&mut fresh, 1)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .insert(0, field("active", graph_value::Kind::Bool(true)));
    assert!(matches!(
        validate_block_changes(&fresh, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedHistoryMismatch { operation_index: 1 })
    ));

    let mut invalid = changes.clone();
    set_mut(&mut invalid, 0)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .push(field(
            "zz_ghost",
            graph_value::Kind::String("not-in-empty-store".to_owned()),
        ));
    assert!(matches!(
        validate_block_changes(&invalid, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedHistoryMismatch { operation_index: 0 })
    ));

    let mut invalid = changes.clone();
    invalid.operations[0].source_causality_region = 0;
    assert!(matches!(
        validate_block_changes(&invalid, &COMPATIBILITY_ID),
        Err(ValidationError::PoiParticipationMismatch { .. })
    ));

    let mut invalid = changes.clone();
    invalid.operations[0].poi_causality_region = Some("ethereum/base".to_owned());
    assert!(matches!(
        validate_block_changes(&invalid, &COMPATIBILITY_ID),
        Err(ValidationError::PoiParticipationMismatch { .. })
    ));

    let mut failed = changes;
    failed.operations = vec![
        EntityOperation {
            operation_index: 0,
            handler_group_order: 1,
            source_trigger_order: 1,
            poi_causality_region: None,
            handler_order: 2,
            source_causality_region: 1,
            operation: Some(entity_operation::Operation::Remove(RemoveEntity {
                key: None,
                poi_entity_type: String::new(),
                poi_entity_id: String::new(),
                store_disposition: StoreDisposition::Discarded as i32,
            })),
        },
        EntityOperation {
            operation_index: 1,
            handler_group_order: 1,
            source_trigger_order: 1,
            poi_causality_region: None,
            handler_order: 2,
            source_causality_region: 1,
            operation: Some(entity_operation::Operation::DeterministicError(
                DeterministicError { redacted_events: 0 },
            )),
        },
    ];
    assert!(matches!(
        validate_block_changes(&failed, &COMPATIBILITY_ID),
        Err(ValidationError::OffchainDeterministicError { operation_index: 1 })
    ));
}

#[test]
fn rejects_contract_and_compatibility_drift() {
    let mut changes = golden_changes();
    changes.contract.push_str("-drift");
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::Contract)
    ));

    let changes = golden_changes();
    let wrong_id = test_compatibility("non_fatal", "base", "ethereum/base").unwrap();
    assert!(matches!(
        validate_block_changes(&changes, &wrong_id),
        Err(ValidationError::CompatibilityIdMismatch)
    ));

    let wrong_policy = test_compatibility("fatal", "base", "ethereum/base").unwrap();
    let mut changes = golden_changes();
    changes.compatibility_id = wrong_policy.to_vec();
    assert!(matches!(
        validate_block_changes(&changes, &wrong_policy),
        Err(ValidationError::DeterministicErrorPolicyMismatch)
    ));

    let mut changes = golden_changes();
    changes.compatibility_id.pop();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::CompatibilityIdLength { actual: 31 })
    ));

    let mut changes = golden_changes();
    changes.compatibility_id = vec![0; 32];
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::ZeroCompatibilityId)
    ));

    let mut changes = golden_changes();
    changes.deterministic_error_policy = DeterministicErrorPolicy::Unspecified as i32;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::UnknownDeterministicErrorPolicy { actual: 0 })
    ));

    assert!(matches!(
        test_compatibility("non_fatal", "base", ""),
        Err(CompatibilityDescriptorError::ExpectedPoiCausalityRegion)
    ));

    assert!(matches!(
        test_compatibility("non_fatal", "base", "ethereum/mainnet"),
        Err(CompatibilityDescriptorError::PoiCausalityRegionNetworkMismatch)
    ));

    let wrong_region = test_compatibility("non_fatal", "mainnet", "ethereum/mainnet").unwrap();
    let mut changes = golden_changes();
    changes.compatibility_id = wrong_region.to_vec();
    assert!(matches!(
        validate_block_changes(&changes, &wrong_region),
        Err(ValidationError::PoiCausalityRegionCompatibility)
    ));

    assert!(matches!(
        test_compatibility("sometimes", "base", "ethereum/base"),
        Err(CompatibilityDescriptorError::DeterministicErrorPolicy)
    ));
}

#[test]
fn rejects_incoherent_block_and_operation_ordering() {
    let mut changes = golden_changes();
    changes.block_number = i32::MAX as u64;
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    let mut changes = golden_changes();
    changes.block_number = i32::MAX as u64 + 1;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::BlockNumberOutOfRange { .. })
    ));

    let mut changes = golden_changes();
    changes.block_hash.pop();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::BlockHashLength { actual: 31 })
    ));

    let mut changes = golden_changes();
    changes.block_hash.push(0xab);
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::BlockHashLength { actual: 33 })
    ));

    let mut changes = golden_changes();
    changes.mapping_triggered = false;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MappingTriggerMismatch)
    ));

    let mut changes = golden_changes();
    changes.triggered_poi_causality_regions[0].clear();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::EmptyTriggeredPoiCausalityRegion { .. })
    ));

    let mut changes = golden_changes();
    changes.triggered_poi_causality_regions =
        vec!["file/ipfs".to_owned(), "ethereum/base".to_owned()];
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::TriggeredPoiCausalityRegionOrder { .. })
    ));

    let mut changes = golden_changes();
    changes.triggered_poi_causality_regions =
        vec!["ethereum/base".to_owned(), "ethereum/base".to_owned()];
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::TriggeredPoiCausalityRegionOrder { .. })
    ));

    let mut changes = golden_changes();
    changes.triggered_poi_causality_regions =
        vec!["ethereum/base".to_owned(), "ethereum/mainnet".to_owned()];
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::PoiCausalityRegionCompatibility)
    ));

    let mut changes = golden_changes();
    changes.operations[0].operation_index = 9;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::OperationIndex {
            expected: 0,
            actual: 9
        })
    ));

    let mut changes = golden_changes();
    changes.operations[1].handler_group_order = 2;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::HandlerGroupOrder { .. })
    ));

    let mut changes = golden_changes();
    changes.operations[0].handler_order = 1;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::HandlerOrder { .. })
    ));

    let mut changes = golden_changes();
    changes.operations[0].poi_causality_region = Some("ethereum/mainnet".to_owned());
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::OperationRegionNotTriggered { .. })
    ));

    let mut changes = golden_changes();
    changes.operations[0].operation = None;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MissingOperation { .. })
    ));
}

#[test]
fn separates_handler_groups_from_reprocessed_source_triggers() {
    let mut changes = golden_changes();
    for operation in &mut changes.operations {
        operation.source_trigger_order = match operation.handler_group_order {
            3 => 10,
            4 => 11,
            5 => 2,
            6 => 3,
            7 => 2,
            8 => 2,
            _ => unreachable!(),
        };
    }
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    let mut invalid = changes.clone();
    invalid.operations[1].source_trigger_order = 9;
    assert!(matches!(
        validate_block_changes(&invalid, &COMPATIBILITY_ID),
        Err(ValidationError::HandlerGroupSourceTriggerMismatch { operation_index: 1 })
    ));

    let mut invalid = changes;
    invalid.operations[1].poi_causality_region = None;
    invalid.operations[1].source_causality_region = 1;
    assert!(matches!(
        validate_block_changes(&invalid, &COMPATIBILITY_ID),
        Err(ValidationError::HandlerGroupPoiRegionMismatch { operation_index: 1 })
    ));
}

#[test]
fn rejects_invalid_disposition_and_deterministic_error_sequences() {
    let mut changes = golden_changes();
    set_mut(&mut changes, 0).store_disposition = 0;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::UnknownStoreDisposition { actual: 0, .. })
    ));

    let mut changes = golden_changes();
    if let entity_operation::Operation::DeterministicError(error) =
        changes.operations[6].operation.as_mut().unwrap()
    {
        error.redacted_events = 2;
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::DeterministicErrorRedaction { .. })
    ));

    let mut changes = golden_changes();
    changes.operations.truncate(8);
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::DiscardedWithoutDeterministicError { operation_index: 7 })
    ));

    let mut changes = golden_changes();
    changes.operations[7].handler_group_order = 7;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::OperationAfterDeterministicError { operation_index: 7 })
    ));

    let mut changes = golden_changes();
    changes.operations[5].handler_order = 0;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::HandlerDispositionMismatch { operation_index: 5 })
    ));
}

#[test]
fn applies_manifest_fatal_policy_to_every_successful_handler_effect() {
    let fatal_compatibility = test_compatibility("fatal", "base", "ethereum/base").unwrap();
    let mut changes = golden_changes();
    changes.compatibility_id = fatal_compatibility.to_vec();
    changes.deterministic_error_policy = DeterministicErrorPolicy::Fatal as i32;
    for operation in &mut changes.operations {
        if let Some(disposition) = disposition_mut(operation) {
            if *disposition == StoreDisposition::Committed as i32 {
                *disposition = StoreDisposition::BlockDiscarded as i32;
            }
        }
    }
    validate_block_changes(&changes, &fatal_compatibility).unwrap();

    let mut invalid = changes.clone();
    let set = set_mut(&mut invalid, 0);
    set.materialized = None;
    set.failure_stage = SetFailureStage::BeforeCacheSideEffects as i32;
    assert!(matches!(
        validate_block_changes(&invalid, &fatal_compatibility),
        Err(ValidationError::CommittedSetMissingMaterialized { operation_index: 0 })
    ));

    let mut invalid = changes.clone();
    remove_mut(&mut invalid, 2).key = None;
    assert!(matches!(
        validate_block_changes(&invalid, &fatal_compatibility),
        Err(ValidationError::CommittedRemoveMissingKey { operation_index: 2 })
    ));

    set_mut(&mut changes, 0).store_disposition = StoreDisposition::Committed as i32;
    assert!(matches!(
        validate_block_changes(&changes, &fatal_compatibility),
        Err(ValidationError::HandlerDispositionMismatch { operation_index: 0 })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).store_disposition = StoreDisposition::BlockDiscarded as i32;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::HandlerDispositionMismatch { operation_index: 0 })
    ));

    let mut changes = golden_changes();
    changes.compatibility_id = fatal_compatibility.to_vec();
    changes.deterministic_error_policy = DeterministicErrorPolicy::Fatal as i32;
    changes.operations.truncate(5);
    validate_block_changes(&changes, &fatal_compatibility).unwrap();
}

#[test]
fn redacted_count_includes_committed_and_discarded_handlers() {
    let mut changes = golden_changes();
    set_mut(&mut changes, 1).store_disposition = StoreDisposition::Discarded as i32;
    changes.operations[1].handler_order = 1;
    for (index, operation) in changes.operations.iter_mut().enumerate().skip(2) {
        operation.operation_index = index as u64 + 1;
    }
    changes.operations.insert(
        2,
        operation(
            2,
            3,
            1,
            "ethereum/base",
            entity_operation::Operation::DeterministicError(DeterministicError {
                redacted_events: 2,
            }),
        ),
    );
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    if let entity_operation::Operation::DeterministicError(error) =
        changes.operations[2].operation.as_mut().unwrap()
    {
        error.redacted_events = 1;
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::DeterministicErrorRedaction {
            expected: 2,
            actual: 1,
            ..
        })
    ));
}

#[test]
fn terminal_failed_host_calls_end_the_failed_handler() {
    let mut changes = golden_changes();
    let later = changes.operations[5].clone();
    let terminal = set_mut(&mut changes, 5);
    terminal.materialized = None;
    terminal.failure_stage = SetFailureStage::AfterCapacityAndVid as i32;
    changes.operations.insert(6, later);
    reindex(&mut changes);
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::OperationAfterTerminalHostFailure {
            operation_index: 6,
            terminal_operation_index: 5
        })
    ));

    let mut changes = golden_changes();
    let later = changes.operations[7].clone();
    changes.operations.insert(8, later);
    reindex(&mut changes);
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::OperationAfterTerminalHostFailure {
            operation_index: 8,
            terminal_operation_index: 7
        })
    ));
}

#[test]
fn enforces_set_and_remove_key_and_poi_semantics() {
    let mut changes = golden_changes();
    set_mut(&mut changes, 0).key = None;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MissingEntityKey { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).poi_entity_type = "Other".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::SetPoiEntityTypeMismatch { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).poi_entity_id = "POOL-1".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::SetPoiEntityIdMismatch { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 3).poi_entity_id = "00ff".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::SetPoiEntityIdMismatch { .. })
    ));

    let mut changes = golden_changes();
    remove_mut(&mut changes, 4).poi_entity_type = "Other".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::RemovePoiEntityTypeMismatch { .. })
    ));

    let mut changes = golden_changes();
    remove_mut(&mut changes, 4).poi_entity_id = "0X00FF".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::RemovePoiEntityIdMismatch { .. })
    ));

    let mut changes = golden_changes();
    remove_mut(&mut changes, 2).key = None;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::CommittedRemoveMissingKey { .. })
    ));
}

#[test]
fn enforces_typed_set_display_and_remove_parse_rules() {
    for raw in ["0x00ff", "00FF", "0x00FF"] {
        let mut changes = golden_changes();
        remove_mut(&mut changes, 4).poi_entity_id = raw.to_owned();
        validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
    }

    for raw in ["7", "+7", "007", "+007"] {
        let mut changes = golden_changes();
        let remove = remove_mut(&mut changes, 4);
        remove.key = Some(int8_key("Counter", 7, 0));
        remove.poi_entity_type = "Counter".to_owned();
        remove.poi_entity_id = raw.to_owned();
        validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
    }

    for raw in ["00ff", "0x00FF", "0X00ff"] {
        let mut changes = golden_changes();
        set_mut(&mut changes, 3).poi_entity_id = raw.to_owned();
        assert!(matches!(
            validate_block_changes(&changes, &COMPATIBILITY_ID),
            Err(ValidationError::SetPoiEntityIdMismatch { .. })
        ));
    }

    for raw in ["+7", "07", "+007"] {
        let mut changes = golden_changes();
        set_mut(&mut changes, 5).poi_entity_id = raw.to_owned();
        assert!(matches!(
            validate_block_changes(&changes, &COMPATIBILITY_ID),
            Err(ValidationError::SetPoiEntityIdMismatch { .. })
        ));
    }
}

#[test]
fn rejects_non_schema_names_reserved_vid_and_invalid_causality() {
    let mut changes = golden_changes();
    set_mut(&mut changes, 0).key.as_mut().unwrap().entity_type = "Bad-Type".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::InvalidGraphQlName { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).poi_entity_type = "Bad.Type".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::InvalidGraphQlName { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).written_fields[0].name = "bad-name".to_owned();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::InvalidGraphQlName { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0)
        .written_fields
        .push(field("vid", graph_value::Kind::Int8(42)));
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::ReservedField { .. })
    ));

    let mut changes = golden_changes();
    changes.operations[0].source_causality_region = -1;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::NegativeSourceCausalityRegion { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0)
        .key
        .as_mut()
        .unwrap()
        .storage_causality_region = -1;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::NegativeStorageCausalityRegion { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0)
        .key
        .as_mut()
        .unwrap()
        .storage_causality_region = 1;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::EntitySourceCausalityMismatch { .. })
    ));
}

#[test]
fn enforces_materialized_presence_fields_and_projection() {
    let mut changes = golden_changes();
    set_mut(&mut changes, 0).materialized = None;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::CommittedSetMissingMaterialized { .. })
    ));

    let mut changes = golden_changes();
    let set = set_mut(&mut changes, 5);
    set.materialized = None;
    set.failure_stage = SetFailureStage::BeforeCacheSideEffects as i32;
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    let mut changes = golden_changes();
    set_mut(&mut changes, 5).materialized = None;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::SetFailureStageMismatch { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 5).failure_stage = SetFailureStage::AfterCapacityAndVid as i32;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::SetFailureStageMismatch { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).written_fields[0].name.clear();
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::EmptyFieldName { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).written_fields.swap(0, 1);
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::FieldOrder { .. })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 0).written_fields[0].value = None;
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MissingFieldValue { .. })
    ));

    let mut changes = golden_changes();
    let set = set_mut(&mut changes, 0);
    set.materialized.as_mut().unwrap().fields[0].value =
        Some(graph_value(graph_value::Kind::Null(NullValue {})));
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedProjection { .. })
    ));

    let mut changes = golden_changes();
    let set = set_mut(&mut changes, 0);
    set.materialized.as_mut().unwrap().fields[0].value =
        Some(graph_value(graph_value::Kind::Bool(false)));
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedProjection { .. })
    ));

    let mut changes = golden_changes();
    let set = set_mut(&mut changes, 0);
    set.materialized
        .as_mut()
        .unwrap()
        .fields
        .retain(|field| field.name != "id");
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MissingIdField { .. })
    ));
}

#[test]
fn replays_known_in_frame_materialized_boundaries_exactly() {
    let mut changes = golden_changes();
    set_mut(&mut changes, 1)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .retain(|field| field.name != "active");
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedHistoryMismatch { operation_index: 1 })
    ));

    let mut changes = golden_changes();
    set_mut(&mut changes, 1)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .push(field(
            "zz_ghost",
            graph_value::Kind::String("not-in-predecessor".to_owned()),
        ));
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedHistoryMismatch { operation_index: 1 })
    ));
}

#[test]
fn replays_null_reset_and_reintroduction_across_handler_boundaries() {
    let ethereum = "ethereum/base";
    let mut changes = golden_changes();
    changes.operations = vec![
        operation(
            0,
            0,
            0,
            ethereum,
            entity_operation::Operation::Remove(RemoveEntity {
                key: Some(string_key("Pool", "pool-1", 0)),
                poi_entity_type: "Pool".to_owned(),
                poi_entity_id: "pool-1".to_owned(),
                store_disposition: StoreDisposition::Committed as i32,
            }),
        ),
        operation(
            1,
            1,
            0,
            ethereum,
            entity_operation::Operation::Set(SetEntity {
                key: Some(string_key("Pool", "pool-1", 0)),
                poi_entity_type: "Pool".to_owned(),
                poi_entity_id: "pool-1".to_owned(),
                written_fields: vec![
                    field("id", graph_value::Kind::String("pool-1".to_owned())),
                    field("nullable", graph_value::Kind::Null(NullValue {})),
                ],
                materialized: Some(EntityFields {
                    fields: vec![
                        field("id", graph_value::Kind::String("pool-1".to_owned())),
                        field("nullable", graph_value::Kind::Null(NullValue {})),
                    ],
                }),
                store_disposition: StoreDisposition::Committed as i32,
                failure_stage: SetFailureStage::Unspecified as i32,
            }),
        ),
        operation(
            2,
            2,
            0,
            ethereum,
            entity_operation::Operation::Set(SetEntity {
                key: Some(string_key("Pool", "pool-1", 0)),
                poi_entity_type: "Pool".to_owned(),
                poi_entity_id: "pool-1".to_owned(),
                written_fields: vec![
                    field("id", graph_value::Kind::String("pool-1".to_owned())),
                    field("nullable", graph_value::Kind::Null(NullValue {})),
                ],
                materialized: Some(EntityFields {
                    fields: vec![field("id", graph_value::Kind::String("pool-1".to_owned()))],
                }),
                store_disposition: StoreDisposition::Committed as i32,
                failure_stage: SetFailureStage::Unspecified as i32,
            }),
        ),
        operation(
            3,
            3,
            0,
            ethereum,
            entity_operation::Operation::Set(SetEntity {
                key: Some(string_key("Pool", "pool-1", 0)),
                poi_entity_type: "Pool".to_owned(),
                poi_entity_id: "pool-1".to_owned(),
                written_fields: vec![
                    field("id", graph_value::Kind::String("pool-1".to_owned())),
                    field("int", graph_value::Kind::Int(9)),
                ],
                materialized: Some(EntityFields {
                    fields: vec![
                        field("id", graph_value::Kind::String("pool-1".to_owned())),
                        field("int", graph_value::Kind::Int(9)),
                        field("nullable", graph_value::Kind::Null(NullValue {})),
                    ],
                }),
                store_disposition: StoreDisposition::Committed as i32,
                failure_stage: SetFailureStage::Unspecified as i32,
            }),
        ),
    ];
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
    let valid_operations = changes.operations.clone();

    set_mut(&mut changes, 1)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .retain(|field| field.name != "nullable");
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedHistoryMismatch { operation_index: 1 })
    ));

    let mut invalid = golden_changes();
    invalid.operations = valid_operations;
    set_mut(&mut invalid, 2)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .push(field("nullable", graph_value::Kind::Null(NullValue {})));
    assert!(matches!(
        validate_block_changes(&invalid, &COMPATIBILITY_ID),
        Err(ValidationError::MaterializedHistoryMismatch { operation_index: 2 })
    ));
}

#[test]
fn enforces_graph_integer_and_decimal_canonicalization() {
    let mut changes = golden_changes();
    if let Some(graph_value::Kind::BigInt(value)) =
        written_value_mut(set_mut(&mut changes, 0), "bigInt")
            .kind
            .as_mut()
    {
        value.signed_be = vec![0];
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::InvalidSignedBigEndian { .. })
    ));

    let mut changes = golden_changes();
    if let Some(graph_value::Kind::BigInt(value)) =
        written_value_mut(set_mut(&mut changes, 0), "bigInt")
            .kind
            .as_mut()
    {
        value.signed_be = vec![0, 1];
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::InvalidSignedBigEndian { .. })
    ));

    let mut changes = golden_changes();
    if let Some(graph_value::Kind::BigInt(value)) =
        written_value_mut(set_mut(&mut changes, 0), "bigInt")
            .kind
            .as_mut()
    {
        value.signed_be = vec![0x7f; 54_428];
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::BigIntTooLarge { .. })
    ));

    let mut changes = golden_changes();
    if let Some(graph_value::Kind::BigDecimal(value)) =
        written_value_mut(set_mut(&mut changes, 0), "bigDecimal")
            .kind
            .as_mut()
    {
        value.coefficient_signed_be.clear();
        value.scale = 1;
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::NonCanonicalZeroDecimal { .. })
    ));

    let mut changes = golden_changes();
    if let Some(graph_value::Kind::BigDecimal(value)) =
        written_value_mut(set_mut(&mut changes, 0), "bigDecimal")
            .kind
            .as_mut()
    {
        value.scale = 6_144;
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::DecimalScale { .. })
    ));

    let mut changes = golden_changes();
    if let Some(graph_value::Kind::BigDecimal(value)) =
        written_value_mut(set_mut(&mut changes, 0), "bigDecimal")
            .kind
            .as_mut()
    {
        value.coefficient_signed_be =
            BigInt::parse_bytes(b"11111111111111111111111111111111111", 10)
                .unwrap()
                .to_signed_bytes_be();
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::DecimalPrecision { .. })
    ));

    let mut changes = golden_changes();
    if let Some(graph_value::Kind::BigDecimal(value)) =
        written_value_mut(set_mut(&mut changes, 0), "bigDecimal")
            .kind
            .as_mut()
    {
        value.coefficient_signed_be = vec![10];
    }
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::NonNormalizedDecimal { .. })
    ));
}

#[test]
fn accepts_exact_bigint_and_decimal_boundaries() {
    let max_bigint = BigInt::from(1u8) << 435_410usize;
    let mut changes = golden_changes();
    set_first_boundary_value(
        &mut changes,
        "bigInt",
        graph_value::Kind::BigInt(BigIntValue {
            signed_be: max_bigint.to_signed_bytes_be(),
        }),
    );
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    let too_large = BigInt::from(1u8) << 435_411usize;
    let mut changes = golden_changes();
    set_first_boundary_value(
        &mut changes,
        "bigInt",
        graph_value::Kind::BigInt(BigIntValue {
            signed_be: too_large.to_signed_bytes_be(),
        }),
    );
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::BigIntTooLarge { .. })
    ));

    for scale in [-6_144, 6_143] {
        let mut changes = golden_changes();
        set_first_boundary_value(
            &mut changes,
            "bigDecimal",
            graph_value::Kind::BigDecimal(BigDecimalValue {
                coefficient_signed_be: vec![1],
                scale,
            }),
        );
        validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
    }

    for scale in [-6_145, 6_144] {
        let mut changes = golden_changes();
        set_first_boundary_value(
            &mut changes,
            "bigDecimal",
            graph_value::Kind::BigDecimal(BigDecimalValue {
                coefficient_signed_be: vec![1],
                scale,
            }),
        );
        assert!(matches!(
            validate_block_changes(&changes, &COMPATIBILITY_ID),
            Err(ValidationError::DecimalScale { .. })
        ));
    }

    let coefficient_34 = BigInt::parse_bytes(b"1111111111111111111111111111111111", 10).unwrap();
    let mut changes = golden_changes();
    set_first_boundary_value(
        &mut changes,
        "bigDecimal",
        graph_value::Kind::BigDecimal(BigDecimalValue {
            coefficient_signed_be: coefficient_34.to_signed_bytes_be(),
            scale: 0,
        }),
    );
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    let coefficient_35 = BigInt::parse_bytes(b"11111111111111111111111111111111111", 10).unwrap();
    let mut changes = golden_changes();
    set_first_boundary_value(
        &mut changes,
        "bigDecimal",
        graph_value::Kind::BigDecimal(BigDecimalValue {
            coefficient_signed_be: coefficient_35.to_signed_bytes_be(),
            scale: 0,
        }),
    );
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::DecimalPrecision { .. })
    ));

    let mut changes = golden_changes();
    set_first_boundary_value(
        &mut changes,
        "bigDecimal",
        graph_value::Kind::BigDecimal(BigDecimalValue {
            coefficient_signed_be: Vec::new(),
            scale: 0,
        }),
    );
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();

    for (coefficient_signed_be, scale) in [(vec![0], 0), (Vec::new(), 1)] {
        let mut changes = golden_changes();
        set_first_boundary_value(
            &mut changes,
            "bigDecimal",
            graph_value::Kind::BigDecimal(BigDecimalValue {
                coefficient_signed_be,
                scale,
            }),
        );
        assert!(validate_block_changes(&changes, &COMPATIBILITY_ID).is_err());
    }
}

#[test]
fn enforces_pinned_graph_timestamp_domain() {
    let mut changes = golden_changes();
    written_value_mut(set_mut(&mut changes, 0), "timestamp").kind =
        Some(graph_value::Kind::TimestampMicros(-1));
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::InvalidTimestamp { .. })
    ));

    let mut changes = golden_changes();
    written_value_mut(set_mut(&mut changes, 0), "timestamp").kind =
        Some(graph_value::Kind::TimestampMicros(i64::MAX));
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::InvalidTimestamp { .. })
    ));

    let mut changes = golden_changes();
    let value = graph_value(graph_value::Kind::TimestampMicros(-1_000_000));
    written_value_mut(set_mut(&mut changes, 0), "timestamp").kind = value.kind.clone();
    let set = set_mut(&mut changes, 0);
    set.materialized
        .as_mut()
        .unwrap()
        .fields
        .iter_mut()
        .find(|field| field.name == "timestamp")
        .unwrap()
        .value = Some(value);
    changes.operations.truncate(1);
    validate_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
}

#[test]
fn rejects_excessive_value_nesting() {
    let mut nested = graph_value(graph_value::Kind::Null(NullValue {}));
    for _ in 0..=32 {
        nested = graph_value(graph_value::Kind::List(ListValue {
            values: vec![nested],
        }));
    }
    let mut changes = golden_changes();
    set_mut(&mut changes, 0).written_fields.push(EntityField {
        name: "zz_nested".to_owned(),
        value: Some(nested),
    });
    assert!(matches!(
        validate_block_changes(&changes, &COMPATIBILITY_ID),
        Err(ValidationError::ValueNestingTooDeep { .. })
    ));
}

#[test]
fn maximum_value_nesting_round_trips_through_prost() {
    let mut nested = graph_value(graph_value::Kind::Null(NullValue {}));
    for _ in 0..32 {
        nested = graph_value(graph_value::Kind::List(ListValue {
            values: vec![nested],
        }));
    }
    let mut changes = golden_changes();
    set_mut(&mut changes, 0).written_fields.push(EntityField {
        name: "zz_nested".to_owned(),
        value: Some(nested.clone()),
    });
    set_mut(&mut changes, 0)
        .materialized
        .as_mut()
        .unwrap()
        .fields
        .push(EntityField {
            name: "zz_nested".to_owned(),
            value: Some(nested),
        });
    changes.operations.truncate(1);
    let encoded = encode_canonical_block_changes(&changes, &COMPATIBILITY_ID).unwrap();
    decode_canonical_block_changes(&encoded, &COMPATIBILITY_ID).unwrap();
}

#[test]
fn rejects_unknown_duplicate_nonminimal_default_and_reordered_wire_fields() {
    let canonical = encode_canonical_block_changes(&golden_changes(), &COMPATIBILITY_ID).unwrap();

    let mut unknown = canonical.clone();
    unknown.extend_from_slice(&[0xa0, 0x06, 0x01]);
    assert!(matches!(
        decode_canonical_block_changes(&unknown, &COMPATIBILITY_ID),
        Err(ValidationError::NonCanonicalEncoding)
    ));

    let mut explicit_default = canonical.clone();
    explicit_default.extend_from_slice(&[0x18, 0x00]);
    assert!(matches!(
        decode_canonical_block_changes(&explicit_default, &COMPATIBILITY_ID),
        Err(ValidationError::NonCanonicalEncoding)
    ));

    let mut duplicate = canonical.clone();
    duplicate.extend_from_slice(&[0x18, 0x2a]);
    assert!(matches!(
        decode_canonical_block_changes(&duplicate, &COMPATIBILITY_ID),
        Err(ValidationError::NonCanonicalEncoding)
    ));

    let block_number = canonical
        .windows(2)
        .position(|window| window == [0x18, 0x2a])
        .expect("golden block number field");
    let mut nonminimal_varint = canonical.clone();
    nonminimal_varint.splice(block_number + 1..block_number + 2, [0xaa, 0x00]);
    assert!(matches!(
        decode_canonical_block_changes(&nonminimal_varint, &COMPATIBILITY_ID),
        Err(ValidationError::NonCanonicalEncoding)
    ));

    assert_eq!(canonical[0], 0x0a);
    let contract_len = canonical[1] as usize;
    let first_end = 2 + contract_len;
    let mut reordered = canonical[first_end..].to_vec();
    reordered.extend_from_slice(&canonical[..first_end]);
    assert!(matches!(
        decode_canonical_block_changes(&reordered, &COMPATIBILITY_ID),
        Err(ValidationError::NonCanonicalEncoding)
    ));
}

#[test]
#[allow(deprecated)]
fn rejects_standard_or_coalesced_entity_changes_input() {
    let standard = EntityChanges {
        entity_changes: vec![EntityChange {
            entity: "Pool".to_owned(),
            id: "pool-1".to_owned(),
            ordinal: 0,
            operation: entity_change::Operation::Update as i32,
            fields: Vec::new(),
        }],
    }
    .encode_to_vec();
    assert!(decode_canonical_block_changes(&standard, &COMPATIBILITY_ID).is_err());
}
