//! Immutable, fully verified seed rows on disk with a bounded replay overlay.
//!
//! The database is a private oracle cache, never an engine checkpoint. Its only
//! constructor streams and verifies the complete externally pinned seed. Partial
//! imports cannot produce a store. No historical entity is omitted, normalized,
//! or eagerly materialized. The overlay lives for the entire oracle run.

use std::{collections::BTreeMap, io::Read, path::Path, sync::RwLock};

use anyhow::{anyhow, bail, Context, Result};
use backfill_common::{
    seed_manifest::{Binding, SeedSnapshotReader, VerifiedSeed},
    state_snapshot::{
        self as snapshot, EntityIdPolicy, Limits, ReadPurpose, SnapshotHeader, StoredEntity,
    },
};
use graph::{
    components::store::write::EntityModification,
    data::store::Entity,
    schema::{EntityKey, InputSchema},
};
use redb::{Database, ReadableDatabase, ReadableTable, TableDefinition};

use crate::{blockchanges, store::StoreUndo};
#[cfg(test)]
mod tests;

const ROWS: TableDefinition<&[u8], &[u8]> = TableDefinition::new("oracle_seed_rows_v1");
const IMPORT_BATCH_BYTES: usize = 32 * 1024 * 1024;
const DATABASE_CACHE_BYTES: usize = 64 * 1024 * 1024;

/// Explicit ceilings for the complete window, not a cache eviction policy.
#[derive(Clone, Copy, Debug)]
pub struct OverlayLimits {
    pub keys: usize,
    pub encoded_bytes: usize,
}
impl Default for OverlayLimits {
    fn default() -> Self {
        Self {
            keys: 1_000_000,
            encoded_bytes: 512 * 1024 * 1024,
        }
    }
}

#[derive(Default)]
struct Overlay {
    rows: BTreeMap<EntityKey, Option<Entity>>,
    sizes: BTreeMap<EntityKey, usize>,
    bytes: usize,
    counts: BTreeMap<String, usize>,
}

pub struct DiskStore {
    db: Database,
    schema: InputSchema,
    seed: VerifiedSeed,
    header: SnapshotHeader,
    seed_fields: usize,
    overlay: RwLock<Overlay>,
    limits: OverlayLimits,
}

impl DiskStore {
    /// `path` must not exist. An interrupted/invalid import may leave a private
    /// database file, but there is deliberately no API that admits it by path.
    /// The caller publishes its enclosing staging directory only after success.
    #[allow(clippy::too_many_arguments)]
    pub fn import<R: Read>(
        path: &Path,
        input: R,
        manifest: &[u8],
        manifest_sha256: &str,
        expected: &Binding,
        schema: InputSchema,
        limits: OverlayLimits,
        snapshot_limits: Limits,
    ) -> Result<Self> {
        if limits.keys == 0 || limits.encoded_bytes == 0 {
            bail!("oracle overlay limits must be positive");
        }
        if path.try_exists()? {
            bail!("oracle seed database already exists");
        }
        if expected.snapshot.entity_id_policy != EntityIdPolicy::StringOnly {
            bail!("disk oracle requires StringOnly entity IDs");
        }
        let mut entity_types: Vec<String> = schema
            .entity_types()
            .iter()
            .map(|t| t.typename().to_string())
            .collect();
        entity_types.sort();
        if expected.snapshot.type_ordinals != entity_types
            || expected.snapshot.retention_sha256
                != hex::encode(backfill_common::descriptor::RetentionPolicy::default().sha256())
        {
            bail!("disk oracle requires every schema entity type with persistent retention");
        }
        // The canary requires a complete physical seed, including immutable rows.
        // In particular, a pruned/retention-reduced input cannot be used here.
        let mut reader = SeedSnapshotReader::new(
            input,
            manifest,
            manifest_sha256,
            expected,
            ReadPurpose::OracleComparison,
            snapshot_limits,
        )
        .map_err(anyhow::Error::msg)?;
        let header = reader.header().clone();
        let mut db_builder = Database::builder();
        db_builder.set_cache_size(DATABASE_CACHE_BYTES);
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)?;
        let db = db_builder
            .create_file(file)
            .context("creating private oracle seed database")?;
        let mut tx = db.begin_write()?;
        let mut batch_bytes = 0usize;
        let mut counts = BTreeMap::new();
        let mut seed_fields = 0usize;
        while let Some(record) = reader.next_record().map_err(anyhow::Error::msg)? {
            let key =
                snapshot::decode_key(&header.binding, &record.key).map_err(anyhow::Error::msg)?;
            if key.storage_causality_region != 0 {
                bail!("disk oracle requires on-chain region zero");
            }
            let value = StoredEntity::decode(&key, &record.value).map_err(anyhow::Error::msg)?;
            seed_fields = seed_fields
                .checked_add(value.fields.len())
                .ok_or_else(|| anyhow!("oracle field count overflow"))?;
            let native_key = blockchanges::key_from_wire(&schema, &key)?;
            let native = decode_entity(&schema, &value)?;
            // Conversion through the pinned Graph Node scalar types must be exact.
            if blockchanges::convert_entity(&native) != value.fields
                || blockchanges::convert_key(&native_key) != key
            {
                bail!("seed row changes under Graph Node conversion");
            }
            {
                let mut table = tx.open_table(ROWS)?;
                if table
                    .insert(record.key.as_slice(), record.value.as_slice())?
                    .is_some()
                {
                    bail!("duplicate oracle seed key");
                }
            }
            let count = counts.entry(key.entity_type).or_insert(0usize);
            *count = count
                .checked_add(1)
                .ok_or_else(|| anyhow!("oracle count overflow"))?;
            batch_bytes = batch_bytes
                .checked_add(record.key.len())
                .and_then(|n| n.checked_add(record.value.len()))
                .ok_or_else(|| anyhow!("oracle batch size overflow"))?;
            if batch_bytes >= IMPORT_BATCH_BYTES {
                tx.commit()?;
                tx = db.begin_write()?;
                batch_bytes = 0;
            }
        }
        // Even a zero-row seed has a table. No usable handle escapes until all
        // footer, EOF, digest, inventory and complete-history checks succeed.
        {
            tx.open_table(ROWS)?;
        }
        let seed = reader.finish().map_err(anyhow::Error::msg)?;
        seed.require_complete_source_history()
            .map_err(anyhow::Error::msg)?;
        tx.commit()?;
        Ok(Self {
            db,
            schema,
            seed,
            header,
            seed_fields,
            overlay: RwLock::new(Overlay {
                counts,
                ..Overlay::default()
            }),
            limits,
        })
    }

    pub fn seed(&self) -> &VerifiedSeed {
        &self.seed
    }
    pub fn header(&self) -> &SnapshotHeader {
        &self.header
    }
    pub fn seed_fields(&self) -> usize {
        self.seed_fields
    }
    pub fn schema(&self) -> &InputSchema {
        &self.schema
    }

    fn base_lookup(&self, key: &EntityKey) -> Result<Option<Entity>> {
        let wire = blockchanges::convert_key(key);
        if wire.storage_causality_region != 0 {
            bail!("disk oracle requires on-chain region zero");
        }
        // Poi$ is kept in the bounded overlay because BCGSNAP carries it in its
        // header, separately from the entity ordinal table.
        if key.entity_type == self.schema.poi_type() {
            return Ok(None);
        }
        let encoded =
            snapshot::encode_key(&self.header.binding, &wire).map_err(anyhow::Error::msg)?;
        let tx = self.db.begin_read()?;
        let table = tx.open_table(ROWS)?;
        let row = table.get(encoded.as_slice())?;
        row.map(|row| {
            StoredEntity::decode(&wire, row.value())
                .map_err(anyhow::Error::msg)
                .and_then(|v| decode_entity(&self.schema, &v))
        })
        .transpose()
    }

    pub fn lookup(&self, key: &EntityKey) -> Result<Option<Entity>> {
        let overlay = self
            .overlay
            .read()
            .map_err(|_| anyhow!("oracle overlay lock poisoned"))?;
        if let Some(row) = overlay.rows.get(key) {
            return Ok(row.clone());
        }
        self.base_lookup(key)
    }

    /// Preflight every row/read and budget before mutating the overlay or undo.
    /// Thus disk failures and logical budget refusals leave the block retryable.
    pub(crate) fn apply_recording(
        &self,
        mods: &[EntityModification],
        undo: &mut StoreUndo,
    ) -> Result<()> {
        let mut changes = BTreeMap::new();
        for modification in mods {
            match modification {
                EntityModification::Insert { key, data, .. }
                | EntityModification::Overwrite { key, data, .. } => {
                    changes.insert(key.clone(), Some(data.as_ref().clone()));
                }
                EntityModification::Remove { key, .. } => {
                    changes.insert(key.clone(), None);
                }
            }
        }
        self.apply_changes(changes, Some(undo))
    }

    fn apply_changes(
        &self,
        changes: BTreeMap<EntityKey, Option<Entity>>,
        mut undo: Option<&mut StoreUndo>,
    ) -> Result<()> {
        let mut overlay = self
            .overlay
            .write()
            .map_err(|_| anyhow!("oracle overlay lock poisoned"))?;
        let mut pending = Vec::with_capacity(changes.len());
        let mut bytes = overlay.bytes;
        let mut keys = overlay.rows.len();
        let mut counts = overlay.counts.clone();
        for (key, value) in changes {
            let before = match overlay.rows.get(&key) {
                Some(v) => v.clone(),
                None => self.base_lookup(&key)?,
            };
            // Reserve the largest value seen for this key, including its base
            // image: a later fatal rollback must never exceed the budget that
            // admitted the forward write. No eviction/reclamation changes LFU.
            let size = encoded_size(&key, value.as_ref())?
                .max(encoded_size(&key, before.as_ref())?)
                .max(*overlay.sizes.get(&key).unwrap_or(&0));
            if !overlay.rows.contains_key(&key) {
                keys = keys
                    .checked_add(1)
                    .ok_or_else(|| anyhow!("oracle key count overflow"))?;
            }
            bytes = bytes
                .checked_sub(*overlay.sizes.get(&key).unwrap_or(&0))
                .and_then(|n| n.checked_add(size))
                .ok_or_else(|| anyhow!("oracle overlay size overflow"))?;
            if keys > self.limits.keys || bytes > self.limits.encoded_bytes {
                bail!("oracle overlay limit exceeded; no eviction or partial success permitted");
            }
            let name = key.entity_type.typename().to_string();
            if before.is_none() && value.is_some() {
                let n = counts.entry(name).or_default();
                *n = n
                    .checked_add(1)
                    .ok_or_else(|| anyhow!("oracle row count overflow"))?;
            } else if before.is_some() && value.is_none() {
                let n = counts
                    .get_mut(&name)
                    .ok_or_else(|| anyhow!("oracle count missing"))?;
                *n = n
                    .checked_sub(1)
                    .ok_or_else(|| anyhow!("oracle count underflow"))?;
                if *n == 0 {
                    counts.remove(&name);
                }
            }
            pending.push((key, value, before, size));
        }
        for (key, value, before, size) in pending {
            if let Some(ref mut undo) = undo {
                undo.entry(key.clone()).or_insert(before);
            }
            overlay.sizes.insert(key.clone(), size);
            overlay.rows.insert(key, value);
        }
        overlay.bytes = bytes;
        overlay.counts = counts;
        Ok(())
    }

    pub(crate) fn rollback(&self, undo: StoreUndo) -> Result<()> {
        self.apply_changes(undo, None)
    }
    pub(crate) fn insert_poi(&self, key: EntityKey, value: Entity) -> Result<()> {
        self.apply_changes(BTreeMap::from([(key, Some(value))]), None)
    }
    pub fn counts_by_type(&self) -> BTreeMap<String, usize> {
        self.overlay
            .read()
            .expect("oracle overlay lock poisoned")
            .counts
            .clone()
    }
    pub fn len(&self) -> usize {
        self.counts_by_type().values().sum()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// A bounded cursor over the immutable seed; never the replay overlay.
    pub fn visit_seed(
        &self,
        mut visit: impl FnMut(
            &backfill_common::pb::pinax::graph::backfill::v1::EntityKey,
            &StoredEntity,
        ) -> Result<()>,
    ) -> Result<()> {
        let tx = self.db.begin_read()?;
        let table = tx.open_table(ROWS)?;
        for row in table.iter()? {
            let (key, value) = row?;
            let key = snapshot::decode_key(&self.header.binding, key.value())
                .map_err(anyhow::Error::msg)?;
            let value = StoredEntity::decode(&key, value.value()).map_err(anyhow::Error::msg)?;
            visit(&key, &value)?;
        }
        Ok(())
    }
}

fn decode_entity(schema: &InputSchema, value: &StoredEntity) -> Result<Entity> {
    let mut entity = blockchanges::entity_from_wire(schema, &value.fields)?;
    entity
        .set_vid(value.vid)
        .map_err(|e| anyhow!("restoring oracle VID: {e:?}"))?;
    Ok(entity)
}
fn encoded_size(key: &EntityKey, value: Option<&Entity>) -> Result<usize> {
    use prost::Message;
    let key = blockchanges::convert_key(key).encoded_len();
    let fields = value
        .map(|e| {
            backfill_common::pb::pinax::graph::backfill::v1::EntityFields {
                fields: blockchanges::convert_entity(e),
            }
            .encoded_len()
        })
        .unwrap_or(0);
    // Fixed overhead covers map keys/values; key count independently bounds
    // allocator/node overhead, and one bounded undo is retained per block.
    key.checked_add(fields)
        .and_then(|n| n.checked_add(128))
        .ok_or_else(|| anyhow!("oracle encoded row size overflow"))
}
