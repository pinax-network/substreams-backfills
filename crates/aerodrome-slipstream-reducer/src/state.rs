//! Handler-local operations layered over block operations and immutable DB
//! images. Sealing and committing are separate: errors never publish state.
use crate::{
    entity::{self, Entity, EntityClass},
    identity::InputBinding,
    input::BlockInput,
    refuse, require, Address, ReducerError, Result,
};
use backfill_common::pb::pinax::graph::backfill::{v1 as pb, v2};
use backfill_common::{
    block_ops::{BlockOpsBuilder, RecordedOp},
    clock,
    state_snapshot::Boundary,
    CacheOperation,
};
use std::collections::{BTreeMap, BTreeSet};
pub type Fields = Vec<pb::EntityField>;
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Key {
    pub entity_type: String,
    pub id: String,
}
impl Key {
    pub fn new(entity_type: &str, id: &str) -> Self {
        Self {
            entity_type: entity_type.into(),
            id: id.into(),
        }
    }
    fn wire(&self) -> pb::EntityKey {
        entity::key(&self.entity_type, &self.id)
    }
}
/// A backend returns owned Graph Node cache images. Commit must atomically check
/// the expected boundary and install every row/source plus the new boundary.
/// Retention labels do not authorize eviction; this implementation keeps all rows.
pub trait EntityBackend {
    fn boundary(&self) -> &Boundary;
    fn compatibility_id(&self) -> [u8; 32];
    fn get(&self, key: &Key) -> Result<Option<Fields>>;
    fn has_source(&self, pool: &Address) -> bool;
    fn commit(&mut self, sealed: SealedBlock) -> Result<()>;
}
#[derive(Clone, Debug)]
pub struct MemoryBackend {
    compatibility_id: [u8; 32],
    boundary: Boundary,
    rows: BTreeMap<Key, Fields>,
    sources: BTreeMap<Address, Boundary>,
}
impl MemoryBackend {
    pub fn root(binding: &InputBinding, parent_hash: [u8; 32]) -> Result<Self> {
        require(parent_hash != [0; 32], "root parent hash is zero")?;
        Ok(Self {
            compatibility_id: *binding.compatibility().id(),
            boundary: Boundary {
                block_number: binding.compatibility().capabilities().unwrap().start_block - 1,
                block_hash: parent_hash,
            },
            rows: BTreeMap::new(),
            sources: BTreeMap::new(),
        })
    }
    /// Structurally checked in-memory seed for tests/oracles. This is not a
    /// verified snapshot import or proof of source/physical-state provenance.
    pub fn from_images(
        binding: &InputBinding,
        boundary: Boundary,
        rows: BTreeMap<Key, Fields>,
        sources: BTreeMap<Address, Boundary>,
    ) -> Result<Self> {
        require(
            boundary.block_hash != [0; 32]
                && boundary.block_number
                    >= binding.compatibility().capabilities().unwrap().start_block - 1
                && boundary.block_number <= clock::MAX_BLOCK_NUMBER,
            "invalid seed boundary",
        )?;
        for (key, value) in &rows {
            entity::validate_fields(&key.entity_type, &key.id, value, true)?;
            require(
                !value.iter().any(backfill_common::field_is_null),
                "DB image contains top-level Null",
            )?;
        }
        for (pool, created) in &sources {
            require(
                *pool != [0; 20]
                    && created.block_hash != [0; 32]
                    && created.block_number
                        >= binding.compatibility().capabilities().unwrap().start_block
                    && created.block_number <= boundary.block_number,
                "invalid seeded source boundary",
            )?;
        }
        Ok(Self {
            compatibility_id: *binding.compatibility().id(),
            boundary,
            rows,
            sources,
        })
    }
    /// Get-visible cached images, including the existing-row overwrite Null quirk.
    pub fn rows(&self) -> &BTreeMap<Key, Fields> {
        &self.rows
    }
    /// SQL reload image; distinct from the LFU image returned by `get`.
    pub fn database_rows(&self) -> BTreeMap<Key, Fields> {
        self.rows
            .iter()
            .map(|(k, v)| {
                (
                    k.clone(),
                    v.iter()
                        .filter(|f| !backfill_common::field_is_null(f))
                        .cloned()
                        .collect(),
                )
            })
            .collect()
    }
    pub fn sources(&self) -> &BTreeMap<Address, Boundary> {
        &self.sources
    }
}
impl EntityBackend for MemoryBackend {
    fn boundary(&self) -> &Boundary {
        &self.boundary
    }
    fn compatibility_id(&self) -> [u8; 32] {
        self.compatibility_id
    }
    fn get(&self, key: &Key) -> Result<Option<Fields>> {
        Ok(self.rows.get(key).cloned())
    }
    fn has_source(&self, pool: &Address) -> bool {
        self.sources.contains_key(pool)
    }
    fn commit(&mut self, sealed: SealedBlock) -> Result<()> {
        require(
            sealed.expected == self.boundary && sealed.compatibility_id == self.compatibility_id,
            "stale or incompatible sealed block",
        )?;
        require(
            sealed.committable,
            "fatal discarded block cannot commit a state boundary",
        )?;
        for (key, expected) in &sealed.observed {
            require(
                self.rows.get(key) == expected.as_ref(),
                "sealed block read-set changed",
            )?;
        }
        for (pool, expected) in &sealed.observed_sources {
            require(
                self.sources.contains_key(pool) == *expected,
                "sealed source read-set changed",
            )?;
        }
        for source in &sealed.changes.created_data_sources {
            let address: Address = source.param.as_slice().try_into().unwrap();
            require(
                !self.sources.contains_key(&address),
                "sealed source already exists",
            )?;
        }
        // All fallible validation happened before mutation. Private SealedBlock
        // fields prevent callers from swapping the authenticated patch/frame.
        for (key, value) in sealed.patch {
            match value {
                Some(v) => {
                    self.rows.insert(key, v);
                }
                None => {
                    self.rows.remove(&key);
                }
            }
        }
        for source in &sealed.changes.created_data_sources {
            self.sources.insert(
                source.param.as_slice().try_into().unwrap(),
                sealed.boundary.clone(),
            );
        }
        self.boundary = sealed.boundary;
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Abort {
    pub message: String,
}
#[derive(Debug)]
pub enum Step {
    Abort(Abort),
    Fatal(ReducerError),
}
impl From<ReducerError> for Step {
    fn from(e: ReducerError) -> Self {
        Self::Fatal(e)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HandlerStatus {
    Committed,
    Aborted(Abort),
}

pub struct BlockStore<'a, B: EntityBackend> {
    backend: &'a B,
    binding: InputBinding,
    expected: Boundary,
    boundary: Boundary,
    baselines: BTreeMap<Key, Option<Fields>>,
    source_baselines: BTreeMap<Address, bool>,
    main: BTreeMap<Key, CacheOperation>,
    builder: BlockOpsBuilder,
    next_group: u64,
    failed: bool,
    has_abort: bool,
    created: Vec<v2::CreatedDataSource>,
    created_set: BTreeSet<Address>,
}
impl<'a, B: EntityBackend> BlockStore<'a, B> {
    pub fn begin(backend: &'a B, binding: &InputBinding, input: &BlockInput) -> Result<Self> {
        let block = input.block();
        require(
            backend.compatibility_id() == *binding.compatibility().id(),
            "state/descriptor mismatch",
        )?;
        require(
            backend.boundary().block_number.checked_add(1) == Some(block.number)
                && backend.boundary().block_hash.as_slice() == block.parent_hash,
            "state/input boundary mismatch",
        )?;
        Ok(Self {
            backend,
            binding: binding.clone(),
            expected: backend.boundary().clone(),
            boundary: Boundary {
                block_number: block.number,
                block_hash: block.hash.as_slice().try_into().unwrap(),
            },
            baselines: BTreeMap::new(),
            source_baselines: BTreeMap::new(),
            main: BTreeMap::new(),
            builder: BlockOpsBuilder::new(),
            next_group: 0,
            failed: false,
            has_abort: false,
            created: Vec::new(),
            created_set: BTreeSet::new(),
        })
    }
    /// Inspect the block's get-visible image without starting a handler.
    pub fn visible_fields(&mut self, entity_type: &str, id: &str) -> Result<Option<Fields>> {
        require(!self.failed, "block transaction is poisoned")?;
        let key = Key::new(entity_type, id);
        let result = (|| {
            entity::definition(entity_type)?;
            if !self.baselines.contains_key(&key) {
                let value = self.backend.get(&key)?;
                if let Some(fields) = &value {
                    entity::validate_fields(entity_type, id, fields, true)?;
                }
                self.baselines.insert(key.clone(), value);
            }
            let base = self.baselines[&key].clone();
            Ok(self
                .main
                .get(&key)
                .map_or(base.clone(), |op| op.apply_to(&base)))
        })();
        if result.is_err() {
            self.failed = true;
        }
        result
    }
    pub fn run_handler<F>(&mut self, source_trigger_order: u64, run: F) -> Result<HandlerStatus>
    where
        F: FnOnce(&mut HandlerJournal<'_, B>) -> std::result::Result<(), Step>,
    {
        require(!self.failed, "block transaction is poisoned")?;
        self.failed = true; // also poison a panic unwound through the handler closure
        let group = self.next_group;
        self.next_group = self
            .next_group
            .checked_add(1)
            .ok_or_else(|| refuse("handler count overflow"))?;
        let mut journal = HandlerJournal {
            backend: self.backend,
            baselines: &mut self.baselines,
            source_baselines: &mut self.source_baselines,
            main: &self.main,
            locals: BTreeMap::new(),
            before: BTreeMap::new(),
            ops: Vec::new(),
            created: Vec::new(),
            known_created: &self.created_set,
            poisoned: None,
        };
        let outcome = run(&mut journal);
        if let Some(error) = journal.poisoned.take() {
            self.failed = true;
            return Err(error);
        }
        if let Err(Step::Fatal(error)) = outcome {
            self.failed = true;
            return Err(error);
        }
        let HandlerJournal {
            locals,
            before,
            ops,
            created,
            ..
        } = journal;
        if let Err(error) = self
            .builder
            .push_handler(group, source_trigger_order, 0, ops, |key| {
                before.get(key).cloned().flatten()
            })
        {
            self.failed = true;
            return Err(refuse(error.to_string()));
        }
        match outcome {
            Ok(()) => {
                for (key, op) in locals {
                    match self.main.get_mut(&key) {
                        Some(previous) => previous.accumulate(op),
                        None => {
                            self.main.insert(key, op);
                        }
                    }
                }
                for pool in created {
                    if self.created_set.insert(pool) {
                        self.created.push(v2::CreatedDataSource {
                            ordinal: self
                                .created
                                .len()
                                .try_into()
                                .map_err(|_| refuse("source count overflow"))?,
                            manifest_idx: 2,
                            template: "Pool".into(),
                            handler_group_order: group,
                            param: pool.to_vec(),
                            context_json: None,
                        });
                    }
                }
                self.failed = false;
                Ok(HandlerStatus::Committed)
            }
            Err(Step::Abort(abort)) => {
                self.has_abort = true;
                self.builder
                    .push_deterministic_error(
                        group,
                        source_trigger_order,
                        0,
                        "ethereum/base".into(),
                    )
                    .map_err(|e| {
                        self.failed = true;
                        refuse(e.to_string())
                    })?;
                self.failed = false;
                Ok(HandlerStatus::Aborted(abort))
            }
            Err(Step::Fatal(_)) => unreachable!(),
        }
    }
    pub fn seal(self) -> Result<SealedBlock> {
        require(!self.failed, "block transaction is poisoned")?;
        let policy = self.binding.compatibility().deterministic_error_policy();
        let committable = !(self.has_abort && policy == pb::DeterministicErrorPolicy::Fatal);
        let triggered = self.next_group > 0;
        let base = self
            .builder
            .finish(
                self.binding.compatibility(),
                self.boundary.block_number,
                self.boundary.block_hash.to_vec(),
                triggered,
                if triggered {
                    vec!["ethereum/base".into()]
                } else {
                    vec![]
                },
                policy,
            )
            .map_err(|e| refuse(e.to_string()))?;
        let mut changes = v2::BlockChanges::from(base);
        if committable {
            changes.created_data_sources = self.created;
        }
        let payload = backfill_common::encode_canonical_in_band_block_changes(
            &changes,
            self.binding.compatibility(),
        )
        .map_err(|e| refuse(e.to_string()))?;
        // Validate the same extended wire boundary the engine will consume.
        let decoded = backfill_common::decode_canonical_in_band_block_changes(
            &payload,
            self.binding.compatibility(),
        )
        .map_err(|e| refuse(e.to_string()))?;
        require(decoded == changes, "canonical frame roundtrip mismatch")?;
        let mut patch = BTreeMap::new();
        if committable {
            for (key, operation) in self.main {
                let baseline = self.baselines.get(&key).expect("writes captured baseline");
                let value = operation.apply_to(baseline).map(|mut fields| {
                    // Exact as_modifications/cache rule: insert strips Null,
                    // existing Update removes Null through apply_to, existing
                    // Overwrite preserves explicit Null in the LFU image.
                    if baseline.is_none() {
                        fields.retain(|f| !backfill_common::field_is_null(f));
                    }
                    fields
                });
                if let Some(fields) = &value {
                    entity::validate_fields(&key.entity_type, &key.id, fields, true)?;
                }
                patch.insert(key, value);
            }
        }
        let frame = clock::Frame {
            kind: clock::FrameKind::Observed,
            block_number: self.boundary.block_number,
            block_hash: self.boundary.block_hash,
            payload,
        };
        Ok(SealedBlock {
            expected: self.expected,
            boundary: self.boundary,
            compatibility_id: *self.binding.compatibility().id(),
            changes,
            frame,
            patch,
            observed: self.baselines,
            observed_sources: self.source_baselines,
            committable,
        })
    }
}
/// Everything mutable belongs to one handler. Dropping/aborting it drops its
/// operation effects and source creations; earlier handlers remain visible.
pub struct HandlerJournal<'a, B: EntityBackend> {
    backend: &'a B,
    baselines: &'a mut BTreeMap<Key, Option<Fields>>,
    source_baselines: &'a mut BTreeMap<Address, bool>,
    main: &'a BTreeMap<Key, CacheOperation>,
    locals: BTreeMap<Key, CacheOperation>,
    before: BTreeMap<Key, Option<Fields>>,
    ops: Vec<RecordedOp<Key>>,
    created: Vec<Address>,
    known_created: &'a BTreeSet<Address>,
    poisoned: Option<ReducerError>,
}
impl<B: EntityBackend> HandlerJournal<'_, B> {
    fn checked<T>(&mut self, result: Result<T>) -> Result<T> {
        if let Err(e) = &result {
            self.poisoned = Some(e.clone());
        }
        result
    }
    fn before(&mut self, key: &Key) -> Result<Option<Fields>> {
        if !self.baselines.contains_key(key) {
            let value = self.backend.get(key)?;
            if let Some(fields) = &value {
                entity::validate_fields(&key.entity_type, &key.id, fields, true)?;
            }
            self.baselines.insert(key.clone(), value);
        }
        let base = self.baselines[key].clone();
        Ok(self
            .main
            .get(key)
            .map_or(base.clone(), |op| op.apply_to(&base)))
    }
    fn image(&mut self, key: &Key) -> Result<Option<Fields>> {
        let before = self.before(key)?;
        Ok(self
            .locals
            .get(key)
            .map_or(before.clone(), |op| op.apply_to(&before)))
    }
    pub fn load_fields(&mut self, entity_type: &str, id: &str) -> Result<Option<Fields>> {
        let result = (|| {
            entity::definition(entity_type)?;
            self.image(&Key::new(entity_type, id))
        })();
        self.checked(result)
    }
    pub fn load<E: Entity>(&mut self, id: &str) -> Result<Option<E>> {
        let result = self
            .load_fields(E::DEF.name, id)
            .and_then(|f| f.map(|f| E::from_fields(&f)).transpose());
        self.checked(result)
    }
    pub fn load_required<E: Entity>(
        &mut self,
        id: &str,
        abort: Abort,
    ) -> std::result::Result<E, Step> {
        self.load::<E>(id)?.ok_or(Step::Abort(abort))
    }
    pub fn save<E: Entity>(&mut self, entity: &E) -> Result<()> {
        let fields = match entity.to_fields() {
            Ok(v) => v,
            Err(e) => return self.checked(Err(e)),
        };
        self.save_fields(E::DEF.name, entity.id(), &fields)
    }
    pub fn save_fields(
        &mut self,
        entity_type: &str,
        id: &str,
        fields: &[pb::EntityField],
    ) -> Result<()> {
        let result = (|| {
            let definition = entity::definition(entity_type)?;
            require(
                definition.class != EntityClass::NeverWritten,
                "mapping never writes this entity type",
            )?;
            let key = Key::new(entity_type, id);
            let mut written = entity::normalize_fields(fields);
            if !written.iter().any(|f| f.name == "id") {
                written.push(pb::EntityField {
                    name: "id".into(),
                    value: Some(pb::GraphValue {
                        kind: Some(pb::graph_value::Kind::String(id.into())),
                    }),
                });
                written.sort_by(|a, b| a.name.cmp(&b.name));
            }
            entity::validate_fields(entity_type, id, &written, false)?;
            let before = self.before(&key)?;
            let mut operation = self
                .locals
                .get(&key)
                .cloned()
                .unwrap_or(CacheOperation::Update(vec![]));
            operation.accumulate(CacheOperation::Update(written.clone()));
            let image = operation.apply_to(&before).unwrap();
            entity::validate_fields(entity_type, id, &image, true)?;
            self.before.entry(key.clone()).or_insert(before);
            self.locals.insert(key.clone(), operation);
            self.ops.push(RecordedOp::Set {
                native_key: key.clone(),
                key: key.wire(),
                poi_entity_type: entity_type.into(),
                poi_entity_id: id.into(),
                written_fields: written,
                source_causality_region: 0,
                poi_causality_region: "ethereum/base".into(),
            });
            Ok(())
        })();
        self.checked(result)
    }
    pub fn remove<E: Entity>(&mut self, id: &str) -> Result<()> {
        self.remove_fields(E::DEF.name, id)
    }
    pub fn remove_fields(&mut self, entity_type: &str, id: &str) -> Result<()> {
        let result = (|| {
            require(
                entity::definition(entity_type)?.class != EntityClass::NeverWritten,
                "mapping never removes this entity type",
            )?;
            require(!id.contains('\0'), "NUL in entity ID")?;
            let key = Key::new(entity_type, id);
            let before = self.before(&key)?;
            self.before.entry(key.clone()).or_insert(before);
            self.locals.insert(key.clone(), CacheOperation::Remove);
            self.ops.push(RecordedOp::Remove {
                native_key: Some(key.clone()),
                key: Some(key.wire()),
                poi_entity_type: entity_type.into(),
                poi_entity_id: id.into(),
                source_causality_region: 0,
                poi_causality_region: "ethereum/base".into(),
            });
            Ok(())
        })();
        self.checked(result)
    }
    pub fn create_pool_source(&mut self, pool: Address) -> Result<bool> {
        if pool == [0; 20] {
            return self.checked(Err(refuse("zero Pool source address")));
        }
        let existed = *self
            .source_baselines
            .entry(pool)
            .or_insert_with(|| self.backend.has_source(&pool));
        if existed || self.known_created.contains(&pool) || self.created.contains(&pool) {
            return Ok(false);
        }
        self.created.push(pool);
        Ok(true)
    }
}
/// Immutable validated output plus a state patch bound to its predecessor.
/// Writer/checkpoint atomicity across a process crash belongs to the later
/// driver; this API does not claim durable delivery merely because it sealed.
pub struct SealedBlock {
    expected: Boundary,
    boundary: Boundary,
    compatibility_id: [u8; 32],
    changes: v2::BlockChanges,
    frame: clock::Frame,
    patch: BTreeMap<Key, Option<Fields>>,
    observed: BTreeMap<Key, Option<Fields>>,
    observed_sources: BTreeMap<Address, bool>,
    committable: bool,
}
impl SealedBlock {
    pub fn expected_boundary(&self) -> &Boundary {
        &self.expected
    }
    pub fn boundary(&self) -> &Boundary {
        &self.boundary
    }
    pub fn compatibility_id(&self) -> &[u8; 32] {
        &self.compatibility_id
    }
    /// Immutable state patch for future atomic backend implementations.
    pub fn patch(&self) -> &BTreeMap<Key, Option<Fields>> {
        &self.patch
    }
    pub fn observed_rows(&self) -> &BTreeMap<Key, Option<Fields>> {
        &self.observed
    }
    pub fn observed_sources(&self) -> &BTreeMap<Address, bool> {
        &self.observed_sources
    }
    pub fn changes(&self) -> &v2::BlockChanges {
        &self.changes
    }
    pub fn frame(&self) -> &clock::Frame {
        &self.frame
    }
    pub fn write_to(&self, writer: &mut impl std::io::Write) -> Result<()> {
        clock::write_frame(writer, &self.frame).map_err(|e| refuse(e.to_string()))
    }
    pub fn committable(&self) -> bool {
        self.committable
    }
}
