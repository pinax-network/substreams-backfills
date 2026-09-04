//! The final in-memory store, in the consumer's generic-state encoding.
//!
//! `--store-out` exists so a replay can be checked against a consumer end to
//! end, not only frame by frame. The frames are an *operation stream*: they say
//! what each handler asked the store to do. What the store then holds is a
//! separate fact, and the only way to prove a consumer folds the stream the way
//! Graph Node does is to compare the two final images.
//!
//! ## The encoding is the frames' encoding
//!
//! Every value here goes through [`crate::blockchanges::convert_value`], the
//! same function that fills a frame's `written_fields` and `materialized`, and
//! every key through [`crate::blockchanges::convert_key`]. Nothing is
//! re-encoded, rounded or stringified on the way out: a `BigInt` keeps its
//! minimal two's-complement big-endian bytes and a `BigDecimal` keeps its
//! (coefficient, scale) pair, because those are the bytes the contract defines
//! and the bytes a consumer will have.
//!
//! Rows are ordered by [`backfill_common::MaterializedKey`], the storage
//! identity the contract keys entities by, so the array is byte-stable and
//! directly comparable with a consumer that keys its state the same way.
//!
//! ## Why `Poi$` is a separate array
//!
//! Graph Node writes the proof-of-indexing entity itself, at the end of the
//! block, from a digest no mapping handler ever sees. It is in this store
//! because [`crate::runner::SegmentHost::process_block`] applies that write, and
//! it is *not* in any frame, because the recorder only observes mapping saves.
//! Hiding it would make this file a partial image of the store; folding it into
//! `entities` would make a consumer's frame-derived state look wrong for a row
//! no frame carries. So it is dumped beside them, and `poi` carries the digest a
//! consumer computes independently and can compare against.

use std::collections::BTreeMap;

use anyhow::Result;
use backfill_common::pb::pinax::graph::backfill::v1 as pb;
use backfill_common::{materialized_key, MaterializedId, MaterializedKey};
use graph::data::store::Entity;
use graph::schema::EntityKey;
use serde::{Deserialize, Serialize};

use crate::blockchanges::{convert_entity, convert_key};

/// Schema identifier written into every store dump.
pub const STORE_STATE_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.store-state/v1";

/// A `GraphValue` in serialisable form, variant for variant.
///
/// The tagging is adjacent — `{"kind": …, "value": …}` — so every variant,
/// including the primitive ones, survives a JSON round trip.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum StoreValue {
    String(String),
    Int(i32),
    Int8(i64),
    TimestampMicros(i64),
    BigDecimal {
        coefficient_signed_be: Vec<u8>,
        scale: i64,
    },
    Bool(bool),
    List(Vec<StoreValue>),
    Null,
    Bytes(Vec<u8>),
    BigInt {
        signed_be: Vec<u8>,
    },
}

impl StoreValue {
    /// Mirror one wire value. The wire form is the input, so nothing here can
    /// disagree with what the frames carry.
    pub fn from_wire(value: &pb::GraphValue) -> Result<Self> {
        use pb::graph_value::Kind;
        let kind = value
            .kind
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("a stored value has no kind"))?;
        Ok(match kind {
            Kind::String(value) => StoreValue::String(value.clone()),
            Kind::Int(value) => StoreValue::Int(*value),
            Kind::Int8(value) => StoreValue::Int8(*value),
            Kind::TimestampMicros(value) => StoreValue::TimestampMicros(*value),
            Kind::BigDecimal(value) => StoreValue::BigDecimal {
                coefficient_signed_be: value.coefficient_signed_be.clone(),
                scale: value.scale,
            },
            Kind::Bool(value) => StoreValue::Bool(*value),
            Kind::List(value) => StoreValue::List(
                value
                    .values
                    .iter()
                    .map(StoreValue::from_wire)
                    .collect::<Result<Vec<_>>>()?,
            ),
            Kind::Null(_) => StoreValue::Null,
            Kind::Bytes(value) => StoreValue::Bytes(value.clone()),
            Kind::BigInt(value) => StoreValue::BigInt {
                signed_be: value.signed_be.clone(),
            },
        })
    }

    /// The wire value this mirrors, variant for variant.
    ///
    /// The exact inverse of [`StoreValue::from_wire`], which is what lets a dump
    /// be read back into the store it was taken from; see [`crate::checkpoint`].
    pub fn to_wire(&self) -> pb::GraphValue {
        use pb::graph_value::Kind;
        let kind = match self {
            StoreValue::String(value) => Kind::String(value.clone()),
            StoreValue::Int(value) => Kind::Int(*value),
            StoreValue::Int8(value) => Kind::Int8(*value),
            StoreValue::TimestampMicros(value) => Kind::TimestampMicros(*value),
            StoreValue::BigDecimal {
                coefficient_signed_be,
                scale,
            } => Kind::BigDecimal(pb::BigDecimalValue {
                coefficient_signed_be: coefficient_signed_be.clone(),
                scale: *scale,
            }),
            StoreValue::Bool(value) => Kind::Bool(*value),
            StoreValue::List(values) => Kind::List(pb::ListValue {
                values: values.iter().map(StoreValue::to_wire).collect(),
            }),
            StoreValue::Null => Kind::Null(pb::NullValue {}),
            StoreValue::Bytes(value) => Kind::Bytes(value.clone()),
            StoreValue::BigInt { signed_be } => Kind::BigInt(pb::BigIntValue {
                signed_be: signed_be.clone(),
            }),
        };
        pb::GraphValue { kind: Some(kind) }
    }
}

/// A typed entity id, in the three kinds the contract defines.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum StoreEntityId {
    String(String),
    Bytes(Vec<u8>),
    Int8(i64),
}

impl From<&MaterializedId> for StoreEntityId {
    fn from(id: &MaterializedId) -> Self {
        match id {
            MaterializedId::String(value) => StoreEntityId::String(value.clone()),
            MaterializedId::Bytes(value) => StoreEntityId::Bytes(value.clone()),
            MaterializedId::Int8(value) => StoreEntityId::Int8(*value),
        }
    }
}

impl StoreEntityId {
    /// The wire id this mirrors, for reading a dump back into a store.
    pub fn to_wire(&self) -> pb::EntityId {
        let value = match self {
            StoreEntityId::String(value) => pb::entity_id::Value::String(value.clone()),
            StoreEntityId::Bytes(value) => pb::entity_id::Value::Bytes(value.clone()),
            StoreEntityId::Int8(value) => pb::entity_id::Value::Int8(*value),
        };
        pb::EntityId { value: Some(value) }
    }

    /// The storage identity this mirrors, so a dumped row sorts exactly as the
    /// live row it came from.
    pub fn to_materialized(&self) -> MaterializedId {
        match self {
            StoreEntityId::String(value) => MaterializedId::String(value.clone()),
            StoreEntityId::Bytes(value) => MaterializedId::Bytes(value.clone()),
            StoreEntityId::Int8(value) => MaterializedId::Int8(*value),
        }
    }
}

/// One live row: its storage identity and its complete get-visible field set.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StoreEntity {
    pub entity_type: String,
    pub id: StoreEntityId,
    pub storage_causality_region: i32,
    /// Sorted by field name, `vid` excluded, exactly as a frame's
    /// `materialized` orders it — both come from `Entity::sorted_ref`.
    pub fields: Vec<(String, StoreValue)>,
}

impl StoreEntity {
    fn new(key: &MaterializedKey, fields: &[pb::EntityField]) -> Result<Self> {
        Ok(StoreEntity {
            entity_type: key.entity_type.clone(),
            id: StoreEntityId::from(&key.id),
            storage_causality_region: key.storage_causality_region,
            fields: fields
                .iter()
                .map(|field| {
                    let value = field
                        .value
                        .as_ref()
                        .ok_or_else(|| anyhow::anyhow!("field `{}` has no value", field.name))?;
                    Ok((field.name.clone(), StoreValue::from_wire(value)?))
                })
                .collect::<Result<Vec<_>>>()?,
        })
    }
}

/// The run's closing proof of indexing, as the last block that opened the
/// causality region left it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StorePoi {
    /// The block whose replay produced these digests.
    pub block: i32,
    /// `legacy` or `fast`.
    pub version: String,
    /// Causality region name to its paused digest, hex without `0x`. This is
    /// the value Graph Node stores in the `Poi$` entity's digest field, and the
    /// value that chains from block to block.
    pub causality_regions: BTreeMap<String, String>,
    /// `ProofOfIndexingFinisher` with `indexer: None`.
    pub public_digest: String,
}

/// How many rows of what.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StoreTotals {
    /// Rows in `entities`.
    pub entities: usize,
    /// Rows in `poi_entities`.
    pub poi_entities: usize,
    /// Fields across `entities`, so a truncated file cannot pass unnoticed.
    pub fields: usize,
}

/// The replayed range, half-open, as the CLI was asked for it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StoreRange {
    pub from: i32,
    pub to: i32,
    /// Blocks actually replayed. Equal to `to - from` for a contiguous live
    /// range, and the fixture count for a sampled one.
    pub blocks: usize,
}

/// The whole dump.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StoreState {
    pub schema: String,
    pub deployment: String,
    pub network: String,
    pub spec_version: String,
    pub poi_causality_region: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range: Option<StoreRange>,
    pub totals: StoreTotals,
    /// Live rows per entity type, `Poi$` included. The same numbers the
    /// per-block report's `store_counts` carries for the last block.
    pub counts_by_type: BTreeMap<String, usize>,
    /// `None` when no block in the range opened the causality region.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub poi: Option<StorePoi>,
    /// Every live row except the proof-of-indexing entity, ordered by storage
    /// identity.
    pub entities: Vec<StoreEntity>,
    /// The proof-of-indexing rows, which no frame carries; see the module docs.
    pub poi_entities: Vec<StoreEntity>,
}

impl StoreState {
    /// Pretty JSON with a closing newline, as every other artifact this crate
    /// writes.
    pub fn to_json(&self) -> Result<String> {
        let mut json = serde_json::to_string_pretty(self)?;
        json.push('\n');
        Ok(json)
    }
}

/// Split a store snapshot into ordinary rows and proof-of-indexing rows.
///
/// `poi_type` is the deployed schema's own PoI typename, read from the schema
/// rather than spelled here, so a schema that names it differently still sorts
/// correctly.
pub fn split_rows(
    rows: &BTreeMap<EntityKey, Entity>,
    poi_type: &str,
) -> Result<(Vec<StoreEntity>, Vec<StoreEntity>)> {
    let mut entities: BTreeMap<MaterializedKey, StoreEntity> = BTreeMap::new();
    let mut poi_entities: BTreeMap<MaterializedKey, StoreEntity> = BTreeMap::new();
    for (key, entity) in rows {
        let wire_key = convert_key(key);
        let is_poi = wire_key.entity_type == poi_type;
        let materialized = materialized_key(&wire_key);
        let row = StoreEntity::new(&materialized, &convert_entity(entity))?;
        let target = if is_poi {
            &mut poi_entities
        } else {
            &mut entities
        };
        if target.insert(materialized.clone(), row).is_some() {
            anyhow::bail!(
                "two store rows share the storage identity {}/{:?}",
                materialized.entity_type,
                materialized.id
            );
        }
    }
    Ok((
        entities.into_values().collect(),
        poi_entities.into_values().collect(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wire(kind: pb::graph_value::Kind) -> pb::GraphValue {
        pb::GraphValue { kind: Some(kind) }
    }

    #[test]
    fn every_value_kind_round_trips_through_json() {
        use pb::graph_value::Kind;
        let values = vec![
            Kind::String("pool-1".to_owned()),
            Kind::Int(-7),
            Kind::Int8(9_223_372_036_854_775),
            Kind::TimestampMicros(1_725_000_000_123_456),
            Kind::BigDecimal(pb::BigDecimalValue {
                coefficient_signed_be: vec![0x01, 0x02],
                scale: 18,
            }),
            Kind::Bool(true),
            Kind::List(pb::ListValue {
                values: vec![
                    wire(Kind::String("nested".to_owned())),
                    wire(Kind::Null(pb::NullValue {})),
                    wire(Kind::Bytes(vec![1, 2])),
                ],
            }),
            Kind::Null(pb::NullValue {}),
            Kind::Bytes(vec![0xde, 0xad]),
            Kind::BigInt(pb::BigIntValue {
                signed_be: vec![0xff],
            }),
        ];
        for kind in values {
            let mirrored = StoreValue::from_wire(&wire(kind)).expect("mirrored");
            let json = serde_json::to_string(&mirrored).expect("serialised");
            let back: StoreValue = serde_json::from_str(&json).expect("deserialised");
            assert_eq!(mirrored, back, "{json}");
        }
    }

    /// The adjacent tagging is the contract with the consumer, so it is pinned
    /// as text rather than only as a round trip.
    #[test]
    fn the_json_shape_is_kind_and_value() {
        use pb::graph_value::Kind;
        let cases = [
            (
                Kind::String("pool-1".to_owned()),
                r#"{"kind":"string","value":"pool-1"}"#,
            ),
            (Kind::Int(-7), r#"{"kind":"int","value":-7}"#),
            (Kind::Null(pb::NullValue {}), r#"{"kind":"null"}"#),
            (
                Kind::Bytes(vec![0xde, 0xad]),
                r#"{"kind":"bytes","value":[222,173]}"#,
            ),
            (
                Kind::BigInt(pb::BigIntValue {
                    signed_be: vec![0x01],
                }),
                r#"{"kind":"big_int","value":{"signed_be":[1]}}"#,
            ),
            (
                Kind::BigDecimal(pb::BigDecimalValue {
                    coefficient_signed_be: vec![0x02],
                    scale: 18,
                }),
                r#"{"kind":"big_decimal","value":{"coefficient_signed_be":[2],"scale":18}}"#,
            ),
            (
                Kind::TimestampMicros(7),
                r#"{"kind":"timestamp_micros","value":7}"#,
            ),
        ];
        for (kind, expected) in cases {
            let mirrored = StoreValue::from_wire(&wire(kind)).expect("mirrored");
            assert_eq!(
                serde_json::to_string(&mirrored).expect("serialised"),
                expected
            );
        }
    }

    #[test]
    fn a_value_without_a_kind_is_refused() {
        let error = StoreValue::from_wire(&pb::GraphValue { kind: None })
            .expect_err("a kindless value is not a value");
        assert!(error.to_string().contains("no kind"), "{error}");
    }

    #[test]
    fn entity_ids_keep_their_kind() {
        assert_eq!(
            serde_json::to_string(&StoreEntityId::from(&MaterializedId::Bytes(vec![
                0x00, 0xff
            ])))
            .expect("serialised"),
            r#"{"kind":"bytes","value":[0,255]}"#
        );
        assert_eq!(
            serde_json::to_string(&StoreEntityId::from(&MaterializedId::Int8(-1)))
                .expect("serialised"),
            r#"{"kind":"int8","value":-1}"#
        );
    }
}
