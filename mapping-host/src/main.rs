//! `graph-mapping-host` — replay a deployed subgraph's mapping WASM over
//! Firehose blocks and write a deterministic report.
//!
//! Blocks come from one of two places. `--blocks <pb>...` replays the committed
//! fixtures, which is what CI runs and what the goldens pin. `--from N --to M`
//! streams the half-open range live from `sf.firehose.v2.Stream/Blocks`, which
//! is the only way to exercise handlers whose data source was created in a block
//! the four sampled fixtures skip.
//!
//! A live range long enough to matter outlives both the process and the
//! connection, so `--checkpoint-every` writes a resumable boundary as the run
//! goes and the stream reconnects itself when the transport fails. The per-block
//! loop and the rules about what a checkpoint may describe live in
//! [`graph_mapping_host::replay`]; what a resumed run may do to output files
//! that already exist lives in [`graph_mapping_host::outputs`].

use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use graph_mapping_host::checkpoint::HostCheckpoint;
use graph_mapping_host::live::{Bcf1Writer, FrameWriter, Progress, ReportWriter};
use graph_mapping_host::outputs::{self, ResumePolicy};
use graph_mapping_host::replay::{self, CheckpointPolicy, ReplayOutputs};
use graph_mapping_host::report::RunHeader;
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::source::{
    token_from_env, BlockSource, CheckedSource, FirehoseConnector, FirehoseTarget, FixtureSource,
    Ordering, ReconnectCounter, ReconnectingSource, RetryPolicy,
};
use graph_mapping_host::store_state::{StorePoi, StoreRange};
use graph_mapping_host::{bundle, descriptor, evidence};

#[derive(Parser)]
#[command(
    name = "graph-mapping-host",
    about = "Run deployed subgraph mappings under Graph Node's own runtime, hermetically"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Replay blocks under one segment bundle.
    Run(Box<RunArgs>),
    /// Build segment bundles from a flat directory of IPFS objects.
    BuildBundles(BuildBundlesArgs),
    /// Verify a bundle's digests without running anything.
    VerifyBundle {
        #[arg(long)]
        segment: PathBuf,
    },
    /// Generate each segment's BlockChanges compatibility descriptor and sidecar.
    BuildDescriptors(BuildDescriptorsArgs),
    /// Derive a committable evidence summary from a live run's streamed report.
    Summarize(SummarizeArgs),
}

#[derive(clap::Args)]
struct SummarizeArgs {
    /// The streamed report a live run wrote with `--out`.
    #[arg(long)]
    report: PathBuf,
    /// The evidence summary to write. When it already exists its `run` and
    /// `findings` are carried forward and everything else is recomputed, so a
    /// regeneration keeps the prose and cannot keep a stale count.
    #[arg(long)]
    evidence: PathBuf,
    /// The sibling per-block file. Defaults to the summary's name with
    /// `.blocks.jsonl` in place of `.json`.
    #[arg(long)]
    per_block: Option<PathBuf>,
    /// The segment bundle, for the entity types the deployed schema declares.
    #[arg(long)]
    segment: Option<PathBuf>,
    /// The cassette the run replayed, for its row counts and digest.
    #[arg(long)]
    cassette: Option<PathBuf>,
    /// Directory of committed golden frames to cross-check the run against.
    #[arg(long)]
    goldens: Option<PathBuf>,
    /// The committed sampled-run report, so the cross-check reports what the
    /// four-block replay produced beside what it digested to.
    #[arg(long)]
    sampled_report: Option<PathBuf>,
    /// Which blocks the per-block file lists: `all` (the default, a
    /// `run-evidence/v1` summary), or `handler-blocks`, which lists only blocks
    /// that ran a handler, wrote a PoI, carried an operation or were discarded,
    /// writes the complete file beside it (`--all-blocks`) and pins it by
    /// digest. That makes a `run-evidence/v2` summary, which also records every
    /// data source creation by wave. Use it for a range too long to commit block
    /// by block.
    #[arg(long, default_value = "all")]
    per_block_scope: String,
    /// The complete per-block file a `handler-blocks` summary pins. Defaults to
    /// the summary's name with `.all-blocks.jsonl` in place of `.json`. Ignored
    /// with `--per-block-scope all`, whose one per-block file is complete.
    #[arg(long)]
    all_blocks: Option<PathBuf>,
}

#[derive(clap::Args)]
struct BuildDescriptorsArgs {
    /// Generate a separate v2 in-band oracle descriptor, retaining frozen v1 descriptors.
    #[arg(long)]
    data_sources_in_band: bool,
    /// Directory holding one subdirectory per deployment.
    #[arg(long, default_value = "segments")]
    segments: PathBuf,
    /// Repository root, for the canonical proto and prost binding digests.
    #[arg(long, default_value = "..")]
    repo_root: PathBuf,
}

#[derive(clap::Args)]
struct RunArgs {
    /// Path to the segment bundle directory, named after the deployment CID.
    #[arg(long)]
    segment: PathBuf,
    /// Firehose `sf.ethereum.type.v2.Block` files, one block each. They are
    /// replayed in ascending block order regardless of the order given.
    #[arg(long, num_args = 1.., conflicts_with_all = ["from", "to"])]
    blocks: Vec<PathBuf>,
    /// Replay only these block numbers, out of everything `--blocks` holds.
    #[arg(long, num_args = 1.., requires = "blocks")]
    only: Vec<i32>,
    /// First block of a live Firehose range, inclusive. Needs `--to`, and
    /// `$FIREHOSE_ENDPOINT` naming a `host:port`.
    #[arg(long, requires = "to")]
    from: Option<i32>,
    /// One past the last block of a live Firehose range.
    #[arg(long, requires = "from")]
    to: Option<i32>,
    /// The `eth_call` cassette.
    #[arg(long)]
    cassette: PathBuf,
    /// Record cassette misses against `ETHEREUM_RPC_URL` instead of failing.
    #[arg(long = "record", alias = "record-calls")]
    record: bool,
    /// Where to write the report. Defaults to stdout. A fixture run writes one
    /// pretty-printed JSON document; a live run writes JSON Lines.
    #[arg(long)]
    out: Option<PathBuf>,
    /// Directory to write one canonical `<number>.pb` BlockChanges frame per
    /// block into, plus an index pinning each frame's SHA-256 (`index.json` for
    /// a fixture run, `index.jsonl` for a live one).
    #[arg(long)]
    block_changes_out: Option<PathBuf>,
    /// Additionally write every frame as one `BCF1` clock-v1 stream, which the
    /// engine's `--input-format block-changes-v1-framed` reads directly.
    #[arg(long)]
    bcf1_out: Option<PathBuf>,
    /// Complete onchain source metadata for a fresh, contiguous root run only.
    /// Bounded to 10000 blocks; refuses checkpoints, grafts and indexing errors.
    #[arg(long, requires = "bcf1_out", conflicts_with_all = ["checkpoint_in", "continue_outputs"])]
    data_sources_out: Option<PathBuf>,
    /// Emit accepted dynamic-source creations in field 9 of the extended envelope.
    /// Requires a separately generated descriptor bound to this compiled source closure.
    #[arg(long, requires = "bcf1_out", conflicts_with_all = ["data_sources_out", "source_chunk_out"])]
    data_sources_in_band: bool,
    /// Seal one immutable v2 source/checkpoint chunk. Owns all output files;
    /// reports stream to stdout. Does not support grafts or partial appends.
    #[arg(long, conflicts_with_all = ["data_sources_out", "bcf1_out", "checkpoint_in", "checkpoint_out", "checkpoint_every", "continue_outputs", "block_changes_out", "store_out", "out"])]
    source_chunk_out: Option<PathBuf>,
    /// The verified immutable v2 predecessor. Its checkpoint is selected by
    /// the sealed inventory, never by an independent caller-provided path.
    #[arg(long, requires = "source_chunk_out")]
    source_chunk_in: Option<PathBuf>,
    /// Write the final in-memory store as deterministic sorted JSON: every live
    /// row in the frames' own value encoding, the closing proof of indexing, and
    /// the per-type counts. This is what a consumer's final state is compared
    /// against; see `src/store_state.rs`.
    #[arg(long)]
    store_out: Option<PathBuf>,
    /// Seconds between live progress lines on stderr; `0` silences them.
    #[arg(long, default_value_t = 10)]
    progress_secs: u64,
    /// Write a host checkpoint after the last block of this run, so a later run
    /// can continue from exactly here. Captures the entity store, the
    /// proof-of-indexing rows that chain the digest, the entity cache's key set
    /// and the ordered dynamic data sources; see `src/checkpoint.rs`.
    ///
    /// Written atomically, so passing the same path as `--checkpoint-in` is safe
    /// and is how a chain of chunks advances.
    #[arg(long)]
    checkpoint_out: Option<PathBuf>,
    /// Also write the checkpoint every N blocks, not only at the end of the run.
    ///
    /// A twenty-hour replay that checkpoints only at the end is all-or-nothing,
    /// and a stream that dies at hour nineteen loses everything. Each mid-run
    /// checkpoint is written atomically over the same path, after every artifact
    /// for that block is on disk, so what is on disk is always a boundary that
    /// was fully applied.
    ///
    /// Because a checkpoint may never be ahead of the outputs it belongs with,
    /// this also switches the report to JSON Lines and the frame index to
    /// `index.jsonl`, which a live run already uses.
    #[arg(long, requires = "checkpoint_out", value_name = "N")]
    checkpoint_every: Option<usize>,
    /// Continue the output files this run's checkpoint belongs with, instead of
    /// refusing them.
    ///
    /// A killed run leaves its report, frames and `BCF1` stream covering blocks
    /// past the last checkpoint. This cuts each of them back to exactly the
    /// checkpoint's boundary and then appends, so re-running the same command
    /// line recovers. Without it, a resumed run refuses an output file that
    /// already exists rather than duplicating the blocks in between.
    #[arg(long, requires = "checkpoint_in")]
    continue_outputs: bool,
    /// Consecutive reconnection attempts allowed without a block arriving.
    ///
    /// A live range does not survive twenty hours on one connection. A transport
    /// failure — a reset, an HTTP/2 protocol error, a stream that stops early —
    /// re-opens the stream from the next block needed; the counter resets every
    /// time a block arrives, so this bounds a stream that is not working rather
    /// than a long run. A server refusing the request is never retried.
    #[arg(long, default_value_t = 10, value_name = "N")]
    stream_retries: u32,
    /// The first reconnection delay, in milliseconds. Each further consecutive
    /// attempt doubles it.
    #[arg(long, default_value_t = 1_000, value_name = "MS")]
    stream_backoff_ms: u64,
    /// The ceiling the reconnection delay stops doubling at, in milliseconds.
    #[arg(long, default_value_t = 60_000, value_name = "MS")]
    stream_backoff_max_ms: u64,
    /// Continue from a checkpoint an earlier run wrote.
    ///
    /// A live range must start at exactly the checkpoint's boundary block plus
    /// one; a fixture run must replay only blocks above it. Either way the first
    /// block's parent hash is checked against the boundary when the two are
    /// adjacent.
    #[arg(long)]
    checkpoint_in: Option<PathBuf>,
    /// Superseded by `--checkpoint-in`; always refused, with a pointer.
    #[arg(long)]
    resume: bool,
}

#[derive(clap::Args)]
struct BuildBundlesArgs {
    /// Directory of `<cid>.{yaml,wasm,bin}` IPFS objects.
    #[arg(long)]
    from: PathBuf,
    /// Directory to write `<deployment-cid>/` bundles into.
    #[arg(long)]
    out: PathBuf,
}

fn main() -> Result<()> {
    graph_mapping_host::env_pin::pin();
    let cli = Cli::parse();
    match cli.command {
        Command::Run(args) => tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()?
            .block_on(run(*args)),
        Command::BuildBundles(args) => {
            let built = bundle::build_bundles(&args.from, &args.out)?;
            for deployment in built {
                println!("built {deployment}");
            }
            Ok(())
        }
        Command::BuildDescriptors(args) => tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()?
            .block_on(build_descriptors(args)),
        Command::Summarize(args) => summarize(args),
        Command::VerifyBundle { segment } => {
            let bundle = bundle::SegmentBundle::load(&segment)?;
            println!(
                "{}: {} files verified",
                bundle.lock().deployment,
                bundle.lock().files.len()
            );
            Ok(())
        }
    }
}

/// Why `--resume` no longer exists. Written once here so the CLI refusal and
/// `README.md` say exactly the same thing.
const RESUME_REFUSAL: &str = "\
--resume is gone; use --checkpoint-out and --checkpoint-in instead.\n\
\n\
--resume never worked, because a partial run's state cannot be rebuilt from the \
artifacts a run writes: the BlockChanges frames are a per-save operation stream \
rather than a store image, and neither the proof-of-indexing rows nor the \
accumulated dynamic data sources appear in them at all. The host holds all three \
in memory, so it now writes them itself.\n\
\n\
  graph-mapping-host run ... --from A --to B --checkpoint-out chunk-1.jsonl\n\
  graph-mapping-host run ... --from B --to C --checkpoint-in chunk-1.jsonl \\\n\
                             --checkpoint-out chunk-2.jsonl\n\
\n\
A continuation must start at exactly the checkpoint's boundary block plus one, \
and is refused on a gap, an overlap, a different segment, a different bundle or \
a cassette that changed underneath it.";

async fn run(mut args: RunArgs) -> Result<()> {
    // Before anything else, so an old command line gets the pointer rather than
    // whichever of the checks below happens to fire first.
    if args.resume {
        bail!("{RESUME_REFUSAL}");
    }
    let live_range = match (args.from, args.to) {
        (Some(from), Some(to)) => Some((from, to)),
        (None, None) => None,
        // clap's `requires` already rules this out; keep the arm total.
        _ => bail!("--from and --to must be given together"),
    };
    if live_range.is_none() && args.blocks.is_empty() {
        bail!(
            "nothing to replay: pass either --blocks <pb>... for the committed fixtures, or \
             --from <N> --to <N> for a live Firehose range"
        );
    }
    if args.checkpoint_every == Some(0) {
        bail!(
            "--checkpoint-every 0 would ask for a checkpoint after no blocks. Give it a block \
             count, or drop it to checkpoint only at the end of the run."
        );
    }
    if args.data_sources_out.as_ref().is_some_and(|p| p.exists()) {
        bail!("--data-sources-out refuses an existing path");
    }

    // v2 cannot select a naked diagnostic checkpoint or separate output files.
    // Verify the direct predecessor before network access or any file creation.
    let mut chunk_plan = args
        .source_chunk_out
        .as_deref()
        .map(|output| {
            graph_mapping_host::source_chunk::Plan::preflight(
                &args.segment,
                output,
                args.source_chunk_in.as_deref(),
            )
        })
        .transpose()?;
    if let Some(plan) = &chunk_plan {
        args.checkpoint_in = plan.checkpoint_input();
        args.checkpoint_out = Some(
            plan.building
                .join(backfill_common::dynamic_sources_v2::seal::CHECKPOINT),
        );
        args.bcf1_out = Some(
            plan.building
                .join(backfill_common::dynamic_sources_v2::seal::STREAM),
        );
    }

    // The endpoint and the token are validated before anything expensive
    // happens, so a bad endpoint fails in milliseconds rather than after a
    // bundle load. Neither is ever echoed.
    let firehose = match live_range {
        Some(_) => Some((FirehoseTarget::from_env()?, token_from_env()?)),
        None => None,
    };

    // Read the checkpoint before the bundle: a checkpoint that does not parse is
    // a mistake worth catching in milliseconds, and its boundary decides whether
    // the requested range is even legal.
    let resumed = match &args.checkpoint_in {
        Some(path) => Some(HostCheckpoint::read(path)?),
        None => None,
    };
    if let (Some((checkpoint, _)), Some((from, _))) = (resumed.as_ref(), live_range) {
        let boundary = checkpoint.header.boundary.block;
        if from != boundary + 1 {
            bail!(
                "--from {from} does not continue this checkpoint, which stops after block \
                 {boundary}. A contiguous replay has to resume at exactly {}: a lower --from \
                 would replay blocks the checkpoint has already applied, and a higher one would \
                 skip the blocks between, leaving the store and the proof-of-indexing chain \
                 short of everything those blocks wrote.",
                boundary + 1
            );
        }
    }

    // What this run may do to output files that already exist. Decided before
    // anything is opened, because refusing is the default and a refusal must
    // cost no work.
    let resume_policy = ResumePolicy::new(
        resumed
            .as_ref()
            .map(|(checkpoint, _)| checkpoint.header.boundary.block),
        args.continue_outputs,
    )?;

    // A mid-run checkpoint may never be ahead of the outputs it belongs with, so
    // asking for one puts the report and the frame index into their streamed
    // forms even for a fixture replay. Without it nothing about either changes.
    let streaming = live_range.is_some() || args.checkpoint_every.is_some() || chunk_plan.is_some();

    // The cassette as it stands before the run: its digest, and every row
    // reduced to a pair of digests. A recording run appends rows as it goes, so
    // this is the only moment at which the in-memory cassette and the file agree
    // and a checkpoint being *loaded* can be checked against either.
    let cassette_before = replay::file_sha256(&args.cassette)?;

    let config = SegmentHostConfig {
        bundle_dir: &args.segment,
        cassette_path: &args.cassette,
        record: args.record,
    };
    let mut host = if args.data_sources_in_band {
        SegmentHost::load_in_band(config).await?
    } else {
        SegmentHost::load(config).await?
    };

    if args.data_sources_out.is_some() {
        let bundle = graph_mapping_host::SegmentBundle::load(&args.segment)?;
        let manifest = bundle
            .manifest(&graph::prelude::Logger::root(
                graph::prelude::slog::Discard,
                graph::prelude::o!(),
            ))
            .await?;
        if manifest.graft.is_some() {
            bail!("--data-sources-out refuses grafted segments");
        }
        if let Some((from, to)) = live_range {
            if from != host.bounds().start
                || (to - from) as usize > backfill_common::dynamic_sources::MAX_BLOCKS
            {
                bail!("--data-sources-out requires a fresh root run of at most 10000 blocks");
            }
        }
    }

    if let Some((checkpoint, digest)) = resumed.as_ref() {
        let cassette = host
            .cassette()
            .fingerprint(cassette_before)
            .context("fingerprinting the cassette this run loaded")?;
        host.restore_checkpoint(checkpoint, &cassette)
            .with_context(|| {
                format!(
                    "restoring {}",
                    args.checkpoint_in
                        .as_ref()
                        .expect("a restored checkpoint has a path")
                        .display()
                )
            })?;
        eprintln!(
            "{}: restored {} rows and {} dynamic data sources after block {} ({digest})",
            args.checkpoint_in
                .as_ref()
                .expect("a restored checkpoint has a path")
                .display(),
            checkpoint.rows.len(),
            checkpoint.data_sources.len(),
            checkpoint.header.boundary.block
        );
    }
    if let Some(plan) = &chunk_plan {
        plan.validate_restored(&host, resumed.as_ref().map(|(checkpoint, _)| checkpoint))?;
    }

    // Replay in ascending order. Out of order would make both the store and the
    // PoI chain meaningless, so either source is wrapped in a `CheckedSource`.
    // Handed out by a reconnecting source before it is boxed, so the progress
    // line can still report how often the stream was re-opened.
    let mut reconnects: Option<ReconnectCounter> = None;
    let mut source: Box<dyn BlockSource> = match live_range {
        Some((from, to)) => {
            let (target, token) = firehose.expect("a live range always resolves an endpoint");
            // The range is checked against the segment *before* the stream is
            // opened, so an out-of-bounds request costs no network at all.
            host.bounds().check_range(from, to)?;
            if let Some(plan) = &mut chunk_plan {
                plan.bind_range(&host, (from, to))?;
            }
            let retry = RetryPolicy {
                retries: args.stream_retries,
                backoff: Duration::from_millis(args.stream_backoff_ms),
                backoff_max: Duration::from_millis(args.stream_backoff_max_ms),
            };
            // Reconnection is *inside* the contiguity checks, never outside
            // them: a reconnect that skipped, repeated or forked is refused by
            // the same `CheckedSource` an unbroken stream passes.
            let live =
                ReconnectingSource::connect(FirehoseConnector::new(target, token), from, to, retry)
                    .await?;
            reconnects = Some(live.reconnect_counter());
            let checked = CheckedSource::new(
                live,
                Ordering::Contiguous {
                    start: from,
                    stop: to,
                },
            );
            Box::new(if chunk_plan.is_some() || args.data_sources_in_band {
                checked.require_parent_hashes()
            } else {
                checked
            })
        }
        None => {
            let fixtures = FixtureSource::load(&args.blocks, &args.only)?;
            let ordering = if let Some(plan) = &mut chunk_plan {
                let range = fixtures.contiguous_range()?;
                plan.bind_range(&host, range)?;
                Ordering::Contiguous {
                    start: range.0,
                    stop: range.1,
                }
            } else {
                // Legacy sampled fixtures keep their existing behavior.
                Ordering::Sampled
            };
            let checked = CheckedSource::new(fixtures, ordering);
            Box::new(if chunk_plan.is_some() || args.data_sources_in_band {
                checked.require_parent_hashes()
            } else {
                checked
            })
        }
    };

    let source_description = source.describe();
    let base_report = host.new_report();
    if let Some(plan) = &chunk_plan {
        plan.prepare()?;
    }
    // Every output destination is inspected before any of them is opened, so a
    // resumed run that would have to refuse one refuses before it truncates
    // another.
    let report_disposition =
        outputs::prepare_report(args.out.as_deref(), streaming, resume_policy)?;
    let frames_disposition =
        outputs::prepare_frames(args.block_changes_out.as_deref(), streaming, resume_policy)?;
    let bcf1_disposition = outputs::prepare_bcf1(args.bcf1_out.as_deref(), resume_policy)?;

    let writer = if streaming {
        ReportWriter::lines(
            &RunHeader::new(&base_report, source_description.clone(), live_range),
            args.out.clone(),
            report_disposition,
        )?
    } else {
        ReportWriter::whole(base_report, args.out.clone())
    };

    let frames = match (&args.block_changes_out, streaming) {
        (Some(dir), true) => Some(FrameWriter::streaming(
            dir,
            host.descriptor_sha256(),
            frames_disposition,
        )?),
        (Some(dir), false) => Some(FrameWriter::buffered(dir)?),
        (None, _) => None,
    };
    let bcf1 = match &args.bcf1_out {
        Some(path) => Some(Bcf1Writer::create(path, streaming, bcf1_disposition)?),
        None => None,
    };
    let progress =
        live_range.map(|range| Progress::new(range, Duration::from_secs(args.progress_secs)));
    let mut outputs = ReplayOutputs {
        report: writer,
        frames,
        bcf1,
        progress,
        reconnects,
    };

    // The closing proof of indexing is the last block that opened the causality
    // region, not the last block replayed: a block in which no handler ran does
    // not advance the digest. A continuation starts from the checkpoint's, so a
    // chunk whose blocks open no region still reports the chain's closing value.
    let seed_poi: Option<StorePoi> = resumed
        .as_ref()
        .and_then(|(checkpoint, _)| checkpoint.header.poi.clone());
    // Checked against the first block that arrives, then dropped.
    let continues_from = resumed
        .as_ref()
        .map(|(checkpoint, _)| checkpoint.header.boundary.clone());

    let policy = CheckpointPolicy {
        out: args.checkpoint_out.clone(),
        every: args.checkpoint_every,
        cassette: args.cassette.clone(),
        source: source_description,
        range: chunk_plan
            .as_ref()
            .and_then(|plan| plan.range())
            .or(live_range),
        previous: resumed
            .as_ref()
            .map(|(checkpoint, digest)| (checkpoint.header.boundary.clone(), digest.clone())),
    };

    let result = replay::replay_range(
        &mut host,
        source.as_mut(),
        &mut outputs,
        &policy,
        continues_from,
        seed_poi,
    )
    .await?;
    let ReplayOutputs {
        report: writer,
        frames,
        bcf1,
        progress,
        ..
    } = outputs;
    let closing_poi = result.closing_poi;

    if let Some(frames) = frames {
        frames.finish(host.descriptor_sha256())?;
    }
    if let Some(bcf1) = bcf1 {
        bcf1.finish()?;
    }
    if let Some(path) = &args.data_sources_out {
        let (compatibility, _) = descriptor::load(&args.segment)?;
        graph_mapping_host::dynamic_sources::write(
            &host,
            args.bcf1_out.as_deref().expect("clap requires BCF1 output"),
            path,
            &compatibility,
        )?;
    }
    if let Some(path) = &args.store_out {
        let blocks = writer.blocks();
        let range = live_range.map(|(from, to)| StoreRange { from, to, blocks });
        let state = host.store_state(range, closing_poi.clone())?;
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)
                    .with_context(|| format!("creating {}", parent.display()))?;
            }
        }
        std::fs::write(path, state.to_json()?)
            .with_context(|| format!("writing {}", path.display()))?;
        eprintln!(
            "{}: {} entities, {} proof-of-indexing rows",
            path.display(),
            state.totals.entities,
            state.totals.poi_entities
        );
    }
    if host.cassette().is_dirty() {
        host.cassette().save(&args.cassette)?;
    }

    // The closing checkpoint. `CheckpointPolicy::write` saves the cassette
    // first, so the digest recorded here is the file the next chunk will load: a
    // recording run appends rows, and the next chunk must see the same bytes or
    // refuse.
    if let Some(path) = &args.checkpoint_out {
        let Some(last_applied) = result.last_applied.as_ref() else {
            bail!(
                "--checkpoint-out {} was asked for but this run replayed no block, so there is no \
                 boundary to continue from",
                path.display()
            );
        };
        policy.write(&host, writer.blocks(), last_applied, closing_poi.clone())?;
    }

    let blocks = writer.blocks();
    writer.finish(host.cassette().len())?;
    if let Some(plan) = &chunk_plan {
        let sealed = plan.finish(&host)?;
        eprintln!(
            "v2 source chunk sealed: {} ({} blocks, {} cumulative sources)",
            sealed.directory.display(),
            sealed.chunk.to - sealed.chunk.from,
            sealed.chunk.after.order.count
        );
    }
    if let Some(mut progress) = progress {
        if let Some((block, _)) = result.last_checkpoint.as_ref() {
            progress.record_checkpoint(*block);
        }
        if let Some(last_applied) = result.last_applied.as_ref() {
            if args.checkpoint_out.is_some() {
                progress.record_checkpoint(last_applied.0);
            }
        }
        progress.finish();
        eprintln!(
            "{blocks} blocks replayed; {} cassette rows",
            host.cassette().len()
        );
    }
    Ok(())
}

/// Derive the evidence summary and its per-block sibling, and write both.
///
/// Nothing here touches the network or replays a block: the report the run
/// already wrote is the only input, which is what makes the summary a record of
/// *that* run rather than of a second one.
fn summarize(args: SummarizeArgs) -> Result<()> {
    let per_block_scope = evidence::PerBlockScope::parse(&args.per_block_scope)?;
    let sibling = |explicit: &Option<PathBuf>, extension: &str| {
        explicit
            .clone()
            .unwrap_or_else(|| args.evidence.with_extension("").with_extension(extension))
    };
    let file_name = |path: &Path| {
        path.file_name()
            .map(|name| name.to_string_lossy().to_string())
            .unwrap_or_else(|| path.to_string_lossy().to_string())
    };
    let per_block_path = sibling(&args.per_block, "blocks.jsonl");
    let all_blocks_path = sibling(&args.all_blocks, "all-blocks.jsonl");

    // Carrying the previous file's prose forward is the whole reason this reads
    // before it writes. A file that does not parse is an error, not a silent
    // reset that would drop hand-written findings.
    let previous = evidence::Narrative::read(&args.evidence)?;

    let summary = evidence::summarize(evidence::SummarizeInputs {
        report: &args.report,
        previous,
        per_block_name: file_name(&per_block_path),
        segment: args.segment.as_deref(),
        cassette: args.cassette.as_deref(),
        goldens: args.goldens.as_deref(),
        sampled_report: args.sampled_report.as_deref(),
        per_block_scope,
        all_blocks_name: Some(file_name(&all_blocks_path)),
    })?;

    if let Some(parent) = args.evidence.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("creating {}", parent.display()))?;
    }
    std::fs::write(&per_block_path, &summary.per_block)
        .with_context(|| format!("writing {}", per_block_path.display()))?;
    if let Some(all_blocks) = &summary.all_blocks {
        std::fs::write(&all_blocks_path, all_blocks)
            .with_context(|| format!("writing {}", all_blocks_path.display()))?;
    }
    let evidence = &summary.evidence;
    std::fs::write(&args.evidence, evidence.to_json()?)
        .with_context(|| format!("writing {}", args.evidence.display()))?;

    eprintln!(
        "{}: {} blocks, {} handler groups, {} operations ({})",
        args.evidence.display(),
        evidence.range.blocks,
        evidence.totals.handler_groups,
        evidence.totals.operations,
        evidence.schema
    );
    Ok(())
}

async fn build_descriptors(args: BuildDescriptorsArgs) -> Result<()> {
    graph_mapping_host::env_pin::pin();
    let logger = graph::prelude::Logger::root(graph::prelude::slog::Discard, graph::prelude::o!());
    let mut segments: Vec<PathBuf> = std::fs::read_dir(&args.segments)
        .with_context(|| format!("listing {}", args.segments.display()))?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .collect();
    segments.sort();
    for segment in segments {
        let digest = if args.data_sources_in_band {
            descriptor::write_in_band(&segment, &args.repo_root, &logger).await
        } else {
            descriptor::write(&segment, &args.repo_root, &logger).await
        }
        .with_context(|| format!("building the descriptor for {}", segment.display()))?;
        println!("{} {digest}", segment.display());
    }
    Ok(())
}
