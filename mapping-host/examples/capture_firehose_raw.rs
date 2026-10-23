//! Read-only capture of original finalized Firehose protobuf payloads. BCF1 is
//! framing only: these are sf.ethereum blocks, not BlockChanges/ExtractorBlock.
use anyhow::{bail, Context, Result};
use backfill_common::clock::{self, Frame, FrameKind};
use graph_mapping_host::{
    block::identify,
    source::{self, FirehoseSource, FirehoseTarget},
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, OpenOptions},
    io::{BufWriter, Write},
    path::PathBuf,
    time::{Duration, Instant},
};

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        // The source never includes credentials; remove the configured endpoint
        // too so evidence logs contain no transport URL.
        let mut message = format!("{error:#}");
        if let Ok(endpoint) = std::env::var(source::ENDPOINT_VAR) {
            message = message.replace(&endpoint, "[endpoint]");
        }
        eprintln!("capture refused: {message}");
        std::process::exit(4);
    }
}
async fn run() -> Result<()> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.len() != 4 {
        bail!("usage: capture_firehose_raw START STOP_EXCLUSIVE NEW_DIRECTORY SOURCE_COMMIT");
    }
    let start: i32 = args[0].parse()?;
    let stop: i32 = args[1].parse()?;
    if start < 0
        || stop <= start
        || args[3].len() != 40
        || !args[3].bytes().all(|b| b.is_ascii_hexdigit())
    {
        bail!("invalid range or source commit");
    }
    let root = PathBuf::from(&args[2]);
    fs::create_dir(&root).context("capture directory must be new")?;
    let new_file = |name: &str| {
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(root.join(name))
    };
    let mut raw = BufWriter::new(new_file("raw-firehose.bcf1")?);
    let mut index = BufWriter::new(new_file("raw-firehose.index.jsonl")?);
    let target = FirehoseTarget::from_env()?;
    let mut input =
        FirehoseSource::connect(&target, source::token_from_env()?, start, stop).await?;
    let mut digest = Sha256::new();
    let mut index_digest = Sha256::new();
    let mut bytes = 0_u64;
    let mut previous = None;
    let mut first_parent = None;
    let mut progress = Instant::now();
    let mut retries = 0;
    for expected in start..stop {
        let (payload, block) = loop {
            match input.next_raw_block().await {
                Ok(Some(value)) => break value,
                Ok(None) => bail!("early EOF before block {expected}"),
                Err(error) if source::is_transport_failure(&error) && retries < 5 => {
                    retries += 1;
                    tokio::time::sleep(Duration::from_secs(2)).await;
                    input =
                        FirehoseSource::connect(&target, source::token_from_env()?, expected, stop)
                            .await?;
                }
                Err(error) => return Err(error),
            }
        };
        let identity = identify(&block);
        if identity.number != expected {
            bail!("raw capture number mismatch");
        }
        let parent = identity
            .parent_hash
            .context("raw block lacks parent hash")?;
        let hash = hex::decode(identity.hash.trim_start_matches("0x"))?;
        let parent_bytes = hex::decode(parent.trim_start_matches("0x"))?;
        if hash.len() != 32
            || parent_bytes.len() != 32
            || hash.iter().all(|b| *b == 0)
            || parent_bytes.iter().all(|b| *b == 0)
        {
            bail!("invalid raw block hash");
        }
        if previous.as_ref().is_some_and(|h| h != &parent) {
            bail!("parent chain mismatch at block {expected}");
        }
        if first_parent.is_none() {
            first_parent = Some(parent.clone());
        }
        let entry = json!({"block":expected,"hash":identity.hash,"parent_hash":parent,"protobuf_bytes":payload.len(),"protobuf_sha256":hex::encode(Sha256::digest(&payload)),"offset":bytes});
        let mut line = serde_json::to_vec(&entry)?;
        line.push(b'\n');
        index_digest.update(&line);
        index.write_all(&line)?;
        let mut encoded = Vec::new();
        clock::write_frame(
            &mut encoded,
            &Frame {
                kind: FrameKind::Observed,
                block_number: expected as u64,
                block_hash: hash.try_into().unwrap(),
                payload,
            },
        )?;
        digest.update(&encoded);
        bytes += encoded.len() as u64;
        raw.write_all(&encoded)?;
        previous = Some(identity.hash);
        if progress.elapsed() >= Duration::from_secs(30) {
            eprintln!("captured through block {expected}; bytes {bytes}");
            progress = Instant::now();
            raw.flush()?;
            index.flush()?;
        }
    }
    tokio::time::timeout(Duration::from_secs(60), input.finish_raw_capture())
        .await
        .context("server EOF timeout")??;
    raw.flush()?;
    index.flush()?;
    raw.get_ref().sync_all()?;
    index.get_ref().sync_all()?;
    let receipt = json!({"schema":"aerodrome-raw-firehose-capture/v1","source_commit":args[3],"binary_sha256":hex::encode(Sha256::digest(fs::read(std::env::current_exe()?)?)),"protobuf_type":source::ETHEREUM_BLOCK_TYPE,"from":start,"to_exclusive":stop,"blocks":stop-start,"first_parent_hash":first_parent,"last_hash":previous,"final_blocks_only":true,"server_eof":true,"raw_bcf1_bytes":bytes,"raw_bcf1_sha256":hex::encode(digest.finalize()),"index_sha256":hex::encode(index_digest.finalize()),"transport_reconnects":retries});
    let mut success = new_file("capture-success.json")?;
    serde_json::to_writer_pretty(&mut success, &receipt)?;
    success.write_all(b"\n")?;
    success.sync_all()?;
    eprintln!(
        "capture complete: {} observed blocks, {bytes} bytes",
        stop - start
    );
    Ok(())
}
