//! Segment-transaction working state. Committing an individual block changes
//! only the open redb transaction; dropping it restores the previous boundary.
//! Logical checkpoint/undo evidence is independent of redb's physical bytes.
use crate::{
    entity,
    hosts::HostSet,
    identity::InputBinding,
    refuse, require,
    state::{EntityBackend, Fields, Key, SealedBlock},
    Address, Result,
};
use backfill_common::{
    descriptor::ProducerContract,
    dynamic_sources::DataSource,
    dynamic_sources_v2::{Creation, SourceOrder},
    pb::pinax::graph::backfill::v1::EntityFields,
    producer_checkpoint::{self as checkpoint, Binding, FailedHosts, Manifest, Origin, Sources},
    state_snapshot::Boundary,
};
use prost::Message;
use redb::{
    Database, Durability, ReadableDatabase, ReadableTable, ReadableTableMetadata, TableDefinition,
    WriteTransaction,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{BufReader, BufWriter, Read, Write},
    path::{Path, PathBuf},
};

const ENTITIES: TableDefinition<&[u8], &[u8]> = TableDefinition::new("entities");
const SOURCES: TableDefinition<&[u8], &[u8]> = TableDefinition::new("sources");
const FAILED: TableDefinition<&[u8], &[u8]> = TableDefinition::new("failed_hosts");
const UNDO: TableDefinition<&[u8], &[u8]> = TableDefinition::new("undo");
const META: TableDefinition<&str, &[u8]> = TableDefinition::new("meta");
const MAX_RECORD: usize = 256 * 1024 * 1024;
const UNDO_MAGIC: &[u8; 8] = b"ARUNDO1\0";
const UNDO_END: &[u8; 8] = b"ARUEND1\0";

mod seed;
pub use seed::{SeedImportPins, SourceHistoryAssertion};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct UndoHeader {
    before: Manifest,
    to: Boundary,
    records: u64,
}

struct HashWriter<W> {
    output: W,
    hash: Sha256,
    bytes: u64,
}
impl<W: Write> HashWriter<W> {
    fn new(output: W) -> Self {
        Self {
            output,
            hash: Sha256::new(),
            bytes: 0,
        }
    }
    fn put(&mut self, bytes: &[u8]) -> Result<()> {
        self.output.write_all(bytes).map_err(error)?;
        self.hash.update(bytes);
        self.bytes = self
            .bytes
            .checked_add(bytes.len() as u64)
            .ok_or_else(|| refuse("output size overflow"))?;
        Ok(())
    }
    fn record(&mut self, bytes: &[u8]) -> Result<()> {
        require(bytes.len() <= MAX_RECORD, "undo record exceeds ceiling")?;
        self.put(&(bytes.len() as u32).to_be_bytes())?;
        self.put(bytes)
    }
}
fn optional_bytes(output: &mut Vec<u8>, bytes: Option<&[u8]>) -> Result<()> {
    output.push(u8::from(bytes.is_some()));
    if let Some(bytes) = bytes {
        require(bytes.len() <= MAX_RECORD, "undo image exceeds ceiling")?;
        output.extend((bytes.len() as u32).to_be_bytes());
        output.extend(bytes);
    }
    Ok(())
}
fn take_optional(input: &mut &[u8]) -> Result<Option<Vec<u8>>> {
    let mut flag = [0];
    input.read_exact(&mut flag).map_err(error)?;
    if flag == [0] {
        return Ok(None);
    }
    require(flag == [1], "bad undo presence")?;
    let mut len = [0; 4];
    input.read_exact(&mut len).map_err(error)?;
    let n = u32::from_be_bytes(len) as usize;
    require(
        n <= MAX_RECORD && input.len() >= n,
        "truncated/oversized undo image",
    )?;
    let value = input[..n].to_vec();
    *input = &input[n..];
    Ok(Some(value))
}
fn immutable_bytes(path: &Path, bytes: &[u8]) -> Result<()> {
    match OpenOptions::new().create_new(true).write(true).open(path) {
        Ok(mut file) => {
            file.write_all(bytes).map_err(error)?;
            file.sync_all().map_err(error)
        }
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => require(
            fs::symlink_metadata(path).map_err(error)?.is_file()
                && fs::read(path).map_err(error)? == bytes,
            "immutable evidence collision",
        ),
        Err(e) => Err(error(e)),
    }
}

fn error(e: impl std::fmt::Display) -> crate::ReducerError {
    refuse(e.to_string())
}
fn sync_dir(path: &Path) -> Result<()> {
    File::open(path).and_then(|f| f.sync_all()).map_err(error)
}
fn create(path: &Path) -> Result<File> {
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .read(true)
        .open(path)
        .map_err(error)
}
fn canonical<T: Serialize>(v: &T) -> Result<Vec<u8>> {
    serde_json::to_vec(v).map_err(error)
}
fn decode<T: serde::de::DeserializeOwned + Serialize>(b: &[u8]) -> Result<T> {
    require(b.len() <= MAX_RECORD, "state record exceeds ceiling")?;
    let v = serde_json::from_slice(b).map_err(error)?;
    require(canonical(&v)? == b, "noncanonical state record")?;
    Ok(v)
}
fn key_bytes(key: &Key) -> Result<Vec<u8>> {
    require(
        !key.entity_type.is_empty() && !key.entity_type.contains('\0'),
        "invalid entity type",
    )?;
    let mut bytes = key.entity_type.as_bytes().to_vec();
    bytes.push(0);
    bytes.extend(key.id.as_bytes());
    Ok(bytes)
}
fn decode_key(bytes: &[u8]) -> Result<Key> {
    let n = bytes
        .iter()
        .position(|b| *b == 0)
        .ok_or_else(|| refuse("invalid entity key"))?;
    Ok(Key::new(
        std::str::from_utf8(&bytes[..n]).map_err(error)?,
        std::str::from_utf8(&bytes[n + 1..]).map_err(error)?,
    ))
}
fn fields_bytes(key: &Key, fields: &Fields) -> Result<Vec<u8>> {
    entity::validate_fields(&key.entity_type, &key.id, fields, true)?;
    let bytes = EntityFields {
        fields: fields.clone(),
    }
    .encode_to_vec();
    require(bytes.len() <= MAX_RECORD, "entity exceeds state ceiling")?;
    Ok(bytes)
}
fn decode_fields(key: &Key, bytes: &[u8]) -> Result<Fields> {
    require(bytes.len() <= MAX_RECORD, "entity exceeds state ceiling")?;
    let v = EntityFields::decode(bytes).map_err(error)?;
    require(v.encode_to_vec() == bytes, "noncanonical entity state")?;
    entity::validate_fields(&key.entity_type, &key.id, &v.fields, true)?;
    Ok(v.fields)
}
fn bind(input: &InputBinding, binding: &Binding) -> Result<()> {
    binding.validate().map_err(error)?;
    let cap = input.compatibility().capabilities().unwrap();
    let ProducerContract::NativeBlockChangesReducer { reducer, extractor } = &cap.producer_contract
    else {
        return Err(refuse("durable producer contract is not native"));
    };
    require(
        binding.family == "aerodrome-slipstream"
            && binding.deployment == cap.deployment
            && binding.network == "base"
            && binding.descriptor_sha256 == hex::encode(input.compatibility().id())
            && binding.reducer_commit == reducer.commit
            && binding.spkg_sha256 == extractor.spkg_sha256
            && binding.module == extractor.module
            && binding.module_hash == extractor.module_hash,
        "durable producer binding differs from input descriptor",
    )
}

pub struct DurableStore {
    database: Database,
    root: PathBuf,
    binding: Binding,
}
impl DurableStore {
    /// Root state uses the same zero-hash sentinel as BCGSNAP1. Neither an
    /// origin manifest nor a successful initialization is a completed segment.
    pub fn init_empty(
        root: &Path,
        input: &InputBinding,
        binding: Binding,
        engine_lineage: &str,
        cache_bytes: usize,
    ) -> Result<Self> {
        bind(input, &binding)?;
        require(cache_bytes > 0, "state cache must be positive")?;
        let origin = Origin::EmptyRoot {
            start_block: input.compatibility().capabilities().unwrap().start_block,
        };
        let manifest = Manifest {
            format: checkpoint::FORMAT.into(),
            boundary: origin.boundary().map_err(error)?,
            reducer_lineage: checkpoint::initial_lineage(&binding, &origin).map_err(error)?,
            binding: binding.clone(),
            origin,
            engine_lineage_before: engine_lineage.into(),
            transition: None,
            sources: Sources::empty(),
            failed_hosts: FailedHosts::empty(),
            retained_by_type: BTreeMap::new(),
            full_state_sha256: None,
        };
        let bytes = manifest.encode().map_err(error)?;
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
        tx.open_table(META)
            .map_err(error)?
            .insert("manifest", bytes.as_slice())
            .map_err(error)?;
        let name = format!("{}.json", hex::encode(Sha256::digest(&bytes)));
        let mut file = create(&root.join("checkpoints").join(name))?;
        file.write_all(&bytes).map_err(error)?;
        file.sync_all().map_err(error)?;
        sync_dir(&root.join("checkpoints"))?;
        sync_dir(root)?;
        tx.commit().map_err(|e| {
            refuse(format!(
                "initial commit outcome unknown; reopen to inspect: {e}"
            ))
        })?;
        Ok(Self {
            database: db,
            root: root.into(),
            binding,
        })
    }
    pub fn open(
        root: &Path,
        input: &InputBinding,
        binding: Binding,
        cache_bytes: usize,
    ) -> Result<Self> {
        bind(input, &binding)?;
        require(
            cache_bytes > 0
                && fs::symlink_metadata(root).map_err(error)?.is_dir()
                && fs::symlink_metadata(root.join("state.redb"))
                    .map_err(error)?
                    .is_file(),
            "invalid state store",
        )?;
        let database = Database::builder()
            .set_cache_size(cache_bytes)
            .open(root.join("state.redb"))
            .map_err(error)?;
        let store = Self {
            database,
            root: root.into(),
            binding,
        };
        store.manifest()?;
        Ok(store)
    }
    pub fn manifest(&self) -> Result<Manifest> {
        let tx = self.database.begin_read().map_err(error)?;
        let table = tx.open_table(META).map_err(error)?;
        let bytes = table
            .get("manifest")
            .map_err(error)?
            .ok_or_else(|| refuse("store never initialized"))?;
        let manifest = Manifest::decode(bytes.value()).map_err(error)?;
        require(manifest.binding == self.binding, "state binding mismatch")?;
        let pin = hex::encode(Sha256::digest(bytes.value()));
        let actual =
            fs::read(self.root.join("checkpoints").join(format!("{pin}.json"))).map_err(error)?;
        require(
            actual == bytes.value(),
            "committed checkpoint evidence differs from state",
        )?;
        seed::verify_retained_evidence(&tx, &self.root, &manifest)?;
        Ok(manifest)
    }
    /// Exact requested predecessor is mandatory. At the root, the nonzero
    /// observed parent comes from the first verified input block and is used
    /// only for execution's hash-chain check, never as the synthetic origin.
    pub fn begin_segment(
        &self,
        expected: &Boundary,
        lineage: &str,
        engine_lineage_before: &str,
        observed_root_parent: Option<[u8; 32]>,
    ) -> Result<Segment> {
        // Seed provenance is immutable across every continuation, not only open.
        self.manifest()?;
        let tx = self.database.begin_write().map_err(error)?;
        let bytes = tx
            .open_table(META)
            .map_err(error)?
            .get("manifest")
            .map_err(error)?
            .ok_or_else(|| refuse("store never initialized"))?
            .value()
            .to_vec();
        let before = Manifest::decode(&bytes).map_err(error)?;
        let predecessor_path = self
            .root
            .join("checkpoints")
            .join(format!("{}.json", hex::encode(Sha256::digest(&bytes))));
        require(
            fs::symlink_metadata(&predecessor_path)
                .map_err(error)?
                .is_file()
                && fs::read(predecessor_path).map_err(error)? == bytes,
            "predecessor checkpoint evidence differs",
        )?;
        require(
            before.binding == self.binding
                && &before.boundary == expected
                && before.reducer_lineage == lineage,
            "requested reducer predecessor differs from store",
        )?;
        require(
            tx.open_table(UNDO)
                .map_err(error)?
                .is_empty()
                .map_err(error)?,
            "unsealed committed undo",
        )?;
        require(
            tx.open_table(ENTITIES)
                .map_err(error)?
                .len()
                .map_err(error)?
                == before.retained_by_type.values().sum::<u64>()
                && tx
                    .open_table(SOURCES)
                    .map_err(error)?
                    .len()
                    .map_err(error)?
                    == before.sources.count
                && tx.open_table(FAILED).map_err(error)?.len().map_err(error)?
                    == before.failed_hosts.count,
            "durable table counts differ from checkpoint",
        )?;
        let mut boundary = before.boundary.clone();
        if boundary.block_hash == [0; 32] {
            boundary.block_hash = observed_root_parent
                .filter(|h| *h != [0; 32])
                .ok_or_else(|| refuse("initial segment requires observed parent"))?;
        } else {
            require(observed_root_parent.is_none(), "unexpected root parent")?;
        }
        let mut after = before.clone();
        after.engine_lineage_before = engine_lineage_before.into();
        // Check the independent engine identity before any block can mutate.
        after.validate().map_err(error)?;
        Ok(Segment {
            tx: Some(tx),
            root: self.root.clone(),
            before,
            after,
            boundary,
            observed_root_parent,
            poisoned: Cell::new(false),
            #[cfg(test)]
            fail_after: Cell::new(None),
        })
    }
    /// Rewind exactly one completed segment using its checksum-verified undo.
    /// Every after-image must still match. Failure drops the whole transaction.
    pub fn rewind_one(&self, expected: &Manifest) -> Result<Manifest> {
        self.manifest()?;
        let mut tx = self.database.begin_write().map_err(error)?;
        let current_bytes = tx
            .open_table(META)
            .map_err(error)?
            .get("manifest")
            .map_err(error)?
            .ok_or_else(|| refuse("uninitialized state"))?
            .value()
            .to_vec();
        let current = Manifest::decode(&current_bytes).map_err(error)?;
        require(
            &current == expected && current.binding == self.binding,
            "rewind expected head differs",
        )?;
        let transition = current
            .transition
            .as_ref()
            .ok_or_else(|| refuse("cannot rewind initial state"))?;
        let path = self.root.join(&transition.undo.path);
        require(
            fs::symlink_metadata(&path).map_err(error)?.is_file(),
            "undo is not a regular file",
        )?;
        let header = read_undo(&path, &transition.undo, |kind, key, before, after| {
            let mut table = tx.open_table(table(kind)?).map_err(error)?;
            let actual = table.get(key).map_err(error)?.map(|v| v.value().to_vec());
            require(
                actual.as_deref() == after,
                "undo after-image differs from store",
            )?;
            if let Some(before) = before {
                table.insert(key, before).map_err(error)?;
            } else {
                table.remove(key).map_err(error)?;
            }
            Ok(())
        })?;
        require(header.to == current.boundary, "undo final boundary differs")?;
        let previous_bytes = header.before.encode().map_err(error)?;
        current
            .require_predecessor(&previous_bytes)
            .map_err(error)?;
        let pinned = self
            .root
            .join("checkpoints")
            .join(format!("{}.json", transition.previous_checkpoint_sha256));
        require(
            fs::read(pinned).map_err(error)? == previous_bytes,
            "predecessor checkpoint evidence differs",
        )?;
        tx.open_table(META)
            .map_err(error)?
            .insert("manifest", previous_bytes.as_slice())
            .map_err(error)?;
        tx.set_durability(Durability::Immediate).map_err(error)?;
        tx.commit()
            .map_err(|e| refuse(format!("rewind outcome unknown; reopen and inspect: {e}")))?;
        Ok(header.before)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    creation_block: u64,
    // Accepted source identity/order does not include a creation-block hash;
    // BCGSNAP1 seeds cannot supply one. Only failed outcomes retain this hash.
    failed_at_hash: Option<[u8; 32]>,
    ordinal: u64,
}

fn logical_state_digest(tx: &WriteTransaction) -> Result<String> {
    let mut h = Sha256::new();
    h.update(b"pinax.aerodrome.reducer-state/v1\0");
    for kind in 0..3u8 {
        h.update([kind]);
        let t = tx.open_table(table(kind)?).map_err(error)?;
        for row in t.iter().map_err(error)? {
            let (k, v) = row.map_err(error)?;
            h.update((k.value().len() as u64).to_be_bytes());
            h.update(k.value());
            h.update((v.value().len() as u64).to_be_bytes());
            h.update(v.value());
        }
    }
    Ok(hex::encode(h.finalize()))
}

pub struct Segment {
    tx: Option<WriteTransaction>,
    root: PathBuf,
    before: Manifest,
    after: Manifest,
    boundary: Boundary,
    observed_root_parent: Option<[u8; 32]>,
    poisoned: Cell<bool>,
    #[cfg(test)]
    fail_after: Cell<Option<usize>>,
}
impl Segment {
    fn tx(&self) -> &WriteTransaction {
        self.tx.as_ref().expect("live transaction")
    }
    fn healthy(&self) -> Result<()> {
        require(!self.poisoned.get(), "durable reducer segment is poisoned")
    }
    fn io<T>(&self, r: std::result::Result<T, impl std::fmt::Display>) -> Result<T> {
        r.map_err(|e| {
            self.poisoned.set(true);
            error(e)
        })
    }
    fn get_raw(&self, table: TableDefinition<&[u8], &[u8]>, key: &[u8]) -> Result<Option<Vec<u8>>> {
        self.healthy()?;
        let t = self.io(self.tx().open_table(table))?;
        let value = self.io(t.get(key))?.map(|v| v.value().to_vec());
        Ok(value)
    }
    fn write_raw(&self, kind: u8, key: &[u8], value: Option<&[u8]>) -> Result<()> {
        self.healthy()?;
        #[cfg(test)]
        if let Some(n) = self.fail_after.get() {
            if n == 0 {
                return self.io::<()>(Err("injected state write failure"));
            }
            self.fail_after.set(Some(n - 1));
        }
        let table = table(kind)?;
        let mut undo_key = vec![kind];
        undo_key.extend(key);
        let mut undo = self.io(self.tx().open_table(UNDO))?;
        if self.io(undo.get(undo_key.as_slice()))?.is_none() {
            let before = self.get_raw(table, key)?;
            let mut encoded = vec![u8::from(before.is_some())];
            if let Some(bytes) = before {
                encoded.extend(bytes);
            }
            self.io(undo.insert(undo_key.as_slice(), encoded.as_slice()))?;
        }
        drop(undo);
        let mut table = self.io(self.tx().open_table(table))?;
        if let Some(value) = value {
            self.io(table.insert(key, value))?;
        } else {
            self.io(table.remove(key))?;
        }
        Ok(())
    }
    pub fn abort(mut self) -> Result<()> {
        self.tx.take().unwrap().abort().map_err(error)
    }
    pub fn predecessor(&self) -> &Manifest {
        &self.before
    }
    /// Exhaustive logical digest over ordered rows, source and failed-host
    /// records. This scan is explicit, never silently performed each block.
    pub fn state_digest(&self) -> Result<String> {
        self.healthy()?;
        self.io(logical_state_digest(self.tx()))
    }
    /// Private: only the full stream/producer-success gate below may commit a
    /// segment. Callers cannot turn a per-block commit into durable completion.
    fn seal_and_commit(mut self, full_digest: bool, output: &Path) -> Result<Manifest> {
        self.healthy()?;
        require(
            self.boundary.block_number > self.before.boundary.block_number,
            "cannot seal empty segment",
        )?;
        let records = self.io(self.tx().open_table(UNDO))?;
        let header = UndoHeader {
            before: self.before.clone(),
            to: self.boundary.clone(),
            records: self.io(records.len())?,
        };
        let temporary = output.join("undo.partial");
        let mut writer = HashWriter::new(BufWriter::new(create(&temporary)?));
        writer.put(UNDO_MAGIC)?;
        writer.record(&canonical(&header)?)?;
        for row in self.io(records.iter())? {
            let (key, before) = self.io(row)?;
            let raw = key.value();
            require(raw.len() > 1, "empty undo key")?;
            let after = self.get_raw(table(raw[0])?, &raw[1..])?;
            let before = before.value();
            require(
                !before.is_empty() && (before[0] == 1 || before == [0]),
                "bad undo before image",
            )?;
            let mut encoded = (raw.len() as u32).to_be_bytes().to_vec();
            encoded.extend(raw);
            optional_bytes(&mut encoded, (before[0] == 1).then_some(&before[1..]))?;
            optional_bytes(&mut encoded, after.as_deref())?;
            writer.record(&encoded)?;
        }
        drop(records);
        writer.put(UNDO_END)?;
        writer.put(&header.records.to_be_bytes())?;
        let checksum = writer.hash.clone().finalize();
        writer.put(&checksum)?;
        writer.output.flush().map_err(error)?;
        writer.output.get_ref().sync_all().map_err(error)?;
        let undo_sha = hex::encode(writer.hash.finalize());
        let undo_bytes = writer.bytes;
        drop(writer.output);
        let undo_relative = format!("undo/{undo_sha}.bin");
        let undo_path = self.root.join(&undo_relative);
        // Content-addressed files are immutable. hard_link atomically installs
        // the completed inode; an existing pin must verify before reuse.
        match fs::hard_link(&temporary, &undo_path) {
            Ok(()) => (),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                let pin = checkpoint::FilePin {
                    path: undo_relative.clone(),
                    bytes: undo_bytes,
                    sha256: undo_sha.clone(),
                };
                read_undo(&undo_path, &pin, |_, _, _, _| Ok(()))?;
            }
            Err(e) => return Err(error(e)),
        }
        sync_dir(&self.root.join("undo"))?;
        self.after.boundary = self.boundary.clone();
        self.after.reducer_lineage =
            checkpoint::advance_lineage(&self.before.reducer_lineage, &undo_sha).map_err(error)?;
        self.after.transition = Some(checkpoint::Transition {
            from: self.before.boundary.clone(),
            observed_root_parent_hash: self.observed_root_parent,
            previous_checkpoint_sha256: hex::encode(Sha256::digest(
                self.before.encode().map_err(error)?,
            )),
            lineage_before: self.before.reducer_lineage.clone(),
            undo: checkpoint::FilePin {
                path: undo_relative,
                bytes: undo_bytes,
                sha256: undo_sha,
            },
        });
        self.after.full_state_sha256 = if full_digest {
            Some(self.state_digest()?)
        } else {
            None
        };
        self.after
            .require_predecessor(&self.before.encode().map_err(error)?)
            .map_err(error)?;
        let bytes = self.after.encode().map_err(error)?;
        immutable_bytes(
            &self
                .root
                .join("checkpoints")
                .join(format!("{}.json", hex::encode(Sha256::digest(&bytes)))),
            &bytes,
        )?;
        immutable_bytes(&output.join("producer-checkpoint.json"), &bytes)?;
        sync_dir(&self.root.join("checkpoints"))?;
        sync_dir(output)?;
        self.io(self.tx().open_table(META))?
            .insert("manifest", bytes.as_slice())
            .map_err(error)?;
        self.io(self.tx().open_table(UNDO))?
            .retain(|_, _| false)
            .map_err(error)?;
        let mut tx = self.tx.take().unwrap();
        tx.set_durability(Durability::Immediate).map_err(error)?;
        tx.commit().map_err(|e| {
            refuse(format!(
                "segment commit outcome unknown; reopen and inspect: {e}"
            ))
        })?;
        Ok(self.after)
    }
}

/// Bounded streaming reader; callbacks mutate only an uncommitted transaction.
/// No returned header exists until trailer, checksum, exact pin and EOF pass.
fn read_undo(
    path: &Path,
    pin: &checkpoint::FilePin,
    mut visit: impl FnMut(u8, &[u8], Option<&[u8]>, Option<&[u8]>) -> Result<()>,
) -> Result<UndoHeader> {
    pin.validate().map_err(error)?;
    let file = File::open(path).map_err(error)?;
    require(
        file.metadata().map_err(error)?.len() == pin.bytes,
        "undo size differs",
    )?;
    let mut input = BufReader::new(file);
    let mut hash = Sha256::new();
    fn read(input: &mut impl Read, hash: &mut Sha256, n: usize) -> Result<Vec<u8>> {
        require(n <= MAX_RECORD, "undo read exceeds ceiling")?;
        let mut bytes = vec![0; n];
        input.read_exact(&mut bytes).map_err(error)?;
        hash.update(&bytes);
        Ok(bytes)
    }
    fn record(input: &mut impl Read, hash: &mut Sha256) -> Result<Vec<u8>> {
        let n = u32::from_be_bytes(read(input, hash, 4)?.try_into().unwrap()) as usize;
        read(input, hash, n)
    }
    require(
        read(&mut input, &mut hash, 8)? == UNDO_MAGIC,
        "bad undo magic",
    )?;
    let header: UndoHeader = decode(&record(&mut input, &mut hash)?)?;
    header.before.validate().map_err(error)?;
    require(
        header.to.block_hash != [0; 32]
            && header.to.block_number > header.before.boundary.block_number
            && header.to.block_number <= i32::MAX as u64,
        "bad undo boundaries",
    )?;
    let mut previous = Vec::new();
    for _ in 0..header.records {
        let bytes = record(&mut input, &mut hash)?;
        let mut r = bytes.as_slice();
        let mut len = [0; 4];
        r.read_exact(&mut len).map_err(error)?;
        let n = u32::from_be_bytes(len) as usize;
        require(n > 1 && r.len() >= n, "truncated undo key")?;
        let key = &r[..n];
        r = &r[n..];
        require(key > previous.as_slice(), "unordered/duplicate undo key")?;
        table(key[0])?;
        let before = take_optional(&mut r)?;
        let after = take_optional(&mut r)?;
        require(r.is_empty(), "trailing undo record data")?;
        if key[0] == 0 {
            let k = decode_key(&key[1..])?;
            for image in [before.as_deref(), after.as_deref()].into_iter().flatten() {
                decode_fields(&k, image)?;
            }
        } else {
            crate::address(&key[1..])?;
            for image in [before.as_deref(), after.as_deref()].into_iter().flatten() {
                let _: Source = decode(image)?;
            }
        }
        visit(key[0], &key[1..], before.as_deref(), after.as_deref())?;
        previous = key.to_vec();
    }
    require(
        read(&mut input, &mut hash, 8)? == UNDO_END,
        "bad undo trailer",
    )?;
    let count = u64::from_be_bytes(read(&mut input, &mut hash, 8)?.try_into().unwrap());
    require(count == header.records, "undo trailer count differs")?;
    let expected = hash.clone().finalize();
    let actual = read(&mut input, &mut hash, 32)?;
    require(
        expected.as_slice() == actual && hex::encode(hash.finalize()) == pin.sha256,
        "undo checksum/pin differs",
    )?;
    let mut extra = [0];
    require(
        input.read(&mut extra).map_err(error)? == 0,
        "trailing undo bytes",
    )?;
    Ok(header)
}

/// Local streaming execution, never a producer/v2 supervisor receipt. The
/// callback must reap/cancel its input producer even on refusal. Disk state is
/// committed only after exact input EOF and callback success; a failed result
/// can leave immutable evidence, but never a false completion marker.
pub fn run_segment<R: Read>(
    runner: crate::runner::Runner<Segment>,
    input: crate::input::InputStream<R>,
    output: &Path,
    max_blocks: u64,
    full_digest: bool,
    producer_success: impl FnOnce(crate::runner::InputCompletion) -> Result<()>,
) -> Result<Manifest> {
    use crate::runner::InputCompletion;
    run_segment_streaming(
        runner,
        input,
        output,
        max_blocks,
        full_digest,
        &mut std::io::sink(),
        |head| {
            producer_success(if head.is_some() {
                InputCompletion::Complete
            } else {
                InputCompletion::Refused
            })
        },
    )
}

/// Emit provisional frames as they are executed. Consumers must not publish
/// them without the actual successful producer exit and checkpoint. The
/// callback receives a verified final boundary only after complete input EOF;
/// `None` requires cancellation/refusal and cannot authorize a commit.
pub fn run_segment_streaming<R: Read, W: Write>(
    mut runner: crate::runner::Runner<Segment>,
    mut input: crate::input::InputStream<R>,
    output: &Path,
    max_blocks: u64,
    full_digest: bool,
    provisional: &mut W,
    producer_success: impl FnOnce(Option<&Boundary>) -> Result<()>,
) -> Result<Manifest> {
    let result = (|| {
        require(
            max_blocks > 0 && max_blocks <= 50_000,
            "segment block limit must be 1..=50000",
        )?;
        require(
            input.binding().compatibility().id() == &runner.backend().compatibility_id(),
            "segment input binding differs",
        )?;
        fs::create_dir(output).map_err(error)?;
        let mut writer =
            HashWriter::new(BufWriter::new(create(&output.join("frames.bcf1.partial"))?));
        let mut blocks = 0u64;
        while let Some(block) = input.next_block()? {
            require(blocks < max_blocks, "segment block limit exceeded")?;
            let block = runner.process(&block)?;
            let mut bytes = Vec::new();
            backfill_common::clock::write_frame(&mut bytes, block.frame()).map_err(error)?;
            writer.put(&bytes)?;
            provisional.write_all(&bytes).map_err(error)?;
            blocks += 1;
        }
        let end = input.finish()?;
        require(
            blocks > 0 && runner.backend().boundary().block_hash == end,
            "segment final boundary differs",
        )?;
        writer.output.flush().map_err(error)?;
        writer.output.get_ref().sync_all().map_err(error)?;
        provisional.flush().map_err(error)?;
        Ok((blocks, writer.bytes, hex::encode(writer.hash.finalize())))
    })();
    let producer = producer_success(result.is_ok().then(|| runner.backend().boundary()));
    let (blocks, bytes, hash) = result?;
    producer?;
    fs::rename(
        output.join("frames.bcf1.partial"),
        output.join("frames.bcf1"),
    )
    .map_err(error)?;
    sync_dir(output)?;
    let manifest = runner
        .into_backend()?
        .seal_and_commit(full_digest, output)?;
    let receipt = serde_json::json!({"format":"pinax.aerodrome.local-durable-segment/v1",
        "blocks":blocks,"frames_bytes":bytes,"frames_sha256":hash,
        "checkpoint_sha256":hex::encode(Sha256::digest(manifest.encode().map_err(error)?)),
        "producer_supervisor_receipt":false,"production_qualified":false});
    let mut file = create(&output.join("complete.json.partial"))?;
    serde_json::to_writer_pretty(&mut file, &receipt).map_err(error)?;
    file.write_all(b"\n").map_err(error)?;
    file.sync_all().map_err(error)?;
    sync_dir(output)?;
    // No fallible work follows publication. If an earlier step fails after
    // commit, callers inspect the store's exact boundary and immutable pins.
    fs::rename(
        output.join("complete.json.partial"),
        output.join("complete.json"),
    )
    .map_err(error)?;
    Ok(manifest)
}
fn table(kind: u8) -> Result<TableDefinition<'static, &'static [u8], &'static [u8]>> {
    match kind {
        0 => Ok(ENTITIES),
        1 => Ok(SOURCES),
        2 => Ok(FAILED),
        _ => Err(refuse("invalid undo table")),
    }
}

#[cfg(test)]
mod tests;
impl EntityBackend for Segment {
    fn boundary(&self) -> &Boundary {
        &self.boundary
    }
    fn compatibility_id(&self) -> [u8; 32] {
        hex::decode(&self.before.binding.descriptor_sha256)
            .unwrap()
            .try_into()
            .unwrap()
    }
    fn get(&self, key: &Key) -> Result<Option<Fields>> {
        self.get_raw(ENTITIES, &key_bytes(key)?)?
            .map(|b| self.io(decode_fields(key, &b)))
            .transpose()
    }
    fn has_source(&self, pool: &Address) -> Result<bool> {
        Ok(self.get_raw(SOURCES, pool)?.is_some())
    }
    fn host_set(&self) -> Result<HostSet> {
        self.healthy()?;
        let mut hosts = HostSet::default();
        let mut source_order = SourceOrder::empty();
        let mut failed_order = FailedHosts::empty();
        for (table, failed) in [(SOURCES, false), (FAILED, true)] {
            let rows = self.io(self.tx().open_table(table))?;
            let mut order = BTreeMap::new();
            for row in self.io(rows.iter())? {
                let (k, v) = self.io(row)?;
                let pool = crate::address(k.value())?;
                let source: Source = self.io(decode(v.value()))?;
                require(
                    (if failed {
                        source.failed_at_hash.is_some_and(|h| h != [0; 32])
                    } else {
                        source.failed_at_hash.is_none()
                    }) && order
                        .insert(
                            source.ordinal,
                            (pool, source.creation_block, source.failed_at_hash),
                        )
                        .is_none(),
                    "invalid durable host boundary or duplicate ordinal",
                )?;
                if failed {
                    hosts.seed_aborted(pool, source.creation_block, self.boundary.block_number)?;
                } else {
                    hosts.seed(pool, source.creation_block, self.boundary.block_number)?;
                }
            }
            for (ordinal, (pool, creation_block, failed_at_hash)) in order {
                if failed {
                    require(ordinal == failed_order.count, "failed-host ordinal gap")?;
                    let mut hash = Sha256::new();
                    hash.update(b"pinax.reducer-failed-hosts/v1\0");
                    hash.update(hex::decode(&failed_order.sha256).map_err(error)?);
                    hash.update(pool);
                    hash.update(creation_block.to_be_bytes());
                    hash.update(failed_at_hash.unwrap());
                    failed_order.sha256 = hex::encode(hash.finalize());
                    failed_order.count += 1;
                } else {
                    source_order
                        .append(&Creation {
                            ordinal,
                            source: DataSource {
                                creation_block: creation_block as i32,
                                manifest_idx: 2,
                                causality_region: 0,
                                param: hex::encode(pool),
                                context: None,
                                done_at: None,
                            },
                        })
                        .map_err(error)?;
                }
            }
        }
        require(
            source_order.count == self.after.sources.count
                && source_order.sha256 == self.after.sources.order_sha256
                && failed_order == self.after.failed_hosts,
            "durable host commitments differ",
        )?;
        Ok(hosts)
    }
    fn commit(&mut self, sealed: SealedBlock) -> Result<()> {
        self.healthy()?;
        require(
            sealed.expected_boundary() == &self.boundary
                && sealed.compatibility_id() == &self.compatibility_id()
                && sealed.committable(),
            "stale/incompatible/uncommittable durable block",
        )?;
        for (key, expected) in sealed.observed_rows() {
            require(
                self.get(key)?.as_ref() == expected.as_ref(),
                "durable block read-set changed",
            )?;
        }
        for (pool, expected) in sealed.observed_sources() {
            require(
                self.has_source(pool)? == *expected,
                "durable source read-set changed",
            )?;
        }
        let mut writes = Vec::new();
        let mut counts = self.after.retained_by_type.clone();
        for (key, value) in sealed.patch() {
            let old = self.get(key)?;
            if old.is_some() != value.is_some() {
                let n = counts.entry(key.entity_type.clone()).or_default();
                *n = if value.is_some() {
                    n.checked_add(1)
                } else {
                    n.checked_sub(1)
                }
                .ok_or_else(|| refuse("retained entity count overflow"))?;
            }
            writes.push((
                0,
                key_bytes(key)?,
                value.as_ref().map(|v| fields_bytes(key, v)).transpose()?,
            ));
        }
        counts.retain(|_, n| *n > 0);
        let mut sources = SourceOrder {
            count: self.after.sources.count,
            sha256: self.after.sources.order_sha256.clone(),
        };
        for source in &sealed.changes().created_data_sources {
            let pool = crate::address(&source.param)?;
            require(
                !self.has_source(&pool)? && self.get_raw(FAILED, &pool)?.is_none(),
                "duplicate durable source",
            )?;
            let row = Source {
                creation_block: sealed.boundary().block_number,
                failed_at_hash: None,
                ordinal: sources.count,
            };
            sources
                .append(&Creation {
                    ordinal: row.ordinal,
                    source: DataSource {
                        manifest_idx: source.manifest_idx as i32,
                        param: hex::encode(pool),
                        creation_block: sealed.boundary().block_number as i32,
                        causality_region: 0,
                        context: None,
                        done_at: None,
                    },
                })
                .map_err(error)?;
            writes.push((1, pool.to_vec(), Some(canonical(&row)?)));
        }
        let mut failed = self.after.failed_hosts.clone();
        for pool in sealed.aborted_sources() {
            require(
                !self.has_source(pool)? && self.get_raw(FAILED, pool)?.is_none(),
                "duplicate durable failed source",
            )?;
            let row = Source {
                creation_block: sealed.boundary().block_number,
                failed_at_hash: Some(sealed.boundary().block_hash),
                ordinal: failed.count,
            };
            let mut hash = Sha256::new();
            hash.update(b"pinax.reducer-failed-hosts/v1\0");
            hash.update(hex::decode(&failed.sha256).map_err(error)?);
            hash.update(pool);
            hash.update(row.creation_block.to_be_bytes());
            hash.update(row.failed_at_hash.unwrap());
            failed.sha256 = hex::encode(hash.finalize());
            failed.count = failed
                .count
                .checked_add(1)
                .ok_or_else(|| refuse("failed host count overflow"))?;
            writes.push((2, pool.to_vec(), Some(canonical(&row)?)));
        }
        // Logical validation completed. Any redb error from this point poisons
        // the whole segment, including subsequent reads and checkpoint attempts.
        for (kind, key, value) in writes {
            self.write_raw(kind, &key, value.as_deref())?;
        }
        self.after.sources = Sources {
            count: sources.count,
            order_sha256: sources.sha256,
        };
        self.after.failed_hosts = failed;
        self.after.retained_by_type = counts;
        self.boundary = sealed.boundary().clone();
        Ok(())
    }
}
