//! Surviving a replay long enough to outlive its process and its connection.
//!
//! **Hermetic.** Nothing here opens a socket. The reconnection cases drive a
//! scripted connector that hands out fake block pointers and fails where the
//! script says to; the checkpoint cases replay the four committed block
//! fixtures through the real host and the real writers, with a source that
//! stops serving mid-run to stand in for a killed process.
//!
//! Two claims are made, and they are the two things a twenty-hour backfill needs
//! to be true.
//!
//! 1. **A mid-run checkpoint is a resume point, not a hint.** A run cut short at
//!    block `D` with its last checkpoint at block `B <= D` recovers to output
//!    that is *byte-identical* to an uninterrupted run over the same blocks —
//!    the same report lines, the same frame files, the same `index.jsonl`, the
//!    same `BCF1` bytes — after the outputs are cut back to `B`. Not a matching
//!    final store: the same bytes, block by block.
//! 2. **A reconnect is never trusted.** The reconnecting source sits inside the
//!    same contiguity checks an unbroken stream passes, so a reconnect that
//!    skips a block, repeats one, or comes back on another chain is a hard
//!    failure. Every one of those is exercised here as a refusal, and the
//!    working case is exercised as an equality against an unbroken stream, so
//!    neither half can pass vacuously.

use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use anyhow::{anyhow, Result};
use async_trait::async_trait;
use graph::blockchain::Block as _;
use graph_chain_ethereum::chain::BlockFinality;
use graph_mapping_host::checkpoint::HostCheckpoint;
use graph_mapping_host::live::{Bcf1Writer, FrameWriter, ReportWriter};
use graph_mapping_host::outputs::{self, ResumePolicy};
use graph_mapping_host::replay::{self, CheckpointPolicy, ReplayOutputs};
use graph_mapping_host::report::RunHeader;
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::source::{
    BlockSource, CheckedSource, Ordering, ReconnectingSource, RetryPolicy, StreamConnector,
    TransportFailure,
};

use super::block_source::{fake_block, fake_block_with_parent};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
const FIXTURES: &[&str] = &["12369621", "12369739", "12369879", "12370523"];
/// The block the second fixture is, which is where the crash cases checkpoint.
const SECOND_BLOCK: i32 = 12_369_739;

// ---------------------------------------------------------------------------
// Reconnection, over a scripted connector
// ---------------------------------------------------------------------------

/// How one opened stream stops.
#[derive(Clone, Copy, Debug)]
enum End {
    /// A broken connection: retryable.
    Transport,
    /// A refusal about the data itself: never retryable.
    Refusal,
    /// A clean close before the range was satisfied: a truncated stream, which
    /// is retryable because the range says so, not because the socket did.
    Eof,
}

/// What the connector does the next time it is asked for a stream.
#[derive(Clone, Copy, Debug)]
enum Plan {
    /// Opening fails.
    ConnectFails { transport: bool },
    /// Serve `serve` blocks and then stop the way `end` says.
    ///
    /// `start_at` overrides where the stream actually resumes, which is how a
    /// reconnect that skips or repeats a block is simulated. `fork` makes the
    /// first block served claim a parent on another chain.
    Serve {
        start_at: Option<i32>,
        serve: usize,
        end: End,
        fork: bool,
    },
    /// Serve every remaining block and end cleanly.
    Rest,
}

/// One opened stream.
struct Scripted {
    next: i32,
    stop: i32,
    remaining: usize,
    end: Option<End>,
    /// The first block served claims a parent on chain 9 rather than chain 0.
    fork_first: bool,
}

#[async_trait]
impl BlockSource for Scripted {
    async fn next_block(&mut self) -> Result<Option<BlockFinality>> {
        if self.next >= self.stop {
            return Ok(None);
        }
        if self.remaining == 0 {
            return match self.end {
                Some(End::Transport) => Err(anyhow!(
                    "error reading a body from connection: stream error received: unspecific \
                     protocol error detected"
                )
                .context(TransportFailure)),
                Some(End::Refusal) => Err(anyhow!(
                    "the Firehose response for block {} is STEP_NEW, not STEP_FINAL",
                    self.next
                )),
                Some(End::Eof) | None => Ok(None),
            };
        }
        let number = self.next;
        let forked = self.fork_first;
        self.fork_first = false;
        self.remaining -= 1;
        self.next += 1;
        Ok(Some(if forked {
            fake_block_with_parent(0, number, 9)
        } else {
            fake_block(0, number)
        }))
    }

    fn describe(&self) -> String {
        "scripted".to_string()
    }
}

/// Hands out streams according to a script, counting how often it was asked.
struct ScriptedConnector {
    plans: VecDeque<Plan>,
    opens: std::sync::Arc<std::sync::atomic::AtomicUsize>,
}

impl ScriptedConnector {
    fn new(plans: Vec<Plan>) -> Self {
        ScriptedConnector {
            plans: plans.into(),
            opens: std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0)),
        }
    }

    fn opens(&self) -> std::sync::Arc<std::sync::atomic::AtomicUsize> {
        std::sync::Arc::clone(&self.opens)
    }
}

#[async_trait]
impl StreamConnector for ScriptedConnector {
    async fn connect(&mut self, from: i32, stop: i32) -> Result<Box<dyn BlockSource>> {
        self.opens
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let plan = self.plans.pop_front().unwrap_or(Plan::Rest);
        match plan {
            Plan::ConnectFails { transport: true } => Err(anyhow!(
                "error reading a body from connection: connection reset"
            )
            .context(TransportFailure)),
            Plan::ConnectFails { transport: false } => {
                Err(anyhow!("PermissionDenied: this chain is not yours"))
            }
            Plan::Serve {
                start_at,
                serve,
                end,
                fork,
            } => Ok(Box::new(Scripted {
                next: start_at.unwrap_or(from),
                stop,
                remaining: serve,
                end: Some(end),
                fork_first: fork,
            })),
            Plan::Rest => Ok(Box::new(Scripted {
                next: from,
                stop,
                remaining: usize::MAX,
                end: None,
                fork_first: false,
            })),
        }
    }

    fn describe(&self, from: i32, stop: i32) -> String {
        format!("scripted blocks [{from}, {stop})")
    }
}

fn instant_retries(retries: u32) -> RetryPolicy {
    RetryPolicy {
        retries,
        backoff: Duration::ZERO,
        backoff_max: Duration::ZERO,
    }
}

fn current_thread() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("tokio runtime")
}

/// Drain a scripted range through the real contiguity checks.
///
/// Returns the numbers delivered, how many streams were opened, and how many
/// times the source re-opened one — or the first refusal.
fn drain_scripted(
    plans: Vec<Plan>,
    start: i32,
    stop: i32,
    retries: u32,
) -> (Result<Vec<i32>, String>, usize, u64) {
    let runtime = current_thread();
    runtime.block_on(async {
        let connector = ScriptedConnector::new(plans);
        let opens = connector.opens();
        let live =
            match ReconnectingSource::connect(connector, start, stop, instant_retries(retries))
                .await
            {
                Ok(live) => live.quiet(),
                Err(error) => {
                    return (
                        Err(format!("{error:#}")),
                        opens.load(std::sync::atomic::Ordering::Relaxed),
                        0,
                    )
                }
            };
        let counter = live.reconnect_counter();
        let mut source = CheckedSource::new(live, Ordering::Contiguous { start, stop });
        let mut seen = Vec::new();
        loop {
            match source.next_block().await {
                Ok(Some(block)) => seen.push(block.number()),
                Ok(None) => {
                    return (
                        Ok(seen),
                        opens.load(std::sync::atomic::Ordering::Relaxed),
                        counter.get(),
                    )
                }
                Err(error) => {
                    return (
                        Err(format!("{error:#}")),
                        opens.load(std::sync::atomic::Ordering::Relaxed),
                        counter.get(),
                    )
                }
            }
        }
    })
}

#[test]
fn an_unbroken_stream_opens_once_and_never_reconnects() {
    let (blocks, opens, reconnects) = drain_scripted(vec![Plan::Rest], 100, 110, 5);
    assert_eq!(blocks, Ok((100..110).collect::<Vec<_>>()));
    assert_eq!(opens, 1, "an unbroken stream must not be re-opened");
    assert_eq!(reconnects, 0);
}

/// The claim reconnection exists for: the blocks a broken-and-resumed stream
/// delivers are exactly the blocks an unbroken one delivers.
#[test]
fn a_reconnect_delivers_the_same_blocks_as_an_unbroken_stream() {
    let unbroken = drain_scripted(vec![Plan::Rest], 100, 110, 5).0;

    // Three failures at different points in the range, so the seam is exercised
    // at the start, the middle and the last block.
    let broken = drain_scripted(
        vec![
            Plan::Serve {
                start_at: None,
                serve: 1,
                end: End::Transport,
                fork: false,
            },
            Plan::Serve {
                start_at: None,
                serve: 5,
                end: End::Transport,
                fork: false,
            },
            Plan::Serve {
                start_at: None,
                serve: 3,
                end: End::Transport,
                fork: false,
            },
            Plan::Rest,
        ],
        100,
        110,
        5,
    );
    assert_eq!(
        broken.0, unbroken,
        "a reconnect changed which blocks arrived"
    );
    assert_eq!(broken.1, 4, "four streams were scripted");
    assert_eq!(broken.2, 3, "three of them were reconnections");
    // Not vacuous: the unbroken run really did produce the whole range.
    assert_eq!(unbroken.as_ref().map(Vec::len), Ok(10));
}

#[test]
fn a_reconnect_that_would_skip_a_block_is_refused() {
    let (blocks, _, _) = drain_scripted(
        vec![
            Plan::Serve {
                start_at: None,
                serve: 3,
                end: End::Transport,
                fork: false,
            },
            // Comes back one block too high.
            Plan::Serve {
                start_at: Some(104),
                serve: 6,
                end: End::Transport,
                fork: false,
            },
        ],
        100,
        110,
        5,
    );
    let error = blocks.expect_err("a reconnect that skips a block is not tolerated");
    assert!(error.contains("gap in the block stream"), "{error}");
    assert!(error.contains("expected block 103, got 104"), "{error}");
}

#[test]
fn a_reconnect_that_would_repeat_a_block_is_refused() {
    let (blocks, _, _) = drain_scripted(
        vec![
            Plan::Serve {
                start_at: None,
                serve: 3,
                end: End::Transport,
                fork: false,
            },
            // Comes back on the block it already delivered.
            Plan::Serve {
                start_at: Some(102),
                serve: 6,
                end: End::Transport,
                fork: false,
            },
        ],
        100,
        110,
        5,
    );
    let error = blocks.expect_err("a reconnect that repeats a block is not tolerated");
    assert!(error.contains("block 102 was produced twice"), "{error}");
}

#[test]
fn a_reconnect_that_would_regress_is_refused() {
    let (blocks, _, _) = drain_scripted(
        vec![
            Plan::Serve {
                start_at: None,
                serve: 3,
                end: End::Transport,
                fork: false,
            },
            Plan::Serve {
                start_at: Some(100),
                serve: 6,
                end: End::Transport,
                fork: false,
            },
        ],
        100,
        110,
        5,
    );
    let error = blocks.expect_err("a reconnect that goes backwards is not tolerated");
    assert!(error.contains("strictly ascending"), "{error}");
}

/// The seam is the one place two chains could be joined without any block
/// number noticing, so the parent hash is checked straight across it.
#[test]
fn a_reconnect_onto_a_different_chain_is_refused() {
    let (blocks, _, _) = drain_scripted(
        vec![
            Plan::Serve {
                start_at: None,
                serve: 3,
                end: End::Transport,
                fork: false,
            },
            // Right height, right order, wrong chain.
            Plan::Serve {
                start_at: None,
                serve: 6,
                end: End::Transport,
                fork: true,
            },
        ],
        100,
        110,
        5,
    );
    let error = blocks.expect_err("a reconnect onto another chain is not tolerated");
    assert!(error.contains("block 103 names parent"), "{error}");
    assert!(error.contains("changed chains mid-range"), "{error}");
}

/// A stream that closes early has not satisfied the range, so it is a truncated
/// stream rather than an end, and it is reconnected.
#[test]
fn a_stream_that_closes_before_the_range_is_reconnected() {
    let (blocks, opens, reconnects) = drain_scripted(
        vec![
            Plan::Serve {
                start_at: None,
                serve: 4,
                end: End::Eof,
                fork: false,
            },
            Plan::Rest,
        ],
        100,
        110,
        5,
    );
    assert_eq!(blocks, Ok((100..110).collect::<Vec<_>>()));
    assert_eq!(opens, 2);
    assert_eq!(reconnects, 1);
}

/// A server saying no is not a broken connection, and retrying it would turn a
/// clear refusal into a slow one.
#[test]
fn a_refusal_about_the_data_is_not_retried() {
    let (blocks, opens, reconnects) = drain_scripted(
        vec![Plan::Serve {
            start_at: None,
            serve: 2,
            end: End::Refusal,
            fork: false,
        }],
        100,
        110,
        5,
    );
    let error = blocks.expect_err("a refusal is not retried");
    assert!(error.contains("not a transport failure"), "{error}");
    assert!(error.contains("STEP_NEW"), "{error}");
    assert_eq!(opens, 1, "a refusal must not cost a reconnection");
    assert_eq!(reconnects, 0);
}

#[test]
fn a_server_refusing_the_connection_is_not_retried() {
    let (blocks, opens, _) = drain_scripted(
        vec![
            Plan::Serve {
                start_at: None,
                serve: 2,
                end: End::Transport,
                fork: false,
            },
            Plan::ConnectFails { transport: false },
        ],
        100,
        110,
        5,
    );
    let error = blocks.expect_err("PermissionDenied is not retried");
    assert!(error.contains("not a transport failure"), "{error}");
    assert_eq!(opens, 2, "the refusing connect is attempted exactly once");
}

/// The budget is consecutive failures with no block delivered, and it is
/// honoured exactly.
#[test]
fn the_retry_cap_is_honoured() {
    let mut plans = vec![Plan::Serve {
        start_at: None,
        serve: 2,
        end: End::Transport,
        fork: false,
    }];
    plans.extend(std::iter::repeat_n(
        Plan::ConnectFails { transport: true },
        20,
    ));
    let (blocks, opens, _) = drain_scripted(plans, 100, 110, 3);
    let error = blocks.expect_err("a stream that never works is given up on");
    assert!(
        error.contains("giving up after 3 consecutive transport failures"),
        "{error}"
    );
    assert!(error.contains("--stream-retries 3"), "{error}");
    // One opening connect, then exactly three retries and no more.
    assert_eq!(opens, 4, "the cap must bound the connect attempts");
}

/// The counter resets on progress, so a long run that keeps delivering blocks is
/// never killed by a cap it has already been under many times.
#[test]
fn the_retry_budget_resets_whenever_a_block_arrives() {
    let mut plans = Vec::new();
    // Ten separate failures, each after one delivered block, under a cap of 1.
    for _ in 0..10 {
        plans.push(Plan::Serve {
            start_at: None,
            serve: 1,
            end: End::Transport,
            fork: false,
        });
    }
    plans.push(Plan::Rest);
    let (blocks, _, reconnects) = drain_scripted(plans, 100, 110, 1);
    assert_eq!(blocks, Ok((100..110).collect::<Vec<_>>()));
    // Nine seams: the tenth stream serves the last block of the range, so it
    // ends rather than failing. Nine reconnections under a cap of one is only
    // possible because a delivered block clears the counter.
    assert_eq!(reconnects, 9);
}

#[test]
fn an_endpoint_that_is_down_at_the_start_is_retried_and_then_given_up_on() {
    let plans = std::iter::repeat_n(Plan::ConnectFails { transport: true }, 20).collect();
    let (blocks, opens, _) = drain_scripted(plans, 100, 110, 2);
    let error = blocks.expect_err("an endpoint that never answers is given up on");
    assert!(error.contains("giving up after 2"), "{error}");
    assert_eq!(opens, 3);
}

// ---------------------------------------------------------------------------
// Periodic checkpointing, over the real host and the real writers
// ---------------------------------------------------------------------------

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

/// The committed fixtures, served in order, stopping after `serve` of them.
///
/// Stopping stands in for a killed process: `replay_range` gets a transport
/// failure it cannot do anything with, exactly as `main` would if the stream
/// died and the retries ran out.
struct FixtureStream {
    names: VecDeque<&'static str>,
    serve: usize,
}

impl FixtureStream {
    fn new(names: &[&'static str], serve: usize) -> Self {
        FixtureStream {
            names: names.iter().copied().collect(),
            serve,
        }
    }
}

#[async_trait]
impl BlockSource for FixtureStream {
    async fn next_block(&mut self) -> Result<Option<BlockFinality>> {
        let Some(name) = self.names.pop_front() else {
            return Ok(None);
        };
        if self.serve == 0 {
            return Err(anyhow!(
                "error reading a body from connection: stream error received: unspecific \
                 protocol error detected"
            )
            .context(TransportFailure));
        }
        self.serve -= 1;
        Ok(Some(
            graph_mapping_host::block::load_block(&block_fixture(name)).expect("loading a fixture"),
        ))
    }

    fn describe(&self) -> String {
        // Constant, so a crashed run and an uninterrupted one write the same
        // report header and the comparison below can be byte-for-byte.
        "fixtures".to_string()
    }
}

/// Every file a replay wrote into one directory, for a byte-for-byte compare.
fn artifacts(dir: &Path) -> Vec<(String, Vec<u8>)> {
    let mut found = Vec::new();
    collect(dir, dir, &mut found);
    found.sort_by(|a, b| a.0.cmp(&b.0));
    return found;

    fn collect(root: &Path, dir: &Path, found: &mut Vec<(String, Vec<u8>)>) {
        for entry in std::fs::read_dir(dir).expect("listing a run directory") {
            let path = entry.expect("a directory entry").path();
            if path.is_dir() {
                collect(root, &path, found);
                continue;
            }
            let name = path
                .strip_prefix(root)
                .expect("a path under the root")
                .to_string_lossy()
                .into_owned();
            // The checkpoint is a resume point, not an artifact of the replay,
            // and a crashed run's differs from an uninterrupted one's by the
            // block count of the chunk. Everything else must match exactly.
            if name.ends_with(".ckpt") {
                continue;
            }
            found.push((name, std::fs::read(&path).expect("reading an artifact")));
        }
    }
}

/// Open the three streamed writers into `dir` with the given disposition.
fn open_outputs(
    host: &SegmentHost,
    dir: &Path,
    source: &str,
    policy: ResumePolicy,
) -> ReplayOutputs {
    let report = dir.join("report.jsonl");
    let frames = dir.join("frames");
    let bcf1 = dir.join("run.bcf1");
    let report_disposition =
        outputs::prepare_report(Some(&report), true, policy).expect("preparing the report");
    let frames_disposition =
        outputs::prepare_frames(Some(&frames), true, policy).expect("preparing the frames");
    let bcf1_disposition = outputs::prepare_bcf1(Some(&bcf1), policy).expect("preparing the BCF1");

    let base = host.new_report();
    ReplayOutputs {
        report: ReportWriter::lines(
            &RunHeader::new(&base, source.to_string(), None),
            Some(report),
            report_disposition,
        )
        .expect("opening the report"),
        frames: Some(
            FrameWriter::streaming(&frames, host.descriptor_sha256(), frames_disposition)
                .expect("opening the frame writer"),
        ),
        bcf1: Some(Bcf1Writer::create(&bcf1, true, bcf1_disposition).expect("opening the BCF1")),
        progress: None,
        reconnects: None,
    }
}

fn finish(outputs: ReplayOutputs, host: &SegmentHost) {
    let ReplayOutputs {
        report,
        frames,
        bcf1,
        ..
    } = outputs;
    if let Some(frames) = frames {
        frames.finish(host.descriptor_sha256()).expect("finishing");
    }
    if let Some(bcf1) = bcf1 {
        bcf1.finish().expect("finishing");
    }
    report.finish(host.cassette().len()).expect("finishing");
}

fn policy_for(dir: &Path, every: Option<usize>) -> CheckpointPolicy {
    CheckpointPolicy {
        out: Some(dir.join("run.ckpt")),
        every,
        cassette: cassette_path(),
        source: "fixtures".to_string(),
        range: None,
        previous: None,
    }
}

/// A run over every fixture that is never interrupted: the thing everything
/// else is compared against.
fn uninterrupted(dir: &Path) {
    let runtime = current_thread();
    runtime.block_on(async {
        let mut host = load_host().await;
        let mut source = FixtureStream::new(FIXTURES, FIXTURES.len());
        let mut outputs = open_outputs(&host, dir, "fixtures", ResumePolicy::Fresh);
        let policy = policy_for(dir, Some(2));
        let result =
            replay::replay_range(&mut host, &mut source, &mut outputs, &policy, None, None)
                .await
                .expect("an uninterrupted replay");
        assert_eq!(result.blocks, FIXTURES.len());
        let last = result.last_applied.clone().expect("a last block");
        policy
            .write(&host, result.blocks, &last, result.closing_poi.clone())
            .expect("the closing checkpoint");
        finish(outputs, &host);
    });
}

/// A mid-run checkpoint must describe a boundary that was fully applied, so it
/// must equal the checkpoint an ordinary run over exactly those blocks writes.
#[test]
fn a_periodic_checkpoint_is_the_checkpoint_a_run_over_those_blocks_would_write() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let crashed = temp.path().join("crashed");
    let short = temp.path().join("short");
    std::fs::create_dir_all(&crashed).expect("mkdir");
    std::fs::create_dir_all(&short).expect("mkdir");

    let runtime = current_thread();

    // Four blocks asked for, three served, a checkpoint every two: the last
    // checkpoint lands on block two while the outputs reach block three.
    let crashed_checkpoint = runtime.block_on(async {
        let mut host = load_host().await;
        let mut source = FixtureStream::new(FIXTURES, 3);
        let mut outputs = open_outputs(&host, &crashed, "fixtures", ResumePolicy::Fresh);
        let policy = policy_for(&crashed, Some(2));
        let error = replay::replay_range(&mut host, &mut source, &mut outputs, &policy, None, None)
            .await
            .expect_err("the stream died");
        assert!(
            format!("{error:#}").contains("error reading a body"),
            "{error:#}"
        );
        // The writers are dropped without `finish`, which is what a killed
        // process does. Everything was flushed per block.
        drop(outputs);
        HostCheckpoint::read(&crashed.join("run.ckpt"))
            .expect("a checkpoint survived the crash")
            .0
    });

    // A plain two-block run, checkpointing only at the end.
    let short_checkpoint = runtime.block_on(async {
        let mut host = load_host().await;
        let mut source = FixtureStream::new(&FIXTURES[..2], 2);
        let mut outputs = open_outputs(&host, &short, "fixtures", ResumePolicy::Fresh);
        let policy = policy_for(&short, None);
        let result =
            replay::replay_range(&mut host, &mut source, &mut outputs, &policy, None, None)
                .await
                .expect("a two-block replay");
        let last = result.last_applied.clone().expect("a last block");
        policy
            .write(&host, result.blocks, &last, result.closing_poi.clone())
            .expect("the closing checkpoint");
        finish(outputs, &host);
        HostCheckpoint::read(&short.join("run.ckpt"))
            .expect("a checkpoint")
            .0
    });

    assert_eq!(
        crashed_checkpoint.header.boundary.block, SECOND_BLOCK,
        "the mid-run checkpoint did not land on the second block"
    );
    assert_eq!(crashed_checkpoint, short_checkpoint);

    // Not vacuous: block two creates pools, so the checkpoint really carries
    // restored state rather than an empty store.
    assert!(!crashed_checkpoint.rows.is_empty());
    assert!(!crashed_checkpoint.data_sources.is_empty());

    // And the outputs really did get ahead of it, which is the whole reason the
    // trim below exists.
    assert!(
        crashed.join("frames/12369879.pb").exists(),
        "the crashed run wrote no frame past its checkpoint, so nothing was trimmed"
    );
}

/// The central claim: a run cut short mid-chunk recovers from its last periodic
/// checkpoint to output that is byte-for-byte an uninterrupted run's.
#[test]
fn recovering_from_a_mid_run_checkpoint_reproduces_an_uninterrupted_run_byte_for_byte() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let whole = temp.path().join("whole");
    let recovered = temp.path().join("recovered");
    std::fs::create_dir_all(&whole).expect("mkdir");
    std::fs::create_dir_all(&recovered).expect("mkdir");

    uninterrupted(&whole);

    let runtime = current_thread();

    // Crash: three of four blocks served, checkpointing every two.
    runtime.block_on(async {
        let mut host = load_host().await;
        let mut source = FixtureStream::new(FIXTURES, 3);
        let mut outputs = open_outputs(&host, &recovered, "fixtures", ResumePolicy::Fresh);
        let policy = policy_for(&recovered, Some(2));
        replay::replay_range(&mut host, &mut source, &mut outputs, &policy, None, None)
            .await
            .expect_err("the stream died");
        drop(outputs);
    });

    // A negative control for the recovery below: what the crash left is *not*
    // what an uninterrupted run leaves, so the comparison at the end has
    // something to prove.
    assert_ne!(
        artifacts(&recovered),
        artifacts(&whole),
        "the crashed run already matched an uninterrupted one, so recovery proves nothing"
    );

    // Recover: restore the checkpoint, cut the outputs back to its boundary,
    // and replay the rest.
    runtime.block_on(async {
        let (checkpoint, _) =
            HostCheckpoint::read(&recovered.join("run.ckpt")).expect("the checkpoint");
        let boundary = checkpoint.header.boundary.block;
        assert_eq!(boundary, SECOND_BLOCK);

        let mut host = load_host().await;
        let cassette = replay::file_sha256(&cassette_path()).expect("the cassette digest");
        host.restore_checkpoint(&checkpoint, cassette)
            .expect("restoring");

        let resume = ResumePolicy::new(Some(boundary), true).expect("a continue policy");
        let mut outputs = open_outputs(&host, &recovered, "fixtures", resume);
        let mut source = FixtureStream::new(&FIXTURES[2..], 2);
        let policy = CheckpointPolicy {
            out: Some(recovered.join("run.ckpt")),
            every: Some(2),
            cassette: cassette_path(),
            source: "fixtures".to_string(),
            range: None,
            previous: None,
        };
        let result = replay::replay_range(
            &mut host,
            &mut source,
            &mut outputs,
            &policy,
            Some(checkpoint.header.boundary.clone()),
            checkpoint.header.poi.clone(),
        )
        .await
        .expect("the recovery replayed");
        assert_eq!(result.blocks, 2);
        finish(outputs, &host);
    });

    let recovered_files = artifacts(&recovered);
    let whole_files = artifacts(&whole);
    assert_eq!(
        recovered_files
            .iter()
            .map(|(name, _)| name)
            .collect::<Vec<_>>(),
        whole_files.iter().map(|(name, _)| name).collect::<Vec<_>>(),
        "recovery left a different set of files"
    );
    for ((name, recovered), (_, whole)) in recovered_files.iter().zip(whole_files.iter()) {
        assert_eq!(
            recovered, whole,
            "{name} differs between a recovered run and an uninterrupted one"
        );
    }

    // Not vacuous: four frames, a report of five lines, and a non-empty BCF1.
    assert_eq!(
        whole_files
            .iter()
            .filter(|(name, _)| name.ends_with(".pb"))
            .count(),
        FIXTURES.len()
    );
    let report = std::fs::read_to_string(whole.join("report.jsonl")).expect("the report");
    assert_eq!(report.lines().count(), FIXTURES.len() + 1, "{report}");
    assert!(!std::fs::read(whole.join("run.bcf1"))
        .expect("the stream")
        .is_empty());
}

/// The default is a refusal, because a resumed run cannot tell a dead sibling
/// of its checkpoint from a finished chunk somebody still needs.
#[test]
fn a_resume_refuses_outputs_it_was_not_told_to_continue() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let dir = temp.path().join("run");
    std::fs::create_dir_all(&dir).expect("mkdir");

    let runtime = current_thread();
    runtime.block_on(async {
        let mut host = load_host().await;
        let mut source = FixtureStream::new(FIXTURES, 3);
        let mut outputs = open_outputs(&host, &dir, "fixtures", ResumePolicy::Fresh);
        let policy = policy_for(&dir, Some(2));
        replay::replay_range(&mut host, &mut source, &mut outputs, &policy, None, None)
            .await
            .expect_err("the stream died");
        drop(outputs);
    });

    let refusal = ResumePolicy::new(Some(SECOND_BLOCK), false).expect("a refuse policy");
    let error = outputs::prepare_report(Some(&dir.join("report.jsonl")), true, refusal)
        .expect_err("an existing report is refused");
    let message = format!("{error:#}");
    assert!(message.contains("already exists"), "{message}");
    assert!(message.contains("--continue-outputs"), "{message}");

    let error = outputs::prepare_bcf1(Some(&dir.join("run.bcf1")), refusal)
        .expect_err("an existing BCF1 stream is refused");
    assert!(
        format!("{error:#}").contains("--continue-outputs"),
        "{error:#}"
    );

    let error = outputs::prepare_frames(Some(&dir.join("frames")), true, refusal)
        .expect_err("an existing frame directory is refused");
    assert!(
        format!("{error:#}").contains("--continue-outputs"),
        "{error:#}"
    );
}

// ---------------------------------------------------------------------------
// The CLI's own wiring
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

fn cli_ok(args: &[&str]) -> String {
    let output = cli(args);
    assert!(
        output.status.success(),
        "graph-mapping-host {args:?} failed:\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stderr).into_owned()
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

/// Every block a checkpoint line on stderr named, in order.
fn checkpointed_blocks(stderr: &str) -> Vec<i32> {
    stderr
        .lines()
        .filter_map(|line| line.split_once("dynamic data sources, after block "))
        .filter_map(|(_, rest)| rest.split_whitespace().next())
        .filter_map(|number| number.parse().ok())
        .collect()
}

#[test]
fn the_cli_checkpoints_every_n_blocks_and_streams_its_report() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let report = temp.path().join("run.jsonl");
    let checkpoint = temp.path().join("run.ckpt");

    let all = fixture_args(FIXTURES);
    let mut args: Vec<&str> = all.iter().map(String::as_str).collect();
    args.extend([
        "--out",
        report.to_str().expect("utf-8"),
        "--checkpoint-out",
        checkpoint.to_str().expect("utf-8"),
        "--checkpoint-every",
        "1",
    ]);
    let stderr = cli_ok(&args);

    // One per block, plus the closing one over the same last block.
    assert_eq!(
        checkpointed_blocks(&stderr),
        vec![12_369_621, 12_369_739, 12_369_879, 12_370_523, 12_370_523],
        "{stderr}"
    );

    // Asking for periodic checkpoints puts the report into its streamed form,
    // because a checkpoint may not be ahead of the file it belongs with.
    let text = std::fs::read_to_string(&report).expect("the report");
    assert_eq!(text.lines().count(), FIXTURES.len() + 1, "{text}");
    for line in text.lines() {
        serde_json::from_str::<serde_json::Value>(line).expect("each line is one JSON object");
    }
}

#[test]
fn checkpoint_every_needs_a_checkpoint_to_write() {
    require_fixtures();
    let blocks = fixture_args(&FIXTURES[..1]);
    let mut args: Vec<&str> = blocks.iter().map(String::as_str).collect();
    args.extend(["--checkpoint-every", "1"]);
    let error = cli_failure(&args);
    assert!(error.contains("--checkpoint-out"), "{error}");
}

#[test]
fn checkpoint_every_zero_is_refused_rather_than_silently_disabled() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let checkpoint = temp.path().join("run.ckpt");
    let blocks = fixture_args(&FIXTURES[..1]);
    let mut args: Vec<&str> = blocks.iter().map(String::as_str).collect();
    args.extend([
        "--checkpoint-out",
        checkpoint.to_str().expect("utf-8"),
        "--checkpoint-every",
        "0",
    ]);
    let error = cli_failure(&args);
    assert!(error.contains("after no blocks"), "{error}");
}

#[test]
fn continue_outputs_needs_a_checkpoint_to_continue_from() {
    require_fixtures();
    let blocks = fixture_args(&FIXTURES[..1]);
    let mut args: Vec<&str> = blocks.iter().map(String::as_str).collect();
    args.extend(["--continue-outputs"]);
    let error = cli_failure(&args);
    assert!(error.contains("--checkpoint-in"), "{error}");
}

/// Through the binary's own flags: a resumed chunk that continues its
/// predecessor's output files produces the same bytes as one uninterrupted run.
#[test]
fn the_cli_continues_output_files_across_a_resume() {
    require_fixtures();
    let temp = tempfile::tempdir().expect("temp dir");
    let whole_report = temp.path().join("whole.jsonl");
    let whole_bcf1 = temp.path().join("whole.bcf1");
    let whole_checkpoint = temp.path().join("whole.ckpt");
    let joined_report = temp.path().join("joined.jsonl");
    let joined_bcf1 = temp.path().join("joined.bcf1");
    let checkpoint = temp.path().join("chunk-1.ckpt");

    let all = fixture_args(FIXTURES);
    let mut args: Vec<&str> = all.iter().map(String::as_str).collect();
    args.extend([
        "--out",
        whole_report.to_str().expect("utf-8"),
        "--bcf1-out",
        whole_bcf1.to_str().expect("utf-8"),
        "--checkpoint-out",
        whole_checkpoint.to_str().expect("utf-8"),
        "--checkpoint-every",
        "1",
    ]);
    cli_ok(&args);

    let head = fixture_args(&FIXTURES[..2]);
    let mut args: Vec<&str> = head.iter().map(String::as_str).collect();
    args.extend([
        "--out",
        joined_report.to_str().expect("utf-8"),
        "--bcf1-out",
        joined_bcf1.to_str().expect("utf-8"),
        "--checkpoint-out",
        checkpoint.to_str().expect("utf-8"),
        "--checkpoint-every",
        "1",
    ]);
    cli_ok(&args);

    // Without --continue-outputs the second chunk refuses the files the first
    // one left, rather than appending a second header and a duplicate span.
    let tail = fixture_args(&FIXTURES[2..]);
    let mut refuse: Vec<&str> = tail.iter().map(String::as_str).collect();
    refuse.extend([
        "--out",
        joined_report.to_str().expect("utf-8"),
        "--checkpoint-in",
        checkpoint.to_str().expect("utf-8"),
        "--checkpoint-out",
        checkpoint.to_str().expect("utf-8"),
        "--checkpoint-every",
        "1",
    ]);
    let error = cli_failure(&refuse);
    assert!(error.contains("--continue-outputs"), "{error}");

    let mut args: Vec<&str> = tail.iter().map(String::as_str).collect();
    args.extend([
        "--out",
        joined_report.to_str().expect("utf-8"),
        "--bcf1-out",
        joined_bcf1.to_str().expect("utf-8"),
        "--checkpoint-in",
        checkpoint.to_str().expect("utf-8"),
        "--continue-outputs",
        "--checkpoint-out",
        checkpoint.to_str().expect("utf-8"),
        "--checkpoint-every",
        "1",
    ]);
    cli_ok(&args);

    // The block lines, not the header: the header records how blocks reached the
    // run, and two chunks of two fixtures genuinely did not reach it the way one
    // run of four did. Everything the replay produced must still be identical.
    let joined_text = std::fs::read_to_string(&joined_report).expect("the joined report");
    let whole_text = std::fs::read_to_string(&whole_report).expect("the whole report");
    assert_eq!(
        joined_text.lines().skip(1).collect::<Vec<_>>(),
        whole_text.lines().skip(1).collect::<Vec<_>>(),
        "continuing the report across a resume did not reproduce one run's block lines"
    );
    // Exactly one header, so appending did not write a second one.
    assert_eq!(
        joined_text
            .lines()
            .filter(|line| line.contains("\"schema\""))
            .count(),
        1,
        "{joined_text}"
    );
    assert_eq!(
        std::fs::read(&joined_bcf1).expect("the joined stream"),
        std::fs::read(&whole_bcf1).expect("the whole stream"),
        "continuing the BCF1 stream across a resume did not reproduce one run's bytes"
    );
    // Not vacuous.
    assert_eq!(
        whole_text.lines().count(),
        FIXTURES.len() + 1,
        "{whole_text}"
    );
    assert_eq!(
        joined_text.lines().count(),
        FIXTURES.len() + 1,
        "{joined_text}"
    );
}
