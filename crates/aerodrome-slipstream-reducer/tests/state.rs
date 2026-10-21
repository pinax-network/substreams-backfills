use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    entity::{self, Entity, EntityClass, Presence, Scalar, ALL_ENTITIES},
    identity::{build_descriptor, InputBinding, OUTPUT_MODULE, OUTPUT_TYPE},
    input::{validate_block, BlockInput},
    pb as extractor,
    state::{Abort, BlockStore, EntityBackend, HandlerStatus, Key, MemoryBackend, Step},
};
use backfill_common::{
    clock::{Frame, FrameKind},
    descriptor::ExtractorIdentity,
    pb::pinax::graph::backfill::v1 as pb,
    state_snapshot::Boundary,
};
use graph_numerics::{BigInt, GraphDecimal};
use graphql_parser::schema::{parse_schema, Definition, TypeDefinition};
use pb::graph_value::Kind;
use prost::Message;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
fn binding(fatal: bool) -> InputBinding {
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let bytes = build_descriptor(&extractor, &"33".repeat(20), !fatal).unwrap();
    InputBinding::new(&bytes, Sha256::digest(&bytes).into(), &extractor).unwrap()
}
fn input(number: u64, parent: u8, hash: u8) -> BlockInput {
    let b = extractor::ExtractorBlock {
        number,
        hash: vec![hash; 32],
        parent_hash: vec![parent; 32],
        timestamp: 1700000000 + number,
        contract: aerodrome_extractor_core::config::CONTRACT.into(),
        firehose_block_version: 5,
        audit: Some(Default::default()),
        calls: Some(Default::default()),
        ..Default::default()
    };
    validate_block(
        &Frame {
            kind: FrameKind::Observed,
            block_number: number,
            block_hash: [hash; 32],
            payload: b.encode_to_vec(),
        },
        [parent; 32],
    )
    .unwrap()
}
fn field(name: &str, kind: Kind) -> pb::EntityField {
    pb::EntityField {
        name: name.into(),
        value: Some(pb::GraphValue { kind: Some(kind) }),
    }
}
fn str_field(name: &str, v: &str) -> pb::EntityField {
    field(name, Kind::String(v.into()))
}
fn null(name: &str) -> pb::EntityField {
    field(name, Kind::Null(pb::NullValue {}))
}
fn sample(name: &str, id: &str) -> Vec<pb::EntityField> {
    entity::definition(name)
        .unwrap()
        .fields
        .iter()
        .filter(|f| f.graphql_type.ends_with('!'))
        .map(|f| {
            field(
                f.name,
                match f.graphql_type {
                    "Int!" => Kind::Int(0),
                    "BigInt!" => BigInt::from(0).encode().unwrap(),
                    "BigDecimal!" => GraphDecimal::zero().encode().unwrap(),
                    "Bytes!" => Kind::Bytes(vec![0; 20]),
                    "[Pool!]!" => Kind::List(pb::ListValue { values: vec![] }),
                    _ => Kind::String(if f.name == "id" { id } else { "ref" }.into()),
                },
            )
        })
        .collect()
}
fn version(fields: &[pb::EntityField]) -> Option<&Kind> {
    fields
        .iter()
        .find(|f| f.name == "version")
        .and_then(|f| f.value.as_ref()?.kind.as_ref())
}
#[test]
fn declarations_match_every_locked_schema_field_and_nullability() {
    let source = include_str!("../../../aerodrome-slipstream-base/reference/schema.graphql");
    let schema = parse_schema::<String>(source).unwrap();
    let (mut total, mut derived, mut stored) = (0, 0, 0);
    let mut names = vec![];
    for d in schema.definitions {
        if let Definition::TypeDefinition(TypeDefinition::Object(o)) = d {
            if !o.directives.iter().any(|d| d.name == "entity") {
                continue;
            }
            names.push(o.name.clone());
            let def = entity::definition(&o.name).unwrap();
            let mut actual = BTreeMap::new();
            for f in o.fields {
                total += 1;
                if f.directives.iter().any(|d| d.name == "derivedFrom") {
                    derived += 1;
                    continue;
                }
                stored += 1;
                actual.insert(f.name, f.field_type.to_string());
            }
            assert_eq!(
                actual,
                def.fields
                    .iter()
                    .map(|f| (f.name.into(), f.graphql_type.into()))
                    .collect()
            );
        }
    }
    names.sort();
    assert_eq!((total, stored, derived), (302, 289, 13));
    assert_eq!(
        names,
        ALL_ENTITIES.iter().map(|d| d.name).collect::<Vec<_>>()
    );
    for d in ALL_ENTITIES {
        assert_eq!(
            d.class == EntityClass::NeverWritten,
            matches!(d.name, "Collect" | "Flash" | "TickHourData")
        );
    }
}
#[test]
fn all_twenty_typed_objects_roundtrip_and_optional_presence_is_distinct() {
    fn check<E: Entity>() {
        let f = sample(E::DEF.name, "x");
        assert_eq!(E::from_fields(&f).unwrap().to_fields().unwrap(), f);
    }
    check::<entity::Factory>();
    check::<entity::Bundle>();
    check::<entity::Token>();
    check::<entity::Pool>();
    check::<entity::Tick>();
    check::<entity::Position>();
    check::<entity::PositionSnapshot>();
    check::<entity::Transaction>();
    check::<entity::Mint>();
    check::<entity::Burn>();
    check::<entity::Swap>();
    check::<entity::Collect>();
    check::<entity::Flash>();
    check::<entity::UniswapDayData>();
    check::<entity::PoolDayData>();
    check::<entity::PoolHourData>();
    check::<entity::TickHourData>();
    check::<entity::TickDayData>();
    check::<entity::TokenDayData>();
    check::<entity::TokenHourData>();
    let mut t = entity::Token::from_fields(&sample("Token", "t")).unwrap();
    assert_eq!(t.version, Presence::Absent);
    t.version = Presence::Null;
    assert!(matches!(
        version(&t.to_fields().unwrap()),
        Some(Kind::Null(_))
    ));
    t.version = Presence::Set(2);
    assert_eq!(version(&t.to_fields().unwrap()), Some(&Kind::Int(2)));
    t.symbol = "A\0B".into();
    assert_eq!(
        entity::Token::from_fields(&t.to_fields().unwrap())
            .unwrap()
            .symbol,
        "AB"
    );
}
#[test]
fn fields_reject_unknown_derived_wrong_types_nulls_duplicates_and_nonfixed_decimals() {
    let original = sample("Token", "t");
    for bad in [
        str_field("unknown", "x"),
        str_field("tokenDayData", "x"),
        field("decimals", Kind::Int(18)),
        null("symbol"),
        str_field("id", "other"),
    ] {
        let mut f = original.clone();
        f.retain(|f| f.name != bad.name);
        f.push(bad);
        f.sort_by(|a, b| a.name.cmp(&b.name));
        assert!(entity::validate_fields("Token", "t", &f, true).is_err());
    }
    let mut f = original.clone();
    f.push(f[0].clone());
    assert!(entity::Token::from_fields(&f).is_err());
    let mut t = entity::Token::from_fields(&original).unwrap();
    let n = -(BigInt::from(1) << 116usize) * BigInt::from(1000);
    t.volume = GraphDecimal::from_bigint(&n).unwrap();
    assert!(!t.volume.is_fixed_point());
    assert!(t.to_fields().is_err());
}
#[test]
fn owned_loads_partial_updates_abort_and_sources_are_atomic() {
    let binding = binding(false);
    let mut backend = MemoryBackend::root(&binding, [1; 32]).unwrap();
    let block = input(INITIAL_BLOCK, 1, 2);
    let mut store = BlockStore::begin(&backend, &binding, &block).unwrap();
    store
        .run_handler(10, |h| {
            h.save_fields("Token", "t", &sample("Token", "t"))?;
            let mut t = h.load::<entity::Token>("t")?.unwrap();
            t.symbol = "not saved".into();
            assert_ne!(h.load::<entity::Token>("t")?.unwrap().symbol, t.symbol);
            h.save_fields("Token", "t", &[field("version", Kind::Int(1))])?;
            assert_eq!(
                h.load::<entity::Token>("t")?.unwrap().version,
                Presence::Set(1)
            );
            assert!(h.create_pool_source([3; 20])?);
            assert!(!h.create_pool_source([3; 20])?);
            Ok(())
        })
        .unwrap();
    let status = store
        .run_handler(11, |h| {
            h.save_fields("Token", "t", &[field("version", Kind::Int(99))])?;
            h.create_pool_source([4; 20])?;
            h.remove::<entity::Token>("t")?;
            assert!(h.load::<entity::Token>("t")?.is_none());
            Err(Step::Abort(Abort {
                message: "synthetic".into(),
            }))
        })
        .unwrap();
    assert!(matches!(status, HandlerStatus::Aborted(_)));
    store
        .run_handler(1, |h| {
            assert_eq!(
                h.load::<entity::Token>("t")?.unwrap().version,
                Presence::Set(1)
            );
            Ok(())
        })
        .unwrap();
    let sealed = store.seal().unwrap();
    assert_eq!(sealed.changes().created_data_sources.len(), 1);
    assert_eq!(
        sealed.changes().created_data_sources[0].handler_group_order,
        0
    );
    assert_eq!(sealed.changes().operations.len(), 5);
    for (idx, op) in sealed.changes().operations.iter().enumerate() {
        assert_eq!(op.operation_index, idx as u64);
    }
    assert!(
        matches!(sealed.changes().operations[2].operation,Some(pb::entity_operation::Operation::Set(ref s)) if s.store_disposition==pb::StoreDisposition::Discarded as i32)
    );
    backend.commit(sealed).unwrap();
    assert_eq!(backend.sources().len(), 1);
    assert_eq!(
        version(&backend.rows()[&Key::new("Token", "t")]),
        Some(&Kind::Int(1))
    );
}
#[test]
fn null_cache_finalization_distinguishes_insert_update_and_existing_recreate() {
    let binding = binding(false);
    let mut backend = MemoryBackend::root(&binding, [1; 32]).unwrap();
    for step in 0..3 {
        let block = input(INITIAL_BLOCK + step, step as u8 + 1, step as u8 + 2);
        let mut store = BlockStore::begin(&backend, &binding, &block).unwrap();
        store
            .run_handler(0, |h| {
                if step == 2 {
                    h.remove::<entity::Token>("t")?;
                }
                let mut fields = if step == 1 {
                    vec![]
                } else {
                    sample("Token", "t")
                };
                fields.push(null("version"));
                h.save_fields("Token", "t", &fields)?;
                assert_eq!(
                    h.load::<entity::Token>("t")?.unwrap().version,
                    if step == 1 {
                        Presence::Absent
                    } else {
                        Presence::Null
                    }
                );
                Ok(())
            })
            .unwrap();
        let sealed = store.seal().unwrap();
        backend.commit(sealed).unwrap();
        assert_eq!(
            version(&backend.rows()[&Key::new("Token", "t")]).is_some(),
            step == 2
        );
    }
    assert!(version(&backend.database_rows()[&Key::new("Token", "t")]).is_none());
}
#[test]
fn sealing_requires_valid_identity_and_commits_only_the_expected_boundary() {
    let binding = binding(false);
    let mut backend = MemoryBackend::root(&binding, [1; 32]).unwrap();
    let input = input(INITIAL_BLOCK, 1, 2);
    let mut a = BlockStore::begin(&backend, &binding, &input).unwrap();
    a.run_handler(4, |_| Ok(())).unwrap();
    let first = a.seal().unwrap();
    assert!(first.changes().mapping_triggered);
    assert!(first.changes().operations.is_empty());
    let second = BlockStore::begin(&backend, &binding, &input)
        .unwrap()
        .seal()
        .unwrap();
    let mut wire = vec![];
    first.write_to(&mut wire).unwrap();
    let read = backfill_common::clock::read_frame(
        &mut wire.as_slice(),
        backfill_common::clock::MAX_PAYLOAD_LEN,
    )
    .unwrap()
    .unwrap();
    assert_eq!(&read, first.frame());
    let decoded = backfill_common::decode_canonical_in_band_block_changes(
        &read.payload,
        binding.compatibility(),
    )
    .unwrap();
    assert_eq!(&decoded, first.changes());
    backend.commit(first).unwrap();
    assert!(backend.commit(second).is_err());
    let bad_binding = binding_for_other_hash();
    assert!(BlockStore::begin(&backend, &bad_binding, &input).is_err());
}
fn binding_for_other_hash() -> InputBinding {
    let extractor = ExtractorIdentity {
        spkg_sha256: "44".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let b = build_descriptor(&extractor, &"33".repeat(20), true).unwrap();
    InputBinding::new(&b, Sha256::digest(&b).into(), &extractor).unwrap()
}
#[test]
fn fatal_error_invalid_save_ignored_error_and_unwind_never_commit() {
    let binding = binding(true);
    let mut backend = MemoryBackend::root(&binding, [1; 32]).unwrap();
    let input = input(INITIAL_BLOCK, 1, 2);
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    store
        .run_handler(0, |h| {
            h.save_fields("Bundle", "1", &sample("Bundle", "1"))?;
            h.create_pool_source([2; 20])?;
            Ok(())
        })
        .unwrap();
    store
        .run_handler(1, |_| {
            Err(Step::Abort(Abort {
                message: "error".into(),
            }))
        })
        .unwrap();
    let sealed = store.seal().unwrap();
    assert!(!sealed.committable());
    assert!(sealed.changes().created_data_sources.is_empty());
    assert!(backend.commit(sealed).is_err());
    assert!(backend.rows().is_empty());
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    assert!(store
        .run_handler(0, |h| {
            let _ = h.save_fields("Bundle", "1", &[]);
            Ok(())
        })
        .is_err());
    assert!(store.seal().is_err());
    let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        store.run_handler(0, |_| panic!("synthetic unwind"))
    }));
    assert!(result.is_err());
    assert!(store.seal().is_err());
}
#[test]
fn never_written_types_refuse_and_block_local_rows_are_retained_conservatively() {
    let binding = binding(false);
    let mut backend = MemoryBackend::root(&binding, [1; 32]).unwrap();
    let block = input(INITIAL_BLOCK, 1, 2);
    for name in ["Collect", "Flash", "TickHourData"] {
        let mut s = BlockStore::begin(&backend, &binding, &block).unwrap();
        assert!(s
            .run_handler(0, |h| {
                h.save_fields(name, "x", &sample(name, "x"))?;
                Ok(())
            })
            .is_err());
        assert!(s.seal().is_err());
    }
    let mut s = BlockStore::begin(&backend, &binding, &block).unwrap();
    s.run_handler(0, |h| {
        h.save_fields("Transaction", "tx", &sample("Transaction", "tx"))?;
        Ok(())
    })
    .unwrap();
    backend.commit(s.seal().unwrap()).unwrap();
    assert!(backend.rows().contains_key(&Key::new("Transaction", "tx")));
}
#[test]
fn mapping_host_descriptor_is_not_accepted_as_native_input() {
    let b = binding(false);
    let _ = b; // Exercise the alternative enum with an independently rehashed descriptor.
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let bytes = build_descriptor(&extractor, &"33".repeat(20), true).unwrap();
    let mut v: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    v["producer_contract"] = serde_json::json!({"kind":"mapping_host_oracle","repository":"pinax-network/substreams-backfills","source_closure_sha256":"44".repeat(32),"bundle_lock_sha256":"55".repeat(32)});
    let bytes = serde_json::to_vec(&v).unwrap();
    assert!(InputBinding::new(&bytes, Sha256::digest(&bytes).into(), &extractor).is_err());
}

#[test]
fn every_cache_read_and_block_boundary_matches_actual_graph_node() {
    let corpus: serde_json::Value =
        serde_json::from_str(include_str!("../fixtures/graph-node-state.json")).unwrap();
    assert_eq!(corpus["schema"], "pinax.aerodrome.reducer-entity-cache/v1");
    assert_eq!(
        corpus["graph_node_commit"],
        "77823b5a7adc4eac4abf03202c8dd7cb00dea31d"
    );
    let images: Vec<Vec<pb::EntityField>> = corpus["images"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| {
            pb::EntityFields::decode(hex::decode(v.as_str().unwrap()).unwrap().as_slice())
                .unwrap()
                .fields
        })
        .collect();
    let image = |v: &serde_json::Value| v.as_u64().map(|n| images[n as usize].clone());
    let binding = binding(false);
    let mut reads = 0;
    for (case_idx, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let mut backend = MemoryBackend::from_images(
            &binding,
            Boundary {
                block_number: INITIAL_BLOCK - 1,
                block_hash: [1; 32],
            },
            image(&case["initial"])
                .map(|fields| (Key::new("Token", "t"), fields))
                .into_iter()
                .collect(),
            BTreeMap::new(),
        )
        .unwrap();
        for (block_idx, block) in case["blocks"].as_array().unwrap().iter().enumerate() {
            let input = input(
                INITIAL_BLOCK + block_idx as u64,
                block_idx as u8 + 1,
                block_idx as u8 + 2,
            );
            let mut store = BlockStore::begin(&backend, &binding, &input).unwrap();
            for (handler_idx, handler) in block["handlers"].as_array().unwrap().iter().enumerate() {
                let location = format!("case {case_idx} block {block_idx} handler {handler_idx}");
                assert_eq!(
                    store.visible_fields("Token", "t").unwrap(),
                    image(&handler["before"]),
                    "before {location}"
                );
                store
                    .run_handler(handler_idx as u64, |journal| {
                        for (action_idx, action) in
                            handler["actions"].as_array().unwrap().iter().enumerate()
                        {
                            match image(&action["fields"]) {
                                Some(fields) => journal.save_fields("Token", "t", &fields)?,
                                None => journal.remove::<entity::Token>("t")?,
                            }
                            assert_eq!(
                                journal.load_fields("Token", "t")?,
                                image(&action["visible"]),
                                "{location} action {action_idx}"
                            );
                            reads += 1;
                        }
                        if handler["abort"].as_bool().unwrap() {
                            Err(Step::Abort(Abort {
                                message: "synthetic".into(),
                            }))
                        } else {
                            Ok(())
                        }
                    })
                    .unwrap();
                assert_eq!(
                    store.visible_fields("Token", "t").unwrap(),
                    image(&handler["after"]),
                    "after {location}"
                );
                reads += 2;
            }
            backend.commit(store.seal().unwrap()).unwrap();
            assert_eq!(
                backend.get(&Key::new("Token", "t")).unwrap(),
                image(&block["final"]),
                "final case {case_idx} block {block_idx}"
            );
            reads += 1;
        }
    }
    assert_eq!(reads, 4800);
}

#[test]
fn sealed_read_set_cannot_be_applied_to_a_different_seed_and_writer_failure_is_inert() {
    let binding = binding(false);
    let mut backend = MemoryBackend::root(&binding, [1; 32]).unwrap();
    let block = input(INITIAL_BLOCK, 1, 2);
    let mut store = BlockStore::begin(&backend, &binding, &block).unwrap();
    store
        .run_handler(0, |h| {
            h.save_fields("Token", "t", &sample("Token", "t"))?;
            h.create_pool_source([3; 20])?;
            Ok(())
        })
        .unwrap();
    let sealed = store.seal().unwrap();
    struct FailingWriter;
    impl std::io::Write for FailingWriter {
        fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
            Err(std::io::Error::other("synthetic failure"))
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    assert!(sealed.write_to(&mut FailingWriter).is_err());
    assert!(backend.rows().is_empty());
    assert!(backend.sources().is_empty());
    assert_eq!(backend.boundary().block_number, INITIAL_BLOCK - 1);
    let mut different_seed = MemoryBackend::from_images(
        &binding,
        backend.boundary().clone(),
        BTreeMap::from([(Key::new("Token", "t"), sample("Token", "t"))]),
        BTreeMap::new(),
    )
    .unwrap();
    assert!(different_seed.commit(sealed).is_err());
    assert!(different_seed.sources().is_empty());
    assert_eq!(different_seed.boundary().block_number, INITIAL_BLOCK - 1);
    // A failed write did not prevent a fresh block from being constructed.
    let sealed = BlockStore::begin(&backend, &binding, &block)
        .unwrap()
        .seal()
        .unwrap();
    backend.commit(sealed).unwrap();
}

#[test]
fn source_deduplication_reads_are_bound_to_the_sealed_state() {
    let binding = binding(false);
    let boundary = Boundary {
        block_number: INITIAL_BLOCK,
        block_hash: [2; 32],
    };
    let pool = [3; 20];
    let seeded = MemoryBackend::from_images(
        &binding,
        boundary.clone(),
        BTreeMap::new(),
        BTreeMap::from([(pool, boundary.clone())]),
    )
    .unwrap();
    let mut other =
        MemoryBackend::from_images(&binding, boundary, BTreeMap::new(), BTreeMap::new()).unwrap();
    let input = input(INITIAL_BLOCK + 1, 2, 4);
    let mut store = BlockStore::begin(&seeded, &binding, &input).unwrap();
    store
        .run_handler(0, |h| {
            assert!(!h.create_pool_source(pool)?);
            Ok(())
        })
        .unwrap();
    assert!(other.commit(store.seal().unwrap()).is_err());
    assert_eq!(other.boundary().block_number, INITIAL_BLOCK);
}
