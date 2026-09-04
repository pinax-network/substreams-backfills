//! Bounded root-run metadata companion. A partial/resumed run must not claim a
//! complete deployment; that requires a future seed-bound sidecar contract.
use crate::runner::SegmentHost;
use anyhow::{bail, Context, Result};
use backfill_common::{
    decode_canonical_block_changes,
    dynamic_sources::{Block, Sidecar, CONTRACT, MAX_BLOCKS},
    BlockChangesCompatibility,
};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::File,
    io::{Read, Write},
    path::Path,
};

pub fn write(
    host: &SegmentHost,
    stream: &Path,
    output: &Path,
    compatibility: &BlockChangesCompatibility,
) -> Result<()> {
    let mut input = File::open(stream)?;
    let mut hash = Sha256::new();
    let mut blocks = Vec::new();
    let mut sources = BTreeMap::<u64, Vec<_>>::new();
    for source in host.stored_dynamic_data_sources()? {
        sources
            .entry(source.creation_block as u64)
            .or_default()
            .push(source);
    }
    loop {
        let mut header = [0; 52];
        if input.read(&mut header[..1])? == 0 {
            break;
        }
        input
            .read_exact(&mut header[1..])
            .context("truncated BCF1 header")?;
        if &header[..8] != b"BCF1\x01\0\0\0" {
            bail!("sidecar requires canonical observed BCF1 frames");
        }
        let number = u64::from_be_bytes(header[8..16].try_into()?);
        let length = u32::from_be_bytes(header[48..52].try_into()?) as usize;
        if length > 16 * 1024 * 1024 {
            bail!("sidecar frame exceeds bounded size");
        }
        let mut payload = vec![0; length];
        input
            .read_exact(&mut payload)
            .context("truncated BCF1 payload")?;
        let changes = decode_canonical_block_changes(&payload, compatibility)
            .map_err(|e| anyhow::anyhow!(e))?;
        if changes.block_number != number || changes.block_hash != header[16..48] {
            bail!("BCF1 payload identity mismatch");
        }
        if changes.operations.iter().any(|op| matches!(op.operation, Some(backfill_common::pb::pinax::graph::backfill::v1::entity_operation::Operation::DeterministicError(_)))) {
            bail!("data-source sidecar refuses deterministic-error runs: indexing-error metadata is not implemented");
        }
        hash.update(header);
        hash.update(&payload);
        blocks.push(Block {
            block_number: number,
            block_hash: hex::encode(&header[16..48]),
            payload_sha256: hex::encode(Sha256::digest(&payload)),
            sources: sources.remove(&number).unwrap_or_default(),
        });
        if blocks.len() > MAX_BLOCKS {
            bail!("sidecar is limited to 10000 blocks");
        }
    }
    if !sources.is_empty() {
        bail!("dynamic sources fall outside the frame stream");
    }
    let sidecar = Sidecar {
        contract: CONTRACT.into(),
        descriptor_sha256: host.descriptor_sha256().into(),
        stream_sha256: hex::encode(hash.finalize()),
        root_start_block: host.bounds().start as u64,
        blocks,
    };
    sidecar
        .validate(host.descriptor_sha256())
        .map_err(anyhow::Error::msg)?;
    let bytes = serde_json::to_vec_pretty(&sidecar)?;
    if bytes.len() > backfill_common::dynamic_sources::MAX_BYTES {
        bail!("data-source sidecar exceeds bounded size");
    }
    let mut file = File::options().write(true).create_new(true).open(output)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}
