use backfill_common::{
    pb::pinax::graph::backfill::v1::{
        entity_id, graph_value, EntityField, EntityId, EntityKey, GraphValue,
    },
    producer_checkpoint::{FilePin, SnapshotPurpose},
    seed_manifest::{self as seed, *},
    state_snapshot::{self as snap, *},
};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

fn boundary(n: u64) -> Boundary {
    Boundary {
        block_number: n,
        block_hash: [n as u8; 32],
    }
}
fn digest(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
fn fixture(purpose: SnapshotPurpose) -> (Manifest, SnapshotHeader, Vec<SnapshotRecord>) {
    let binding = Binding {
        snapshot: SnapshotBinding {
            deployment: "QmSeedFixture".into(),
            network: "base".into(),
            descriptor_sha256: "11".repeat(32),
            retention_sha256: hex::encode(
                backfill_common::descriptor::RetentionPolicy::default().sha256(),
            ),
            type_ordinals: vec!["Token".into()],
            entity_id_policy: EntityIdPolicy::StringOnly,
        },
        purpose: purpose.clone(),
        boundary: boundary(100),
        start_block: 10,
        target: Target {
            schema: "sgd42".into(),
            site_id: 42,
            database: "graph".into(),
            system_identifier: "123456789".into(),
        },
        profile_sha256: "33".repeat(32),
        catalog_sha256: "44".repeat(32),
        schema_sha256: "55".repeat(32),
        raw_manifest_sha256: "66".repeat(32),
        capture_binary_sha256: "77".repeat(32),
        creating_graph_node: GraphNode {
            version: "0.44.0".into(),
            commit: "77823b5a7adc4eac4abf03202c8dd7cb00dea31d".into(),
        },
        spec_version: "1.0.0".into(),
        manifest_graft: None,
        landing_graft: None,
    };
    let capture = SeedOrigin {
        schema: binding.target.schema.clone(),
        site_id: binding.target.site_id,
        database: binding.target.database.clone(),
        system_identifier: binding.target.system_identifier.clone(),
        server_version_num: 160000,
        capture_tool_sha256: binding.capture_binary_sha256.clone(),
        profile_sha256: binding.profile_sha256.clone(),
        head: boundary(100),
        health: "healthy".into(),
        non_fatal_errors: vec![],
    };
    let header = SnapshotHeader {
        format: snap::FORMAT.into(),
        version: snap::VERSION,
        binding: binding.snapshot.clone(),
        boundary: binding.boundary.clone(),
        origin: if purpose == SnapshotPurpose::Landing {
            SnapshotOrigin::Landing {
                seed: capture.clone(),
            }
        } else {
            SnapshotOrigin::Oracle {
                seed: capture.clone(),
            }
        },
        vid: if purpose == SnapshotPurpose::Landing {
            Some(VidState {
                tables: vec![TableVid {
                    entity_type: "Token".into(),
                    postgres_table: "token".into(),
                    max_vid: 1,
                    sequence_last_value: 1,
                    sequence_is_called: true,
                    active_rows: Some(1),
                }],
            })
        } else {
            None
        },
        poi: GenericPoiState::default(),
        sources: SourceSnapshot::from_rows(vec![SnapshotSource {
            vid: 1,
            creation_block: 12,
            manifest_idx: 2,
            param: vec![3; 20],
        }])
        .unwrap(),
        period_max: BTreeMap::new(),
        entity_count: Some(1),
        records: 1,
    };
    let key = EntityKey {
        entity_type: "Token".into(),
        id: Some(EntityId {
            value: Some(entity_id::Value::String("a".into())),
        }),
        storage_causality_region: 0,
    };
    let row = SnapshotRecord::from_entity(
        &binding.snapshot,
        &key,
        &StoredEntity {
            vid: 1,
            block_range_start: 99,
            fields: vec![EntityField {
                name: "id".into(),
                value: Some(GraphValue {
                    kind: Some(graph_value::Kind::String("a".into())),
                }),
            }],
        },
    )
    .unwrap();
    let manifest = Manifest {
        format: seed::FORMAT.into(),
        deployment: DeploymentObservation {
            deployment: binding.snapshot.deployment.clone(),
            spec_version: binding.spec_version.clone(),
            start_parent: boundary(9),
            graft: None,
            schema_sha256: binding.schema_sha256.clone(),
            raw_manifest_sha256: binding.raw_manifest_sha256.clone(),
            creating_graph_node: binding.creating_graph_node.clone(),
            failed: false,
            fatal_error: None,
            retained_error_count: 0,
            current_reorg_depth: 0,
            postponed_indexes_created: true,
            namespace_count: 1,
        },
        transaction: TransactionObservation {
            isolation: "repeatable read".into(),
            read_only: true,
            backend_pid: 1234,
            write_lock: true,
            copy_lock: true,
            prune_lock: true,
        },
        history: History::UnprunedFromDeploymentStart {
            history_blocks: i32::MAX as u64,
            earliest_block: 9,
            table_last_pruned_block: [("Token".into(), None)].into(),
        },
        catalog_sha256: binding.catalog_sha256.clone(),
        sources: seed::SourceCommitment {
            count: header.sources.count,
            max_vid: header.sources.max_vid,
            order_sha256: header.sources.order_sha256.clone(),
        },
        captured_rows: [("Token".into(), 1)].into(),
        capture,
        binding,
        snapshot: FilePin {
            path: "seed.bcgsnap".into(),
            bytes: 1,
            sha256: "88".repeat(32),
        },
        lineage: "00".repeat(32),
    };
    (manifest, header, vec![row])
}
fn seal(
    mut manifest: Manifest,
    header: SnapshotHeader,
    rows: &[SnapshotRecord],
) -> (Manifest, Vec<u8>, Vec<u8>) {
    let mut writer = SnapshotWriter::new(Vec::new(), header, Limits::default()).unwrap();
    for row in rows {
        writer.write_record(row).unwrap();
    }
    let (snapshot, pin) = writer.finish().unwrap();
    manifest.snapshot.bytes = pin.bytes();
    manifest.snapshot.sha256 = hex::encode(pin.file_sha256());
    manifest.lineage = hex::encode(pin.lineage());
    let bytes = manifest.encode().unwrap();
    (manifest, bytes, snapshot)
}

fn schema() -> graph::schema::InputSchema {
    graph::schema::InputSchema::parse_latest(
        "type Token @entity(immutable: true) { id: ID!, value: BigDecimal, tag: String }",
        graph::prelude::DeploymentHash::new("QmSeedFixture").unwrap(),
    )
    .unwrap()
}

fn opened(limits: super::OverlayLimits) -> (tempfile::TempDir, super::DiskStore) {
    let dir = tempfile::tempdir().unwrap();
    let (m, h, mut r) = fixture(SnapshotPurpose::Oracle);
    let key = snap::decode_key(&h.binding, &r[0].key).unwrap();
    let mut value = StoredEntity::decode(&key, &r[0].value).unwrap();
    value.fields.push(EntityField {
        name: "tag".into(),
        value: Some(GraphValue {
            kind: Some(graph_value::Kind::Null(Default::default())),
        }),
    });
    value.fields.push(EntityField {
        name: "value".into(),
        value: Some(GraphValue {
            kind: Some(graph_value::Kind::BigDecimal(
                backfill_common::pb::pinax::graph::backfill::v1::BigDecimalValue {
                    coefficient_signed_be: vec![0x85],
                    scale: 2,
                },
            )),
        }),
    });
    r[0] = SnapshotRecord::from_entity(&h.binding, &key, &value).unwrap();
    let (m, manifest, bytes) = seal(m, h, &r);
    let store = super::DiskStore::import(
        &dir.path().join("seed.redb"),
        bytes.as_slice(),
        &manifest,
        &digest(&manifest),
        &m.binding,
        schema(),
        limits,
        Limits::default(),
    )
    .unwrap();
    (dir, store)
}

fn modification(
    store: &super::DiskStore,
    id: &str,
    tag: &str,
) -> graph::components::store::write::EntityModification {
    let key = store
        .schema()
        .entity_type("Token")
        .unwrap()
        .parse_key(id)
        .unwrap();
    let mut entity = store
        .schema()
        .make_entity(vec![
            ("id".into(), graph::data::store::Value::String(id.into())),
            ("tag".into(), graph::data::store::Value::String(tag.into())),
        ])
        .unwrap();
    entity.set_vid(123).unwrap();
    graph::components::store::write::EntityModification::Insert {
        key,
        data: std::sync::Arc::new(entity),
        block: 101,
        end: None,
    }
}

#[test]
fn immutable_base_preserves_negative_decimal_null_vid_and_stream_order() {
    let (_dir, store) = opened(super::OverlayLimits::default());
    let key = store
        .schema()
        .entity_type("Token")
        .unwrap()
        .parse_key("a")
        .unwrap();
    let value = store.lookup(&key).unwrap().unwrap();
    assert_eq!(value.vid(), 1);
    let fields = crate::blockchanges::convert_entity(&value);
    assert!(matches!(
        fields[1].value.as_ref().unwrap().kind,
        Some(graph_value::Kind::Null(_))
    ));
    assert!(
        matches!(fields[2].value.as_ref().unwrap().kind, Some(graph_value::Kind::BigDecimal(ref d)) if d.coefficient_signed_be == vec![0x85] && d.scale == 2)
    );
    let mut seen = 0;
    store
        .visit_seed(|k, v| {
            assert_eq!(k.entity_type, "Token");
            assert_eq!(v.fields, fields);
            assert_eq!(v.vid, 1);
            seen += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(seen, 1);
}

#[test]
fn overlay_first_touch_undo_restores_base_and_absence_with_exact_vid() {
    let (_dir, store) = opened(super::OverlayLimits::default());
    let a = store
        .schema()
        .entity_type("Token")
        .unwrap()
        .parse_key("a")
        .unwrap();
    let b = store
        .schema()
        .entity_type("Token")
        .unwrap()
        .parse_key("b")
        .unwrap();
    let before = store.lookup(&a).unwrap().unwrap();
    let mut undo = crate::store::StoreUndo::new();
    store
        .apply_recording(
            &[
                modification(&store, "a", "changed"),
                modification(&store, "b", "new"),
            ],
            &mut undo,
        )
        .unwrap();
    store
        .apply_recording(&[modification(&store, "a", "again")], &mut undo)
        .unwrap();
    assert_eq!(store.len(), 2);
    store.rollback(undo).unwrap();
    let after = store.lookup(&a).unwrap().unwrap();
    assert_eq!(after, before);
    assert_eq!(after.vid(), before.vid());
    assert!(store.lookup(&b).unwrap().is_none());
    assert_eq!(store.len(), 1);
}

#[test]
fn entire_batch_budget_refusal_leaves_overlay_and_undo_unchanged() {
    let (_dir, store) = opened(super::OverlayLimits {
        keys: 1,
        encoded_bytes: 4096,
    });
    let a = store
        .schema()
        .entity_type("Token")
        .unwrap()
        .parse_key("a")
        .unwrap();
    let before = store.lookup(&a).unwrap().unwrap();
    let mut undo = crate::store::StoreUndo::new();
    let error = store
        .apply_recording(
            &[
                modification(&store, "a", "changed"),
                modification(&store, "b", "new"),
            ],
            &mut undo,
        )
        .unwrap_err();
    assert!(error.to_string().contains("limit exceeded"));
    assert!(undo.is_empty());
    assert_eq!(store.lookup(&a).unwrap().unwrap(), before);
    assert_eq!(store.overlay.read().unwrap().rows.len(), 0);
}

#[test]
fn invalid_footer_truncation_and_binding_never_admit_partial_database() {
    for mode in 0..4 {
        let dir = tempfile::tempdir().unwrap();
        let (m, h, r) = fixture(SnapshotPurpose::Oracle);
        let (m, manifest, mut bytes) = seal(m, h, &r);
        let mut binding = m.binding.clone();
        match mode {
            0 => {
                bytes.pop();
            }
            1 => {
                let last = bytes.len() - 1;
                bytes[last] ^= 1;
            }
            2 => binding.snapshot.retention_sha256 = "22".repeat(32),
            _ => bytes.push(0),
        }
        let error = super::DiskStore::import(
            &dir.path().join("seed.redb"),
            bytes.as_slice(),
            &manifest,
            &digest(&manifest),
            &binding,
            schema(),
            super::OverlayLimits::default(),
            Limits::default(),
        )
        .err()
        .expect("invalid input refused");
        assert!(!error.to_string().is_empty());
    }
}

#[test]
fn eager_exports_refuse_instead_of_returning_overlay_only_rows() {
    // Construction and full-base lookups are exercised here; the explicit
    // ReadStore refusal is also enforced by the deployed import inventory test.
    let (_dir, store) = opened(super::OverlayLimits::default());
    let host = crate::store::HostStore::Disk(Box::new(store));
    assert!(host
        .snapshot()
        .unwrap_err()
        .to_string()
        .contains("full in-memory"));
    assert!(host
        .restore(BTreeMap::new())
        .unwrap_err()
        .to_string()
        .contains("immutable"));
}

#[test]
fn exact_deployed_aerodrome_wasm_has_no_derived_or_remove_import() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("segments/QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV");
    let bundle = crate::bundle::SegmentBundle::load(&path).unwrap();
    let mut modules = 0;
    for file in &bundle.lock().files {
        if !file.path.ends_with(".wasm") {
            continue;
        }
        let bytes = std::fs::read(path.join(&file.path)).unwrap();
        let mut imports = std::collections::BTreeSet::new();
        for payload in wasmparser::Parser::new(0).parse_all(&bytes) {
            if let wasmparser::Payload::ImportSection(section) = payload.unwrap() {
                for import in section {
                    let import = import.unwrap();
                    if import.name.starts_with("store.") {
                        imports.insert(import.name.to_owned());
                    }
                }
            }
        }
        assert_eq!(
            imports,
            ["store.get".to_owned(), "store.set".to_owned()].into(),
            "{}",
            file.path
        );
        modules += 1;
    }
    assert_eq!(modules, 3);
}

fn copy_tree(from: &std::path::Path, to: &std::path::Path) {
    std::fs::create_dir(to).unwrap();
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), target).unwrap();
        }
    }
}

#[tokio::test]
async fn populated_seed_cold_checkpoint_and_continuous_replay_match_memory() {
    use crate::{
        calls::CassetteFingerprint,
        checkpoint::{CheckpointBoundary, HostCheckpoint},
        runner::{DiskRunLimits, SegmentHost, SegmentHostConfig},
    };
    use graph::prelude::prost::Message;
    use graph::prelude::{o, slog, Logger};
    const DEPLOYMENT: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let temp = tempfile::tempdir().unwrap();
    let segment = temp.path().join(DEPLOYMENT);
    copy_tree(&root.join("segments").join(DEPLOYMENT), &segment);
    let logger = Logger::root(slog::Discard, o!());
    crate::descriptor::write_in_band(&segment, root.parent().unwrap(), &logger)
        .await
        .unwrap();
    let cassette = root.join(format!("fixtures/cassettes/{DEPLOYMENT}.json"));
    let cassette_bytes = std::fs::read(&cassette).unwrap();
    let config = || SegmentHostConfig {
        bundle_dir: &segment,
        cassette_path: &cassette,
        record: false,
    };
    let mut original = SegmentHost::load_in_band(config()).await.unwrap();
    let raw = std::fs::read(
        root.parent()
            .unwrap()
            .join("aerodrome-slipstream-base/fixtures/blocks/base/13899663.pb"),
    )
    .expect("hydrate locked Base fixtures");
    let original_block = graph_chain_ethereum::codec::Block::decode(raw.as_slice()).unwrap();
    let outcome = original
        .process_block((&original_block).try_into().unwrap())
        .await
        .unwrap();
    let checkpoint_boundary = CheckpointBoundary {
        block: outcome.report.number,
        block_hash: outcome.report.hash.clone(),
        source: "synthetic seed fixture from actual first-pool replay".into(),
        chunk_from: None,
        chunk_to: None,
        blocks_in_chunk: 1,
        blocks_total: 1,
        chunk_index: 0,
        previous_checkpoint_sha256: None,
    };
    let cassette_pin: CassetteFingerprint = original
        .cassette()
        .fingerprint(digest(&cassette_bytes))
        .unwrap();
    let checkpoint = original
        .checkpoint(&cassette_pin, checkpoint_boundary, None)
        .unwrap();
    let schema = original.store_state(None, None).unwrap();
    assert!(!schema.entities.is_empty());
    let (mut m, mut h, _) = fixture(SnapshotPurpose::Oracle);
    let lock = crate::bundle::SegmentBundle::load(&segment).unwrap();
    let types: Vec<String> = schema
        .entities
        .iter()
        .map(|e| e.entity_type.clone())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    // The complete inventory includes zero-row types too.
    let parsed = graph::schema::InputSchema::parse_latest(
        &std::fs::read_to_string(segment.join("schema.graphql")).unwrap(),
        graph::prelude::DeploymentHash::new(DEPLOYMENT).unwrap(),
    )
    .unwrap();
    let mut all_types: Vec<_> = parsed
        .entity_types()
        .iter()
        .map(|t| t.typename().to_string())
        .collect();
    all_types.sort();
    assert!(all_types.len() >= types.len());
    m.binding.snapshot.deployment = DEPLOYMENT.into();
    m.binding.snapshot.type_ordinals = all_types.clone();
    m.binding.spec_version = "1.2.0".into();
    m.binding.start_block = 13843704;
    m.binding.boundary = Boundary {
        block_number: outcome.report.number as u64,
        block_hash: original_block.hash.as_slice().try_into().unwrap(),
    };
    m.binding.schema_sha256 = lock
        .lock()
        .files
        .iter()
        .find(|f| f.path == "schema.graphql")
        .unwrap()
        .sha256
        .clone();
    m.binding.raw_manifest_sha256 = lock
        .lock()
        .files
        .iter()
        .find(|f| f.path == "manifest.yaml")
        .unwrap()
        .sha256
        .clone();
    m.capture.head = m.binding.boundary.clone();
    m.deployment.deployment = DEPLOYMENT.into();
    m.deployment.spec_version = m.binding.spec_version.clone();
    m.deployment.start_parent = boundary(m.binding.start_block - 1);
    m.deployment.schema_sha256 = m.binding.schema_sha256.clone();
    m.deployment.raw_manifest_sha256 = m.binding.raw_manifest_sha256.clone();
    m.history = History::UnprunedFromDeploymentStart {
        history_blocks: i32::MAX as u64,
        earliest_block: m.binding.start_block - 1,
        table_last_pruned_block: all_types.iter().map(|t| (t.clone(), None)).collect(),
    };
    h.binding = m.binding.snapshot.clone();
    h.boundary = m.binding.boundary.clone();
    h.origin = SnapshotOrigin::Oracle {
        seed: m.capture.clone(),
    };
    h.sources = SourceSnapshot::from_rows(
        checkpoint
            .data_sources
            .iter()
            .enumerate()
            .map(|(i, s)| SnapshotSource {
                vid: i as i32 + 1,
                creation_block: s.creation_block,
                manifest_idx: s.manifest_idx as i32,
                param: hex::decode(s.params[0].trim_start_matches("0x")).unwrap(),
            })
            .collect(),
    )
    .unwrap();
    m.sources = SourceCommitment {
        count: h.sources.count,
        max_vid: h.sources.max_vid,
        order_sha256: h.sources.order_sha256.clone(),
    };
    m.captured_rows = all_types.iter().map(|t| (t.clone(), 0)).collect();
    let mut records = Vec::new();
    for row in &checkpoint.rows {
        if row.entity_type == "Poi$" {
            let Some(graph_value::Kind::Bytes(digest)) = row
                .wire_fields()
                .into_iter()
                .find(|f| f.name == "digest")
                .unwrap()
                .value
                .unwrap()
                .kind
            else {
                panic!("PoI bytes");
            };
            h.poi = GenericPoiState {
                region_digest: Some(digest.clone()),
                active: Some(PoiVersion {
                    vid: row.vid,
                    block_range_start: outcome.report.number,
                    id: "ethereum/base".into(),
                    digest,
                }),
            };
            continue;
        }
        *m.captured_rows.get_mut(&row.entity_type).unwrap() += 1;
        records.push(
            SnapshotRecord::from_entity(
                &h.binding,
                &row.key().to_wire(),
                &StoredEntity {
                    vid: row.vid,
                    block_range_start: outcome.report.number,
                    fields: row.wire_fields(),
                },
            )
            .unwrap(),
        );
    }
    records.sort_by(|a, b| a.key.cmp(&b.key));
    h.records = records.len() as u64;
    h.entity_count = Some(records.len() as i64);
    let (m, manifest, snapshot) = seal(m, h, &records);
    let mut disk = SegmentHost::load_disk_seed(
        config(),
        &temp.path().join("seed.redb"),
        snapshot.as_slice(),
        &manifest,
        &digest(&manifest),
        &m.binding,
        super::OverlayLimits::default(),
        DiskRunLimits {
            sources: 100,
            cache_keys: 100000,
            blocks: 3,
        },
        Limits::default(),
    )
    .await
    .unwrap();
    let mut cold = Vec::new();
    disk.write_cold_seed_checkpoint(&mut cold).unwrap();
    let cold = HostCheckpoint::parse(cold.as_slice()).unwrap();
    assert_eq!(cold.header.totals.cached_present, 0);
    assert_eq!(cold.header.totals.cached_absent, 0);
    assert_eq!(cold.rows.len(), checkpoint.rows.len());
    for (a, b) in cold.rows.iter().zip(&checkpoint.rows) {
        assert_eq!(a.key(), b.key());
        assert_eq!(a.vid, b.vid);
        assert_eq!(a.fields, b.fields);
    }
    let mut memory = SegmentHost::load_in_band(config()).await.unwrap();
    memory.restore_checkpoint(&cold, &cassette_pin).unwrap();
    let mut previous = original_block.hash.clone();
    let mut input_blocks = Vec::new();
    let mut expected_frames = Vec::new();
    for i in 1..=2 {
        let mut next = original_block.clone();
        next.number += i;
        next.hash = vec![40 + i as u8; 32];
        let header = next.header.as_mut().unwrap();
        header.number = next.number;
        header.hash = next.hash.clone();
        header.parent_hash = previous;
        next.transaction_traces.clear();
        let a = disk
            .process_block((&next).try_into().unwrap())
            .await
            .unwrap();
        let b = memory
            .process_block((&next).try_into().unwrap())
            .await
            .unwrap();
        assert_eq!(a.changes, b.changes);
        assert_eq!(a.report.poi, b.report.poi);
        assert_eq!(a.report.store_counts, b.report.store_counts);
        let payload = crate::blockchanges::seal(&a.changes, disk.compatibility()).unwrap();
        expected_frames
            .push(crate::blockchanges::bcf1_frame(next.number, &next.hash, &payload).unwrap());
        let path = temp.path().join(format!("block-{i}.pb"));
        let raw = next.encode_to_vec();
        std::fs::write(&path, &raw).unwrap();
        input_blocks.push(crate::disk_oracle::Artifact {
            path,
            bytes: raw.len() as u64,
            sha256: digest(&raw),
        });
        previous = next.hash;
    }
    assert!(disk.write_cold_seed_checkpoint(&mut Vec::new()).is_err());
    // The exact orchestrator preserves this one host across report partitions.
    use crate::disk_oracle::{Artifact, Input, Request};
    let manifest_path = temp.path().join("seed-manifest.json");
    let snapshot_path = temp.path().join("seed.bcgsnap");
    std::fs::write(&manifest_path, &manifest).unwrap();
    std::fs::write(&snapshot_path, &snapshot).unwrap();
    let mut request = Request {
        schema: crate::disk_oracle::REQUEST_SCHEMA.into(),
        segment: segment.clone(),
        output: temp.path().join("run"),
        seed_binding: m.binding.clone(),
        seed_manifest: Artifact {
            path: manifest_path,
            bytes: manifest.len() as u64,
            sha256: digest(&manifest),
        },
        seed_snapshot: Artifact {
            path: snapshot_path,
            bytes: snapshot.len() as u64,
            sha256: digest(&snapshot),
        },
        rpc_cassette: Artifact {
            path: cassette.clone(),
            bytes: cassette_bytes.len() as u64,
            sha256: digest(&cassette_bytes),
        },
        input: Input::Fixtures {
            blocks: input_blocks.clone(),
        },
        to_exclusive: outcome.report.number + 3,
        partition_blocks: 1,
        timeout_seconds: 60,
        overlay_keys: 100000,
        overlay_bytes: 64 * 1024 * 1024,
        cache_keys: 100000,
        sources: 100,
    };
    let request_path = temp.path().join("request.json");
    let save_request = |request: &Request| {
        let mut raw = serde_json::to_vec_pretty(request).unwrap();
        raw.push(b'\n');
        std::fs::write(&request_path, &raw).unwrap();
        digest(&raw)
    };
    crate::disk_oracle::run(&request_path, &save_request(&request))
        .await
        .unwrap();
    let completion: serde_json::Value =
        serde_json::from_slice(&std::fs::read(request.output.join("complete.json")).unwrap())
            .unwrap();
    assert_eq!(completion["fixture_only"], true);
    assert_eq!(completion["partitions"].as_array().unwrap().len(), 2);
    assert_eq!(
        completion["rpc_cassette"]["sha256"],
        digest(&cassette_bytes)
    );
    for (i, want) in expected_frames.iter().enumerate() {
        assert_eq!(
            std::fs::read(request.output.join(format!("partition-{i:03}/frames.bcf1"))).unwrap(),
            *want
        );
    }
    assert!(!request.output.join(".complete.json.partial").exists());
    // Explicit fixture-generation mode, never enabled in normal tests or CI.
    // This produces only synthetic cold-seed evidence for the installed-image smoke.
    if let Some(export) = std::env::var_os("DISK_ORACLE_FIXTURE_EXPORT") {
        let export = std::path::PathBuf::from(export);
        std::fs::create_dir(&export).unwrap();
        std::fs::write(export.join("seed-manifest.json"), &manifest).unwrap();
        std::fs::write(export.join("seed.bcgsnap"), &snapshot).unwrap();
        std::fs::write(export.join("rpc-cassette.json"), &cassette_bytes).unwrap();
        std::fs::copy(
            request.output.join("seed.checkpoint.jsonl"),
            export.join("expected-checkpoint.jsonl"),
        )
        .unwrap();
        let mut portable = request.clone();
        portable.segment = format!("/opt/mapping-host/segments/{DEPLOYMENT}").into();
        portable.output = "/output/disk-oracle".into();
        portable.seed_manifest.path = "/fixtures/disk-seed/seed-manifest.json".into();
        portable.seed_snapshot.path = "/fixtures/disk-seed/seed.bcgsnap".into();
        portable.rpc_cassette.path = "/fixtures/disk-seed/rpc-cassette.json".into();
        let Input::Fixtures { blocks } = &mut portable.input else {
            unreachable!()
        };
        for (i, block) in blocks.iter_mut().enumerate() {
            std::fs::copy(&block.path, export.join(format!("block-{i}.pb"))).unwrap();
            block.path = format!("/fixtures/disk-seed/block-{i}.pb").into();
            std::fs::write(
                export.join(format!("expected-{i}.bcf1")),
                &expected_frames[i],
            )
            .unwrap();
        }
        let mut encoded = serde_json::to_vec_pretty(&portable).unwrap();
        encoded.push(b'\n');
        std::fs::write(export.join("request.json"), &encoded).unwrap();
        let provenance = serde_json::json!({"format":"pinax.mapping-host.disk-oracle-smoke-fixture/v1","fixture_only":true,"seed":"synthetic complete cold seed from actual deployed first-pool memory replay","source_block":13899663,"source_block_sha256":digest(&raw),"successors":"two synthetic empty blocks with exact parent linkage","request_sha256":digest(&encoded),"production_selectable":false});
        let mut encoded = serde_json::to_vec_pretty(&provenance).unwrap();
        encoded.push(b'\n');
        std::fs::write(export.join("provenance.json"), encoded).unwrap();
    }
    assert!(
        crate::disk_oracle::run(&request_path, &save_request(&request))
            .await
            .is_err()
    );
    // A complete-looking first partition never publishes completion after a bad suffix.
    request.output = temp.path().join("truncated-run");
    let Input::Fixtures { blocks } = &mut request.input else {
        unreachable!()
    };
    blocks[1].sha256 = "00".repeat(32);
    assert!(
        crate::disk_oracle::run(&request_path, &save_request(&request))
            .await
            .is_err()
    );
    assert!(request.output.join("partition-000/frames.bcf1").exists());
    assert!(!request.output.join("complete.json").exists());
    // Wrong ancestry poisons the host, including any attempted retry afterwards.
    let mut bad = original_block.clone();
    bad.number += 3;
    bad.hash = vec![50; 32];
    let header = bad.header.as_mut().unwrap();
    header.number = bad.number;
    header.hash = bad.hash.clone();
    header.parent_hash = vec![99; 32];
    bad.transaction_traces.clear();
    assert!(disk
        .process_block((&bad).try_into().unwrap())
        .await
        .err()
        .expect("invalid block refused")
        .to_string()
        .contains("exact seed/replay boundary"));
    assert!(disk
        .process_block((&bad).try_into().unwrap())
        .await
        .err()
        .expect("invalid block refused")
        .to_string()
        .contains("poisoned"));
}

#[test]
fn normalization_domain_is_refused_without_rewriting_the_seed() {
    use graph::prelude::BigInt;
    use std::str::FromStr;
    let (m, h, mut rows) = fixture(SnapshotPurpose::Oracle);
    let key = snap::decode_key(&h.binding, &rows[0].key).unwrap();
    let mut value = StoredEntity::decode(&key, &rows[0].value).unwrap();
    // Pinned GN stores this 35-digit negative tuple after one normalization;
    // restoring it normalizes again and changes it. It cannot be an exact seed.
    let n = BigInt::from_str("-85070591730234615865843651857942052").unwrap();
    value.fields.push(EntityField {
        name: "value".into(),
        value: Some(GraphValue {
            kind: Some(graph_value::Kind::BigDecimal(
                backfill_common::pb::pinax::graph::backfill::v1::BigDecimalValue {
                    coefficient_signed_be: n.to_signed_bytes_le().into_iter().rev().collect(),
                    scale: -3,
                },
            )),
        }),
    });
    let native = super::decode_entity(&schema(), &value).unwrap();
    assert_ne!(crate::blockchanges::convert_entity(&native), value.fields);
    let error = SnapshotRecord::from_entity(&h.binding, &key, &value).unwrap_err();
    assert!(
        error.to_string().contains("normalization would round"),
        "{error}"
    );
    // The admitted production negative TVL is in the exact fixed-point domain.
    let production = BigInt::from_str("-19582627366648723548155211868460794").unwrap();
    let graph_value::Kind::BigDecimal(decimal) = value
        .fields
        .last_mut()
        .unwrap()
        .value
        .as_mut()
        .unwrap()
        .kind
        .as_mut()
        .unwrap()
    else {
        unreachable!()
    };
    decimal.coefficient_signed_be = production.to_signed_bytes_le().into_iter().rev().collect();
    decimal.scale = 31;
    rows[0] = SnapshotRecord::from_entity(&h.binding, &key, &value).unwrap();
    let (m, manifest, snapshot) = seal(m, h, &rows);
    let temp = tempfile::tempdir().unwrap();
    let store = super::DiskStore::import(
        &temp.path().join("seed.redb"),
        snapshot.as_slice(),
        &manifest,
        &digest(&manifest),
        &m.binding,
        schema(),
        super::OverlayLimits::default(),
        Limits::default(),
    )
    .unwrap();
    let native_key = crate::blockchanges::key_from_wire(store.schema(), &key).unwrap();
    assert_eq!(
        crate::blockchanges::convert_entity(&store.lookup(&native_key).unwrap().unwrap()),
        value.fields
    );
}

#[test]
fn seed_stream_crosses_transaction_batches_without_materializing_history() {
    use std::io::{Read, Write};
    let temp = tempfile::tempdir().unwrap();
    let (mut m, mut h, template) = fixture(SnapshotPurpose::Oracle);
    const ROWS: u64 = 600;
    h.records = ROWS;
    h.entity_count = Some(ROWS as i64);
    m.captured_rows.insert("Token".into(), ROWS);
    let mut writer = SnapshotWriter::new(
        std::fs::File::create(temp.path().join("seed.bcgsnap")).unwrap(),
        h.clone(),
        Limits::default(),
    )
    .unwrap();
    let mut key = snap::decode_key(&h.binding, &template[0].key).unwrap();
    let mut value = StoredEntity::decode(&key, &template[0].value).unwrap();
    value.fields.push(EntityField {
        name: "tag".into(),
        value: Some(GraphValue {
            kind: Some(graph_value::Kind::String("x".repeat(64 * 1024))),
        }),
    });
    for index in 0..ROWS {
        let id = format!("id-{index:06}");
        key.id.as_mut().unwrap().value = Some(entity_id::Value::String(id.clone()));
        value.fields[0].value.as_mut().unwrap().kind = Some(graph_value::Kind::String(id));
        value.vid = index as i64;
        writer
            .write_record(&SnapshotRecord::from_entity(&h.binding, &key, &value).unwrap())
            .unwrap();
    }
    let (mut output, pin) = writer.finish().unwrap();
    output.flush().unwrap();
    drop(output);
    assert!(pin.bytes() > super::IMPORT_BATCH_BYTES as u64);
    m.snapshot.bytes = pin.bytes();
    m.snapshot.sha256 = hex::encode(pin.file_sha256());
    m.lineage = hex::encode(pin.lineage());
    let manifest = m.encode().unwrap();
    struct Chunked(std::fs::File);
    impl Read for Chunked {
        fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
            let n = buf.len().min(8192);
            self.0.read(&mut buf[..n])
        }
    }
    let store = super::DiskStore::import(
        &temp.path().join("seed.redb"),
        Chunked(std::fs::File::open(temp.path().join("seed.bcgsnap")).unwrap()),
        &manifest,
        &digest(&manifest),
        &m.binding,
        schema(),
        super::OverlayLimits::default(),
        Limits::default(),
    )
    .unwrap();
    assert_eq!(store.len(), ROWS as usize);
    assert!(store.overlay.read().unwrap().rows.is_empty());
    let mut observed = 0;
    store
        .visit_seed(|_, row| {
            assert_eq!(row.vid, observed);
            observed += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(observed, ROWS as i64);
}

#[tokio::test]
async fn disk_read_corruption_and_derived_queries_fail_without_false_absence() {
    use graph::components::store::{DerivedEntityQuery, ReadStore};
    let (_dir, store) = opened(super::OverlayLimits::default());
    let entity_type = store.schema().entity_type("Token").unwrap();
    let key = entity_type.parse_key("a").unwrap();
    let query = DerivedEntityQuery {
        entity_type,
        entity_field: "tag".into(),
        value: key.entity_id.clone(),
        causality_region: key.causality_region,
    };
    let host = crate::store::HostStore::Disk(Box::new(store));
    assert!(host
        .get_derived(&query)
        .await
        .unwrap_err()
        .to_string()
        .contains("full derived queries"));
    let crate::store::HostStore::Disk(store) = host else {
        unreachable!()
    };
    let wire = crate::blockchanges::convert_key(&key);
    let encoded = snap::encode_key(&store.header().binding, &wire).unwrap();
    let tx = store.db.begin_write().unwrap();
    {
        let mut table = tx.open_table(super::ROWS).unwrap();
        table
            .insert(encoded.as_slice(), b"corrupt stored entity".as_slice())
            .unwrap();
    }
    tx.commit().unwrap();
    assert!(store.lookup(&key).is_err());
    let mut undo = crate::store::StoreUndo::new();
    assert!(store
        .apply_recording(&[modification(&store, "a", "new")], &mut undo)
        .is_err());
    assert!(undo.is_empty());
    assert!(store.overlay.read().unwrap().rows.is_empty());
}
