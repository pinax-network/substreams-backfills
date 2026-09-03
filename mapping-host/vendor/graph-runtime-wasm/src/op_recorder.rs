//! Observation hook for the ordered entity-operation stream.
//!
//! `EntityCache` collapses writes into a `HashMap`, so the order in which a
//! mapping called `store.set` is not recoverable from `as_modifications`. It is
//! recoverable here: `HostExports::store_set` and `store_remove` already write
//! one `ProofOfIndexingEvent` per call, in call order, and that event stream is
//! what the proof of indexing hashes. A recorder invoked beside those writes
//! therefore observes exactly the sequence the PoI commits to, with no new
//! ordering guarantee to reason about.
//!
//! The recorder sees the entity *as hashed*: schema-filtered, with the id and
//! any timeseries timestamp already injected, and before `EntityCache::set`
//! merges it into a predecessor or stamps a VID. That is the `written_fields`
//! boundary a downstream operation stream needs.
//!
//! Nothing calls a recorder unless one is installed, and the default is `None`,
//! so an unconfigured runtime behaves exactly as it did before.

use std::sync::Arc;

use graph::data::store::Entity;
use graph::schema::EntityKey;

/// Receives every store effect a mapping requests, in call order.
///
/// Implementations must be cheap: they run inside the handler, between the PoI
/// write and the cache write, on the mapping's own thread.
pub trait EntityOpRecorder: Send + Sync {
    /// A `store.set` that has passed schema filtering and id resolution, about
    /// to be handed to `EntityCache::set`.
    ///
    /// `entity` is the exact value hashed into the PoI `SetEntity` event.
    fn record_set(&self, key: &EntityKey, entity: &Entity, poi_causality_region: &str);

    /// A `store.remove`, recorded where the PoI event is written — before the
    /// schema is resolved and the typed key parsed, which is why only the
    /// caller's strings are available.
    fn record_remove(&self, entity_type: &str, entity_id: &str, poi_causality_region: &str);

    /// The typed key for the `store.remove` just recorded, once it parses.
    /// A remove whose key fails to parse is discarded by the handler and this
    /// is never called for it.
    fn record_remove_key(&self, _key: &EntityKey) {}
}

/// A shared recorder, or none.
pub type SharedEntityOpRecorder = Option<Arc<dyn EntityOpRecorder>>;
