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
//! Nothing here prints unless it is asked to: [`Progress`] is constructed only
//! by the live path in `main`, so the hermetic tests, which drive
//! [`crate::runner::SegmentHost`] directly, emit nothing at all.

use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

use crate::bundle;
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
    pub fn lines(header: &RunHeader, out: Option<PathBuf>) -> Result<Self> {
        let mut sink: Box<dyn Write> = match &out {
            Some(path) => Box::new(BufWriter::new(create(path)?)),
            None => Box::new(std::io::stdout()),
        };
        sink.write_all(json_line(header)?.as_bytes())?;
        sink.flush()?;
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
    pub fn streaming(dir: &Path, descriptor_sha256: &str) -> Result<Self> {
        std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
        let mut sink = BufWriter::new(create(&dir.join("index.jsonl"))?);
        let header = serde_json::json!({
            "contract": BLOCK_CHANGES_CONTRACT,
            "descriptor_sha256": descriptor_sha256,
            "schema": FRAME_INDEX_STREAM_SCHEMA,
        });
        sink.write_all(json_line(&header)?.as_bytes())?;
        sink.flush()?;
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
    pub fn create(path: &Path, flush_each: bool) -> Result<Self> {
        Ok(Bcf1Writer {
            sink: BufWriter::new(create(path)?),
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
        }
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
        eprintln!(
            "block {at}  {}/{total} blocks  {rate:.1} blocks/s  {} handler groups  {:.0}s{suffix}",
            self.blocks, self.handler_groups, elapsed
        );
    }
}
