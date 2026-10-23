//! Complete-capture admission and virtual concatenation. Validate every raw
//! block and receipt before extraction, then reread the same open files and
//! verify their digests again before allowing a projection success marker.
use super::*;
use backfill_common::clock;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File},
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CaptureReceipt {
    pub schema: String,
    pub source_commit: String,
    pub binary_sha256: String,
    pub protobuf_type: String,
    pub from: u64,
    pub to_exclusive: u64,
    pub blocks: u64,
    pub first_parent_hash: String,
    pub last_hash: String,
    pub final_blocks_only: bool,
    pub server_eof: bool,
    pub raw_bcf1_bytes: u64,
    pub raw_bcf1_sha256: String,
    pub index_sha256: String,
    pub transport_reconnects: u64,
}
struct Part {
    file: File,
    receipt: CaptureReceipt,
}
pub struct CaptureSet {
    parts: Vec<Part>,
    pub from: u64,
    pub to_exclusive: u64,
    pub raw_bytes: u64,
    pub raw_sha256: String,
    pub receipts: Vec<CaptureReceipt>,
}
fn io(e: impl std::fmt::Display) -> crate::ReducerError {
    refuse(e.to_string())
}
fn open_regular(path: &Path) -> Result<File> {
    require(
        fs::symlink_metadata(path)
            .map_err(io)?
            .file_type()
            .is_file(),
        "capture input must be a regular file",
    )?;
    File::open(path).map_err(io)
}
fn hash_reader(reader: &mut impl Read) -> Result<String> {
    let mut hash = Sha256::new();
    let mut buf = [0; 65536];
    loop {
        let n = reader.read(&mut buf).map_err(io)?;
        if n == 0 {
            break;
        }
        hash.update(&buf[..n]);
    }
    Ok(hex::encode(hash.finalize()))
}
fn hex_hash(value: &str) -> Result<[u8; 32]> {
    crate::word(
        &hex::decode(
            value
                .strip_prefix("0x")
                .ok_or_else(|| refuse("capture hash lacks prefix"))?,
        )
        .map_err(io)?,
    )
}
fn pin(value: &str, len: usize) -> bool {
    value.len() == len
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
impl CaptureSet {
    pub fn open(paths: &[PathBuf], source_commit: &str, binary_sha256: &str) -> Result<Self> {
        require(
            !paths.is_empty() && pin(source_commit, 40) && pin(binary_sha256, 64),
            "invalid capture source/binary pins",
        )?;
        let mut parts = vec![];
        let mut previous = None;
        let mut next = INITIAL_BLOCK;
        let mut all_hash = Sha256::new();
        let mut total_bytes = 0;
        for path in paths {
            let receipt: CaptureReceipt =
                serde_json::from_reader(open_regular(&path.join("capture-success.json"))?)
                    .map_err(io)?;
            require(
                receipt.schema == "aerodrome-raw-firehose-capture/v1"
                    && receipt.source_commit == source_commit
                    && receipt.binary_sha256 == binary_sha256
                    && receipt.protobuf_type == "sf.ethereum.type.v2.Block"
                    && receipt.final_blocks_only
                    && receipt.server_eof,
                "capture receipt identity or completion mismatch",
            )?;
            require(
                receipt.from == next
                    && receipt.to_exclusive > receipt.from
                    && receipt.to_exclusive <= i32::MAX as u64
                    && receipt.blocks == receipt.to_exclusive - receipt.from,
                "capture ranges must be nonempty contiguous from deployment root",
            )?;
            require(
                pin(&receipt.raw_bcf1_sha256, 64) && pin(&receipt.index_sha256, 64),
                "invalid capture digest",
            )?;
            let first_parent = hex_hash(&receipt.first_parent_hash)?;
            let last_hash = hex_hash(&receipt.last_hash)?;
            require(
                first_parent != [0; 32]
                    && last_hash != [0; 32]
                    && previous.is_none_or(|p| p == first_parent),
                "capture receipt parent linkage mismatch",
            )?;
            let mut index_file = open_regular(&path.join("raw-firehose.index.jsonl"))?;
            require(
                hash_reader(&mut index_file)? == receipt.index_sha256,
                "capture index digest mismatch",
            )?;
            index_file.seek(SeekFrom::Start(0)).map_err(io)?;
            let mut index = BufReader::new(index_file).lines();
            let file = open_regular(&path.join("raw-firehose.bcf1"))?;
            require(
                file.metadata().map_err(io)?.len() == receipt.raw_bcf1_bytes,
                "capture length mismatch",
            )?;
            let mut input = BufReader::new(file);
            let mut digest = Sha256::new();
            let mut bytes = 0;
            for number in receipt.from..receipt.to_exclusive {
                let frame = clock::read_frame(&mut input, clock::MAX_PAYLOAD_LEN)
                    .map_err(io)?
                    .ok_or_else(|| refuse("capture early EOF"))?;
                require(
                    frame.kind == FrameKind::Observed
                        && frame.block_number == number
                        && !frame.payload.is_empty(),
                    "capture frame identity mismatch",
                )?;
                let raw = decode_raw(&frame.payload)?;
                let parent = crate::word(
                    &raw.header
                        .ok_or_else(|| refuse("raw block missing header"))?
                        .parent_hash,
                )?;
                require(
                    raw.number == number
                        && raw.hash.as_slice() == frame.block_hash
                        && parent != [0; 32]
                        && previous.is_none_or(|p| p == parent),
                    "capture protobuf identity/parent mismatch",
                )?;
                if number == receipt.from {
                    require(parent == first_parent, "capture first parent mismatch")?;
                }
                let row: serde_json::Value = serde_json::from_str(
                    &index
                        .next()
                        .ok_or_else(|| refuse("capture index early EOF"))?
                        .map_err(io)?,
                )
                .map_err(io)?;
                require(
                    row["block"].as_u64() == Some(number)
                        && row["hash"] == format!("0x{}", hex::encode(frame.block_hash))
                        && row["parent_hash"] == format!("0x{}", hex::encode(parent))
                        && row["protobuf_bytes"].as_u64() == Some(frame.payload.len() as u64)
                        && row["protobuf_sha256"] == hex::encode(Sha256::digest(&frame.payload))
                        && row["offset"].as_u64() == Some(bytes),
                    "capture index/frame mismatch",
                )?;
                let mut encoded = Vec::new();
                clock::write_frame(&mut encoded, &frame).map_err(io)?;
                digest.update(&encoded);
                all_hash.update(&encoded);
                bytes += encoded.len() as u64;
                previous = Some(frame.block_hash);
            }
            require(
                clock::read_frame(&mut input, clock::MAX_PAYLOAD_LEN)
                    .map_err(io)?
                    .is_none()
                    && index.next().is_none(),
                "capture has extra frames or index rows",
            )?;
            require(
                bytes == receipt.raw_bcf1_bytes
                    && hex::encode(digest.finalize()) == receipt.raw_bcf1_sha256
                    && previous == Some(last_hash),
                "capture stream digest/boundary mismatch",
            )?;
            let mut file = input.into_inner();
            file.seek(SeekFrom::Start(0)).map_err(io)?;
            next = receipt.to_exclusive;
            total_bytes += bytes;
            parts.push(Part { file, receipt });
        }
        let receipts = parts.iter().map(|p| p.receipt.clone()).collect();
        Ok(Self {
            parts,
            from: INITIAL_BLOCK,
            to_exclusive: next,
            raw_bytes: total_bytes,
            raw_sha256: hex::encode(all_hash.finalize()),
            receipts,
        })
    }
    /// Success means each already-validated file was reread in full, unchanged.
    /// A callback error stops immediately; callers must not write completion.
    pub fn for_each(mut self, mut consume: impl FnMut(Frame) -> Result<()>) -> Result<()> {
        for part in &mut self.parts {
            let mut input = BufReader::new(&mut part.file);
            let mut hash = Sha256::new();
            let mut count = 0;
            while let Some(frame) =
                clock::read_frame(&mut input, clock::MAX_PAYLOAD_LEN).map_err(io)?
            {
                let mut encoded = Vec::new();
                clock::write_frame(&mut encoded, &frame).map_err(io)?;
                hash.update(encoded);
                consume(frame)?;
                count += 1;
            }
            require(
                count == part.receipt.blocks
                    && hex::encode(hash.finalize()) == part.receipt.raw_bcf1_sha256,
                "capture changed after preflight",
            )?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn part(root: &Path, number: u64, hash: [u8; 32], parent: [u8; 32]) -> PathBuf {
        let path = root.join(number.to_string());
        fs::create_dir(&path).unwrap();
        let source = fs::read(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../aerodrome-slipstream-base/fixtures/blocks/base/13899663.pb"),
        )
        .unwrap();
        let mut raw = eth::Block::decode(source.as_slice()).unwrap();
        raw.number = number;
        raw.hash = hash.to_vec();
        raw.header.as_mut().unwrap().number = number;
        raw.header.as_mut().unwrap().parent_hash = parent.to_vec();
        raw.transaction_traces.clear();
        let payload = raw.encode_to_vec();
        let frame = Frame {
            kind: FrameKind::Observed,
            block_number: number,
            block_hash: hash,
            payload,
        };
        let mut bytes = vec![];
        clock::write_frame(&mut bytes, &frame).unwrap();
        let row = json!({"block":number,"hash":format!("0x{}",hex::encode(hash)),"parent_hash":format!("0x{}",hex::encode(parent)),"protobuf_bytes":frame.payload.len(),"protobuf_sha256":hex::encode(Sha256::digest(&frame.payload)),"offset":0});
        let index = format!("{}\n", serde_json::to_string(&row).unwrap());
        let receipt = CaptureReceipt {
            schema: "aerodrome-raw-firehose-capture/v1".into(),
            source_commit: "11".repeat(20),
            binary_sha256: "22".repeat(32),
            protobuf_type: "sf.ethereum.type.v2.Block".into(),
            from: number,
            to_exclusive: number + 1,
            blocks: 1,
            first_parent_hash: format!("0x{}", hex::encode(parent)),
            last_hash: format!("0x{}", hex::encode(hash)),
            final_blocks_only: true,
            server_eof: true,
            raw_bcf1_bytes: bytes.len() as u64,
            raw_bcf1_sha256: hex::encode(Sha256::digest(&bytes)),
            index_sha256: hex::encode(Sha256::digest(index.as_bytes())),
            transport_reconnects: 0,
        };
        fs::write(path.join("raw-firehose.bcf1"), bytes).unwrap();
        fs::write(path.join("raw-firehose.index.jsonl"), index).unwrap();
        fs::write(
            path.join("capture-success.json"),
            serde_json::to_vec(&receipt).unwrap(),
        )
        .unwrap();
        path
    }
    fn open(paths: &[PathBuf]) -> Result<CaptureSet> {
        CaptureSet::open(paths, &"11".repeat(20), &"22".repeat(32))
    }
    #[test]
    fn complete_disjoint_parts_join_only_with_exact_receipts_and_chain() {
        let dir = tempfile::tempdir().unwrap();
        let a = part(dir.path(), INITIAL_BLOCK, [1; 32], [3; 32]);
        let b = part(dir.path(), INITIAL_BLOCK + 1, [2; 32], [1; 32]);
        let set = open(&[a.clone(), b.clone()]).unwrap();
        assert_eq!(set.to_exclusive, INITIAL_BLOCK + 2);
        let mut reference = ReferenceExtractor::new(
            Cassette::from_json(
                br#"{"schema":"pinax.substreams-backfills.mapping-host.cassette/v1","entries":[]}"#,
            )
            .unwrap(),
            INITIAL_BLOCK + 2,
        )
        .unwrap();
        set.for_each(|frame| reference.process(frame).map(|_| ()))
            .unwrap();
        reference.finish().unwrap();
        assert!(open(&[b.clone(), a.clone()]).is_err());
        fs::remove_file(b.join("capture-success.json")).unwrap();
        assert!(open(&[a.clone(), b]).is_err());
        fs::write(a.join("raw-firehose.index.jsonl"), b"{}\n").unwrap();
        assert!(open(&[a]).is_err());
    }
    #[test]
    fn changes_after_preflight_and_callback_failures_never_complete() {
        use std::io::Write;
        let dir = tempfile::tempdir().unwrap();
        let a = part(dir.path(), INITIAL_BLOCK, [1; 32], [3; 32]);
        let set = open(std::slice::from_ref(&a)).unwrap();
        let mut file = fs::OpenOptions::new()
            .append(true)
            .open(a.join("raw-firehose.bcf1"))
            .unwrap();
        file.write_all(b"BCF1").unwrap();
        assert!(set.for_each(|_| Ok(())).is_err());
        let other = tempfile::tempdir().unwrap();
        let a = part(other.path(), INITIAL_BLOCK, [1; 32], [3; 32]);
        let set = open(&[a]).unwrap();
        assert!(set
            .for_each(|_| Err(refuse("consumer refused")))
            .unwrap_err()
            .0
            .contains("consumer refused"));
    }
    #[test]
    fn forged_clean_eof_wrong_binary_and_cross_part_fork_are_refused() {
        let dir = tempfile::tempdir().unwrap();
        let a = part(dir.path(), INITIAL_BLOCK, [1; 32], [3; 32]);
        let b = part(dir.path(), INITIAL_BLOCK + 1, [2; 32], [4; 32]);
        assert!(open(&[a.clone(), b])
            .unwrap_err_text()
            .contains("parent linkage"));
        assert!(
            CaptureSet::open(std::slice::from_ref(&a), &"11".repeat(20), &"ff".repeat(32)).is_err()
        );
        let path = a.join("capture-success.json");
        let mut r: CaptureReceipt = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        r.server_eof = false;
        fs::write(path, serde_json::to_vec(&r).unwrap()).unwrap();
        assert!(open(&[a]).is_err());
    }
    trait ErrorText {
        fn unwrap_err_text(self) -> String;
    }
    impl ErrorText for Result<CaptureSet> {
        fn unwrap_err_text(self) -> String {
            match self {
                Ok(_) => panic!("expected refusal"),
                Err(e) => e.0,
            }
        }
    }
}
