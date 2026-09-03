//! `graph-mapping-host` — replay a deployed subgraph's mapping WASM over
//! Firehose block fixtures and write a deterministic report.

use std::path::PathBuf;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use graph_mapping_host::block;
use graph_mapping_host::bundle;
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};

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

    for (number, path, b) in blocks {
        let block_report = host
            .process_block(b)
            .await
            .with_context(|| format!("replaying block {number} from {}", path.display()))?;
        report.blocks.push(block_report);
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
