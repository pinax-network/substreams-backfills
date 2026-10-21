//! Deterministic, bounded `BCGSNAP1` entity snapshots shared with the engine.
//!
//! Wire format: `BCGSNAP1`, a u32-BE length and canonical named MessagePack
//! header, then `header.records` records (each a u32-BE length and canonical
//! MessagePack map `{key: bin, value: bin}`). Keys and values use the exact
//! binary layout documented by [`encode_key`] and [`StoredEntity::encode`].
//! The trailer is `BCGSEND1`, u64-BE record count, and SHA-256 of **all** bytes
//! preceding the digest, including the trailer magic and count. EOF is required.
//!
//! Records returned by [`SnapshotReader::next_record`] are provisional. Only
//! [`SnapshotReader::finish`] returns a verified full-file identity, after the
//! trailer and EOF checks; consumers must stage changes until that succeeds.
//! Memory is bounded by the encoded header, one encoded/decoded record and the
//! previous key, independent of the snapshot's total entity count. The complete
//! source list is in the header: its default limit is 64 MiB **encoded bytes**,
//! not an arbitrary source-row count. Oversized headers are refused, never
//! truncated. A future separately versioned format may stream sources too.
//!
//! This codec proves canonical content, self-consistent metadata and the exact
//! caller-supplied binding. A loader must additionally check the pinned physical
//! profile, descriptor template membership, retention classes and source-capture
//! evidence before applying a loadable snapshot. `SeedOrigin` records provenance;
//! a checksum does not authenticate the database or the capture process.

use crate::{
    block_changes::validate_materialized_entity,
    dynamic_sources::DataSource,
    dynamic_sources_v2::{Creation, SourceOrder},
    pb::pinax::graph::backfill::v1::{entity_id, EntityFields, EntityId, EntityKey},
};
use prost::Message;
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{self, Read, Write},
};

pub const MAGIC: &[u8; 8] = b"BCGSNAP1";
pub const TRAILER_MAGIC: &[u8; 8] = b"BCGSEND1";
pub const FORMAT: &str = "pinax.graph-node.generic-state-snapshot";
pub const VERSION: u32 = 1;
const LINEAGE_DOMAIN: &[u8] = b"pinax.generic-state-lineage/v1\0";

#[derive(Clone, Copy, Debug)]
pub struct Limits {
    pub header_bytes: u32,
    pub record_bytes: u32,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            header_bytes: 64 * 1024 * 1024,
            // Same ceiling as the engine's MAX_PROTOBUF_FRAME_LEN.
            record_bytes: 256 * 1024 * 1024,
        }
    }
}

impl Limits {
    fn validate(self) -> Result<(), String> {
        let defaults = Self::default();
        require(
            self.header_bytes > 0
                && self.header_bytes <= defaults.header_bytes
                && self.record_bytes > 0
                && self.record_bytes <= defaults.record_bytes,
            "snapshot limits must be positive and may only lower the format ceilings",
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum EntityIdPolicy {
    StringOnly,
    AllKinds,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotBinding {
    pub deployment: String,
    pub network: String,
    pub descriptor_sha256: String,
    pub retention_sha256: String,
    /// Strictly sorted, unique GraphQL names; index is the u16 store ordinal.
    pub type_ordinals: Vec<String>,
    pub entity_id_policy: EntityIdPolicy,
}

impl SnapshotBinding {
    pub fn validate(&self) -> Result<(), String> {
        require(
            !self.deployment.is_empty() && !self.network.is_empty(),
            "empty snapshot deployment/network",
        )?;
        require(
            digest(&self.descriptor_sha256) && digest(&self.retention_sha256),
            "invalid snapshot binding digest",
        )?;
        require(
            !self.type_ordinals.is_empty() && self.type_ordinals.len() <= u16::MAX as usize + 1,
            "snapshot type ordinals must contain 1..=65536 types",
        )?;
        require(
            self.type_ordinals.iter().all(|s| graphql_name(s))
                && self.type_ordinals.windows(2).all(|w| w[0] < w[1]),
            "snapshot type ordinals are not sorted unique GraphQL names",
        )
    }

    pub fn sha256(&self) -> Result<[u8; 32], String> {
        self.validate()?;
        Ok(Sha256::digest(canonical(self, Limits::default().header_bytes)?).into())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Boundary {
    pub block_number: u64,
    pub block_hash: [u8; 32],
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SnapshotOrigin {
    EmptyRoot {
        start_block: u64,
    },
    Landing {
        seed: SeedOrigin,
    },
    Oracle {
        seed: SeedOrigin,
    },
    Compaction {
        base_lineage: [u8; 32],
        through_lineage: [u8; 32],
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedOrigin {
    pub schema: String,
    pub site_id: i32,
    pub database: String,
    pub system_identifier: String,
    pub server_version_num: u32,
    pub capture_tool_sha256: String,
    pub profile_sha256: String,
    pub head: Boundary,
    pub health: String,
    pub non_fatal_errors: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VidState {
    /// Sorted by entity_type, including physical metadata for omitted tables.
    pub tables: Vec<TableVid>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableVid {
    pub entity_type: String,
    pub postgres_table: String,
    pub max_vid: i64,
    pub sequence_last_value: i64,
    pub sequence_is_called: bool,
    pub active_rows: Option<u64>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenericPoiState {
    pub region_digest: Option<Vec<u8>>,
    pub active: Option<PoiVersion>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PoiVersion {
    pub vid: i64,
    pub block_range_start: i32,
    pub id: String,
    pub digest: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotSource {
    pub vid: i32,
    pub creation_block: i32,
    pub manifest_idx: i32,
    pub param: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceSnapshot {
    pub count: u64,
    pub order_sha256: String,
    pub max_vid: i32,
    /// Complete, sorted by (creation_block, vid); never silently truncated.
    pub rows: Vec<SnapshotSource>,
}

impl SourceSnapshot {
    /// Reuses the v2 chained hash domain
    /// `pinax.graph.backfill.data-sources/v2/creation-order\0` exactly.
    pub fn from_rows(rows: Vec<SnapshotSource>) -> Result<Self, String> {
        let (order, max_vid) = source_order(&rows)?;
        Ok(Self {
            count: order.count,
            order_sha256: order.sha256,
            max_vid,
            rows,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotHeader {
    pub format: String,
    pub version: u32,
    pub binding: SnapshotBinding,
    pub boundary: Boundary,
    pub origin: SnapshotOrigin,
    pub vid: Option<VidState>,
    pub poi: GenericPoiState,
    pub sources: SourceSnapshot,
    pub period_max: BTreeMap<String, u64>,
    pub entity_count: Option<i64>,
    pub records: u64,
}

impl SnapshotHeader {
    pub fn validate(&self) -> Result<(), String> {
        require(
            self.format == FORMAT && self.version == VERSION,
            "unsupported snapshot format/version",
        )?;
        self.binding.validate()?;
        require(
            self.boundary.block_number <= i32::MAX as u64,
            "snapshot boundary exceeds Graph Node block domain",
        )?;
        require(
            self.entity_count.is_none_or(|n| n >= 0),
            "negative snapshot entity count",
        )?;
        require(
            self.period_max
                .keys()
                .all(|k| self.binding.type_ordinals.binary_search(k).is_ok()),
            "unknown period-max entity type",
        )?;
        let (order, max_vid) = source_order(&self.sources.rows)?;
        require(
            self.sources.count == order.count
                && self.sources.order_sha256 == order.sha256
                && self.sources.max_vid == max_vid,
            "snapshot source commitment mismatch",
        )?;
        require(
            self.sources
                .rows
                .iter()
                .all(|s| s.creation_block as u64 <= self.boundary.block_number),
            "source creation after snapshot boundary",
        )?;
        match &self.origin {
            SnapshotOrigin::EmptyRoot { start_block } => {
                require(
                    *start_block <= i32::MAX as u64
                        && self.boundary.block_number == start_block.saturating_sub(1)
                        && self.boundary.block_hash == [0; 32],
                    "invalid empty-root boundary",
                )?;
                require(
                    self.records == 0
                        && self.sources.count == 0
                        && self.poi == GenericPoiState::default()
                        && self.period_max.is_empty()
                        && self.entity_count.is_none_or(|n| n == 0),
                    "empty root contains state",
                )?;
            }
            SnapshotOrigin::Landing { seed } | SnapshotOrigin::Oracle { seed } => {
                require(self.boundary.block_hash != [0; 32], "zero seed block hash")?;
                require(
                    !seed.schema.is_empty()
                        && seed.site_id >= 0
                        && !seed.database.is_empty()
                        && !seed.system_identifier.is_empty()
                        && seed.server_version_num > 0
                        && digest(&seed.capture_tool_sha256)
                        && digest(&seed.profile_sha256)
                        && !seed.health.is_empty()
                        && seed.head.block_number <= i32::MAX as u64
                        && seed.head.block_hash != [0; 32],
                    "invalid snapshot seed provenance",
                )?;
                if matches!(self.origin, SnapshotOrigin::Landing { .. }) {
                    require(
                        seed.head == self.boundary,
                        "landing seed head differs from boundary",
                    )?;
                } else {
                    require(
                        seed.head.block_number >= self.boundary.block_number,
                        "oracle boundary follows source head",
                    )?;
                }
            }
            SnapshotOrigin::Compaction {
                base_lineage,
                through_lineage,
            } => {
                require(
                    self.boundary.block_hash != [0; 32]
                        && *base_lineage != [0; 32]
                        && *through_lineage != [0; 32],
                    "invalid compaction boundary/lineage",
                )?;
            }
        }
        require(
            self.vid.is_none() == matches!(self.origin, SnapshotOrigin::Oracle { .. }),
            "oracle must omit VID state; other snapshots require it",
        )?;
        if let Some(vid) = &self.vid {
            require(
                vid.tables
                    .windows(2)
                    .all(|w| w[0].entity_type < w[1].entity_type),
                "VID tables are not sorted unique",
            )?;
            let mut tables = BTreeSet::new();
            for t in &vid.tables {
                require(
                    !t.entity_type.is_empty()
                        && !t.postgres_table.is_empty()
                        && tables.insert(&t.postgres_table)
                        && t.max_vid >= -1
                        && t.sequence_last_value >= 0,
                    "invalid table VID state",
                )?;
                if matches!(self.origin, SnapshotOrigin::EmptyRoot { .. }) {
                    require(
                        t.max_vid == -1 && t.active_rows.is_none_or(|n| n == 0),
                        "empty root has allocated entity VIDs",
                    )?;
                }
            }
            require(
                self.binding.type_ordinals.iter().all(|name| {
                    vid.tables
                        .binary_search_by(|t| t.entity_type.cmp(name))
                        .is_ok()
                }),
                "VID state is missing an entity table",
            )?;
        }
        match (&self.poi.region_digest, &self.poi.active) {
            (None, None) => (),
            (Some(d), Some(a)) => require(
                !d.is_empty()
                    && d == &a.digest
                    && a.id == format!("ethereum/{}", self.binding.network)
                    && a.vid >= 0
                    && a.block_range_start >= 0
                    && a.block_range_start as u64 <= self.boundary.block_number,
                "inconsistent snapshot PoI state",
            )?,
            _ => return Err("inconsistent snapshot PoI state".into()),
        }
        Ok(())
    }

    pub fn require_binding(&self, expected: &SnapshotBinding) -> Result<(), String> {
        expected.validate()?;
        require(&self.binding == expected, "snapshot binding mismatch")
    }

    pub fn require_loadable(&self) -> Result<(), String> {
        require(
            !matches!(self.origin, SnapshotOrigin::Oracle { .. }),
            "oracle snapshot is never loadable",
        )
    }

    pub fn next_block(&self) -> u64 {
        match self.origin {
            SnapshotOrigin::EmptyRoot { start_block } => start_block,
            _ => self.boundary.block_number + 1,
        }
    }
}

fn source_order(rows: &[SnapshotSource]) -> Result<(SourceOrder, i32), String> {
    require(
        rows.windows(2)
            .all(|w| (w[0].creation_block, w[0].vid) < (w[1].creation_block, w[1].vid)),
        "snapshot sources are not in creation order",
    )?;
    let mut ids = BTreeSet::new();
    let mut vids = BTreeSet::new();
    let mut order = SourceOrder::empty();
    let mut max_vid = -1;
    for row in rows {
        require(
            row.vid >= 0 && vids.insert(row.vid) && ids.insert((row.manifest_idx, &row.param)),
            "duplicate source identity/VID or negative VID",
        )?;
        order.append(&Creation {
            ordinal: order.count,
            source: DataSource {
                creation_block: row.creation_block,
                manifest_idx: row.manifest_idx,
                causality_region: 0,
                param: hex::encode(&row.param),
                context: None,
                done_at: None,
            },
        })?;
        max_vid = max_vid.max(row.vid);
    }
    Ok((order, max_vid))
}

/// StoreKey = u16-BE type ordinal, sign-flipped i32-BE causality region,
/// id-kind byte (0 string, 1 bytes, 2 int8), then ID bytes (sign-flipped
/// i64-BE for int8). This is also the snapshot's strict bytewise sort order.
pub fn encode_key(binding: &SnapshotBinding, key: &EntityKey) -> Result<Vec<u8>, String> {
    let ordinal = binding
        .type_ordinals
        .binary_search(&key.entity_type)
        .map_err(|_| "unknown store key entity type")?;
    let ordinal = u16::try_from(ordinal).map_err(|_| "store key ordinal overflow")?;
    require(
        key.storage_causality_region >= 0,
        "negative store key causality region",
    )?;
    let id = key
        .id
        .as_ref()
        .and_then(|id| id.value.as_ref())
        .ok_or("missing store key ID")?;
    let mut bytes = ordinal.to_be_bytes().to_vec();
    bytes.extend_from_slice(&(key.storage_causality_region as u32 ^ 0x8000_0000).to_be_bytes());
    match id {
        entity_id::Value::String(id) => {
            bytes.push(0);
            bytes.extend_from_slice(id.as_bytes());
        }
        entity_id::Value::Bytes(id) => {
            require(
                binding.entity_id_policy == EntityIdPolicy::AllKinds,
                "non-string store key refused",
            )?;
            bytes.push(1);
            bytes.extend_from_slice(id);
        }
        entity_id::Value::Int8(id) => {
            require(
                binding.entity_id_policy == EntityIdPolicy::AllKinds,
                "non-string store key refused",
            )?;
            bytes.push(2);
            bytes.extend_from_slice(&(*id as u64 ^ 0x8000_0000_0000_0000).to_be_bytes());
        }
    }
    Ok(bytes)
}

pub fn decode_key(binding: &SnapshotBinding, bytes: &[u8]) -> Result<EntityKey, String> {
    require(bytes.len() >= 7, "truncated store key")?;
    let ordinal = u16::from_be_bytes(bytes[..2].try_into().unwrap()) as usize;
    let entity_type = binding
        .type_ordinals
        .get(ordinal)
        .ok_or("unknown store key ordinal")?
        .clone();
    let storage_causality_region =
        (u32::from_be_bytes(bytes[2..6].try_into().unwrap()) ^ 0x8000_0000) as i32;
    let id = match bytes[6] {
        0 => entity_id::Value::String(
            std::str::from_utf8(&bytes[7..])
                .map_err(|_| "invalid store key UTF-8")?
                .into(),
        ),
        1 => entity_id::Value::Bytes(bytes[7..].to_vec()),
        2 if bytes.len() == 15 => entity_id::Value::Int8(
            (u64::from_be_bytes(bytes[7..].try_into().unwrap()) ^ 0x8000_0000_0000_0000) as i64,
        ),
        _ => return Err("invalid store key ID kind/length".into()),
    };
    let key = EntityKey {
        entity_type,
        id: Some(EntityId { value: Some(id) }),
        storage_causality_region,
    };
    require(
        encode_key(binding, &key)? == bytes,
        "noncanonical store key",
    )?;
    Ok(key)
}

#[derive(Clone, Debug, PartialEq)]
pub struct StoredEntity {
    pub vid: i64,
    pub block_range_start: i32,
    pub fields: Vec<crate::pb::pinax::graph::backfill::v1::EntityField>,
}

impl StoredEntity {
    /// Value = version byte 1, i64-BE VID, i32-BE range start, and exact
    /// canonical prost EntityFields. No normalization or lossy conversion.
    pub fn encode(&self, key: &EntityKey) -> Result<Vec<u8>, String> {
        require(
            self.vid >= 0 && self.block_range_start >= 0,
            "negative entity VID/range start",
        )?;
        validate_materialized_entity(0, key, &self.fields).map_err(|e| e.to_string())?;
        let mut bytes = vec![1];
        bytes.extend_from_slice(&self.vid.to_be_bytes());
        bytes.extend_from_slice(&self.block_range_start.to_be_bytes());
        EntityFields {
            fields: self.fields.clone(),
        }
        .encode(&mut bytes)
        .map_err(|e| e.to_string())?;
        Ok(bytes)
    }

    pub fn decode(key: &EntityKey, bytes: &[u8]) -> Result<Self, String> {
        require(
            bytes.len() >= 13 && bytes[0] == 1,
            "invalid stored entity envelope",
        )?;
        let image = EntityFields::decode(&bytes[13..]).map_err(|e| e.to_string())?;
        require(
            image.encode_to_vec() == bytes[13..],
            "noncanonical stored EntityFields protobuf",
        )?;
        let entity = Self {
            vid: i64::from_be_bytes(bytes[1..9].try_into().unwrap()),
            block_range_start: i32::from_be_bytes(bytes[9..13].try_into().unwrap()),
            fields: image.fields,
        };
        require(
            entity.vid >= 0 && entity.block_range_start >= 0,
            "negative entity VID/range start",
        )?;
        validate_materialized_entity(0, key, &entity.fields).map_err(|e| e.to_string())?;
        Ok(entity)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotRecord {
    #[serde(with = "binary")]
    pub key: Vec<u8>,
    #[serde(with = "binary")]
    pub value: Vec<u8>,
}

impl SnapshotRecord {
    pub fn from_entity(
        binding: &SnapshotBinding,
        key: &EntityKey,
        entity: &StoredEntity,
    ) -> Result<Self, String> {
        Ok(Self {
            key: encode_key(binding, key)?,
            value: entity.encode(key)?,
        })
    }

    fn validate(&self, header: &SnapshotHeader) -> Result<(), String> {
        let key = decode_key(&header.binding, &self.key)?;
        let entity = StoredEntity::decode(&key, &self.value)?;
        require(
            entity.block_range_start as u64 <= header.boundary.block_number,
            "entity version starts after snapshot boundary",
        )?;
        if let Some(vid) = &header.vid {
            let table = vid
                .tables
                .binary_search_by(|t| t.entity_type.cmp(&key.entity_type))
                .map_err(|_| "entity VID table missing")?;
            require(
                entity.vid <= vid.tables[table].max_vid,
                "entity VID exceeds table maximum",
            )?;
        }
        Ok(())
    }
}

/// The purpose must be explicit; comparison consumers may read oracle seeds,
/// whereas a loader must select Loadable and refuse them before any records.
#[derive(Clone, Copy, Debug)]
pub enum ReadPurpose {
    Loadable,
    OracleComparison,
}

/// Created only after checksum/EOF validation (reader) or successful flush
/// (writer). It includes the checksum trailer in the full-file SHA-256.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedSnapshot {
    file_sha256: [u8; 32],
    bytes: u64,
    records: u64,
    lineage: [u8; 32],
}

impl VerifiedSnapshot {
    pub fn file_sha256(&self) -> [u8; 32] {
        self.file_sha256
    }
    pub fn bytes(&self) -> u64 {
        self.bytes
    }
    pub fn records(&self) -> u64 {
        self.records
    }
    pub fn lineage(&self) -> [u8; 32] {
        self.lineage
    }
}

/// L0 for root/landing/oracle snapshots. Compaction snapshots use the existing
/// through_lineage instead; see VerifiedSnapshot::lineage.
pub fn initial_lineage(snapshot_sha256: [u8; 32]) -> [u8; 32] {
    advance_lineage([0; 32], snapshot_sha256)
}

pub fn advance_lineage(previous: [u8; 32], delta_sha256: [u8; 32]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(LINEAGE_DOMAIN);
    h.update(previous);
    h.update(delta_sha256);
    h.finalize().into()
}

fn verified(header: &SnapshotHeader, hash: Sha256, bytes: u64) -> VerifiedSnapshot {
    let file_sha256 = hash.finalize().into();
    let lineage = match header.origin {
        SnapshotOrigin::Compaction {
            through_lineage, ..
        } => through_lineage,
        _ => initial_lineage(file_sha256),
    };
    VerifiedSnapshot {
        file_sha256,
        bytes,
        records: header.records,
        lineage,
    }
}

pub struct SnapshotWriter<W> {
    output: W,
    header: SnapshotHeader,
    limits: Limits,
    hash: Sha256,
    bytes: u64,
    written: u64,
    previous_key: Option<Vec<u8>>,
    failed: bool,
}

impl<W: Write> SnapshotWriter<W> {
    pub fn new(output: W, header: SnapshotHeader, limits: Limits) -> Result<Self, String> {
        limits.validate()?;
        header.validate()?;
        let encoded = canonical(&header, limits.header_bytes)?;
        let mut writer = Self {
            output,
            header,
            limits,
            hash: Sha256::new(),
            bytes: 0,
            written: 0,
            previous_key: None,
            failed: false,
        };
        writer.put(MAGIC)?;
        writer.put(&(encoded.len() as u32).to_be_bytes())?;
        writer.put(&encoded)?;
        Ok(writer)
    }

    pub fn write_record(&mut self, record: &SnapshotRecord) -> Result<(), String> {
        require(!self.failed, "snapshot writer is poisoned")?;
        let result = self.write_record_inner(record);
        if result.is_err() {
            self.failed = true;
        }
        result
    }

    fn write_record_inner(&mut self, record: &SnapshotRecord) -> Result<(), String> {
        require(
            self.written < self.header.records,
            "too many snapshot records",
        )?;
        require(
            self.previous_key.as_ref().is_none_or(|k| k < &record.key),
            "snapshot keys are not strictly sorted",
        )?;
        require(
            record.key.len().saturating_add(record.value.len())
                <= self.limits.record_bytes as usize,
            "snapshot record exceeds configured bound",
        )?;
        record.validate(&self.header)?;
        let bytes = canonical(record, self.limits.record_bytes)?;
        self.put(&(bytes.len() as u32).to_be_bytes())?;
        self.put(&bytes)?;
        self.previous_key = Some(record.key.clone());
        self.written += 1;
        Ok(())
    }

    pub fn finish(mut self) -> Result<(W, VerifiedSnapshot), String> {
        require(
            !self.failed && self.written == self.header.records,
            "snapshot writer failed or record count incomplete",
        )?;
        self.put(TRAILER_MAGIC)?;
        self.put(&self.written.to_be_bytes())?;
        let checksum: [u8; 32] = self.hash.clone().finalize().into();
        self.put(&checksum)?;
        self.output.flush().map_err(|e| e.to_string())?;
        Ok((self.output, verified(&self.header, self.hash, self.bytes)))
    }

    fn put(&mut self, bytes: &[u8]) -> Result<(), String> {
        self.output.write_all(bytes).map_err(|e| e.to_string())?;
        self.hash.update(bytes);
        self.bytes += bytes.len() as u64;
        Ok(())
    }
}

pub struct SnapshotReader<R> {
    input: R,
    header: SnapshotHeader,
    limits: Limits,
    hash: Sha256,
    bytes: u64,
    read: u64,
    previous_key: Option<Vec<u8>>,
    failed: bool,
}

impl<R: Read> SnapshotReader<R> {
    pub fn new(
        mut input: R,
        expected: &SnapshotBinding,
        purpose: ReadPurpose,
        limits: Limits,
    ) -> Result<Self, String> {
        limits.validate()?;
        let mut hash = Sha256::new();
        let mut bytes = 0;
        let magic = take::<8>(&mut input, &mut hash, &mut bytes)?;
        require(&magic == MAGIC, "unsupported snapshot magic")?;
        let encoded = read_frame(&mut input, &mut hash, &mut bytes, limits.header_bytes)?;
        let header: SnapshotHeader = decode_canonical(&encoded, limits.header_bytes)?;
        header.validate()?;
        header.require_binding(expected)?;
        if matches!(purpose, ReadPurpose::Loadable) {
            header.require_loadable()?;
        }
        Ok(Self {
            input,
            header,
            limits,
            hash,
            bytes,
            read: 0,
            previous_key: None,
            failed: false,
        })
    }

    pub fn header(&self) -> &SnapshotHeader {
        &self.header
    }

    /// `None` means only that the declared body count was reached. It does
    /// not certify the snapshot; the caller must still call finish().
    pub fn next_record(&mut self) -> Result<Option<SnapshotRecord>, String> {
        require(!self.failed, "snapshot reader is poisoned")?;
        let result = self.next_inner();
        if result.is_err() {
            self.failed = true;
        }
        result
    }

    fn next_inner(&mut self) -> Result<Option<SnapshotRecord>, String> {
        if self.read == self.header.records {
            return Ok(None);
        }
        let encoded = read_frame(
            &mut self.input,
            &mut self.hash,
            &mut self.bytes,
            self.limits.record_bytes,
        )?;
        let record: SnapshotRecord = decode_canonical(&encoded, self.limits.record_bytes)?;
        require(
            self.previous_key.as_ref().is_none_or(|k| k < &record.key),
            "snapshot keys are not strictly sorted",
        )?;
        record.validate(&self.header)?;
        self.previous_key = Some(record.key.clone());
        self.read += 1;
        Ok(Some(record))
    }

    pub fn finish(mut self) -> Result<VerifiedSnapshot, String> {
        require(
            !self.failed && self.read == self.header.records,
            "snapshot reader failed or records remain unread",
        )?;
        require(
            &take::<8>(&mut self.input, &mut self.hash, &mut self.bytes)? == TRAILER_MAGIC,
            "invalid snapshot trailer",
        )?;
        let count =
            u64::from_be_bytes(take::<8>(&mut self.input, &mut self.hash, &mut self.bytes)?);
        require(count == self.read, "snapshot trailer record count mismatch")?;
        let expected: [u8; 32] = self.hash.clone().finalize().into();
        let checksum = take::<32>(&mut self.input, &mut self.hash, &mut self.bytes)?;
        require(checksum == expected, "snapshot checksum mismatch")?;
        let mut extra = [0];
        loop {
            match self.input.read(&mut extra) {
                Ok(0) => break,
                Ok(_) => return Err("snapshot has trailing bytes".into()),
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e.to_string()),
            }
        }
        Ok(verified(&self.header, self.hash, self.bytes))
    }
}

fn take<const N: usize>(
    input: &mut impl Read,
    hash: &mut Sha256,
    bytes: &mut u64,
) -> Result<[u8; N], String> {
    let mut value = [0; N];
    input.read_exact(&mut value).map_err(|e| e.to_string())?;
    hash.update(value);
    *bytes += N as u64;
    Ok(value)
}

fn read_frame(
    input: &mut impl Read,
    hash: &mut Sha256,
    bytes: &mut u64,
    max: u32,
) -> Result<Vec<u8>, String> {
    let len = u32::from_be_bytes(take::<4>(input, hash, bytes)?);
    require(
        len != 0 && len <= max,
        "snapshot encoded frame exceeds configured bound or is empty",
    )?;
    let mut value = vec![0; len as usize];
    input.read_exact(&mut value).map_err(|e| e.to_string())?;
    hash.update(&value);
    *bytes += len as u64;
    Ok(value)
}

struct BoundedBuffer {
    bytes: Vec<u8>,
    max: usize,
}
impl Write for BoundedBuffer {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.max.saturating_sub(self.bytes.len()) {
            return Err(io::Error::other(
                "snapshot encoded frame exceeds configured bound",
            ));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn canonical<T: Serialize>(value: &T, max: u32) -> Result<Vec<u8>, String> {
    let mut buffer = BoundedBuffer {
        bytes: Vec::new(),
        max: max as usize,
    };
    value
        .serialize(&mut rmp_serde::Serializer::new(&mut buffer).with_struct_map())
        .map_err(|e| e.to_string())?;
    Ok(buffer.bytes)
}

fn decode_canonical<T: DeserializeOwned + Serialize>(bytes: &[u8], max: u32) -> Result<T, String> {
    let value = rmp_serde::from_slice(bytes).map_err(|e| e.to_string())?;
    require(
        canonical(&value, max)? == bytes,
        "noncanonical snapshot MessagePack",
    )?;
    Ok(value)
}

fn digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn graphql_name(s: &str) -> bool {
    let mut bytes = s.bytes();
    bytes
        .next()
        .is_some_and(|b| b.is_ascii_alphabetic() || b == b'_')
        && bytes.all(|b| b.is_ascii_alphanumeric() || b == b'_')
}
fn require(ok: bool, error: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(error.into())
    }
}

mod binary {
    use serde::{Deserialize, Deserializer, Serializer};
    pub fn serialize<S: Serializer>(bytes: &[u8], s: S) -> Result<S::Ok, S::Error> {
        s.serialize_bytes(bytes)
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<u8>, D::Error> {
        Vec::<u8>::deserialize(d)
    }
}
