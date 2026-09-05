//! v2 producer chunk orchestration. The immutable direct predecessor seal,
//! checkpoint and sorted identity index are verified before opening outputs.
//! This does not bound the host's complete entity store, cache or cassette.
use crate::{
    checkpoint::{CheckpointHeader, HostCheckpoint},
    descriptor,
    runner::SegmentHost,
};
use anyhow::{bail, ensure, Context, Result};
use backfill_common::{
    decode_canonical_block_changes,
    dynamic_sources_v2::{
        self as v2, index, seal, Block, Chunk, Creation, FilePin, SourceOrder, SourceState,
    },
    BlockChangesCompatibility,
};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    io::{BufRead, BufReader, Read},
    path::{Path, PathBuf},
};

pub struct Plan {
    pub output: PathBuf,
    pub building: PathBuf,
    pub parent: Option<seal::SealedChunk>,
    range: Option<(i32, i32)>,
}

impl Plan {
    pub fn preflight(segment: &Path, output: &Path, previous: Option<&Path>) -> Result<Self> {
        ensure!(
            output.extension().and_then(|e| e.to_str()) == Some("ready"),
            "--source-chunk-out must end in .ready"
        );
        let building = output.with_extension("building");
        absent(output)?;
        absent(&building)?;
        let (compatibility, digest) = descriptor::load(segment)?;
        let parent = previous
            .map(|path| seal::SealedChunk::open(path, &digest).map_err(anyhow::Error::msg))
            .transpose()?;
        if let Some(parent) = &parent {
            // The direct predecessor itself must obey the zero-error mapping
            // contract, not only its self-consistent byte-level seal.
            scan(
                &parent.directory.join(seal::STREAM),
                &compatibility,
                parent.chunk.from,
                parent.chunk.to,
                BTreeMap::new(),
            )?;
            let output_parent = output
                .parent()
                .filter(|p| !p.as_os_str().is_empty())
                .unwrap_or(Path::new("."));
            ensure!(
                !output_parent
                    .canonicalize()?
                    .starts_with(parent.directory.canonicalize()?),
                "source chunk output cannot modify its immutable predecessor directory"
            );
        }
        Ok(Self {
            output: output.to_owned(),
            building,
            parent,
            range: None,
        })
    }

    pub fn checkpoint_input(&self) -> Option<PathBuf> {
        self.parent
            .as_ref()
            .map(|p| p.directory.join(seal::CHECKPOINT))
    }

    pub fn validate_restored(
        &self,
        host: &SegmentHost,
        checkpoint: Option<&HostCheckpoint>,
    ) -> Result<()> {
        ensure!(
            !host.is_grafted(),
            "v2 source chunks refuse grafted manifests"
        );
        let identity = host.checkpoint_identity();
        match (&self.parent, checkpoint) {
            (Some(parent), Some(checkpoint)) => {
                ensure!(
                    parent.chunk.deployment == identity.deployment
                        && parent.chunk.network == identity.network,
                    "source chunk predecessor deployment/network mismatch"
                );
                validate_checkpoint_header(&parent.chunk, &checkpoint.header)?;
                let mut order = SourceOrder::empty();
                let mut index = index::Index::open(
                    &parent.directory.join(seal::IDENTITIES),
                    &parent.chunk.after,
                )
                .map_err(anyhow::Error::msg)?;
                for source in host.stored_dynamic_data_sources_iter() {
                    let key = order
                        .append(&Creation {
                            ordinal: order.count,
                            source: source?,
                        })
                        .map_err(anyhow::Error::msg)?;
                    ensure!(
                        index.contains(&key).map_err(anyhow::Error::msg)?,
                        "restored host source is absent from its predecessor identity index"
                    );
                }
                ensure!(
                    order == parent.chunk.after.order,
                    "restored host source order differs from its predecessor metadata"
                );
            }
            (None, None) => ensure!(
                host.dynamic_data_sources().is_empty(),
                "fresh source chunk has preexisting dynamic hosts"
            ),
            _ => bail!("v2 source continuation requires its sealed predecessor checkpoint"),
        }
        Ok(())
    }

    pub fn bind_range(&mut self, host: &SegmentHost, range: (i32, i32)) -> Result<()> {
        ensure!(
            !host.is_grafted(),
            "v2 source chunks refuse grafted manifests"
        );
        host.bounds().check_range(range.0, range.1)?;
        ensure!(
            (range.1 as i64 - range.0 as i64) <= v2::MAX_BLOCKS as i64,
            "v2 source chunks are limited to 10000 blocks per chunk"
        );
        let expected = self
            .parent
            .as_ref()
            .map(|p| p.chunk.to)
            .unwrap_or(host.bounds().start as u64);
        ensure!(
            range.0 as u64 == expected,
            "v2 source chunk range does not begin at its exact predecessor/root boundary"
        );
        if let Some(parent) = &self.parent {
            ensure!(
                parent.chunk.root_start_block == host.bounds().start as u64,
                "source chunk root start changed across checkpoints"
            );
        }
        self.range = Some(range);
        Ok(())
    }

    pub fn range(&self) -> Option<(i32, i32)> {
        self.range
    }

    pub fn prepare(&self) -> Result<()> {
        ensure!(self.range.is_some(), "source chunk range was not validated");
        if let Some(parent) = &self.parent {
            parent.verify_unchanged().map_err(anyhow::Error::msg)?;
        }
        absent(&self.output)?;
        absent(&self.building)?;
        fs::create_dir(&self.building).context("creating fresh source chunk staging directory")?;
        Ok(())
    }

    pub fn finish(&self, host: &SegmentHost) -> Result<seal::SealedChunk> {
        ensure!(
            !host.is_grafted(),
            "v2 source chunks refuse grafted manifests"
        );
        let (from, to) = self.range.context("source chunk range was not validated")?;
        let before = self
            .parent
            .as_ref()
            .map(|p| p.chunk.after.clone())
            .unwrap_or_else(SourceState::empty);
        let mut order = SourceOrder::empty();
        let mut sources = BTreeMap::<u64, Vec<Creation>>::new();
        let mut source_bytes = 0;
        let mut prefix_checked = before.order.count == 0;
        for source in host.stored_dynamic_data_sources_iter() {
            let creation = Creation {
                ordinal: order.count,
                source: source?,
            };
            order.append(&creation).map_err(anyhow::Error::msg)?;
            if creation.ordinal < before.order.count {
                if order.count == before.order.count {
                    ensure!(
                        order == before.order,
                        "host source prefix changed while replaying a chunk"
                    );
                    prefix_checked = true;
                }
                continue;
            }
            // Account before retaining a creation. Historical hosts never form
            // a second vector and new metadata cannot grow past the chunk cap.
            source_bytes += serde_json::to_vec(&creation)?.len();
            ensure!(
                source_bytes <= v2::MAX_BYTES,
                "v2 source chunk metadata exceeds 16 MiB"
            );
            sources
                .entry(creation.source.creation_block as u64)
                .or_default()
                .push(creation);
        }
        ensure!(prefix_checked, "host lost predecessor source metadata");
        let (blocks, stream) = scan(
            &self.building.join(seal::STREAM),
            host.compatibility(),
            from as u64,
            to as u64,
            sources,
        )?;
        let new_keys = blocks
            .iter()
            .flat_map(|b| &b.sources)
            .map(|c| v2::identity(&c.source))
            .collect::<Result<std::collections::BTreeSet<_>, _>>()
            .map_err(anyhow::Error::msg)?;
        let parent_index = self
            .parent
            .as_ref()
            .map(|p| p.directory.join(seal::IDENTITIES));
        let identities = index::merge(
            &self.building.join(seal::IDENTITIES),
            parent_index.as_deref().map(|p| (p, &before)),
            &new_keys,
        )
        .map_err(anyhow::Error::msg)?;
        let identity = host.checkpoint_identity();
        let chunk = Chunk {
            contract: v2::CONTRACT.into(),
            deployment: identity.deployment,
            network: identity.network,
            descriptor_sha256: host.descriptor_sha256().into(),
            root_start_block: host.bounds().start as u64,
            from: from as u64,
            to: to as u64,
            parent: self.parent.as_ref().map(|p| p.parent()),
            stream,
            checkpoint: FilePin::read(&self.building.join(seal::CHECKPOINT))
                .map_err(anyhow::Error::msg)?,
            before,
            after: SourceState { order, identities },
            blocks,
        };
        // Read only the bounded header, never a second complete checkpoint
        // image. The checkpoint writer and live host must agree before sealing.
        let input = index::open_regular(&self.building.join(seal::CHECKPOINT))
            .map_err(anyhow::Error::msg)?;
        let mut line = String::new();
        BufReader::new(input)
            .take(v2::MAX_BYTES as u64 + 1)
            .read_line(&mut line)?;
        ensure!(
            line.len() <= v2::MAX_BYTES,
            "checkpoint header exceeds size bound"
        );
        let header: CheckpointHeader = serde_json::from_str(&line)?;
        ensure!(
            header.identity == host.checkpoint_identity(),
            "closing checkpoint identity mismatch"
        );
        validate_checkpoint_header(&chunk, &header)?;
        seal::publish(&self.building, &self.output, &chunk, self.parent.as_ref())
            .map_err(anyhow::Error::msg)
    }
}

fn validate_checkpoint_header(chunk: &Chunk, header: &CheckpointHeader) -> Result<()> {
    let boundary = &header.boundary;
    ensure!(
        boundary.block as u64 == chunk.to - 1
            && boundary.block_hash.trim_start_matches("0x") == chunk.boundary().hash
            && boundary.chunk_from.map(i64::from) == Some(chunk.from as i64)
            && boundary.chunk_to.map(i64::from) == Some(chunk.to as i64)
            && boundary.blocks_in_chunk as u64 == chunk.to - chunk.from
            && boundary.blocks_total as u64 == chunk.to - chunk.root_start_block,
        "source chunk producer checkpoint boundary/range mismatch"
    );
    ensure!(
        boundary.previous_checkpoint_sha256.as_deref()
            == chunk.parent.as_ref().map(|p| p.checkpoint.sha256.as_str())
            && (boundary.chunk_index == 0) == chunk.parent.is_none(),
        "source chunk producer checkpoint ancestry mismatch"
    );
    ensure!(
        header.totals.dynamic_data_sources as u64 == chunk.after.order.count,
        "source chunk producer checkpoint source count mismatch"
    );
    Ok(())
}

fn absent(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
        Ok(_) => bail!("source chunk refuses existing output {}", path.display()),
    }
}

fn scan(
    path: &Path,
    compatibility: &BlockChangesCompatibility,
    from: u64,
    to: u64,
    mut sources: BTreeMap<u64, Vec<Creation>>,
) -> Result<(Vec<Block>, FilePin)> {
    ensure!(
        to > from && to - from <= v2::MAX_BLOCKS as u64,
        "invalid bounded source chunk range"
    );
    let mut input = index::open_regular(path).map_err(anyhow::Error::msg)?;
    let mut hash = Sha256::new();
    let mut bytes = 0;
    let mut blocks = Vec::new();
    loop {
        let mut header = [0; 52];
        if input.read(&mut header[..1])? == 0 {
            break;
        }
        input
            .read_exact(&mut header[1..])
            .context("truncated v2 BCF1 header")?;
        ensure!(
            &header[..8] == b"BCF1\x01\0\0\0",
            "v2 requires observed BCF1 frames"
        );
        let number = u64::from_be_bytes(header[8..16].try_into()?);
        ensure!(
            number == from + blocks.len() as u64 && number < to,
            "v2 BCF1 range/coverage mismatch"
        );
        let length = u32::from_be_bytes(header[48..].try_into()?) as usize;
        ensure!(length <= v2::MAX_BYTES, "v2 BCF1 frame exceeds size bound");
        let mut payload = vec![0; length];
        input
            .read_exact(&mut payload)
            .context("truncated v2 BCF1 payload")?;
        let changes =
            decode_canonical_block_changes(&payload, compatibility).map_err(anyhow::Error::msg)?;
        ensure!(
            changes.block_number == number && changes.block_hash == header[16..48],
            "v2 BCF1 payload identity mismatch"
        );
        ensure!(!changes.operations.iter().any(|op| matches!(op.operation,
            Some(backfill_common::pb::pinax::graph::backfill::v1::entity_operation::Operation::DeterministicError(_)))),
            "v2 source chunks refuse deterministic indexing errors");
        hash.update(header);
        hash.update(&payload);
        bytes += 52 + length as u64;
        blocks.push(Block {
            block_number: number,
            block_hash: hex::encode(&header[16..48]),
            payload_sha256: hex::encode(Sha256::digest(payload)),
            sources: sources.remove(&number).unwrap_or_default(),
        });
    }
    ensure!(
        blocks.len() as u64 == to - from && sources.is_empty(),
        "v2 source chunk has incomplete block/source coverage"
    );
    Ok((
        blocks,
        FilePin {
            bytes,
            sha256: hex::encode(hash.finalize()),
        },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn the_real_fatal_frame_is_never_source_metadata_eligible() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let segment = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
        let (compatibility, _) =
            descriptor::load(&root.join(format!("segments/{segment}"))).unwrap();
        let payload =
            fs::read(root.join(format!("fixtures/block-changes/{segment}/12370523.pb"))).unwrap();
        let changes = decode_canonical_block_changes(&payload, &compatibility).unwrap();
        let tmp = tempfile::tempdir().unwrap();
        let stream = tmp.path().join("fatal.bcf1");
        fs::write(
            &stream,
            crate::blockchanges::bcf1_frame(changes.block_number, &changes.block_hash, &payload)
                .unwrap(),
        )
        .unwrap();
        let error = scan(&stream, &compatibility, 12370523, 12370524, BTreeMap::new()).unwrap_err();
        assert!(
            error.to_string().contains("deterministic indexing errors"),
            "{error}"
        );
        assert_eq!(fs::read_dir(tmp.path()).unwrap().count(), 1);
    }
}
