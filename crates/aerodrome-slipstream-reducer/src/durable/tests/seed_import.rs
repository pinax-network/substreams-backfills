use super::*;
use backfill_common::{
    pb::pinax::graph::backfill::v1::{graph_value::Kind, EntityField, GraphValue, NullValue},
    producer_checkpoint::SnapshotPurpose,
    state_snapshot::{
        self as snap, SnapshotHeader, SnapshotOrigin, SnapshotRecord, SnapshotWriter,
    },
};

const CAPTURE_MANIFEST: &[u8] =
    br#"{"fixture":"synthetic capture provenance, not E5 certification"}"#;

#[test]
fn every_distinct_committed_actual_graph_node_cache_image_imports_losslessly() {
    let corpus: serde_json::Value =
        serde_json::from_str(include_str!("../../../fixtures/graph-node-state.json")).unwrap();
    assert_eq!(
        corpus["graph_node_commit"],
        "77823b5a7adc4eac4abf03202c8dd7cb00dea31d"
    );
    let indices = corpus["cases"]
        .as_array()
        .unwrap()
        .iter()
        .flat_map(|c| c["blocks"].as_array().unwrap())
        .filter_map(|b| b["final"].as_u64())
        .collect::<std::collections::BTreeSet<_>>();
    assert!(!indices.is_empty());
    let t = tempfile::tempdir().unwrap();
    let mut null_images = 0;
    for index in indices {
        let fields = EntityFields::decode(
            hex::decode(corpus["images"][index as usize].as_str().unwrap())
                .unwrap()
                .as_slice(),
        )
        .unwrap()
        .fields;
        null_images += usize::from(fields.iter().any(backfill_common::field_is_null));
        let (mut h, _) = fixture();
        h.records = 1;
        h.entity_count = Some(1);
        h.sources = snap::SourceSnapshot::from_rows(vec![]).unwrap();
        let record = SnapshotRecord::from_entity(
            &h.binding,
            &entity::key("Token", "t"),
            &snap::StoredEntity {
                vid: 1,
                block_range_start: h.boundary.block_number as i32,
                fields: fields.clone(),
            },
        )
        .unwrap();
        let data = encode(h.clone(), &[record]);
        let root = t.path().join(index.to_string());
        let s = import(&root, &data, pins(&h, &data)).unwrap();
        let segment = begin(&s, &h.boundary.block_hash);
        assert_eq!(
            segment.get(&Key::new("Token", "t")).unwrap(),
            Some(fields),
            "actual Graph Node committed image {index}"
        );
    }
    assert!(null_images > 0);
}

fn fixture() -> (SnapshotHeader, Vec<SnapshotRecord>) {
    let b = first();
    let mut memory = MemoryRunner::new(
        bindings().0,
        MemoryBackend::root(&bindings().0, b.parent_hash.clone().try_into().unwrap()).unwrap(),
    )
    .unwrap();
    memory
        .process(&validate_block(&frame(&b), b.parent_hash.clone().try_into().unwrap()).unwrap())
        .unwrap();
    let binding = seed::snapshot_binding(&bindings().0);
    let rows = memory.backend().rows();
    let records = rows
        .iter()
        .map(|(key, fields)| {
            SnapshotRecord::from_entity(
                &binding,
                &entity::key(&key.entity_type, &key.id),
                &snap::StoredEntity {
                    vid: 4,
                    block_range_start: b.number as i32,
                    fields: fields.clone(),
                },
            )
            .unwrap()
        })
        .collect::<Vec<_>>();
    let sources = memory
        .backend()
        .sources()
        .keys()
        .map(|pool| snap::SnapshotSource {
            vid: 41,
            creation_block: b.number as i32,
            manifest_idx: 2,
            param: pool.to_vec(),
        })
        .collect();
    let boundary = Boundary {
        block_number: b.number,
        block_hash: b.hash.try_into().unwrap(),
    };
    let header = SnapshotHeader {
        format: snap::FORMAT.into(),
        version: snap::VERSION,
        vid: Some(snap::VidState {
            tables: binding
                .type_ordinals
                .iter()
                .map(|name| snap::TableVid {
                    entity_type: name.clone(),
                    postgres_table: name.to_lowercase(),
                    max_vid: 4,
                    sequence_last_value: 5,
                    sequence_is_called: false,
                    active_rows: None,
                })
                .collect(),
        }),
        origin: SnapshotOrigin::Landing {
            seed: snap::SeedOrigin {
                schema: "sgd_fixture".into(),
                site_id: 7,
                database: "fixture".into(),
                system_identifier: "fixture-system".into(),
                server_version_num: 170000,
                capture_tool_sha256: "08".repeat(32),
                profile_sha256: "07".repeat(32),
                head: boundary.clone(),
                health: "healthy".into(),
                non_fatal_errors: vec![],
            },
        },
        binding,
        boundary,
        poi: Default::default(),
        sources: snap::SourceSnapshot::from_rows(sources).unwrap(),
        period_max: BTreeMap::new(),
        entity_count: Some(rows.len() as i64),
        records: records.len() as u64,
    };
    (header, records)
}
fn encode(header: SnapshotHeader, records: &[SnapshotRecord]) -> Vec<u8> {
    let mut writer = SnapshotWriter::new(Vec::new(), header, snap::Limits::default()).unwrap();
    for r in records {
        writer.write_record(r).unwrap();
    }
    writer.finish().unwrap().0
}
fn pins(header: &SnapshotHeader, bytes: &[u8]) -> SeedImportPins {
    let sha = Sha256::digest(bytes).into();
    SeedImportPins {
        snapshot_sha256: sha,
        seed_manifest_sha256: Sha256::digest(CAPTURE_MANIFEST).into(),
        profile_sha256: [7; 32],
        boundary: header.boundary.clone(),
        purpose: if matches!(header.origin, SnapshotOrigin::Oracle { .. }) {
            SnapshotPurpose::Oracle
        } else {
            SnapshotPurpose::Landing
        },
        source_history: SourceHistoryAssertion::CompleteSuccessfulSourcesNoFailedHosts,
        engine_lineage: snap::initial_lineage(sha),
    }
}
fn import(root: &Path, bytes: &[u8], pins: SeedImportPins) -> Result<DurableStore> {
    let (b, p) = bindings();
    DurableStore::import_snapshot(
        root,
        &b,
        p,
        Cursor::new(bytes),
        CAPTURE_MANIFEST,
        pins,
        1024 * 1024,
    )
}
fn assert_uninitialized(root: &Path) {
    let (b, p) = bindings();
    assert!(DurableStore::open(root, &b, p, 1024 * 1024).is_err());
    assert!(!root.join("seed-import.json").exists());
    assert!(!root.join("seed-manifest.bin").exists());
    if root.join("checkpoints").exists() {
        assert_eq!(fs::read_dir(root.join("checkpoints")).unwrap().count(), 0);
    }
}
fn initialized() -> pb::ExtractorBlock {
    let mut b = pb::ExtractorBlock::decode(
        include_bytes!("../../../fixtures/first-pool-extractor.pb").as_slice(),
    )
    .unwrap();
    b.number = INITIAL_BLOCK + 1;
    b.parent_hash = first().hash;
    b.hash = vec![91; 32];
    b.candidates.retain(|c| {
        crate::abi::Abis::locked()
            .decode(c)
            .unwrap()
            .is_some_and(|event| event.name == "Initialize")
    });
    assert_eq!(b.candidates.len(), 1);
    b.candidates[0].wave = 0;
    b.candidates[0].host_order_key = 2 + INITIAL_BLOCK * (1 << 24);
    b.pools_created.clear();
    b.calls = Some(Default::default());
    b
}

#[test]
fn import_matches_uninterrupted_logical_state_and_seeded_handler_frames() {
    let t = tempfile::tempdir().unwrap();
    let (h, records) = fixture();
    let bytes = encode(h.clone(), &records);
    let source = store(&t.path().join("source"));
    let first_manifest = run(&source, &[first()], &t.path().join("first"));
    let root = t.path().join("seeded");
    let seeded = import(&root, &bytes, pins(&h, &bytes)).unwrap();
    let initial = seeded.manifest().unwrap();
    assert_eq!(initial.full_state_sha256, first_manifest.full_state_sha256);
    assert_eq!(initial.sources, first_manifest.sources);
    assert_eq!(initial.sources.count, 1);
    assert_eq!(h.sources.max_vid, 41); // Source identity/order does not assume dense physical VIDs.
    assert_eq!(initial.failed_hosts, FailedHosts::empty());
    assert_eq!(initial.retained_by_type, first_manifest.retained_by_type);
    let other = import(&t.path().join("same"), &bytes, pins(&h, &bytes)).unwrap();
    assert_eq!(initial, other.manifest().unwrap());
    drop(seeded);
    let (b, p) = bindings();
    let seeded = DurableStore::open(&root, &b, p, 1024 * 1024).unwrap();
    let block = initialized();
    let a = run(
        &source,
        std::slice::from_ref(&block),
        &t.path().join("root-next"),
    );
    let b = run(
        &seeded,
        std::slice::from_ref(&block),
        &t.path().join("seed-next"),
    );
    assert_eq!(a.full_state_sha256, b.full_state_sha256);
    assert_eq!(
        fs::read(t.path().join("root-next/frames.bcf1")).unwrap(),
        fs::read(t.path().join("seed-next/frames.bcf1")).unwrap()
    );
    assert_eq!(seeded.rewind_one(&b).unwrap(), initial);
    assert!(seeded.rewind_one(&initial).is_err());
    assert!(import(&root, &bytes, pins(&h, &bytes)).is_err());
    assert_eq!(seeded.manifest().unwrap(), initial);
}

#[test]
fn exact_null_image_is_preserved_and_distinct_from_sql_reload() {
    let t = tempfile::tempdir().unwrap();
    let (h, mut records) = fixture();
    let r = records
        .iter_mut()
        .find(|r| snap::decode_key(&h.binding, &r.key).unwrap().entity_type == "Pool")
        .unwrap();
    let key = snap::decode_key(&h.binding, &r.key).unwrap();
    let mut v = snap::StoredEntity::decode(&key, &r.value).unwrap();
    v.fields.retain(|f| f.name != "tick");
    let absent = v.fields.clone();
    v.fields.push(EntityField {
        name: "tick".into(),
        value: Some(GraphValue {
            kind: Some(Kind::Null(NullValue {})),
        }),
    });
    v.fields.sort_by(|a, b| a.name.cmp(&b.name));
    r.value = v.encode(&key).unwrap();
    let bytes = encode(h.clone(), &records);
    let s = import(&t.path().join("state"), &bytes, pins(&h, &bytes)).unwrap();
    let segment = begin(&s, &h.boundary.block_hash);
    let Some(backfill_common::pb::pinax::graph::backfill::v1::entity_id::Value::String(id)) =
        key.id.as_ref().and_then(|id| id.value.as_ref())
    else {
        unreachable!()
    };
    let logical = Key::new("Pool", id);
    assert_eq!(segment.get(&logical).unwrap().unwrap(), v.fields);
    assert_ne!(segment.get(&logical).unwrap().unwrap(), absent);
    let digest = segment.state_digest().unwrap();
    segment.abort().unwrap();
    assert_eq!(s.manifest().unwrap().full_state_sha256, Some(digest));
    drop(s);
    let (b, p) = bindings();
    let s = DurableStore::open(&t.path().join("state"), &b, p, 1024 * 1024).unwrap();
    assert_eq!(
        begin(&s, &h.boundary.block_hash)
            .get(&logical)
            .unwrap()
            .unwrap(),
        v.fields
    );
}

#[test]
fn oracle_origin_cannot_be_relabelled_after_continuation_or_rewind() {
    let t = tempfile::tempdir().unwrap();
    let (mut h, rs) = fixture();
    let SnapshotOrigin::Landing { mut seed } = h.origin else {
        unreachable!()
    };
    seed.head.block_number += 10;
    seed.head.block_hash = [2; 32];
    h.origin = SnapshotOrigin::Oracle { seed };
    h.vid = None;
    let data = encode(h.clone(), &rs);
    let p = pins(&h, &data);
    let mut wrong = p.clone();
    wrong.purpose = SnapshotPurpose::Landing;
    assert!(import(&t.path().join("wrong"), &data, wrong).is_err());
    assert!(!t.path().join("wrong").exists());
    let s = import(&t.path().join("oracle"), &data, p).unwrap();
    let initial = s.manifest().unwrap();
    assert!(initial.require_loadable().is_err());
    let next = run(&s, &[initialized()], &t.path().join("next"));
    assert_eq!(next.origin, initial.origin);
    assert!(next.require_loadable().is_err());
    assert!(s.rewind_one(&next).unwrap().require_loadable().is_err());
    assert!(s.manifest().unwrap().require_loadable().is_err());
}

#[test]
fn corrupt_truncated_extra_and_terminal_error_inputs_never_publish_seed() {
    let t = tempfile::tempdir().unwrap();
    let (h, rs) = fixture();
    let data = encode(h.clone(), &rs);
    let p = pins(&h, &data);
    for (i, mutated) in [
        data[..data.len() - 1].to_vec(),
        data[..data.len() / 2].to_vec(),
        {
            let mut d = data.clone();
            d.push(0);
            d
        },
        {
            let mut d = data.clone();
            let n = d.len();
            d[n - 3] ^= 1;
            d
        },
    ]
    .into_iter()
    .enumerate()
    {
        let root = t.path().join(format!("bad-{i}"));
        assert!(import(&root, &mutated, p.clone()).is_err());
        assert_uninitialized(&root);
    }
    let mut wrong = p.clone();
    wrong.snapshot_sha256 = [9; 32];
    wrong.engine_lineage = snap::initial_lineage(wrong.snapshot_sha256);
    let root = t.path().join("digest");
    assert!(import(&root, &data, wrong).is_err());
    assert_uninitialized(&root);
    struct FailAtEof(Cursor<Vec<u8>>);
    impl Read for FailAtEof {
        fn read(&mut self, b: &mut [u8]) -> std::io::Result<usize> {
            let n = self.0.read(b)?;
            if n == 0 {
                Err(std::io::Error::other("terminal injected error"))
            } else {
                Ok(n)
            }
        }
    }
    let root = t.path().join("terminal");
    let (b, pin) = bindings();
    assert!(DurableStore::import_snapshot(
        &root,
        &b,
        pin,
        FailAtEof(Cursor::new(data)),
        CAPTURE_MANIFEST,
        p,
        1024 * 1024
    )
    .is_err());
    assert_uninitialized(&root);
}

#[test]
fn header_identity_health_history_and_template_refusals_precede_creation() {
    let t = tempfile::tempdir().unwrap();
    let (h, rs) = fixture();
    for i in 0..8 {
        let mut h = h.clone();
        match i {
            0 => h.binding.deployment.push('x'),
            1 => h.binding.retention_sha256 = "01".repeat(32),
            2 => h
                .period_max
                .insert("Pool".into(), 0)
                .map(|_| ())
                .unwrap_or(()),
            3 => {
                if let SnapshotOrigin::Landing { seed } = &mut h.origin {
                    seed.health = "unhealthy".into()
                }
            }
            4 => {
                if let SnapshotOrigin::Landing { seed } = &mut h.origin {
                    seed.non_fatal_errors
                        .push("missing failed host history".into())
                }
            }
            5 => {
                if let SnapshotOrigin::Landing { seed } = &mut h.origin {
                    seed.profile_sha256 = "01".repeat(32)
                }
            }
            6 => {
                h.sources.rows[0].manifest_idx = 3;
                h.sources = snap::SourceSnapshot::from_rows(h.sources.rows).unwrap()
            }
            7 => {
                h.sources.rows[0].param = hex::decode(crate::hosts::FACTORY_EXCLUDED_POOL).unwrap();
                h.sources = snap::SourceSnapshot::from_rows(h.sources.rows).unwrap()
            }
            _ => unreachable!(),
        }
        let data = encode(h.clone(), &rs);
        let root = t.path().join(format!("header-{i}"));
        assert!(import(&root, &data, pins(&h, &data)).is_err(), "case{i}");
        assert!(!root.exists(), "case{i}");
    }
    let data = encode(h.clone(), &rs);
    for i in 0..4 {
        let mut p = pins(&h, &data);
        match i {
            0 => p.boundary.block_hash = [2; 32],
            1 => p.engine_lineage = [1; 32],
            2 => p.seed_manifest_sha256 = [1; 32],
            3 => p.purpose = SnapshotPurpose::Oracle,
            _ => unreachable!(),
        }
        let root = t.path().join(format!("pin-{i}"));
        assert!(import(&root, &data, p).is_err());
        assert!(!root.exists());
    }
}

#[test]
fn schema_and_storage_region_errors_rollback_all_preceding_rows() {
    let t = tempfile::tempdir().unwrap();
    let (h, original) = fixture();
    for i in 0..4 {
        let mut rs = original.clone();
        let r = rs.last_mut().unwrap();
        let mut key = snap::decode_key(&h.binding, &r.key).unwrap();
        let mut value = snap::StoredEntity::decode(&key, &r.value).unwrap();
        match i {
            0 => value.fields.push(EntityField {
                name: "zzUnknown".into(),
                value: Some(GraphValue {
                    kind: Some(Kind::Int(1)),
                }),
            }),
            1 => value.fields.retain(|f| f.name != "symbol"),
            2 => {
                value
                    .fields
                    .iter_mut()
                    .find(|f| f.name == "symbol")
                    .unwrap()
                    .value = Some(GraphValue {
                    kind: Some(Kind::Int(7)),
                })
            }
            3 => key.storage_causality_region = 1,
            _ => unreachable!(),
        }
        *r = SnapshotRecord::from_entity(&h.binding, &key, &value).unwrap();
        rs.sort_by(|a, b| a.key.cmp(&b.key));
        let data = encode(h.clone(), &rs);
        let root = t.path().join(format!("row-{i}"));
        assert!(import(&root, &data, pins(&h, &data)).is_err(), "case{i}");
        assert_uninitialized(&root);
    }
}

#[test]
fn retained_opaque_manifest_is_pinned_but_never_capture_certification() {
    let t = tempfile::tempdir().unwrap();
    let (h, rs) = fixture();
    let data = encode(h.clone(), &rs);
    let root = t.path().join("state");
    let s = import(&root, &data, pins(&h, &data)).unwrap();
    let evidence: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("seed-import.json")).unwrap()).unwrap();
    assert_eq!(evidence["production_selectable"], false);
    assert_eq!(evidence["capture_manifest_verified"], false);
    assert_eq!(
        fs::read(root.join("seed-manifest.bin")).unwrap(),
        CAPTURE_MANIFEST
    );
    fs::write(root.join("seed-manifest.bin"), b"changed").unwrap();
    assert!(s.manifest().is_err());
    drop(s);
    let (b, p) = bindings();
    assert!(DurableStore::open(&root, &b, p, 1024 * 1024).is_err());
}
