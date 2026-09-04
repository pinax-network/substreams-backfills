//! The host checkpoint: everything a faithful continuation needs.
//!
//! A long contiguous replay cannot be one process. The first `Flash` event on
//! mainnet is block 12,764,397, which is 394,776 blocks past segment 1's
//! graft-free root, and a faithful replay has to start at the root because the
//! handlers read pool and token rows that only exist if the blocks that created
//! them were replayed. At the rates in `README.md` that is many hours in a
//! single process, and until now `--resume` was refused outright.
//!
//! ## What actually carries across a block boundary
//!
//! Three things in [`crate::runner::SegmentHost`] change as blocks are replayed
//! and are still needed by the next block. All three are captured. The
//! proof-of-indexing chain is listed separately because it is the one people
//! expect to be a fourth, and it is not:
//!
//! 1. **The entity store** ([`crate::store::MemoryStore`]). Every live row,
//!    `Poi$` rows included.
//! 2. **The `Poi$` rows themselves.** The Legacy proof-of-indexing chain is not
//!    a separate variable: `poi::update_proof_of_indexing` reads the previous
//!    block's per-region digest back out of the store, through
//!    `EntityCache::get(.., GetScope::Store)`. Restoring the store therefore
//!    restores the chain. The closing [`StorePoi`] is carried too, but only as
//!    the reported value; the chaining input is the row.
//! 3. **The dynamic data sources**, in creation order, with the parameters,
//!    context and creation block each was instantiated from. Replaying that list
//!    through the same `create_dynamic_data_sources` puts the same hosts in the
//!    same order, which is what `handler_order` indexes.
//! 4. **The entity cache** (`EntityLfuCache`). This is a cache over the store,
//!    not a second copy of it: `EntityCache::get` reads the store on a miss, and
//!    graph-node's own `debug_assert!` in that function compares the cached
//!    entry against the store on every read, which is live in this crate's test
//!    builds. Its *keys* still matter — `EntityCache::as_modifications` skips
//!    the store lookup for an immutable entity type whose key is absent from the
//!    cache, which would turn an `Overwrite` into an `Insert` — so the key set is
//!    captured and each entry is rehydrated from the store on load.
//!
//! Nothing else crosses a block. The `SeqGenerator` that mints VIDs is created
//! fresh per block from the block number; the op recorder is drained per handler
//! and asserted empty at the start of each block; the WASM module is
//! re-instantiated per trigger (`vendor/graph-runtime-wasm/src/mapping.rs`
//! calls `instantiate_module` inside the request loop), so no AssemblyScript
//! global outlives a handler; and the cassette is a file.
//!
//! ## What is deliberately *not* captured
//!
//! * **The LFU frecency counters.** They are read only by `LfuCache::evict`,
//!   which this crate never calls, so they cannot change a replay. The key set
//!   is captured; the priorities are not.
//! * **A stale VID inside a cached entity.** `as_modifications` can leave the
//!   cache holding a row whose VID is one step ahead of the store's when a write
//!   changed nothing (`changed == false` emits no modification). VIDs are
//!   overwritten on every `set` and excluded from `Entity`'s own equality, so
//!   the difference is unobservable; the store's VID is the one restored.
//!
//! ## The encoding
//!
//! JSON Lines, because a checkpoint for a million-block chunk holds the whole
//! store and a single pretty-printed document would be gigabytes to build in
//! memory before the first byte is written. One header line, then one line per
//! dynamic data source, then one line per row, then one line per cache key that
//! the store has no row for. Values use [`StoreValue`], the same encoding
//! `--store-out` writes, and rows are ordered by
//! [`backfill_common::MaterializedKey`], so the file is byte-stable for a given
//! host state.
//!
//! The header's `totals` are checked on load against what was actually read, so
//! a truncated checkpoint is refused rather than resumed from.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;

use anyhow::{bail, Context, Result};
use backfill_common::pb::pinax::graph::backfill::v1 as pb;
use backfill_common::MaterializedKey;
use serde::{Deserialize, Serialize};

use crate::bundle::sha256_hex;
use crate::store_state::{StoreEntityId, StorePoi, StoreValue};

/// Schema identifier written into every checkpoint's header line.
pub const CHECKPOINT_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.checkpoint/v1";

/// Everything that has to agree before a checkpoint may be loaded.
///
/// A checkpoint is a store image plus a host set for *one* segment replayed
/// against *one* cassette under *one* graph-node revision. Loading it into
/// anything else would produce a store and a proof-of-indexing chain that no
/// single run could have produced, so each field below is compared and any
/// difference is a refusal.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointIdentity {
    /// Deployment CID; also the bundle directory name.
    pub deployment: String,
    pub network: String,
    pub spec_version: String,
    /// `legacy` or `fast`.
    pub poi_version: String,
    pub poi_causality_region: String,
    /// `fatal` or `non_fatal`.
    pub deterministic_error_policy: String,
    pub graph_node_rev: String,
    /// SHA-256 of the bundle's `bundle.lock.json`, which itself pins every
    /// manifest, mapping, ABI and schema file by digest.
    pub bundle_lock_sha256: String,
    /// SHA-256 of the segment's `block-changes-descriptor.json`.
    pub descriptor_sha256: String,
    /// SHA-256 of the cassette file as it stood when the checkpoint was written.
    /// Empty when no cassette file existed.
    pub cassette_sha256: String,
}

impl CheckpointIdentity {
    /// Refuse a checkpoint that does not belong to this host.
    ///
    /// Every mismatch is named, one line each, rather than collapsed into "the
    /// checkpoint does not match": the operator needs to know whether they
    /// pointed at the wrong segment or whether the cassette grew underneath
    /// them.
    pub fn check_loadable_into(&self, current: &CheckpointIdentity) -> Result<()> {
        let mut problems: Vec<String> = Vec::new();
        let mut compare = |field: &str, want: &str, got: &str| {
            if want != got {
                problems.push(format!(
                    "  {field}: checkpoint has `{want}`, this run has `{got}`"
                ));
            }
        };
        compare("deployment", &self.deployment, &current.deployment);
        compare("network", &self.network, &current.network);
        compare("spec_version", &self.spec_version, &current.spec_version);
        compare("poi_version", &self.poi_version, &current.poi_version);
        compare(
            "poi_causality_region",
            &self.poi_causality_region,
            &current.poi_causality_region,
        );
        compare(
            "deterministic_error_policy",
            &self.deterministic_error_policy,
            &current.deterministic_error_policy,
        );
        compare(
            "graph_node_rev",
            &self.graph_node_rev,
            &current.graph_node_rev,
        );
        compare(
            "bundle_lock_sha256",
            &self.bundle_lock_sha256,
            &current.bundle_lock_sha256,
        );
        compare(
            "descriptor_sha256",
            &self.descriptor_sha256,
            &current.descriptor_sha256,
        );
        compare(
            "cassette_sha256",
            &self.cassette_sha256,
            &current.cassette_sha256,
        );
        if problems.is_empty() {
            return Ok(());
        }
        bail!(
            "this checkpoint was not taken by this host:\n{}\n\
             A checkpoint is a store image and a host set for one segment, one cassette and one \
             graph-node revision. Continuing across any of those differences would produce a \
             store and a proof-of-indexing chain no single run could have produced.",
            problems.join("\n")
        )
    }
}

/// Where the run that wrote this checkpoint stopped.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointBoundary {
    /// The last block whose effects are in this checkpoint. A continuation
    /// replays from `block + 1`.
    pub block: i32,
    /// That block's hash, `0x`-prefixed. The first block of a continuation must
    /// name it as its parent, which is a fork check the block numbers alone
    /// cannot make.
    pub block_hash: String,
    /// How blocks reached the run that wrote this checkpoint. Never carries a
    /// credential; the live source records only `host:port`.
    pub source: String,
    /// The half-open range that chunk was asked for, when it was asked for one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chunk_from: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chunk_to: Option<i32>,
    /// Blocks replayed by the chunk that wrote this checkpoint.
    pub blocks_in_chunk: usize,
    /// Blocks replayed by every chunk in the chain, this one included.
    pub blocks_total: usize,
    /// 0 for a chunk that started from nothing, 1 for the first continuation,
    /// and so on.
    pub chunk_index: usize,
    /// SHA-256 of the checkpoint this chunk resumed from, so a chain of chunks
    /// is auditable end to end.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub previous_checkpoint_sha256: Option<String>,
}

/// How much of what, so a truncated file cannot pass unnoticed.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointTotals {
    pub dynamic_data_sources: usize,
    /// Rows excluding the proof-of-indexing rows.
    pub rows: usize,
    pub poi_rows: usize,
    /// Fields across every row, proof-of-indexing rows included.
    pub fields: usize,
    /// Cache keys the store has a row for.
    pub cached_present: usize,
    /// Cache keys the store has no row for: a read that missed, cached as a
    /// known absence.
    pub cached_absent: usize,
}

/// The header line.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointHeader {
    pub schema: String,
    pub identity: CheckpointIdentity,
    pub boundary: CheckpointBoundary,
    /// The closing proof of indexing across the whole chain of chunks, as the
    /// last block that opened the causality region left it. `None` when no block
    /// so far has opened one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub poi: Option<StorePoi>,
    pub totals: CheckpointTotals,
    /// Live rows per entity type, `Poi$` included.
    pub counts_by_type: BTreeMap<String, usize>,
}

/// One dynamic data source, exactly as `InstanceDSTemplateInfo` described it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointDataSource {
    /// The template's name, for a readable file. `manifest_idx` is what the
    /// template is actually resolved by.
    pub template: String,
    pub manifest_idx: u32,
    pub params: Vec<String>,
    /// `dataSource.context`, sorted by key. `None` for a plain `create`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub context: Option<Vec<(String, StoreValue)>>,
    pub creation_block: i32,
}

/// A row's storage identity.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointKey {
    pub entity_type: String,
    pub id: StoreEntityId,
    pub storage_causality_region: i32,
}

impl CheckpointKey {
    pub fn to_wire(&self) -> pb::EntityKey {
        pb::EntityKey {
            entity_type: self.entity_type.clone(),
            id: Some(self.id.to_wire()),
            storage_causality_region: self.storage_causality_region,
        }
    }

    fn ordering(&self) -> MaterializedKey {
        MaterializedKey {
            entity_type: self.entity_type.clone(),
            id: self.id.to_materialized(),
            storage_causality_region: self.storage_causality_region,
        }
    }
}

/// One live store row.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointRow {
    pub entity_type: String,
    pub id: StoreEntityId,
    pub storage_causality_region: i32,
    /// The VID the store row carries. Restored exactly, so nothing has to
    /// depend on the argument that it is unobservable.
    pub vid: i64,
    /// True when the entity cache held this key when the checkpoint was taken.
    pub cached: bool,
    /// Sorted by field name, `vid` excluded, exactly as a frame's
    /// `materialized` orders it.
    pub fields: Vec<(String, StoreValue)>,
}

impl CheckpointRow {
    pub fn key(&self) -> CheckpointKey {
        CheckpointKey {
            entity_type: self.entity_type.clone(),
            id: self.id.clone(),
            storage_causality_region: self.storage_causality_region,
        }
    }

    pub fn wire_fields(&self) -> Vec<pb::EntityField> {
        self.fields
            .iter()
            .map(|(name, value)| pb::EntityField {
                name: name.clone(),
                value: Some(value.to_wire()),
            })
            .collect()
    }
}

/// One line after the header.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum CheckpointLine {
    DataSource(CheckpointDataSource),
    Row(CheckpointRow),
    /// A cache key the store has no row for.
    CachedAbsent(CheckpointKey),
}

/// A whole checkpoint, in memory.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HostCheckpoint {
    pub header: CheckpointHeader,
    /// In creation order, which is the order they must be re-instantiated in.
    pub data_sources: Vec<CheckpointDataSource>,
    /// Ordered by storage identity, proof-of-indexing rows included.
    pub rows: Vec<CheckpointRow>,
    /// Ordered by storage identity.
    pub cached_absent: Vec<CheckpointKey>,
}

impl HostCheckpoint {
    /// Assemble a checkpoint and fill in its totals.
    ///
    /// `rows` and `cached_absent` are sorted here rather than trusted, so the
    /// file is byte-stable no matter what order a caller collected them in.
    pub fn new(
        identity: CheckpointIdentity,
        boundary: CheckpointBoundary,
        poi: Option<StorePoi>,
        poi_type: &str,
        data_sources: Vec<CheckpointDataSource>,
        mut rows: Vec<CheckpointRow>,
        mut cached_absent: Vec<CheckpointKey>,
    ) -> Self {
        rows.sort_by_key(|row| row.key().ordering());
        cached_absent.sort_by_key(CheckpointKey::ordering);

        let mut counts_by_type: BTreeMap<String, usize> = BTreeMap::new();
        let mut totals = CheckpointTotals {
            dynamic_data_sources: data_sources.len(),
            cached_absent: cached_absent.len(),
            ..CheckpointTotals::default()
        };
        for row in &rows {
            *counts_by_type.entry(row.entity_type.clone()).or_default() += 1;
            totals.fields += row.fields.len();
            if row.cached {
                totals.cached_present += 1;
            }
            if row.entity_type == poi_type {
                totals.poi_rows += 1;
            } else {
                totals.rows += 1;
            }
        }

        HostCheckpoint {
            header: CheckpointHeader {
                schema: CHECKPOINT_SCHEMA.to_string(),
                identity,
                boundary,
                poi,
                totals,
                counts_by_type,
            },
            data_sources,
            rows,
            cached_absent,
        }
    }

    /// Write the checkpoint as JSON Lines.
    pub fn write_to(&self, sink: &mut impl Write) -> Result<()> {
        writeln!(sink, "{}", serde_json::to_string(&self.header)?)?;
        for data_source in &self.data_sources {
            let line = CheckpointLine::DataSource(data_source.clone());
            writeln!(sink, "{}", serde_json::to_string(&line)?)?;
        }
        for row in &self.rows {
            let line = CheckpointLine::Row(row.clone());
            writeln!(sink, "{}", serde_json::to_string(&line)?)?;
        }
        for key in &self.cached_absent {
            let line = CheckpointLine::CachedAbsent(key.clone());
            writeln!(sink, "{}", serde_json::to_string(&line)?)?;
        }
        Ok(())
    }

    /// The whole file as a string, for tests and for callers that want the
    /// bytes rather than a file.
    pub fn to_jsonl(&self) -> Result<String> {
        let mut bytes = Vec::new();
        self.write_to(&mut bytes)?;
        Ok(String::from_utf8(bytes).expect("serde_json emits UTF-8"))
    }

    /// Write atomically, and return the SHA-256 of what was written.
    ///
    /// The temporary file plus rename is the same discipline the cassette uses:
    /// a run that dies mid-write must not leave a checkpoint that parses to a
    /// partial store. Writing to the same path a checkpoint was read from is
    /// therefore safe, which is what a chain of chunks does.
    pub fn write(&self, path: &Path) -> Result<String> {
        let bytes = {
            let mut bytes = Vec::new();
            self.write_to(&mut bytes)?;
            bytes
        };
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)
                    .with_context(|| format!("creating {}", parent.display()))?;
            }
        }
        let temp = path.with_extension(format!("tmp{}", std::process::id()));
        std::fs::write(&temp, &bytes).with_context(|| format!("writing {}", temp.display()))?;
        std::fs::rename(&temp, path)
            .with_context(|| format!("renaming {} to {}", temp.display(), path.display()))?;
        Ok(sha256_hex(&bytes))
    }

    /// Parse JSON Lines, checking the header's totals against what was read.
    pub fn parse(source: impl BufRead) -> Result<Self> {
        let mut lines = source.lines();
        let header_line = lines
            .next()
            .transpose()
            .context("reading the checkpoint header")?
            .ok_or_else(|| anyhow::anyhow!("the checkpoint is empty; it has no header line"))?;
        let header: CheckpointHeader = serde_json::from_str(&header_line)
            .context("parsing the checkpoint header; it is not a checkpoint/v1 header line")?;
        if header.schema != CHECKPOINT_SCHEMA {
            bail!(
                "unexpected checkpoint schema `{}`, want `{CHECKPOINT_SCHEMA}`",
                header.schema
            );
        }

        let mut data_sources = Vec::new();
        let mut rows = Vec::new();
        let mut cached_absent = Vec::new();
        for (offset, line) in lines.enumerate() {
            let number = offset + 2;
            let line = line.with_context(|| format!("reading checkpoint line {number}"))?;
            if line.trim().is_empty() {
                continue;
            }
            let parsed: CheckpointLine = serde_json::from_str(&line)
                .with_context(|| format!("parsing checkpoint line {number}"))?;
            match parsed {
                CheckpointLine::DataSource(value) => data_sources.push(value),
                CheckpointLine::Row(value) => rows.push(value),
                CheckpointLine::CachedAbsent(value) => cached_absent.push(value),
            }
        }

        let checkpoint = HostCheckpoint {
            header,
            data_sources,
            rows,
            cached_absent,
        };
        checkpoint.check_totals()?;
        Ok(checkpoint)
    }

    /// Read a checkpoint from disk, returning it with the SHA-256 of the file.
    pub fn read(path: &Path) -> Result<(Self, String)> {
        let bytes = std::fs::read(path)
            .with_context(|| format!("reading checkpoint {}", path.display()))?;
        let digest = sha256_hex(&bytes);
        let checkpoint = Self::parse(BufReader::new(std::io::Cursor::new(bytes)))
            .with_context(|| format!("parsing checkpoint {}", path.display()))?;
        Ok((checkpoint, digest))
    }

    /// Recompute the totals and compare them with the header's.
    ///
    /// This is what catches a truncated file: the last row of a checkpoint cut
    /// short still parses, and only the counts reveal that the rest is missing.
    fn check_totals(&self) -> Result<()> {
        let stated = &self.header.totals;
        let mut seen = CheckpointTotals {
            dynamic_data_sources: self.data_sources.len(),
            cached_absent: self.cached_absent.len(),
            ..CheckpointTotals::default()
        };
        // The header's `counts_by_type` names the proof-of-indexing type only
        // implicitly, so the split is recovered from the stated totals instead:
        // the rows are counted whole here and the split is checked below.
        for row in &self.rows {
            seen.fields += row.fields.len();
            if row.cached {
                seen.cached_present += 1;
            }
        }
        if self.rows.len() != stated.rows + stated.poi_rows {
            bail!(
                "the checkpoint states {} rows and {} proof-of-indexing rows but carries {}; \
                 it is truncated or was edited",
                stated.rows,
                stated.poi_rows,
                self.rows.len()
            );
        }
        let mismatches = [
            (
                "dynamic data sources",
                seen.dynamic_data_sources,
                stated.dynamic_data_sources,
            ),
            ("fields", seen.fields, stated.fields),
            ("cached rows", seen.cached_present, stated.cached_present),
            ("cached absences", seen.cached_absent, stated.cached_absent),
        ];
        for (what, seen, stated) in mismatches {
            if seen != stated {
                bail!(
                    "the checkpoint states {stated} {what} but carries {seen}; it is truncated \
                     or was edited"
                );
            }
        }

        let mut counts: BTreeMap<String, usize> = BTreeMap::new();
        for row in &self.rows {
            *counts.entry(row.entity_type.clone()).or_default() += 1;
        }
        if counts != self.header.counts_by_type {
            bail!("the checkpoint's per-type counts disagree with the rows it carries");
        }

        let mut ordered: Vec<MaterializedKey> =
            self.rows.iter().map(|row| row.key().ordering()).collect();
        let sorted = {
            let mut sorted = ordered.clone();
            sorted.sort();
            sorted
        };
        if ordered != sorted {
            bail!("the checkpoint's rows are not in storage-identity order");
        }
        ordered.dedup();
        if ordered.len() != self.rows.len() {
            bail!("the checkpoint carries two rows with the same storage identity");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity() -> CheckpointIdentity {
        CheckpointIdentity {
            deployment: "QmDeployment".to_string(),
            network: "mainnet".to_string(),
            spec_version: "0.0.4".to_string(),
            poi_version: "legacy".to_string(),
            poi_causality_region: "ethereum".to_string(),
            deterministic_error_policy: "fatal".to_string(),
            graph_node_rev: "77823b5".to_string(),
            bundle_lock_sha256: "aa".to_string(),
            descriptor_sha256: "bb".to_string(),
            cassette_sha256: "cc".to_string(),
        }
    }

    fn boundary() -> CheckpointBoundary {
        CheckpointBoundary {
            block: 12_370_674,
            block_hash: "0xabcd".to_string(),
            source: "fixtures".to_string(),
            chunk_from: Some(12_369_621),
            chunk_to: Some(12_370_675),
            blocks_in_chunk: 1_054,
            blocks_total: 1_054,
            chunk_index: 0,
            previous_checkpoint_sha256: None,
        }
    }

    fn row(entity_type: &str, id: &str, cached: bool) -> CheckpointRow {
        CheckpointRow {
            entity_type: entity_type.to_string(),
            id: StoreEntityId::String(id.to_string()),
            storage_causality_region: 0,
            vid: 42,
            cached,
            fields: vec![("id".to_string(), StoreValue::String(id.to_string()))],
        }
    }

    fn sample() -> HostCheckpoint {
        HostCheckpoint::new(
            identity(),
            boundary(),
            None,
            "Poi$",
            vec![CheckpointDataSource {
                template: "Pool".to_string(),
                manifest_idx: 1,
                params: vec!["0x00".to_string()],
                context: None,
                creation_block: 12_369_621,
            }],
            // Deliberately out of order: `new` sorts.
            vec![
                row("Pool", "b", true),
                row("Poi$", "a", false),
                row("Pool", "a", true),
            ],
            vec![CheckpointKey {
                entity_type: "Token".to_string(),
                id: StoreEntityId::String("missing".to_string()),
                storage_causality_region: 0,
            }],
        )
    }

    #[test]
    fn a_checkpoint_round_trips_through_json_lines() {
        let checkpoint = sample();
        let text = checkpoint.to_jsonl().expect("serialised");
        let back = HostCheckpoint::parse(text.as_bytes()).expect("parsed");
        assert_eq!(checkpoint, back);
        assert_eq!(back.to_jsonl().expect("re-serialised"), text);
    }

    #[test]
    fn rows_are_written_in_storage_identity_order() {
        let checkpoint = sample();
        let ids: Vec<_> = checkpoint
            .rows
            .iter()
            .map(|row| (row.entity_type.clone(), row.id.clone()))
            .collect();
        assert_eq!(
            ids,
            vec![
                ("Poi$".to_string(), StoreEntityId::String("a".to_string())),
                ("Pool".to_string(), StoreEntityId::String("a".to_string())),
                ("Pool".to_string(), StoreEntityId::String("b".to_string())),
            ]
        );
    }

    #[test]
    fn the_totals_are_computed_not_trusted() {
        let checkpoint = sample();
        assert_eq!(checkpoint.header.totals.rows, 2);
        assert_eq!(checkpoint.header.totals.poi_rows, 1);
        assert_eq!(checkpoint.header.totals.fields, 3);
        assert_eq!(checkpoint.header.totals.cached_present, 2);
        assert_eq!(checkpoint.header.totals.cached_absent, 1);
        assert_eq!(checkpoint.header.totals.dynamic_data_sources, 1);
    }

    #[test]
    fn a_truncated_checkpoint_is_refused() {
        let text = sample().to_jsonl().expect("serialised");
        let mut lines: Vec<&str> = text.lines().collect();
        lines.pop();
        let truncated = format!("{}\n", lines.join("\n"));
        let error = HostCheckpoint::parse(truncated.as_bytes())
            .expect_err("a checkpoint missing its last line is not loadable");
        assert!(error.to_string().contains("truncated"), "{error}");
    }

    #[test]
    fn a_reordered_checkpoint_is_refused() {
        let text = sample().to_jsonl().expect("serialised");
        let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
        // Swap the two `Pool` rows, which follow the header, the data source
        // line and the `Poi$` row.
        lines.swap(3, 4);
        let reordered = format!("{}\n", lines.join("\n"));
        let error = HostCheckpoint::parse(reordered.as_bytes())
            .expect_err("rows out of storage-identity order are not loadable");
        assert!(
            error.to_string().contains("storage-identity order"),
            "{error}"
        );
    }

    #[test]
    fn a_foreign_checkpoint_names_every_difference() {
        let mut other = identity();
        other.deployment = "QmSomethingElse".to_string();
        other.cassette_sha256 = "dd".to_string();
        let error = other
            .check_loadable_into(&identity())
            .expect_err("a checkpoint from another segment is not loadable");
        let message = error.to_string();
        assert!(message.contains("deployment:"), "{message}");
        assert!(message.contains("cassette_sha256:"), "{message}");
        assert!(!message.contains("network:"), "{message}");
    }

    #[test]
    fn a_matching_identity_loads() {
        identity()
            .check_loadable_into(&identity())
            .expect("the same host loads its own checkpoint");
    }

    #[test]
    fn a_header_that_is_not_a_checkpoint_is_refused() {
        let error = HostCheckpoint::parse(&b"{\"schema\":\"something/v1\"}\n"[..])
            .expect_err("a foreign header is not a checkpoint");
        assert!(error.to_string().contains("checkpoint"), "{error}");
    }
}
