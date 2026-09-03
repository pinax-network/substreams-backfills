//! Offline checks for the Uniswap V3 block fixtures and module goldens (#113).

use std::fmt;
use std::path::{Path, PathBuf};

use serde_json::Value;
use sha2::{Digest, Sha256};

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

/// One top-level field of a serialized protobuf message: its number, its wire
/// type, and the byte range holding its value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct TopField {
    number: u64,
    wire: u8,
    value: (usize, usize),
}

/// Walk the top-level fields of `bytes` from `from`, stopping at the end of
/// the buffer or where a second serialized message begins.
///
/// Protobuf serializers emit a message's fields in ascending field-number
/// order, and consecutive entries of a repeated field keep the same number, so
/// a field whose number is lower than its predecessor's cannot belong to the
/// message being read: it is the first field of the next message of a
/// concatenated stream. Returns the first message's fields and the offset just
/// past it.
fn scan_message(bytes: &[u8], from: usize) -> Result<(Vec<TopField>, usize)> {
    let mut fields: Vec<TopField> = Vec::new();
    let mut i = from;
    let mut previous: Option<u64> = None;
    while i < bytes.len() {
        let start = i;
        let Some((tag, next)) = varint(bytes, i) else {
            return fail(format!("truncated protobuf tag at byte {start}"));
        };
        let number = tag >> 3;
        let wire = (tag & 7) as u8;
        if number == 0 {
            return fail(format!("field number 0 at byte {start}"));
        }
        if previous.is_some_and(|previous| number < previous) {
            return Ok((fields, start));
        }
        i = next;
        let value = match wire {
            0 => {
                let Some((_, next)) = varint(bytes, i) else {
                    return fail(format!("truncated varint for field {number} at byte {i}"));
                };
                let range = (i, next);
                i = next;
                range
            }
            1 | 5 => {
                let width = if wire == 1 { 8usize } else { 4usize };
                if i + width > bytes.len() {
                    return fail(format!(
                        "fixed-width field {number} at byte {start} exceeds buffer"
                    ));
                }
                let range = (i, i + width);
                i += width;
                range
            }
            2 => {
                let Some((len, next)) = varint(bytes, i) else {
                    return fail(format!("truncated length for field {number} at byte {i}"));
                };
                let end = next
                    .checked_add(len as usize)
                    .filter(|end| *end <= bytes.len())
                    .ok_or_else(|| {
                        FixtureError(format!(
                            "length-delimited field {number} at byte {start} exceeds buffer"
                        ))
                    })?;
                i = end;
                (next, end)
            }
            other => {
                return fail(format!(
                    "unsupported wire type {other} for field {number} at byte {start}"
                ))
            }
        };
        fields.push(TopField {
            number,
            wire,
            value,
        });
        previous = Some(number);
    }
    Ok((fields, i))
}

/// Header facts read from the first top-level fields of an
/// `sf.ethereum.type.v2.Block` protobuf: `ver` (1), `hash` (2), `number` (3).
#[derive(Debug, PartialEq, Eq)]
pub struct BlockIdentity {
    pub version: u64,
    pub hash: Vec<u8>,
    pub number: u64,
}

fn identity_of(bytes: &[u8], fields: &[TopField]) -> Result<BlockIdentity> {
    let mut version = None;
    let mut hash = None;
    let mut number = None;
    for field in fields {
        match (field.number, field.wire) {
            (1, 0) => version = varint(bytes, field.value.0).map(|(value, _)| value),
            (2, 2) => hash = Some(bytes[field.value.0..field.value.1].to_vec()),
            (3, 0) => number = varint(bytes, field.value.0).map(|(value, _)| value),
            _ => {}
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

/// Read the header of a fixture that must hold **exactly one**
/// `sf.ethereum.type.v2.Block`.
///
/// A buffer holding two concatenated messages — what `firecore tools
/// firehose-client … B:B+1` writes — is rejected here instead of being
/// silently merged into one oversized block by `prost` at decode time (#113).
pub fn block_identity(bytes: &[u8]) -> Result<BlockIdentity> {
    let (fields, end) = scan_message(bytes, 0)?;
    if end != bytes.len() {
        let trailing = scan_message(bytes, end)
            .and_then(|(fields, _)| identity_of(bytes, &fields))
            .map(|identity| format!(" (block {})", identity.number))
            .unwrap_or_default();
        return fail(format!(
            "expected exactly one sf.ethereum.type.v2.Block message, found a second one{trailing} starting at byte {end} of {}; run `cargo xtask fixtures normalize`",
            bytes.len()
        ));
    }
    identity_of(bytes, &fields)
}

/// Where the first complete message ends inside a fixture, and the block
/// number of the message that follows it when the buffer holds two.
#[derive(Debug, PartialEq, Eq)]
pub struct Boundary {
    pub first_end: usize,
    pub total: usize,
    pub first_number: u64,
    pub trailing_number: Option<u64>,
}

/// Locate the end of the first `sf.ethereum.type.v2.Block` in a fixture.
///
/// A buffer holding one message reports `first_end == total` and no trailing
/// number. A buffer holding two reports the boundary and the second block's
/// number; that second message must itself run to the end of the buffer, so a
/// third message is an error rather than a silent truncation.
pub fn boundary(bytes: &[u8]) -> Result<Boundary> {
    let (fields, first_end) = scan_message(bytes, 0)?;
    let first_number = identity_of(bytes, &fields)?.number;
    if first_end == bytes.len() {
        return Ok(Boundary {
            first_end,
            total: bytes.len(),
            first_number,
            trailing_number: None,
        });
    }
    let (trailing_fields, trailing_end) = scan_message(bytes, first_end)?;
    if trailing_end != bytes.len() {
        return fail(format!(
            "fixture holds more than two messages: the second ends at byte {trailing_end} of {}",
            bytes.len()
        ));
    }
    let trailing_number = identity_of(bytes, &trailing_fields)?.number;
    Ok(Boundary {
        first_end,
        total: bytes.len(),
        first_number,
        trailing_number: Some(trailing_number),
    })
}

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn block_number_of(path: &Path) -> Result<u64> {
    path.file_stem()
        .and_then(|stem| stem.to_str())
        .and_then(|stem| stem.parse().ok())
        .ok_or_else(|| {
            FixtureError(format!(
                "{}: file name must be the block number",
                path.display()
            ))
        })
}

#[derive(Debug)]
pub struct Report {
    pub lines: Vec<String>,
}

/// Re-cut every locked fixture block to its first `sf.ethereum.type.v2.Block`.
///
/// The `block-fixtures-v1` capture used a `B:B+1` Firehose range and so wrote
/// two concatenated messages per file. This truncates each file to its first
/// message, refusing anything whose first message is not the block the path
/// names or whose second message is not that block's successor. Without
/// `write` it only reports what it would do; after a write the lock is stale
/// and must be regenerated against a new release.
pub fn normalize(root: &Path, lock_path: &Path, write: bool) -> Result<Report> {
    let lock = Lock::load(lock_path).map_err(|error| FixtureError(error.to_string()))?;
    let mut lines = vec![format!(
        "{:<48} {:>9} {:>9}  {:<24} {}",
        "path", "bytes", "first", "blocks", "sha256"
    )];
    let mut two_message = 0usize;
    let mut rewritten = 0usize;
    for asset in &lock.assets {
        let path = PathBuf::from(&asset.path);
        let expected = block_number_of(&path)?;
        let full = root.join(&path);
        let bytes = std::fs::read(&full)
            .map_err(|error| FixtureError(format!("{}: {error}", asset.path)))?;
        let found =
            boundary(&bytes).map_err(|error| FixtureError(format!("{}: {error}", asset.path)))?;
        if found.first_number != expected {
            return fail(format!(
                "{}: first message is block {} but the path names {expected}",
                asset.path, found.first_number
            ));
        }
        let Some(trailing) = found.trailing_number else {
            lines.push(format!(
                "{:<48} {:>9} {:>9}  {:<24} {}",
                asset.path,
                found.total,
                found.first_end,
                expected.to_string(),
                sha256(&bytes)
            ));
            continue;
        };
        if trailing != expected + 1 {
            return fail(format!(
                "{}: second message is block {trailing}, not {}",
                asset.path,
                expected + 1
            ));
        }
        two_message += 1;
        let first = &bytes[..found.first_end];
        let identity = block_identity(first)
            .map_err(|error| FixtureError(format!("{}: first message: {error}", asset.path)))?;
        if identity.number != expected || identity.hash.len() != 32 {
            return fail(format!(
                "{}: the first message does not stand alone as block {expected}",
                asset.path
            ));
        }
        lines.push(format!(
            "{:<48} {:>9} {:>9}  {:<24} {} -> {}",
            asset.path,
            found.total,
            found.first_end,
            format!("{expected} then {trailing}"),
            sha256(&bytes),
            sha256(first)
        ));
        if write {
            std::fs::write(&full, first)
                .map_err(|error| FixtureError(format!("{}: {error}", asset.path)))?;
            rewritten += 1;
        }
    }
    lines.push(if write {
        format!(
            "fixtures normalize: rewrote {rewritten} of {} locked blocks; regenerate the lock against a new release with `cargo xtask evidence lock`",
            lock.assets.len()
        )
    } else {
        format!(
            "fixtures normalize: {two_message} of {} locked blocks hold a second message (rerun with --write)",
            lock.assets.len()
        )
    });
    Ok(Report { lines })
}

/// Verify hydrated fixture blocks against the lock and each file's own header
/// (exactly one `sf.ethereum.type.v2.Block` per file, numbered by its path),
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
        let expected = block_number_of(path)?;
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

    fn varint_bytes(mut value: u64) -> Vec<u8> {
        let mut out = Vec::new();
        loop {
            let byte = (value & 0x7f) as u8;
            value >>= 7;
            if value == 0 {
                out.push(byte);
                return out;
            }
            out.push(byte | 0x80);
        }
    }

    /// A stand-in for one serialized `sf.ethereum.type.v2.Block`: `ver` (1),
    /// `hash` (2), `number` (3), `size` (4), and a length-delimited field 11,
    /// written in ascending field-number order the way protobuf does.
    fn synthetic_block(number: u64, hash_byte: u8) -> Vec<u8> {
        let mut bytes = vec![0x08, 0x03];
        bytes.extend([0x12, 0x20]);
        bytes.extend(std::iter::repeat_n(hash_byte, 32));
        bytes.push(0x18);
        bytes.extend(varint_bytes(number));
        bytes.extend([0x20, 0x2a]);
        bytes.extend([0x5a, 0x03, 1, 2, 3]);
        bytes
    }

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
    fn block_identity_accepts_one_message_and_rejects_two() {
        let one = synthetic_block(12369621, 0xab);
        assert_eq!(
            block_identity(&one).unwrap(),
            BlockIdentity {
                version: 3,
                hash: vec![0xab; 32],
                number: 12369621
            }
        );

        let mut two = one.clone();
        two.extend(synthetic_block(12369622, 0xcd));
        let error = block_identity(&two).unwrap_err().0;
        assert!(error.contains("(block 12369622)"), "{error}");
        assert!(error.contains(&format!("byte {}", one.len())), "{error}");
    }

    #[test]
    fn boundary_locates_the_second_message() {
        let one = synthetic_block(19470000, 1);
        assert_eq!(
            boundary(&one).unwrap(),
            Boundary {
                first_end: one.len(),
                total: one.len(),
                first_number: 19470000,
                trailing_number: None,
            }
        );

        let mut two = one.clone();
        two.extend(synthetic_block(19470001, 2));
        let found = boundary(&two).unwrap();
        assert_eq!(
            found,
            Boundary {
                first_end: one.len(),
                total: two.len(),
                first_number: 19470000,
                trailing_number: Some(19470001),
            }
        );
        assert_eq!(&two[..found.first_end], one.as_slice());
        assert_eq!(
            block_identity(&two[..found.first_end]).unwrap().number,
            19470000
        );

        let mut three = two.clone();
        three.extend(synthetic_block(19470002, 3));
        assert!(boundary(&three)
            .unwrap_err()
            .0
            .contains("more than two messages"));
        assert!(boundary(&one[..10]).is_err());
    }

    #[test]
    fn normalize_truncates_two_message_fixtures_to_the_first_block() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path();
        let directory = root.join("blocks/mainnet");
        std::fs::create_dir_all(&directory).unwrap();
        let first = synthetic_block(19470000, 1);
        let mut both = first.clone();
        both.extend(synthetic_block(19470001, 2));
        std::fs::write(directory.join("19470000.pb"), &both).unwrap();
        let paths = vec!["blocks/mainnet/19470000.pb".to_string()];
        let lock = evidence::lock_from_tree(
            root,
            "pinax-network/substreams-backfills",
            "block-fixtures-test",
            paths,
            Vec::new(),
        )
        .unwrap();
        let lock_path = root.join("blocks.lock.json");
        std::fs::write(&lock_path, lock.render()).unwrap();

        let dry = normalize(root, &lock_path, false).unwrap();
        assert!(
            dry.lines.last().unwrap().contains("1 of 1 locked blocks"),
            "{:?}",
            dry.lines
        );
        assert_eq!(std::fs::read(directory.join("19470000.pb")).unwrap(), both);

        let written = normalize(root, &lock_path, true).unwrap();
        assert!(
            written.lines.last().unwrap().contains("rewrote 1 of 1"),
            "{:?}",
            written.lines
        );
        assert_eq!(std::fs::read(directory.join("19470000.pb")).unwrap(), first);

        // Idempotent: a normalized fixture is left alone and reported as one block.
        let again = normalize(root, &lock_path, true).unwrap();
        assert!(again.lines.last().unwrap().contains("rewrote 0 of 1"));
        assert_eq!(std::fs::read(directory.join("19470000.pb")).unwrap(), first);
    }

    #[test]
    fn normalize_refuses_a_fixture_whose_blocks_do_not_match_the_path() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path();
        let directory = root.join("blocks/mainnet");
        std::fs::create_dir_all(&directory).unwrap();
        let mut both = synthetic_block(19470000, 1);
        both.extend(synthetic_block(19470007, 2));
        std::fs::write(directory.join("19470000.pb"), &both).unwrap();
        let lock = evidence::lock_from_tree(
            root,
            "pinax-network/substreams-backfills",
            "block-fixtures-test",
            vec!["blocks/mainnet/19470000.pb".to_string()],
            Vec::new(),
        )
        .unwrap();
        let lock_path = root.join("blocks.lock.json");
        std::fs::write(&lock_path, lock.render()).unwrap();
        let error = normalize(root, &lock_path, true).unwrap_err().0;
        assert!(
            error.contains("second message is block 19470007"),
            "{error}"
        );
        assert_eq!(std::fs::read(directory.join("19470000.pb")).unwrap(), both);
    }

    #[test]
    fn goldens_and_lock_in_repository_are_consistent_when_hydrated() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
        let lock = Lock::load(&root.join(BLOCKS_LOCK)).unwrap();
        assert_eq!(lock.release_tag, "block-fixtures-v2");
        assert!(lock.assets.iter().all(|a| a.asset.ends_with(".pb")));
        if evidence::check(&lock, &root).ok() {
            let report = check(&root).unwrap();
            assert!(report.lines.last().unwrap().contains("goldens verified"));
        }
    }
}
