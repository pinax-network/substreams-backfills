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
use graph_mapping_host::block::BlockIdentity;
use graph_mapping_host::checkpoint::{CheckpointBoundary, HostCheckpoint};
use graph_mapping_host::live::{Bcf1Writer, FrameWriter, Progress, ReportWriter};
use graph_mapping_host::report::RunHeader;
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::source::{
    token_from_env, BlockSource, CheckedSource, FirehoseSource, FirehoseTarget, FixtureSource,
    Ordering,
};
use graph_mapping_host::store_state::{StorePoi, StoreRange};
use graph_mapping_host::{block, blockchanges, bundle, descriptor, evidence};

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

/// The SHA-256 of a file, or the empty string when there is no file.
///
/// The cassette is the only input a run may legitimately rewrite, so its digest
/// is taken twice: once before the run, to check a checkpoint being loaded, and
/// once after, to record in the checkpoint being written.
fn file_sha256(path: &std::path::Path) -> Result<String> {
    if !path.exists() {
        return Ok(String::new());
    }
    let bytes = std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
    Ok(bundle::sha256_hex(&bytes))
}

/// Refuse a first block that does not continue the checkpoint.
///
/// Two checks, and they catch different things. The block number catches a
/// replay of ground the checkpoint already covers, whose effects would be
/// applied twice. The parent hash catches a *different chain* at the same
/// height, which no block number can see; it is only available when the first
/// block is the boundary's immediate successor, which a live range always is and
/// a sampled fixture run generally is not.
fn check_continuation(boundary: &CheckpointBoundary, first: &BlockIdentity) -> Result<()> {
    if first.number <= boundary.block {
        bail!(
            "the checkpoint already covers block {}, and this run starts at block {}: replaying \
             a block the checkpoint has already applied would apply its effects twice",
            boundary.block,
            first.number
        );
    }
    if first.number != boundary.block + 1 {
        return Ok(());
    }
    match first.parent_hash.as_deref() {
        Some(parent) if parent.eq_ignore_ascii_case(&boundary.block_hash) => Ok(()),
        Some(parent) => bail!(
            "block {} names parent {parent}, but the checkpoint stopped at block {} with hash {}: \
             this is a different chain, and continuing would fold two histories into one store",
            first.number,
            boundary.block,
            boundary.block_hash
        ),
        // A block with no parent pointer is the genesis block, which no segment
        // in this repository starts at; nothing to check.
        None => Ok(()),
    }
}

async fn run(args: RunArgs) -> Result<()> {
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

    // The cassette as it stands before the run. A recording run rewrites it, so
    // this is the digest a checkpoint being *loaded* must name, and the digest a
    // checkpoint being written names is taken again at the end.
    let cassette_before = file_sha256(&args.cassette)?;

    let mut host = SegmentHost::load(SegmentHostConfig {
        bundle_dir: &args.segment,
        cassette_path: &args.cassette,
        record: args.record,
    })
    .await?;

    if let Some((checkpoint, digest)) = resumed.as_ref() {
        host.restore_checkpoint(checkpoint, cassette_before)
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
    // The closing proof of indexing is the last block that opened the causality
    // region, not the last block replayed: a block in which no handler ran does
    // not advance the digest. A continuation starts from the checkpoint's, so a
    // chunk whose blocks open no region still reports the chain's closing value.
    let mut closing_poi: Option<StorePoi> = resumed
        .as_ref()
        .and_then(|(checkpoint, _)| checkpoint.header.poi.clone());

    let source_description = source.describe();
    // Checked against the first block that arrives, then dropped.
    let mut continues_from = resumed
        .as_ref()
        .map(|(checkpoint, _)| checkpoint.header.boundary.clone());
    // The last block applied, which is where a checkpoint written here stops.
    let mut last_applied: Option<(i32, String)> = None;

    while let Some(block) = source.next_block().await? {
        let number = block.number();
        if let Some(boundary) = continues_from.take() {
            check_continuation(&boundary, &block::identify(&block))?;
        }
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
        if let Some(poi) = block_report.poi.as_ref() {
            closing_poi = Some(StorePoi {
                block: number,
                version: poi.version.clone(),
                causality_regions: poi.causality_regions.clone(),
                public_digest: poi.public_digest.clone(),
            });
        }

        let block_number = outcome.changes.block_number;
        let block_hash = outcome.changes.block_hash.as_slice();
        if let Some(frames) = frames.as_mut() {
            frames.push(block_number, block_hash, &bytes)?;
        }
        if let Some(bcf1) = bcf1.as_mut() {
            bcf1.push(block_number, block_hash, &bytes)?;
        }
        last_applied = Some((number, block_report.hash.clone()));
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

    // After the cassette, so the digest recorded here is the file the next chunk
    // will load. A recording run appends rows; the next chunk must see the same
    // bytes or refuse.
    if let Some(path) = &args.checkpoint_out {
        let Some((block, block_hash)) = last_applied else {
            bail!(
                "--checkpoint-out {} was asked for but this run replayed no block, so there is no \
                 boundary to continue from",
                path.display()
            );
        };
        let previous = resumed
            .as_ref()
            .map(|(checkpoint, digest)| (checkpoint.header.boundary.clone(), digest.clone()));
        let blocks_in_chunk = writer.blocks();
        let boundary = CheckpointBoundary {
            block,
            block_hash,
            source: source_description,
            chunk_from: live_range.map(|(from, _)| from),
            chunk_to: live_range.map(|(_, to)| to),
            blocks_in_chunk,
            blocks_total: previous
                .as_ref()
                .map(|(boundary, _)| boundary.blocks_total)
                .unwrap_or_default()
                + blocks_in_chunk,
            chunk_index: previous
                .as_ref()
                .map(|(boundary, _)| boundary.chunk_index + 1)
                .unwrap_or_default(),
            previous_checkpoint_sha256: previous.map(|(_, digest)| digest),
        };
        let checkpoint = host.checkpoint(file_sha256(&args.cassette)?, boundary, closing_poi)?;
        let digest = checkpoint.write(path)?;
        eprintln!(
            "{}: {} rows, {} dynamic data sources, after block {} ({digest})",
            path.display(),
            checkpoint.rows.len(),
            checkpoint.data_sources.len(),
            checkpoint.header.boundary.block
        );
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

/// Derive the evidence summary and its per-block sibling, and write both.
///
/// Nothing here touches the network or replays a block: the report the run
/// already wrote is the only input, which is what makes the summary a record of
/// *that* run rather than of a second one.
fn summarize(args: SummarizeArgs) -> Result<()> {
    let per_block_path = args.per_block.clone().unwrap_or_else(|| {
        args.evidence
            .with_extension("")
            .with_extension("blocks.jsonl")
    });
    let per_block_name = per_block_path
        .file_name()
        .map(|name| name.to_string_lossy().to_string())
        .unwrap_or_else(|| per_block_path.to_string_lossy().to_string());

    // Carrying the previous file's prose forward is the whole reason this reads
    // before it writes. A file that does not parse is an error, not a silent
    // reset that would drop hand-written findings.
    let previous = evidence::Narrative::read(&args.evidence)?;

    let (summary, per_block) = evidence::summarize(evidence::SummarizeInputs {
        report: &args.report,
        previous,
        per_block_name,
        segment: args.segment.as_deref(),
        cassette: args.cassette.as_deref(),
        goldens: args.goldens.as_deref(),
        sampled_report: args.sampled_report.as_deref(),
    })?;

    if let Some(parent) = args.evidence.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("creating {}", parent.display()))?;
    }
    std::fs::write(&per_block_path, &per_block)
        .with_context(|| format!("writing {}", per_block_path.display()))?;
    std::fs::write(&args.evidence, summary.to_json()?)
        .with_context(|| format!("writing {}", args.evidence.display()))?;

    eprintln!(
        "{}: {} blocks, {} handler groups, {} operations",
        args.evidence.display(),
        summary.range.blocks,
        summary.totals.handler_groups,
        summary.totals.operations
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
        let digest = descriptor::write(&segment, &args.repo_root, &logger)
            .await
            .with_context(|| format!("building the descriptor for {}", segment.display()))?;
        println!("{} {digest}", segment.display());
    }
    Ok(())
}
