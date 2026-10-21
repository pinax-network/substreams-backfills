//! Fail-closed semantic and canonical-wire validation for BlockChanges v1.

use crate::descriptor::DescriptorCapabilities;
use crate::pb::pinax::graph::backfill::v1::{
    entity_id, entity_operation, graph_value, BlockChanges, DeterministicErrorPolicy, EntityField,
    EntityKey, GraphValue, RemoveEntity, SetEntity, SetFailureStage, StoreDisposition,
};
use num_bigint::BigInt;
use prost::Message;
use sha2::{Digest, Sha256};
use std::{collections::HashMap, error::Error, fmt};

pub const BLOCK_CHANGES_V1_CONTRACT: &str = "pinax.graph.backfill.block-changes/v1";
const COMPATIBILITY_ID_LEN: usize = 32;
const GRAPH_BIGINT_MAX_BITS: u64 = 435_412;
/// Graph Node v0.44 `BigDecimal::MAX_SIGNFICANT_DIGITS`: the precision its
/// `normalized()` passes to bigdecimal 0.1.2's `with_prec`.
const GRAPH_DECIMAL_PRECISION: u64 = 34;
/// The literal divisor bigdecimal 0.1.2's `count_decimal_digits` uses to turn a
/// bit length into a digit estimate. It is deliberately not
/// `std::f64::consts::LOG2_10`: the port has to divide by the same `f64`.
#[allow(clippy::approx_constant)]
const BIGDECIMAL_0_1_2_BITS_PER_DIGIT: f64 = 3.3219280949;
const GRAPH_DECIMAL_MIN_SCALE: i64 = -6_144;
const GRAPH_DECIMAL_MAX_SCALE: i64 = 6_143;
// Prost 0.13 enforces a 100-message decode recursion limit. Each list layer
// consumes a ListValue and child GraphValue frame in addition to the envelope,
// so 32 leaves a deliberate round-trip safety margin.
const MAX_VALUE_DEPTH: usize = 32;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockChangesCompatibility {
    id: [u8; COMPATIBILITY_ID_LEN],
    deterministic_error_policy: DeterministicErrorPolicy,
    expected_poi_causality_region: String,
    capabilities: Option<DescriptorCapabilities>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CompatibilityDescriptorError {
    Json(String),
    Contract,
    DescriptorVersion,
    DeterministicErrorPolicy,
    Network,
    ExpectedPoiCausalityRegion,
    PoiCausalityRegionNetworkMismatch,
    Capabilities(String),
}

impl BlockChangesCompatibility {
    pub fn from_descriptor(descriptor_bytes: &[u8]) -> Result<Self, CompatibilityDescriptorError> {
        let descriptor: serde_json::Value = serde_json::from_slice(descriptor_bytes)
            .map_err(|error| CompatibilityDescriptorError::Json(error.to_string()))?;
        let object = descriptor
            .as_object()
            .ok_or(CompatibilityDescriptorError::Json(
                "descriptor root is not an object".to_owned(),
            ))?;
        if object.get("contract").and_then(serde_json::Value::as_str)
            != Some(BLOCK_CHANGES_V1_CONTRACT)
        {
            return Err(CompatibilityDescriptorError::Contract);
        }
        let capabilities = match object
            .get("descriptor_version")
            .and_then(serde_json::Value::as_u64)
        {
            Some(1) => None,
            Some(2) => {
                crate::descriptor::validate_unique_json(descriptor_bytes)
                    .map_err(CompatibilityDescriptorError::Json)?;
                Some(
                    DescriptorCapabilities::from_descriptor(&descriptor)
                        .map_err(CompatibilityDescriptorError::Capabilities)?,
                )
            }
            _ => return Err(CompatibilityDescriptorError::DescriptorVersion),
        };
        let deterministic_error_policy = match object
            .get("deterministic_error_policy")
            .and_then(serde_json::Value::as_str)
        {
            Some("fatal") => DeterministicErrorPolicy::Fatal,
            Some("non_fatal") => DeterministicErrorPolicy::NonFatal,
            _ => return Err(CompatibilityDescriptorError::DeterministicErrorPolicy),
        };
        let network = object
            .get("network")
            .and_then(serde_json::Value::as_str)
            .filter(|network| !network.is_empty())
            .ok_or(CompatibilityDescriptorError::Network)?;
        let expected_poi_causality_region = object
            .get("expected_poi_causality_region")
            .and_then(serde_json::Value::as_str)
            .filter(|region| !region.is_empty())
            .ok_or(CompatibilityDescriptorError::ExpectedPoiCausalityRegion)?;
        if expected_poi_causality_region != format!("ethereum/{network}") {
            return Err(CompatibilityDescriptorError::PoiCausalityRegionNetworkMismatch);
        }

        let digest = Sha256::digest(descriptor_bytes);
        let mut id = [0; COMPATIBILITY_ID_LEN];
        id.copy_from_slice(&digest);
        Ok(Self {
            id,
            deterministic_error_policy,
            expected_poi_causality_region: expected_poi_causality_region.to_owned(),
            capabilities,
        })
    }

    pub const fn id(&self) -> &[u8; COMPATIBILITY_ID_LEN] {
        &self.id
    }

    pub fn deterministic_error_policy(&self) -> DeterministicErrorPolicy {
        self.deterministic_error_policy
    }

    pub fn expected_poi_causality_region(&self) -> &str {
        &self.expected_poi_causality_region
    }

    pub fn to_vec(&self) -> Vec<u8> {
        self.id.to_vec()
    }

    /// Absent for v1 descriptors, whose validation and raw-byte identity are unchanged.
    pub fn capabilities(&self) -> Option<&DescriptorCapabilities> {
        self.capabilities.as_ref()
    }
}

impl AsRef<[u8]> for BlockChangesCompatibility {
    fn as_ref(&self) -> &[u8] {
        &self.id
    }
}

impl fmt::Display for CompatibilityDescriptorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Json(error) => {
                write!(formatter, "invalid compatibility descriptor JSON: {error}")
            }
            Self::Contract => write!(formatter, "compatibility descriptor contract drift"),
            Self::DescriptorVersion => {
                write!(formatter, "compatibility descriptor version is not 1 or 2")
            }
            Self::DeterministicErrorPolicy => write!(
                formatter,
                "compatibility descriptor deterministic-error policy is missing or unknown"
            ),
            Self::Network => write!(
                formatter,
                "compatibility descriptor network is missing or empty"
            ),
            Self::ExpectedPoiCausalityRegion => write!(
                formatter,
                "compatibility descriptor expected PoI causality region is missing or empty"
            ),
            Self::PoiCausalityRegionNetworkMismatch => write!(
                formatter,
                "compatibility descriptor PoI causality region does not match its network"
            ),
            Self::Capabilities(error) => {
                write!(formatter, "invalid descriptor v2 capabilities: {error}")
            }
        }
    }
}

impl Error for CompatibilityDescriptorError {}

/// Storage identity of one entity as Graph Node's `EntityCache` keys it.
///
/// Exported so consumers replay the same merge algebra the validator uses
/// instead of restating it; two independent implementations of these
/// semantics is the failure mode this contract exists to prevent.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct MaterializedKey {
    pub entity_type: String,
    pub id: MaterializedId,
    pub storage_causality_region: i32,
}

/// Typed entity id as stored, preserving the wire representation exactly.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MaterializedId {
    String(String),
    Bytes(Vec<u8>),
    Int8(i64),
}

/// How a written top-level `Null` merges into a predecessor entity.
///
/// `Remove` is Graph Node's partial-update behaviour against an existing
/// entity; `Preserve` keeps the explicit Null get-visible when an absent or
/// removed entity is overwritten.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NullMergeMode {
    Remove,
    Preserve,
}

/// One entity's accumulated `EntityCache` effect within a handler.
#[derive(Clone, Debug, PartialEq)]
pub enum CacheOperation {
    Remove,
    Update(Vec<EntityField>),
    Overwrite(Vec<EntityField>),
}

#[derive(Clone, Debug)]
struct ReplayCandidate {
    baseline: Option<Vec<EntityField>>,
    main_operation: Option<CacheOperation>,
}

#[derive(Clone, Debug)]
enum MainReplayState {
    Unknown,
    Known(Vec<ReplayCandidate>),
}

#[derive(Clone, Debug)]
struct LocalReplay {
    candidates: Vec<ReplayCandidate>,
    operation: CacheOperation,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
enum HistoryDomainKey {
    Onchain(MaterializedKey),
    Offchain(u64, MaterializedKey),
}

#[derive(Clone, Debug)]
struct ActiveHandler {
    handler_group_order: u64,
    handler_order: u64,
    source_causality_region: i32,
    disposition: StoreDisposition,
    locals: HashMap<HistoryDomainKey, LocalReplay>,
}

#[derive(Default)]
struct HistoryStates {
    onchain: HashMap<MaterializedKey, MainReplayState>,
    offchain: HashMap<(u64, MaterializedKey), MainReplayState>,
    active_handler: Option<ActiveHandler>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ValidationError {
    Decode(String),
    NonCanonicalEncoding,
    Contract,
    CompatibilityIdLength {
        actual: usize,
    },
    ZeroCompatibilityId,
    CompatibilityIdMismatch,
    UnknownDeterministicErrorPolicy {
        actual: i32,
    },
    DeterministicErrorPolicyMismatch,
    PoiCausalityRegionCompatibility,
    BlockNumberOutOfRange {
        actual: u64,
    },
    BlockHashLength {
        actual: usize,
    },
    MappingTriggerMismatch,
    EmptyTriggeredPoiCausalityRegion {
        region_index: usize,
    },
    TriggeredPoiCausalityRegionOrder {
        region_index: usize,
    },
    OperationIndex {
        expected: u64,
        actual: u64,
    },
    HandlerGroupOrder {
        previous: u64,
        actual: u64,
    },
    HandlerOrder {
        handler_group_order: u64,
        previous: u64,
        actual: u64,
    },
    HandlerGroupPoiRegionMismatch {
        operation_index: u64,
    },
    HandlerGroupSourceTriggerMismatch {
        operation_index: u64,
    },
    HandlerGroupSourceCausalityMismatch {
        operation_index: u64,
    },
    EmptyPoiCausalityRegion {
        operation_index: u64,
    },
    NegativeSourceCausalityRegion {
        operation_index: u64,
        actual: i32,
    },
    PoiParticipationMismatch {
        operation_index: u64,
    },
    OperationRegionNotTriggered {
        operation_index: u64,
    },
    MissingOperation {
        operation_index: u64,
    },
    OperationAfterDeterministicError {
        operation_index: u64,
    },
    OffchainDeterministicError {
        operation_index: u64,
    },
    OperationAfterTerminalHostFailure {
        operation_index: u64,
        terminal_operation_index: u64,
    },
    DeterministicErrorRedaction {
        operation_index: u64,
        expected: u64,
        actual: u64,
    },
    DiscardedWithoutDeterministicError {
        operation_index: u64,
    },
    HandlerDispositionMismatch {
        operation_index: u64,
    },
    UnknownStoreDisposition {
        operation_index: u64,
        actual: i32,
    },
    MissingEntityKey {
        operation_index: u64,
    },
    CommittedSetMissingMaterialized {
        operation_index: u64,
    },
    SetFailureStageMismatch {
        operation_index: u64,
        actual: i32,
    },
    CommittedRemoveMissingKey {
        operation_index: u64,
    },
    EmptyEntityType {
        operation_index: u64,
    },
    InvalidGraphQlName {
        operation_index: u64,
        context: &'static str,
        name: String,
    },
    NegativeStorageCausalityRegion {
        operation_index: u64,
        actual: i32,
    },
    EntitySourceCausalityMismatch {
        operation_index: u64,
    },
    MissingEntityId {
        operation_index: u64,
    },
    EmptyPoiEntityType {
        operation_index: u64,
    },
    SetPoiEntityTypeMismatch {
        operation_index: u64,
    },
    SetPoiEntityIdMismatch {
        operation_index: u64,
    },
    RemovePoiEntityTypeMismatch {
        operation_index: u64,
    },
    RemovePoiEntityIdMismatch {
        operation_index: u64,
    },
    EmptyFieldName {
        operation_index: u64,
        set: &'static str,
    },
    ReservedField {
        operation_index: u64,
        set: &'static str,
    },
    FieldOrder {
        operation_index: u64,
        set: &'static str,
    },
    MissingFieldValue {
        operation_index: u64,
        field: String,
    },
    MaterializedProjection {
        operation_index: u64,
        field: String,
    },
    MaterializedHistoryMismatch {
        operation_index: u64,
    },
    MissingIdField {
        operation_index: u64,
        set: &'static str,
    },
    IdFieldMismatch {
        operation_index: u64,
        set: &'static str,
    },
    InvalidSignedBigEndian {
        operation_index: u64,
        field: String,
    },
    BigIntTooLarge {
        operation_index: u64,
        field: String,
    },
    NonCanonicalZeroDecimal {
        operation_index: u64,
        field: String,
    },
    DecimalScale {
        operation_index: u64,
        field: String,
    },
    DecimalPrecision {
        operation_index: u64,
        field: String,
    },
    NonNormalizedDecimal {
        operation_index: u64,
        field: String,
    },
    ValueNestingTooDeep {
        operation_index: u64,
        field: String,
    },
    InvalidTimestamp {
        operation_index: u64,
        field: String,
    },
}

impl fmt::Display for ValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Decode(error) => write!(formatter, "invalid BlockChanges protobuf: {error}"),
            Self::NonCanonicalEncoding => write!(formatter, "noncanonical BlockChanges protobuf"),
            Self::Contract => write!(formatter, "BlockChanges contract identifier drift"),
            Self::CompatibilityIdLength { actual } => write!(
                formatter,
                "BlockChanges compatibility id has {actual} bytes instead of 32"
            ),
            Self::ZeroCompatibilityId => {
                write!(formatter, "BlockChanges compatibility id is an all-zero placeholder")
            }
            Self::CompatibilityIdMismatch => write!(
                formatter,
                "BlockChanges compatibility id does not match the expected producer"
            ),
            Self::UnknownDeterministicErrorPolicy { actual } => write!(
                formatter,
                "BlockChanges deterministic-error policy {actual} is unspecified or unknown"
            ),
            Self::DeterministicErrorPolicyMismatch => write!(
                formatter,
                "BlockChanges deterministic-error policy differs from the expected compatibility descriptor"
            ),
            Self::PoiCausalityRegionCompatibility => write!(
                formatter,
                "BlockChanges triggered PoI regions differ from the expected compatibility descriptor"
            ),
            Self::BlockNumberOutOfRange { actual } => write!(
                formatter,
                "BlockChanges block number {actual} exceeds Graph Node's i32 range"
            ),
            Self::BlockHashLength { actual } => write!(
                formatter,
                "BlockChanges block hash has {actual} bytes instead of 32"
            ),
            Self::MappingTriggerMismatch => write!(
                formatter,
                "BlockChanges mapping_triggered disagrees with its triggered PoI regions"
            ),
            Self::EmptyTriggeredPoiCausalityRegion { region_index } => write!(
                formatter,
                "BlockChanges triggered PoI causality region {region_index} is empty"
            ),
            Self::TriggeredPoiCausalityRegionOrder { region_index } => write!(
                formatter,
                "BlockChanges triggered PoI causality region {region_index} is not strictly sorted"
            ),
            Self::OperationIndex { expected, actual } => write!(
                formatter,
                "BlockChanges operation index is not dense: expected {expected}, got {actual}"
            ),
            Self::HandlerGroupOrder { previous, actual } => write!(
                formatter,
                "BlockChanges handler group order regressed from {previous} to {actual}"
            ),
            Self::HandlerOrder {
                handler_group_order,
                previous,
                actual,
            } => write!(
                formatter,
                "BlockChanges handler order for group {handler_group_order} regressed from {previous} to {actual}"
            ),
            Self::HandlerGroupPoiRegionMismatch { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} changes PoI participation or region within one handler group"
            ),
            Self::HandlerGroupSourceTriggerMismatch { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} changes source trigger order within one handler group"
            ),
            Self::HandlerGroupSourceCausalityMismatch { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} changes source causality region within one handler group"
            ),
            Self::EmptyPoiCausalityRegion { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} has an empty PoI causality region"
            ),
            Self::NegativeSourceCausalityRegion {
                operation_index,
                actual,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} has negative source causality region {actual}"
            ),
            Self::PoiParticipationMismatch { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} PoI participation disagrees with its source causality region"
            ),
            Self::OperationRegionNotTriggered { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} uses a PoI region not listed by the block"
            ),
            Self::MissingOperation { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} has no operation payload"
            ),
            Self::OperationAfterDeterministicError { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} follows a deterministic error in the same handler group"
            ),
            Self::OffchainDeterministicError { operation_index } => write!(
                formatter,
                "BlockChanges deterministic error {operation_index} is offchain and makes the block inapplicable"
            ),
            Self::OperationAfterTerminalHostFailure {
                operation_index,
                terminal_operation_index,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} follows terminal failed host call {terminal_operation_index} in the same handler"
            ),
            Self::DeterministicErrorRedaction {
                operation_index,
                expected,
                actual,
            } => write!(
                formatter,
                "BlockChanges deterministic error {operation_index} redacts {actual} events instead of {expected}"
            ),
            Self::DiscardedWithoutDeterministicError { operation_index } => write!(
                formatter,
                "BlockChanges discarded operation {operation_index} has no matching deterministic error"
            ),
            Self::HandlerDispositionMismatch { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} disposition disagrees with its handler outcome"
            ),
            Self::UnknownStoreDisposition {
                operation_index,
                actual,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} has invalid store disposition {actual}"
            ),
            Self::MissingEntityKey { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} has no entity key"
            ),
            Self::CommittedSetMissingMaterialized { operation_index } => write!(
                formatter,
                "BlockChanges committed set {operation_index} has no materialized boundary"
            ),
            Self::SetFailureStageMismatch {
                operation_index,
                actual,
            } => write!(
                formatter,
                "BlockChanges set {operation_index} has failure stage {actual} inconsistent with its materialized boundary"
            ),
            Self::CommittedRemoveMissingKey { operation_index } => write!(
                formatter,
                "BlockChanges committed remove {operation_index} has no typed entity key"
            ),
            Self::EmptyEntityType { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} has an empty storage entity type"
            ),
            Self::InvalidGraphQlName {
                operation_index,
                context,
                name,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} {context} {name:?} is not a GraphQL name"
            ),
            Self::NegativeStorageCausalityRegion {
                operation_index,
                actual,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} has negative storage causality region {actual}"
            ),
            Self::EntitySourceCausalityMismatch { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} entity and source causality regions differ"
            ),
            Self::MissingEntityId { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} has no typed entity id"
            ),
            Self::EmptyPoiEntityType { operation_index } => write!(
                formatter,
                "BlockChanges set operation {operation_index} has an empty PoI entity type"
            ),
            Self::SetPoiEntityTypeMismatch { operation_index } => write!(
                formatter,
                "BlockChanges set operation {operation_index} PoI type differs from its storage key"
            ),
            Self::SetPoiEntityIdMismatch { operation_index } => write!(
                formatter,
                "BlockChanges set operation {operation_index} PoI id is not the typed key's canonical display"
            ),
            Self::RemovePoiEntityTypeMismatch { operation_index } => write!(
                formatter,
                "BlockChanges remove operation {operation_index} PoI type differs from its storage key"
            ),
            Self::RemovePoiEntityIdMismatch { operation_index } => write!(
                formatter,
                "BlockChanges remove operation {operation_index} PoI id does not parse to its typed key"
            ),
            Self::EmptyFieldName {
                operation_index,
                set,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} {set} fields contain an empty name"
            ),
            Self::ReservedField {
                operation_index,
                set,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} {set} fields expose reserved Graph Node field vid"
            ),
            Self::FieldOrder {
                operation_index,
                set,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} {set} fields are not strictly sorted"
            ),
            Self::MissingFieldValue {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} has no typed value"
            ),
            Self::MaterializedProjection {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} materialized state disagrees with written field {field:?}"
            ),
            Self::MaterializedHistoryMismatch { operation_index } => write!(
                formatter,
                "BlockChanges operation {operation_index} materialized state disagrees with the known in-frame predecessor state"
            ),
            Self::MissingIdField {
                operation_index,
                set,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} {set} fields omit id"
            ),
            Self::IdFieldMismatch {
                operation_index,
                set,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} {set} id does not match the typed key"
            ),
            Self::InvalidSignedBigEndian {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} has noncanonical signed bytes"
            ),
            Self::BigIntTooLarge {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} exceeds Graph Node's BigInt limit"
            ),
            Self::NonCanonicalZeroDecimal {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} has a noncanonical decimal zero"
            ),
            Self::DecimalScale {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} has a decimal scale outside Graph Node's range"
            ),
            Self::DecimalPrecision {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} has a decimal coefficient Graph Node v0.44 normalization would round: more than 34 digits if positive, a magnitude of 2^116 or more if negative"
            ),
            Self::NonNormalizedDecimal {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} has a decimal coefficient ending in zero"
            ),
            Self::ValueNestingTooDeep {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} exceeds the value nesting limit"
            ),
            Self::InvalidTimestamp {
                operation_index,
                field,
            } => write!(
                formatter,
                "BlockChanges operation {operation_index} field {field:?} is outside Graph Node's timestamp domain"
            ),
        }
    }
}

impl Error for ValidationError {}

pub fn encode_canonical_block_changes(
    changes: &BlockChanges,
    expected_compatibility: &BlockChangesCompatibility,
) -> Result<Vec<u8>, ValidationError> {
    validate_block_changes(changes, expected_compatibility)?;
    Ok(changes.encode_to_vec())
}

pub fn decode_canonical_block_changes(
    bytes: &[u8],
    expected_compatibility: &BlockChangesCompatibility,
) -> Result<BlockChanges, ValidationError> {
    let changes =
        BlockChanges::decode(bytes).map_err(|error| ValidationError::Decode(error.to_string()))?;
    validate_block_changes(&changes, expected_compatibility)?;
    if changes.encode_to_vec() != bytes {
        return Err(ValidationError::NonCanonicalEncoding);
    }
    Ok(changes)
}

pub fn validate_block_changes(
    changes: &BlockChanges,
    expected_compatibility: &BlockChangesCompatibility,
) -> Result<(), ValidationError> {
    if changes.contract != BLOCK_CHANGES_V1_CONTRACT {
        return Err(ValidationError::Contract);
    }
    if changes.compatibility_id.len() != COMPATIBILITY_ID_LEN {
        return Err(ValidationError::CompatibilityIdLength {
            actual: changes.compatibility_id.len(),
        });
    }
    if changes.compatibility_id.iter().all(|byte| *byte == 0) {
        return Err(ValidationError::ZeroCompatibilityId);
    }
    if changes.compatibility_id.as_slice() != expected_compatibility.id() {
        return Err(ValidationError::CompatibilityIdMismatch);
    }
    let deterministic_error_policy =
        match DeterministicErrorPolicy::try_from(changes.deterministic_error_policy) {
            Ok(DeterministicErrorPolicy::Fatal) => DeterministicErrorPolicy::Fatal,
            Ok(DeterministicErrorPolicy::NonFatal) => DeterministicErrorPolicy::NonFatal,
            Ok(DeterministicErrorPolicy::Unspecified) | Err(_) => {
                return Err(ValidationError::UnknownDeterministicErrorPolicy {
                    actual: changes.deterministic_error_policy,
                });
            }
        };
    if deterministic_error_policy != expected_compatibility.deterministic_error_policy() {
        return Err(ValidationError::DeterministicErrorPolicyMismatch);
    }
    if changes.block_number > i32::MAX as u64 {
        return Err(ValidationError::BlockNumberOutOfRange {
            actual: changes.block_number,
        });
    }
    if changes.block_hash.len() != 32 {
        return Err(ValidationError::BlockHashLength {
            actual: changes.block_hash.len(),
        });
    }
    validate_triggered_regions(changes)?;
    if !changes.triggered_poi_causality_regions.is_empty()
        && (changes.triggered_poi_causality_regions.len() != 1
            || changes.triggered_poi_causality_regions[0]
                != expected_compatibility.expected_poi_causality_region())
    {
        return Err(ValidationError::PoiCausalityRegionCompatibility);
    }

    let mut previous_handler_group_order = None;
    let mut event_counts: HashMap<(u64, &str), u64> = HashMap::new();
    let mut previous_handler_orders: HashMap<u64, u64> = HashMap::new();
    let mut deterministic_errors: HashMap<u64, u64> = HashMap::new();
    let mut group_poi_regions: HashMap<u64, Option<&str>> = HashMap::new();
    let mut group_source_triggers: HashMap<u64, u64> = HashMap::new();
    let mut group_source_causality_regions: HashMap<u64, i32> = HashMap::new();
    let mut terminal_host_failures: HashMap<(u64, u64), u64> = HashMap::new();
    let mut history_states = HistoryStates::default();
    let mut handler_effects = Vec::new();

    for (expected_index, operation) in changes.operations.iter().enumerate() {
        let expected_index = expected_index as u64;
        if operation.operation_index != expected_index {
            return Err(ValidationError::OperationIndex {
                expected: expected_index,
                actual: operation.operation_index,
            });
        }
        if let Some(previous) = previous_handler_group_order {
            if operation.handler_group_order < previous {
                return Err(ValidationError::HandlerGroupOrder {
                    previous,
                    actual: operation.handler_group_order,
                });
            }
        }
        previous_handler_group_order = Some(operation.handler_group_order);

        if deterministic_errors.contains_key(&operation.handler_group_order) {
            return Err(ValidationError::OperationAfterDeterministicError {
                operation_index: expected_index,
            });
        }

        let poi_region = operation.poi_causality_region.as_deref();
        if operation.source_causality_region < 0 {
            return Err(ValidationError::NegativeSourceCausalityRegion {
                operation_index: expected_index,
                actual: operation.source_causality_region,
            });
        }
        if (operation.source_causality_region == 0) != poi_region.is_some() {
            return Err(ValidationError::PoiParticipationMismatch {
                operation_index: expected_index,
            });
        }
        if poi_region == Some("") {
            return Err(ValidationError::EmptyPoiCausalityRegion {
                operation_index: expected_index,
            });
        }
        if let Some(region) = poi_region {
            if changes
                .triggered_poi_causality_regions
                .binary_search_by(|candidate| candidate.as_str().cmp(region))
                .is_err()
            {
                return Err(ValidationError::OperationRegionNotTriggered {
                    operation_index: expected_index,
                });
            }
        }
        if group_poi_regions
            .get(&operation.handler_group_order)
            .is_some_and(|expected| *expected != poi_region)
        {
            return Err(ValidationError::HandlerGroupPoiRegionMismatch {
                operation_index: expected_index,
            });
        }
        group_poi_regions
            .entry(operation.handler_group_order)
            .or_insert(poi_region);
        if group_source_triggers
            .get(&operation.handler_group_order)
            .is_some_and(|expected| *expected != operation.source_trigger_order)
        {
            return Err(ValidationError::HandlerGroupSourceTriggerMismatch {
                operation_index: expected_index,
            });
        }
        group_source_triggers
            .entry(operation.handler_group_order)
            .or_insert(operation.source_trigger_order);
        if group_source_causality_regions
            .get(&operation.handler_group_order)
            .is_some_and(|expected| *expected != operation.source_causality_region)
        {
            return Err(ValidationError::HandlerGroupSourceCausalityMismatch {
                operation_index: expected_index,
            });
        }
        group_source_causality_regions
            .entry(operation.handler_group_order)
            .or_insert(operation.source_causality_region);

        match operation.operation.as_ref() {
            Some(entity_operation::Operation::Set(set)) => {
                validate_handler_order(
                    operation.handler_group_order,
                    operation.handler_order,
                    &mut previous_handler_orders,
                )?;
                if let Some(terminal_operation_index) = terminal_host_failures
                    .get(&(operation.handler_group_order, operation.handler_order))
                {
                    return Err(ValidationError::OperationAfterTerminalHostFailure {
                        operation_index: expected_index,
                        terminal_operation_index: *terminal_operation_index,
                    });
                }
                let disposition =
                    validate_set(expected_index, operation.source_causality_region, set)?;
                validate_set_history(
                    expected_index,
                    operation.handler_group_order,
                    operation.handler_order,
                    operation.source_causality_region,
                    disposition,
                    set,
                    &mut history_states,
                )?;
                handler_effects.push((
                    expected_index,
                    operation.handler_group_order,
                    operation.handler_order,
                    disposition,
                ));
                if disposition == StoreDisposition::Discarded && set.materialized.is_none() {
                    terminal_host_failures.insert(
                        (operation.handler_group_order, operation.handler_order),
                        expected_index,
                    );
                }
                if let Some(region) = poi_region {
                    *event_counts
                        .entry((operation.handler_group_order, region))
                        .or_default() += 1;
                }
            }
            Some(entity_operation::Operation::Remove(remove)) => {
                validate_handler_order(
                    operation.handler_group_order,
                    operation.handler_order,
                    &mut previous_handler_orders,
                )?;
                if let Some(terminal_operation_index) = terminal_host_failures
                    .get(&(operation.handler_group_order, operation.handler_order))
                {
                    return Err(ValidationError::OperationAfterTerminalHostFailure {
                        operation_index: expected_index,
                        terminal_operation_index: *terminal_operation_index,
                    });
                }
                let disposition =
                    validate_remove(expected_index, operation.source_causality_region, remove)?;
                record_remove_history(
                    operation.handler_group_order,
                    operation.handler_order,
                    operation.source_causality_region,
                    disposition,
                    remove,
                    &mut history_states,
                )?;
                handler_effects.push((
                    expected_index,
                    operation.handler_group_order,
                    operation.handler_order,
                    disposition,
                ));
                if disposition == StoreDisposition::Discarded && remove.key.is_none() {
                    terminal_host_failures.insert(
                        (operation.handler_group_order, operation.handler_order),
                        expected_index,
                    );
                }
                if let Some(region) = poi_region {
                    *event_counts
                        .entry((operation.handler_group_order, region))
                        .or_default() += 1;
                }
            }
            Some(entity_operation::Operation::DeterministicError(error)) => {
                let Some(region) = poi_region else {
                    return Err(ValidationError::OffchainDeterministicError {
                        operation_index: expected_index,
                    });
                };
                let expected = event_counts
                    .get(&(operation.handler_group_order, region))
                    .copied()
                    .unwrap_or(0);
                if error.redacted_events != expected {
                    return Err(ValidationError::DeterministicErrorRedaction {
                        operation_index: expected_index,
                        expected,
                        actual: error.redacted_events,
                    });
                }
                deterministic_errors.insert(operation.handler_group_order, operation.handler_order);
            }
            None => {
                return Err(ValidationError::MissingOperation {
                    operation_index: expected_index,
                });
            }
        }
    }

    let has_deterministic_error = !deterministic_errors.is_empty();
    for (operation_index, handler_group_order, handler_order, disposition) in handler_effects {
        let failed_handler = deterministic_errors.get(&handler_group_order).copied();
        if disposition == StoreDisposition::Discarded && failed_handler.is_none() {
            return Err(ValidationError::DiscardedWithoutDeterministicError { operation_index });
        }
        let expected = if failed_handler == Some(handler_order) {
            StoreDisposition::Discarded
        } else if has_deterministic_error
            && deterministic_error_policy == DeterministicErrorPolicy::Fatal
        {
            StoreDisposition::BlockDiscarded
        } else {
            StoreDisposition::Committed
        };
        if disposition != expected {
            return Err(ValidationError::HandlerDispositionMismatch { operation_index });
        }
    }

    Ok(())
}

fn validate_handler_order(
    handler_group_order: u64,
    handler_order: u64,
    previous_handler_orders: &mut HashMap<u64, u64>,
) -> Result<(), ValidationError> {
    if let Some(previous) = previous_handler_orders.insert(handler_group_order, handler_order) {
        if handler_order < previous {
            return Err(ValidationError::HandlerOrder {
                handler_group_order,
                previous,
                actual: handler_order,
            });
        }
    }
    Ok(())
}

fn validate_triggered_regions(changes: &BlockChanges) -> Result<(), ValidationError> {
    if !changes.mapping_triggered
        && (!changes.triggered_poi_causality_regions.is_empty() || !changes.operations.is_empty())
    {
        return Err(ValidationError::MappingTriggerMismatch);
    }

    let mut previous: Option<&str> = None;
    for (region_index, region) in changes.triggered_poi_causality_regions.iter().enumerate() {
        if region.is_empty() {
            return Err(ValidationError::EmptyTriggeredPoiCausalityRegion { region_index });
        }
        if previous.is_some_and(|value| value >= region.as_str()) {
            return Err(ValidationError::TriggeredPoiCausalityRegionOrder { region_index });
        }
        previous = Some(region);
    }
    Ok(())
}

fn validate_set(
    operation_index: u64,
    source_causality_region: i32,
    set: &SetEntity,
) -> Result<StoreDisposition, ValidationError> {
    let disposition = validate_disposition(operation_index, set.store_disposition)?;
    let key = set
        .key
        .as_ref()
        .ok_or(ValidationError::MissingEntityKey { operation_index })?;
    let id = validate_key(operation_index, Some(key))?;
    if key.storage_causality_region != source_causality_region {
        return Err(ValidationError::EntitySourceCausalityMismatch { operation_index });
    }
    if set.poi_entity_type.is_empty() {
        return Err(ValidationError::EmptyPoiEntityType { operation_index });
    }
    validate_graphql_name(operation_index, "PoI entity type", &set.poi_entity_type)?;
    if set.poi_entity_type != key.entity_type {
        return Err(ValidationError::SetPoiEntityTypeMismatch { operation_index });
    }
    if set.poi_entity_id != canonical_id(id) {
        return Err(ValidationError::SetPoiEntityIdMismatch { operation_index });
    }
    validate_fields(operation_index, "written", &set.written_fields)?;
    validate_id_field(operation_index, "written", id, &set.written_fields)?;
    let failure_stage = SetFailureStage::try_from(set.failure_stage).map_err(|_| {
        ValidationError::SetFailureStageMismatch {
            operation_index,
            actual: set.failure_stage,
        }
    })?;
    match set.materialized.as_ref() {
        Some(materialized) => {
            if failure_stage != SetFailureStage::Unspecified {
                return Err(ValidationError::SetFailureStageMismatch {
                    operation_index,
                    actual: set.failure_stage,
                });
            }
            validate_fields(operation_index, "materialized", &materialized.fields)?;
            validate_id_field(operation_index, "materialized", id, &materialized.fields)?;
            validate_projection(operation_index, &set.written_fields, &materialized.fields)?;
        }
        None if matches!(
            disposition,
            StoreDisposition::Committed | StoreDisposition::BlockDiscarded
        ) =>
        {
            return Err(ValidationError::CommittedSetMissingMaterialized { operation_index });
        }
        None if failure_stage == SetFailureStage::Unspecified => {
            return Err(ValidationError::SetFailureStageMismatch {
                operation_index,
                actual: set.failure_stage,
            });
        }
        None => {}
    }
    Ok(disposition)
}

fn validate_remove(
    operation_index: u64,
    source_causality_region: i32,
    remove: &RemoveEntity,
) -> Result<StoreDisposition, ValidationError> {
    let disposition = validate_disposition(operation_index, remove.store_disposition)?;
    let Some(key) = remove.key.as_ref() else {
        if matches!(
            disposition,
            StoreDisposition::Committed | StoreDisposition::BlockDiscarded
        ) {
            return Err(ValidationError::CommittedRemoveMissingKey { operation_index });
        }
        return Ok(disposition);
    };
    let id = validate_key(operation_index, Some(key))?;
    if key.storage_causality_region != source_causality_region {
        return Err(ValidationError::EntitySourceCausalityMismatch { operation_index });
    }
    if remove.poi_entity_type != key.entity_type {
        return Err(ValidationError::RemovePoiEntityTypeMismatch { operation_index });
    }
    if !remove_id_matches(id, &remove.poi_entity_id) {
        return Err(ValidationError::RemovePoiEntityIdMismatch { operation_index });
    }
    Ok(disposition)
}

fn validate_set_history(
    operation_index: u64,
    handler_group_order: u64,
    handler_order: u64,
    source_causality_region: i32,
    disposition: StoreDisposition,
    set: &SetEntity,
    history: &mut HistoryStates,
) -> Result<(), ValidationError> {
    history.record_set(
        operation_index,
        handler_group_order,
        handler_order,
        source_causality_region,
        disposition,
        set,
    )
}

fn record_remove_history(
    handler_group_order: u64,
    handler_order: u64,
    source_causality_region: i32,
    disposition: StoreDisposition,
    remove: &RemoveEntity,
    history: &mut HistoryStates,
) -> Result<(), ValidationError> {
    history.record_remove(
        handler_group_order,
        handler_order,
        source_causality_region,
        disposition,
        remove,
    )
}

impl CacheOperation {
    /// Fold a later save or remove for the same entity into this effect.
    pub fn accumulate(&mut self, next: Self) {
        let update = match next {
            Self::Remove | Self::Overwrite(_) => {
                *self = next;
                return;
            }
            Self::Update(update) => update,
        };

        match self {
            Self::Remove => *self = Self::Overwrite(update),
            Self::Update(current) | Self::Overwrite(current) => {
                apply_written_fields(current, &update, NullMergeMode::Preserve);
            }
        }
    }

    /// Project this effect onto the entity visible before it ran.
    pub fn apply_to(&self, entity: &Option<Vec<EntityField>>) -> Option<Vec<EntityField>> {
        match (self, entity) {
            (Self::Remove, _) => None,
            (Self::Overwrite(fields), _) | (Self::Update(fields), None) => Some(fields.clone()),
            (Self::Update(fields), Some(entity)) => {
                let mut materialized = entity.clone();
                apply_written_fields(&mut materialized, fields, NullMergeMode::Remove);
                Some(materialized)
            }
        }
    }
}

impl ReplayCandidate {
    fn visible_before_handler(&self) -> Option<Vec<EntityField>> {
        match &self.main_operation {
            Some(operation) => operation.apply_to(&self.baseline),
            None => self.baseline.clone(),
        }
    }

    fn visible_with(&self, local: &CacheOperation) -> Option<Vec<EntityField>> {
        local.apply_to(&self.visible_before_handler())
    }

    fn commit(&mut self, local: CacheOperation) {
        match &mut self.main_operation {
            Some(main) => main.accumulate(local),
            None => self.main_operation = Some(local),
        }
    }
}

impl HistoryStates {
    fn record_set(
        &mut self,
        operation_index: u64,
        handler_group_order: u64,
        handler_order: u64,
        source_causality_region: i32,
        disposition: StoreDisposition,
        set: &SetEntity,
    ) -> Result<(), ValidationError> {
        let Some(materialized) = set.materialized.as_ref() else {
            return Ok(());
        };
        self.begin_handler(
            handler_group_order,
            handler_order,
            source_causality_region,
            disposition,
        )?;

        let key = materialized_key(set.key.as_ref().expect("validated Set key"));
        let domain = history_domain(handler_group_order, source_causality_region, key);
        let needs_local = !self
            .active_handler
            .as_ref()
            .expect("active handler")
            .locals
            .contains_key(&domain);

        if needs_local {
            let operation = CacheOperation::Update(set.written_fields.clone());
            let candidates = match self.main_state(&domain) {
                MainReplayState::Unknown => infer_unknown_replay_candidates(
                    operation_index,
                    &set.written_fields,
                    &materialized.fields,
                )?,
                MainReplayState::Known(candidates) => filter_replay_candidates(
                    operation_index,
                    candidates,
                    &operation,
                    &materialized.fields,
                )?,
            };
            self.active_handler
                .as_mut()
                .expect("active handler")
                .locals
                .insert(
                    domain,
                    LocalReplay {
                        candidates,
                        operation,
                    },
                );
            return Ok(());
        }

        let local = self
            .active_handler
            .as_mut()
            .expect("active handler")
            .locals
            .get_mut(&domain)
            .expect("checked local replay");
        local
            .operation
            .accumulate(CacheOperation::Update(set.written_fields.clone()));
        local.candidates = filter_replay_candidates(
            operation_index,
            std::mem::take(&mut local.candidates),
            &local.operation,
            &materialized.fields,
        )?;
        Ok(())
    }

    fn record_remove(
        &mut self,
        handler_group_order: u64,
        handler_order: u64,
        source_causality_region: i32,
        disposition: StoreDisposition,
        remove: &RemoveEntity,
    ) -> Result<(), ValidationError> {
        self.begin_handler(
            handler_group_order,
            handler_order,
            source_causality_region,
            disposition,
        )?;
        let Some(key) = remove.key.as_ref().map(materialized_key) else {
            return Ok(());
        };
        let domain = history_domain(handler_group_order, source_causality_region, key);
        let needs_local = !self
            .active_handler
            .as_ref()
            .expect("active handler")
            .locals
            .contains_key(&domain);
        if needs_local {
            let candidates = match self.main_state(&domain) {
                MainReplayState::Unknown => vec![ReplayCandidate {
                    baseline: None,
                    main_operation: None,
                }],
                MainReplayState::Known(candidates) => candidates,
            };
            self.active_handler
                .as_mut()
                .expect("active handler")
                .locals
                .insert(
                    domain,
                    LocalReplay {
                        candidates,
                        operation: CacheOperation::Remove,
                    },
                );
        } else {
            self.active_handler
                .as_mut()
                .expect("active handler")
                .locals
                .get_mut(&domain)
                .expect("checked local replay")
                .operation
                .accumulate(CacheOperation::Remove);
        }
        Ok(())
    }

    fn begin_handler(
        &mut self,
        handler_group_order: u64,
        handler_order: u64,
        source_causality_region: i32,
        disposition: StoreDisposition,
    ) -> Result<(), ValidationError> {
        let changed = self.active_handler.as_ref().is_some_and(|active| {
            active.handler_group_order != handler_group_order
                || active.handler_order != handler_order
                || active.source_causality_region != source_causality_region
        });
        if changed {
            self.finish_handler();
        }
        match self.active_handler.as_ref() {
            Some(_) => {}
            None => {
                self.active_handler = Some(ActiveHandler {
                    handler_group_order,
                    handler_order,
                    source_causality_region,
                    disposition,
                    locals: HashMap::new(),
                });
            }
        }
        Ok(())
    }

    fn finish_handler(&mut self) {
        let Some(active) = self.active_handler.take() else {
            return;
        };
        if active.disposition == StoreDisposition::Discarded {
            return;
        }
        for (domain, local) in active.locals {
            let candidates = local
                .candidates
                .into_iter()
                .map(|mut candidate| {
                    candidate.commit(local.operation.clone());
                    candidate
                })
                .collect();
            self.set_main_state(domain, MainReplayState::Known(candidates));
        }
    }

    fn main_state(&self, domain: &HistoryDomainKey) -> MainReplayState {
        match domain {
            HistoryDomainKey::Onchain(key) => self
                .onchain
                .get(key)
                .cloned()
                .unwrap_or(MainReplayState::Unknown),
            HistoryDomainKey::Offchain(group, key) => self
                .offchain
                .get(&(*group, key.clone()))
                .cloned()
                .unwrap_or_else(empty_store_replay_state),
        }
    }

    fn set_main_state(&mut self, domain: HistoryDomainKey, state: MainReplayState) {
        match domain {
            HistoryDomainKey::Onchain(key) => {
                self.onchain.insert(key, state);
            }
            HistoryDomainKey::Offchain(group, key) => {
                self.offchain.insert((group, key), state);
            }
        }
    }
}

fn history_domain(
    handler_group_order: u64,
    source_causality_region: i32,
    key: MaterializedKey,
) -> HistoryDomainKey {
    if source_causality_region == 0 {
        HistoryDomainKey::Onchain(key)
    } else {
        HistoryDomainKey::Offchain(handler_group_order, key)
    }
}

fn empty_store_replay_state() -> MainReplayState {
    MainReplayState::Known(vec![ReplayCandidate {
        baseline: None,
        main_operation: None,
    }])
}

fn infer_unknown_replay_candidates(
    operation_index: u64,
    written: &[EntityField],
    materialized: &[EntityField],
) -> Result<Vec<ReplayCandidate>, ValidationError> {
    let update = CacheOperation::Update(written.to_vec());
    let mut candidates = Vec::new();

    let absent = ReplayCandidate {
        baseline: None,
        main_operation: None,
    };
    if absent.visible_with(&update).as_deref() == Some(materialized) {
        candidates.push(absent);
    }

    let present = ReplayCandidate {
        baseline: Some(materialized.to_vec()),
        main_operation: None,
    };
    if present.visible_with(&update).as_deref() == Some(materialized) {
        candidates.push(present);
    }

    if candidates.is_empty() {
        Err(ValidationError::MaterializedHistoryMismatch { operation_index })
    } else {
        Ok(candidates)
    }
}

fn filter_replay_candidates(
    operation_index: u64,
    candidates: Vec<ReplayCandidate>,
    local: &CacheOperation,
    materialized: &[EntityField],
) -> Result<Vec<ReplayCandidate>, ValidationError> {
    let candidates: Vec<_> = candidates
        .into_iter()
        .filter(|candidate| candidate.visible_with(local).as_deref() == Some(materialized))
        .collect();
    if candidates.is_empty() {
        Err(ValidationError::MaterializedHistoryMismatch { operation_index })
    } else {
        Ok(candidates)
    }
}

/// Merge `written` into the name-sorted `materialized` field list in place.
pub fn apply_written_fields(
    materialized: &mut Vec<EntityField>,
    written: &[EntityField],
    null_mode: NullMergeMode,
) {
    for field in written {
        match materialized.binary_search_by(|candidate| candidate.name.cmp(&field.name)) {
            Ok(index) if field_is_null(field) && null_mode == NullMergeMode::Remove => {
                materialized.remove(index);
            }
            Ok(index) => materialized[index] = field.clone(),
            Err(_) if field_is_null(field) && null_mode == NullMergeMode::Remove => {}
            Err(index) => materialized.insert(index, field.clone()),
        }
    }
}

/// True when the field carries an explicit top-level `NullValue`.
pub fn field_is_null(field: &EntityField) -> bool {
    matches!(
        field.value.as_ref().and_then(|value| value.kind.as_ref()),
        Some(graph_value::Kind::Null(_))
    )
}

/// Storage identity of a validated `EntityKey`.
///
/// The key must already have passed [`validate_block_changes`]; an absent or
/// empty id is a validator refusal, not a caller input.
pub fn materialized_key(key: &EntityKey) -> MaterializedKey {
    let id = match key
        .id
        .as_ref()
        .and_then(|entity_id| entity_id.value.as_ref())
        .expect("validated entity id")
    {
        entity_id::Value::String(value) => MaterializedId::String(value.clone()),
        entity_id::Value::Bytes(value) => MaterializedId::Bytes(value.clone()),
        entity_id::Value::Int8(value) => MaterializedId::Int8(*value),
    };
    MaterializedKey {
        entity_type: key.entity_type.clone(),
        id,
        storage_causality_region: key.storage_causality_region,
    }
}

fn validate_disposition(
    operation_index: u64,
    value: i32,
) -> Result<StoreDisposition, ValidationError> {
    match StoreDisposition::try_from(value) {
        Ok(StoreDisposition::Committed) => Ok(StoreDisposition::Committed),
        Ok(StoreDisposition::Discarded) => Ok(StoreDisposition::Discarded),
        Ok(StoreDisposition::BlockDiscarded) => Ok(StoreDisposition::BlockDiscarded),
        Ok(StoreDisposition::Unspecified) | Err(_) => {
            Err(ValidationError::UnknownStoreDisposition {
                operation_index,
                actual: value,
            })
        }
    }
}

/// Validate a snapshot/seed entity with the same scalar, field-order and ID
/// rules as a materialized BlockChanges save. The index identifies the record
/// in diagnostics; this does not invent a mapping operation or a PoI event.
pub fn validate_materialized_entity(
    record_index: u64,
    key: &EntityKey,
    fields: &[EntityField],
) -> Result<(), ValidationError> {
    let id = validate_key(record_index, Some(key))?;
    validate_fields(record_index, "materialized", fields)?;
    validate_id_field(record_index, "materialized", id, fields)
}

fn validate_key(
    operation_index: u64,
    key: Option<&EntityKey>,
) -> Result<&entity_id::Value, ValidationError> {
    let key = key.ok_or(ValidationError::MissingEntityKey { operation_index })?;
    if key.entity_type.is_empty() {
        return Err(ValidationError::EmptyEntityType { operation_index });
    }
    validate_graphql_name(operation_index, "storage entity type", &key.entity_type)?;
    if key.storage_causality_region < 0 {
        return Err(ValidationError::NegativeStorageCausalityRegion {
            operation_index,
            actual: key.storage_causality_region,
        });
    }
    key.id
        .as_ref()
        .and_then(|id| id.value.as_ref())
        .ok_or(ValidationError::MissingEntityId { operation_index })
}

fn validate_fields(
    operation_index: u64,
    set: &'static str,
    fields: &[EntityField],
) -> Result<(), ValidationError> {
    let mut previous: Option<&str> = None;
    for field in fields {
        if field.name.is_empty() {
            return Err(ValidationError::EmptyFieldName {
                operation_index,
                set,
            });
        }
        validate_graphql_name(operation_index, "field", &field.name)?;
        if field.name == "vid" {
            return Err(ValidationError::ReservedField {
                operation_index,
                set,
            });
        }
        if previous.is_some_and(|value| value >= field.name.as_str()) {
            return Err(ValidationError::FieldOrder {
                operation_index,
                set,
            });
        }
        let value = field
            .value
            .as_ref()
            .ok_or_else(|| ValidationError::MissingFieldValue {
                operation_index,
                field: field.name.clone(),
            })?;
        validate_value(operation_index, &field.name, value, 0)?;
        previous = Some(&field.name);
    }
    Ok(())
}

fn validate_graphql_name(
    operation_index: u64,
    context: &'static str,
    name: &str,
) -> Result<(), ValidationError> {
    let mut characters = name.bytes();
    let valid_start = characters
        .next()
        .is_some_and(|byte| byte == b'_' || byte.is_ascii_alphabetic());
    let valid_rest = characters.all(|byte| byte == b'_' || byte.is_ascii_alphanumeric());
    if !valid_start || !valid_rest {
        return Err(ValidationError::InvalidGraphQlName {
            operation_index,
            context,
            name: name.to_owned(),
        });
    }
    Ok(())
}

fn validate_id_field(
    operation_index: u64,
    set: &'static str,
    id: &entity_id::Value,
    fields: &[EntityField],
) -> Result<(), ValidationError> {
    let field =
        fields
            .iter()
            .find(|field| field.name == "id")
            .ok_or(ValidationError::MissingIdField {
                operation_index,
                set,
            })?;
    let matches = match (
        id,
        field.value.as_ref().and_then(|value| value.kind.as_ref()),
    ) {
        (entity_id::Value::String(expected), Some(graph_value::Kind::String(actual))) => {
            expected == actual
        }
        (entity_id::Value::Bytes(expected), Some(graph_value::Kind::Bytes(actual))) => {
            expected == actual
        }
        (entity_id::Value::Int8(expected), Some(graph_value::Kind::Int8(actual))) => {
            expected == actual
        }
        _ => false,
    };
    if !matches {
        return Err(ValidationError::IdFieldMismatch {
            operation_index,
            set,
        });
    }
    Ok(())
}

fn validate_projection(
    operation_index: u64,
    written: &[EntityField],
    materialized: &[EntityField],
) -> Result<(), ValidationError> {
    for written_field in written {
        let written_value = written_field
            .value
            .as_ref()
            .expect("written fields were validated before their projection");
        let materialized_value = materialized
            .binary_search_by_key(&written_field.name.as_str(), |field| field.name.as_str())
            .ok()
            .and_then(|index| materialized[index].value.as_ref());
        let projected = match written_value.kind.as_ref() {
            Some(graph_value::Kind::Null(_)) => {
                materialized_value.is_none()
                    || materialized_value
                        .is_some_and(|value| matches!(value.kind, Some(graph_value::Kind::Null(_))))
            }
            Some(_) => materialized_value == Some(written_value),
            None => unreachable!("written fields were validated before their projection"),
        };
        if !projected {
            return Err(ValidationError::MaterializedProjection {
                operation_index,
                field: written_field.name.clone(),
            });
        }
    }
    Ok(())
}

fn canonical_id(id: &entity_id::Value) -> String {
    match id {
        entity_id::Value::String(value) => value.clone(),
        entity_id::Value::Bytes(value) => format!("0x{}", hex::encode(value)),
        entity_id::Value::Int8(value) => value.to_string(),
    }
}

fn remove_id_matches(id: &entity_id::Value, raw: &str) -> bool {
    match id {
        entity_id::Value::String(expected) => expected == raw,
        entity_id::Value::Bytes(expected) => {
            hex::decode(raw.trim_start_matches("0x")).is_ok_and(|actual| actual == *expected)
        }
        entity_id::Value::Int8(expected) => raw.parse::<i64>() == Ok(*expected),
    }
}

fn validate_value(
    operation_index: u64,
    field: &str,
    value: &GraphValue,
    depth: usize,
) -> Result<(), ValidationError> {
    if depth > MAX_VALUE_DEPTH {
        return Err(ValidationError::ValueNestingTooDeep {
            operation_index,
            field: field.to_owned(),
        });
    }
    let kind = value
        .kind
        .as_ref()
        .ok_or_else(|| ValidationError::MissingFieldValue {
            operation_index,
            field: field.to_owned(),
        })?;
    match kind {
        graph_value::Kind::BigInt(value) => {
            validate_signed_bytes(operation_index, field, &value.signed_be)?;
            let value = BigInt::from_signed_bytes_be(&value.signed_be);
            if value.bits() + 1 > GRAPH_BIGINT_MAX_BITS {
                return Err(ValidationError::BigIntTooLarge {
                    operation_index,
                    field: field.to_owned(),
                });
            }
        }
        graph_value::Kind::BigDecimal(value) => {
            validate_decimal(operation_index, field, value)?;
        }
        graph_value::Kind::List(value) => {
            for item in &value.values {
                validate_value(operation_index, field, item, depth + 1)?;
            }
        }
        graph_value::Kind::TimestampMicros(micros) => {
            let seconds = micros / 1_000_000;
            let nanos = (micros % 1_000_000) * 1_000;
            if nanos < 0
                || chrono::DateTime::<chrono::Utc>::from_timestamp(seconds, nanos as u32).is_none()
            {
                return Err(ValidationError::InvalidTimestamp {
                    operation_index,
                    field: field.to_owned(),
                });
            }
        }
        graph_value::Kind::String(_)
        | graph_value::Kind::Int(_)
        | graph_value::Kind::Int8(_)
        | graph_value::Kind::Bool(_)
        | graph_value::Kind::Null(_)
        | graph_value::Kind::Bytes(_) => {}
    }
    Ok(())
}

fn validate_decimal(
    operation_index: u64,
    field: &str,
    value: &crate::pb::pinax::graph::backfill::v1::BigDecimalValue,
) -> Result<(), ValidationError> {
    validate_signed_bytes(operation_index, field, &value.coefficient_signed_be)?;
    if !(GRAPH_DECIMAL_MIN_SCALE..=GRAPH_DECIMAL_MAX_SCALE).contains(&value.scale) {
        return Err(ValidationError::DecimalScale {
            operation_index,
            field: field.to_owned(),
        });
    }

    let coefficient = BigInt::from_signed_bytes_be(&value.coefficient_signed_be);
    if coefficient == BigInt::from(0) {
        if value.scale != 0 || !value.coefficient_signed_be.is_empty() {
            return Err(ValidationError::NonCanonicalZeroDecimal {
                operation_index,
                field: field.to_owned(),
            });
        }
        return Ok(());
    }

    // A nonzero tuple is accepted exactly when Graph Node v0.44's
    // `BigDecimal::normalized()` maps it to itself. That function runs
    // bigdecimal 0.1.2's `with_prec(34)` and then strips base-10 trailing
    // zeros. `with_prec` changes the value only in its `digits > prec` branch,
    // which rounds a positive coefficient and truncates a negative one. Its
    // `digits < prec` branch appends zeros, which the strip removes again, and
    // its `digits == prec` branch is the identity. So the tuple is a fixed
    // point if and only if the ported digit count is at most 34 and the
    // coefficient has no trailing zero.
    if bigdecimal_0_1_2_digits_exceed(&coefficient, GRAPH_DECIMAL_PRECISION) {
        return Err(ValidationError::DecimalPrecision {
            operation_index,
            field: field.to_owned(),
        });
    }
    if coefficient.magnitude() % 10u8 == num_bigint::BigUint::from(0u8) {
        return Err(ValidationError::NonNormalizedDecimal {
            operation_index,
            field: field.to_owned(),
        });
    }
    Ok(())
}

/// Whether bigdecimal 0.1.2's `count_decimal_digits(int)` exceeds `prec`.
///
/// This is a port of the pinned crate's arithmetic, not a digit count:
///
/// ```text
/// let mut digits = (int.bits() as f64 / 3.3219280949) as u64;
/// let mut num = ten_to_the(digits);
/// while int >= &num { num *= 10u8; digits += 1; }
/// ```
///
/// `bits()` is the magnitude's bit length in both num-bigint 0.2 and 0.4. The
/// correction loop compares the *signed* integer with a positive power of ten,
/// so it never runs for a negative coefficient. A negative coefficient's
/// count is therefore the bit estimate alone, which is one short of its decimal
/// length across part of each decade. For precision 34 that makes the exact
/// boundary 116 bits, not 35 digits: a negative magnitude is accepted up to
/// 2^116 - 1 = 83,076,749,736,557,242,056,487,941,267,521,535. A positive
/// coefficient gets the true decimal length.
///
/// The loop only ever increases the count, so an estimate already above
/// `prec` is final. Returning early there keeps the cost bounded however large
/// the coefficient is; the port never computes a power of ten above `prec`.
fn bigdecimal_0_1_2_digits_exceed(int: &BigInt, prec: u64) -> bool {
    if int.sign() == num_bigint::Sign::NoSign {
        // `count_decimal_digits` returns 1 for zero.
        return 1 > prec;
    }
    let mut digits = (int.bits() as f64 / BIGDECIMAL_0_1_2_BITS_PER_DIGIT) as u64;
    if digits > prec {
        return true;
    }
    let mut num = BigInt::from(10u8).pow(digits as u32);
    while int >= &num {
        num *= 10u8;
        digits += 1;
        if digits > prec {
            return true;
        }
    }
    false
}

fn validate_signed_bytes(
    operation_index: u64,
    field: &str,
    value: &[u8],
) -> Result<(), ValidationError> {
    let zero_byte = value == [0];
    let redundant_sign = value.len() > 1
        && ((value[0] == 0 && value[1] & 0x80 == 0) || (value[0] == 0xff && value[1] & 0x80 != 0));
    if zero_byte || redundant_sign {
        return Err(ValidationError::InvalidSignedBigEndian {
            operation_index,
            field: field.to_owned(),
        });
    }
    Ok(())
}
