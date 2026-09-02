//! Offline checks for the Uniswap V3 block fixtures and module goldens (#113).

use std::fmt;
use std::path::Path;

use serde_json::Value;

use crate::evidence::{self, Lock};

pub const BLOCKS_LOCK: &str = "uniswap-v3/fixtures/blocks.lock.json";
pub const GOLDENS_ROOT: &str = "uniswap-v3/fixtures/goldens";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FixtureError(pub String);

impl fmt::Display for FixtureError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for FixtureError {}

pub type Result<T> = std::result::Result<T, FixtureError>;

fn fail<T>(message: impl Into<String>) -> Result<T> {
    Err(FixtureError(message.into()))
}

fn varint(bytes: &[u8], mut i: usize) -> Option<(u64, usize)> {
    let mut value: u64 = 0;
    let mut shift = 0u32;
    loop {
        let byte = *bytes.get(i)?;
        i += 1;
        value |= u64::from(byte & 0x7f) << shift;
        if byte & 0x80 == 0 {
            return Some((value, i));
        }
        shift += 7;
        if shift > 63 {
            return None;
        }
    }
}

/// Header facts read from the first top-level fields of an
/// `sf.ethereum.type.v2.Block` protobuf: `ver` (1), `hash` (2), `number` (3).
#[derive(Debug, PartialEq, Eq)]
pub struct BlockIdentity {
    pub version: u64,
    pub hash: Vec<u8>,
    pub number: u64,
}

pub fn block_identity(bytes: &[u8]) -> Result<BlockIdentity> {
    let mut i = 0usize;
    let mut version = None;
    let mut hash = None;
    let mut number = None;
    while i < bytes.len() && (version.is_none() || hash.is_none() || number.is_none()) {
        let Some((tag, next)) = varint(bytes, i) else {
            return fail("truncated protobuf tag");
        };
        i = next;
        let field = tag >> 3;
        match tag & 7 {
            0 => {
                let Some((value, next)) = varint(bytes, i) else {
                    return fail("truncated varint");
                };
                i = next;
                match field {
                    1 => version = Some(value),
                    3 => number = Some(value),
                    _ => {}
                }
            }
            2 => {
                let Some((len, next)) = varint(bytes, i) else {
                    return fail("truncated length");
                };
                let end = next + len as usize;
                if end > bytes.len() {
                    return fail("length-delimited field exceeds buffer");
                }
                if field == 2 {
                    hash = Some(bytes[next..end].to_vec());
                }
                i = end;
            }
            _ => {
                return fail(format!(
                    "unexpected wire type in block header at field {field}"
                ))
            }
        }
    }
    match (version, hash, number) {
        (Some(version), Some(hash), Some(number)) => Ok(BlockIdentity {
            version,
            hash,
            number,
        }),
        _ => fail("block header lacks ver, hash, or number"),
    }
}

pub struct Report {
    pub lines: Vec<String>,
}

/// Verify hydrated fixture blocks against the lock and each file's own header,
/// then every golden: valid JSONL, one record per line, `@block` and `@module`
/// matching the path, and a locked fixture block for that block number.
pub fn check(root: &Path) -> Result<Report> {
    let lock = Lock::load(&root.join(BLOCKS_LOCK)).map_err(|e| FixtureError(e.to_string()))?;
    let report = evidence::check(&lock, root);
    if !report.ok() {
        let missing: Vec<&str> = report
            .rows
            .iter()
            .filter(|(_, status, _)| *status != evidence::Status::Verified)
            .map(|(path, _, _)| path.as_str())
            .collect();
        return fail(format!("fixture blocks not hydrated or mismatched: {missing:?} (run `cargo xtask evidence fetch --lock {BLOCKS_LOCK}`)"));
    }
    let mut lines = Vec::new();
    let mut locked_blocks = std::collections::BTreeSet::new();
    for asset in &lock.assets {
        let path = Path::new(&asset.path);
        let stem = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or_default();
        let expected: u64 = stem.parse().map_err(|_| {
            FixtureError(format!(
                "{}: file name must be the block number",
                asset.path
            ))
        })?;
        let bytes = std::fs::read(root.join(path))
            .map_err(|e| FixtureError(format!("{}: {e}", asset.path)))?;
        let identity =
            block_identity(&bytes).map_err(|e| FixtureError(format!("{}: {e}", asset.path)))?;
        if identity.number != expected {
            return fail(format!(
                "{}: protobuf block number {} differs from file name",
                asset.path, identity.number
            ));
        }
        if identity.hash.len() != 32 {
            return fail(format!(
                "{}: block hash has {} bytes",
                asset.path,
                identity.hash.len()
            ));
        }
        let network = path
            .parent()
            .and_then(|p| p.file_name())
            .and_then(|n| n.to_str())
            .unwrap_or_default()
            .to_string();
        locked_blocks.insert((network.clone(), expected));
        lines.push(format!(
            "block {network}/{expected}: {} bytes, ver {}, hash 0x{}",
            asset.bytes,
            identity.version,
            hex::encode(&identity.hash)
        ));
    }

    let goldens_root = root.join(GOLDENS_ROOT);
    let mut golden_count = 0usize;
    let mut networks = std::fs::read_dir(&goldens_root)
        .map_err(|e| FixtureError(format!("{GOLDENS_ROOT}: {e}")))?
        .flatten()
        .map(|e| e.path())
        .collect::<Vec<_>>();
    networks.sort();
    for network_dir in networks {
        let network = network_dir
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or_default()
            .to_string();
        let mut blocks = std::fs::read_dir(&network_dir)
            .map_err(|e| FixtureError(e.to_string()))?
            .flatten()
            .map(|e| e.path())
            .collect::<Vec<_>>();
        blocks.sort();
        for block_dir in blocks {
            let block: u64 = block_dir
                .file_name()
                .and_then(|n| n.to_str())
                .and_then(|s| s.parse().ok())
                .ok_or_else(|| {
                    FixtureError(format!(
                        "{}: golden directory must be a block number",
                        block_dir.display()
                    ))
                })?;
            if !locked_blocks.contains(&(network.clone(), block)) {
                return fail(format!(
                    "goldens for {network}/{block} have no locked fixture block"
                ));
            }
            let mut files = std::fs::read_dir(&block_dir)
                .map_err(|e| FixtureError(e.to_string()))?
                .flatten()
                .map(|e| e.path())
                .collect::<Vec<_>>();
            files.sort();
            for file in files {
                let module = file
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or_default()
                    .to_string();
                if file.extension().and_then(|e| e.to_str()) != Some("jsonl") {
                    return fail(format!("{}: goldens must be .jsonl", file.display()));
                }
                let text = std::fs::read_to_string(&file)
                    .map_err(|e| FixtureError(format!("{}: {e}", file.display())))?;
                let mut records = 0usize;
                for (index, line) in text.lines().enumerate() {
                    if line.trim().is_empty() {
                        return fail(format!("{}: blank line {}", file.display(), index + 1));
                    }
                    let record: Value = serde_json::from_str(line).map_err(|e| {
                        FixtureError(format!("{}:{}: {e}", file.display(), index + 1))
                    })?;
                    if record.get("@module").and_then(Value::as_str) != Some(module.as_str()) {
                        return fail(format!(
                            "{}:{}: @module differs from file name",
                            file.display(),
                            index + 1
                        ));
                    }
                    if record.get("@block").and_then(Value::as_u64) != Some(block) {
                        return fail(format!(
                            "{}:{}: @block differs from directory",
                            file.display(),
                            index + 1
                        ));
                    }
                    if !record.get("@data").is_some_and(Value::is_object) {
                        return fail(format!(
                            "{}:{}: @data must be an object",
                            file.display(),
                            index + 1
                        ));
                    }
                    records += 1;
                }
                if records == 0 {
                    return fail(format!("{}: empty golden", file.display()));
                }
                golden_count += 1;
                lines.push(format!(
                    "golden {network}/{block}/{module}: {records} record(s)"
                ));
            }
        }
    }
    lines.push(format!(
        "fixtures check: {} blocks and {golden_count} goldens verified",
        lock.assets.len()
    ));
    Ok(Report { lines })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn block_identity_reads_ver_hash_number() {
        // ver=3, hash=32 zero bytes, number=12369621 (varint d5 fd f2 05)
        let mut bytes = vec![0x08, 0x03, 0x12, 0x20];
        bytes.extend(std::iter::repeat_n(0u8, 32));
        bytes.extend([0x18, 0xd5, 0xfd, 0xf2, 0x05]);
        bytes.extend([0x20, 0x01]); // size=1, ignored
        let identity = block_identity(&bytes).unwrap();
        assert_eq!(
            identity,
            BlockIdentity {
                version: 3,
                hash: vec![0; 32],
                number: 12369621
            }
        );
        assert!(block_identity(&bytes[..10]).is_err());
        assert!(block_identity(&[0x08]).is_err());
    }

    #[test]
    fn goldens_and_lock_in_repository_are_consistent_when_hydrated() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
        let lock = Lock::load(&root.join(BLOCKS_LOCK)).unwrap();
        assert_eq!(lock.release_tag, "block-fixtures-v1");
        assert!(lock.assets.iter().all(|a| a.asset.ends_with(".pb")));
        if evidence::check(&lock, &root).ok() {
            let report = check(&root).unwrap();
            assert!(report.lines.last().unwrap().contains("goldens verified"));
        }
    }
}
