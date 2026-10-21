//! Family-neutral construction of ordered BlockChanges operations.
//!
//! Moved from the mapping-host oracle, with only its lookup key made generic.
//! A consumer supplies the entity visible before each handler. Saves accumulate
//! against that fixed baseline through the shared `CacheOperation` algebra;
//! sequentially merging each materialized save would change null semantics.
//!
//! `finish` assigns store dispositions but does not certify a frame. Always
//! seal with `encode_canonical_block_changes`, which checks ordering, domains,
//! materialized values, error groups, and the selected compatibility contract.

use crate::{pb::pinax::graph::backfill::v1 as pb, BlockChangesCompatibility, CacheOperation};
use std::{collections::BTreeMap, fmt};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BuilderError(pub String);
impl fmt::Display for BuilderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for BuilderError {}
type Result<T> = std::result::Result<T, BuilderError>;

#[derive(Clone, Debug)]
pub enum RecordedOp<K> {
    Set {
        /// The consumer lookup key for the same wire identity. The mapping-host
        /// uses its Graph Node key; a native reducer may use the wire key.
        native_key: K,
        key: pb::EntityKey,
        poi_entity_type: String,
        poi_entity_id: String,
        written_fields: Vec<pb::EntityField>,
        source_causality_region: i32,
        poi_causality_region: String,
    },
    Remove {
        native_key: Option<K>,
        /// Absent when the typed key never parsed, which Graph Node hashes
        /// before it resolves the schema.
        key: Option<pb::EntityKey>,
        poi_entity_type: String,
        poi_entity_id: String,
        source_causality_region: i32,
        poi_causality_region: String,
    },
}

/// Storage identity, matching `crate::materialized_key` without
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
    pub fn push_handler<K, F>(
        &mut self,
        handler_group_order: u64,
        source_trigger_order: u64,
        handler_order: u64,
        ops: Vec<RecordedOp<K>>,
        mut visible_before: F,
    ) -> Result<()>
    where
        F: FnMut(&K) -> Option<Vec<pb::EntityField>>,
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
                    let materialized =
                        effect.operation.apply_to(&effect.baseline).ok_or_else(|| {
                            BuilderError("a set must leave the entity visible".into())
                        })?;

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
            return Err(BuilderError(format!(
                "handler group {handler_group_order} already carries a deterministic error"
            )));
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
            contract: crate::BLOCK_CHANGES_V1_CONTRACT.to_string(),
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
