//! The live-mode CLI surface, hermetically.
//!
//! Every case here is a **refusal**, and every refusal happens before any socket
//! is opened: the endpoint string is validated first, `--resume` is refused
//! before that, and the range is checked against the segment bundle before
//! `sf.firehose.v2.Stream/Blocks` is dialled. So none of these tests needs the
//! network, and `FIREHOSE_ENDPOINT` is set to an address nothing listens on to
//! prove it.
//!
//! The happy path is deliberately not tested here. It needs a real endpoint and
//! a real token, which is what the live smoke run in `README.md` is for; CI runs
//! the committed fixtures only.

use std::path::PathBuf;
use std::process::{Command, Output};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";

/// Segment 1's own first block, from `manifest.yaml`.
const SEGMENT_START: i32 = 12369621;

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// Run `graph-mapping-host run` with a deliberately dead endpoint, and return
/// the combined failure output.
fn run(endpoint: Option<&str>, args: &[&str]) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_graph-mapping-host"));
    command
        .current_dir(crate_dir())
        .arg("run")
        .arg("--segment")
        .arg(format!("segments/{SEGMENT}"))
        .arg("--cassette")
        .arg(format!("fixtures/cassettes/{SEGMENT}.json"))
        .args(args)
        // Never inherit a real token, and never inherit a real endpoint.
        .env_remove("FIREHOSE_API_TOKEN")
        .env_remove("SUBSTREAMS_API_TOKEN")
        .env_remove("ETHEREUM_RPC_URL")
        .env_remove("FIREHOSE_ENDPOINT");
    if let Some(endpoint) = endpoint {
        command.env("FIREHOSE_ENDPOINT", endpoint);
    }
    command.output().expect("running graph-mapping-host")
}

fn failure(endpoint: Option<&str>, args: &[&str]) -> String {
    let output = run(endpoint, args);
    assert!(
        !output.status.success(),
        "expected a refusal, got success:\n{}",
        String::from_utf8_lossy(&output.stdout)
    );
    String::from_utf8_lossy(&output.stderr).into_owned()
}

/// An address on the loopback interface with nothing behind it. If a refusal
/// ever stops short of the network, the test fails on a connection error rather
/// than passing quietly.
const DEAD_ENDPOINT: &str = "127.0.0.1:1";

#[test]
fn a_credentialed_endpoint_is_refused_before_anything_else() {
    let error = failure(
        Some("someone:hunter2@eth.firehose.pinax.network:443"),
        &["--from", "12369739", "--to", "12369741"],
    );
    assert!(error.contains("userinfo"), "{error}");
    assert!(error.contains("FIREHOSE_API_TOKEN"), "{error}");
    // The endpoint is parsed before the bundle is loaded, so nothing about the
    // segment can appear in this message.
    assert!(!error.contains("bundle.lock.json"), "{error}");
}

#[test]
fn a_live_run_needs_an_endpoint() {
    let error = failure(None, &["--from", "12369739", "--to", "12369741"]);
    assert!(error.contains("FIREHOSE_ENDPOINT"), "{error}");
    assert!(error.contains("no endpoint is compiled in"), "{error}");
}

/// `--resume` is gone. It still parses, so a command line written against the
/// old flag gets a pointer at the two that replaced it rather than clap's
/// "unexpected argument".
#[test]
fn resume_points_at_the_checkpoint_flags() {
    let error = failure(
        Some(DEAD_ENDPOINT),
        &["--from", "12369739", "--to", "12369741", "--resume"],
    );
    assert!(error.contains("--resume is gone"), "{error}");
    assert!(error.contains("--checkpoint-out"), "{error}");
    assert!(error.contains("--checkpoint-in"), "{error}");
}

/// A continuation must start exactly where the checkpoint stopped, and that is
/// decided from the checkpoint's own header before the endpoint is dialled.
#[test]
fn a_live_range_that_does_not_continue_the_checkpoint_is_refused() {
    let temp = tempfile::tempdir().expect("temp dir");
    let path = temp.path().join("chunk-1.jsonl");
    write_boundary_checkpoint(&path, 12_369_739);

    // One block short: 12,369,739 is already in the checkpoint.
    let error = failure(
        Some(DEAD_ENDPOINT),
        &[
            "--from",
            "12369739",
            "--to",
            "12369741",
            "--checkpoint-in",
            path.to_str().expect("utf-8"),
        ],
    );
    assert!(
        error.contains("does not continue this checkpoint"),
        "{error}"
    );
    assert!(error.contains("stops after block 12369739"), "{error}");
    assert!(!error.to_lowercase().contains("connect"), "{error}");

    // One block past: 12,369,741 would skip 12,369,740.
    let error = failure(
        Some(DEAD_ENDPOINT),
        &[
            "--from",
            "12369741",
            "--to",
            "12369743",
            "--checkpoint-in",
            path.to_str().expect("utf-8"),
        ],
    );
    assert!(error.contains("skip the blocks between"), "{error}");
    assert!(!error.to_lowercase().contains("connect"), "{error}");
}

/// A checkpoint whose header names a boundary and nothing else. Enough for the
/// range check, which happens before the bundle is loaded, and deliberately not
/// a real one: this file never replays a block.
fn write_boundary_checkpoint(path: &std::path::Path, block: i32) {
    let header = serde_json::json!({
        "schema": "pinax.substreams-backfills.mapping-host.checkpoint/v2",
        "identity": {
            "deployment": SEGMENT,
            "network": "mainnet",
            "spec_version": "0.0.4",
            "poi_version": "legacy",
            "poi_causality_region": "ethereum/mainnet",
            "deterministic_error_policy": "fatal",
            "graph_node_rev": "unset",
            "bundle_lock_sha256": "unset",
            "descriptor_sha256": "unset",
        },
        "cassette": { "mode": "exact", "sha256": "unset" },
        "boundary": {
            "block": block,
            "block_hash": "0x00",
            "source": "test",
            "blocks_in_chunk": 1,
            "blocks_total": 1,
            "chunk_index": 0,
        },
        "totals": {
            "dynamic_data_sources": 0,
            "rows": 0,
            "poi_rows": 0,
            "fields": 0,
            "cached_present": 0,
            "cached_absent": 0,
        },
        "counts_by_type": {},
    });
    std::fs::write(path, format!("{header}\n")).expect("writing a checkpoint header");
}

#[test]
fn a_range_outside_the_segment_is_refused_before_the_stream_is_opened() {
    // One block below segment 1's first block.
    let error = failure(
        Some(DEAD_ENDPOINT),
        &[
            "--from",
            &(SEGMENT_START - 1).to_string(),
            "--to",
            &(SEGMENT_START + 4).to_string(),
        ],
    );
    assert!(
        error.contains("below this segment's first block 12369621"),
        "{error}"
    );
    assert!(!error.to_lowercase().contains("connect"), "{error}");

    // An inverted range is empty, and is caught in the same place.
    let error = failure(
        Some(DEAD_ENDPOINT),
        &["--from", "12369741", "--to", "12369739"],
    );
    assert!(error.contains("empty range"), "{error}");
}

#[test]
fn a_run_needs_either_fixtures_or_a_range() {
    let error = failure(Some(DEAD_ENDPOINT), &[]);
    assert!(error.contains("nothing to replay"), "{error}");
    assert!(error.contains("--blocks"), "{error}");
    assert!(error.contains("--from"), "{error}");
}

#[test]
fn the_two_sources_cannot_be_mixed() {
    let error = failure(
        Some(DEAD_ENDPOINT),
        &[
            "--blocks",
            "../uniswap-v3/fixtures/blocks/mainnet/12369739.pb",
            "--from",
            "12369739",
            "--to",
            "12369741",
        ],
    );
    assert!(error.contains("cannot be used with"), "{error}");
}

#[test]
fn half_a_range_is_refused() {
    let error = failure(Some(DEAD_ENDPOINT), &["--from", "12369739"]);
    assert!(error.contains("--to"), "{error}");

    let error = failure(Some(DEAD_ENDPOINT), &["--to", "12369741"]);
    assert!(error.contains("--from"), "{error}");
}
