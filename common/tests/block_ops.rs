use backfill_common::{
    block_ops::{BlockOpsBuilder, RecordedOp},
    decode_canonical_block_changes, encode_canonical_block_changes,
    pb::pinax::graph::backfill::v1 as pb,
    BlockChangesCompatibility,
};

fn compatibility() -> BlockChangesCompatibility {
    BlockChangesCompatibility::from_descriptor(include_bytes!(
        "../fixtures/block-changes-v1/compatibility.json"
    ))
    .unwrap()
}

fn recorded(op: &pb::EntityOperation) -> RecordedOp<pb::EntityKey> {
    let region = op.poi_causality_region.clone().unwrap();
    match op.operation.as_ref().unwrap() {
        pb::entity_operation::Operation::Set(set) => RecordedOp::Set {
            native_key: set.key.clone().unwrap(),
            key: set.key.clone().unwrap(),
            poi_entity_type: set.poi_entity_type.clone(),
            poi_entity_id: set.poi_entity_id.clone(),
            written_fields: set.written_fields.clone(),
            source_causality_region: op.source_causality_region,
            poi_causality_region: region,
        },
        pb::entity_operation::Operation::Remove(remove) => RecordedOp::Remove {
            native_key: remove.key.clone(),
            key: remove.key.clone(),
            poi_entity_type: remove.poi_entity_type.clone(),
            poi_entity_id: remove.poi_entity_id.clone(),
            source_causality_region: op.source_causality_region,
            poi_causality_region: region,
        },
        _ => panic!("only store calls are recorded"),
    }
}

#[test]
fn rebuilding_published_golden_uses_exact_save_order_dispositions_and_redaction_counts() {
    let compatibility = compatibility();
    let compact: String = include_str!("../fixtures/block-changes-v1/golden.pb.hex")
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect();
    let bytes = hex::decode(compact).unwrap();
    let golden = decode_canonical_block_changes(&bytes, &compatibility).unwrap();
    let mut builder = BlockOpsBuilder::new();
    let mut i = 0;
    while i < golden.operations.len() {
        let first = &golden.operations[i];
        let mut records = Vec::new();
        while i < golden.operations.len() {
            let op = &golden.operations[i];
            if (op.handler_group_order, op.handler_order)
                != (first.handler_group_order, first.handler_order)
                || matches!(
                    op.operation,
                    Some(pb::entity_operation::Operation::DeterministicError(_))
                )
            {
                break;
            }
            records.push(recorded(op));
            i += 1;
        }
        builder
            .push_handler(
                first.handler_group_order,
                first.source_trigger_order,
                first.handler_order,
                records,
                |_| None,
            )
            .unwrap();
        if let Some(error) = golden.operations.get(i).filter(|op| {
            matches!(
                op.operation,
                Some(pb::entity_operation::Operation::DeterministicError(_))
            )
        }) {
            builder
                .push_deterministic_error(
                    error.handler_group_order,
                    error.source_trigger_order,
                    error.handler_order,
                    error.poi_causality_region.clone().unwrap(),
                )
                .unwrap();
            i += 1;
        }
    }
    let rebuilt = builder
        .finish(
            &compatibility,
            golden.block_number,
            golden.block_hash.clone(),
            golden.mapping_triggered,
            golden.triggered_poi_causality_regions.clone(),
            pb::DeterministicErrorPolicy::NonFatal,
        )
        .unwrap();
    assert_eq!(rebuilt, golden);
    assert_eq!(
        encode_canonical_block_changes(&rebuilt, &compatibility).unwrap(),
        bytes
    );
}

fn field(name: &str, kind: pb::graph_value::Kind) -> pb::EntityField {
    pb::EntityField {
        name: name.into(),
        value: Some(pb::GraphValue { kind: Some(kind) }),
    }
}
fn id() -> pb::EntityField {
    field("id", pb::graph_value::Kind::String("p".into()))
}
fn key() -> pb::EntityKey {
    pb::EntityKey {
        entity_type: "Pool".into(),
        id: Some(pb::EntityId {
            value: Some(pb::entity_id::Value::String("p".into())),
        }),
        storage_causality_region: 0,
    }
}
fn set(fields: Vec<pb::EntityField>) -> RecordedOp<u32> {
    RecordedOp::Set {
        native_key: 17,
        key: key(),
        poi_entity_type: "Pool".into(),
        poi_entity_id: "p".into(),
        written_fields: fields,
        source_causality_region: 0,
        poi_causality_region: "ethereum/base".into(),
    }
}
fn finish(
    builder: BlockOpsBuilder,
    compatibility: &BlockChangesCompatibility,
    policy: pb::DeterministicErrorPolicy,
) -> pb::BlockChanges {
    let frame = builder
        .finish(
            compatibility,
            42,
            vec![0xab; 32],
            true,
            vec!["ethereum/base".into()],
            policy,
        )
        .unwrap();
    encode_canonical_block_changes(&frame, compatibility).unwrap();
    frame
}
fn materialized(frame: &pb::BlockChanges, index: usize) -> &[pb::EntityField] {
    match frame.operations[index].operation.as_ref().unwrap() {
        pb::entity_operation::Operation::Set(set) => &set.materialized.as_ref().unwrap().fields,
        _ => panic!("set"),
    }
}

#[test]
fn repeated_saves_merge_against_one_handler_baseline_preserving_new_entity_nulls() {
    for existing in [false, true] {
        let mut builder = BlockOpsBuilder::new();
        let mut reads = 0;
        let nulled = vec![
            id(),
            field("nullable", pb::graph_value::Kind::Null(pb::NullValue {})),
        ];
        builder
            .push_handler(
                0,
                0,
                0,
                vec![
                    set(vec![
                        id(),
                        field("nullable", pb::graph_value::Kind::String("first".into())),
                    ]),
                    set(nulled.clone()),
                ],
                |native_key| {
                    assert_eq!(*native_key, 17);
                    reads += 1;
                    existing.then(|| vec![id()])
                },
            )
            .unwrap();
        assert_eq!(reads, 1);
        let frame = finish(
            builder,
            &compatibility(),
            pb::DeterministicErrorPolicy::NonFatal,
        );
        assert_eq!(
            materialized(&frame, 1),
            if existing { vec![id()] } else { nulled }
        );
        assert_eq!(frame.operations.len(), 2);
    }
}

#[test]
fn remove_recreate_discards_baseline_but_preserves_explicit_null_in_handler_view() {
    let mut builder = BlockOpsBuilder::new();
    let fields = vec![
        id(),
        field("nullable", pb::graph_value::Kind::Null(pb::NullValue {})),
    ];
    builder
        .push_handler(
            0,
            0,
            0,
            vec![
                RecordedOp::Remove {
                    native_key: Some(17),
                    key: Some(key()),
                    poi_entity_type: "Pool".into(),
                    poi_entity_id: "p".into(),
                    source_causality_region: 0,
                    poi_causality_region: "ethereum/base".into(),
                },
                set(fields.clone()),
            ],
            |_| Some(vec![id(), field("old", pb::graph_value::Kind::Int(1))]),
        )
        .unwrap();
    let frame = finish(
        builder,
        &compatibility(),
        pb::DeterministicErrorPolicy::NonFatal,
    );
    assert_eq!(materialized(&frame, 1), fields);
}

#[test]
fn errors_redact_the_whole_group_but_discard_only_the_failed_handler_unless_fatal() {
    for policy in [
        pb::DeterministicErrorPolicy::NonFatal,
        pb::DeterministicErrorPolicy::Fatal,
    ] {
        let mut descriptor: serde_json::Value = serde_json::from_slice(include_bytes!(
            "../fixtures/block-changes-v1/compatibility.json"
        ))
        .unwrap();
        descriptor["deterministic_error_policy"] =
            serde_json::json!(if policy == pb::DeterministicErrorPolicy::Fatal {
                "fatal"
            } else {
                "non_fatal"
            });
        let compatibility =
            BlockChangesCompatibility::from_descriptor(&serde_json::to_vec(&descriptor).unwrap())
                .unwrap();
        let mut builder = BlockOpsBuilder::new();
        builder
            .push_handler(0, 9, 0, vec![set(vec![id()])], |_| None)
            .unwrap();
        builder
            .push_handler(0, 9, 1, vec![set(vec![id()])], |_| Some(vec![id()]))
            .unwrap();
        builder
            .push_deterministic_error(0, 9, 1, "ethereum/base".into())
            .unwrap();
        assert!(builder
            .push_deterministic_error(0, 9, 1, "ethereum/base".into())
            .is_err());
        // A dynamic-source replay wave can return to a lower source trigger.
        builder
            .push_handler(1, 2, 0, vec![set(vec![id()])], |_| Some(vec![id()]))
            .unwrap();
        let frame = finish(builder, &compatibility, policy);
        let expected = if policy == pb::DeterministicErrorPolicy::Fatal {
            pb::StoreDisposition::BlockDiscarded
        } else {
            pb::StoreDisposition::Committed
        } as i32;
        for (index, disposition) in [
            (0, expected),
            (1, pb::StoreDisposition::Discarded as i32),
            (3, expected),
        ] {
            match frame.operations[index].operation.as_ref().unwrap() {
                pb::entity_operation::Operation::Set(set) => {
                    assert_eq!(set.store_disposition, disposition)
                }
                _ => unreachable!(),
            }
        }
        assert_eq!(
            frame.operations[2].operation,
            Some(pb::entity_operation::Operation::DeterministicError(
                pb::DeterministicError { redacted_events: 2 }
            ))
        );
    }
}
