//! `--store-out`: the final in-memory store, in the frames' own encoding.
//!
//! Hermetic: the committed cassette and the four hydrated block fixtures, no
//! network.
//!
//! The claim this file makes is the one a consumer is compared against. A frame
//! is an *operation stream*; the store is what folding that stream leaves
//! behind. So the central test does not check the dump against a golden, which
//! would only prove the dump is stable — it checks every row against the last
//! **committed** `Set` for that key in the frames, which proves the dump and the
//! frames describe the same store, field for field, in the same value encoding.
//!
//! Block 12,370,523 is what makes that check bite: under this manifest's fatal
//! policy its two handlers fail deterministically, so the block's saves carry a
//! discarded disposition, none of them reaches the store, and a dump that
//! ignored disposition would disagree here and nowhere else.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::OnceLock;

use backfill_common::pb::pinax::graph::backfill::v2 as pb;
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::store_state::{
    StoreEntity, StoreEntityId, StorePoi, StoreRange, StoreState, StoreValue, STORE_STATE_SCHEMA,
};
use graph_mapping_host::{block, blockchanges};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
const FIXTURES: &[&str] = &["12369621", "12369739", "12369879", "12370523"];
/// The typename Graph Node gives the proof-of-indexing entity.
const POI_TYPE: &str = "Poi$";

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn block_fixture(name: &str) -> PathBuf {
    crate_dir()
        .parent()
        .expect("mapping-host has a parent")
        .join(format!("uniswap-v3/fixtures/blocks/mainnet/{name}.pb"))
}

struct Run {
    state: StoreState,
    frames: Vec<pb::BlockChanges>,
    /// Live rows per entity type as the last replayed block reported them.
    final_counts: BTreeMap<String, usize>,
}

fn run() -> &'static Run {
    static RUN: OnceLock<Run> = OnceLock::new();
    RUN.get_or_init(|| {
        for name in FIXTURES {
            assert!(
                block_fixture(name).exists(),
                "missing block fixture; run `cargo xtask evidence fetch --lock \
                 uniswap-v3/fixtures/blocks.lock.json` from the repository root"
            );
        }
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime")
            .block_on(replay())
    })
}

async fn replay() -> Run {
    let mut host = SegmentHost::load(SegmentHostConfig {
        bundle_dir: &crate_dir().join(format!("segments/{SEGMENT}")),
        cassette_path: &crate_dir().join(format!("fixtures/cassettes/{SEGMENT}.json")),
        record: false,
    })
    .await
    .expect("loading the segment");

    use graph::blockchain::Block as _;
    let mut blocks = Vec::new();
    for name in FIXTURES {
        blocks.push(block::load_block(&block_fixture(name)).expect("loading a fixture"));
    }
    blocks.sort_by_key(|b| b.number());

    let mut frames = Vec::new();
    let mut closing_poi = None;
    let mut final_counts = BTreeMap::new();
    for b in blocks {
        let number = b.number();
        let outcome = host
            .process_block(b)
            .await
            .unwrap_or_else(|error| panic!("replaying block {number}: {error:#}"));
        // Sealing is what proves the frame is canonical; a dump checked against
        // an unvalidated frame would prove nothing about the wire form.
        blockchanges::seal(&outcome.changes, host.compatibility())
            .unwrap_or_else(|error| panic!("sealing block {number}: {error:#}"));
        if let Some(poi) = outcome.report.poi.as_ref() {
            closing_poi = Some(StorePoi {
                block: number,
                version: poi.version.clone(),
                causality_regions: poi.causality_regions.clone(),
                public_digest: poi.public_digest.clone(),
            });
        }
        final_counts = outcome.report.store_counts.clone();
        frames.push(outcome.changes);
    }

    let state = host
        .store_state(
            Some(StoreRange {
                from: 12369621,
                to: 12370524,
                blocks: FIXTURES.len(),
            }),
            closing_poi,
        )
        .expect("dumping the store");

    Run {
        state,
        frames,
        final_counts,
    }
}

/// Storage identity, as both the dump and a frame key an entity.
type Identity = (String, StoreEntityId, i32);

fn identity(entity: &StoreEntity) -> Identity {
    (
        entity.entity_type.clone(),
        entity.id.clone(),
        entity.storage_causality_region,
    )
}

fn wire_identity(key: &pb::EntityKey) -> Identity {
    let id = match key.id.as_ref().and_then(|id| id.value.as_ref()) {
        Some(pb::entity_id::Value::String(value)) => StoreEntityId::String(value.clone()),
        Some(pb::entity_id::Value::Bytes(value)) => StoreEntityId::Bytes(value.clone()),
        Some(pb::entity_id::Value::Int8(value)) => StoreEntityId::Int8(*value),
        None => panic!("a validated Set always carries an id"),
    };
    (key.entity_type.clone(), id, key.storage_causality_region)
}

/// The last committed `Set` for every key, in frame then operation order.
///
/// This is the fold a consumer performs. Removes never occur in this segment —
/// no deployed V3 module imports `store.remove` — so the last committed write
/// wins outright and nothing needs to be deleted from the map.
fn last_committed_sets() -> BTreeMap<Identity, Vec<(String, StoreValue)>> {
    let mut latest = BTreeMap::new();
    for changes in &run().frames {
        for operation in &changes.operations {
            let Some(pb::entity_operation::Operation::Set(set)) = operation.operation.as_ref()
            else {
                continue;
            };
            if set.store_disposition != pb::StoreDisposition::Committed as i32 {
                continue;
            }
            let key = set.key.as_ref().expect("a validated Set carries a key");
            let materialized = set
                .materialized
                .as_ref()
                .expect("a validated Set carries its materialized entity");
            let fields = materialized
                .fields
                .iter()
                .map(|field| {
                    (
                        field.name.clone(),
                        StoreValue::from_wire(field.value.as_ref().expect("a field has a value"))
                            .expect("a wire value mirrors"),
                    )
                })
                .collect();
            latest.insert(wire_identity(key), fields);
        }
    }
    latest
}

#[test]
fn every_row_equals_the_last_committed_save_in_the_frames() {
    let expected = last_committed_sets();
    let dumped: BTreeMap<Identity, Vec<(String, StoreValue)>> = run()
        .state
        .entities
        .iter()
        .map(|entity| (identity(entity), entity.fields.clone()))
        .collect();

    assert!(
        !expected.is_empty(),
        "the fixture blocks must commit at least one save"
    );
    assert_eq!(
        dumped.keys().collect::<Vec<_>>(),
        expected.keys().collect::<Vec<_>>(),
        "the dump and the frames disagree about which entities exist"
    );
    for (key, fields) in &expected {
        assert_eq!(
            dumped.get(key),
            Some(fields),
            "entity {}/{:?} differs between the store dump and its last committed save",
            key.0,
            key.1
        );
    }
}

#[test]
fn discarded_saves_never_reach_the_store() {
    let discarded: Vec<Identity> = run()
        .frames
        .iter()
        .flat_map(|changes| &changes.operations)
        .filter_map(|operation| match operation.operation.as_ref() {
            Some(pb::entity_operation::Operation::Set(set))
                if set.store_disposition != pb::StoreDisposition::Committed as i32 =>
            {
                Some(wire_identity(set.key.as_ref().expect("a Set has a key")))
            }
            _ => None,
        })
        .collect();
    assert!(
        !discarded.is_empty(),
        "block 12,370,523 must contribute discarded saves, or this test proves nothing"
    );

    let committed = last_committed_sets();
    let dumped: Vec<Identity> = run().state.entities.iter().map(identity).collect();
    for key in discarded {
        if committed.contains_key(&key) {
            // Another handler wrote the same entity and did commit; the row is
            // in the store because of that write, not this one.
            continue;
        }
        assert!(
            !dumped.contains(&key),
            "discarded save {}/{:?} reached the store",
            key.0,
            key.1
        );
    }
}

#[test]
fn the_proof_of_indexing_row_is_dumped_apart_from_the_mapping_entities() {
    let state = &run().state;
    assert!(
        state
            .entities
            .iter()
            .all(|entity| entity.entity_type != POI_TYPE),
        "the proof-of-indexing entity must not be mixed into the mapping entities"
    );
    assert_eq!(state.poi_entities.len(), 1, "{:?}", state.poi_entities);

    let poi_entity = &state.poi_entities[0];
    assert_eq!(poi_entity.entity_type, POI_TYPE);
    assert_eq!(
        poi_entity.id,
        StoreEntityId::String(state.poi_causality_region.clone())
    );

    // The digest the row stores is the digest the run reported: the value that
    // chains from block to block, and the value a consumer computes for itself.
    let poi = state.poi.as_ref().expect("the fixtures open a region");
    let expected = poi
        .causality_regions
        .get(&state.poi_causality_region)
        .expect("the region the deployment declares");
    let digest = poi_entity
        .fields
        .iter()
        .find_map(|(name, value)| match (name.as_str(), value) {
            ("digest", StoreValue::Bytes(bytes)) => Some(hex::encode(bytes)),
            _ => None,
        })
        .expect("the proof-of-indexing row stores a bytes digest");
    assert_eq!(&digest, expected);
    assert_eq!(
        poi.version, "legacy",
        "spec 0.0.2 folds with the legacy hasher"
    );
}

#[test]
fn the_totals_and_counts_describe_the_rows_that_are_there() {
    let state = &run().state;
    assert_eq!(state.schema, STORE_STATE_SCHEMA);
    assert_eq!(state.deployment, SEGMENT);
    assert_eq!(state.totals.entities, state.entities.len());
    assert_eq!(state.totals.poi_entities, state.poi_entities.len());
    assert_eq!(
        state.totals.fields,
        state
            .entities
            .iter()
            .map(|entity| entity.fields.len())
            .sum::<usize>()
    );

    // `counts_by_type` covers both arrays, which is what the per-block report's
    // `store_counts` means; the last block's report must therefore agree.
    assert_eq!(state.counts_by_type, run().final_counts);
    assert_eq!(
        state.counts_by_type.values().sum::<usize>(),
        state.entities.len() + state.poi_entities.len()
    );
    let mut by_type: BTreeMap<String, usize> = BTreeMap::new();
    for entity in state.entities.iter().chain(&state.poi_entities) {
        *by_type.entry(entity.entity_type.clone()).or_default() += 1;
    }
    assert_eq!(by_type, state.counts_by_type);
}

#[test]
fn rows_are_ordered_by_storage_identity_and_fields_by_name() {
    let state = &run().state;
    let identities: Vec<Identity> = state.entities.iter().map(identity).collect();
    let mut sorted = identities.clone();
    sorted.sort();
    assert_eq!(
        identities, sorted,
        "rows must be ordered by storage identity"
    );
    assert!(
        identities.windows(2).all(|pair| pair[0] != pair[1]),
        "a storage identity must appear once"
    );

    for entity in &state.entities {
        let names: Vec<&str> = entity
            .fields
            .iter()
            .map(|(name, _)| name.as_str())
            .collect();
        let mut sorted = names.clone();
        sorted.sort_unstable();
        assert_eq!(
            names, sorted,
            "{} fields must be sorted by name",
            entity.entity_type
        );
        assert!(
            !names.contains(&"vid"),
            "the sequence-generated vid is not part of the hashed entity"
        );
    }
}

#[test]
fn the_dump_round_trips_through_its_own_json() {
    let state = &run().state;
    let json = state.to_json().expect("serialised");
    assert!(json.ends_with('\n'), "artifacts end with a newline");
    let back: StoreState = serde_json::from_str(&json).expect("deserialised");
    assert_eq!(&back, state);
    // Byte-stability: a second serialisation of the parsed value is the same
    // text, so the artifact can be pinned by digest.
    assert_eq!(back.to_json().expect("serialised"), json);
}
