//! An in-memory `ReadStore`.
//!
//! `EntityCache` needs only [`ReadStore`] — four methods — not `WritableStore`,
//! so the host never touches Postgres. The map persists across blocks within one
//! run, which is what makes a multi-block replay meaningful.
//!
//! ## Why writes land here between handlers
//!
//! Graph Node uses **one** `BlockState`, and therefore one `EntityCache`, for
//! every handler in a block; a handler's `store.get` sees writes an earlier
//! handler in the same block made, because `EntityCache::get` layers `updates`
//! over `current`.
//!
//! To report *per-handler* modifications we give each handler its own
//! `BlockState` and take `as_modifications` after it returns. To keep reads
//! observationally identical to the shared cache we do two things per handler:
//!
//! 1. apply that handler's modifications into this store, and
//! 2. thread the `entity_lfu_cache` that `as_modifications` returns into the next
//!    handler's `BlockState` via `EntityCache::with_current`.
//!
//! After `as_modifications`, `current` holds the post-write entity for every key
//! the handler touched and `updates` is empty, so the next handler's `get` reads
//! the same bytes the shared cache would have produced. Step 1 keeps `current`
//! and the store in agreement, which also satisfies the `debug_assert!` in
//! `EntityCache::get` that compares them (that assertion is live in test builds).
//!
//! The two models are equivalent for reads. They differ in two ways, neither of
//! which the Uniswap V3 mappings can reach:
//!
//! * A shared cache emits **no** modification when a handler changes an entity
//!   and a later handler changes it back; per-handler snapshots emit both. That
//!   is the difference we want: the report is a per-handler operation stream, not
//!   a coalesced block diff.
//! * `Remove` then `Set` on one key is a single `Overwrite` under a shared cache
//!   and a `Remove` followed by an `Insert` here. The V3 mappings never remove an
//!   entity — none of the twenty deployed modules imports `store.remove` — so the
//!   case cannot arise.
//!
//! Sequence numbers are *not* per handler: the [`SeqGenerator`] is cloned, and a
//! clone shares the same atomic counters, so VIDs stay dense and monotonic across
//! the whole block exactly as Graph Node's do.
//!
//! [`SeqGenerator`]: graph::components::store::SeqGenerator

use std::collections::{BTreeMap, BTreeSet};
use std::sync::RwLock;

use async_trait::async_trait;
use graph::components::store::write::EntityModification;
use graph::components::store::{DerivedEntityQuery, EnsLookup, ReadStore, StoreError};
use graph::data::store::Entity;
use graph::schema::{EntityKey, InputSchema};

/// The existing memory implementation remains unchanged. Disk mode makes I/O
/// failures explicit at every runner boundary and refuses eager full exports.
pub enum HostStore {
    Memory(MemoryStore),
    Disk(Box<crate::disk_store::DiskStore>),
}

impl HostStore {
    pub fn schema(&self) -> &InputSchema {
        match self {
            Self::Memory(s) => s.schema(),
            Self::Disk(s) => s.schema(),
        }
    }
    pub fn poi_typename(&self) -> String {
        self.schema().poi_type().typename().to_string()
    }
    pub fn lookup(&self, key: &EntityKey) -> anyhow::Result<Option<Entity>> {
        match self {
            Self::Memory(s) => Ok(s.lookup(key)),
            Self::Disk(s) => s.lookup(key),
        }
    }
    pub fn snapshot(&self) -> anyhow::Result<BTreeMap<EntityKey, Entity>> {
        match self { Self::Memory(s) => Ok(s.snapshot()), Self::Disk(_) => anyhow::bail!("disk oracle refuses full in-memory checkpoint/export; use the initial streamed cold checkpoint") }
    }
    pub fn restore(&self, rows: BTreeMap<EntityKey, Entity>) -> anyhow::Result<()> {
        match self {
            Self::Memory(s) => {
                s.restore(rows);
                Ok(())
            }
            Self::Disk(_) => anyhow::bail!(
                "disk oracle seed is immutable; eager checkpoint restore is unsupported"
            ),
        }
    }
    pub fn counts_by_type(&self) -> BTreeMap<String, usize> {
        match self {
            Self::Memory(s) => s.counts_by_type(),
            Self::Disk(s) => s.counts_by_type(),
        }
    }
    pub fn len(&self) -> usize {
        match self {
            Self::Memory(s) => s.len(),
            Self::Disk(s) => s.len(),
        }
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
    pub(crate) fn apply(&self, mods: &[EntityModification]) -> anyhow::Result<()> {
        match self {
            Self::Memory(s) => {
                s.apply(mods);
                Ok(())
            }
            Self::Disk(s) => s.apply_recording(mods, &mut StoreUndo::new()),
        }
    }
    pub(crate) fn apply_recording(
        &self,
        mods: &[EntityModification],
        undo: &mut StoreUndo,
    ) -> anyhow::Result<()> {
        match self {
            Self::Memory(s) => {
                s.apply_recording(mods, undo);
                Ok(())
            }
            Self::Disk(s) => s.apply_recording(mods, undo),
        }
    }
    pub(crate) fn rollback(&self, undo: StoreUndo) -> anyhow::Result<()> {
        match self {
            Self::Memory(s) => {
                s.rollback(undo);
                Ok(())
            }
            Self::Disk(s) => s.rollback(undo),
        }
    }
}

#[async_trait]
impl ReadStore for HostStore {
    async fn get(&self, key: &EntityKey) -> Result<Option<Entity>, StoreError> {
        self.lookup(key).map_err(StoreError::from)
    }
    async fn get_many(
        &self,
        keys: BTreeSet<EntityKey>,
    ) -> Result<BTreeMap<EntityKey, Entity>, StoreError> {
        let mut rows = BTreeMap::new();
        for key in keys {
            if let Some(entity) = self.lookup(&key).map_err(StoreError::from)? {
                rows.insert(key, entity);
            }
        }
        Ok(rows)
    }
    async fn get_derived(
        &self,
        query: &DerivedEntityQuery,
    ) -> Result<BTreeMap<EntityKey, Entity>, StoreError> {
        match self { Self::Memory(s) => s.get_derived(query).await, Self::Disk(_) => Err(StoreError::from(anyhow::anyhow!("disk oracle does not implement full derived queries; refusing rather than returning overlay-only rows"))) }
    }
    fn input_schema(&self) -> InputSchema {
        self.schema().clone()
    }
}

/// A `BTreeMap`-backed store over one subgraph schema.
pub struct MemoryStore {
    schema: InputSchema,
    rows: RwLock<Rows>,
}

/// The first value of each key changed in one block, including absence. This
/// grows with distinct writes in the block, not with all historical live rows.
pub(crate) type StoreUndo = BTreeMap<EntityKey, Option<Entity>>;

#[derive(Default)]
struct Rows {
    entities: BTreeMap<EntityKey, Entity>,
    counts: BTreeMap<String, usize>,
}

impl Rows {
    fn set(&mut self, key: EntityKey, value: Option<Entity>) {
        match value {
            Some(entity) => {
                let name = key.entity_type.typename().to_string();
                if self.entities.insert(key, entity).is_none() {
                    *self.counts.entry(name).or_default() += 1;
                }
            }
            None => {
                if self.entities.remove(&key).is_some() {
                    let name = key.entity_type.typename().to_string();
                    let count = self.counts.get_mut(&name).expect("live row has a count");
                    *count -= 1;
                    if *count == 0 {
                        self.counts.remove(&name);
                    }
                }
            }
        }
    }
}

impl MemoryStore {
    pub fn new(schema: InputSchema) -> Self {
        MemoryStore {
            schema,
            rows: RwLock::new(Rows::default()),
        }
    }

    /// Apply one handler's modifications, in the order Graph Node would have
    /// written them at the end of the block.
    pub fn apply(&self, mods: &[EntityModification]) {
        self.apply_inner(mods, None);
    }

    /// Preserve each key's pre-block value once, across all handlers and waves.
    /// Recording a later overwrite as the original would corrupt fatal rollback.
    pub(crate) fn apply_recording(&self, mods: &[EntityModification], undo: &mut StoreUndo) {
        self.apply_inner(mods, Some(undo));
    }

    fn apply_inner(&self, mods: &[EntityModification], mut undo: Option<&mut StoreUndo>) {
        let mut rows = self.rows.write().expect("store lock poisoned");
        for m in mods {
            let (key, value) = match m {
                EntityModification::Insert { key, data, .. }
                | EntityModification::Overwrite { key, data, .. } => {
                    (key, Some(data.as_ref().clone()))
                }
                EntityModification::Remove { key, .. } => (key, None),
            };
            if let Some(undo) = undo.as_mut() {
                undo.entry(key.clone())
                    .or_insert_with(|| rows.entities.get(key).cloned());
            }
            rows.set(key.clone(), value);
        }
    }

    /// Restore only keys touched by this block. PoI is applied separately by
    /// the runner after a fatal block's entity modifications have been undone.
    pub(crate) fn rollback(&self, undo: StoreUndo) {
        let mut rows = self.rows.write().expect("store lock poisoned");
        for (key, value) in undo {
            rows.set(key, value);
        }
    }

    /// Read one row without an async boundary, for the BlockChanges builder,
    /// which needs the entity visible before the current handler ran.
    pub fn lookup(&self, key: &EntityKey) -> Option<Entity> {
        self.rows
            .read()
            .expect("store lock poisoned")
            .entities
            .get(key)
            .cloned()
    }

    /// A copy of every row for explicit checkpoint/export operations, not for
    /// per-block rollback. Those exports still require full-state memory.
    pub fn snapshot(&self) -> BTreeMap<EntityKey, Entity> {
        self.rows
            .read()
            .expect("store lock poisoned")
            .entities
            .clone()
    }

    /// Replace every row with a snapshot taken earlier.
    pub fn restore(&self, snapshot: BTreeMap<EntityKey, Entity>) {
        let mut counts = BTreeMap::new();
        for key in snapshot.keys() {
            *counts
                .entry(key.entity_type.typename().to_string())
                .or_default() += 1;
        }
        *self.rows.write().expect("store lock poisoned") = Rows {
            entities: snapshot,
            counts,
        };
    }

    /// Number of live rows, for reporting.
    pub fn len(&self) -> usize {
        self.rows
            .read()
            .expect("store lock poisoned")
            .entities
            .len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// The deployed schema this store was built over.
    ///
    /// [`ReadStore::input_schema`] returns a clone; a checkpoint restore needs
    /// the schema to rebuild keys and entities and has no reason to pay for one
    /// per row.
    pub fn schema(&self) -> &InputSchema {
        &self.schema
    }

    /// The deployed schema's own proof-of-indexing typename.
    ///
    /// Read from the schema rather than spelled as a literal, so a deployment
    /// that names it differently still splits correctly in
    /// [`crate::store_state`].
    pub fn poi_typename(&self) -> String {
        self.schema.poi_type().typename().to_string()
    }

    /// Live rows grouped by entity type, for reporting.
    pub fn counts_by_type(&self) -> BTreeMap<String, usize> {
        self.rows
            .read()
            .expect("store lock poisoned")
            .counts
            .clone()
    }
}

#[async_trait]
impl ReadStore for MemoryStore {
    async fn get(&self, key: &EntityKey) -> Result<Option<Entity>, StoreError> {
        Ok(self
            .rows
            .read()
            .expect("store lock poisoned")
            .entities
            .get(key)
            .cloned())
    }

    async fn get_many(
        &self,
        keys: BTreeSet<EntityKey>,
    ) -> Result<BTreeMap<EntityKey, Entity>, StoreError> {
        let rows = self.rows.read().expect("store lock poisoned");
        Ok(keys
            .into_iter()
            .filter_map(|k| rows.entities.get(&k).cloned().map(|e| (k, e)))
            .collect())
    }

    async fn get_derived(
        &self,
        query: &DerivedEntityQuery,
    ) -> Result<BTreeMap<EntityKey, Entity>, StoreError> {
        let rows = self.rows.read().expect("store lock poisoned");
        Ok(rows
            .entities
            .iter()
            .filter(|(key, entity)| query.matches(key, entity))
            .map(|(key, entity)| (key.clone(), entity.clone()))
            .collect())
    }

    fn input_schema(&self) -> InputSchema {
        self.schema.clone()
    }
}

/// ENS is not reachable hermetically, and no Uniswap V3 module imports
/// `ens.nameByHash`. Returning `None` matches a Graph Node with an empty ENS
/// table, which is also what `is_table_empty` reports.
pub struct NoEnsLookup;

#[async_trait]
impl EnsLookup for NoEnsLookup {
    async fn find_name(&self, _hash: &str) -> Result<Option<String>, StoreError> {
        Ok(None)
    }

    async fn is_table_empty(&self) -> Result<bool, StoreError> {
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use graph::data::store::Value;
    use graph::prelude::DeploymentHash;
    use std::sync::Arc;

    fn store() -> MemoryStore {
        MemoryStore::new(
            InputSchema::parse_latest(
                "type Thing @entity(immutable: false) { id: ID!, value: Int! }\n\
             type Other @entity(immutable: false) { id: ID!, value: Int! }",
                DeploymentHash::new("rollback_test").unwrap(),
            )
            .unwrap(),
        )
    }

    fn key(store: &MemoryStore, kind: &str, id: &str) -> EntityKey {
        store
            .schema()
            .entity_type(kind)
            .unwrap()
            .parse_key(id)
            .unwrap()
    }

    fn put(store: &MemoryStore, kind: &str, id: &str, value: i32) -> EntityModification {
        let mut entity = store
            .schema()
            .make_entity(vec![
                ("id".into(), Value::String(id.to_string())),
                ("value".into(), Value::Int(value)),
            ])
            .unwrap();
        entity.set_vid(i64::from(value) + 100).unwrap();
        EntityModification::Insert {
            key: key(store, kind, id),
            data: Arc::new(entity),
            block: 1,
            end: None,
        }
    }

    fn remove(store: &MemoryStore, kind: &str, id: &str) -> EntityModification {
        EntityModification::Remove {
            key: key(store, kind, id),
            block: 1,
        }
    }

    fn overwrite(store: &MemoryStore, kind: &str, id: &str, value: i32) -> EntityModification {
        match put(store, kind, id, value) {
            EntityModification::Insert {
                key,
                data,
                block,
                end,
            } => EntityModification::Overwrite {
                key,
                data,
                block,
                end,
            },
            _ => unreachable!(),
        }
    }

    fn assert_snapshot(store: &MemoryStore, expected: &BTreeMap<EntityKey, Entity>) {
        let actual = store.snapshot();
        assert_eq!(&actual, expected);
        // Graph Node's Entity equality deliberately excludes VID.
        for (key, entity) in expected {
            assert_eq!(actual[key].vid(), entity.vid(), "VID changed for {key:?}");
        }
    }

    fn check_counts(store: &MemoryStore) {
        let mut expected = BTreeMap::new();
        for key in store.snapshot().keys() {
            *expected
                .entry(key.entity_type.typename().to_string())
                .or_default() += 1;
        }
        assert_eq!(store.counts_by_type(), expected);
        assert_eq!(store.len(), expected.values().sum::<usize>());
    }

    #[test]
    fn rollback_preserves_first_value_and_absence_across_handlers() {
        let store = store();
        store.apply(&[put(&store, "Thing", "a", 1), put(&store, "Other", "a", 2)]);
        let before = store.snapshot();
        let mut undo = StoreUndo::new();
        // Distinct batches stand for handlers/waves in the same block.
        store.apply_recording(
            &[
                overwrite(&store, "Thing", "a", 3),
                put(&store, "Thing", "new", 4),
            ],
            &mut undo,
        );
        store.apply_recording(
            &[
                remove(&store, "Thing", "a"),
                remove(&store, "Thing", "new"),
                remove(&store, "Other", "a"),
                remove(&store, "Other", "absent"),
            ],
            &mut undo,
        );
        store.apply_recording(
            &[put(&store, "Thing", "a", 5), put(&store, "Thing", "new", 6)],
            &mut undo,
        );
        assert_eq!(undo.len(), 4);
        assert_eq!(
            undo[&key(&store, "Thing", "a")],
            Some(before[&key(&store, "Thing", "a")].clone())
        );
        assert_eq!(undo[&key(&store, "Thing", "new")], None);
        check_counts(&store);
        store.rollback(undo);
        assert_snapshot(&store, &before);
        check_counts(&store);
    }

    #[test]
    fn successful_block_discards_only_undo_and_next_block_has_new_baseline() {
        let store = store();
        let mut undo = StoreUndo::new();
        store.apply_recording(&[put(&store, "Thing", "a", 1)], &mut undo);
        drop(undo); // Successful block: keep the modified store.
        let before = store.snapshot();
        let mut undo = StoreUndo::new();
        store.apply_recording(&[overwrite(&store, "Thing", "a", 2)], &mut undo);
        store.rollback(undo);
        assert_snapshot(&store, &before);
        // The runner's separate post-rollback PoI write uses the ordinary path.
        store.apply(&[put(&store, "Other", "poi", 3)]);
        assert_eq!(store.len(), 2);
        check_counts(&store);
    }

    #[test]
    fn empty_and_sparse_blocks_do_not_copy_unrelated_rows() {
        let store = store();
        let rows: Vec<_> = (0..10_000)
            .map(|i| put(&store, "Thing", &i.to_string(), i))
            .collect();
        store.apply(&rows);
        let mut undo = StoreUndo::new();
        store.apply_recording(&[], &mut undo);
        assert!(undo.is_empty());
        store.apply_recording(&[put(&store, "Thing", "500", 1)], &mut undo);
        assert_eq!(undo.len(), 1);
        assert_eq!(store.len(), 10_000);
        store.rollback(undo);
        assert_eq!(
            store.lookup(&key(&store, "Thing", "500")),
            match &rows[500] {
                EntityModification::Insert { data, .. } => Some(data.as_ref().clone()),
                _ => unreachable!(),
            }
        );
        check_counts(&store);
    }

    #[test]
    fn cached_counts_match_full_scan_through_mutations_rollback_and_restore() {
        let store = store();
        for block in 0..10 {
            let before = store.snapshot();
            let mut undo = StoreUndo::new();
            for i in 0..50 {
                let kind = if i % 2 == 0 { "Thing" } else { "Other" };
                let id = ((i * 7 + block) % 13).to_string();
                let change = if (i + block) % 3 == 0 {
                    remove(&store, kind, &id)
                } else {
                    put(&store, kind, &id, i + block)
                };
                store.apply_recording(&[change], &mut undo);
                check_counts(&store);
            }
            if block % 2 == 0 {
                store.rollback(undo);
                assert_snapshot(&store, &before);
            }
            check_counts(&store);
            let saved = store.snapshot();
            store.restore(BTreeMap::new());
            assert!(store.is_empty());
            assert!(store.counts_by_type().is_empty());
            store.restore(saved);
            check_counts(&store);
        }
    }
}
