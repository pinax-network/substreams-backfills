//! The per-block replay loop, and where a checkpoint is allowed to land.
//!
//! Lifted out of `main.rs` so a test can drive it with a source that fails
//! whenever it likes. A fake Firehose is the only honest way to prove what
//! happens after a twenty-hour stream dies, and the loop, not the CLI, is where
//! that behaviour lives.
//!
//! ## The invariant
//!
//! **A checkpoint on disk always describes a block boundary that was fully
//! applied, and the per-block outputs on disk always cover at least that
//! boundary.**
//!
//! Both halves are enforced by ordering, and the order is the whole design:
//!
//! 1. `process_block` applies the block to the store, or fails and leaves the
//!    host untouched by it. Nothing has been written yet.
//! 2. The frame is sealed, then written to `<number>.pb`, then to the index,
//!    then to the `BCF1` stream, then to the report — each flushed as it goes.
//! 3. Only then, and only on a `--checkpoint-every` boundary, is the cassette
//!    saved and the checkpoint written, atomically, through a temporary file
//!    and a rename.
//!
//! So a process killed anywhere in step 2 leaves outputs ahead of the
//! checkpoint, which [`crate::outputs`] knows how to cut back. A process killed
//! during step 3 leaves either the old checkpoint or the new one, never half of
//! one, because `rename` is atomic. There is no ordering in which the checkpoint
//! is ahead of the outputs, and there is none in which it names a block whose
//! effects are only partly in the store.
//!
//! The one thing not claimed is durability against power loss: the writers are
//! flushed to the operating system, not `fsync`ed to the platter, on every block
//! (the checkpoint and the trimmer do `fsync`). Against a process that dies —
//! which is what a broken stream, an OOM kill or a `^C` actually is — flushing
//! is exactly enough.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use graph::blockchain::Block as _;

use crate::block::{self, BlockIdentity};
use crate::checkpoint::CheckpointBoundary;
use crate::live::{Bcf1Writer, FrameWriter, Progress, ReportWriter};
use crate::runner::SegmentHost;
use crate::source::{BlockSource, ReconnectCounter};
use crate::store_state::StorePoi;
use crate::{blockchanges, bundle};

/// Every per-block sink a replay writes to.
pub struct ReplayOutputs {
    pub report: ReportWriter,
    pub frames: Option<FrameWriter>,
    pub bcf1: Option<Bcf1Writer>,
    pub progress: Option<Progress>,
    /// A live reconnect count, when the source is one that reconnects.
    pub reconnects: Option<ReconnectCounter>,
}

/// When and where a checkpoint is written.
pub struct CheckpointPolicy {
    /// The checkpoint path. `None` disables checkpointing.
    pub out: Option<PathBuf>,
    /// Blocks between mid-run checkpoints. `None` writes one at the end only.
    pub every: Option<usize>,
    /// The cassette, saved before every checkpoint so the digest a checkpoint
    /// records is the digest of the file the next chunk will load.
    pub cassette: PathBuf,
    /// `source.describe()`, recorded in the boundary. Never carries a token.
    pub source: String,
    /// The half-open range this chunk was asked for, when it was asked for one.
    pub range: Option<(i32, i32)>,
    /// The checkpoint this run resumed from, and its digest.
    pub previous: Option<(CheckpointBoundary, String)>,
}

impl CheckpointPolicy {
    /// A policy that never writes anything.
    pub fn none(cassette: &Path, source: String) -> Self {
        CheckpointPolicy {
            out: None,
            every: None,
            cassette: cassette.to_path_buf(),
            source,
            range: None,
            previous: None,
        }
    }

    /// Save the cassette, then write a checkpoint describing everything applied
    /// through `last_applied`.
    ///
    /// The cassette first, because a recording run appends rows as it goes and
    /// the checkpoint pins the cassette by digest: a checkpoint naming a digest
    /// the file no longer has is one that can never be resumed from.
    ///
    /// Returns the checkpoint's SHA-256.
    pub fn write(
        &self,
        host: &SegmentHost,
        blocks_in_chunk: usize,
        last_applied: &(i32, String),
        poi: Option<StorePoi>,
    ) -> Result<String> {
        let Some(path) = self.out.as_deref() else {
            bail!("a checkpoint was asked for but no --checkpoint-out was given");
        };
        if host.cassette().is_dirty() {
            host.cassette().save(&self.cassette)?;
        }
        let (block, block_hash) = last_applied.clone();
        let boundary = CheckpointBoundary {
            block,
            block_hash,
            source: self.source.clone(),
            chunk_from: self.range.map(|(from, _)| from),
            chunk_to: self.range.map(|(_, to)| to),
            blocks_in_chunk,
            blocks_total: self
                .previous
                .as_ref()
                .map(|(boundary, _)| boundary.blocks_total)
                .unwrap_or_default()
                + blocks_in_chunk,
            chunk_index: self
                .previous
                .as_ref()
                .map(|(boundary, _)| boundary.chunk_index + 1)
                .unwrap_or_default(),
            previous_checkpoint_sha256: self.previous.as_ref().map(|(_, digest)| digest.clone()),
        };
        // Fingerprinted *after* the save above, so what the checkpoint pins is
        // the cassette the next chunk will load rather than the one this chunk
        // started from.
        let cassette = host
            .cassette()
            .fingerprint(file_sha256(&self.cassette)?)
            .context("fingerprinting the cassette for a checkpoint")?;
        let checkpoint = host.checkpoint(&cassette, boundary, poi)?;
        let digest = checkpoint.write(path)?;
        eprintln!(
            "{}: {} rows, {} dynamic data sources, {} cassette row(s) pinned, after block \
             {block} ({digest})",
            path.display(),
            checkpoint.rows.len(),
            checkpoint.data_sources.len(),
            checkpoint.cassette_rows.len(),
        );
        Ok(digest)
    }
}

/// What a replay left behind.
#[derive(Clone, Debug)]
pub struct ReplayResult {
    /// Blocks this run replayed.
    pub blocks: usize,
    /// The closing proof of indexing across the whole chain of chunks.
    pub closing_poi: Option<StorePoi>,
    /// The last block applied, and its hash.
    pub last_applied: Option<(i32, String)>,
    /// The last block a mid-run checkpoint covered, and that checkpoint's
    /// digest. `None` when no mid-run checkpoint was written.
    pub last_checkpoint: Option<(i32, String)>,
}

/// Replay every block `source` produces, writing outputs and checkpoints.
///
/// `continues_from` is the boundary of a checkpoint this run resumed from; it is
/// checked against the first block that arrives and then dropped. `closing_poi`
/// seeds the chain from that same checkpoint, so a chunk whose blocks open no
/// causality region still reports the chain's closing value.
pub async fn replay_range(
    host: &mut SegmentHost,
    source: &mut dyn BlockSource,
    outputs: &mut ReplayOutputs,
    policy: &CheckpointPolicy,
    mut continues_from: Option<CheckpointBoundary>,
    mut closing_poi: Option<StorePoi>,
) -> Result<ReplayResult> {
    let mut last_applied: Option<(i32, String)> = None;
    let mut last_checkpoint: Option<(i32, String)> = None;
    let mut since_checkpoint = 0usize;
    let periodic = match (policy.out.as_deref(), policy.every) {
        (Some(_), Some(every)) if every > 0 => Some(every),
        _ => None,
    };

    while let Some(raw_block) = source.next_block().await? {
        let number = raw_block.number();
        if let Some(boundary) = continues_from.take() {
            check_continuation(&boundary, &block::identify(&raw_block))?;
        }
        let outcome = host
            .process_block(raw_block)
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
        if let Some(frames) = outputs.frames.as_mut() {
            frames.push(block_number, block_hash, &bytes)?;
        }
        if let Some(bcf1) = outputs.bcf1.as_mut() {
            bcf1.push(block_number, block_hash, &bytes)?;
        }
        last_applied = Some((number, block_report.hash.clone()));
        let reconnects = outputs.reconnects.as_ref().map(ReconnectCounter::get);
        if let Some(progress) = outputs.progress.as_mut() {
            if let Some(reconnects) = reconnects {
                progress.record_reconnects(reconnects);
            }
            progress.record(number, block_report.handler_groups.len());
            // A long recording run should not lose its rows to a crash at block
            // 900,000. The cassette is a sorted `BTreeMap`, so each rewrite is
            // the same bytes plus the new rows.
            if host.cassette().is_dirty() {
                host.cassette().save(&policy.cassette)?;
            }
        }
        // Last, so that once this returns every artifact for this block is on
        // disk and a checkpoint taken now cannot be ahead of any of them.
        outputs.report.push(block_report)?;

        since_checkpoint += 1;
        if let Some(every) = periodic {
            if since_checkpoint >= every {
                let applied = last_applied
                    .as_ref()
                    .expect("a block was just applied")
                    .clone();
                let digest =
                    policy.write(host, outputs.report.blocks(), &applied, closing_poi.clone())?;
                last_checkpoint = Some((applied.0, digest));
                since_checkpoint = 0;
                if let Some(progress) = outputs.progress.as_mut() {
                    progress.record_checkpoint(applied.0);
                }
            }
        }
    }

    Ok(ReplayResult {
        blocks: outputs.report.blocks(),
        closing_poi,
        last_applied,
        last_checkpoint,
    })
}

/// The SHA-256 of a file, or the empty string when there is no file.
///
/// The cassette is the only input a run may legitimately rewrite, so its digest
/// is taken twice: once before the run, to check a checkpoint being loaded, and
/// again at each checkpoint, to record in the one being written.
pub fn file_sha256(path: &Path) -> Result<String> {
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
pub fn check_continuation(boundary: &CheckpointBoundary, first: &BlockIdentity) -> Result<()> {
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
