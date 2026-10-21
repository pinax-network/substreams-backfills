use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    handlers::SupportedHandler,
    hosts::HostSet,
    identity::{build_descriptor, InputBinding, OUTPUT_MODULE, OUTPUT_TYPE},
    input::validate_block,
    pb,
    state::{BlockStore, EntityBackend, HandlerStatus, Key, MemoryBackend, SealedBlock},
};
use backfill_common::{
    clock::{Frame, FrameKind},
    descriptor::ExtractorIdentity,
    pb::pinax::graph::backfill::v2 as output,
    state_snapshot::Boundary,
};
use prost::Message;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

// Oracle checkpoints carry cache images, including explicit Null. Keep the
// production DB seed validator strict; this read-only backend supplies the
// actual oracle cache image while delegating identity/source validation.
struct OracleSeed {
    database: MemoryBackend,
    cache: BTreeMap<Key, Vec<output::EntityField>>,
}
impl EntityBackend for OracleSeed {
    fn boundary(&self) -> &Boundary {
        self.database.boundary()
    }
    fn compatibility_id(&self) -> [u8; 32] {
        self.database.compatibility_id()
    }
    fn get(
        &self,
        key: &Key,
    ) -> aerodrome_slipstream_reducer::Result<Option<Vec<output::EntityField>>> {
        Ok(self.cache.get(key).cloned())
    }
    fn has_source(&self, pool: &aerodrome_slipstream_reducer::Address) -> bool {
        self.database.has_source(pool)
    }
    fn commit(&mut self, _: SealedBlock) -> aerodrome_slipstream_reducer::Result<()> {
        Err(aerodrome_slipstream_reducer::ReducerError(
            "read-only oracle fixture backend".into(),
        ))
    }
}

pub fn original() -> pb::ExtractorBlock {
    pb::ExtractorBlock::decode(include_bytes!("../../fixtures/first-pool-extractor.pb").as_slice())
        .unwrap()
}
fn binding() -> InputBinding {
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let bytes = build_descriptor(&extractor, &"33".repeat(20), true).unwrap();
    InputBinding::new(&bytes, Sha256::digest(&bytes).into(), &extractor).unwrap()
}
pub fn run_seeded(
    b: &pb::ExtractorBlock,
    indexes: &[usize],
    seed: &[Value],
) -> output::BlockChanges {
    let binding = binding();
    let input = validate_block(
        &Frame {
            kind: FrameKind::Observed,
            block_number: b.number,
            block_hash: b.hash.clone().try_into().unwrap(),
            payload: b.encode_to_vec(),
        },
        b.parent_hash.clone().try_into().unwrap(),
    )
    .unwrap();
    let mut backend = MemoryBackend::from_images(
        &binding,
        Boundary {
            block_number: b.number - 1,
            block_hash: b.parent_hash.clone().try_into().unwrap(),
        },
        BTreeMap::new(),
        BTreeMap::new(),
    )
    .unwrap();
    let mut hosts = HostSet::default();
    let mut cache = BTreeMap::new();
    if !seed.is_empty() {
        let mut rows = BTreeMap::new();
        for value in seed {
            let bytes = hex::decode(value.as_str().unwrap()).unwrap();
            let image = output::SetEntity::decode(bytes.as_slice()).unwrap();
            let key = image.key.unwrap();
            let Some(output::entity_id::Value::String(id)) = key.id.unwrap().value else {
                panic!("string id")
            };
            rows.insert(
                aerodrome_slipstream_reducer::state::Key::new(&key.entity_type, &id),
                image.written_fields,
            );
        }
        let original = original();
        let pool = original.pools_created[0].pool.clone().try_into().unwrap();
        let boundary = Boundary {
            block_number: original.number,
            block_hash: original.hash.try_into().unwrap(),
        };
        cache = rows.clone();
        for fields in rows.values_mut() {
            fields.retain(|f| !backfill_common::field_is_null(f));
        }
        backend = MemoryBackend::from_images(
            &binding,
            boundary.clone(),
            rows,
            BTreeMap::from([(pool, boundary)]),
        )
        .unwrap();
        hosts.seed(pool, original.number, original.number).unwrap();
    }

    let backend = OracleSeed {
        database: backend,
        cache,
    };
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    for &index in indexes {
        let Some(handler) = SupportedHandler::match_candidate(&input, &hosts, index).unwrap()
        else {
            continue;
        };
        let mut created = None;
        let status = store
            .run_handler(handler.source_trigger_order(), |journal| {
                created = handler.run(journal)?;
                Ok(())
            })
            .unwrap();
        if let Some(pool) = created {
            assert_eq!(status, HandlerStatus::Committed);
            hosts.record_creation_outcome(&input, pool, true).unwrap();
        }
    }
    let mut result = store.seal().unwrap().changes().clone();
    result.compatibility_id.clear();
    result
}
