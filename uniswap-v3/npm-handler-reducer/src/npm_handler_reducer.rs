//! Host-only joint NonfungiblePositionManager entity-state reducer.
//!
//! This module intentionally has no Substreams handler, store, RPC, database,
//! or `graph_out` integration. It models Transaction, Position, and
//! PositionSnapshot effects in one clone-on-write handler scratch behind
//! explicit hermetic inputs.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::fmt::{self, Write as _};

use num_bigint::{BigInt, BigUint, Sign};
use num_traits::Zero;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use substreams::errors::Error;

use crate::pb::writer::writer_event::Event;
use crate::pb::writer::{WriterEvent, WriterEvents};

const REDUCER_CONTRACT_SHA256: &str = "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143";
const REDUCER_CONTRACT_VERSION: &str = "uniswap-v3-npm-handler-reducer/v1";
const SOURCE_POSITION_REDUCER_SHA256: &str = "3099c3f08208cf46ce68df3433dd5b757436a3a7e315daec3f0d96bf242185c1";
const SOURCE_TRANSACTION_REDUCER_SHA256: &str = "c9f355d141720dfda4347b4ef6cb5350a96803db31cf4770f035b5efca9def7f";
const SOURCE_WRITER_CONTRACT_SHA256: &str = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4";
const SOURCE_PROFILE_SHA256: &str = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823";
const SOURCE_MATRIX_SHA256: &str = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161";
const SOURCE_WRITER_RUNTIME_SHA256: &str = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca";
const SOURCE_EXECUTION_ORDER_RAW_SHA256: &str = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2";
const WRITER_DESCRIPTOR_SHA256: &str = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0";
const HISTORICAL_GUARD_BLOCK: u64 = 14_317_993;
const EXCLUDED_POOL: Address = [
    0x8f, 0xe8, 0xd9, 0xbb, 0x8e, 0xeb, 0xa3, 0xed, 0x68, 0x80, 0x69, 0xc3, 0xd6, 0xb5, 0x56, 0xc9, 0xca, 0x25, 0x82,
    0x48,
];

pub type Address = [u8; 20];
pub type TransactionHash = [u8; 32];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decimal {
    coefficient: BigInt,
    scale: i64,
}

impl Decimal {
    pub fn zero() -> Self {
        Self {
            coefficient: BigInt::zero(),
            scale: 0,
        }
    }

    pub fn parse(value: &str) -> Result<Self, String> {
        if value.is_empty() || value.starts_with('+') {
            return Err(format!("invalid decimal `{value}`"));
        }
        let negative = value.starts_with('-');
        let unsigned = value.strip_prefix('-').unwrap_or(value);
        let mut parts = unsigned.split('.');
        let whole = parts.next().unwrap_or_default();
        let fraction = parts.next();
        if parts.next().is_some()
            || whole.is_empty()
            || !whole.bytes().all(|byte| byte.is_ascii_digit())
            || fraction
                .map(|digits| digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()))
                .unwrap_or(false)
        {
            return Err(format!("invalid decimal `{value}`"));
        }
        let fraction = fraction.unwrap_or_default();
        let digits = format!("{whole}{fraction}");
        let mut coefficient =
            BigInt::parse_bytes(digits.as_bytes(), 10).ok_or_else(|| format!("invalid decimal `{value}`"))?;
        if negative {
            coefficient = -coefficient;
        }
        Ok(Self::graph_normalized(coefficient, fraction.len() as i64))
    }

    fn from_unsigned_units(value: &str, scale: u8) -> Result<Self, HandlerError> {
        let value = parse_unsigned("event amount", value)?;
        Ok(Self::graph_normalized(BigInt::from(value), i64::from(scale)))
    }

    /// Mirrors graph-node v0.44.0 `BigDecimal::normalized`: every host
    /// construction and arithmetic result is rounded to decimal128's 34
    /// significant digits, then trailing zeroes are removed.
    fn graph_normalized(mut coefficient: BigInt, mut scale: i64) -> Self {
        if coefficient.is_zero() {
            return Self::zero();
        }
        let negative = coefficient.sign() == Sign::Minus;
        let digits = if negative {
            (-&coefficient).to_str_radix(10).len()
        } else {
            coefficient.to_str_radix(10).len()
        };
        if digits > 34 {
            let difference = (digits - 34) as u64;
            let divisor = power_of_ten(difference);
            let remainder = &coefficient % &divisor;
            coefficient /= &divisor;
            let absolute_remainder = if remainder.sign() == Sign::Minus {
                -remainder
            } else {
                remainder
            };
            if absolute_remainder * BigInt::from(2_u8) >= divisor {
                if negative {
                    coefficient -= 1_u8;
                } else {
                    coefficient += 1_u8;
                }
            }
            scale -= difference as i64;
        }
        let ten = BigInt::from(10_u8);
        while (&coefficient % &ten).is_zero() {
            coefficient /= &ten;
            scale -= 1;
        }
        Self { coefficient, scale }
    }

    fn add(&self, other: &Self) -> Self {
        let scale = self.scale.max(other.scale);
        let left = &self.coefficient * power_of_ten((scale - self.scale) as u64);
        let right = &other.coefficient * power_of_ten((scale - other.scale) as u64);
        Self::graph_normalized(left + right, scale)
    }
}

impl Default for Decimal {
    fn default() -> Self {
        Self::zero()
    }
}

impl fmt::Display for Decimal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let negative = self.coefficient.sign() == Sign::Minus;
        let mut digits = if negative {
            (-&self.coefficient).to_str_radix(10)
        } else {
            self.coefficient.to_str_radix(10)
        };
        match self.scale.cmp(&0) {
            Ordering::Greater => {
                let scale = self.scale as usize;
                if digits.len() <= scale {
                    digits = format!("{}{}", "0".repeat(scale + 1 - digits.len()), digits);
                }
                digits.insert(digits.len() - scale, '.');
            }
            Ordering::Less => digits.push_str(&"0".repeat((-self.scale) as usize)),
            Ordering::Equal => {}
        }
        if negative {
            write!(formatter, "-{digits}")
        } else {
            formatter.write_str(&digits)
        }
    }
}

fn power_of_ten(power: u64) -> BigInt {
    BigInt::from(10_u8).pow(power as u32)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PositionCall {
    pub token0: Address,
    pub token1: Address,
    pub fee: u32,
    pub tick_lower: i32,
    pub tick_upper: i32,
    pub fee_growth_inside0_last_x128: BigUint,
    pub fee_growth_inside1_last_x128: BigUint,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TransactionMetadata {
    pub transaction_hash: TransactionHash,
    pub gas_limit: String,
    pub gas_price: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TransactionEntity {
    pub id: String,
    pub block_number: u64,
    pub timestamp: u64,
    pub gas_used: String,
    pub gas_price: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Position {
    pub token_id: String,
    pub owner: Address,
    pub pool: Address,
    pub token0: Address,
    pub token1: Address,
    pub tick_lower: i32,
    pub tick_upper: i32,
    pub liquidity: BigInt,
    pub deposited_token0: Decimal,
    pub deposited_token1: Decimal,
    pub withdrawn_token0: Decimal,
    pub withdrawn_token1: Decimal,
    pub collected_fees_token0: Decimal,
    pub collected_fees_token1: Decimal,
    pub transaction: TransactionHash,
    pub fee_growth_inside0_last_x128: BigUint,
    pub fee_growth_inside1_last_x128: BigUint,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PositionSnapshot {
    pub id: String,
    pub position: String,
    pub owner: Address,
    pub pool: Address,
    pub block_number: u64,
    pub timestamp: u64,
    pub liquidity: BigInt,
    pub deposited_token0: Decimal,
    pub deposited_token1: Decimal,
    pub withdrawn_token0: Decimal,
    pub withdrawn_token1: Decimal,
    pub collected_fees_token0: Decimal,
    pub collected_fees_token1: Decimal,
    pub transaction: TransactionHash,
    pub fee_growth_inside0_last_x128: BigUint,
    pub fee_growth_inside1_last_x128: BigUint,
}

impl PositionSnapshot {
    fn from_position(position: &Position, block_number: u64, timestamp: u64, transaction: TransactionHash) -> Self {
        Self {
            id: format!("{}#{block_number}", position.token_id),
            position: position.token_id.clone(),
            owner: position.owner,
            pool: position.pool,
            block_number,
            timestamp,
            liquidity: position.liquidity.clone(),
            deposited_token0: position.deposited_token0.clone(),
            deposited_token1: position.deposited_token1.clone(),
            withdrawn_token0: position.withdrawn_token0.clone(),
            withdrawn_token1: position.withdrawn_token1.clone(),
            collected_fees_token0: position.collected_fees_token0.clone(),
            collected_fees_token1: position.collected_fees_token1.clone(),
            transaction,
            fee_growth_inside0_last_x128: position.fee_growth_inside0_last_x128.clone(),
            fee_growth_inside1_last_x128: position.fee_growth_inside1_last_x128.clone(),
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReducerState {
    pub transactions: BTreeMap<String, TransactionEntity>,
    pub positions: BTreeMap<String, Position>,
    pub snapshots: BTreeMap<String, PositionSnapshot>,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct BlockScope {
    pub network: String,
    pub block_number: u64,
    pub block_hash: Option<TransactionHash>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockContext {
    pub number: u64,
    pub timestamp: u64,
    pub hash: Option<TransactionHash>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailurePhase {
    None,
    AfterIdentity,
    AfterPositionSave,
    AfterSnapshotLoad,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EventControl {
    pub ordinal: u64,
    pub failure_phase: FailurePhase,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DiagnosticInput {
    pub writer_events: WriterEvents,
    pub block: BlockContext,
    pub transactions: Vec<TransactionMetadata>,
    pub controls: Vec<EventControl>,
}

pub trait ReducerInputs {
    /// Models `NonfungiblePositionManager.try_positions` at post-block state.
    fn position_at_block(
        &mut self,
        scope: &BlockScope,
        position_manager: Address,
        token_id: &str,
    ) -> Result<Option<PositionCall>, String>;

    /// Models the non-try Factory `getPool` call used only by `getPosition`.
    fn pool_at_block(
        &mut self,
        scope: &BlockScope,
        factory: Address,
        token0: Address,
        token1: Address,
        fee: u32,
    ) -> Result<Address, String>;

    /// Models `Token.load` in the entity state visible at a trigger ordinal.
    fn token_decimals_at_ordinal(&mut self, address: Address, ordinal: u64) -> Result<Option<u8>, String>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventKind {
    Increase,
    Decrease,
    Collect,
    Transfer,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NormalReturnReason {
    HistoricalGuard,
    MissingPosition,
    ExcludedPool,
    MissingToken,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EventDisposition {
    Committed,
    NormalReturn(NormalReturnReason),
    NonFatalError(String),
    FatalError(String),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransactionLoadSite {
    PositionCreation,
    PositionSnapshot,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityWriteSite {
    Transaction(TransactionLoadSite),
    Position,
    PositionSnapshot,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EventOutcome {
    pub ordinal: u64,
    pub token_id: String,
    pub kind: EventKind,
    pub transaction_id: String,
    pub disposition: EventDisposition,
    pub attempted_writes: Vec<EntityWriteSite>,
    pub event_state_committed: bool,
    pub block_state_committed: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BlockDisposition {
    /// This reducer consumed its complete NPM WriterEvents envelope and modeled
    /// the scoped user-entity projection. It is not Graph block or checkpoint
    /// success authority.
    ModeledNpmUserEntityProjectionComplete,
    /// Final persisted NPM user-entity projection shortcut only. Graph keeps
    /// executing runnable triggers and dynamic stages after the first fatal
    /// handler error; those post-fatal effects are deliberately outside this trace.
    FatalNpmUserEntityProjection {
        ordinal: u64,
        message: String,
        omitted_event_count: usize,
    },
}

impl BlockDisposition {
    /// A completed host-only projection never authorizes Graph block or
    /// checkpoint success. The exhaustive match intentionally makes every new
    /// disposition opt in explicitly if this invariant ever changes.
    pub const fn authorizes_graph_block_or_checkpoint_success(&self) -> bool {
        match self {
            Self::ModeledNpmUserEntityProjectionComplete => false,
            Self::FatalNpmUserEntityProjection { .. } => false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockReduction {
    pub state: ReducerState,
    pub outcomes: Vec<EventOutcome>,
    pub disposition: BlockDisposition,
    pub segment_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum EventEffect {
    Commit,
    NormalReturn(NormalReturnReason),
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct HandlerError(String);

impl HandlerError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

#[derive(Debug)]
enum ExecutionFailure {
    Invalid(String),
    Handler(HandlerError),
}

impl ExecutionFailure {
    fn invalid(message: impl Into<String>) -> Self {
        Self::Invalid(message.into())
    }
}

impl From<HandlerError> for ExecutionFailure {
    fn from(error: HandlerError) -> Self {
        Self::Handler(error)
    }
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum Network {
    Mainnet,
    Base,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum StoredGasUsedMode {
    TransactionGasLimit,
    Zero,
}

impl Network {
    fn parse(value: &str) -> Result<Self, Error> {
        match value {
            "mainnet" => Ok(Self::Mainnet),
            "base" => Ok(Self::Base),
            other => Err(Error::msg(format!("unknown position-reducer network `{other}`"))),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Mainnet => "mainnet",
            Self::Base => "base",
        }
    }
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum CollectMode {
    OwnFieldAmounts,
    Fee0FromFee1PlusAmount1,
    NoAmountAccumulation,
    Amount0ToBoth,
    Amount0ToBothIfToken0Exists,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum MissingTokenPolicy {
    DeterministicError,
    NoTokenRead,
    PreserveAmountsRefreshAndSave,
    DropEvent,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum TokenRead {
    Token0,
    Token1,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct SourceContract {
    path: String,
    contract_version: String,
    sha256: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct SourceRawContract {
    path: String,
    contract_version: String,
    raw_sha256: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct SourceWriterRuntime {
    path: String,
    contract_version: String,
    sha256: String,
    writer_descriptor_sha256: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct NetworkContract {
    network: Network,
    factory: String,
    nonfungible_position_manager: String,
    runtime_start_block: u64,
    npm_start_block: u64,
}

impl NetworkContract {
    fn factory_address(&self) -> Result<Address, Error> {
        decode_contract_address("factory", &self.factory)
    }

    fn position_manager_address(&self) -> Result<Address, Error> {
        decode_contract_address("nonfungible_position_manager", &self.nonfungible_position_manager)
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ExecutionContract {
    event_order: String,
    block_context: String,
    producer_corruption: String,
    event_state: String,
    nonfatal_error: String,
    fatal_error: String,
    post_fatal_execution: String,
    graph_call_scope: String,
    graph_call_cache: String,
    token_read_scope: String,
    provisional_identity: String,
    snapshot_id: String,
    fee_refresh_handlers: Vec<String>,
    fee_refresh_revert: String,
    snapshot_handlers: Vec<String>,
    excluded_pool: String,
    excluded_pool_handlers: Vec<String>,
    historical_guard_block: u64,
    historical_guard_handlers: Vec<String>,
    historical_guard_order: String,
    transaction_id: String,
    transaction_metadata: String,
    legacy_stored_gas_used: String,
    current_stored_gas_used: String,
    new_position_transaction_loads: u8,
    existing_position_transaction_loads: u8,
    transaction_save_observability: String,
    normal_return_orphans: Vec<String>,
    position_transaction: String,
    snapshot_transaction: String,
    physical_side_effect_scope: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct NpmProfile {
    profile_id: String,
    collect_mode: CollectMode,
    collect_token_reads: Vec<TokenRead>,
    collect_missing_token_policy: MissingTokenPolicy,
    increase_decrease_missing_token_policy: MissingTokenPolicy,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Segment {
    network: Network,
    start_block_inclusive: u64,
    end_block_inclusive: Option<u64>,
    deployment: String,
    segment_id: String,
    semantic_contract_sha256: String,
    npm_profile_id: String,
    api_version: String,
    stored_gas_used_mode: StoredGasUsedMode,
    nonfatal_errors: bool,
    historical_guard_effective: bool,
}

impl Segment {
    fn includes(&self, network: Network, block: u64) -> bool {
        self.network == network
            && self.start_block_inclusive <= block
            && self.end_block_inclusive.map_or(true, |end| block <= end)
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct TruthBoundary {
    all_eight_npm_segments_executable: bool,
    backfill_ready: bool,
    boundary_state_continuity_complete: bool,
    combined_handler_order_implemented: bool,
    diagnostic_only: bool,
    dynamic_datasource_stage_order_implemented: bool,
    failed_handler_poi_error_stream_semantics_certified: bool,
    full_npm_handler_semantics: bool,
    graph_node_execution_order_supplement_bound: bool,
    graph_out_replaced: bool,
    graph_execution_trace_complete: bool,
    joint_npm_entity_state_modeled: bool,
    live_calls_added: bool,
    logical_oracle_complete: bool,
    npm_handler_entity_atomicity_modeled: bool,
    npm_normal_return_orphan_transaction_modeled: bool,
    npm_transaction_entity_effects_modeled: bool,
    physical_parity_complete: bool,
    physical_entity_vid_semantics_certified: bool,
    post_fatal_execution_modeled: bool,
    poi_parity_complete: bool,
    pool_cross_component_execution_order_certified: bool,
    pool_transaction_writers_audited: bool,
    production_ready: bool,
    runtime_consumes_execution_order_contract: bool,
    runtime_population_complete: bool,
    shared_transaction_last_writer_semantics_certified: bool,
    stores_added: bool,
    substreams_handler_added: bool,
    checkpoint_or_graph_block_success_authorized: bool,
    target_runtime_identity_bound: bool,
    writer_runtime_consumes_this_matrix: bool,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ReducerContract {
    format_version: u32,
    contract_version: String,
    mode: String,
    source_position_reducer: SourceContract,
    source_transaction_reducer: SourceContract,
    source_writer_contract: SourceContract,
    source_segment_profiles: SourceContract,
    source_segment_matrix: SourceContract,
    source_writer_runtime: SourceWriterRuntime,
    source_execution_order: SourceRawContract,
    network_contracts: Vec<NetworkContract>,
    execution_contract: ExecutionContract,
    npm_profiles: Vec<NpmProfile>,
    segments: Vec<Segment>,
    truth_boundary: TruthBoundary,
}

impl ReducerContract {
    fn embedded() -> Result<Self, Error> {
        let raw = include_str!("../configs/npm-handler-reducer-v1.json");
        if hex::encode(Sha256::digest(raw.as_bytes())) != REDUCER_CONTRACT_SHA256 {
            return Err(Error::msg("NPM-handler reducer contract digest mismatch"));
        }
        let contract: Self = serde_json::from_str(raw)
            .map_err(|error| Error::msg(format!("invalid NPM-handler reducer contract JSON: {error}")))?;
        contract.validate()?;
        Ok(contract)
    }

    fn validate(&self) -> Result<(), Error> {
        if self.format_version != 1
            || self.contract_version != REDUCER_CONTRACT_VERSION
            || self.mode != "host-diagnostic-only"
        {
            return Err(Error::msg("unsupported NPM-handler reducer contract"));
        }
        if self.source_position_reducer.path != "uniswap-v3/position-reducer/contract-v1.json"
            || self.source_position_reducer.contract_version != "uniswap-v3-position-reducer-runtime/v1"
            || self.source_position_reducer.sha256 != SOURCE_POSITION_REDUCER_SHA256
            || self.source_transaction_reducer.path != "uniswap-v3/transaction-reducer/contract-v1.json"
            || self.source_transaction_reducer.contract_version != "uniswap-v3-transaction-reducer-runtime/v1"
            || self.source_transaction_reducer.sha256 != SOURCE_TRANSACTION_REDUCER_SHA256
            || self.source_writer_contract.path != "uniswap-v3/graft-ancestry/v2/writer-compatibility.json"
            || self.source_writer_contract.contract_version != "uniswap-v3-writer-compatibility/v3"
            || self.source_writer_contract.sha256 != SOURCE_WRITER_CONTRACT_SHA256
            || self.source_segment_profiles.path != "uniswap-v3/writer-runtime/segment-profiles-v1.json"
            || self.source_segment_profiles.contract_version != "uniswap-v3-writer-runtime-segment-profiles/v1"
            || self.source_segment_profiles.sha256 != SOURCE_PROFILE_SHA256
            || self.source_segment_matrix.path != "uniswap-v3/segment-writer-matrix/v1/contract.json"
            || self.source_segment_matrix.contract_version != "uniswap-v3-segment-writer-matrix/v1"
            || self.source_segment_matrix.sha256 != SOURCE_MATRIX_SHA256
            || self.source_writer_runtime.path != "uniswap-v3/writer-runtime/contract-v1.json"
            || self.source_writer_runtime.contract_version != "uniswap-v3-writer-runtime/v1"
            || self.source_writer_runtime.sha256 != SOURCE_WRITER_RUNTIME_SHA256
            || self.source_writer_runtime.writer_descriptor_sha256 != WRITER_DESCRIPTOR_SHA256
            || self.source_execution_order.path != "uniswap-v3/execution-order/v1/contract.json"
            || self.source_execution_order.contract_version != "uniswap-v3-execution-order/v1"
            || self.source_execution_order.raw_sha256 != SOURCE_EXECUTION_ORDER_RAW_SHA256
        {
            return Err(Error::msg("NPM-handler reducer source binding drift"));
        }
        self.validate_network_contracts()?;
        self.validate_execution_contract()?;
        self.validate_profiles()?;
        self.validate_segments()?;
        if self.truth_boundary
            != (TruthBoundary {
                all_eight_npm_segments_executable: true,
                backfill_ready: false,
                boundary_state_continuity_complete: false,
                combined_handler_order_implemented: false,
                diagnostic_only: true,
                dynamic_datasource_stage_order_implemented: false,
                failed_handler_poi_error_stream_semantics_certified: false,
                full_npm_handler_semantics: false,
                graph_node_execution_order_supplement_bound: true,
                graph_out_replaced: false,
                graph_execution_trace_complete: false,
                joint_npm_entity_state_modeled: true,
                live_calls_added: false,
                logical_oracle_complete: false,
                npm_handler_entity_atomicity_modeled: true,
                npm_normal_return_orphan_transaction_modeled: true,
                npm_transaction_entity_effects_modeled: true,
                physical_parity_complete: false,
                physical_entity_vid_semantics_certified: false,
                post_fatal_execution_modeled: false,
                poi_parity_complete: false,
                pool_cross_component_execution_order_certified: false,
                pool_transaction_writers_audited: false,
                production_ready: false,
                runtime_consumes_execution_order_contract: false,
                runtime_population_complete: false,
                shared_transaction_last_writer_semantics_certified: false,
                stores_added: false,
                substreams_handler_added: false,
                checkpoint_or_graph_block_success_authorized: false,
                target_runtime_identity_bound: false,
                writer_runtime_consumes_this_matrix: false,
            })
        {
            return Err(Error::msg("NPM-handler reducer truth boundary promoted"));
        }
        Ok(())
    }

    fn validate_execution_contract(&self) -> Result<(), Error> {
        let execution = &self.execution_contract;
        if execution.event_order
            != "strictly increasing global ordinal with strictly increasing block_log_index"
            || execution.block_context
                != "immutable number, timestamp, and optional hash; number must match WriterEvents and every snapshot uses the exact timestamp"
            || execution.producer_corruption
                != "reject before event execution and before applying segment nonfatal policy"
            || execution.event_state
                != "one clone-on-write Transaction, Position, and PositionSnapshot scratch per NPM handler; only a normal return or fully accepted handler commits it"
            || execution.nonfatal_error != "discard the failing joint handler scratch state and continue"
            || execution.fatal_error
                != "final persisted NPM user-entity projection shortcut: return the exact block-baseline Transaction, Position, and PositionSnapshot state at the first fatal error; this is not a Graph execution stop"
            || execution.post_fatal_execution
                != "intentionally not modeled: Graph continues remaining runnable triggers and breadth-first dynamic stages and may encounter a later retryable failure that aborts before the block transaction; otherwise the fatal transaction filters user modifications to PoI, passes persisted data sources and deterministic errors, advances the failed block pointer, and stops the deployment"
            || execution.graph_call_scope
                != "one reducer invocation and its exact block pointer; hash-bound when available and number fallback otherwise; never event ordinal"
            || execution.graph_call_cache
                != "invocation-local raw results keyed by target address and exact positions or getPool calldata"
            || execution.token_read_scope != "event ordinal; never block-only"
            || execution.provisional_identity
                != "a new getPosition identity remains provisional while its first loadTransaction is committed to joint scratch; a later normal return may retain only Transaction"
            || execution.snapshot_id
                != "position token id plus # plus block number; the last accepted same-position event in a block overwrites it"
            || execution.fee_refresh_handlers != ["collect", "decrease", "increase"]
            || execution.fee_refresh_revert != "preserve prior fee-growth-inside values"
            || execution.snapshot_handlers != ["collect", "decrease", "increase", "transfer"]
            || execution.excluded_pool != hex::encode(EXCLUDED_POOL)
            || execution.excluded_pool_handlers != ["collect", "decrease", "increase"]
            || execution.historical_guard_block != HISTORICAL_GUARD_BLOCK
            || execution.historical_guard_handlers != ["decrease", "increase"]
            || execution.historical_guard_order
                != "before Position identity calls, Transaction saves, pool calls, token reads, mutation, fee refresh, and snapshot"
            || execution.transaction_id != "lowercase 0x plus the exact 32-byte transaction hash"
            || execution.transaction_metadata
                != "one exact host-only gas-limit and gas-price record per referenced transaction hash; receipt gas is excluded"
            || execution.legacy_stored_gas_used
                != "apiVersion 0.0.4 writes the transaction gas_limit exposed to the mapping as event.transaction.gasUsed"
            || execution.current_stored_gas_used
                != "apiVersion 0.0.7 writes zero while preserving gasPrice"
            || execution.new_position_transaction_loads != 2
            || execution.existing_position_transaction_loads != 1
            || execution.transaction_save_observability
                != "every attempted helper call in the modeled event prefix through the first fatal error is retained in the ordered diagnostic outcome even when identical ids overwrite one entity"
            || execution.normal_return_orphans
                != [
                    "new identity followed by excluded-pool return",
                    "new identity followed by current Increase or Decrease missing-token return",
                ]
            || execution.position_transaction != "first successfully persisted identity-creation transaction"
            || execution.snapshot_transaction
                != "current accepted event transaction; last accepted same-position event in a block overwrites the snapshot"
            || execution.physical_side_effect_scope
                != "final persisted NPM user-entity projection only; post-fatal handlers, dynamic stages, retryable failures, calls, attempts, persisted data sources, VID allocation, proof-of-indexing, and error streams are not modeled"
        {
            return Err(Error::msg("NPM-handler reducer execution contract drift"));
        }
        Ok(())
    }

    fn validate_network_contracts(&self) -> Result<(), Error> {
        let expected = [
            (
                Network::Mainnet,
                "1f98431c8ad98523631ae4a59f267346ea31f984",
                "c36442b4a4522e871399cd717abdd847ab11fe88",
                12_369_621,
                12_369_651,
            ),
            (
                Network::Base,
                "33128a8fc17869897dce68ed026d694621f6fdfd",
                "03a520b32c04bf3beef7beb72e919cf822ed34f1",
                1_371_679,
                1_371_713,
            ),
        ];
        if self.network_contracts.len() != expected.len() {
            return Err(Error::msg("position-reducer network contract count drift"));
        }
        for (actual, expected) in self.network_contracts.iter().zip(expected) {
            if (
                actual.network,
                actual.factory.as_str(),
                actual.nonfungible_position_manager.as_str(),
                actual.runtime_start_block,
                actual.npm_start_block,
            ) != expected
            {
                return Err(Error::msg("position-reducer network contract drift"));
            }
            actual.factory_address()?;
            actual.position_manager_address()?;
        }
        Ok(())
    }

    fn validate_profiles(&self) -> Result<(), Error> {
        let expected = [
            (
                "mainnet-root-correct-collect",
                CollectMode::OwnFieldAmounts,
                &[TokenRead::Token0, TokenRead::Token1][..],
                MissingTokenPolicy::DeterministicError,
                MissingTokenPolicy::DeterministicError,
            ),
            (
                "mainnet-second-fee0-overwrite",
                CollectMode::Fee0FromFee1PlusAmount1,
                &[TokenRead::Token0, TokenRead::Token1][..],
                MissingTokenPolicy::DeterministicError,
                MissingTokenPolicy::DeterministicError,
            ),
            (
                "mainnet-no-collect-amounts",
                CollectMode::NoAmountAccumulation,
                &[][..],
                MissingTokenPolicy::NoTokenRead,
                MissingTokenPolicy::DeterministicError,
            ),
            (
                "base-root-amount0-to-both",
                CollectMode::Amount0ToBoth,
                &[TokenRead::Token0][..],
                MissingTokenPolicy::DeterministicError,
                MissingTokenPolicy::DeterministicError,
            ),
            (
                "current-amount0-to-both",
                CollectMode::Amount0ToBothIfToken0Exists,
                &[TokenRead::Token0][..],
                MissingTokenPolicy::PreserveAmountsRefreshAndSave,
                MissingTokenPolicy::DropEvent,
            ),
        ];
        if self.npm_profiles.len() != expected.len() {
            return Err(Error::msg("position-reducer NPM profile count drift"));
        }
        for (profile, (id, mode, reads, collect_missing, liquidity_missing)) in self.npm_profiles.iter().zip(expected) {
            if profile.profile_id != id
                || profile.collect_mode != mode
                || profile.collect_token_reads != reads
                || profile.collect_missing_token_policy != collect_missing
                || profile.increase_decrease_missing_token_policy != liquidity_missing
            {
                return Err(Error::msg("position-reducer NPM profile drift"));
            }
        }
        Ok(())
    }

    fn validate_segments(&self) -> Result<(), Error> {
        type SegmentRange = (Network, u64, Option<u64>, bool, bool, &'static str, StoredGasUsedMode);
        const RANGES: &[SegmentRange] = &[
            (
                Network::Mainnet,
                12_369_621,
                Some(13_450_880),
                false,
                false,
                "0.0.4",
                StoredGasUsedMode::TransactionGasLimit,
            ),
            (
                Network::Mainnet,
                13_450_881,
                Some(13_498_328),
                false,
                false,
                "0.0.4",
                StoredGasUsedMode::TransactionGasLimit,
            ),
            (
                Network::Mainnet,
                13_498_329,
                Some(13_591_197),
                false,
                false,
                "0.0.4",
                StoredGasUsedMode::TransactionGasLimit,
            ),
            (
                Network::Mainnet,
                13_591_198,
                Some(13_605_860),
                false,
                false,
                "0.0.4",
                StoredGasUsedMode::TransactionGasLimit,
            ),
            (
                Network::Mainnet,
                13_605_861,
                Some(19_470_000),
                false,
                false,
                "0.0.4",
                StoredGasUsedMode::TransactionGasLimit,
            ),
            (
                Network::Mainnet,
                19_470_001,
                None,
                true,
                false,
                "0.0.7",
                StoredGasUsedMode::Zero,
            ),
            (
                Network::Base,
                1_371_679,
                Some(19_852_000),
                true,
                true,
                "0.0.4",
                StoredGasUsedMode::TransactionGasLimit,
            ),
            (
                Network::Base,
                19_852_001,
                None,
                true,
                false,
                "0.0.7",
                StoredGasUsedMode::Zero,
            ),
        ];
        if self.segments.len() != RANGES.len() {
            return Err(Error::msg("position-reducer requires exactly eight ordered segments"));
        }
        for (segment, expected) in self.segments.iter().zip(RANGES) {
            if (
                segment.network,
                segment.start_block_inclusive,
                segment.end_block_inclusive,
                segment.nonfatal_errors,
                segment.historical_guard_effective,
                segment.api_version.as_str(),
                segment.stored_gas_used_mode,
            ) != *expected
                || segment.segment_id != format!("{}:{}", segment.network.as_str(), segment.deployment)
                || segment.deployment.len() != 46
                || !segment.deployment.starts_with("Qm")
                || segment.semantic_contract_sha256.len() != 64
                || !self
                    .npm_profiles
                    .iter()
                    .any(|profile| profile.profile_id == segment.npm_profile_id)
            {
                return Err(Error::msg("position-reducer segment binding drift"));
            }
        }
        Ok(())
    }

    fn select(&self, network: Network, block: u64) -> Result<&Segment, Error> {
        let mut matches = self.segments.iter().filter(|segment| segment.includes(network, block));
        let segment = matches.next().ok_or_else(|| {
            Error::msg(format!(
                "no position-reducer segment for {} block {block}",
                network.as_str()
            ))
        })?;
        if matches.next().is_some() {
            return Err(Error::msg("overlapping position-reducer segments"));
        }
        Ok(segment)
    }

    fn profile(&self, id: &str) -> Result<&NpmProfile, Error> {
        self.npm_profiles
            .iter()
            .find(|profile| profile.profile_id == id)
            .ok_or_else(|| Error::msg(format!("unknown position-reducer NPM profile `{id}`")))
    }

    fn network_contract(&self, network: Network) -> Result<&NetworkContract, Error> {
        self.network_contracts
            .iter()
            .find(|contract| contract.network == network)
            .ok_or_else(|| Error::msg("position-reducer network contract missing"))
    }
}

struct GraphCallCache<'a, I: ReducerInputs> {
    inputs: &'a mut I,
    scope: BlockScope,
    positions: BTreeMap<(Address, String), Result<Option<PositionCall>, String>>,
    pools: BTreeMap<(Address, Address, Address, u32), Result<Address, String>>,
}

impl<'a, I: ReducerInputs> GraphCallCache<'a, I> {
    fn new(inputs: &'a mut I, scope: BlockScope) -> Self {
        Self {
            inputs,
            scope,
            positions: BTreeMap::new(),
            pools: BTreeMap::new(),
        }
    }

    fn position(&mut self, position_manager: Address, token_id: &str) -> Result<Option<PositionCall>, HandlerError> {
        let key = (position_manager, token_id.to_string());
        if !self.positions.contains_key(&key) {
            let result = self
                .inputs
                .position_at_block(&self.scope, position_manager, token_id)
                .and_then(|result| {
                    if let Some(call) = &result {
                        validate_position_call(call).map_err(|error| error.0)?;
                    }
                    Ok(result)
                });
            self.positions.insert(key.clone(), result);
        }
        self.positions
            .get(&key)
            .expect("position result inserted")
            .clone()
            .map_err(|message| HandlerError::new(format!("positions({token_id}) failed: {message}")))
    }

    fn pool(&mut self, factory: Address, call: &PositionCall) -> Result<Address, HandlerError> {
        let key = (factory, call.token0, call.token1, call.fee);
        let result = if let Some(result) = self.pools.get(&key) {
            result.clone()
        } else {
            let result = self
                .inputs
                .pool_at_block(&self.scope, factory, call.token0, call.token1, call.fee);
            self.pools.insert(key, result.clone());
            result
        };
        result.map_err(|message| HandlerError::new(format!("getPool failed: {message}")))
    }

    fn token_decimals(&mut self, address: Address, ordinal: u64) -> Result<Option<u8>, HandlerError> {
        self.inputs
            .token_decimals_at_ordinal(address, ordinal)
            .map_err(|message| HandlerError::new(format!("Token.load at ordinal {ordinal} failed: {message}")))
    }
}

/// Project final persisted NPM user-entity state for one block.
///
/// A legacy fatal error returns the block baseline at the first failing event
/// because Graph's eventual fatal transaction filters all user-entity changes.
/// Outcomes are only the WriterEvents prefix consumed by this reducer;
/// `omitted_event_count` reports the remaining reducer suffix, not later Graph
/// triggers or dynamic stages. This is deliberately not a Graph execution
/// trace: Graph continues runnable triggers and breadth-first dynamic stages,
/// while this diagnostic omits all later handlers, retryable failures, calls,
/// attempts, data sources, PoI, and error-stream effects. No returned
/// disposition authorizes Graph block or checkpoint success.
pub fn reduce_npm_handler_block<I: ReducerInputs>(
    initial: &ReducerState,
    input: &DiagnosticInput,
    inputs: &mut I,
) -> Result<BlockReduction, Error> {
    let contract = ReducerContract::embedded()?;
    let events = &input.writer_events;
    let block = &input.block;
    let network = Network::parse(&events.network)?;
    if block.number != events.block_number {
        return Err(Error::msg("NPM-handler reducer BlockContext number drift"));
    }
    let network_contract = contract.network_contract(network)?;
    let segment = contract.select(network, events.block_number)?;
    if events.segment_id != segment.segment_id
        || events.segment_semantic_contract_sha256 != segment.semantic_contract_sha256
        || events.source_writer_contract_sha256 != SOURCE_WRITER_CONTRACT_SHA256
    {
        return Err(Error::msg("NPM-handler reducer WriterEvents binding drift"));
    }
    if events.block_number < network_contract.npm_start_block && !events.events.is_empty() {
        return Err(Error::msg(
            "NPM-handler reducer received events before the producer NPM gate",
        ));
    }
    let position_manager = network_contract.position_manager_address()?;
    let factory = network_contract.factory_address()?;
    validate_events(events, position_manager)?;
    let profile = contract.profile(&segment.npm_profile_id)?;
    validate_state(initial)?;
    validate_diagnostic_inputs(input)?;
    let metadata = input
        .transactions
        .iter()
        .map(|item| (item.transaction_hash, item))
        .collect::<BTreeMap<_, _>>();
    let controls = input
        .controls
        .iter()
        .map(|item| (item.ordinal, item))
        .collect::<BTreeMap<_, _>>();
    let baseline = initial.clone();
    let mut working = initial.clone();
    let scope = BlockScope {
        network: events.network.clone(),
        block_number: events.block_number,
        block_hash: block.hash,
    };
    let mut cache = GraphCallCache::new(inputs, scope);
    let mut outcomes = Vec::with_capacity(events.events.len());

    for event in &events.events {
        let (kind, token_id) = event_identity(event)?;
        let transaction_hash = exact_transaction_hash(&event.transaction_hash)?;
        let transaction_id = transaction_id(&transaction_hash);
        let transaction = metadata[&transaction_hash];
        let control = controls[&event.ordinal];
        let mut scratch = working.clone();
        let mut attempted_writes = Vec::new();
        let result = reduce_event(
            &mut scratch,
            event,
            kind,
            &token_id,
            block,
            transaction,
            control,
            position_manager,
            factory,
            segment,
            profile,
            &mut cache,
            &mut attempted_writes,
        );
        match result {
            Ok(EventEffect::Commit) => {
                working = scratch;
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    transaction_id,
                    disposition: EventDisposition::Committed,
                    attempted_writes,
                    event_state_committed: true,
                    block_state_committed: true,
                });
            }
            Ok(EventEffect::NormalReturn(reason)) => {
                working = scratch;
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    transaction_id,
                    disposition: EventDisposition::NormalReturn(reason),
                    attempted_writes,
                    event_state_committed: true,
                    block_state_committed: true,
                });
            }
            Err(ExecutionFailure::Invalid(message)) => return Err(Error::msg(message)),
            Err(ExecutionFailure::Handler(error)) if segment.nonfatal_errors => outcomes.push(EventOutcome {
                ordinal: event.ordinal,
                token_id,
                kind,
                transaction_id,
                disposition: EventDisposition::NonFatalError(error.0),
                attempted_writes,
                event_state_committed: false,
                block_state_committed: false,
            }),
            Err(ExecutionFailure::Handler(error)) => {
                let message = error.0;
                for outcome in &mut outcomes {
                    outcome.block_state_committed = false;
                }
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    transaction_id,
                    disposition: EventDisposition::FatalError(message.clone()),
                    attempted_writes,
                    event_state_committed: false,
                    block_state_committed: false,
                });
                let omitted_event_count = events.events.len() - outcomes.len();
                return Ok(BlockReduction {
                    state: baseline,
                    outcomes,
                    disposition: BlockDisposition::FatalNpmUserEntityProjection {
                        ordinal: event.ordinal,
                        message,
                        omitted_event_count,
                    },
                    segment_id: segment.segment_id.clone(),
                });
            }
        }
    }

    Ok(BlockReduction {
        state: working,
        outcomes,
        disposition: BlockDisposition::ModeledNpmUserEntityProjectionComplete,
        segment_id: segment.segment_id.clone(),
    })
}

#[allow(clippy::too_many_arguments)]
fn reduce_event<I: ReducerInputs>(
    state: &mut ReducerState,
    event: &WriterEvent,
    kind: EventKind,
    token_id: &str,
    block: &BlockContext,
    transaction: &TransactionMetadata,
    control: &EventControl,
    position_manager: Address,
    factory: Address,
    segment: &Segment,
    profile: &NpmProfile,
    cache: &mut GraphCallCache<'_, I>,
    attempted_writes: &mut Vec<EntityWriteSite>,
) -> Result<EventEffect, ExecutionFailure> {
    if segment.historical_guard_effective
        && block.number == HISTORICAL_GUARD_BLOCK
        && matches!(kind, EventKind::Increase | EventKind::Decrease)
    {
        require_no_unreachable_failure(control, event.ordinal)?;
        return Ok(EventEffect::NormalReturn(NormalReturnReason::HistoricalGuard));
    }

    let new_identity = !state.positions.contains_key(token_id);
    let mut position = match state.positions.get(token_id) {
        Some(position) => position.clone(),
        None => {
            let Some(call) = cache.position(position_manager, token_id)? else {
                require_no_unreachable_failure(control, event.ordinal)?;
                return Ok(EventEffect::NormalReturn(NormalReturnReason::MissingPosition));
            };
            let pool = cache.pool(factory, &call)?;
            provisional_position(token_id, event, call, pool)?
        }
    };

    if new_identity {
        load_transaction(
            state,
            transaction,
            block,
            segment.stored_gas_used_mode,
            TransactionLoadSite::PositionCreation,
            attempted_writes,
        );
    }
    if control.failure_phase == FailurePhase::AfterIdentity {
        return Err(HandlerError::new(format!(
            "injected deterministic error after identity at ordinal {}",
            event.ordinal
        ))
        .into());
    }

    if position.pool == EXCLUDED_POOL && !matches!(kind, EventKind::Transfer) {
        require_no_unreachable_failure(control, event.ordinal)?;
        return Ok(EventEffect::NormalReturn(NormalReturnReason::ExcludedPool));
    }

    let event_payload = event
        .event
        .as_ref()
        .ok_or_else(|| HandlerError::new("WriterEvent payload missing"))?;
    match event_payload {
        Event::IncreaseLiquidity(increase) => {
            let Some((token0_decimals, token1_decimals)) =
                liquidity_token_decimals(&position, event.ordinal, profile, cache)?
            else {
                require_no_unreachable_failure(control, event.ordinal)?;
                return Ok(EventEffect::NormalReturn(NormalReturnReason::MissingToken));
            };
            position.liquidity += BigInt::from(parse_unsigned("liquidity", &increase.liquidity)?);
            position.deposited_token0 = position
                .deposited_token0
                .add(&Decimal::from_unsigned_units(&increase.amount0, token0_decimals)?);
            position.deposited_token1 = position
                .deposited_token1
                .add(&Decimal::from_unsigned_units(&increase.amount1, token1_decimals)?);
            refresh_fee_growth(&mut position, position_manager, cache)?;
        }
        Event::DecreaseLiquidity(decrease) => {
            let Some((token0_decimals, token1_decimals)) =
                liquidity_token_decimals(&position, event.ordinal, profile, cache)?
            else {
                require_no_unreachable_failure(control, event.ordinal)?;
                return Ok(EventEffect::NormalReturn(NormalReturnReason::MissingToken));
            };
            position.liquidity -= BigInt::from(parse_unsigned("liquidity", &decrease.liquidity)?);
            position.withdrawn_token0 = position
                .withdrawn_token0
                .add(&Decimal::from_unsigned_units(&decrease.amount0, token0_decimals)?);
            position.withdrawn_token1 = position
                .withdrawn_token1
                .add(&Decimal::from_unsigned_units(&decrease.amount1, token1_decimals)?);
            refresh_fee_growth(&mut position, position_manager, cache)?;
        }
        Event::Collect(collect) => {
            apply_collect(&mut position, event.ordinal, collect, profile, cache)?;
            refresh_fee_growth(&mut position, position_manager, cache)?;
        }
        Event::Transfer(transfer) => {
            position.owner = exact_address("Transfer.to", &transfer.to)?;
        }
    }

    state.positions.insert(token_id.to_owned(), position.clone());
    attempted_writes.push(EntityWriteSite::Position);
    if control.failure_phase == FailurePhase::AfterPositionSave {
        return Err(HandlerError::new(format!(
            "injected deterministic error after Position save at ordinal {}",
            event.ordinal
        ))
        .into());
    }
    load_transaction(
        state,
        transaction,
        block,
        segment.stored_gas_used_mode,
        TransactionLoadSite::PositionSnapshot,
        attempted_writes,
    );
    if control.failure_phase == FailurePhase::AfterSnapshotLoad {
        return Err(HandlerError::new(format!(
            "injected deterministic error after snapshot load at ordinal {}",
            event.ordinal
        ))
        .into());
    }

    let event_transaction =
        exact_transaction_hash(&event.transaction_hash).map_err(|error| HandlerError::new(error.to_string()))?;
    let snapshot = PositionSnapshot::from_position(&position, block.number, block.timestamp, event_transaction);
    state.snapshots.insert(snapshot.id.clone(), snapshot);
    attempted_writes.push(EntityWriteSite::PositionSnapshot);
    Ok(EventEffect::Commit)
}

fn require_no_unreachable_failure(control: &EventControl, ordinal: u64) -> Result<(), ExecutionFailure> {
    if control.failure_phase != FailurePhase::None {
        return Err(ExecutionFailure::invalid(format!(
            "injected failure phase is unreachable after normal return at ordinal {ordinal}"
        )));
    }
    Ok(())
}

fn load_transaction(
    state: &mut ReducerState,
    metadata: &TransactionMetadata,
    block: &BlockContext,
    mode: StoredGasUsedMode,
    site: TransactionLoadSite,
    attempted_writes: &mut Vec<EntityWriteSite>,
) {
    let id = transaction_id(&metadata.transaction_hash);
    let gas_used = match mode {
        StoredGasUsedMode::TransactionGasLimit => metadata.gas_limit.clone(),
        StoredGasUsedMode::Zero => "0".to_owned(),
    };
    state.transactions.insert(
        id.clone(),
        TransactionEntity {
            id,
            block_number: block.number,
            timestamp: block.timestamp,
            gas_used,
            gas_price: metadata.gas_price.clone(),
        },
    );
    attempted_writes.push(EntityWriteSite::Transaction(site));
}

fn provisional_position(
    token_id: &str,
    event: &WriterEvent,
    call: PositionCall,
    pool: Address,
) -> Result<Position, HandlerError> {
    let transaction =
        exact_transaction_hash(&event.transaction_hash).map_err(|error| HandlerError::new(error.to_string()))?;
    Ok(Position {
        token_id: token_id.to_string(),
        owner: [0; 20],
        pool,
        token0: call.token0,
        token1: call.token1,
        tick_lower: call.tick_lower,
        tick_upper: call.tick_upper,
        liquidity: BigInt::zero(),
        deposited_token0: Decimal::zero(),
        deposited_token1: Decimal::zero(),
        withdrawn_token0: Decimal::zero(),
        withdrawn_token1: Decimal::zero(),
        collected_fees_token0: Decimal::zero(),
        collected_fees_token1: Decimal::zero(),
        transaction,
        fee_growth_inside0_last_x128: call.fee_growth_inside0_last_x128,
        fee_growth_inside1_last_x128: call.fee_growth_inside1_last_x128,
    })
}

fn liquidity_token_decimals<I: ReducerInputs>(
    position: &Position,
    ordinal: u64,
    profile: &NpmProfile,
    cache: &mut GraphCallCache<'_, I>,
) -> Result<Option<(u8, u8)>, HandlerError> {
    let token0 = cache.token_decimals(position.token0, ordinal)?;
    let token1 = cache.token_decimals(position.token1, ordinal)?;
    match (token0, token1) {
        (Some(token0), Some(token1)) => Ok(Some((token0, token1))),
        _ if profile.increase_decrease_missing_token_policy == MissingTokenPolicy::DropEvent => Ok(None),
        _ => Err(HandlerError::new(format!(
            "legacy Token.load dereference failed at ordinal {ordinal}"
        ))),
    }
}

fn apply_collect<I: ReducerInputs>(
    position: &mut Position,
    ordinal: u64,
    collect: &crate::pb::writer::Collect,
    profile: &NpmProfile,
    cache: &mut GraphCallCache<'_, I>,
) -> Result<(), HandlerError> {
    match profile.collect_mode {
        CollectMode::OwnFieldAmounts => {
            let (token0, token1) = required_collect_tokens(position, ordinal, profile, cache)?;
            let amount0 = Decimal::from_unsigned_units(&collect.amount0, token0)?;
            let amount1 = Decimal::from_unsigned_units(&collect.amount1, token1)?;
            position.collected_fees_token0 = position.collected_fees_token0.add(&amount0);
            position.collected_fees_token1 = position.collected_fees_token1.add(&amount1);
        }
        CollectMode::Fee0FromFee1PlusAmount1 => {
            let (token0, token1) = required_collect_tokens(position, ordinal, profile, cache)?;
            let _amount0 = Decimal::from_unsigned_units(&collect.amount0, token0)?;
            let amount1 = Decimal::from_unsigned_units(&collect.amount1, token1)?;
            position.collected_fees_token0 = position.collected_fees_token1.add(&amount1);
        }
        CollectMode::NoAmountAccumulation => {
            if profile.collect_missing_token_policy != MissingTokenPolicy::NoTokenRead {
                return Err(HandlerError::new("no-amount Collect profile policy drift"));
            }
        }
        CollectMode::Amount0ToBoth => {
            if profile.collect_token_reads != [TokenRead::Token0]
                || profile.collect_missing_token_policy != MissingTokenPolicy::DeterministicError
            {
                return Err(HandlerError::new("Base-root Collect profile policy drift"));
            }
            let token0 = cache.token_decimals(position.token0, ordinal)?.ok_or_else(|| {
                HandlerError::new(format!("legacy Token.load dereference failed at ordinal {ordinal}"))
            })?;
            let amount0 = Decimal::from_unsigned_units(&collect.amount0, token0)?;
            position.collected_fees_token0 = position.collected_fees_token0.add(&amount0);
            position.collected_fees_token1 = position.collected_fees_token1.add(&amount0);
        }
        CollectMode::Amount0ToBothIfToken0Exists => {
            if profile.collect_token_reads != [TokenRead::Token0]
                || profile.collect_missing_token_policy != MissingTokenPolicy::PreserveAmountsRefreshAndSave
            {
                return Err(HandlerError::new("current Collect profile policy drift"));
            }
            if let Some(token0) = cache.token_decimals(position.token0, ordinal)? {
                let amount0 = Decimal::from_unsigned_units(&collect.amount0, token0)?;
                position.collected_fees_token0 = position.collected_fees_token0.add(&amount0);
                position.collected_fees_token1 = position.collected_fees_token1.add(&amount0);
            }
        }
    }
    Ok(())
}

fn required_collect_tokens<I: ReducerInputs>(
    position: &Position,
    ordinal: u64,
    profile: &NpmProfile,
    cache: &mut GraphCallCache<'_, I>,
) -> Result<(u8, u8), HandlerError> {
    if profile.collect_token_reads != [TokenRead::Token0, TokenRead::Token1]
        || profile.collect_missing_token_policy != MissingTokenPolicy::DeterministicError
    {
        return Err(HandlerError::new("legacy Collect profile policy drift"));
    }
    let token0 = cache.token_decimals(position.token0, ordinal)?;
    let token1 = cache.token_decimals(position.token1, ordinal)?;
    match (token0, token1) {
        (Some(token0), Some(token1)) => Ok((token0, token1)),
        _ => Err(HandlerError::new(format!(
            "legacy Token.load dereference failed at ordinal {ordinal}"
        ))),
    }
}

fn refresh_fee_growth<I: ReducerInputs>(
    position: &mut Position,
    position_manager: Address,
    cache: &mut GraphCallCache<'_, I>,
) -> Result<(), HandlerError> {
    if let Some(call) = cache.position(position_manager, &position.token_id)? {
        position.fee_growth_inside0_last_x128 = call.fee_growth_inside0_last_x128;
        position.fee_growth_inside1_last_x128 = call.fee_growth_inside1_last_x128;
    }
    Ok(())
}

fn validate_diagnostic_inputs(input: &DiagnosticInput) -> Result<(), Error> {
    let referenced_hashes = input
        .writer_events
        .events
        .iter()
        .map(|event| exact_transaction_hash(&event.transaction_hash))
        .collect::<Result<BTreeSet<_>, _>>()?;
    let event_ordinals = input
        .writer_events
        .events
        .iter()
        .map(|event| event.ordinal)
        .collect::<BTreeSet<_>>();

    let mut metadata_hashes = BTreeSet::new();
    for metadata in &input.transactions {
        if !metadata_hashes.insert(metadata.transaction_hash) {
            return Err(Error::msg(format!(
                "duplicate transaction metadata for {}",
                transaction_id(&metadata.transaction_hash)
            )));
        }
        parse_unsigned("transaction gas limit", &metadata.gas_limit).map_err(|error| Error::msg(error.0))?;
        parse_unsigned("transaction gas price", &metadata.gas_price).map_err(|error| Error::msg(error.0))?;
    }
    if metadata_hashes != referenced_hashes {
        return Err(Error::msg(
            "transaction metadata set must exactly match referenced writer-event hashes",
        ));
    }

    let mut control_ordinals = BTreeSet::new();
    for control in &input.controls {
        if !control_ordinals.insert(control.ordinal) {
            return Err(Error::msg(format!(
                "duplicate event control ordinal {}",
                control.ordinal
            )));
        }
    }
    if control_ordinals != event_ordinals {
        return Err(Error::msg("event control ordinals must exactly match writer events"));
    }
    Ok(())
}

fn validate_events(events: &WriterEvents, position_manager: Address) -> Result<(), Error> {
    let mut previous = None;
    let mut previous_block_index = None;
    for event in &events.events {
        if event.block_number != events.block_number {
            return Err(Error::msg("position-reducer event block-number drift"));
        }
        if previous.map_or(false, |ordinal| ordinal >= event.ordinal) {
            return Err(Error::msg(
                "position-reducer events must have strictly increasing global ordinals",
            ));
        }
        previous = Some(event.ordinal);
        if previous_block_index.map_or(false, |index| index >= event.block_log_index) {
            return Err(Error::msg(
                "position-reducer block log indices must be strictly increasing with ordinals",
            ));
        }
        previous_block_index = Some(event.block_log_index);
        exact_transaction_hash(&event.transaction_hash)?;
        if exact_address("event contract address", &event.contract_address).map_err(|error| Error::msg(error.0))?
            != position_manager
        {
            return Err(Error::msg(
                "position-reducer event contract address is not the configured NPM",
            ));
        }
        event_identity(event)?;
        validate_producer_payload(event)?;
    }
    Ok(())
}

fn validate_producer_payload(event: &WriterEvent) -> Result<(), Error> {
    let validate_uint = |field: &str, value: &str| {
        parse_unsigned(field, value)
            .map(|_| ())
            .map_err(|error| Error::msg(format!("position-reducer producer corruption: {}", error.0)))
    };
    let validate_address = |field: &str, value: &[u8]| {
        exact_address(field, value)
            .map(|_| ())
            .map_err(|error| Error::msg(format!("position-reducer producer corruption: {}", error.0)))
    };
    match event
        .event
        .as_ref()
        .ok_or_else(|| Error::msg("position-reducer WriterEvent payload missing"))?
    {
        Event::IncreaseLiquidity(value) => {
            validate_uint("IncreaseLiquidity.liquidity", &value.liquidity)?;
            validate_uint("IncreaseLiquidity.amount0", &value.amount0)?;
            validate_uint("IncreaseLiquidity.amount1", &value.amount1)?;
        }
        Event::DecreaseLiquidity(value) => {
            validate_uint("DecreaseLiquidity.liquidity", &value.liquidity)?;
            validate_uint("DecreaseLiquidity.amount0", &value.amount0)?;
            validate_uint("DecreaseLiquidity.amount1", &value.amount1)?;
        }
        Event::Collect(value) => {
            validate_address("Collect.recipient", &value.recipient)?;
            validate_uint("Collect.amount0", &value.amount0)?;
            validate_uint("Collect.amount1", &value.amount1)?;
        }
        Event::Transfer(value) => {
            validate_address("Transfer.from", &value.from)?;
            validate_address("Transfer.to", &value.to)?;
        }
    }
    Ok(())
}

fn validate_position_call(call: &PositionCall) -> Result<(), HandlerError> {
    const MAX_U24: u32 = (1_u32 << 24) - 1;
    const MIN_I24: i32 = -(1_i32 << 23);
    const MAX_I24: i32 = (1_i32 << 23) - 1;
    if call.fee > MAX_U24 {
        return Err(HandlerError::new("positions fee exceeds uint24"));
    }
    if !(MIN_I24..=MAX_I24).contains(&call.tick_lower) || !(MIN_I24..=MAX_I24).contains(&call.tick_upper) {
        return Err(HandlerError::new("positions tick exceeds int24"));
    }
    let maximum = maximum_uint256();
    if call.fee_growth_inside0_last_x128 > maximum || call.fee_growth_inside1_last_x128 > maximum {
        return Err(HandlerError::new("positions fee growth exceeds uint256"));
    }
    Ok(())
}

fn validate_state(state: &ReducerState) -> Result<(), Error> {
    for (key, transaction) in &state.transactions {
        if key != &transaction.id || !valid_transaction_id(key) {
            return Err(Error::msg(format!("invalid Transaction state identity `{key}`")));
        }
        parse_unsigned("Transaction.gasUsed", &transaction.gas_used).map_err(|error| Error::msg(error.0))?;
        parse_unsigned("Transaction.gasPrice", &transaction.gas_price).map_err(|error| Error::msg(error.0))?;
    }
    for (key, position) in &state.positions {
        if key != &position.token_id {
            return Err(Error::msg("position-reducer state key/identity drift"));
        }
        parse_unsigned("position token id", key).map_err(|error| Error::msg(error.0))?;
    }
    for (key, snapshot) in &state.snapshots {
        if key != &snapshot.id || snapshot.id != format!("{}#{}", snapshot.position, snapshot.block_number) {
            return Err(Error::msg("position-reducer snapshot identity drift"));
        }
    }
    Ok(())
}

fn event_identity(event: &WriterEvent) -> Result<(EventKind, String), Error> {
    let (kind, token_id) = match event.event.as_ref() {
        Some(Event::IncreaseLiquidity(value)) => (EventKind::Increase, &value.token_id),
        Some(Event::DecreaseLiquidity(value)) => (EventKind::Decrease, &value.token_id),
        Some(Event::Collect(value)) => (EventKind::Collect, &value.token_id),
        Some(Event::Transfer(value)) => (EventKind::Transfer, &value.token_id),
        None => return Err(Error::msg("position-reducer WriterEvent payload missing")),
    };
    let parsed = parse_unsigned("token id", token_id).map_err(|error| Error::msg(error.0))?;
    if parsed.to_str_radix(10) != *token_id {
        return Err(Error::msg(
            "position-reducer token id must be canonical unsigned decimal",
        ));
    }
    Ok((kind, token_id.clone()))
}

fn parse_unsigned(field: &str, value: &str) -> Result<BigUint, HandlerError> {
    if value.is_empty()
        || !value.bytes().all(|byte| byte.is_ascii_digit())
        || (value.len() > 1 && value.starts_with('0'))
    {
        return Err(HandlerError::new(format!("{field} must be canonical unsigned decimal")));
    }
    let parsed = BigUint::parse_bytes(value.as_bytes(), 10)
        .ok_or_else(|| HandlerError::new(format!("invalid {field} `{value}`")))?;
    let maximum = maximum_uint256();
    if parsed > maximum {
        return Err(HandlerError::new(format!("{field} exceeds uint256")));
    }
    Ok(parsed)
}

fn maximum_uint256() -> BigUint {
    (BigUint::from(1_u8) << 256_u32) - BigUint::from(1_u8)
}

fn exact_address(field: &str, value: &[u8]) -> Result<Address, HandlerError> {
    value
        .try_into()
        .map_err(|_| HandlerError::new(format!("{field} must be 20 bytes")))
}

fn exact_transaction_hash(value: &[u8]) -> Result<TransactionHash, Error> {
    value
        .try_into()
        .map_err(|_| Error::msg("position-reducer transaction hash must be 32 bytes"))
}

fn transaction_id(hash: &TransactionHash) -> String {
    let mut output = String::with_capacity(66);
    output.push_str("0x");
    for byte in hash {
        write!(&mut output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

fn valid_transaction_id(value: &str) -> bool {
    value.len() == 66
        && value.starts_with("0x")
        && value[2..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn decode_contract_address(field: &str, value: &str) -> Result<Address, Error> {
    if value.len() != 40
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(Error::msg(format!(
            "position-reducer {field} must be a lowercase 20-byte address"
        )));
    }
    let decoded =
        hex::decode(value).map_err(|error| Error::msg(format!("position-reducer invalid {field}: {error}")))?;
    decoded
        .try_into()
        .map_err(|_| Error::msg(format!("position-reducer {field} must be 20 bytes")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pb::writer::{Collect, DecreaseLiquidity, IncreaseLiquidity, Transfer};

    const TOKEN0: Address = [0x10; 20];
    const TOKEN1: Address = [0x11; 20];
    const POOL: Address = [0x20; 20];
    const OWNER: Address = [0x30; 20];
    const NEW_OWNER: Address = [0x31; 20];

    #[derive(Clone, Debug, PartialEq, Eq)]
    enum CallRecord {
        Position(BlockScope, Address, String),
        Pool(BlockScope, Address, Address, Address, u32),
        Token(Address, u64),
    }

    type PoolLookupKey = (String, u64, Address, Address, u32);

    #[derive(Default)]
    struct FakeInputs {
        positions: BTreeMap<(String, u64, String), Result<Option<PositionCall>, String>>,
        pools: BTreeMap<PoolLookupKey, Result<Address, String>>,
        tokens: BTreeMap<(Address, u64), Result<Option<u8>, String>>,
        calls: Vec<CallRecord>,
    }

    impl FakeInputs {
        fn position(&mut self, network: &str, block: u64, token_id: &str, value: Option<PositionCall>) {
            self.positions
                .insert((network.to_owned(), block, token_id.to_owned()), Ok(value));
        }

        fn position_error(&mut self, network: &str, block: u64, token_id: &str, message: &str) {
            self.positions.insert(
                (network.to_owned(), block, token_id.to_owned()),
                Err(message.to_owned()),
            );
        }

        fn pool(&mut self, network: &str, block: u64, call: &PositionCall, pool: Address) {
            self.pools.insert(
                (network.to_owned(), block, call.token0, call.token1, call.fee),
                Ok(pool),
            );
        }

        fn pool_error(&mut self, network: &str, block: u64, call: &PositionCall, message: &str) {
            self.pools.insert(
                (network.to_owned(), block, call.token0, call.token1, call.fee),
                Err(message.to_owned()),
            );
        }

        fn token(&mut self, address: Address, ordinal: u64, decimals: Option<u8>) {
            self.tokens.insert((address, ordinal), Ok(decimals));
        }
    }

    impl ReducerInputs for FakeInputs {
        fn position_at_block(
            &mut self,
            scope: &BlockScope,
            position_manager: Address,
            token_id: &str,
        ) -> Result<Option<PositionCall>, String> {
            self.calls.push(CallRecord::Position(
                scope.clone(),
                position_manager,
                token_id.to_owned(),
            ));
            self.positions
                .get(&(scope.network.clone(), scope.block_number, token_id.to_owned()))
                .cloned()
                .unwrap_or(Ok(None))
        }

        fn pool_at_block(
            &mut self,
            scope: &BlockScope,
            factory: Address,
            token0: Address,
            token1: Address,
            fee: u32,
        ) -> Result<Address, String> {
            self.calls
                .push(CallRecord::Pool(scope.clone(), factory, token0, token1, fee));
            self.pools
                .get(&(scope.network.clone(), scope.block_number, token0, token1, fee))
                .cloned()
                .unwrap_or_else(|| Err("unconfigured pool call".to_owned()))
        }

        fn token_decimals_at_ordinal(&mut self, address: Address, ordinal: u64) -> Result<Option<u8>, String> {
            self.calls.push(CallRecord::Token(address, ordinal));
            self.tokens.get(&(address, ordinal)).cloned().unwrap_or(Ok(None))
        }
    }

    fn position_call(fee0: u64, fee1: u64) -> PositionCall {
        PositionCall {
            token0: TOKEN0,
            token1: TOKEN1,
            fee: 3_000,
            tick_lower: -120,
            tick_upper: 120,
            fee_growth_inside0_last_x128: fee0.into(),
            fee_growth_inside1_last_x128: fee1.into(),
        }
    }

    fn seed(token_id: &str) -> Position {
        Position {
            token_id: token_id.to_owned(),
            owner: OWNER,
            pool: POOL,
            token0: TOKEN0,
            token1: TOKEN1,
            tick_lower: -120,
            tick_upper: 120,
            liquidity: BigInt::from(100_u64),
            deposited_token0: Decimal::parse("1").unwrap(),
            deposited_token1: Decimal::parse("2").unwrap(),
            withdrawn_token0: Decimal::zero(),
            withdrawn_token1: Decimal::zero(),
            collected_fees_token0: Decimal::parse("3").unwrap(),
            collected_fees_token1: Decimal::parse("4").unwrap(),
            transaction: [0xaa; 32],
            fee_growth_inside0_last_x128: 5_u64.into(),
            fee_growth_inside1_last_x128: 6_u64.into(),
        }
    }

    fn partial_state(positions: impl IntoIterator<Item = Position>) -> ReducerState {
        ReducerState {
            transactions: BTreeMap::new(),
            positions: positions
                .into_iter()
                .map(|position| (position.token_id.clone(), position))
                .collect(),
            snapshots: BTreeMap::new(),
        }
    }

    fn transaction(hash: TransactionHash, block: u64) -> TransactionEntity {
        TransactionEntity {
            id: transaction_id(&hash),
            block_number: block,
            timestamp: 1,
            gas_used: "1".to_owned(),
            gas_price: "2".to_owned(),
        }
    }

    fn segment(network: &str, block: u64) -> Segment {
        ReducerContract::embedded()
            .unwrap()
            .select(Network::parse(network).unwrap(), block)
            .unwrap()
            .clone()
    }

    fn writer_events(network: &str, block: u64, mut events: Vec<WriterEvent>) -> WriterEvents {
        let segment = segment(network, block);
        let contract = ReducerContract::embedded().unwrap();
        let npm = contract
            .network_contract(Network::parse(network).unwrap())
            .unwrap()
            .position_manager_address()
            .unwrap();
        for event in &mut events {
            event.contract_address = npm.to_vec();
        }
        WriterEvents {
            events,
            network: network.to_owned(),
            block_number: block,
            segment_id: segment.segment_id,
            source_writer_contract_sha256: SOURCE_WRITER_CONTRACT_SHA256.to_owned(),
            segment_semantic_contract_sha256: segment.semantic_contract_sha256,
        }
    }

    fn common(ordinal: u64, block: u64, event: Event) -> WriterEvent {
        WriterEvent {
            ordinal,
            transaction_hash: vec![ordinal as u8; 32],
            block_number: block,
            transaction_log_index: ordinal as u32,
            block_log_index: ordinal as u32,
            contract_address: vec![0x99; 20],
            event: Some(event),
        }
    }

    fn increase(
        ordinal: u64,
        block: u64,
        token_id: &str,
        liquidity: &str,
        amount0: &str,
        amount1: &str,
    ) -> WriterEvent {
        common(
            ordinal,
            block,
            Event::IncreaseLiquidity(IncreaseLiquidity {
                token_id: token_id.to_owned(),
                liquidity: liquidity.to_owned(),
                amount0: amount0.to_owned(),
                amount1: amount1.to_owned(),
            }),
        )
    }

    fn decrease(
        ordinal: u64,
        block: u64,
        token_id: &str,
        liquidity: &str,
        amount0: &str,
        amount1: &str,
    ) -> WriterEvent {
        common(
            ordinal,
            block,
            Event::DecreaseLiquidity(DecreaseLiquidity {
                token_id: token_id.to_owned(),
                liquidity: liquidity.to_owned(),
                amount0: amount0.to_owned(),
                amount1: amount1.to_owned(),
            }),
        )
    }

    fn collect(ordinal: u64, block: u64, token_id: &str, amount0: &str, amount1: &str) -> WriterEvent {
        common(
            ordinal,
            block,
            Event::Collect(Collect {
                token_id: token_id.to_owned(),
                recipient: vec![0x77; 20],
                amount0: amount0.to_owned(),
                amount1: amount1.to_owned(),
            }),
        )
    }

    fn transfer(ordinal: u64, block: u64, token_id: &str, to: Address) -> WriterEvent {
        common(
            ordinal,
            block,
            Event::Transfer(Transfer {
                from: OWNER.to_vec(),
                to: to.to_vec(),
                token_id: token_id.to_owned(),
            }),
        )
    }

    fn diagnostic(writer_events: WriterEvents, timestamp: u64) -> DiagnosticInput {
        let transactions = writer_events
            .events
            .iter()
            .map(|event| exact_transaction_hash(&event.transaction_hash).unwrap())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .map(|hash| TransactionMetadata {
                transaction_hash: hash,
                gas_limit: (21_000_u64 + u64::from(hash[0])).to_string(),
                gas_price: (100_u64 + u64::from(hash[0])).to_string(),
            })
            .collect();
        let controls = writer_events
            .events
            .iter()
            .map(|event| EventControl {
                ordinal: event.ordinal,
                failure_phase: FailurePhase::None,
            })
            .collect();
        let number = writer_events.block_number;
        DiagnosticInput {
            writer_events,
            block: BlockContext {
                number,
                timestamp,
                hash: Some([number as u8; 32]),
            },
            transactions,
            controls,
        }
    }

    fn set_failure(input: &mut DiagnosticInput, ordinal: u64, phase: FailurePhase) {
        input
            .controls
            .iter_mut()
            .find(|control| control.ordinal == ordinal)
            .unwrap()
            .failure_phase = phase;
    }

    fn configure_new_position(inputs: &mut FakeInputs, network: &str, block: u64, token_id: &str, pool: Address) {
        let call = position_call(7, 8);
        inputs.position(network, block, token_id, Some(call.clone()));
        inputs.pool(network, block, &call, pool);
    }

    fn configure_tokens(inputs: &mut FakeInputs, ordinals: &[u64]) {
        for ordinal in ordinals {
            inputs.token(TOKEN0, *ordinal, Some(2));
            inputs.token(TOKEN1, *ordinal, Some(3));
        }
    }

    fn transaction_write_count(outcome: &EventOutcome) -> usize {
        outcome
            .attempted_writes
            .iter()
            .filter(|site| matches!(site, EntityWriteSite::Transaction(_)))
            .count()
    }

    fn assert_no_graph_block_or_checkpoint_success_authority(disposition: &BlockDisposition) {
        assert!(!disposition.authorizes_graph_block_or_checkpoint_success());
        match disposition {
            BlockDisposition::ModeledNpmUserEntityProjectionComplete => {}
            BlockDisposition::FatalNpmUserEntityProjection { .. } => {}
        }
    }

    #[test]
    fn modeled_and_fatal_block_dispositions_never_authorize_graph_or_checkpoint_success() {
        let modeled = BlockDisposition::ModeledNpmUserEntityProjectionComplete;
        let fatal = BlockDisposition::FatalNpmUserEntityProjection {
            ordinal: 7,
            message: "diagnostic fatal handler error".to_owned(),
            omitted_event_count: 2,
        };
        assert_no_graph_block_or_checkpoint_success_authority(&modeled);
        assert_no_graph_block_or_checkpoint_success_authority(&fatal);
    }

    #[test]
    fn new_and_existing_positions_share_one_ordered_handler_scratch() {
        let block = 20_000_000;
        let events = writer_events("base", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let input = diagnostic(events, 99);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "base", block, "1", POOL);
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert_no_graph_block_or_checkpoint_success_authority(&result.disposition);
        assert_eq!(
            result.disposition,
            BlockDisposition::ModeledNpmUserEntityProjectionComplete
        );
        assert_eq!(
            result.outcomes[0].attempted_writes,
            vec![
                EntityWriteSite::Transaction(TransactionLoadSite::PositionCreation),
                EntityWriteSite::Position,
                EntityWriteSite::Transaction(TransactionLoadSite::PositionSnapshot),
                EntityWriteSite::PositionSnapshot,
            ]
        );
        assert_eq!(transaction_write_count(&result.outcomes[0]), 2);
        assert_eq!(result.state.transactions.len(), 1);
        assert_eq!(result.state.positions["1"].transaction, [10; 32]);
        assert_eq!(result.state.snapshots[&format!("1#{block}")].transaction, [10; 32]);

        let events = writer_events("base", block, vec![transfer(20, block, "1", [0x44; 20])]);
        let input = diagnostic(events, 100);
        let mut calls = FakeInputs::default();
        let result = reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut calls).unwrap();
        assert_eq!(
            result.outcomes[0].attempted_writes,
            vec![
                EntityWriteSite::Position,
                EntityWriteSite::Transaction(TransactionLoadSite::PositionSnapshot),
                EntityWriteSite::PositionSnapshot,
            ]
        );
        assert_eq!(transaction_write_count(&result.outcomes[0]), 1);
        assert_eq!(result.state.positions["1"].transaction, [0xaa; 32]);
        assert_eq!(result.state.snapshots[&format!("1#{block}")].transaction, [20; 32]);
    }

    #[test]
    fn normal_returns_commit_only_reachable_transaction_writes() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![collect(10, block, "1", "1", "1")]);
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "mainnet", block, "1", EXCLUDED_POOL);
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NormalReturn(NormalReturnReason::ExcludedPool)
        );
        assert_eq!(
            result.outcomes[0].attempted_writes,
            vec![EntityWriteSite::Transaction(TransactionLoadSite::PositionCreation)]
        );
        assert_eq!(result.state.transactions.len(), 1);
        assert!(result.state.positions.is_empty());
        assert!(result.state.snapshots.is_empty());

        let mut existing = seed("1");
        existing.pool = EXCLUDED_POOL;
        let events = writer_events("mainnet", block, vec![collect(10, block, "1", "1", "1")]);
        let input = diagnostic(events, 1);
        let result = reduce_npm_handler_block(&partial_state([existing]), &input, &mut FakeInputs::default()).unwrap();
        assert!(result.outcomes[0].attempted_writes.is_empty());
        assert!(result.state.transactions.is_empty());
    }

    #[test]
    fn current_missing_tokens_keep_new_orphan_but_existing_position_writes_nothing() {
        for network in ["mainnet", "base"] {
            let block = 20_000_001;
            let events = writer_events(network, block, vec![increase(10, block, "1", "1", "1", "1")]);
            let input = diagnostic(events, 1);
            let mut calls = FakeInputs::default();
            configure_new_position(&mut calls, network, block, "1", POOL);
            let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
            assert_eq!(
                result.outcomes[0].disposition,
                EventDisposition::NormalReturn(NormalReturnReason::MissingToken)
            );
            assert_eq!(result.state.transactions.len(), 1);
            assert!(result.state.positions.is_empty());

            let events = writer_events(network, block, vec![decrease(10, block, "1", "1", "1", "1")]);
            let input = diagnostic(events, 1);
            let result =
                reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut FakeInputs::default()).unwrap();
            assert!(result.outcomes[0].attempted_writes.is_empty());
            assert!(result.state.transactions.is_empty());
        }
    }

    #[test]
    fn legacy_missing_token_discards_staged_transaction_by_fatal_or_nonfatal_policy() {
        let mainnet_block = 12_400_000;
        let events = writer_events(
            "mainnet",
            mainnet_block,
            vec![increase(10, mainnet_block, "1", "1", "1", "1")],
        );
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "mainnet", mainnet_block, "1", POOL);
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert_no_graph_block_or_checkpoint_success_authority(&result.disposition);
        assert!(matches!(
            &result.disposition,
            BlockDisposition::FatalNpmUserEntityProjection {
                ordinal: 10,
                omitted_event_count: 0,
                ..
            }
        ));
        assert_eq!(transaction_write_count(&result.outcomes[0]), 1);
        assert_eq!(result.state, ReducerState::default());

        let base_block = 10_000_000;
        let events = writer_events(
            "base",
            base_block,
            vec![
                increase(10, base_block, "1", "1", "1", "1"),
                transfer(20, base_block, "2", NEW_OWNER),
            ],
        );
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "base", base_block, "1", POOL);
        configure_new_position(&mut calls, "base", base_block, "2", POOL);
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert!(matches!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert_eq!(result.outcomes[1].disposition, EventDisposition::Committed);
        assert_eq!(result.state.transactions.len(), 1);
        assert!(!result.state.transactions.contains_key(&transaction_id(&[10; 32])));
        assert!(result.state.positions.contains_key("2"));
    }

    #[test]
    fn injected_failures_discard_the_entire_joint_scratch() {
        let block = 20_000_000;
        for (phase, expected_writes) in [
            (FailurePhase::AfterIdentity, 1),
            (FailurePhase::AfterPositionSave, 2),
            (FailurePhase::AfterSnapshotLoad, 3),
        ] {
            let events = writer_events("base", block, vec![transfer(10, block, "1", NEW_OWNER)]);
            let mut input = diagnostic(events, 1);
            set_failure(&mut input, 10, phase);
            let mut calls = FakeInputs::default();
            configure_new_position(&mut calls, "base", block, "1", POOL);
            let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
            assert!(matches!(
                result.outcomes[0].disposition,
                EventDisposition::NonFatalError(_)
            ));
            assert_eq!(result.outcomes[0].attempted_writes.len(), expected_writes);
            assert_eq!(result.state, ReducerState::default());
        }
    }

    #[test]
    fn fatal_failure_restores_exact_block_baseline_after_successful_and_orphan_events() {
        let block = 12_400_000;
        let mut baseline = partial_state([seed("9")]);
        let baseline_transaction = transaction([0xdd; 32], block - 1);
        baseline
            .transactions
            .insert(baseline_transaction.id.clone(), baseline_transaction);
        let events = writer_events(
            "mainnet",
            block,
            vec![
                transfer(10, block, "1", NEW_OWNER),
                collect(20, block, "2", "1", "1"),
                transfer(30, block, "3", NEW_OWNER),
            ],
        );
        let mut input = diagnostic(events, 1);
        set_failure(&mut input, 30, FailurePhase::AfterSnapshotLoad);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "mainnet", block, "1", POOL);
        let mut excluded_call = position_call(7, 8);
        excluded_call.fee = 500;
        calls.position("mainnet", block, "2", Some(excluded_call.clone()));
        calls.pool("mainnet", block, &excluded_call, EXCLUDED_POOL);
        let mut third_call = position_call(7, 8);
        third_call.fee = 1_000;
        calls.position("mainnet", block, "3", Some(third_call.clone()));
        calls.pool("mainnet", block, &third_call, POOL);
        let result = reduce_npm_handler_block(&baseline, &input, &mut calls).unwrap();
        assert!(matches!(
            result.disposition,
            BlockDisposition::FatalNpmUserEntityProjection { ordinal: 30, .. }
        ));
        assert_eq!(result.state, baseline);
        assert!(result.outcomes.iter().all(|outcome| !outcome.block_state_committed));
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert_eq!(
            result.outcomes[1].disposition,
            EventDisposition::NormalReturn(NormalReturnReason::ExcludedPool)
        );
    }

    #[test]
    fn fatal_projection_outcomes_are_only_modeled_prefix_not_graph_execution_trace() {
        let block = 12_400_000;
        let events = writer_events(
            "mainnet",
            block,
            vec![
                transfer(10, block, "1", NEW_OWNER),
                increase(20, block, "2", "1", "1", "1"),
                transfer(30, block, "3", NEW_OWNER),
            ],
        );
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "mainnet", block, "1", POOL);
        configure_new_position(&mut calls, "mainnet", block, "2", POOL);
        configure_new_position(&mut calls, "mainnet", block, "3", POOL);

        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert_no_graph_block_or_checkpoint_success_authority(&result.disposition);
        assert!(matches!(
            &result.disposition,
            BlockDisposition::FatalNpmUserEntityProjection {
                ordinal: 20,
                omitted_event_count: 1,
                ..
            }
        ));
        assert_eq!(
            result
                .outcomes
                .iter()
                .map(|outcome| outcome.ordinal)
                .collect::<Vec<_>>(),
            vec![10, 20]
        );
        assert_eq!(result.state, ReducerState::default());
        assert!(result.outcomes.iter().all(|outcome| !outcome.block_state_committed));
        assert!(!calls
            .calls
            .iter()
            .any(|call| matches!(call, CallRecord::Position(_, _, token_id) if token_id == "3")));

        // Graph still runs the ordinal-30 trigger and any later breadth-first
        // dynamic stages. The diagnostic intentionally returns only the prefix
        // needed to project final persisted NPM user entities.
        assert_eq!(input.writer_events.events.len(), result.outcomes.len() + 1);
    }

    #[test]
    fn repeated_interleaved_positions_are_cumulative_and_last_snapshot_wins() {
        let block = 20_000_000;
        let events = writer_events(
            "mainnet",
            block,
            vec![
                increase(10, block, "1", "2", "100", "1000"),
                transfer(20, block, "2", NEW_OWNER),
                decrease(30, block, "1", "1", "50", "500"),
                transfer(40, block, "1", [0x44; 20]),
            ],
        );
        let input = diagnostic(events, 77);
        let mut calls = FakeInputs::default();
        configure_tokens(&mut calls, &[10, 30]);
        calls.position("mainnet", block, "1", Some(position_call(70, 80)));
        let result = reduce_npm_handler_block(&partial_state([seed("1"), seed("2")]), &input, &mut calls).unwrap();
        let position = &result.state.positions["1"];
        assert_eq!(position.liquidity, BigInt::from(101_u64));
        assert_eq!(position.deposited_token0.to_string(), "2");
        assert_eq!(position.withdrawn_token0.to_string(), "0.5");
        assert_eq!(position.owner, [0x44; 20]);
        assert_eq!(result.state.positions["2"].owner, NEW_OWNER);
        assert_eq!(result.state.snapshots.len(), 2);
        assert_eq!(result.state.snapshots[&format!("1#{block}")].transaction, [40; 32]);
        assert_eq!(result.state.snapshots[&format!("2#{block}")].transaction, [20; 32]);
    }

    #[test]
    fn identical_transaction_saves_remain_visible_in_the_ordered_write_trace() {
        let block = 20_000_000;
        let mut first = transfer(10, block, "1", NEW_OWNER);
        let mut second = transfer(20, block, "1", [0x44; 20]);
        first.transaction_hash = vec![0x77; 32];
        second.transaction_hash = vec![0x77; 32];
        let events = writer_events("base", block, vec![first, second]);
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "base", block, "1", POOL);
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert_eq!(result.state.transactions.len(), 1);
        assert_eq!(transaction_write_count(&result.outcomes[0]), 2);
        assert_eq!(transaction_write_count(&result.outcomes[1]), 1);
        assert_eq!(result.outcomes[0].transaction_id, result.outcomes[1].transaction_id);
        assert_eq!(result.state.positions["1"].transaction, [0x77; 32]);
        assert_eq!(result.state.snapshots[&format!("1#{block}")].transaction, [0x77; 32]);
    }

    #[test]
    fn historical_guard_precedes_every_call_and_save_only_on_base_root() {
        let block = HISTORICAL_GUARD_BLOCK;
        let events = writer_events("base", block, vec![increase(10, block, "1", "1", "1", "1")]);
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NormalReturn(NormalReturnReason::HistoricalGuard)
        );
        assert!(result.outcomes[0].attempted_writes.is_empty());
        assert!(calls.calls.is_empty());

        let events = writer_events("mainnet", block, vec![increase(10, block, "1", "1", "1", "1")]);
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "mainnet", block, "1", POOL);
        configure_tokens(&mut calls, &[10]);
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert!(!calls.calls.is_empty());
    }

    #[test]
    fn all_five_collect_profiles_execute_and_qmrv_resets_fee0_from_fee1() {
        let cases = [
            ("mainnet", 12_400_000, "4", "5"),
            ("mainnet", 13_470_000, "5", "4"),
            ("mainnet", 14_000_000, "3", "4"),
            ("base", 10_000_000, "4", "5"),
            ("mainnet", 20_000_000, "4", "5"),
        ];
        for (network, block, expected_fee0, expected_fee1) in cases {
            let events = writer_events(network, block, vec![collect(10, block, "1", "100", "1000")]);
            let input = diagnostic(events, 1);
            let mut calls = FakeInputs::default();
            configure_tokens(&mut calls, &[10]);
            calls.position(network, block, "1", None);
            let result = reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut calls).unwrap();
            assert_eq!(
                result.state.positions["1"].collected_fees_token0.to_string(),
                expected_fee0
            );
            assert_eq!(
                result.state.positions["1"].collected_fees_token1.to_string(),
                expected_fee1
            );
        }

        let block = 13_470_000;
        let events = writer_events(
            "mainnet",
            block,
            vec![
                collect(10, block, "1", "100", "1000"),
                collect(20, block, "1", "100", "2000"),
            ],
        );
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_tokens(&mut calls, &[10, 20]);
        calls.position("mainnet", block, "1", None);
        let result = reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut calls).unwrap();
        assert_eq!(result.state.positions["1"].collected_fees_token0.to_string(), "6");
        assert_eq!(result.state.positions["1"].collected_fees_token1.to_string(), "4");
    }

    #[test]
    fn current_collect_missing_token0_still_refreshes_and_saves_joint_state() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![collect(10, block, "1", "100", "1000")]);
        let input = diagnostic(events, 55);
        let mut calls = FakeInputs::default();
        calls.token(TOKEN0, 10, None);
        calls.position("mainnet", block, "1", Some(position_call(70, 80)));
        let result = reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut calls).unwrap();
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert_eq!(
            result.outcomes[0].attempted_writes,
            vec![
                EntityWriteSite::Position,
                EntityWriteSite::Transaction(TransactionLoadSite::PositionSnapshot),
                EntityWriteSite::PositionSnapshot,
            ]
        );
        assert_eq!(result.state.positions["1"].collected_fees_token0.to_string(), "3");
        assert_eq!(result.state.positions["1"].collected_fees_token1.to_string(), "4");
        assert_eq!(
            result.state.positions["1"].fee_growth_inside0_last_x128,
            BigUint::from(70_u64)
        );
        assert_eq!(
            result.state.positions["1"].fee_growth_inside1_last_x128,
            BigUint::from(80_u64)
        );
        assert!(result.state.snapshots.contains_key(&format!("1#{block}")));
    }

    #[test]
    fn fee_refresh_reversion_preserves_values_and_call_cache_is_invocation_local() {
        let block = 20_000_000;
        let events = writer_events(
            "mainnet",
            block,
            vec![
                increase(10, block, "1", "1", "1", "1"),
                decrease(20, block, "1", "1", "1", "1"),
            ],
        );
        let mut input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_tokens(&mut calls, &[10, 20]);
        calls.position("mainnet", block, "1", None);
        let result = reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut calls).unwrap();
        assert_eq!(
            result.state.positions["1"].fee_growth_inside0_last_x128,
            BigUint::from(5_u64)
        );
        assert_eq!(
            result.state.positions["1"].fee_growth_inside1_last_x128,
            BigUint::from(6_u64)
        );
        assert_eq!(
            calls
                .calls
                .iter()
                .filter(|call| matches!(call, CallRecord::Position(_, _, _)))
                .count(),
            1
        );
        assert_eq!(
            calls
                .calls
                .iter()
                .filter_map(|call| match call {
                    CallRecord::Token(_, ordinal) => Some(*ordinal),
                    _ => None,
                })
                .collect::<Vec<_>>(),
            vec![10, 10, 20, 20]
        );
        input.block.hash = Some([0xee; 32]);
        reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut calls).unwrap();
        let scopes = calls
            .calls
            .iter()
            .filter_map(|call| match call {
                CallRecord::Position(scope, _, _) => Some(scope),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(scopes.len(), 2);
        assert_ne!(scopes[0].block_hash, scopes[1].block_hash);
    }

    #[test]
    fn all_eight_segments_execute_with_exact_api_gas_behavior() {
        let contract = ReducerContract::embedded().unwrap();
        assert_eq!(contract.segments.len(), 8);
        assert_eq!(contract.npm_profiles.len(), 5);
        for (index, segment) in contract.segments.iter().enumerate() {
            let network = segment.network.as_str();
            let npm_start = contract.network_contract(segment.network).unwrap().npm_start_block;
            let block = segment.start_block_inclusive.max(npm_start);
            let token_id = (index + 1).to_string();
            let events = writer_events(network, block, vec![transfer(10, block, &token_id, NEW_OWNER)]);
            let mut input = diagnostic(events, 1);
            input.transactions[0].gas_limit = String::from("77777");
            input.transactions[0].gas_price = String::from("88888");
            let mut calls = FakeInputs::default();
            configure_new_position(&mut calls, network, block, &token_id, POOL);
            let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
            let entity = &result.state.transactions[&transaction_id(&[10; 32])];
            let expected_gas = if segment.api_version == "0.0.4" { "77777" } else { "0" };
            assert_eq!(entity.gas_used, expected_gas);
            assert_eq!(entity.gas_price, "88888");
            assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        }
    }

    #[test]
    fn malformed_metadata_controls_and_order_fail_before_external_inputs() {
        let block = 20_000_000;
        let events = writer_events("base", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let valid = diagnostic(events, 1);
        for mutation in 0..6 {
            let mut input = valid.clone();
            match mutation {
                0 => input.transactions.clear(),
                1 => input.transactions.push(input.transactions[0].clone()),
                2 => input.transactions[0].gas_limit = String::from("01"),
                3 => input.controls.clear(),
                4 => input.controls.push(input.controls[0]),
                5 => input.controls[0].ordinal = 11,
                _ => unreachable!(),
            }
            let mut calls = FakeInputs::default();
            assert!(reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).is_err());
            assert!(calls.calls.is_empty());
        }

        let events = writer_events(
            "base",
            block,
            vec![transfer(20, block, "1", NEW_OWNER), transfer(10, block, "2", NEW_OWNER)],
        );
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        assert!(reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).is_err());
        assert!(calls.calls.is_empty());

        let mut events = writer_events(
            "base",
            block,
            vec![transfer(10, block, "1", NEW_OWNER), transfer(20, block, "2", NEW_OWNER)],
        );
        events.events[0].block_log_index = 2;
        events.events[1].block_log_index = 1;
        let input = diagnostic(events, 1);
        assert!(reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).is_err());
        assert!(calls.calls.is_empty());
    }

    #[test]
    fn malformed_envelopes_and_payloads_are_rejected_outside_nonfatal_policy() {
        let block = 20_000_000;
        let events = writer_events("base", block, vec![increase(10, block, "1", "1", "1", "1")]);
        let valid = diagnostic(events, 1);
        for mutation in 0..6 {
            let mut input = valid.clone();
            match mutation {
                0 => input.writer_events.events[0].contract_address = vec![0xff; 20],
                1 => {
                    input.writer_events.events[0].transaction_hash.pop();
                }
                2 => input.writer_events.segment_semantic_contract_sha256 = "0".repeat(64),
                3 => input.writer_events.events[0].block_number += 1,
                4 => input.block.number += 1,
                5 => {
                    let Some(Event::IncreaseLiquidity(value)) = &mut input.writer_events.events[0].event else {
                        unreachable!();
                    };
                    value.amount0 = String::from("01");
                }
                _ => unreachable!(),
            }
            let mut calls = FakeInputs::default();
            assert!(reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).is_err());
            assert!(calls.calls.is_empty());
        }
    }

    #[test]
    fn load_transaction_unconditionally_overwrites_existing_entity_fields() {
        let block = 20_000_000;
        let events = writer_events("base", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let mut input = diagnostic(events, 999);
        input.transactions[0].gas_limit = String::from("54321");
        input.transactions[0].gas_price = String::from("12345");
        let mut initial = partial_state([seed("1")]);
        let stale = transaction([10; 32], block - 1);
        initial.transactions.insert(stale.id.clone(), stale);
        let result = reduce_npm_handler_block(&initial, &input, &mut FakeInputs::default()).unwrap();
        let entity = &result.state.transactions[&transaction_id(&[10; 32])];
        assert_eq!(entity.block_number, block);
        assert_eq!(entity.timestamp, 999);
        assert_eq!(entity.gas_used, "0");
        assert_eq!(entity.gas_price, "12345");
    }

    #[test]
    fn identity_dependency_errors_obey_segment_policy_without_transaction_leaks() {
        let block = 20_000_000;
        let events = writer_events("base", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        calls.position_error("base", block, "1", "reverted");
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert!(matches!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert_eq!(result.state, ReducerState::default());
        assert!(result.outcomes[0].attempted_writes.is_empty());

        let block = 12_400_000;
        let events = writer_events("mainnet", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let input = diagnostic(events, 1);
        let call = position_call(1, 2);
        let mut calls = FakeInputs::default();
        calls.position("mainnet", block, "1", Some(call.clone()));
        calls.pool_error("mainnet", block, &call, "reverted");
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();
        assert!(matches!(
            result.disposition,
            BlockDisposition::FatalNpmUserEntityProjection { .. }
        ));
        assert!(result.outcomes[0].attempted_writes.is_empty());
    }

    #[test]
    fn projections_retain_position_and_transaction_reducer_contracts() {
        let block = 20_000_000;
        let events = writer_events(
            "base",
            block,
            vec![
                increase(10, block, "1", "2", "100", "1000"),
                transfer(20, block, "1", NEW_OWNER),
            ],
        );
        let input = diagnostic(events, 77);
        let mut calls = FakeInputs::default();
        configure_new_position(&mut calls, "base", block, "1", POOL);
        configure_tokens(&mut calls, &[10]);
        let result = reduce_npm_handler_block(&ReducerState::default(), &input, &mut calls).unwrap();

        // Position reducer projection: first relation is retained, fields are
        // cumulative, and the last accepted event overwrites the snapshot.
        let position = &result.state.positions["1"];
        assert_eq!(position.transaction, [10; 32]);
        assert_eq!(position.liquidity, BigInt::from(2_u64));
        assert_eq!(position.owner, NEW_OWNER);
        assert_eq!(result.state.snapshots[&format!("1#{block}")].transaction, [20; 32]);

        // Transaction reducer projection: current API writes zero gasUsed,
        // preserves gasPrice, and exposes two loads for new then one existing.
        assert_eq!(transaction_write_count(&result.outcomes[0]), 2);
        assert_eq!(transaction_write_count(&result.outcomes[1]), 1);
        assert_eq!(result.state.transactions[&transaction_id(&[10; 32])].gas_used, "0");
        assert_eq!(result.state.transactions[&transaction_id(&[20; 32])].gas_used, "0");
    }

    #[test]
    fn decimal_uint256_and_partial_initial_state_boundaries_remain_exact() {
        assert_eq!(
            Decimal::parse("12345678901234567890123456789012345")
                .unwrap()
                .to_string(),
            "12345678901234567890123456789012350"
        );
        assert_eq!(
            Decimal::from_unsigned_units(&maximum_uint256().to_str_radix(10), 18)
                .unwrap()
                .to_string(),
            "115792089237316195423570985008687900000000000000000000000000"
        );

        let block = 20_000_000;
        let events = writer_events("base", block, vec![decrease(10, block, "1", "101", "0", "0")]);
        let input = diagnostic(events, 1);
        let mut calls = FakeInputs::default();
        configure_tokens(&mut calls, &[10]);
        calls.position("base", block, "1", None);
        let result = reduce_npm_handler_block(&partial_state([seed("1")]), &input, &mut calls).unwrap();
        assert_eq!(result.state.positions["1"].liquidity, BigInt::from(-1));
        assert!(result.state.transactions.contains_key(&transaction_id(&[10; 32])));
    }
}
