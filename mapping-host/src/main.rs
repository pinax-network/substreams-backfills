//! `graph-mapping-host` — replay a deployed subgraph's mapping WASM over
//! Firehose blocks and write a deterministic report.
//!
//! Blocks come from one of two places. `--blocks <pb>...` replays the committed
//! fixtures, which is what CI runs and what the goldens pin. `--from N --to M`
//! streams the half-open range live from `sf.firehose.v2.Stream/Blocks`, which
//! is the only way to exercise handlers whose data source was created in a block
//! the four sampled fixtures skip.

use std::path::PathBuf;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use graph::blockchain::Block as _;
use graph_mapping_host::live::{Bcf1Writer, FrameWriter, Progress, ReportWriter};
use graph_mapping_host::report::RunHeader;
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::source::{
    token_from_env, BlockSource, CheckedSource, FirehoseSource, FirehoseTarget, FixtureSource,
    Ordering,
};
use graph_mapping_host::{blockchanges, bundle, descriptor};

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
    Run(RunArgs),
    /// Build segment bundles from a flat directory of IPFS objects.
    BuildBundles(BuildBundlesArgs),
    /// Verify a bundle's digests without running anything.
    VerifyBundle {
        #[arg(long)]
        segment: PathBuf,
    },
    /// Generate each segment's BlockChanges compatibility descriptor and sidecar.
    BuildDescriptors(BuildDescriptorsArgs),
}

#[derive(clap::Args)]
struct BuildDescriptorsArgs {
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
    /// Seconds between live progress lines on stderr; `0` silences them.
    #[arg(long, default_value_t = 10)]
    progress_secs: u64,
    /// Continue a live range from the last fully written block.
    ///
    /// This is refused, with an explanation; see `README.md`.
    #[arg(long, requires = "from")]
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
            .block_on(run(args)),
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

/// Why `--resume` cannot be honoured. Written once here so the CLI refusal and
/// `README.md` say exactly the same thing.
const RESUME_REFUSAL: &str = "\
--resume is refused, deliberately, because this host cannot rebuild a partial \
run's state faithfully. Three things carry across a block boundary and none of \
them survives the process:\n\
  * the in-memory store. Nothing is persisted between blocks; there is no \
    snapshot format, and the written BlockChanges frames are a per-save \
    operation stream, not a store image.\n\
  * the Legacy PoI chain. Each block's causality-region digest mixes in the \
    previous block's, and it lives in a `Poi$` entity that no mapping handler \
    writes, so the recorder never sees it and no frame carries it.\n\
  * the host set. Dynamic data sources accumulate across blocks; only a replay \
    from the segment's first block puts the same hosts in the same order.\n\
Resuming from partial state would silently produce a different PoI and a \
different store, which is the one failure this crate exists to prevent. Re-run \
the whole range from --from instead.";

async fn run(args: RunArgs) -> Result<()> {
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
    if args.resume {
        bail!("{RESUME_REFUSAL}");
    }

    // The endpoint and the token are validated before anything expensive
    // happens, so a bad endpoint fails in milliseconds rather than after a
    // bundle load. Neither is ever echoed.
    let firehose = match live_range {
        Some(_) => Some((FirehoseTarget::from_env()?, token_from_env()?)),
        None => None,
    };

    let mut host = SegmentHost::load(SegmentHostConfig {
        bundle_dir: &args.segment,
        cassette_path: &args.cassette,
        record: args.record,
    })
    .await?;

    // Replay in ascending order. Out of order would make both the store and the
    // PoI chain meaningless, so either source is wrapped in a `CheckedSource`.
    let mut source: Box<dyn BlockSource> = match live_range {
        Some((from, to)) => {
            let (target, token) = firehose.expect("a live range always resolves an endpoint");
            // The range is checked against the segment *before* the stream is
            // opened, so an out-of-bounds request costs no network at all.
            host.bounds().check_range(from, to)?;
            let live = FirehoseSource::connect(&target, token, from, to).await?;
            Box::new(CheckedSource::new(
                live,
                Ordering::Contiguous {
                    start: from,
                    stop: to,
                },
            ))
        }
        None => Box::new(CheckedSource::new(
            FixtureSource::load(&args.blocks, &args.only)?,
            // The four committed fixtures are four sampled points, not a range,
            // so only strict ascent is enforced here.
            Ordering::Sampled,
        )),
    };

    let base_report = host.new_report();
    let mut writer = match live_range {
        Some((from, to)) => ReportWriter::lines(
            &RunHeader::new(&base_report, source.describe(), Some((from, to))),
            args.out.clone(),
        )?,
        None => ReportWriter::whole(base_report, args.out.clone()),
    };

    let mut frames = match (&args.block_changes_out, live_range) {
        (Some(dir), Some(_)) => Some(FrameWriter::streaming(dir, host.descriptor_sha256())?),
        (Some(dir), None) => Some(FrameWriter::buffered(dir)?),
        (None, _) => None,
    };
    let mut bcf1 = match &args.bcf1_out {
        Some(path) => Some(Bcf1Writer::create(path, live_range.is_some())?),
        None => None,
    };
    let mut progress =
        live_range.map(|range| Progress::new(range, Duration::from_secs(args.progress_secs)));

    while let Some(block) = source.next_block().await? {
        let number = block.number();
        let outcome = host
            .process_block(block)
            .await
            .with_context(|| format!("replaying block {number}"))?;
        // Validate and round-trip every frame, whether or not it is written, so
        // a run cannot report success on a frame the engine would refuse.
        let bytes = blockchanges::seal(&outcome.changes, host.compatibility())
            .with_context(|| format!("sealing the BlockChanges frame for block {number}"))?;
        let mut block_report = outcome.report;
        block_report.block_changes = Some(blockchanges::summarize(&outcome.changes, &bytes));

        let block_number = outcome.changes.block_number;
        let block_hash = outcome.changes.block_hash.as_slice();
        if let Some(frames) = frames.as_mut() {
            frames.push(block_number, block_hash, &bytes)?;
        }
        if let Some(bcf1) = bcf1.as_mut() {
            bcf1.push(block_number, block_hash, &bytes)?;
        }
        if let Some(progress) = progress.as_mut() {
            progress.record(number, block_report.handler_groups.len());
            // A long recording run should not lose its rows to a crash at block
            // 900,000. The cassette is a sorted `BTreeMap`, so each rewrite is
            // the same bytes plus the new rows.
            if host.cassette().is_dirty() {
                host.cassette().save(&args.cassette)?;
            }
        }
        writer.push(block_report)?;
    }

    if let Some(frames) = frames {
        frames.finish(host.descriptor_sha256())?;
    }
    if let Some(bcf1) = bcf1 {
        bcf1.finish()?;
    }
    if host.cassette().is_dirty() {
        host.cassette().save(&args.cassette)?;
    }

    let blocks = writer.blocks();
    writer.finish(host.cassette().len())?;
    if let Some(progress) = progress {
        progress.finish();
        eprintln!(
            "{blocks} blocks replayed; {} cassette rows",
            host.cassette().len()
        );
    }
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
        let digest = descriptor::write(&segment, &args.repo_root, &logger)
            .await
            .with_context(|| format!("building the descriptor for {}", segment.display()))?;
        println!("{} {digest}", segment.display());
    }
    Ok(())
}
