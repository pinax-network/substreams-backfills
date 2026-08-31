//! Hermetic host executor for the conservative NPM observation plan.
//!
//! Provider payloads are transient. The returned audit is a canonical
//! conservative request-evaluation trace, not an exact Graph call trace.

use std::fmt;

use sha2::{Digest, Sha256};

use crate::npm_handler_reducer::{BlockReduction, ReducerState};
use crate::npm_observation_plan::{
    complete_observation_plan, plan_position_observations, preflight_resolved_frame, reduce_preflighted_npm_frame,
    CoverageAudit,
};
use crate::npm_plan_pb::{PoolRequest, PositionRequest, TokenRequest};
use crate::npm_resolved_inputs::{
    CapturedCallScope, CapturedPoolObservation, CapturedPoolResult, CapturedPositionObservation,
    CapturedPositionResult, CapturedTokenObservation, CapturedTokenResult, Gated,
};
use crate::pb::npm_source::NpmSourceBlock;

pub const EXECUTOR_SEMANTICS_SHA256: &str = "42be28917cbd73c84911084e17e0869f9655c16a4cec50c8a636aa7b9f021bbe";
pub const OBSERVATION_PLAN_RUNTIME_SHA256: &str = "8cd45b0c31994332e75bd25ccd515d961fe0de9d93ac30874f5a17c0f35b6c10";
pub const OBSERVATION_PLAN_SEMANTICS_SHA256: &str = "2d305149664b4c1e83d31a21a4131e585e44f8f25636d311ff741b9c437eaa3f";
pub const SELECTED_FIELD_SEMANTICS_V1_SHA256: &str = "4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e";
pub const TRACE_KIND: &str = "canonical conservative request-evaluation trace";
const AUDIT_DOMAIN: &[u8] = b"uniswap-v3-npm-provider-executor-audit/v1\0";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProviderAuthority {
    HermeticFixture,
    ExternalLive,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProviderResolution<T> {
    Resolved(T),
    PossibleReorg,
    Unknown,
}

pub trait NpmObservationProvider {
    type Error;

    fn authority(&self) -> ProviderAuthority;

    fn resolve_position(
        &mut self,
        scope: &CapturedCallScope,
        request: &PositionRequest,
    ) -> Result<ProviderResolution<CapturedPositionResult>, Self::Error>;

    fn resolve_pool(
        &mut self,
        scope: &CapturedCallScope,
        request: &PoolRequest,
    ) -> Result<ProviderResolution<CapturedPoolResult>, Self::Error>;

    fn resolve_token(
        &mut self,
        scope: &CapturedCallScope,
        request: &TokenRequest,
    ) -> Result<ProviderResolution<CapturedTokenResult>, Self::Error>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EvaluationPhase {
    CallScope,
    Position,
    Pool,
    Token,
    Preflight,
    Reduction,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExecutionErrorKind {
    ContractDrift,
    AuthorityRefused,
    InvalidInput,
    ProviderError,
    PossibleReorg,
    Unknown,
    PreflightRejected,
    ReductionRejected,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderExecutionError {
    pub kind: ExecutionErrorKind,
    pub phase: EvaluationPhase,
    pub request_index: Option<usize>,
}

impl fmt::Display for ProviderExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self.kind {
            ExecutionErrorKind::ContractDrift => "executor contract rejected",
            ExecutionErrorKind::AuthorityRefused => "provider authority refused",
            ExecutionErrorKind::InvalidInput => "executor input rejected",
            ExecutionErrorKind::ProviderError => "provider evaluation failed",
            ExecutionErrorKind::PossibleReorg => "provider evaluation is reorg-unstable",
            ExecutionErrorKind::Unknown => "provider evaluation is unresolved",
            ExecutionErrorKind::PreflightRejected => "closed-frame preflight rejected",
            ExecutionErrorKind::ReductionRejected => "certified reduction rejected",
        };
        match self.request_index {
            Some(index) => write!(
                formatter,
                "{label} in {:?} phase at canonical request {index}",
                self.phase
            ),
            None => write!(formatter, "{label} in {:?} phase", self.phase),
        }
    }
}

impl std::error::Error for ProviderExecutionError {}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CanonicalRequestKey {
    Position {
        position_manager: [u8; 20],
        token_id: [u8; 32],
    },
    Pool {
        factory: [u8; 20],
        token0: [u8; 20],
        token1: [u8; 20],
        fee: u32,
    },
    Token {
        ordinal: u64,
        address: [u8; 20],
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResolvedResultClass {
    PositionValue,
    PositionNone,
    PoolValue,
    PoolNone,
    TokenFound,
    TokenMissing,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RequestEvaluation {
    pub phase: EvaluationPhase,
    pub canonical_index: usize,
    pub key: CanonicalRequestKey,
    pub result: ResolvedResultClass,
    pub reason_mask: u32,
    pub expected_consumption_count: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObservationExecutionAudit {
    pub trace_kind: &'static str,
    pub source_frame_sha256: [u8; 32],
    pub planning_state_sha256: [u8; 32],
    pub block_number: u64,
    pub block_hash: [u8; 32],
    pub call_scope: CapturedCallScope,
    pub segment_id: String,
    pub npm_profile_id: String,
    pub evaluations: Vec<RequestEvaluation>,
    pub coverage: CoverageAudit,
    pub canonical_sha256: [u8; 32],
}

impl ObservationExecutionAudit {
    pub fn is_canonical(&self) -> bool {
        canonical_audit_sha256(self) == self.canonical_sha256
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ProviderExecution {
    pub reduction: BlockReduction,
    pub audit: ObservationExecutionAudit,
}

pub fn execute_npm_provider<P: NpmObservationProvider>(
    source: &NpmSourceBlock,
    initial: &ReducerState,
    call_scope: Gated<CapturedCallScope>,
    provider: &mut P,
) -> Result<ProviderExecution, ProviderExecutionError> {
    verify_executor_contract()?;
    if provider.authority() != ProviderAuthority::HermeticFixture {
        return Err(error(
            ExecutionErrorKind::AuthorityRefused,
            EvaluationPhase::CallScope,
            None,
        ));
    }
    let mut scope_copy = call_scope.clone();
    let scope = scope_copy
        .resolved_value_mut()
        .cloned()
        .ok_or_else(|| error(ExecutionErrorKind::InvalidInput, EvaluationPhase::CallScope, None))?;
    let position_phase = plan_position_observations(source, initial, call_scope)
        .map_err(|_| error(ExecutionErrorKind::InvalidInput, EvaluationPhase::Position, None))?;
    let position_requests = position_phase.requests().to_vec();
    let mut evaluations = Vec::new();
    let mut positions = Vec::with_capacity(position_requests.len());
    for (index, request) in position_requests.iter().enumerate() {
        let result = resolve(
            provider.resolve_position(&scope, request),
            EvaluationPhase::Position,
            index,
        )?;
        evaluations.push(position_evaluation(index, request, &result)?);
        positions.push(Gated::resolved(CapturedPositionObservation {
            position_manager: request.position_manager.clone(),
            token_id: request.token_id.clone(),
            result,
        }));
    }
    let complete = complete_observation_plan(position_phase, positions)
        .map_err(|_| error(ExecutionErrorKind::PreflightRejected, EvaluationPhase::Position, None))?;
    let plan = complete.plan().clone();
    let mut pools = Vec::with_capacity(plan.pool_requests.len());
    for (index, request) in plan.pool_requests.iter().enumerate() {
        let result = resolve(provider.resolve_pool(&scope, request), EvaluationPhase::Pool, index)?;
        evaluations.push(pool_evaluation(index, request, &result)?);
        pools.push(Gated::resolved(CapturedPoolObservation {
            factory: request.factory.clone(),
            token0: request.token0.clone(),
            token1: request.token1.clone(),
            fee: request.fee,
            result,
        }));
    }
    let mut tokens = Vec::with_capacity(plan.token_requests.len());
    for (index, request) in plan.token_requests.iter().enumerate() {
        let result = resolve(provider.resolve_token(&scope, request), EvaluationPhase::Token, index)?;
        evaluations.push(token_evaluation(index, request, &result)?);
        tokens.push(Gated::resolved(CapturedTokenObservation {
            address: request.address.clone(),
            ordinal: request.ordinal,
            result,
        }));
    }
    let preflighted = preflight_resolved_frame(complete, pools, tokens)
        .map_err(|_| error(ExecutionErrorKind::PreflightRejected, EvaluationPhase::Preflight, None))?;
    let (reduction, coverage) = reduce_preflighted_npm_frame(initial, preflighted)
        .map_err(|_| error(ExecutionErrorKind::ReductionRejected, EvaluationPhase::Reduction, None))?;
    let mut audit = ObservationExecutionAudit {
        trace_kind: TRACE_KIND,
        source_frame_sha256: exact_array(&plan.source_frame_sha256, EvaluationPhase::Preflight)?,
        planning_state_sha256: exact_array(&plan.planning_state_sha256, EvaluationPhase::Preflight)?,
        block_number: plan.block_number,
        block_hash: exact_array(&plan.block_hash, EvaluationPhase::Preflight)?,
        call_scope: scope,
        segment_id: plan.segment_id,
        npm_profile_id: plan.npm_profile_id,
        evaluations,
        coverage,
        canonical_sha256: [0; 32],
    };
    audit.canonical_sha256 = canonical_audit_sha256(&audit);
    Ok(ProviderExecution { reduction, audit })
}

fn resolve<T, E>(
    result: Result<ProviderResolution<T>, E>,
    phase: EvaluationPhase,
    index: usize,
) -> Result<T, ProviderExecutionError> {
    match result {
        Ok(ProviderResolution::Resolved(value)) => Ok(value),
        Ok(ProviderResolution::PossibleReorg) => Err(error(ExecutionErrorKind::PossibleReorg, phase, Some(index))),
        Ok(ProviderResolution::Unknown) => Err(error(ExecutionErrorKind::Unknown, phase, Some(index))),
        Err(_) => Err(error(ExecutionErrorKind::ProviderError, phase, Some(index))),
    }
}

fn position_evaluation(
    index: usize,
    request: &PositionRequest,
    result: &CapturedPositionResult,
) -> Result<RequestEvaluation, ProviderExecutionError> {
    Ok(RequestEvaluation {
        phase: EvaluationPhase::Position,
        canonical_index: index,
        key: CanonicalRequestKey::Position {
            position_manager: exact_array(&request.position_manager, EvaluationPhase::Position)?,
            token_id: exact_array(&request.token_id, EvaluationPhase::Position)?,
        },
        result: match result {
            CapturedPositionResult::Value(_) => ResolvedResultClass::PositionValue,
            CapturedPositionResult::None => ResolvedResultClass::PositionNone,
        },
        reason_mask: request.reason_mask,
        expected_consumption_count: request.expected_consumption_count,
    })
}

fn pool_evaluation(
    index: usize,
    request: &PoolRequest,
    result: &CapturedPoolResult,
) -> Result<RequestEvaluation, ProviderExecutionError> {
    Ok(RequestEvaluation {
        phase: EvaluationPhase::Pool,
        canonical_index: index,
        key: CanonicalRequestKey::Pool {
            factory: exact_array(&request.factory, EvaluationPhase::Pool)?,
            token0: exact_array(&request.token0, EvaluationPhase::Pool)?,
            token1: exact_array(&request.token1, EvaluationPhase::Pool)?,
            fee: request.fee,
        },
        result: match result {
            CapturedPoolResult::Value(_) => ResolvedResultClass::PoolValue,
            CapturedPoolResult::None => ResolvedResultClass::PoolNone,
        },
        reason_mask: request.reason_mask,
        expected_consumption_count: request.expected_consumption_count,
    })
}

fn token_evaluation(
    index: usize,
    request: &TokenRequest,
    result: &CapturedTokenResult,
) -> Result<RequestEvaluation, ProviderExecutionError> {
    Ok(RequestEvaluation {
        phase: EvaluationPhase::Token,
        canonical_index: index,
        key: CanonicalRequestKey::Token {
            ordinal: request.ordinal,
            address: exact_array(&request.address, EvaluationPhase::Token)?,
        },
        result: match result {
            CapturedTokenResult::Found(_) => ResolvedResultClass::TokenFound,
            CapturedTokenResult::Missing => ResolvedResultClass::TokenMissing,
        },
        reason_mask: request.reason_mask,
        expected_consumption_count: request.expected_consumption_count,
    })
}

fn exact_array<const N: usize>(bytes: &[u8], phase: EvaluationPhase) -> Result<[u8; N], ProviderExecutionError> {
    bytes
        .try_into()
        .map_err(|_| error(ExecutionErrorKind::PreflightRejected, phase, None))
}

fn error(kind: ExecutionErrorKind, phase: EvaluationPhase, request_index: Option<usize>) -> ProviderExecutionError {
    ProviderExecutionError {
        kind,
        phase,
        request_index,
    }
}

fn verify_executor_contract() -> Result<(), ProviderExecutionError> {
    let raw = include_str!("../configs/npm-provider-executor-v1.json");
    if hex::encode(Sha256::digest(raw.as_bytes())) != EXECUTOR_SEMANTICS_SHA256 {
        return Err(error(
            ExecutionErrorKind::ContractDrift,
            EvaluationPhase::CallScope,
            None,
        ));
    }
    if crate::npm_observation_plan::PLAN_SEMANTICS_SHA256 != OBSERVATION_PLAN_SEMANTICS_SHA256 {
        return Err(error(
            ExecutionErrorKind::ContractDrift,
            EvaluationPhase::CallScope,
            None,
        ));
    }
    Ok(())
}

fn canonical_audit_sha256(audit: &ObservationExecutionAudit) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(AUDIT_DOMAIN);
    put_bytes(&mut hasher, audit.trace_kind.as_bytes());
    hasher.update(audit.source_frame_sha256);
    hasher.update(audit.planning_state_sha256);
    hasher.update(audit.block_number.to_be_bytes());
    hasher.update(audit.block_hash);
    match &audit.call_scope {
        CapturedCallScope::Eip1898Hash(hash) => {
            hasher.update([1]);
            put_bytes(&mut hasher, hash);
        }
        CapturedCallScope::BlockNumberFallback(number) => {
            hasher.update([2]);
            hasher.update(number.to_be_bytes());
        }
    }
    put_bytes(&mut hasher, audit.segment_id.as_bytes());
    put_bytes(&mut hasher, audit.npm_profile_id.as_bytes());
    hasher.update((audit.evaluations.len() as u64).to_be_bytes());
    for evaluation in &audit.evaluations {
        hasher.update([phase_tag(evaluation.phase)]);
        hasher.update((evaluation.canonical_index as u64).to_be_bytes());
        match &evaluation.key {
            CanonicalRequestKey::Position {
                position_manager,
                token_id,
            } => {
                hasher.update([1]);
                hasher.update(position_manager);
                hasher.update(token_id);
            }
            CanonicalRequestKey::Pool {
                factory,
                token0,
                token1,
                fee,
            } => {
                hasher.update([2]);
                hasher.update(factory);
                hasher.update(token0);
                hasher.update(token1);
                hasher.update(fee.to_be_bytes());
            }
            CanonicalRequestKey::Token { ordinal, address } => {
                hasher.update([3]);
                hasher.update(ordinal.to_be_bytes());
                hasher.update(address);
            }
        }
        hasher.update([result_tag(evaluation.result)]);
        hasher.update(evaluation.reason_mask.to_be_bytes());
        hasher.update(evaluation.expected_consumption_count.to_be_bytes());
    }
    for value in [
        audit.coverage.planned_position_keys,
        audit.coverage.planned_pool_keys,
        audit.coverage.planned_token_keys,
        audit.coverage.resolved_position_keys,
        audit.coverage.resolved_pool_keys,
        audit.coverage.resolved_token_keys,
        audit.coverage.consumed_position_calls,
        audit.coverage.consumed_pool_calls,
        audit.coverage.consumed_token_reads,
        audit.coverage.unconsumed_position_keys,
        audit.coverage.unconsumed_pool_keys,
        audit.coverage.unconsumed_token_keys,
    ] {
        hasher.update((value as u64).to_be_bytes());
    }
    hasher.finalize().into()
}

fn put_bytes(hasher: &mut Sha256, value: &[u8]) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value);
}

fn phase_tag(phase: EvaluationPhase) -> u8 {
    match phase {
        EvaluationPhase::CallScope => 0,
        EvaluationPhase::Position => 1,
        EvaluationPhase::Pool => 2,
        EvaluationPhase::Token => 3,
        EvaluationPhase::Preflight => 4,
        EvaluationPhase::Reduction => 5,
    }
}

fn result_tag(result: ResolvedResultClass) -> u8 {
    match result {
        ResolvedResultClass::PositionValue => 1,
        ResolvedResultClass::PositionNone => 2,
        ResolvedResultClass::PoolValue => 3,
        ResolvedResultClass::PoolNone => 4,
        ResolvedResultClass::TokenFound => 5,
        ResolvedResultClass::TokenMissing => 6,
    }
}
