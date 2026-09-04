//! The per-block pipeline: waves, hosts, handler groups.
//!
//! This is a faithful reimplementation of `SubgraphRunner::process_block`
//! (`core/src/subgraph/runner/mod.rs:1071`) and `process_dynamic_data_sources`
//! (`:924`), restricted to what a hermetic replay needs. `SubgraphRunner` itself
//! is not reusable — it wants an `IndexingContext`, a `WritableStore` and a block
//! stream — but the two places determinism actually lives are reused verbatim:
//! `BlockWithTriggers::new` for the sort and dedup, and
//! `RuntimeHost::match_and_decode` for matching and decoding.
//!
//! ## The wave model
//!
//! Stage 0 runs every host that exists at the start of the block over that
//! block's sorted triggers, trigger-major and host-minor. Handlers that create
//! data sources queue them. After the stage, the queue is drained in creation
//! order, non-duplicate hosts are instantiated, the **same block** is re-scanned
//! for triggers matching only those new hosts, and the stage repeats. Breadth
//! first over the parent/child tree.
//!
//! A dynamic data source is gated by its creation *block* only
//! (`chain/ethereum/src/data_source.rs:700`, `self.start_block > block.number()`),
//! with no creation-log-ordinal gate. So a Pool log with a *lower* log index than
//! the `PoolCreated` that created that pool still runs, in the later wave.
//!
//! ## What could not be reproduced through public API
//!
//! * **Per-handler gas.** `RuntimeHost::process_mapping_trigger` throws the `Gas`
//!   away (`runtime/wasm/src/host.rs:224`) and `WasmRequest` is `pub(crate)`.
//!   Reported as `null`.
//! * **Per-`store.set` ordering.** `EntityCache` collapses writes into a
//!   `HashMap`; ordering inside one handler is not observable without patching
//!   `HostExports`. Phase 1 reports one ordered modification set per handler,
//!   which is exact at handler granularity.
//! * **`parse_log_triggers` and `EthereumLogFilter`.** Both `pub(crate)`;
//!   reproduced in [`crate::block`].
//! * **`SubgraphTriggerProcessor`.** Lives in `graph-core`, which we do not
//!   depend on; its twenty-line body is reproduced in [`SegmentHost::run_group`].

use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use graph::blockchain::{Block as _, BlockPtr};
use graph::cheap_clone::CheapClone;
use graph::components::metrics::gas::GasMetrics;
use graph::components::metrics::MetricsRegistry;
use graph::components::store::write::EntityModification;
use graph::components::store::{EntityLfuCache, ModificationsAndCache, SeqGenerator};
use graph::components::subgraph::{
    BlockState, HostMetrics, MappingError, PoICausalityRegion, ProofOfIndexingVersion,
    SharedProofOfIndexing,
};
use graph::data::subgraph::{DeploymentHash, SubgraphFeature};
use graph::data_source::{DataSource, DataSourceTemplate, TriggerData};
use graph::prelude::{
    o, slog, InstanceDSTemplateInfo, Logger, RuntimeHost as RuntimeHostTrait,
    RuntimeHostBuilder as RuntimeHostBuilderTrait, StopwatchMetrics,
};
use graph_chain_ethereum::chain::BlockFinality;
use graph_chain_ethereum::trigger::EthereumTrigger;
use graph_chain_ethereum::Chain;
use graph_runtime_wasm::RuntimeHostBuilder;

use backfill_common::pb::pinax::graph::backfill::v1 as pb;
use backfill_common::BlockChangesCompatibility;

use crate::block;
use crate::blockchanges::{self, BlockOpsBuilder, OpRecorder};
use crate::bundle::SegmentBundle;
use crate::calls::{Cassette, CassetteMode, CassetteRuntimeAdapter};
use crate::descriptor;
use crate::poi;
use crate::report::{
    BlockReport, CreatedDataSourceReport, HandlerGroupReport, HandlerReport, ModificationReport,
    PoiReport, RunReport, TriggerReport,
};
use crate::store::{MemoryStore, NoEnsLookup};

/// The graph-node revision every artifact in this crate is bound to.
pub const GRAPH_NODE_REV: &str = "77823b5a7adc4eac4abf03202c8dd7cb00dea31d";

/// `graph_runtime_wasm::host` is a private module, so `RuntimeHost` and
/// `WasmRequest` cannot be named directly. Both are reachable as associated
/// types of the builder, which is public.
type Host = <RuntimeHostBuilder<Chain> as RuntimeHostBuilderTrait<Chain>>::Host;
type MappingRequest = <RuntimeHostBuilder<Chain> as RuntimeHostBuilderTrait<Chain>>::Req;
type MappingSender = graph::futures01::sync::mpsc::Sender<MappingRequest>;

/// How to build a [`SegmentHost`].
pub struct SegmentHostConfig<'a> {
    pub bundle_dir: &'a Path,
    pub cassette_path: &'a Path,
    /// Record misses against `ETHEREUM_RPC_URL` instead of failing closed.
    pub record: bool,
}

/// One block's results: the human-readable report, and the canonical frame.
pub struct BlockOutcome {
    pub report: BlockReport,
    pub changes: pb::BlockChanges,
}

/// A loaded segment, ready to replay blocks.
pub struct SegmentHost {
    logger: Logger,
    deployment: DeploymentHash,
    network: String,
    spec_version: String,
    features: Vec<String>,
    api_versions: Vec<String>,
    templates: Arc<Vec<DataSourceTemplate<Chain>>>,
    builder: RuntimeHostBuilder<Chain>,
    metrics: Arc<HostMetrics>,
    stopwatch: StopwatchMetrics,
    store: Arc<MemoryStore>,
    cassette: Arc<Cassette>,
    hosts: Vec<Arc<Host>>,
    module_cache: HashMap<String, MappingSender>,
    lfu_cache: EntityLfuCache,
    poi_version: ProofOfIndexingVersion,
    errors_are_fatal: bool,
    causality_region: String,
    recorder: Arc<OpRecorder>,
    compatibility: BlockChangesCompatibility,
    descriptor_sha256: String,
    bounds: SegmentBounds,
}

/// The block range this segment's own manifest claims.
///
/// `start` is the first block the deployment itself processes: the lowest
/// `dataSources[].source.startBlock`, or the block after the graft when the
/// manifest grafts, because a graft copies the base deployment up to and
/// including that block.
///
/// `end` is only `Some` when *every* data source declares an `endBlock`, which
/// none of the deployed Uniswap V3 manifests do. A segment's upper bound in the
/// deployment succession is a repository fact, not a manifest fact, so it cannot
/// be enforced from a bundle; see `README.md`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SegmentBounds {
    pub start: i32,
    pub end: Option<i32>,
}

impl SegmentBounds {
    /// Refuse a half-open `[from, to)` range that leaves this segment.
    pub fn check_range(&self, from: i32, to: i32) -> Result<()> {
        if to <= from {
            bail!("--from {from} --to {to} is an empty range; --to is exclusive and must exceed --from");
        }
        if from < self.start {
            bail!(
                "--from {from} is below this segment's first block {}; the deployment does not \
                 process anything earlier, so the store and the PoI chain would start from a \
                 block the mapping never saw",
                self.start
            );
        }
        if let Some(end) = self.end {
            if to - 1 > end {
                bail!(
                    "--to {to} reaches block {} but this segment's manifest ends at {end}",
                    to - 1
                );
            }
        }
        Ok(())
    }
}

impl SegmentHost {
    /// Load a bundle, resolve its manifest through graph-node, and instantiate a
    /// host for every manifest data source, in manifest order.
    pub async fn load(config: SegmentHostConfig<'_>) -> Result<Self> {
        crate::env_pin::pin();

        let logger = Logger::root(slog::Discard, o!());
        let bundle = SegmentBundle::load(config.bundle_dir)?;
        let manifest = bundle.manifest(&logger).await?;

        let mode = if config.record {
            let rpc_url = std::env::var("ETHEREUM_RPC_URL").map_err(|_| {
                anyhow!("--record needs ETHEREUM_RPC_URL; no endpoint is compiled in")
            })?;
            CassetteMode::Record { rpc_url }
        } else {
            CassetteMode::Replay
        };
        let cassette = Arc::new(Cassette::load(config.cassette_path, mode)?);

        let deployment = manifest.id.cheap_clone();
        let network = manifest.network_name();
        let spec_version = manifest.spec_version.to_string();
        let errors_are_fatal = !manifest.features.contains(&SubgraphFeature::NonFatalErrors);
        let poi_version = poi::version_for_spec(&manifest.spec_version);
        let features: Vec<String> = manifest.features.iter().map(|f| f.to_string()).collect();

        let registry = Arc::new(MetricsRegistry::mock());
        let stopwatch = StopwatchMetrics::new(
            logger.cheap_clone(),
            deployment.cheap_clone(),
            "mapping-host",
            registry.cheap_clone(),
            "hermetic".to_string(),
        );
        let gas_metrics = GasMetrics::new(deployment.cheap_clone(), registry.cheap_clone());
        let metrics = Arc::new(HostMetrics::new(
            registry,
            deployment.as_str(),
            stopwatch.cheap_clone(),
            gas_metrics,
        ));

        let schema = manifest.schema.cheap_clone();
        let store = Arc::new(MemoryStore::new(schema));

        // The recorder is the whole point of the vendored graph-runtime-wasm: it
        // observes every store effect beside the PoI write that hashes it, in
        // call order, which `EntityCache` cannot report.
        let recorder = Arc::new(OpRecorder::new());
        let builder = RuntimeHostBuilder::<Chain>::new(
            Arc::new(CassetteRuntimeAdapter::new(cassette.cheap_clone())),
            bundle.link_resolver(),
            Arc::new(NoEnsLookup),
        )
        .with_op_recorder(Some(recorder.clone()));

        let (compatibility, descriptor_sha256) = descriptor::load(config.bundle_dir)?;
        let expected_policy = if errors_are_fatal {
            pb::DeterministicErrorPolicy::Fatal
        } else {
            pb::DeterministicErrorPolicy::NonFatal
        };
        if compatibility.deterministic_error_policy() != expected_policy {
            bail!(
                "descriptor declares a {:?} deterministic-error policy, but the manifest's \
                 features say {:?}",
                compatibility.deterministic_error_policy(),
                expected_policy
            );
        }
        if compatibility.expected_poi_causality_region()
            != PoICausalityRegion::from_network(&network)
        {
            bail!(
                "descriptor expects PoI causality region `{}`, but this segment's network is `{}`",
                compatibility.expected_poi_causality_region(),
                network
            );
        }

        let templates = Arc::new(manifest.templates.clone());
        let mut api_versions: Vec<String> = manifest
            .data_sources
            .iter()
            .filter_map(|ds| ds.as_onchain())
            .map(|ds| ds.mapping.api_version.to_string())
            .collect();
        api_versions.sort();
        api_versions.dedup();

        let causality_region = PoICausalityRegion::from_network(&network);

        // `start_blocks()` is graph-node's own accessor; `end_block()` is only
        // set when a manifest declares one, which is why `end` collapses to
        // `None` unless every data source has one.
        let manifest_start =
            manifest.start_blocks().into_iter().min().ok_or_else(|| {
                anyhow!("the manifest declares no data source with a start block")
            })?;
        let graft_start = manifest.graft.as_ref().map(|graft| graft.block + 1);
        let end_blocks: Vec<Option<i32>> = manifest
            .data_sources
            .iter()
            .map(|ds| ds.end_block())
            .collect();
        let bounds = SegmentBounds {
            start: manifest_start.max(graft_start.unwrap_or(i32::MIN)),
            end: if end_blocks.iter().all(Option::is_some) {
                end_blocks.into_iter().flatten().max()
            } else {
                None
            },
        };

        let mut host = SegmentHost {
            logger,
            deployment,
            network,
            spec_version,
            features,
            api_versions,
            templates,
            builder,
            metrics,
            stopwatch,
            store,
            cassette,
            hosts: Vec::new(),
            module_cache: HashMap::new(),
            lfu_cache: EntityLfuCache::default(),
            poi_version,
            errors_are_fatal,
            causality_region,
            recorder,
            compatibility,
            descriptor_sha256,
            bounds,
        };

        // Manifest data sources first, in manifest order. That order feeds host
        // insertion order, which is what `handler_order` indexes.
        for ds in manifest.data_sources.iter() {
            let runtime_host = host.new_host(ds.clone())?;
            match runtime_host {
                Some(h) => host.hosts.push(h),
                None => bail!("manifest data source `{}` has no runtime", ds.name()),
            }
        }

        Ok(host)
    }

    pub fn deployment(&self) -> &DeploymentHash {
        &self.deployment
    }

    pub fn cassette(&self) -> &Arc<Cassette> {
        &self.cassette
    }

    pub fn compatibility(&self) -> &BlockChangesCompatibility {
        &self.compatibility
    }

    pub fn descriptor_sha256(&self) -> &str {
        &self.descriptor_sha256
    }

    /// The block range this segment's manifest claims.
    pub fn bounds(&self) -> SegmentBounds {
        self.bounds
    }

    fn error_policy(&self) -> pb::DeterministicErrorPolicy {
        if self.errors_are_fatal {
            pb::DeterministicErrorPolicy::Fatal
        } else {
            pb::DeterministicErrorPolicy::NonFatal
        }
    }

    /// Start a report for a run over this segment.
    pub fn new_report(&self) -> RunReport {
        let mut report = RunReport::new(
            self.deployment.to_string(),
            self.network.clone(),
            self.spec_version.clone(),
        );
        report.api_versions = self.api_versions.clone();
        report.features = self.features.clone();
        report
    }

    /// `SubgraphInstance::new_host` (`core/src/subgraph/context/instance/mod.rs:96`).
    /// One WASM thread per distinct module, shared by every data source that uses
    /// it — without this, one Pool template instance per pool would mean one
    /// thread per pool.
    fn new_host(&mut self, data_source: DataSource<Chain>) -> Result<Option<Arc<Host>>> {
        let Some(module_bytes) = data_source.runtime() else {
            return Ok(None);
        };
        let module_key = crate::bundle::sha256_hex(module_bytes.as_ref());
        let sender = match self.module_cache.get(&module_key) {
            Some(sender) => sender.clone(),
            None => {
                let sender =
                    <RuntimeHostBuilder<Chain> as RuntimeHostBuilderTrait<Chain>>::spawn_mapping(
                        module_bytes.as_ref(),
                        self.logger.cheap_clone(),
                        self.deployment.cheap_clone(),
                        self.metrics.cheap_clone(),
                    )?;
                self.module_cache.insert(module_key, sender.clone());
                sender
            }
        };

        let host = self.builder.build(
            self.network.clone(),
            self.deployment.cheap_clone(),
            data_source,
            self.templates.cheap_clone(),
            sender,
            self.metrics.cheap_clone(),
        )?;
        Ok(Some(Arc::new(host)))
    }

    /// `SubgraphRunner::create_dynamic_data_sources` (`runner/mod.rs:1222`) plus
    /// `SubgraphInstance::add_dynamic_data_source` (`instance/mod.rs:132`).
    /// Returns the hosts that were actually added, preserving creation order and
    /// skipping duplicates.
    fn create_dynamic_data_sources(
        &mut self,
        created: Vec<InstanceDSTemplateInfo>,
    ) -> Result<Vec<Arc<Host>>> {
        let mut added = Vec::new();
        for info in created {
            let manifest_idx = info
                .template
                .manifest_idx()
                .ok_or_else(|| anyhow!("created data source template has no manifest index"))?;
            let template = self
                .templates
                .iter()
                .find(|t| t.manifest_idx() == manifest_idx)
                .ok_or_else(|| {
                    anyhow!(
                        "no template with manifest index {manifest_idx} for a created data source"
                    )
                })?
                .clone();

            let onchain = <graph_chain_ethereum::DataSource as graph::blockchain::DataSource<
                Chain,
            >>::from_template_info(info, &template)
            .context("instantiating a dynamic data source")?;
            let data_source = DataSource::Onchain(onchain);

            let Some(host) = self.new_host(data_source)? else {
                continue;
            };
            // `RuntimeHost: PartialEq` is `DataSource::is_duplicate_of`, which
            // deliberately ignores the creation block.
            if self.hosts.contains(&host) {
                continue;
            }
            self.hosts.push(host.cheap_clone());
            added.push(host);
        }
        Ok(added)
    }

    /// Replay one block.
    pub async fn process_block(&mut self, raw_block: BlockFinality) -> Result<BlockOutcome> {
        let identity = block::identify(&raw_block);
        let shared_block = Arc::new(raw_block);
        let block_ptr: BlockPtr = shared_block.ptr();
        let block_time = shared_block.timestamp();

        let proof_of_indexing = SharedProofOfIndexing::new(block_ptr.number, self.poi_version);
        let seq_gen = SeqGenerator::new(block_ptr.number);

        let mut report = BlockReport {
            number: identity.number,
            hash: identity.hash,
            parent_hash: identity.parent_hash,
            timestamp: identity.timestamp,
            mapping_triggered: false,
            triggers_per_stage: Vec::new(),
            hosts_per_stage: Vec::new(),
            handler_groups: Vec::new(),
            created_data_sources: Vec::new(),
            deterministic_errors: Vec::new(),
            deterministic_error_policy: if self.errors_are_fatal {
                "fatal".to_string()
            } else {
                "non_fatal".to_string()
            },
            block_discarded: false,
            modification_count: 0,
            poi: None,
            store_counts: BTreeMap::new(),
            block_changes: None,
        };

        // Snapshot for the fatal-policy rollback below. Under a manifest without
        // `nonFatalErrors`, one deterministic error makes Graph Node keep only
        // the PoI write and discard everything else in the block
        // (`runner/mod.rs:731`, `mods.retain(is_poi_entity)`), so the store must
        // not carry forward writes earlier handlers in the block made.
        let pre_block = self.store.snapshot();

        // Anything the previous block left behind would be attributed to this
        // one; a non-empty drain here is a bug, not a recoverable state.
        let stale = self.recorder.drain();
        if !stale.is_empty() {
            bail!(
                "{} recorded operations leaked across a block boundary",
                stale.len()
            );
        }
        let mut ops = BlockOpsBuilder::new();

        let mut handler_group_order: u32 = 0;
        let mut stage: usize = 0;
        // Hosts this stage runs. Stage 0 is every host that already exists.
        let mut stage_hosts: Vec<Arc<Host>> = self.hosts.clone();
        let mut pending: Vec<InstanceDSTemplateInfo> = Vec::new();

        loop {
            let data_sources: Vec<&graph_chain_ethereum::DataSource> = stage_hosts
                .iter()
                .filter_map(|h| h.data_source().as_onchain())
                .collect();
            let triggers = block::block_triggers(&shared_block, &data_sources, &self.logger)?;
            report.triggers_per_stage.push(triggers.len());
            report.hosts_per_stage.push(stage_hosts.len());

            for (source_trigger_order, trigger) in triggers.iter().enumerate() {
                let group = self
                    .run_group(
                        &shared_block,
                        trigger,
                        &stage_hosts,
                        &proof_of_indexing,
                        &seq_gen,
                        block_ptr.number,
                        stage,
                        source_trigger_order,
                        handler_group_order,
                        &mut pending,
                        &mut report,
                        &mut ops,
                    )
                    .await?;
                if let Some(group) = group {
                    handler_group_order += 1;
                    report.handler_groups.push(group);
                }
            }

            if pending.is_empty() {
                break;
            }
            let created = std::mem::take(&mut pending);
            let added = self.create_dynamic_data_sources(created)?;
            if added.is_empty() {
                break;
            }
            stage_hosts = added;
            stage += 1;
        }

        report.mapping_triggered = !report.handler_groups.is_empty();
        report.block_discarded = self.errors_are_fatal && !report.deterministic_errors.is_empty();
        if report.block_discarded {
            // Roll the store back to the start of the block. The PoI write below
            // is applied on top, which is exactly the one modification Graph Node
            // keeps. The entity cache is dropped rather than rewound, because it
            // is only a cache: the next read repopulates it from the store.
            self.store.restore(pre_block);
            self.lfu_cache = EntityLfuCache::default();
        }

        // End of block: the PoI entity, then the public digest.
        if let Some(inner) = proof_of_indexing.into_inner() {
            let mut poi_state = BlockState::new(
                self.store.cheap_clone(),
                std::mem::take(&mut self.lfu_cache),
                seq_gen.cheap_clone(),
            );
            let paused =
                poi::update_proof_of_indexing(inner, block_time, &mut poi_state.entity_cache)
                    .await?;
            let ModificationsAndCache {
                modifications,
                entity_lfu_cache,
                ..
            } = poi_state
                .entity_cache
                .as_modifications(block_ptr.number, &self.stopwatch)
                .await?;
            self.lfu_cache = entity_lfu_cache;
            self.store.apply(&modifications);

            if !paused.is_empty() {
                let finished = poi::finish(&block_ptr, &self.deployment, self.poi_version, &paused);
                report.poi = Some(PoiReport {
                    version: match self.poi_version {
                        ProofOfIndexingVersion::Fast => "fast".to_string(),
                        ProofOfIndexingVersion::Legacy => "legacy".to_string(),
                    },
                    causality_regions: finished.causality_regions,
                    public_digest: finished.public_digest,
                });
            }
        }

        report.store_counts = self.store.counts_by_type();

        let triggered_regions = if report.mapping_triggered {
            vec![self.causality_region.clone()]
        } else {
            Vec::new()
        };
        let changes = ops
            .finish(
                &self.compatibility,
                block_ptr.number as u64,
                block_ptr.hash_slice().to_vec(),
                report.mapping_triggered,
                triggered_regions,
                self.error_policy(),
            )
            .with_context(|| format!("building BlockChanges for block {}", block_ptr.number))?;

        Ok(BlockOutcome { report, changes })
    }

    /// `SubgraphTriggerProcessor::process_trigger`
    /// (`core/src/subgraph/trigger_processor.rs:24`), reproduced because
    /// `graph-core` is not a dependency.
    ///
    /// `start_handler` fires once per trigger that has at least one matching
    /// host, never for a trigger no host matches. A deterministic error anywhere
    /// in the group appends one `DeterministicError` PoI event after the group,
    /// counting every event since that group's `start_handler`.
    #[allow(clippy::too_many_arguments)]
    async fn run_group(
        &mut self,
        shared_block: &Arc<BlockFinality>,
        trigger: &EthereumTrigger,
        stage_hosts: &[Arc<Host>],
        proof_of_indexing: &SharedProofOfIndexing,
        seq_gen: &SeqGenerator,
        block_number: i32,
        stage: usize,
        source_trigger_order: usize,
        handler_group_order: u32,
        pending: &mut Vec<InstanceDSTemplateInfo>,
        report: &mut BlockReport,
        ops: &mut BlockOpsBuilder,
    ) -> Result<Option<HandlerGroupReport>> {
        let trigger_data = TriggerData::Onchain(trigger.clone());

        // Match and decode against the stage's hosts, in insertion order.
        let mut hosted = Vec::new();
        for host in stage_hosts {
            if let Some(mapping_trigger) =
                host.match_and_decode(&trigger_data, shared_block, &self.logger)?
            {
                hosted.push((host.cheap_clone(), mapping_trigger));
            }
        }
        if hosted.is_empty() {
            return Ok(None);
        }

        proof_of_indexing.start_handler(&self.causality_region);

        let (transaction_hash, log_index, address) = block::trigger_identity(trigger)?;
        let mut group = HandlerGroupReport {
            handler_group_order,
            stage,
            source_trigger_order,
            causality_region: self.causality_region.clone(),
            trigger: TriggerReport {
                transaction_hash,
                log_index,
                address,
            },
            handlers: Vec::new(),
        };

        let mut group_errored: Option<u64> = None;
        for (handler_order, (host, mapping_trigger)) in hosted.into_iter().enumerate() {
            let handler = mapping_trigger.handler_name().to_string();
            let state = BlockState::new(
                self.store.cheap_clone(),
                std::mem::take(&mut self.lfu_cache),
                seq_gen.cheap_clone(),
            );

            let mut state = host
                .process_mapping_trigger(
                    &self.logger,
                    mapping_trigger,
                    state,
                    proof_of_indexing.cheap_clone(),
                    &None,
                    false,
                )
                .await
                .map_err(|e| match e {
                    // A cassette can never produce a `PossibleReorg`; if one
                    // appears the run is not hermetic and must stop.
                    MappingError::PossibleReorg(e) => {
                        anyhow!("non-hermetic failure (possible reorg) in {handler}: {e:#}")
                    }
                    MappingError::Unknown(e) => {
                        anyhow!("non-deterministic failure in {handler}: {e:#}")
                    }
                })?;

            // Drain and project the recorded saves *before* this handler's
            // modifications reach the store: `visible_before` must read the
            // entity as it stood when the handler started.
            let recorded = self.recorder.drain();
            let store = self.store.cheap_clone();
            ops.push_handler(
                u64::from(handler_group_order),
                source_trigger_order as u64,
                handler_order as u64,
                recorded,
                |key| store.lookup(key).map(|e| blockchanges::convert_entity(&e)),
            )?;

            let created = state.drain_created_data_sources();
            let errors = std::mem::take(&mut state.deterministic_errors);
            let ModificationsAndCache {
                modifications,
                entity_lfu_cache,
                ..
            } = state
                .entity_cache
                .as_modifications(block_number, &self.stopwatch)
                .await?;
            self.lfu_cache = entity_lfu_cache;
            self.store.apply(&modifications);

            let created_reports: Vec<CreatedDataSourceReport> = created
                .iter()
                .map(|info| CreatedDataSourceReport {
                    template: info.template.name().to_string(),
                    params: info.params.clone(),
                    creation_block: info.creation_block,
                })
                .collect();
            report
                .created_data_sources
                .extend(created_reports.iter().cloned());
            pending.extend(created);

            let outcome = if errors.is_empty() {
                "ok".to_string()
            } else {
                group_errored = Some(handler_order as u64);
                "deterministic_error".to_string()
            };
            let error = errors.first().map(|e| e.message.clone());
            for e in &errors {
                report.deterministic_errors.push(e.message.clone());
            }

            report.modification_count += modifications.len();

            // `EntityCache::as_modifications` iterates a `HashMap`, so its order
            // is arbitrary and varies between processes. Sort by
            // `(entity type, id)` to make the report reproducible.
            //
            // This is emphatically *not* the order the mapping called
            // `store.set` in. Recovering that needs the `HostExports` recorder
            // patch phase 2 adds; see the module docs. Anything that depends on
            // save order — "`Pool.save` precedes the `Mint` write in
            // `handleMint`", for instance — cannot be checked from this report.
            let mut sorted = modifications
                .iter()
                .map(describe_modification)
                .collect::<Vec<_>>();
            sorted.sort_by(|a, b| (&a.entity, &a.id).cmp(&(&b.entity, &b.id)));

            let data_source = host.data_source();
            group.handlers.push(HandlerReport {
                handler_order,
                data_source: data_source.name().to_string(),
                data_source_address: data_source
                    .address()
                    .map(|a| format!("0x{}", hex::encode(a))),
                handler,
                gas: None,
                outcome,
                error,
                modifications: sorted,
                created_data_sources: created_reports,
            });
        }

        if let Some(failed_handler_order) = group_errored {
            proof_of_indexing.write_deterministic_error(&self.logger, &self.causality_region);
            ops.push_deterministic_error(
                u64::from(handler_group_order),
                source_trigger_order as u64,
                failed_handler_order,
                self.causality_region.clone(),
            )?;
        }

        Ok(Some(group))
    }
}

/// Render one modification for the report, with the entity's full field set.
fn describe_modification(m: &EntityModification) -> ModificationReport {
    let (op, key, data) = match m {
        EntityModification::Insert { key, data, .. } => ("insert", key, Some(data)),
        EntityModification::Overwrite { key, data, .. } => ("overwrite", key, Some(data)),
        EntityModification::Remove { key, .. } => ("remove", key, None),
    };
    ModificationReport {
        op: op.to_string(),
        entity: key.entity_type.typename().to_string(),
        id: key.entity_id.to_string(),
        vid: data.map(|d| d.vid()),
        data: data.map(|d| {
            d.sorted_ref()
                .into_iter()
                .map(|(name, value)| {
                    (
                        name.to_string(),
                        serde_json::to_value(value).unwrap_or(serde_json::Value::Null),
                    )
                })
                .collect()
        }),
    }
}
