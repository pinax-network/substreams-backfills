//! Portable producer checkpoint identity. Database bytes are working state, not
//! evidence. A consumer verifies this complete canonical manifest and its pins;
//! accepting a hash supplied by the producer alone does not prove a checkpoint.
//! This codec does not certify package bytes, undo contents, or execution.
use crate::{dynamic_sources_v2::SourceOrder, state_snapshot::Boundary};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

pub const FORMAT: &str = "pinax.backfill.producer-checkpoint/v1";
pub const MAX_BYTES: usize = 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Binding {
    pub family: String,
    pub deployment: String,
    pub network: String,
    pub descriptor_sha256: String,
    pub extractor_lock_sha256: String,
    pub spkg_sha256: String,
    pub module: String,
    pub module_hash: String,
    pub reducer_commit: String,
    pub reducer_binary_sha256: String,
}
impl Binding {
    pub fn validate(&self) -> Result<(), String> {
        require(
            [&self.family, &self.deployment, &self.network, &self.module]
                .iter()
                .all(|s| !s.is_empty() && !s.chars().any(char::is_control))
                && [
                    &self.descriptor_sha256,
                    &self.extractor_lock_sha256,
                    &self.spkg_sha256,
                    &self.reducer_binary_sha256,
                ]
                .iter()
                .all(|s| digest(s))
                && hex_n(&self.module_hash, 40)
                && hex_n(&self.reducer_commit, 40),
            "invalid producer checkpoint binding",
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Origin {
    EmptyRoot {
        start_block: u64,
    },
    Snapshot {
        purpose: SnapshotPurpose,
        snapshot_sha256: String,
        seed_manifest_sha256: String,
        boundary: Boundary,
    },
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SnapshotPurpose {
    Landing,
    Oracle,
}
impl Origin {
    pub fn boundary(&self) -> Result<Boundary, String> {
        let boundary = match self {
            Self::EmptyRoot { start_block } => Boundary {
                block_number: start_block
                    .checked_sub(1)
                    .ok_or("root start must be positive")?,
                block_hash: [0; 32],
            },
            Self::Snapshot {
                snapshot_sha256,
                seed_manifest_sha256,
                boundary,
                ..
            } => {
                require(
                    digest(snapshot_sha256) && digest(seed_manifest_sha256),
                    "invalid seed pin",
                )?;
                boundary.clone()
            }
        };
        if matches!(self, Self::EmptyRoot { .. }) {
            require(
                boundary.block_number < i32::MAX as u64,
                "invalid root boundary",
            )?;
        } else {
            validate_boundary(&boundary)?;
        }
        Ok(boundary)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilePin {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
}
impl FilePin {
    pub fn validate(&self) -> Result<(), String> {
        require(
            !self.path.is_empty()
                && !self.path.contains(['\\', '\0', ':'])
                && self
                    .path
                    .split('/')
                    .all(|p| !p.is_empty() && p != "." && p != "..")
                && self.bytes > 0
                && digest(&self.sha256),
            "invalid producer evidence pin",
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Transition {
    pub from: Boundary,
    /// Root state uses the shared zero-hash sentinel. The first segment records
    /// the actual nonzero parent observed in its verified first input block.
    /// This is absent for every later or seeded transition.
    pub observed_root_parent_hash: Option<[u8; 32]>,
    pub previous_checkpoint_sha256: String,
    pub lineage_before: String,
    pub undo: FilePin,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sources {
    pub count: u64,
    pub order_sha256: String,
}
impl Sources {
    pub fn empty() -> Self {
        Self {
            count: 0,
            order_sha256: SourceOrder::empty().sha256,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FailedHosts {
    pub count: u64,
    pub sha256: String,
}
impl FailedHosts {
    pub fn empty() -> Self {
        Self {
            count: 0,
            sha256: hex::encode(Sha256::digest(b"pinax.reducer-failed-hosts/v1\0")),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub binding: Binding,
    pub origin: Origin,
    pub boundary: Boundary,
    pub engine_lineage_before: String,
    pub reducer_lineage: String,
    /// Absent only for the imported/empty initial state, which cannot seal an
    /// engine spool. Every completed segment has an undo pin and predecessor.
    pub transition: Option<Transition>,
    pub sources: Sources,
    pub failed_hosts: FailedHosts,
    pub retained_by_type: BTreeMap<String, u64>,
    /// Optional expensive full logical scan; its absence makes no state-digest
    /// claim. redb physical page layout is never used as this digest.
    pub full_state_sha256: Option<String>,
}
impl Manifest {
    pub fn validate(&self) -> Result<(), String> {
        self.binding.validate()?;
        let origin = self.origin.boundary()?;
        if self.transition.is_some() || !matches!(self.origin, Origin::EmptyRoot { .. }) {
            validate_boundary(&self.boundary)?;
        }
        require(
            self.format == FORMAT
                && digest(&self.engine_lineage_before)
                && digest(&self.reducer_lineage)
                && self.boundary.block_number >= origin.block_number,
            "invalid producer checkpoint header",
        )?;
        require(
            digest(&self.sources.order_sha256)
                && (self.sources.count != 0 || self.sources == Sources::empty())
                && digest(&self.failed_hosts.sha256)
                && (self.failed_hosts.count != 0 || self.failed_hosts == FailedHosts::empty())
                && self.full_state_sha256.as_ref().is_none_or(|s| digest(s)),
            "invalid producer state commitment",
        )?;
        require(
            self.retained_by_type
                .iter()
                .all(|(k, v)| graphql_name(k) && *v > 0),
            "invalid retained entity inventory",
        )?;
        self.retained_by_type
            .values()
            .try_fold(0u64, |n, v| n.checked_add(*v))
            .ok_or("retained count overflow")?;
        if let Some(t) = &self.transition {
            let root_start = matches!(self.origin, Origin::EmptyRoot { .. }) && t.from == origin;
            if root_start {
                require(
                    t.observed_root_parent_hash.is_some_and(|h| h != [0; 32]),
                    "initial segment lacks observed parent",
                )?;
            } else {
                validate_boundary(&t.from)?;
                require(
                    t.observed_root_parent_hash.is_none(),
                    "unexpected root parent observation",
                )?;
            }
            t.undo.validate()?;
            require(
                t.from.block_number >= origin.block_number
                    && t.from.block_number < self.boundary.block_number
                    && digest(&t.previous_checkpoint_sha256)
                    && self.reducer_lineage == advance_lineage(&t.lineage_before, &t.undo.sha256)?,
                "invalid reducer checkpoint transition",
            )?;
            if t.from.block_number == origin.block_number {
                require(
                    t.from == origin
                        && t.lineage_before == initial_lineage(&self.binding, &self.origin)?,
                    "initial reducer checkpoint ancestry mismatch",
                )?;
            }
        } else {
            require(
                self.boundary == origin
                    && self.reducer_lineage == initial_lineage(&self.binding, &self.origin)?,
                "initial reducer checkpoint boundary/lineage mismatch",
            )?;
            if matches!(self.origin, Origin::EmptyRoot { .. }) {
                require(
                    self.sources == Sources::empty()
                        && self.failed_hosts == FailedHosts::empty()
                        && self.retained_by_type.is_empty(),
                    "nonempty root producer checkpoint",
                )?;
            }
        }
        Ok(())
    }
    pub fn encode(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        let mut bytes = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        require(
            bytes.len() <= MAX_BYTES,
            "producer checkpoint exceeds byte ceiling",
        )?;
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, String> {
        require(
            !bytes.is_empty() && bytes.len() <= MAX_BYTES,
            "producer checkpoint exceeds byte ceiling",
        )?;
        let value: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        require(
            value.encode()? == bytes,
            "noncanonical producer checkpoint JSON",
        )?;
        Ok(value)
    }
    /// Checks actual retained manifest bytes against an independently supplied
    /// digest and complete producer binding. This does not open undo evidence.
    pub fn verify(bytes: &[u8], expected_sha256: &str, binding: &Binding) -> Result<Self, String> {
        require(
            digest(expected_sha256) && hex::encode(Sha256::digest(bytes)) == expected_sha256,
            "producer checkpoint digest mismatch",
        )?;
        let manifest = Self::decode(bytes)?;
        require(
            &manifest.binding == binding,
            "producer checkpoint binding mismatch",
        )?;
        Ok(manifest)
    }
    /// The predecessor file is supplied by the consumer, not trusted by path.
    pub fn require_predecessor(&self, previous_bytes: &[u8]) -> Result<(), String> {
        self.validate()?;
        let t = self
            .transition
            .as_ref()
            .ok_or("initial checkpoint has no predecessor")?;
        let previous = Self::verify(previous_bytes, &t.previous_checkpoint_sha256, &self.binding)?;
        require(
            previous.origin == self.origin
                && previous.boundary == t.from
                && previous.reducer_lineage == t.lineage_before
                && previous.sources.count <= self.sources.count
                && (previous.sources.count != self.sources.count
                    || previous.sources == self.sources)
                && previous.failed_hosts.count <= self.failed_hosts.count
                && (previous.failed_hosts.count != self.failed_hosts.count
                    || previous.failed_hosts == self.failed_hosts),
            "producer checkpoint predecessor mismatch",
        )
    }
    pub fn require_loadable(&self) -> Result<(), String> {
        self.validate()?;
        require(
            !matches!(
                self.origin,
                Origin::Snapshot {
                    purpose: SnapshotPurpose::Oracle,
                    ..
                }
            ),
            "oracle producer state is never loadable",
        )
    }
}
pub fn initial_lineage(binding: &Binding, origin: &Origin) -> Result<String, String> {
    binding.validate()?;
    origin.boundary()?;
    let mut h = Sha256::new();
    h.update(b"pinax.reducer-origin/v1\0");
    // Tuple serialization avoids ambiguity between variable-width objects.
    h.update(serde_json::to_vec(&(binding, origin)).map_err(|e| e.to_string())?);
    Ok(hex::encode(h.finalize()))
}
pub fn advance_lineage(before: &str, undo_sha256: &str) -> Result<String, String> {
    require(
        digest(before) && digest(undo_sha256),
        "invalid reducer lineage inputs",
    )?;
    let mut h = Sha256::new();
    h.update(b"pinax.reducer-lineage/v1\0");
    h.update(hex::decode(before).map_err(|e| e.to_string())?);
    h.update(hex::decode(undo_sha256).map_err(|e| e.to_string())?);
    Ok(hex::encode(h.finalize()))
}
fn validate_boundary(b: &Boundary) -> Result<(), String> {
    require(
        b.block_number <= i32::MAX as u64 && b.block_hash != [0; 32],
        "invalid producer checkpoint boundary",
    )
}
fn hex_n(s: &str, n: usize) -> bool {
    s.len() == n
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn digest(s: &str) -> bool {
    hex_n(s, 64) && s.bytes().any(|b| b != b'0')
}
fn graphql_name(s: &str) -> bool {
    let mut b = s.bytes();
    b.next()
        .is_some_and(|b| b == b'_' || b.is_ascii_alphabetic())
        && b.all(|b| b == b'_' || b.is_ascii_alphanumeric())
}
fn require(ok: bool, message: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn root() -> Manifest {
        let binding = Binding {
            family: "aerodrome-slipstream".into(),
            deployment: "deployment".into(),
            network: "base".into(),
            descriptor_sha256: "11".repeat(32),
            extractor_lock_sha256: "22".repeat(32),
            spkg_sha256: "33".repeat(32),
            module: "map_extractor_block".into(),
            module_hash: "44".repeat(20),
            reducer_commit: "55".repeat(20),
            reducer_binary_sha256: "66".repeat(32),
        };
        let origin = Origin::EmptyRoot { start_block: 100 };
        Manifest {
            format: FORMAT.into(),
            boundary: origin.boundary().unwrap(),
            reducer_lineage: initial_lineage(&binding, &origin).unwrap(),
            binding,
            origin,
            engine_lineage_before: "88".repeat(32),
            transition: None,
            sources: Sources::empty(),
            failed_hosts: FailedHosts::empty(),
            retained_by_type: BTreeMap::new(),
            full_state_sha256: None,
        }
    }
    fn next(previous: &Manifest) -> Manifest {
        let mut m = previous.clone();
        m.boundary = Boundary {
            block_number: previous.boundary.block_number + 6,
            block_hash: [9; 32],
        };
        m.transition = Some(Transition {
            from: previous.boundary.clone(),
            observed_root_parent_hash: previous.transition.is_none().then_some([7; 32]),
            previous_checkpoint_sha256: hex::encode(Sha256::digest(previous.encode().unwrap())),
            lineage_before: previous.reducer_lineage.clone(),
            undo: FilePin {
                path: "undo/100-105.bin".into(),
                bytes: 200,
                sha256: "aa".repeat(32),
            },
        });
        m.reducer_lineage = advance_lineage(&previous.reducer_lineage, &"aa".repeat(32)).unwrap();
        m
    }
    #[test]
    fn actual_bytes_binding_and_canonical_form_are_required() {
        let m = root();
        let bytes = m.encode().unwrap();
        let hash = hex::encode(Sha256::digest(&bytes));
        assert_eq!(Manifest::verify(&bytes, &hash, &m.binding).unwrap(), m);
        assert!(Manifest::verify(&bytes, &"aa".repeat(32), &m.binding).is_err());
        let mut other = m.binding.clone();
        other.extractor_lock_sha256 = "ab".repeat(32);
        assert!(Manifest::verify(&bytes, &hash, &other).is_err());
        assert!(Manifest::decode(&serde_json::to_vec(&m).unwrap()).is_err());
        let mut value = serde_json::to_value(&m).unwrap();
        value["surprise"] = true.into();
        assert!(Manifest::decode(&serde_json::to_vec_pretty(&value).unwrap()).is_err());
        assert!(Manifest::decode(&vec![b' '; MAX_BYTES + 1]).is_err());
    }
    #[test]
    fn ancestry_undo_and_root_state_are_bound() {
        let root = root();
        let bytes = root.encode().unwrap();
        let m = next(&root);
        m.require_predecessor(&bytes).unwrap();
        let mut bad = m.clone();
        bad.transition.as_mut().unwrap().undo.sha256 = "bb".repeat(32);
        assert!(bad.validate().is_err());
        let mut bad = m.clone();
        bad.transition.as_mut().unwrap().from.block_hash = [6; 32];
        assert!(bad.validate().is_err());
        let mut bad = m.clone();
        bad.transition.as_mut().unwrap().undo.path = "../undo".into();
        assert!(bad.validate().is_err());
        let mut bad = root.clone();
        bad.retained_by_type.insert("Pool".into(), 1);
        assert!(bad.validate().is_err());
        let mut other = root.clone();
        other.engine_lineage_before = "cc".repeat(32);
        assert!(m.require_predecessor(&other.encode().unwrap()).is_err());
        let mut bad = m;
        bad.reducer_lineage = "dd".repeat(32);
        assert!(bad.validate().is_err());
    }
    #[test]
    fn oracle_origin_can_be_a_diagnostic_but_never_loadable() {
        let mut m = root();
        m.boundary.block_hash = [7; 32];
        m.origin = Origin::Snapshot {
            purpose: SnapshotPurpose::Oracle,
            snapshot_sha256: "ab".repeat(32),
            seed_manifest_sha256: "bc".repeat(32),
            boundary: m.boundary.clone(),
        };
        m.reducer_lineage = initial_lineage(&m.binding, &m.origin).unwrap();
        m.validate().unwrap();
        assert!(m.require_loadable().is_err());
        m.origin = Origin::Snapshot {
            purpose: SnapshotPurpose::Landing,
            snapshot_sha256: "ab".repeat(32),
            seed_manifest_sha256: "bc".repeat(32),
            boundary: m.boundary.clone(),
        };
        m.reducer_lineage = initial_lineage(&m.binding, &m.origin).unwrap();
        m.require_loadable().unwrap();
    }
    #[test]
    fn invalid_boundary_counters_and_empty_commitments_are_refused() {
        for mutate in [
            |m: &mut Manifest| m.boundary.block_hash = [9; 32],
            |m: &mut Manifest| m.sources.order_sha256 = "aa".repeat(32),
            |m: &mut Manifest| m.failed_hosts.sha256 = "bb".repeat(32),
            |m: &mut Manifest| m.binding.extractor_lock_sha256 = "00".repeat(32),
            |m: &mut Manifest| {
                m.retained_by_type
                    .insert("bad-name".into(), 1)
                    .map(|_| ())
                    .unwrap_or(())
            },
        ] {
            let mut m = root();
            mutate(&mut m);
            assert!(m.validate().is_err());
        }
    }
    #[test]
    fn append_only_inventories_cannot_shrink_or_change_without_growth() {
        let mut previous = next(&root());
        previous.sources = Sources {
            count: 1,
            order_sha256: "ac".repeat(32),
        };
        previous.failed_hosts = FailedHosts {
            count: 1,
            sha256: "ad".repeat(32),
        };
        let bytes = previous.encode().unwrap();
        let next = next(&previous);
        next.require_predecessor(&bytes).unwrap();
        for mutate in [
            |m: &mut Manifest| m.sources = Sources::empty(),
            |m: &mut Manifest| m.sources.order_sha256 = "bc".repeat(32),
            |m: &mut Manifest| m.failed_hosts = FailedHosts::empty(),
            |m: &mut Manifest| m.failed_hosts.sha256 = "bd".repeat(32),
        ] {
            let mut m = next.clone();
            mutate(&mut m);
            assert!(m.require_predecessor(&bytes).is_err());
        }
    }
}
