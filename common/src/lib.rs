//! Family-neutral contracts shared by Substreams backfill modules and the
//! Graph Node compatibility engine.
//!
//! `BlockChanges` deliberately preserves mapping-save order, the exact entity
//! hashed by Graph Node, and each post-merge state. Standard coalesced
//! `EntityChanges` is not an equivalent boundary because it loses intermediate
//! saves and empty-but-triggered proof-of-indexing streams.

pub mod block_changes;
pub mod pb;

pub use block_changes::{
    decode_canonical_block_changes, encode_canonical_block_changes, validate_block_changes,
    BlockChangesCompatibility, CompatibilityDescriptorError, ValidationError,
    BLOCK_CHANGES_V1_CONTRACT,
};
