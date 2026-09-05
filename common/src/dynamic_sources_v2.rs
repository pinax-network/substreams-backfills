//! Immutable, bounded chunks of accepted onchain source creations.
//!
//! This is a separate capability from `data-sources/v1`, not a relaxation of
//! its root-only rules. It does not bound the mapping host's entity store.
use crate::dynamic_sources::DataSource;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::Path;

pub mod index;
pub mod seal;

pub const CONTRACT: &str = "pinax.graph.backfill.data-sources/v2";
pub const MAX_BLOCKS: usize = 10_000;
pub const MAX_BYTES: usize = 16 * 1024 * 1024;
const ORDER_DOMAIN: &[u8] = b"pinax.graph.backfill.data-sources/v2/creation-order\0";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilePin {
    pub bytes: u64,
    pub sha256: String,
}

impl FilePin {
    pub fn for_bytes(bytes: &[u8]) -> Self {
        Self {
            bytes: bytes.len() as u64,
            sha256: hex::encode(Sha256::digest(bytes)),
        }
    }

    pub fn read(path: &Path) -> Result<Self, String> {
        index::hash_file(path)
    }

    fn validate(&self) -> Result<(), String> {
        require(hex_value(&self.sha256, 32), "invalid file SHA-256")
    }
}

/// This semantic commitment is independent of chunk boundaries and paths.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceOrder {
    pub count: u64,
    pub sha256: String,
}

impl SourceOrder {
    pub fn empty() -> Self {
        Self {
            count: 0,
            sha256: hex::encode(Sha256::digest(ORDER_DOMAIN)),
        }
    }

    pub fn append(&mut self, creation: &Creation) -> Result<index::Identity, String> {
        require(
            creation.ordinal == self.count,
            "source creation ordinal is not contiguous",
        )?;
        let identity = identity(&creation.source)?;
        require(hex_value(&self.sha256, 32), "invalid source order SHA-256")?;
        let mut h = Sha256::new();
        h.update(ORDER_DOMAIN);
        h.update(hex::decode(&self.sha256).map_err(|e| e.to_string())?);
        h.update(creation.ordinal.to_be_bytes());
        h.update(creation.source.creation_block.to_be_bytes());
        h.update(identity);
        self.sha256 = hex::encode(h.finalize());
        self.count = self.count.checked_add(1).ok_or("source count overflow")?;
        Ok(identity)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceState {
    pub order: SourceOrder,
    /// Sorted unique identities, not creation order. Stored on disk, not in
    /// the checkpoint's in-memory entity image.
    pub identities: FilePin,
}

impl SourceState {
    pub fn empty() -> Self {
        Self {
            order: SourceOrder::empty(),
            identities: FilePin::for_bytes(index::MAGIC),
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        self.identities.validate()?;
        require(
            hex_value(&self.order.sha256, 32),
            "invalid source order SHA-256",
        )?;
        let length = self
            .order
            .count
            .checked_mul(index::RECORD_BYTES as u64)
            .and_then(|n| n.checked_add(index::MAGIC.len() as u64))
            .ok_or("source identity index length overflow")?;
        require(
            self.identities.bytes == length,
            "source identity index count/length mismatch",
        )?;
        if self.order.count == 0 {
            require(
                self == &Self::empty(),
                "empty source state has a non-empty commitment",
            )?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Boundary {
    pub block: u64,
    pub hash: String,
}

/// Exact immediate predecessor artifacts, not caller assertions about a head.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Parent {
    pub boundary: Boundary,
    pub seal: FilePin,
    pub manifest: FilePin,
    pub stream: FilePin,
    pub metadata: FilePin,
    pub checkpoint: FilePin,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Creation {
    pub ordinal: u64,
    pub source: DataSource,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Block {
    pub block_number: u64,
    pub block_hash: String,
    pub payload_sha256: String,
    pub sources: Vec<Creation>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Chunk {
    pub contract: String,
    pub deployment: String,
    pub network: String,
    pub descriptor_sha256: String,
    pub root_start_block: u64,
    pub from: u64,
    pub to: u64,
    pub parent: Option<Parent>,
    pub stream: FilePin,
    pub checkpoint: FilePin,
    pub before: SourceState,
    pub after: SourceState,
    pub blocks: Vec<Block>,
}

impl Chunk {
    pub fn parse(bytes: &[u8], descriptor_sha256: &str) -> Result<Self, String> {
        require(bytes.len() <= MAX_BYTES, "v2 source chunk exceeds 16 MiB")?;
        let value: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        value.validate(descriptor_sha256)?;
        Ok(value)
    }

    pub fn validate(&self, descriptor_sha256: &str) -> Result<(), String> {
        require(
            self.contract == CONTRACT,
            "unsupported source metadata capability",
        )?;
        require(
            hex_value(&self.descriptor_sha256, 32) && self.descriptor_sha256 == descriptor_sha256,
            "source chunk descriptor mismatch",
        )?;
        require(
            !self.deployment.is_empty() && !self.network.is_empty(),
            "missing source chunk identity",
        )?;
        require(
            self.from >= self.root_start_block
                && self.to > self.from
                && self.to <= i32::MAX as u64 + 1
                && self.to - self.from <= MAX_BLOCKS as u64,
            "v2 source chunk requires 1..=10000 blocks",
        )?;
        require(
            self.blocks.len() as u64 == self.to - self.from,
            "source chunk has missing block coverage",
        )?;
        self.before.validate()?;
        self.after.validate()?;
        self.stream.validate()?;
        self.checkpoint.validate()?;
        if let Some(parent) = &self.parent {
            require(
                parent.boundary.block.checked_add(1) == Some(self.from)
                    && self.from > self.root_start_block
                    && block_hash(&parent.boundary.hash),
                "source chunk parent boundary mismatch",
            )?;
            for pin in [
                &parent.seal,
                &parent.manifest,
                &parent.stream,
                &parent.metadata,
                &parent.checkpoint,
            ] {
                pin.validate()?;
            }
        } else {
            require(
                self.from == self.root_start_block && self.before == SourceState::empty(),
                "source chunk without predecessor must begin at an empty root",
            )?;
        }
        let mut order = self.before.order.clone();
        let mut identities = std::collections::BTreeSet::new();
        for (offset, block) in self.blocks.iter().enumerate() {
            require(
                block.block_number == self.from + offset as u64
                    && block_hash(&block.block_hash)
                    && hex_value(&block.payload_sha256, 32),
                "source chunk block order/hash mismatch",
            )?;
            for creation in &block.sources {
                require(
                    creation.source.creation_block as i64 == block.block_number as i64,
                    "source creation falls outside its block",
                )?;
                let key = order.append(creation)?;
                require(
                    identities.insert(key),
                    "duplicate source identity inside chunk",
                )?;
            }
        }
        require(
            order == self.after.order,
            "source chunk final creation-order commitment mismatch",
        )
    }

    pub fn boundary(&self) -> Boundary {
        let last = self.blocks.last().expect("validated nonempty chunk");
        Boundary {
            block: last.block_number,
            hash: last.block_hash.clone(),
        }
    }

    pub fn require_parent(&self, previous: &seal::SealedChunk) -> Result<(), String> {
        let expected = previous.parent();
        require(
            self.parent.as_ref() == Some(&expected),
            "source chunk predecessor artifacts mismatch",
        )?;
        require(
            self.before == previous.chunk.after
                && self.root_start_block == previous.chunk.root_start_block
                && self.descriptor_sha256 == previous.chunk.descriptor_sha256
                && self.deployment == previous.chunk.deployment
                && self.network == previous.chunk.network,
            "source chunk predecessor state/identity mismatch",
        )
    }

    pub fn verify_frame(
        &self,
        offset: usize,
        number: u64,
        hash: &[u8],
        payload: &[u8],
    ) -> Result<&[Creation], String> {
        let block = self
            .blocks
            .get(offset)
            .ok_or("source chunk missing frame")?;
        require(
            block.block_number == number
                && block.block_hash == hex::encode(hash)
                && block.payload_sha256 == hex::encode(Sha256::digest(payload)),
            "source chunk disagrees with BCF1 frame",
        )?;
        Ok(&block.sources)
    }

    pub fn new_identities(&self) -> Result<std::collections::BTreeSet<index::Identity>, String> {
        self.validate(&self.descriptor_sha256)?;
        self.blocks
            .iter()
            .flat_map(|b| &b.sources)
            .map(|c| identity(&c.source))
            .collect()
    }
}

pub fn identity(source: &DataSource) -> Result<index::Identity, String> {
    require(
        source.creation_block >= 0
            && source.manifest_idx >= 0
            && source.causality_region == 0
            && source.context.is_none()
            && source.done_at.is_none()
            && hex_value(&source.param, 20),
        "v2 requires onchain Ethereum sources with NULL context and no done_at",
    )?;
    let mut key = [0; index::RECORD_BYTES];
    key[..4].copy_from_slice(&source.manifest_idx.to_be_bytes());
    key[4..].copy_from_slice(&hex::decode(&source.param).map_err(|e| e.to_string())?);
    Ok(key)
}

fn block_hash(s: &str) -> bool {
    hex_value(s, 32) && s.bytes().any(|b| b != b'0')
}
fn hex_value(s: &str, n: usize) -> bool {
    s.len() == n * 2
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn require(ok: bool, message: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(message.to_owned())
    }
}
