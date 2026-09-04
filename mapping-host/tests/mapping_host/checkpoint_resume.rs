//! `--checkpoint-out` and `--checkpoint-in`: a chunked replay equals an
//! uninterrupted one.
//!
//! **Hermetic.** Every test here uses the committed cassette and the four
//! hydrated block fixtures. Nothing opens a socket, and the CLI cases run the
//! binary with `--blocks`, which never reaches Firehose.
//!
//! The claim is the one that makes checkpoints usable at all: replaying a window
//! in two chunks through a checkpoint produces *the same run*. Not a similar
//! store, and not a matching final digest with different frames along the way —
//! the same per-block reports, the same BlockChanges frame for every block, the
//! same `BCF1` stream bytes, and the same closing proof of indexing. Anything
//! weaker would let a divergence hide in a block the final state happens to
//! agree about.
//!
//! The split point matters. Block 12,369,621 creates pools, so the second chunk
//! starts with dynamic data sources that exist only because the checkpoint
//! restored them; if the host set were rebuilt wrongly, the later blocks would
//! run a different set of handlers and every later frame would differ. Block
//! 12,370,523 fails deterministically under this manifest's fatal policy, so the
//! second chunk also exercises the rollback path against a restored store.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use graph::blockchain::Block as _;
use graph_mapping_host::bundle::sha256_hex;
use graph_mapping_host::calls::CassetteFingerprint;
use graph_mapping_host::checkpoint::{CheckpointBoundary, HostCheckpoint};
use graph_mapping_host::report::{BlockReport, RunReport};
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::store_state::{StorePoi, StoreState};
use graph_mapping_host::{block, blockchanges};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
const FIXTURES: &[&str] = &["12369621", "12369739", "12369879", "12370523"];
/// Where the chunked replay is cut. The first chunk replays the first two
/// fixtures, the second the last two.
const SPLIT: usize = 2;

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn segment_dir() -> PathBuf {
    crate_dir().join(format!("segments/{SEGMENT}"))
}

fn cassette_path() -> PathBuf {
    crate_dir().join(format!("fixtures/cassettes/{SEGMENT}.json"))
}

fn block_fixture(name: &str) -> PathBuf {
    crate_dir()
        .parent()
        .expect("mapping-host has a parent")
        .join(format!("uniswap-v3/fixtures/blocks/mainnet/{name}.pb"))
}

fn cassette_sha256() -> String {
    sha256_hex(&std::fs::read(cassette_path()).expect("reading the committed cassette"))
}

/// The committed cassette as a checkpoint sees it.
///
/// Every run in this suite replays rather than records, so the pin is
/// `Exact` and the rule stays byte-for-byte. The recording rule, where the
/// cassette may grow, is exercised in `long_run`.
fn cassette_fingerprint(host: &SegmentHost) -> CassetteFingerprint {
    host.cassette()
        .fingerprint(cassette_sha256())
        .expect("fingerprinting the committed cassette")
}

fn require_fixtures() {
    for name in FIXTURES {
        assert!(
            block_fixture(name).exists(),
            "missing block fixture; run `cargo xtask evidence fetch --lock \
             uniswap-v3/fixtures/blocks.lock.json` from the repository root"
        );
    }
}

async fn load_host() -> SegmentHost {
    SegmentHost::load(SegmentHostConfig {
        bundle_dir: &segment_dir(),
        cassette_path: &cassette_path(),
        record: false,
    })
    .await
    .expect("loading the segment")
}

/// Everything one replay produced, in the order it produced it.
struct Replay {
    reports: Vec<BlockReport>,
    /// SHA-256 of each block's sealed canonical frame.
    frame_digests: Vec<String>,
    /// The `BCF1` clock-v1 stream, exactly as `--bcf1-out` writes it.
    bcf1: Vec<u8>,
    closing_poi: Option<StorePoi>,
    state: StoreState,
    /// The checkpoint the run would have written, when one was asked for.
    checkpoint: Option<HostCheckpoint>,
}

/// Replay the named fixtures through `host` and collect everything a caller can
/// compare.
///
/// The names are in ascending block order in `FIXTURES`, which is the order a
/// contiguous replay would see them in; `process_block` takes a block by value
/// and `BlockFinality` is not `Clone`, so each replay loads its own copies. The
/// bytes are identical because the fixtures are digest-pinned.
async fn replay(
    host: &mut SegmentHost,
    names: &[&str],
    mut closing_poi: Option<StorePoi>,
    checkpoint_after: bool,
) -> Replay {
    let mut reports = Vec::new();
    let mut frame_digests = Vec::new();
    let mut bcf1 = Vec::new();
    let mut last: Option<(i32, String)> = None;

    for name in names {
        let raw = block::load_block(&block_fixture(name)).expect("loading a fixture");
        let number = raw.number();
        let outcome = host
            .process_block(raw)
            .await
            .unwrap_or_else(|error| panic!("replaying block {number}: {error:#}"));
        let bytes = blockchanges::seal(&outcome.changes, host.compatibility())
            .unwrap_or_else(|error| panic!("sealing block {number}: {error:#}"));
        let mut report = outcome.report;
        report.block_changes = Some(blockchanges::summarize(&outcome.changes, &bytes));
        if let Some(poi) = report.poi.as_ref() {
            closing_poi = Some(StorePoi {
                block: number,
                version: poi.version.clone(),
                causality_regions: poi.causality_regions.clone(),
                public_digest: poi.public_digest.clone(),
            });
        }
        frame_digests.push(sha256_hex(&bytes));
        bcf1.extend_from_slice(
            &blockchanges::bcf1_frame(
                outcome.changes.block_number,
                outcome.changes.block_hash.as_slice(),
                &bytes,
            )
            .expect("framing"),
        );
        last = Some((number, report.hash.clone()));
        reports.push(report);
    }

    let state = host
        .store_state(None, closing_poi.clone())
        .expect("dumping the store");
    let checkpoint = checkpoint_after.then(|| {
        let (block, block_hash) = last.clone().expect("a chunk replayed at least one block");
        host.checkpoint(
            &cassette_fingerprint(host),
            CheckpointBoundary {
                block,
                block_hash,
                source: "fixtures".to_string(),
                chunk_from: None,
                chunk_to: None,
                blocks_in_chunk: names.len(),
                blocks_total: names.len(),
                chunk_index: 0,
                previous_checkpoint_sha256: None,
            },
            closing_poi.clone(),
        )
        .expect("taking a checkpoint")
    });

    Replay {
        reports,
        frame_digests,
        bcf1,
        closing_poi,
        state,
        checkpoint,
    }
}

fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("tokio runtime")
}

/// The uninterrupted replay of all four fixtures.
async fn whole() -> Replay {
    let mut host = load_host().await;
    replay(&mut host, FIXTURES, None, false).await
}

/// The same four fixtures, in two chunks joined by a checkpoint.
async fn chunked() -> (Replay, Replay, HostCheckpoint, String) {
    let mut first_host = load_host().await;
    let first = replay(&mut first_host, &FIXTURES[..SPLIT], None, true).await;
    let checkpoint = first
        .checkpoint
        .clone()
        .expect("the first chunk checkpoints");

    // Through the file, not through memory: what a second process would read is
    // what the second chunk must restore from.
    let text = checkpoint.to_jsonl().expect("serialising the checkpoint");
    let parsed = HostCheckpoint::parse(text.as_bytes()).expect("parsing the checkpoint");

    let mut second_host = load_host().await;
    let fingerprint = cassette_fingerprint(&second_host);
    second_host
        .restore_checkpoint(&parsed, &fingerprint)
        .expect("restoring the checkpoint");
    assert_eq!(
        first_host.stored_dynamic_data_sources().unwrap(),
        second_host.stored_dynamic_data_sources().unwrap()
    );
    let second = replay(
        &mut second_host,
        &FIXTURES[SPLIT..],
        parsed.header.poi.clone(),
        false,
    )
    .await;

    (first, second, parsed, text)
}

/// The central claim: two chunks joined by a checkpoint are one run.
#[test]
fn a_chunked_replay_is_indistinguishable_from_an_uninterrupted_one() {
    require_fixtures();
    let runtime = runtime();
    let whole = runtime.block_on(whole());
    let (first, second, _, _) = runtime.block_on(chunked());

    let joined_reports: Vec<&BlockReport> =
        first.reports.iter().chain(second.reports.iter()).collect();
    let whole_reports: Vec<&BlockReport> = whole.reports.iter().collect();
    assert_eq!(
        joined_reports.len(),
        whole_reports.len(),
        "the chunks replayed a different number of blocks"
    );
    for (chunked, uninterrupted) in joined_reports.iter().zip(whole_reports.iter()) {
        assert_eq!(
            chunked, uninterrupted,
            "block {} differs between a chunked and an uninterrupted replay",
            uninterrupted.number
        );
    }

    let joined_digests: Vec<&String> = first
        .frame_digests
        .iter()
        .chain(second.frame_digests.iter())
        .collect();
    let whole_digests: Vec<&String> = whole.frame_digests.iter().collect();
    assert_eq!(
        joined_digests, whole_digests,
        "the BlockChanges frames differ between a chunked and an uninterrupted replay"
    );

    let mut joined_bcf1 = first.bcf1.clone();
    joined_bcf1.extend_from_slice(&second.bcf1);
    assert_eq!(
        joined_bcf1, whole.bcf1,
        "the BCF1 stream differs between a chunked and an uninterrupted replay"
    );

    assert_eq!(
        second.closing_poi, whole.closing_poi,
        "the closing proof of indexing differs between a chunked and an uninterrupted replay"
    );

    assert_eq!(
        second.state, whole.state,
        "the final store differs between a chunked and an uninterrupted replay"
    );

    // A guard against the whole comparison passing vacuously.
    assert_eq!(whole.reports.len(), FIXTURES.len());
    assert!(
        whole
            .closing_poi
            .as_ref()
            .is_some_and(|poi| !poi.public_digest.is_empty()),
        "the window produced no proof of indexing, so the comparison proved nothing"
    );
}

/// A checkpoint is only useful if the state it carries is the state that was
/// there, so the restored host is compared with the host that wrote it.
#[test]
fn a_restored_host_holds_the_state_the_checkpoint_was_taken_from() {
    require_fixtures();
    let runtime = runtime();
    let (first, _, parsed, text) = runtime.block_on(chunked());

    // The store the first chunk left behind, and the checkpoint's own rows.
    let expected: BTreeMap<String, usize> = first.state.counts_by_type.clone();
    assert_eq!(
        parsed.header.counts_by_type, expected,
        "the checkpoint's per-type counts are not the store's"
    );
    assert_eq!(
        parsed.header.totals.rows + parsed.header.totals.poi_rows,
        first.state.totals.entities + first.state.totals.poi_entities
    );
    assert_eq!(parsed.header.poi, first.closing_poi);

    // Re-serialising a parsed checkpoint is byte-identical, which is what makes
    // a chain of chunks auditable by digest.
    assert_eq!(parsed.to_jsonl().expect("re-serialised"), text);

    // The window creates pools, so the host set the checkpoint carries is not
    // empty; without that this suite would never exercise the restore.
    assert!(
        !parsed.data_sources.is_empty(),
        "the first chunk created no dynamic data source, so the host-set restore is untested"
    );
    assert!(
        parsed.header.totals.cached_present > 0,
        "no cache key was captured, so the cache restore is untested"
    );
}

#[test]
fn a_checkpoint_from_another_segment_is_refused() {
    require_fixtures();
    let runtime = runtime();
    let (first, _, mut parsed, _) = runtime.block_on(chunked());
    let _ = first;

    parsed.header.identity.deployment = "QmSomeOtherDeployment".to_string();
    let error = runtime.block_on(async {
        let mut host = load_host().await;
        let fingerprint = cassette_fingerprint(&host);
        host.restore_checkpoint(&parsed, &fingerprint)
            .expect_err("a checkpoint from another deployment is not loadable")
    });
    assert!(error.to_string().contains("deployment:"), "{error}");
}

#[test]
fn a_checkpoint_whose_cassette_changed_is_refused() {
    require_fixtures();
    let runtime = runtime();
    let (_, _, parsed, _) = runtime.block_on(chunked());

    let error = runtime.block_on(async {
        let mut host = load_host().await;
        let mut fingerprint = cassette_fingerprint(&host);
        fingerprint.sha256 = "0000".to_string();
        host.restore_checkpoint(&parsed, &fingerprint)
            .expect_err("a cassette that changed underneath the run is not loadable")
    });
    let message = format!("{error:#}");
    assert!(message.contains("the cassette changed"), "{message}");
    assert!(message.contains("was not recording"), "{message}");
}

#[test]
fn a_checkpoint_cannot_be_restored_over_a_host_that_has_already_replayed() {
    require_fixtures();
    let runtime = runtime();
    let (_, _, parsed, _) = runtime.block_on(chunked());

    let error = runtime.block_on(async {
        let mut host = load_host().await;
        replay(&mut host, &FIXTURES[..1], None, false).await;
        let fingerprint = cassette_fingerprint(&host);
        host.restore_checkpoint(&parsed, &fingerprint)
            .expect_err("a host that has replayed a block cannot adopt a checkpoint")
    });
    assert!(error.to_string().contains("already replayed"), "{error}");
}

// ---------------------------------------------------------------------------
// The CLI, end to end, over the same fixtures.
// ---------------------------------------------------------------------------

fn cli(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_graph-mapping-host"))
        .current_dir(crate_dir())
        .arg("run")
        .arg("--segment")
        .arg(format!("segments/{SEGMENT}"))
        .arg("--cassette")
        .arg(format!("fixtures/cassettes/{SEGMENT}.json"))
        .args(args)
        .env_remove("FIREHOSE_API_TOKEN")
        .env_remove("SUBSTREAMS_API_TOKEN")
        .env_remove("ETHEREUM_RPC_URL")
        .env_remove("FIREHOSE_ENDPOINT")
        .output()
        .expect("running graph-mapping-host")
}

fn cli_ok(args: &[&str]) {
    let output = cli(args);
    assert!(
        output.status.success(),
        "graph-mapping-host {args:?} failed:\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn cli_failure(args: &[&str]) -> String {
    let output = cli(args);
    assert!(
        !output.status.success(),
        "expected a refusal from graph-mapping-host {args:?}, got success"
    );
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn fixture_args(names: &[&str]) -> Vec<String> {
    let mut args = vec!["--blocks".to_string()];
    args.extend(
        names
            .iter()
            .map(|name| format!("../uniswap-v3/fixtures/blocks/mainnet/{name}.pb")),
    );
    args
}

fn read_report(path: &Path) -> RunReport {
    let bytes = std::fs::read(path).expect("reading a report");
    serde_json::from_slice(&bytes).expect("parsing a report")
}

/// The same claim again, but through the binary's own flags, so the wiring is
/// covered and not only the library.
#[test]
fn the_cli_chunks_a_run_through_a_checkpoint() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let whole_report = temp.path().join("whole.json");
    let whole_bcf1 = temp.path().join("whole.bcf1");
    let first_report = temp.path().join("first.json");
    let first_bcf1 = temp.path().join("first.bcf1");
    let second_report = temp.path().join("second.json");
    let second_bcf1 = temp.path().join("second.bcf1");
    let checkpoint = temp.path().join("chunk-1.jsonl");

    let all = fixture_args(FIXTURES);
    let mut args: Vec<&str> = all.iter().map(String::as_str).collect();
    args.extend([
        "--out",
        whole_report.to_str().expect("utf-8"),
        "--bcf1-out",
        whole_bcf1.to_str().expect("utf-8"),
    ]);
    cli_ok(&args);

    let head = fixture_args(&FIXTURES[..SPLIT]);
    let mut args: Vec<&str> = head.iter().map(String::as_str).collect();
    args.extend([
        "--out",
        first_report.to_str().expect("utf-8"),
        "--bcf1-out",
        first_bcf1.to_str().expect("utf-8"),
        "--checkpoint-out",
        checkpoint.to_str().expect("utf-8"),
    ]);
    cli_ok(&args);

    let tail = fixture_args(&FIXTURES[SPLIT..]);
    let mut args: Vec<&str> = tail.iter().map(String::as_str).collect();
    args.extend([
        "--out",
        second_report.to_str().expect("utf-8"),
        "--bcf1-out",
        second_bcf1.to_str().expect("utf-8"),
        "--checkpoint-in",
        checkpoint.to_str().expect("utf-8"),
    ]);
    cli_ok(&args);

    let whole = read_report(&whole_report);
    let mut joined = read_report(&first_report).blocks;
    joined.extend(read_report(&second_report).blocks);
    assert_eq!(
        joined, whole.blocks,
        "the CLI's chunked per-block reports differ from its uninterrupted ones"
    );

    let mut joined_bcf1 = std::fs::read(&first_bcf1).expect("reading the first stream");
    joined_bcf1.extend(std::fs::read(&second_bcf1).expect("reading the second stream"));
    assert_eq!(
        joined_bcf1,
        std::fs::read(&whole_bcf1).expect("reading the whole stream"),
        "the CLI's chunked BCF1 bytes differ from its uninterrupted ones"
    );

    // The checkpoint the CLI wrote is the one the library writes.
    let (parsed, _) = HostCheckpoint::read(&checkpoint).expect("reading the CLI's checkpoint");
    assert_eq!(parsed.header.boundary.block, 12_369_739);
    assert_eq!(parsed.header.boundary.blocks_in_chunk, SPLIT);
    assert_eq!(parsed.header.boundary.chunk_index, 0);
    assert!(parsed.header.boundary.previous_checkpoint_sha256.is_none());
}

/// Chunk three of three: a checkpoint written by a run that itself resumed
/// records its predecessor's digest and the running block total.
#[test]
fn checkpoints_chain_across_more_than_two_chunks() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let first = temp.path().join("chunk-1.jsonl");
    let second = temp.path().join("chunk-2.jsonl");

    let head = fixture_args(&FIXTURES[..1]);
    let mut args: Vec<&str> = head.iter().map(String::as_str).collect();
    args.extend(["--checkpoint-out", first.to_str().expect("utf-8")]);
    cli_ok(&args);

    let middle = fixture_args(&FIXTURES[1..2]);
    let mut args: Vec<&str> = middle.iter().map(String::as_str).collect();
    args.extend([
        "--checkpoint-in",
        first.to_str().expect("utf-8"),
        "--checkpoint-out",
        second.to_str().expect("utf-8"),
    ]);
    cli_ok(&args);

    let (one, one_digest) = HostCheckpoint::read(&first).expect("reading chunk 1");
    let (two, _) = HostCheckpoint::read(&second).expect("reading chunk 2");
    assert_eq!(one.header.boundary.blocks_total, 1);
    assert_eq!(two.header.boundary.blocks_total, 2);
    assert_eq!(two.header.boundary.chunk_index, 1);
    assert_eq!(
        two.header.boundary.previous_checkpoint_sha256.as_deref(),
        Some(one_digest.as_str())
    );

    // The third chunk continues from the second, which is the case a long
    // backfill actually runs.
    let tail = fixture_args(&FIXTURES[2..]);
    let mut args: Vec<&str> = tail.iter().map(String::as_str).collect();
    args.extend(["--checkpoint-in", second.to_str().expect("utf-8")]);
    cli_ok(&args);
}

/// Writing to the path a checkpoint was read from is how a chain advances in
/// place, and the write is atomic, so it has to be safe.
#[test]
fn a_checkpoint_may_be_written_over_the_one_it_resumed_from() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let path = temp.path().join("rolling.jsonl");

    let head = fixture_args(&FIXTURES[..1]);
    let mut args: Vec<&str> = head.iter().map(String::as_str).collect();
    args.extend(["--checkpoint-out", path.to_str().expect("utf-8")]);
    cli_ok(&args);
    let (before, _) = HostCheckpoint::read(&path).expect("reading the first checkpoint");

    let middle = fixture_args(&FIXTURES[1..2]);
    let mut args: Vec<&str> = middle.iter().map(String::as_str).collect();
    args.extend([
        "--checkpoint-in",
        path.to_str().expect("utf-8"),
        "--checkpoint-out",
        path.to_str().expect("utf-8"),
    ]);
    cli_ok(&args);

    let (after, _) = HostCheckpoint::read(&path).expect("reading the rolled checkpoint");
    assert_eq!(before.header.boundary.block, 12_369_621);
    assert_eq!(after.header.boundary.block, 12_369_739);
    assert_eq!(after.header.boundary.blocks_total, 2);
}

#[test]
fn a_fixture_run_cannot_replay_ground_the_checkpoint_covers() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let path = temp.path().join("chunk-1.jsonl");

    let head = fixture_args(&FIXTURES[..SPLIT]);
    let mut args: Vec<&str> = head.iter().map(String::as_str).collect();
    args.extend(["--checkpoint-out", path.to_str().expect("utf-8")]);
    cli_ok(&args);

    // The same two blocks again, on top of the checkpoint that already applied
    // them.
    let again = fixture_args(&FIXTURES[..SPLIT]);
    let mut args: Vec<&str> = again.iter().map(String::as_str).collect();
    args.extend(["--checkpoint-in", path.to_str().expect("utf-8")]);
    let error = cli_failure(&args);
    assert!(error.contains("already covers block 12369739"), "{error}");
    assert!(error.contains("apply its effects twice"), "{error}");
}

#[test]
fn a_checkpoint_that_is_not_a_checkpoint_is_refused_before_the_bundle_loads() {
    let temp = tempfile::tempdir().expect("temp dir");
    let path = temp.path().join("not-a-checkpoint.jsonl");
    std::fs::write(&path, "{\"schema\":\"something-else/v1\"}\n").expect("writing");

    let blocks = fixture_args(&FIXTURES[..1]);
    let mut args: Vec<&str> = blocks.iter().map(String::as_str).collect();
    args.extend(["--checkpoint-in", path.to_str().expect("utf-8")]);
    let error = cli_failure(&args);
    assert!(error.contains("checkpoint"), "{error}");
    // The bundle is never touched, so nothing about the segment can appear.
    assert!(!error.contains("bundle.lock.json"), "{error}");
}
