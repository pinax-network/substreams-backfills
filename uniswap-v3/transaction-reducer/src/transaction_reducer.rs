//! Host-only NonfungiblePositionManager Transaction side-effect reducer.
//!
//! The module is intentionally disconnected from Substreams handlers,
//! `graph_out`, stores, RPC, and databases. All external mapping outcomes are
//! explicit hermetic inputs, while segment selection and Transaction behavior
//! are fixed by the retained eight-segment contracts.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write;

use num_bigint::BigUint;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use substreams::errors::Error;

use crate::pb::writer::writer_event::Event;
use crate::pb::writer::{WriterEvent, WriterEvents};

const REDUCER_CONTRACT_SHA256: &str = "83268d10f0ef3008d6d30fc3b6fd304fd46a067866b4284344fe468397878246";
const REDUCER_CONTRACT_VERSION: &str = "uniswap-v3-transaction-reducer/v1";
const SOURCE_MATRIX_SHA256: &str = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161";
const SOURCE_PROFILE_SHA256: &str = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823";
const SOURCE_WRITER_RUNTIME_SHA256: &str = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca";
const SOURCE_WRITER_SHA256: &str = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4";
const SOURCE_EXECUTION_ORDER_RAW_SHA256: &str = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2";
const WRITER_DESCRIPTOR_SHA256: &str = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0";
const GRAPH_NODE_VERSION: &str = "v0.44.0";
const GRAPH_NODE_COMMIT: &str = "77823b5a7adc4eac4abf03202c8dd7cb00dea31d";
const GRAPH_NODE_TREE: &str = "1f372b47e4de659ddbf503cdbc31ebe4d54df239";
const HISTORICAL_GUARD_BLOCK: u64 = 14_317_993;

pub type TransactionHash = [u8; 32];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockContext {
    pub number: u64,
    pub timestamp: u64,
}

/// Metadata absent from the pinned writer-event protobuf. It remains a
/// host-only diagnostic input and never changes a package descriptor.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TransactionMetadata {
    pub transaction_hash: TransactionHash,
    pub gas_limit: String,
    pub gas_price: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PositionLookupPlan {
    /// A Position relation already exists at this event ordinal.
    Existing,
    /// `getPosition` constructs a provisional identity and calls
    /// `loadTransaction`, but the Position is not persisted until the handler
    /// reaches its save.
    NewIdentity,
    /// The generated `try_positions` call reverted, so `getPosition` returns
    /// null normally and makes no Transaction write.
    PositionsReverted,
    /// A non-try identity dependency failed deterministically before
    /// `loadTransaction` was reached.
    DeterministicError,
    /// Only valid when the historical guard returns before lookup.
    NotConsulted,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TokenAvailability {
    Both,
    Token0Only,
    Token1Only,
    Neither,
}

impl TokenAvailability {
    fn token0(self) -> bool {
        matches!(self, Self::Both | Self::Token0Only)
    }

    fn token1(self) -> bool {
        matches!(self, Self::Both | Self::Token1Only)
    }
}

/// A host-failure injection used only to assert handler-atomic entity-state
/// discard. It does not model consumed VIDs or PoI/error-stream effects and is
/// not a claim that a particular deployed host call fails.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailurePhase {
    None,
    AfterIdentity,
    BeforeSnapshotLoad,
    AfterSnapshotLoad,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EventControl {
    pub ordinal: u64,
    pub position_lookup: PositionLookupPlan,
    pub excluded_pool: bool,
    pub token_availability: TokenAvailability,
    pub failure_phase: FailurePhase,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DiagnosticInput {
    pub writer_events: WriterEvents,
    pub block: BlockContext,
    pub transactions: Vec<TransactionMetadata>,
    pub controls: Vec<EventControl>,
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
pub struct PositionTransaction {
    pub token_id: String,
    pub transaction: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SnapshotTransaction {
    pub id: String,
    pub position: String,
    pub block_number: u64,
    pub transaction: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReducerState {
    pub transactions: BTreeMap<String, TransactionEntity>,
    pub positions: BTreeMap<String, PositionTransaction>,
    pub snapshots: BTreeMap<String, SnapshotTransaction>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventKind {
    Increase,
    Decrease,
    Collect,
    Transfer,
}

impl EventKind {
    fn applies_historical_guard(self) -> bool {
        matches!(self, Self::Increase | Self::Decrease)
    }

    fn applies_excluded_pool(self) -> bool {
        matches!(self, Self::Increase | Self::Decrease | Self::Collect)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NormalReturnReason {
    HistoricalGuard,
    PositionsReverted,
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

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EventOutcome {
    pub ordinal: u64,
    pub token_id: String,
    pub kind: EventKind,
    pub transaction_id: String,
    pub disposition: EventDisposition,
    pub attempted_loads: Vec<TransactionLoadSite>,
    pub event_state_committed: bool,
    pub block_state_committed: bool,
    pub position_transaction_written: Option<String>,
    pub snapshot_transaction_written: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BlockDisposition {
    Committed,
    /// Final persisted Transaction/relation projection after a fatal handler
    /// error. Graph execution itself continues outside this host-only reducer.
    FatalTransactionUserEntityProjection {
        ordinal: u64,
        message: String,
        omitted_event_count: usize,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockReduction {
    pub state: ReducerState,
    pub outcomes: Vec<EventOutcome>,
    pub disposition: BlockDisposition,
    pub segment_id: String,
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
            other => Err(Error::msg(format!("unknown transaction-reducer network `{other}`"))),
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
enum StoredGasUsedMode {
    TransactionGasLimit,
    Zero,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum MissingTokenPolicy {
    DeterministicError,
    NormalReturn,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum CollectTokenRequirement {
    Both,
    None,
    Token0,
    OptionalToken0,
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
struct GraphNodeSourceFile {
    path: String,
    sha256: String,
    relevant_lines: Vec<String>,
    immutable_url: String,
    claim: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct SourceGraphNodeTransactionGas {
    version: String,
    commit: String,
    tree: String,
    legacy_api_version: String,
    legacy_mapping_property: String,
    legacy_wat_field_offset_bytes: u8,
    asc_transaction_field: String,
    entity_field: String,
    receipt_gas_used_used: bool,
    target_runtime_binary_or_source_identity_bound: bool,
    files: Vec<GraphNodeSourceFile>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ExecutionContract {
    transaction_id: String,
    load_transaction: String,
    legacy_stored_gas_used: String,
    current_stored_gas_used: String,
    receipt_gas_used: String,
    new_position_helper_calls: u8,
    existing_position_helper_calls: u8,
    position_transaction: String,
    snapshot_transaction: String,
    normal_return_orphans: Vec<String>,
    deterministic_error_entity_state: String,
    fatal_error_entity_state: String,
    post_fatal_execution: String,
    nonfatal_error_entity_state: String,
    npm_writer_event_order: String,
    pool_cross_component_execution_order: String,
    physical_graph_node_side_effects: String,
    producer_corruption: String,
    metadata_scope: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Segment {
    network: Network,
    start_block_inclusive: u64,
    end_block_inclusive: Option<u64>,
    npm_start_block: u64,
    segment_id: String,
    semantic_contract_sha256: String,
    npm_profile_id: String,
    api_version: String,
    stored_gas_used_mode: StoredGasUsedMode,
    nonfatal_errors: bool,
    historical_guard_effective: bool,
    increase_decrease_missing_token_policy: MissingTokenPolicy,
    collect_token_requirement: CollectTokenRequirement,
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
    full_npm_handler_semantics: bool,
    graph_out_replaced: bool,
    graph_execution_trace_complete: bool,
    live_calls_added: bool,
    logical_oracle_complete: bool,
    physical_parity_complete: bool,
    poi_parity_complete: bool,
    post_fatal_execution_modeled: bool,
    failed_handler_poi_error_stream_semantics_certified: bool,
    physical_entity_vid_semantics_certified: bool,
    pool_cross_component_execution_order_certified: bool,
    pool_transaction_writers_audited: bool,
    production_ready: bool,
    runtime_population_complete: bool,
    shared_transaction_last_writer_semantics_certified: bool,
    stores_added: bool,
    substreams_handler_added: bool,
    checkpoint_or_graph_block_success_authorized: bool,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ReducerContract {
    format_version: u8,
    contract_version: String,
    mode: String,
    source_writer_runtime: SourceWriterRuntime,
    source_segment_matrix: SourceContract,
    source_segment_profiles: SourceContract,
    source_graph_node_transaction_gas: SourceGraphNodeTransactionGas,
    source_execution_order: SourceRawContract,
    execution_contract: ExecutionContract,
    segments: Vec<Segment>,
    truth_boundary: TruthBoundary,
}

#[derive(Clone, Copy)]
struct ExpectedSegment {
    network: Network,
    start: u64,
    end: Option<u64>,
    npm_start: u64,
    id: &'static str,
    semantic: &'static str,
    profile: &'static str,
    api: &'static str,
    stored_gas: StoredGasUsedMode,
    nonfatal: bool,
    guard: bool,
    missing: MissingTokenPolicy,
    collect: CollectTokenRequirement,
}

const EXPECTED_SEGMENTS: [ExpectedSegment; 8] = [
    ExpectedSegment {
        network: Network::Mainnet,
        start: 12_369_621,
        end: Some(13_450_880),
        npm_start: 12_369_651,
        id: "mainnet:Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB",
        semantic: "4839ecce0391345e412ccde53a12d6d243cafd3d6a99e9072f8f1d2020b802ff",
        profile: "mainnet-root-correct-collect",
        api: "0.0.4",
        stored_gas: StoredGasUsedMode::TransactionGasLimit,
        nonfatal: false,
        guard: false,
        missing: MissingTokenPolicy::DeterministicError,
        collect: CollectTokenRequirement::Both,
    },
    ExpectedSegment {
        network: Network::Mainnet,
        start: 13_450_881,
        end: Some(13_498_328),
        npm_start: 12_369_651,
        id: "mainnet:QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry",
        semantic: "b344c20468dc56e3a6a4d32cf785de598f816270edbad4e5a7e979d6d5428a3c",
        profile: "mainnet-second-fee0-overwrite",
        api: "0.0.4",
        stored_gas: StoredGasUsedMode::TransactionGasLimit,
        nonfatal: false,
        guard: false,
        missing: MissingTokenPolicy::DeterministicError,
        collect: CollectTokenRequirement::Both,
    },
    ExpectedSegment {
        network: Network::Mainnet,
        start: 13_498_329,
        end: Some(13_591_197),
        npm_start: 12_369_651,
        id: "mainnet:QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P",
        semantic: "cc0894a0822321f296585430bb93f705903494b832e56a20b858994c6f7052d0",
        profile: "mainnet-no-collect-amounts",
        api: "0.0.4",
        stored_gas: StoredGasUsedMode::TransactionGasLimit,
        nonfatal: false,
        guard: false,
        missing: MissingTokenPolicy::DeterministicError,
        collect: CollectTokenRequirement::None,
    },
    ExpectedSegment {
        network: Network::Mainnet,
        start: 13_591_198,
        end: Some(13_605_860),
        npm_start: 12_369_651,
        id: "mainnet:QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX",
        semantic: "9b890298b85194fb05123b7a0c5836feb63d2224c845f6714183d8588882d85a",
        profile: "mainnet-no-collect-amounts",
        api: "0.0.4",
        stored_gas: StoredGasUsedMode::TransactionGasLimit,
        nonfatal: false,
        guard: false,
        missing: MissingTokenPolicy::DeterministicError,
        collect: CollectTokenRequirement::None,
    },
    ExpectedSegment {
        network: Network::Mainnet,
        start: 13_605_861,
        end: Some(19_470_000),
        npm_start: 12_369_651,
        id: "mainnet:QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF",
        semantic: "83e4269b0582acfec8d1f868c59c6a71e362554ee41ecab4a7ccfbab87888815",
        profile: "mainnet-no-collect-amounts",
        api: "0.0.4",
        stored_gas: StoredGasUsedMode::TransactionGasLimit,
        nonfatal: false,
        guard: false,
        missing: MissingTokenPolicy::DeterministicError,
        collect: CollectTokenRequirement::None,
    },
    ExpectedSegment {
        network: Network::Mainnet,
        start: 19_470_001,
        end: None,
        npm_start: 12_369_651,
        id: "mainnet:QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
        semantic: "0b2a208cc7ff5cbced29818ddb4fddabfa236393fc289686a87a48e8c309b754",
        profile: "current-amount0-to-both",
        api: "0.0.7",
        stored_gas: StoredGasUsedMode::Zero,
        nonfatal: true,
        guard: false,
        missing: MissingTokenPolicy::NormalReturn,
        collect: CollectTokenRequirement::OptionalToken0,
    },
    ExpectedSegment {
        network: Network::Base,
        start: 1_371_679,
        end: Some(19_852_000),
        npm_start: 1_371_713,
        id: "base:QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
        semantic: "03d3fdaeecacfbb4aae325a1021117ddc6c3baf48d9589af69d0f3db7cdfab20",
        profile: "base-root-amount0-to-both",
        api: "0.0.4",
        stored_gas: StoredGasUsedMode::TransactionGasLimit,
        nonfatal: true,
        guard: true,
        missing: MissingTokenPolicy::DeterministicError,
        collect: CollectTokenRequirement::Token0,
    },
    ExpectedSegment {
        network: Network::Base,
        start: 19_852_001,
        end: None,
        npm_start: 1_371_713,
        id: "base:Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP",
        semantic: "5dd72427adcb71c3e4fd249dc4371005fb372875f236fb90439adf5fe9d7398b",
        profile: "current-amount0-to-both",
        api: "0.0.7",
        stored_gas: StoredGasUsedMode::Zero,
        nonfatal: true,
        guard: false,
        missing: MissingTokenPolicy::NormalReturn,
        collect: CollectTokenRequirement::OptionalToken0,
    },
];

fn expected_graph_node_transaction_gas_source() -> SourceGraphNodeTransactionGas {
    SourceGraphNodeTransactionGas {
        version: String::from(GRAPH_NODE_VERSION),
        commit: String::from(GRAPH_NODE_COMMIT),
        tree: String::from(GRAPH_NODE_TREE),
        legacy_api_version: String::from("0.0.4"),
        legacy_mapping_property: String::from("event.transaction.gasUsed"),
        legacy_wat_field_offset_bytes: 20,
        asc_transaction_field: String::from("gas_limit"),
        entity_field: String::from("Transaction.gasUsed"),
        receipt_gas_used_used: false,
        target_runtime_binary_or_source_identity_bound: false,
        files: vec![
            GraphNodeSourceFile {
                path: String::from("chain/ethereum/src/runtime/abi.rs"),
                sha256: String::from("86932f5228b303ea15121767a5cc5d39417208346a351a2e057e4ac430a6d6c9"),
                relevant_lines: vec![String::from("254-269"), String::from("520-537")],
                immutable_url: String::from(
                    "https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/chain/ethereum/src/runtime/abi.rs",
                ),
                claim: String::from(
                    "the API 0.0.4 AscEthereumTransaction_0_0_2 field at offset 20 is gas_limit and ToAscObj populates it from EthereumTransactionData.gas_limit",
                ),
            },
            GraphNodeSourceFile {
                path: String::from("chain/ethereum/src/trigger.rs"),
                sha256: String::from("6b31d65fa9c0289d76a5bb7d812965e51e26054bb4fad417aa641843c531700f"),
                relevant_lines: vec![String::from("127-184"), String::from("552-557")],
                immutable_url: String::from(
                    "https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/chain/ethereum/src/trigger.rs",
                ),
                claim: String::from(
                    "API 0.0.4 selects AscEthereumTransaction_0_0_2 and EthereumTransactionData.gas_limit delegates to the transaction gas_limit accessor",
                ),
            },
            GraphNodeSourceFile {
                path: String::from("graph/src/components/transaction_receipt.rs"),
                sha256: String::from("4f491ddc90f16f4aff919dde803ba0ba47cdccf979db5904366b4bc4ca82ec36"),
                relevant_lines: vec![String::from("9-27")],
                immutable_url: String::from(
                    "https://github.com/graphprotocol/graph-node/blob/77823b5a7adc4eac4abf03202c8dd7cb00dea31d/graph/src/components/transaction_receipt.rs",
                ),
                claim: String::from(
                    "receipt gas_used is a distinct transaction-receipt field and is not the legacy transaction offset",
                ),
            },
        ],
    }
}

impl ReducerContract {
    fn parse() -> Result<Self, Error> {
        let raw = include_str!("../configs/transaction-reducer-v1.json");
        let digest = format!("{:x}", Sha256::digest(raw.as_bytes()));
        if digest != REDUCER_CONTRACT_SHA256 {
            return Err(Error::msg("transaction-reducer contract digest drift"));
        }
        let contract: Self = serde_json::from_str(raw)
            .map_err(|error| Error::msg(format!("invalid transaction-reducer contract: {error}")))?;
        contract.validate()?;
        Ok(contract)
    }

    fn validate(&self) -> Result<(), Error> {
        if self.format_version != 1
            || self.contract_version != REDUCER_CONTRACT_VERSION
            || self.mode != "host-diagnostic-only"
        {
            return Err(Error::msg("unsupported transaction-reducer contract"));
        }
        if self.source_writer_runtime.path != "uniswap-v3/writer-runtime/contract-v1.json"
            || self.source_writer_runtime.contract_version != "uniswap-v3-writer-runtime/v1"
            || self.source_writer_runtime.sha256 != SOURCE_WRITER_RUNTIME_SHA256
            || self.source_writer_runtime.writer_descriptor_sha256 != WRITER_DESCRIPTOR_SHA256
            || self.source_segment_matrix.path != "uniswap-v3/segment-writer-matrix/v1/contract.json"
            || self.source_segment_matrix.contract_version != "uniswap-v3-segment-writer-matrix/v1"
            || self.source_segment_matrix.sha256 != SOURCE_MATRIX_SHA256
            || self.source_segment_profiles.path != "uniswap-v3/writer-runtime/segment-profiles-v1.json"
            || self.source_segment_profiles.contract_version != "uniswap-v3-writer-runtime-segment-profiles/v1"
            || self.source_segment_profiles.sha256 != SOURCE_PROFILE_SHA256
            || self.source_execution_order.path != "uniswap-v3/execution-order/v1/contract.json"
            || self.source_execution_order.contract_version != "uniswap-v3-execution-order/v1"
            || self.source_execution_order.raw_sha256 != SOURCE_EXECUTION_ORDER_RAW_SHA256
        {
            return Err(Error::msg("transaction-reducer source binding drift"));
        }
        if self.source_graph_node_transaction_gas != expected_graph_node_transaction_gas_source() {
            return Err(Error::msg("Graph Node transaction gas source binding drift"));
        }
        if self.execution_contract.new_position_helper_calls != 2
            || self.execution_contract.existing_position_helper_calls != 1
            || self.execution_contract.normal_return_orphans.len() != 2
            || self.execution_contract.legacy_stored_gas_used
                != "apiVersion 0.0.4 writes the transaction gas_limit exposed to the mapping as event.transaction.gasUsed"
            || self.execution_contract.current_stored_gas_used
                != "apiVersion 0.0.7 writes zero while preserving gasPrice"
            || self.execution_contract.receipt_gas_used
                != "not consumed by either deployed NPM loadTransaction generation"
            || self.execution_contract.deterministic_error_entity_state
                != "discard all attempted entity-state writes from the failing handler"
            || self.execution_contract.fatal_error_entity_state
                != "final persisted NPM Transaction and relation user-entity projection shortcut: return the exact block baseline at the first fatal error; this is not a Graph execution stop"
            || self.execution_contract.post_fatal_execution
                != "intentionally not modeled: Graph continues remaining runnable triggers and breadth-first dynamic stages and may encounter a later retryable failure that aborts before the block transaction; otherwise the fatal transaction filters user modifications to PoI, passes persisted data sources and deterministic errors, advances the failed block pointer, and stops the deployment"
            || self.execution_contract.npm_writer_event_order
                != "strictly increasing global ordinal and block_log_index within the NPM WriterEvents envelope"
            || !self
                .execution_contract
                .pool_cross_component_execution_order
                .contains("dynamic Pool data-source triggers execute after")
            || !self
                .execution_contract
                .physical_graph_node_side_effects
                .contains("consume entity VIDs")
            || !self.execution_contract.metadata_scope.contains("writer protobuf")
        {
            return Err(Error::msg("transaction-reducer execution contract drift"));
        }
        let truth = &self.truth_boundary;
        if !truth.diagnostic_only
            || truth.backfill_ready
            || truth.boundary_state_continuity_complete
            || truth.full_npm_handler_semantics
            || truth.graph_out_replaced
            || truth.graph_execution_trace_complete
            || truth.live_calls_added
            || truth.logical_oracle_complete
            || truth.physical_parity_complete
            || truth.poi_parity_complete
            || truth.post_fatal_execution_modeled
            || truth.failed_handler_poi_error_stream_semantics_certified
            || truth.physical_entity_vid_semantics_certified
            || truth.pool_cross_component_execution_order_certified
            || truth.pool_transaction_writers_audited
            || truth.production_ready
            || truth.runtime_population_complete
            || truth.shared_transaction_last_writer_semantics_certified
            || truth.stores_added
            || truth.substreams_handler_added
            || truth.checkpoint_or_graph_block_success_authorized
        {
            return Err(Error::msg("transaction-reducer conservative gate promoted"));
        }
        if self.segments.len() != EXPECTED_SEGMENTS.len() {
            return Err(Error::msg("transaction-reducer requires exactly eight segments"));
        }
        for (actual, expected) in self.segments.iter().zip(EXPECTED_SEGMENTS) {
            if actual.network != expected.network
                || actual.start_block_inclusive != expected.start
                || actual.end_block_inclusive != expected.end
                || actual.npm_start_block != expected.npm_start
                || actual.segment_id != expected.id
                || actual.semantic_contract_sha256 != expected.semantic
                || actual.npm_profile_id != expected.profile
                || actual.api_version != expected.api
                || actual.stored_gas_used_mode != expected.stored_gas
                || actual.nonfatal_errors != expected.nonfatal
                || actual.historical_guard_effective != expected.guard
                || actual.increase_decrease_missing_token_policy != expected.missing
                || actual.collect_token_requirement != expected.collect
            {
                return Err(Error::msg(format!(
                    "transaction-reducer segment drift: {}",
                    actual.segment_id
                )));
            }
        }
        Ok(())
    }

    fn select(&self, network: Network, block: u64) -> Result<&Segment, Error> {
        let matches = self
            .segments
            .iter()
            .filter(|segment| segment.includes(network, block))
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(Error::msg(format!(
                "expected exactly one transaction-reducer segment for {} block {block}, found {}",
                network.as_str(),
                matches.len()
            )));
        }
        Ok(matches[0])
    }
}

#[derive(Debug)]
enum ExecutionFailure {
    Invalid(String),
    Handler(String),
}

impl ExecutionFailure {
    fn invalid(message: impl Into<String>) -> Self {
        Self::Invalid(message.into())
    }

    fn handler(message: impl Into<String>) -> Self {
        Self::Handler(message.into())
    }
}

#[derive(Debug)]
struct SuccessfulExecution {
    disposition: EventDisposition,
    position_transaction_written: Option<String>,
    snapshot_transaction_written: Option<String>,
}

/// Apply the NPM-local Transaction helper-call and final user-entity projection
/// contract to one validated writer envelope. Outcomes are a consumed prefix;
/// they never authorize Graph block or checkpoint success. Pool shared-Transaction
/// writers, Graph Node VID allocation, and PoI/error-stream effects are absent.
pub fn reduce_transaction_block(
    input: &DiagnosticInput,
    initial_state: &ReducerState,
) -> Result<BlockReduction, Error> {
    let contract = ReducerContract::parse()?;
    let network = Network::parse(&input.writer_events.network)?;
    let segment = contract.select(network, input.writer_events.block_number)?;
    validate_input(input, initial_state, segment)?;

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
    let baseline = initial_state.clone();
    let mut state = initial_state.clone();
    let mut outcomes = Vec::with_capacity(input.writer_events.events.len());

    for event in &input.writer_events.events {
        let hash = transaction_hash(event)?;
        let tx_id = transaction_id(&hash);
        let transaction = metadata[&hash];
        let control = controls[&event.ordinal];
        let (kind, token_id) = event_identity(event)?;
        let mut scratch = state.clone();
        let mut attempted_loads = Vec::new();

        match execute_event(
            event,
            kind,
            &token_id,
            transaction,
            control,
            &input.block,
            segment,
            &mut scratch,
            &mut attempted_loads,
        ) {
            Ok(success) => {
                state = scratch;
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    transaction_id: tx_id,
                    disposition: success.disposition,
                    attempted_loads,
                    event_state_committed: true,
                    block_state_committed: true,
                    position_transaction_written: success.position_transaction_written,
                    snapshot_transaction_written: success.snapshot_transaction_written,
                });
            }
            Err(ExecutionFailure::Invalid(message)) => return Err(Error::msg(message)),
            Err(ExecutionFailure::Handler(message)) if segment.nonfatal_errors => {
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    transaction_id: tx_id,
                    disposition: EventDisposition::NonFatalError(message),
                    attempted_loads,
                    event_state_committed: false,
                    block_state_committed: false,
                    position_transaction_written: None,
                    snapshot_transaction_written: None,
                });
            }
            Err(ExecutionFailure::Handler(message)) => {
                for outcome in &mut outcomes {
                    outcome.block_state_committed = false;
                }
                outcomes.push(EventOutcome {
                    ordinal: event.ordinal,
                    token_id,
                    kind,
                    transaction_id: tx_id,
                    disposition: EventDisposition::FatalError(message.clone()),
                    attempted_loads,
                    event_state_committed: false,
                    block_state_committed: false,
                    position_transaction_written: None,
                    snapshot_transaction_written: None,
                });
                let omitted_event_count = input.writer_events.events.len() - outcomes.len();
                return Ok(BlockReduction {
                    state: baseline,
                    outcomes,
                    disposition: BlockDisposition::FatalTransactionUserEntityProjection {
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
        state,
        outcomes,
        disposition: BlockDisposition::Committed,
        segment_id: segment.segment_id.clone(),
    })
}

#[allow(clippy::too_many_arguments)]
fn execute_event(
    event: &WriterEvent,
    kind: EventKind,
    token_id: &str,
    metadata: &TransactionMetadata,
    control: &EventControl,
    block: &BlockContext,
    segment: &Segment,
    state: &mut ReducerState,
    attempted_loads: &mut Vec<TransactionLoadSite>,
) -> Result<SuccessfulExecution, ExecutionFailure> {
    let guarded =
        segment.historical_guard_effective && block.number == HISTORICAL_GUARD_BLOCK && kind.applies_historical_guard();
    if guarded {
        if control.position_lookup != PositionLookupPlan::NotConsulted || control.failure_phase != FailurePhase::None {
            return Err(ExecutionFailure::invalid(format!(
                "historical guard control must be NotConsulted with no injected failure at ordinal {}",
                event.ordinal
            )));
        }
        return Ok(normal_return(NormalReturnReason::HistoricalGuard));
    }
    if control.position_lookup == PositionLookupPlan::NotConsulted {
        return Err(ExecutionFailure::invalid(format!(
            "unguarded event cannot use NotConsulted lookup at ordinal {}",
            event.ordinal
        )));
    }

    let existed = state.positions.contains_key(token_id);
    let new_identity = match control.position_lookup {
        PositionLookupPlan::Existing if existed => false,
        PositionLookupPlan::Existing => {
            return Err(ExecutionFailure::invalid(format!(
                "Existing lookup has no Position `{token_id}` at ordinal {}",
                event.ordinal
            )));
        }
        PositionLookupPlan::NewIdentity if !existed => true,
        PositionLookupPlan::NewIdentity => {
            return Err(ExecutionFailure::invalid(format!(
                "NewIdentity lookup conflicts with existing Position `{token_id}` at ordinal {}",
                event.ordinal
            )));
        }
        PositionLookupPlan::PositionsReverted if !existed => {
            require_no_unreachable_failure(control, event.ordinal)?;
            return Ok(normal_return(NormalReturnReason::PositionsReverted));
        }
        PositionLookupPlan::PositionsReverted => {
            return Err(ExecutionFailure::invalid(format!(
                "PositionsReverted lookup conflicts with existing Position `{token_id}` at ordinal {}",
                event.ordinal
            )));
        }
        PositionLookupPlan::DeterministicError if !existed => {
            if control.failure_phase != FailurePhase::None {
                return Err(ExecutionFailure::invalid(format!(
                    "identity error cannot combine with an injected failure at ordinal {}",
                    event.ordinal
                )));
            }
            return Err(ExecutionFailure::handler(format!(
                "deterministic identity dependency error at ordinal {}",
                event.ordinal
            )));
        }
        PositionLookupPlan::DeterministicError => {
            return Err(ExecutionFailure::invalid(format!(
                "identity error lookup conflicts with existing Position `{token_id}` at ordinal {}",
                event.ordinal
            )));
        }
        PositionLookupPlan::NotConsulted => unreachable!(),
    };

    let tx_id = transaction_id(&metadata.transaction_hash);
    if new_identity {
        load_transaction(state, metadata, block, segment.stored_gas_used_mode);
        attempted_loads.push(TransactionLoadSite::PositionCreation);
    }
    if control.failure_phase == FailurePhase::AfterIdentity {
        return Err(ExecutionFailure::handler(format!(
            "injected deterministic error after identity at ordinal {}",
            event.ordinal
        )));
    }

    if kind.applies_excluded_pool() && control.excluded_pool {
        require_no_unreachable_failure(control, event.ordinal)?;
        return Ok(normal_return(NormalReturnReason::ExcludedPool));
    }

    match kind {
        EventKind::Increase | EventKind::Decrease
            if !(control.token_availability.token0() && control.token_availability.token1()) =>
        {
            match segment.increase_decrease_missing_token_policy {
                MissingTokenPolicy::DeterministicError => {
                    return Err(ExecutionFailure::handler(format!(
                        "legacy missing Token dereference at ordinal {}",
                        event.ordinal
                    )))
                }
                MissingTokenPolicy::NormalReturn => {
                    require_no_unreachable_failure(control, event.ordinal)?;
                    return Ok(normal_return(NormalReturnReason::MissingToken));
                }
            }
        }
        EventKind::Collect => match segment.collect_token_requirement {
            CollectTokenRequirement::Both
                if !(control.token_availability.token0() && control.token_availability.token1()) =>
            {
                return Err(ExecutionFailure::handler(format!(
                    "legacy Collect missing Token dereference at ordinal {}",
                    event.ordinal
                )))
            }
            CollectTokenRequirement::Token0 if !control.token_availability.token0() => {
                return Err(ExecutionFailure::handler(format!(
                    "Base-root Collect missing token0 dereference at ordinal {}",
                    event.ordinal
                )))
            }
            CollectTokenRequirement::None
            | CollectTokenRequirement::OptionalToken0
            | CollectTokenRequirement::Token0
            | CollectTokenRequirement::Both => {}
        },
        EventKind::Transfer | EventKind::Increase | EventKind::Decrease => {}
    }

    if control.failure_phase == FailurePhase::BeforeSnapshotLoad {
        return Err(ExecutionFailure::handler(format!(
            "injected deterministic error before snapshot load at ordinal {}",
            event.ordinal
        )));
    }
    load_transaction(state, metadata, block, segment.stored_gas_used_mode);
    attempted_loads.push(TransactionLoadSite::PositionSnapshot);
    if control.failure_phase == FailurePhase::AfterSnapshotLoad {
        return Err(ExecutionFailure::handler(format!(
            "injected deterministic error after snapshot load at ordinal {}",
            event.ordinal
        )));
    }

    let position_transaction_written = if new_identity {
        state.positions.insert(
            token_id.to_owned(),
            PositionTransaction {
                token_id: token_id.to_owned(),
                transaction: tx_id.clone(),
            },
        );
        Some(tx_id.clone())
    } else {
        None
    };
    let snapshot_id = format!("{token_id}#{}", block.number);
    state.snapshots.insert(
        snapshot_id.clone(),
        SnapshotTransaction {
            id: snapshot_id,
            position: token_id.to_owned(),
            block_number: block.number,
            transaction: tx_id.clone(),
        },
    );
    Ok(SuccessfulExecution {
        disposition: EventDisposition::Committed,
        position_transaction_written,
        snapshot_transaction_written: Some(tx_id),
    })
}

fn normal_return(reason: NormalReturnReason) -> SuccessfulExecution {
    SuccessfulExecution {
        disposition: EventDisposition::NormalReturn(reason),
        position_transaction_written: None,
        snapshot_transaction_written: None,
    }
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
    stored_gas_used_mode: StoredGasUsedMode,
) {
    let id = transaction_id(&metadata.transaction_hash);
    let stored_gas_used = match stored_gas_used_mode {
        StoredGasUsedMode::TransactionGasLimit => metadata.gas_limit.clone(),
        StoredGasUsedMode::Zero => "0".to_owned(),
    };
    state.transactions.insert(
        id.clone(),
        TransactionEntity {
            id,
            block_number: block.number,
            timestamp: block.timestamp,
            gas_used: stored_gas_used,
            gas_price: metadata.gas_price.clone(),
        },
    );
}

fn validate_input(input: &DiagnosticInput, state: &ReducerState, segment: &Segment) -> Result<(), Error> {
    if input.block.number != input.writer_events.block_number {
        return Err(Error::msg("transaction-reducer block context number mismatch"));
    }
    if input.writer_events.segment_id != segment.segment_id
        || input.writer_events.segment_semantic_contract_sha256 != segment.semantic_contract_sha256
        || input.writer_events.source_writer_contract_sha256 != SOURCE_WRITER_SHA256
    {
        return Err(Error::msg("transaction-reducer writer envelope binding drift"));
    }
    if input.writer_events.block_number < segment.npm_start_block && !input.writer_events.events.is_empty() {
        return Err(Error::msg(
            "writer envelope contains NPM events before the segment NPM origin",
        ));
    }
    validate_state(state)?;

    let mut previous_ordinal = None;
    let mut previous_block_log_index = None;
    let mut referenced_hashes = BTreeSet::new();
    let mut ordinals = BTreeSet::new();
    for event in &input.writer_events.events {
        if event.block_number != input.writer_events.block_number {
            return Err(Error::msg(format!(
                "writer-event block mismatch at ordinal {}",
                event.ordinal
            )));
        }
        if previous_ordinal.is_some_and(|value| event.ordinal <= value)
            || previous_block_log_index.is_some_and(|value| event.block_log_index <= value)
        {
            return Err(Error::msg(
                "writer events are not strictly ordered by ordinal and block_log_index",
            ));
        }
        previous_ordinal = Some(event.ordinal);
        previous_block_log_index = Some(event.block_log_index);
        let hash = transaction_hash(event)?;
        referenced_hashes.insert(hash);
        ordinals.insert(event.ordinal);
        let (_, token_id) = event_identity(event)?;
        validate_uint256("token id", &token_id)?;
    }

    let mut metadata_hashes = BTreeSet::new();
    for metadata in &input.transactions {
        if !metadata_hashes.insert(metadata.transaction_hash) {
            return Err(Error::msg(format!(
                "duplicate transaction metadata for {}",
                transaction_id(&metadata.transaction_hash)
            )));
        }
        validate_uint256("transaction gas limit", &metadata.gas_limit)?;
        validate_uint256("gas price", &metadata.gas_price)?;
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
    if control_ordinals != ordinals {
        return Err(Error::msg("event control ordinals must exactly match writer events"));
    }
    Ok(())
}

fn validate_state(state: &ReducerState) -> Result<(), Error> {
    for (key, entity) in &state.transactions {
        if key != &entity.id || !valid_transaction_id(key) {
            return Err(Error::msg(format!("invalid Transaction state identity `{key}`")));
        }
        validate_uint256("state gas used", &entity.gas_used)?;
        validate_uint256("state gas price", &entity.gas_price)?;
    }
    for (key, position) in &state.positions {
        validate_uint256("Position token id", key)?;
        if key != &position.token_id || !valid_transaction_id(&position.transaction) {
            return Err(Error::msg(format!("invalid Position transaction relation `{key}`")));
        }
    }
    for (key, snapshot) in &state.snapshots {
        validate_uint256("PositionSnapshot position", &snapshot.position)?;
        if key != &snapshot.id
            || snapshot.id != format!("{}#{}", snapshot.position, snapshot.block_number)
            || !valid_transaction_id(&snapshot.transaction)
        {
            return Err(Error::msg(format!(
                "invalid PositionSnapshot transaction relation `{key}`"
            )));
        }
    }
    Ok(())
}

fn validate_uint256(name: &str, value: &str) -> Result<(), Error> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || !value.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(Error::msg(format!(
            "{name} is not canonical unsigned decimal: `{value}`"
        )));
    }
    let parsed = BigUint::parse_bytes(value.as_bytes(), 10)
        .ok_or_else(|| Error::msg(format!("{name} is not an unsigned integer: `{value}`")))?;
    if parsed.bits() > 256 {
        return Err(Error::msg(format!("{name} exceeds uint256: `{value}`")));
    }
    Ok(())
}

fn event_identity(event: &WriterEvent) -> Result<(EventKind, String), Error> {
    match event.event.as_ref() {
        Some(Event::IncreaseLiquidity(value)) => Ok((EventKind::Increase, value.token_id.clone())),
        Some(Event::DecreaseLiquidity(value)) => Ok((EventKind::Decrease, value.token_id.clone())),
        Some(Event::Collect(value)) => Ok((EventKind::Collect, value.token_id.clone())),
        Some(Event::Transfer(value)) => Ok((EventKind::Transfer, value.token_id.clone())),
        None => Err(Error::msg(format!(
            "writer event missing oneof at ordinal {}",
            event.ordinal
        ))),
    }
}

fn transaction_hash(event: &WriterEvent) -> Result<TransactionHash, Error> {
    event.transaction_hash.as_slice().try_into().map_err(|_| {
        Error::msg(format!(
            "writer-event transaction hash must be 32 bytes at ordinal {}",
            event.ordinal
        ))
    })
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pb::writer::{Collect, DecreaseLiquidity, IncreaseLiquidity, Transfer, WriterEvent};

    #[derive(Clone)]
    struct TestEvent {
        ordinal: u64,
        block_log_index: u32,
        transaction_byte: u8,
        token_id: &'static str,
        kind: EventKind,
        lookup: PositionLookupPlan,
        excluded_pool: bool,
        tokens: TokenAvailability,
        failure: FailurePhase,
        gas_limit: &'static str,
        gas_price: &'static str,
    }

    impl TestEvent {
        fn transfer(ordinal: u64, transaction_byte: u8, token_id: &'static str, lookup: PositionLookupPlan) -> Self {
            Self {
                ordinal,
                block_log_index: ordinal as u32,
                transaction_byte,
                token_id,
                kind: EventKind::Transfer,
                lookup,
                excluded_pool: false,
                tokens: TokenAvailability::Both,
                failure: FailurePhase::None,
                gas_limit: "500000",
                gas_price: "9000000000",
            }
        }

        fn increase(
            ordinal: u64,
            transaction_byte: u8,
            token_id: &'static str,
            lookup: PositionLookupPlan,
            tokens: TokenAvailability,
        ) -> Self {
            Self {
                kind: EventKind::Increase,
                tokens,
                ..Self::transfer(ordinal, transaction_byte, token_id, lookup)
            }
        }

        fn decrease(
            ordinal: u64,
            transaction_byte: u8,
            token_id: &'static str,
            lookup: PositionLookupPlan,
            tokens: TokenAvailability,
        ) -> Self {
            Self {
                kind: EventKind::Decrease,
                tokens,
                ..Self::transfer(ordinal, transaction_byte, token_id, lookup)
            }
        }

        fn collect(
            ordinal: u64,
            transaction_byte: u8,
            token_id: &'static str,
            lookup: PositionLookupPlan,
            tokens: TokenAvailability,
        ) -> Self {
            Self {
                kind: EventKind::Collect,
                tokens,
                ..Self::transfer(ordinal, transaction_byte, token_id, lookup)
            }
        }
    }

    fn hash(byte: u8) -> TransactionHash {
        [byte; 32]
    }

    fn tx_id(byte: u8) -> String {
        transaction_id(&hash(byte))
    }

    fn writer_event(block: u64, item: &TestEvent) -> WriterEvent {
        let event = match item.kind {
            EventKind::Increase => Event::IncreaseLiquidity(IncreaseLiquidity {
                token_id: item.token_id.to_owned(),
                liquidity: "1".to_owned(),
                amount0: "2".to_owned(),
                amount1: "3".to_owned(),
            }),
            EventKind::Decrease => Event::DecreaseLiquidity(DecreaseLiquidity {
                token_id: item.token_id.to_owned(),
                liquidity: "1".to_owned(),
                amount0: "2".to_owned(),
                amount1: "3".to_owned(),
            }),
            EventKind::Collect => Event::Collect(Collect {
                token_id: item.token_id.to_owned(),
                recipient: vec![0x44; 20],
                amount0: "2".to_owned(),
                amount1: "3".to_owned(),
            }),
            EventKind::Transfer => Event::Transfer(Transfer {
                from: vec![0x55; 20],
                to: vec![0x66; 20],
                token_id: item.token_id.to_owned(),
            }),
        };
        WriterEvent {
            ordinal: item.ordinal,
            transaction_hash: hash(item.transaction_byte).to_vec(),
            block_number: block,
            transaction_log_index: item.block_log_index,
            block_log_index: item.block_log_index,
            contract_address: vec![0x77; 20],
            event: Some(event),
        }
    }

    fn input(segment_index: usize, block: u64, items: &[TestEvent]) -> DiagnosticInput {
        let segment = EXPECTED_SEGMENTS[segment_index];
        let mut metadata = BTreeMap::new();
        for item in items {
            metadata
                .entry(hash(item.transaction_byte))
                .or_insert_with(|| TransactionMetadata {
                    transaction_hash: hash(item.transaction_byte),
                    gas_limit: item.gas_limit.to_owned(),
                    gas_price: item.gas_price.to_owned(),
                });
        }
        DiagnosticInput {
            writer_events: WriterEvents {
                events: items.iter().map(|item| writer_event(block, item)).collect(),
                network: segment.network.as_str().to_owned(),
                block_number: block,
                segment_id: segment.id.to_owned(),
                source_writer_contract_sha256: SOURCE_WRITER_SHA256.to_owned(),
                segment_semantic_contract_sha256: segment.semantic.to_owned(),
            },
            block: BlockContext {
                number: block,
                timestamp: 1_700_000_123,
            },
            transactions: metadata.into_values().collect(),
            controls: items
                .iter()
                .map(|item| EventControl {
                    ordinal: item.ordinal,
                    position_lookup: item.lookup,
                    excluded_pool: item.excluded_pool,
                    token_availability: item.tokens,
                    failure_phase: item.failure,
                })
                .collect(),
        }
    }

    fn position(token_id: &str, transaction_byte: u8) -> PositionTransaction {
        PositionTransaction {
            token_id: token_id.to_owned(),
            transaction: tx_id(transaction_byte),
        }
    }

    #[test]
    fn contract_binds_exact_eight_segments_and_sources() {
        let contract = ReducerContract::parse().unwrap();
        assert_eq!(contract.segments.len(), 8);
        assert_eq!(contract.source_writer_runtime.sha256, SOURCE_WRITER_RUNTIME_SHA256);
        assert_eq!(contract.source_segment_matrix.sha256, SOURCE_MATRIX_SHA256);
        assert!(contract.truth_boundary.diagnostic_only);
        assert!(!contract.truth_boundary.pool_transaction_writers_audited);
        assert!(!contract.truth_boundary.pool_cross_component_execution_order_certified);
        assert!(!contract.truth_boundary.physical_entity_vid_semantics_certified);
        assert!(
            !contract
                .truth_boundary
                .failed_handler_poi_error_stream_semantics_certified
        );
        assert!(
            !contract
                .truth_boundary
                .shared_transaction_last_writer_semantics_certified
        );
    }

    #[test]
    fn new_position_calls_helper_twice_and_legacy_uses_transaction_gas_limit() {
        let item = TestEvent::transfer(1, 0xab, "42", PositionLookupPlan::NewIdentity);
        let result = reduce_transaction_block(&input(0, 12_400_000, &[item]), &ReducerState::default()).unwrap();
        assert_eq!(result.disposition, BlockDisposition::Committed);
        assert_eq!(
            result.outcomes[0].attempted_loads,
            vec![
                TransactionLoadSite::PositionCreation,
                TransactionLoadSite::PositionSnapshot
            ]
        );
        let id = tx_id(0xab);
        assert_eq!(id, format!("0x{}", "ab".repeat(32)));
        assert_eq!(
            result.state.transactions[&id],
            TransactionEntity {
                id: id.clone(),
                block_number: 12_400_000,
                timestamp: 1_700_000_123,
                gas_used: "500000".to_owned(),
                gas_price: "9000000000".to_owned(),
            }
        );
        assert_eq!(result.state.positions["42"].transaction, id);
        assert_eq!(result.state.snapshots["42#12400000"].transaction, tx_id(0xab));
    }

    #[test]
    fn all_eight_segments_execute_committed_event_with_expected_gas_contract() {
        let blocks = [
            12_400_000, 13_460_000, 13_500_000, 13_600_000, 14_000_000, 20_000_000, 2_000_000, 20_000_000,
        ];
        for (segment_index, block) in blocks.into_iter().enumerate() {
            let transaction_byte = 0xb0 + segment_index as u8;
            let item = TestEvent::transfer(1, transaction_byte, "900", PositionLookupPlan::NewIdentity);
            let result =
                reduce_transaction_block(&input(segment_index, block, &[item]), &ReducerState::default()).unwrap();
            assert_eq!(
                result.disposition,
                BlockDisposition::Committed,
                "segment {segment_index}"
            );
            assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
            let expected_gas_used = if matches!(segment_index, 5 | 7) { "0" } else { "500000" };
            assert_eq!(
                result.state.transactions[&tx_id(transaction_byte)].gas_used,
                expected_gas_used,
                "segment {segment_index}"
            );
        }
    }

    #[test]
    fn legacy_and_current_stored_gas_used_distinguish_gas_limit_from_receipt_usage() {
        let receipt_actual_gas_used = "21000";
        let transaction_gas_limit = "750000";
        let mut legacy = TestEvent::transfer(1, 0xac, "43", PositionLookupPlan::NewIdentity);
        legacy.gas_limit = transaction_gas_limit;
        let legacy_result =
            reduce_transaction_block(&input(0, 12_400_000, &[legacy]), &ReducerState::default()).unwrap();
        let legacy_stored_gas_used = &legacy_result.state.transactions[&tx_id(0xac)].gas_used;
        assert_eq!(legacy_stored_gas_used, transaction_gas_limit);
        assert_ne!(legacy_stored_gas_used, receipt_actual_gas_used);

        let mut current = TestEvent::transfer(1, 0xad, "44", PositionLookupPlan::NewIdentity);
        current.gas_limit = transaction_gas_limit;
        let current_result =
            reduce_transaction_block(&input(5, 20_000_000, &[current]), &ReducerState::default()).unwrap();
        let current_stored_gas_used = &current_result.state.transactions[&tx_id(0xad)].gas_used;
        assert_eq!(current_stored_gas_used, "0");
        assert_ne!(current_stored_gas_used, transaction_gas_limit);
        assert_ne!(current_stored_gas_used, receipt_actual_gas_used);
    }

    #[test]
    fn existing_position_calls_helper_once_and_current_forces_zero_gas_used() {
        let mut initial = ReducerState::default();
        initial.positions.insert("42".to_owned(), position("42", 0x11));
        let mut item = TestEvent::transfer(1, 0xcd, "42", PositionLookupPlan::Existing);
        item.gas_limit = "987654";
        item.gas_price = "123456789";
        let result = reduce_transaction_block(&input(5, 20_000_000, &[item]), &initial).unwrap();
        assert_eq!(
            result.outcomes[0].attempted_loads,
            vec![TransactionLoadSite::PositionSnapshot]
        );
        assert_eq!(result.state.positions["42"].transaction, tx_id(0x11));
        assert_eq!(result.state.snapshots["42#20000000"].transaction, tx_id(0xcd));
        let transaction = &result.state.transactions[&tx_id(0xcd)];
        assert_eq!(transaction.gas_used, "0");
        assert_eq!(transaction.gas_price, "123456789");
    }

    #[test]
    fn unconditional_upsert_overwrites_every_transaction_field() {
        let id = tx_id(0xef);
        let mut initial = ReducerState::default();
        initial.transactions.insert(
            id.clone(),
            TransactionEntity {
                id: id.clone(),
                block_number: 1,
                timestamp: 2,
                gas_used: "3".to_owned(),
                gas_price: "4".to_owned(),
            },
        );
        let mut item = TestEvent::transfer(1, 0xef, "7", PositionLookupPlan::NewIdentity);
        item.excluded_pool = true;
        item.kind = EventKind::Increase;
        item.gas_limit = "555";
        item.gas_price = "666";
        let result = reduce_transaction_block(&input(0, 12_400_000, &[item]), &initial).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NormalReturn(NormalReturnReason::ExcludedPool)
        );
        assert_eq!(
            result.outcomes[0].attempted_loads,
            vec![TransactionLoadSite::PositionCreation]
        );
        assert_eq!(
            result.state.transactions[&id],
            TransactionEntity {
                id,
                block_number: 12_400_000,
                timestamp: 1_700_000_123,
                gas_used: "555".to_owned(),
                gas_price: "666".to_owned(),
            }
        );
        assert!(!result.state.positions.contains_key("7"));
        assert!(result.state.snapshots.is_empty());
    }

    #[test]
    fn current_missing_tokens_normal_return_can_leave_new_identity_orphan() {
        let event = TestEvent::increase(
            1,
            0x21,
            "8",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Neither,
        );
        let result = reduce_transaction_block(&input(5, 20_000_000, &[event]), &ReducerState::default()).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NormalReturn(NormalReturnReason::MissingToken)
        );
        assert_eq!(
            result.outcomes[0].attempted_loads,
            vec![TransactionLoadSite::PositionCreation]
        );
        assert!(result.state.transactions.contains_key(&tx_id(0x21)));
        assert!(result.state.positions.is_empty());
        assert!(result.state.snapshots.is_empty());

        let mut existing = ReducerState::default();
        existing.positions.insert("8".to_owned(), position("8", 0x19));
        let event = TestEvent::increase(1, 0x22, "8", PositionLookupPlan::Existing, TokenAvailability::Neither);
        let result = reduce_transaction_block(&input(5, 20_000_000, &[event]), &existing).unwrap();
        assert!(result.outcomes[0].attempted_loads.is_empty());
        assert!(!result.state.transactions.contains_key(&tx_id(0x22)));
    }

    #[test]
    fn orphan_transaction_then_later_same_token_success_creates_relations() {
        let mut orphan = TestEvent::increase(1, 0x23, "8", PositionLookupPlan::NewIdentity, TokenAvailability::Both);
        orphan.excluded_pool = true;
        let success = TestEvent::transfer(2, 0x24, "8", PositionLookupPlan::NewIdentity);
        let result =
            reduce_transaction_block(&input(5, 20_000_000, &[orphan, success]), &ReducerState::default()).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NormalReturn(NormalReturnReason::ExcludedPool)
        );
        assert_eq!(
            result.outcomes[0].attempted_loads,
            vec![TransactionLoadSite::PositionCreation]
        );
        assert_eq!(
            result.outcomes[1].attempted_loads,
            vec![
                TransactionLoadSite::PositionCreation,
                TransactionLoadSite::PositionSnapshot
            ]
        );
        assert!(result.state.transactions.contains_key(&tx_id(0x23)));
        assert!(result.state.transactions.contains_key(&tx_id(0x24)));
        assert_eq!(result.state.positions["8"].transaction, tx_id(0x24));
        assert_eq!(result.state.snapshots["8#20000000"].transaction, tx_id(0x24));
    }

    #[test]
    fn decrease_success_and_missing_token_fatal_nonfatal_policies() {
        let success = TestEvent::decrease(1, 0x25, "25", PositionLookupPlan::NewIdentity, TokenAvailability::Both);
        let result = reduce_transaction_block(&input(0, 12_400_000, &[success]), &ReducerState::default()).unwrap();
        assert_eq!(result.disposition, BlockDisposition::Committed);
        assert_eq!(result.outcomes[0].disposition, EventDisposition::Committed);
        assert_eq!(result.state.positions["25"].transaction, tx_id(0x25));

        let missing_fatal = TestEvent::decrease(
            1,
            0x26,
            "26",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Token0Only,
        );
        let result =
            reduce_transaction_block(&input(0, 12_400_000, &[missing_fatal]), &ReducerState::default()).unwrap();
        assert!(matches!(
            result.disposition,
            BlockDisposition::FatalTransactionUserEntityProjection {
                ordinal: 1,
                omitted_event_count: 0,
                ..
            }
        ));
        assert_eq!(result.state, ReducerState::default());
        assert_eq!(
            result.outcomes[0].attempted_loads,
            vec![TransactionLoadSite::PositionCreation]
        );

        let missing_nonfatal = TestEvent::decrease(
            1,
            0x27,
            "27",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Token0Only,
        );
        let following_success = TestEvent::transfer(2, 0x28, "28", PositionLookupPlan::NewIdentity);
        let result = reduce_transaction_block(
            &input(6, 2_000_000, &[missing_nonfatal, following_success]),
            &ReducerState::default(),
        )
        .unwrap();
        assert_eq!(result.disposition, BlockDisposition::Committed);
        assert!(matches!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert!(!result.state.transactions.contains_key(&tx_id(0x27)));
        assert!(result.state.transactions.contains_key(&tx_id(0x28)));
    }

    #[test]
    fn fatal_legacy_error_returns_baseline_projection_and_omits_later_events() {
        let first = TestEvent::transfer(1, 0x31, "1", PositionLookupPlan::NewIdentity);
        let second = TestEvent::increase(
            2,
            0x32,
            "2",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Token0Only,
        );
        let third = TestEvent::transfer(3, 0x33, "3", PositionLookupPlan::NewIdentity);
        let baseline = ReducerState::default();
        let result = reduce_transaction_block(&input(0, 12_400_000, &[first, second, third]), &baseline).unwrap();
        assert!(matches!(
            result.disposition,
            BlockDisposition::FatalTransactionUserEntityProjection {
                ordinal: 2,
                omitted_event_count: 1,
                ..
            }
        ));
        assert_eq!(result.state, baseline);
        assert_eq!(result.outcomes.len(), 2);
        assert!(!result.outcomes[0].block_state_committed);
        assert_eq!(
            result.outcomes[1].attempted_loads,
            vec![TransactionLoadSite::PositionCreation]
        );
        assert!(!result.outcomes[1].event_state_committed);
    }

    #[test]
    fn base_root_nonfatal_error_discards_event_scratch_and_continues() {
        let bad = TestEvent::increase(
            1,
            0x41,
            "1",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Token0Only,
        );
        let good = TestEvent::transfer(2, 0x42, "2", PositionLookupPlan::NewIdentity);
        let result = reduce_transaction_block(&input(6, 2_000_000, &[bad, good]), &ReducerState::default()).unwrap();
        assert_eq!(result.disposition, BlockDisposition::Committed);
        assert!(matches!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert!(!result.state.transactions.contains_key(&tx_id(0x41)));
        assert!(result.state.transactions.contains_key(&tx_id(0x42)));
        assert!(result.state.positions.contains_key("2"));
    }

    #[test]
    fn failure_after_second_helper_call_discards_entity_state_nonfatally() {
        let mut event = TestEvent::transfer(1, 0x51, "9", PositionLookupPlan::NewIdentity);
        event.failure = FailurePhase::AfterSnapshotLoad;
        let id = tx_id(0x51);
        let sentinel = TransactionEntity {
            id: id.clone(),
            block_number: 123,
            timestamp: 456,
            gas_used: "789".to_owned(),
            gas_price: "101112".to_owned(),
        };
        let mut initial = ReducerState::default();
        initial.transactions.insert(id.clone(), sentinel.clone());
        let result = reduce_transaction_block(&input(5, 20_000_000, &[event]), &initial).unwrap();
        assert_eq!(
            result.outcomes[0].attempted_loads,
            vec![
                TransactionLoadSite::PositionCreation,
                TransactionLoadSite::PositionSnapshot
            ]
        );
        assert!(matches!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert_eq!(result.state, initial);
        assert_eq!(result.state.transactions[&id], sentinel);
        assert!(!result.state.positions.contains_key("9"));
        assert!(result.state.snapshots.is_empty());
    }

    #[test]
    fn base_root_guard_covers_increase_and_decrease_before_identity() {
        for mut event in [
            TestEvent::increase(1, 0x61, "10", PositionLookupPlan::NotConsulted, TokenAvailability::Both),
            TestEvent::decrease(
                1,
                0x62,
                "11",
                PositionLookupPlan::NotConsulted,
                TokenAvailability::Neither,
            ),
        ] {
            event.excluded_pool = true;
            let result =
                reduce_transaction_block(&input(6, HISTORICAL_GUARD_BLOCK, &[event]), &ReducerState::default())
                    .unwrap();
            assert_eq!(
                result.outcomes[0].disposition,
                EventDisposition::NormalReturn(NormalReturnReason::HistoricalGuard)
            );
            assert!(result.outcomes[0].attempted_loads.is_empty());
            assert!(result.state.transactions.is_empty());
        }
    }

    #[test]
    fn reverted_position_lookup_returns_without_transaction_write() {
        let event = TestEvent::transfer(1, 0x65, "10", PositionLookupPlan::PositionsReverted);
        let result = reduce_transaction_block(&input(5, 20_000_000, &[event]), &ReducerState::default()).unwrap();
        assert_eq!(
            result.outcomes[0].disposition,
            EventDisposition::NormalReturn(NormalReturnReason::PositionsReverted)
        );
        assert!(result.outcomes[0].attempted_loads.is_empty());
        assert!(result.state.transactions.is_empty());
    }

    #[test]
    fn deterministic_identity_error_discards_entity_state_before_helper_nonfatally() {
        let bad = TestEvent::transfer(1, 0x63, "10", PositionLookupPlan::DeterministicError);
        let good = TestEvent::transfer(2, 0x64, "11", PositionLookupPlan::NewIdentity);
        let result = reduce_transaction_block(&input(5, 20_000_000, &[bad, good]), &ReducerState::default()).unwrap();
        assert!(matches!(
            result.outcomes[0].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert!(result.outcomes[0].attempted_loads.is_empty());
        assert!(!result.state.transactions.contains_key(&tx_id(0x63)));
        assert!(result.state.transactions.contains_key(&tx_id(0x64)));
    }

    #[test]
    fn position_keeps_first_transaction_while_snapshot_tracks_current_event() {
        let first = TestEvent::transfer(1, 0x71, "77", PositionLookupPlan::NewIdentity);
        let second = TestEvent::transfer(2, 0x72, "77", PositionLookupPlan::Existing);
        let result =
            reduce_transaction_block(&input(5, 20_000_000, &[first, second]), &ReducerState::default()).unwrap();
        assert_eq!(result.state.positions["77"].transaction, tx_id(0x71));
        assert_eq!(result.state.snapshots["77#20000000"].transaction, tx_id(0x72));
        assert_eq!(result.outcomes[0].position_transaction_written, Some(tx_id(0x71)));
        assert_eq!(result.outcomes[1].position_transaction_written, None);
        assert_eq!(result.outcomes[1].snapshot_transaction_written, Some(tx_id(0x72)));
    }

    #[test]
    fn same_and_different_transactions_interleave_deterministically() {
        let first = TestEvent::transfer(1, 0x81, "1", PositionLookupPlan::NewIdentity);
        let second = TestEvent::transfer(2, 0x82, "2", PositionLookupPlan::NewIdentity);
        let third = TestEvent::transfer(3, 0x81, "1", PositionLookupPlan::Existing);
        let result =
            reduce_transaction_block(&input(5, 20_000_000, &[first, second, third]), &ReducerState::default()).unwrap();
        assert_eq!(result.state.transactions.len(), 2);
        assert_eq!(result.state.positions["1"].transaction, tx_id(0x81));
        assert_eq!(result.state.positions["2"].transaction, tx_id(0x82));
        assert_eq!(result.state.snapshots["1#20000000"].transaction, tx_id(0x81));
        assert_eq!(
            result.outcomes[2].attempted_loads,
            vec![TransactionLoadSite::PositionSnapshot]
        );
    }

    #[test]
    fn collect_token_requirements_follow_all_deployed_profiles() {
        let middle = TestEvent::collect(
            1,
            0x91,
            "1",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Neither,
        );
        let middle_result =
            reduce_transaction_block(&input(2, 13_500_000, &[middle]), &ReducerState::default()).unwrap();
        assert_eq!(middle_result.outcomes[0].disposition, EventDisposition::Committed);

        let base_token0 = TestEvent::collect(
            1,
            0x92,
            "2",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Token0Only,
        );
        let base_result =
            reduce_transaction_block(&input(6, 2_000_000, &[base_token0]), &ReducerState::default()).unwrap();
        assert_eq!(base_result.outcomes[0].disposition, EventDisposition::Committed);

        let base_missing_token0 = TestEvent::collect(
            1,
            0x93,
            "3",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Token1Only,
        );
        let base_result =
            reduce_transaction_block(&input(6, 2_000_000, &[base_missing_token0]), &ReducerState::default()).unwrap();
        assert!(matches!(
            base_result.outcomes[0].disposition,
            EventDisposition::NonFatalError(_)
        ));
        assert!(base_result.state.transactions.is_empty());

        let current = TestEvent::collect(
            1,
            0x94,
            "4",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Neither,
        );
        let current_result =
            reduce_transaction_block(&input(5, 20_000_000, &[current]), &ReducerState::default()).unwrap();
        assert_eq!(current_result.outcomes[0].disposition, EventDisposition::Committed);
    }

    #[test]
    fn producer_corruption_is_rejected_before_nonfatal_policy() {
        let event = TestEvent::transfer(1, 0xa1, "1", PositionLookupPlan::NewIdentity);
        let valid = input(5, 20_000_000, &[event]);
        let mutations = ["metadata", "order", "gas", "hash", "control"];
        for mutation in mutations {
            let mut candidate = valid.clone();
            match mutation {
                "metadata" => candidate.transactions.clear(),
                "order" => {
                    candidate
                        .writer_events
                        .events
                        .push(candidate.writer_events.events[0].clone());
                    candidate.writer_events.events[1].ordinal = 1;
                    candidate.writer_events.events[1].block_log_index = 1;
                }
                "gas" => "01".clone_into(&mut candidate.transactions[0].gas_price),
                "hash" => {
                    candidate.writer_events.events[0].transaction_hash.pop();
                }
                "control" => candidate.controls.clear(),
                _ => unreachable!(),
            }
            assert!(
                reduce_transaction_block(&candidate, &ReducerState::default()).is_err(),
                "mutation {mutation} escaped"
            );
        }
    }

    #[test]
    fn inconsistent_lookup_and_unreachable_failure_plans_fail_closed() {
        let existing = TestEvent::transfer(1, 0xb1, "1", PositionLookupPlan::Existing);
        assert!(reduce_transaction_block(&input(5, 20_000_000, &[existing]), &ReducerState::default()).is_err());

        let mut early = TestEvent::increase(
            1,
            0xb2,
            "2",
            PositionLookupPlan::NewIdentity,
            TokenAvailability::Neither,
        );
        early.failure = FailurePhase::AfterSnapshotLoad;
        assert!(reduce_transaction_block(&input(5, 20_000_000, &[early]), &ReducerState::default()).is_err());
    }
}
