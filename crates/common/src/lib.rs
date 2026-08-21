//! Shared encoding for graph-node-faithful entity emission.
//!
//! The single hard invariant of this workspace lives here: entities emitted by any
//! backfill module must load (via substreams-graph-node-backfill) into a graph-node
//! schema such that queries are indistinguishable from a natively-synced deployment.
//!
//! What that means concretely (M1 scope):
//! - mutable entities carry `block_range int4range` semantics: a version is
//!   [lower, upper) in blocks; the current version is upper-unbounded. `vid` is a
//!   monotonically increasing i64 in write order — the engine assigns final vids,
//!   we must emit versions in deterministic block order per entity.
//! - immutable entities (`@entity(immutable: true)`) carry `block$` (creation block)
//!   instead of a range and are never updated.
//! - BigDecimal/BigInt string forms must round-trip identically to graph-node's
//!   storage normalization (no scientific notation drift, no trailing zeros).
//! - PoI is NOT reproduced by backfills; deployments land paused and unfailed with
//!   PoI table empty beyond the landing block, matching the transplant recipe.

/// Placeholder for the M1 entity-encoding contract. Replaced by generated types per
/// family schema; kept minimal until the engine contract test pins the byte format.
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
