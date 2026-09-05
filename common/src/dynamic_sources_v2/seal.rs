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
    publish_with_sync(building, output, chunk, parent, |path| {
        index::open_regular(path)?
            .sync_all()
            .map_err(|e| e.to_string())
    })
}

// Private injection point for durability failure tests; never a caller flag or
// public route around fsync. All payload syncs must succeed before READY exists.
fn publish_with_sync(
    building: &Path,
    output: &Path,
    chunk: &Chunk,
    parent: Option<&SealedChunk>,
    mut sync_payload: impl FnMut(&Path) -> Result<(), String>,
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
        sync_payload(&building.join(name))?;
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
    // Checking absence gives an early refusal; only the native no-replace
    // primitive closes the race with a directory created after this check.
    require_absent(output)?;
    rename_no_replace(building, output)?;
    if let Some(parent_dir) = output.parent() {
        File::open(parent_dir)
            .and_then(|f| f.sync_all())
            .map_err(|e| e.to_string())?;
    }
    SealedChunk::open(output, &chunk.descriptor_sha256)
}

/// Atomic filesystem promotion only, not validation or a sealing authority.
/// Callers must first validate and sync their full payload and metadata, then
/// sync the parent directory after this succeeds. Existing destinations of any
/// kind are never replaced, including an empty directory racing the caller.
pub fn rename_no_replace(from: &Path, to: &Path) -> Result<(), String> {
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    {
        rustix::fs::renameat_with(
            rustix::fs::CWD,
            from,
            rustix::fs::CWD,
            to,
            rustix::fs::RenameFlags::NOREPLACE,
        )
        .map_err(|e| e.to_string())
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        let _ = (from, to);
        Err("v2 atomic no-replace promotion is unsupported on this platform".into())
    }
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

#[cfg(test)]
mod durability_tests {
    use super::*;
    use crate::dynamic_sources_v2::{Block, SourceState, CONTRACT};

    #[test]
    fn each_payload_sync_failure_prevents_metadata_ready_and_promotion() {
        for failing in 0..3 {
            let root = tempfile::tempdir().unwrap();
            let building = root.path().join("chunk.building");
            let output = root.path().join("chunk.ready");
            fs::create_dir(&building).unwrap();
            let mut stream = b"BCF1\x01\0\0\0".to_vec();
            stream.extend(10u64.to_be_bytes());
            stream.extend([1; 32]);
            stream.extend(1u32.to_be_bytes());
            stream.push(42);
            fs::write(building.join(STREAM), &stream).unwrap();
            fs::write(building.join(CHECKPOINT), b"synthetic checkpoint").unwrap();
            fs::write(building.join(IDENTITIES), index::MAGIC).unwrap();
            let chunk = Chunk {
                contract: CONTRACT.into(),
                deployment: "synthetic".into(),
                network: "mainnet".into(),
                descriptor_sha256: "ab".repeat(32),
                root_start_block: 10,
                from: 10,
                to: 11,
                parent: None,
                stream: FilePin::for_bytes(&stream),
                checkpoint: FilePin::for_bytes(b"synthetic checkpoint"),
                before: SourceState::empty(),
                after: SourceState::empty(),
                blocks: vec![Block {
                    block_number: 10,
                    block_hash: "01".repeat(32),
                    payload_sha256: FilePin::for_bytes(&[42]).sha256,
                    sources: vec![],
                }],
            };
            let mut calls = Vec::new();
            let result = publish_with_sync(&building, &output, &chunk, None, |path| {
                calls.push(path.file_name().unwrap().to_owned());
                if calls.len() == failing + 1 {
                    return Err("injected payload fsync failure".into());
                }
                index::open_regular(path)?
                    .sync_all()
                    .map_err(|e| e.to_string())
            });
            assert!(result
                .err()
                .unwrap()
                .contains("injected payload fsync failure"));
            assert_eq!(
                calls,
                [STREAM, CHECKPOINT, IDENTITIES][..=failing]
                    .iter()
                    .map(std::ffi::OsString::from)
                    .collect::<Vec<_>>()
            );
            for name in [METADATA, MANIFEST, READY] {
                assert!(!building.join(name).exists());
            }
            assert!(!output.exists());
            assert_eq!(fs::read(building.join(STREAM)).unwrap(), stream);
        }
    }

    #[test]
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    fn atomic_no_replace_preserves_an_existing_empty_directory() {
        let root = tempfile::tempdir().unwrap();
        let from = root.path().join("staged");
        let to = root.path().join("raced.ready");
        fs::create_dir(&from).unwrap();
        fs::write(from.join("payload"), b"keep").unwrap();
        // Equivalent to a competitor creating this directory immediately after
        // the caller's final absence check. Ordinary rename would replace it.
        fs::create_dir(&to).unwrap();
        assert!(rename_no_replace(&from, &to).is_err());
        assert!(to.is_dir());
        assert_eq!(fs::read_dir(&to).unwrap().count(), 0);
        assert_eq!(fs::read(from.join("payload")).unwrap(), b"keep");
        let fresh = root.path().join("fresh.ready");
        rename_no_replace(&from, &fresh).unwrap();
        assert!(!from.exists());
        assert_eq!(fs::read(fresh.join("payload")).unwrap(), b"keep");
    }
}
