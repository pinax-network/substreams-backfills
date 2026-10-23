//! Bounded disk-seeded oracle execution. This is read-only oracle evidence,
//! never an engine publication, reducer checkpoint or load authorization.
use crate::{
    block, blockchanges,
    bundle::sha256_hex,
    disk_store::OverlayLimits,
    report::RunHeader,
    runner::{DiskRunLimits, SegmentHost, SegmentHostConfig},
    source::{token_from_env, FirehoseSource, FirehoseTarget},
};
use anyhow::{anyhow, bail, Context, Result};
use backfill_common::{seed_manifest::Binding, state_snapshot::Limits};
use graph::prelude::prost::Message;
use graph_chain_ethereum::{chain::BlockFinality, codec};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{BufReader, BufWriter, Read, Write},
    os::unix::fs::{DirBuilderExt, OpenOptionsExt},
    path::{Path, PathBuf},
};

pub const REQUEST_SCHEMA: &str = "pinax.mapping-host.disk-oracle-request/v1";
const MAX_INPUT: u64 = 16 * 1024 * 1024 * 1024;
const MAX_BLOCK: usize = 64 * 1024 * 1024;
// The engine canary bounds the payload, excluding the 52-byte BCF1 envelope.
const MAX_FRAME: usize = 16 * 1024 * 1024;
// Engine canary::oracle::Lines counts the terminating LF in its MAX_JSON bound.
pub(crate) const MAX_JSON_LINE: usize = 4 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Artifact {
    pub path: PathBuf,
    pub bytes: u64,
    pub sha256: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Input {
    /// Final-only live Firehose; credentials remain in the existing environment.
    Firehose,
    /// Hermetic reference-only protobuf files, one exact block per artifact.
    Fixtures { blocks: Vec<Artifact> },
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema: String,
    pub segment: PathBuf,
    pub output: PathBuf,
    pub seed_binding: Binding,
    pub seed_manifest: Artifact,
    pub seed_snapshot: Artifact,
    pub rpc_cassette: Artifact,
    pub input: Input,
    pub to_exclusive: i32,
    pub partition_blocks: u32,
    pub timeout_seconds: u64,
    pub overlay_keys: usize,
    pub overlay_bytes: usize,
    pub cache_keys: usize,
    pub sources: usize,
}

fn regular(path: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    if !file.metadata()?.is_file() {
        bail!("oracle input must be a regular file");
    }
    Ok(file)
}
fn read_pin(pin: &Artifact, max: u64) -> Result<Vec<u8>> {
    if pin.bytes > max || pin.bytes == 0 {
        bail!("oracle artifact exceeds bound");
    }
    let mut bytes = Vec::new();
    regular(&pin.path)?
        .take(pin.bytes + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 != pin.bytes || sha256_hex(&bytes) != pin.sha256 {
        bail!("oracle artifact digest or length mismatch");
    }
    Ok(bytes)
}
fn new_file(path: &Path) -> Result<File> {
    Ok(OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?)
}
fn save(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = new_file(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
fn pin_file(path: &Path) -> Result<Artifact> {
    let mut file = regular(path)?;
    let mut hash = Sha256::new();
    let mut size = 0u64;
    let mut buf = [0u8; 1024 * 1024];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hash.update(&buf[..n]);
        size = size
            .checked_add(n as u64)
            .ok_or_else(|| anyhow!("artifact size overflow"))?;
    }
    Ok(Artifact {
        path: path.to_owned(),
        bytes: size,
        sha256: hex::encode(hash.finalize()),
    })
}

/// Success publishes only `complete.json` after actual input EOF, all output
/// flushes/fsyncs and exact digest receipts. Failed directories are retained and
/// never reused. The private disk cache is not an independently loadable state.
pub async fn run(request_path: &Path, request_sha256: &str) -> Result<()> {
    let mut bytes = Vec::new();
    regular(request_path)?
        .take(4 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 4 * 1024 * 1024 || sha256_hex(&bytes) != request_sha256 {
        bail!("disk oracle request pin/bound mismatch");
    }
    let request: Request = serde_json::from_slice(&bytes)?;
    let executable = pin_file(&std::env::current_exe()?)?;
    let mut canonical = serde_json::to_vec_pretty(&request)?;
    canonical.push(b'\n');
    if canonical != bytes || request.schema != REQUEST_SCHEMA {
        bail!("disk oracle request is not canonical");
    }
    let from: i32 = request
        .seed_binding
        .boundary
        .block_number
        .checked_add(1)
        .ok_or_else(|| anyhow!("seed boundary overflow"))?
        .try_into()?;
    let count = request
        .to_exclusive
        .checked_sub(from)
        .ok_or_else(|| anyhow!("oracle range overflow"))?;
    if !(1..=1000).contains(&count)
        || !(1..=500).contains(&request.partition_blocks)
        || !(1..=7200).contains(&request.timeout_seconds)
        || request.sources == 0
        || request.sources > 100_000
        || request.cache_keys == 0
        || request.cache_keys > 1_000_000
        || request.overlay_keys == 0
        || request.overlay_keys > 1_000_000
        || request.overlay_bytes == 0
        || request.overlay_bytes > 1024 * 1024 * 1024
    {
        bail!("disk oracle range/budgets outside bounded admission");
    }
    if !request.output.is_absolute() || !request.segment.is_absolute() {
        bail!("disk oracle paths must be absolute");
    }
    let manifest = read_pin(
        &request.seed_manifest,
        backfill_common::seed_manifest::MAX_BYTES as u64,
    )?;
    let manifest_value = backfill_common::seed_manifest::Manifest::verify(
        &manifest,
        &request.seed_manifest.sha256,
        &request.seed_binding,
    )
    .map_err(anyhow::Error::msg)?;
    if request.seed_snapshot.sha256 != manifest_value.snapshot.sha256
        || request.seed_snapshot.bytes != manifest_value.snapshot.bytes
    {
        bail!("snapshot artifact differs from pinned manifest");
    }
    let cassette = read_pin(&request.rpc_cassette, 64 * 1024 * 1024)?;
    if let Input::Fixtures { blocks } = &request.input {
        if blocks.len() != count as usize {
            bail!("fixture inventory does not cover the complete requested range");
        }
    }
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&request.output)
        .context("creating fresh disk oracle output")?;
    save(&request.output.join("request.json"), &bytes)?;
    save(&request.output.join("seed-manifest.json"), &manifest)?;
    let cassette_path = request.output.join("rpc-cassette.json");
    save(&cassette_path, &cassette)?;
    let mut host = SegmentHost::load_disk_seed(
        SegmentHostConfig {
            bundle_dir: &request.segment,
            cassette_path: &cassette_path,
            record: false,
        },
        &request.output.join("seed.redb"),
        BufReader::new(regular(&request.seed_snapshot.path)?),
        &manifest,
        &request.seed_manifest.sha256,
        &request.seed_binding,
        OverlayLimits {
            keys: request.overlay_keys,
            encoded_bytes: request.overlay_bytes,
        },
        DiskRunLimits {
            sources: request.sources,
            cache_keys: request.cache_keys,
            blocks: count as usize,
        },
        Limits::default(),
    )
    .await?;
    let checkpoint_path = request.output.join("seed.checkpoint.jsonl");
    let mut checkpoint = BufWriter::new(new_file(&checkpoint_path)?);
    host.write_cold_seed_checkpoint(&mut checkpoint)?;
    checkpoint.flush()?;
    checkpoint.get_ref().sync_all()?;
    drop(checkpoint);
    let descriptor_path = request
        .segment
        .join(crate::descriptor::IN_BAND_DESCRIPTOR_FILE);
    let descriptor = pin_file(&descriptor_path)?;
    if descriptor.sha256 != host.descriptor_sha256() {
        bail!("oracle descriptor changed during seed admission");
    }
    let retained_descriptor = request.output.join("descriptor.json");
    save(
        &retained_descriptor,
        &read_pin(&descriptor, MAX_JSON_LINE as u64)?,
    )?;
    let descriptor = pin_file(&retained_descriptor)?;
    let deadline =
        tokio::time::Instant::now() + std::time::Duration::from_secs(request.timeout_seconds);
    let mut live = match request.input {
        Input::Firehose => Some(
            tokio::time::timeout_at(
                deadline,
                FirehoseSource::connect(
                    &FirehoseTarget::from_env()?,
                    token_from_env()?,
                    from,
                    request.to_exclusive,
                ),
            )
            .await
            .context("disk oracle Firehose connection deadline")??,
        ),
        _ => None,
    };
    let mut partitions = Vec::new();
    let mut total_input_bytes = 0u64;
    let mut number = from;
    while number < request.to_exclusive {
        let start = number;
        let stop = request.to_exclusive.min(
            start
                .checked_add(request.partition_blocks as i32)
                .ok_or_else(|| anyhow!("partition overflow"))?,
        );
        let index = partitions.len();
        let prefix = request.output.join(format!("partition-{index:03}"));
        std::fs::DirBuilder::new().mode(0o700).create(&prefix)?;
        let input_path = prefix.join("input.fob1");
        let frames_path = prefix.join("frames.bcf1");
        let report_path = prefix.join("report.jsonl");
        let mut input = BufWriter::new(new_file(&input_path)?);
        input.write_all(b"FOB1")?;
        let mut frames = BufWriter::new(new_file(&frames_path)?);
        let report_header = RunHeader::new(
            &host.new_report(),
            if live.is_some() {
                "final-only Firehose".into()
            } else {
                "pinned reference fixtures".into()
            },
            Some((start, stop)),
        );
        let mut report = BufWriter::new(new_file(&report_path)?);
        write_json_line(&mut report, &report_header)?;
        report.flush()?;
        while number < stop {
            let (raw, block) = if let Some(live) = live.as_mut() {
                tokio::time::timeout_at(deadline, live.next_raw_block())
                    .await
                    .context("disk oracle input deadline")??
                    .ok_or_else(|| anyhow!("oracle source ended before complete range"))?
            } else {
                let Input::Fixtures { blocks } = &request.input else {
                    unreachable!()
                };
                let raw = read_pin(&blocks[(number - from) as usize], MAX_BLOCK as u64)?;
                let chunks = block::split_messages(&raw)?;
                if chunks.len() != 1 {
                    bail!("oracle fixture does not contain exactly one block");
                }
                let decoded = codec::Block::decode(chunks[0].1)?;
                let block: BlockFinality = (&decoded)
                    .try_into()
                    .map_err(|e| anyhow!("decoding oracle block: {e}"))?;
                (raw, block)
            };
            if raw.len() > MAX_BLOCK {
                bail!("oracle raw block exceeds 64 MiB");
            }
            total_input_bytes = total_input_bytes
                .checked_add(raw.len() as u64)
                .ok_or_else(|| anyhow!("raw input size overflow"))?;
            if total_input_bytes > MAX_INPUT {
                bail!("oracle raw input exceeds 16 GiB window bound");
            }
            input.write_all(&(raw.len() as u32).to_be_bytes())?;
            input.write_all(&raw)?;
            let mut outcome = tokio::time::timeout_at(deadline, host.process_block(block))
                .await
                .context("disk oracle replay deadline")??;
            if outcome.report.number != number {
                bail!("oracle block number differs from requested clock");
            }
            let payload = blockchanges::seal(&outcome.changes, host.compatibility())?;
            require_frame_bound(payload.len())?;
            outcome.report.block_changes =
                Some(blockchanges::summarize(&outcome.changes, &payload));
            frames.write_all(&blockchanges::bcf1_frame(
                number as u64,
                &outcome.changes.block_hash,
                &payload,
            )?)?;
            write_json_line(&mut report, &outcome.report)?;
            report.flush()?;
            number += 1;
        }
        input.flush()?;
        input.get_ref().sync_all()?;
        frames.flush()?;
        frames.get_ref().sync_all()?;
        report.flush()?;
        report.get_ref().sync_all()?;
        regular(&report_path)?.sync_all()?;
        File::open(&prefix)?.sync_all()?;
        partitions.push(serde_json::json!({"from":start,"to_exclusive":stop,"input":pin_file(&input_path)?,"frames":pin_file(&frames_path)?,"report":pin_file(&report_path)?}));
        eprintln!("disk oracle processed {number}/{}", request.to_exclusive);
    }
    if let Some(live) = live.as_mut() {
        tokio::time::timeout_at(deadline, live.finish_raw_capture())
            .await
            .context("disk oracle EOF deadline")??;
    }
    let final_executable = pin_file(&std::env::current_exe()?)?;
    if final_executable.sha256 != executable.sha256 || final_executable.bytes != executable.bytes {
        bail!("oracle executable changed during execution");
    }
    let receipt = serde_json::json!({"format":"pinax.mapping-host.disk-oracle-complete/v1","request_sha256":request_sha256,"production_selectable":false,"fixture_only":matches!(request.input,Input::Fixtures{..}),"source_closure_sha256":crate::descriptor::SOURCE_CLOSURE_SHA256,"executable":executable,"seed_snapshot":request.seed_snapshot,"seed_manifest":request.seed_manifest,"rpc_cassette":pin_file(&cassette_path)?,"cold_checkpoint":pin_file(&checkpoint_path)?,"descriptor":descriptor,"from":from,"to_exclusive":request.to_exclusive,"partitions":partitions});
    let mut out = serde_json::to_vec_pretty(&receipt)?;
    out.push(b'\n');
    publish_complete(&request.output, |file| {
        file.write_all(&out)?;
        Ok(())
    })?;
    Ok(())
}

/// Every checkpoint and report line uses the exact consumer ceiling, including LF.
/// Serialization and admission complete before the sink sees any bytes.
pub(crate) fn write_json_line(sink: &mut impl Write, value: &impl Serialize) -> Result<()> {
    struct Bounded(Vec<u8>);
    impl Write for Bounded {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            if self
                .0
                .len()
                .checked_add(bytes.len())
                .is_none_or(|n| n >= MAX_JSON_LINE)
            {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "oracle JSONL exceeds 4 MiB consumer line bound including LF",
                ));
            }
            self.0.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut bounded = Bounded(Vec::new());
    serde_json::to_writer(&mut bounded, value)?;
    let mut bytes = bounded.0;
    bytes.push(b'\n');
    sink.write_all(&bytes)?;
    Ok(())
}

fn require_frame_bound(length: usize) -> Result<()> {
    if length > MAX_FRAME {
        bail!("oracle frame payload exceeds 16 MiB consumer bound");
    }
    Ok(())
}

fn publish_complete(directory: &Path, write: impl FnOnce(&mut File) -> Result<()>) -> Result<()> {
    let partial = directory.join(".complete.json.partial");
    let complete = directory.join("complete.json");
    let mut file = new_file(&partial)?;
    write(&mut file)?;
    file.sync_all()?;
    drop(file);
    // link publishes a complete inode atomically and refuses an existing marker.
    // Unlike rename, it cannot replace evidence left by another invocation.
    std::fs::hard_link(&partial, &complete)?;
    File::open(directory)?.sync_all()?;
    std::fs::remove_file(partial)?;
    File::open(directory)?.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn jsonl_bound_includes_lf_and_refuses_before_writing() {
        let mut out = Vec::new();
        let exact = "x".repeat(MAX_JSON_LINE - 3); // JSON string quotes plus LF.
        write_json_line(&mut out, &exact).unwrap();
        assert_eq!(out.len(), MAX_JSON_LINE);
        assert_eq!(out.last(), Some(&b'\n'));
        assert_eq!(serde_json::from_slice::<String>(&out).unwrap(), exact);
        let before = out.clone();
        assert!(write_json_line(&mut out, &(exact + "x")).is_err());
        assert_eq!(out, before);
    }
    #[test]
    fn frame_limit_matches_exact_consumer_payload_bound() {
        use backfill_common::clock::{self, Frame, FrameKind};
        let payload = vec![1; MAX_FRAME];
        require_frame_bound(payload.len()).unwrap();
        let mut encoded = Vec::new();
        clock::write_frame(
            &mut encoded,
            &Frame {
                kind: FrameKind::Observed,
                block_number: 1,
                block_hash: [1; 32],
                payload,
            },
        )
        .unwrap();
        assert_eq!(encoded.len(), MAX_FRAME + 52);
        assert_eq!(
            clock::read_frame(&mut encoded.as_slice(), MAX_FRAME)
                .unwrap()
                .unwrap()
                .payload
                .len(),
            MAX_FRAME
        );
        assert!(require_frame_bound(MAX_FRAME + 1).is_err());
        assert!(clock::read_frame(&mut encoded.as_slice(), MAX_FRAME - 1).is_err());
    }
    #[test]
    fn failed_completion_is_never_visible_and_existing_marker_is_not_replaced() {
        let temp = tempfile::tempdir().unwrap();
        assert!(publish_complete(temp.path(), |f| {
            f.write_all(b"partial")?;
            bail!("injected write failure")
        })
        .is_err());
        assert!(!temp.path().join("complete.json").exists());
        assert_eq!(
            std::fs::read(temp.path().join(".complete.json.partial")).unwrap(),
            b"partial"
        );
        let temp = tempfile::tempdir().unwrap();
        publish_complete(temp.path(), |f| {
            f.write_all(b"complete\n")?;
            Ok(())
        })
        .unwrap();
        assert_eq!(
            std::fs::read(temp.path().join("complete.json")).unwrap(),
            b"complete\n"
        );
        assert!(publish_complete(temp.path(), |f| {
            f.write_all(b"replacement")?;
            Ok(())
        })
        .is_err());
        assert_eq!(
            std::fs::read(temp.path().join("complete.json")).unwrap(),
            b"complete\n"
        );
    }
}
