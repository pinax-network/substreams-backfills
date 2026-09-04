//! What a resumed run may do to output files that already exist.
//!
//! ## The problem periodic checkpointing creates
//!
//! A checkpoint written at block `B` and the per-block outputs are two records
//! of the same replay, and they advance at different rates. The outputs advance
//! every block; the checkpoint advances every `--checkpoint-every` blocks. So
//! when a run dies at block `D`, the report, the frame index, the `BCF1` stream
//! and the `<number>.pb` frames all cover `(.., D]` while the checkpoint covers
//! `(.., B]` with `B <= D`. Resuming from `B` and appending would write blocks
//! `B+1 ..= D` a second time. Nothing in the file formats would notice: the
//! report is JSON Lines, the index is JSON Lines, and `BCF1` is bare
//! concatenation, so a duplicated span parses perfectly and is simply wrong.
//!
//! ## The rule
//!
//! **A run that resumes from a checkpoint never appends to an output it has not
//! first cut back to the checkpoint's boundary, and never cuts one back without
//! being told to.**
//!
//! Concretely, for each output destination a resuming run was given:
//!
//! * it does not exist — write it fresh, which is the per-chunk model `#138`
//!   established and the concatenation of chunk files stays exact;
//! * it exists and `--continue-outputs` was not given — **refuse**, naming the
//!   file. This is the default because the run cannot know whether the file is a
//!   dead sibling of this checkpoint or a finished chunk somebody still needs;
//! * it exists and `--continue-outputs` was given — **trim it to exactly the
//!   checkpoint boundary and append**. Every record past the boundary is
//!   dropped, including a torn last record, and the trim refuses outright if
//!   what is left does not end at the boundary.
//!
//! The last case is what makes crash recovery one command: re-run the same
//! command line with `--checkpoint-in` and `--continue-outputs`, and the outputs
//! and the checkpoint are made to agree before a single new block is replayed.
//!
//! ## Why trimming is safe to define
//!
//! Every streamed output is a sequence of records that names its own block:
//! the report's block lines carry `number`, `index.jsonl` carries
//! `block_number`, a `BCF1` frame carries the block number in its 52-byte
//! header, and a frame file *is* `<number>.pb`. So "the prefix covering blocks
//! `<= B`" is well defined in all four, and a trim is a truncation at a record
//! boundary rather than a rewrite.
//!
//! A whole-document report — the pretty-printed `RunReport` a fixture run writes
//! at the end — has no such prefix, so it cannot be trimmed and is refused.
//! `--checkpoint-every` therefore switches the report and the frame index to
//! their streamed forms in every mode: a checkpoint that is ahead of every
//! output file is exactly the inconsistency this module exists to prevent.
//!
//! `--store-out` is not in scope. It is a whole-file dump of the final store
//! written once at the end, so it is either absent or complete; a resumed run
//! overwrites it with the state it actually reached.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};

use crate::blockchanges::BCF1_MAGIC;

/// The fixed part of a `BCF1` frame: magic, version, three padding bytes, the
/// block number, the block hash and the payload length.
const BCF1_HEADER: usize = 4 + 1 + 3 + 8 + 32 + 4;

/// How a run may treat output files that already exist.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResumePolicy {
    /// Not resuming from a checkpoint. Existing files are overwritten, which is
    /// what every run did before checkpoints existed.
    Fresh,
    /// Resuming. Any existing output is refused, because appending to it would
    /// duplicate the blocks between the checkpoint and where it actually ends.
    Refuse { boundary: i32 },
    /// Resuming, and told to continue the outputs in place: each is trimmed back
    /// to `boundary` and appended to.
    Continue { boundary: i32 },
}

impl ResumePolicy {
    /// The policy a run has, given whether it resumed and what it was told.
    pub fn new(boundary: Option<i32>, continue_outputs: bool) -> Result<Self> {
        match (boundary, continue_outputs) {
            (None, false) => Ok(ResumePolicy::Fresh),
            (None, true) => bail!(
                "--continue-outputs only means something with --checkpoint-in: there is no \
                 boundary to continue the output files from"
            ),
            (Some(boundary), false) => Ok(ResumePolicy::Refuse { boundary }),
            (Some(boundary), true) => Ok(ResumePolicy::Continue { boundary }),
        }
    }
}

/// Whether a writer opens a fresh file or appends to a trimmed one.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Disposition {
    /// Nothing was there, or nothing is being resumed: write from scratch.
    Fresh,
    /// The file was trimmed to the boundary; append to what is left.
    Append,
}

/// Refuse an existing destination, with the reason and the two ways out.
fn refuse(path: &Path, boundary: i32, what: &str) -> anyhow::Error {
    anyhow::anyhow!(
        "{} already exists, and this run resumes from a checkpoint that stops after block \
         {boundary}. {what} covering blocks past {boundary} would be written twice, once by the \
         run that produced this file and once by this one, and neither the file format nor a \
         later consumer would notice. Either point this run at a path of its own and concatenate \
         the chunks afterwards, or pass --continue-outputs to cut this file back to block \
         {boundary} first.",
        path.display()
    )
}

/// Decide what to do with a streamed JSON Lines report at `path`.
pub fn prepare_report(
    path: Option<&Path>,
    streaming: bool,
    policy: ResumePolicy,
) -> Result<Disposition> {
    let Some(path) = path else {
        return Ok(Disposition::Fresh);
    };
    let Some(boundary) = boundary_of(policy) else {
        return Ok(Disposition::Fresh);
    };
    if !path.exists() {
        return Ok(Disposition::Fresh);
    }
    match policy {
        ResumePolicy::Continue { .. } => {
            if !streaming {
                bail!(
                    "{} already exists and this run writes one whole-document report at the end, \
                     which has no prefix to cut back to block {boundary}. Pass \
                     --checkpoint-every to stream the report, or point --out at a path of its \
                     own.",
                    path.display()
                );
            }
            let kept = trim_jsonl(path, "number", boundary, "report")?;
            eprintln!(
                "{}: trimmed to {kept} block(s), ending at block {boundary}",
                path.display()
            );
            Ok(Disposition::Append)
        }
        _ => Err(refuse(path, boundary, "The per-block report lines")),
    }
}

/// Decide what to do with a frame directory: its index and its `<n>.pb` files.
pub fn prepare_frames(
    dir: Option<&Path>,
    streaming: bool,
    policy: ResumePolicy,
) -> Result<Disposition> {
    let Some(dir) = dir else {
        return Ok(Disposition::Fresh);
    };
    let Some(boundary) = boundary_of(policy) else {
        return Ok(Disposition::Fresh);
    };
    let index = dir.join("index.jsonl");
    let buffered = dir.join("index.json");
    let has_frames = !frame_files(dir, i32::MIN)?.is_empty();
    if !dir.exists() || (!index.exists() && !buffered.exists() && !has_frames) {
        return Ok(Disposition::Fresh);
    }
    match policy {
        ResumePolicy::Continue { .. } => {
            if buffered.exists() {
                bail!(
                    "{} already exists: it is a whole-document frame index, written at the end of \
                     a run, so it has no prefix to cut back to block {boundary}. Point \
                     --block-changes-out at a directory of its own.",
                    buffered.display()
                );
            }
            if !streaming {
                bail!(
                    "{} already holds frames and this run writes a whole-document index at the \
                     end. Pass --checkpoint-every to stream the index, or point \
                     --block-changes-out at a directory of its own.",
                    dir.display()
                );
            }
            let kept = trim_jsonl(&index, "block_number", boundary, "frame index")?;
            let dropped = remove_frames_after(dir, boundary)?;
            eprintln!(
                "{}: trimmed to {kept} frame(s) ending at block {boundary}; {dropped} frame \
                 file(s) removed",
                dir.display()
            );
            Ok(Disposition::Append)
        }
        _ => Err(refuse(dir, boundary, "The BlockChanges frames and index")),
    }
}

/// Decide what to do with a `BCF1` stream at `path`.
pub fn prepare_bcf1(path: Option<&Path>, policy: ResumePolicy) -> Result<Disposition> {
    let Some(path) = path else {
        return Ok(Disposition::Fresh);
    };
    let Some(boundary) = boundary_of(policy) else {
        return Ok(Disposition::Fresh);
    };
    if !path.exists() {
        return Ok(Disposition::Fresh);
    }
    match policy {
        ResumePolicy::Continue { .. } => {
            let kept = trim_bcf1(path, boundary)?;
            eprintln!(
                "{}: trimmed to {kept} frame(s), ending at block {boundary}",
                path.display()
            );
            Ok(Disposition::Append)
        }
        _ => Err(refuse(path, boundary, "The BCF1 frames")),
    }
}

fn boundary_of(policy: ResumePolicy) -> Option<i32> {
    match policy {
        ResumePolicy::Fresh => None,
        ResumePolicy::Refuse { boundary } | ResumePolicy::Continue { boundary } => Some(boundary),
    }
}

/// Cut a JSON Lines stream back to the last record for block `boundary`.
///
/// The first line is a header and is always kept. Every line after it must be an
/// object carrying `field` as an integer block number, strictly ascending. Lines
/// past `boundary` are dropped; a trailing line that does not parse at all is
/// dropped too, because a killed process can leave one. The trim refuses if what
/// survives does not end at exactly `boundary`, which is the case where the
/// checkpoint is *ahead* of the file and continuing would leave a gap.
///
/// Returns the number of block records kept.
fn trim_jsonl(path: &Path, field: &str, boundary: i32, what: &str) -> Result<usize> {
    let file = std::fs::File::open(path).with_context(|| format!("reading {}", path.display()))?;
    let mut lines = BufReader::new(file).lines();
    let header = lines
        .next()
        .transpose()
        .with_context(|| format!("reading the {what} header in {}", path.display()))?
        .ok_or_else(|| {
            anyhow::anyhow!(
                "{} is empty, so it is not the {what} of a run that reached block {boundary}",
                path.display()
            )
        })?;
    let header_value: serde_json::Value = serde_json::from_str(&header).with_context(|| {
        format!(
            "parsing the first line of {} as a {what} header",
            path.display()
        )
    })?;
    if header_value.get(field).is_some() {
        bail!(
            "the first line of {} is a block record, not a {what} header; this is not a file \
             this run could have written",
            path.display()
        );
    }

    let mut kept: Vec<String> = vec![header];
    let mut records = 0usize;
    let mut last: Option<i32> = None;
    let mut lineno = 1usize;
    let mut pending: Option<String> = None;
    for line in lines {
        lineno += 1;
        let line = line.with_context(|| format!("reading {} line {lineno}", path.display()))?;
        if line.trim().is_empty() {
            continue;
        }
        // A record that does not parse is only tolerable as the very last line
        // of the file: that is a torn write. One in the middle means the file is
        // not what it claims to be.
        if let Some(torn) = pending.take() {
            bail!(
                "{} line {} is not a {what} record and is not the last line either: `{}`",
                path.display(),
                lineno - 1,
                torn.chars().take(80).collect::<String>()
            );
        }
        let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) else {
            pending = Some(line);
            continue;
        };
        let number = value.get(field).and_then(serde_json::Value::as_i64);
        let Some(number) = number else {
            pending = Some(line);
            continue;
        };
        let number = i32::try_from(number)
            .with_context(|| format!("{} line {lineno} names block {number}", path.display()))?;
        if let Some(previous) = last {
            if number <= previous {
                bail!(
                    "{} is not in ascending block order: line {lineno} is block {number} after \
                     block {previous}",
                    path.display()
                );
            }
        }
        last = Some(number);
        if number > boundary {
            continue;
        }
        kept.push(line);
        records += 1;
    }

    if kept.len() == 1 {
        bail!(
            "{} holds no record for block {boundary} or earlier, so the checkpoint is ahead of \
             it: continuing would leave the {what} missing every block between",
            path.display()
        );
    }
    let ends_at = kept
        .last()
        .and_then(|line| serde_json::from_str::<serde_json::Value>(line).ok())
        .and_then(|value| value.get(field).and_then(serde_json::Value::as_i64));
    if ends_at != Some(i64::from(boundary)) {
        bail!(
            "{} ends at block {} after trimming, not at the checkpoint's block {boundary}: the \
             checkpoint is ahead of the {what}, and continuing would leave the blocks between \
             missing from it",
            path.display(),
            ends_at.map_or_else(|| "nothing".to_string(), |n| n.to_string())
        );
    }

    let mut bytes = Vec::new();
    for line in &kept {
        bytes.extend_from_slice(line.as_bytes());
        bytes.push(b'\n');
    }
    write_atomically(path, &bytes)?;
    Ok(records)
}

/// Cut a `BCF1` stream back to the last frame for block `boundary`.
///
/// The format is bare concatenation of self-describing frames, so this walks
/// them and truncates at a frame boundary. A trailing partial frame is dropped
/// by construction: the walk stops as soon as the rest of the file is shorter
/// than the frame it announces.
fn trim_bcf1(path: &Path, boundary: i32) -> Result<usize> {
    let bytes = std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
    let mut offset = 0usize;
    let mut keep_to = 0usize;
    let mut kept = 0usize;
    let mut last: Option<i32> = None;
    let mut ends_at_boundary = false;

    while offset + BCF1_HEADER <= bytes.len() {
        if bytes[offset..offset + 4] != BCF1_MAGIC[..] {
            bail!(
                "{} has no BCF1 frame at byte {offset}; it is not a BCF1 stream this run wrote",
                path.display()
            );
        }
        let number = u64::from_be_bytes(
            bytes[offset + 8..offset + 16]
                .try_into()
                .expect("eight bytes"),
        );
        let length = u32::from_be_bytes(
            bytes[offset + 48..offset + 52]
                .try_into()
                .expect("four bytes"),
        ) as usize;
        let end = offset + BCF1_HEADER + length;
        if end > bytes.len() {
            // A torn final frame. Everything before it is whole.
            break;
        }
        let number = i32::try_from(number).with_context(|| {
            format!(
                "{} has a frame for block {number}, which is out of range",
                path.display()
            )
        })?;
        if let Some(previous) = last {
            if number <= previous {
                bail!(
                    "{} is not in ascending block order: a frame for block {number} follows one \
                     for block {previous}",
                    path.display()
                );
            }
        }
        last = Some(number);
        if number > boundary {
            break;
        }
        keep_to = end;
        kept += 1;
        ends_at_boundary = number == boundary;
        offset = end;
    }

    if !ends_at_boundary {
        bail!(
            "{} ends at block {} after trimming, not at the checkpoint's block {boundary}: the \
             checkpoint is ahead of the BCF1 stream, and continuing would leave the blocks \
             between missing from it",
            path.display(),
            last.map_or_else(|| "nothing".to_string(), |n| n.to_string())
        );
    }

    let file = std::fs::OpenOptions::new()
        .write(true)
        .open(path)
        .with_context(|| format!("opening {} to truncate", path.display()))?;
    file.set_len(keep_to as u64)
        .with_context(|| format!("truncating {} to {keep_to} bytes", path.display()))?;
    file.sync_all()
        .with_context(|| format!("flushing {}", path.display()))?;
    Ok(kept)
}

/// Delete every `<number>.pb` frame above `boundary`, returning how many.
fn remove_frames_after(dir: &Path, boundary: i32) -> Result<usize> {
    let stale = frame_files(dir, boundary)?;
    for path in &stale {
        std::fs::remove_file(path).with_context(|| format!("removing {}", path.display()))?;
    }
    Ok(stale.len())
}

fn frame_files(dir: &Path, boundary: i32) -> Result<Vec<PathBuf>> {
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut stale = Vec::new();
    for entry in std::fs::read_dir(dir).with_context(|| format!("listing {}", dir.display()))? {
        let path = entry
            .with_context(|| format!("listing {}", dir.display()))?
            .path();
        if path.extension().and_then(|e| e.to_str()) != Some("pb") {
            continue;
        }
        let Some(stem) = path.file_stem().and_then(|s| s.to_str()) else {
            continue;
        };
        let Ok(number) = stem.parse::<i64>() else {
            continue;
        };
        if number > i64::from(boundary) {
            stale.push(path);
        }
    }
    stale.sort();
    Ok(stale)
}

/// Write through a temporary file and rename, so a trim that dies halfway
/// leaves the original file rather than a half-trimmed one.
fn write_atomically(path: &Path, bytes: &[u8]) -> Result<()> {
    let temp = path.with_extension(format!("trim{}", std::process::id()));
    {
        let mut file =
            std::fs::File::create(&temp).with_context(|| format!("creating {}", temp.display()))?;
        file.write_all(bytes)
            .with_context(|| format!("writing {}", temp.display()))?;
        file.sync_all()
            .with_context(|| format!("flushing {}", temp.display()))?;
    }
    std::fs::rename(&temp, path)
        .with_context(|| format!("renaming {} to {}", temp.display(), path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::blockchanges::bcf1_frame;

    fn temp() -> tempfile::TempDir {
        tempfile::tempdir().expect("temp dir")
    }

    fn report_lines(numbers: &[i32]) -> String {
        let mut text = String::from("{\"schema\":\"report-stream/v1\"}\n");
        for number in numbers {
            text.push_str(&format!(
                "{{\"number\":{number},\"hash\":\"0x{number:x}\"}}\n"
            ));
        }
        text
    }

    fn bcf1_bytes(numbers: &[i32]) -> Vec<u8> {
        let mut bytes = Vec::new();
        for number in numbers {
            bytes.extend_from_slice(
                &bcf1_frame(*number as u64, &[7u8; 32], format!("{number}").as_bytes())
                    .expect("framing"),
            );
        }
        bytes
    }

    #[test]
    fn a_resume_without_continue_outputs_refuses_an_existing_report() {
        let dir = temp();
        let path = dir.path().join("run.jsonl");
        std::fs::write(&path, report_lines(&[10, 11, 12])).expect("writing");
        let error = prepare_report(Some(&path), true, ResumePolicy::Refuse { boundary: 11 })
            .expect_err("an existing report is refused");
        let message = format!("{error:#}");
        assert!(message.contains("already exists"), "{message}");
        assert!(message.contains("--continue-outputs"), "{message}");
        // Untouched.
        assert_eq!(
            std::fs::read_to_string(&path).expect("reading"),
            report_lines(&[10, 11, 12])
        );
    }

    #[test]
    fn continuing_trims_a_report_back_to_the_boundary() {
        let dir = temp();
        let path = dir.path().join("run.jsonl");
        std::fs::write(&path, report_lines(&[10, 11, 12, 13])).expect("writing");
        let disposition =
            prepare_report(Some(&path), true, ResumePolicy::Continue { boundary: 11 })
                .expect("trimmed");
        assert_eq!(disposition, Disposition::Append);
        assert_eq!(
            std::fs::read_to_string(&path).expect("reading"),
            report_lines(&[10, 11])
        );
    }

    #[test]
    fn a_torn_last_line_is_dropped_rather_than_refused() {
        let dir = temp();
        let path = dir.path().join("run.jsonl");
        let mut text = report_lines(&[10, 11]);
        text.push_str("{\"number\":12,\"ha");
        std::fs::write(&path, text).expect("writing");
        prepare_report(Some(&path), true, ResumePolicy::Continue { boundary: 11 })
            .expect("a torn tail is trimmed away");
        assert_eq!(
            std::fs::read_to_string(&path).expect("reading"),
            report_lines(&[10, 11])
        );
    }

    #[test]
    fn a_report_that_stops_before_the_boundary_is_refused() {
        let dir = temp();
        let path = dir.path().join("run.jsonl");
        std::fs::write(&path, report_lines(&[10, 11])).expect("writing");
        let error = prepare_report(Some(&path), true, ResumePolicy::Continue { boundary: 12 })
            .expect_err("a checkpoint ahead of the report is refused");
        let message = format!("{error:#}");
        assert!(message.contains("checkpoint is ahead"), "{message}");
        // Refused before anything was written.
        assert_eq!(
            std::fs::read_to_string(&path).expect("reading"),
            report_lines(&[10, 11])
        );
    }

    #[test]
    fn a_whole_document_report_cannot_be_continued() {
        let dir = temp();
        let path = dir.path().join("run.json");
        std::fs::write(&path, "{\"blocks\":[]}").expect("writing");
        let error = prepare_report(Some(&path), false, ResumePolicy::Continue { boundary: 11 })
            .expect_err("a buffered report has no prefix");
        assert!(format!("{error:#}").contains("whole-document"), "{error:#}");
    }

    #[test]
    fn continuing_trims_a_bcf1_stream_at_a_frame_boundary() {
        let dir = temp();
        let path = dir.path().join("run.bcf1");
        std::fs::write(&path, bcf1_bytes(&[10, 11, 12, 13])).expect("writing");
        let disposition =
            prepare_bcf1(Some(&path), ResumePolicy::Continue { boundary: 11 }).expect("trimmed");
        assert_eq!(disposition, Disposition::Append);
        assert_eq!(
            std::fs::read(&path).expect("reading"),
            bcf1_bytes(&[10, 11])
        );
    }

    #[test]
    fn a_torn_bcf1_frame_is_dropped() {
        let dir = temp();
        let path = dir.path().join("run.bcf1");
        let mut bytes = bcf1_bytes(&[10, 11]);
        let mut torn = bcf1_bytes(&[12]);
        torn.truncate(20);
        bytes.extend_from_slice(&torn);
        std::fs::write(&path, bytes).expect("writing");
        prepare_bcf1(Some(&path), ResumePolicy::Continue { boundary: 11 }).expect("trimmed");
        assert_eq!(
            std::fs::read(&path).expect("reading"),
            bcf1_bytes(&[10, 11])
        );
    }

    #[test]
    fn a_bcf1_stream_that_stops_before_the_boundary_is_refused() {
        let dir = temp();
        let path = dir.path().join("run.bcf1");
        std::fs::write(&path, bcf1_bytes(&[10, 11])).expect("writing");
        let error = prepare_bcf1(Some(&path), ResumePolicy::Continue { boundary: 20 })
            .expect_err("a checkpoint ahead of the stream is refused");
        assert!(
            format!("{error:#}").contains("checkpoint is ahead"),
            "{error:#}"
        );
        assert_eq!(
            std::fs::read(&path).expect("reading"),
            bcf1_bytes(&[10, 11]),
            "a refused trim must not truncate anything"
        );
    }

    #[test]
    fn continuing_drops_frame_files_past_the_boundary() {
        let dir = temp();
        let frames = dir.path().join("frames");
        std::fs::create_dir_all(&frames).expect("mkdir");
        let mut index = String::from("{\"schema\":\"index-stream/v1\"}\n");
        for number in [10, 11, 12, 13] {
            index.push_str(&format!(
                "{{\"block_number\":{number},\"file\":\"{number}.pb\"}}\n"
            ));
            std::fs::write(frames.join(format!("{number}.pb")), b"x").expect("frame");
        }
        std::fs::write(frames.join("index.jsonl"), index).expect("index");

        prepare_frames(Some(&frames), true, ResumePolicy::Continue { boundary: 11 })
            .expect("trimmed");
        assert!(frames.join("10.pb").exists());
        assert!(frames.join("11.pb").exists());
        assert!(!frames.join("12.pb").exists());
        assert!(!frames.join("13.pb").exists());
        let index = std::fs::read_to_string(frames.join("index.jsonl")).expect("reading");
        assert_eq!(index.lines().count(), 3, "{index}");
    }

    #[test]
    fn an_empty_directory_is_fresh() {
        let dir = temp();
        let frames = dir.path().join("frames");
        std::fs::create_dir_all(&frames).expect("mkdir");
        assert_eq!(
            prepare_frames(Some(&frames), true, ResumePolicy::Refuse { boundary: 11 })
                .expect("an empty directory is not an existing output"),
            Disposition::Fresh
        );
    }

    #[test]
    fn a_run_that_is_not_resuming_leaves_every_decision_alone() {
        let dir = temp();
        let path = dir.path().join("run.jsonl");
        std::fs::write(&path, report_lines(&[10, 11])).expect("writing");
        assert_eq!(
            prepare_report(Some(&path), true, ResumePolicy::Fresh).expect("fresh"),
            Disposition::Fresh
        );
        assert_eq!(
            std::fs::read_to_string(&path).expect("reading"),
            report_lines(&[10, 11]),
            "a non-resuming run must not trim anything here; the writer truncates"
        );
    }

    #[test]
    fn continue_outputs_without_a_checkpoint_is_refused() {
        let error = ResumePolicy::new(None, true).expect_err("nothing to continue from");
        assert!(
            format!("{error:#}").contains("--checkpoint-in"),
            "{error:#}"
        );
    }
}
