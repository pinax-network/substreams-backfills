//! Host-only sequential Pool Flash reducer.
//!
//! This module intentionally has no Substreams handler, store, RPC client,
//! entity encoder, database access, or `graph_out` integration. Contract calls
//! are supplied by a hermetic trait so the reviewed Flash state transition can
//! be tested before any runtime application is designed or authorized. Its
//! ordered event envelope is a diagnostic input convention, not a Graph Node
//! dynamic-data-source stage-order implementation.

use std::collections::{BTreeMap, BTreeSet};

use num_bigint::BigUint;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use substreams::errors::Error;

const REDUCER_CONTRACT_SHA256: &str = "8951469c026898de69d1a76381539eda3ddfdf094051d2b4b7f4295c860dfa43";
const REDUCER_CONTRACT_VERSION: &str = "uniswap-v3-flash-reducer/v1";
const SOURCE_WRITER_CONTRACT_SHA256: &str = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4";
const SOURCE_PROFILE_SHA256: &str = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823";
const SOURCE_WRITER_RUNTIME_SHA256: &str = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca";
const WRITER_DESCRIPTOR_SHA256: &str = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0";
const SOURCE_EXECUTION_ORDER_CONTRACT_RAW_SHA256: &str =
    "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2";
const FEE_GROWTH_0_CALLDATA: [u8; 4] = [0xf3, 0x05, 0x83, 0x99];
const FEE_GROWTH_1_CALLDATA: [u8; 4] = [0x46, 0x14, 0x13, 0x19];
const FACTORY_REJECTED_POOL: Address = [
    0x8f, 0xe8, 0xd9, 0xbb, 0x8e, 0xeb, 0xa3, 0xed, 0x68, 0x80, 0x69, 0xc3, 0xd6, 0xb5, 0x56, 0xc9, 0xca, 0x25, 0x82,
    0x48,
];

pub type Address = [u8; 20];
pub type BlockHash = [u8; 32];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Pool {
    pub address: Address,
    pub fee_growth_global0_x128: BigUint,
    pub fee_growth_global1_x128: BigUint,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReducerState {
    /// Diagnostic-envelope-current Pool rows. Other Pool fields are
    /// intentionally outside this tranche and remain unchanged by every
    /// returned update.
    pub pools: BTreeMap<Address, Pool>,
    /// Membership under this reducer's diagnostic creation-ordinal convention;
    /// this is not Graph Node block-scoped dynamic-data-source activation.
    pub active_pool_datasources: BTreeSet<Address>,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct BlockScope {
    pub network: String,
    pub block_number: u64,
    pub block_hash: Option<BlockHash>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockContext {
    pub network: String,
    pub number: u64,
    pub hash: Option<BlockHash>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FlashPayload {
    pub sender: Address,
    pub recipient: Address,
    pub amount0: BigUint,
    pub amount1: BigUint,
    pub paid0: BigUint,
    pub paid1: BigUint,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PoolCreated {
    pub factory: Address,
    pub pool: Address,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Flash {
    pub pool: Address,
    /// Already-decoded event fields are carried only to prove that the
    /// deployed handler ignores them.
    pub payload: FlashPayload,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PoolEvent {
    PoolCreated(PoolCreated),
    Flash(Flash),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OrderedPoolEvent {
    pub ordinal: u64,
    pub block_number: u64,
    pub block_log_index: u32,
    pub event: PoolEvent,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FlashBlock {
    pub events: Vec<OrderedPoolEvent>,
    pub network: String,
    pub block_number: u64,
    pub segment_id: String,
    pub source_writer_contract_sha256: String,
    pub segment_semantic_contract_sha256: String,
}

/// Hermetic diagnostic call interface at the supplied block pointer. It is not
/// proof of Graph Node runtime integration. An implementation must return raw
/// ABI bytes and may not silently substitute zero for a revert or malformed
/// response.
pub trait FlashCalls {
    fn call_at_block(&mut self, scope: &BlockScope, target: Address, calldata: &[u8]) -> Result<Vec<u8>, String>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventKind {
    PoolCreated,
    Flash,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DropReason {
    ForeignFactory,
    FactoryRejectedPool,
    InactivePoolDatasource,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailureStage {
    MissingPool,
    FeeGrowth0Call,
    FeeGrowth0Decode,
    FeeGrowth1Call,
    FeeGrowth1Decode,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EventDisposition {
    Committed,
    Dropped(DropReason),
    NonFatalError(FailureStage),
    FatalError(FailureStage),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EventOutcome {
    pub ordinal: u64,
    pub block_log_index: u32,
    pub address: Address,
    pub kind: EventKind,
    pub disposition: EventDisposition,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BlockDisposition {
    /// Accepted by this in-memory diagnostic reducer only; this says nothing
    /// about a Graph Node transaction or physical database commit.
    Committed,
    /// Final persisted Pool user-entity projection after a fatal handler error.
    /// The diagnostic membership reset is not a persisted-data-source projection,
    /// and Graph execution continues outside this host-only reducer.
    FatalPoolUserEntityProjection {
        ordinal: u64,
        stage: FailureStage,
        omitted_event_count: usize,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PoolUpdate {
    pub ordinal: u64,
    pub block_log_index: u32,
    pub address: Address,
    pub fee_growth_global0_x128: BigUint,
    pub fee_growth_global1_x128: BigUint,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockReduction {
    pub state: ReducerState,
    pub outcomes: Vec<EventOutcome>,
    /// Exactly one entry per committed Flash. There is no representation for
    /// Flash, Transaction, or aggregate rows in this API.
    pub pool_updates: Vec<PoolUpdate>,
    pub disposition: BlockDisposition,
    pub segment_id: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct ReducerError(FailureStage);

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
            other => Err(Error::msg(format!("unknown flash-reducer network `{other}`"))),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Mainnet => "mainnet",
            Self::Base => "base",
        }
    }
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
    runtime_start_block: u64,
}

impl NetworkContract {
    fn factory_address(&self) -> Result<Address, Error> {
        decode_contract_address("factory", &self.factory)
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ExecutionContract {
    event_order: String,
    block_context: String,
    producer_corruption: String,
    membership: String,
    graph_node_order_scope: String,
    factory_rejected_pool: String,
    pool_load: String,
    call_scope: String,
    call_cache: String,
    fee_growth_0_calldata: String,
    fee_growth_1_calldata: String,
    call_order: String,
    abi_decode: String,
    atomicity: String,
    missing_pool: String,
    first_call_failure: String,
    second_call_failure: String,
    fatal_error: String,
    post_fatal_execution: String,
    nonfatal_error: String,
    event_fields: String,
    flash_specific_guards: Vec<String>,
    inapplicable_guards: Vec<String>,
    emitted_row_types: Vec<String>,
    synthetic_row_types: Vec<String>,
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
    pool_mapping_cid: String,
    pool_profile_id: String,
    nonfatal_errors: bool,
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
    combined_handler_order_implemented: bool,
    cross_component_order_proven: bool,
    diagnostic_only: bool,
    dynamic_datasource_stage_order_implemented: bool,
    full_pool_handler_semantics: bool,
    graph_node_execution_order_supplement_bound: bool,
    graph_out_replaced: bool,
    graph_execution_trace_complete: bool,
    live_rpc_added: bool,
    logical_oracle_complete: bool,
    physical_parity_complete: bool,
    poi_parity_complete: bool,
    post_fatal_execution_modeled: bool,
    persisted_data_source_projection_complete: bool,
    production_ready: bool,
    rpc_trigger_binding_complete: bool,
    runtime_consumes_execution_order_contract: bool,
    runtime_population_complete: bool,
    same_path_order_machine_proven: bool,
    stores_added: bool,
    substreams_handler_added: bool,
    target_runtime_identity_bound: bool,
    checkpoint_or_graph_block_success_authorized: bool,
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
    source_execution_order_contract: SourceRawContract,
    network_contracts: Vec<NetworkContract>,
    execution_contract: ExecutionContract,
    segments: Vec<Segment>,
    truth_boundary: TruthBoundary,
}

type SegmentExpectation = (Network, u64, Option<u64>, &'static str, &'static str, bool);

impl ReducerContract {
    fn embedded() -> Result<Self, Error> {
        let raw = include_str!("../configs/flash-reducer-v1.json");
        if hex::encode(Sha256::digest(raw.as_bytes())) != REDUCER_CONTRACT_SHA256 {
            return Err(Error::msg("flash-reducer contract digest mismatch"));
        }
        let contract: Self = serde_json::from_str(raw)
            .map_err(|error| Error::msg(format!("invalid flash-reducer contract JSON: {error}")))?;
        contract.validate()?;
        Ok(contract)
    }

    fn validate(&self) -> Result<(), Error> {
        if self.format_version != 1
            || self.contract_version != REDUCER_CONTRACT_VERSION
            || self.mode != "host-diagnostic-only"
        {
            return Err(Error::msg("unsupported flash-reducer contract"));
        }
        if self.source_writer_contract
            != (SourceContract {
                path: "uniswap-v3/graft-ancestry/v2/writer-compatibility.json".to_string(),
                contract_version: "uniswap-v3-writer-compatibility/v3".to_string(),
                sha256: SOURCE_WRITER_CONTRACT_SHA256.to_string(),
            })
            || self.source_segment_profiles
                != (SourceContract {
                    path: "uniswap-v3/writer-runtime/segment-profiles-v1.json".to_string(),
                    contract_version: "uniswap-v3-writer-runtime-segment-profiles/v1".to_string(),
                    sha256: SOURCE_PROFILE_SHA256.to_string(),
                })
            || self.source_writer_runtime
                != (SourceWriterRuntime {
                    path: "uniswap-v3/writer-runtime/contract-v1.json".to_string(),
                    contract_version: "uniswap-v3-writer-runtime/v1".to_string(),
                    sha256: SOURCE_WRITER_RUNTIME_SHA256.to_string(),
                    writer_descriptor_sha256: WRITER_DESCRIPTOR_SHA256.to_string(),
                })
            || self.source_execution_order_contract
                != (SourceRawContract {
                    path: "uniswap-v3/execution-order/v1/contract.json".to_string(),
                    contract_version: "uniswap-v3-execution-order/v1".to_string(),
                    raw_sha256: SOURCE_EXECUTION_ORDER_CONTRACT_RAW_SHA256.to_string(),
                })
        {
            return Err(Error::msg("flash-reducer source binding drift"));
        }
        self.validate_networks()?;
        self.validate_execution_contract()?;
        self.validate_segments()?;
        if self.truth_boundary
            != (TruthBoundary {
                backfill_ready: false,
                boundary_state_continuity_complete: false,
                combined_handler_order_implemented: false,
                cross_component_order_proven: false,
                diagnostic_only: true,
                dynamic_datasource_stage_order_implemented: false,
                full_pool_handler_semantics: false,
                graph_node_execution_order_supplement_bound: true,
                graph_out_replaced: false,
                graph_execution_trace_complete: false,
                live_rpc_added: false,
                logical_oracle_complete: false,
                physical_parity_complete: false,
                poi_parity_complete: false,
                post_fatal_execution_modeled: false,
                persisted_data_source_projection_complete: false,
                production_ready: false,
                rpc_trigger_binding_complete: false,
                runtime_consumes_execution_order_contract: false,
                runtime_population_complete: false,
                same_path_order_machine_proven: false,
                stores_added: false,
                substreams_handler_added: false,
                target_runtime_identity_bound: false,
                checkpoint_or_graph_block_success_authorized: false,
            })
        {
            return Err(Error::msg("flash-reducer truth boundary promoted"));
        }
        Ok(())
    }

    fn validate_networks(&self) -> Result<(), Error> {
        const EXPECTED: &[(Network, &str, u64)] = &[
            (Network::Mainnet, "1f98431c8ad98523631ae4a59f267346ea31f984", 12_369_621),
            (Network::Base, "33128a8fc17869897dce68ed026d694621f6fdfd", 1_371_679),
        ];
        if self.network_contracts.len() != EXPECTED.len() {
            return Err(Error::msg("flash-reducer network contract count drift"));
        }
        for (actual, expected) in self.network_contracts.iter().zip(EXPECTED) {
            if (actual.network, actual.factory.as_str(), actual.runtime_start_block) != *expected {
                return Err(Error::msg("flash-reducer network contract drift"));
            }
            actual.factory_address()?;
        }
        Ok(())
    }

    fn validate_execution_contract(&self) -> Result<(), Error> {
        let execution = &self.execution_contract;
        let expected_guards = [
            "npm block 14317993",
            "npm excluded pool 8fe8d9bb8eeba3ed688069c3d6b556c9ca258248",
            "swap-only excluded pool 9663f2ca0454accad3e094448ea6f77443880454",
        ];
        if execution.event_order
            != "diagnostic input convention: ordinal and block_log_index strictly increase within the supplied PoolCreated/Flash envelope"
            || execution.block_context
                != "immutable network, number, and optional hash; number must match every ordered event"
            || execution.producer_corruption
                != "reject before event execution and before applying segment nonfatal policy"
            || execution.membership
                != "diagnostic creation-ordinal input convention: an earlier supplied PoolCreated marks membership for a later supplied Flash; this does not model Graph Node block-scoped activation"
            || execution.graph_node_order_scope
                != "does not model Graph Node dynamic-datasource stage order, breadth-first whole-block replay, or block-scoped activation; no same-path or cross-component order claim"
            || execution.factory_rejected_pool != hex::encode(FACTORY_REJECTED_POOL)
            || execution.pool_load
                != "load Pool by the Flash event address from diagnostic envelope-current reducer state"
            || execution.call_scope
                != "post-block state at the exact block hash when present or block number otherwise; never log-ordinal state"
            || execution.call_cache != "none; every active Flash attempts its own fee0 then fee1 calls"
            || execution.fee_growth_0_calldata != hex::encode(FEE_GROWTH_0_CALLDATA)
            || execution.fee_growth_1_calldata != hex::encode(FEE_GROWTH_1_CALLDATA)
            || execution.call_order
                != "feeGrowthGlobal0X128 first; only after success feeGrowthGlobal1X128"
            || execution.abi_decode != "exactly one 32-byte big-endian uint256 return value"
            || execution.atomicity
                != "set both Pool fee-growth fields and save one Pool update only after both calls decode"
            || execution.missing_pool != "diagnostic reducer error before either contract call"
            || execution.first_call_failure
                != "stop this Flash handler before fee1; emit no Pool update"
            || execution.second_call_failure
                != "both calls attempted; discard fee0 scratch; emit no Pool update"
            || execution.fatal_error
                != "final persisted Pool user-entity projection shortcut: return the exact block-baseline Pool state at the first fatal error; diagnostic membership reset is not a Graph persisted-data-source projection and this is not a Graph execution stop"
            || execution.post_fatal_execution
                != "intentionally not modeled: Graph continues remaining runnable triggers and breadth-first dynamic stages and may encounter a later retryable failure that aborts before the block transaction; otherwise the fatal transaction filters user modifications to PoI, passes persisted data sources and deterministic errors, advances the failed block pointer, and stops the deployment"
            || execution.nonfatal_error
                != "discard only the failing Flash scratch and continue with later events in the diagnostic envelope"
            || execution.event_fields
                != "sender, recipient, amount0, amount1, paid0, and paid1 are decoded upstream and ignored"
            || !execution.flash_specific_guards.is_empty()
            || execution.inapplicable_guards != expected_guards
            || execution.emitted_row_types != ["Pool"]
            || !execution.synthetic_row_types.is_empty()
        {
            return Err(Error::msg("flash-reducer execution contract drift"));
        }
        Ok(())
    }

    fn validate_segments(&self) -> Result<(), Error> {
        const EXPECTED: &[SegmentExpectation] = &[
            (
                Network::Mainnet,
                12_369_621,
                Some(13_450_880),
                "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw",
                "legacy-mainnet-root",
                false,
            ),
            (
                Network::Mainnet,
                13_450_881,
                Some(13_498_328),
                "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65",
                "legacy-mainnet-qmrv",
                false,
            ),
            (
                Network::Mainnet,
                13_498_329,
                Some(13_591_197),
                "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW",
                "legacy-mainnet-stable",
                false,
            ),
            (
                Network::Mainnet,
                13_591_198,
                Some(13_605_860),
                "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8",
                "legacy-mainnet-stable-fee-tier-1",
                false,
            ),
            (
                Network::Mainnet,
                13_605_861,
                Some(19_470_000),
                "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY",
                "legacy-mainnet-stable-fee-tier-100",
                false,
            ),
            (
                Network::Mainnet,
                19_470_001,
                None,
                "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD",
                "modern-mainnet",
                true,
            ),
            (
                Network::Base,
                1_371_679,
                Some(19_852_000),
                "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3",
                "legacy-base-root",
                true,
            ),
            (
                Network::Base,
                19_852_001,
                None,
                "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P",
                "modern-base",
                true,
            ),
        ];
        if self.segments.len() != EXPECTED.len() {
            return Err(Error::msg("flash-reducer requires exactly eight ordered segments"));
        }
        for (segment, expected) in self.segments.iter().zip(EXPECTED) {
            if (
                segment.network,
                segment.start_block_inclusive,
                segment.end_block_inclusive,
                segment.pool_mapping_cid.as_str(),
                segment.pool_profile_id.as_str(),
                segment.nonfatal_errors,
            ) != *expected
                || segment.segment_id != format!("{}:{}", segment.network.as_str(), segment.deployment)
                || segment.deployment.len() != 46
                || !segment.deployment.starts_with("Qm")
                || segment.pool_mapping_cid.len() != 46
                || !segment.pool_mapping_cid.starts_with("Qm")
                || !is_sha256(&segment.semantic_contract_sha256)
            {
                return Err(Error::msg("flash-reducer segment binding drift"));
            }
        }
        Ok(())
    }

    fn select(&self, network: Network, block: u64) -> Result<&Segment, Error> {
        let mut matches = self.segments.iter().filter(|segment| segment.includes(network, block));
        let segment = matches.next().ok_or_else(|| {
            Error::msg(format!(
                "no flash-reducer segment for {} block {block}",
                network.as_str()
            ))
        })?;
        if matches.next().is_some() {
            return Err(Error::msg("overlapping flash-reducer segments"));
        }
        Ok(segment)
    }

    fn network_contract(&self, network: Network) -> Result<&NetworkContract, Error> {
        self.network_contracts
            .iter()
            .find(|contract| contract.network == network)
            .ok_or_else(|| Error::msg("flash-reducer network contract missing"))
    }
}

/// Reduces the final persisted Pool user-entity projection only. Outcomes are a
/// consumed diagnostic-envelope prefix and never authorize Graph block or
/// checkpoint success. Membership is diagnostic, not persisted-DS projection.
pub fn reduce_flash_block<I: FlashCalls>(
    initial: &ReducerState,
    events: &FlashBlock,
    block: &BlockContext,
    calls: &mut I,
) -> Result<BlockReduction, Error> {
    let contract = ReducerContract::embedded()?;
    let network = Network::parse(&events.network)?;
    if block.network != events.network || block.number != events.block_number {
        return Err(Error::msg("flash-reducer BlockContext binding drift"));
    }
    let network_contract = contract.network_contract(network)?;
    let segment = contract.select(network, block.number)?;
    if events.segment_id != segment.segment_id
        || events.segment_semantic_contract_sha256 != segment.semantic_contract_sha256
        || events.source_writer_contract_sha256 != SOURCE_WRITER_CONTRACT_SHA256
    {
        return Err(Error::msg("flash-reducer event envelope binding drift"));
    }
    if events.block_number < network_contract.runtime_start_block && !events.events.is_empty() {
        return Err(Error::msg("flash-reducer received events before runtime origin"));
    }
    validate_events(events)?;
    validate_state(initial)?;

    let factory = network_contract.factory_address()?;
    let scope = BlockScope {
        network: events.network.clone(),
        block_number: events.block_number,
        block_hash: block.hash,
    };
    let mut working = initial.clone();
    let mut outcomes = Vec::with_capacity(events.events.len());
    let mut pool_updates = Vec::new();

    for ordered in &events.events {
        match &ordered.event {
            PoolEvent::PoolCreated(created) => {
                let disposition = if created.factory != factory {
                    EventDisposition::Dropped(DropReason::ForeignFactory)
                } else if created.pool == FACTORY_REJECTED_POOL {
                    EventDisposition::Dropped(DropReason::FactoryRejectedPool)
                } else {
                    working.active_pool_datasources.insert(created.pool);
                    EventDisposition::Committed
                };
                outcomes.push(EventOutcome {
                    ordinal: ordered.ordinal,
                    block_log_index: ordered.block_log_index,
                    address: created.pool,
                    kind: EventKind::PoolCreated,
                    disposition,
                });
            }
            PoolEvent::Flash(flash) => {
                if !working.active_pool_datasources.contains(&flash.pool) {
                    outcomes.push(EventOutcome {
                        ordinal: ordered.ordinal,
                        block_log_index: ordered.block_log_index,
                        address: flash.pool,
                        kind: EventKind::Flash,
                        disposition: EventDisposition::Dropped(DropReason::InactivePoolDatasource),
                    });
                    continue;
                }
                match reduce_flash(&working, flash.pool, ordered, &scope, calls) {
                    Ok((pool, update)) => {
                        working.pools.insert(pool.address, pool);
                        pool_updates.push(update);
                        outcomes.push(EventOutcome {
                            ordinal: ordered.ordinal,
                            block_log_index: ordered.block_log_index,
                            address: flash.pool,
                            kind: EventKind::Flash,
                            disposition: EventDisposition::Committed,
                        });
                    }
                    Err(error) if segment.nonfatal_errors => outcomes.push(EventOutcome {
                        ordinal: ordered.ordinal,
                        block_log_index: ordered.block_log_index,
                        address: flash.pool,
                        kind: EventKind::Flash,
                        disposition: EventDisposition::NonFatalError(error.0),
                    }),
                    Err(error) => {
                        outcomes.push(EventOutcome {
                            ordinal: ordered.ordinal,
                            block_log_index: ordered.block_log_index,
                            address: flash.pool,
                            kind: EventKind::Flash,
                            disposition: EventDisposition::FatalError(error.0),
                        });
                        let omitted_event_count = events.events.len() - outcomes.len();
                        return Ok(BlockReduction {
                            state: initial.clone(),
                            outcomes,
                            pool_updates: Vec::new(),
                            disposition: BlockDisposition::FatalPoolUserEntityProjection {
                                ordinal: ordered.ordinal,
                                stage: error.0,
                                omitted_event_count,
                            },
                            segment_id: segment.segment_id.clone(),
                        });
                    }
                }
            }
        }
    }

    Ok(BlockReduction {
        state: working,
        outcomes,
        pool_updates,
        disposition: BlockDisposition::Committed,
        segment_id: segment.segment_id.clone(),
    })
}

fn reduce_flash<I: FlashCalls>(
    state: &ReducerState,
    address: Address,
    ordered: &OrderedPoolEvent,
    scope: &BlockScope,
    calls: &mut I,
) -> Result<(Pool, PoolUpdate), ReducerError> {
    let mut pool = state
        .pools
        .get(&address)
        .cloned()
        .ok_or(ReducerError(FailureStage::MissingPool))?;

    let fee0_raw = calls
        .call_at_block(scope, address, &FEE_GROWTH_0_CALLDATA)
        .map_err(|_| ReducerError(FailureStage::FeeGrowth0Call))?;
    let fee0 = decode_uint256(&fee0_raw).ok_or(ReducerError(FailureStage::FeeGrowth0Decode))?;
    let fee1_raw = calls
        .call_at_block(scope, address, &FEE_GROWTH_1_CALLDATA)
        .map_err(|_| ReducerError(FailureStage::FeeGrowth1Call))?;
    let fee1 = decode_uint256(&fee1_raw).ok_or(ReducerError(FailureStage::FeeGrowth1Decode))?;

    pool.fee_growth_global0_x128.clone_from(&fee0);
    pool.fee_growth_global1_x128.clone_from(&fee1);
    let update = PoolUpdate {
        ordinal: ordered.ordinal,
        block_log_index: ordered.block_log_index,
        address,
        fee_growth_global0_x128: fee0,
        fee_growth_global1_x128: fee1,
    };
    Ok((pool, update))
}

fn validate_events(events: &FlashBlock) -> Result<(), Error> {
    let mut prior: Option<(u64, u32)> = None;
    for event in &events.events {
        if event.block_number != events.block_number {
            return Err(Error::msg("flash-reducer event block number drift"));
        }
        if let Some((ordinal, log_index)) = prior {
            if event.ordinal <= ordinal || event.block_log_index <= log_index {
                return Err(Error::msg(
                    "flash-reducer diagnostic envelope events must have strictly increasing ordinal and block_log_index",
                ));
            }
        }
        prior = Some((event.ordinal, event.block_log_index));
    }
    Ok(())
}

fn validate_state(state: &ReducerState) -> Result<(), Error> {
    let maximum = max_uint256();
    for (address, pool) in &state.pools {
        if address != &pool.address {
            return Err(Error::msg("flash-reducer Pool map key drift"));
        }
        if pool.fee_growth_global0_x128 > maximum || pool.fee_growth_global1_x128 > maximum {
            return Err(Error::msg("flash-reducer Pool fee growth exceeds uint256"));
        }
    }
    if state.active_pool_datasources.contains(&FACTORY_REJECTED_POOL) {
        return Err(Error::msg(
            "flash-reducer factory-rejected pool cannot be an active datasource",
        ));
    }
    Ok(())
}

fn decode_uint256(raw: &[u8]) -> Option<BigUint> {
    (raw.len() == 32).then(|| BigUint::from_bytes_be(raw))
}

fn max_uint256() -> BigUint {
    (BigUint::from(1_u8) << 256_u32) - BigUint::from(1_u8)
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn decode_contract_address(field: &str, value: &str) -> Result<Address, Error> {
    if value.len() != 40
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(Error::msg(format!(
            "flash-reducer {field} must be a lowercase 20-byte address"
        )));
    }
    let decoded = hex::decode(value).map_err(|error| Error::msg(format!("flash-reducer invalid {field}: {error}")))?;
    decoded
        .try_into()
        .map_err(|_| Error::msg(format!("flash-reducer {field} must be 20 bytes")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    const POOL_A: Address = [0x20; 20];
    const POOL_B: Address = [0x21; 20];
    const SENDER: Address = [0x30; 20];
    const RECIPIENT: Address = [0x31; 20];
    const FOREIGN_FACTORY: Address = [0x44; 20];
    const SWAP_ONLY_POOL: Address = [
        0x96, 0x63, 0xf2, 0xca, 0x04, 0x54, 0xac, 0xca, 0xd3, 0xe0, 0x94, 0x44, 0x8e, 0xa6, 0xf7, 0x74, 0x43, 0x88,
        0x04, 0x54,
    ];

    #[derive(Clone, Debug, PartialEq, Eq)]
    struct CallRecord {
        scope: BlockScope,
        target: Address,
        calldata: Vec<u8>,
    }

    #[derive(Default)]
    struct FakeCalls {
        results: VecDeque<Result<Vec<u8>, String>>,
        records: Vec<CallRecord>,
    }

    impl FakeCalls {
        fn success(&mut self, value: BigUint) {
            let bytes = value.to_bytes_be();
            let mut encoded = vec![0_u8; 32 - bytes.len()];
            encoded.extend(bytes);
            self.results.push_back(Ok(encoded));
        }

        fn failure(&mut self) {
            self.results
                .push_back(Err("provider detail must not escape".to_string()));
        }

        fn malformed(&mut self, raw: Vec<u8>) {
            self.results.push_back(Ok(raw));
        }
    }

    impl FlashCalls for FakeCalls {
        fn call_at_block(&mut self, scope: &BlockScope, target: Address, calldata: &[u8]) -> Result<Vec<u8>, String> {
            self.records.push(CallRecord {
                scope: scope.clone(),
                target,
                calldata: calldata.to_vec(),
            });
            self.results
                .pop_front()
                .unwrap_or_else(|| Err("unconfigured call".to_string()))
        }
    }

    fn payload(seed: u8) -> FlashPayload {
        FlashPayload {
            sender: [seed; 20],
            recipient: [seed.wrapping_add(1); 20],
            amount0: BigUint::from(seed),
            amount1: BigUint::from(seed) << 200_u32,
            paid0: max_uint256(),
            paid1: BigUint::from(0_u8),
        }
    }

    fn pool(address: Address, fee0: u64, fee1: u64) -> Pool {
        Pool {
            address,
            fee_growth_global0_x128: fee0.into(),
            fee_growth_global1_x128: fee1.into(),
        }
    }

    fn state(addresses: &[Address]) -> ReducerState {
        ReducerState {
            pools: addresses
                .iter()
                .map(|address| (*address, pool(*address, 7, 9)))
                .collect(),
            active_pool_datasources: addresses.iter().copied().collect(),
        }
    }

    fn context(network: &str, block: u64) -> BlockContext {
        BlockContext {
            network: network.to_string(),
            number: block,
            hash: Some([block as u8; 32]),
        }
    }

    fn segment(network: &str, block: u64) -> Segment {
        ReducerContract::embedded()
            .unwrap()
            .select(Network::parse(network).unwrap(), block)
            .unwrap()
            .clone()
    }

    fn block(network: &str, number: u64, events: Vec<OrderedPoolEvent>) -> FlashBlock {
        let segment = segment(network, number);
        FlashBlock {
            events,
            network: network.to_string(),
            block_number: number,
            segment_id: segment.segment_id,
            source_writer_contract_sha256: SOURCE_WRITER_CONTRACT_SHA256.to_string(),
            segment_semantic_contract_sha256: segment.semantic_contract_sha256,
        }
    }

    fn flash(ordinal: u64, block: u64, log_index: u32, address: Address) -> OrderedPoolEvent {
        OrderedPoolEvent {
            ordinal,
            block_number: block,
            block_log_index: log_index,
            event: PoolEvent::Flash(Flash {
                pool: address,
                payload: payload(ordinal as u8),
            }),
        }
    }

    fn created(ordinal: u64, block: u64, log_index: u32, factory: Address, address: Address) -> OrderedPoolEvent {
        OrderedPoolEvent {
            ordinal,
            block_number: block,
            block_log_index: log_index,
            event: PoolEvent::PoolCreated(PoolCreated { factory, pool: address }),
        }
    }

    fn factory(network: &str) -> Address {
        ReducerContract::embedded()
            .unwrap()
            .network_contract(Network::parse(network).unwrap())
            .unwrap()
            .factory_address()
            .unwrap()
    }

    #[test]
    fn all_eight_segments_have_the_exact_failure_policy() {
        let contract = ReducerContract::embedded().unwrap();
        assert_eq!(contract.segments.len(), 8);
        assert_eq!(
            contract
                .segments
                .iter()
                .map(|segment| segment.nonfatal_errors)
                .collect::<Vec<_>>(),
            [false, false, false, false, false, true, true, true]
        );
    }

    #[test]
    fn every_segment_executes_its_bound_fatal_or_nonfatal_policy() {
        let representatives = [
            ("mainnet", 12_369_621, false),
            ("mainnet", 13_450_881, false),
            ("mainnet", 13_498_329, false),
            ("mainnet", 13_591_198, false),
            ("mainnet", 13_605_861, false),
            ("mainnet", 19_470_001, true),
            ("base", 1_371_679, true),
            ("base", 19_852_001, true),
        ];
        for (network, number, nonfatal) in representatives {
            let initial = state(&[POOL_A]);
            let events = block(network, number, vec![flash(1, number, 1, POOL_A)]);
            let mut calls = FakeCalls::default();
            calls.failure();
            let result = reduce_flash_block(&initial, &events, &context(network, number), &mut calls).unwrap();
            assert_eq!(result.state, initial, "{network}:{number}");
            assert!(result.pool_updates.is_empty(), "{network}:{number}");
            if nonfatal {
                assert_eq!(result.disposition, BlockDisposition::Committed, "{network}:{number}");
                assert_eq!(
                    result.outcomes[0].disposition,
                    EventDisposition::NonFatalError(FailureStage::FeeGrowth0Call),
                    "{network}:{number}"
                );
            } else {
                assert_eq!(
                    result.disposition,
                    BlockDisposition::FatalPoolUserEntityProjection {
                        ordinal: 1,
                        stage: FailureStage::FeeGrowth0Call,
                        omitted_event_count: 0,
                    },
                    "{network}:{number}"
                );
                assert_eq!(
                    result.outcomes[0].disposition,
                    EventDisposition::FatalError(FailureStage::FeeGrowth0Call),
                    "{network}:{number}"
                );
            }
        }
    }

    #[test]
    fn successful_flash_calls_fee0_then_fee1_and_commits_once() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let events = block("mainnet", number, vec![flash(10, number, 3, POOL_A)]);
        let mut calls = FakeCalls::default();
        calls.success(100_u64.into());
        calls.success(200_u64.into());

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert_eq!(result.disposition, BlockDisposition::Committed);
        assert_eq!(result.pool_updates.len(), 1);
        assert_eq!(result.pool_updates[0].fee_growth_global0_x128, BigUint::from(100_u64));
        assert_eq!(result.pool_updates[0].fee_growth_global1_x128, BigUint::from(200_u64));
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global0_x128,
            BigUint::from(100_u64)
        );
        assert_eq!(calls.records.len(), 2);
        assert_eq!(calls.records[0].calldata, FEE_GROWTH_0_CALLDATA);
        assert_eq!(calls.records[1].calldata, FEE_GROWTH_1_CALLDATA);
        assert_eq!(calls.records[0].target, POOL_A);
        assert_eq!(calls.records[0].scope.block_hash, Some([number as u8; 32]));
    }

    #[test]
    fn first_call_failure_stops_before_fee1_without_partial_update() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
        let mut calls = FakeCalls::default();
        calls.failure();
        calls.success(999_u64.into());

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert_eq!(calls.records.len(), 1);
        assert_eq!(result.state, initial);
        assert!(result.pool_updates.is_empty());
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(FailureStage::FeeGrowth0Call)
        );
    }

    #[test]
    fn second_call_failure_discards_fee0_scratch_without_fallback() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
        let mut calls = FakeCalls::default();
        calls.success(123_u64.into());
        calls.failure();

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert_eq!(calls.records.len(), 2);
        assert_eq!(result.state, initial);
        assert!(result.pool_updates.is_empty());
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(FailureStage::FeeGrowth1Call)
        );
    }

    #[test]
    fn malformed_first_and_second_results_are_not_zero_fallbacks() {
        let number = 20_000_000;
        for (results, expected_calls, stage) in [
            (vec![Ok(vec![])], 1, FailureStage::FeeGrowth0Decode),
            (vec![Ok(vec![0_u8; 33])], 1, FailureStage::FeeGrowth0Decode),
            (
                vec![Ok(vec![0_u8; 32]), Ok(vec![0_u8; 31])],
                2,
                FailureStage::FeeGrowth1Decode,
            ),
            (
                vec![Ok(vec![0_u8; 32]), Ok(vec![0_u8; 33])],
                2,
                FailureStage::FeeGrowth1Decode,
            ),
        ] {
            let initial = state(&[POOL_A]);
            let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
            let mut calls = FakeCalls {
                results: results.into(),
                records: Vec::new(),
            };
            let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();
            assert_eq!(calls.records.len(), expected_calls);
            assert_eq!(result.state, initial);
            assert!(result.pool_updates.is_empty());
            assert_eq!(result.outcomes[0].disposition, EventDisposition::NonFatalError(stage));
        }
    }

    #[test]
    fn missing_pool_stops_before_calls() {
        let number = 20_000_000;
        let mut initial = ReducerState::default();
        initial.active_pool_datasources.insert(POOL_A);
        let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
        let mut calls = FakeCalls::default();

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert!(calls.records.is_empty());
        assert!(result.pool_updates.is_empty());
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(FailureStage::MissingPool)
        );
    }

    #[test]
    fn uint256_zero_huge_and_maximum_decode_exactly() {
        let number = 20_000_000;
        let huge = BigUint::from(1_u8) << 255_u32;
        for (fee0, fee1) in [(BigUint::from(0_u8), huge), (max_uint256(), max_uint256())] {
            let initial = state(&[POOL_A]);
            let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
            let mut calls = FakeCalls::default();
            calls.success(fee0.clone());
            calls.success(fee1.clone());
            let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();
            assert_eq!(result.pool_updates[0].fee_growth_global0_x128, fee0);
            assert_eq!(result.pool_updates[0].fee_growth_global1_x128, fee1);
        }
    }

    #[test]
    fn repeated_pools_are_never_deduplicated_or_cached() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let events = block(
            "mainnet",
            number,
            vec![flash(1, number, 1, POOL_A), flash(2, number, 2, POOL_A)],
        );
        let mut calls = FakeCalls::default();
        for value in [10_u64, 11, 20, 21] {
            calls.success(value.into());
        }

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert_eq!(calls.records.len(), 4);
        assert_eq!(result.pool_updates.len(), 2);
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global0_x128,
            BigUint::from(20_u64)
        );
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global1_x128,
            BigUint::from(21_u64)
        );
    }

    #[test]
    fn multiple_pools_and_interleaving_preserve_diagnostic_envelope_order() {
        let number = 20_000_000;
        let initial = state(&[POOL_A, POOL_B]);
        let events = block(
            "mainnet",
            number,
            vec![
                flash(10, number, 1, POOL_A),
                flash(20, number, 2, POOL_B),
                flash(30, number, 3, POOL_A),
            ],
        );
        let mut calls = FakeCalls::default();
        for value in 1_u64..=6 {
            calls.success(value.into());
        }

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert_eq!(
            result
                .pool_updates
                .iter()
                .map(|update| update.ordinal)
                .collect::<Vec<_>>(),
            [10, 20, 30]
        );
        assert_eq!(
            calls.records.iter().map(|record| record.target).collect::<Vec<_>>(),
            [POOL_A, POOL_A, POOL_B, POOL_B, POOL_A, POOL_A]
        );
    }

    #[test]
    fn diagnostic_creation_ordinal_membership_applies_only_to_later_envelope_events() {
        let number = 20_000_000;
        let mut initial = state(&[]);
        initial.pools.insert(POOL_A, pool(POOL_A, 7, 9));
        let factory = factory("mainnet");
        let before = block(
            "mainnet",
            number,
            vec![created(1, number, 1, factory, POOL_A), flash(2, number, 2, POOL_A)],
        );
        let mut calls = FakeCalls::default();
        calls.success(10_u64.into());
        calls.success(11_u64.into());
        let accepted = reduce_flash_block(&initial, &before, &context("mainnet", number), &mut calls).unwrap();
        assert_eq!(accepted.pool_updates.len(), 1);

        let after = block(
            "mainnet",
            number,
            vec![flash(1, number, 1, POOL_A), created(2, number, 2, factory, POOL_A)],
        );
        let mut no_calls = FakeCalls::default();
        let rejected = reduce_flash_block(&initial, &after, &context("mainnet", number), &mut no_calls).unwrap();
        assert!(rejected.pool_updates.is_empty());
        assert!(no_calls.records.is_empty());
        assert_eq!(
            rejected.outcomes[0].disposition,
            EventDisposition::Dropped(DropReason::InactivePoolDatasource)
        );
        assert!(rejected.state.active_pool_datasources.contains(&POOL_A));
    }

    #[test]
    fn factory_rejected_pool_and_foreign_factory_never_activate() {
        let number = 20_000_000;
        let mut initial = ReducerState::default();
        initial
            .pools
            .insert(FACTORY_REJECTED_POOL, pool(FACTORY_REJECTED_POOL, 7, 9));
        initial.pools.insert(POOL_A, pool(POOL_A, 7, 9));
        let events = block(
            "mainnet",
            number,
            vec![
                created(1, number, 1, factory("mainnet"), FACTORY_REJECTED_POOL),
                flash(2, number, 2, FACTORY_REJECTED_POOL),
                created(3, number, 3, FOREIGN_FACTORY, POOL_A),
                flash(4, number, 4, POOL_A),
            ],
        );
        let mut calls = FakeCalls::default();
        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert!(calls.records.is_empty());
        assert!(result.pool_updates.is_empty());
        assert_eq!(
            result
                .outcomes
                .iter()
                .map(|outcome| outcome.disposition.clone())
                .collect::<Vec<_>>(),
            [
                EventDisposition::Dropped(DropReason::FactoryRejectedPool),
                EventDisposition::Dropped(DropReason::InactivePoolDatasource),
                EventDisposition::Dropped(DropReason::ForeignFactory),
                EventDisposition::Dropped(DropReason::InactivePoolDatasource),
            ]
        );
    }

    #[test]
    fn flash_has_no_npm_block_or_swap_only_pool_guard() {
        let number = 14_317_993;
        let initial = state(&[SWAP_ONLY_POOL]);
        let events = block("mainnet", number, vec![flash(1, number, 1, SWAP_ONLY_POOL)]);
        let mut calls = FakeCalls::default();
        calls.success(10_u64.into());
        calls.success(11_u64.into());

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert_eq!(result.pool_updates.len(), 1);
        assert_eq!(calls.records.len(), 2);
    }

    #[test]
    fn base_block_14317993_flash_remains_active_and_commits_after_two_calls() {
        let number = 14_317_993;
        let initial = state(&[POOL_A]);
        let events = block("base", number, vec![flash(1, number, 1, POOL_A)]);
        let mut calls = FakeCalls::default();
        calls.success(100_u64.into());
        calls.success(101_u64.into());

        let result = reduce_flash_block(&initial, &events, &context("base", number), &mut calls).unwrap();

        assert_eq!(result.disposition, BlockDisposition::Committed);
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert_eq!(result.pool_updates.len(), 1);
        assert_eq!(calls.records.len(), 2);
        assert_eq!(calls.records[0].calldata, FEE_GROWTH_0_CALLDATA);
        assert_eq!(calls.records[1].calldata, FEE_GROWTH_1_CALLDATA);
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global0_x128,
            BigUint::from(100_u64)
        );
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global1_x128,
            BigUint::from(101_u64)
        );
    }

    #[test]
    fn number_fallback_binds_both_calls_to_the_exact_original_block() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
        let fallback = BlockContext {
            network: "mainnet".to_string(),
            number,
            hash: None,
        };
        let mut calls = FakeCalls::default();
        calls.success(10_u64.into());
        calls.success(11_u64.into());

        let result = reduce_flash_block(&initial, &events, &fallback, &mut calls).unwrap();

        assert_eq!(result.pool_updates.len(), 1);
        assert_eq!(calls.records.len(), 2);
        for record in &calls.records {
            assert_eq!(record.scope.network, "mainnet");
            assert_eq!(record.scope.block_number, number);
            assert_eq!(record.scope.block_hash, None);
        }

        let mutated = BlockContext {
            number: number + 1,
            ..fallback
        };
        let mut rejected_calls = FakeCalls::default();
        assert!(reduce_flash_block(&initial, &events, &mutated, &mut rejected_calls).is_err());
        assert!(rejected_calls.records.is_empty());
    }

    #[test]
    fn legacy_fatal_failure_returns_pool_baseline_projection_and_omits_later_events() {
        let number = 14_000_000;
        let mut initial = state(&[POOL_A]);
        initial.pools.insert(POOL_B, pool(POOL_B, 7, 9));
        let events = block(
            "mainnet",
            number,
            vec![
                flash(1, number, 1, POOL_A),
                created(2, number, 2, factory("mainnet"), POOL_B),
                flash(3, number, 3, POOL_B),
                flash(4, number, 4, POOL_A),
            ],
        );
        let mut calls = FakeCalls::default();
        calls.success(10_u64.into());
        calls.success(11_u64.into());
        calls.failure();

        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();

        assert_eq!(result.state, initial);
        assert!(result.pool_updates.is_empty());
        assert_eq!(
            result.disposition,
            BlockDisposition::FatalPoolUserEntityProjection {
                ordinal: 3,
                stage: FailureStage::FeeGrowth0Call,
                omitted_event_count: 1,
            }
        );
        assert_eq!(result.outcomes.len(), 3);
    }

    #[test]
    fn current_nonfatal_failure_preserves_diagnostic_neighbors_and_continues() {
        let number = 20_000_000;
        let initial = state(&[POOL_A, POOL_B]);
        let events = block(
            "base",
            number,
            vec![
                flash(1, number, 1, POOL_A),
                flash(2, number, 2, POOL_B),
                flash(3, number, 3, POOL_A),
            ],
        );
        let mut calls = FakeCalls::default();
        calls.success(10_u64.into());
        calls.success(11_u64.into());
        calls.failure();
        calls.success(30_u64.into());
        calls.success(31_u64.into());

        let result = reduce_flash_block(&initial, &events, &context("base", number), &mut calls).unwrap();

        assert_eq!(result.pool_updates.len(), 2);
        assert_eq!(
            result
                .pool_updates
                .iter()
                .map(|update| update.ordinal)
                .collect::<Vec<_>>(),
            [1, 3]
        );
        assert_eq!(result.state.pools[&POOL_B], initial.pools[&POOL_B]);
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global0_x128,
            BigUint::from(30_u64)
        );
    }

    #[test]
    fn event_payload_is_ignored_and_cannot_swap_call_results() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let mut event = flash(1, number, 1, POOL_A);
        if let PoolEvent::Flash(value) = &mut event.event {
            value.payload = FlashPayload {
                sender: SENDER,
                recipient: RECIPIENT,
                amount0: max_uint256(),
                amount1: BigUint::from(0_u8),
                paid0: BigUint::from(444_u64),
                paid1: BigUint::from(555_u64),
            };
        }
        let events = block("mainnet", number, vec![event]);
        let mut calls = FakeCalls::default();
        calls.success(111_u64.into());
        calls.success(222_u64.into());
        let result = reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).unwrap();
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global0_x128,
            BigUint::from(111_u64)
        );
        assert_eq!(
            result.state.pools[&POOL_A].fee_growth_global1_x128,
            BigUint::from(222_u64)
        );
    }

    #[test]
    fn invalid_diagnostic_envelope_order_context_and_segment_bindings_fail_before_calls() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let cases = [
            // Graph Node can replay an earlier log in a later dynamic-data-source
            // stage; this single-envelope diagnostic convention deliberately
            // rejects that shape instead of claiming cross-stage equivalence.
            block(
                "mainnet",
                number,
                vec![
                    created(1, number, 10, factory("mainnet"), POOL_A),
                    flash(2, number, 3, POOL_A),
                ],
            ),
            block(
                "mainnet",
                number,
                vec![flash(2, number, 2, POOL_A), flash(1, number, 3, POOL_A)],
            ),
            block(
                "mainnet",
                number,
                vec![flash(1, number, 2, POOL_A), flash(2, number, 1, POOL_A)],
            ),
        ];
        for events in cases {
            let mut calls = FakeCalls::default();
            assert!(reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).is_err());
            assert!(calls.records.is_empty());
        }

        let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
        for bad_context in [context("base", number), context("mainnet", number + 1)] {
            let mut calls = FakeCalls::default();
            assert!(reduce_flash_block(&initial, &events, &bad_context, &mut calls).is_err());
            assert!(calls.records.is_empty());
        }
        let mut bad_binding = events.clone();
        bad_binding.segment_id.push_str("-drift");
        let mut calls = FakeCalls::default();
        assert!(reduce_flash_block(&initial, &bad_binding, &context("mainnet", number), &mut calls).is_err());
        assert!(calls.records.is_empty());
    }

    #[test]
    fn event_block_drift_and_invalid_initial_state_fail_closed() {
        let number = 20_000_000;
        let initial = state(&[POOL_A]);
        let events = block("mainnet", number, vec![flash(1, number + 1, 1, POOL_A)]);
        let mut calls = FakeCalls::default();
        assert!(reduce_flash_block(&initial, &events, &context("mainnet", number), &mut calls).is_err());

        let mut invalid = initial.clone();
        invalid.pools.get_mut(&POOL_A).unwrap().address = POOL_B;
        let events = block("mainnet", number, vec![flash(1, number, 1, POOL_A)]);
        assert!(reduce_flash_block(&invalid, &events, &context("mainnet", number), &mut calls).is_err());
        assert!(calls.records.is_empty());
    }

    #[test]
    fn helper_can_queue_malformed_responses() {
        let mut calls = FakeCalls::default();
        calls.malformed(vec![1_u8; 31]);
        assert_eq!(calls.results.len(), 1);
    }
}
