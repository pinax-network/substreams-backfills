//! Host-only conservative observation planner for the joint NPM reducer.
//!
//! The planner closes every request identity that the NPM reducer can consume
//! from the complete WriterEvents envelope. It intentionally over-plans paths
//! that a later handler return or fatal projection may skip. Resolution status
//! and provider failure payloads remain outside every canonical message.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

use num_bigint::BigUint;
use prost::Message;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::npm_handler_reducer::{Address, BlockReduction, ReducerState};
use crate::npm_inputs_pb::position_observation::Result as PositionResult;
use crate::npm_inputs_pb::resolved_call_scope::Scope;
use crate::npm_inputs_pb::{NpmResolvedInputs, PositionObservation};
use crate::npm_plan_pb::{NpmObservationPlan, PoolRequest, PositionRequest, TokenRequest};
use crate::npm_resolved_inputs::{
    self, CapturedCallScope, CapturedPoolObservation, CapturedPositionObservation, CapturedTokenObservation, Gated,
    InputConsumption, SuppliedResolvedObservations,
};
use crate::pb::npm_source::NpmSourceBlock;
use crate::pb::writer::writer_event::Event;
use crate::pb::writer::WriterEvent;

pub const PLAN_SEMANTICS_SHA256: &str = "6e80d215e6e8fb22a8b1bf69172f973fb065d6a5605e5cdcb7d69298fbed41c9";
pub const RESOLVED_INPUT_RUNTIME_SHA256: &str = "c5ad1556273b0c532f8d00e27c257250b596d022dc25dc4f9443c429303c0a1a";
pub const RESOLVED_INPUT_SEMANTICS_SHA256: &str = "01f7e87b22f52d84f8bb2fe806e963ecfb9dc196ab29804baee4c156eabbdbd9";
pub const NPM_SOURCE_RUNTIME_SHA256: &str = "701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5";
pub const NPM_HANDLER_REDUCER_RUNTIME_SHA256: &str = "6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6";
pub const NPM_HANDLER_REDUCER_SEMANTICS_SHA256: &str =
    "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143";
pub const WRITER_RUNTIME_SHA256: &str = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca";
pub const WRITER_PROFILE_SHA256: &str = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823";
pub const WRITER_COMPATIBILITY_SHA256: &str = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4";
pub const SEGMENT_MATRIX_SHA256: &str = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161";
pub const EXECUTION_ORDER_SHA256: &str = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2";

pub const POSITION_REASON_IDENTITY: u32 = 1 << 0;
pub const POSITION_REASON_FEE_REFRESH: u32 = 1 << 1;
pub const POSITION_REASON_FULL_ENVELOPE: u32 = 1 << 2;
pub const POOL_REASON_PROVISIONAL_IDENTITY: u32 = 1 << 0;
pub const POOL_REASON_FULL_ENVELOPE: u32 = 1 << 1;
pub const TOKEN_REASON_TOKEN0_SCALE: u32 = 1 << 0;
pub const TOKEN_REASON_TOKEN1_SCALE: u32 = 1 << 1;
pub const TOKEN_REASON_FULL_ENVELOPE: u32 = 1 << 2;

const POSITION_REASON_MASK: u32 =
    POSITION_REASON_IDENTITY | POSITION_REASON_FEE_REFRESH | POSITION_REASON_FULL_ENVELOPE;
const POOL_REASON_MASK: u32 = POOL_REASON_PROVISIONAL_IDENTITY | POOL_REASON_FULL_ENVELOPE;
const TOKEN_REASON_MASK: u32 = TOKEN_REASON_TOKEN0_SCALE | TOKEN_REASON_TOKEN1_SCALE | TOKEN_REASON_FULL_ENVELOPE;
const PLANNING_STATE_DOMAIN: &[u8] = b"uniswap-v3-npm-planning-state/v1\0";

type PositionKey = (Address, [u8; 32]);
type PoolKey = (Address, Address, Address, u32);
type TokenKey = (u64, Address);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObservationPlanError(pub String);

impl fmt::Display for ObservationPlanError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for ObservationPlanError {}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PlanningPosition {
    token0: Address,
    token1: Address,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TokenRole {
    Token0,
    Token1,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct SelectedSemantics {
    npm_profile_id: String,
    position_manager: Address,
    factory: Address,
    collect_token_reads: Vec<TokenRole>,
}

#[derive(Clone, Debug)]
struct ResolvedPlanningCallScope(CapturedCallScope);

#[derive(Clone, Debug)]
pub struct PositionPlanningPhase {
    source: NpmSourceBlock,
    call_scope: ResolvedPlanningCallScope,
    planning_positions: BTreeMap<String, PlanningPosition>,
    planning_state_sha256: [u8; 32],
    semantics: SelectedSemantics,
    requests: Vec<PositionRequest>,
}

impl PositionPlanningPhase {
    pub fn requests(&self) -> &[PositionRequest] {
        &self.requests
    }

    pub fn planning_state_sha256(&self) -> [u8; 32] {
        self.planning_state_sha256
    }
}

#[derive(Clone, Debug)]
pub struct CompletePlanningPhase {
    phase: PositionPlanningPhase,
    positions: Vec<Gated<CapturedPositionObservation>>,
    plan: NpmObservationPlan,
}

impl CompletePlanningPhase {
    pub fn plan(&self) -> &NpmObservationPlan {
        &self.plan
    }
}

#[derive(Clone, Debug)]
pub struct PreflightedResolvedFrame {
    frame: NpmResolvedInputs,
    plan: NpmObservationPlan,
}

impl PreflightedResolvedFrame {
    pub fn frame(&self) -> &NpmResolvedInputs {
        &self.frame
    }

    pub fn plan(&self) -> &NpmObservationPlan {
        &self.plan
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CoverageAudit {
    pub planned_position_keys: usize,
    pub planned_pool_keys: usize,
    pub planned_token_keys: usize,
    pub resolved_position_keys: usize,
    pub resolved_pool_keys: usize,
    pub resolved_token_keys: usize,
    pub consumed_position_calls: usize,
    pub consumed_pool_calls: usize,
    pub consumed_token_reads: usize,
    pub unconsumed_position_keys: usize,
    pub unconsumed_pool_keys: usize,
    pub unconsumed_token_keys: usize,
}

pub fn plan_position_observations(
    source: &NpmSourceBlock,
    initial: &ReducerState,
    mut call_scope: Gated<CapturedCallScope>,
) -> Result<PositionPlanningPhase, ObservationPlanError> {
    crate::npm_source_block::validate_npm_source_block(source)
        .map_err(|error| ObservationPlanError(format!("invalid NPM source block: {error}")))?;
    verify_plan_contract()?;
    let semantics = select_semantics(source)?;
    let call_scope = call_scope
        .resolved_value_mut()
        .cloned()
        .ok_or_else(|| ObservationPlanError("planning call scope is unresolved or unstable".to_owned()))?;
    validate_call_scope(source, &call_scope)?;
    let call_scope = ResolvedPlanningCallScope(call_scope);
    let (planning_positions, planning_state_sha256) = planning_state(initial)?;
    let events = &source.writer_events.as_ref().expect("validated source events").events;
    let mut requests: BTreeMap<PositionKey, RequestAccumulator> = BTreeMap::new();
    for event in events {
        let (kind, token_id) = event_identity(event)?;
        let token_word = canonical_token_word(&token_id)?;
        let entry = requests.entry((semantics.position_manager, token_word)).or_default();
        entry.ordinals.insert(event.ordinal);
        entry.reason_mask |= POSITION_REASON_IDENTITY | POSITION_REASON_FULL_ENVELOPE;
        if matches!(kind, EventKind::Increase | EventKind::Decrease | EventKind::Collect) {
            entry.reason_mask |= POSITION_REASON_FEE_REFRESH;
        }
    }
    let requests = requests
        .into_iter()
        .map(|((position_manager, token_id), value)| PositionRequest {
            position_manager: position_manager.to_vec(),
            token_id: token_id.to_vec(),
            event_ordinals: value.ordinals.into_iter().collect(),
            reason_mask: value.reason_mask,
            expected_consumption_count: 1,
        })
        .collect();
    Ok(PositionPlanningPhase {
        source: source.clone(),
        call_scope,
        planning_positions,
        planning_state_sha256,
        semantics,
        requests,
    })
}

pub fn complete_observation_plan(
    phase: PositionPlanningPhase,
    positions: Vec<Gated<CapturedPositionObservation>>,
) -> Result<CompletePlanningPhase, ObservationPlanError> {
    let position_frame = npm_resolved_inputs::map_resolved_npm_inputs(
        &phase.source,
        SuppliedResolvedObservations {
            call_scope: Gated::resolved(phase.call_scope.0.clone()),
            position_calls: positions.clone(),
            pool_calls: Vec::new(),
            token_reads: Vec::new(),
        },
    )
    .map_err(|error| ObservationPlanError(format!("position phase rejected: {error}")))?;
    require_exact_position_keys(&phase.requests, &position_frame.position_calls)?;
    let position_values = normalized_position_values(&position_frame.position_calls)?;
    let events = &phase
        .source
        .writer_events
        .as_ref()
        .expect("validated source events")
        .events;
    let mut pools: BTreeMap<PoolKey, RequestAccumulator> = BTreeMap::new();
    let mut tokens: BTreeMap<TokenKey, TokenAccumulator> = BTreeMap::new();
    for event in events {
        let (kind, token_id) = event_identity(event)?;
        let token_word = canonical_token_word(&token_id)?;
        let initial_position = phase.planning_positions.get(&token_id);
        let resolved_position = position_values
            .get(&(phase.semantics.position_manager, token_word))
            .ok_or_else(|| ObservationPlanError(format!("position phase omitted token id {token_id}")))?;
        let identity = if let Some(position) = initial_position {
            Some(position.clone())
        } else {
            resolved_position.clone().map(|value| PlanningPosition {
                token0: value.token0,
                token1: value.token1,
            })
        };
        if initial_position.is_none() {
            if let Some(value) = resolved_position {
                let key = (phase.semantics.factory, value.token0, value.token1, value.fee);
                let entry = pools.entry(key).or_default();
                entry.ordinals.insert(event.ordinal);
                entry.reason_mask |= POOL_REASON_PROVISIONAL_IDENTITY | POOL_REASON_FULL_ENVELOPE;
            }
        }
        let Some(identity) = identity else {
            continue;
        };
        let roles: &[TokenRole] = match kind {
            EventKind::Increase | EventKind::Decrease => &[TokenRole::Token0, TokenRole::Token1],
            EventKind::Collect => &phase.semantics.collect_token_reads,
            EventKind::Transfer => &[],
        };
        for role in roles {
            let (address, reason) = match role {
                TokenRole::Token0 => (identity.token0, TOKEN_REASON_TOKEN0_SCALE),
                TokenRole::Token1 => (identity.token1, TOKEN_REASON_TOKEN1_SCALE),
            };
            let entry = tokens.entry((event.ordinal, address)).or_default();
            entry.reason_mask |= reason | TOKEN_REASON_FULL_ENVELOPE;
            entry.expected_consumption_count = entry
                .expected_consumption_count
                .checked_add(1)
                .ok_or_else(|| ObservationPlanError("Token request multiplicity overflow".to_owned()))?;
        }
    }
    let pool_requests = pools
        .into_iter()
        .map(|((factory, token0, token1, fee), value)| PoolRequest {
            factory: factory.to_vec(),
            token0: token0.to_vec(),
            token1: token1.to_vec(),
            fee,
            event_ordinals: value.ordinals.into_iter().collect(),
            reason_mask: value.reason_mask,
            expected_consumption_count: 1,
        })
        .collect();
    let token_requests = tokens
        .into_iter()
        .map(|((ordinal, address), value)| TokenRequest {
            address: address.to_vec(),
            ordinal,
            reason_mask: value.reason_mask,
            expected_consumption_count: value.expected_consumption_count,
        })
        .collect();
    let block = phase.source.block.as_ref().expect("validated source block");
    let events_envelope = phase.source.writer_events.as_ref().expect("validated source events");
    let plan = NpmObservationPlan {
        source_frame_sha256: sha256(&phase.source.encode_to_vec()).to_vec(),
        planning_state_sha256: phase.planning_state_sha256.to_vec(),
        call_scope: position_frame.call_scope.clone(),
        network: events_envelope.network.clone(),
        block_number: block.number,
        block_hash: block.hash.clone(),
        segment_id: events_envelope.segment_id.clone(),
        segment_semantic_contract_sha256: events_envelope.segment_semantic_contract_sha256.clone(),
        npm_profile_id: phase.semantics.npm_profile_id.clone(),
        position_requests: phase.requests.clone(),
        pool_requests,
        token_requests,
        plan_contract_sha256: PLAN_SEMANTICS_SHA256.to_owned(),
        resolved_input_runtime_sha256: RESOLVED_INPUT_RUNTIME_SHA256.to_owned(),
    };
    validate_plan(&plan)?;
    Ok(CompletePlanningPhase { phase, positions, plan })
}

pub fn preflight_resolved_frame(
    phase: CompletePlanningPhase,
    pools: Vec<Gated<CapturedPoolObservation>>,
    tokens: Vec<Gated<CapturedTokenObservation>>,
) -> Result<PreflightedResolvedFrame, ObservationPlanError> {
    let frame = npm_resolved_inputs::map_resolved_npm_inputs(
        &phase.phase.source,
        SuppliedResolvedObservations {
            call_scope: Gated::resolved(phase.phase.call_scope.0.clone()),
            position_calls: phase.positions,
            pool_calls: pools,
            token_reads: tokens,
        },
    )
    .map_err(|error| ObservationPlanError(format!("resolved frame rejected: {error}")))?;
    require_exact_position_keys(&phase.plan.position_requests, &frame.position_calls)?;
    require_exact_pool_keys(&phase.plan.pool_requests, &frame.pool_calls)?;
    require_exact_token_keys(&phase.plan.token_requests, &frame.token_reads)?;
    if frame.call_scope != phase.plan.call_scope {
        return Err(ObservationPlanError(
            "resolved frame call scope differs from plan".to_owned(),
        ));
    }
    validate_plan(&phase.plan)?;
    let canonical = phase.plan.encode_to_vec();
    if decode_npm_observation_plan(&canonical)? != phase.plan {
        return Err(ObservationPlanError("canonical plan round trip drift".to_owned()));
    }
    Ok(PreflightedResolvedFrame {
        frame,
        plan: phase.plan,
    })
}

pub fn reduce_preflighted_npm_frame(
    initial: &ReducerState,
    preflighted: PreflightedResolvedFrame,
) -> Result<(BlockReduction, CoverageAudit), ObservationPlanError> {
    let (_, state_digest) = planning_state(initial)?;
    if preflighted.plan.planning_state_sha256 != state_digest {
        return Err(ObservationPlanError(
            "reducer planning-state projection differs from preflight plan".to_owned(),
        ));
    }
    let source = preflighted
        .frame
        .source
        .as_ref()
        .ok_or_else(|| ObservationPlanError("preflighted frame source is missing".to_owned()))?;
    if preflighted.plan.source_frame_sha256 != sha256(&source.encode_to_vec()) {
        return Err(ObservationPlanError(
            "preflighted frame source differs from plan commitment".to_owned(),
        ));
    }
    validate_plan(&preflighted.plan)?;
    let (reduction, consumption) =
        npm_resolved_inputs::reduce_npm_resolved_input_frame_with_audit(initial, &preflighted.frame)
            .map_err(|error| ObservationPlanError(format!("preflighted reducer rejected frame: {error}")))?;
    let audit = coverage_audit(&preflighted.plan, &preflighted.frame, &consumption)?;
    Ok((reduction, audit))
}

pub fn decode_npm_observation_plan(bytes: &[u8]) -> Result<NpmObservationPlan, ObservationPlanError> {
    let plan = NpmObservationPlan::decode(bytes)
        .map_err(|error| ObservationPlanError(format!("invalid observation-plan protobuf: {error}")))?;
    if plan.encode_to_vec() != bytes {
        return Err(ObservationPlanError(
            "observation-plan protobuf is noncanonical or contains unknown fields".to_owned(),
        ));
    }
    validate_plan(&plan)?;
    Ok(plan)
}

fn validate_plan(plan: &NpmObservationPlan) -> Result<(), ObservationPlanError> {
    verify_plan_contract()?;
    if plan.source_frame_sha256.len() != 32 || plan.planning_state_sha256.len() != 32 || plan.block_hash.len() != 32 {
        return Err(ObservationPlanError(
            "observation-plan digest/hash width drift".to_owned(),
        ));
    }
    if plan.plan_contract_sha256 != PLAN_SEMANTICS_SHA256
        || plan.resolved_input_runtime_sha256 != RESOLVED_INPUT_RUNTIME_SHA256
        || !valid_sha256(&plan.segment_semantic_contract_sha256)
    {
        return Err(ObservationPlanError(
            "observation-plan contract digest drift".to_owned(),
        ));
    }
    let scope = plan
        .call_scope
        .as_ref()
        .and_then(|scope| scope.scope.as_ref())
        .ok_or_else(|| ObservationPlanError("observation-plan call scope is missing".to_owned()))?;
    match scope {
        Scope::Eip1898Hash(hash) if hash == &plan.block_hash && hash.len() == 32 => {}
        Scope::BlockNumberFallback(number) if *number == plan.block_number => {}
        Scope::Eip1898Hash(_) | Scope::BlockNumberFallback(_) => {
            return Err(ObservationPlanError("observation-plan call scope drift".to_owned()));
        }
    }
    let semantics = select_semantics_from_identity(
        &plan.network,
        plan.block_number,
        &plan.segment_id,
        &plan.segment_semantic_contract_sha256,
    )?;
    if semantics.npm_profile_id != plan.npm_profile_id {
        return Err(ObservationPlanError("observation-plan NPM profile drift".to_owned()));
    }
    validate_position_requests(&plan.position_requests, semantics.position_manager)?;
    validate_pool_requests(&plan.pool_requests, semantics.factory)?;
    validate_token_requests(&plan.token_requests)
}

fn validate_position_requests(requests: &[PositionRequest], manager: Address) -> Result<(), ObservationPlanError> {
    let mut previous: Option<PositionKey> = None;
    for request in requests {
        let key = (
            exact_array::<20>("planned position manager", &request.position_manager)?,
            exact_array::<32>("planned position token id", &request.token_id)?,
        );
        if key.0 != manager
            || previous.is_some_and(|prior| prior >= key)
            || request.reason_mask & (POSITION_REASON_IDENTITY | POSITION_REASON_FULL_ENVELOPE)
                != POSITION_REASON_IDENTITY | POSITION_REASON_FULL_ENVELOPE
            || request.reason_mask & !POSITION_REASON_MASK != 0
        {
            return Err(ObservationPlanError("position request contract drift".to_owned()));
        }
        validate_ordinals(&request.event_ordinals, "position request")?;
        if request.expected_consumption_count != 1 {
            return Err(ObservationPlanError("position request multiplicity drift".to_owned()));
        }
        previous = Some(key);
    }
    Ok(())
}

fn validate_pool_requests(requests: &[PoolRequest], factory: Address) -> Result<(), ObservationPlanError> {
    let mut previous: Option<PoolKey> = None;
    for request in requests {
        let key = (
            exact_array::<20>("planned pool factory", &request.factory)?,
            exact_array::<20>("planned pool token0", &request.token0)?,
            exact_array::<20>("planned pool token1", &request.token1)?,
            request.fee,
        );
        if key.0 != factory
            || previous.is_some_and(|prior| prior >= key)
            || request.reason_mask != POOL_REASON_PROVISIONAL_IDENTITY | POOL_REASON_FULL_ENVELOPE
            || request.reason_mask & !POOL_REASON_MASK != 0
            || request.fee > 0x00ff_ffff
        {
            return Err(ObservationPlanError("pool request contract drift".to_owned()));
        }
        validate_ordinals(&request.event_ordinals, "pool request")?;
        if request.expected_consumption_count != 1 {
            return Err(ObservationPlanError("pool request multiplicity drift".to_owned()));
        }
        previous = Some(key);
    }
    Ok(())
}

fn validate_token_requests(requests: &[TokenRequest]) -> Result<(), ObservationPlanError> {
    let mut previous: Option<TokenKey> = None;
    for request in requests {
        let key = (
            request.ordinal,
            exact_array::<20>("planned Token address", &request.address)?,
        );
        let role_count = u32::from(request.reason_mask & TOKEN_REASON_TOKEN0_SCALE != 0)
            + u32::from(request.reason_mask & TOKEN_REASON_TOKEN1_SCALE != 0);
        if previous.is_some_and(|prior| prior >= key)
            || request.expected_consumption_count != role_count
            || request.reason_mask & TOKEN_REASON_FULL_ENVELOPE == 0
            || request.reason_mask & !TOKEN_REASON_MASK != 0
        {
            return Err(ObservationPlanError("Token request contract drift".to_owned()));
        }
        previous = Some(key);
    }
    Ok(())
}

fn validate_ordinals(ordinals: &[u64], name: &str) -> Result<(), ObservationPlanError> {
    if ordinals.is_empty() || ordinals.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(ObservationPlanError(format!(
            "{name} ordinals are empty, duplicate, or unsorted"
        )));
    }
    Ok(())
}

fn require_exact_position_keys(
    expected: &[PositionRequest],
    actual: &[PositionObservation],
) -> Result<(), ObservationPlanError> {
    let actual_len = actual.len();
    let expected = expected
        .iter()
        .map(|request| {
            Ok((
                exact_array::<20>("planned position manager", &request.position_manager)?,
                exact_array::<32>("planned position token id", &request.token_id)?,
            ))
        })
        .collect::<Result<BTreeSet<_>, ObservationPlanError>>()?;
    let actual = actual
        .iter()
        .map(|observation| {
            Ok((
                exact_array::<20>("resolved position manager", &observation.position_manager)?,
                exact_array::<32>("resolved position token id", &observation.token_id)?,
            ))
        })
        .collect::<Result<BTreeSet<_>, ObservationPlanError>>()?;
    if expected != actual || actual_len != expected.len() {
        return Err(ObservationPlanError(
            "resolved Position keys do not exactly equal the plan".to_owned(),
        ));
    }
    Ok(())
}

fn require_exact_pool_keys(
    expected: &[PoolRequest],
    actual: &[crate::npm_inputs_pb::PoolObservation],
) -> Result<(), ObservationPlanError> {
    let actual_len = actual.len();
    let expected = expected
        .iter()
        .map(|request| {
            Ok((
                exact_array::<20>("planned pool factory", &request.factory)?,
                exact_array::<20>("planned pool token0", &request.token0)?,
                exact_array::<20>("planned pool token1", &request.token1)?,
                request.fee,
            ))
        })
        .collect::<Result<BTreeSet<_>, ObservationPlanError>>()?;
    let actual = actual
        .iter()
        .map(|observation| {
            Ok((
                exact_array::<20>("resolved pool factory", &observation.factory)?,
                exact_array::<20>("resolved pool token0", &observation.token0)?,
                exact_array::<20>("resolved pool token1", &observation.token1)?,
                observation.fee,
            ))
        })
        .collect::<Result<BTreeSet<_>, ObservationPlanError>>()?;
    if expected != actual || actual_len != expected.len() {
        return Err(ObservationPlanError(
            "resolved Pool keys do not exactly equal the plan".to_owned(),
        ));
    }
    Ok(())
}

fn require_exact_token_keys(
    expected: &[TokenRequest],
    actual: &[crate::npm_inputs_pb::TokenObservation],
) -> Result<(), ObservationPlanError> {
    let actual_len = actual.len();
    let expected = expected
        .iter()
        .map(|request| {
            Ok((
                request.ordinal,
                exact_array::<20>("planned Token address", &request.address)?,
            ))
        })
        .collect::<Result<BTreeSet<_>, ObservationPlanError>>()?;
    let actual = actual
        .iter()
        .map(|observation| {
            Ok((
                observation.ordinal,
                exact_array::<20>("resolved Token address", &observation.address)?,
            ))
        })
        .collect::<Result<BTreeSet<_>, ObservationPlanError>>()?;
    if expected != actual || actual_len != expected.len() {
        return Err(ObservationPlanError(
            "resolved Token keys do not exactly equal the plan".to_owned(),
        ));
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ResolvedPositionValue {
    token0: Address,
    token1: Address,
    fee: u32,
}

fn normalized_position_values(
    positions: &[PositionObservation],
) -> Result<BTreeMap<PositionKey, Option<ResolvedPositionValue>>, ObservationPlanError> {
    positions
        .iter()
        .map(|position| {
            let key = (
                exact_array::<20>("position manager", &position.position_manager)?,
                exact_array::<32>("position token id", &position.token_id)?,
            );
            let value = match position
                .result
                .as_ref()
                .ok_or_else(|| ObservationPlanError("position result is missing".to_owned()))?
            {
                PositionResult::None(_) => None,
                PositionResult::Value(value) => Some(ResolvedPositionValue {
                    token0: exact_array::<20>("position token0", &value.token0)?,
                    token1: exact_array::<20>("position token1", &value.token1)?,
                    fee: value.fee,
                }),
            };
            Ok((key, value))
        })
        .collect()
}

fn coverage_audit(
    plan: &NpmObservationPlan,
    frame: &NpmResolvedInputs,
    consumption: &InputConsumption,
) -> Result<CoverageAudit, ObservationPlanError> {
    require_exact_position_keys(&plan.position_requests, &frame.position_calls)?;
    require_exact_pool_keys(&plan.pool_requests, &frame.pool_calls)?;
    require_exact_token_keys(&plan.token_requests, &frame.token_reads)?;
    let position_limits = plan
        .position_requests
        .iter()
        .map(|request| {
            Ok((
                (
                    exact_array::<20>("planned position manager", &request.position_manager)?,
                    exact_array::<32>("planned position token id", &request.token_id)?,
                ),
                request.expected_consumption_count as usize,
            ))
        })
        .collect::<Result<BTreeMap<_, _>, ObservationPlanError>>()?;
    let pool_limits = plan
        .pool_requests
        .iter()
        .map(|request| {
            Ok((
                (
                    exact_array::<20>("planned pool factory", &request.factory)?,
                    exact_array::<20>("planned pool token0", &request.token0)?,
                    exact_array::<20>("planned pool token1", &request.token1)?,
                    request.fee,
                ),
                request.expected_consumption_count as usize,
            ))
        })
        .collect::<Result<BTreeMap<_, _>, ObservationPlanError>>()?;
    let token_limits = plan
        .token_requests
        .iter()
        .map(|request| {
            Ok((
                (
                    request.ordinal,
                    exact_array::<20>("planned Token address", &request.address)?,
                ),
                request.expected_consumption_count as usize,
            ))
        })
        .collect::<Result<BTreeMap<_, _>, ObservationPlanError>>()?;
    ensure_consumed_subset("Position", &consumption.position_requests, &position_limits)?;
    ensure_consumed_subset("Pool", &consumption.pool_requests, &pool_limits)?;
    ensure_consumed_subset("Token", &consumption.token_requests, &token_limits)?;
    Ok(CoverageAudit {
        planned_position_keys: plan.position_requests.len(),
        planned_pool_keys: plan.pool_requests.len(),
        planned_token_keys: plan.token_requests.len(),
        resolved_position_keys: frame.position_calls.len(),
        resolved_pool_keys: frame.pool_calls.len(),
        resolved_token_keys: frame.token_reads.len(),
        consumed_position_calls: consumption.position_requests.values().sum(),
        consumed_pool_calls: consumption.pool_requests.values().sum(),
        consumed_token_reads: consumption.token_requests.values().sum(),
        unconsumed_position_keys: position_limits
            .keys()
            .filter(|key| !consumption.position_requests.contains_key(key))
            .count(),
        unconsumed_pool_keys: pool_limits
            .keys()
            .filter(|key| !consumption.pool_requests.contains_key(key))
            .count(),
        unconsumed_token_keys: token_limits
            .keys()
            .filter(|key| !consumption.token_requests.contains_key(key))
            .count(),
    })
}

#[cfg(test)]
pub(crate) fn coverage_audit_for_test(
    plan: &NpmObservationPlan,
    frame: &NpmResolvedInputs,
    consumption: &InputConsumption,
) -> Result<CoverageAudit, ObservationPlanError> {
    coverage_audit(plan, frame, consumption)
}

fn ensure_consumed_subset<K: Ord + fmt::Debug>(
    name: &str,
    consumed: &BTreeMap<K, usize>,
    planned: &BTreeMap<K, usize>,
) -> Result<(), ObservationPlanError> {
    for (key, count) in consumed {
        let Some(limit) = planned.get(key) else {
            return Err(ObservationPlanError(format!(
                "{name} reducer consumed an unplanned key {key:?}"
            )));
        };
        if count > limit {
            return Err(ObservationPlanError(format!(
                "{name} reducer consumed key {key:?} {count} times; planned limit is {limit}"
            )));
        }
    }
    Ok(())
}

fn planning_state(
    initial: &ReducerState,
) -> Result<(BTreeMap<String, PlanningPosition>, [u8; 32]), ObservationPlanError> {
    let mut positions = BTreeMap::new();
    let mut words = BTreeSet::new();
    let mut hasher = Sha256::new();
    hasher.update(PLANNING_STATE_DOMAIN);
    hasher.update((initial.positions.len() as u64).to_be_bytes());
    for (key, position) in &initial.positions {
        if key != &position.token_id {
            return Err(ObservationPlanError(
                "planning state key/Position identity drift".to_owned(),
            ));
        }
        let word = canonical_token_word(key)?;
        if !words.insert(word) {
            return Err(ObservationPlanError(
                "planning state contains duplicate canonical token ids".to_owned(),
            ));
        }
        let key_len =
            u32::try_from(key.len()).map_err(|_| ObservationPlanError("planning token id is too long".to_owned()))?;
        hasher.update(key_len.to_be_bytes());
        hasher.update(key.as_bytes());
        hasher.update(word);
        hasher.update(position.pool);
        hasher.update(position.token0);
        hasher.update(position.token1);
        positions.insert(
            key.clone(),
            PlanningPosition {
                token0: position.token0,
                token1: position.token1,
            },
        );
    }
    Ok((positions, hasher.finalize().into()))
}

fn validate_call_scope(source: &NpmSourceBlock, scope: &CapturedCallScope) -> Result<(), ObservationPlanError> {
    let block = source.block.as_ref().expect("validated source block");
    match scope {
        CapturedCallScope::Eip1898Hash(hash) if hash == &block.hash && hash.len() == 32 => Ok(()),
        CapturedCallScope::BlockNumberFallback(number) if *number == block.number => Ok(()),
        CapturedCallScope::Eip1898Hash(_) | CapturedCallScope::BlockNumberFallback(_) => Err(ObservationPlanError(
            "planning call scope does not match source block".to_owned(),
        )),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum EventKind {
    Increase,
    Decrease,
    Collect,
    Transfer,
}

fn event_identity(event: &WriterEvent) -> Result<(EventKind, String), ObservationPlanError> {
    let (kind, token_id) = match event
        .event
        .as_ref()
        .ok_or_else(|| ObservationPlanError("planned WriterEvent payload is missing".to_owned()))?
    {
        Event::IncreaseLiquidity(value) => (EventKind::Increase, value.token_id.clone()),
        Event::DecreaseLiquidity(value) => (EventKind::Decrease, value.token_id.clone()),
        Event::Collect(value) => (EventKind::Collect, value.token_id.clone()),
        Event::Transfer(value) => (EventKind::Transfer, value.token_id.clone()),
    };
    canonical_token_word(&token_id)?;
    Ok((kind, token_id))
}

fn canonical_token_word(value: &str) -> Result<[u8; 32], ObservationPlanError> {
    if value.is_empty()
        || !value.bytes().all(|byte| byte.is_ascii_digit())
        || (value.len() > 1 && value.starts_with('0'))
    {
        return Err(ObservationPlanError(format!(
            "token id `{value}` is not canonical unsigned decimal"
        )));
    }
    let value = BigUint::parse_bytes(value.as_bytes(), 10)
        .ok_or_else(|| ObservationPlanError(format!("invalid token id `{value}`")))?;
    let bytes = value.to_bytes_be();
    if bytes.len() > 32 {
        return Err(ObservationPlanError(format!("token id `{value}` exceeds uint256")));
    }
    let mut output = [0_u8; 32];
    output[32 - bytes.len()..].copy_from_slice(&bytes);
    Ok(output)
}

fn select_semantics(source: &NpmSourceBlock) -> Result<SelectedSemantics, ObservationPlanError> {
    let events = source.writer_events.as_ref().expect("validated source events");
    let block = source.block.as_ref().expect("validated source block");
    select_semantics_from_identity(
        &events.network,
        block.number,
        &events.segment_id,
        &events.segment_semantic_contract_sha256,
    )
}

fn select_semantics_from_identity(
    network: &str,
    block_number: u64,
    segment_id: &str,
    segment_semantic_contract_sha256: &str,
) -> Result<SelectedSemantics, ObservationPlanError> {
    let raw = include_str!("../configs/npm-handler-reducer-v1.json");
    if hex::encode(Sha256::digest(raw.as_bytes())) != NPM_HANDLER_REDUCER_SEMANTICS_SHA256 {
        return Err(ObservationPlanError("joint reducer semantic digest drift".to_owned()));
    }
    let contract: Value = serde_json::from_str(raw)
        .map_err(|error| ObservationPlanError(format!("invalid joint reducer semantics: {error}")))?;
    let network_contracts = contract
        .get("network_contracts")
        .and_then(Value::as_array)
        .ok_or_else(|| ObservationPlanError("joint reducer network contracts missing".to_owned()))?;
    let network_contract = network_contracts
        .iter()
        .find(|item| item.get("network").and_then(Value::as_str) == Some(network))
        .ok_or_else(|| ObservationPlanError(format!("unsupported planning network `{network}`")))?;
    let position_manager = decode_address(
        "position manager",
        network_contract
            .get("nonfungible_position_manager")
            .and_then(Value::as_str)
            .ok_or_else(|| ObservationPlanError("position manager contract missing".to_owned()))?,
    )?;
    let factory = decode_address(
        "factory",
        network_contract
            .get("factory")
            .and_then(Value::as_str)
            .ok_or_else(|| ObservationPlanError("factory contract missing".to_owned()))?,
    )?;
    let segments = contract
        .get("segments")
        .and_then(Value::as_array)
        .ok_or_else(|| ObservationPlanError("joint reducer segments missing".to_owned()))?;
    let matches = segments
        .iter()
        .filter(|segment| {
            segment.get("network").and_then(Value::as_str) == Some(network)
                && segment
                    .get("start_block_inclusive")
                    .and_then(Value::as_u64)
                    .is_some_and(|start| start <= block_number)
        })
        .filter(|segment| {
            segment
                .get("end_block_inclusive")
                .and_then(Value::as_u64)
                .map_or(true, |end| block_number <= end)
        })
        .collect::<Vec<_>>();
    if matches.len() != 1 {
        return Err(ObservationPlanError(format!(
            "expected one planning segment for {network} block {block_number}, found {}",
            matches.len()
        )));
    }
    let segment = matches[0];
    if segment.get("segment_id").and_then(Value::as_str) != Some(segment_id)
        || segment.get("semantic_contract_sha256").and_then(Value::as_str) != Some(segment_semantic_contract_sha256)
    {
        return Err(ObservationPlanError("planning segment binding drift".to_owned()));
    }
    let npm_profile_id = segment
        .get("npm_profile_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ObservationPlanError("planning NPM profile id missing".to_owned()))?;
    let profiles = contract
        .get("npm_profiles")
        .and_then(Value::as_array)
        .ok_or_else(|| ObservationPlanError("joint reducer NPM profiles missing".to_owned()))?;
    let profile = profiles
        .iter()
        .find(|item| item.get("profile_id").and_then(Value::as_str) == Some(npm_profile_id))
        .ok_or_else(|| ObservationPlanError(format!("unknown planning NPM profile `{npm_profile_id}`")))?;
    let collect_token_reads = profile
        .get("collect_token_reads")
        .and_then(Value::as_array)
        .ok_or_else(|| ObservationPlanError("collect Token-read profile missing".to_owned()))?
        .iter()
        .map(|value| match value.as_str() {
            Some("token0") => Ok(TokenRole::Token0),
            Some("token1") => Ok(TokenRole::Token1),
            other => Err(ObservationPlanError(format!("unknown collect Token role {other:?}"))),
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(SelectedSemantics {
        npm_profile_id: npm_profile_id.to_owned(),
        position_manager,
        factory,
        collect_token_reads,
    })
}

fn verify_plan_contract() -> Result<(), ObservationPlanError> {
    let raw = include_str!("../configs/npm-observation-plan-v1.json");
    if hex::encode(Sha256::digest(raw.as_bytes())) != PLAN_SEMANTICS_SHA256 {
        return Err(ObservationPlanError(
            "observation-plan semantic digest drift".to_owned(),
        ));
    }
    let contract: Value = serde_json::from_str(raw)
        .map_err(|error| ObservationPlanError(format!("invalid observation-plan semantics: {error}")))?;
    let string = |key: &str| contract.get(key).and_then(Value::as_str);
    if contract.get("format_version").and_then(Value::as_u64) != Some(1)
        || string("contract_version") != Some("uniswap-v3-npm-observation-plan/v1")
        || string("mode") != Some("host-diagnostic-only")
        || string("source_resolved_input_runtime_sha256") != Some(RESOLVED_INPUT_RUNTIME_SHA256)
        || string("source_resolved_input_semantics_sha256") != Some(RESOLVED_INPUT_SEMANTICS_SHA256)
        || string("source_npm_source_runtime_sha256") != Some(NPM_SOURCE_RUNTIME_SHA256)
        || string("source_npm_handler_reducer_runtime_sha256") != Some(NPM_HANDLER_REDUCER_RUNTIME_SHA256)
        || string("source_npm_handler_reducer_semantics_sha256") != Some(NPM_HANDLER_REDUCER_SEMANTICS_SHA256)
        || string("source_writer_runtime_sha256") != Some(WRITER_RUNTIME_SHA256)
        || string("source_writer_profiles_sha256") != Some(WRITER_PROFILE_SHA256)
        || string("source_writer_compatibility_sha256") != Some(WRITER_COMPATIBILITY_SHA256)
        || string("source_segment_matrix_sha256") != Some(SEGMENT_MATRIX_SHA256)
        || string("source_execution_order_sha256") != Some(EXECUTION_ORDER_SHA256)
    {
        return Err(ObservationPlanError(
            "observation-plan semantic binding drift".to_owned(),
        ));
    }
    let truth = contract
        .get("truth_boundary")
        .and_then(Value::as_object)
        .ok_or_else(|| ObservationPlanError("observation-plan truth boundary missing".to_owned()))?;
    for key in [
        "integrated_provider_executor_added",
        "all_required_observations_evaluated",
        "exact_graph_call_trace_complete",
        "post_fatal_execution_modeled",
        "graph_execution_trace_complete",
        "factory_pool_combined_schedule_implemented",
        "dynamic_datasource_stage_order_implemented",
        "entity_changes_or_block_changes_implemented",
        "checkpoint_or_graph_block_success_authorized",
        "boundary_state_continuity_complete",
        "physical_parity_complete",
        "poi_parity_complete",
        "backfill_ready",
        "production_ready",
    ] {
        if truth.get(key).and_then(Value::as_bool) != Some(false) {
            return Err(ObservationPlanError(format!(
                "observation-plan false truth gate `{key}` drift"
            )));
        }
    }
    for key in [
        "host_observation_plan_implemented",
        "complete_conservative_npm_request_closure",
        "post_fatal_writer_event_suffix_in_plan",
        "exact_plan_resolved_frame_key_equality_enforced",
        "all_planned_rows_resolved_before_certified_reducer_path",
        "all_eight_npm_segment_profiles_bound",
    ] {
        if truth.get(key).and_then(Value::as_bool) != Some(true) {
            return Err(ObservationPlanError(format!(
                "observation-plan true truth gate `{key}` drift"
            )));
        }
    }
    Ok(())
}

fn decode_address(field: &str, value: &str) -> Result<Address, ObservationPlanError> {
    let value = value.strip_prefix("0x").unwrap_or(value);
    let bytes =
        hex::decode(value).map_err(|error| ObservationPlanError(format!("invalid {field} address: {error}")))?;
    exact_array::<20>(field, &bytes)
}

fn exact_array<const N: usize>(field: &str, bytes: &[u8]) -> Result<[u8; N], ObservationPlanError> {
    bytes
        .try_into()
        .map_err(|_| ObservationPlanError(format!("{field} must be exactly {N} bytes")))
}

fn sha256(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

#[derive(Default)]
struct RequestAccumulator {
    ordinals: BTreeSet<u64>,
    reason_mask: u32,
}

#[derive(Default)]
struct TokenAccumulator {
    reason_mask: u32,
    expected_consumption_count: u32,
}
