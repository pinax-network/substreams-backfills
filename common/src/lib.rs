//! Family-neutral contracts shared by Substreams backfill modules and the
//! Graph Node compatibility engine.
//!
//! `BlockChanges` deliberately preserves mapping-save order, the exact entity
//! hashed by Graph Node, and each post-merge state. Standard coalesced
//! `EntityChanges` is not an equivalent boundary because it loses intermediate
//! saves and empty-but-triggered proof-of-indexing streams.

pub mod block_changes;
pub mod block_ops;
pub mod clock;
pub mod descriptor;
pub mod dynamic_sources;
pub mod dynamic_sources_v2;
pub mod pb;
pub mod state_snapshot;

pub use block_changes::{
    apply_written_fields, decode_canonical_block_changes, decode_canonical_in_band_block_changes,
    encode_canonical_block_changes, encode_canonical_in_band_block_changes, field_is_null,
    materialized_key, validate_block_changes, validate_in_band_block_changes,
    BlockChangesCompatibility, CacheOperation, CompatibilityDescriptorError, MaterializedId,
    MaterializedKey, NullMergeMode, ValidationError, BLOCK_CHANGES_V1_CONTRACT,
};
