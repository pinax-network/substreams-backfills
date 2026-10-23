//! Real public executable and private-pipe control, using an explicitly synthetic
//! tiny package. These test protocol behavior, never historical/OCI qualification.
use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    identity::build_descriptor,
    pb,
    runtime::{
        self, hash, json_bytes, pin, ExtractorLock, FamilyContract, RuntimeManifest,
        SourceManifest, VerifiedRuntime,
    },
};
use backfill_common::{
    clock::{self, Frame, FrameKind},
    descriptor::ExtractorIdentity,
    producer_checkpoint::Manifest,
    state_snapshot::Boundary,
    upstream_completion::Request,
};
use prost::Message;
use std::{
    collections::BTreeMap,
    fs,
    path::Path,
    process::{Command, Output},
};

fn setup(root: &Path) -> VerifiedRuntime {
    for dir in ["bin", "contract", "spkg"] {
        fs::create_dir(root.join(dir)).unwrap();
    }
    fs::copy(env!("CARGO_BIN_EXE_producer"), root.join("bin/producer")).unwrap();
    let source = "33".repeat(20);
    let identity: ExtractorIdentity = serde_json::from_slice(include_bytes!(
        "../fixtures/runtime/synthetic-extractor-identity.json"
    ))
    .unwrap();
    let descriptor = build_descriptor(&identity, &source, true).unwrap();
    fs::write(
        root.join("contract/block-changes-descriptor.json.sha256"),
        format!("{}\n", hash(&descriptor)),
    )
    .unwrap();
    fs::write(
        root.join("contract/block-changes-descriptor.json"),
        descriptor,
    )
    .unwrap();
    fs::write(
        root.join("contract/compatibility.json"),
        json_bytes(&FamilyContract::aerodrome()).unwrap(),
    )
    .unwrap();
    fs::write(
        root.join("spkg/extractor.spkg"),
        include_bytes!("../fixtures/runtime/synthetic-extractor.spkg"),
    )
    .unwrap();
    fs::write(
        root.join("spkg/extractor-identity.json"),
        json_bytes(&identity).unwrap(),
    )
    .unwrap();
    fs::write(
        root.join("spkg/extractor-lock.json"),
        json_bytes(&ExtractorLock {
            format: "pinax.backfill.extractor-lock/v1".into(),
            source_commit: source.clone(),
            production_selectable: false,
            identity,
        })
        .unwrap(),
    )
    .unwrap();
    fs::write(
        root.join("source.json"),
        json_bytes(&SourceManifest {
            format: "pinax.backfill.producer-source/v1".into(),
            repository: "pinax-network/substreams-backfills".into(),
            source_commit: source.clone(),
            files: BTreeMap::from([(
                "SYNTHETIC-TEST-ONLY".into(),
                pin(b"fixture, not source build evidence"),
            )]),
        })
        .unwrap(),
    )
    .unwrap();
    fs::write(
        root.join("runtime.json"),
        json_bytes(&RuntimeManifest {
            format: runtime::FORMAT.into(),
            protocol: runtime::PROTOCOL.into(),
            family: runtime::FAMILY.into(),
            production_selectable: false,
            source_commit: source,
            files: runtime::FILES
                .into_iter()
                .map(|p| (p.into(), pin(&fs::read(root.join(p)).unwrap())))
                .collect(),
        })
        .unwrap(),
    )
    .unwrap();
    VerifiedRuntime::load(root, None).unwrap()
}
fn command(root: &Path, allow: bool, args: &[&str]) -> Output {
    let mut c = Command::new(root.join("bin/producer"));
    c.args([
        "--runtime-sha256",
        &hash(&fs::read(root.join("runtime.json")).unwrap()),
    ]);
    if allow {
        c.arg("--allow-non-final");
    }
    c.args(args).output().unwrap()
}
fn success(out: Output) -> Vec<u8> {
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    out.stdout
}
fn text(path: &Path) -> &str {
    path.to_str().unwrap()
}

#[test]
fn public_runtime_stages_exact_bytes_and_requires_explicit_nonfinal_execution() {
    let t = tempfile::tempdir().unwrap();
    let bundle = t.path().join("bundle");
    fs::create_dir(&bundle).unwrap();
    setup(&bundle);
    let manifest = fs::read(bundle.join("runtime.json")).unwrap();
    assert_eq!(
        success(command(&bundle, false, &["version", "--json"])),
        manifest
    );
    let staged = t.path().join("staged");
    success(command(&bundle, false, &["stage", "--dest", text(&staged)]));
    assert_eq!(
        success(command(&staged, false, &["version", "--json"])),
        manifest
    );
    assert!(
        !command(&bundle, false, &["stage", "--dest", text(&staged)])
            .status
            .success()
    );
    let state = t.path().join("state");
    let start = INITIAL_BLOCK.to_string();
    let lineage = "66".repeat(32);
    let args = [
        "seed",
        "--empty",
        "--start-block",
        &start,
        "--out",
        text(&state),
        "--engine-lineage",
        &lineage,
        "--cache-mib",
        "1",
    ];
    assert_eq!(command(&staged, false, &args).status.code(), Some(5));
    assert!(!state.exists());
    let initial: Manifest =
        serde_json::from_slice(&success(command(&staged, true, &args))).unwrap();
    assert_eq!(initial.boundary.block_number, INITIAL_BLOCK - 1);
    assert_eq!(initial.binding.family, runtime::CHECKPOINT_FAMILY);
    assert_eq!(
        initial.binding.extractor_lock_sha256,
        hash(&fs::read(staged.join("spkg/extractor-lock.json")).unwrap())
    );
    let inspected: Manifest = serde_json::from_slice(&success(command(
        &staged,
        true,
        &["inspect", "--state-dir", text(&state)],
    )))
    .unwrap();
    assert_eq!(initial, inspected);
    for bad in [
        vec!["inspect", "--state-dir"],
        vec![
            "inspect",
            "--state-dir",
            text(&state),
            "--producer-binding",
            "fake",
        ],
        vec![
            "seed",
            "--empty",
            "--start-block",
            "1",
            "--out",
            "no-state",
            "--engine-lineage",
            &lineage,
        ],
    ] {
        assert_eq!(command(&staged, true, &bad).status.code(), Some(2));
    }
    let out = Command::new(staged.join("bin/producer"))
        .args(["--runtime-sha256", &"00".repeat(32), "version", "--json"])
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(4));
}

#[test]
#[cfg(unix)]
fn public_reduce_requires_real_private_completion_then_supports_exact_rewind() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    let bundle = root.join("bundle");
    fs::create_dir(&bundle).unwrap();
    let runtime = setup(&bundle);
    let state = root.join("state");
    let lineage = "66".repeat(32);
    let initial: Manifest = serde_json::from_slice(&success(command(
        &bundle,
        true,
        &[
            "seed",
            "--empty",
            "--start-block",
            &INITIAL_BLOCK.to_string(),
            "--out",
            text(&state),
            "--engine-lineage",
            &lineage,
            "--cache-mib",
            "1",
        ],
    )))
    .unwrap();
    let mut b = pb::ExtractorBlock::decode(
        include_bytes!("../fixtures/first-pool-extractor.pb").as_slice(),
    )
    .unwrap();
    b.number = INITIAL_BLOCK;
    b.candidates.truncate(1);
    let c = b.calls.as_mut().unwrap();
    c.ticks.clear();
    c.positions.clear();
    c.fee_growth.clear();
    c.get_pool.clear();
    let mut input = vec![];
    clock::write_frame(
        &mut input,
        &Frame {
            kind: FrameKind::Observed,
            block_number: b.number,
            block_hash: b.hash.clone().try_into().unwrap(),
            payload: b.encode_to_vec(),
        },
    )
    .unwrap();
    fs::write(root.join("input"), input).unwrap();
    let python = Command::new("python3").args(["-c", "import hashlib,sys;print(hashlib.sha256(open(sys.executable,'rb').read()).hexdigest())"]).output().unwrap();
    let request = Request {
        binding: runtime.producer_binding(),
        attempt_nonce: "77".repeat(32),
        substreams_native_sha256: String::from_utf8(success(python)).unwrap().trim().into(),
        from: INITIAL_BLOCK,
        stop_exclusive: INITIAL_BLOCK + 1,
        predecessor: initial.boundary.clone(),
        observed_parent_hash: hex::encode(&b.parent_hash),
        reducer_lineage_before: initial.reducer_lineage.clone(),
        engine_lineage_before: lineage,
    };
    fs::write(
        root.join("stream-request.json"),
        serde_json::to_vec(&request).unwrap(),
    )
    .unwrap();
    for case in ["failed-native", "bad-digest", "success"] {
        let output = root.join(case);
        let args = vec![
            text(&bundle.join("bin/producer")).to_owned(),
            "--allow-non-final".into(),
            "reduce".into(),
            "--runtime-sha256".into(),
            hash(runtime.manifest_bytes()),
            "--state-dir".into(),
            text(&state).into(),
            "--cache-mib".into(),
            "1".into(),
            "--from".into(),
            INITIAL_BLOCK.to_string(),
            "--stop-exclusive".into(),
            (INITIAL_BLOCK + 1).to_string(),
            "--expected-parent-hash".into(),
            request.observed_parent_hash.clone(),
            "--expected-head-block".into(),
            initial.boundary.block_number.to_string(),
            "--expected-head-hash".into(),
            hex::encode(initial.boundary.block_hash),
            "--expected-reducer-lineage".into(),
            initial.reducer_lineage.clone(),
            "--engine-lineage".into(),
            request.engine_lineage_before.clone(),
            "--attempt-nonce".into(),
            request.attempt_nonce.clone(),
            "--substreams-native-sha256".into(),
            request.substreams_native_sha256.clone(),
            "--output".into(),
            text(&output).into(),
        ];
        fs::write(root.join("stream-config.json"), serde_json::to_vec(&serde_json::json!({"args":args,"request":request,"output":output,"head":Boundary {block_number:b.number,block_hash:b.hash.clone().try_into().unwrap()}})).unwrap()).unwrap();
        let result = Command::new("python3")
            .arg(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/tests/support/stream_supervisor.py"
            ))
            .arg(root)
            .arg(case)
            .output()
            .unwrap();
        let result: serde_json::Value = serde_json::from_slice(&success(result)).unwrap();
        let current: Manifest = serde_json::from_slice(&success(command(
            &bundle,
            true,
            &["inspect", "--state-dir", text(&state)],
        )))
        .unwrap();
        if case == "success" {
            assert_eq!(
                result["producer_exit"],
                0,
                "{}",
                fs::read_to_string(root.join(format!("{case}.stderr"))).unwrap()
            );
            assert_eq!(current.boundary.block_number, INITIAL_BLOCK);
            assert!(output.join("complete.json").exists());
            assert_eq!(
                fs::read(output.join("frames.bcf1")).unwrap(),
                fs::read(root.join(format!("{case}.stdout"))).unwrap()
            );
            let before = initial.boundary.block_number.to_string();
            let hash = hash(&current.encode().unwrap());
            let zero = "00".repeat(32);
            let rewind = [
                "rewind",
                "--state-dir",
                text(&state),
                "--expected-checkpoint-sha256",
                &hash,
                "--to-block",
                &before,
                "--to-hash",
                &zero,
            ];
            let rewound: Manifest =
                serde_json::from_slice(&success(command(&bundle, true, &rewind))).unwrap();
            assert_eq!(rewound, initial);
        } else {
            assert_ne!(result["producer_exit"], 0);
            assert_eq!(current, initial);
            assert!(!output.join("complete.json").exists());
        }
    }
}

#[test]
fn public_runtime_cannot_reuse_an_opaque_development_seed() {
    use aerodrome_slipstream_reducer::durable::{
        DurableStore, SeedImportPins, SourceHistoryAssertion,
    };
    use backfill_common::{producer_checkpoint::SnapshotPurpose, state_snapshot as snap};
    use sha2::{Digest, Sha256};
    let t = tempfile::tempdir().unwrap();
    let bundle = t.path().join("bundle");
    fs::create_dir(&bundle).unwrap();
    let runtime = setup(&bundle);
    let input = runtime.input_binding();
    let cap = input.compatibility().capabilities().unwrap();
    let boundary = Boundary {
        block_number: INITIAL_BLOCK,
        block_hash: [9; 32],
    };
    let header = snap::SnapshotHeader {
        format: snap::FORMAT.into(),
        version: snap::VERSION,
        binding: snap::SnapshotBinding {
            deployment: cap.deployment.clone(),
            network: "base".into(),
            descriptor_sha256: hex::encode(input.compatibility().id()),
            retention_sha256: hex::encode(cap.retention_sha256()),
            type_ordinals: cap.storage_profile.entity_types.clone(),
            entity_id_policy: snap::EntityIdPolicy::StringOnly,
        },
        boundary: boundary.clone(),
        origin: snap::SnapshotOrigin::Oracle {
            seed: snap::SeedOrigin {
                schema: "sgd1".into(),
                site_id: 1,
                database: "synthetic".into(),
                system_identifier: "12345".into(),
                server_version_num: 160000,
                capture_tool_sha256: "08".repeat(32),
                profile_sha256: "07".repeat(32),
                head: boundary.clone(),
                health: "healthy".into(),
                non_fatal_errors: vec![],
            },
        },
        vid: None,
        poi: Default::default(),
        sources: snap::SourceSnapshot::from_rows(vec![]).unwrap(),
        period_max: Default::default(),
        entity_count: None,
        records: 0,
    };
    let (snapshot, verified) =
        snap::SnapshotWriter::new(Vec::new(), header, snap::Limits::default())
            .unwrap()
            .finish()
            .unwrap();
    let evidence = b"opaque fixture; deliberately no typed capture";
    let pins = SeedImportPins {
        snapshot_sha256: verified.file_sha256(),
        seed_manifest_sha256: Sha256::digest(evidence).into(),
        profile_sha256: [7; 32],
        boundary,
        purpose: SnapshotPurpose::Oracle,
        source_history: SourceHistoryAssertion::CompleteSuccessfulSourcesNoFailedHosts,
        engine_lineage: verified.lineage(),
    };
    let state = t.path().join("state");
    let store = DurableStore::import_snapshot(
        &state,
        &input,
        runtime.producer_binding(),
        snapshot.as_slice(),
        evidence,
        pins,
        1024 * 1024,
    )
    .unwrap();
    let before = store.manifest().unwrap();
    drop(store);
    let out = command(&bundle, true, &["inspect", "--state-dir", text(&state)]);
    assert_eq!(out.status.code(), Some(4));
    assert!(String::from_utf8(out.stderr)
        .unwrap()
        .contains("seed history requires verified capture evidence"));
    let reopened =
        DurableStore::open(&state, &input, runtime.producer_binding(), 1024 * 1024).unwrap();
    assert_eq!(before, reopened.manifest().unwrap());
}
