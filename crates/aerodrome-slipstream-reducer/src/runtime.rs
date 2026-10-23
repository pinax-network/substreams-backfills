//! Closed, development-only producer runtime bundles. Hashes establish identity,
//! not qualification or a claim that a binary was reproducibly built. Source
//! closure is checked by the packaging tool before building the executable.
mod package;
use crate::{identity::InputBinding, refuse, require, Result};
use aerodrome_extractor_core::config::{DEPLOYMENT, INITIAL_BLOCK};
use backfill_common::{
    descriptor::{ExtractorIdentity, ProducerContract},
    producer_checkpoint::Binding,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};

pub const FORMAT: &str = "pinax.backfill.producer-runtime/v1";
pub const PROTOCOL: &str = "pinax.backfill.producer/v1";
pub const FAMILY: &str = "aerodrome-slipstream-base";
/// Historical logical checkpoint identity; distinct from the deployment family.
pub const CHECKPOINT_FAMILY: &str = "aerodrome-slipstream";
pub const FILES: [&str; 8] = [
    "bin/producer",
    "contract/block-changes-descriptor.json",
    "contract/block-changes-descriptor.json.sha256",
    "contract/compatibility.json",
    "source.json",
    "spkg/extractor-identity.json",
    "spkg/extractor-lock.json",
    "spkg/extractor.spkg",
];
const MAX_FILE: u64 = 256 * 1024 * 1024;
const MAX_JSON: u64 = 4 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilePin {
    pub bytes: u64,
    pub sha256: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeManifest {
    pub format: String,
    pub protocol: String,
    pub family: String,
    pub production_selectable: bool,
    pub source_commit: String,
    pub files: BTreeMap<String, FilePin>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceManifest {
    pub format: String,
    pub repository: String,
    pub source_commit: String,
    /// Exact Git blobs materialized into the build context; never a dirty tree.
    pub files: BTreeMap<String, FilePin>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FamilyContract {
    pub format: String,
    pub family: String,
    pub producer_checkpoint_family: String,
    pub network: String,
    pub deployment: String,
    pub spec_version: String,
    pub mapping_api_version: String,
    pub graph_node_version: String,
    pub graph_node_commit: String,
    pub poi_version: String,
    pub initial_block: u64,
    pub manifest_features: Vec<String>,
    pub data_source_transport: String,
    pub requires_non_fatal_handover: bool,
    pub required_engine_capabilities: Vec<String>,
}
impl FamilyContract {
    pub fn aerodrome() -> Self {
        Self {
            format: "pinax.backfill.family-contract/v1".into(),
            family: FAMILY.into(),
            producer_checkpoint_family: CHECKPOINT_FAMILY.into(),
            network: "base".into(),
            deployment: DEPLOYMENT.into(),
            spec_version: "1.2.0".into(),
            mapping_api_version: "0.0.7".into(),
            graph_node_version: "0.44.0".into(),
            graph_node_commit: graph_numerics::GRAPH_NODE_COMMIT.into(),
            poi_version: "fast".into(),
            initial_block: INITIAL_BLOCK,
            manifest_features: vec!["grafting".into(), "nonFatalErrors".into()],
            data_source_transport: "in_band_v1".into(),
            requires_non_fatal_handover: true,
            required_engine_capabilities: [
                "deterministic_error_stop_before",
                "data_sources_in_band_v1",
                "graph_decimal_v044_fixed_point",
                "producer_completion_receipt_v2",
                "final_blocks_only",
                "graft_self_copy_landing",
            ]
            .into_iter()
            .map(str::to_owned)
            .collect(),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExtractorLock {
    pub format: String,
    pub source_commit: String,
    pub production_selectable: bool,
    pub identity: ExtractorIdentity,
}

pub struct VerifiedRuntime {
    root: PathBuf,
    bytes: Vec<u8>,
    manifest: RuntimeManifest,
    input: InputBinding,
    producer: Binding,
}
impl VerifiedRuntime {
    pub fn load(root: &Path, expected_sha256: Option<&str>) -> Result<Self> {
        require(
            fs::symlink_metadata(root).map_err(io)?.is_dir(),
            "runtime root is not a real directory",
        )?;
        let root = root.canonicalize().map_err(io)?;
        let bytes = read_regular(&root.join("runtime.json"), MAX_JSON)?;
        if let Some(expected) = expected_sha256 {
            require(
                digest(expected, 64) && hash(&bytes) == expected,
                "runtime digest mismatch",
            )?;
        }
        let manifest: RuntimeManifest = json(&bytes)?;
        require(
            manifest.format == FORMAT
                && manifest.protocol == PROTOCOL
                && manifest.family == FAMILY
                && !manifest.production_selectable
                && digest(&manifest.source_commit, 40),
            "unsupported runtime identity or production qualification",
        )?;
        require(
            manifest.files.keys().map(String::as_str).eq(FILES),
            "runtime file inventory differs from closed contract",
        )?;
        let mut expected: BTreeSet<String> = FILES.iter().map(|s| (*s).into()).collect();
        expected.insert("runtime.json".into());
        require(
            inventory(&root)? == expected,
            "runtime contains unexpected files or directories",
        )?;
        let mut contents = BTreeMap::new();
        for (path, pin) in &manifest.files {
            require(
                pin.bytes > 0 && pin.bytes <= MAX_FILE && digest(&pin.sha256, 64),
                "invalid runtime file pin",
            )?;
            let limit = if path.ends_with(".json") || path.ends_with(".sha256") {
                MAX_JSON
            } else {
                MAX_FILE
            };
            let data = read_regular(&root.join(path), limit)?;
            require(
                data.len() as u64 == pin.bytes && hash(&data) == pin.sha256,
                "runtime file digest/size mismatch",
            )?;
            contents.insert(path.as_str(), data);
        }
        executable(&root.join("bin/producer"))?;
        let source: SourceManifest = json(&contents["source.json"])?;
        require(
            source.format == "pinax.backfill.producer-source/v1"
                && source.repository == "pinax-network/substreams-backfills"
                && source.source_commit == manifest.source_commit
                && !source.files.is_empty(),
            "source identity mismatch",
        )?;
        for (path, pin) in source.files {
            require(
                safe_path(&path) && pin.bytes <= MAX_FILE && digest(&pin.sha256, 64),
                "invalid source closure entry",
            )?;
        }
        let family: FamilyContract = json(&contents["contract/compatibility.json"])?;
        require(
            family == FamilyContract::aerodrome(),
            "family contract mismatch",
        )?;
        let identity: ExtractorIdentity = json(&contents["spkg/extractor-identity.json"])?;
        let lock: ExtractorLock = json(&contents["spkg/extractor-lock.json"])?;
        require(
            lock.format == "pinax.backfill.extractor-lock/v1"
                && digest(&lock.source_commit, 40)
                && !lock.production_selectable
                && lock.identity == identity,
            "extractor lock mismatch or unsupported qualification",
        )?;
        verify_package(&contents["spkg/extractor.spkg"], &identity)?;
        let descriptor = &contents["contract/block-changes-descriptor.json"];
        let descriptor_sha256 = hash(descriptor);
        require(
            contents["contract/block-changes-descriptor.json.sha256"]
                == format!("{descriptor_sha256}\n").as_bytes(),
            "descriptor sidecar mismatch (expected raw digest plus LF)",
        )?;
        let input = InputBinding::new(descriptor, Sha256::digest(descriptor).into(), &identity)?;
        let ProducerContract::NativeBlockChangesReducer { reducer, .. } = &input
            .compatibility()
            .capabilities()
            .ok_or_else(|| refuse("missing v2 capability"))?
            .producer_contract
        else {
            return Err(refuse("not a native reducer descriptor"));
        };
        require(
            reducer.commit == manifest.source_commit,
            "descriptor reducer/source commit mismatch",
        )?;
        let producer = Binding {
            family: CHECKPOINT_FAMILY.into(),
            deployment: DEPLOYMENT.into(),
            network: "base".into(),
            descriptor_sha256,
            extractor_lock_sha256: hash(&contents["spkg/extractor-lock.json"]),
            spkg_sha256: identity.spkg_sha256,
            module: identity.module,
            module_hash: identity.module_hash,
            reducer_commit: manifest.source_commit.clone(),
            reducer_binary_sha256: hash(&contents["bin/producer"]),
        };
        producer.validate().map_err(refuse)?;
        Ok(Self {
            root,
            bytes,
            manifest,
            input,
            producer,
        })
    }
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn manifest(&self) -> &RuntimeManifest {
        &self.manifest
    }
    pub fn input_binding(&self) -> InputBinding {
        self.input.clone()
    }
    pub fn producer_binding(&self) -> Binding {
        self.producer.clone()
    }
    pub fn verify_running_executable(&self) -> Result<()> {
        let path = std::env::current_exe().map_err(io)?;
        let bytes = read_regular(&path, MAX_FILE)?;
        require(
            hash(&bytes) == self.producer.reducer_binary_sha256,
            "running executable differs from bundled producer",
        )
    }
    /// Revalidate the source and stage all bytes under an unpublished sibling.
    /// Atomic no-replace promotion preserves any pre-existing destination.
    pub fn stage(&self, dest: &Path) -> Result<()> {
        Self::load(&self.root, Some(&hash(&self.bytes)))?;
        let parent = dest
            .parent()
            .ok_or_else(|| refuse("stage destination needs parent"))?;
        let parent = if parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            parent
        };
        let parent = parent.canonicalize().map_err(io)?;
        let name = dest
            .file_name()
            .ok_or_else(|| refuse("stage destination needs name"))?;
        let dest = parent.join(name);
        require(
            fs::symlink_metadata(&dest).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound),
            "stage destination already exists or cannot be inspected",
        )?;
        let mut selected = None;
        for i in 0..100 {
            let path = parent.join(format!(".producer-stage-{}-{i}", std::process::id()));
            match fs::create_dir(&path) {
                Ok(()) => {
                    selected = Some(path);
                    break;
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(e) => return Err(io(e)),
            }
        }
        let temp = selected.ok_or_else(|| refuse("no free stage sibling"))?;
        let result = (|| {
            for path in ["bin", "contract", "spkg"] {
                fs::create_dir(temp.join(path)).map_err(io)?;
            }
            for path in FILES.into_iter().chain(["runtime.json"]) {
                let bytes = read_regular(&self.root.join(path), MAX_FILE)?;
                let mut f = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(temp.join(path))
                    .map_err(io)?;
                f.write_all(&bytes).map_err(io)?;
                if path == "bin/producer" {
                    set_executable(&f)?;
                }
                f.sync_all().map_err(io)?;
            }
            Self::load(&temp, Some(&hash(&self.bytes)))?;
            for path in ["bin", "contract", "spkg", ""] {
                File::open(temp.join(path))
                    .map_err(io)?
                    .sync_all()
                    .map_err(io)?;
            }
            backfill_common::dynamic_sources_v2::seal::rename_no_replace(&temp, &dest)
                .map_err(refuse)?;
            File::open(&parent).map_err(io)?.sync_all().map_err(io)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_dir_all(&temp);
        }
        result
    }
}
/// The supported package subset is deliberately bounded: v1 map/store graph,
/// no network overrides, block filters, foundational stores or unknown module
/// fields. The module hash follows Substreams v1.18.4's manifest/signature.go.
pub fn verify_package(bytes: &[u8], identity: &ExtractorIdentity) -> Result<()> {
    require(
        identity.spkg_sha256 == hash(bytes)
            && identity.module == crate::identity::OUTPUT_MODULE
            && identity.output_type == crate::identity::OUTPUT_TYPE
            && identity.initial_block == INITIAL_BLOCK
            && digest(&identity.module_hash, 40),
        "package identity mismatch",
    )?;
    package::verify(bytes, identity)
}
pub fn hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
pub fn pin(bytes: &[u8]) -> FilePin {
    FilePin {
        bytes: bytes.len() as u64,
        sha256: hash(bytes),
    }
}
pub fn json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec_pretty(value).map_err(|e| refuse(e.to_string()))?;
    bytes.push(b'\n');
    Ok(bytes)
}
fn json<T: for<'a> Deserialize<'a> + Serialize>(bytes: &[u8]) -> Result<T> {
    let value: T = serde_json::from_slice(bytes).map_err(|e| refuse(e.to_string()))?;
    require(
        json_bytes(&value)? == bytes,
        "noncanonical JSON (or duplicate fields)",
    )?;
    Ok(value)
}
fn digest(s: &str, n: usize) -> bool {
    s.len() == n
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn safe_path(p: &str) -> bool {
    !p.contains(['\\', ':', '\0']) && p.split('/').all(|s| !s.is_empty() && s != "." && s != "..")
}
fn io(e: std::io::Error) -> crate::ReducerError {
    refuse(e.to_string())
}
fn read_regular(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let m = fs::symlink_metadata(path).map_err(io)?;
    require(
        m.is_file() && m.len() <= limit,
        "runtime path is not a bounded regular file",
    )?;
    let mut data = Vec::new();
    File::open(path)
        .map_err(io)?
        .take(limit + 1)
        .read_to_end(&mut data)
        .map_err(io)?;
    require(data.len() as u64 <= limit, "runtime file grew beyond limit")?;
    Ok(data)
}
fn inventory(root: &Path) -> Result<BTreeSet<String>> {
    fn walk(root: &Path, current: &Path, files: &mut BTreeSet<String>) -> Result<()> {
        for item in fs::read_dir(current).map_err(io)? {
            let item = item.map_err(io)?;
            let path = item.path();
            let relative = path
                .strip_prefix(root)
                .map_err(|e| refuse(e.to_string()))?
                .to_str()
                .ok_or_else(|| refuse("non UTF-8 runtime path"))?
                .to_owned();
            let kind = item.file_type().map_err(io)?;
            if kind.is_dir() {
                require(
                    ["bin", "contract", "spkg"].contains(&relative.as_str()),
                    "unexpected runtime directory",
                )?;
                walk(root, &path, files)?;
            } else {
                require(kind.is_file(), "runtime symlink or special file refused")?;
                files.insert(relative);
            }
        }
        Ok(())
    }
    let mut files = BTreeSet::new();
    walk(root, root, &mut files)?;
    Ok(files)
}
#[cfg(unix)]
fn executable(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    require(
        fs::metadata(path).map_err(io)?.permissions().mode() & 0o111 != 0,
        "producer is not executable",
    )
}
#[cfg(not(unix))]
fn executable(_: &Path) -> Result<()> {
    Err(refuse("runtime requires Unix executable semantics"))
}
#[cfg(unix)]
fn set_executable(f: &File) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    f.set_permissions(fs::Permissions::from_mode(0o755))
        .map_err(io)
}
#[cfg(not(unix))]
fn set_executable(_: &File) -> Result<()> {
    Err(refuse("runtime requires Unix executable semantics"))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        for path in ["bin", "contract", "spkg"] {
            fs::create_dir(dir.path().join(path)).unwrap();
        }
        let (package, identity) = package::fixture();
        let commit = "ab".repeat(20);
        let descriptor = crate::identity::build_descriptor(&identity, &commit, true).unwrap();
        let source = SourceManifest {
            format: "pinax.backfill.producer-source/v1".into(),
            repository: "pinax-network/substreams-backfills".into(),
            source_commit: commit.clone(),
            files: BTreeMap::from([("Cargo.toml".into(), pin(b"source fixture"))]),
        };
        let lock = ExtractorLock {
            format: "pinax.backfill.extractor-lock/v1".into(),
            source_commit: "cd".repeat(20),
            production_selectable: false,
            identity: identity.clone(),
        };
        let contents = BTreeMap::from([
            ("bin/producer", b"test executable\n".to_vec()),
            ("contract/block-changes-descriptor.json", descriptor.clone()),
            (
                "contract/block-changes-descriptor.json.sha256",
                format!("{}\n", hash(&descriptor)).into_bytes(),
            ),
            (
                "contract/compatibility.json",
                json_bytes(&FamilyContract::aerodrome()).unwrap(),
            ),
            ("source.json", json_bytes(&source).unwrap()),
            (
                "spkg/extractor-identity.json",
                json_bytes(&identity).unwrap(),
            ),
            ("spkg/extractor-lock.json", json_bytes(&lock).unwrap()),
            ("spkg/extractor.spkg", package),
        ]);
        let files = contents
            .iter()
            .map(|(p, b)| ((*p).into(), pin(b)))
            .collect();
        for (path, bytes) in contents {
            fs::write(dir.path().join(path), bytes).unwrap();
        }
        set_executable(&File::open(dir.path().join("bin/producer")).unwrap()).unwrap();
        let manifest = RuntimeManifest {
            format: FORMAT.into(),
            protocol: PROTOCOL.into(),
            family: FAMILY.into(),
            production_selectable: false,
            source_commit: commit,
            files,
        };
        fs::write(
            dir.path().join("runtime.json"),
            json_bytes(&manifest).unwrap(),
        )
        .unwrap();
        dir
    }
    fn reseal(root: &Path) {
        let mut m: RuntimeManifest = json(&fs::read(root.join("runtime.json")).unwrap()).unwrap();
        for (p, pin) in &mut m.files {
            *pin = super::pin(&fs::read(root.join(p)).unwrap());
        }
        fs::write(root.join("runtime.json"), json_bytes(&m).unwrap()).unwrap();
    }
    #[test]
    fn closed_bundle_binds_independent_lock_and_checkpoint_family() {
        let d = fixture();
        let raw = fs::read(d.path().join("runtime.json")).unwrap();
        let v = VerifiedRuntime::load(d.path(), Some(&hash(&raw))).unwrap();
        assert_eq!(v.manifest().family, FAMILY);
        assert_eq!(v.producer_binding().family, CHECKPOINT_FAMILY);
        assert_eq!(
            v.producer_binding().extractor_lock_sha256,
            hash(&fs::read(d.path().join("spkg/extractor-lock.json")).unwrap())
        );
        assert_ne!(
            v.producer_binding().extractor_lock_sha256,
            hash(v.manifest_bytes())
        );
        assert!(v.verify_running_executable().is_err());
        assert!(VerifiedRuntime::load(d.path(), Some(&"00".repeat(32))).is_err());
    }
    #[test]
    fn every_payload_mutation_refuses_before_bindings_exist() {
        for path in FILES {
            let d = fixture();
            let mut b = fs::read(d.path().join(path)).unwrap();
            b.push(b'!');
            fs::write(d.path().join(path), b).unwrap();
            assert!(VerifiedRuntime::load(d.path(), None).is_err(), "{path}");
        }
    }
    #[test]
    fn self_rehashed_identity_claims_do_not_override_actual_contracts() {
        for path in [
            "source.json",
            "contract/compatibility.json",
            "spkg/extractor-lock.json",
            "spkg/extractor-identity.json",
        ] {
            let d = fixture();
            let p = d.path().join(path);
            let bytes = fs::read(&p).unwrap();
            let changed = match path {
                "source.json" => {
                    let mut x: SourceManifest = json(&bytes).unwrap();
                    x.source_commit = "fe".repeat(20);
                    json_bytes(&x).unwrap()
                }
                "contract/compatibility.json" => {
                    let mut x: FamilyContract = json(&bytes).unwrap();
                    x.producer_checkpoint_family = FAMILY.into();
                    json_bytes(&x).unwrap()
                }
                "spkg/extractor-lock.json" => {
                    let mut x: ExtractorLock = json(&bytes).unwrap();
                    x.identity.module_hash = "00".repeat(20);
                    json_bytes(&x).unwrap()
                }
                _ => {
                    let mut x: ExtractorIdentity = json(&bytes).unwrap();
                    x.module_hash = "00".repeat(20);
                    json_bytes(&x).unwrap()
                }
            };
            fs::write(p, changed).unwrap();
            reseal(d.path());
            assert!(VerifiedRuntime::load(d.path(), None).is_err(), "{path}");
        }
        let d = fixture();
        let p = d.path().join("runtime.json");
        let mut m: RuntimeManifest = json(&fs::read(&p).unwrap()).unwrap();
        m.production_selectable = true;
        fs::write(p, json_bytes(&m).unwrap()).unwrap();
        assert!(VerifiedRuntime::load(d.path(), None).is_err());
    }
    #[test]
    fn inventory_traversal_symlinks_and_extra_physical_profile_refuse() {
        let d = fixture();
        fs::write(d.path().join("physical-profile.json"), b"{}").unwrap();
        assert!(VerifiedRuntime::load(d.path(), None).is_err());
        let d = fixture();
        let p = d.path().join("runtime.json");
        let mut m: RuntimeManifest = json(&fs::read(&p).unwrap()).unwrap();
        m.files.insert("../escape".into(), pin(b"x"));
        fs::write(p, json_bytes(&m).unwrap()).unwrap();
        assert!(VerifiedRuntime::load(d.path(), None).is_err());
        #[cfg(unix)]
        {
            let d = fixture();
            fs::rename(d.path().join("source.json"), d.path().join("outside")).unwrap();
            std::os::unix::fs::symlink("outside", d.path().join("source.json")).unwrap();
            assert!(VerifiedRuntime::load(d.path(), None).is_err());
        }
    }
    #[test]
    fn stage_revalidates_and_never_clobbers_destination() {
        let d = fixture();
        let v = VerifiedRuntime::load(d.path(), None).unwrap();
        let out = tempfile::tempdir().unwrap();
        let target = out.path().join("bundle");
        v.stage(&target).unwrap();
        assert_eq!(
            fs::read(target.join("runtime.json")).unwrap(),
            v.manifest_bytes()
        );
        VerifiedRuntime::load(&target, Some(&hash(v.manifest_bytes()))).unwrap();
        assert!(v.stage(&target).is_err());
        assert_eq!(
            fs::read(target.join("runtime.json")).unwrap(),
            v.manifest_bytes()
        );
        fs::write(d.path().join("bin/producer"), b"changed").unwrap();
        assert!(v.stage(&out.path().join("refused")).is_err());
        assert!(!out.path().join("refused").exists());
        assert_eq!(fs::read_dir(out.path()).unwrap().count(), 1);
    }
}
