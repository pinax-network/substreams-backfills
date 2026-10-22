use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    identity::{build_descriptor, OUTPUT_MODULE, OUTPUT_TYPE},
    pb,
};
use backfill_common::{
    clock::{self, Frame, FrameKind},
    descriptor::ExtractorIdentity,
    producer_checkpoint::{Binding, Manifest},
};
use prost::Message;
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::Path,
    process::{Command, Output},
};
fn setup(root: &Path) -> (pb::ExtractorBlock, Vec<u8>) {
    let x = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let descriptor = build_descriptor(&x, &"33".repeat(20), true).unwrap();
    let binding = Binding {
        family: "aerodrome-slipstream".into(),
        deployment: aerodrome_extractor_core::config::DEPLOYMENT.into(),
        network: "base".into(),
        descriptor_sha256: hex::encode(Sha256::digest(&descriptor)),
        extractor_lock_sha256: "44".repeat(32),
        spkg_sha256: x.spkg_sha256.clone(),
        module: x.module.clone(),
        module_hash: x.module_hash.clone(),
        reducer_commit: "33".repeat(20),
        reducer_binary_sha256: hex::encode(Sha256::digest(
            fs::read(env!("CARGO_BIN_EXE_aerodrome-durable-fixture")).unwrap(),
        )),
    };
    fs::write(root.join("descriptor"), descriptor).unwrap();
    fs::write(root.join("identity"), serde_json::to_vec(&x).unwrap()).unwrap();
    fs::write(root.join("binding"), serde_json::to_vec(&binding).unwrap()).unwrap();
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
    let mut bytes = vec![];
    clock::write_frame(
        &mut bytes,
        &Frame {
            kind: FrameKind::Observed,
            block_number: b.number,
            block_hash: b.hash.clone().try_into().unwrap(),
            payload: b.encode_to_vec(),
        },
    )
    .unwrap();
    fs::write(root.join("input"), &bytes).unwrap();
    (b, bytes)
}
fn command(root: &Path, name: &str, extra: &[(&str, String)]) -> Output {
    let descriptor = fs::read(root.join("descriptor")).unwrap();
    let mut c = Command::new(env!("CARGO_BIN_EXE_aerodrome-durable-fixture"));
    c.arg(name)
        .arg("--state-dir")
        .arg(root.join("state"))
        .arg("--descriptor")
        .arg(root.join("descriptor"))
        .arg("--descriptor-sha256")
        .arg(hex::encode(Sha256::digest(descriptor)))
        .arg("--extractor-identity")
        .arg(root.join("identity"))
        .arg("--producer-binding")
        .arg(root.join("binding"))
        .args(["--cache-mib", "1"]);
    for (k, v) in extra {
        c.arg(k).arg(v);
    }
    c.output().unwrap()
}
fn success(out: Output) -> Vec<u8> {
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    out.stdout
}
#[test]
fn offline_cli_checks_executable_input_digest_exact_head_and_rewind_pin() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    let (b, bytes) = setup(root);
    let initial = success(command(
        root,
        "init",
        &[("--engine-lineage", "66".repeat(32))],
    ));
    let initial: Manifest = serde_json::from_slice(&initial).unwrap();
    assert!(
        !command(root, "init", &[("--engine-lineage", "66".repeat(32))])
            .status
            .success()
    );
    let mut opts = vec![
        ("--input", root.join("input").display().to_string()),
        ("--input-sha256", "aa".repeat(32)),
        ("--from", INITIAL_BLOCK.to_string()),
        ("--stop-exclusive", (INITIAL_BLOCK + 1).to_string()),
        ("--expected-parent-hash", hex::encode(&b.parent_hash)),
        ("--expected-head-block", (INITIAL_BLOCK - 1).to_string()),
        ("--expected-head-hash", "00".repeat(32)),
        (
            "--expected-reducer-lineage",
            initial.reducer_lineage.clone(),
        ),
        ("--engine-lineage", "66".repeat(32)),
        ("--output", root.join("bad").display().to_string()),
        ("--full-state-digest", "true".into()),
    ];
    assert!(!command(root, "reduce", &opts).status.success());
    assert!(!root.join("bad/complete.json").exists());
    let observed: Manifest =
        serde_json::from_slice(&success(command(root, "inspect", &[]))).unwrap();
    assert_eq!(observed, initial);
    opts.iter_mut()
        .find(|(k, _)| *k == "--input-sha256")
        .unwrap()
        .1 = hex::encode(Sha256::digest(bytes));
    opts.iter_mut().find(|(k, _)| *k == "--output").unwrap().1 =
        root.join("good").display().to_string();
    success(command(root, "reduce", &opts));
    assert!(root.join("good/complete.json").exists());
    let current: Manifest =
        serde_json::from_slice(&success(command(root, "inspect", &[]))).unwrap();
    assert_eq!(current.sources.count, 1);
    let mut rewind = vec![
        ("--expected-checkpoint-sha256", "aa".repeat(32)),
        ("--to-block", initial.boundary.block_number.to_string()),
        ("--to-hash", hex::encode(initial.boundary.block_hash)),
    ];
    assert!(!command(root, "rewind", &rewind).status.success());
    rewind[0].1 = hex::encode(Sha256::digest(current.encode().unwrap()));
    let got: Manifest = serde_json::from_slice(&success(command(root, "rewind", &rewind))).unwrap();
    assert_eq!(got, initial);
    let mut binding: Binding =
        serde_json::from_slice(&fs::read(root.join("binding")).unwrap()).unwrap();
    binding.reducer_binary_sha256 = "aa".repeat(32);
    fs::write(root.join("binding"), serde_json::to_vec(&binding).unwrap()).unwrap();
    assert!(!command(root, "inspect", &[]).status.success());
}

#[cfg(unix)]
#[test]
fn supervised_stream_waits_for_real_upstream_exit_and_exact_private_control() {
    use backfill_common::{state_snapshot::Boundary, upstream_completion::Request};
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    let (b, _) = setup(root);
    let initial: Manifest = serde_json::from_slice(&success(command(
        root,
        "init",
        &[("--engine-lineage", "66".repeat(32))],
    )))
    .unwrap();
    let descriptor = fs::read(root.join("descriptor")).unwrap();
    let binding: Binding =
        serde_json::from_slice(&fs::read(root.join("binding")).unwrap()).unwrap();
    let python = Command::new("python3").args(["-c", "import hashlib,sys;print(hashlib.sha256(open(sys.executable,'rb').read()).hexdigest())"]).output().unwrap();
    assert!(python.status.success());
    let request = Request {
        binding,
        attempt_nonce: "77".repeat(32),
        substreams_native_sha256: String::from_utf8(python.stdout).unwrap().trim().into(),
        from: INITIAL_BLOCK,
        stop_exclusive: INITIAL_BLOCK + 1,
        predecessor: initial.boundary.clone(),
        observed_parent_hash: hex::encode(&b.parent_hash),
        reducer_lineage_before: initial.reducer_lineage.clone(),
        engine_lineage_before: "66".repeat(32),
    };
    fs::write(
        root.join("stream-request.json"),
        serde_json::to_vec_pretty(&request).unwrap(),
    )
    .unwrap();
    for case in [
        "bad-nonce",
        "bad-digest",
        "stale-lineage",
        "short-control",
        "extra-control",
        "failed-native",
        "short-input",
        "regular-control",
        "success",
    ] {
        let output = root.join(case);
        let args = vec![
            env!("CARGO_BIN_EXE_aerodrome-durable-fixture").into(),
            "stream".into(),
            "--state-dir".into(),
            root.join("state").display().to_string(),
            "--descriptor".into(),
            root.join("descriptor").display().to_string(),
            "--descriptor-sha256".into(),
            hex::encode(Sha256::digest(&descriptor)),
            "--extractor-identity".into(),
            root.join("identity").display().to_string(),
            "--producer-binding".into(),
            root.join("binding").display().to_string(),
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
            output.display().to_string(),
        ];
        let config = serde_json::json!({"args":args,"request":request,"output":output,
            "head":Boundary {block_number:b.number,block_hash:b.hash.clone().try_into().unwrap()}});
        fs::write(
            root.join("stream-config.json"),
            serde_json::to_vec(&config).unwrap(),
        )
        .unwrap();
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
        let current: Manifest =
            serde_json::from_slice(&success(command(root, "inspect", &[]))).unwrap();
        if case == "success" {
            assert_eq!(
                result["producer_exit"],
                0,
                "{}",
                fs::read_to_string(root.join(format!("{case}.stderr"))).unwrap()
            );
            assert_eq!(result["native_exit"], 0);
            assert_eq!(current.boundary.block_number, INITIAL_BLOCK);
            assert_eq!(current.sources.count, 1);
            assert!(output.join("complete.json").exists());
            assert!(output.join("upstream-completion.json").exists());
            assert_eq!(
                fs::read(output.join("frames.bcf1")).unwrap(),
                fs::read(root.join(format!("{case}.stdout"))).unwrap()
            );
        } else {
            assert_ne!(result["producer_exit"], 0, "{case}");
            assert_eq!(current, initial, "{case}");
            assert!(!output.join("complete.json").exists(), "{case}");
        }
    }
}
