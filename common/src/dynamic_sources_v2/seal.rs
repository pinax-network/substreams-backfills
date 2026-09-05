//! The verified immutable direct predecessor is the continuation trust boundary.
//! Older chain receipts are retained separately; loading a child does not claim
//! to rehash all historical ancestors or perform a graft-state audit.
use super::{index, require, Chunk, FilePin, Parent, MAX_BYTES};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs::{self, File},
    io::{Read, Write},
    path::{Path, PathBuf},
};

pub const FORMAT: &str = "pinax.graph.backfill.source-chunk/v2";
pub const STREAM: &str = "blocks.bcf1";
pub const METADATA: &str = "data-sources.json";
pub const CHECKPOINT: &str = "host-checkpoint.json";
pub const IDENTITIES: &str = "source-identities.bin";
pub const MANIFEST: &str = "manifest.json";
pub const READY: &str = "READY.json";
const FILES: [&str; 6] = [STREAM, METADATA, CHECKPOINT, IDENTITIES, MANIFEST, READY];

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub stream: FilePin,
    pub metadata: FilePin,
    pub checkpoint: FilePin,
    pub identities: FilePin,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Ready {
    pub format: String,
    pub manifest: FilePin,
}

pub struct SealedChunk {
    pub directory: PathBuf,
    pub chunk: Chunk,
    pub manifest: Manifest,
    pub manifest_pin: FilePin,
    pub seal_pin: FilePin,
}

impl SealedChunk {
    pub fn open(directory: &Path, descriptor: &str) -> Result<Self, String> {
        require(
            directory.extension().and_then(|s| s.to_str()) == Some("ready"),
            "source chunk predecessor must be a promoted .ready directory",
        )?;
        Self::inspect(directory, descriptor)
    }

    fn inspect(directory: &Path, descriptor: &str) -> Result<Self, String> {
        require(
            fs::symlink_metadata(directory)
                .map_err(|e| e.to_string())?
                .file_type()
                .is_dir(),
            "source chunk must be a real directory, not a symlink",
        )?;
        let names: BTreeSet<_> = fs::read_dir(directory)
            .map_err(|e| e.to_string())?
            .map(|entry| entry.map(|e| e.file_name()).map_err(|e| e.to_string()))
            .collect::<Result<_, _>>()?;
        let expected: BTreeSet<_> = FILES.iter().map(std::ffi::OsString::from).collect();
        require(
            names == expected,
            "source chunk inventory is incomplete or has extra files",
        )?;
        let ready_bytes = read_bounded(&directory.join(READY), 4096)?;
        let ready: Ready = serde_json::from_slice(&ready_bytes).map_err(|e| e.to_string())?;
        require(ready.format == FORMAT, "unsupported source chunk seal")?;
        require(
            serde_json::to_vec(&ready).map_err(|e| e.to_string())? == ready_bytes,
            "source chunk seal is not canonical",
        )?;
        let manifest_bytes = read_bounded(&directory.join(MANIFEST), 16 * 1024)?;
        let manifest_pin = FilePin::for_bytes(&manifest_bytes);
        require(
            ready.manifest == manifest_pin,
            "source chunk manifest seal mismatch",
        )?;
        let manifest: Manifest =
            serde_json::from_slice(&manifest_bytes).map_err(|e| e.to_string())?;
        require(
            manifest.format == FORMAT,
            "unsupported source chunk manifest",
        )?;
        for (name, pin) in [
            (STREAM, &manifest.stream),
            (METADATA, &manifest.metadata),
            (CHECKPOINT, &manifest.checkpoint),
            (IDENTITIES, &manifest.identities),
        ] {
            require(
                FilePin::read(&directory.join(name))? == *pin,
                "source chunk artifact pin mismatch",
            )?;
        }
        let chunk = Chunk::parse(
            &read_bounded(&directory.join(METADATA), MAX_BYTES)?,
            descriptor,
        )?;
        require(
            chunk.stream == manifest.stream
                && chunk.checkpoint == manifest.checkpoint
                && chunk.after.identities == manifest.identities,
            "source chunk metadata/manifest mismatch",
        )?;
        index::Index::open(&directory.join(IDENTITIES), &chunk.after)?;
        verify_stream(&directory.join(STREAM), &chunk)?;
        Ok(Self {
            directory: directory.to_owned(),
            chunk,
            manifest,
            manifest_pin,
            seal_pin: FilePin::for_bytes(&ready_bytes),
        })
    }

    pub fn parent(&self) -> Parent {
        Parent {
            boundary: self.chunk.boundary(),
            seal: self.seal_pin.clone(),
            manifest: self.manifest_pin.clone(),
            stream: self.manifest.stream.clone(),
            metadata: self.manifest.metadata.clone(),
            checkpoint: self.manifest.checkpoint.clone(),
        }
    }

    pub fn verify_unchanged(&self) -> Result<(), String> {
        let now = Self::open(&self.directory, &self.chunk.descriptor_sha256)?;
        require(
            now.manifest_pin == self.manifest_pin && now.seal_pin == self.seal_pin,
            "source chunk predecessor changed after preflight",
        )
    }
}

pub fn read_bounded(path: &Path, max: usize) -> Result<Vec<u8>, String> {
    let input = index::open_regular(path)?;
    require(
        input.metadata().map_err(|e| e.to_string())?.len() <= max as u64,
        "source metadata file exceeds size bound",
    )?;
    let mut bytes = Vec::new();
    input
        .take(max as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    require(
        bytes.len() <= max,
        "source metadata file grew beyond size bound",
    )?;
    Ok(bytes)
}

/// Refuse a changed/truncated/noncanonical envelope, including empty blocks.
pub fn verify_stream(path: &Path, chunk: &Chunk) -> Result<(), String> {
    let mut input = index::open_regular(path)?;
    let mut h = Sha256::new();
    let mut bytes = 0;
    let mut offset = 0;
    loop {
        let mut header = [0; 52];
        if input.read(&mut header[..1]).map_err(|e| e.to_string())? == 0 {
            break;
        }
        input
            .read_exact(&mut header[1..])
            .map_err(|e| e.to_string())?;
        require(
            &header[..8] == b"BCF1\x01\0\0\0",
            "source chunk requires observed BCF1 frames",
        )?;
        let size = u32::from_be_bytes(header[48..].try_into().expect("four bytes")) as usize;
        require(size <= MAX_BYTES, "source chunk frame exceeds size bound")?;
        let mut payload = vec![0; size];
        input.read_exact(&mut payload).map_err(|e| e.to_string())?;
        let number = u64::from_be_bytes(header[8..16].try_into().expect("eight bytes"));
        chunk.verify_frame(offset, number, &header[16..48], &payload)?;
        offset += 1;
        h.update(header);
        h.update(&payload);
        bytes += 52 + size as u64;
    }
    require(
        offset == chunk.blocks.len(),
        "source chunk stream coverage mismatch",
    )?;
    require(
        chunk.stream
            == FilePin {
                bytes,
                sha256: hex::encode(h.finalize()),
            },
        "source chunk stream digest mismatch",
    )
}

/// Files are written only inside a fresh staging directory. READY is last and
/// the enclosing directory is promoted atomically; no existing target is
/// removed. Callers must create that staging directory without replacing it.
pub fn publish(
    building: &Path,
    output: &Path,
    chunk: &Chunk,
    parent: Option<&SealedChunk>,
) -> Result<SealedChunk, String> {
    require(
        output.extension().and_then(|s| s.to_str()) == Some("ready"),
        "source chunk output must end in .ready",
    )?;
    require_absent(output)?;
    chunk.validate(&chunk.descriptor_sha256)?;
    match (chunk.parent.as_ref(), parent) {
        (Some(_), Some(parent)) => {
            parent.verify_unchanged()?;
            chunk.require_parent(parent)?;
        }
        (None, None) => {}
        _ => return Err("source chunk has no verified predecessor".into()),
    }
    let names: BTreeSet<_> = fs::read_dir(building)
        .map_err(|e| e.to_string())?
        .map(|entry| entry.map(|e| e.file_name()).map_err(|e| e.to_string()))
        .collect::<Result<_, _>>()?;
    let expected: BTreeSet<_> = [STREAM, CHECKPOINT, IDENTITIES]
        .iter()
        .map(std::ffi::OsString::from)
        .collect();
    require(
        names == expected,
        "source chunk staging inventory is incomplete or has extra files",
    )?;
    for (name, pin) in [
        (STREAM, &chunk.stream),
        (CHECKPOINT, &chunk.checkpoint),
        (IDENTITIES, &chunk.after.identities),
    ] {
        require(
            FilePin::read(&building.join(name))? == *pin,
            "source chunk staging artifact pin mismatch",
        )?;
    }
    index::Index::open(&building.join(IDENTITIES), &chunk.after)?;
    verify_stream(&building.join(STREAM), chunk)?;
    let metadata = serde_json::to_vec(chunk).map_err(|e| e.to_string())?;
    require(
        metadata.len() <= MAX_BYTES,
        "v2 source chunk exceeds 16 MiB",
    )?;
    write_new(&building.join(METADATA), &metadata)?;
    let manifest = Manifest {
        format: FORMAT.into(),
        stream: chunk.stream.clone(),
        metadata: FilePin::for_bytes(&metadata),
        checkpoint: chunk.checkpoint.clone(),
        identities: chunk.after.identities.clone(),
    };
    let encoded = serde_json::to_vec(&manifest).map_err(|e| e.to_string())?;
    write_new(&building.join(MANIFEST), &encoded)?;
    let ready = Ready {
        format: FORMAT.into(),
        manifest: FilePin::for_bytes(&encoded),
    };
    write_new(
        &building.join(READY),
        &serde_json::to_vec(&ready).map_err(|e| e.to_string())?,
    )?;
    // Validate our own sealed inventory before any path can claim completion.
    SealedChunk::inspect(building, &chunk.descriptor_sha256)?;
    File::open(building)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    // The production caller owns a fresh unique sibling target. A rename must
    // never be used to repair/remove an existing directory.
    require_absent(output)?;
    fs::rename(building, output).map_err(|e| e.to_string())?;
    if let Some(parent_dir) = output.parent() {
        File::open(parent_dir)
            .and_then(|f| f.sync_all())
            .map_err(|e| e.to_string())?;
    }
    SealedChunk::open(output, &chunk.descriptor_sha256)
}

fn require_absent(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.to_string()),
        Ok(_) => Err("source chunk target already exists".into()),
    }
}

pub fn write_new(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = File::options()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|e| e.to_string())
}
