//! Atomic BCGSNAP1 import with separate development and typed capture paths.
use super::*;
use backfill_common::{
    descriptor::RetentionClass,
    pb::pinax::graph::backfill::v1::entity_id,
    producer_checkpoint::SnapshotPurpose,
    seed_manifest::{self as capture, SeedSnapshotReader},
    state_snapshot::{
        self as snapshot, EntityIdPolicy, ReadPurpose, SnapshotBinding, SnapshotOrigin,
    },
};

/// BCGSNAP1 cannot recover failed Factory hosts. This assertion must come from
/// the caller's capture evidence, not be inferred from a checksum or row count.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceHistoryAssertion {
    CompleteSuccessfulSourcesNoFailedHosts,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedImportPins {
    pub snapshot_sha256: [u8; 32],
    pub seed_manifest_sha256: [u8; 32],
    pub profile_sha256: [u8; 32],
    pub boundary: Boundary,
    pub purpose: SnapshotPurpose,
    pub source_history: SourceHistoryAssertion,
    pub engine_lineage: [u8; 32],
}

/// External capture identity supplied independently of the manifest being read.
/// The engine lineage must equal the exact snapshot's initial lineage.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CapturedSeedPins {
    pub seed_manifest_sha256: [u8; 32],
    pub capture_binding: capture::Binding,
    pub engine_lineage: [u8; 32],
}

enum ImportReader<R> {
    Development(Box<snapshot::SnapshotReader<R>>),
    Captured(Box<SeedSnapshotReader<R>>),
}
impl<R: Read> ImportReader<R> {
    fn header(&self) -> &snapshot::SnapshotHeader {
        match self {
            Self::Development(r) => r.header(),
            Self::Captured(r) => r.header(),
        }
    }
    fn next_record(&mut self) -> std::result::Result<Option<snapshot::SnapshotRecord>, String> {
        match self {
            Self::Development(r) => r.next_record(),
            Self::Captured(r) => r.next_record(),
        }
    }
    fn finish(self) -> std::result::Result<snapshot::VerifiedSnapshot, String> {
        match self {
            Self::Development(r) => r.finish(),
            Self::Captured(r) => {
                // This token exists only after the exact complete imported stream.
                let verified = r.finish()?;
                verified.require_complete_source_history()?;
                Ok(verified.snapshot().clone())
            }
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ImportEvidence {
    format: String,
    production_selectable: bool,
    capture_manifest_verified: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    capture_binding: Option<capture::Binding>,
    pins: SeedImportPins,
    header: snapshot::SnapshotHeader,
    snapshot_bytes: u64,
    retained_by_type: BTreeMap<String, u64>,
    logical_state_sha256: String,
}

pub(super) fn snapshot_binding(input: &InputBinding) -> SnapshotBinding {
    let cap = input.compatibility().capabilities().unwrap();
    SnapshotBinding {
        deployment: cap.deployment.clone(),
        network: "base".into(),
        descriptor_sha256: hex::encode(input.compatibility().id()),
        retention_sha256: hex::encode(cap.retention_sha256()),
        type_ordinals: cap.storage_profile.entity_types.clone(),
        entity_id_policy: EntityIdPolicy::StringOnly,
    }
}

impl DurableStore {
    /// Runtime consumers must call this before using seeded state. Empty-root
    /// state has no imported history; imported state requires the typed E5 path.
    /// Oracle state can be replayed for comparison, but its manifest remains
    /// non-loadable. This does not certify the current runtime or a DB writer.
    pub fn require_complete_seed_history(&self) -> Result<()> {
        let manifest = self.manifest()?;
        if matches!(manifest.origin, Origin::EmptyRoot { .. }) {
            return Ok(());
        }
        let tx = self.database.begin_read().map_err(error)?;
        let table = tx.open_table(META).map_err(error)?;
        let value = table
            .get("seed-import")
            .map_err(error)?
            .ok_or_else(|| refuse("seed import evidence missing"))?;
        let evidence: ImportEvidence = decode(value.value())?;
        require(
            evidence.capture_manifest_verified && evidence.capture_binding.is_some(),
            "seed history requires verified capture evidence",
        )
    }

    /// Stream an independently pinned landing/oracle snapshot into a new store.
    /// No initialized state is committed until the common reader proves trailer,
    /// checksum, exact EOF and full-file digest. Failures leave an uninitialized
    /// directory for diagnosis; they never replace or resume another store.
    ///
    /// Manifest bytes are retained verbatim as opaque evidence. This development
    /// API does not authenticate their contents, physical layout, stopped-writer
    /// status or complete historical error inventory. E5's typed capture verifier
    /// is required before any production seed selection.
    pub fn import_snapshot<R: Read>(
        root: &Path,
        input: &InputBinding,
        binding: Binding,
        snapshot_input: R,
        seed_manifest: &[u8],
        pins: SeedImportPins,
        cache_bytes: usize,
    ) -> Result<Self> {
        bind(input, &binding)?;
        require(cache_bytes > 0, "state cache must be positive")?;
        require(
            !seed_manifest.is_empty()
                && seed_manifest.len() <= checkpoint::MAX_BYTES
                && <[u8; 32]>::from(Sha256::digest(seed_manifest)) == pins.seed_manifest_sha256,
            "seed manifest bytes/size/digest differ",
        )?;
        let expected = snapshot_binding(input);
        let purpose = match pins.purpose {
            SnapshotPurpose::Landing => ReadPurpose::Loadable,
            SnapshotPurpose::Oracle => ReadPurpose::OracleComparison,
        };
        let reader = snapshot::SnapshotReader::new(
            snapshot_input,
            &expected,
            purpose,
            snapshot::Limits::default(),
        )
        .map_err(error)?;
        Self::import_reader(
            root,
            input,
            binding,
            ImportReader::Development(Box::new(reader)),
            seed_manifest,
            pins,
            None,
            cache_bytes,
        )
    }

    /// Import using E5's typed capture verifier. No caller history assertion is
    /// accepted here. This establishes capture evidence, not worker exclusion,
    /// physical-profile selection, runtime certification or loading authority.
    pub fn import_captured_snapshot<R: Read>(
        root: &Path,
        input: &InputBinding,
        binding: Binding,
        snapshot_input: R,
        seed_manifest: &[u8],
        pins: CapturedSeedPins,
        cache_bytes: usize,
    ) -> Result<Self> {
        bind(input, &binding)?;
        require(cache_bytes > 0, "state cache must be positive")?;
        let expected = &pins.capture_binding;
        let cap = input.compatibility().capabilities().unwrap();
        require(
            expected.snapshot == snapshot_binding(input)
                && expected.start_block == cap.start_block
                && expected.spec_version == cap.spec_version
                && expected.manifest_graft.is_none()
                && expected.schema_sha256
                    == hex::encode(Sha256::digest(include_bytes!(
                        "../../../../aerodrome-slipstream-base/reference/schema.graphql"
                    ))),
            "capture binding differs from locked Aerodrome deployment/schema",
        )?;
        let expected_sha = hex::encode(pins.seed_manifest_sha256);
        let manifest =
            capture::Manifest::verify(seed_manifest, &expected_sha, expected).map_err(error)?;
        let hash = |s: &str| -> Result<[u8; 32]> {
            hex::decode(s)
                .map_err(error)?
                .try_into()
                .map_err(|_| refuse("capture hash length differs"))
        };
        let imported = SeedImportPins {
            snapshot_sha256: hash(&manifest.snapshot.sha256)?,
            seed_manifest_sha256: pins.seed_manifest_sha256,
            profile_sha256: hash(&expected.profile_sha256)?,
            boundary: expected.boundary.clone(),
            purpose: expected.purpose.clone(),
            // This private compatibility record is derived from the typed
            // verifier; the public captured path takes no such assertion.
            source_history: SourceHistoryAssertion::CompleteSuccessfulSourcesNoFailedHosts,
            engine_lineage: pins.engine_lineage,
        };
        let purpose = match expected.purpose {
            SnapshotPurpose::Landing => ReadPurpose::Loadable,
            SnapshotPurpose::Oracle => ReadPurpose::OracleComparison,
        };
        let reader = SeedSnapshotReader::new(
            snapshot_input,
            seed_manifest,
            &expected_sha,
            expected,
            purpose,
            snapshot::Limits::default(),
        )
        .map_err(error)?;
        Self::import_reader(
            root,
            input,
            binding,
            ImportReader::Captured(Box::new(reader)),
            seed_manifest,
            imported,
            Some(pins.capture_binding),
            cache_bytes,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn import_reader<R: Read>(
        root: &Path,
        input: &InputBinding,
        binding: Binding,
        mut reader: ImportReader<R>,
        seed_manifest: &[u8],
        pins: SeedImportPins,
        capture_binding: Option<capture::Binding>,
        cache_bytes: usize,
    ) -> Result<Self> {
        let expected = snapshot_binding(input);
        let header = reader.header().clone();
        let provenance = match (&header.origin, &pins.purpose) {
            (SnapshotOrigin::Landing { seed }, SnapshotPurpose::Landing)
            | (SnapshotOrigin::Oracle { seed }, SnapshotPurpose::Oracle) => seed,
            _ => return Err(refuse("snapshot origin differs from explicit seed purpose")),
        };
        require(
            header.boundary == pins.boundary
                && header.next_block() >= input.compatibility().capabilities().unwrap().start_block
                && provenance.profile_sha256 == hex::encode(pins.profile_sha256)
                && provenance.health == "healthy"
                && provenance.non_fatal_errors.is_empty(),
            "seed boundary/profile/declared health differs or failed-host history is unavailable",
        )?;
        let retention = &input
            .compatibility()
            .capabilities()
            .unwrap()
            .entity_retention;
        for name in header.period_max.keys() {
            require(
                matches!(retention.class(name), RetentionClass::PeriodScoped { .. }),
                "snapshot period maximum belongs to non-period type",
            )?;
        }
        // Validate the complete ordered host inventory before creating output.
        let mut hosts = HostSet::default();
        for source in &header.sources.rows {
            require(
                source.manifest_idx == 2,
                "seed source is not the Pool template",
            )?;
            hosts.seed(
                crate::address(&source.param)?,
                source.creation_block as u64,
                header.boundary.block_number,
            )?;
        }
        require(
            pins.engine_lineage == snapshot::initial_lineage(pins.snapshot_sha256),
            "seed engine lineage differs from pinned snapshot",
        )?;
        fs::create_dir(root).map_err(error)?;
        fs::create_dir(root.join("checkpoints")).map_err(error)?;
        fs::create_dir(root.join("undo")).map_err(error)?;
        let db = Database::builder()
            .set_cache_size(cache_bytes)
            .create_file(create(&root.join("state.redb"))?)
            .map_err(error)?;
        let mut tx = db.begin_write().map_err(error)?;
        tx.set_durability(Durability::Immediate).map_err(error)?;
        for table in [ENTITIES, SOURCES, FAILED, UNDO] {
            tx.open_table(table).map_err(error)?;
        }
        let mut counts = BTreeMap::<String, u64>::new();
        while let Some(record) = reader.next_record().map_err(error)? {
            let wire_key = snapshot::decode_key(&expected, &record.key).map_err(error)?;
            require(
                wire_key.storage_causality_region == 0,
                "seed causality region is not zero",
            )?;
            let Some(entity_id::Value::String(id)) =
                wire_key.id.as_ref().and_then(|id| id.value.as_ref())
            else {
                return Err(refuse("seed ID is not a string"));
            };
            let key = Key::new(&wire_key.entity_type, id);
            match retention.class(&key.entity_type) {
                RetentionClass::Persistent => (),
                RetentionClass::BlockLocal { .. } => {
                    return Err(refuse("block-local seed contains retained rows"))
                }
                RetentionClass::PeriodScoped { period_id } => require(
                    header.period_max.get(&key.entity_type)
                        == Some(&period_id.parse(id).map_err(error)?),
                    "seed row differs from retained period maximum",
                )?,
            }
            let value = snapshot::StoredEntity::decode(&wire_key, &record.value).map_err(error)?;
            // Preserve the exact get-visible image, including explicit Null.
            // VID and physical range metadata stay in the pinned snapshot.
            let encoded = fields_bytes(&key, &value.fields)?;
            let encoded_key = key_bytes(&key)?;
            require(
                tx.open_table(ENTITIES)
                    .map_err(error)?
                    .insert(encoded_key.as_slice(), encoded.as_slice())
                    .map_err(error)?
                    .is_none(),
                "duplicate logical seed key",
            )?;
            let count = counts.entry(key.entity_type).or_default();
            *count = count
                .checked_add(1)
                .ok_or_else(|| refuse("seed row count overflow"))?;
        }
        let verified = reader.finish().map_err(error)?;
        require(
            verified.file_sha256() == pins.snapshot_sha256
                && verified.lineage() == pins.engine_lineage,
            "seed full-file digest/lineage differs",
        )?;
        for (ordinal, source) in header.sources.rows.iter().enumerate() {
            let value = canonical(&Source {
                creation_block: source.creation_block as u64,
                failed_at_hash: None,
                ordinal: ordinal as u64,
            })?;
            require(
                tx.open_table(SOURCES)
                    .map_err(error)?
                    .insert(source.param.as_slice(), value.as_slice())
                    .map_err(error)?
                    .is_none(),
                "duplicate logical seed source",
            )?;
        }
        let logical_state_sha256 = logical_state_digest(&tx)?;
        let origin = Origin::Snapshot {
            purpose: pins.purpose.clone(),
            snapshot_sha256: hex::encode(pins.snapshot_sha256),
            seed_manifest_sha256: hex::encode(pins.seed_manifest_sha256),
            boundary: header.boundary.clone(),
        };
        let manifest = Manifest {
            format: checkpoint::FORMAT.into(),
            boundary: header.boundary.clone(),
            reducer_lineage: checkpoint::initial_lineage(&binding, &origin).map_err(error)?,
            binding: binding.clone(),
            origin,
            engine_lineage_before: hex::encode(verified.lineage()),
            transition: None,
            sources: Sources {
                count: header.sources.count,
                order_sha256: header.sources.order_sha256.clone(),
            },
            failed_hosts: FailedHosts::empty(),
            retained_by_type: counts.clone(),
            full_state_sha256: Some(logical_state_sha256.clone()),
        };
        let evidence = canonical(&ImportEvidence {
            format: if capture_binding.is_some() {
                "pinax.aerodrome.verified-seed-import/v1"
            } else {
                "pinax.aerodrome.development-seed-import/v1"
            }
            .into(),
            production_selectable: false,
            capture_manifest_verified: capture_binding.is_some(),
            capture_binding,
            pins,
            header,
            snapshot_bytes: verified.bytes(),
            retained_by_type: counts,
            logical_state_sha256,
        })?;
        require(
            evidence.len() <= MAX_RECORD,
            "seed import evidence exceeds state ceiling",
        )?;
        let bytes = manifest.encode().map_err(error)?;
        immutable_bytes(&root.join("seed-manifest.bin"), seed_manifest)?;
        immutable_bytes(&root.join("seed-import.json"), &evidence)?;
        immutable_bytes(
            &root
                .join("checkpoints")
                .join(format!("{}.json", hex::encode(Sha256::digest(&bytes)))),
            &bytes,
        )?;
        tx.open_table(META)
            .map_err(error)?
            .insert("seed-import", evidence.as_slice())
            .map_err(error)?;
        tx.open_table(META)
            .map_err(error)?
            .insert("manifest", bytes.as_slice())
            .map_err(error)?;
        sync_dir(&root.join("checkpoints"))?;
        sync_dir(root)?;
        tx.commit().map_err(|e| {
            refuse(format!(
                "seed commit outcome unknown; reopen and inspect: {e}"
            ))
        })?;
        Ok(Self {
            database: db,
            root: root.into(),
            binding,
        })
    }
}

pub(super) fn verify_retained_evidence(
    tx: &redb::ReadTransaction,
    root: &Path,
    manifest: &Manifest,
) -> Result<()> {
    let Origin::Snapshot {
        purpose,
        snapshot_sha256,
        seed_manifest_sha256,
        boundary,
    } = &manifest.origin
    else {
        return Ok(());
    };
    let bytes = tx
        .open_table(META)
        .map_err(error)?
        .get("seed-import")
        .map_err(error)?
        .ok_or_else(|| refuse("seed import evidence missing"))?
        .value()
        .to_vec();
    let evidence: ImportEvidence = decode(&bytes)?;
    let capture_bytes = fs::read(root.join("seed-manifest.bin")).map_err(error)?;
    match &evidence.capture_binding {
        Some(binding) => {
            require(
                evidence.format == "pinax.aerodrome.verified-seed-import/v1"
                    && evidence.capture_manifest_verified,
                "verified seed evidence kind differs",
            )?;
            let captured = capture::Manifest::verify(&capture_bytes, seed_manifest_sha256, binding)
                .map_err(error)?;
            captured.validate_header(&evidence.header).map_err(error)?;
            require(
                matches!(
                    captured.history,
                    capture::History::UnprunedFromDeploymentStart { .. }
                ) && captured.snapshot.sha256 == *snapshot_sha256
                    && captured.snapshot.bytes == evidence.snapshot_bytes
                    && captured.lineage == hex::encode(evidence.pins.engine_lineage)
                    && captured.binding.boundary == *boundary,
                "retained verified capture differs from imported origin",
            )?;
        }
        None => require(
            evidence.format == "pinax.aerodrome.development-seed-import/v1"
                && !evidence.capture_manifest_verified,
            "development seed evidence kind differs",
        )?,
    }
    require(
        !evidence.production_selectable
            && &evidence.pins.purpose == purpose
            && hex::encode(evidence.pins.snapshot_sha256) == *snapshot_sha256
            && hex::encode(evidence.pins.seed_manifest_sha256) == *seed_manifest_sha256
            && &evidence.pins.boundary == boundary
            && fs::read(root.join("seed-import.json")).map_err(error)? == bytes
            && hex::encode(Sha256::digest(&capture_bytes)) == *seed_manifest_sha256,
        "retained seed evidence differs from immutable origin",
    )
}
