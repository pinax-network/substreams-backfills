//! Frozen v1 and capability-gated v2 BlockChanges envelope emission.
//!
//! Phase 1 could report one modification set per handler, sorted by key, because
//! `EntityCache` collapses writes into a `HashMap`. Phase 2 records the ordered
//! per-save stream instead, from the recorder patched into
//! `vendor/graph-runtime-wasm` beside the proof-of-indexing writes, and projects
//! it onto the canonical frame.
//!
//! Every frame uses the shared canonical in-band codec. Empty creation lists
//! preserve the exact frozen v1 encoding; field 9 requires the v2 descriptor
//! capability and an engine consumer that explicitly supports that envelope.
//!
//! ## The merge algebra is imported, not restated
//!
//! `materialized` is the schema-level, get-visible entity after one save. It is
//! computed with `backfill_common::CacheOperation`, whose `accumulate` and
//! `apply_to` are the canonical wrappers over `apply_written_fields` and
//! `NullMergeMode` — the exact items the validator uses. Two independent
//! implementations of these semantics is the failure mode the contract exists to
//! prevent, so none is written here.
//!
//! Within a handler, saves to one key accumulate: `CacheOperation::accumulate`
//! folds each later write into the running effect with `NullMergeMode::Preserve`,
//! and `apply_to` projects that effect onto the entity visible before the handler
//! ran, using `NullMergeMode::Remove` only when a predecessor exists. That is
//! Graph Node's `EntityCache::get`, which layers accumulated `handler_updates`
//! over `current`. Re-merging incrementally instead would diverge: two saves
//! where the second nulls a field the first set produce a *retained* Null over an
//! absent baseline, and a *removed* field if each save is merged in turn.

use std::sync::Mutex;

use anyhow::{anyhow, bail, Context, Result};
use backfill_common::pb::pinax::graph::backfill::v2 as pb;
use backfill_common::{
    decode_canonical_in_band_block_changes as decode_canonical_block_changes,
    encode_canonical_in_band_block_changes as encode_canonical_block_changes,
    BlockChangesCompatibility,
};
use graph::data::store::{Entity, Id, Value};
use graph::schema::{EntityKey, InputSchema};
use graph_runtime_wasm::op_recorder::EntityOpRecorder;

/// The `BCF1` clock-v1 frame header is fixed width; see `header` below.
pub const BCF1_MAGIC: &[u8; 4] = b"BCF1";

/// Exact shared ordered builder; Graph Node keys are only the lookup adapter.
pub use backfill_common::block_ops::BlockOpsBuilder;
pub type RecordedOp = backfill_common::block_ops::RecordedOp<EntityKey>;

/// The recorder installed on every runtime host.
///
/// Exactly one handler runs at a time in this host: the runner awaits
/// `process_mapping_trigger` before starting the next, and the mapping thread
/// only runs between that send and its reply. The mutex is therefore
/// uncontended, and [`drain`](Self::drain) after each handler yields that
/// handler's saves in call order.
#[derive(Default)]
pub struct OpRecorder {
    ops: Mutex<Vec<RecordedOp>>,
}

impl OpRecorder {
    pub fn new() -> Self {
        Self::default()
    }

    /// Take everything recorded since the last drain.
    pub fn drain(&self) -> Vec<RecordedOp> {
        std::mem::take(&mut *self.ops.lock().expect("recorder lock poisoned"))
    }
}

impl EntityOpRecorder for OpRecorder {
    fn record_set(&self, key: &EntityKey, entity: &Entity, poi_causality_region: &str) {
        let converted = convert_key(key);
        let op = RecordedOp::Set {
            native_key: key.clone(),
            poi_entity_type: key.entity_type.typename().to_string(),
            poi_entity_id: key.entity_id.to_string(),
            written_fields: convert_entity(entity),
            source_causality_region: converted.storage_causality_region,
            key: converted,
            poi_causality_region: poi_causality_region.to_string(),
        };
        self.ops.lock().expect("recorder lock poisoned").push(op);
    }

    fn record_remove(&self, entity_type: &str, entity_id: &str, poi_causality_region: &str) {
        let op = RecordedOp::Remove {
            native_key: None,
            key: None,
            poi_entity_type: entity_type.to_string(),
            poi_entity_id: entity_id.to_string(),
            // Filled in by `record_remove_key` once the typed key parses; a
            // remove that never parses is discarded with its handler.
            source_causality_region: 0,
            poi_causality_region: poi_causality_region.to_string(),
        };
        self.ops.lock().expect("recorder lock poisoned").push(op);
    }

    fn record_remove_key(&self, key: &EntityKey) {
        let mut ops = self.ops.lock().expect("recorder lock poisoned");
        if let Some(RecordedOp::Remove {
            native_key,
            key: slot,
            source_causality_region,
            ..
        }) = ops.last_mut()
        {
            let converted = convert_key(key);
            *source_causality_region = converted.storage_causality_region;
            *slot = Some(converted);
            *native_key = Some(key.clone());
        }
    }
}

/// The wire key for a graph-native key, as every recorded operation uses it.
pub fn convert_key(key: &EntityKey) -> pb::EntityKey {
    pb::EntityKey {
        entity_type: key.entity_type.typename().to_string(),
        id: Some(convert_id(&key.entity_id)),
        // `CausalityRegion` holds a private `i32`; `Display` is the public
        // accessor. Uniswap V3 is onchain-only, so this is always zero, but
        // parsing keeps the field honest for an offchain family later.
        storage_causality_region: key.causality_region.to_string().parse().unwrap_or_default(),
    }
}

fn convert_id(id: &Id) -> pb::EntityId {
    let value = match id {
        Id::String(word) => pb::entity_id::Value::String(word.to_string()),
        Id::Bytes(bytes) => pb::entity_id::Value::Bytes(bytes.as_slice().to_vec()),
        Id::Int8(value) => pb::entity_id::Value::Int8(*value),
    };
    pb::EntityId { value: Some(value) }
}

/// The schema-filtered entity as hashed: sorted by field name, `vid` excluded by
/// `Entity::sorted_ref` itself.
pub fn convert_entity(entity: &Entity) -> Vec<pb::EntityField> {
    entity
        .sorted_ref()
        .into_iter()
        .map(|(name, value)| pb::EntityField {
            name: name.to_string(),
            value: Some(convert_value(value)),
        })
        .collect()
}

/// Minimal two's-complement signed big-endian, with the empty slice as the sole
/// representation of zero. `num_bigint` renders zero as `[0]`, which the
/// canonical validator refuses.
fn signed_be(value: &graph::data::store::scalar::BigInt) -> Vec<u8> {
    let mut bytes = value.to_signed_bytes_le();
    bytes.reverse();
    if bytes == [0] {
        return Vec::new();
    }
    bytes
}

pub fn convert_value(value: &Value) -> pb::GraphValue {
    use pb::graph_value::Kind;
    let kind = match value {
        Value::String(value) => Kind::String(value.clone()),
        Value::Int(value) => Kind::Int(*value),
        Value::Int8(value) => Kind::Int8(*value),
        Value::Timestamp(value) => Kind::TimestampMicros(value.as_microseconds_since_epoch()),
        Value::BigDecimal(value) => {
            // The recorder sees the entity after `asc_get`, so `BigDecimal::new`
            // has already run Graph Node v0.44's `normalized()` on this value.
            // The coefficient is emitted unchanged and may have more than 34
            // digits. bigdecimal 0.1.2 counts a negative coefficient's digits
            // from its bit length, so a negative value keeps up to 116 bits,
            // which includes 35-digit values below 2^116. Arithmetic results
            // are normalized again on the way back from the mapping, so they
            // always arrive as fixed points, which `seal` accepts. A raw
            // `BigInt.toBigDecimal()` saved without host arithmetic can arrive
            // as a 117-bit coefficient that a second pass would truncate.
            // `seal` refuses that value with `DecimalPrecision` rather than
            // emitting a frame no re-normalizing consumer reproduces; see
            // docs/block-changes-v1.md. `as_bigint_and_exponent` returns the
            // (coefficient, scale) pair the wire format defines.
            // `to_signed_bytes_be` is called on whatever `num_bigint` version
            // `graph` links; naming the type here would tie this crate to one of
            // the two in the graph, and bytes are bytes.
            let (coefficient, scale) = value.as_bigint_and_exponent();
            let mut coefficient_signed_be = coefficient.to_signed_bytes_be();
            if coefficient_signed_be == [0] {
                coefficient_signed_be = Vec::new();
            }
            Kind::BigDecimal(pb::BigDecimalValue {
                coefficient_signed_be,
                scale,
            })
        }
        Value::Bool(value) => Kind::Bool(*value),
        Value::List(values) => Kind::List(pb::ListValue {
            values: values.iter().map(convert_value).collect(),
        }),
        Value::Null => Kind::Null(pb::NullValue {}),
        Value::Bytes(value) => Kind::Bytes(value.as_slice().to_vec()),
        Value::BigInt(value) => Kind::BigInt(pb::BigIntValue {
            signed_be: signed_be(value),
        }),
    };
    pb::GraphValue { kind: Some(kind) }
}

/// The inverse of [`convert_value`].
///
/// A checkpoint restores the store from the wire encoding, so the way back has
/// to be the exact mirror of the way out; otherwise a resumed run would hold
/// values that merely *look* like the ones an uninterrupted run held. Every
/// variant round-trips. `BigInt` and the `BigDecimal` coefficient are minimal
/// two's-complement big-endian with the empty slice for zero, which
/// `num_bigint` reads back unchanged, and `BigDecimal::new(digits, exp)` negates
/// its argument to reach `bigdecimal`'s scale, so the recorded `scale` goes back
/// in as `-scale`. `BigDecimal::new` also normalizes again. That is the identity
/// on exactly the decimal domain `seal` accepts, Graph Node's normalization
/// fixed points, so a checkpoint never changes an emitted value.
pub fn value_from_wire(value: &pb::GraphValue) -> Result<Value> {
    use graph::data::store::scalar::{BigDecimal, BigInt, Bytes, Timestamp};
    use pb::graph_value::Kind;
    let kind = value
        .kind
        .as_ref()
        .ok_or_else(|| anyhow!("a stored value has no kind"))?;
    Ok(match kind {
        Kind::String(value) => Value::String(value.clone()),
        Kind::Int(value) => Value::Int(*value),
        Kind::Int8(value) => Value::Int8(*value),
        Kind::TimestampMicros(value) => Value::Timestamp(
            Timestamp::from_microseconds_since_epoch(*value)
                .map_err(|error| anyhow!("a stored timestamp is out of range: {error}"))?,
        ),
        Kind::BigDecimal(value) => Value::BigDecimal(BigDecimal::new(
            BigInt::from_signed_bytes_be(&value.coefficient_signed_be)
                .context("a stored BigDecimal coefficient")?,
            -value.scale,
        )),
        Kind::Bool(value) => Value::Bool(*value),
        Kind::List(value) => Value::List(
            value
                .values
                .iter()
                .map(value_from_wire)
                .collect::<Result<Vec<_>>>()?,
        ),
        Kind::Null(_) => Value::Null,
        Kind::Bytes(value) => Value::Bytes(Bytes::from(value.as_slice())),
        Kind::BigInt(value) => Value::BigInt(
            BigInt::from_signed_bytes_be(&value.signed_be).context("a stored BigInt")?,
        ),
    })
}

/// The inverse of [`convert_key`], resolved against the deployed schema.
///
/// The typename is looked up rather than trusted, so a checkpoint naming a type
/// this schema does not declare is refused instead of silently dropped. The id
/// kind is checked against the type's declared id type for the same reason: a
/// `String` id restored into a `Bytes`-keyed type would order differently from
/// the row the run actually held.
pub fn key_from_wire(schema: &InputSchema, key: &pb::EntityKey) -> Result<EntityKey> {
    use graph::data::store::scalar::Bytes;
    use graph::data::value::Word;
    use graph::data_source::CausalityRegion;

    let poi_type = schema.poi_type();
    let entity_type = if key.entity_type == poi_type.typename() {
        poi_type
    } else {
        schema
            .entity_type(key.entity_type.as_str())
            .with_context(|| {
                format!(
                    "the deployed schema declares no entity type `{}`",
                    key.entity_type
                )
            })?
    };

    let id = match key.id.as_ref().and_then(|id| id.value.as_ref()) {
        Some(pb::entity_id::Value::String(value)) => Id::String(Word::from(value.as_str())),
        Some(pb::entity_id::Value::Bytes(value)) => Id::Bytes(Bytes::from(value.as_slice())),
        Some(pb::entity_id::Value::Int8(value)) => Id::Int8(*value),
        None => bail!("an entity key for `{}` has no id", key.entity_type),
    };
    // `id_type()` errors for a type that stores no data of its own; only check
    // where the schema has an answer.
    if let Ok(declared) = entity_type.id_type() {
        if id.id_type() != declared {
            bail!(
                "`{}` is keyed by {declared:?} in the deployed schema, but the checkpoint's id \
                 is {:?}",
                key.entity_type,
                id.id_type()
            );
        }
    }

    Ok(entity_type.key_in(id, CausalityRegion::from(key.storage_causality_region)))
}

/// The inverse of [`convert_entity`], resolved against the deployed schema.
///
/// `vid` is not part of the wire form — `Entity::sorted_ref` excludes it — so a
/// caller restoring a store row sets it afterwards with `Entity::set_vid`.
pub fn entity_from_wire(schema: &InputSchema, fields: &[pb::EntityField]) -> Result<Entity> {
    use graph::data::value::Word;
    let mut pairs: Vec<(Word, Value)> = Vec::with_capacity(fields.len());
    for field in fields {
        let value = field
            .value
            .as_ref()
            .ok_or_else(|| anyhow!("field `{}` has no value", field.name))?;
        pairs.push((Word::from(field.name.as_str()), value_from_wire(value)?));
    }
    schema
        .make_entity(pairs)
        .map_err(|error| anyhow!("rebuilding a stored entity: {error}"))
}

/// Count a frame's operations for the human-readable report.
pub fn summarize(changes: &pb::BlockChanges, bytes: &[u8]) -> crate::report::BlockChangesSummary {
    let mut sets = 0;
    let mut removes = 0;
    let mut deterministic_errors = 0;
    for operation in &changes.operations {
        match operation.operation.as_ref() {
            Some(pb::entity_operation::Operation::Set(_)) => sets += 1,
            Some(pb::entity_operation::Operation::Remove(_)) => removes += 1,
            Some(pb::entity_operation::Operation::DeterministicError(_)) => {
                deterministic_errors += 1
            }
            None => {}
        }
    }
    crate::report::BlockChangesSummary {
        operations: changes.operations.len(),
        sets,
        removes,
        deterministic_errors,
        frame_bytes: bytes.len(),
        frame_sha256: crate::bundle::sha256_hex(bytes),
    }
}

/// Validate, encode, and prove the encoding round-trips.
pub fn seal(
    changes: &pb::BlockChanges,
    compatibility: &BlockChangesCompatibility,
) -> Result<Vec<u8>> {
    let bytes = encode_canonical_block_changes(changes, compatibility)
        .map_err(|error| anyhow!("BlockChanges frame is not canonical: {error}"))?;
    let decoded = decode_canonical_block_changes(&bytes, compatibility)
        .map_err(|error| anyhow!("BlockChanges frame did not round-trip: {error}"))?;
    if &decoded != changes {
        bail!("BlockChanges frame did not round-trip to an equal message");
    }
    Ok(bytes)
}

/// One `BCF1` clock-v1 frame, the envelope `cmd/substreams-native` writes and
/// the engine's `block-changes-v1-framed` mode reads.
///
/// ```text
/// 0  ..4    "BCF1"
/// 4         version, 1
/// 5  ..8    reserved, zero
/// 8  ..16   block number, big-endian u64
/// 16 ..48   block hash, 32 bytes
/// 48 ..52   payload length, big-endian u32
/// 52 ..     payload
/// ```
pub fn bcf1_frame(block_number: u64, block_hash: &[u8], payload: &[u8]) -> Result<Vec<u8>> {
    if block_hash.len() != 32 {
        bail!(
            "a BCF1 frame needs a 32-byte block hash, got {}",
            block_hash.len()
        );
    }
    let mut bytes = Vec::with_capacity(52 + payload.len());
    backfill_common::clock::write_frame(
        &mut bytes,
        &backfill_common::clock::Frame {
            kind: backfill_common::clock::FrameKind::Observed,
            block_number,
            block_hash: block_hash.try_into().expect("length checked"),
            payload: payload.to_vec(),
        },
    )?;
    Ok(bytes)
}

#[cfg(test)]
mod value_round_trip_tests {
    use super::*;
    use graph::data::store::scalar::{BigDecimal, BigInt, Bytes, Timestamp};

    /// Every variant, and for the numeric ones every sign and the zero, because
    /// zero is the value the canonical encoding spells differently from
    /// `num_bigint` and is therefore the one a naive inverse loses.
    fn cases() -> Vec<Value> {
        vec![
            Value::String("pool-1".to_owned()),
            Value::String(String::new()),
            Value::Int(0),
            Value::Int(-7),
            Value::Int(i32::MIN),
            Value::Int8(0),
            Value::Int8(i64::MIN),
            Value::Int8(i64::MAX),
            Value::Timestamp(
                Timestamp::from_microseconds_since_epoch(1_725_000_000_123_456).expect("in range"),
            ),
            Value::Timestamp(Timestamp::from_microseconds_since_epoch(0).expect("in range")),
            Value::BigDecimal(BigDecimal::zero()),
            Value::BigDecimal(
                BigDecimal::new(BigInt::from(123_456_789_i64), -18) / BigDecimal::from(7),
            ),
            Value::BigDecimal(BigDecimal::new(BigInt::from(-1_i64), 6)),
            Value::Bool(true),
            Value::Bool(false),
            Value::Null,
            Value::Bytes(Bytes::from(Vec::new())),
            Value::Bytes(Bytes::from(vec![0x00, 0xde, 0xad, 0xff])),
            Value::BigInt(BigInt::from(0_i64)),
            Value::BigInt(BigInt::from(-1_i64)),
            Value::BigInt(BigInt::from(i64::MIN)),
            Value::BigInt(
                BigInt::from_signed_bytes_be(&[0x7f; 32]).expect("32 bytes is within the limit"),
            ),
            Value::List(vec![
                Value::String("nested".to_owned()),
                Value::Null,
                Value::BigInt(BigInt::from(0_i64)),
                Value::List(vec![Value::Int(1)]),
            ]),
            Value::List(Vec::new()),
        ]
    }

    #[test]
    fn every_value_survives_the_round_trip_through_the_wire_form() {
        for value in cases() {
            let wire = convert_value(&value);
            let back = value_from_wire(&wire).unwrap_or_else(|e| panic!("{value:?}: {e:#}"));
            assert_eq!(back, value, "{value:?}");
            // And the way out from the restored value is byte-identical, which
            // is what a checkpointed run's frames depend on.
            assert_eq!(convert_value(&back), wire, "{value:?}");
        }
    }

    #[test]
    fn a_wire_value_without_a_kind_is_refused() {
        let error = value_from_wire(&pb::GraphValue { kind: None })
            .expect_err("a kindless value is not a value");
        assert!(error.to_string().contains("no kind"), "{error}");
    }
}

/// The BlockChanges v1 decimal domain, checked against Graph Node's own
/// `BigDecimal` rather than a restatement of it.
///
/// `backfill_common` accepts a decimal exactly when Graph Node v0.44's
/// `normalized()` maps it to itself. This crate links that code, through
/// `graph` and bigdecimal 0.1.2, so these tests can treat it as the oracle:
/// `BigDecimal::new` is the normalization `asc_get` applies to every value a
/// mapping hands to the host, and the arithmetic operators are the host's.
#[cfg(test)]
mod graph_decimal_domain_tests {
    use super::*;
    use graph::data::store::scalar::{BigDecimal, BigInt};
    use pb::graph_value::Kind;
    use std::str::FromStr;

    const REGION: &str = "ethereum/base";
    const PRECISION_REFUSAL: &str = "normalization would round";

    fn compatibility() -> BlockChangesCompatibility {
        let descriptor = format!(
            "{{\"contract\":\"{}\",\"descriptor_version\":1,\"deterministic_error_policy\":\"non_fatal\",\"network\":\"base\",\"expected_poi_causality_region\":\"{REGION}\"}}",
            backfill_common::BLOCK_CHANGES_V1_CONTRACT
        );
        BlockChangesCompatibility::from_descriptor(descriptor.as_bytes())
            .expect("a minimal fixture-only descriptor")
    }

    /// Seal a one-save frame whose only non-ID field is `value`, through the
    /// same `seal` the runner calls for every block.
    fn seal_one(value: pb::GraphValue, compatibility: &BlockChangesCompatibility) -> Result<()> {
        let fields = vec![
            pb::EntityField {
                name: "id".to_owned(),
                value: Some(pb::GraphValue {
                    kind: Some(Kind::String("t".to_owned())),
                }),
            },
            pb::EntityField {
                name: "value".to_owned(),
                value: Some(value),
            },
        ];
        let changes = pb::BlockChanges {
            contract: backfill_common::BLOCK_CHANGES_V1_CONTRACT.to_owned(),
            compatibility_id: compatibility.to_vec(),
            block_number: 1,
            block_hash: vec![0xab; 32],
            mapping_triggered: true,
            triggered_poi_causality_regions: vec![REGION.to_owned()],
            operations: vec![pb::EntityOperation {
                operation_index: 0,
                handler_group_order: 0,
                source_trigger_order: 0,
                poi_causality_region: Some(REGION.to_owned()),
                handler_order: 0,
                source_causality_region: 0,
                operation: Some(pb::entity_operation::Operation::Set(pb::SetEntity {
                    key: Some(pb::EntityKey {
                        entity_type: "Token".to_owned(),
                        id: Some(pb::EntityId {
                            value: Some(pb::entity_id::Value::String("t".to_owned())),
                        }),
                        storage_causality_region: 0,
                    }),
                    poi_entity_type: "Token".to_owned(),
                    poi_entity_id: "t".to_owned(),
                    written_fields: fields.clone(),
                    materialized: Some(pb::EntityFields { fields }),
                    store_disposition: pb::StoreDisposition::Committed as i32,
                    failure_stage: pb::SetFailureStage::Unspecified as i32,
                })),
            }],
            deterministic_error_policy: pb::DeterministicErrorPolicy::NonFatal as i32,
            created_data_sources: Vec::new(),
        };
        seal(&changes, compatibility).map(|_| ())
    }

    fn wire(value: &BigDecimal) -> pb::GraphValue {
        convert_value(&Value::BigDecimal(value.clone()))
    }

    fn tuple(value: &BigDecimal) -> (Vec<u8>, i64) {
        match wire(value).kind {
            Some(Kind::BigDecimal(decimal)) => (decimal.coefficient_signed_be, decimal.scale),
            other => panic!("a BigDecimal converted to {other:?}"),
        }
    }

    /// Graph Node's normalization once more: what `asc_get` does to a value
    /// the mapping passes back to the host, including `store.set`'s entity.
    fn renormalized(value: &BigDecimal) -> BigDecimal {
        let (coefficient, scale) = value.as_bigint_and_exponent();
        let coefficient = BigInt::from_signed_bytes_be(&coefficient.to_signed_bytes_be())
            .expect("a normalized coefficient is far inside the BigInt limit");
        BigDecimal::new(coefficient, -scale)
    }

    fn is_fixed_point(value: &BigDecimal) -> bool {
        tuple(&renormalized(value)) == tuple(value)
    }

    fn negate(value: BigInt) -> BigInt {
        BigInt::from(0_i64) - value
    }

    #[test]
    fn every_fixture_row_matches_graph_nodes_normalization_and_the_validator() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../common/fixtures/block-changes-v1/graph-decimal-domain.json"
        ))
        .expect("the checked-in decimal domain fixture");
        let compatibility = compatibility();
        let cases = fixture["cases"].as_array().expect("cases");
        assert_eq!(cases.len(), 20);
        for case in cases {
            let name = case["name"].as_str().expect("name");
            let coefficient = BigInt::from_str(case["coefficient"].as_str().expect("coefficient"))
                .expect("a decimal coefficient");
            let scale = case["scale"].as_i64().expect("scale");
            let given = (signed_be(&coefficient), scale);

            let normalized = BigDecimal::new(coefficient, -scale);
            let fixed_point = tuple(&normalized) == given;
            assert_eq!(
                fixed_point,
                case["graph_node_fixed_point"].as_bool().expect("flag"),
                "{name}: Graph Node v0.44 normalizes it to {normalized:?}"
            );

            let sealed = seal_one(
                pb::GraphValue {
                    kind: Some(Kind::BigDecimal(pb::BigDecimalValue {
                        coefficient_signed_be: given.0,
                        scale,
                    })),
                },
                &compatibility,
            );
            assert_eq!(sealed.is_ok(), fixed_point, "{name}: {:?}", sealed.err());
        }
    }

    #[test]
    fn host_arithmetic_saves_carry_35_digit_negatives_that_seal() {
        let compatibility = compatibility();

        let third = renormalized(&(BigDecimal::from(-1) / BigDecimal::from(3)));
        assert_eq!(third.to_string(), "-0.33333333333333333333333333333333333");
        seal_one(wire(&third), &compatibility).expect("Graph Node's -1/3");
        let third = renormalized(&(BigDecimal::from(1) / BigDecimal::from(3)));
        assert_eq!(third.to_string(), "0.3333333333333333333333333333333333");
        seal_one(wire(&third), &compatibility).expect("Graph Node's 1/3");

        // The production V4 Base Token TVL, as the deployed mapping computes it:
        // two host multiplications, the intermediate handed back through WASM.
        let tvl = BigDecimal::from_str("-1958.23222").unwrap();
        let derived = BigDecimal::from_str("0.000443428497055167816687599679621575").unwrap();
        let eth_usd = BigDecimal::from_str("2255.190161262956454194198227130777").unwrap();
        let intermediate = tvl * derived;
        assert_eq!(
            intermediate.to_string(),
            "-0.86833597019960473614471136709664557"
        );
        assert!(!is_fixed_point(&intermediate));
        let error = seal_one(wire(&intermediate), &compatibility)
            .expect_err("the mapping never saves the transient intermediate");
        assert!(error.to_string().contains(PRECISION_REFUSAL), "{error:#}");
        let passed_back = renormalized(&intermediate);
        assert_eq!(
            passed_back.to_string(),
            "-0.8683359701996047361447113670966455"
        );
        let saved = renormalized(&(passed_back * eth_usd));
        assert_eq!(saved.to_string(), "-1958.2627366648723548155211868460794");
        assert!(is_fixed_point(&saved));
        seal_one(wire(&saved), &compatibility).expect("the V4 Base TVL value");
    }

    #[test]
    fn a_raw_negative_to_big_decimal_past_116_bits_is_refused() {
        let compatibility = compatibility();
        // `BigInt.toBigDecimal()` of -(2^126 - 1), saved with no host
        // arithmetic: the store boundary normalizes it exactly once.
        let raw = negate(BigInt::from_str("85070591730234615865843651857942052863").unwrap());
        let stored = BigDecimal::new(raw, 0);
        let expected = negate(BigInt::from_str("85070591730234615865843651857942052").unwrap());
        assert_eq!(tuple(&stored), (signed_be(&expected), -3));
        assert!(!is_fixed_point(&stored));
        let error = seal_one(wire(&stored), &compatibility)
            .expect_err("a value no re-normalizing consumer reproduces");
        assert!(error.to_string().contains(PRECISION_REFUSAL), "{error:#}");
        // Loading and saving it again, or restoring it from a checkpoint,
        // truncates it to 34 digits.
        let truncated = negate(BigInt::from_str("8507059173023461586584365185794205").unwrap());
        assert_eq!(tuple(&renormalized(&stored)), (signed_be(&truncated), -4));
        let restored = value_from_wire(&wire(&stored)).unwrap();
        assert_ne!(convert_value(&restored), wire(&stored));
    }

    /// A seeded sweep: for every stored value Graph Node can produce from a
    /// raw `(digits, exp)` in this range, the validator's verdict equals
    /// Graph Node's fixed-point test. Re-saving any of them, which is what an
    /// arithmetic result goes through, always seals.
    #[test]
    fn the_validator_accepts_exactly_graph_nodes_normalization_fixed_points() {
        let compatibility = compatibility();
        let mut state = 0x9E37_79B9_7F4A_7C15_u64;
        let mut next = move || {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state
        };
        let mut accepted_negative_35_digits = 0;
        let mut refused = 0;
        for round in 0..4_000_u32 {
            let magnitude = if round % 4 == 0 {
                // Just below a power of two whose bigdecimal 0.1.2 truncation
                // lands at or above 2^116, the only source of refusals.
                let bits = [126_u8, 136, 146, 156][(next() % 4) as usize];
                (BigInt::from(1_u8) << bits) - BigInt::from(1_u8) - BigInt::from(next() >> 1)
            } else {
                let bits = 1 + next() % 160;
                let mut bytes: Vec<u8> = (0..bits.div_ceil(8)).map(|_| next() as u8).collect();
                let top_bits = (bits - (bytes.len() as u64 - 1) * 8) as u32;
                let top = bytes.last_mut().expect("at least one byte");
                *top = (*top & ((1_u16 << top_bits) - 1) as u8) | (1_u8 << (top_bits - 1));
                BigInt::from_unsigned_bytes_le(&bytes).expect("at most 160 bits")
            };
            let negative = next() % 2 == 0;
            let digits = if negative {
                negate(magnitude)
            } else {
                magnitude
            };
            let exp = (next() % 81) as i64 - 40;

            let stored = BigDecimal::new(digits, exp);
            let fixed_point = is_fixed_point(&stored);
            let sealed = seal_one(wire(&stored), &compatibility);
            assert_eq!(
                sealed.is_ok(),
                fixed_point,
                "{stored:?}: {:?}",
                sealed.err()
            );
            if fixed_point {
                // A checkpoint restore is exact on the accepted domain.
                let back = value_from_wire(&wire(&stored)).unwrap();
                assert_eq!(convert_value(&back), wire(&stored), "{stored:?}");
                if negative && stored.as_bigint_and_exponent().0.to_string().len() == 36 {
                    accepted_negative_35_digits += 1;
                }
            } else {
                assert!(
                    negative,
                    "{stored:?}: only negatives escape the fixed points"
                );
                refused += 1;
            }

            let resaved = renormalized(&stored);
            assert!(is_fixed_point(&resaved), "{resaved:?}");
            seal_one(wire(&resaved), &compatibility)
                .unwrap_or_else(|error| panic!("{resaved:?}: {error:#}"));
        }
        assert!(accepted_negative_35_digits > 0);
        assert!(refused > 0);
    }
}
