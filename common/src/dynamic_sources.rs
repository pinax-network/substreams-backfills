//! Explicit metadata companion to unchanged BlockChanges v1. This bounded
//! onchain/root-only contract is not a general graft or offchain protocol.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

pub const CONTRACT: &str = "pinax.graph.backfill.data-sources/v1";
pub const MAX_BLOCKS: usize = 10_000;
pub const MAX_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DataSource {
    pub creation_block: i32,
    pub manifest_idx: i32,
    pub causality_region: i32,
    /// Lowercase hex without a prefix; onchain Ethereum address bytes.
    pub param: String,
    /// Exact Graph Node `DataSourceContext` serde representation, not a
    /// GraphQL/entity-value projection.
    pub context: Option<serde_json::Value>,
    pub done_at: Option<i32>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Block {
    pub block_number: u64,
    pub block_hash: String,
    pub payload_sha256: String,
    /// Accepted, deduplicated and committed sources in host creation order.
    pub sources: Vec<DataSource>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sidecar {
    pub contract: String,
    pub descriptor_sha256: String,
    pub stream_sha256: String,
    /// This version refuses checkpoint/graft input, even an empty one.
    pub root_start_block: u64,
    /// Every observed frame, including blocks creating no source.
    pub blocks: Vec<Block>,
}

fn digest(value: &str, bytes: usize) -> bool {
    value.len() == bytes * 2
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

impl Sidecar {
    pub fn parse(bytes: &[u8], descriptor_sha256: &str) -> Result<Self, String> {
        if bytes.len() > MAX_BYTES {
            return Err("data-source sidecar exceeds bounded v1 size".into());
        }
        let sidecar: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        sidecar.validate(descriptor_sha256)?;
        Ok(sidecar)
    }

    pub fn validate(&self, descriptor_sha256: &str) -> Result<(), String> {
        if self.contract != CONTRACT
            || self.descriptor_sha256 != descriptor_sha256
            || !digest(&self.descriptor_sha256, 32)
            || !digest(&self.stream_sha256, 32)
        {
            return Err(
                "data-source sidecar contract or descriptor/stream binding mismatch".into(),
            );
        }
        if self.blocks.is_empty() || self.blocks.len() > MAX_BLOCKS {
            return Err("data-source sidecar requires 1..=10000 observed blocks".into());
        }
        if self.root_start_block > i32::MAX as u64 {
            return Err("data-source root start exceeds Graph Node block domain".into());
        }
        let mut identities = BTreeSet::new();
        for (offset, block) in self.blocks.iter().enumerate() {
            if block.block_number != self.root_start_block + offset as u64
                || block.block_number > i32::MAX as u64
                || !digest(&block.block_hash, 32)
                || block.block_hash == "00".repeat(32)
                || !digest(&block.payload_sha256, 32)
            {
                return Err("data-source sidecar block coverage/hash is invalid".into());
            }
            for source in &block.sources {
                if source.creation_block < 0
                    || source.creation_block as u64 != block.block_number
                    || source.manifest_idx < 0
                    || source.causality_region != 0
                    || source.done_at.is_some()
                    || !digest(&source.param, 20)
                    || source.context.as_ref().is_some_and(|v| !v.is_object())
                {
                    return Err(
                        "data-source sidecar requires committed onchain Ethereum creations".into(),
                    );
                }
                let identity = (
                    source.manifest_idx,
                    source.param.clone(),
                    serde_json::to_string(&source.context).map_err(|e| e.to_string())?,
                );
                if !identities.insert(identity) {
                    return Err("data-source sidecar contains a duplicate source identity".into());
                }
            }
        }
        Ok(())
    }

    pub fn verify_frame(
        &self,
        offset: usize,
        number: u64,
        hash: &[u8],
        payload: &[u8],
    ) -> Result<&[DataSource], String> {
        let block = self
            .blocks
            .get(offset)
            .ok_or("data-source sidecar missing frame coverage")?;
        if block.block_number != number
            || block.block_hash != hex::encode(hash)
            || block.payload_sha256 != hex::encode(Sha256::digest(payload))
        {
            return Err(format!("data-source sidecar disagrees with frame {number}"));
        }
        Ok(&block.sources)
    }
}

/// Hash the unique canonical observed BCF1 encoding. Synthetic frames are
/// intentionally unsupported by this companion contract.
pub fn hash_frame(
    hasher: &mut Sha256,
    number: u64,
    hash: &[u8],
    payload: &[u8],
) -> Result<(), String> {
    if hash.len() != 32 || payload.len() > u32::MAX as usize {
        return Err("invalid observed BCF1 frame".into());
    }
    hasher.update(b"BCF1\x01\0\0\0");
    hasher.update(number.to_be_bytes());
    hasher.update(hash);
    hasher.update((payload.len() as u32).to_be_bytes());
    hasher.update(payload);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Sidecar {
        Sidecar {
            contract: CONTRACT.into(),
            descriptor_sha256: "ab".repeat(32),
            stream_sha256: "cd".repeat(32),
            root_start_block: 10,
            blocks: vec![Block {
                block_number: 10,
                block_hash: "01".repeat(32),
                payload_sha256: hex::encode(Sha256::digest(b"payload")),
                sources: vec![DataSource {
                    creation_block: 10,
                    manifest_idx: 2,
                    causality_region: 0,
                    param: "ab".repeat(20),
                    context: Some(serde_json::json!({"label":{"type":"String","data":"a\tb"}})),
                    done_at: None,
                }],
            }],
        }
    }
    #[test]
    fn exact_round_trip_and_frame_binding() {
        let s = fixture();
        assert_eq!(
            Sidecar::parse(&serde_json::to_vec(&s).unwrap(), &s.descriptor_sha256).unwrap(),
            s
        );
        assert_eq!(
            s.verify_frame(0, 10, &[1; 32], b"payload").unwrap().len(),
            1
        );
        assert!(s.verify_frame(1, 10, &[1; 32], b"payload").is_err());
        assert!(s.verify_frame(0, 10, &[2; 32], b"payload").is_err());
        assert!(s.verify_frame(0, 10, &[1; 32], b"other").is_err());
    }
    #[test]
    fn rejects_missing_duplicate_reordered_and_unsupported_metadata() {
        let changes: Vec<fn(&mut Sidecar)> = vec![
            |s| s.blocks.clear(),
            |s| s.blocks.push(s.blocks[0].clone()),
            |s| s.blocks[0].block_number += 1,
            |s| s.root_start_block += 1,
            |s| {
                let source = s.blocks[0].sources[0].clone();
                s.blocks[0].sources.push(source);
            },
            |s| s.blocks[0].sources[0].causality_region = 1,
            |s| s.blocks[0].sources[0].creation_block -= 1,
            |s| s.blocks[0].sources[0].done_at = Some(10),
            |s| s.blocks[0].sources[0].param = "AB".repeat(20),
            |s| s.blocks[0].sources[0].context = Some(serde_json::json!([])),
        ];
        for change in changes {
            let mut s = fixture();
            change(&mut s);
            assert!(s.validate(&"ab".repeat(32)).is_err());
        }
        assert!(fixture().validate(&"00".repeat(32)).is_err());
    }
}
