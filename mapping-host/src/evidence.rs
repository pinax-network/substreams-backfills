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

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

use crate::bundle::sha256_hex;
use crate::report::{BlockReport, RunHeader, REPORT_STREAM_SCHEMA};

/// Schema identifier written into every evidence summary.
pub const EVIDENCE_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.run-evidence/v1";

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
}

/// Derive an evidence summary and the per-block file it pins.
///
/// Returns the summary and the per-block file's exact bytes; the caller writes
/// both. The digest in [`PerBlockFile::sha256`] is taken over those bytes, so a
/// summary and its sibling can never disagree about what was produced.
pub fn summarize(inputs: SummarizeInputs<'_>) -> Result<(RunEvidence, String)> {
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

        per_block.push(PerBlockLine {
            number: block.number,
            frame_sha256: changes.frame_sha256.clone(),
            poi_public_digest: block.poi.as_ref().map(|poi| poi.public_digest.clone()),
            operations: changes.operations,
        });
    }

    let mut per_block_text = String::new();
    for line in &per_block {
        per_block_text.push_str(&crate::report::json_line(line)?);
    }

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
        schema: EVIDENCE_SCHEMA.to_string(),
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
            lines: per_block.len(),
            bytes: per_block_text.len(),
            sha256: sha256_hex(per_block_text.as_bytes()),
            fields: vec![
                "number".into(),
                "frame_sha256".into(),
                "poi_public_digest".into(),
                "operations".into(),
            ],
        },
        findings: inputs
            .previous
            .map(|previous| previous.findings)
            .unwrap_or_default(),
    };

    Ok((evidence, per_block_text))
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
fn relative_to_crate(path: &Path) -> String {
    let crate_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    path.strip_prefix(crate_dir)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
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
