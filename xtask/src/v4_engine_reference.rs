//! Fail-closed verification for the Uniswap V4 engine v0.5.0 reference
//! capsule (port of `scripts/verify-uniswap-v4-engine-reference.py`, #110).
//!
//! The capsule under `docs/provenance/uniswap-v4-engine-v0.5.0/` retains
//! byte-locked copies of engine fixtures plus a closure manifest. This module
//! checks the capsule inventory, every byte lock, the closure's exact shape
//! and all-false operational gates, the imported Store-state package and its
//! three locked reference files, and the semantic cross-references between
//! the retained certificate, benchmark, parity, GraphQL, lifecycle, and
//! overlap fixtures. Every expectation is a literal from the Python verifier.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::path::{Component, Path, PathBuf};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub const CONTRACT: &str = "uniswap-v4-engine-v0.5.0-reference/v1";
pub const CAPSULE_DIRECTORY: &str = "docs/provenance/uniswap-v4-engine-v0.5.0";
pub const CLOSURE_PATH: &str = "docs/provenance/uniswap-v4-engine-v0.5.0/closure.json";
pub const PACKAGE_PATH: &str =
    "uniswap-v4/release/v0.4.0/uniswap-v4-base-store-state-reducer-v0.4.0.spkg";
pub const PACKAGE_CONTRACT_PATH: &str = "uniswap-v4/packages/base-uniswap-v4-v0.4.0.json";
pub const IMPORT_PROVENANCE_PATH: &str = "docs/provenance/uniswap-v4-v0.4.1.json";
pub const IMPORT_INVENTORY_PATH: &str = "docs/provenance/uniswap-v4-v0.4.1-files.json";
pub const DEPLOYMENT: &str = "Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB";
pub const IMPORTED_SPKG_SHA256: &str =
    "bc8a841dbb74f9bbc7d90826251ab766ad350170a4832fc3e9b084664d22254a";
pub const LEGACY_SPKG_SHA256: &str =
    "44520f81a7177af201aa89cd0645f3c9fdf8a50200da1a9232e6335bfecf1a0d";

/// Byte lock for one retained capsule file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileLock {
    pub local_path: &'static str,
    pub source_path: &'static str,
    pub role: &'static str,
    pub bytes: u64,
    pub sha256: String,
    pub git_blob: &'static str,
}

/// Locks are a value so adversarial tests can move a byte lock and prove the
/// semantic cross-reference checks still fail closed.
pub fn expected_file_locks() -> Vec<FileLock> {
    vec![
        FileLock {
            local_path: "compatibility.json",
            source_path: "adapters/uniswap-v4-base/compatibility.json",
            role: "engine-compatibility-contract",
            bytes: 7490,
            sha256: "fafd21c63a23925327a17db315cb8a5cf7a8127c07401ab08e0c37b8920ea65c".into(),
            git_blob: "c309986c1b70443111541705d97663b1c15d1068",
        },
        FileLock {
            local_path: "certificate.json",
            source_path: "fixtures/kan-base-v4-store-state-100k-certificate.json",
            role: "retained-100k-certificate",
            bytes: 1976,
            sha256: "2ee4bd2986269361a3490c2dd87e1c775d4ac528fa898ab6093c1a1fa356ff33".into(),
            git_blob: "594a383fca4e18823f28bf96f377bc61af64d274",
        },
        FileLock {
            local_path: "benchmark.json",
            source_path: "fixtures/kan-base-v4-store-state-100k-benchmark.json",
            role: "retained-frame-checkpoint-benchmark",
            bytes: 1899,
            sha256: "a5ab9fbfc75a2d00698d49da648d7d0b9b1b5d3f209ac9eb685a4991f58248ae".into(),
            git_blob: "a983471b329a11a51be14376ffd4af46733aa19b",
        },
        FileLock {
            local_path: "parity.json",
            source_path: "fixtures/kan-base-v4-store-state-100k-parity.json",
            role: "retained-20-table-physical-and-poi-parity",
            bytes: 5623,
            sha256: "f337a01844fafd45881ad4b24fdfa6220d4a37598afe506ab5c8552813a10388".into(),
            git_blob: "ce2fe3367846ba2d622d5eb7a46d1a9ebfa3fb58",
        },
        FileLock {
            local_path: "graphql.json",
            source_path: "fixtures/kan-base-v4-store-state-graphql.json",
            role: "retained-head-and-graphql-parity",
            bytes: 556,
            sha256: "3cc7aee86dadf4dbb5abbf454e897a469bc24ca7050f39e64b9c300640497d96".into(),
            git_blob: "d285d18c04b3fa3d767885042fab289a9c0b05ce",
        },
        FileLock {
            local_path: "lifecycle.json",
            source_path: "fixtures/kan-base-v4-store-state-lifecycle.json",
            role: "historical-legacy-candidate-lifecycle-support",
            bytes: 2598,
            sha256: "45fef8b545251e912c7e4e6dac517b2c2f4e6452d61a09af5eeadb7f206857ea".into(),
            git_blob: "8710ab18321a057324679f7871ffaa49198ed522",
        },
        FileLock {
            local_path: "overlap.json",
            source_path: "fixtures/kan-base-v4-store-state-sharded-overlap.json",
            role: "separate-range-sharded-package-overlap-support",
            bytes: 686,
            sha256: "8a5f67a511d219be9e361b1661e13320903ae94a13a31788c0cb60bf25e3df61".into(),
            git_blob: "73a9c55ffed0769ed591c84074f34b4db65e5e4c",
        },
    ]
}

pub const REFERENCE_FILE_LOCKS: &[(&str, u64, &str)] = &[
    (
        PACKAGE_CONTRACT_PATH,
        3718,
        "e6e279232b62104a15d355b48fdead8203c0e1adffee8bc46de35d44644e39d4",
    ),
    (
        IMPORT_PROVENANCE_PATH,
        3241,
        "bdd4d895ea3c0d913eb834766781b683e4dbd6cbf26f89c5516b2bf81a0a71fc",
    ),
    (
        IMPORT_INVENTORY_PATH,
        25724,
        "d173b5d8d6ba127df4e1396356474a364fd96e0f95acaf91fbe64712917c3b42",
    ),
];

fn expected_source() -> Value {
    json!({
        "repository": "pinax-network/substreams-graph-node-backfill",
        "tag": "v0.5.0",
        "commit": "2b5ef82e2db987a5bfe861330aba0a222956122e",
        "tree": "d1f8c5973ee2177a3a4cdae75717efb939e5da95",
    })
}

const ENGINE_IMAGE: &str = "ghcr.io/pinax-network/substreams-graph-node-backfill@sha256:dbb88e451dbd44fd3e412f1d6814939cbc2a0b93c539837ebfb1f28d3dd1711e";

fn expected_engine() -> Value {
    json!({
        "release": "v0.5.0",
        "platform": "linux/amd64",
        "image": ENGINE_IMAGE,
        "binary_sha256": {
            "state-replay": "de05b611bc53e99ff695d8e0426ed619c27244947130b8b12ca4591c6fa68390",
            "parquet-backfill": "82554a1ab6573279ff564937cd50a5b7fb52ae39837c0f88fba6d341517709b9",
            "postgres-spool-load": "34886bb9c868974eb5f4844a323d76960ff9730fd4dd024e778ed6375d2824e5",
            "substreams-native": "4d8bdd9077551b4f7b55105828721d6fca252de96e30c625c4912d5bb2097ddf",
        },
        "graph_node": {
            "version": "v0.44.0",
            "commit": "77823b5a7adc4eac4abf03202c8dd7cb00dea31d",
            "dump_format": 1,
        },
    })
}

const PACKAGE_BYTES: u64 = 1458573;
const PACKAGE_GIT_BLOB: &str = "c1b32733c3949bb754bffc773d954aa3008c72b6";
const PACKAGE_REPOSITORY: &str = "pinax-network/substreams-v4-subgraph";
const PACKAGE_SOURCE_TAG: &str = "v0.4.1";
const PACKAGE_SOURCE_COMMIT: &str = "6812a4deaa5a520020e8d727e17f6d0b7113d0a9";
const PACKAGE_SOURCE_TREE: &str = "2d60d30242443adc2c021a5b609c27edcb75128a";
const PACKAGE_RELEASE_TAG: &str = "v0.4.0";
const PACKAGE_RELEASE_COMMIT: &str = "7609dc67ce83865a16e441ff2b3b56db6c46ee2a";
const PACKAGE_NAME: &str = "uniswap_v4_base_store_state_reducer";
const PACKAGE_VERSION: &str = "v0.4.0";
const PACKAGE_NETWORK: &str = "base";
const PACKAGE_MODULE: &str = "map_store_state_inputs";
const PACKAGE_MODULE_HASH: &str = "223408b90abae80960c41e11205fad2294accfa9";
const PACKAGE_OUTPUT_TYPE: &str = "proto:pinax.uniswap.v4.base.store.v1.ReducerInputs";
const PACKAGE_INITIAL_BLOCK: u64 = 25350988;
const PACKAGE_ASSET_NAME: &str = "uniswap-v4-base-store-state-reducer-v0.4.0.spkg";

fn expected_package() -> Value {
    json!({
        "path": PACKAGE_PATH,
        "bytes": PACKAGE_BYTES,
        "sha256": IMPORTED_SPKG_SHA256,
        "git_blob": PACKAGE_GIT_BLOB,
        "repository": PACKAGE_REPOSITORY,
        "source_tag": PACKAGE_SOURCE_TAG,
        "source_commit": PACKAGE_SOURCE_COMMIT,
        "source_tree": PACKAGE_SOURCE_TREE,
        "production_release_tag": PACKAGE_RELEASE_TAG,
        "production_release_commit": PACKAGE_RELEASE_COMMIT,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "network": PACKAGE_NETWORK,
        "module": PACKAGE_MODULE,
        "module_hash": PACKAGE_MODULE_HASH,
        "output_type": PACKAGE_OUTPUT_TYPE,
        "initial_block": PACKAGE_INITIAL_BLOCK,
    })
}

const SEED_BLOCK: u64 = 32374154;
const START_BLOCK: u64 = 32374155;
const END_BLOCK: u64 = 32474154;
const RANGE_BLOCKS: u64 = 100000;
const SEED_HASH: &str = "b4b30252f3b6c183c9b5b36341bd5c1ebb50a87811753d1976b69c01c09e05d4";
const END_HASH: &str = "e2c6b741291ec233e265848784944b7ea33469dd7422b013e537967d0ad79bf9";

fn expected_range() -> Value {
    json!({
        "seed_block": SEED_BLOCK,
        "start_block": START_BLOCK,
        "end_block": END_BLOCK,
        "blocks": RANGE_BLOCKS,
        "seed_hash": SEED_HASH,
        "end_hash": END_HASH,
    })
}

pub const EXPECTED_TABLES: &[&str] = &[
    "pool_manager",
    "bundle",
    "token",
    "pool",
    "tick",
    "uniswap_day_data",
    "pool_day_data",
    "pool_hour_data",
    "token_day_data",
    "token_hour_data",
    "position",
    "arrakis_hook",
    "poi2$",
    "transaction",
    "swap",
    "modify_liquidity",
    "subscribe",
    "unsubscribe",
    "transfer",
    "data_sources$",
];

fn expected_poi() -> Value {
    json!({
        "table": "poi2$",
        "local_rows": 86343,
        "source_rows": 86343,
        "local_digest": "906139fe973ba753f93bdc6ac41ee42a8d1dfa33857b065c02007bd08feb41cc",
        "source_digest": "906139fe973ba753f93bdc6ac41ee42a8d1dfa33857b065c02007bd08feb41cc",
    })
}

const HISTORICAL_INT_GATES: &[(&str, i64)] = &[
    ("tables_matched", 20),
    ("tables_mismatched", 0),
    ("vid_sequences_valid", 20),
];
const HISTORICAL_BOOL_GATES: &[&str] = &[
    "stopped_physical_clone",
    "graft_parent_preserved",
    "graphql_exact",
    "poi_exact",
    "no_op_resume",
    "graph_node_continuation",
    "graph_node_restart",
    "graph_node_rewind",
    "graph_node_replay",
    "sharded_overlap_byte_identical",
];

pub const EXPECTED_GATES: &[&str] = &[
    "reproduction_complete",
    "scratch_target_named",
    "scratch_target_disposable",
    "scratch_target_stopped",
    "independent_zero_writer_proven",
    "k3_runtime_contract_approved",
    "workflow_submission_authorized",
    "workflow_submitted",
    "database_write_authorized",
    "database_mutation_performed",
    "source_database_mutation_performed",
    "recovery_database_mutation_performed",
    "existing_v4_workflow_mutation_performed",
    "readiness",
    "backfill_ready",
    "production_ready",
    "promotion_eligible",
];

fn expected_missing_reference_bytes() -> Value {
    json!([
        "selected 100k runtime checkpoint manifest bytes and SHA-256",
        "selected 100k literal COPY spool filenames and file digests",
        "selected 100k frame payload bytes",
        "selected 100k checkpoint bytes",
    ])
}

fn expected_protected_resources() -> Value {
    json!({
        "source_database": {"schema": "sgd1246", "mutation_authorized": false, "mutation_performed": false},
        "recovery_database": {"schema": "sgd5303", "mutation_authorized": false, "mutation_performed": false},
        "existing_v4_workflow": {"identifier": null, "mutation_authorized": false, "mutation_performed": false},
    })
}

fn expected_non_claims() -> Value {
    json!([
        "The retained 100k range has not been reproduced with engine v0.5.0 or the imported sharded package.",
        "The historical sgd2 target is not authorization to reuse it and no new scratch target is named.",
        "No independent zero-writer evidence, K3 approval, workflow authorization, workflow submission, or database write is represented.",
        "The lifecycle fixture is historical support from a 189-block legacy-candidate continuation, not v0.5.0 evidence.",
        "The overlap fixture is a separate-range package-equivalence result, not reproduction of the selected 100k range.",
        "This capsule does not establish backfill, production, release, or promotion readiness.",
    ])
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerificationError(pub String);

impl fmt::Display for VerificationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for VerificationError {}

pub type Result<T> = std::result::Result<T, VerificationError>;

fn require(condition: bool, message: impl Into<String>) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(VerificationError(message.into()))
    }
}

/// `json.loads(..., object_pairs_hook=reject_duplicate_keys)`: a strict parse
/// that refuses duplicate object keys at any depth.
pub fn load_json_strict(text: &str, label: &str) -> Result<Value> {
    fn check(value: &Value) -> Option<String> {
        match value {
            Value::Object(map) => map.values().find_map(check),
            Value::Array(items) => items.iter().find_map(check),
            _ => None,
        }
    }
    // serde_json's default Map silently keeps the last duplicate, so scan
    // the raw text with a tiny tokenizer that tracks object-key sets.
    if let Some(key) = first_duplicate_key(text) {
        return Err(VerificationError(format!("duplicate JSON key: {key}")));
    }
    let value: Value = serde_json::from_str(text)
        .map_err(|e| VerificationError(format!("cannot load JSON {label}: {e}")))?;
    let _ = check(&value);
    Ok(value)
}

fn first_duplicate_key(text: &str) -> Option<String> {
    #[derive(Default)]
    struct Frame {
        is_object: bool,
        keys: BTreeSet<String>,
        expecting_key: bool,
    }
    let bytes = text.as_bytes();
    let mut stack: Vec<Frame> = Vec::new();
    let mut i = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b'{' => {
                stack.push(Frame {
                    is_object: true,
                    keys: BTreeSet::new(),
                    expecting_key: true,
                });
                i += 1;
            }
            b'[' => {
                stack.push(Frame {
                    is_object: false,
                    keys: BTreeSet::new(),
                    expecting_key: false,
                });
                i += 1;
            }
            b'}' | b']' => {
                stack.pop();
                i += 1;
            }
            b',' => {
                if let Some(frame) = stack.last_mut() {
                    if frame.is_object {
                        frame.expecting_key = true;
                    }
                }
                i += 1;
            }
            b'"' => {
                let mut j = i + 1;
                let mut out = String::new();
                while j < bytes.len() && bytes[j] != b'"' {
                    if bytes[j] == b'\\' {
                        j += 1;
                    }
                    if j < bytes.len() {
                        out.push(bytes[j] as char);
                    }
                    j += 1;
                }
                if let Some(frame) = stack.last_mut() {
                    if frame.is_object && frame.expecting_key {
                        frame.expecting_key = false;
                        if !frame.keys.insert(out.clone()) {
                            return Some(out);
                        }
                    }
                }
                i = j + 1;
            }
            _ => i += 1,
        }
    }
    None
}

fn load_json(path: &Path) -> Result<Value> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| VerificationError(format!("cannot load JSON {}: {e}", path.display())))?;
    load_json_strict(&text, &path.display().to_string())
}

fn require_exact_keys(value: &Value, expected: &[&str], context: &str) -> Result<()> {
    let Some(map) = value.as_object() else {
        return Err(VerificationError(format!("{context} must be an object")));
    };
    let actual: BTreeSet<&str> = map.keys().map(String::as_str).collect();
    let expected_set: BTreeSet<&str> = expected.iter().copied().collect();
    let missing: Vec<&&str> = expected_set.difference(&actual).collect();
    let extra: Vec<&&str> = actual.difference(&expected_set).collect();
    require(
        missing.is_empty() && extra.is_empty(),
        format!("{context} keys drift: missing={missing:?}, extra={extra:?}"),
    )
}

fn require_regular_file(root: &Path, relative: &str, context: &str) -> Result<PathBuf> {
    let rel = Path::new(relative);
    require(
        !rel.is_absolute(),
        format!("{context} path must be relative"),
    )?;
    require(
        !rel.components().any(|c| matches!(c, Component::ParentDir)),
        format!("{context} path escapes repository"),
    )?;
    let mut component = root.to_path_buf();
    for part in rel.components() {
        component.push(part);
        let meta = component
            .symlink_metadata()
            .map_err(|e| VerificationError(format!("{context} is unavailable: {relative}: {e}")))?;
        require(
            !meta.file_type().is_symlink(),
            format!("{context} path contains a symlink: {relative}"),
        )?;
    }
    let path = root.join(rel);
    let meta = path
        .symlink_metadata()
        .map_err(|e| VerificationError(format!("{context} is unavailable: {relative}: {e}")))?;
    require(
        meta.is_file(),
        format!("{context} must be a regular file: {relative}"),
    )?;
    let resolved = path
        .canonicalize()
        .map_err(|e| VerificationError(format!("{context} is unavailable: {relative}: {e}")))?;
    let root_resolved = root
        .canonicalize()
        .map_err(|e| VerificationError(format!("root is unavailable: {e}")))?;
    require(
        resolved.starts_with(&root_resolved),
        format!("{context} escapes repository: {relative}"),
    )?;
    Ok(path)
}

fn sha256_file(path: &Path) -> Result<(u64, String)> {
    let payload = std::fs::read(path)
        .map_err(|e| VerificationError(format!("cannot read {}: {e}", path.display())))?;
    Ok((payload.len() as u64, hex::encode(Sha256::digest(&payload))))
}

fn expected_file_records(locks: &[FileLock]) -> Value {
    Value::Array(
        locks
            .iter()
            .map(|lock| {
                json!({
                    "local_path": lock.local_path,
                    "source_path": lock.source_path,
                    "role": lock.role,
                    "bytes": lock.bytes,
                    "sha256": lock.sha256,
                    "git_blob": lock.git_blob,
                })
            })
            .collect(),
    )
}

fn verify_inventory(root: &Path, locks: &[FileLock]) -> Result<()> {
    let capsule = root.join(CAPSULE_DIRECTORY);
    let meta = capsule
        .symlink_metadata()
        .map_err(|e| VerificationError(format!("capsule directory is unavailable: {e}")))?;
    require(
        !meta.file_type().is_symlink(),
        "capsule directory must not be a symlink",
    )?;
    require(meta.is_dir(), "capsule path must be a directory")?;
    let mut expected: BTreeSet<String> = locks.iter().map(|l| l.local_path.to_string()).collect();
    expected.insert("closure.json".into());
    expected.insert("README.md".into());
    let mut actual = BTreeSet::new();
    let mut children = BTreeSet::new();
    for entry in std::fs::read_dir(&capsule)
        .map_err(|e| VerificationError(format!("capsule directory is unavailable: {e}")))?
    {
        let entry = entry.map_err(|e| VerificationError(e.to_string()))?;
        let name = entry.file_name().to_string_lossy().to_string();
        let meta = entry
            .path()
            .symlink_metadata()
            .map_err(|e| VerificationError(e.to_string()))?;
        require(
            !meta.file_type().is_symlink(),
            format!("capsule entry must not be a symlink: {name}"),
        )?;
        if name == "q8" {
            require(meta.is_dir(), "q8 child capsule must be a directory")?;
            children.insert(name);
            continue;
        }
        require(
            meta.is_file(),
            format!("capsule contains an unexpected directory: {name}"),
        )?;
        actual.insert(name);
    }
    require(
        children == BTreeSet::from(["q8".to_string()]),
        "q8 child capsule inventory drift",
    )?;
    let missing: Vec<&String> = expected.difference(&actual).collect();
    let extra: Vec<&String> = actual.difference(&expected).collect();
    require(
        missing.is_empty() && extra.is_empty(),
        format!("capsule file inventory drift: missing={missing:?}, extra={extra:?}"),
    )
}

fn verify_file_locks(
    root: &Path,
    closure: &Value,
    locks: &[FileLock],
) -> Result<BTreeMap<String, Value>> {
    require(
        closure["files"] == expected_file_records(locks),
        "closure source file records drift",
    )?;
    let mut loaded = BTreeMap::new();
    for lock in locks {
        let relative = format!("{CAPSULE_DIRECTORY}/{}", lock.local_path);
        let path = require_regular_file(root, &relative, &format!("retained {}", lock.local_path))?;
        let (bytes, sha) = sha256_file(&path)?;
        require(
            bytes == lock.bytes,
            format!("{} byte length drift: {bytes}", lock.local_path),
        )?;
        require(
            sha == lock.sha256,
            format!("{} SHA-256 drift: {sha}", lock.local_path),
        )?;
        loaded.insert(lock.local_path.to_string(), load_json(&path)?);
    }
    Ok(loaded)
}

fn is_int(value: &Value) -> bool {
    value.is_i64() || value.is_u64()
}

fn verify_closure_shape(closure: &Value) -> Result<()> {
    require_exact_keys(
        closure,
        &[
            "format_version",
            "contract",
            "status",
            "scope",
            "source",
            "files",
            "engine",
            "imported_package",
            "selected_reference",
            "supporting_evidence",
            "protected_resources",
            "missing_reference_bytes",
            "gates",
            "non_claims",
        ],
        "closure",
    )?;
    require(
        closure["format_version"] == json!(1),
        "closure format version drift",
    )?;
    require(
        closure["contract"] == json!(CONTRACT),
        "closure contract drift",
    )?;
    require(
        closure["status"] == json!("pre-execution-reference-only"),
        "closure status overclaims execution",
    )?;
    require(
        closure["scope"]
            == json!({
                "repository": "pinax-network/substreams-backfills",
                "github_issue": 26,
                "supports_acceptance_criteria": [1, 2],
                "fully_satisfied_acceptance_criteria": [1],
                "partially_satisfied_acceptance_criteria": [2],
                "unsupported_acceptance_criteria": [3, 4, 5, 6, 7, 8],
            }),
        "issue #26 acceptance-criteria scope drift",
    )?;
    for key in [
        "supports_acceptance_criteria",
        "fully_satisfied_acceptance_criteria",
        "partially_satisfied_acceptance_criteria",
        "unsupported_acceptance_criteria",
    ] {
        require(
            closure["scope"][key]
                .as_array()
                .is_some_and(|items| items.iter().all(is_int)),
            "acceptance-criteria identifiers must be integers",
        )?;
    }
    require(
        closure["source"] == expected_source(),
        "tagged engine source identity drift",
    )?;
    require(
        closure["engine"] == expected_engine(),
        "engine v0.5.0 identity drift",
    )?;
    require(
        is_int(&closure["engine"]["graph_node"]["dump_format"]),
        "Graph Node dump format must be an integer",
    )?;
    require(
        closure["imported_package"] == expected_package(),
        "imported package closure identity drift",
    )?;
    require(
        is_int(&closure["imported_package"]["initial_block"]),
        "imported package initial block must be an integer",
    )?;
    require_exact_keys(
        &closure["supporting_evidence"],
        &["lifecycle", "sharded_overlap"],
        "supporting evidence",
    )?;
    require(
        closure["protected_resources"] == expected_protected_resources(),
        "protected-resource boundary drift",
    )?;
    let flags_false = closure["protected_resources"]
        .as_object()
        .is_some_and(|resources| {
            resources.values().all(|resource| {
                resource.as_object().is_some_and(|fields| {
                    fields
                        .iter()
                        .filter(|(k, _)| {
                            matches!(k.as_str(), "mutation_authorized" | "mutation_performed")
                        })
                        .all(|(_, v)| *v == Value::Bool(false))
                })
            })
        });
    require(
        flags_false,
        "protected-resource mutation flags must be false booleans",
    )?;
    require_exact_keys(&closure["gates"], EXPECTED_GATES, "operational gates")?;
    require(
        EXPECTED_GATES
            .iter()
            .all(|gate| closure["gates"][*gate] == Value::Bool(false)),
        "operational gate drift",
    )?;
    require(
        closure["missing_reference_bytes"] == expected_missing_reference_bytes(),
        "missing-reference disclosure drift",
    )?;
    require(
        closure["non_claims"] == expected_non_claims(),
        "non-claim boundary drift",
    )
}

fn verify_imported_package(root: &Path, closure: &Value, compatibility: &Value) -> Result<()> {
    let package = require_regular_file(root, PACKAGE_PATH, "imported Store-state SPKG")?;
    let (bytes, sha) = sha256_file(&package)?;
    require(bytes == PACKAGE_BYTES, "imported SPKG byte length drift")?;
    require(sha == IMPORTED_SPKG_SHA256, "imported SPKG SHA-256 drift")?;

    let mut locked: BTreeMap<&str, PathBuf> = BTreeMap::new();
    for (relative, expected_bytes, expected_sha) in REFERENCE_FILE_LOCKS {
        let path = require_regular_file(root, relative, &format!("locked reference {relative}"))?;
        let observed = sha256_file(&path)?;
        require(
            observed == (*expected_bytes, expected_sha.to_string()),
            format!("{relative} byte/SHA-256 drift: got {observed:?}, expected ({expected_bytes}, {expected_sha:?})"),
        )?;
        locked.insert(relative, path);
    }
    let package_contract = load_json(&locked[PACKAGE_CONTRACT_PATH])?;
    let provenance = load_json(&locked[IMPORT_PROVENANCE_PATH])?;
    let inventory = load_json(&locked[IMPORT_INVENTORY_PATH])?;

    require_exact_keys(
        &package_contract,
        &[
            "format_version",
            "network",
            "deployment",
            "initial_block",
            "repository",
            "release",
            "historical_build_repository",
            "packages",
        ],
        "V4 package contract",
    )?;
    require(
        package_contract["format_version"] == json!(1)
            && package_contract["network"] == json!(PACKAGE_NETWORK)
            && package_contract["deployment"] == json!(DEPLOYMENT)
            && package_contract["initial_block"] == json!(PACKAGE_INITIAL_BLOCK)
            && package_contract["repository"] == json!(PACKAGE_REPOSITORY)
            && package_contract["release"] == json!(PACKAGE_RELEASE_TAG),
        "V4 package contract root identity drift",
    )?;
    let state_contract = &package_contract["packages"]["store_state"];
    for (key, expected) in [
        ("asset", json!(PACKAGE_ASSET_NAME)),
        ("sha256", json!(IMPORTED_SPKG_SHA256)),
        ("package_name", json!(PACKAGE_NAME)),
        ("package_version", json!(PACKAGE_VERSION)),
        ("module", json!(PACKAGE_MODULE)),
        ("module_hash", json!(PACKAGE_MODULE_HASH)),
        ("output_type", json!(PACKAGE_OUTPUT_TYPE)),
    ] {
        require(
            state_contract[key] == expected,
            format!("V4 package contract {key} drift"),
        )?;
    }

    require_exact_keys(
        &provenance,
        &[
            "format_version",
            "family",
            "source",
            "production_release",
            "release_assets",
            "module_contracts",
            "ownership",
            "integration_constraints",
            "retirement_gates",
        ],
        "V4 import provenance",
    )?;
    require(
        provenance["source"]
            == json!({
                "repository": PACKAGE_REPOSITORY,
                "tag": PACKAGE_SOURCE_TAG,
                "commit": PACKAGE_SOURCE_COMMIT,
                "history_mirror": "refs/heads/upstream/uniswap-v4-v0.4.1",
                "tree": PACKAGE_SOURCE_TREE,
                "tracked_files": 98,
                "executable_files": 13,
            }),
        "V4 imported source provenance drift",
    )?;
    require(
        provenance["production_release"]
            == json!({"tag": PACKAGE_RELEASE_TAG, "commit": PACKAGE_RELEASE_COMMIT}),
        "V4 production release provenance drift",
    )?;
    let retained: Vec<&Value> = provenance["release_assets"]
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter(|i| i["name"] == json!(PACKAGE_ASSET_NAME))
                .collect()
        })
        .unwrap_or_default();
    require(
        retained
            == vec![
                &json!({"release": "v0.4.0", "name": PACKAGE_ASSET_NAME, "sha256": IMPORTED_SPKG_SHA256, "retained_in_import": true}),
            ],
        "V4 retained release asset identity drift",
    )?;
    require(
        provenance["module_contracts"]["map_store_state_inputs"] == json!(PACKAGE_MODULE_HASH),
        "V4 imported module contract drift",
    )?;

    require_exact_keys(
        &inventory,
        &[
            "format_version",
            "source_commit",
            "source_tree",
            "file_count",
            "executable_count",
            "files",
        ],
        "V4 import inventory",
    )?;
    require(
        inventory["format_version"] == json!(1)
            && inventory["source_commit"] == json!(PACKAGE_SOURCE_COMMIT)
            && inventory["source_tree"] == json!(PACKAGE_SOURCE_TREE)
            && inventory["file_count"] == json!(98)
            && inventory["executable_count"] == json!(13),
        "V4 import inventory identity drift",
    )?;
    let relative_package = PACKAGE_PATH
        .strip_prefix("uniswap-v4/")
        .unwrap_or(PACKAGE_PATH);
    let record: Vec<&Value> = inventory["files"]
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter(|i| i["path"] == json!(relative_package))
                .collect()
        })
        .unwrap_or_default();
    require(
        record
            == vec![
                &json!({"path": relative_package, "mode": "100644", "size": PACKAGE_BYTES, "git_blob": PACKAGE_GIT_BLOB, "sha256": IMPORTED_SPKG_SHA256}),
            ],
        "V4 imported package inventory record drift",
    )?;

    let store_state = &compatibility["store_state_spkg"];
    let observed_identity = json!({
        "repository": store_state["repository"],
        "release": store_state["release"],
        "asset": store_state["asset"],
        "sha256": store_state["sha256"],
        "package_name": store_state["package_name"],
        "package_version": store_state["package_version"],
        "network": store_state["network"],
        "module": store_state["module"],
        "module_hash": store_state["module_hash"],
        "output_type": store_state["output_type"],
        "initial_block": store_state["initial_block"],
    });
    let expected_identity = json!({
        "repository": PACKAGE_REPOSITORY,
        "release": PACKAGE_RELEASE_TAG,
        "asset": PACKAGE_ASSET_NAME,
        "sha256": IMPORTED_SPKG_SHA256,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "network": PACKAGE_NETWORK,
        "module": PACKAGE_MODULE,
        "module_hash": PACKAGE_MODULE_HASH,
        "output_type": PACKAGE_OUTPUT_TYPE,
        "initial_block": PACKAGE_INITIAL_BLOCK,
    });
    require(
        observed_identity == expected_identity,
        "compatibility contract and imported package identity differ",
    )?;
    require(
        store_state["imported_module_hashes"] == state_contract["imported_module_hashes"],
        "imported Store module hashes differ between compatibility and package contracts",
    )?;
    let compatibility_shards = &store_state["tick_liquidity_shards"];
    let package_shards = &state_contract["tick_liquidity_shards"];
    require(
        json!({
            "count": compatibility_shards["count"],
            "partition": compatibility_shards["partition"],
            "module_hashes": compatibility_shards["module_hashes"],
        }) == *package_shards,
        "Tick-liquidity shard identity differs between compatibility and package contracts",
    )?;
    require(
        compatibility_shards["legacy_key_encoding"] == Value::Bool(true)
            && compatibility_shards["replaces_module"] == json!("store_tick_liquidity")
            && compatibility_shards["replaced_module_hash"]
                == json!("6abfe7cad14187870e808e940ae4f4b3b56a0bfd"),
        "Tick-liquidity replacement contract drift",
    )?;
    let mut built: Vec<Value> = compatibility_shards["module_hashes"]
        .as_object()
        .map(|m| m.keys().map(|k| Value::String(k.clone())).collect())
        .unwrap_or_default();
    built.extend(
        [
            "store_pool_sqrt_price",
            "store_token_decimals",
            "store_pool_token_decimals",
            PACKAGE_MODULE,
        ]
        .iter()
        .map(|s| Value::String(s.to_string())),
    );
    require(
        store_state["built_modules"] == Value::Array(built),
        "Store-state built-module inventory drift",
    )?;
    require(
        closure["imported_package"]["sha256"] == json!(sha),
        "closure and imported SPKG bytes differ",
    )
}

fn verify_compatibility(compatibility: &Value) -> Result<()> {
    require_exact_keys(
        compatibility,
        &[
            "format_version",
            "adapter",
            "deployment",
            "graft_base",
            "graft_block",
            "spkg",
            "store_spkg",
            "store_fed_spkg",
            "store_state_spkg",
            "direct_postgres",
            "runtime",
            "graph_node",
        ],
        "compatibility contract",
    )?;
    require(
        compatibility["format_version"] == json!(1)
            && compatibility["adapter"] == json!("uniswap-v4-base")
            && compatibility["deployment"] == json!(DEPLOYMENT),
        "compatibility root identity drift",
    )
}

fn verify_engine_compatibility(compatibility: &Value, closure: &Value) -> Result<()> {
    let engine = expected_engine();
    require(
        compatibility["runtime"]
            == json!({"release": engine["release"], "platform": engine["platform"], "image": engine["image"], "binary_sha256": engine["binary_sha256"]}),
        "compatibility runtime does not pin engine v0.5.0",
    )?;
    require(
        compatibility["graph_node"] == engine["graph_node"],
        "compatibility Graph Node identity drift",
    )?;
    require(closure["engine"] == engine, "closure engine identity drift")
}

fn verify_certificate_artifact_links(
    certificate: &Value,
    loaded: &BTreeMap<String, Value>,
    locks: &[FileLock],
) -> Result<()> {
    require_exact_keys(
        certificate,
        &[
            "format_version",
            "status",
            "network",
            "deployment",
            "range",
            "legacy_runtime",
            "sharded_runtime",
            "artifacts",
            "gates",
        ],
        "retained certificate",
    )?;
    let links: [(&str, &str, &str); 5] = [
        (
            "benchmark",
            "benchmark.json",
            "fixtures/kan-base-v4-store-state-100k-benchmark.json",
        ),
        (
            "parity",
            "parity.json",
            "fixtures/kan-base-v4-store-state-100k-parity.json",
        ),
        (
            "graphql",
            "graphql.json",
            "fixtures/kan-base-v4-store-state-graphql.json",
        ),
        (
            "lifecycle",
            "lifecycle.json",
            "fixtures/kan-base-v4-store-state-lifecycle.json",
        ),
        (
            "overlap",
            "overlap.json",
            "fixtures/kan-base-v4-store-state-sharded-overlap.json",
        ),
    ];
    let artifact_keys: BTreeSet<&str> = certificate["artifacts"]
        .as_object()
        .map(|m| m.keys().map(String::as_str).collect())
        .unwrap_or_default();
    require(
        artifact_keys == links.iter().map(|l| l.0).collect(),
        "certificate artifact set drift",
    )?;
    for (name, local_path, source_path) in links {
        let lock = locks
            .iter()
            .find(|l| l.local_path == local_path)
            .expect("lock exists");
        require(
            certificate["artifacts"][name] == json!({"path": source_path, "sha256": lock.sha256}),
            format!("certificate {name} artifact cross-reference drift"),
        )?;
        require(
            loaded.contains_key(local_path),
            format!("retained {name} JSON was not loaded"),
        )?;
    }
    Ok(())
}

fn verify_selected_reference(
    loaded: &BTreeMap<String, Value>,
    closure: &Value,
    locks: &[FileLock],
) -> Result<()> {
    let certificate = &loaded["certificate.json"];
    let benchmark = &loaded["benchmark.json"];
    let parity = &loaded["parity.json"];
    let graphql = &loaded["graphql.json"];
    let lifecycle = &loaded["lifecycle.json"];
    let overlap = &loaded["overlap.json"];
    let selected = &closure["selected_reference"];

    require_exact_keys(
        selected,
        &[
            "classification",
            "deployment",
            "network",
            "range",
            "frame_stream",
            "retained_manifest",
            "runtime_checkpoint_manifest",
            "copy_inventory",
            "checkpoint",
            "physical_rows",
            "poi",
            "graphql",
            "historical_target_evidence",
        ],
        "selected reference",
    )?;
    require(
        selected["classification"]
            == json!("historical-retained-certificate-not-v0.5.0-reproduction"),
        "selected reference classification overclaims reproduction",
    )?;
    require(
        selected["deployment"] == json!(DEPLOYMENT) && selected["network"] == json!("base"),
        "selected reference deployment identity drift",
    )?;
    require(
        selected["range"] == expected_range(),
        "selected range closure drift",
    )?;

    require(
        certificate["format_version"] == json!(1)
            && certificate["status"] == json!("complete")
            && certificate["network"] == json!("base")
            && certificate["deployment"] == json!(DEPLOYMENT),
        "retained certificate root identity drift",
    )?;
    require(
        certificate["range"] == expected_range(),
        "certificate range/hash cross-reference drift",
    )?;
    require(
        START_BLOCK == SEED_BLOCK + 1 && END_BLOCK - START_BLOCK + 1 == RANGE_BLOCKS,
        "selected range arithmetic is invalid",
    )?;
    require(
        certificate["legacy_runtime"]["spkg_sha256"] == json!(LEGACY_SPKG_SHA256),
        "retained certificate legacy package identity drift",
    )?;
    require(
        certificate["sharded_runtime"]["spkg_sha256"] == json!(IMPORTED_SPKG_SHA256),
        "retained certificate sharded package identity drift",
    )?;
    let gate_names: Vec<&str> = HISTORICAL_INT_GATES
        .iter()
        .map(|(n, _)| *n)
        .chain(HISTORICAL_BOOL_GATES.iter().copied())
        .collect();
    require_exact_keys(
        &certificate["gates"],
        &gate_names,
        "historical certificate gates",
    )?;
    for (gate, expected) in HISTORICAL_INT_GATES {
        let value = &certificate["gates"][*gate];
        require(
            is_int(value) && *value == json!(expected),
            format!("historical certificate gate drift: {gate}"),
        )?;
    }
    for gate in HISTORICAL_BOOL_GATES {
        require(
            certificate["gates"][*gate] == Value::Bool(true),
            format!("historical certificate gate drift: {gate}"),
        )?;
    }
    verify_certificate_artifact_links(certificate, loaded, locks)?;

    require(
        benchmark["format_version"] == json!(1)
            && benchmark["status"] == json!("complete")
            && benchmark["network"] == json!("base")
            && benchmark["deployment"] == json!(DEPLOYMENT),
        "benchmark root identity drift",
    )?;
    require(
        benchmark["range"]
            == json!({"seed": SEED_BLOCK, "start": START_BLOCK, "end": END_BLOCK, "blocks": RANGE_BLOCKS, "seed_hash": SEED_HASH, "end_hash": END_HASH}),
        "benchmark range/hash cross-reference drift",
    )?;
    require(
        benchmark["spkg_sha256"] == json!(LEGACY_SPKG_SHA256),
        "benchmark legacy SPKG drift",
    )?;
    require(
        benchmark["image"] != json!(ENGINE_IMAGE),
        "historical benchmark must not be relabeled as v0.5.0 execution",
    )?;
    let frame_stream = json!({"input": "store-state-protobuf-framed", "event_bearing_frames": 86342, "protobuf_payload_bytes": 1069268806});
    require(
        selected["frame_stream"]
            == json!({"input": benchmark["input"], "event_bearing_frames": benchmark["cold_cache"]["event_bearing_frames"], "protobuf_payload_bytes": benchmark["cold_cache"]["protobuf_payload_bytes"]})
            && selected["frame_stream"] == frame_stream,
        "frame-stream cross-reference drift",
    )?;
    let checkpoint = json!({"bytes": 5942403462u64, "sha256": "69b69f4f44f7344f64bddb798f393fbc7411be044fc98932579a36d1ff66231a"});
    require(
        selected["checkpoint"] == benchmark["checkpoint"] && benchmark["checkpoint"] == checkpoint,
        "checkpoint cross-reference drift",
    )?;
    let target = &selected["historical_target_evidence"];
    require(
        benchmark["cluster"] == target["cluster"]
            && benchmark["schema"] == target["schema"]
            && benchmark["graft_parent_seed"]["source_schema"] == target["source_schema"],
        "historical target-evidence cross-reference drift",
    )?;
    require(
        target["classification"]
            == json!("prior-certificate-context-only-not-a-new-authorized-target"),
        "historical target evidence was promoted to an authorized target",
    )?;
    require(
        *target
            == json!({"cluster": "kan-subgraphs-a", "schema": "sgd2", "source_schema": "sgd1246", "classification": "prior-certificate-context-only-not-a-new-authorized-target"}),
        "historical target evidence contains unapproved fields",
    )?;
    let certificate_lock = locks
        .iter()
        .find(|l| l.local_path == "certificate.json")
        .expect("certificate lock");
    require(
        selected["retained_manifest"]
            == json!({"kind": "certificate-artifact-digest-manifest", "path": "certificate.json", "sha256": certificate_lock.sha256}),
        "retained certificate-manifest identity drift",
    )?;
    require(
        selected["runtime_checkpoint_manifest"]
            == json!({"retained": false, "sha256": null, "bytes": null}),
        "missing runtime checkpoint manifest was falsely claimed",
    )?;

    require_exact_keys(
        parity,
        &[
            "deployment",
            "local_schema",
            "source_schema",
            "range",
            "vid_policy",
            "row_comparison",
            "future_range_policy",
            "source_policy",
            "seed_policy",
            "matched_tables",
            "mismatched_tables",
            "local_rows",
            "source_rows",
            "tables",
        ],
        "20-table parity",
    )?;
    require(
        parity["deployment"] == json!(DEPLOYMENT)
            && parity["range"]
                == json!({"seed": SEED_BLOCK, "start": START_BLOCK, "end": END_BLOCK}),
        "parity range cross-reference drift",
    )?;
    let tables = parity["tables"].as_array().cloned().unwrap_or_default();
    require(
        parity["matched_tables"] == json!(20)
            && parity["mismatched_tables"] == json!(0)
            && tables.len() == 20,
        "20-table parity cardinality drift",
    )?;
    let table_names: Vec<&str> = tables
        .iter()
        .map(|t| t["table"].as_str().unwrap_or_default())
        .collect();
    require(
        table_names == EXPECTED_TABLES,
        "COPY table inventory or order drift",
    )?;
    require(
        table_names.iter().collect::<BTreeSet<_>>().len() == 20,
        "COPY table inventory contains duplicates",
    )?;
    let mut local_total: i128 = 0;
    let mut source_total: i128 = 0;
    for table in &tables {
        let name = table["table"].as_str().unwrap_or_default();
        let local_rows = table["local_rows"].as_i64();
        require(
            table["status"] == json!("match")
                && is_int(&table["local_rows"])
                && local_rows.is_some_and(|v| v >= 0)
                && table["local_rows"] == table["source_rows"],
            format!("physical row parity drift for {name}"),
        )?;
        let keys: BTreeSet<&str> = table
            .as_object()
            .map(|m| m.keys().map(String::as_str).collect())
            .unwrap_or_default();
        if name == "data_sources$" {
            require(
                keys == ["table", "status", "local_rows", "source_rows"]
                    .into_iter()
                    .collect(),
                "data_sources$ parity shape drift",
            )?;
        } else {
            require(
                keys == [
                    "table",
                    "status",
                    "local_rows",
                    "source_rows",
                    "local_digest",
                    "source_digest",
                ]
                .into_iter()
                .collect()
                    && table["local_digest"] == table["source_digest"],
                format!("physical digest parity drift for {name}"),
            )?;
        }
        local_total += i128::from(local_rows.unwrap_or_default());
        source_total += i128::from(table["source_rows"].as_i64().unwrap_or_default());
    }
    require(
        json!(local_total) == parity["local_rows"]
            && json!(source_total) == parity["source_rows"]
            && parity["local_rows"] == json!(12393562)
            && parity["source_rows"] == json!(12393562),
        "physical-row total cross-reference drift",
    )?;
    require(
        selected["copy_inventory"]
            == json!({
                "classification": "table-level-parity-inventory-not-copy-spool-file-set",
                "matched_tables": 20,
                "mismatched_tables": 0,
                "tables": EXPECTED_TABLES,
                "copy_spool_file_set_retained": false,
            }),
        "COPY inventory claim boundary drift",
    )?;
    require(
        selected["copy_inventory"]["copy_spool_file_set_retained"] == Value::Bool(false),
        "COPY spool retention flag must be a false boolean",
    )?;
    require(
        selected["physical_rows"]
            == json!({"local": parity["local_rows"], "source": parity["source_rows"]}),
        "physical-row closure cross-reference drift",
    )?;
    let poi = tables
        .iter()
        .find(|t| t["table"] == json!("poi2$"))
        .cloned()
        .unwrap_or(Value::Null);
    let mut expected_poi_row = expected_poi();
    expected_poi_row["status"] = json!("match");
    require(poi == expected_poi_row, "retained PoI table identity drift")?;
    require(
        selected["poi"] == expected_poi(),
        "PoI closure cross-reference drift",
    )?;

    require(
        *graphql
            == json!({
                "deployment": DEPLOYMENT,
                "block": {"number": END_BLOCK, "hash": END_HASH},
                "local_subgraph": "prototype/uniswap-v4-base-substreams-kan",
                "source_subgraph": "transplant/sgd1246",
                "response": {"pool_managers": 1, "bundles": 1, "tokens": 25, "pools": 25, "normalized_sha256": "336c7e85baa68501dfaf5a12d764aa9f9ea9fd3f9668696944a9d008fc6fe982"},
                "match": true,
                "local_head_exact": true,
                "status": "complete",
            }),
        "GraphQL retained artifact drift",
    )?;
    require(
        selected["graphql"]
            == json!({"block": graphql["block"]["number"], "block_hash": graphql["block"]["hash"], "normalized_sha256": graphql["response"]["normalized_sha256"]}),
        "GraphQL closure cross-reference drift",
    )?;

    let lifecycle_support = &closure["supporting_evidence"]["lifecycle"];
    require(
        lifecycle["status"] == json!("complete")
            && lifecycle["deployment"] == json!(DEPLOYMENT)
            && lifecycle["seed"]["block"] == json!(END_BLOCK)
            && lifecycle["seed"]["hash"] == json!(END_HASH)
            && lifecycle["seed"]["graphql_sha256"] == graphql["response"]["normalized_sha256"],
        "historical lifecycle seed cross-reference drift",
    )?;
    let target_block = lifecycle["target"]["block"].as_i64().unwrap_or_default();
    let seed_block = lifecycle["seed"]["block"].as_i64().unwrap_or_default();
    require(
        target_block - seed_block == 189 && lifecycle["target"]["blocks"] == json!(189),
        "historical lifecycle range drift",
    )?;
    require(
        lifecycle["candidate"]["spkg_sha256"] == json!(LEGACY_SPKG_SHA256)
            && lifecycle["candidate"]["image"] != json!(ENGINE_IMAGE),
        "historical lifecycle was relabeled as v0.5.0/imported-package evidence",
    )?;
    require(
        *lifecycle_support
            == json!({
                "classification": "historical-189-block-legacy-candidate-continuation-only",
                "seed_block": lifecycle["seed"]["block"],
                "seed_hash": lifecycle["seed"]["hash"],
                "target_block": lifecycle["target"]["block"],
                "target_hash": lifecycle["target"]["hash"],
                "legacy_spkg_sha256": lifecycle["candidate"]["spkg_sha256"],
            }),
        "historical lifecycle support classification drift",
    )?;

    let overlap_support = &closure["supporting_evidence"]["sharded_overlap"];
    let overlap_start = overlap["range"]["start_block"].as_i64().unwrap_or_default();
    let overlap_end = overlap["range"]["end_block"].as_i64().unwrap_or_default();
    require(
        overlap["version"] == json!(1)
            && overlap["spkg_sha256"] == json!(IMPORTED_SPKG_SHA256)
            && overlap_end - overlap_start + 1 == 100000
            && overlap["byte_identical_to_legacy_checkpoint"] == Value::Bool(true)
            && overlap["postgres_default_transaction_read_only"] == Value::Bool(true)
            && overlap["database_head_unchanged"] == Value::Bool(true),
        "sharded overlap evidence drift",
    )?;
    require(
        overlap_start != START_BLOCK as i64 && overlap_end != END_BLOCK as i64,
        "separate-range overlap was conflated with selected reproduction",
    )?;
    require(
        *overlap_support
            == json!({
                "classification": "separate-range-immutable-package-equivalence-only",
                "start_block": overlap["range"]["start_block"],
                "end_block": overlap["range"]["end_block"],
                "blocks": 100000,
                "spkg_sha256": overlap["spkg_sha256"],
                "checkpoint_sha256": overlap["checkpoint_sha256"],
                "checkpoint_bytes": overlap["checkpoint_bytes"],
                "byte_identical_to_legacy_checkpoint": true,
                "postgres_default_transaction_read_only": true,
                "database_head_unchanged": true,
            }),
        "sharded overlap support classification drift",
    )
}

/// Verify the capsule under `root` with the given byte locks.
pub fn verify_with_locks(root: &Path, locks: &[FileLock]) -> Result<()> {
    let root = root
        .canonicalize()
        .map_err(|e| VerificationError(format!("root is unavailable: {e}")))?;
    verify_inventory(&root, locks)?;
    let closure = load_json(&require_regular_file(
        &root,
        CLOSURE_PATH,
        "closure manifest",
    )?)?;
    verify_closure_shape(&closure)?;
    let loaded = verify_file_locks(&root, &closure, locks)?;
    let compatibility = &loaded["compatibility.json"];
    verify_compatibility(compatibility)?;
    verify_engine_compatibility(compatibility, &closure)?;
    verify_imported_package(&root, &closure, compatibility)?;
    verify_selected_reference(&loaded, &closure, locks)
}

pub fn verify(root: &Path) -> Result<()> {
    verify_with_locks(root, &expected_file_locks())
}

pub fn success_line() -> &'static str {
    "verified engine v0.5.0 identity, imported V4 package, retained 100k pre-execution summary, typed historical certificate gates, and all-false execution/readiness gates"
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
        locks: Vec<FileLock>,
    }

    fn copy_dir(from: &Path, to: &Path) {
        fs::create_dir_all(to).unwrap();
        for entry in fs::read_dir(from).unwrap() {
            let entry = entry.unwrap();
            let target = to.join(entry.file_name());
            if entry.path().is_dir() {
                copy_dir(&entry.path(), &target);
            } else {
                fs::copy(entry.path(), target).unwrap();
            }
        }
    }

    impl Fixture {
        fn new() -> Fixture {
            let dir = tempfile::tempdir().unwrap();
            copy_dir(
                &repository().join(CAPSULE_DIRECTORY),
                &dir.path().join(CAPSULE_DIRECTORY),
            );
            for relative in [
                PACKAGE_PATH,
                PACKAGE_CONTRACT_PATH,
                IMPORT_PROVENANCE_PATH,
                IMPORT_INVENTORY_PATH,
            ] {
                let destination = dir.path().join(relative);
                fs::create_dir_all(destination.parent().unwrap()).unwrap();
                fs::copy(repository().join(relative), destination).unwrap();
            }
            Fixture {
                dir,
                locks: expected_file_locks(),
            }
        }
        fn root(&self) -> &Path {
            self.dir.path()
        }
        fn capsule(&self) -> PathBuf {
            self.root().join(CAPSULE_DIRECTORY)
        }
        fn read(&self, relative: &str) -> Value {
            serde_json::from_str(&fs::read_to_string(self.root().join(relative)).unwrap()).unwrap()
        }
        fn write(&self, relative: &str, value: &Value) {
            fs::write(
                self.root().join(relative),
                format!("{}\n", serde_json::to_string_pretty(value).unwrap()),
            )
            .unwrap();
        }
        fn read_fixture(&self, name: &str) -> Value {
            self.read(&format!("{CAPSULE_DIRECTORY}/{name}"))
        }
        fn write_fixture(&self, name: &str, value: &Value) {
            self.write(&format!("{CAPSULE_DIRECTORY}/{name}"), value)
        }
        /// Move byte locks so a test reaches the semantic cross-reference checks.
        fn accept_modified_retained_bytes(&mut self, names: &[&str]) {
            let mut closure = self.read(CLOSURE_PATH);
            for name in names {
                let payload = fs::read(self.capsule().join(name)).unwrap();
                let bytes = payload.len() as u64;
                let sha = hex::encode(Sha256::digest(&payload));
                let lock = self
                    .locks
                    .iter_mut()
                    .find(|l| l.local_path == *name)
                    .unwrap();
                lock.bytes = bytes;
                lock.sha256 = sha.clone();
                for record in closure["files"].as_array_mut().unwrap() {
                    if record["local_path"] == json!(name) {
                        record["bytes"] = json!(bytes);
                        record["sha256"] = json!(sha);
                    }
                }
                if *name == "certificate.json" {
                    closure["selected_reference"]["retained_manifest"]["sha256"] = json!(sha);
                }
            }
            self.write(CLOSURE_PATH, &closure);
        }
        fn update_certificate_artifact_sha(&self, artifact: &str, fixture: &str) {
            let payload = fs::read(self.capsule().join(fixture)).unwrap();
            let mut certificate = self.read_fixture("certificate.json");
            certificate["artifacts"][artifact]["sha256"] =
                json!(hex::encode(Sha256::digest(&payload)));
            self.write_fixture("certificate.json", &certificate);
        }
        fn error(&self) -> String {
            verify_with_locks(self.root(), &self.locks)
                .unwrap_err()
                .to_string()
        }
    }

    #[test]
    fn exact_reference_passes() {
        verify(Fixture::new().root()).unwrap();
        verify(&repository()).unwrap();
    }

    #[test]
    fn tampered_tagged_fixture_bytes_are_rejected() {
        let f = Fixture::new();
        let path = f.capsule().join("benchmark.json");
        let mut bytes = fs::read(&path).unwrap();
        bytes.push(b'\n');
        fs::write(&path, bytes).unwrap();
        let error = f.error();
        assert!(
            error.contains("byte length drift") || error.contains("SHA-256 drift"),
            "{error}"
        );
    }

    #[test]
    fn unlisted_capsule_file_is_rejected() {
        let f = Fixture::new();
        fs::write(f.capsule().join("extra.json"), b"{}").unwrap();
        assert!(f.error().contains("file inventory drift"));
    }

    #[test]
    fn symlinked_retained_fixture_is_rejected() {
        let f = Fixture::new();
        let target = f.capsule().join("graphql.json");
        let moved = f.root().join("graphql-moved.json");
        fs::rename(&target, &moved).unwrap();
        std::os::unix::fs::symlink(&moved, &target).unwrap();
        assert!(f.error().contains("symlink"));
    }

    #[test]
    fn duplicate_closure_key_is_rejected() {
        let f = Fixture::new();
        let text = fs::read_to_string(f.root().join(CLOSURE_PATH)).unwrap();
        let duplicated = text.replacen(
            "\"format_version\": 1,",
            "\"format_version\": 1,\n  \"format_version\": 1,",
            1,
        );
        fs::write(f.root().join(CLOSURE_PATH), duplicated).unwrap();
        assert!(f.error().contains("duplicate JSON key"));
    }

    #[test]
    fn engine_digest_drift_is_rejected() {
        let f = Fixture::new();
        let mut closure = f.read(CLOSURE_PATH);
        let image = closure["engine"]["image"]
            .as_str()
            .unwrap()
            .split('@')
            .next()
            .unwrap()
            .to_string();
        closure["engine"]["image"] = json!(format!("{image}@sha256:{}", "0".repeat(64)));
        f.write(CLOSURE_PATH, &closure);
        assert!(f.error().contains("engine v0.5.0 identity drift"));
    }

    #[test]
    fn any_operational_gate_is_rejected() {
        let f = Fixture::new();
        let mut closure = f.read(CLOSURE_PATH);
        closure["gates"]["workflow_submission_authorized"] = json!(true);
        f.write(CLOSURE_PATH, &closure);
        assert!(f.error().contains("operational gate drift"));
    }

    #[test]
    fn numeric_zero_is_not_accepted_as_a_false_gate() {
        let f = Fixture::new();
        let mut closure = f.read(CLOSURE_PATH);
        closure["gates"]["workflow_submitted"] = json!(0);
        f.write(CLOSURE_PATH, &closure);
        assert!(f.error().contains("operational gate drift"));
    }

    #[test]
    fn protected_resource_mutation_claim_is_rejected() {
        let f = Fixture::new();
        let mut closure = f.read(CLOSURE_PATH);
        closure["protected_resources"]["recovery_database"]["mutation_performed"] = json!(true);
        f.write(CLOSURE_PATH, &closure);
        assert!(f.error().contains("protected-resource boundary drift"));
    }

    #[test]
    fn issue_scope_cannot_claim_reproduction() {
        let f = Fixture::new();
        let mut closure = f.read(CLOSURE_PATH);
        closure["scope"]["fully_satisfied_acceptance_criteria"]
            .as_array_mut()
            .unwrap()
            .push(json!(3));
        f.write(CLOSURE_PATH, &closure);
        assert!(f.error().contains("acceptance-criteria scope drift"));
    }

    #[test]
    fn missing_runtime_bytes_cannot_be_claimed_retained() {
        let f = Fixture::new();
        let mut closure = f.read(CLOSURE_PATH);
        closure["selected_reference"]["runtime_checkpoint_manifest"] =
            json!({"retained": true, "sha256": "0".repeat(64), "bytes": 1});
        f.write(CLOSURE_PATH, &closure);
        assert!(f
            .error()
            .contains("runtime checkpoint manifest was falsely claimed"));
    }

    #[test]
    fn checkpoint_drift_fails_after_self_consistent_hash_move() {
        let mut f = Fixture::new();
        let mut benchmark = f.read_fixture("benchmark.json");
        benchmark["checkpoint"]["sha256"] = json!("0".repeat(64));
        f.write_fixture("benchmark.json", &benchmark);
        f.update_certificate_artifact_sha("benchmark", "benchmark.json");
        f.accept_modified_retained_bytes(&["benchmark.json", "certificate.json"]);
        assert!(f.error().contains("checkpoint cross-reference drift"));
    }

    #[test]
    fn historical_certificate_gate_drift_fails_after_hash_move() {
        let mut f = Fixture::new();
        let mut certificate = f.read_fixture("certificate.json");
        certificate["gates"]["graph_node_restart"] = json!(false);
        f.write_fixture("certificate.json", &certificate);
        f.accept_modified_retained_bytes(&["certificate.json"]);
        assert!(f
            .error()
            .contains("historical certificate gate drift: graph_node_restart"));
    }

    #[test]
    fn frame_count_drift_fails_after_self_consistent_hash_move() {
        let mut f = Fixture::new();
        let mut benchmark = f.read_fixture("benchmark.json");
        let frames = benchmark["cold_cache"]["event_bearing_frames"]
            .as_i64()
            .unwrap();
        benchmark["cold_cache"]["event_bearing_frames"] = json!(frames + 1);
        f.write_fixture("benchmark.json", &benchmark);
        f.update_certificate_artifact_sha("benchmark", "benchmark.json");
        f.accept_modified_retained_bytes(&["benchmark.json", "certificate.json"]);
        assert!(f.error().contains("frame-stream cross-reference drift"));
    }

    #[test]
    fn poi_drift_fails_after_self_consistent_hash_move() {
        let mut f = Fixture::new();
        let mut parity = f.read_fixture("parity.json");
        for table in parity["tables"].as_array_mut().unwrap() {
            if table["table"] == json!("poi2$") {
                table["local_digest"] = json!("0".repeat(64));
                table["source_digest"] = json!("0".repeat(64));
            }
        }
        f.write_fixture("parity.json", &parity);
        f.update_certificate_artifact_sha("parity", "parity.json");
        f.accept_modified_retained_bytes(&["parity.json", "certificate.json"]);
        assert!(f.error().contains("retained PoI table identity drift"));
    }

    #[test]
    fn copy_table_inventory_drift_fails_after_hash_move() {
        let mut f = Fixture::new();
        let mut parity = f.read_fixture("parity.json");
        parity["tables"][0]["table"] = json!("invented_copy_table");
        f.write_fixture("parity.json", &parity);
        f.update_certificate_artifact_sha("parity", "parity.json");
        f.accept_modified_retained_bytes(&["parity.json", "certificate.json"]);
        assert!(f.error().contains("COPY table inventory"));
    }

    #[test]
    fn imported_package_bytes_are_rejected_when_tampered() {
        let f = Fixture::new();
        let path = f.root().join(PACKAGE_PATH);
        let mut bytes = fs::read(&path).unwrap();
        bytes.push(0);
        fs::write(&path, bytes).unwrap();
        let error = f.error();
        assert!(
            error.contains("imported SPKG byte length drift")
                || error.contains("imported SPKG SHA-256 drift"),
            "{error}"
        );
    }

    #[test]
    fn package_contract_byte_drift_is_rejected() {
        let f = Fixture::new();
        let mut contract = f.read(PACKAGE_CONTRACT_PATH);
        contract["packages"]["store_state"]["module_hash"] = json!("0".repeat(40));
        f.write(PACKAGE_CONTRACT_PATH, &contract);
        assert!(f.error().contains("byte/SHA-256 drift"));
    }

    #[test]
    fn import_provenance_tree_drift_is_rejected() {
        let f = Fixture::new();
        let mut provenance = f.read(IMPORT_PROVENANCE_PATH);
        provenance["source"]["tree"] = json!("0".repeat(40));
        f.write(IMPORT_PROVENANCE_PATH, &provenance);
        assert!(f.error().contains("byte/SHA-256 drift"));
    }

    #[test]
    fn strict_json_rejects_nested_duplicate_keys() {
        assert!(load_json_strict("{\"a\": {\"b\": 1, \"b\": 2}}", "t").is_err());
        assert!(load_json_strict("{\"a\": [{\"b\": 1}, {\"b\": 2}]}", "t").is_ok());
        assert!(load_json_strict("{\"a\": \"x,\\\"y\", \"a\": 1}", "t").is_err());
    }
}
