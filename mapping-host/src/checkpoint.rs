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
use crate::calls::CassetteFingerprint;
use crate::store_state::{StoreEntityId, StorePoi, StoreValue};

/// Schema identifier written into every checkpoint's header line.
///
/// `v2` moved the cassette out of [`CheckpointIdentity`] and into its own
/// [`CassettePin`], because a `--record` run rewrites the cassette and pinning
/// its exact bytes made exactly the runs periodic checkpointing exists for
/// unresumable. `v1` is refused rather than migrated; see
/// [`HostCheckpoint::parse`].
pub const CHECKPOINT_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.checkpoint/v2";

/// The schema a `v1` checkpoint carries, named so the refusal can be specific.
pub const CHECKPOINT_SCHEMA_V1: &str = "pinax.substreams-backfills.mapping-host.checkpoint/v1";

/// The inputs a run cannot change, and that a continuation must therefore match
/// exactly.
///
/// A checkpoint is a store image plus a host set for *one* segment under *one*
/// graph-node revision. Loading it into anything else would produce a store and
/// a proof-of-indexing chain that no single run could have produced, so each
/// field below is compared and any difference is a refusal.
///
/// The cassette is deliberately **not** here. It is the one input a run may
/// legitimately rewrite, so it gets [`CassettePin`], which is a different rule.
/// Everything that remains is immutable for the life of a run: the first six
/// fields come from the resolved manifest inside the bundle, `graph_node_rev` is
/// a compile-time constant, and `bundle_lock_sha256` and `descriptor_sha256`
/// digest files that only the `build-bundles` and `build-descriptors`
/// subcommands ever write.
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
        if problems.is_empty() {
            return Ok(());
        }
        bail!(
            "this checkpoint was not taken by this host:\n{}\n\
             A checkpoint is a store image and a host set for one segment under one graph-node \
             revision. Continuing across any of those differences would produce a store and a \
             proof-of-indexing chain no single run could have produced.",
            problems.join("\n")
        )
    }
}

/// How a checkpoint pins the cassette it was taken against.
///
/// The cassette is the one input a run may rewrite, so it cannot be pinned the
/// way the bundle is. A `--record` run appends a row every time a handler makes
/// a call the file has not seen, and saves after each block, so the file the run
/// wrote is *never* the file it read. Pinning the exact bytes therefore made
/// every recording run unresumable — which is the one workflow periodic
/// checkpointing exists to serve.
///
/// The property that actually matters is weaker and is the one enforced here:
/// **the cassette has only grown.** Every row present when the checkpoint was
/// taken must still be present with the same answer, so every call the store
/// already reflects would be answered the same way again. Rows added since are
/// fine; they are what a recording run produces.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case")]
pub enum CassettePin {
    /// The run replayed the cassette without recording, so it cannot have
    /// written to it: the file must be byte-identical. This is the strictest
    /// rule and it costs nothing to keep, so a replay run keeps it.
    Exact {
        /// SHA-256 of the file. Empty when there was no cassette file.
        sha256: String,
    },
    /// The run was recording. The file may have grown; every row it held then
    /// must still be held now, unchanged. The rows themselves are carried as
    /// separate `cassette_row` lines rather than in this header, so the header
    /// stays one line whatever the cassette's size.
    Extended {
        /// SHA-256 of the file as it stood at the boundary. When the file still
        /// digests to this, nothing has changed and the row check is skipped.
        sha256: String,
        /// How many rows the cassette held, and so how many `cassette_row`
        /// lines this checkpoint carries.
        rows: usize,
    },
}

impl CassettePin {
    /// The digest of the file this checkpoint was taken against.
    pub fn sha256(&self) -> &str {
        match self {
            CassettePin::Exact { sha256 } | CassettePin::Extended { sha256, .. } => sha256,
        }
    }

    /// Which rule this pin applies, for a log line or an error.
    pub fn rule(&self) -> &'static str {
        match self {
            CassettePin::Exact { .. } => "exact bytes (the run was not recording)",
            CassettePin::Extended { .. } => "rows only grew (the run was recording)",
        }
    }
}

/// One cassette row as a checkpoint records it.
///
/// Two digests and a block number, ~130 bytes a row. The key digest is the
/// identity, the row digest is what must not have moved, and the block number is
/// there so a refusal can point an operator at a place in the file rather than
/// at a digest.
///
/// The key itself is deliberately not stored: it is a block hash, an address and
/// arbitrary calldata, which would roughly triple the size of this list for no
/// gain — a changed row is named from the cassette in hand, which does have it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointCassetteRow {
    pub block: i32,
    pub key_sha256: String,
    pub row_sha256: String,
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
    /// Cassette rows carried as `cassette_row` lines. Zero unless the run was
    /// recording; a replay run's cassette is pinned by its bytes instead.
    #[serde(default)]
    pub cassette_rows: usize,
}

/// The header line.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointHeader {
    pub schema: String,
    pub identity: CheckpointIdentity,
    /// The one input a run may rewrite, pinned by its own rule.
    pub cassette: CassettePin,
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
    /// One cassette row, present only when the run was recording.
    CassetteRow(CheckpointCassetteRow),
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
    /// Ordered by key digest. Empty unless the run was recording.
    pub cassette_rows: Vec<CheckpointCassetteRow>,
}

impl HostCheckpoint {
    /// Assemble a checkpoint and fill in its totals.
    ///
    /// `rows` and `cached_absent` are sorted here rather than trusted, so the
    /// file is byte-stable no matter what order a caller collected them in.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        identity: CheckpointIdentity,
        cassette: &CassetteFingerprint,
        boundary: CheckpointBoundary,
        poi: Option<StorePoi>,
        poi_type: &str,
        data_sources: Vec<CheckpointDataSource>,
        mut rows: Vec<CheckpointRow>,
        mut cached_absent: Vec<CheckpointKey>,
    ) -> Self {
        rows.sort_by_key(|row| row.key().ordering());
        cached_absent.sort_by_key(CheckpointKey::ordering);

        // A run that cannot write to the cassette is pinned by the file's bytes,
        // which is stricter and costs nothing. A recording run carries the rows,
        // because its file is guaranteed to differ by the time anyone resumes.
        let (pin, cassette_rows) = if cassette.recording {
            let rows: Vec<CheckpointCassetteRow> = cassette
                .rows
                .iter()
                .map(|row| CheckpointCassetteRow {
                    block: row.block,
                    key_sha256: row.key_sha256.clone(),
                    row_sha256: row.row_sha256.clone(),
                })
                .collect();
            (
                CassettePin::Extended {
                    sha256: cassette.sha256.clone(),
                    rows: rows.len(),
                },
                rows,
            )
        } else {
            (
                CassettePin::Exact {
                    sha256: cassette.sha256.clone(),
                },
                Vec::new(),
            )
        };

        let mut counts_by_type: BTreeMap<String, usize> = BTreeMap::new();
        let mut totals = CheckpointTotals {
            dynamic_data_sources: data_sources.len(),
            cached_absent: cached_absent.len(),
            cassette_rows: cassette_rows.len(),
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
                cassette: pin,
                boundary,
                poi,
                totals,
                counts_by_type,
            },
            data_sources,
            rows,
            cached_absent,
            cassette_rows,
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
        for row in &self.cassette_rows {
            let line = CheckpointLine::CassetteRow(row.clone());
            writeln!(sink, "{}", serde_json::to_string(&line)?)?;
        }
        Ok(())
    }

    /// Refuse a cassette that is not the one this checkpoint was taken against.
    ///
    /// Two rules, and which one applies is recorded in the checkpoint rather
    /// than decided by the run doing the resuming:
    ///
    /// * [`CassettePin::Exact`] — the file must be byte-identical. A run that
    ///   was not recording cannot have written to it, so anything else means
    ///   somebody or something else did.
    /// * [`CassettePin::Extended`] — the file may have grown, and every row the
    ///   checkpoint recorded must still be there with the same digest. A row
    ///   that is gone, or that answers differently, is a hard refusal naming the
    ///   call, because the store this checkpoint carries was built from that
    ///   answer and cannot be reconciled with another one.
    ///
    /// The whole-file digest short-circuits the second rule: a cassette that has
    /// not moved at all needs no row walk.
    pub fn check_cassette(&self, current: &CassetteFingerprint) -> Result<()> {
        let pin = &self.header.cassette;
        if pin.sha256() == current.sha256 {
            return Ok(());
        }
        let CassettePin::Extended { sha256, rows } = pin else {
            bail!(
                "the cassette changed underneath this checkpoint:\n  \
                 checkpoint has `{}`, this run has `{}`\n\
                 The run that wrote this checkpoint was not recording, so it could not have \
                 written to the cassette and the file was expected to be byte-identical. Point \
                 --cassette at the file that checkpoint was taken against.",
                pin.sha256(),
                current.sha256
            );
        };

        for recorded in &self.cassette_rows {
            let Some(now) = current.row(&recorded.key_sha256) else {
                bail!(
                    "a cassette row this checkpoint was built on is gone: the call recorded at \
                     block {} (key {}) is not in {} rows of the cassette this run loaded.\n\
                     The store this checkpoint carries already reflects that call's answer, so a \
                     cassette that no longer holds it cannot continue it. A recording run may \
                     only ever *add* rows.",
                    recorded.block,
                    recorded.key_sha256,
                    current.rows.len()
                );
            };
            if now.row_sha256 != recorded.row_sha256 {
                bail!(
                    "a cassette row this checkpoint was built on has changed: `{}` at block {}.\n  \
                     checkpoint recorded row digest {}\n  the cassette now holds {}\n\
                     The store this checkpoint carries was built from the old answer, so \
                     replaying on top of the new one would fold two different chains of \
                     `eth_call` results into one store.",
                    now.call,
                    now.block,
                    recorded.row_sha256,
                    now.row_sha256
                );
            }
        }

        // Only reachable when every recorded row is still there, so the file
        // genuinely only grew. Say so, because "the digest changed and the run
        // continued anyway" should never be silent.
        eprintln!(
            "cassette: {rows} recorded row(s) all still present and unchanged; the file has \
             grown to {} row(s) since this checkpoint ({sha256} -> {})",
            current.rows.len(),
            current.sha256
        );
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
    ///
    /// A `v1` checkpoint is refused with the reason rather than migrated. `v1`
    /// pinned the cassette by its exact bytes, so a `v1` checkpoint written by a
    /// `--record` run names a file that no longer exists anywhere: the run
    /// itself overwrote it on the next block. There is nothing to migrate *to*,
    /// because the information that would let a resume verify the cassette was
    /// never written down.
    pub fn parse(source: impl BufRead) -> Result<Self> {
        let mut lines = source.lines();
        let header_line = lines
            .next()
            .transpose()
            .context("reading the checkpoint header")?
            .ok_or_else(|| anyhow::anyhow!("the checkpoint is empty; it has no header line"))?;
        // Read the schema before the header, so a version this build cannot
        // parse gets the explanation rather than a serde field error.
        let schema = serde_json::from_str::<serde_json::Value>(&header_line)
            .ok()
            .and_then(|value| {
                value
                    .get("schema")
                    .and_then(serde_json::Value::as_str)
                    .map(str::to_string)
            });
        match schema.as_deref() {
            Some(CHECKPOINT_SCHEMA) => {}
            Some(CHECKPOINT_SCHEMA_V1) => bail!(
                "this is a `{CHECKPOINT_SCHEMA_V1}` checkpoint, and this build writes and reads \
                 `{CHECKPOINT_SCHEMA}`.\n\
                 A v1 checkpoint pins the cassette by the exact bytes of the file, which is a rule \
                 no --record run can satisfy: a recording run appends a row whenever a handler \
                 makes a call the file has not seen and saves after every block, so the file it \
                 wrote is never the file it read. v2 records the cassette's rows instead, and \
                 accepts a cassette that has only grown.\n\
                 A v1 checkpoint cannot be migrated, because the rows it would need were never \
                 written down and the cassette it pinned was overwritten in place. Restart the \
                 chunk that wrote it under this build.",
            ),
            Some(other) => {
                bail!("unexpected checkpoint schema `{other}`, want `{CHECKPOINT_SCHEMA}`")
            }
            None => {
                bail!("the first line of this file is not a checkpoint header; it names no schema")
            }
        }
        let header: CheckpointHeader = serde_json::from_str(&header_line)
            .context("parsing the checkpoint header; it is not a checkpoint/v2 header line")?;

        let mut data_sources = Vec::new();
        let mut rows = Vec::new();
        let mut cached_absent = Vec::new();
        let mut cassette_rows = Vec::new();
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
                CheckpointLine::CassetteRow(value) => cassette_rows.push(value),
            }
        }

        let checkpoint = HostCheckpoint {
            header,
            data_sources,
            rows,
            cached_absent,
            cassette_rows,
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
            cassette_rows: self.cassette_rows.len(),
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
            ("cassette rows", seen.cassette_rows, stated.cassette_rows),
        ];
        for (what, seen, stated) in mismatches {
            if seen != stated {
                bail!(
                    "the checkpoint states {stated} {what} but carries {seen}; it is truncated \
                     or was edited"
                );
            }
        }

        // The pin and the rows must agree, or a resume would walk a row list
        // that does not describe the cassette the header names.
        match &self.header.cassette {
            CassettePin::Exact { .. } if !self.cassette_rows.is_empty() => bail!(
                "the checkpoint pins the cassette by its exact bytes but also carries {} cassette \
                 rows; it was edited",
                self.cassette_rows.len()
            ),
            CassettePin::Extended { rows, .. } if *rows != self.cassette_rows.len() => bail!(
                "the checkpoint states {rows} cassette rows in its header but carries {}; it is \
                 truncated or was edited",
                self.cassette_rows.len()
            ),
            _ => {}
        }
        let mut keys: Vec<&str> = self
            .cassette_rows
            .iter()
            .map(|row| row.key_sha256.as_str())
            .collect();
        if keys.windows(2).any(|pair| pair[0] > pair[1]) {
            bail!("the checkpoint's cassette rows are not in key-digest order");
        }
        keys.dedup();
        if keys.len() != self.cassette_rows.len() {
            bail!("the checkpoint carries two cassette rows with the same key digest");
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
    use crate::calls::CassetteRowFingerprint;

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
        }
    }

    /// A cassette fingerprint with `calls` rows, of which the first `changed`
    /// answer differently from [`cassette`]'s.
    fn cassette_with(sha256: &str, recording: bool, calls: &[&str]) -> CassetteFingerprint {
        let mut rows: Vec<CassetteRowFingerprint> = calls
            .iter()
            .enumerate()
            .map(|(at, call)| CassetteRowFingerprint {
                block: 12_369_621 + at as i32,
                key_sha256: sha256_hex(call.as_bytes()),
                row_sha256: sha256_hex(format!("{call}=answer").as_bytes()),
                call: (*call).to_string(),
            })
            .collect();
        rows.sort_by(|a, b| a.key_sha256.cmp(&b.key_sha256));
        CassetteFingerprint {
            sha256: sha256.to_string(),
            recording,
            rows,
        }
    }

    fn cassette() -> CassetteFingerprint {
        cassette_with("cc", false, &["a", "b"])
    }

    fn recording_cassette() -> CassetteFingerprint {
        cassette_with("cc", true, &["a", "b"])
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
        sample_against(&cassette())
    }

    fn sample_against(cassette: &CassetteFingerprint) -> HostCheckpoint {
        HostCheckpoint::new(
            identity(),
            cassette,
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
        other.descriptor_sha256 = "dd".to_string();
        let error = other
            .check_loadable_into(&identity())
            .expect_err("a checkpoint from another segment is not loadable");
        let message = error.to_string();
        assert!(message.contains("deployment:"), "{message}");
        assert!(message.contains("descriptor_sha256:"), "{message}");
        assert!(!message.contains("network:"), "{message}");
    }

    // -----------------------------------------------------------------------
    // The cassette, which is the one input a run may rewrite
    // -----------------------------------------------------------------------

    #[test]
    fn a_replay_run_pins_the_cassette_by_its_bytes() {
        let checkpoint = sample_against(&cassette());
        assert_eq!(
            checkpoint.header.cassette,
            CassettePin::Exact {
                sha256: "cc".to_string()
            }
        );
        // A replay run cannot write to the cassette, so no rows are carried and
        // the file must be byte-identical.
        assert!(checkpoint.cassette_rows.is_empty());
        checkpoint
            .check_cassette(&cassette())
            .expect("the same file loads");
        let error = checkpoint
            .check_cassette(&cassette_with("dd", false, &["a", "b"]))
            .expect_err("a changed file is refused");
        let message = format!("{error:#}");
        assert!(message.contains("was not recording"), "{message}");
        assert!(message.contains("byte-identical"), "{message}");
    }

    #[test]
    fn a_recording_run_pins_the_cassette_by_its_rows() {
        let checkpoint = sample_against(&recording_cassette());
        assert_eq!(
            checkpoint.header.cassette,
            CassettePin::Extended {
                sha256: "cc".to_string(),
                rows: 2
            }
        );
        assert_eq!(checkpoint.cassette_rows.len(), 2);

        // Grown: the two recorded rows are still there, a third has appeared,
        // and the file digests differently. Accepted.
        checkpoint
            .check_cassette(&cassette_with("dd", true, &["a", "b", "c"]))
            .expect("a cassette that only grew is loadable");

        // Unchanged: the fast path, without walking a row.
        checkpoint
            .check_cassette(&recording_cassette())
            .expect("an unchanged cassette is loadable");
    }

    #[test]
    fn a_cassette_row_that_answers_differently_is_refused_by_name() {
        let checkpoint = sample_against(&recording_cassette());
        let mut grown = cassette_with("dd", true, &["a", "b", "c"]);
        // Change the answer of the row keyed `b`, leaving its key alone.
        let at = grown
            .rows
            .iter()
            .position(|row| row.call == "b")
            .expect("the row is there");
        grown.rows[at].row_sha256 = sha256_hex(b"b=something else");

        let error = checkpoint
            .check_cassette(&grown)
            .expect_err("a changed answer is refused");
        let message = format!("{error:#}");
        assert!(message.contains("has changed"), "{message}");
        // Named by the call, not by a digest.
        assert!(message.contains("`b` at block"), "{message}");
        assert!(message.contains("fold two different chains"), "{message}");
    }

    #[test]
    fn a_cassette_row_that_is_gone_is_refused() {
        let checkpoint = sample_against(&recording_cassette());
        let shrunk = cassette_with("dd", true, &["a"]);
        let error = checkpoint
            .check_cassette(&shrunk)
            .expect_err("a removed row is refused");
        let message = format!("{error:#}");
        assert!(message.contains("is gone"), "{message}");
        assert!(message.contains("may only ever *add* rows"), "{message}");
    }

    #[test]
    fn a_checkpoint_that_claims_exact_bytes_may_not_carry_rows() {
        let mut checkpoint = sample_against(&cassette());
        checkpoint.cassette_rows = vec![CheckpointCassetteRow {
            block: 1,
            key_sha256: "aa".to_string(),
            row_sha256: "bb".to_string(),
        }];
        checkpoint.header.totals.cassette_rows = 1;
        let error = HostCheckpoint::parse(checkpoint.to_jsonl().expect("serialised").as_bytes())
            .expect_err("the pin and the rows must agree");
        assert!(format!("{error:#}").contains("exact bytes"), "{error:#}");
    }

    #[test]
    fn a_truncated_cassette_row_list_is_refused() {
        let checkpoint = sample_against(&recording_cassette());
        let text = checkpoint.to_jsonl().expect("serialised");
        let mut lines: Vec<&str> = text.lines().collect();
        // The cassette rows are written last.
        lines.pop();
        let truncated = format!("{}\n", lines.join("\n"));
        let error = HostCheckpoint::parse(truncated.as_bytes())
            .expect_err("a checkpoint missing a cassette row is not loadable");
        assert!(format!("{error:#}").contains("cassette rows"), "{error:#}");
    }

    #[test]
    fn a_recording_checkpoint_round_trips_through_json_lines() {
        let checkpoint = sample_against(&recording_cassette());
        let text = checkpoint.to_jsonl().expect("serialised");
        let back = HostCheckpoint::parse(text.as_bytes()).expect("parsed");
        assert_eq!(checkpoint, back);
        assert_eq!(back.to_jsonl().expect("re-serialised"), text);
    }

    #[test]
    fn a_v1_checkpoint_is_refused_with_the_reason() {
        let error = HostCheckpoint::parse(
            format!("{{\"schema\":\"{CHECKPOINT_SCHEMA_V1}\"}}\n").as_bytes(),
        )
        .expect_err("a v1 checkpoint is not loadable");
        let message = format!("{error:#}");
        assert!(message.contains("cannot be migrated"), "{message}");
        assert!(message.contains("--record"), "{message}");
        assert!(message.contains("Restart the chunk"), "{message}");
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
