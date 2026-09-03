//! Segment bundles: the deployed artifacts of one subgraph deployment, laid out
//! on disk with a digest lock so a run can prove what it executed.
//!
//! Layout under `segments/<deployment-cid>/`:
//!
//! ```text
//! manifest.yaml            byte-identical to the IPFS object <deployment-cid>
//! schema.graphql           the manifest's `schema.file` object
//! abis/<Name>.json         one per distinct ABI name across data sources and templates
//! mappings/<mapping-cid>.wasm
//! bundle.lock.json         every file above with its IPFS CID, byte length and SHA-256
//! ```
//!
//! The manifest keeps its original `/ipfs/<cid>` links, so its bytes still hash to
//! the deployment CID. Resolution is done with graph-node's own
//! [`FileLinkResolver`], seeded with an alias table mapping each CID to the
//! friendly path above, so data sources, templates, ABIs and handlers all come
//! out of graph-node's parser rather than ours.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use graph::components::link_resolver::FileLinkResolver;
use graph::data::subgraph::{DeploymentHash, SubgraphManifest, LATEST_VERSION};
use graph::prelude::{LinkResolver, Logger};
use graph_chain_ethereum::Chain;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Schema identifier written into every `bundle.lock.json`.
pub const BUNDLE_LOCK_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.bundle/v1";

/// One file in a bundle, with the provenance needed to prove it is the deployed
/// artifact and the digest needed to detect drift on disk.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct BundleFile {
    /// Path relative to the bundle directory, e.g. `abis/Factory.json`.
    pub path: String,
    /// The IPFS CID this file was fetched under.
    pub cid: String,
    /// Byte length on disk.
    pub bytes: u64,
    /// Lowercase hex SHA-256 of the file contents.
    pub sha256: String,
}

/// The digest lock for one segment bundle.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct BundleLock {
    pub schema: String,
    /// Deployment CID; also the directory name and the `manifest.yaml` CID.
    pub deployment: String,
    pub network: String,
    pub spec_version: String,
    /// Manifest `features`, verbatim and in manifest order.
    pub features: Vec<String>,
    /// Files sorted by `path`.
    pub files: Vec<BundleFile>,
}

impl BundleLock {
    fn file_for_cid(&self, cid: &str) -> Option<&BundleFile> {
        self.files.iter().find(|f| f.cid == cid)
    }
}

/// A loaded, digest-verified segment bundle.
pub struct SegmentBundle {
    dir: PathBuf,
    lock: BundleLock,
    deployment: DeploymentHash,
}

impl SegmentBundle {
    /// Load and verify a bundle directory. Refuses drift: every file listed in
    /// the lock must exist with exactly the recorded length and SHA-256, and the
    /// directory must contain no extra `.wasm`, `.json`, `.yaml` or `.graphql`
    /// file that the lock does not cover.
    pub fn load(dir: impl AsRef<Path>) -> Result<Self> {
        let dir = dir.as_ref().to_path_buf();
        let lock_path = dir.join("bundle.lock.json");
        let lock_bytes = std::fs::read(&lock_path)
            .with_context(|| format!("reading {}", lock_path.display()))?;
        let lock: BundleLock = serde_json::from_slice(&lock_bytes)
            .with_context(|| format!("parsing {}", lock_path.display()))?;

        if lock.schema != BUNDLE_LOCK_SCHEMA {
            bail!(
                "{}: unexpected lock schema `{}`, want `{}`",
                lock_path.display(),
                lock.schema,
                BUNDLE_LOCK_SCHEMA
            );
        }

        let dir_name = dir
            .file_name()
            .and_then(|n| n.to_str())
            .ok_or_else(|| anyhow!("bundle directory has no name: {}", dir.display()))?;
        if dir_name != lock.deployment {
            bail!(
                "bundle directory `{}` does not match its locked deployment `{}`",
                dir_name,
                lock.deployment
            );
        }

        let mut locked_paths = BTreeMap::new();
        for file in &lock.files {
            if locked_paths.insert(file.path.clone(), file).is_some() {
                bail!("{}: duplicate path `{}`", lock_path.display(), file.path);
            }
            let path = dir.join(&file.path);
            let bytes = std::fs::read(&path)
                .with_context(|| format!("reading bundle file {}", path.display()))?;
            if bytes.len() as u64 != file.bytes {
                bail!(
                    "bundle drift: {} is {} bytes, lock says {}",
                    path.display(),
                    bytes.len(),
                    file.bytes
                );
            }
            let digest = sha256_hex(&bytes);
            if digest != file.sha256 {
                bail!(
                    "bundle drift: {} hashes to {}, lock says {}",
                    path.display(),
                    digest,
                    file.sha256
                );
            }
        }

        for path in walk_bundle(&dir)? {
            let rel = path
                .strip_prefix(&dir)
                .expect("walk_bundle only yields paths under dir")
                .to_string_lossy()
                .replace('\\', "/");
            if rel == "bundle.lock.json" {
                continue;
            }
            if !locked_paths.contains_key(&rel) {
                bail!(
                    "bundle drift: {} is present on disk but absent from {}",
                    path.display(),
                    lock_path.display()
                );
            }
        }

        let deployment = DeploymentHash::new(lock.deployment.clone())
            .map_err(|s| anyhow!("invalid deployment hash `{}`", s))?;

        Ok(SegmentBundle {
            dir,
            lock,
            deployment,
        })
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    pub fn lock(&self) -> &BundleLock {
        &self.lock
    }

    pub fn deployment(&self) -> &DeploymentHash {
        &self.deployment
    }

    pub fn network(&self) -> &str {
        &self.lock.network
    }

    /// A link resolver that maps every `/ipfs/<cid>` link in the manifest to the
    /// friendly path the bundle stores it under.
    pub fn link_resolver(&self) -> Arc<dyn LinkResolver> {
        let aliases: HashMap<String, PathBuf> = self
            .lock
            .files
            .iter()
            .map(|f| (f.cid.clone(), self.dir.join(&f.path)))
            .collect();
        Arc::new(FileLinkResolver::new(Some(self.dir.clone()), aliases))
    }

    /// Resolve the manifest through graph-node's own parser.
    ///
    /// `amp_client` is typed but always `None`: `resolve_from_raw` is generic over
    /// `amp::Client` and the V3 deployments declare no Amp data sources, so we
    /// hand it the concrete `FlightClient` type and never construct one.
    pub async fn manifest(&self, logger: &Logger) -> Result<SubgraphManifest<Chain>> {
        let manifest_file = self
            .lock
            .files
            .iter()
            .find(|f| f.path == "manifest.yaml")
            .ok_or_else(|| anyhow!("bundle {} has no manifest.yaml", self.lock.deployment))?;
        let raw_bytes = std::fs::read(self.dir.join(&manifest_file.path))?;
        let raw: serde_yaml::Mapping = serde_yaml::from_slice(&raw_bytes)
            .with_context(|| format!("parsing manifest of {}", self.lock.deployment))?;

        let resolver = self.link_resolver();
        SubgraphManifest::<Chain>::resolve_from_raw(
            self.deployment.clone(),
            raw,
            &resolver,
            None::<Arc<graph::amp::client::flight_client::FlightClient>>,
            logger,
            LATEST_VERSION.clone(),
        )
        .await
        .with_context(|| format!("resolving manifest of {}", self.lock.deployment))
    }

    /// The bundle-relative path a CID is stored under, for reporting provenance.
    pub fn path_for_cid(&self, cid: &str) -> Option<&str> {
        self.lock.file_for_cid(cid).map(|f| f.path.as_str())
    }
}

/// Lowercase hex SHA-256.
pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

fn walk_bundle(dir: &Path) -> Result<Vec<PathBuf>> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(current) = stack.pop() {
        for entry in
            std::fs::read_dir(&current).with_context(|| format!("listing {}", current.display()))?
        {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else {
                out.push(path);
            }
        }
    }
    out.sort();
    Ok(out)
}

/// Build the bundles for every `<cid>.yaml` manifest in `src`, writing one
/// directory per deployment under `out`.
///
/// `src` is a flat directory of IPFS objects named `<cid>.{yaml,wasm,bin}`, which
/// is how the deployment artifacts were fetched. This is the only place that
/// knows about that layout; everything downstream reads bundles.
pub fn build_bundles(src: &Path, out: &Path) -> Result<Vec<String>> {
    let mut manifests: Vec<PathBuf> = std::fs::read_dir(src)
        .with_context(|| format!("listing {}", src.display()))?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("yaml"))
        .collect();
    manifests.sort();

    let mut built = Vec::new();
    for manifest_path in manifests {
        let deployment = manifest_path
            .file_stem()
            .and_then(|s| s.to_str())
            .ok_or_else(|| anyhow!("bad manifest name {}", manifest_path.display()))?
            .to_string();
        build_bundle(src, out, &deployment, &manifest_path)?;
        built.push(deployment);
    }
    Ok(built)
}

fn build_bundle(src: &Path, out: &Path, deployment: &str, manifest_path: &Path) -> Result<()> {
    let manifest_bytes = std::fs::read(manifest_path)?;
    let raw: serde_yaml::Value = serde_yaml::from_slice(&manifest_bytes)?;

    let dir = out.join(deployment);
    std::fs::create_dir_all(dir.join("abis"))?;
    std::fs::create_dir_all(dir.join("mappings"))?;

    let mut files: Vec<BundleFile> = Vec::new();
    let mut seen_cids: BTreeMap<String, String> = BTreeMap::new();

    // The manifest itself, byte-identical to the IPFS object.
    std::fs::write(dir.join("manifest.yaml"), &manifest_bytes)?;
    files.push(BundleFile {
        path: "manifest.yaml".to_string(),
        cid: deployment.to_string(),
        bytes: manifest_bytes.len() as u64,
        sha256: sha256_hex(&manifest_bytes),
    });
    seen_cids.insert(deployment.to_string(), "manifest.yaml".to_string());

    let schema_cid = link_of(&raw["schema"]["file"])
        .ok_or_else(|| anyhow!("{}: manifest has no schema link", deployment))?;
    place(
        src,
        &dir,
        deployment,
        &schema_cid,
        "schema.graphql".to_string(),
        &mut files,
        &mut seen_cids,
    )?;

    let mut network = String::new();
    let mut features = Vec::new();
    if let Some(list) = raw.get("features").and_then(|f| f.as_sequence()) {
        for f in list {
            if let Some(s) = f.as_str() {
                features.push(s.to_string());
            }
        }
    }

    let mut abi_names: BTreeMap<String, String> = BTreeMap::new();
    for section in ["dataSources", "templates"] {
        let Some(list) = raw.get(section).and_then(|v| v.as_sequence()) else {
            continue;
        };
        for entry in list {
            if network.is_empty() {
                if let Some(n) = entry.get("network").and_then(|n| n.as_str()) {
                    network = n.to_string();
                }
            }
            let mapping = &entry["mapping"];
            if let Some(cid) = link_of(&mapping["file"]) {
                place(
                    src,
                    &dir,
                    deployment,
                    &cid,
                    format!("mappings/{cid}.wasm"),
                    &mut files,
                    &mut seen_cids,
                )?;
            }
            let Some(abis) = mapping.get("abis").and_then(|v| v.as_sequence()) else {
                continue;
            };
            for abi in abis {
                let name = abi["name"]
                    .as_str()
                    .ok_or_else(|| anyhow!("{}: ABI without a name", deployment))?;
                let cid = link_of(&abi["file"])
                    .ok_or_else(|| anyhow!("{}: ABI `{}` without a link", deployment, name))?;
                match abi_names.get(name) {
                    Some(existing) if existing != &cid => bail!(
                        "{}: ABI name `{}` maps to two CIDs, {} and {}",
                        deployment,
                        name,
                        existing,
                        cid
                    ),
                    Some(_) => continue,
                    None => {
                        abi_names.insert(name.to_string(), cid.clone());
                        place(
                            src,
                            &dir,
                            deployment,
                            &cid,
                            format!("abis/{name}.json"),
                            &mut files,
                            &mut seen_cids,
                        )?;
                    }
                }
            }
        }
    }

    let spec_version = raw["specVersion"]
        .as_str()
        .ok_or_else(|| anyhow!("{}: manifest has no specVersion", deployment))?
        .to_string();

    files.sort_by(|a, b| a.path.cmp(&b.path));
    let lock = BundleLock {
        schema: BUNDLE_LOCK_SCHEMA.to_string(),
        deployment: deployment.to_string(),
        network,
        spec_version,
        features,
        files,
    };
    let mut json = serde_json::to_string_pretty(&lock)?;
    json.push('\n');
    std::fs::write(dir.join("bundle.lock.json"), json)?;
    Ok(())
}

/// Copy the IPFS object `cid` into the bundle at `rel`, recording its digest.
/// A CID already placed at the same path is a no-op; at a different path it is a
/// hard error, so one object can never be duplicated under two names.
#[allow(clippy::too_many_arguments)]
fn place(
    src: &Path,
    dir: &Path,
    deployment: &str,
    cid: &str,
    rel: String,
    files: &mut Vec<BundleFile>,
    seen_cids: &mut BTreeMap<String, String>,
) -> Result<()> {
    if let Some(existing) = seen_cids.get(cid) {
        if existing != &rel {
            bail!(
                "{}: CID {} wanted at both `{}` and `{}`",
                deployment,
                cid,
                existing,
                rel
            );
        }
        return Ok(());
    }
    let source = find_object(src, cid)?;
    let bytes = std::fs::read(&source)
        .with_context(|| format!("reading IPFS object {}", source.display()))?;
    std::fs::write(dir.join(&rel), &bytes)?;
    files.push(BundleFile {
        path: rel.clone(),
        cid: cid.to_string(),
        bytes: bytes.len() as u64,
        sha256: sha256_hex(&bytes),
    });
    seen_cids.insert(cid.to_string(), rel);
    Ok(())
}

fn link_of(value: &serde_yaml::Value) -> Option<String> {
    value
        .get("/")
        .and_then(|v| v.as_str())
        .map(|s| s.trim_start_matches("/ipfs/").to_string())
}

fn find_object(src: &Path, cid: &str) -> Result<PathBuf> {
    for ext in ["wasm", "bin", "yaml", "json", "graphql"] {
        let candidate = src.join(format!("{cid}.{ext}"));
        if candidate.exists() {
            return Ok(candidate);
        }
    }
    let bare = src.join(cid);
    if bare.exists() {
        return Ok(bare);
    }
    Err(anyhow!(
        "no IPFS object for {} under {}",
        cid,
        src.display()
    ))
}
