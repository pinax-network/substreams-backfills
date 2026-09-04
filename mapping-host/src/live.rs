//! Streaming output, for runs too long to buffer.
//!
//! A fixture run is four blocks and can hold everything in memory: it writes one
//! pretty-printed [`RunReport`], one `index.json`, and one `BCF1` stream, all at
//! the end. That is what the goldens pin, and none of it changes here.
//!
//! A live run cannot. The Uniswap V3 parity window is 1,053 blocks and the full
//! segment-1 range is 1,081,260, so the report becomes JSON Lines — a header
//! line, then one object per block — the frame index becomes `index.jsonl`, and
//! every writer is flushed per block. Both modes write the same `<number>.pb`
//! frames into the same directory and the same `BCF1` byte stream, so a live run
//! over a fixture's block produces byte-identical artifacts.
//!
//! A fixture run joins the streamed column in one case: `--checkpoint-every`. A
//! mid-run checkpoint may never describe a block that no output file records,
//! and a whole-document report records nothing until the run ends, so asking for
//! periodic checkpoints necessarily asks for a streamed report and a streamed
//! index. See [`crate::outputs`].
//!
//! Each writer can also be opened to *append*, which happens only after
//! [`crate::outputs`] has cut the file back to a checkpoint boundary: an
//! appending report and an appending index skip their header line, because the
//! file already carries it.
//!
//! Nothing here prints unless it is asked to: [`Progress`] is constructed only
//! by the live path in `main`, so the hermetic tests, which drive
//! [`crate::runner::SegmentHost`] directly, emit nothing at all.

use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

use crate::bundle;
use crate::outputs::Disposition;
use crate::report::{json_line, BlockReport, RunHeader, RunReport};

/// Schema identifier for the first line of a streamed frame index.
pub const FRAME_INDEX_STREAM_SCHEMA: &str =
    "pinax.substreams-backfills.mapping-host.block-changes-index-stream/v1";

/// Schema identifier for the whole-run frame index a fixture run writes.
pub const FRAME_INDEX_SCHEMA: &str =
    "pinax.substreams-backfills.mapping-host.block-changes-index/v1";

/// The `BlockChanges` contract every frame is sealed against.
pub const BLOCK_CHANGES_CONTRACT: &str = "pinax.graph.backfill.block-changes/v1";

/// Open a file for writing, creating its parent directory.
fn create(path: &Path) -> Result<std::fs::File> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("creating {}", parent.display()))?;
        }
    }
    std::fs::File::create(path).with_context(|| format!("creating {}", path.display()))
}

/// Open a file for appending, creating its parent directory.
///
/// Only ever reached after [`crate::outputs`] has cut the file back to a
/// checkpoint boundary, so what is appended to is a prefix of a run rather than
/// a whole one.
fn append(path: &Path) -> Result<std::fs::File> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("creating {}", parent.display()))?;
        }
    }
    std::fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(path)
        .with_context(|| format!("opening {} to append", path.display()))
}

/// Open a file fresh or for appending, as [`Disposition`] decided.
fn open_for(path: &Path, disposition: Disposition) -> Result<std::fs::File> {
    match disposition {
        Disposition::Fresh => create(path),
        Disposition::Append => append(path),
    }
}

/// Where the per-block report goes.
enum ReportMode {
    /// Buffer every block and write one pretty JSON document at the end.
    Whole {
        report: RunReport,
        out: Option<PathBuf>,
    },
    /// A header line, then one line per block, flushed as each is produced.
    Lines {
        sink: Box<dyn Write>,
        blocks: usize,
        out: Option<PathBuf>,
    },
}

/// The run report, buffered or streamed.
pub struct ReportWriter(ReportMode);

impl ReportWriter {
    /// One pretty-printed [`RunReport`], written at the end. Byte-for-byte what
    /// `mapping-host` has always produced.
    pub fn whole(report: RunReport, out: Option<PathBuf>) -> Self {
        ReportWriter(ReportMode::Whole { report, out })
    }

    /// JSON Lines: the header now, one object per block as they arrive.
    ///
    /// With [`Disposition::Append`] the file already carries the header and the
    /// blocks up to a checkpoint boundary, so only the block lines are added;
    /// writing a second header would make the stream unreadable.
    pub fn lines(
        header: &RunHeader,
        out: Option<PathBuf>,
        disposition: Disposition,
    ) -> Result<Self> {
        let mut sink: Box<dyn Write> = match &out {
            Some(path) => Box::new(BufWriter::new(open_for(path, disposition)?)),
            None => Box::new(std::io::stdout()),
        };
        if disposition == Disposition::Fresh {
            sink.write_all(json_line(header)?.as_bytes())?;
            sink.flush()?;
        }
        Ok(ReportWriter(ReportMode::Lines {
            sink,
            blocks: 0,
            out,
        }))
    }

    pub fn push(&mut self, block: BlockReport) -> Result<()> {
        match &mut self.0 {
            ReportMode::Whole { report, .. } => {
                report.blocks.push(block);
                Ok(())
            }
            ReportMode::Lines { sink, blocks, .. } => {
                sink.write_all(json_line(&block)?.as_bytes())?;
                sink.flush()?;
                *blocks += 1;
                Ok(())
            }
        }
    }

    /// How many blocks have been written so far.
    pub fn blocks(&self) -> usize {
        match &self.0 {
            ReportMode::Whole { report, .. } => report.blocks.len(),
            ReportMode::Lines { blocks, .. } => *blocks,
        }
    }

    /// Where the report was written, for the closing summary.
    pub fn destination(&self) -> Option<&Path> {
        match &self.0 {
            ReportMode::Whole { out, .. } | ReportMode::Lines { out, .. } => out.as_deref(),
        }
    }

    pub fn finish(self, cassette_entries: usize) -> Result<()> {
        match self.0 {
            ReportMode::Whole { mut report, out } => {
                report.cassette_entries = cassette_entries;
                let json = report.to_json()?;
                match out {
                    Some(path) => {
                        if let Some(parent) = path.parent() {
                            if !parent.as_os_str().is_empty() {
                                std::fs::create_dir_all(parent)?;
                            }
                        }
                        std::fs::write(&path, json)
                            .with_context(|| format!("writing {}", path.display()))?;
                    }
                    None => print!("{json}"),
                }
                Ok(())
            }
            ReportMode::Lines { mut sink, .. } => {
                // Every line was already flushed; this only drains the
                // `BufWriter` wrapper, which a `Drop` would swallow errors from.
                sink.flush()?;
                Ok(())
            }
        }
    }
}

/// The frame index, buffered (`index.json`) or streamed (`index.jsonl`).
enum IndexMode {
    Buffered(Vec<serde_json::Value>),
    Lines(BufWriter<std::fs::File>),
}

/// One canonical `<number>.pb` per block, plus an index pinning each by SHA-256.
pub struct FrameWriter {
    dir: PathBuf,
    index: IndexMode,
}

impl FrameWriter {
    /// Buffer the index and write `index.json` at the end.
    pub fn buffered(dir: &Path) -> Result<Self> {
        std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
        Ok(FrameWriter {
            dir: dir.to_path_buf(),
            index: IndexMode::Buffered(Vec::new()),
        })
    }

    /// Append to `index.jsonl` as each frame lands.
    pub fn streaming(
        dir: &Path,
        descriptor_sha256: &str,
        disposition: Disposition,
    ) -> Result<Self> {
        std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
        let mut sink = BufWriter::new(open_for(&dir.join("index.jsonl"), disposition)?);
        if disposition == Disposition::Fresh {
            let header = serde_json::json!({
                "contract": BLOCK_CHANGES_CONTRACT,
                "descriptor_sha256": descriptor_sha256,
                "schema": FRAME_INDEX_STREAM_SCHEMA,
            });
            sink.write_all(json_line(&header)?.as_bytes())?;
            sink.flush()?;
        }
        Ok(FrameWriter {
            dir: dir.to_path_buf(),
            index: IndexMode::Lines(sink),
        })
    }

    pub fn push(&mut self, number: u64, hash: &[u8], bytes: &[u8]) -> Result<()> {
        let name = format!("{number}.pb");
        let path = self.dir.join(&name);
        std::fs::write(&path, bytes).with_context(|| format!("writing {}", path.display()))?;
        let entry = serde_json::json!({
            "block_number": number,
            "block_hash": format!("0x{}", hex::encode(hash)),
            "bytes": bytes.len(),
            "file": name,
            "sha256": bundle::sha256_hex(bytes),
        });
        match &mut self.index {
            IndexMode::Buffered(entries) => entries.push(entry),
            IndexMode::Lines(sink) => {
                sink.write_all(json_line(&entry)?.as_bytes())?;
                sink.flush()?;
            }
        }
        Ok(())
    }

    pub fn finish(self, descriptor_sha256: &str) -> Result<()> {
        match self.index {
            IndexMode::Buffered(entries) => {
                let index = serde_json::json!({
                    "contract": BLOCK_CHANGES_CONTRACT,
                    "descriptor_sha256": descriptor_sha256,
                    "frames": entries,
                    "schema": FRAME_INDEX_SCHEMA,
                });
                let mut json = serde_json::to_string_pretty(&index)?;
                json.push('\n');
                let path = self.dir.join("index.json");
                std::fs::write(&path, json)
                    .with_context(|| format!("writing {}", path.display()))?;
                Ok(())
            }
            IndexMode::Lines(mut sink) => {
                sink.flush()?;
                Ok(())
            }
        }
    }
}

/// The `BCF1` clock-v1 stream, written frame by frame.
///
/// Concatenation is the whole format, so streaming and buffering produce
/// identical bytes.
pub struct Bcf1Writer {
    sink: BufWriter<std::fs::File>,
    flush_each: bool,
}

impl Bcf1Writer {
    pub fn create(path: &Path, flush_each: bool, disposition: Disposition) -> Result<Self> {
        Ok(Bcf1Writer {
            sink: BufWriter::new(open_for(path, disposition)?),
            flush_each,
        })
    }

    pub fn push(&mut self, number: u64, hash: &[u8], bytes: &[u8]) -> Result<()> {
        self.sink
            .write_all(&crate::blockchanges::bcf1_frame(number, hash, bytes)?)?;
        if self.flush_each {
            self.sink.flush()?;
        }
        Ok(())
    }

    pub fn finish(mut self) -> Result<()> {
        self.sink.flush()?;
        Ok(())
    }
}

/// Periodic stderr progress for a run long enough to need watching.
pub struct Progress {
    started: Instant,
    last_tick: Instant,
    every: Duration,
    range: (i32, i32),
    blocks: u64,
    handler_groups: u64,
    last_block: Option<i32>,
    /// The last block a checkpoint on disk describes, which is where a killed
    /// run would resume from. An operator watching a twenty-hour replay needs
    /// this more than any other number on the line.
    last_checkpoint: Option<i32>,
    reconnects: u64,
}

impl Progress {
    /// `every` of zero disables output entirely.
    pub fn new(range: (i32, i32), every: Duration) -> Self {
        let now = Instant::now();
        Progress {
            started: now,
            last_tick: now,
            every,
            range,
            blocks: 0,
            handler_groups: 0,
            last_block: None,
            last_checkpoint: None,
            reconnects: 0,
        }
    }

    /// Record that a checkpoint now on disk covers everything through `block`.
    pub fn record_checkpoint(&mut self, block: i32) {
        self.last_checkpoint = Some(block);
    }

    /// Record how many times the stream has been re-opened so far.
    pub fn record_reconnects(&mut self, reconnects: u64) {
        self.reconnects = reconnects;
    }

    /// Record one block and print a line if the interval has elapsed.
    pub fn record(&mut self, number: i32, handler_groups: usize) {
        self.blocks += 1;
        self.handler_groups += handler_groups as u64;
        self.last_block = Some(number);
        if self.every.is_zero() {
            return;
        }
        let now = Instant::now();
        if now.duration_since(self.last_tick) < self.every {
            return;
        }
        self.last_tick = now;
        self.emit("");
    }

    /// The closing line, printed unconditionally.
    pub fn finish(&self) {
        self.emit(" done");
    }

    fn emit(&self, suffix: &str) {
        eprintln!("{}", self.line(suffix));
    }

    /// The line `emit` prints. Split out so its shape is testable without
    /// capturing stderr.
    pub fn line(&self, suffix: &str) -> String {
        let elapsed = self.started.elapsed().as_secs_f64();
        let rate = if elapsed > 0.0 {
            self.blocks as f64 / elapsed
        } else {
            0.0
        };
        let (from, to) = self.range;
        let total = (to - from) as u64;
        let at = self
            .last_block
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_string());
        let checkpoint = self
            .last_checkpoint
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_string());
        let reconnects = if self.reconnects == 0 {
            String::new()
        } else {
            format!("  {} reconnects", self.reconnects)
        };
        format!(
            "block {at}  {}/{total} blocks  {rate:.1} blocks/s  {} handler groups  \
             checkpoint {checkpoint}{reconnects}  {:.0}s{suffix}",
            self.blocks, self.handler_groups, elapsed
        )
    }
}

#[cfg(test)]
mod progress_tests {
    use super::*;

    #[test]
    fn the_progress_line_names_the_last_checkpoint() {
        let mut progress = Progress::new((100, 200), Duration::from_secs(3600));
        progress.record(100, 2);
        progress.record(101, 0);
        // Nothing checkpointed yet: an operator must be able to tell the
        // difference between "no recovery point" and "a recovery point at 0".
        assert!(
            progress.line("").contains("checkpoint -"),
            "{}",
            progress.line("")
        );

        progress.record_checkpoint(101);
        progress.record(102, 1);
        let line = progress.line("");
        assert!(line.contains("checkpoint 101"), "{line}");
        assert!(line.contains("3/100 blocks"), "{line}");
        assert!(line.contains("3 handler groups"), "{line}");
        // No reconnect yet, so the line stays quiet about them.
        assert!(!line.contains("reconnects"), "{line}");

        progress.record_reconnects(2);
        assert!(
            progress.line("").contains("2 reconnects"),
            "{}",
            progress.line("")
        );
    }
}
