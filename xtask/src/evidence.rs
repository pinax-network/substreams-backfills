//! Content-addressed evidence assets.
//!
//! Large generated contract blobs are stored as immutable GitHub release
//! assets instead of tracked files. `evidence-assets.lock.json` binds every
//! externalized path to its release tag, asset name, exact byte length, and
//! SHA-256. Everything here fails closed: a byte is promoted into the working
//! tree only after its length and digest match the lock.

use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const LOCK_SCHEMA: &str = "pinax.substreams-backfills.evidence-assets/v1";
pub const DEFAULT_LOCK_PATH: &str = "evidence-assets.lock.json";

#[derive(Debug)]
pub enum EvidenceError {
    Io { path: PathBuf, source: io::Error },
    Lock(String),
    NotFetched { path: PathBuf },
    Mismatch { path: PathBuf, detail: String },
    Fetch { asset: String, detail: String },
    Release(String),
}

impl fmt::Display for EvidenceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            EvidenceError::Io { path, source } => {
                write!(f, "io error at {}: {source}", path.display())
            }
            EvidenceError::Lock(detail) => write!(f, "invalid evidence lock: {detail}"),
            EvidenceError::NotFetched { path } => write!(
                f,
                "evidence blob not fetched: {} (run `cargo xtask evidence fetch`)",
                path.display()
            ),
            EvidenceError::Mismatch { path, detail } => {
                write!(f, "evidence blob mismatch: {}: {detail}", path.display())
            }
            EvidenceError::Fetch { asset, detail } => {
                write!(f, "fetch failed for {asset}: {detail}")
            }
            EvidenceError::Release(detail) => write!(f, "release audit failed: {detail}"),
        }
    }
}

impl std::error::Error for EvidenceError {}

pub type Result<T> = std::result::Result<T, EvidenceError>;

fn io_err(path: &Path, source: io::Error) -> EvidenceError {
    EvidenceError::Io {
        path: path.to_path_buf(),
        source,
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lock {
    pub schema: String,
    pub repository: String,
    pub release_tag: String,
    pub assets: Vec<Asset>,
    /// In-tree contract files whose bytes are pinned but not externalized.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tracked: Vec<Tracked>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Tracked {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Asset {
    pub path: String,
    pub asset: String,
    pub bytes: u64,
    pub sha256: String,
}

impl Asset {
    /// Content-addressed asset name: `sha256-<digest><extension of path>`.
    /// The extension is kept so a release listing stays readable and viewers
    /// pick a sensible content type; identity is the digest alone.
    pub fn expected_asset_name_for(path: &str, sha256: &str) -> String {
        let extension = Path::new(path)
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| format!(".{e}"))
            .unwrap_or_default();
        format!("sha256-{sha256}{extension}")
    }
}

impl Lock {
    pub fn parse(text: &str) -> Result<Lock> {
        let lock: Lock =
            serde_json::from_str(text).map_err(|e| EvidenceError::Lock(e.to_string()))?;
        lock.validate()?;
        Ok(lock)
    }

    pub fn load(path: &Path) -> Result<Lock> {
        let text = fs::read_to_string(path).map_err(|e| io_err(path, e))?;
        Lock::parse(&text)
    }

    pub fn render(&self) -> String {
        let mut out = serde_json::to_string_pretty(self).expect("lock serializes");
        out.push('\n');
        out
    }

    pub fn validate(&self) -> Result<()> {
        if self.schema != LOCK_SCHEMA {
            return Err(EvidenceError::Lock(format!(
                "schema must be {LOCK_SCHEMA}, got {}",
                self.schema
            )));
        }
        let repo_ok = self.repository.split('/').filter(|s| !s.is_empty()).count() == 2
            && self
                .repository
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '/'));
        if !repo_ok {
            return Err(EvidenceError::Lock(format!(
                "repository must be owner/name, got {}",
                self.repository
            )));
        }
        if self.release_tag.is_empty()
            || !self
                .release_tag
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        {
            return Err(EvidenceError::Lock(format!(
                "release_tag has invalid characters: {}",
                self.release_tag
            )));
        }
        if self.assets.is_empty() {
            return Err(EvidenceError::Lock("assets must not be empty".into()));
        }
        let mut paths = BTreeSet::new();
        let mut names = BTreeSet::new();
        let mut previous: Option<&str> = None;
        for asset in &self.assets {
            validate_relative_path(&asset.path)?;
            if asset.bytes == 0 {
                return Err(EvidenceError::Lock(format!(
                    "{}: bytes must be positive",
                    asset.path
                )));
            }
            if asset.sha256.len() != 64
                || !asset
                    .sha256
                    .chars()
                    .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
            {
                return Err(EvidenceError::Lock(format!(
                    "{}: sha256 must be 64 lowercase hex characters",
                    asset.path
                )));
            }
            let expected = Asset::expected_asset_name_for(&asset.path, &asset.sha256);
            if asset.asset != expected {
                return Err(EvidenceError::Lock(format!(
                    "{}: asset name must be content-addressed {expected}, got {}",
                    asset.path, asset.asset
                )));
            }
            if !paths.insert(asset.path.as_str()) {
                return Err(EvidenceError::Lock(format!(
                    "duplicate path {}",
                    asset.path
                )));
            }
            if !names.insert(asset.asset.as_str()) {
                return Err(EvidenceError::Lock(format!(
                    "duplicate asset {}",
                    asset.asset
                )));
            }
            if let Some(prev) = previous {
                if prev >= asset.path.as_str() {
                    return Err(EvidenceError::Lock(format!(
                        "assets must be sorted by path; {} follows {prev}",
                        asset.path
                    )));
                }
            }
            previous = Some(asset.path.as_str());
        }
        let mut previous_tracked: Option<&str> = None;
        for tracked in &self.tracked {
            validate_relative_path(&tracked.path)?;
            if tracked.bytes == 0 {
                return Err(EvidenceError::Lock(format!(
                    "{}: bytes must be positive",
                    tracked.path
                )));
            }
            if tracked.sha256.len() != 64
                || !tracked
                    .sha256
                    .chars()
                    .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
            {
                return Err(EvidenceError::Lock(format!(
                    "{}: sha256 must be 64 lowercase hex characters",
                    tracked.path
                )));
            }
            if paths.contains(tracked.path.as_str()) {
                return Err(EvidenceError::Lock(format!(
                    "{} is both externalized and tracked",
                    tracked.path
                )));
            }
            if let Some(prev) = previous_tracked {
                if prev >= tracked.path.as_str() {
                    return Err(EvidenceError::Lock(format!(
                        "tracked must be sorted by unique path; {} follows {prev}",
                        tracked.path
                    )));
                }
            }
            previous_tracked = Some(tracked.path.as_str());
        }
        Ok(())
    }
}

fn validate_relative_path(path: &str) -> Result<()> {
    let p = Path::new(path);
    if path.is_empty() || p.is_absolute() || path.contains('\\') {
        return Err(EvidenceError::Lock(format!(
            "path must be relative and forward-slash: {path}"
        )));
    }
    for component in p.components() {
        match component {
            Component::Normal(_) => {}
            _ => {
                return Err(EvidenceError::Lock(format!(
                    "path contains a non-normal component: {path}"
                )))
            }
        }
    }
    Ok(())
}

/// Streaming SHA-256 plus byte count of a file.
pub fn digest_file(path: &Path) -> Result<(u64, String)> {
    let mut file = fs::File::open(path).map_err(|e| io_err(path, e))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 1 << 16];
    let mut total = 0u64;
    loop {
        let read = file.read(&mut buffer).map_err(|e| io_err(path, e))?;
        if read == 0 {
            break;
        }
        total += read as u64;
        hasher.update(&buffer[..read]);
    }
    Ok((total, hex::encode(hasher.finalize())))
}

fn verify_file(path: &Path, asset: &Asset) -> Result<()> {
    let (bytes, sha256) = digest_file(path)?;
    if bytes != asset.bytes {
        return Err(EvidenceError::Mismatch {
            path: path.to_path_buf(),
            detail: format!("expected {} bytes, found {bytes}", asset.bytes),
        });
    }
    if sha256 != asset.sha256 {
        return Err(EvidenceError::Mismatch {
            path: path.to_path_buf(),
            detail: format!("expected sha256 {}, found {sha256}", asset.sha256),
        });
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Verified,
    Missing,
    Mismatch,
}

pub struct CheckReport {
    pub rows: Vec<(String, Status, String)>,
}

impl CheckReport {
    pub fn ok(&self) -> bool {
        self.rows.iter().all(|(_, s, _)| *s == Status::Verified)
    }
}

/// Verify every locked path in `root`; never touches the network or cache.
pub fn check(lock: &Lock, root: &Path) -> CheckReport {
    let mut rows = Vec::with_capacity(lock.assets.len() + lock.tracked.len());
    for asset in &lock.assets {
        let path = root.join(&asset.path);
        let row = if !path.is_file() {
            let e = EvidenceError::NotFetched {
                path: PathBuf::from(&asset.path),
            };
            (asset.path.clone(), Status::Missing, e.to_string())
        } else {
            match verify_file(&path, asset) {
                Ok(()) => (
                    asset.path.clone(),
                    Status::Verified,
                    format!("{} bytes", asset.bytes),
                ),
                Err(e) => (asset.path.clone(), Status::Mismatch, e.to_string()),
            }
        };
        rows.push(row);
    }
    for tracked in &lock.tracked {
        let asset = Asset {
            path: tracked.path.clone(),
            asset: String::new(),
            bytes: tracked.bytes,
            sha256: tracked.sha256.clone(),
        };
        let path = root.join(&tracked.path);
        let row = if !path.is_file() {
            (
                tracked.path.clone(),
                Status::Missing,
                format!("tracked contract missing: {}", tracked.path),
            )
        } else {
            match verify_file(&path, &asset) {
                Ok(()) => (
                    tracked.path.clone(),
                    Status::Verified,
                    format!("{} bytes (tracked)", tracked.bytes),
                ),
                Err(e) => (tracked.path.clone(), Status::Mismatch, e.to_string()),
            }
        };
        rows.push(row);
    }
    CheckReport { rows }
}

/// Source of asset bytes. Implementations stream the named release asset into
/// `dest`; they never verify, the caller does.
pub trait Fetcher {
    fn fetch(&self, lock: &Lock, asset: &Asset, dest: &mut dyn Write) -> Result<()>;
}

/// Local directory fetcher used by tests and offline mirrors: assets are files
/// named by their content-addressed asset name.
pub struct DirectoryFetcher {
    pub directory: PathBuf,
}

impl Fetcher for DirectoryFetcher {
    fn fetch(&self, _lock: &Lock, asset: &Asset, dest: &mut dyn Write) -> Result<()> {
        let source = self.directory.join(&asset.asset);
        let mut file = fs::File::open(&source).map_err(|e| EvidenceError::Fetch {
            asset: asset.asset.clone(),
            detail: format!("{}: {e}", source.display()),
        })?;
        io::copy(&mut file, dest).map_err(|e| EvidenceError::Fetch {
            asset: asset.asset.clone(),
            detail: e.to_string(),
        })?;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    AlreadyPresent,
    FromCache,
    Downloaded,
}

pub struct FetchOptions<'a> {
    pub cache_dir: &'a Path,
    pub offline: bool,
}

/// Checksum-keyed cache path: `<cache_dir>/sha256/<hex>`.
pub fn cache_path(cache_dir: &Path, asset: &Asset) -> PathBuf {
    cache_dir.join("sha256").join(&asset.sha256)
}

fn write_atomic_from_temp(temp: tempfile::NamedTempFile, dest: &Path) -> Result<()> {
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).map_err(|e| io_err(parent, e))?;
    }
    temp.persist(dest).map_err(|e| io_err(dest, e.error))?;
    Ok(())
}

fn copy_verified(source: &Path, dest: &Path, asset: &Asset) -> Result<()> {
    let parent = dest.parent().unwrap_or(Path::new("."));
    fs::create_dir_all(parent).map_err(|e| io_err(parent, e))?;
    let mut temp = tempfile::NamedTempFile::new_in(parent).map_err(|e| io_err(parent, e))?;
    let mut input = fs::File::open(source).map_err(|e| io_err(source, e))?;
    io::copy(&mut input, &mut temp).map_err(|e| io_err(dest, e))?;
    verify_file(temp.path(), asset)?;
    write_atomic_from_temp(temp, dest)
}

/// Ensure one asset is present and verified in `root`, using the cache and
/// then the fetcher. Every promotion goes through a temporary file that is
/// verified before rename; a cache entry that fails verification is deleted.
pub fn ensure_asset(
    lock: &Lock,
    asset: &Asset,
    root: &Path,
    fetcher: &dyn Fetcher,
    options: &FetchOptions,
) -> Result<Outcome> {
    let target = root.join(&asset.path);
    if target.is_file() && verify_file(&target, asset).is_ok() {
        return Ok(Outcome::AlreadyPresent);
    }
    let cached = cache_path(options.cache_dir, asset);
    if cached.is_file() {
        match verify_file(&cached, asset) {
            Ok(()) => {
                copy_verified(&cached, &target, asset)?;
                return Ok(Outcome::FromCache);
            }
            Err(_) => {
                fs::remove_file(&cached).map_err(|e| io_err(&cached, e))?;
            }
        }
    }
    if options.offline {
        return Err(EvidenceError::NotFetched {
            path: PathBuf::from(&asset.path),
        });
    }
    let cache_parent = cached.parent().unwrap_or(options.cache_dir);
    fs::create_dir_all(cache_parent).map_err(|e| io_err(cache_parent, e))?;
    let mut temp =
        tempfile::NamedTempFile::new_in(cache_parent).map_err(|e| io_err(cache_parent, e))?;
    fetcher.fetch(lock, asset, &mut temp)?;
    temp.flush().map_err(|e| io_err(temp.path(), e))?;
    verify_file(temp.path(), asset).map_err(|e| match e {
        EvidenceError::Mismatch { detail, .. } => EvidenceError::Fetch {
            asset: asset.asset.clone(),
            detail,
        },
        other => other,
    })?;
    write_atomic_from_temp(temp, &cached)?;
    copy_verified(&cached, &target, asset)?;
    Ok(Outcome::Downloaded)
}

pub fn fetch_all(
    lock: &Lock,
    root: &Path,
    fetcher: &dyn Fetcher,
    options: &FetchOptions,
) -> Result<Vec<(String, Outcome)>> {
    let mut outcomes = Vec::with_capacity(lock.assets.len());
    for asset in &lock.assets {
        let outcome = ensure_asset(lock, asset, root, fetcher, options)?;
        outcomes.push((asset.path.clone(), outcome));
    }
    Ok(outcomes)
}

/// Build lock entries from the working tree for every path in `paths`.
pub fn lock_from_tree(
    root: &Path,
    repository: &str,
    release_tag: &str,
    mut paths: Vec<String>,
    mut tracked_paths: Vec<String>,
) -> Result<Lock> {
    tracked_paths.sort();
    let mut tracked = Vec::with_capacity(tracked_paths.len());
    for path in tracked_paths {
        validate_relative_path(&path)?;
        let (bytes, sha256) = digest_file(&root.join(&path))?;
        tracked.push(Tracked {
            path,
            bytes,
            sha256,
        });
    }
    paths.sort();
    let mut assets = Vec::with_capacity(paths.len());
    for path in paths {
        validate_relative_path(&path)?;
        let (bytes, sha256) = digest_file(&root.join(&path))?;
        let asset = Asset::expected_asset_name_for(&path, &sha256);
        assets.push(Asset {
            path,
            asset,
            bytes,
            sha256,
        });
    }
    let lock = Lock {
        schema: LOCK_SCHEMA.into(),
        repository: repository.into(),
        release_tag: release_tag.into(),
        assets,
        tracked,
    };
    lock.validate()?;
    Ok(lock)
}

/// Compare the set of `(name, size)` pairs published on the release with the
/// lock. Extra, missing, or differently sized assets fail.
pub fn audit_release_assets(lock: &Lock, published: &[(String, u64)]) -> Result<()> {
    let expected: BTreeSet<(String, u64)> = lock
        .assets
        .iter()
        .map(|a| (a.asset.clone(), a.bytes))
        .collect();
    let found: BTreeSet<(String, u64)> = published.iter().cloned().collect();
    let missing: Vec<_> = expected.difference(&found).collect();
    let extra: Vec<_> = found.difference(&expected).collect();
    if missing.is_empty() && extra.is_empty() {
        return Ok(());
    }
    let mut detail = String::new();
    for (name, size) in missing {
        detail.push_str(&format!("missing on release: {name} ({size} bytes); "));
    }
    for (name, size) in extra {
        detail.push_str(&format!(
            "unlocked asset on release: {name} ({size} bytes); "
        ));
    }
    Err(EvidenceError::Release(
        detail.trim_end_matches("; ").to_string(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sha(bytes: &[u8]) -> String {
        hex::encode(Sha256::digest(bytes))
    }

    fn lock_for(root: &Path, files: &[(&str, &[u8])]) -> Lock {
        for (path, bytes) in files {
            let p = root.join(path);
            fs::create_dir_all(p.parent().unwrap()).unwrap();
            fs::write(&p, bytes).unwrap();
        }
        lock_from_tree(
            root,
            "pinax-network/substreams-backfills",
            "evidence-assets-v1",
            files.iter().map(|(p, _)| p.to_string()).collect(),
            Vec::new(),
        )
        .unwrap()
    }

    #[test]
    fn lock_round_trips_and_is_sorted() {
        let dir = tempfile::tempdir().unwrap();
        let lock = lock_for(
            dir.path(),
            &[
                ("b/contract.json", b"{\"b\":1}"),
                ("a/contract.json", b"{\"a\":1}"),
            ],
        );
        assert_eq!(lock.assets[0].path, "a/contract.json");
        assert_eq!(
            lock.assets[0].asset,
            format!("sha256-{}.json", sha(b"{\"a\":1}"))
        );
        let parsed = Lock::parse(&lock.render()).unwrap();
        assert_eq!(parsed, lock);
    }

    #[test]
    fn lock_rejects_bad_shapes() {
        let dir = tempfile::tempdir().unwrap();
        let good = lock_for(dir.path(), &[("a/contract.json", b"aaa")]);
        let mut bad = good.clone();
        bad.schema = "other".into();
        assert!(bad.validate().is_err());
        let mut bad = good.clone();
        bad.assets[0].asset = "contract.json".into();
        assert!(bad
            .validate()
            .unwrap_err()
            .to_string()
            .contains("content-addressed"));
        let mut bad = good.clone();
        bad.assets[0].sha256 = bad.assets[0].sha256.to_uppercase();
        assert!(bad.validate().is_err());
        let mut bad = good.clone();
        bad.assets[0].path = "../escape.json".into();
        assert!(bad.validate().is_err());
        let mut bad = good.clone();
        bad.assets[0].path = "/abs.json".into();
        assert!(bad.validate().is_err());
        let mut bad = good.clone();
        bad.assets.push(bad.assets[0].clone());
        assert!(bad
            .validate()
            .unwrap_err()
            .to_string()
            .contains("duplicate path"));
        let mut bad = good.clone();
        let mut second = bad.assets[0].clone();
        second.path = "0-earlier/contract.json".into();
        second.sha256 = "0".repeat(64);
        second.asset = Asset::expected_asset_name_for(&second.path, &second.sha256);
        bad.assets.push(second);
        assert!(bad.validate().unwrap_err().to_string().contains("sorted"));
        let mut bad = good.clone();
        bad.assets[0].bytes = 0;
        assert!(bad.validate().is_err());
        let mut bad = good.clone();
        bad.release_tag = "v1 latest".into();
        assert!(bad.validate().is_err());
        assert!(Lock::parse("{\"schema\":\"x\"}").is_err());
        assert!(Lock::parse(
            &good
                .render()
                .replace("\"assets\"", "\"extra\":1,\"assets\"")
        )
        .is_err());
    }

    #[test]
    fn check_reports_missing_and_mismatch() {
        let dir = tempfile::tempdir().unwrap();
        let lock = lock_for(
            dir.path(),
            &[("a/contract.json", b"aaa"), ("b/contract.json", b"bbb")],
        );
        assert!(check(&lock, dir.path()).ok());
        fs::remove_file(dir.path().join("a/contract.json")).unwrap();
        fs::write(dir.path().join("b/contract.json"), b"bbbb").unwrap();
        let report = check(&lock, dir.path());
        assert!(!report.ok());
        assert_eq!(report.rows[0].1, Status::Missing);
        assert!(report.rows[0].2.contains("evidence blob not fetched"));
        assert_eq!(report.rows[1].1, Status::Mismatch);
        assert!(report.rows[1].2.contains("expected 3 bytes"));
    }

    #[test]
    fn fetch_promotes_only_verified_bytes_and_uses_cache() {
        let source = tempfile::tempdir().unwrap();
        let lock = lock_for(
            source.path(),
            &[("a/contract.json", b"aaa"), ("b/contract.json", b"bbb")],
        );
        let mirror = tempfile::tempdir().unwrap();
        for asset in &lock.assets {
            fs::copy(
                source.path().join(&asset.path),
                mirror.path().join(&asset.asset),
            )
            .unwrap();
        }
        let tree = tempfile::tempdir().unwrap();
        let cache = tempfile::tempdir().unwrap();
        let fetcher = DirectoryFetcher {
            directory: mirror.path().to_path_buf(),
        };
        let options = FetchOptions {
            cache_dir: cache.path(),
            offline: false,
        };

        let outcomes = fetch_all(&lock, tree.path(), &fetcher, &options).unwrap();
        assert!(outcomes.iter().all(|(_, o)| *o == Outcome::Downloaded));
        assert!(check(&lock, tree.path()).ok());
        assert!(cache_path(cache.path(), &lock.assets[0]).is_file());

        // Second run: nothing to do.
        let outcomes = fetch_all(&lock, tree.path(), &fetcher, &options).unwrap();
        assert!(outcomes.iter().all(|(_, o)| *o == Outcome::AlreadyPresent));

        // Remove from tree: served from cache, no fetcher needed.
        fs::remove_file(tree.path().join("a/contract.json")).unwrap();
        let empty = tempfile::tempdir().unwrap();
        let no_fetch = DirectoryFetcher {
            directory: empty.path().to_path_buf(),
        };
        let outcomes = fetch_all(&lock, tree.path(), &no_fetch, &options).unwrap();
        assert_eq!(outcomes[0].1, Outcome::FromCache);

        // Poisoned cache entry is discarded, then offline refuses.
        fs::write(cache_path(cache.path(), &lock.assets[0]), b"poison").unwrap();
        fs::remove_file(tree.path().join("a/contract.json")).unwrap();
        let offline = FetchOptions {
            cache_dir: cache.path(),
            offline: true,
        };
        let err = fetch_all(&lock, tree.path(), &no_fetch, &offline).unwrap_err();
        assert!(err.to_string().contains("evidence blob not fetched"));
        assert!(!cache_path(cache.path(), &lock.assets[0]).exists());
        assert!(!tree.path().join("a/contract.json").exists());

        // Wrong bytes from the fetcher never reach the tree or the cache.
        let bad = tempfile::tempdir().unwrap();
        fs::write(bad.path().join(&lock.assets[0].asset), b"aab").unwrap();
        let bad_fetcher = DirectoryFetcher {
            directory: bad.path().to_path_buf(),
        };
        let err = fetch_all(&lock, tree.path(), &bad_fetcher, &options).unwrap_err();
        assert!(err.to_string().contains("fetch failed"), "{err}");
        assert!(!tree.path().join("a/contract.json").exists());
        assert!(!cache_path(cache.path(), &lock.assets[0]).exists());
        assert_eq!(
            fs::read_dir(cache.path().join("sha256")).unwrap().count(),
            1,
            "no temp files linger"
        );
    }

    #[test]
    fn asset_names_keep_the_path_extension() {
        let dir = tempfile::tempdir().unwrap();
        let lock = lock_for(
            dir.path(),
            &[
                ("blocks/mainnet/12369621.pb", b"\x08\x03"),
                ("a/contract.json", b"{}"),
            ],
        );
        assert!(
            lock.assets[1].asset.ends_with(".pb"),
            "{}",
            lock.assets[1].asset
        );
        assert!(lock.assets[0].asset.ends_with(".json"));
        assert_eq!(Asset::expected_asset_name_for("x/y", "ab"), "sha256-ab");
        let mut bad = lock.clone();
        bad.assets[1].asset = format!("sha256-{}.json", bad.assets[1].sha256);
        assert!(bad
            .validate()
            .unwrap_err()
            .to_string()
            .contains("content-addressed"));
    }

    #[test]
    fn release_audit_rejects_missing_and_unlocked() {
        let dir = tempfile::tempdir().unwrap();
        let lock = lock_for(dir.path(), &[("a/contract.json", b"aaa")]);
        let exact = vec![(lock.assets[0].asset.clone(), 3)];
        audit_release_assets(&lock, &exact).unwrap();
        let err = audit_release_assets(&lock, &[]).unwrap_err().to_string();
        assert!(err.contains("missing on release"));
        let mut extra = exact.clone();
        extra.push(("sha256-ffff.json".into(), 9));
        assert!(audit_release_assets(&lock, &extra)
            .unwrap_err()
            .to_string()
            .contains("unlocked asset"));
        let wrong_size = vec![(lock.assets[0].asset.clone(), 4)];
        assert!(audit_release_assets(&lock, &wrong_size).is_err());
    }
}

#[cfg(test)]
mod tracked_tests {
    use super::*;

    #[test]
    fn tracked_entries_are_verified_and_cannot_overlap_assets() {
        let dir = tempfile::tempdir().unwrap();
        for (p, b) in [
            ("ext/contract.json", b"ext".as_slice()),
            ("small/contract.json", b"small".as_slice()),
        ] {
            let path = dir.path().join(p);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(&path, b).unwrap();
        }
        let lock = lock_from_tree(
            dir.path(),
            "pinax-network/substreams-backfills",
            "evidence-assets-v1",
            vec!["ext/contract.json".into()],
            vec!["small/contract.json".into()],
        )
        .unwrap();
        assert_eq!(lock.tracked.len(), 1);
        assert!(check(&lock, dir.path()).ok());
        let parsed = Lock::parse(&lock.render()).unwrap();
        assert_eq!(parsed, lock);

        fs::write(dir.path().join("small/contract.json"), b"smal").unwrap();
        let report = check(&lock, dir.path());
        assert_eq!(report.rows[1].1, Status::Mismatch);
        fs::remove_file(dir.path().join("small/contract.json")).unwrap();
        let report = check(&lock, dir.path());
        assert_eq!(report.rows[1].1, Status::Missing);
        assert!(report.rows[1].2.contains("tracked contract missing"));

        let mut overlap = lock.clone();
        overlap.tracked[0].path = "ext/contract.json".into();
        assert!(overlap
            .validate()
            .unwrap_err()
            .to_string()
            .contains("both externalized and tracked"));
        let mut unsorted = lock.clone();
        unsorted.tracked.push(Tracked {
            path: "a/contract.json".into(),
            bytes: 1,
            sha256: "0".repeat(64),
        });
        assert!(unsorted
            .validate()
            .unwrap_err()
            .to_string()
            .contains("sorted"));
        // Old locks without a tracked field still parse.
        let legacy = lock
            .render()
            .replace(",\n  \"tracked\": [", ",\n  \"tracked_legacy_removed\": [");
        assert!(Lock::parse(&legacy).is_err(), "unknown field is rejected");
        let mut no_tracked = lock.clone();
        no_tracked.tracked.clear();
        assert!(Lock::parse(&no_tracked.render())
            .unwrap()
            .tracked
            .is_empty());
    }
}
