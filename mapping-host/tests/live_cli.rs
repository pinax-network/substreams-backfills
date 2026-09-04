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

#[test]
fn resume_is_refused_with_an_explanation() {
    let error = failure(
        Some(DEAD_ENDPOINT),
        &["--from", "12369739", "--to", "12369741", "--resume"],
    );
    assert!(error.contains("--resume is refused"), "{error}");
    assert!(error.contains("in-memory store"), "{error}");
    assert!(error.contains("PoI chain"), "{error}");
    assert!(error.contains("host set"), "{error}");
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
