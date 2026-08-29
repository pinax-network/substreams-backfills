//! Host-only resolved-observation adapter for the joint NPM reducer.
//!
//! The canonical input is a complete, already-built `NpmSourceBlock` plus
//! resolved Graph call/entity observations. Resolution status is deliberately
//! transient: only resolved values cross the protobuf boundary.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

use num_bigint::BigUint;
use prost::Message;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::npm_handler_reducer::{
    self, Address, BlockContext, BlockDisposition, BlockReduction, BlockScope, DiagnosticInput, EventControl,
    FailurePhase, PositionCall, ReducerInputs, ReducerState, TransactionMetadata,
};
use crate::npm_inputs_pb::pool_observation::Result as PoolResult;
use crate::npm_inputs_pb::position_observation::Result as PositionResult;
use crate::npm_inputs_pb::resolved_call_scope::Scope;
use crate::npm_inputs_pb::token_observation::Result as TokenResult;
use crate::npm_inputs_pb::{
    NpmResolvedInputs, PoolObservation, PositionObservation, PositionValue, ResolvedCallScope, ResolvedNone,
    TokenFound, TokenObservation,
};
use crate::pb::npm_source::NpmSourceBlock;

pub const INPUT_SEMANTICS_SHA256: &str = "01f7e87b22f52d84f8bb2fe806e963ecfb9dc196ab29804baee4c156eabbdbd9";
pub const NPM_SOURCE_RUNTIME_SHA256: &str = "701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5";
pub const NPM_SOURCE_SEMANTICS_SHA256: &str = "267dfc6b7240c36cdf345553e02a4f7b5332fa70548349bc6ef4b3075b4fcb4b";
pub const NPM_SOURCE_PROTO_SHA256: &str = "bd394a11de37449710f0fd7dc10eac4e7f4ad299141a9fd54ec156980246fe1e";
pub const NPM_SOURCE_VALIDATOR_SHA256: &str = "5dac40f6f81223b0e373eb69e12a652754bc92879c0da28244ba80849b95c177";
pub const NPM_SOURCE_BINDING_SHA256: &str = "0dba8501e790d4efd0cda3cf64c9eddbca01cb9ce90da3931568224b38c7be3d";
pub const NPM_HANDLER_REDUCER_RUNTIME_SHA256: &str = "6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6";
pub const NPM_HANDLER_REDUCER_SEMANTICS_SHA256: &str =
    "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143";
pub const WRITER_RUNTIME_SHA256: &str = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca";
pub const WRITER_PROFILE_SHA256: &str = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823";
pub const WRITER_COMPATIBILITY_SHA256: &str = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4";
pub const WRITER_PROTO_SHA256: &str = "f87b4bc718349bae2ff8fe799e4a4dadbb507240b7b6e9bc8d7a199299e33c59";
pub const SEGMENT_MATRIX_SHA256: &str = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161";
pub const EXECUTION_ORDER_SHA256: &str = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2";

const MAINNET_MANAGER: Address = [
    0xc3, 0x64, 0x42, 0xb4, 0xa4, 0x52, 0x2e, 0x87, 0x13, 0x99, 0xcd, 0x71, 0x7a, 0xbd, 0xd8, 0x47, 0xab, 0x11, 0xfe,
    0x88,
];
const MAINNET_FACTORY: Address = [
    0x1f, 0x98, 0x43, 0x1c, 0x8a, 0xd9, 0x85, 0x23, 0x63, 0x1a, 0xe4, 0xa5, 0x9f, 0x26, 0x73, 0x46, 0xea, 0x31, 0xf9,
    0x84,
];
const BASE_MANAGER: Address = [
    0x03, 0xa5, 0x20, 0xb3, 0x2c, 0x04, 0xbf, 0x3b, 0xee, 0xf7, 0xbe, 0xb7, 0x2e, 0x91, 0x9c, 0xf8, 0x22, 0xed, 0x34,
    0xf1,
];
const BASE_FACTORY: Address = [
    0x33, 0x12, 0x8a, 0x8f, 0xc1, 0x78, 0x69, 0x89, 0x7d, 0xce, 0x68, 0xed, 0x02, 0x6d, 0x69, 0x46, 0x21, 0xf6, 0xdf,
    0xd0,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResolutionGate {
    Resolved,
    PossibleReorg,
    Unknown,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Gated<T> {
    gate: ResolutionGate,
    value: Option<T>,
}

impl<T> Gated<T> {
    pub fn resolved(value: T) -> Self {
        Self {
            gate: ResolutionGate::Resolved,
            value: Some(value),
        }
    }

    pub fn possible_reorg() -> Self {
        Self {
            gate: ResolutionGate::PossibleReorg,
            value: None,
        }
    }

    pub fn unknown() -> Self {
        Self {
            gate: ResolutionGate::Unknown,
            value: None,
        }
    }

    pub fn resolved_value_mut(&mut self) -> Option<&mut T> {
        match self.gate {
            ResolutionGate::Resolved => self.value.as_mut(),
            ResolutionGate::PossibleReorg | ResolutionGate::Unknown => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CapturedCallScope {
    Eip1898Hash(Vec<u8>),
    BlockNumberFallback(u64),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CapturedPositionResult {
    Value(CapturedPositionValue),
    None,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedPositionValue {
    pub token0: Vec<u8>,
    pub token1: Vec<u8>,
    pub fee: u32,
    pub tick_lower: i32,
    pub tick_upper: i32,
    pub fee_growth_inside0_last_x128: Vec<u8>,
    pub fee_growth_inside1_last_x128: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedPositionObservation {
    pub position_manager: Vec<u8>,
    pub token_id: Vec<u8>,
    pub result: CapturedPositionResult,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CapturedPoolResult {
    Value(Vec<u8>),
    None,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedPoolObservation {
    pub factory: Vec<u8>,
    pub token0: Vec<u8>,
    pub token1: Vec<u8>,
    pub fee: u32,
    pub result: CapturedPoolResult,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CapturedTokenResult {
    Found(u8),
    Missing,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedTokenObservation {
    pub address: Vec<u8>,
    pub ordinal: u64,
    pub result: CapturedTokenResult,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SuppliedResolvedObservations {
    pub call_scope: Gated<CapturedCallScope>,
    pub position_calls: Vec<Gated<CapturedPositionObservation>>,
    pub pool_calls: Vec<Gated<CapturedPoolObservation>>,
    pub token_reads: Vec<Gated<CapturedTokenObservation>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputBuildError(pub String);

impl fmt::Display for InputBuildError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for InputBuildError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputFrameError(pub String);

impl fmt::Display for InputFrameError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for InputFrameError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InputConsumption {
    pub position_requests: BTreeMap<(Address, [u8; 32]), usize>,
    pub pool_requests: BTreeMap<(Address, Address, Address, u32), usize>,
    pub token_requests: BTreeMap<(u64, Address), usize>,
}

pub fn map_resolved_npm_inputs(
    source: &NpmSourceBlock,
    supplied: SuppliedResolvedObservations,
) -> Result<NpmResolvedInputs, InputBuildError> {
    crate::npm_source_block::validate_npm_source_block(source)
        .map_err(|error| InputBuildError(format!("invalid NPM source block: {error}")))?;
    verify_embedded_contract().map_err(|error| InputBuildError(error.0))?;
    let block = source.block.as_ref().expect("validated source block");
    let events = source.writer_events.as_ref().expect("validated source events");
    let (manager, factory) = configured_addresses(&events.network).map_err(InputBuildError)?;

    let scope = require_resolved(supplied.call_scope, "call scope")?;
    let scope = match scope {
        CapturedCallScope::Eip1898Hash(hash) => {
            let hash = exact_array::<32>("resolved EIP-1898 hash", &hash).map_err(to_build)?;
            let source_hash = exact_array::<32>("source block hash", &block.hash).map_err(to_build)?;
            if hash != source_hash {
                return Err(InputBuildError(
                    "resolved EIP-1898 hash does not equal source block hash".to_owned(),
                ));
            }
            Scope::Eip1898Hash(hash.to_vec())
        }
        CapturedCallScope::BlockNumberFallback(number) if number == block.number => Scope::BlockNumberFallback(number),
        CapturedCallScope::BlockNumberFallback(_) => {
            return Err(InputBuildError(
                "resolved block-number fallback does not equal source block number".to_owned(),
            ));
        }
    };

    let position_calls = normalize_positions(supplied.position_calls, manager)?;
    let pool_calls = normalize_pools(supplied.pool_calls, factory)?;
    let token_reads = normalize_tokens(supplied.token_reads)?;
    let frame = NpmResolvedInputs {
        source: Some(source.clone()),
        call_scope: Some(ResolvedCallScope { scope: Some(scope) }),
        position_calls,
        pool_calls,
        token_reads,
        input_contract_sha256: INPUT_SEMANTICS_SHA256.to_owned(),
        npm_source_contract_sha256: NPM_SOURCE_RUNTIME_SHA256.to_owned(),
        npm_handler_reducer_contract_sha256: NPM_HANDLER_REDUCER_RUNTIME_SHA256.to_owned(),
    };
    validate_frame(&frame).map_err(|error| InputBuildError(error.0))?;
    Ok(frame)
}

pub fn decode_npm_resolved_input_frame(bytes: &[u8]) -> Result<NpmResolvedInputs, InputFrameError> {
    let frame = NpmResolvedInputs::decode(bytes)
        .map_err(|error| InputFrameError(format!("invalid resolved-input protobuf: {error}")))?;
    if frame.encode_to_vec() != bytes {
        return Err(InputFrameError(
            "resolved-input protobuf is noncanonical or contains unknown fields".to_owned(),
        ));
    }
    validate_frame(&frame)?;
    Ok(frame)
}

pub fn reduce_npm_resolved_input_frame(
    initial: &ReducerState,
    frame: &NpmResolvedInputs,
) -> Result<BlockReduction, InputFrameError> {
    reduce_npm_resolved_input_frame_with_audit(initial, frame).map(|(reduction, _)| reduction)
}

pub fn reduce_npm_resolved_input_frame_with_audit(
    initial: &ReducerState,
    frame: &NpmResolvedInputs,
) -> Result<(BlockReduction, InputConsumption), InputFrameError> {
    validate_frame(frame)?;
    let source = frame.source.as_ref().expect("validated source");
    let events = source.writer_events.as_ref().expect("validated source events");
    let block = source.block.as_ref().expect("validated source block");
    let hash = match frame
        .call_scope
        .as_ref()
        .expect("validated call scope")
        .scope
        .as_ref()
        .expect("validated call-scope oneof")
    {
        Scope::Eip1898Hash(value) => Some(exact_array::<32>("resolved EIP-1898 hash", value)?),
        Scope::BlockNumberFallback(_) => None,
    };
    let diagnostic = DiagnosticInput {
        writer_events: events.clone(),
        block: BlockContext {
            number: block.number,
            timestamp: block.timestamp_seconds,
            hash,
        },
        transactions: source
            .transactions
            .iter()
            .map(|transaction| {
                Ok(TransactionMetadata {
                    transaction_hash: exact_array::<32>("source transaction hash", &transaction.hash)?,
                    gas_limit: transaction.gas_limit.to_string(),
                    gas_price: BigUint::from_bytes_be(&transaction.gas_price_be).to_str_radix(10),
                })
            })
            .collect::<Result<Vec<_>, InputFrameError>>()?,
        controls: events
            .events
            .iter()
            .map(|event| EventControl {
                ordinal: event.ordinal,
                failure_phase: FailurePhase::None,
            })
            .collect(),
    };
    let mut inputs = FrameReducerInputs::new(frame)?;
    let reduction = npm_handler_reducer::reduce_npm_handler_block(initial, &diagnostic, &mut inputs)
        .map_err(|error| InputFrameError(format!("joint NPM reducer rejected frame: {error}")))?;
    if let Some(message) = inputs.missing_consumed {
        return Err(InputFrameError(message));
    }
    if reduction.disposition.authorizes_graph_block_or_checkpoint_success() {
        return Err(InputFrameError(
            "joint reducer disposition unexpectedly authorized Graph/checkpoint success".to_owned(),
        ));
    }
    Ok((reduction, inputs.consumption))
}

pub const fn source_frame_authorizes_graph_block_or_checkpoint_success(_: &NpmSourceBlock) -> bool {
    false
}

pub const fn resolved_input_frame_authorizes_graph_block_or_checkpoint_success(_: &NpmResolvedInputs) -> bool {
    false
}

pub const fn reducer_disposition_authorizes_graph_block_or_checkpoint_success(disposition: &BlockDisposition) -> bool {
    disposition.authorizes_graph_block_or_checkpoint_success()
}

fn require_resolved<T>(gated: Gated<T>, name: &str) -> Result<T, InputBuildError> {
    match gated.gate {
        ResolutionGate::Resolved => gated
            .value
            .ok_or_else(|| InputBuildError(format!("resolved {name} is missing its value"))),
        ResolutionGate::PossibleReorg => Err(InputBuildError(format!(
            "{name} resolution is not stable at the requested block pointer"
        ))),
        ResolutionGate::Unknown => Err(InputBuildError(format!("{name} resolution is unknown"))),
    }
}

fn normalize_positions(
    supplied: Vec<Gated<CapturedPositionObservation>>,
    manager: Address,
) -> Result<Vec<PositionObservation>, InputBuildError> {
    let mut keys = BTreeSet::new();
    let mut output = Vec::with_capacity(supplied.len());
    for gated in supplied {
        let call = require_resolved(gated, "position observation")?;
        let actual_manager = exact_array::<20>("position manager", &call.position_manager).map_err(to_build)?;
        let token_id = exact_array::<32>("position token id", &call.token_id).map_err(to_build)?;
        if actual_manager != manager {
            return Err(InputBuildError("position observation uses a non-static NPM".to_owned()));
        }
        if !keys.insert((actual_manager, token_id)) {
            return Err(InputBuildError("duplicate position observation".to_owned()));
        }
        let result = match call.result {
            CapturedPositionResult::None => PositionResult::None(ResolvedNone {}),
            CapturedPositionResult::Value(value) => {
                validate_position_value(&value).map_err(to_build)?;
                PositionResult::Value(PositionValue {
                    token0: value.token0,
                    token1: value.token1,
                    fee: value.fee,
                    tick_lower: value.tick_lower,
                    tick_upper: value.tick_upper,
                    fee_growth_inside0_last_x128: value.fee_growth_inside0_last_x128,
                    fee_growth_inside1_last_x128: value.fee_growth_inside1_last_x128,
                })
            }
        };
        output.push(PositionObservation {
            position_manager: actual_manager.to_vec(),
            token_id: token_id.to_vec(),
            result: Some(result),
        });
    }
    output.sort_by(|left, right| {
        (&left.position_manager, &left.token_id).cmp(&(&right.position_manager, &right.token_id))
    });
    Ok(output)
}

fn normalize_pools(
    supplied: Vec<Gated<CapturedPoolObservation>>,
    factory: Address,
) -> Result<Vec<PoolObservation>, InputBuildError> {
    let mut keys = BTreeSet::new();
    let mut output = Vec::with_capacity(supplied.len());
    for gated in supplied {
        let call = require_resolved(gated, "pool observation")?;
        let actual_factory = exact_array::<20>("pool factory", &call.factory).map_err(to_build)?;
        let token0 = exact_array::<20>("pool token0", &call.token0).map_err(to_build)?;
        let token1 = exact_array::<20>("pool token1", &call.token1).map_err(to_build)?;
        validate_fee(call.fee).map_err(to_build)?;
        if actual_factory != factory {
            return Err(InputBuildError("pool observation uses a non-static factory".to_owned()));
        }
        if !keys.insert((actual_factory, token0, token1, call.fee)) {
            return Err(InputBuildError("duplicate pool observation".to_owned()));
        }
        let result = match call.result {
            CapturedPoolResult::None => PoolResult::None(ResolvedNone {}),
            CapturedPoolResult::Value(pool) => {
                let pool = exact_array::<20>("pool result", &pool).map_err(to_build)?;
                PoolResult::Pool(pool.to_vec())
            }
        };
        output.push(PoolObservation {
            factory: actual_factory.to_vec(),
            token0: token0.to_vec(),
            token1: token1.to_vec(),
            fee: call.fee,
            result: Some(result),
        });
    }
    output.sort_by(|left, right| {
        (&left.factory, &left.token0, &left.token1, left.fee).cmp(&(
            &right.factory,
            &right.token0,
            &right.token1,
            right.fee,
        ))
    });
    Ok(output)
}

fn normalize_tokens(supplied: Vec<Gated<CapturedTokenObservation>>) -> Result<Vec<TokenObservation>, InputBuildError> {
    let mut keys = BTreeSet::new();
    let mut output = Vec::with_capacity(supplied.len());
    for gated in supplied {
        let read = require_resolved(gated, "Token observation")?;
        let address = exact_array::<20>("Token address", &read.address).map_err(to_build)?;
        if !keys.insert((read.ordinal, address)) {
            return Err(InputBuildError("duplicate Token observation".to_owned()));
        }
        let result = match read.result {
            CapturedTokenResult::Found(decimals) => TokenResult::Found(TokenFound {
                decimals: u32::from(decimals),
            }),
            CapturedTokenResult::Missing => TokenResult::Missing(ResolvedNone {}),
        };
        output.push(TokenObservation {
            address: address.to_vec(),
            ordinal: read.ordinal,
            result: Some(result),
        });
    }
    output.sort_by(|left, right| (left.ordinal, &left.address).cmp(&(right.ordinal, &right.address)));
    Ok(output)
}

fn validate_frame(frame: &NpmResolvedInputs) -> Result<(), InputFrameError> {
    verify_embedded_contract()?;
    if frame.input_contract_sha256 != INPUT_SEMANTICS_SHA256
        || frame.npm_source_contract_sha256 != NPM_SOURCE_RUNTIME_SHA256
        || frame.npm_handler_reducer_contract_sha256 != NPM_HANDLER_REDUCER_RUNTIME_SHA256
    {
        return Err(InputFrameError("resolved-input contract digest drift".to_owned()));
    }
    let source = frame
        .source
        .as_ref()
        .ok_or_else(|| InputFrameError("NpmSourceBlock is missing".to_owned()))?;
    crate::npm_source_block::validate_npm_source_block(source)
        .map_err(|error| InputFrameError(format!("invalid nested NpmSourceBlock: {error}")))?;
    if source_frame_authorizes_graph_block_or_checkpoint_success(source)
        || resolved_input_frame_authorizes_graph_block_or_checkpoint_success(frame)
    {
        return Err(InputFrameError("source/input authority gate drift".to_owned()));
    }
    let block = source.block.as_ref().expect("validated source block");
    match frame
        .call_scope
        .as_ref()
        .ok_or_else(|| InputFrameError("resolved call scope is missing".to_owned()))?
        .scope
        .as_ref()
        .ok_or_else(|| InputFrameError("resolved call-scope oneof is missing".to_owned()))?
    {
        Scope::Eip1898Hash(hash)
            if exact_array::<32>("resolved EIP-1898 hash", hash)?
                == exact_array::<32>("source block hash", &block.hash)? => {}
        Scope::Eip1898Hash(_) => {
            return Err(InputFrameError(
                "resolved EIP-1898 hash does not equal source block hash".to_owned(),
            ));
        }
        Scope::BlockNumberFallback(number) if *number == block.number => {}
        Scope::BlockNumberFallback(_) => {
            return Err(InputFrameError(
                "resolved block-number fallback does not equal source block number".to_owned(),
            ));
        }
    }
    let events = source.writer_events.as_ref().expect("validated source events");
    let (manager, factory) = configured_addresses(&events.network).map_err(InputFrameError)?;
    validate_frame_positions(&frame.position_calls, manager)?;
    validate_frame_pools(&frame.pool_calls, factory)?;
    validate_frame_tokens(&frame.token_reads)
}

fn validate_frame_positions(calls: &[PositionObservation], manager: Address) -> Result<(), InputFrameError> {
    let mut previous: Option<(Address, [u8; 32])> = None;
    for call in calls {
        let actual_manager = exact_array::<20>("position manager", &call.position_manager)?;
        let token_id = exact_array::<32>("position token id", &call.token_id)?;
        if actual_manager != manager {
            return Err(InputFrameError("position observation uses a non-static NPM".to_owned()));
        }
        let key = (actual_manager, token_id);
        if previous.is_some_and(|prior| prior >= key) {
            return Err(InputFrameError(
                "position observations are duplicate or unsorted".to_owned(),
            ));
        }
        previous = Some(key);
        match call
            .result
            .as_ref()
            .ok_or_else(|| InputFrameError("position result oneof is missing".to_owned()))?
        {
            PositionResult::None(_) => {}
            PositionResult::Value(value) => validate_position_value_proto(value)?,
        }
    }
    Ok(())
}

fn validate_frame_pools(calls: &[PoolObservation], factory: Address) -> Result<(), InputFrameError> {
    let mut previous: Option<(Address, Address, Address, u32)> = None;
    for call in calls {
        let actual_factory = exact_array::<20>("pool factory", &call.factory)?;
        let token0 = exact_array::<20>("pool token0", &call.token0)?;
        let token1 = exact_array::<20>("pool token1", &call.token1)?;
        validate_fee(call.fee)?;
        if actual_factory != factory {
            return Err(InputFrameError("pool observation uses a non-static factory".to_owned()));
        }
        let key = (actual_factory, token0, token1, call.fee);
        if previous.is_some_and(|prior| prior >= key) {
            return Err(InputFrameError(
                "pool observations are duplicate or unsorted".to_owned(),
            ));
        }
        previous = Some(key);
        match call
            .result
            .as_ref()
            .ok_or_else(|| InputFrameError("pool result oneof is missing".to_owned()))?
        {
            PoolResult::Pool(pool) => {
                exact_array::<20>("pool result", pool)?;
            }
            PoolResult::None(_) => {}
        }
    }
    Ok(())
}

fn validate_frame_tokens(reads: &[TokenObservation]) -> Result<(), InputFrameError> {
    let mut previous: Option<(u64, Address)> = None;
    for read in reads {
        let address = exact_array::<20>("Token address", &read.address)?;
        let key = (read.ordinal, address);
        if previous.is_some_and(|prior| prior >= key) {
            return Err(InputFrameError(
                "Token observations are duplicate or unsorted".to_owned(),
            ));
        }
        previous = Some(key);
        match read
            .result
            .as_ref()
            .ok_or_else(|| InputFrameError("Token result oneof is missing".to_owned()))?
        {
            TokenResult::Found(found) if found.decimals <= u32::from(u8::MAX) => {}
            TokenResult::Found(_) => return Err(InputFrameError("Token decimals exceed 255".to_owned())),
            TokenResult::Missing(_) => {}
        }
    }
    Ok(())
}

fn validate_position_value(value: &CapturedPositionValue) -> Result<(), InputFrameError> {
    exact_array::<20>("position token0", &value.token0)?;
    exact_array::<20>("position token1", &value.token1)?;
    validate_fee_tick_growth(
        value.fee,
        value.tick_lower,
        value.tick_upper,
        &value.fee_growth_inside0_last_x128,
        &value.fee_growth_inside1_last_x128,
    )
}

fn validate_position_value_proto(value: &PositionValue) -> Result<(), InputFrameError> {
    exact_array::<20>("position token0", &value.token0)?;
    exact_array::<20>("position token1", &value.token1)?;
    validate_fee_tick_growth(
        value.fee,
        value.tick_lower,
        value.tick_upper,
        &value.fee_growth_inside0_last_x128,
        &value.fee_growth_inside1_last_x128,
    )
}

fn validate_fee_tick_growth(
    fee: u32,
    tick_lower: i32,
    tick_upper: i32,
    fee_growth0: &[u8],
    fee_growth1: &[u8],
) -> Result<(), InputFrameError> {
    validate_fee(fee)?;
    for (name, tick) in [("tick_lower", tick_lower), ("tick_upper", tick_upper)] {
        if !(-8_388_608..=8_388_607).contains(&tick) {
            return Err(InputFrameError(format!("{name} is outside signed int24")));
        }
    }
    exact_array::<32>("fee_growth_inside0_last_x128", fee_growth0)?;
    exact_array::<32>("fee_growth_inside1_last_x128", fee_growth1)?;
    Ok(())
}

fn validate_fee(fee: u32) -> Result<(), InputFrameError> {
    if fee > 0x00ff_ffff {
        return Err(InputFrameError("fee exceeds uint24".to_owned()));
    }
    Ok(())
}

fn configured_addresses(network: &str) -> Result<(Address, Address), String> {
    match network {
        "mainnet" => Ok((MAINNET_MANAGER, MAINNET_FACTORY)),
        "base" => Ok((BASE_MANAGER, BASE_FACTORY)),
        other => Err(format!("unsupported resolved-input network `{other}`")),
    }
}

fn verify_embedded_contract() -> Result<(), InputFrameError> {
    let raw = include_str!("../configs/npm-resolved-inputs-v1.json");
    if hex::encode(Sha256::digest(raw.as_bytes())) != INPUT_SEMANTICS_SHA256 {
        return Err(InputFrameError(
            "resolved-input semantic contract digest drift".to_owned(),
        ));
    }
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| InputFrameError(format!("invalid resolved-input semantic contract: {error}")))?;
    let string = |key: &str| value.get(key).and_then(Value::as_str);
    if value.get("format_version").and_then(Value::as_u64) != Some(1)
        || string("contract_version") != Some("uniswap-v3-npm-resolved-inputs/v1")
        || string("mode") != Some("host-diagnostic-only")
        || string("source_npm_source_runtime_sha256") != Some(NPM_SOURCE_RUNTIME_SHA256)
        || string("source_npm_source_semantics_sha256") != Some(NPM_SOURCE_SEMANTICS_SHA256)
        || string("source_npm_handler_reducer_runtime_sha256") != Some(NPM_HANDLER_REDUCER_RUNTIME_SHA256)
        || string("source_npm_handler_reducer_semantics_sha256") != Some(NPM_HANDLER_REDUCER_SEMANTICS_SHA256)
    {
        return Err(InputFrameError("resolved-input semantic binding drift".to_owned()));
    }
    let truth = value
        .get("truth_boundary")
        .and_then(Value::as_object)
        .ok_or_else(|| InputFrameError("resolved-input truth boundary is missing".to_owned()))?;
    for key in [
        "integrated_host_engine_added",
        "post_fatal_execution_modeled",
        "all_required_observations_evaluated",
        "graph_execution_trace_complete",
        "checkpoint_or_graph_block_success_authorized",
        "boundary_state_continuity_complete",
        "physical_parity_complete",
        "poi_parity_complete",
        "backfill_ready",
        "production_ready",
    ] {
        if truth.get(key).and_then(Value::as_bool) != Some(false) {
            return Err(InputFrameError(format!("resolved-input truth gate `{key}` drift")));
        }
    }
    Ok(())
}

fn exact_array<const N: usize>(field: &str, bytes: &[u8]) -> Result<[u8; N], InputFrameError> {
    bytes
        .try_into()
        .map_err(|_| InputFrameError(format!("{field} must be exactly {N} bytes")))
}

fn to_build(error: InputFrameError) -> InputBuildError {
    InputBuildError(error.0)
}

struct FrameReducerInputs {
    scope: BlockScope,
    positions: BTreeMap<(Address, [u8; 32]), Option<PositionCall>>,
    pools: BTreeMap<(Address, Address, Address, u32), Option<Address>>,
    tokens: BTreeMap<(u64, Address), Option<u8>>,
    missing_consumed: Option<String>,
    consumption: InputConsumption,
}

impl FrameReducerInputs {
    fn new(frame: &NpmResolvedInputs) -> Result<Self, InputFrameError> {
        let source = frame.source.as_ref().expect("validated source");
        let events = source.writer_events.as_ref().expect("validated source events");
        let block = source.block.as_ref().expect("validated source block");
        let block_hash = match frame
            .call_scope
            .as_ref()
            .expect("validated call scope")
            .scope
            .as_ref()
            .expect("validated call-scope oneof")
        {
            Scope::Eip1898Hash(hash) => Some(exact_array::<32>("resolved EIP-1898 hash", hash)?),
            Scope::BlockNumberFallback(_) => None,
        };
        let positions = frame
            .position_calls
            .iter()
            .map(|call| {
                let key = (
                    exact_array::<20>("position manager", &call.position_manager)?,
                    exact_array::<32>("position token id", &call.token_id)?,
                );
                let value = match call.result.as_ref().expect("validated position result") {
                    PositionResult::None(_) => None,
                    PositionResult::Value(value) => Some(PositionCall {
                        token0: exact_array::<20>("position token0", &value.token0)?,
                        token1: exact_array::<20>("position token1", &value.token1)?,
                        fee: value.fee,
                        tick_lower: value.tick_lower,
                        tick_upper: value.tick_upper,
                        fee_growth_inside0_last_x128: BigUint::from_bytes_be(&value.fee_growth_inside0_last_x128),
                        fee_growth_inside1_last_x128: BigUint::from_bytes_be(&value.fee_growth_inside1_last_x128),
                    }),
                };
                Ok((key, value))
            })
            .collect::<Result<BTreeMap<_, _>, InputFrameError>>()?;
        let pools = frame
            .pool_calls
            .iter()
            .map(|call| {
                let key = (
                    exact_array::<20>("pool factory", &call.factory)?,
                    exact_array::<20>("pool token0", &call.token0)?,
                    exact_array::<20>("pool token1", &call.token1)?,
                    call.fee,
                );
                let value = match call.result.as_ref().expect("validated pool result") {
                    PoolResult::Pool(pool) => Some(exact_array::<20>("pool result", pool)?),
                    PoolResult::None(_) => None,
                };
                Ok((key, value))
            })
            .collect::<Result<BTreeMap<_, _>, InputFrameError>>()?;
        let tokens = frame
            .token_reads
            .iter()
            .map(|read| {
                let key = (read.ordinal, exact_array::<20>("Token address", &read.address)?);
                let value = match read.result.as_ref().expect("validated Token result") {
                    TokenResult::Found(found) => Some(found.decimals as u8),
                    TokenResult::Missing(_) => None,
                };
                Ok((key, value))
            })
            .collect::<Result<BTreeMap<_, _>, InputFrameError>>()?;
        Ok(Self {
            scope: BlockScope {
                network: events.network.clone(),
                block_number: block.number,
                block_hash,
            },
            positions,
            pools,
            tokens,
            missing_consumed: None,
            consumption: InputConsumption::default(),
        })
    }

    fn missing(&mut self, message: String) -> String {
        if self.missing_consumed.is_none() {
            self.missing_consumed = Some(message.clone());
        }
        message
    }

    fn validate_scope(&mut self, scope: &BlockScope) -> Result<(), String> {
        if scope != &self.scope {
            return Err(self.missing("consumed call scope does not match resolved frame pointer".to_owned()));
        }
        Ok(())
    }
}

impl ReducerInputs for FrameReducerInputs {
    fn position_at_block(
        &mut self,
        scope: &BlockScope,
        position_manager: Address,
        token_id: &str,
    ) -> Result<Option<PositionCall>, String> {
        self.validate_scope(scope)?;
        let token_id_value = BigUint::parse_bytes(token_id.as_bytes(), 10)
            .ok_or_else(|| self.missing(format!("invalid consumed token id {token_id}")))?;
        let raw = token_id_value.to_bytes_be();
        if raw.len() > 32 {
            return Err(self.missing(format!("consumed token id exceeds uint256: {token_id}")));
        }
        let mut word = [0_u8; 32];
        word[32 - raw.len()..].copy_from_slice(&raw);
        let key = (position_manager, word);
        *self.consumption.position_requests.entry(key).or_default() += 1;
        self.positions
            .get(&key)
            .cloned()
            .ok_or_else(|| self.missing(format!("missing resolved positions({token_id}) observation")))
    }

    fn pool_at_block(
        &mut self,
        scope: &BlockScope,
        factory: Address,
        token0: Address,
        token1: Address,
        fee: u32,
    ) -> Result<Address, String> {
        self.validate_scope(scope)?;
        let key = (factory, token0, token1, fee);
        *self.consumption.pool_requests.entry(key).or_default() += 1;
        match self.pools.get(&key).copied() {
            Some(Some(pool)) => Ok(pool),
            Some(None) => Err("resolved getPool returned no value".to_owned()),
            None => Err(self.missing(format!(
                "missing resolved getPool({}, {}, {}) observation",
                hex::encode(token0),
                hex::encode(token1),
                fee
            ))),
        }
    }

    fn token_decimals_at_ordinal(&mut self, address: Address, ordinal: u64) -> Result<Option<u8>, String> {
        let key = (ordinal, address);
        *self.consumption.token_requests.entry(key).or_default() += 1;
        self.tokens
            .get(&key)
            .copied()
            .ok_or_else(|| self.missing(format!("missing resolved Token.load at ordinal {ordinal}")))
    }
}
