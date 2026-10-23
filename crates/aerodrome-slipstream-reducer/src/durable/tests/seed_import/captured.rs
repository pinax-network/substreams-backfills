use super::*;
use backfill_common::seed_manifest as capture;

fn captured_fixture(oracle: bool) -> (Vec<u8>, capture::Manifest, CapturedSeedPins) {
    let (mut header, records) = fixture();
    let SnapshotOrigin::Landing { mut seed } = header.origin else {
        unreachable!()
    };
    seed.schema = "sgd7".into();
    seed.system_identifier = "123456789".into();
    let purpose = if oracle {
        SnapshotPurpose::Oracle
    } else {
        SnapshotPurpose::Landing
    };
    header.origin = if oracle {
        header.vid = None;
        SnapshotOrigin::Oracle { seed: seed.clone() }
    } else {
        SnapshotOrigin::Landing { seed: seed.clone() }
    };
    let bytes = encode(header.clone(), &records);
    let input = bindings().0;
    let cap = input.compatibility().capabilities().unwrap();
    let graph_node = capture::GraphNode {
        version: "0.44.0".into(),
        commit: graph_numerics::GRAPH_NODE_COMMIT.into(),
    };
    let binding = capture::Binding {
        snapshot: header.binding.clone(),
        purpose,
        boundary: header.boundary.clone(),
        start_block: INITIAL_BLOCK,
        target: capture::Target {
            schema: seed.schema.clone(),
            site_id: seed.site_id,
            database: seed.database.clone(),
            system_identifier: seed.system_identifier.clone(),
        },
        profile_sha256: seed.profile_sha256.clone(),
        catalog_sha256: "09".repeat(32),
        schema_sha256: hex::encode(Sha256::digest(include_bytes!(
            "../../../../../../aerodrome-slipstream-base/reference/schema.graphql"
        ))),
        raw_manifest_sha256: "10".repeat(32),
        capture_binary_sha256: seed.capture_tool_sha256.clone(),
        creating_graph_node: graph_node.clone(),
        spec_version: cap.spec_version.clone(),
        manifest_graft: None,
        landing_graft: None,
    };
    let mut counts: BTreeMap<_, u64> = header
        .binding
        .type_ordinals
        .iter()
        .map(|n| (n.clone(), 0))
        .collect();
    for row in &records {
        let key = snap::decode_key(&header.binding, &row.key).unwrap();
        *counts.get_mut(&key.entity_type).unwrap() += 1;
    }
    let digest = Sha256::digest(&bytes).into();
    let manifest = capture::Manifest {
        format: capture::FORMAT.into(),
        binding: binding.clone(),
        snapshot: checkpoint::FilePin {
            path: "seed.bcgsnap".into(),
            bytes: bytes.len() as u64,
            sha256: hex::encode(digest),
        },
        lineage: hex::encode(snap::initial_lineage(digest)),
        capture: seed,
        deployment: capture::DeploymentObservation {
            deployment: cap.deployment.clone(),
            spec_version: cap.spec_version.clone(),
            start_parent: Boundary {
                block_number: INITIAL_BLOCK - 1,
                block_hash: [19; 32],
            },
            graft: None,
            schema_sha256: binding.schema_sha256.clone(),
            raw_manifest_sha256: binding.raw_manifest_sha256.clone(),
            creating_graph_node: graph_node,
            failed: false,
            fatal_error: None,
            retained_error_count: 0,
            current_reorg_depth: 0,
            postponed_indexes_created: true,
            namespace_count: 1,
        },
        transaction: capture::TransactionObservation {
            isolation: "repeatable read".into(),
            read_only: true,
            backend_pid: 42,
            write_lock: true,
            copy_lock: true,
            prune_lock: true,
        },
        history: capture::History::UnprunedFromDeploymentStart {
            history_blocks: i32::MAX as u64,
            earliest_block: INITIAL_BLOCK - 1,
            table_last_pruned_block: header
                .binding
                .type_ordinals
                .iter()
                .map(|n| (n.clone(), None))
                .collect(),
        },
        catalog_sha256: binding.catalog_sha256.clone(),
        sources: capture::SourceCommitment {
            count: header.sources.count,
            max_vid: header.sources.max_vid,
            order_sha256: header.sources.order_sha256.clone(),
        },
        captured_rows: counts,
    };
    let pins = CapturedSeedPins {
        seed_manifest_sha256: Sha256::digest(manifest.encode().unwrap()).into(),
        capture_binding: binding,
        engine_lineage: snap::initial_lineage(digest),
    };
    (bytes, manifest, pins)
}

fn import_captured(
    root: &Path,
    snapshot: &[u8],
    manifest: &capture::Manifest,
    pins: CapturedSeedPins,
) -> Result<DurableStore> {
    let (input, binding) = bindings();
    DurableStore::import_captured_snapshot(
        root,
        &input,
        binding,
        snapshot,
        &manifest.encode().unwrap(),
        pins,
        1024 * 1024,
    )
}

#[test]
fn typed_capture_matches_real_seeded_images_and_remains_verified_after_replay_and_rewind() {
    for oracle in [false, true] {
        let t = tempfile::tempdir().unwrap();
        let (bytes, captured, pins) = captured_fixture(oracle);
        let root = t.path().join("captured");
        let seeded = import_captured(&root, &bytes, &captured, pins).unwrap();
        seeded.require_complete_seed_history().unwrap();
        let initial = seeded.manifest().unwrap();
        assert_eq!(initial.require_loadable().is_err(), oracle);
        let source = store(&t.path().join("source"));
        let first = run(&source, &[first()], &t.path().join("source-first"));
        assert_eq!(first.full_state_sha256, initial.full_state_sha256);
        let block = initialized();
        let expected = run(
            &source,
            std::slice::from_ref(&block),
            &t.path().join("source-next"),
        );
        let actual = run(&seeded, &[block], &t.path().join("seed-next"));
        assert_eq!(actual.full_state_sha256, expected.full_state_sha256);
        assert_eq!(
            fs::read(t.path().join("source-next/frames.bcf1")).unwrap(),
            fs::read(t.path().join("seed-next/frames.bcf1")).unwrap()
        );
        assert_eq!(actual.require_loadable().is_err(), oracle);
        assert_eq!(seeded.rewind_one(&actual).unwrap(), initial);
        drop(seeded);
        let (input, binding) = bindings();
        let reopened = DurableStore::open(&root, &input, binding, 1024 * 1024).unwrap();
        reopened.require_complete_seed_history().unwrap();
        let evidence: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join("seed-import.json")).unwrap()).unwrap();
        assert_eq!(evidence["capture_manifest_verified"], true);
        assert_eq!(evidence["production_selectable"], false);
        fs::write(root.join("seed-manifest.bin"), b"changed").unwrap();
        assert!(reopened.require_complete_seed_history().is_err());
        assert!(reopened.manifest().is_err());
    }
}

#[test]
fn development_history_assertion_cannot_pass_runtime_seed_gate() {
    let t = tempfile::tempdir().unwrap();
    let (h, records) = fixture();
    let bytes = encode(h.clone(), &records);
    let dev = import(&t.path().join("dev"), &bytes, pins(&h, &bytes)).unwrap();
    assert!(dev
        .require_complete_seed_history()
        .unwrap_err()
        .0
        .contains("verified capture"));
    store(&t.path().join("root"))
        .require_complete_seed_history()
        .unwrap();
}

#[test]
fn unproven_history_and_wrong_locked_schema_refuse_before_creating_state() {
    for variant in 0..3 {
        let t = tempfile::tempdir().unwrap();
        let (bytes, mut captured, mut pins) = captured_fixture(false);
        if variant == 0 {
            captured.history = capture::History::Unproven {
                reason: "pruned source".into(),
            };
        } else if variant == 1 {
            captured.binding.schema_sha256 = "aa".repeat(32);
            captured.deployment.schema_sha256 = captured.binding.schema_sha256.clone();
            pins.capture_binding = captured.binding.clone();
        } else {
            pins.engine_lineage = [42; 32];
        }
        pins.seed_manifest_sha256 = Sha256::digest(captured.encode().unwrap()).into();
        let root = t.path().join("state");
        assert!(import_captured(&root, &bytes, &captured, pins).is_err());
        assert!(!root.exists());
    }
}

#[test]
fn corrupt_or_incomplete_capture_stream_never_commits_imported_rows() {
    for variant in 0..3 {
        let t = tempfile::tempdir().unwrap();
        let (mut bytes, captured, pins) = captured_fixture(false);
        match variant {
            0 => {
                bytes.pop();
            }
            1 => bytes.push(0),
            _ => {
                let n = bytes.len() - 10;
                bytes[n] ^= 1;
            }
        }
        let root = t.path().join("state");
        assert!(import_captured(&root, &bytes, &captured, pins).is_err());
        let (input, binding) = bindings();
        assert!(DurableStore::open(&root, &input, binding, 1024 * 1024).is_err());
        assert!(!root.join("seed-import.json").exists());
    }
}
