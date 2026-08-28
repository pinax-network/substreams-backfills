//! Host-only sequential Position/PositionSnapshot reducer.
//!
//! This module intentionally has no Substreams handler, store, RPC, database,
//! or `graph_out` integration. It models the reviewed Graph mapping behavior
//! behind explicit, hermetic inputs so state-transition rules can be tested
//! before any runtime application is designed or authorized.

use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::fmt;

use num_bigint::{BigInt, BigUint, Sign};
use num_traits::Zero;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use substreams::errors::Error;

use crate::pb::writer::writer_event::Event;
use crate::pb::writer::{WriterEvent, WriterEvents};

const REDUCER_CONTRACT_SHA256: &str = "7b734cca8bf10038c73fd11a9af1a29e0aa7d7082ad621658485fec4bf947d2b";
const REDUCER_CONTRACT_VERSION: &str = "uniswap-v3-position-reducer/v1";
const SOURCE_WRITER_CONTRACT_SHA256: &str = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4";
const SOURCE_PROFILE_SHA256: &str = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823";
const SOURCE_WRITER_RUNTIME_SHA256: &str = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca";
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
pub enum DropReason {
    HistoricalGuard,
    MissingPosition,
    ExcludedPool,
    MissingToken,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EventDisposition {
    Committed,
    Dropped(DropReason),
    NonFatalError(String),
    FatalError(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EventOutcome {
    pub ordinal: u64,
    pub token_id: String,
    pub kind: EventKind,
    pub disposition: EventDisposition,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BlockDisposition {
    Committed,
    Fatal { ordinal: u64, message: String },
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
    Commit(Box<Position>, Box<PositionSnapshot>),
    Drop(DropReason),
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct HandlerError(String);

impl HandlerError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum Network {
    Mainnet,
    Base,
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
    backfill_ready: bool,
    boundary_state_continuity_complete: bool,
    diagnostic_only: bool,
    graph_out_replaced: bool,
    live_calls_added: bool,
    logical_oracle_complete: bool,
    physical_parity_complete: bool,
    poi_parity_complete: bool,
    production_ready: bool,
    runtime_population_complete: bool,
    stores_added: bool,
    substreams_handler_added: bool,
    transaction_entity_effects_implemented: bool,
    full_npm_handler_semantics: bool,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ReducerContract {
    format_version: u32,
    contract_version: String,
    mode: String,
    source_writer_contract: SourceContract,
    source_segment_profiles: SourceContract,
    source_writer_runtime: SourceWriterRuntime,
    network_contracts: Vec<NetworkContract>,
    execution_contract: ExecutionContract,
    npm_profiles: Vec<NpmProfile>,
    segments: Vec<Segment>,
    truth_boundary: TruthBoundary,
}

impl ReducerContract {
    fn embedded() -> Result<Self, Error> {
        let raw = include_str!("../configs/position-reducer-v1.json");
        if hex::encode(Sha256::digest(raw.as_bytes())) != REDUCER_CONTRACT_SHA256 {
            return Err(Error::msg("position-reducer contract digest mismatch"));
        }
        let contract: Self = serde_json::from_str(raw)
            .map_err(|error| Error::msg(format!("invalid position-reducer contract JSON: {error}")))?;
        contract.validate()?;
        Ok(contract)
    }

    fn validate(&self) -> Result<(), Error> {
        if self.format_version != 1
            || self.contract_version != REDUCER_CONTRACT_VERSION
            || self.mode != "host-diagnostic-only"
        {
            return Err(Error::msg("unsupported position-reducer contract"));
        }
        if self.source_writer_contract.path != "uniswap-v3/graft-ancestry/v2/writer-compatibility.json"
            || self.source_writer_contract.contract_version != "uniswap-v3-writer-compatibility/v3"
            || self.source_writer_contract.sha256 != SOURCE_WRITER_CONTRACT_SHA256
            || self.source_segment_profiles.path != "uniswap-v3/writer-runtime/segment-profiles-v1.json"
            || self.source_segment_profiles.contract_version != "uniswap-v3-writer-runtime-segment-profiles/v1"
            || self.source_segment_profiles.sha256 != SOURCE_PROFILE_SHA256
            || self.source_writer_runtime.path != "uniswap-v3/writer-runtime/contract-v1.json"
            || self.source_writer_runtime.contract_version != "uniswap-v3-writer-runtime/v1"
            || self.source_writer_runtime.sha256 != SOURCE_WRITER_RUNTIME_SHA256
            || self.source_writer_runtime.writer_descriptor_sha256 != WRITER_DESCRIPTOR_SHA256
        {
            return Err(Error::msg("position-reducer source binding drift"));
        }
        self.validate_network_contracts()?;
        self.validate_execution_contract()?;
        self.validate_profiles()?;
        self.validate_segments()?;
        if self.truth_boundary
            != (TruthBoundary {
                backfill_ready: false,
                boundary_state_continuity_complete: false,
                diagnostic_only: true,
                graph_out_replaced: false,
                live_calls_added: false,
                logical_oracle_complete: false,
                physical_parity_complete: false,
                poi_parity_complete: false,
                production_ready: false,
                runtime_population_complete: false,
                stores_added: false,
                substreams_handler_added: false,
                transaction_entity_effects_implemented: false,
                full_npm_handler_semantics: false,
            })
        {
            return Err(Error::msg("position-reducer truth boundary promoted"));
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
                != "clone-on-write; only a fully accepted handler commits Position and PositionSnapshot"
            || execution.nonfatal_error != "discard the failing event scratch state and continue"
            || execution.fatal_error
                != "discard every Position and PositionSnapshot change from the block and stop"
            || execution.graph_call_scope
                != "one reducer invocation and its exact block pointer; hash-bound when available and number fallback otherwise; never event ordinal"
            || execution.graph_call_cache
                != "invocation-local raw results keyed by target address and exact positions or getPool calldata"
            || execution.token_read_scope != "event ordinal; never block-only"
            || execution.provisional_identity
                != "a getPosition identity is Position scratch state until its handler commits; Transaction entity side effects are outside this reducer"
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
                != "before Position identity calls, pool calls, token reads, mutation, fee refresh, and snapshot"
        {
            return Err(Error::msg("position-reducer execution contract drift"));
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
        const RANGES: &[(Network, u64, Option<u64>, bool, bool)] = &[
            (Network::Mainnet, 12_369_621, Some(13_450_880), false, false),
            (Network::Mainnet, 13_450_881, Some(13_498_328), false, false),
            (Network::Mainnet, 13_498_329, Some(13_591_197), false, false),
            (Network::Mainnet, 13_591_198, Some(13_605_860), false, false),
            (Network::Mainnet, 13_605_861, Some(19_470_000), false, false),
            (Network::Mainnet, 19_470_001, None, true, false),
            (Network::Base, 1_371_679, Some(19_852_000), true, true),
            (Network::Base, 19_852_001, None, true, false),
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

pub fn reduce_position_block<I: ReducerInputs>(
    initial: &ReducerState,
    events: &WriterEvents,
    block: &BlockContext,
    inputs: &mut I,
) -> Result<BlockReduction, Error> {
    let contract = ReducerContract::embedded()?;
    let network = Network::parse(&events.network)?;
    if block.number != events.block_number {
        return Err(Error::msg("position-reducer BlockContext number drift"));
    }
    let network_contract = contract.network_contract(network)?;
    let segment = contract.select(network, events.block_number)?;
    if events.segment_id != segment.segment_id
        || events.segment_semantic_contract_sha256 != segment.semantic_contract_sha256
        || events.source_writer_contract_sha256 != SOURCE_WRITER_CONTRACT_SHA256
    {
        return Err(Error::msg("position-reducer WriterEvents binding drift"));
    }
    if events.block_number < network_contract.npm_start_block && !events.events.is_empty() {
        return Err(Error::msg(
            "position-reducer received events before the producer NPM gate",
        ));
    }
    let position_manager = network_contract.position_manager_address()?;
    let factory = network_contract.factory_address()?;
    validate_events(events, position_manager)?;
    let profile = contract.profile(&segment.npm_profile_id)?;
    let mut working = initial.clone();
    validate_state(&working)?;
    let scope = BlockScope {
        network: events.network.clone(),
        block_number: events.block_number,
        block_hash: block.hash,
    };
    let mut cache = GraphCallCache::new(inputs, scope);
    let mut outcomes = Vec::with_capacity(events.events.len());

    for event in &events.events {
        let (kind, token_id) = event_identity(event)?;
        let result = reduce_event(
            &working,
            event,
            kind,
            &token_id,
            events.block_number,
            block.timestamp,
            position_manager,
            factory,
            segment,
            profile,
            &mut cache,
        );
        match result {
            Ok(EventEffect::Commit(position, snapshot)) => {
                working.positions.insert(token_id.clone(), *position);
                working.snapshots.insert(snapshot.id.clone(), *snapshot);
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    disposition: EventDisposition::Committed,
                });
            }
            Ok(EventEffect::Drop(reason)) => outcomes.push(EventOutcome {
                ordinal: event.ordinal,
                token_id,
                kind,
                disposition: EventDisposition::Dropped(reason),
            }),
            Err(error) if segment.nonfatal_errors => outcomes.push(EventOutcome {
                ordinal: event.ordinal,
                token_id,
                kind,
                disposition: EventDisposition::NonFatalError(error.0),
            }),
            Err(error) => {
                let message = error.0;
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    disposition: EventDisposition::FatalError(message.clone()),
                });
                return Ok(BlockReduction {
                    state: initial.clone(),
                    outcomes,
                    disposition: BlockDisposition::Fatal {
                        ordinal: event.ordinal,
                        message,
                    },
                    segment_id: segment.segment_id.clone(),
                });
            }
        }
    }

    Ok(BlockReduction {
        state: working,
        outcomes,
        disposition: BlockDisposition::Committed,
        segment_id: segment.segment_id.clone(),
    })
}

#[allow(clippy::too_many_arguments)]
fn reduce_event<I: ReducerInputs>(
    working: &ReducerState,
    event: &WriterEvent,
    kind: EventKind,
    token_id: &str,
    block_number: u64,
    timestamp: u64,
    position_manager: Address,
    factory: Address,
    segment: &Segment,
    profile: &NpmProfile,
    cache: &mut GraphCallCache<'_, I>,
) -> Result<EventEffect, HandlerError> {
    if segment.historical_guard_effective
        && block_number == HISTORICAL_GUARD_BLOCK
        && matches!(kind, EventKind::Increase | EventKind::Decrease)
    {
        return Ok(EventEffect::Drop(DropReason::HistoricalGuard));
    }

    let mut position = match working.positions.get(token_id) {
        Some(position) => position.clone(),
        None => {
            let Some(call) = cache.position(position_manager, token_id)? else {
                return Ok(EventEffect::Drop(DropReason::MissingPosition));
            };
            let pool = cache.pool(factory, &call)?;
            provisional_position(token_id, event, call, pool)?
        }
    };

    if position.pool == EXCLUDED_POOL && !matches!(kind, EventKind::Transfer) {
        return Ok(EventEffect::Drop(DropReason::ExcludedPool));
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
                return Ok(EventEffect::Drop(DropReason::MissingToken));
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
                return Ok(EventEffect::Drop(DropReason::MissingToken));
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

    let transaction =
        exact_transaction_hash(&event.transaction_hash).map_err(|error| HandlerError::new(error.to_string()))?;
    let snapshot = PositionSnapshot::from_position(&position, block_number, timestamp, transaction);
    Ok(EventEffect::Commit(Box::new(position), Box::new(snapshot)))
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
                .insert((network.to_string(), block, token_id.to_string()), Ok(value));
        }

        fn pool(&mut self, network: &str, block: u64, call: &PositionCall, pool: Address) {
            self.pools.insert(
                (network.to_string(), block, call.token0, call.token1, call.fee),
                Ok(pool),
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
                token_id.to_string(),
            ));
            self.positions
                .get(&(scope.network.clone(), scope.block_number, token_id.to_string()))
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
                .unwrap_or_else(|| Err("unconfigured pool call".to_string()))
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
            token_id: token_id.to_string(),
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

    fn state(position: Position) -> ReducerState {
        ReducerState {
            positions: [(position.token_id.clone(), position)].into_iter().collect(),
            snapshots: BTreeMap::new(),
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
            network: network.to_string(),
            block_number: block,
            segment_id: segment.segment_id,
            source_writer_contract_sha256: SOURCE_WRITER_CONTRACT_SHA256.to_string(),
            segment_semantic_contract_sha256: segment.semantic_contract_sha256,
        }
    }

    fn context(number: u64, timestamp: u64) -> BlockContext {
        BlockContext {
            number,
            timestamp,
            hash: Some([number as u8; 32]),
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
                token_id: token_id.to_string(),
                liquidity: liquidity.to_string(),
                amount0: amount0.to_string(),
                amount1: amount1.to_string(),
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
                token_id: token_id.to_string(),
                liquidity: liquidity.to_string(),
                amount0: amount0.to_string(),
                amount1: amount1.to_string(),
            }),
        )
    }

    fn collect(ordinal: u64, block: u64, token_id: &str, amount0: &str, amount1: &str) -> WriterEvent {
        common(
            ordinal,
            block,
            Event::Collect(Collect {
                token_id: token_id.to_string(),
                recipient: vec![0x77; 20],
                amount0: amount0.to_string(),
                amount1: amount1.to_string(),
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
                token_id: token_id.to_string(),
            }),
        )
    }

    fn configure_tokens(inputs: &mut FakeInputs, ordinals: &[u64]) {
        for ordinal in ordinals {
            inputs.token(TOKEN0, *ordinal, Some(2));
            inputs.token(TOKEN1, *ordinal, Some(3));
        }
    }

    #[test]
    fn repeated_interleaved_events_are_cumulative_and_last_snapshot_wins() {
        let block = 20_000_000;
        let events = writer_events(
            "mainnet",
            block,
            vec![
                increase(10, block, "1", "25", "150", "2500"),
                transfer(20, block, "1", NEW_OWNER),
                decrease(30, block, "1", "5", "50", "500"),
                increase(40, block, "1", "10", "25", "125"),
            ],
        );
        let mut inputs = FakeInputs::default();
        configure_tokens(&mut inputs, &[10, 30, 40]);
        inputs.position("mainnet", block, "1", Some(position_call(50, 60)));
        let result =
            reduce_position_block(&state(seed("1")), &events, &context(block, 1_700_000_000), &mut inputs).unwrap();
        assert_eq!(result.disposition, BlockDisposition::Committed);
        let position = &result.state.positions["1"];
        assert_eq!(position.liquidity, BigInt::from(130_u64));
        assert_eq!(position.deposited_token0.to_string(), "2.75");
        assert_eq!(position.deposited_token1.to_string(), "4.625");
        assert_eq!(position.withdrawn_token0.to_string(), "0.5");
        assert_eq!(position.withdrawn_token1.to_string(), "0.5");
        assert_eq!(position.owner, NEW_OWNER);
        assert_eq!(position.fee_growth_inside0_last_x128, BigUint::from(50_u64));
        let snapshot = &result.state.snapshots[&format!("1#{block}")];
        assert_eq!(snapshot.liquidity, position.liquidity);
        assert_eq!(snapshot.owner, NEW_OWNER);
        assert_eq!(snapshot.transaction, [40; 32]);
        assert_eq!(result.outcomes.len(), 4);
    }

    #[test]
    fn qmrv_collect_overwrites_fee0_from_ordinal_current_fee1() {
        let block = 13_460_000;
        let mut initial = seed("1");
        initial.collected_fees_token0 = Decimal::parse("100").unwrap();
        initial.collected_fees_token1 = Decimal::parse("7").unwrap();
        let events = writer_events(
            "mainnet",
            block,
            vec![
                collect(10, block, "1", "100", "2000"),
                collect(20, block, "1", "500", "5000"),
            ],
        );
        let mut inputs = FakeInputs::default();
        configure_tokens(&mut inputs, &[10, 20]);
        inputs.position("mainnet", block, "1", None);
        let result = reduce_position_block(&state(initial), &events, &context(block, 10), &mut inputs).unwrap();
        let position = &result.state.positions["1"];
        assert_eq!(position.collected_fees_token0.to_string(), "12");
        assert_eq!(position.collected_fees_token1.to_string(), "7");
    }

    #[test]
    fn all_collect_profiles_apply_their_exact_amount_and_token_rules() {
        let cases = [
            ("mainnet", 12_400_000, "4", "6"),
            ("mainnet", 13_500_000, "3", "4"),
            ("base", 14_000_000, "4", "5"),
            ("mainnet", 20_000_000, "4", "5"),
            ("base", 20_000_000, "4", "5"),
        ];
        for (network, block, expected0, expected1) in cases {
            let events = writer_events(network, block, vec![collect(10, block, "1", "100", "2000")]);
            let mut inputs = FakeInputs::default();
            configure_tokens(&mut inputs, &[10]);
            inputs.position(network, block, "1", Some(position_call(50, 60)));
            let result = reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).unwrap();
            assert_eq!(result.state.positions["1"].collected_fees_token0.to_string(), expected0);
            assert_eq!(result.state.positions["1"].collected_fees_token1.to_string(), expected1);
            let token_calls = inputs
                .calls
                .iter()
                .filter(|call| matches!(call, CallRecord::Token(_, _)))
                .count();
            let expected_calls = if block == 13_500_000 {
                0
            } else if network == "base" || block == 20_000_000 {
                1
            } else {
                2
            };
            assert_eq!(token_calls, expected_calls, "{network} {block}");
        }
    }

    #[test]
    fn base_root_collect_reads_only_token0_and_ignores_missing_token1() {
        let block = 14_000_000;
        let events = writer_events("base", block, vec![collect(10, block, "1", "250", "999999")]);
        let mut inputs = FakeInputs::default();
        inputs.token(TOKEN0, 10, Some(2));
        inputs.token(TOKEN1, 10, None);
        inputs.position("base", block, "1", None);
        let result = reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert_eq!(result.state.positions["1"].collected_fees_token0.to_string(), "5.5");
        assert_eq!(result.state.positions["1"].collected_fees_token1.to_string(), "6.5");
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter_map(|call| match call {
                    CallRecord::Token(address, ordinal) => Some((*address, *ordinal)),
                    _ => None,
                })
                .collect::<Vec<_>>(),
            vec![(TOKEN0, 10)]
        );
    }

    #[test]
    fn current_collect_missing_token0_still_refreshes_saves_and_snapshots() {
        let block = 20_000_000;
        let events = writer_events("base", block, vec![collect(10, block, "1", "100", "999")]);
        let mut inputs = FakeInputs::default();
        inputs.token(TOKEN0, 10, None);
        inputs.position("base", block, "1", Some(position_call(70, 80)));
        let result = reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        let position = &result.state.positions["1"];
        assert_eq!(position.collected_fees_token0.to_string(), "3");
        assert_eq!(position.collected_fees_token1.to_string(), "4");
        assert_eq!(position.fee_growth_inside0_last_x128, BigUint::from(70_u64));
        assert!(result.state.snapshots.contains_key(&format!("1#{block}")));
        assert_eq!(inputs.calls.len(), 2);
        assert_eq!(inputs.calls[0], CallRecord::Token(TOKEN0, 10));
        assert!(matches!(
            &inputs.calls[1],
            CallRecord::Position(scope, _, token_id)
                if scope.network == "base"
                    && scope.block_number == block
                    && scope.block_hash == Some([block as u8; 32])
                    && token_id == "1"
        ));
    }

    #[test]
    fn collect_missing_token0_follows_legacy_fatal_and_base_root_nonfatal_policies() {
        for (network, block, fatal) in [("mainnet", 12_400_000, true), ("base", 14_000_000, false)] {
            let events = writer_events(network, block, vec![collect(10, block, "1", "100", "2000")]);
            let initial = state(seed("1"));
            let mut inputs = FakeInputs::default();
            inputs.token(TOKEN0, 10, None);
            inputs.token(TOKEN1, 10, Some(3));
            let result = reduce_position_block(&initial, &events, &context(block, 10), &mut inputs).unwrap();
            assert_eq!(result.state, initial);
            assert!(result.state.snapshots.is_empty());
            if fatal {
                assert!(matches!(
                    result.disposition,
                    BlockDisposition::Fatal { ordinal: 10, .. }
                ));
                assert!(matches!(
                    result.outcomes[0].disposition,
                    EventDisposition::FatalError(_)
                ));
            } else {
                assert_eq!(result.disposition, BlockDisposition::Committed);
                assert!(matches!(
                    result.outcomes[0].disposition,
                    EventDisposition::NonFatalError(_)
                ));
                assert_eq!(
                    inputs
                        .calls
                        .iter()
                        .filter(|call| matches!(call, CallRecord::Token(_, _)))
                        .count(),
                    1
                );
            }
        }
    }

    #[test]
    fn excluded_pool_drops_provisional_identity_without_token_or_snapshot_leaks() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![increase(10, block, "9", "1", "1", "1")]);
        let call = position_call(1, 2);
        let mut inputs = FakeInputs::default();
        inputs.position("mainnet", block, "9", Some(call.clone()));
        inputs.pool("mainnet", block, &call, EXCLUDED_POOL);
        let result =
            reduce_position_block(&ReducerState::default(), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::Dropped(DropReason::ExcludedPool)
        );
        assert!(result.state.positions.is_empty());
        assert!(result.state.snapshots.is_empty());
        assert!(!inputs.calls.iter().any(|call| matches!(call, CallRecord::Token(_, _))));
    }

    #[test]
    fn excluded_pool_does_not_exclude_transfer() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let mut position = seed("1");
        position.pool = EXCLUDED_POOL;
        let mut inputs = FakeInputs::default();
        let result = reduce_position_block(&state(position), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert_eq!(result.state.positions["1"].owner, NEW_OWNER);
        assert!(inputs.calls.is_empty());
    }

    #[test]
    fn current_missing_liquidity_token_drops_all_event_scratch_and_fee_refresh() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![increase(10, block, "9", "7", "10", "20")]);
        let call = position_call(1, 2);
        let mut inputs = FakeInputs::default();
        inputs.position("mainnet", block, "9", Some(call.clone()));
        inputs.pool("mainnet", block, &call, POOL);
        inputs.token(TOKEN0, 10, Some(2));
        inputs.token(TOKEN1, 10, None);
        let result =
            reduce_position_block(&ReducerState::default(), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::Dropped(DropReason::MissingToken)
        );
        assert!(result.state.positions.is_empty());
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter(|call| matches!(call, CallRecord::Position(_, _, _)))
                .count(),
            1
        );
    }

    #[test]
    fn fatal_legacy_error_rolls_back_prior_block_commits_and_stops() {
        let block = 12_400_000;
        let events = writer_events(
            "mainnet",
            block,
            vec![
                transfer(10, block, "1", NEW_OWNER),
                increase(20, block, "1", "5", "10", "20"),
                transfer(30, block, "1", [0x44; 20]),
            ],
        );
        let initial = state(seed("1"));
        let mut inputs = FakeInputs::default();
        inputs.token(TOKEN0, 20, Some(2));
        inputs.token(TOKEN1, 20, None);
        let result = reduce_position_block(&initial, &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(result.state, initial);
        assert!(matches!(
            result.disposition,
            BlockDisposition::Fatal { ordinal: 20, .. }
        ));
        assert_eq!(result.outcomes.len(), 2);
    }

    #[test]
    fn base_root_nonfatal_error_discards_only_failing_scratch_and_continues() {
        let block = 14_000_000;
        let events = writer_events(
            "base",
            block,
            vec![
                transfer(10, block, "1", NEW_OWNER),
                decrease(20, block, "1", "5", "10", "20"),
                transfer(30, block, "1", [0x44; 20]),
            ],
        );
        let mut inputs = FakeInputs::default();
        inputs.token(TOKEN0, 20, Some(2));
        inputs.token(TOKEN1, 20, None);
        let result = reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(result.disposition, BlockDisposition::Committed);
        assert!(matches!(
            result.outcomes[1].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert_eq!(result.state.positions["1"].owner, [0x44; 20]);
        assert_eq!(result.state.positions["1"].liquidity, BigInt::from(100_u64));
        assert_eq!(result.state.snapshots[&format!("1#{block}")].transaction, [30; 32]);
    }

    #[test]
    fn get_pool_failure_follows_each_segment_error_policy() {
        let call = position_call(1, 2);
        for (network, block, fatal) in [("mainnet", 12_400_000, true), ("base", 14_000_000, false)] {
            let events = writer_events(network, block, vec![transfer(10, block, "9", NEW_OWNER)]);
            let mut inputs = FakeInputs::default();
            inputs.position(network, block, "9", Some(call.clone()));
            inputs.pools.insert(
                (network.to_string(), block, call.token0, call.token1, call.fee),
                Err("reverted".to_string()),
            );
            let result =
                reduce_position_block(&ReducerState::default(), &events, &context(block, 10), &mut inputs).unwrap();
            if fatal {
                assert!(matches!(
                    result.disposition,
                    BlockDisposition::Fatal { ordinal: 10, .. }
                ));
            } else {
                assert_eq!(result.disposition, BlockDisposition::Committed);
                assert!(matches!(
                    result.outcomes[0].disposition,
                    EventDisposition::NonFatalError(_)
                ));
            }
            assert!(result.state.positions.is_empty());
            assert!(result.state.snapshots.is_empty());
        }
    }

    #[test]
    fn graph_calls_are_cached_at_block_scope_but_token_reads_keep_event_ordinals() {
        let block = 20_000_000;
        let events = writer_events(
            "mainnet",
            block,
            vec![
                increase(10, block, "1", "1", "1", "1"),
                decrease(20, block, "1", "1", "1", "1"),
            ],
        );
        let mut inputs = FakeInputs::default();
        configure_tokens(&mut inputs, &[10, 20]);
        inputs.position("mainnet", block, "1", Some(position_call(70, 80)));
        reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter(|call| matches!(call, CallRecord::Position(_, _, _)))
                .count(),
            1
        );
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter_map(|call| match call {
                    CallRecord::Token(_, ordinal) => Some(*ordinal),
                    _ => None,
                })
                .collect::<Vec<_>>(),
            vec![10, 10, 20, 20]
        );
        assert!(inputs.calls.iter().any(
            |call| matches!(call, CallRecord::Position(scope, _, _) if scope.block_number == block && scope.network == "mainnet")
        ));

        let mut reorg_context = context(block, 11);
        reorg_context.hash = Some([0xee; 32]);
        reduce_position_block(&state(seed("1")), &events, &reorg_context, &mut inputs).unwrap();
        let position_scopes = inputs
            .calls
            .iter()
            .filter_map(|call| match call {
                CallRecord::Position(scope, _, _) => Some(scope.clone()),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(position_scopes.len(), 2);
        assert_eq!(position_scopes[0].block_hash, Some([block as u8; 32]));
        assert_eq!(position_scopes[1].block_hash, Some([0xee; 32]));
    }

    #[test]
    fn identity_and_fee_refresh_share_one_post_block_positions_call() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![increase(10, block, "9", "1", "100", "1000")]);
        let call = position_call(70, 80);
        let mut inputs = FakeInputs::default();
        inputs.position("mainnet", block, "9", Some(call.clone()));
        inputs.pool("mainnet", block, &call, POOL);
        configure_tokens(&mut inputs, &[10]);
        let result =
            reduce_position_block(&ReducerState::default(), &events, &context(block, 99), &mut inputs).unwrap();
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert_eq!(
            result.state.positions["9"].fee_growth_inside0_last_x128,
            BigUint::from(70_u64)
        );
        assert_eq!(result.state.snapshots[&format!("9#{block}")].timestamp, 99);
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter(|call| matches!(call, CallRecord::Position(_, _, _)))
                .count(),
            1
        );
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter(|call| matches!(call, CallRecord::Pool(_, _, _, _, _)))
                .count(),
            1
        );
    }

    #[test]
    fn graph_cache_keys_include_target_and_exact_calldata() {
        let block = 20_000_000;
        let scope = BlockScope {
            network: "mainnet".to_string(),
            block_number: block,
            block_hash: Some([0xaa; 32]),
        };
        let call = position_call(1, 2);
        let mut inputs = FakeInputs::default();
        inputs.position("mainnet", block, "1", Some(call.clone()));
        inputs.position("mainnet", block, "2", Some(call.clone()));
        inputs.pool("mainnet", block, &call, POOL);
        {
            let mut cache = GraphCallCache::new(&mut inputs, scope);
            assert_eq!(cache.position([0x01; 20], "1").unwrap(), Some(call.clone()));
            assert_eq!(cache.position([0x01; 20], "1").unwrap(), Some(call.clone()));
            assert_eq!(cache.position([0x02; 20], "1").unwrap(), Some(call.clone()));
            assert_eq!(cache.position([0x01; 20], "2").unwrap(), Some(call.clone()));
            assert_eq!(cache.pool([0x03; 20], &call).unwrap(), POOL);
            assert_eq!(cache.pool([0x03; 20], &call).unwrap(), POOL);
            assert_eq!(cache.pool([0x04; 20], &call).unwrap(), POOL);
        }
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter(|record| matches!(record, CallRecord::Position(_, _, _)))
                .count(),
            3
        );
        assert_eq!(
            inputs
                .calls
                .iter()
                .filter(|record| matches!(record, CallRecord::Pool(_, _, _, _, _)))
                .count(),
            2
        );
    }

    #[test]
    fn block_number_fallback_scope_is_explicit_and_invocation_local() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![collect(10, block, "1", "100", "1")]);
        let mut inputs = FakeInputs::default();
        inputs.token(TOKEN0, 10, Some(2));
        inputs.position("mainnet", block, "1", None);
        let mut block_context = context(block, 10);
        block_context.hash = None;
        reduce_position_block(&state(seed("1")), &events, &block_context, &mut inputs).unwrap();
        assert!(inputs
            .calls
            .iter()
            .any(|call| matches!(call, CallRecord::Position(scope, _, _) if scope.block_hash.is_none())));
    }

    #[test]
    fn position_call_reversion_preserves_fee_growth_or_drops_missing_identity() {
        let block = 20_000_000;
        let existing = writer_events("mainnet", block, vec![collect(10, block, "1", "100", "1")]);
        let mut inputs = FakeInputs::default();
        inputs.token(TOKEN0, 10, Some(2));
        inputs.position("mainnet", block, "1", None);
        let result = reduce_position_block(&state(seed("1")), &existing, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(
            result.state.positions["1"].fee_growth_inside0_last_x128,
            BigUint::from(5_u64)
        );
        assert_eq!(result.state.positions["1"].collected_fees_token0.to_string(), "4");
        assert!(result.state.snapshots.contains_key(&format!("1#{block}")));

        let missing = writer_events("mainnet", block, vec![transfer(10, block, "2", NEW_OWNER)]);
        let mut inputs = FakeInputs::default();
        inputs.position("mainnet", block, "2", None);
        let result =
            reduce_position_block(&ReducerState::default(), &missing, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::Dropped(DropReason::MissingPosition)
        );
        assert!(result.state.positions.is_empty());
    }

    #[test]
    fn transfer_can_commit_a_provisional_identity_and_snapshot() {
        let block = 20_000_000;
        let events = writer_events("base", block, vec![transfer(10, block, "2", NEW_OWNER)]);
        let call = position_call(7, 8);
        let mut inputs = FakeInputs::default();
        inputs.position("base", block, "2", Some(call.clone()));
        inputs.pool("base", block, &call, POOL);
        let result =
            reduce_position_block(&ReducerState::default(), &events, &context(block, 99), &mut inputs).unwrap();
        assert_eq!(result.state.positions["2"].owner, NEW_OWNER);
        assert_eq!(result.state.positions["2"].transaction, [10; 32]);
        assert_eq!(result.state.snapshots[&format!("2#{block}")].timestamp, 99);
    }

    #[test]
    fn provisional_position_transaction_stays_at_creation_while_snapshot_tracks_last_event() {
        let block = 20_000_000;
        let events = writer_events(
            "base",
            block,
            vec![
                transfer(10, block, "2", NEW_OWNER),
                transfer(20, block, "2", [0x44; 20]),
            ],
        );
        let call = position_call(7, 8);
        let mut inputs = FakeInputs::default();
        inputs.position("base", block, "2", Some(call.clone()));
        inputs.pool("base", block, &call, POOL);
        let result =
            reduce_position_block(&ReducerState::default(), &events, &context(block, 99), &mut inputs).unwrap();
        assert_eq!(result.state.positions["2"].transaction, [10; 32]);
        assert_eq!(result.state.positions["2"].owner, [0x44; 20]);
        assert_eq!(result.state.snapshots[&format!("2#{block}")].transaction, [20; 32]);
    }

    #[test]
    fn guard_is_before_all_calls_only_for_effective_base_root_segment() {
        let block = HISTORICAL_GUARD_BLOCK;
        let base_events = writer_events("base", block, vec![increase(10, block, "9", "1", "1", "1")]);
        let mut base_inputs = FakeInputs::default();
        let result = reduce_position_block(
            &ReducerState::default(),
            &base_events,
            &context(block, 10),
            &mut base_inputs,
        )
        .unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::Dropped(DropReason::HistoricalGuard)
        );
        assert!(base_inputs.calls.is_empty());

        let mainnet_events = writer_events("mainnet", block, vec![increase(10, block, "9", "1", "1", "1")]);
        let call = position_call(1, 2);
        let mut mainnet_inputs = FakeInputs::default();
        mainnet_inputs.position("mainnet", block, "9", Some(call.clone()));
        mainnet_inputs.pool("mainnet", block, &call, POOL);
        configure_tokens(&mut mainnet_inputs, &[10]);
        let result = reduce_position_block(
            &ReducerState::default(),
            &mainnet_events,
            &context(block, 10),
            &mut mainnet_inputs,
        )
        .unwrap();
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert!(!mainnet_inputs.calls.is_empty());
    }

    #[test]
    fn all_eight_segment_boundaries_select_exactly_and_preserve_guard_asymmetry() {
        let contract = ReducerContract::embedded().unwrap();
        assert_eq!(contract.segments.len(), 8);
        let expected_profiles = [
            "mainnet-root-correct-collect",
            "mainnet-second-fee0-overwrite",
            "mainnet-no-collect-amounts",
            "mainnet-no-collect-amounts",
            "mainnet-no-collect-amounts",
            "current-amount0-to-both",
            "base-root-amount0-to-both",
            "current-amount0-to-both",
        ];
        for (segment, expected_profile) in contract.segments.iter().zip(expected_profiles) {
            assert_eq!(segment.npm_profile_id, expected_profile);
            assert_eq!(
                contract
                    .select(segment.network, segment.start_block_inclusive)
                    .unwrap()
                    .segment_id,
                segment.segment_id
            );
            if let Some(end) = segment.end_block_inclusive {
                assert_eq!(
                    contract.select(segment.network, end).unwrap().segment_id,
                    segment.segment_id
                );
            }
        }
        assert!(contract.select(Network::Mainnet, 12_369_620).is_err());
        assert!(contract.select(Network::Base, 1_371_678).is_err());
        assert!(
            !contract
                .select(Network::Mainnet, HISTORICAL_GUARD_BLOCK)
                .unwrap()
                .historical_guard_effective
        );
        assert!(
            contract
                .select(Network::Base, HISTORICAL_GUARD_BLOCK)
                .unwrap()
                .historical_guard_effective
        );
    }

    #[test]
    fn base_split_origin_accepts_empty_pre_gate_envelopes_and_rejects_events() {
        let empty = writer_events("base", 1_371_712, vec![]);
        let mut inputs = FakeInputs::default();
        let result =
            reduce_position_block(&ReducerState::default(), &empty, &context(1_371_712, 10), &mut inputs).unwrap();
        assert_eq!(result.disposition, BlockDisposition::Committed);

        let invalid = writer_events("base", 1_371_712, vec![transfer(10, 1_371_712, "1", NEW_OWNER)]);
        assert!(
            reduce_position_block(&ReducerState::default(), &invalid, &context(1_371_712, 10), &mut inputs,).is_err()
        );

        let valid = writer_events("base", 1_371_713, vec![transfer(10, 1_371_713, "1", NEW_OWNER)]);
        inputs.position("base", 1_371_713, "1", None);
        let result =
            reduce_position_block(&ReducerState::default(), &valid, &context(1_371_713, 10), &mut inputs).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::Dropped(DropReason::MissingPosition)
        );
    }

    #[test]
    fn mainnet_split_origin_uses_the_exact_writer_event_gate() {
        let mut inputs = FakeInputs::default();
        let empty = writer_events("mainnet", 12_369_650, vec![]);
        assert_eq!(
            reduce_position_block(&ReducerState::default(), &empty, &context(12_369_650, 10), &mut inputs,)
                .unwrap()
                .disposition,
            BlockDisposition::Committed
        );
        let invalid = writer_events("mainnet", 12_369_650, vec![transfer(10, 12_369_650, "1", NEW_OWNER)]);
        assert!(reduce_position_block(
            &ReducerState::default(),
            &invalid,
            &context(12_369_650, 10),
            &mut inputs,
        )
        .is_err());
        let valid = writer_events("mainnet", 12_369_651, vec![transfer(10, 12_369_651, "1", NEW_OWNER)]);
        inputs.position("mainnet", 12_369_651, "1", None);
        assert_eq!(
            reduce_position_block(&ReducerState::default(), &valid, &context(12_369_651, 10), &mut inputs,)
                .unwrap()
                .outcomes[0]
                .disposition,
            EventDisposition::Dropped(DropReason::MissingPosition)
        );
    }

    #[test]
    fn malformed_order_or_bindings_fail_before_inputs_are_touched() {
        let block = 20_000_000;
        let mut events = writer_events(
            "mainnet",
            block,
            vec![transfer(20, block, "1", NEW_OWNER), transfer(10, block, "1", OWNER)],
        );
        let mut inputs = FakeInputs::default();
        assert!(reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).is_err());
        assert!(inputs.calls.is_empty());
        events.events.sort_by_key(|event| event.ordinal);
        events.events[0].block_log_index = 2;
        events.events[1].block_log_index = 1;
        assert!(reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).is_err());
        assert!(inputs.calls.is_empty());
        events.events[0].block_log_index = 1;
        events.events[1].block_log_index = 2;
        events.segment_semantic_contract_sha256 = "0".repeat(64);
        assert!(reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).is_err());
        assert!(inputs.calls.is_empty());
    }

    #[test]
    fn producer_corruption_is_fatal_before_modern_nonfatal_policy() {
        let block = 20_000_000;
        let mut inputs = FakeInputs::default();
        let noncanonical = writer_events("base", block, vec![increase(10, block, "1", "1", "01", "1")]);
        assert!(reduce_position_block(&state(seed("1")), &noncanonical, &context(block, 10), &mut inputs,).is_err());
        let overflow = (maximum_uint256() + BigUint::from(1_u8)).to_str_radix(10);
        let overflowed = writer_events("base", block, vec![collect(10, block, "1", &overflow, "1")]);
        assert!(reduce_position_block(&state(seed("1")), &overflowed, &context(block, 10), &mut inputs,).is_err());
        let mut malformed_address = writer_events("base", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let Some(Event::Transfer(transfer)) = &mut malformed_address.events[0].event else {
            unreachable!();
        };
        transfer.to.pop();
        assert!(
            reduce_position_block(&state(seed("1")), &malformed_address, &context(block, 10), &mut inputs,).is_err()
        );
        assert!(inputs.calls.is_empty());
    }

    #[test]
    fn block_context_number_mismatch_fails_before_inputs_are_touched() {
        let block = 20_000_000;
        let events = writer_events("mainnet", block, vec![transfer(10, block, "1", NEW_OWNER)]);
        let mut inputs = FakeInputs::default();
        assert!(reduce_position_block(&state(seed("1")), &events, &context(block + 1, 10), &mut inputs,).is_err());
        assert!(inputs.calls.is_empty());
    }

    #[test]
    fn integer_quantities_above_f64_precision_stay_exact_and_decrease_may_go_negative() {
        let block = 20_000_000;
        let high = "9007199254740993";
        let events = writer_events("mainnet", block, vec![increase(10, block, "1", high, "0", "0")]);
        let mut inputs = FakeInputs::default();
        configure_tokens(&mut inputs, &[10]);
        inputs.position("mainnet", block, "1", None);
        let result = reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(result.state.positions["1"].liquidity.to_string(), "9007199254741093");

        let events = writer_events("mainnet", block, vec![decrease(10, block, "1", "101", "0", "0")]);
        let mut inputs = FakeInputs::default();
        configure_tokens(&mut inputs, &[10]);
        inputs.position("mainnet", block, "1", None);
        let result = reduce_position_block(&state(seed("1")), &events, &context(block, 10), &mut inputs).unwrap();
        assert_eq!(result.state.positions["1"].liquidity.to_string(), "-1");
    }

    #[test]
    fn decimal_arithmetic_is_exact_and_canonical() {
        assert_eq!(Decimal::parse("001.2300").unwrap().to_string(), "1.23");
        assert_eq!(Decimal::parse("-0.500").unwrap().to_string(), "-0.5");
        assert_eq!(
            Decimal::from_unsigned_units("1", 18).unwrap().to_string(),
            "0.000000000000000001"
        );
        assert_eq!(
            Decimal::parse("0.1")
                .unwrap()
                .add(&Decimal::parse("0.02").unwrap())
                .to_string(),
            "0.12"
        );
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
    }
}
