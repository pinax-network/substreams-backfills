//! Independent S-R3 oracle: actual pinned Graph Node BlockState/EntityCache,
//! including handler rollback and as_modifications across block boundaries.
//! No reducer/common cache algebra is used to calculate expected state.
use graph::{
    components::{
        store::{EntityLfuCache, GetScope, SeqGenerator},
        subgraph::BlockState,
    },
    data::store::{Entity, Value},
    data::subgraph::schema::SubgraphError,
    prelude::{s, slog, DeploymentHash, MetricsRegistry, StopwatchMetrics},
    schema::InputSchema,
};
use graph_mapping_host::{blockchanges::convert_entity, store::MemoryStore};
use prost::Message;
use serde_json::json;
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}
fn image(value: Option<Arc<Entity>>) -> Option<String> {
    value.map(|e| {
        hex::encode(
            backfill_common::pb::pinax::graph::backfill::v1::EntityFields {
                fields: convert_entity(&e),
            }
            .encode_to_vec(),
        )
    })
}
fn full(schema: &InputSchema, symbol: &str, version: Option<Value>) -> Entity {
    let object = schema
        .schema()
        .document
        .definitions
        .iter()
        .find_map(|d| match d {
            s::Definition::TypeDefinition(s::TypeDefinition::Object(o)) if o.name == "Token" => {
                Some(o)
            }
            _ => None,
        })
        .unwrap();
    let mut fields = Vec::new();
    for f in &object.fields {
        if f.directives.iter().any(|d| d.name == "derivedFrom") {
            continue;
        }
        let s::Type::NonNullType(inner) = &f.field_type else {
            continue;
        };
        let value = match inner.as_ref() {
            s::Type::ListType(_) => Value::List(vec![]),
            s::Type::NamedType(name) => match name.as_str() {
                "Int" => Value::Int(0),
                "BigInt" => Value::BigInt(0.into()),
                "BigDecimal" => Value::BigDecimal(0.into()),
                "Bytes" => Value::Bytes(vec![0; 20].into()),
                _ => Value::String(
                    if f.name == "id" {
                        "t"
                    } else if f.name == "symbol" {
                        symbol
                    } else {
                        "ref"
                    }
                    .into(),
                ),
            },
            _ => unreachable!(),
        };
        fields.push((f.name.clone().into(), value));
    }
    if let Some(v) = version {
        fields.push(("version".into(), v));
    }
    schema.make_entity(fields).unwrap()
}
#[test]
fn aerodrome_state_corpus() {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(generate());
}
async fn generate() {
    let hash = DeploymentHash::new("aerodrome_state_oracle").unwrap();
    let schema = InputSchema::parse_latest(
        &std::fs::read_to_string(root().join("aerodrome-slipstream-base/reference/schema.graphql"))
            .unwrap(),
        hash.clone(),
    )
    .unwrap();
    let stopwatch = StopwatchMetrics::new(
        slog::Logger::root(slog::Discard, slog::o!()),
        hash.clone(),
        "state-corpus",
        Arc::new(MetricsRegistry::mock()),
        "hermetic".into(),
    );
    let mut cases = Vec::new();
    let mut rng = 0xa3e0_d00du64;
    for case in 0..64 {
        let store = Arc::new(MemoryStore::new(schema.clone()));
        let key = schema.entity_type("Token").unwrap().parse_key("t").unwrap();
        let initial = if case % 2 == 1 {
            Some(full(&schema, "seed", Some(Value::Int(7))))
        } else {
            None
        };
        if let Some(e) = &initial {
            store.restore(BTreeMap::from([(key.clone(), e.clone())]));
        }
        let initial_wire = image(initial.map(Arc::new));
        let mut lfu = EntityLfuCache::new();
        let mut blocks = Vec::new();
        for block in 0..3 {
            let mut state = BlockState::new(store.clone(), lfu, SeqGenerator::new(block));
            let mut handlers = Vec::new();
            for handler in 0..4 {
                let before = image(state.entity_cache.get(&key, GetScope::Store).await.unwrap());
                state.enter_handler();
                let mut actions = Vec::new();
                for action in 0..4 {
                    rng ^= rng << 13;
                    rng ^= rng >> 7;
                    rng ^= rng << 17;
                    let current = state.entity_cache.get(&key, GetScope::Store).await.unwrap();
                    let selected = if current.is_none() { rng % 3 } else { rng % 7 };
                    let mut fields = None;
                    if selected == 6 {
                        state.entity_cache.remove(key.clone());
                    } else {
                        let data = match selected {
                            0 => full(&schema, &format!("{case}-{block}-{handler}-{action}"), None),
                            1 => full(&schema, "full-null", Some(Value::Null)),
                            2 => full(&schema, "full-value", Some(Value::Int(2))),
                            3 => schema
                                .make_entity(vec![
                                    ("id".into(), "t".into()),
                                    ("version".into(), Value::Null),
                                ])
                                .unwrap(),
                            4 => schema
                                .make_entity(vec![
                                    ("id".into(), "t".into()),
                                    ("version".into(), Value::Int(3)),
                                ])
                                .unwrap(),
                            5 => schema
                                .make_entity(vec![
                                    ("id".into(), Value::String("t".into())),
                                    ("symbol".into(), Value::String("partial".into())),
                                ])
                                .unwrap(),
                            _ => unreachable!(),
                        };
                        fields = image(Some(Arc::new(data.clone())));
                        state
                            .entity_cache
                            .set(key.clone(), data, None)
                            .await
                            .unwrap();
                    }
                    let visible =
                        image(state.entity_cache.get(&key, GetScope::Store).await.unwrap());
                    actions.push(json!({"fields":fields,"visible":visible}));
                }
                let abort = (case + block + handler) % 4 == 0;
                if abort {
                    state.exit_handler_and_discard_changes_due_to_error(SubgraphError {
                        subgraph_id: hash.clone(),
                        message: "synthetic".into(),
                        deterministic: true,
                        ..Default::default()
                    });
                } else {
                    state.exit_handler();
                }
                let after = image(state.entity_cache.get(&key, GetScope::Store).await.unwrap());
                handlers
                    .push(json!({"before":before,"actions":actions,"abort":abort,"after":after}));
            }
            let mods = state
                .entity_cache
                .as_modifications(block, &stopwatch)
                .await
                .unwrap();
            store.apply(&mods.modifications);
            lfu = mods.entity_lfu_cache;
            let final_image = image(store.lookup(&key).map(Arc::new));
            blocks.push(json!({"handlers":handlers,"final":final_image}));
        }
        cases.push(json!({"initial":initial_wire,"blocks":blocks}));
    }
    // Intern identical wire images to keep the checked-in corpus small.
    fn intern(
        value: &mut serde_json::Value,
        images: &mut Vec<String>,
        ids: &mut BTreeMap<String, usize>,
    ) {
        match value {
            serde_json::Value::String(wire) => {
                let id = if let Some(id) = ids.get(wire) {
                    *id
                } else {
                    let id = images.len();
                    images.push(wire.clone());
                    ids.insert(wire.clone(), id);
                    id
                };
                *value = json!(id);
            }
            serde_json::Value::Array(values) => {
                for v in values {
                    intern(v, images, ids)
                }
            }
            serde_json::Value::Object(values) => {
                for v in values.values_mut() {
                    intern(v, images, ids)
                }
            }
            _ => (),
        }
    }
    let mut images = Vec::new();
    let mut ids = BTreeMap::new();
    for case in &mut cases {
        intern(case, &mut images, &mut ids);
    }
    let corpus = json!({"schema":"pinax.aerodrome.reducer-entity-cache/v1","graph_node_commit":"77823b5a7adc4eac4abf03202c8dd7cb00dea31d","images":images,"cases":cases});
    let bytes = format!("{}\n", serde_json::to_string_pretty(&corpus).unwrap());
    let path = root().join("crates/aerodrome-slipstream-reducer/fixtures/graph-node-state.json");
    if std::env::var_os("UPDATE_AERODROME_STATE_CORPUS").as_deref()
        == Some(std::ffi::OsStr::new("1"))
    {
        std::fs::write(&path, &bytes).unwrap();
    }
    assert_eq!(
        std::fs::read_to_string(path).unwrap(),
        bytes,
        "Graph Node state corpus drift; investigate before regeneration"
    );
}
