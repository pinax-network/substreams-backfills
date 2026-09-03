//! Proof of indexing.
//!
//! Two things happen at the end of a block, and they are different:
//!
//! * **The stored PoI entity.** `core/src/subgraph/runner/mod.rs:1700`
//!   `update_proof_of_indexing` pauses each causality region's event stream,
//!   mixing in that region's digest from the *previous* block, and writes the
//!   result as a `Poi$` entity. That is the value that chains from block to
//!   block. [`update_proof_of_indexing`] below is a documented copy of it; the
//!   original is a private free function, so it cannot be called.
//! * **The public PoI.** `ProofOfIndexingFinisher` combines the stored per-region
//!   digests with the block pointer, the deployment hash and an indexer address
//!   into the value a gateway serves. We pass `indexer: None`, which is the
//!   public (indexer-independent) PoI.
//!
//! The version rule is `core/src/subgraph/instance_manager.rs:487`: spec version
//! `>= 0.0.6` uses `Fast`, everything below uses `Legacy`. Every Uniswap V3
//! deployment is spec 0.0.2 or 0.0.4, so all eight are `Legacy`, which is why the
//! `stable-hash` git dependencies are pinned by revision in `Cargo.lock` rather
//! than tracked by branch.
//!
//! A block in which no handler ran produces no causality region, so
//! `ProofOfIndexing::take()` is empty, no PoI entity is written, and the digest
//! does not advance. The report says `poi: null` for such a block. That is Graph
//! Node's behaviour, not a simplification: `update_proof_of_indexing` iterates the
//! regions that were actually touched.

use std::collections::BTreeMap;

use anyhow::{Error, Result};
use graph::blockchain::{BlockPtr, BlockTime};
use graph::components::store::{EntityCache, GetScope};
use graph::components::subgraph::{
    ProofOfIndexing, ProofOfIndexingFinisher, ProofOfIndexingVersion,
};
use graph::data::store::scalar::Bytes;
use graph::data::store::Value;
use graph::data::subgraph::DeploymentHash;
use graph::data_source::CausalityRegion;
use graph::schema::EntityKey;
use graph::semver::Version;

/// Spec versions at or above this use the `Fast` PoI hasher.
const SPEC_VERSION_0_0_6: Version = Version::new(0, 0, 6);

/// `core/src/subgraph/instance_manager.rs:487`.
pub fn version_for_spec(spec_version: &Version) -> ProofOfIndexingVersion {
    if spec_version >= &SPEC_VERSION_0_0_6 {
        ProofOfIndexingVersion::Fast
    } else {
        ProofOfIndexingVersion::Legacy
    }
}

/// The per-block PoI result.
pub struct BlockPoi {
    /// Causality region name to its paused digest, hex without `0x`.
    pub causality_regions: BTreeMap<String, String>,
    /// The public PoI for this block, hex without `0x`.
    pub public_digest: String,
}

/// Documented copy of `update_proof_of_indexing`
/// (`core/src/subgraph/runner/mod.rs:1700`), which is a private free function in
/// graph-node.
///
/// Differences from the original, both of them additive: it returns the paused
/// digests so the caller can report them and feed the finisher, and it does not
/// take a `StopwatchMetrics` section guard.
pub async fn update_proof_of_indexing(
    proof_of_indexing: ProofOfIndexing,
    block_time: BlockTime,
    entity_cache: &mut EntityCache,
) -> Result<BTreeMap<String, Vec<u8>>, Error> {
    // Helper to store the digest as a PoI entity in the cache.
    async fn store_poi_entity(
        entity_cache: &mut EntityCache,
        key: EntityKey,
        digest: Bytes,
        block_time: BlockTime,
    ) -> Result<(), Error> {
        let digest_name = entity_cache.schema.poi_digest();
        let mut data = vec![
            (
                graph::data::store::ID.clone(),
                Value::from(key.entity_id.to_string()),
            ),
            (digest_name, Value::from(digest)),
        ];
        if entity_cache.schema.has_aggregations() {
            let block_time = Value::Int8(block_time.as_secs_since_epoch());
            data.push((entity_cache.schema.poi_block_time(), block_time));
        }
        let poi = entity_cache.make_entity(data)?;
        entity_cache.set(key, poi, None).await
    }

    let mut proof_of_indexing = proof_of_indexing.take();
    let mut paused = BTreeMap::new();

    for (causality_region, stream) in proof_of_indexing.drain() {
        // There are two things called causality regions here: the PoI causality
        // region, which is a string and the PoI entity id, and the data source
        // causality region the PoI belongs to as an entity. Offchain events do not
        // affect the PoI, so the latter is always `ONCHAIN`.
        // See also: poi-ignores-offchain
        let entity_key = entity_cache
            .schema
            .poi_type()
            .key_in(causality_region.clone(), CausalityRegion::ONCHAIN);

        // Grab the current digest attribute on this entity.
        let poi_digest = entity_cache.schema.poi_digest().clone();
        let prev_poi = entity_cache
            .get(&entity_key, GetScope::Store)
            .await
            .map_err(Error::from)?
            .map(|entity| match entity.get(poi_digest.as_str()) {
                Some(Value::Bytes(b)) => b.clone(),
                _ => panic!("Expected POI entity to have a digest and for it to be bytes"),
            });

        // Finish the PoI stream, getting the new PoI value.
        let updated_proof_of_indexing = stream.pause(prev_poi.as_deref());
        paused.insert(
            causality_region.to_string(),
            updated_proof_of_indexing.clone(),
        );
        let updated_proof_of_indexing: Bytes = (&updated_proof_of_indexing[..]).into();

        // Put this onto an entity with the same digest attribute that was expected
        // before when reading.
        store_poi_entity(
            entity_cache,
            entity_key,
            updated_proof_of_indexing,
            block_time,
        )
        .await?;
    }

    Ok(paused)
}

/// Combine the paused per-region digests into the public PoI for this block.
///
/// This is the query-time computation `graph-store-postgres` performs when a
/// gateway asks for a PoI, with `indexer: None`.
pub fn finish(
    block_ptr: &BlockPtr,
    deployment: &DeploymentHash,
    version: ProofOfIndexingVersion,
    paused: &BTreeMap<String, Vec<u8>>,
) -> BlockPoi {
    let mut finisher = ProofOfIndexingFinisher::new(block_ptr, deployment, &None, version);
    // Regions are mixed in unordered by the hasher, but we iterate a `BTreeMap`
    // so a report is byte-stable regardless.
    for (name, bytes) in paused {
        let id = graph::data::store::Id::String(name.clone().into());
        finisher.add_causality_region(&id, bytes);
    }
    BlockPoi {
        causality_regions: paused
            .iter()
            .map(|(k, v)| (k.clone(), hex::encode(v)))
            .collect(),
        public_digest: hex::encode(finisher.finish()),
    }
}
