//! Fixed-width, strictly sorted unique source identities. Historical identities
//! stay on disk; lookup and merge use fixed-size buffers, not a historical set.
use super::{require, FilePin, SourceState};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs::{self, File},
    io::{BufReader, BufWriter, Read, Seek, SeekFrom, Write},
    path::Path,
};

pub const MAGIC: &[u8; 8] = b"BCDSIDX2";
pub const RECORD_BYTES: usize = 24;
pub type Identity = [u8; RECORD_BYTES];
const BUFFER: usize = 64 * 1024;

pub fn open_regular(path: &Path) -> Result<File, String> {
    require(
        fs::symlink_metadata(path)
            .map_err(|e| e.to_string())?
            .file_type()
            .is_file(),
        "source chunk artifact is not a regular file",
    )?;
    File::open(path).map_err(|e| e.to_string())
}

pub fn hash_file(path: &Path) -> Result<FilePin, String> {
    let mut input = open_regular(path)?;
    let mut h = Sha256::new();
    let mut bytes = 0;
    let mut buf = [0; BUFFER];
    loop {
        let n = input.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
        bytes += n as u64;
    }
    Ok(FilePin {
        bytes,
        sha256: hex::encode(h.finalize()),
    })
}

pub struct Index {
    file: File,
    state: SourceState,
}

impl Index {
    /// Validate all bytes and ordering before any caller may open its output.
    pub fn open(path: &Path, state: &SourceState) -> Result<Self, String> {
        state.validate()?;
        let mut file = open_regular(path)?;
        let mut input = BufReader::with_capacity(BUFFER, &mut file);
        let mut magic = [0; 8];
        input.read_exact(&mut magic).map_err(|e| e.to_string())?;
        require(&magic == MAGIC, "unsupported source identity index")?;
        let mut h = Sha256::new();
        h.update(magic);
        let mut previous = None;
        let mut count = 0;
        while let Some(key) = read_key(&mut input)? {
            if let Some(old) = previous {
                require(old < key, "source identity index is not sorted and unique")?;
            }
            require(key[0] < 128, "negative source identity template index")?;
            h.update(key);
            previous = Some(key);
            count += 1;
        }
        require(
            count == state.order.count && hex::encode(h.finalize()) == state.identities.sha256,
            "source identity index digest/count mismatch",
        )?;
        Ok(Self {
            file,
            state: state.clone(),
        })
    }

    pub fn contains(&mut self, key: &Identity) -> Result<bool, String> {
        let (mut lower, mut upper) = (0, self.state.order.count);
        let mut found = [0; RECORD_BYTES];
        while lower < upper {
            let mid = lower + (upper - lower) / 2;
            self.file
                .seek(SeekFrom::Start(
                    MAGIC.len() as u64 + mid * RECORD_BYTES as u64,
                ))
                .map_err(|e| e.to_string())?;
            self.file
                .read_exact(&mut found)
                .map_err(|e| e.to_string())?;
            match found.cmp(key) {
                std::cmp::Ordering::Less => lower = mid + 1,
                std::cmp::Ordering::Greater => upper = mid,
                std::cmp::Ordering::Equal => return Ok(true),
            }
        }
        Ok(false)
    }
}

/// Merge only the current bounded chunk's sorted identities with an immutable
/// predecessor. The predecessor is checked before opening `output`, and hashed
/// again while merging so changed input cannot produce a valid successor.
pub fn merge(
    output: &Path,
    predecessor: Option<(&Path, &SourceState)>,
    new: &BTreeSet<Identity>,
) -> Result<FilePin, String> {
    for key in new {
        require(key[0] < 128, "negative source identity template index")?;
    }
    let mut previous = predecessor.map(|(p, s)| Index::open(p, s)).transpose()?;
    if let Some(index) = previous.as_mut() {
        for key in new {
            require(
                !index.contains(key)?,
                "source identity already exists in predecessor",
            )?;
        }
        index
            .file
            .seek(SeekFrom::Start(MAGIC.len() as u64))
            .map_err(|e| e.to_string())?;
    }
    let file = File::options()
        .write(true)
        .create_new(true)
        .open(output)
        .map_err(|e| e.to_string())?;
    let mut out = BufWriter::with_capacity(BUFFER, file);
    let mut h = Sha256::new();
    out.write_all(MAGIC).map_err(|e| e.to_string())?;
    h.update(MAGIC);
    let mut old_hash = Sha256::new();
    old_hash.update(MAGIC);
    let mut old_count = 0;
    let mut new_iter = new.iter().peekable();
    let mut old_reader = previous
        .as_mut()
        .map(|p| BufReader::with_capacity(BUFFER, &mut p.file));
    let mut old = read_optional(&mut old_reader)?;
    let mut count = 0;
    while old.is_some() || new_iter.peek().is_some() {
        let take_old = match (old.as_ref(), new_iter.peek()) {
            (Some(a), Some(b)) => {
                require(a != *b, "source identity became duplicated during merge")?;
                a < *b
            }
            (Some(_), None) => true,
            _ => false,
        };
        let key = if take_old {
            let key = old.take().expect("present old record");
            old_hash.update(key);
            old_count += 1;
            old = read_optional(&mut old_reader)?;
            key
        } else {
            *new_iter.next().expect("present new record")
        };
        out.write_all(&key).map_err(|e| e.to_string())?;
        h.update(key);
        count += 1;
    }
    if let Some((_, state)) = predecessor {
        require(
            old_count == state.order.count
                && hex::encode(old_hash.finalize()) == state.identities.sha256,
            "predecessor identity index changed during merge",
        )?;
    }
    out.flush().map_err(|e| e.to_string())?;
    out.get_ref().sync_all().map_err(|e| e.to_string())?;
    Ok(FilePin {
        bytes: MAGIC.len() as u64 + count * RECORD_BYTES as u64,
        sha256: hex::encode(h.finalize()),
    })
}

fn read_optional<R: Read>(input: &mut Option<R>) -> Result<Option<Identity>, String> {
    match input {
        Some(reader) => read_key(reader),
        None => Ok(None),
    }
}

fn read_key(input: &mut impl Read) -> Result<Option<Identity>, String> {
    let mut key = [0; RECORD_BYTES];
    if input.read(&mut key[..1]).map_err(|e| e.to_string())? == 0 {
        return Ok(None);
    }
    input.read_exact(&mut key[1..]).map_err(|e| e.to_string())?;
    Ok(Some(key))
}
