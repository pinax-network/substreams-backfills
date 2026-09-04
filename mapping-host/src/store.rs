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

/// A `BTreeMap`-backed store over one subgraph schema.
pub struct MemoryStore {
    schema: InputSchema,
    rows: RwLock<BTreeMap<EntityKey, Entity>>,
}

impl MemoryStore {
    pub fn new(schema: InputSchema) -> Self {
        MemoryStore {
            schema,
            rows: RwLock::new(BTreeMap::new()),
        }
    }

    /// Apply one handler's modifications, in the order Graph Node would have
    /// written them at the end of the block.
    pub fn apply(&self, mods: &[EntityModification]) {
        let mut rows = self.rows.write().expect("store lock poisoned");
        for m in mods {
            match m {
                EntityModification::Insert { key, data, .. }
                | EntityModification::Overwrite { key, data, .. } => {
                    rows.insert(key.clone(), data.as_ref().clone());
                }
                EntityModification::Remove { key, .. } => {
                    rows.remove(key);
                }
            }
        }
    }

    /// Read one row without an async boundary, for the BlockChanges builder,
    /// which needs the entity visible before the current handler ran.
    pub fn lookup(&self, key: &EntityKey) -> Option<Entity> {
        self.rows
            .read()
            .expect("store lock poisoned")
            .get(key)
            .cloned()
    }

    /// A copy of every row, for the fatal-policy rollback in
    /// [`crate::runner::SegmentHost::process_block`].
    pub fn snapshot(&self) -> BTreeMap<EntityKey, Entity> {
        self.rows.read().expect("store lock poisoned").clone()
    }

    /// Replace every row with a snapshot taken earlier.
    pub fn restore(&self, snapshot: BTreeMap<EntityKey, Entity>) {
        *self.rows.write().expect("store lock poisoned") = snapshot;
    }

    /// Number of live rows, for reporting.
    pub fn len(&self) -> usize {
        self.rows.read().expect("store lock poisoned").len()
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
        let rows = self.rows.read().expect("store lock poisoned");
        let mut out: BTreeMap<String, usize> = BTreeMap::new();
        for key in rows.keys() {
            *out.entry(key.entity_type.typename().to_string())
                .or_default() += 1;
        }
        out
    }
}

#[async_trait]
impl ReadStore for MemoryStore {
    async fn get(&self, key: &EntityKey) -> Result<Option<Entity>, StoreError> {
        Ok(self
            .rows
            .read()
            .expect("store lock poisoned")
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
            .filter_map(|k| rows.get(&k).cloned().map(|e| (k, e)))
            .collect())
    }

    async fn get_derived(
        &self,
        query: &DerivedEntityQuery,
    ) -> Result<BTreeMap<EntityKey, Entity>, StoreError> {
        let rows = self.rows.read().expect("store lock poisoned");
        Ok(rows
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
