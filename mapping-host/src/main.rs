//! `graph-mapping-host` — replay a deployed subgraph's mapping WASM over
//! Firehose block fixtures and write a deterministic report.

use std::path::PathBuf;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::{block, blockchanges, bundle, descriptor};

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
    #[arg(long, num_args = 1.., required = true)]
    blocks: Vec<PathBuf>,
    /// Replay only these block numbers, out of everything `--blocks` holds.
    #[arg(long, num_args = 1..)]
    only: Vec<i32>,
    /// The `eth_call` cassette.
    #[arg(long)]
    cassette: PathBuf,
    /// Record cassette misses against `ETHEREUM_RPC_URL` instead of failing.
    #[arg(long)]
    record: bool,
    /// Where to write the report. Defaults to stdout.
    #[arg(long)]
    out: Option<PathBuf>,
    /// Directory to write one canonical `<number>.pb` BlockChanges frame per
    /// block into, plus `index.json` with each frame's SHA-256.
    #[arg(long)]
    block_changes_out: Option<PathBuf>,
    /// Additionally write every frame as one `BCF1` clock-v1 stream, which the
    /// engine's `--input-format block-changes-v1-framed` reads directly.
    #[arg(long)]
    bcf1_out: Option<PathBuf>,
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

async fn run(args: RunArgs) -> Result<()> {
    let mut host = SegmentHost::load(SegmentHostConfig {
        bundle_dir: &args.segment,
        cassette_path: &args.cassette,
        record: args.record,
    })
    .await?;

    let mut report = host.new_report();

    // Replay in ascending order. Out of order would make both the store and the
    // PoI chain meaningless.
    use graph::blockchain::Block as _;
    let mut blocks: Vec<(i32, PathBuf, _)> = Vec::new();
    for path in &args.blocks {
        let b = block::load_block(path)?;
        blocks.push((b.number(), path.clone(), b));
    }
    if !args.only.is_empty() {
        blocks.retain(|(number, _, _)| args.only.contains(number));
        for wanted in &args.only {
            if !blocks.iter().any(|(number, _, _)| number == wanted) {
                bail!("block {wanted} was requested with --only but is not in --blocks");
            }
        }
    }
    blocks.sort_by_key(|(number, _, _)| *number);
    for pair in blocks.windows(2) {
        if pair[0].0 == pair[1].0 {
            bail!("block {} appears in more than one fixture", pair[0].0);
        }
    }

    let mut frames: Vec<(u64, Vec<u8>, Vec<u8>)> = Vec::new();
    for (number, path, b) in blocks {
        let outcome = host
            .process_block(b)
            .await
            .with_context(|| format!("replaying block {number} from {}", path.display()))?;
        // Validate and round-trip every frame, whether or not it is written, so
        // a run cannot report success on a frame the engine would refuse.
        let bytes = blockchanges::seal(&outcome.changes, host.compatibility())
            .with_context(|| format!("sealing the BlockChanges frame for block {number}"))?;
        let mut block_report = outcome.report;
        block_report.block_changes = Some(blockchanges::summarize(&outcome.changes, &bytes));
        frames.push((
            outcome.changes.block_number,
            outcome.changes.block_hash.clone(),
            bytes,
        ));
        report.blocks.push(block_report);
    }

    if let Some(dir) = &args.block_changes_out {
        write_frames(dir, &frames, host.descriptor_sha256())?;
    }
    if let Some(path) = &args.bcf1_out {
        write_bcf1(path, &frames)?;
    }

    if host.cassette().is_dirty() {
        host.cassette().save(&args.cassette)?;
    }
    report.cassette_entries = host.cassette().len();

    let json = report.to_json()?;
    match args.out {
        Some(path) => {
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&path, json).with_context(|| format!("writing {}", path.display()))?;
        }
        None => print!("{json}"),
    }
    Ok(())
}

/// One canonical frame per block, plus an index that pins each by SHA-256 and
/// records which descriptor they were sealed against.
fn write_frames(dir: &PathBuf, frames: &[(u64, Vec<u8>, Vec<u8>)], descriptor: &str) -> Result<()> {
    std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
    let mut entries = Vec::new();
    for (number, hash, bytes) in frames {
        let name = format!("{number}.pb");
        std::fs::write(dir.join(&name), bytes)
            .with_context(|| format!("writing {}", dir.join(&name).display()))?;
        entries.push(serde_json::json!({
            "block_number": number,
            "block_hash": format!("0x{}", hex::encode(hash)),
            "bytes": bytes.len(),
            "file": name,
            "sha256": bundle::sha256_hex(bytes),
        }));
    }
    let index = serde_json::json!({
        "contract": "pinax.graph.backfill.block-changes/v1",
        "descriptor_sha256": descriptor,
        "frames": entries,
        "schema": "pinax.substreams-backfills.mapping-host.block-changes-index/v1",
    });
    let mut json = serde_json::to_string_pretty(&index)?;
    json.push('\n');
    std::fs::write(dir.join("index.json"), json)?;
    Ok(())
}

/// The `BCF1` clock-v1 stream the engine consumes on stdin.
fn write_bcf1(path: &PathBuf, frames: &[(u64, Vec<u8>, Vec<u8>)]) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut stream = Vec::new();
    for (number, hash, bytes) in frames {
        stream.extend_from_slice(&blockchanges::bcf1_frame(*number, hash, bytes)?);
    }
    std::fs::write(path, stream).with_context(|| format!("writing {}", path.display()))?;
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
