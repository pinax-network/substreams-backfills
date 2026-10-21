use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    identity::{build_descriptor, OUTPUT_MODULE, OUTPUT_TYPE},
    pb,
};
use backfill_common::{
    clock::{self, Frame, FrameKind},
    descriptor::ExtractorIdentity,
};
use prost::Message;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::Path,
    process::{Command, Output},
};

fn fixture() -> (pb::ExtractorBlock, Vec<u8>) {
    let mut b = pb::ExtractorBlock::decode(
        include_bytes!("../fixtures/first-pool-extractor.pb").as_slice(),
    )
    .unwrap();
    // Synthetic Factory block at the root, retaining the independent raw log
    // and metadata answers. This tests CLI lifecycle, not historical parity.
    b.number = INITIAL_BLOCK;
    b.candidates.truncate(1);
    let calls = b.calls.as_mut().unwrap();
    calls.ticks.clear();
    calls.positions.clear();
    calls.fee_growth.clear();
    calls.get_pool.clear();
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
    (b, bytes)
}
fn run(root: &Path, output: &Path, bytes: &[u8], sha: &str, stop: u64) -> Output {
    let (b, _) = fixture();
    let identity = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let descriptor = build_descriptor(&identity, &"33".repeat(20), true).unwrap();
    fs::write(root.join("input"), bytes).unwrap();
    fs::write(root.join("descriptor"), &descriptor).unwrap();
    fs::write(
        root.join("identity"),
        serde_json::to_vec(&identity).unwrap(),
    )
    .unwrap();
    Command::new(env!("CARGO_BIN_EXE_aerodrome-replay-fixture"))
        .arg("--input")
        .arg(root.join("input"))
        .arg("--input-sha256")
        .arg(sha)
        .arg("--descriptor")
        .arg(root.join("descriptor"))
        .arg("--descriptor-sha256")
        .arg(hex::encode(Sha256::digest(&descriptor)))
        .arg("--extractor-identity")
        .arg(root.join("identity"))
        .arg("--from")
        .arg(INITIAL_BLOCK.to_string())
        .arg("--stop-exclusive")
        .arg(stop.to_string())
        .arg("--expected-parent-hash")
        .arg(hex::encode(b.parent_hash))
        .arg("--output")
        .arg(output)
        .output()
        .unwrap()
}

#[test]
fn offline_artifact_replay_executes_handlers_and_refuses_clobber() {
    let temp = tempfile::tempdir().unwrap();
    let (_, bytes) = fixture();
    let sha = hex::encode(Sha256::digest(&bytes));
    let output = temp.path().join("attempt");
    let done = run(temp.path(), &output, &bytes, &sha, INITIAL_BLOCK + 1);
    assert!(
        done.status.success(),
        "{}",
        String::from_utf8_lossy(&done.stderr)
    );
    let receipt: Value =
        serde_json::from_slice(&fs::read(output.join("complete.json")).unwrap()).unwrap();
    assert_eq!(receipt["handlers"], 1);
    assert_eq!(receipt["sources"], 1);
    assert_eq!(receipt["entities"], 5);
    assert_eq!(receipt["production_qualified"], false);
    assert_eq!(receipt["producer_receipt"], false);
    let original = fs::read(output.join("frames.bcf1")).unwrap();
    assert_eq!(
        receipt["frames_sha256"],
        hex::encode(Sha256::digest(&original))
    );
    assert!(!run(temp.path(), &output, &bytes, &sha, INITIAL_BLOCK + 1)
        .status
        .success());
    assert_eq!(fs::read(output.join("frames.bcf1")).unwrap(), original);
}
#[test]
fn bad_digest_short_range_and_truncation_never_publish_completion() {
    let temp = tempfile::tempdir().unwrap();
    let (_, bytes) = fixture();
    let sha = hex::encode(Sha256::digest(&bytes));
    for (name, data, digest, stop) in [
        (
            "digest",
            bytes.as_slice(),
            "00".repeat(32),
            INITIAL_BLOCK + 1,
        ),
        ("range", bytes.as_slice(), sha.clone(), INITIAL_BLOCK + 2),
        (
            "truncated",
            &bytes[..bytes.len() - 1],
            sha,
            INITIAL_BLOCK + 1,
        ),
    ] {
        let output = temp.path().join(name);
        let result = run(temp.path(), &output, data, &digest, stop);
        assert!(!result.status.success(), "{name}");
        assert!(result.stdout.is_empty());
        assert!(!output.join("complete.json").exists());
        assert!(!output.join("frames.bcf1").exists());
        assert!(output.join("failure.json").exists());
    }
}
