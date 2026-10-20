//! A compact, verifiable summary of one long replay.
//!
//! A contiguous range produces artifacts far too large to commit: the parity
//! window's streamed report is 2.1 MB and its 1,053 canonical frames are 5.6 MB.
//! What is worth keeping in the repository is the *evidence* — what was run,
//! against what, and what it produced, in a form a reader can check rather than
//! take on trust.
//!
//! So a run leaves two committed files:
//!
//! * `<name>.json`, this structure: the deployment, the range, the exact command
//!   and the *names* of the environment variables it needed, every tally, the
//!   final PoI, and prose findings;
//! * `<name>.blocks.jsonl`, one line per block holding `number`,
//!   `frame_sha256`, `poi_public_digest` and `operations`, whose SHA-256 the
//!   summary pins.
//!
//! Everything except [`RunContext`] and [`Finding`] is *derived* from the run's
//! streamed report, never typed by hand, and [`summarize`] recomputes all of it.
//! Regeneration therefore preserves the prose and cannot preserve a stale count:
//!
//! ```sh
//! graph-mapping-host summarize \
//!   --report report.jsonl \
//!   --evidence evidence/parity-window-12369621-12370674.json \
//!   --segment segments/<cid> \
//!   --cassette fixtures/cassettes/<cid>.json \
//!   --goldens fixtures/block-changes/<cid>
//! ```
//!
//! No credential can reach either file. The report header records the endpoint's
//! `host:port` and nothing else, and [`RunContext::environment`] holds variable
//! *names*.
//!
//! # Two schema versions
//!
//! * [`EVIDENCE_SCHEMA`] (`run-evidence/v1`) is the default, [`PerBlockScope::All`]:
//!   the per-block file lists every block of the range. It is what the
//!   parity-window summary is, and a regeneration of it stays byte-identical.
//! * [`EVIDENCE_SCHEMA_V2`] (`run-evidence/v2`) is written exactly when the
//!   per-block file is sparse, [`PerBlockScope::HandlerBlocks`], for a range too
//!   long to commit block by block. **A reader must honour `per_block.scope`**:
//!   the committed file then lists only the blocks that did something, and the
//!   complete file is named and pinned by `per_block.all_blocks`. The version
//!   changes so that a v1 reader, which knows nothing of `scope`, refuses the file
//!   instead of reading a 3,276-line file as a complete 20,000-block range. A v2
//!   summary also records every data source creation with the wave each handler
//!   on it ran in ([`DataSourceCreation`]), because neither per-block file
//!   carries scheduling and the report that does is not committed.
//!
//! [`RunEvidence::check_schema`] enforces that pairing.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

use crate::bundle::sha256_hex;
use crate::report::{
    BlockReport, HandlerGroupReport, HandlerReport, RunHeader, REPORT_STREAM_SCHEMA,
};

/// Schema identifier of a summary whose per-block file lists every block.
pub const EVIDENCE_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.run-evidence/v1";

/// Schema identifier of a summary whose per-block file may be sparse: see the
/// module documentation. A reader of this version must honour
/// `per_block.scope`.
pub const EVIDENCE_SCHEMA_V2: &str = "pinax.substreams-backfills.mapping-host.run-evidence/v2";

/// What a reader has to be told, because no artifact records it: how the run was
/// invoked and what it is and is not a claim about.
///
/// This is the one hand-written part of the file. [`summarize`] copies it
/// forward unchanged from the evidence file it is rewriting.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RunContext {
    /// ISO date the run was performed.
    pub recorded_on: String,
    /// The exact command, with no credential and no absolute path.
    pub command: String,
    /// Names of the environment variables the command needed. **Names only** —
    /// two of these hold bearer tokens.
    pub environment: Vec<String>,
    /// Rust toolchain, matching `rust-toolchain.toml`.
    pub toolchain: String,
    /// Where blocks came from, as `host:port`.
    pub firehose_endpoint: String,
    /// Where the recorded `eth_call` answers came from.
    pub rpc_endpoint: String,
    /// What was produced but deliberately not committed, and how big it was.
    pub artifacts_not_committed: String,
    /// What this run is evidence *of*, stated so it cannot be over-read.
    pub claim_boundary: String,
}

impl Default for RunContext {
    fn default() -> Self {
        RunContext {
            recorded_on: "TODO".into(),
            command: "TODO".into(),
            environment: Vec::new(),
            toolchain: "TODO".into(),
            firehose_endpoint: "TODO".into(),
            rpc_endpoint: "TODO".into(),
            artifacts_not_committed: "TODO".into(),
            claim_boundary: "TODO".into(),
        }
    }
}

/// One thing the run established, in prose, with the observation behind it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Finding {
    pub id: String,
    pub title: String,
    /// What was observed, and what it does and does not settle.
    pub statement: String,
}

/// The deployment the run replayed, copied from the report header.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Deployment {
    pub deployment: String,
    pub network: String,
    pub spec_version: String,
    pub api_versions: Vec<String>,
    pub features: Vec<String>,
    pub graph_node_rev: String,
    /// The header's own description of the block source. Credential-free.
    pub source: String,
}

/// The half-open range, and proof that every block in it arrived.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Range {
    pub from: i32,
    pub to: i32,
    pub blocks: usize,
    pub first_block: i32,
    pub last_block: i32,
    /// True when the block numbers ascend by exactly one, with no gap and no
    /// repeat, and span `[from, to)` completely.
    pub contiguous: bool,
}

/// Everything countable about the run.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Default)]
pub struct Totals {
    pub blocks: usize,
    /// Blocks in which at least one handler ran.
    pub blocks_with_handlers: usize,
    pub blocks_with_poi: usize,
    pub blocks_discarded: usize,
    pub handler_groups: usize,
    pub handler_invocations: usize,
    /// `BlockChanges` operations: one per `store.set`, in call order.
    pub operations: usize,
    pub sets: usize,
    pub removes: usize,
    /// Deterministic errors, as the frames record them.
    pub deterministic_errors: usize,
    /// What `EntityCache::as_modifications` collapsed those operations to. It is
    /// lower than `operations` by design; the gap is what the recorder buys.
    pub collapsed_modifications: usize,
    pub created_data_sources: usize,
    /// The deepest wave count any single block needed.
    pub max_waves: usize,
    /// Total bytes of canonical frame across the run.
    pub frame_bytes: usize,
}

/// Handlers, by name, and the ones that never ran.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Default)]
pub struct Handlers {
    /// Handler name to invocation count.
    pub invocations: BTreeMap<String, usize>,
    /// Outcome (`ok`, `deterministic_error`) to count, across every invocation.
    pub outcomes: BTreeMap<String, usize>,
}

/// The schema's entity types, split by whether the run ever wrote one.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Default)]
pub struct EntityTypes {
    /// Declared by the deployed schema, from the segment descriptor. Empty when
    /// no `--segment` was given.
    pub declared: Vec<String>,
    pub written: Vec<String>,
    /// Declared but never written. Meaningful only when `declared` is populated.
    pub never_written: Vec<String>,
}

/// The last PoI the run produced, which is what a longer run would chain from.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct FinalPoi {
    /// The last block that wrote a PoI, which is not necessarily `last_block`:
    /// a block in which no handler ran creates no causality region.
    pub block: i32,
    pub version: String,
    pub causality_region: String,
    pub public_digest: String,
}

/// The cassette the run replayed and extended.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Cassette {
    pub path: String,
    pub rows: usize,
    pub bytes: usize,
    pub sha256: String,
    /// Rows by `(contract, function)`, so a reader can see what was called
    /// without opening a 185 KB file.
    pub rows_by_call: BTreeMap<String, usize>,
    /// Rows recording a revert rather than a value.
    pub reverts: usize,
}

/// One committed golden frame, against the same block in the contiguous run.
///
/// The four goldens come from a *sampled* replay of four blocks. A contiguous
/// replay reaches the same blocks with a different store behind it, so agreement
/// is a real result for the blocks that can agree and disagreement is a real
/// result for the blocks that cannot. Recording both digests pins the difference
/// instead of describing it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct FixtureCrossCheck {
    pub block: i32,
    pub identical: bool,
    pub golden_sha256: String,
    pub contiguous_sha256: String,
    /// From the committed sampled report, when one was given.
    pub golden_operations: Option<usize>,
    pub golden_deterministic_errors: Option<usize>,
    pub contiguous_operations: usize,
    pub contiguous_deterministic_errors: usize,
}

/// The sibling per-block file, pinned by digest.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PerBlockFile {
    /// Path relative to this summary.
    pub file: String,
    pub lines: usize,
    pub bytes: usize,
    pub sha256: String,
    pub fields: Vec<String>,
    /// Absent when the file lists every block, which is the default, the v1
    /// schema, and what the parity-window evidence does. `handler_blocks` when it
    /// lists only the blocks [`PerBlockScope::HandlerBlocks`] keeps, which makes
    /// the summary v2: a reader must then not take `lines` for the range.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scope: Option<String>,
    /// The file a [`PerBlockScope::All`] summary would have written, named and
    /// pinned by digest. Present exactly when `scope` is. This is what keeps a
    /// sparse file complete evidence: every block's frame digest is still bound,
    /// so a re-run can be compared block for block. `summarize` writes it beside
    /// the sparse file; it is published rather than committed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub all_blocks: Option<PerBlockDigest>,
}

/// A per-block file reduced to its name, size and digest.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PerBlockDigest {
    /// Path relative to the summary, like [`PerBlockFile::file`].
    pub file: String,
    pub lines: usize,
    pub bytes: usize,
    pub sha256: String,
}

/// One data source a handler created, and how its creation block scheduled the
/// handlers around it. Recorded in v2 summaries only.
///
/// A dynamic data source exists only once the handler that creates it has run,
/// so Graph Node rescans the creation block for it in a later wave. When the
/// new source's own events precede the creating event in the block, as a
/// Slipstream pool's `Initialize` precedes the Factory's `PoolCreated`, they run
/// *after* handlers at higher log indices. This row is that observation, taken
/// from the report rather than restated by hand.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct DataSourceCreation {
    pub block: i32,
    pub template: String,
    pub params: Vec<String>,
    /// The transaction whose handler created it. `None` only if no handler in
    /// the block reports the creation, which the host never produces.
    pub transaction_hash: Option<String>,
    /// The handler that created it.
    pub created_by: Option<ScheduledHandler>,
    /// Every handler in the creation block that ran either in the creating
    /// transaction or on the created data source, in execution order. Bounded by
    /// one transaction plus the new source's own events in that block.
    pub creation_block_handlers: Vec<ScheduledHandler>,
}

/// One handler invocation, placed by log index and by wave.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ScheduledHandler {
    pub data_source: String,
    pub handler: String,
    pub log_index: u64,
    /// The report's `stage`: 0 for the hosts the block started with, 1 for the
    /// first rescan after a creation, and so on.
    pub wave: usize,
    pub outcome: String,
}

impl ScheduledHandler {
    fn of(group: &HandlerGroupReport, handler: &HandlerReport) -> Self {
        ScheduledHandler {
            data_source: handler.data_source.clone(),
            handler: handler.handler.clone(),
            log_index: group.trigger.log_index,
            wave: group.stage,
            outcome: handler.outcome.clone(),
        }
    }
}

/// Every data source created in `block`, with the handlers around it.
fn creations_in(block: &BlockReport) -> Vec<DataSourceCreation> {
    let invocations = || {
        block
            .handler_groups
            .iter()
            .flat_map(|group| group.handlers.iter().map(move |handler| (group, handler)))
    };
    block
        .created_data_sources
        .iter()
        .map(|created| {
            let creator =
                invocations().find(|(_, handler)| handler.created_data_sources.contains(created));
            let transaction_hash = creator.map(|(group, _)| group.trigger.transaction_hash.clone());
            let address = created.params.first();
            let creation_block_handlers = invocations()
                .filter(|(group, handler)| {
                    transaction_hash.as_ref() == Some(&group.trigger.transaction_hash)
                        || (handler.data_source == created.template
                            && address.is_some()
                            && handler.data_source_address.as_ref() == address)
                })
                .map(|(group, handler)| ScheduledHandler::of(group, handler))
                .collect();
            DataSourceCreation {
                block: block.number,
                template: created.template.clone(),
                params: created.params.clone(),
                transaction_hash,
                created_by: creator.map(|(group, handler)| ScheduledHandler::of(group, handler)),
                creation_block_handlers,
            }
        })
        .collect()
}

/// Which blocks the sibling per-block file lists.
///
/// A long contiguous range is mostly blocks in which no handler ran. Listing
/// every one costs about 140 bytes a block, so a range of tens of thousands of
/// blocks makes a multi-megabyte file that belongs in a release asset rather
/// than in the repository.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum PerBlockScope {
    /// One line per block. The default, and unchanged.
    #[default]
    All,
    /// One line per block that ran a handler, wrote a PoI, carried an operation
    /// or was discarded. Every other block is still pinned through
    /// [`PerBlockFile::all_blocks`].
    HandlerBlocks,
}

impl PerBlockScope {
    /// The value `--per-block-scope` takes.
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "all" => Ok(PerBlockScope::All),
            "handler-blocks" => Ok(PerBlockScope::HandlerBlocks),
            other => bail!("unknown per-block scope `{other}`; want `all` or `handler-blocks`"),
        }
    }

    fn keeps(self, block: &BlockReport, line: &PerBlockLine) -> bool {
        match self {
            PerBlockScope::All => true,
            PerBlockScope::HandlerBlocks => {
                block.mapping_triggered
                    || block.block_discarded
                    || line.poi_public_digest.is_some()
                    || line.operations > 0
            }
        }
    }
}

/// One line of the sibling per-block file.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PerBlockLine {
    pub number: i32,
    /// SHA-256 of the canonical `BlockChanges` frame, lowercase hex.
    pub frame_sha256: String,
    /// `null` for a block in which no handler ran, because no causality region
    /// exists and the digest does not advance.
    pub poi_public_digest: Option<String>,
    pub operations: usize,
}

/// A whole run, small enough to read and to review.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RunEvidence {
    pub schema: String,
    pub run: RunContext,
    pub deployment: Deployment,
    pub range: Range,
    pub totals: Totals,
    pub handlers: Handlers,
    /// Data source name to handler invocation count.
    pub data_source_invocations: BTreeMap<String, usize>,
    /// v2 only: every data source the run created, in block order, with the
    /// wave each handler around it ran in. Absent from a v1 summary.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub data_source_creations: Option<Vec<DataSourceCreation>>,
    /// Entity type to *collapsed modification* count. This is `as_modifications`
    /// output, not saves, so it sums to `totals.collapsed_modifications`.
    pub modifications_by_entity: BTreeMap<String, usize>,
    pub entity_types: EntityTypes,
    /// Live rows per entity type after the last block.
    pub final_store_counts: BTreeMap<String, usize>,
    pub final_poi: Option<FinalPoi>,
    pub cassette: Option<Cassette>,
    pub fixture_block_cross_check: Vec<FixtureCrossCheck>,
    pub per_block: PerBlockFile,
    pub findings: Vec<Finding>,
}

impl RunEvidence {
    /// Pretty JSON with a trailing newline, byte-stable for a given run.
    pub fn to_json(&self) -> Result<String> {
        let mut json = serde_json::to_string_pretty(self)?;
        json.push('\n');
        Ok(json)
    }

    /// Refuse a summary whose schema version does not match its shape: a v1
    /// summary carries a complete per-block file and nothing v2 adds, and a v2
    /// summary carries a sparse one, the complete file's pin and the creation
    /// rows. Anything else is a file a reader of either version would misread.
    pub fn check_schema(&self) -> Result<()> {
        let per_block = &self.per_block;
        let v2_fields = [
            per_block.scope.is_some(),
            per_block.all_blocks.is_some(),
            self.data_source_creations.is_some(),
        ];
        match self.schema.as_str() {
            EVIDENCE_SCHEMA if v2_fields.iter().any(|present| *present) => bail!(
                "a `{EVIDENCE_SCHEMA}` summary must list every block: it carries a per-block \
                 scope, an all-blocks pin or creation rows, which only `{EVIDENCE_SCHEMA_V2}` defines"
            ),
            EVIDENCE_SCHEMA => Ok(()),
            EVIDENCE_SCHEMA_V2 if v2_fields.iter().all(|present| *present) => {
                if per_block.scope.as_deref() != Some("handler_blocks") {
                    bail!("unknown per-block scope {:?}", per_block.scope);
                }
                Ok(())
            }
            EVIDENCE_SCHEMA_V2 => bail!(
                "a `{EVIDENCE_SCHEMA_V2}` summary needs `per_block.scope`, `per_block.all_blocks` \
                 and `data_source_creations`"
            ),
            other => bail!("unknown evidence schema `{other}`"),
        }
    }
}

/// The hand-written half of an existing summary, read back so a regeneration
/// keeps it.
///
/// Only these two fields are parsed out of the previous file. Parsing the whole
/// [`RunEvidence`] would make every schema addition break regeneration of the
/// very file being upgraded, and none of the derived fields is worth preserving:
/// they are all recomputed.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct Narrative {
    #[serde(default)]
    pub run: Option<RunContext>,
    #[serde(default)]
    pub findings: Vec<Finding>,
}

impl Narrative {
    /// Read the prose out of an existing summary. A file that is not there is
    /// the first run; a file that is there and unreadable is an error, never a
    /// silent reset that would drop the prose.
    pub fn read(path: &Path) -> Result<Option<Self>> {
        match std::fs::read(path) {
            Ok(bytes) => Ok(Some(serde_json::from_slice(&bytes).with_context(|| {
                format!("parsing the prose out of {}", path.display())
            })?)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e).with_context(|| format!("reading {}", path.display())),
        }
    }
}

/// What [`summarize`] needs besides the report.
pub struct SummarizeInputs<'a> {
    /// The streamed report: one `report-stream/v1` header line, then one
    /// `BlockReport` per line.
    pub report: &'a Path,
    /// The prose of the evidence file being rewritten, carried forward
    /// unchanged. Absent on a first run.
    pub previous: Option<Narrative>,
    /// Name of the sibling per-block file, as it will be referenced.
    pub per_block_name: String,
    /// The segment bundle, for the declared entity types.
    pub segment: Option<&'a Path>,
    /// The cassette the run used.
    pub cassette: Option<&'a Path>,
    /// Directory of committed golden frames, for the cross-check.
    pub goldens: Option<&'a Path>,
    /// The committed sampled-run report, so the cross-check can say what the
    /// four-block replay produced as well as what it digested to.
    pub sampled_report: Option<&'a Path>,
    /// Which blocks the per-block file lists; see [`PerBlockScope`].
    pub per_block_scope: PerBlockScope,
    /// Name of the complete per-block file, as it will be referenced. Required
    /// with [`PerBlockScope::HandlerBlocks`], ignored otherwise.
    pub all_blocks_name: Option<String>,
}

/// What [`summarize`] derives: the summary and the exact bytes of every
/// per-block file it pins.
#[derive(Clone, Debug)]
pub struct Summary {
    pub evidence: RunEvidence,
    /// The file [`PerBlockFile::file`] names.
    pub per_block: String,
    /// The file [`PerBlockDigest::file`] names, for a sparse summary only.
    pub all_blocks: Option<String>,
}

/// Derive an evidence summary and the per-block files it pins.
///
/// Returns the summary and each per-block file's exact bytes; the caller writes
/// them. The digests in [`PerBlockFile`] are taken over those bytes, so a
/// summary and its siblings can never disagree about what was produced.
pub fn summarize(inputs: SummarizeInputs<'_>) -> Result<Summary> {
    let text = std::fs::read_to_string(inputs.report)
        .with_context(|| format!("reading {}", inputs.report.display()))?;
    let mut lines = text.lines();

    let header: RunHeader = serde_json::from_str(
        lines
            .next()
            .ok_or_else(|| anyhow!("{} is empty", inputs.report.display()))?,
    )
    .with_context(|| {
        format!(
            "{} does not start with a report header",
            inputs.report.display()
        )
    })?;
    if header.schema != REPORT_STREAM_SCHEMA {
        bail!(
            "{} is a `{}`, not a `{REPORT_STREAM_SCHEMA}`; only a streamed report of a contiguous \
             range can be summarized",
            inputs.report.display(),
            header.schema
        );
    }
    let (from, to) = match (header.from, header.to) {
        (Some(from), Some(to)) => (from, to),
        _ => bail!("the report header carries no `from`/`to` range"),
    };

    let mut blocks = Vec::new();
    for (index, line) in lines.enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let block: BlockReport = serde_json::from_str(line)
            .with_context(|| format!("parsing block report on line {}", index + 2))?;
        blocks.push(block);
    }
    if blocks.is_empty() {
        bail!("{} holds no block reports", inputs.report.display());
    }

    let mut totals = Totals {
        blocks: blocks.len(),
        ..Totals::default()
    };
    let mut handlers = Handlers::default();
    let mut data_source_invocations: BTreeMap<String, usize> = BTreeMap::new();
    let mut modifications_by_entity: BTreeMap<String, usize> = BTreeMap::new();
    let mut per_block = Vec::with_capacity(blocks.len());
    let mut creations = Vec::new();
    let mut final_poi = None;
    let mut contiguous = blocks.first().map(|b| b.number) == Some(from)
        && blocks.last().map(|b| b.number) == Some(to - 1)
        && blocks.len() == (to - from) as usize;

    let mut expected = from;
    for block in &blocks {
        if block.number != expected {
            contiguous = false;
        }
        expected = block.number.saturating_add(1);

        if block.mapping_triggered {
            totals.blocks_with_handlers += 1;
        }
        if block.block_discarded {
            totals.blocks_discarded += 1;
        }
        totals.handler_groups += block.handler_groups.len();
        totals.collapsed_modifications += block.modification_count;
        totals.created_data_sources += block.created_data_sources.len();
        totals.max_waves = totals.max_waves.max(block.triggers_per_stage.len());
        creations.extend(creations_in(block));

        for group in &block.handler_groups {
            for handler in &group.handlers {
                totals.handler_invocations += 1;
                *handlers
                    .invocations
                    .entry(handler.handler.clone())
                    .or_default() += 1;
                *handlers
                    .outcomes
                    .entry(handler.outcome.clone())
                    .or_default() += 1;
                *data_source_invocations
                    .entry(handler.data_source.clone())
                    .or_default() += 1;
                for modification in &handler.modifications {
                    *modifications_by_entity
                        .entry(modification.entity.clone())
                        .or_default() += 1;
                }
            }
        }

        let changes = block.block_changes.as_ref().ok_or_else(|| {
            anyhow!(
                "block {} has no BlockChanges summary; the run must be one that sealed frames",
                block.number
            )
        })?;
        totals.operations += changes.operations;
        totals.sets += changes.sets;
        totals.removes += changes.removes;
        totals.deterministic_errors += changes.deterministic_errors;
        totals.frame_bytes += changes.frame_bytes;

        if let Some(poi) = block.poi.as_ref() {
            totals.blocks_with_poi += 1;
            // The *last* region to write wins, which for a single-region chain
            // is simply the last block that produced one.
            if let Some((region, _)) = poi.causality_regions.iter().next_back() {
                final_poi = Some(FinalPoi {
                    block: block.number,
                    version: poi.version.clone(),
                    causality_region: region.clone(),
                    public_digest: poi.public_digest.clone(),
                });
            }
        }

        let line = PerBlockLine {
            number: block.number,
            frame_sha256: changes.frame_sha256.clone(),
            poi_public_digest: block.poi.as_ref().map(|poi| poi.public_digest.clone()),
            operations: changes.operations,
        };
        let kept = inputs.per_block_scope.keeps(block, &line);
        per_block.push((line, kept));
    }

    // The complete file is always built, because a sparse summary pins it.
    let mut all_blocks_text = String::new();
    let mut per_block_text = String::new();
    let mut per_block_lines = 0;
    for (line, kept) in &per_block {
        let json = crate::report::json_line(line)?;
        if *kept {
            per_block_text.push_str(&json);
            per_block_lines += 1;
        }
        all_blocks_text.push_str(&json);
    }
    let (schema, scope, all_blocks, data_source_creations) = match inputs.per_block_scope {
        PerBlockScope::All => (EVIDENCE_SCHEMA, None, None, None),
        PerBlockScope::HandlerBlocks => {
            let file = inputs.all_blocks_name.clone().ok_or_else(|| {
                anyhow!("a sparse per-block file needs the complete per-block file's name")
            })?;
            if file == inputs.per_block_name {
                bail!("the sparse and the complete per-block file cannot both be `{file}`");
            }
            (
                EVIDENCE_SCHEMA_V2,
                Some("handler_blocks".to_string()),
                Some(PerBlockDigest {
                    file,
                    lines: per_block.len(),
                    bytes: all_blocks_text.len(),
                    sha256: sha256_hex(all_blocks_text.as_bytes()),
                }),
                Some(creations),
            )
        }
    };

    let written: Vec<String> = modifications_by_entity.keys().cloned().collect();
    let declared = match inputs.segment {
        Some(segment) => declared_entity_types(segment)?,
        None => Vec::new(),
    };
    let written_set: BTreeSet<&str> = written.iter().map(String::as_str).collect();
    let never_written: Vec<String> = declared
        .iter()
        .filter(|entity| !written_set.contains(entity.as_str()))
        .cloned()
        .collect();

    let last = blocks.last().expect("at least one block");
    let evidence = RunEvidence {
        schema: schema.to_string(),
        run: inputs
            .previous
            .as_ref()
            .and_then(|previous| previous.run.clone())
            .unwrap_or_default(),
        deployment: Deployment {
            deployment: header.deployment,
            network: header.network,
            spec_version: header.spec_version,
            api_versions: header.api_versions,
            features: header.features,
            graph_node_rev: header.graph_node_rev,
            source: header.source,
        },
        range: Range {
            from,
            to,
            blocks: blocks.len(),
            first_block: blocks[0].number,
            last_block: last.number,
            contiguous,
        },
        totals,
        handlers,
        data_source_invocations,
        data_source_creations,
        modifications_by_entity,
        entity_types: EntityTypes {
            declared,
            written,
            never_written,
        },
        final_store_counts: last.store_counts.clone(),
        final_poi,
        cassette: match inputs.cassette {
            Some(path) => Some(cassette_facts(path)?),
            None => None,
        },
        fixture_block_cross_check: match inputs.goldens {
            Some(dir) => cross_check(dir, inputs.sampled_report, &blocks)?,
            None => Vec::new(),
        },
        per_block: PerBlockFile {
            file: inputs.per_block_name,
            lines: per_block_lines,
            bytes: per_block_text.len(),
            sha256: sha256_hex(per_block_text.as_bytes()),
            fields: vec![
                "number".into(),
                "frame_sha256".into(),
                "poi_public_digest".into(),
                "operations".into(),
            ],
            scope,
            all_blocks,
        },
        findings: inputs
            .previous
            .map(|previous| previous.findings)
            .unwrap_or_default(),
    };
    evidence.check_schema()?;

    Ok(Summary {
        all_blocks: evidence
            .per_block
            .all_blocks
            .is_some()
            .then_some(all_blocks_text),
        evidence,
        per_block: per_block_text,
    })
}

/// The entity types the deployed schema declares, out of the segment's
/// BlockChanges descriptor rather than a second parse of the schema.
fn declared_entity_types(segment: &Path) -> Result<Vec<String>> {
    #[derive(Deserialize)]
    struct Descriptor {
        storage_profile: StorageProfile,
    }
    #[derive(Deserialize)]
    struct StorageProfile {
        entity_types: Vec<String>,
    }

    let path = segment.join("block-changes-descriptor.json");
    let bytes = std::fs::read(&path).with_context(|| format!("reading {}", path.display()))?;
    let descriptor: Descriptor =
        serde_json::from_slice(&bytes).with_context(|| format!("parsing {}", path.display()))?;
    Ok(descriptor.storage_profile.entity_types)
}

/// Row counts out of the cassette, without restating any of its bytes.
fn cassette_facts(path: &Path) -> Result<Cassette> {
    #[derive(Deserialize)]
    struct File {
        entries: Vec<Entry>,
    }
    #[derive(Deserialize)]
    struct Entry {
        contract: String,
        function: String,
        retval: Retval,
    }
    #[derive(Deserialize)]
    struct Retval {
        kind: String,
    }

    let bytes = std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
    let file: File =
        serde_json::from_slice(&bytes).with_context(|| format!("parsing {}", path.display()))?;

    let mut rows_by_call: BTreeMap<String, usize> = BTreeMap::new();
    let mut reverts = 0;
    for entry in &file.entries {
        *rows_by_call
            .entry(format!("{}::{}", entry.contract, entry.function))
            .or_default() += 1;
        if entry.retval.kind != "value" {
            reverts += 1;
        }
    }

    Ok(Cassette {
        // Recorded relative to the crate, so the file says nothing about whose
        // machine produced it.
        path: relative_to_crate(path),
        rows: file.entries.len(),
        bytes: bytes.len(),
        sha256: sha256_hex(&bytes),
        rows_by_call,
        reverts,
    })
}

/// Every committed golden, beside the same block in this run.
fn cross_check(
    goldens: &Path,
    sampled_report: Option<&Path>,
    blocks: &[BlockReport],
) -> Result<Vec<FixtureCrossCheck>> {
    let sampled: Vec<BlockReport> = match sampled_report {
        Some(path) => {
            let bytes =
                std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
            let report: crate::report::RunReport = serde_json::from_slice(&bytes)
                .with_context(|| format!("parsing {}", path.display()))?;
            report.blocks
        }
        None => Vec::new(),
    };

    let mut checks = Vec::new();
    let mut entries: Vec<std::path::PathBuf> = std::fs::read_dir(goldens)
        .with_context(|| format!("listing {}", goldens.display()))?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "pb"))
        .collect();
    entries.sort();

    for path in entries {
        let stem = path
            .file_stem()
            .and_then(|stem| stem.to_str())
            .ok_or_else(|| anyhow!("{} has no block number", path.display()))?;
        let block: i32 = stem
            .parse()
            .with_context(|| format!("{} is not named after a block number", path.display()))?;
        let bytes = std::fs::read(&path).with_context(|| format!("reading {}", path.display()))?;
        let golden_sha256 = sha256_hex(&bytes);

        let Some(report) = blocks.iter().find(|report| report.number == block) else {
            // A golden outside the range is not evidence about this run.
            continue;
        };
        let changes = report
            .block_changes
            .as_ref()
            .ok_or_else(|| anyhow!("block {block} has no BlockChanges summary"))?;
        let sampled = sampled.iter().find(|report| report.number == block);
        checks.push(FixtureCrossCheck {
            block,
            identical: golden_sha256 == changes.frame_sha256,
            golden_sha256,
            contiguous_sha256: changes.frame_sha256.clone(),
            golden_operations: sampled
                .and_then(|report| report.block_changes.as_ref())
                .map(|changes| changes.operations),
            golden_deterministic_errors: sampled
                .and_then(|report| report.block_changes.as_ref())
                .map(|changes| changes.deterministic_errors),
            contiguous_operations: changes.operations,
            contiguous_deterministic_errors: changes.deterministic_errors,
        });
    }
    Ok(checks)
}

/// A path as it reads from the crate root, so no machine-specific prefix is ever
/// written into a committed file.
///
/// An absolute path outside the crate, such as a cassette a long run kept in a
/// scratch directory because it is too large to commit, is reduced to its file
/// name rather than written out whole.
fn relative_to_crate(path: &Path) -> String {
    let crate_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let relative = match path.strip_prefix(crate_dir) {
        Ok(relative) => relative,
        Err(_) if path.is_absolute() => path
            .file_name()
            .map(Path::new)
            .unwrap_or_else(|| Path::new("")),
        Err(_) => path,
    };
    relative.to_string_lossy().replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_per_block_line_keeps_a_missing_poi_explicit() {
        // `null` has to survive into the file: a block in which no handler ran
        // *has* no PoI, and an omitted key would read as "not recorded" instead.
        let line = PerBlockLine {
            number: 12369621,
            frame_sha256: "ab".into(),
            poi_public_digest: None,
            operations: 0,
        };
        let json = serde_json::to_string(&line).expect("serializing");
        assert!(
            json.contains("\"poi_public_digest\":null"),
            "the null must be explicit: {json}"
        );
    }

    #[allow(clippy::too_many_arguments)]
    fn handler(
        order: u32,
        stage: usize,
        transaction: &str,
        log_index: u64,
        data_source: &str,
        address: &str,
        name: &str,
        created: Vec<crate::report::CreatedDataSourceReport>,
    ) -> HandlerGroupReport {
        HandlerGroupReport {
            handler_group_order: order,
            stage,
            source_trigger_order: log_index as usize,
            causality_region: "ethereum/base".into(),
            trigger: crate::report::TriggerReport {
                transaction_hash: transaction.into(),
                log_index,
                address: address.into(),
            },
            handlers: vec![HandlerReport {
                handler_order: 0,
                data_source: data_source.into(),
                data_source_address: Some(address.into()),
                handler: name.into(),
                gas: None,
                outcome: "ok".into(),
                error: None,
                modifications: Vec::new(),
                created_data_sources: created,
            }],
        }
    }

    /// A three-block streamed report: an empty block, a block with handlers and
    /// a PoI, and another empty block.
    ///
    /// Block 101 is the wave trap in miniature: the Factory's `PoolCreated` at
    /// log 5 creates `Pool` 0xpool in wave 0, beside an unrelated wave-0 handler
    /// in another transaction; the new pool's `Initialize` at log 4 runs in wave 1.
    fn three_block_report(dir: &Path) -> std::path::PathBuf {
        let header = RunHeader {
            schema: REPORT_STREAM_SCHEMA.to_string(),
            deployment: "QmTest".into(),
            network: "base".into(),
            spec_version: "1.2.0".into(),
            api_versions: vec!["0.0.7".into()],
            features: vec!["nonFatalErrors".into()],
            graph_node_rev: crate::runner::GRAPH_NODE_REV.into(),
            source: "fixture".into(),
            from: Some(100),
            to: Some(103),
        };
        let block = |number: i32, triggered: bool| BlockReport {
            number,
            hash: format!("0x{number:064x}"),
            parent_hash: None,
            timestamp: 0,
            mapping_triggered: triggered,
            triggers_per_stage: vec![1],
            hosts_per_stage: vec![1],
            handler_groups: Vec::new(),
            created_data_sources: Vec::new(),
            deterministic_errors: Vec::new(),
            deterministic_error_policy: "non_fatal".into(),
            block_discarded: false,
            modification_count: 0,
            poi: triggered.then(|| crate::report::PoiReport {
                version: "fast".into(),
                causality_regions: [("ethereum/base".to_string(), "aa".to_string())].into(),
                public_digest: format!("{number:064x}"),
            }),
            store_counts: BTreeMap::new(),
            block_changes: Some(crate::report::BlockChangesSummary {
                operations: usize::from(triggered),
                sets: usize::from(triggered),
                removes: 0,
                deterministic_errors: 0,
                frame_bytes: 114,
                frame_sha256: format!("{:064x}", number + 1),
            }),
        };
        let pool = crate::report::CreatedDataSourceReport {
            template: "Pool".into(),
            params: vec!["0xpool".into()],
            creation_block: 101,
        };
        let mut text = crate::report::json_line(&header).unwrap();
        for (number, triggered) in [(100, false), (101, true), (102, false)] {
            let mut report = block(number, triggered);
            if triggered {
                report.triggers_per_stage = vec![3, 3];
                report.handler_groups = vec![
                    handler(
                        0,
                        0,
                        "0xt",
                        5,
                        "Factory",
                        "0xfactory",
                        "handlePoolCreated",
                        vec![pool.clone()],
                    ),
                    handler(1, 0, "0xu", 9, "Other", "0xother", "handleOther", vec![]),
                    handler(2, 1, "0xt", 4, "Pool", "0xpool", "handleInitialize", vec![]),
                ];
                report.created_data_sources = vec![pool.clone()];
            }
            text.push_str(&crate::report::json_line(&report).unwrap());
        }
        let path = dir.join("report.jsonl");
        std::fs::write(&path, text).unwrap();
        path
    }

    fn summarize_with(report: &Path, scope: PerBlockScope) -> Summary {
        summarize(SummarizeInputs {
            report,
            previous: None,
            per_block_name: "x.blocks.jsonl".into(),
            segment: None,
            cassette: None,
            goldens: None,
            sampled_report: None,
            per_block_scope: scope,
            all_blocks_name: Some("x.all-blocks.jsonl".into()),
        })
        .unwrap()
    }

    #[test]
    fn a_sparse_per_block_file_still_pins_every_block() {
        let dir = tempfile::tempdir().unwrap();
        let report = three_block_report(dir.path());
        let all = summarize_with(&report, PerBlockScope::All);
        let sparse = summarize_with(&report, PerBlockScope::HandlerBlocks);
        let (all, all_text) = (all.evidence, all.per_block);
        let sparse_all_text = sparse
            .all_blocks
            .expect("a sparse summary writes both files");
        let (sparse, sparse_text) = (sparse.evidence, sparse.per_block);

        // The default is unchanged: v1, no scope, no second digest, every block.
        assert_eq!(all.schema, EVIDENCE_SCHEMA);
        assert_eq!(all.per_block.scope, None);
        assert_eq!(all.per_block.all_blocks, None);
        assert_eq!(all.data_source_creations, None);
        assert_eq!(all.per_block.lines, 3);
        let json = all.to_json().unwrap();
        for v2_only in ["all_blocks", "scope", "data_source_creations"] {
            assert!(
                !json.contains(v2_only),
                "{v2_only} leaked into a v1 summary"
            );
        }

        // The sparse file lists only the block that did something, and so it is
        // v2, which a v1 reader refuses rather than misreads...
        assert_eq!(sparse.schema, EVIDENCE_SCHEMA_V2);
        assert_eq!(sparse.per_block.scope.as_deref(), Some("handler_blocks"));
        assert_eq!(sparse.per_block.lines, 1);
        assert_eq!(sparse_text.lines().count(), 1);
        assert!(sparse_text.contains("\"number\":101"));
        assert_eq!(sparse.per_block.sha256, sha256_hex(sparse_text.as_bytes()));

        // ...and names and pins the complete file, byte for byte the one the
        // default would write.
        let pinned = sparse.per_block.all_blocks.as_ref().unwrap();
        assert_eq!(pinned.file, "x.all-blocks.jsonl");
        assert_eq!(sparse_all_text, all_text);
        assert_eq!(pinned.sha256, all.per_block.sha256);
        assert_eq!(pinned.sha256, sha256_hex(all_text.as_bytes()));
        assert_eq!((pinned.lines, pinned.bytes), (3, all_text.len()));

        // Nothing but the per-block files, the version and the creation rows
        // depend on the scope.
        assert_eq!(sparse.totals, all.totals);
        assert_eq!(sparse.final_poi, all.final_poi);
        assert_eq!(sparse.handlers, all.handlers);
    }

    #[test]
    fn a_v2_summary_places_every_creation_by_wave() {
        let dir = tempfile::tempdir().unwrap();
        let report = three_block_report(dir.path());
        let evidence = summarize_with(&report, PerBlockScope::HandlerBlocks).evidence;
        assert_eq!(evidence.totals.created_data_sources, 1);
        assert_eq!(evidence.totals.max_waves, 2);

        let creations = evidence.data_source_creations.as_ref().unwrap();
        assert_eq!(creations.len(), 1);
        let pool = &creations[0];
        assert_eq!(
            (pool.block, pool.template.as_str(), pool.params.clone()),
            (101, "Pool", vec!["0xpool".to_string()])
        );
        assert_eq!(pool.transaction_hash.as_deref(), Some("0xt"));
        let created_by = pool.created_by.as_ref().unwrap();
        assert_eq!(
            (
                created_by.handler.as_str(),
                created_by.log_index,
                created_by.wave
            ),
            ("handlePoolCreated", 5, 0)
        );
        // The creating transaction and the new pool's own handlers, in
        // execution order; the unrelated wave-0 handler in `0xu` is left out.
        let placed: Vec<(&str, u64, usize)> = pool
            .creation_block_handlers
            .iter()
            .map(|h| (h.handler.as_str(), h.log_index, h.wave))
            .collect();
        assert_eq!(
            placed,
            vec![("handlePoolCreated", 5, 0), ("handleInitialize", 4, 1)]
        );
    }

    #[test]
    fn a_summary_whose_version_contradicts_its_shape_is_refused() {
        let dir = tempfile::tempdir().unwrap();
        let report = three_block_report(dir.path());
        let v1 = summarize_with(&report, PerBlockScope::All).evidence;
        let v2 = summarize_with(&report, PerBlockScope::HandlerBlocks).evidence;
        v1.check_schema().unwrap();
        v2.check_schema().unwrap();

        // A sparse file under the v1 name is exactly what a v1 reader misreads.
        let mut sparse_as_v1 = v2.clone();
        sparse_as_v1.schema = EVIDENCE_SCHEMA.into();
        assert!(sparse_as_v1.check_schema().is_err());
        // A v2 name without the complete file's pin is not v2.
        let mut unpinned = v2.clone();
        unpinned.per_block.all_blocks = None;
        assert!(unpinned.check_schema().is_err());
        let mut no_rows = v2;
        no_rows.data_source_creations = None;
        assert!(no_rows.check_schema().is_err());
        let mut unknown = v1;
        unknown.schema = "pinax.substreams-backfills.mapping-host.run-evidence/v3".into();
        assert!(unknown.check_schema().is_err());

        // And a sparse summary cannot be written without naming its full file.
        let refused = summarize(SummarizeInputs {
            report: &report,
            previous: None,
            per_block_name: "x.blocks.jsonl".into(),
            segment: None,
            cassette: None,
            goldens: None,
            sampled_report: None,
            per_block_scope: PerBlockScope::HandlerBlocks,
            all_blocks_name: None,
        });
        assert!(refused.is_err());
    }

    #[test]
    fn per_block_scopes_parse_strictly() {
        assert_eq!(PerBlockScope::parse("all").unwrap(), PerBlockScope::All);
        assert_eq!(
            PerBlockScope::parse("handler-blocks").unwrap(),
            PerBlockScope::HandlerBlocks
        );
        assert!(PerBlockScope::parse("handlers").is_err());
    }

    #[test]
    fn no_absolute_path_reaches_a_committed_file() {
        let crate_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        assert_eq!(
            relative_to_crate(&crate_dir.join("fixtures/cassettes/x.json")),
            "fixtures/cassettes/x.json"
        );
        assert_eq!(
            relative_to_crate(Path::new("/private/scratch/run/cassette.json")),
            "cassette.json"
        );
        assert_eq!(
            relative_to_crate(Path::new("fixtures/cassettes/x.json")),
            "fixtures/cassettes/x.json"
        );
    }

    #[test]
    fn the_default_run_context_is_obviously_unfilled() {
        // A first `summarize` writes placeholders rather than plausible-looking
        // blanks, so an unedited file cannot be mistaken for a described run.
        let context = RunContext::default();
        assert_eq!(context.recorded_on, "TODO");
        assert_eq!(context.command, "TODO");
        assert!(context.environment.is_empty());
    }
}
