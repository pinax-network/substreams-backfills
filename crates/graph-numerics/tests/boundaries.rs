use backfill_common::{pb::pinax::graph::backfill::v1 as pb, BlockChangesCompatibility};
use graph_numerics::{bigint, mapping, BigInt, GraphDecimal, NumericError};

fn seal(value: pb::BigDecimalValue) -> Result<Vec<u8>, backfill_common::ValidationError> {
    let descriptor = br#"{"contract":"pinax.graph.backfill.block-changes/v1","descriptor_version":1,"deterministic_error_policy":"non_fatal","network":"base","expected_poi_causality_region":"ethereum/base"}"#;
    let compatibility = BlockChangesCompatibility::from_descriptor(descriptor).unwrap();
    let fields = vec![
        pb::EntityField {
            name: "id".into(),
            value: Some(pb::GraphValue {
                kind: Some(pb::graph_value::Kind::String("t".into())),
            }),
        },
        pb::EntityField {
            name: "value".into(),
            value: Some(pb::GraphValue {
                kind: Some(pb::graph_value::Kind::BigDecimal(value)),
            }),
        },
    ];
    let changes = pb::BlockChanges {
        contract: backfill_common::BLOCK_CHANGES_V1_CONTRACT.into(),
        compatibility_id: compatibility.to_vec(),
        block_number: 1,
        block_hash: vec![0xab; 32],
        mapping_triggered: true,
        triggered_poi_causality_regions: vec!["ethereum/base".into()],
        operations: vec![pb::EntityOperation {
            operation_index: 0,
            handler_group_order: 0,
            source_trigger_order: 0,
            poi_causality_region: Some("ethereum/base".into()),
            handler_order: 0,
            source_causality_region: 0,
            operation: Some(pb::entity_operation::Operation::Set(pb::SetEntity {
                key: Some(pb::EntityKey {
                    entity_type: "Token".into(),
                    id: Some(pb::EntityId {
                        value: Some(pb::entity_id::Value::String("t".into())),
                    }),
                    storage_causality_region: 0,
                }),
                poi_entity_type: "Token".into(),
                poi_entity_id: "t".into(),
                written_fields: fields.clone(),
                materialized: Some(pb::EntityFields { fields }),
                store_disposition: pb::StoreDisposition::Committed as i32,
                failure_stage: pb::SetFailureStage::Unspecified as i32,
            })),
        }],
        deterministic_error_policy: pb::DeterministicErrorPolicy::NonFatal as i32,
    };
    backfill_common::encode_canonical_block_changes(&changes, &compatibility)
}

#[test]
fn single_and_double_normalization_are_not_interchangeable() {
    let raw = bigint::parse("-85070591730234615865843651857942052863").unwrap();
    let once = GraphDecimal::from_bigint(&raw).unwrap();
    assert_eq!(
        once.coefficient_and_scale(),
        (
            bigint::parse("-85070591730234615865843651857942052").unwrap(),
            -3
        )
    );
    assert!(!once.is_fixed_point());
    assert_eq!(
        once.to_block_changes_wire(),
        Err(NumericError::NonFixedPoint)
    );
    assert!(seal(once.to_wire_exact()).is_err());
    let restored = GraphDecimal::from_wire_exact(&once.to_wire_exact()).unwrap();
    assert_eq!(restored.to_wire_exact(), once.to_wire_exact());
    let twice = once.cross().unwrap();
    assert_ne!(twice, once);
    assert!(twice.is_fixed_point());
    assert!(seal(twice.to_block_changes_wire().unwrap()).is_ok());
    assert_eq!(
        GraphDecimal::host_from_string(&raw.to_string()).unwrap(),
        twice
    );
    assert_eq!(GraphDecimal::from_db_text(&raw.to_string()).unwrap(), once);
}

#[test]
fn v1_accepts_exactly_fixed_points_across_the_negative_bit_boundary() {
    let limit = BigInt::from(1) << 116usize;
    for delta in -100i32..=100 {
        let coefficient = -(&limit + BigInt::from(delta));
        let candidate = pb::BigDecimalValue {
            coefficient_signed_be: bigint::signed_bytes(&coefficient),
            scale: 20,
        };
        // Trailing zeroes are intentionally noncanonical, regardless of precision.
        if coefficient.to_string().ends_with('0') {
            continue;
        }
        let value = GraphDecimal::from_wire_exact(&candidate).unwrap();
        assert_eq!(
            seal(candidate).is_ok(),
            value.is_fixed_point(),
            "{coefficient}"
        );
    }
    for s in [
        "-0.33333333333333333333333333333333333",
        "-1958.2627366648723548155211868460794",
    ] {
        assert!(seal(
            GraphDecimal::host_from_string(s)
                .unwrap()
                .to_block_changes_wire()
                .unwrap()
        )
        .is_ok());
    }
}

#[test]
fn common_validator_agrees_with_every_decimal_in_the_committed_corpus() {
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("../fixtures/graph-node-v0.44-numerics.json")).unwrap();
    let mut checked = 0;
    for row in fixture["vectors"].as_array().unwrap() {
        let result = &row["result"];
        let values = if let Some(prices) = result["prices"].as_array() {
            prices.iter().collect::<Vec<_>>()
        } else {
            vec![result]
        };
        for value in values {
            let Some(wire) = value["wire"].as_str().filter(|_| value["scale"].is_i64()) else {
                continue;
            };
            let wire = pb::BigDecimalValue {
                coefficient_signed_be: hex::decode(wire).unwrap(),
                scale: value["scale"].as_i64().unwrap(),
            };
            assert_eq!(
                seal(wire).is_ok(),
                value["fixed"].as_bool().unwrap(),
                "{row}"
            );
            checked += 1;
        }
    }
    assert!(checked > 2000);
}

#[test]
fn wire_restore_refuses_noncanonical_numbers_without_rewriting_them() {
    for (coefficient, scale) in [
        (vec![0], 0),
        (vec![], 1),
        (vec![0, 1], 0),
        (vec![10], 1),
        (vec![1], 6144),
        (vec![1], -6145),
    ] {
        assert!(GraphDecimal::from_wire_exact(&pb::BigDecimalValue {
            coefficient_signed_be: coefficient,
            scale
        })
        .is_err());
    }
    assert!(bigint::from_wire(&pb::BigIntValue {
        signed_be: vec![0xff, 0xff]
    })
    .is_err());
    assert_eq!(
        bigint::from_wire(&pb::BigIntValue { signed_be: vec![] }).unwrap(),
        BigInt::from(0)
    );
}

#[test]
fn malformed_extreme_scales_return_errors_instead_of_panicking() {
    for input in [
        "1e-9223372036854775808",
        "1.0e-9223372036854775807",
        "1e9223372036854775807",
    ] {
        assert!(GraphDecimal::host_from_string(input).is_err());
    }
    assert_eq!(
        GraphDecimal::from_asc_parts(BigInt::from(1), i64::MIN),
        Err(NumericError::ScaleOverflow)
    );
    // Significant digits do not change the host exponent-domain check.
    assert!(GraphDecimal::host_from_string("123e6144").is_ok());
    assert!(GraphDecimal::host_from_string("1e6145").is_err());
    assert!(GraphDecimal::host_from_string("0e9223372036854775807").is_ok());
}

#[test]
fn checked_integer_results_include_the_sign_bit_and_never_divide_by_zero() {
    let highest = BigInt::from(1) << 435410usize;
    assert!(bigint::check_bits(&highest).is_ok());
    assert!(bigint::check_bits(&(-&highest)).is_ok());
    assert!(matches!(
        bigint::left_shift(&highest, 1),
        Err(NumericError::IntegerTooBig(435413))
    ));
    assert!(bigint::divided_by(&BigInt::from(7), &BigInt::from(0)).is_err());
    assert!(bigint::modulo(&BigInt::from(7), &BigInt::from(0)).is_err());
}

#[test]
fn helper_limits_fail_closed_and_zero_decimal_amounts_keep_the_single_crossing() {
    let amount = bigint::parse("-85070591730234615865843651857942052863").unwrap();
    let zero = mapping::convert_token_to_decimal(&amount, &BigInt::from(0)).unwrap();
    assert!(!zero.is_fixed_point());
    let one = mapping::convert_token_to_decimal(&amount, &BigInt::from(1)).unwrap();
    assert!(one.is_fixed_point());
    for decimals in [-1, 256] {
        assert!(mapping::exponent_to_big_decimal(&BigInt::from(decimals)).is_err());
    }
    assert_eq!(
        mapping::safe_div(&GraphDecimal::one(), &GraphDecimal::zero()).unwrap(),
        GraphDecimal::zero()
    );
    let mut ticks = mapping::TickPowTable::default();
    for tick in [i32::MIN, -887273, 887273, i32::MAX] {
        assert!(ticks.price(tick).is_err());
    }
}
