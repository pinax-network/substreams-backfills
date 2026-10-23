//! Typed capture evidence shared by the seed producer, reducer and engine.
//!
//! A digest authenticates bytes only against the consumer's external pin. This
//! codec does not authenticate a database, attest the executable that ran, prove
//! worker exclusion, or authorize a database write. The capture implementation
//! must observe these fields in one read-only repeatable-read transaction.
//! Consumers stage every row until `SeedSnapshotReader::finish` succeeds.
use crate::{
    producer_checkpoint::{FilePin, SnapshotPurpose},
    state_snapshot::{
        self as snapshot, Boundary, Limits, ReadPurpose, SeedOrigin, SnapshotBinding,
        SnapshotHeader, SnapshotOrigin, SnapshotReader, SnapshotRecord, VerifiedSnapshot,
    },
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Read};

pub const FORMAT: &str = "pinax.graph-node.generic-seed-manifest/v1";
pub const MAX_BYTES: usize = 4 * 1024 * 1024;

/// Independently supplied capture/target identity. Never derive the expected
/// binding or expected manifest digest from the manifest being verified.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Binding {
    pub snapshot: SnapshotBinding,
    pub purpose: SnapshotPurpose,
    pub boundary: Boundary,
    pub start_block: u64,
    pub target: Target,
    pub profile_sha256: String,
    pub catalog_sha256: String,
    pub schema_sha256: String,
    pub raw_manifest_sha256: String,
    pub capture_binary_sha256: String,
    /// The version that created the stored manifest. This is not a claim about
    /// the current writer image; the operational run binding verifies that.
    pub creating_graph_node: GraphNode,
    pub spec_version: String,
    /// The deployment's manifest graft is separate from a physical self-copy.
    pub manifest_graft: Option<Graft>,
    pub landing_graft: Option<LandingGraft>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Target {
    pub schema: String,
    pub site_id: i32,
    pub database: String,
    pub system_identifier: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphNode {
    pub version: String,
    pub commit: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Graft {
    pub base: String,
    pub block: u64,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum LandingGraft {
    SelfCopy { base: String, boundary: Boundary },
}
impl Binding {
    pub fn validate(&self) -> Result<(), String> {
        self.snapshot.validate()?;
        boundary(&self.boundary)?;
        require(
            self.start_block > 0
                && self.start_block <= self.boundary.block_number + 1
                && self.target.site_id >= 0
                && self.target.schema == format!("sgd{}", self.target.site_id)
                && text(&self.target.database)
                && !self.target.system_identifier.is_empty()
                && self
                    .target
                    .system_identifier
                    .bytes()
                    .all(|b| b.is_ascii_digit())
                && [
                    &self.profile_sha256,
                    &self.catalog_sha256,
                    &self.schema_sha256,
                    &self.raw_manifest_sha256,
                    &self.capture_binary_sha256,
                ]
                .iter()
                .all(|s| digest(s))
                && text(&self.creating_graph_node.version)
                && hex_n(&self.creating_graph_node.commit, 40)
                && text(&self.spec_version),
            "invalid seed capture binding",
        )?;
        if let Some(graft) = &self.manifest_graft {
            require(
                text(&graft.base) && graft.block <= self.boundary.block_number,
                "invalid manifest graft",
            )?;
        }
        if let Some(LandingGraft::SelfCopy {
            base,
            boundary: copy,
        }) = &self.landing_graft
        {
            boundary(copy)?;
            require(
                self.purpose == SnapshotPurpose::Landing
                    && self.manifest_graft.is_none()
                    && base == &self.snapshot.deployment
                    && copy.block_number < self.boundary.block_number,
                "self-copy landing graft differs from deployment or remains pending",
            )?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeploymentObservation {
    pub deployment: String,
    pub spec_version: String,
    pub start_parent: Boundary,
    pub graft: Option<ObservedGraft>,
    pub schema_sha256: String,
    pub raw_manifest_sha256: String,
    pub creating_graph_node: GraphNode,
    pub failed: bool,
    pub fatal_error: Option<String>,
    pub retained_error_count: u64,
    pub current_reorg_depth: u32,
    /// Observed deferred attribute/query-index state, not a data-completeness
    /// predicate. The exact physical profile/catalog remains independently bound.
    pub postponed_indexes_created: bool,
    pub namespace_count: u32,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObservedGraft {
    pub base: String,
    pub boundary: Boundary,
}

/// SQL settings and lock results, observed in the same capture transaction.
/// Locks are not a substitute for the independently verified stopped writer.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TransactionObservation {
    pub isolation: String,
    pub read_only: bool,
    pub backend_pid: u32,
    pub write_lock: bool,
    pub copy_lock: bool,
    pub prune_lock: bool,
}

/// A changed `history_blocks` setting cannot recover already pruned history.
/// Complete coverage therefore also binds the observed earliest block and all
/// physical entity-table prune markers. Unsupported capture provenance remains
/// useful for diagnostics but cannot certify complete historical source state.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum History {
    Unproven {
        reason: String,
    },
    UnprunedFromDeploymentStart {
        history_blocks: u64,
        earliest_block: u64,
        /// Exact physical entity inventory, keyed by logical entity type. Values
        /// are Graph Node's LEFT JOIN-derived prune markers: an absent table_stats
        /// row and a row with SQL NULL both produce None. Missing entity keys are
        /// still refused; the observed earliest block independently bounds pruning.
        table_last_pruned_block: BTreeMap<String, Option<u64>>,
    },
}
impl History {
    fn validate(&self, binding: &Binding) -> Result<(), String> {
        match self {
            Self::Unproven { reason } => require(text(reason), "missing history refusal reason"),
            Self::UnprunedFromDeploymentStart {
                history_blocks,
                earliest_block,
                table_last_pruned_block,
            } => require(
                *history_blocks == i32::MAX as u64
                    && *earliest_block < binding.start_block
                    && table_last_pruned_block
                        .keys()
                        .eq(binding.snapshot.type_ordinals.iter())
                    && table_last_pruned_block
                        .values()
                        .all(|p| p.is_none_or(|p| p < binding.start_block)),
                "history observations do not cover deployment start",
            ),
        }
    }
    fn require_complete(&self) -> Result<(), String> {
        require(
            matches!(self, Self::UnprunedFromDeploymentStart { .. }),
            "seed historical source/error coverage remains unproven",
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceCommitment {
    pub count: u64,
    pub max_vid: i32,
    pub order_sha256: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub binding: Binding,
    pub snapshot: FilePin,
    pub lineage: String,
    pub capture: SeedOrigin,
    pub deployment: DeploymentObservation,
    pub transaction: TransactionObservation,
    pub history: History,
    pub catalog_sha256: String,
    pub sources: SourceCommitment,
    pub captured_rows: BTreeMap<String, u64>,
}
impl Manifest {
    pub fn validate(&self) -> Result<(), String> {
        self.binding.validate()?;
        self.snapshot.validate()?;
        self.history.validate(&self.binding)?;
        let b = &self.binding;
        let c = &self.capture;
        let d = &self.deployment;
        boundary(&c.head)?;
        boundary(&d.start_parent)?;
        require(
            self.format == FORMAT
                && digest(&self.lineage)
                && self.lineage
                    == hex::encode(snapshot::initial_lineage(hash(&self.snapshot.sha256)?))
                && c.schema == b.target.schema
                && c.site_id == b.target.site_id
                && c.database == b.target.database
                && c.system_identifier == b.target.system_identifier
                && c.server_version_num > 0
                && c.capture_tool_sha256 == b.capture_binary_sha256
                && c.profile_sha256 == b.profile_sha256
                && c.health == "healthy"
                && c.non_fatal_errors.is_empty()
                && d.deployment == b.snapshot.deployment
                && d.spec_version == b.spec_version
                && d.start_parent.block_number + 1 == b.start_block
                && d.schema_sha256 == b.schema_sha256
                && d.raw_manifest_sha256 == b.raw_manifest_sha256
                && d.creating_graph_node == b.creating_graph_node
                && !d.failed
                && d.fatal_error.is_none()
                && d.retained_error_count == 0
                && d.current_reorg_depth == 0
                && d.namespace_count == 1
                && self.catalog_sha256 == b.catalog_sha256,
            "seed capture/deployment observation mismatch or unhealthy source",
        )?;
        let expected_graft = match (&b.landing_graft, &b.manifest_graft) {
            (Some(LandingGraft::SelfCopy { base, boundary }), None) => {
                Some((base, boundary.block_number))
            }
            (None, Some(g)) => Some((&g.base, g.block)),
            (None, None) => None,
            _ => return Err("conflicting graft identities".into()),
        };
        require(
            d.graft.as_ref().map(|g| (&g.base, g.boundary.block_number)) == expected_graft,
            "observed graft differs from binding",
        )?;
        if let Some(g) = &d.graft {
            boundary(&g.boundary)?;
        }
        if let (Some(LandingGraft::SelfCopy { boundary, .. }), Some(g)) =
            (&b.landing_graft, &d.graft)
        {
            require(boundary == &g.boundary, "self-copy graft hash mismatch")?;
        }
        match b.purpose {
            SnapshotPurpose::Landing => require(c.head == b.boundary, "landing head mismatch")?,
            SnapshotPurpose::Oracle => {
                require(
                    c.head.block_number >= b.boundary.block_number
                        && (c.head.block_number != b.boundary.block_number || c.head == b.boundary),
                    "oracle boundary follows head",
                )?;
                self.history.require_complete()?;
            }
        }
        let t = &self.transaction;
        require(
            t.isolation == "repeatable read"
                && t.read_only
                && t.backend_pid > 0
                && t.write_lock
                && t.copy_lock
                && t.prune_lock,
            "capture lacks one read-only repeatable-read transaction and all three locks",
        )?;
        require(
            self.captured_rows
                .keys()
                .eq(b.snapshot.type_ordinals.iter())
                && digest(&self.sources.order_sha256)
                && self.sources.max_vid >= -1,
            "invalid capture row/source inventory",
        )?;
        self.captured_rows
            .values()
            .try_fold(0u64, |n, v| n.checked_add(*v))
            .ok_or("captured count overflow")?;
        Ok(())
    }
    pub fn encode(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        let mut bytes = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        require(
            bytes.len() <= MAX_BYTES,
            "seed manifest exceeds byte ceiling",
        )?;
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, String> {
        require(
            !bytes.is_empty() && bytes.len() <= MAX_BYTES,
            "seed manifest exceeds byte ceiling",
        )?;
        let value: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        require(value.encode()? == bytes, "noncanonical seed manifest JSON")?;
        Ok(value)
    }
    pub fn verify(bytes: &[u8], expected_sha256: &str, expected: &Binding) -> Result<Self, String> {
        require(
            digest(expected_sha256) && hex::encode(Sha256::digest(bytes)) == expected_sha256,
            "seed manifest digest mismatch",
        )?;
        expected.validate()?;
        let manifest = Self::decode(bytes)?;
        require(
            &manifest.binding == expected,
            "seed manifest binding mismatch",
        )?;
        Ok(manifest)
    }
    /// Structural comparison only. Full snapshot evidence is obtained exclusively
    /// through `SeedSnapshotReader`, which binds this header to the actual stream.
    pub fn validate_header(&self, header: &SnapshotHeader) -> Result<(), String> {
        self.validate()?;
        header.validate()?;
        header.require_binding(&self.binding.snapshot)?;
        let seed = match (&self.binding.purpose, &header.origin) {
            (SnapshotPurpose::Landing, SnapshotOrigin::Landing { seed }) => seed,
            (SnapshotPurpose::Oracle, SnapshotOrigin::Oracle { seed }) => seed,
            _ => return Err("seed purpose differs from snapshot origin".into()),
        };
        require(
            seed == &self.capture
                && header.boundary == self.binding.boundary
                && header.sources.count == self.sources.count
                && header.sources.max_vid == self.sources.max_vid
                && header.sources.order_sha256 == self.sources.order_sha256
                && header.records == self.captured_rows.values().sum::<u64>(),
            "seed manifest differs from snapshot header",
        )
    }
}

/// Provisional streaming admission; no verified token exists before checksum/EOF
/// and actual per-type row-count checks. Retain the externally pinned manifest.
pub struct SeedSnapshotReader<R> {
    reader: SnapshotReader<R>,
    manifest: Manifest,
    manifest_sha256: String,
    counts: BTreeMap<String, u64>,
}
impl<R: Read> SeedSnapshotReader<R> {
    pub fn new(
        reader: R,
        manifest: &[u8],
        expected_sha256: &str,
        expected: &Binding,
        purpose: ReadPurpose,
        limits: Limits,
    ) -> Result<Self, String> {
        let manifest = Manifest::verify(manifest, expected_sha256, expected)?;
        if matches!(purpose, ReadPurpose::Loadable) {
            require(
                expected.purpose == SnapshotPurpose::Landing,
                "oracle seed is never loadable",
            )?;
            manifest.history.require_complete()?;
        }
        let reader = SnapshotReader::new(reader, &expected.snapshot, purpose, limits)?;
        manifest.validate_header(reader.header())?;
        let counts = expected
            .snapshot
            .type_ordinals
            .iter()
            .map(|k| (k.clone(), 0))
            .collect();
        Ok(Self {
            reader,
            manifest,
            manifest_sha256: expected_sha256.into(),
            counts,
        })
    }
    pub fn header(&self) -> &SnapshotHeader {
        self.reader.header()
    }
    pub fn next_record(&mut self) -> Result<Option<SnapshotRecord>, String> {
        let record = self.reader.next_record()?;
        if let Some(record) = &record {
            let key = snapshot::decode_key(&self.manifest.binding.snapshot, &record.key)?;
            let count = self
                .counts
                .get_mut(&key.entity_type)
                .ok_or("unknown snapshot entity type")?;
            *count = count.checked_add(1).ok_or("captured count overflow")?;
        }
        Ok(record)
    }
    pub fn finish(self) -> Result<VerifiedSeed, String> {
        let snapshot = self.reader.finish()?;
        require(
            hex::encode(snapshot.file_sha256()) == self.manifest.snapshot.sha256
                && snapshot.bytes() == self.manifest.snapshot.bytes
                && hex::encode(snapshot.lineage()) == self.manifest.lineage
                && self.counts == self.manifest.captured_rows,
            "seed snapshot identity or row inventory mismatch",
        )?;
        Ok(VerifiedSeed {
            manifest: self.manifest,
            manifest_sha256: self.manifest_sha256,
            snapshot,
        })
    }
}
#[derive(Debug)]
pub struct VerifiedSeed {
    manifest: Manifest,
    manifest_sha256: String,
    snapshot: VerifiedSnapshot,
}
impl VerifiedSeed {
    pub fn manifest(&self) -> &Manifest {
        &self.manifest
    }
    pub fn manifest_sha256(&self) -> &str {
        &self.manifest_sha256
    }
    pub fn snapshot(&self) -> &VerifiedSnapshot {
        &self.snapshot
    }
    pub fn require_loadable(&self) -> Result<(), String> {
        require(
            self.manifest.binding.purpose == SnapshotPurpose::Landing,
            "oracle seed is never loadable",
        )?;
        self.manifest.history.require_complete()
    }
    pub fn require_complete_source_history(&self) -> Result<(), String> {
        self.manifest.history.require_complete()
    }
}
fn require(ok: bool, why: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(why.into())
    }
}
fn boundary(b: &Boundary) -> Result<(), String> {
    require(
        b.block_number <= i32::MAX as u64 && b.block_hash != [0; 32],
        "invalid observed seed boundary",
    )
}
fn text(s: &str) -> bool {
    !s.is_empty() && !s.chars().any(char::is_control)
}
fn hex_n(s: &str, n: usize) -> bool {
    s.len() == n
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn digest(s: &str) -> bool {
    hex_n(s, 64)
}
fn hash(s: &str) -> Result<[u8; 32], String> {
    hex::decode(s)
        .map_err(|e| e.to_string())?
        .try_into()
        .map_err(|_| "invalid digest".into())
}
