//! Immutable Uniswap V4 historical release assets (port of
//! `scripts/verify-uniswap-v4-release-assets.py`, #110).
//!
//! The two release packages that were intentionally outside the imported
//! Git tree are mirrored under `artifacts/releases/uniswap-v4/`. Their source
//! release identities, byte sizes, and SHA-256 digests are locked here and in
//! `docs/provenance/uniswap-v4-release-assets-v1.json`; the manifest must
//! equal the pinned contract exactly, every mirrored path must be a regular
//! file reached without symlinks, and the mirror must hold nothing else.

use std::collections::BTreeSet;
use std::fmt;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub const DEFAULT_MANIFEST: &str = "docs/provenance/uniswap-v4-release-assets-v1.json";
pub const MIRROR_ROOT: &str = "artifacts/releases/uniswap-v4";

pub struct ExpectedAsset {
    pub release_tag: &'static str,
    pub release_url: &'static str,
    pub asset_api_id: u64,
    pub asset_name: &'static str,
    pub asset_url: &'static str,
    pub content_type: &'static str,
    pub created_at: &'static str,
    pub size: u64,
    pub sha256: &'static str,
    pub path: &'static str,
}

pub const EXPECTED_ASSETS: &[ExpectedAsset] = &[
    ExpectedAsset {
        release_tag: "v0.1.0",
        release_url: "https://github.com/pinax-network/substreams-v4-subgraph/releases/tag/v0.1.0",
        asset_api_id: 499820971,
        asset_name: "uniswap-v4-base-backfill-v0.1.0.spkg",
        asset_url: "https://github.com/pinax-network/substreams-v4-subgraph/releases/download/v0.1.0/uniswap-v4-base-backfill-v0.1.0.spkg",
        content_type: "application/octet-stream",
        created_at: "2026-08-03T08:36:32Z",
        size: 442378,
        sha256: "75b810d18ec1dc78ca5535b2cc56828334c873b93d39500f93ca036499048453",
        path: "artifacts/releases/uniswap-v4/v0.1.0/uniswap-v4-base-backfill-v0.1.0.spkg",
    },
    ExpectedAsset {
        release_tag: "v0.4.1",
        release_url: "https://github.com/pinax-network/substreams-v4-subgraph/releases/tag/v0.4.1",
        asset_api_id: 523102666,
        asset_name: "uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg",
        asset_url: "https://github.com/pinax-network/substreams-v4-subgraph/releases/download/v0.4.1/uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg",
        content_type: "application/octet-stream",
        created_at: "2026-08-21T02:29:01Z",
        size: 1534793,
        sha256: "c2470ab845cebc929aa20489a21114cb9db891aef9ad99559c97757b1938e81a",
        path: "artifacts/releases/uniswap-v4/v0.4.1/uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg",
    },
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerificationError(pub String);

impl fmt::Display for VerificationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for VerificationError {}

pub type Result<T> = std::result::Result<T, VerificationError>;

fn fail<T>(message: impl Into<String>) -> Result<T> {
    Err(VerificationError(message.into()))
}

/// The exact manifest the repository must carry.
pub fn expected_manifest() -> Value {
    let assets: Vec<Value> = EXPECTED_ASSETS
        .iter()
        .map(|a| {
            json!({
                "release_tag": a.release_tag,
                "release_url": a.release_url,
                "asset_api_id": a.asset_api_id,
                "asset_name": a.asset_name,
                "asset_url": a.asset_url,
                "content_type": a.content_type,
                "created_at": a.created_at,
                "size": a.size,
                "sha256": a.sha256,
                "path": a.path,
            })
        })
        .collect();
    json!({
        "format_version": 1,
        "family": "uniswap-v4-base",
        "source_repository": "pinax-network/substreams-v4-subgraph",
        "mirror_root": MIRROR_ROOT,
        "future_release_authority_transferred": false,
        "assets": assets,
        "boundary": {
            "mirrored_bytes_are_immutable": true,
            "historical_source_releases_must_remain_available": true,
            "active_workflows_may_still_use_source_repository": true,
            "new_release_from_this_repository_verified": false,
            "source_repository_archive_authorized": false,
        }
    })
}

fn reject_symlink_components(root: &Path, relative: &str) -> Result<()> {
    let mut current = root.to_path_buf();
    for component in relative.split('/') {
        current.push(component);
        if current
            .symlink_metadata()
            .map(|m| m.file_type().is_symlink())
            .unwrap_or(false)
        {
            return fail(format!(
                "mirrored asset uses a symlinked path component: {relative}"
            ));
        }
    }
    Ok(())
}

fn sha256_file(path: &Path) -> Result<String> {
    let bytes = std::fs::read(path)
        .map_err(|e| VerificationError(format!("cannot read {}: {e}", path.display())))?;
    Ok(hex::encode(Sha256::digest(&bytes)))
}

fn walk_spkg(dir: &Path, root: &Path, out: &mut BTreeSet<String>) -> Result<()> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Ok(());
    };
    for entry in entries {
        let entry = entry.map_err(|e| VerificationError(e.to_string()))?;
        let path = entry.path();
        let meta = path
            .symlink_metadata()
            .map_err(|e| VerificationError(e.to_string()))?;
        if meta.file_type().is_symlink() || meta.is_file() {
            if path.extension().and_then(|e| e.to_str()) == Some("spkg") {
                let relative = path
                    .strip_prefix(root)
                    .map_err(|e| VerificationError(e.to_string()))?;
                out.insert(relative.to_string_lossy().replace('\\', "/"));
            }
            continue;
        }
        if meta.is_dir() {
            walk_spkg(&path, root, out)?;
        }
    }
    Ok(())
}

pub fn verify(root: &Path, manifest_path: &Path) -> Result<()> {
    let root = root
        .canonicalize()
        .map_err(|e| VerificationError(format!("cannot resolve root {}: {e}", root.display())))?;
    let resolved_manifest = if manifest_path.is_absolute() {
        manifest_path.to_path_buf()
    } else {
        root.join(manifest_path)
    };
    let text = std::fs::read_to_string(&resolved_manifest)
        .map_err(|e| VerificationError(format!("cannot read release-asset manifest: {e}")))?;
    let manifest: Value = serde_json::from_str(&text)
        .map_err(|e| VerificationError(format!("cannot read release-asset manifest: {e}")))?;
    if manifest != expected_manifest() {
        return fail("release-asset manifest differs from the pinned contract");
    }

    let mut expected_paths = BTreeSet::new();
    for asset in EXPECTED_ASSETS {
        expected_paths.insert(asset.path.to_string());
        reject_symlink_components(&root, asset.path)?;
        let candidate = root.join(asset.path);
        let resolved = match candidate.canonicalize() {
            Ok(resolved) if resolved.starts_with(&root) => resolved,
            _ => return fail(format!("unsafe or missing mirrored asset: {}", asset.path)),
        };
        if !resolved.is_file() {
            return fail(format!(
                "mirrored asset is not a regular file: {}",
                asset.path
            ));
        }
        let actual_size = resolved
            .metadata()
            .map_err(|e| VerificationError(e.to_string()))?
            .len();
        if actual_size != asset.size {
            return fail(format!(
                "{} has size {actual_size}, expected {}",
                asset.path, asset.size
            ));
        }
        let actual = sha256_file(&resolved)?;
        if actual != asset.sha256 {
            return fail(format!(
                "{} has SHA-256 {actual}, expected {}",
                asset.path, asset.sha256
            ));
        }
    }

    let mut actual_paths = BTreeSet::new();
    walk_spkg(&root.join(MIRROR_ROOT), &root, &mut actual_paths)?;
    if actual_paths != expected_paths {
        let missing: Vec<&String> = expected_paths.difference(&actual_paths).collect();
        let unexpected: Vec<&String> = actual_paths.difference(&expected_paths).collect();
        return fail(format!(
            "release mirror inventory differs: missing={missing:?}, unexpected={unexpected:?}"
        ));
    }
    Ok(())
}

pub fn default_manifest_path() -> PathBuf {
    PathBuf::from(DEFAULT_MANIFEST)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    struct Fixture {
        dir: tempfile::TempDir,
        manifest: Value,
    }

    impl Fixture {
        fn new() -> Fixture {
            let dir = tempfile::tempdir().unwrap();
            let fixture = Fixture {
                dir,
                manifest: expected_manifest(),
            };
            fixture.write_manifest();
            for asset in EXPECTED_ASSETS {
                let destination = fixture.root().join(asset.path);
                fs::create_dir_all(destination.parent().unwrap()).unwrap();
                fs::copy(repository().join(asset.path), destination).unwrap();
            }
            fixture
        }
        fn root(&self) -> &Path {
            self.dir.path()
        }
        fn write_manifest(&self) {
            let path = self.root().join(DEFAULT_MANIFEST);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(
                path,
                format!(
                    "{}\n",
                    serde_json::to_string_pretty(&self.manifest).unwrap()
                ),
            )
            .unwrap();
        }
        fn verify(&self) -> Result<()> {
            verify(self.root(), &default_manifest_path())
        }
        fn error(&self) -> String {
            self.verify().unwrap_err().to_string()
        }
    }

    #[test]
    fn exact_mirror_passes() {
        Fixture::new().verify().unwrap();
        verify(&repository(), &default_manifest_path()).unwrap();
    }

    #[test]
    fn changed_asset_byte_is_rejected() {
        let f = Fixture::new();
        let path = f.root().join(EXPECTED_ASSETS[0].path);
        let mut bytes = fs::read(&path).unwrap();
        bytes[0] ^= 0xFF;
        fs::write(&path, bytes).unwrap();
        assert!(f.error().contains("SHA-256"));
    }

    #[test]
    fn manifest_metadata_drift_is_rejected() {
        let mut f = Fixture::new();
        f.manifest["assets"][0]["created_at"] = json!("2026-08-03T08:36:33Z");
        f.write_manifest();
        assert!(f.error().contains("pinned contract"));
    }

    #[test]
    fn authority_claim_is_rejected() {
        let mut f = Fixture::new();
        f.manifest["future_release_authority_transferred"] = json!(true);
        f.write_manifest();
        assert!(f.error().contains("pinned contract"));
    }

    #[test]
    fn missing_asset_is_rejected() {
        let f = Fixture::new();
        fs::remove_file(f.root().join(EXPECTED_ASSETS[1].path)).unwrap();
        assert!(f.error().contains("missing mirrored asset"));
    }

    #[test]
    fn unlisted_package_is_rejected() {
        let f = Fixture::new();
        fs::write(f.root().join(MIRROR_ROOT).join("v0.1.0/extra.spkg"), b"x").unwrap();
        assert!(f.error().contains("unexpected"));
    }

    #[test]
    fn symlinked_asset_is_rejected() {
        let f = Fixture::new();
        let target = f.root().join(EXPECTED_ASSETS[0].path);
        let copy_path = f.root().join("copy.spkg");
        fs::rename(&target, &copy_path).unwrap();
        std::os::unix::fs::symlink(&copy_path, &target).unwrap();
        assert!(f.error().contains("symlinked path component"));
    }

    #[test]
    fn symlinked_mirror_root_is_rejected() {
        let f = Fixture::new();
        let mirror = f.root().join(MIRROR_ROOT);
        let relocated = f.root().join("relocated-mirror");
        fs::rename(&mirror, &relocated).unwrap();
        std::os::unix::fs::symlink(&relocated, &mirror).unwrap();
        assert!(f.error().contains("symlinked path component"));
    }

    #[test]
    fn symlinked_version_directory_is_rejected() {
        let f = Fixture::new();
        let version = f.root().join(MIRROR_ROOT).join("v0.4.1");
        let relocated = f.root().join("relocated-version");
        fs::rename(&version, &relocated).unwrap();
        std::os::unix::fs::symlink(&relocated, &version).unwrap();
        assert!(f.error().contains("symlinked path component"));
    }

    #[test]
    fn repository_manifest_equals_pinned_contract() {
        let text = fs::read_to_string(repository().join(DEFAULT_MANIFEST)).unwrap();
        let manifest: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(manifest, expected_manifest());
    }
}
