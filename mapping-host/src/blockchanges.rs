//! `pinax.graph.backfill.v1.BlockChanges` emission.
//!
//! Phase 1 could report one modification set per handler, sorted by key, because
//! `EntityCache` collapses writes into a `HashMap`. Phase 2 records the ordered
//! per-save stream instead, from the recorder patched into
//! `vendor/graph-runtime-wasm` beside the proof-of-indexing writes, and projects
//! it onto the canonical frame.
//!
//! Every frame is validated with `backfill_common::validate_block_changes` and
//! round-tripped through `encode_canonical_block_changes` and
//! `decode_canonical_block_changes` before it is written, so a frame that leaves
//! this crate has already been refused-or-accepted by the same code the engine
//! runs on the read side.
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

use std::collections::BTreeMap;
use std::sync::Mutex;

use anyhow::{anyhow, bail, Context, Result};
use backfill_common::pb::pinax::graph::backfill::v1 as pb;
use backfill_common::{
    decode_canonical_block_changes, encode_canonical_block_changes, BlockChangesCompatibility,
    CacheOperation,
};
use graph::data::store::{Entity, Id, Value};
use graph::schema::EntityKey;
use graph_runtime_wasm::op_recorder::EntityOpRecorder;

/// The `BCF1` clock-v1 frame header is fixed width; see `header` below.
pub const BCF1_MAGIC: &[u8; 4] = b"BCF1";
const BCF1_VERSION: u8 = 1;

/// One store effect, in the order the mapping asked for it.
#[derive(Clone, Debug)]
pub enum RecordedOp {
    Set {
        /// The graph-native key, so the runner can read the entity visible
        /// before this handler ran straight out of its store.
        native_key: EntityKey,
        key: pb::EntityKey,
        poi_entity_type: String,
        poi_entity_id: String,
        written_fields: Vec<pb::EntityField>,
        source_causality_region: i32,
        poi_causality_region: String,
    },
    Remove {
        native_key: Option<EntityKey>,
        /// Absent when the typed key never parsed, which Graph Node hashes
        /// before it resolves the schema.
        key: Option<pb::EntityKey>,
        poi_entity_type: String,
        poi_entity_id: String,
        source_causality_region: i32,
        poi_causality_region: String,
    },
}

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
            // `graph`'s `BigDecimal` is normalized on construction: at most 34
            // significant digits and no trailing zeros, which is exactly the
            // canonical form. `as_bigint_and_exponent` returns the (coefficient,
            // scale) pair the wire format defines.
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

/// Storage identity, matching `backfill_common::materialized_key` without
/// needing a validated frame.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
struct LocalKey {
    entity_type: String,
    id: String,
    storage_causality_region: i32,
}

fn local_key(key: &pb::EntityKey) -> LocalKey {
    let id = match key.id.as_ref().and_then(|id| id.value.as_ref()) {
        Some(pb::entity_id::Value::String(value)) => format!("s:{value}"),
        Some(pb::entity_id::Value::Bytes(value)) => format!("b:{}", hex::encode(value)),
        Some(pb::entity_id::Value::Int8(value)) => format!("i:{value}"),
        None => "?".to_string(),
    };
    LocalKey {
        entity_type: key.entity_type.clone(),
        id,
        storage_causality_region: key.storage_causality_region,
    }
}

/// The running `EntityCache` effect for one entity within one handler.
struct LocalEffect {
    baseline: Option<Vec<pb::EntityField>>,
    operation: CacheOperation,
}

/// Accumulates one block's operations across handlers.
pub struct BlockOpsBuilder {
    operations: Vec<pb::EntityOperation>,
    /// The handler that failed in each handler group, if any did.
    ///
    /// A block may hold several: Graph Node keeps processing triggers after a
    /// deterministic error and only discards effects at `transact_block_state`,
    /// so each failing group writes its own `DeterministicError` PoI event. Two
    /// errors in one group is the case Graph Node itself asserts against.
    failures: BTreeMap<u64, u64>,
    /// Ops emitted so far per handler group, for `redacted_events`.
    group_event_counts: BTreeMap<u64, u64>,
}

impl Default for BlockOpsBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl BlockOpsBuilder {
    pub fn new() -> Self {
        BlockOpsBuilder {
            operations: Vec::new(),
            failures: BTreeMap::new(),
            group_event_counts: BTreeMap::new(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.operations.is_empty()
    }

    /// Append one handler's recorded saves.
    ///
    /// `visible_before` reads the get-visible entity for a key as it stood
    /// before this handler ran; the runner backs it with the in-memory store,
    /// which already carries every earlier handler's committed effect.
    pub fn push_handler<F>(
        &mut self,
        handler_group_order: u64,
        source_trigger_order: u64,
        handler_order: u64,
        ops: Vec<RecordedOp>,
        mut visible_before: F,
    ) -> Result<()>
    where
        F: FnMut(&EntityKey) -> Option<Vec<pb::EntityField>>,
    {
        let mut locals: BTreeMap<LocalKey, LocalEffect> = BTreeMap::new();

        for op in ops {
            let index = self.operations.len() as u64;
            let operation = match op {
                RecordedOp::Set {
                    native_key,
                    key,
                    poi_entity_type,
                    poi_entity_id,
                    written_fields,
                    source_causality_region,
                    poi_causality_region,
                } => {
                    let identity = local_key(&key);
                    let effect = locals.entry(identity).or_insert_with(|| LocalEffect {
                        baseline: visible_before(&native_key),
                        operation: CacheOperation::Update(Vec::new()),
                    });
                    // `accumulate` on a fresh `Update(vec![])` is the identity,
                    // so the first save initialises and later saves fold in.
                    effect
                        .operation
                        .accumulate(CacheOperation::Update(written_fields.clone()));
                    let materialized = effect
                        .operation
                        .apply_to(&effect.baseline)
                        .ok_or_else(|| anyhow!("a set must leave the entity visible"))?;

                    pb::EntityOperation {
                        operation_index: index,
                        handler_group_order,
                        source_trigger_order,
                        poi_causality_region: Some(poi_causality_region),
                        handler_order,
                        source_causality_region,
                        operation: Some(pb::entity_operation::Operation::Set(pb::SetEntity {
                            key: Some(key),
                            poi_entity_type,
                            poi_entity_id,
                            written_fields,
                            materialized: Some(pb::EntityFields {
                                fields: materialized,
                            }),
                            // Filled in by `finish`, once the block's error
                            // state is known.
                            store_disposition: pb::StoreDisposition::Unspecified as i32,
                            failure_stage: pb::SetFailureStage::Unspecified as i32,
                        })),
                    }
                }
                RecordedOp::Remove {
                    native_key,
                    key,
                    poi_entity_type,
                    poi_entity_id,
                    source_causality_region,
                    poi_causality_region,
                } => {
                    if let (Some(key), Some(native_key)) = (key.as_ref(), native_key.as_ref()) {
                        let identity = local_key(key);
                        let effect = locals.entry(identity).or_insert_with(|| LocalEffect {
                            baseline: visible_before(native_key),
                            operation: CacheOperation::Update(Vec::new()),
                        });
                        effect.operation.accumulate(CacheOperation::Remove);
                    }
                    pb::EntityOperation {
                        operation_index: index,
                        handler_group_order,
                        source_trigger_order,
                        poi_causality_region: Some(poi_causality_region),
                        handler_order,
                        source_causality_region,
                        operation: Some(pb::entity_operation::Operation::Remove(
                            pb::RemoveEntity {
                                key,
                                poi_entity_type,
                                poi_entity_id,
                                store_disposition: pb::StoreDisposition::Unspecified as i32,
                            },
                        )),
                    }
                }
            };
            self.operations.push(operation);
            *self
                .group_event_counts
                .entry(handler_group_order)
                .or_default() += 1;
        }
        Ok(())
    }

    /// Close a handler group whose handler failed deterministically.
    ///
    /// Graph Node appends one `DeterministicError` PoI event after the whole
    /// group, counting every event since that group's `start_handler` — not only
    /// the discarded ones.
    pub fn push_deterministic_error(
        &mut self,
        handler_group_order: u64,
        source_trigger_order: u64,
        handler_order: u64,
        poi_causality_region: String,
    ) -> Result<()> {
        if self.failures.contains_key(&handler_group_order) {
            bail!("handler group {handler_group_order} already carries a deterministic error");
        }
        let redacted_events = self
            .group_event_counts
            .get(&handler_group_order)
            .copied()
            .unwrap_or(0);
        self.operations.push(pb::EntityOperation {
            operation_index: self.operations.len() as u64,
            handler_group_order,
            source_trigger_order,
            poi_causality_region: Some(poi_causality_region),
            handler_order,
            source_causality_region: 0,
            operation: Some(pb::entity_operation::Operation::DeterministicError(
                pb::DeterministicError { redacted_events },
            )),
        });
        self.failures.insert(handler_group_order, handler_order);
        Ok(())
    }

    /// Assign dispositions and build the frame.
    #[allow(clippy::too_many_arguments)]
    pub fn finish(
        mut self,
        compatibility: &BlockChangesCompatibility,
        block_number: u64,
        block_hash: Vec<u8>,
        mapping_triggered: bool,
        triggered_regions: Vec<String>,
        policy: pb::DeterministicErrorPolicy,
    ) -> Result<pb::BlockChanges> {
        let has_error = !self.failures.is_empty();
        let block_discarded = has_error && policy == pb::DeterministicErrorPolicy::Fatal;

        for operation in &mut self.operations {
            let failed_here = self
                .failures
                .get(&operation.handler_group_order)
                .is_some_and(|handler| *handler == operation.handler_order);
            let disposition = if failed_here {
                pb::StoreDisposition::Discarded
            } else if block_discarded {
                pb::StoreDisposition::BlockDiscarded
            } else {
                pb::StoreDisposition::Committed
            } as i32;
            match operation.operation.as_mut() {
                Some(pb::entity_operation::Operation::Set(set)) => {
                    set.store_disposition = disposition;
                }
                Some(pb::entity_operation::Operation::Remove(remove)) => {
                    remove.store_disposition = disposition;
                }
                Some(pb::entity_operation::Operation::DeterministicError(_)) | None => {}
            }
        }

        let changes = pb::BlockChanges {
            contract: backfill_common::BLOCK_CHANGES_V1_CONTRACT.to_string(),
            compatibility_id: compatibility.to_vec(),
            block_number,
            block_hash,
            mapping_triggered,
            triggered_poi_causality_regions: triggered_regions,
            operations: self.operations,
            deterministic_error_policy: policy as i32,
        };
        Ok(changes)
    }
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
    let length = u32::try_from(payload.len()).context("payload exceeds a BCF1 frame")?;
    let mut frame = Vec::with_capacity(52 + payload.len());
    frame.extend_from_slice(BCF1_MAGIC);
    frame.push(BCF1_VERSION);
    frame.extend_from_slice(&[0, 0, 0]);
    frame.extend_from_slice(&block_number.to_be_bytes());
    frame.extend_from_slice(block_hash);
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(payload);
    Ok(frame)
}
