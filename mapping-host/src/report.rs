//! The run report: what happened, per block, per handler, in order.
//!
//! Every map is a `BTreeMap` and every list is emitted in execution order, so the
//! JSON is byte-stable for a given input and can be golden-filed.
//!
//! The four ordering fields are the metadata `BlockChanges` v1 needs in phase 2:
//!
//! * `handler_group_order` — one value per `start_handler`, monotonic and dense
//!   within a block. It is the only ordering field that survives re-processing.
//! * `stage` — the wave. Wave 0 is the manifest data sources; each later wave is
//!   one round of dynamically created data sources.
//! * `source_trigger_order` — the trigger's index within *that wave's* sorted
//!   trigger list. It is stage-local, so it may repeat or regress between handler
//!   groups; that is correct and expected, not a bug.
//! * `handler_order` — the host's index within one blockchain trigger.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// Schema identifier written into every report.
pub const REPORT_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.report/v1";

/// One entity modification, as `EntityCache::as_modifications` produced it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ModificationReport {
    /// `insert`, `overwrite` or `remove`.
    pub op: String,
    pub entity: String,
    pub id: String,
    /// The sequence-generated VID. Shared across the whole block.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub vid: Option<i64>,
    /// The full field set after the write, keys sorted. Absent for `remove`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<BTreeMap<String, serde_json::Value>>,
}

/// A data source the mapping asked to create.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CreatedDataSourceReport {
    pub template: String,
    pub params: Vec<String>,
    pub creation_block: i32,
}

/// One host running one handler for one trigger.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HandlerReport {
    pub handler_order: usize,
    pub data_source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data_source_address: Option<String>,
    pub handler: String,
    /// Gas consumed by the handler.
    ///
    /// Always `null`: `RuntimeHost::process_mapping_trigger` discards the `Gas`
    /// that `WasmInstance::handle_trigger` returns (`runtime/wasm/src/host.rs:224`,
    /// `result.map(|(block_state, _)| block_state)`), and the request plumbing
    /// that carries it is `pub(crate)`. Reaching it needs the same vendored
    /// graph-node patch phase 2 needs for the per-save operation stream.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gas: Option<u64>,
    /// `ok` or `deterministic_error`.
    pub outcome: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    /// Sorted by `(entity, id)`, **not** by the order the mapping saved them.
    /// `EntityCache` collapses writes into a `HashMap`, so intra-handler save
    /// order is not observable through graph-node's public API.
    pub modifications: Vec<ModificationReport>,
    pub created_data_sources: Vec<CreatedDataSourceReport>,
}

/// The trigger a handler group ran for.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TriggerReport {
    pub transaction_hash: String,
    pub log_index: u64,
    pub address: String,
}

/// One `start_handler` and everything that ran under it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HandlerGroupReport {
    pub handler_group_order: u32,
    pub stage: usize,
    pub source_trigger_order: usize,
    pub causality_region: String,
    pub trigger: TriggerReport,
    pub handlers: Vec<HandlerReport>,
}

/// The PoI for one block.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PoiReport {
    pub version: String,
    /// Causality region to its stored digest, hex without `0x`.
    pub causality_regions: BTreeMap<String, String>,
    /// The public PoI, hex without `0x`.
    pub public_digest: String,
}

/// One block.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct BlockReport {
    pub number: i32,
    pub hash: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_hash: Option<String>,
    pub timestamp: i64,
    /// True when at least one handler ran, even if it wrote nothing.
    pub mapping_triggered: bool,
    /// Sorted trigger count per wave; the length is the number of waves.
    pub triggers_per_stage: Vec<usize>,
    /// Hosts active at the start of each wave.
    pub hosts_per_stage: Vec<usize>,
    pub handler_groups: Vec<HandlerGroupReport>,
    pub created_data_sources: Vec<CreatedDataSourceReport>,
    pub deterministic_errors: Vec<String>,
    /// `fatal` for a manifest without `nonFatalErrors`, `non_fatal` otherwise.
    pub deterministic_error_policy: String,
    /// True when a deterministic error occurred under a `fatal` policy, in which
    /// case Graph Node discards every non-PoI write in the block.
    pub block_discarded: bool,
    pub modification_count: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub poi: Option<PoiReport>,
    /// Live rows per entity type after this block.
    pub store_counts: BTreeMap<String, usize>,
}

/// A whole run.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RunReport {
    pub schema: String,
    pub deployment: String,
    pub network: String,
    pub spec_version: String,
    pub api_versions: Vec<String>,
    pub features: Vec<String>,
    pub graph_node_rev: String,
    pub blocks: Vec<BlockReport>,
    /// Cassette rows the run consulted or recorded.
    pub cassette_entries: usize,
}

impl RunReport {
    pub fn new(deployment: String, network: String, spec_version: String) -> Self {
        RunReport {
            schema: REPORT_SCHEMA.to_string(),
            deployment,
            network,
            spec_version,
            api_versions: Vec::new(),
            features: Vec::new(),
            graph_node_rev: crate::runner::GRAPH_NODE_REV.to_string(),
            blocks: Vec::new(),
            cassette_entries: 0,
        }
    }

    /// Pretty JSON with a trailing newline, byte-stable for a given run.
    pub fn to_json(&self) -> anyhow::Result<String> {
        let mut json = serde_json::to_string_pretty(self)?;
        json.push('\n');
        Ok(json)
    }
}
