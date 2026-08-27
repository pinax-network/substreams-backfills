//! Shared encoding for graph-node-faithful entity emission.
//!
//! The single hard invariant of this workspace lives here: entities emitted by any
//! backfill module must load (via substreams-graph-node-backfill) into a graph-node
//! schema such that queries are indistinguishable from a natively-synced deployment.
//!
//! What that means concretely (M2 scope):
//! - mutable entities carry `block_range int4range` semantics: a version is
//!   [lower, upper) in blocks; the current version is upper-unbounded. `vid` is a
//!   monotonically increasing i64 in write order — the engine assigns final vids,
//!   we must emit versions in deterministic block order per entity.
//! - immutable entities (`@entity(immutable: true)`) carry `block$` (creation block)
//!   instead of a range and are never updated.
//! - BigDecimal/BigInt string forms must round-trip identically to graph-node's
//!   storage normalization (no scientific notation drift, no trailing zeros).
//! - Proof of indexing is reproduced by the native backfill engine from the exact
//!   ordered mapping operations. A family is not deployment-hash faithful if it
//!   drops, coalesces, or reorders operations needed by Graph Node's PoI stream.

/// Placeholder retained until M2 replaces it with the ordered, V4-derived
/// family-to-engine protocol and pins its byte format through a golden regression.
pub struct EntityVersion {
    pub entity: &'static str,
    pub id: String,
    /// Block at which this version becomes visible.
    pub from_block: u64,
    /// Block at which it is superseded (None = current version).
    pub to_block: Option<u64>,
    /// Column values as (name, graph-node-normalized string form).
    pub values: Vec<(String, String)>,
}
