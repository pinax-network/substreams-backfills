//! Fail-closed verification for the Uniswap V4 q8 metadata capsule (port of
//! `scripts/verify-uniswap-v4-q8-reference.py`, #110).
//!
//! The q8 capsule under `docs/provenance/uniswap-v4-engine-v0.5.0/q8/`
//! retains byte- and Git-blob-locked copies of engine fixtures, a compact
//! metadata archive, and a closure manifest whose every claim is declared
//! historical metadata with acceptance role `none`. This module checks the
//! inventory, every lock, the archive members and their `SHA256SUMS`, the
//! closure shape and all-false gates, both segment manifests and READY
//! seals, the archive's compute semantics, and the reference document's
//! cross-references to the parent capsule, the current compatibility
//! contract, the source observations, and the pod topology.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::io::Read;
use std::path::Path;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub const CONTRACT: &str = "uniswap-v4-engine-v0.5.0-q8-declared-reference/v1";
pub const CAPSULE_DIRECTORY: &str = "docs/provenance/uniswap-v4-engine-v0.5.0/q8";
pub const CLOSURE_PATH: &str = "docs/provenance/uniswap-v4-engine-v0.5.0/q8/closure.json";
pub const PARENT_CLOSURE_PATH: &str = "docs/provenance/uniswap-v4-engine-v0.5.0/closure.json";
pub const CURRENT_COMPATIBILITY_PATH: &str =
    "docs/provenance/uniswap-v4-engine-v0.5.0/compatibility.json";
pub const ARCHIVE_NAME: &str = "release-complete-q8-200k-20260815-r1-evidence-20260815.tar.gz";
pub const DEPLOYMENT: &str = "Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB";
pub const REFERENCE_NAME: &str = "uniswap-v4-base-v0.5.0-q8-reference.json";
pub const PRODUCER_COMPATIBILITY_NAME: &str = "uniswap-v4-base-q8-producer-compatibility.json";
pub const OBSERVATIONS_NAME: &str = "uniswap-v4-base-v4-reference-source-observations.json";
pub const TOPOLOGY_NAME: &str = "uniswap-v4-base-v4-reference-pod-topology.json";

fn expected_source() -> Value {
    json!({
        "repository": "pinax-network/substreams-graph-node-backfill",
        "commit": "395c9fb0d5377cba058d506043b7891c2f2016a8",
        "tree": "c3568b472faf13e07618e14dc9551f9400551fa3",
    })
}

/// (local_path, source_path, role, bytes, sha256, git_blob). Locks are a
/// value so adversarial tests can move one and prove the semantic checks
/// still fail closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileLock {
    pub local_path: &'static str,
    pub source_path: &'static str,
    pub role: &'static str,
    pub bytes: u64,
    pub sha256: String,
    pub git_blob: String,
}

pub fn expected_file_locks() -> Vec<FileLock> {
    let lock = |local_path, source_path, role, bytes, sha256: &str, git_blob: &str| FileLock {
        local_path,
        source_path,
        role,
        bytes,
        sha256: sha256.into(),
        git_blob: git_blob.into(),
    };
    vec![
        lock(
            "LICENSE.source",
            "LICENSE",
            "source-license",
            11357,
            "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
            "261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64",
        ),
        lock(
            PRODUCER_COMPATIBILITY_NAME,
            "fixtures/uniswap-v4-base-q8-producer-compatibility.json",
            "historical-producer-compatibility",
            7252,
            "86b7c38e5d98700b9841aadefaad8ada8543e1d49e5e95d3db881f842b980ce6",
            "e0dee4eaeaec71219491c445374be57e61e32715",
        ),
        lock(
            "uniswap-v4-base-v0.5.0-q8-READY.json",
            "fixtures/uniswap-v4-base-v0.5.0-q8-READY.json",
            "certified-segment-ready-seal",
            215,
            "073081a599d164c929326ea6eb46599884a927bd2fb21ed944bc75d2171f7de2",
            "b5ee568af9989a47f7d311369dd15f61cb090dc9",
        ),
        lock(
            "uniswap-v4-base-v0.5.0-q8-manifest.json",
            "fixtures/uniswap-v4-base-v0.5.0-q8-manifest.json",
            "certified-segment-copy-manifest",
            12877,
            "44718ce74c0a60cdc9f5c452d1ce7b804257c887ec1ce8f34e930cfdb7c4d91a",
            "8401eb8b7e85b7917fdd653ae5d4b8e6cdae0c87",
        ),
        lock(
            REFERENCE_NAME,
            "fixtures/uniswap-v4-base-v0.5.0-q8-reference.json",
            "declared-historical-reference-metadata",
            12671,
            "9a9d2ac3423f19199d527993a97d4e125160f4d07c57cbfde44eb67f7006fc82",
            "f8167150383a610f6bbe41411a24a70fbcf6263b",
        ),
        lock(
            "uniswap-v4-base-v0.5.0-q8-restore-READY.json",
            "fixtures/uniswap-v4-base-v0.5.0-q8-restore-READY.json",
            "restore-segment-ready-seal",
            215,
            "1a8bd8a749aa0c4a74059dcfebf2dcf9cfabfb234ac01729d90dc98b8a2ea233",
            "9a0a2700eb44f68c9c715207458fc4133c8e06c3",
        ),
        lock(
            "uniswap-v4-base-v0.5.0-q8-restore-manifest.json",
            "fixtures/uniswap-v4-base-v0.5.0-q8-restore-manifest.json",
            "restore-segment-copy-manifest",
            12876,
            "9d398169ac19416ace56d429e186fbabae71f924ce538ea7fa9173556c5abdd2",
            "958525256fb5e23dc85c2944ba20efd9de210225",
        ),
        lock(
            TOPOLOGY_NAME,
            "fixtures/uniswap-v4-base-v4-reference-pod-topology.json",
            "declared-clean-run-pod-topology",
            9142,
            "3758fac03502479027a76925cd52b872b26f7b8c82a1aae329fbcbb1630d9aec",
            "4a19c81ddd2911e6759eb11e730ca99f751b6b4b",
        ),
        lock(
            OBSERVATIONS_NAME,
            "fixtures/uniswap-v4-base-v4-reference-source-observations.json",
            "declared-source-observation-contract",
            23284,
            "7e7d5847ce33ae7e8469825cf2a3a7ff0a58a213e5cd1b68964eb0d0792fced9",
            "b2a80ed376fdd51b3e03c9fc69a73cdf6e54f2ae",
        ),
    ]
}

const ARCHIVE_SHA256: &str = "3072f55bac5f0a1bcdff799642cf0b4deeb414381fb19e6a9d18322627ff34d1";
const ARCHIVE_BYTES: u64 = 9047;

fn expected_archive() -> Value {
    json!({
        "local_path": ARCHIVE_NAME,
        "declared_name": ARCHIVE_NAME,
        "status": "locally-recovered-compact-metadata-archive",
        "acceptance_role": "none",
        "bytes": ARCHIVE_BYTES,
        "sha256": ARCHIVE_SHA256,
        "file_members": 11,
        "checksum_bound_members": 10,
        "recovery_evidence": "https://github.com/pinax-network/substreams-graph-node-backfill/issues/32#issuecomment-5303965641",
        "source_reference_availability_is_stale": true,
    })
}

const ARCHIVE_MEMBERS: &[(&str, u64, &str)] = &[
    (
        "compute-events.jsonl",
        8949,
        "bc99a6129e4d5fef6b7fa26f4a0d3ca4fac81defc260da5b84c760f1e8baa586",
    ),
    (
        "compute-evidence.json",
        1021,
        "8ed3fc467f8c4efb951b239ba75a27991f5bc4b89819f36fbf86b27cd65a4428",
    ),
    (
        "compute-output.jsonl",
        1038,
        "aa9f5745718b553c831528c62af5b9425293ac281d26dd3ca6f86e1d1d79e704",
    ),
    (
        "compute-parity.json",
        2379,
        "0f54661fab6f003b67396d87eef2060f2f96261fdcc9cc27c2f243c461859f11",
    ),
    (
        "compute-performance-comparison.json",
        1001,
        "f7f922092fb883df48b92306cab25f8d7becfbce548270b4f3153e0af004d2f8",
    ),
    (
        "compute-progress.jsonl",
        460,
        "35418cc5467392e7209a38e2c86f61b7e2eb0abf5bf8f6ce226cc3c2c59fd816",
    ),
    (
        "run/spools/segment-33374155-33474154.ready/READY.json",
        215,
        "073081a599d164c929326ea6eb46599884a927bd2fb21ed944bc75d2171f7de2",
    ),
    (
        "run/spools/segment-33374155-33474154.ready/manifest.json",
        12877,
        "44718ce74c0a60cdc9f5c452d1ce7b804257c887ec1ce8f34e930cfdb7c4d91a",
    ),
    (
        "run/spools/segment-33474155-33574154.ready/READY.json",
        215,
        "1a8bd8a749aa0c4a74059dcfebf2dcf9cfabfb234ac01729d90dc98b8a2ea233",
    ),
    (
        "run/spools/segment-33474155-33574154.ready/manifest.json",
        12876,
        "9d398169ac19416ace56d429e186fbabae71f924ce538ea7fa9173556c5abdd2",
    ),
    (
        "SHA256SUMS",
        1045,
        "cee449f4f012f527d0342556974245e7bef69a092f7e2343e9c653658e44eb2f",
    ),
];

const ARCHIVE_DIRECTORIES: &[&str] = &[
    ".",
    "run",
    "run/spools",
    "run/spools/segment-33374155-33474154.ready",
    "run/spools/segment-33474155-33574154.ready",
];

pub const EXPECTED_COPY_TABLES: &[&str] = &[
    "arrakis_hook",
    "bundle",
    "modify_liquidity",
    "poi2$",
    "pool",
    "pool_day_data",
    "pool_hour_data",
    "pool_manager",
    "position",
    "subscribe",
    "swap",
    "tick",
    "token",
    "token_day_data",
    "token_hour_data",
    "transaction",
    "transfer",
    "uniswap_day_data",
    "unsubscribe",
];

fn expected_topology_roles() -> Value {
    json!({
        "evidence_runtime": "publication-bound-by-runtime-contract-and-observed-image-id",
        "compute_load_runtime": "dbb88e451dbd44fd3e412f1d6814939cbc2a0b93c539837ebfb1f28d3dd1711e",
        "graph_node": "c14c6d8e2b2b1ed89f6a89babf48d807b18a43e372fda7fb495d3a9050b65b8b",
        "busybox": "b7f3d86d6e84fc17718c48bcde1450807faa2d56704205c697b4bd5df7b9e29f",
        "python_exporter": "f1a962d8ffa50b2006b72b4713a09a89e57def2d28ac28a36900bc070a00db61",
    })
}

struct Segment {
    key: &'static str,
    start_block: u64,
    end_block: u64,
    target_hash: &'static str,
    input_frames: u64,
    input_payload_bytes: u64,
    manifest_sha256: &'static str,
    ready_sha256: &'static str,
    copy_file_set_sha256: &'static str,
    copy_payload_bytes: u64,
    checkpoint_bytes: u64,
    checkpoint_sha256: &'static str,
}

impl Segment {
    fn expected_fields(&self) -> Vec<(&'static str, Value)> {
        vec![
            ("start_block", json!(self.start_block)),
            ("end_block", json!(self.end_block)),
            ("target_hash", json!(self.target_hash)),
            ("input_frames", json!(self.input_frames)),
            ("input_payload_bytes", json!(self.input_payload_bytes)),
            ("manifest_sha256", json!(self.manifest_sha256)),
            ("ready_sha256", json!(self.ready_sha256)),
            ("copy_file_set_sha256", json!(self.copy_file_set_sha256)),
            ("copy_payload_bytes", json!(self.copy_payload_bytes)),
            ("checkpoint_bytes", json!(self.checkpoint_bytes)),
            ("checkpoint_sha256", json!(self.checkpoint_sha256)),
        ]
    }
}

const CERTIFIED: Segment = Segment {
    key: "certified_segment",
    start_block: 33374155,
    end_block: 33474154,
    target_hash: "53ec0561c1a6d3b867e7a188678cd50256e2baca0ad72ea5ed5b7aefe86316e0",
    input_frames: 99248,
    input_payload_bytes: 9061879073,
    manifest_sha256: "44718ce74c0a60cdc9f5c452d1ce7b804257c887ec1ce8f34e930cfdb7c4d91a",
    ready_sha256: "073081a599d164c929326ea6eb46599884a927bd2fb21ed944bc75d2171f7de2",
    copy_file_set_sha256: "f7ac5e9b551f835d9c75baf3bc99e55ce5259d91bd02b9231d52201411ec1ca6",
    copy_payload_bytes: 21065457930,
    checkpoint_bytes: 13589557635,
    checkpoint_sha256: "329a3be191125b90f5e56fa9e5f9da79484c15edcc9d6786405cd3033f238626",
};

const RESTORE: Segment = Segment {
    key: "restore_segment",
    start_block: 33474155,
    end_block: 33574154,
    target_hash: "fe88afd7188b33c593fa4eb81409106a220a9d83ca874af714b21b08a30c9116",
    input_frames: 97580,
    input_payload_bytes: 6948696921,
    manifest_sha256: "9d398169ac19416ace56d429e186fbabae71f924ce538ea7fa9173556c5abdd2",
    ready_sha256: "1a8bd8a749aa0c4a74059dcfebf2dcf9cfabfb234ac01729d90dc98b8a2ea233",
    copy_file_set_sha256: "81ad8bb4da493ea463c8c3fb632f364f6069d7e08896ad6268ffadfd94db4e43",
    copy_payload_bytes: 18165472516,
    checkpoint_bytes: 15996029671,
    checkpoint_sha256: "0232aa8f53e42d45e7cdc57c75f84ef7804f1ec6abec73b84aef472db2e9c9d6",
};

const SEED_BLOCK: u64 = 33374154;
const SEED_HASH: &str = "5e8c1de6fe2065fcf08b382b10342e01fd8585052ca39ee1c9f80f37904c72a6";
const SEED_CHECKPOINT_BYTES: u64 = 11093835518;
const SEED_CHECKPOINT_SHA256: &str =
    "be434078b1b71c3e51a36e37c0473f6b4d7864777511d8119426234d398e397d";

fn expected_retention() -> Value {
    json!({
        "manifest_bytes": true,
        "ready_seal_bytes": true,
        "literal_copy_filenames_sizes_and_digests": true,
        "compute_metadata_archive": true,
        "source_observation_contract": true,
        "pod_topology_contract": true,
        "raw_frame_payload_bytes": false,
        "raw_frame_stream_digest": false,
        "copy_row_and_clamp_payload_bytes": false,
        "seed_checkpoint_bytes": false,
        "certified_checkpoint_bytes": false,
        "restore_checkpoint_bytes": false,
    })
}

fn expected_field_semantics() -> Value {
    json!({
        "input_stream_exact": {
            "observed_value": true,
            "meaning": "input-shape-equality-only",
            "compared_fields": ["input_format", "input_frames", "input_payload_bytes"],
            "raw_byte_identity_proven": false,
            "future_requirement": "emit-and-verify-frame-stream-receipt-sha256",
        }
    })
}

fn expected_scope() -> Value {
    json!({
        "issue": 26,
        "status": "declared-historical-reference-metadata",
        "supports_acceptance_criteria": [2],
        "fully_satisfied_acceptance_criteria": [],
        "acceptance_role": "none",
    })
}

fn expected_gates() -> Value {
    json!({
        "criterion_2_complete": false,
        "raw_frame_stream_retained": false,
        "raw_frame_stream_digest_retained": false,
        "copy_payload_retained": false,
        "checkpoint_payloads_retained": false,
        "scratch_target_authorized": false,
        "independent_zero_writer_proven": false,
        "k3_runtime_contract_approved": false,
        "workflow_submission_authorized": false,
        "workflow_submitted": false,
        "database_write_authorized": false,
        "database_mutation_performed": false,
        "backfill_ready": false,
        "production_ready": false,
        "promotion_eligible": false,
    })
}

fn expected_non_claims() -> Value {
    json!([
        "The recovered compact archive is metadata-only and has acceptance role none.",
        "Historical input_stream_exact means input format, frame count, and payload byte-count equality; it does not prove raw frame-stream byte identity.",
        "No raw frame payload, COPY row or clamp payload, seed checkpoint, or output checkpoint bytes are retained here.",
        "The historical archive cannot replace a new authorized two-phase replay.",
        "No scratch target, Kubernetes submission, workflow, database write, backfill, production, or promotion authority is represented.",
    ])
}

const FORBIDDEN_REFERENCE_CLAIM_KEYS: &[&str] = &[
    "criterion_2_complete",
    "reproduction_complete",
    "raw_frame_stream_retained",
    "raw_frame_stream_digest_retained",
    "copy_payload_retained",
    "checkpoint_payloads_retained",
    "scratch_target_authorized",
    "independent_zero_writer_proven",
    "k3_runtime_contract_approved",
    "workflow_submission_authorized",
    "workflow_submitted",
    "database_write_authorized",
    "database_mutation_performed",
    "backfill_ready",
    "production_ready",
    "promotion_eligible",
    "readiness",
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

fn require(condition: bool, message: impl Into<String>) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(VerificationError(message.into()))
    }
}

/// Python `type(actual) is type(expected)` plus recursive equality: a JSON
/// `1` never equals `true`, and `1.0` never equals `1`.
pub fn strict_equal(actual: &Value, expected: &Value) -> bool {
    match (actual, expected) {
        (Value::Object(a), Value::Object(e)) => {
            a.len() == e.len()
                && e.iter()
                    .all(|(k, v)| a.get(k).is_some_and(|av| strict_equal(av, v)))
        }
        (Value::Array(a), Value::Array(e)) => {
            a.len() == e.len() && a.iter().zip(e).all(|(av, ev)| strict_equal(av, ev))
        }
        (Value::Number(a), Value::Number(e)) => (a.is_f64() == e.is_f64()) && a == e,
        (Value::Bool(a), Value::Bool(e)) => a == e,
        (Value::String(a), Value::String(e)) => a == e,
        (Value::Null, Value::Null) => true,
        _ => false,
    }
}

fn require_strict(actual: &Value, expected: &Value, message: &str) -> Result<()> {
    require(strict_equal(actual, expected), message)
}

fn sha256(payload: &[u8]) -> String {
    hex::encode(Sha256::digest(payload))
}

pub fn git_blob_sha1(payload: &[u8]) -> String {
    use sha1::Digest as _;
    let mut hasher = sha1::Sha1::new();
    hasher.update(format!("blob {}\0", payload.len()).as_bytes());
    hasher.update(payload);
    hex::encode(hasher.finalize())
}

fn load_json_bytes(payload: &[u8], label: &str) -> Result<Value> {
    let text = std::str::from_utf8(payload)
        .map_err(|e| VerificationError(format!("invalid JSON: {label}: {e}")))?;
    crate::v4_engine_reference::load_json_strict(text, label)
        .map_err(|e| VerificationError(format!("invalid JSON: {label}: {}", e.0)))
}

fn load_json(path: &Path) -> Result<Value> {
    let payload = std::fs::read(path)
        .map_err(|e| VerificationError(format!("cannot read {}: {e}", path.display())))?;
    load_json_bytes(&payload, &path.display().to_string())
}

fn reject_forbidden_reference_claims(value: &Value, path: &str) -> Result<()> {
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                require(
                    !FORBIDDEN_REFERENCE_CLAIM_KEYS.contains(&key.as_str()),
                    format!("forbidden operational claim key: {path}.{key}"),
                )?;
                reject_forbidden_reference_claims(child, &format!("{path}.{key}"))?;
            }
            Ok(())
        }
        Value::Array(items) => {
            for (index, child) in items.iter().enumerate() {
                reject_forbidden_reference_claims(child, &format!("{path}[{index}]"))?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

fn regular_bytes(path: &Path, label: &str) -> Result<Vec<u8>> {
    let meta = path
        .symlink_metadata()
        .map_err(|_| VerificationError(format!("missing {label}: {}", path.display())))?;
    require(
        !meta.file_type().is_symlink(),
        format!("{label} must not be a symlink"),
    )?;
    require(meta.is_file(), format!("{label} must be a regular file"))?;
    std::fs::read(path).map_err(|e| VerificationError(format!("cannot read {label}: {e}")))
}

fn verify_lock(path: &Path, byte_count: u64, digest: &str, label: &str) -> Result<Vec<u8>> {
    let payload = regular_bytes(path, label)?;
    require(
        payload.len() as u64 == byte_count,
        format!("{label} byte length drift"),
    )?;
    require(sha256(&payload) == digest, format!("{label} SHA-256 drift"))?;
    Ok(payload)
}

fn expected_closure_files(locks: &[FileLock]) -> Value {
    Value::Array(
        locks
            .iter()
            .map(|l| json!({"local_path": l.local_path, "source_path": l.source_path, "role": l.role, "bytes": l.bytes, "sha256": l.sha256, "git_blob": l.git_blob}))
            .collect(),
    )
}

fn key_set(value: &Value) -> BTreeSet<&str> {
    value
        .as_object()
        .map(|m| m.keys().map(String::as_str).collect())
        .unwrap_or_default()
}

fn set_of<'a>(names: &[&'a str]) -> BTreeSet<&'a str> {
    names.iter().copied().collect()
}

fn verify_closure(closure: &Value, locks: &[FileLock]) -> Result<()> {
    require(
        key_set(closure)
            == set_of(&[
                "format_version",
                "contract",
                "source",
                "files",
                "recovered_archive",
                "selected_reference",
                "retention",
                "historical_field_semantics",
                "scope",
                "gates",
                "non_claims",
            ]),
        "closure top-level inventory drift",
    )?;
    require(
        closure["format_version"] == json!(1),
        "closure format drift",
    )?;
    require(
        closure["contract"] == json!(CONTRACT),
        "closure contract drift",
    )?;
    let source = &closure["source"];
    require(source.is_object(), "source contract missing")?;
    require(
        key_set(source) == set_of(&["repository", "commit", "tree", "license"]),
        "source contract inventory drift",
    )?;
    let expected = expected_source();
    require(
        ["repository", "commit", "tree"]
            .iter()
            .all(|k| source[*k] == expected[*k]),
        "source identity drift",
    )?;
    let license = &locks[0];
    require_strict(
        &source["license"],
        &json!({"spdx": "Apache-2.0", "local_path": license.local_path, "source_path": license.source_path, "bytes": license.bytes, "sha256": license.sha256, "git_blob": license.git_blob}),
        "source license drift",
    )?;
    require_strict(
        &closure["files"],
        &expected_closure_files(locks),
        "source file inventory drift",
    )?;
    require_strict(
        &closure["recovered_archive"],
        &expected_archive(),
        "archive closure drift",
    )?;
    require_strict(
        &closure["retention"],
        &expected_retention(),
        "retention boundary drift",
    )?;
    require_strict(
        &closure["historical_field_semantics"],
        &expected_field_semantics(),
        "historical field semantics drift",
    )?;
    require_strict(
        &closure["scope"],
        &expected_scope(),
        "acceptance scope drift",
    )?;
    require_strict(
        &closure["gates"],
        &expected_gates(),
        "operational gate drift",
    )?;
    let selected = &closure["selected_reference"];
    require(selected.is_object(), "selected q8 reference missing")?;
    require(
        key_set(selected)
            == set_of(&[
                "network",
                "deployment",
                "seed",
                "certified_segment",
                "restore_segment",
            ]),
        "selected reference inventory drift",
    )?;
    require(
        selected["network"] == json!("base"),
        "selected network drift",
    )?;
    require(
        selected["deployment"] == json!(DEPLOYMENT),
        "selected deployment drift",
    )?;
    require_strict(
        &selected["seed"],
        &json!({"block": SEED_BLOCK, "hash": SEED_HASH, "checkpoint_bytes": SEED_CHECKPOINT_BYTES, "checkpoint_sha256": SEED_CHECKPOINT_SHA256}),
        "seed closure drift",
    )?;
    for segment in [&CERTIFIED, &RESTORE] {
        let value = &selected[segment.key];
        require(
            value.is_object(),
            format!("{} closure missing", segment.key),
        )?;
        for (field, expected) in segment.expected_fields() {
            require(
                value[field] == expected,
                format!("{} closure {field} drift", segment.key),
            )?;
        }
        let mut expected_keys: BTreeSet<&str> = segment
            .expected_fields()
            .into_iter()
            .map(|(k, _)| k)
            .collect();
        expected_keys.extend(["blocks", "copy_tables", "seed_preserved_table"]);
        require(
            key_set(value) == expected_keys,
            format!("{} closure inventory drift", segment.key),
        )?;
        require(
            value["blocks"] == json!(100000),
            format!("{} block-count drift", segment.key),
        )?;
        require(
            value["copy_tables"] == json!(19),
            format!("{} COPY table-count drift", segment.key),
        )?;
        require(
            value["seed_preserved_table"] == json!("data_sources$"),
            format!("{} seed table drift", segment.key),
        )?;
    }
    require_strict(
        &closure["non_claims"],
        &expected_non_claims(),
        "non-claim boundary drift",
    )
}

fn normalize_tar_name(name: &str) -> String {
    let normalized = name.strip_prefix("./").unwrap_or(name);
    let normalized = normalized.trim_end_matches('/');
    if normalized.is_empty() {
        ".".to_string()
    } else {
        normalized.to_string()
    }
}

fn verify_archive(path: &Path) -> Result<BTreeMap<String, Vec<u8>>> {
    verify_lock(path, ARCHIVE_BYTES, ARCHIVE_SHA256, "q8 compact archive")?;
    let payload = std::fs::read(path)
        .map_err(|e| VerificationError(format!("invalid q8 compact archive: {e}")))?;
    let decoder = flate2::read::GzDecoder::new(payload.as_slice());
    let mut archive = tar::Archive::new(decoder);
    let mut files: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    let mut directories: BTreeSet<String> = BTreeSet::new();
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let entries = archive
        .entries()
        .map_err(|e| VerificationError(format!("invalid q8 compact archive: {e}")))?;
    for entry in entries {
        let mut entry =
            entry.map_err(|e| VerificationError(format!("invalid q8 compact archive: {e}")))?;
        let raw_name = entry
            .path()
            .map_err(|e| VerificationError(format!("invalid q8 compact archive: {e}")))?
            .to_string_lossy()
            .to_string();
        let name = normalize_tar_name(&raw_name);
        require(
            !name.starts_with('/') && !name.split('/').any(|p| p == ".."),
            format!("unsafe archive member: {name}"),
        )?;
        require(
            !seen.contains(&name),
            format!("duplicate archive member: {name}"),
        )?;
        seen.insert(name.clone());
        let kind = entry.header().entry_type();
        if kind.is_dir() {
            directories.insert(name);
            continue;
        }
        require(
            kind.is_file(),
            format!("non-regular archive member: {name}"),
        )?;
        let mut bytes = Vec::new();
        entry
            .read_to_end(&mut bytes)
            .map_err(|e| VerificationError(format!("unreadable archive member: {name}: {e}")))?;
        files.insert(name, bytes);
    }
    require(
        directories == ARCHIVE_DIRECTORIES.iter().map(|s| s.to_string()).collect(),
        "archive directory inventory drift",
    )?;
    require(
        files.keys().map(String::as_str).collect::<BTreeSet<_>>()
            == ARCHIVE_MEMBERS.iter().map(|m| m.0).collect(),
        "archive file inventory drift",
    )?;
    for (name, bytes, digest) in ARCHIVE_MEMBERS {
        let member = &files[*name];
        require(
            member.len() as u64 == *bytes,
            format!("archive member byte drift: {name}"),
        )?;
        require(
            sha256(member) == *digest,
            format!("archive member SHA-256 drift: {name}"),
        )?;
    }
    let sums_text = std::str::from_utf8(&files["SHA256SUMS"])
        .map_err(|_| VerificationError("invalid archive SHA256SUMS line".into()))?;
    let mut observed: BTreeMap<String, String> = BTreeMap::new();
    for line in sums_text.lines() {
        let (digest, rest) = line
            .split_once("  ./")
            .ok_or_else(|| VerificationError("invalid archive SHA256SUMS line".into()))?;
        require(
            digest.len() == 64
                && digest
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                && !rest.is_empty(),
            "invalid archive SHA256SUMS line",
        )?;
        require(
            !observed.contains_key(rest),
            format!("duplicate SHA256SUMS member: {rest}"),
        )?;
        observed.insert(rest.to_string(), digest.to_string());
    }
    let expected_members: BTreeSet<&str> = files
        .keys()
        .map(String::as_str)
        .filter(|k| *k != "SHA256SUMS")
        .collect();
    require(
        observed.keys().map(String::as_str).collect::<BTreeSet<_>>() == expected_members,
        "SHA256SUMS inventory drift",
    )?;
    for (name, digest) in &observed {
        require(
            sha256(&files[name]) == *digest,
            format!("SHA256SUMS mismatch: {name}"),
        )?;
    }
    Ok(files)
}

fn is_int(value: &Value) -> bool {
    value.is_i64() || value.is_u64()
}

fn is_hex64(value: &Value) -> bool {
    value.as_str().is_some_and(|s| {
        s.len() == 64
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}

fn verify_manifest(
    manifest: &Value,
    ready: &Value,
    expected: &Segment,
    expected_head_block: u64,
    expected_head_hash: &str,
    poi: &Value,
) -> Result<()> {
    require(
        manifest["format"] == json!("pinax.graph-node.copy-spool"),
        "manifest format drift",
    )?;
    require(
        is_int(&manifest["version"]) && manifest["version"] == json!(1),
        "manifest version drift",
    )?;
    require(
        manifest["deployment"] == json!(DEPLOYMENT),
        "manifest deployment drift",
    )?;
    require(
        manifest["expected_head_block"] == json!(expected_head_block),
        "expected head drift",
    )?;
    require(
        manifest["expected_head_hash"] == json!(expected_head_hash),
        "expected hash drift",
    )?;
    require(
        manifest["target_head_block"] == json!(expected.end_block),
        "target head drift",
    )?;
    require(
        manifest["target_head_hash"] == json!(expected.target_hash),
        "target hash drift",
    )?;
    require(
        manifest["input_format"] == json!("store-state-protobuf-framed"),
        "input format drift",
    )?;
    require(
        manifest["input_frames"] == json!(expected.input_frames),
        "input frame-count drift",
    )?;
    require(
        manifest["input_payload_bytes"] == json!(expected.input_payload_bytes),
        "input byte-count drift",
    )?;
    require(
        manifest.get("input_sha256").is_none() && manifest.get("frame_stream_sha256").is_none(),
        "invented historical frame digest",
    )?;
    require(
        manifest["checkpoint"]
            == json!({"file": "checkpoint.pending", "bytes": expected.checkpoint_bytes, "sha256": expected.checkpoint_sha256}),
        "checkpoint identity drift",
    )?;
    let copy = &manifest["copy"];
    require(copy.is_object(), "COPY contract missing")?;
    let tables = copy["tables"].as_array().cloned().unwrap_or_default();
    require(
        copy["tables"].is_array() && tables.len() == 19,
        "COPY table-count drift",
    )?;
    require(
        tables
            .iter()
            .map(|t| t["postgres_table"].as_str().unwrap_or_default())
            .collect::<Vec<_>>()
            == EXPECTED_COPY_TABLES,
        "ordered COPY inventory drift",
    )?;
    require(
        tables
            .iter()
            .map(|t| t["ordinal"].clone())
            .collect::<Vec<_>>()
            == (0..19).map(|i| json!(i)).collect::<Vec<_>>(),
        "COPY ordinal drift",
    )?;
    let (mut row_records, mut clamp_records, mut copy_bytes) = (0i128, 0i128, 0i128);
    for table in &tables {
        let name = table["postgres_table"].as_str().unwrap_or_default();
        for kind in ["rows", "clamps"] {
            let artifact = &table[kind];
            require(artifact.is_object(), format!("{name} {kind} missing"))?;
            require(
                artifact["file"] == json!(format!("{name}.{kind}.csv")),
                format!("{name} {kind} filename drift"),
            )?;
            require(
                is_int(&artifact["bytes"]) && artifact["bytes"].as_i64().is_some_and(|v| v >= 0),
                format!("{name} {kind} bytes invalid"),
            )?;
            require(
                is_int(&artifact["records"])
                    && artifact["records"].as_i64().is_some_and(|v| v >= 0),
                format!("{name} {kind} records invalid"),
            )?;
            require(
                is_hex64(&artifact["sha256"]),
                format!("{name} {kind} digest invalid"),
            )?;
            copy_bytes += i128::from(artifact["bytes"].as_i64().unwrap_or_default());
        }
        row_records += i128::from(table["rows"]["records"].as_i64().unwrap_or_default());
        clamp_records += i128::from(table["clamps"]["records"].as_i64().unwrap_or_default());
    }
    require(
        json!(row_records) == copy["inserted_rows"],
        "inserted-row total drift",
    )?;
    require(
        json!(clamp_records) == copy["clamped_rows"],
        "clamped-row total drift",
    )?;
    require(
        json!(row_records - clamp_records) == copy["new_entities"],
        "new-entity total drift",
    )?;
    require(
        copy_bytes == i128::from(expected.copy_payload_bytes),
        "COPY payload-byte total drift",
    )?;
    require(
        copy["file_set_sha256"] == json!(expected.copy_file_set_sha256),
        "COPY set drift",
    )?;
    let poi_table = tables
        .iter()
        .find(|t| t["postgres_table"] == json!("poi2$"))
        .cloned()
        .unwrap_or(Value::Null);
    for kind in ["rows", "clamps"] {
        let observed = json!({"records": poi_table[kind]["records"], "bytes": poi_table[kind]["bytes"], "sha256": poi_table[kind]["sha256"]});
        require(observed == poi[kind], format!("PoI {kind} identity drift"))?;
    }
    require(
        *ready
            == json!({"version": 1, "manifest_file": "manifest.json", "manifest_sha256": expected.manifest_sha256, "file_set_sha256": expected.copy_file_set_sha256}),
        "READY seal drift",
    )
}

/// JSONL where lines starting with `{` are parsed strictly and other lines
/// are kept as strings (the compute event log mixes both).
fn jsonl(payload: &[u8], label: &str) -> Result<Vec<Value>> {
    let text = std::str::from_utf8(payload)
        .map_err(|e| VerificationError(format!("invalid JSON: {label}: {e}")))?;
    text.lines()
        .enumerate()
        .map(|(index, line)| {
            if line.starts_with('{') {
                load_json_bytes(line.as_bytes(), &format!("{label}:{}", index + 1))
            } else {
                Ok(Value::String(line.to_string()))
            }
        })
        .collect()
}

fn verify_archive_semantics(
    files: &BTreeMap<String, Vec<u8>>,
    payloads: &BTreeMap<String, Vec<u8>>,
) -> Result<()> {
    for (archive_name, local_name) in [
        (
            "run/spools/segment-33374155-33474154.ready/manifest.json",
            "uniswap-v4-base-v0.5.0-q8-manifest.json",
        ),
        (
            "run/spools/segment-33374155-33474154.ready/READY.json",
            "uniswap-v4-base-v0.5.0-q8-READY.json",
        ),
        (
            "run/spools/segment-33474155-33574154.ready/manifest.json",
            "uniswap-v4-base-v0.5.0-q8-restore-manifest.json",
        ),
        (
            "run/spools/segment-33474155-33574154.ready/READY.json",
            "uniswap-v4-base-v0.5.0-q8-restore-READY.json",
        ),
    ] {
        require(
            files[archive_name] == payloads[local_name],
            format!("archive/source fixture drift: {archive_name}"),
        )?;
    }
    let evidence = load_json_bytes(&files["compute-evidence.json"], "compute evidence")?;
    require(
        evidence["status"] == json!("compute-complete")
            && evidence["mode"] == json!("compute-only"),
        "compute evidence status drift",
    )?;
    require(
        evidence["blocks"] == json!(200000),
        "compute evidence block-count drift",
    )?;
    require(
        evidence["postgres_writes"] == Value::Bool(false),
        "historical PostgreSQL-write claim drift",
    )?;
    require(
        evidence["postgres_credentials_mounted"] == Value::Bool(false),
        "historical credential claim drift",
    )?;
    let parity = load_json_bytes(&files["compute-parity.json"], "compute parity")?;
    require(
        parity["scope"] == json!("compute-checkpoint-and-copy-hashes"),
        "compute parity scope drift",
    )?;
    require(
        parity["promotion_ready"] == Value::Bool(false),
        "historical promotion claim drift",
    )?;
    require(
        parity["missing_gate"] == json!("stopped-clone-sql-physical-poi-graphql-and-lifecycle"),
        "missing-gate drift",
    )?;
    let segments = parity["segments"].as_array().cloned().unwrap_or_default();
    require(
        parity["segments"].is_array() && segments.len() == 2,
        "archive segment inventory drift",
    )?;
    for (observed, expected) in segments.iter().zip([&CERTIFIED, &RESTORE]) {
        require(
            observed["target_head_block"] == json!(expected.end_block),
            "archive target drift",
        )?;
        require(
            observed["target_head_hash"] == json!(expected.target_hash),
            "archive target hash drift",
        )?;
        require(
            observed["copy_file_set_sha256"] == json!(expected.copy_file_set_sha256),
            "archive COPY-set drift",
        )?;
        require(
            observed["checkpoint"]
                == json!({"bytes": expected.checkpoint_bytes, "sha256": expected.checkpoint_sha256}),
            "archive checkpoint drift",
        )?;
        require(
            observed["copy_table_count"] == json!(19),
            "archive COPY table-count drift",
        )?;
        require(
            observed["seed_preserved_table"] == json!("data_sources$"),
            "archive seed table drift",
        )?;
        require(
            observed["input_stream_exact"] == Value::Bool(true),
            "historical input-shape flag drift",
        )?;
    }
    require(
        parity["gates"]["input_streams_exact"] == Value::Bool(true),
        "historical input-shape gate drift",
    )?;
    let progress = jsonl(&files["compute-progress.jsonl"], "progress")?;
    let outputs = jsonl(&files["compute-output.jsonl"], "output")?;
    require(
        progress.len() == 2 && outputs.len() == 2,
        "archive progress/output inventory drift",
    )?;
    let events = jsonl(&files["compute-events.jsonl"], "events")?;
    let strings: Vec<&str> = events.iter().filter_map(Value::as_str).collect();
    require(
        strings
            == [
                "native protobuf stream complete: frames=99248 payload_bytes=9061879073 last_block=33474154",
                "native protobuf stream complete: frames=97580 payload_bytes=6948696921 last_block=33574154",
            ],
        "native stream-shape receipt drift",
    )?;
    let performance =
        load_json_bytes(&files["compute-performance-comparison.json"], "performance")?;
    require(
        performance["status"] == json!("comparison-not-faster"),
        "performance status drift",
    )?;
    require(
        performance["promotion_ready"] == Value::Bool(false),
        "performance promotion drift",
    )
}

fn verify_reference(
    root: &Path,
    reference: &Value,
    payloads: &BTreeMap<String, Vec<u8>>,
    locks: &[FileLock],
) -> Result<()> {
    require(
        key_set(reference)
            == set_of(&[
                "format_version",
                "reference_id",
                "status",
                "network",
                "deployment",
                "scratch",
                "certification_execution",
                "contracts",
                "runtime",
                "execution",
                "seed",
                "certified_segment",
                "restore_segment",
                "lifecycle",
                "historical_archive_declaration",
            ]),
        "source reference inventory drift",
    )?;
    reject_forbidden_reference_claims(reference, "reference")?;
    require(
        reference["status"] == json!("declared-historical-reference-metadata"),
        "reference status drift",
    )?;
    require(
        key_set(&reference["seed"])
            == set_of(&[
                "block",
                "hash",
                "checkpoint_bytes",
                "checkpoint_sha256",
                "manifest_sha256",
            ]),
        "source seed inventory drift",
    )?;
    for key in ["certified_segment", "restore_segment"] {
        require(
            key_set(&reference[key])
                == set_of(&[
                    "start_block",
                    "end_block",
                    "blocks",
                    "target_hash",
                    "input_frames",
                    "input_payload_bytes",
                    "manifest_sha256",
                    "ready_sha256",
                    "copy_file_set_sha256",
                    "checkpoint_bytes",
                    "checkpoint_sha256",
                    "inserted_rows",
                    "clamped_rows",
                    "new_entities",
                    "copy_tables",
                    "seed_preserved_table",
                    "poi",
                ]),
            format!("{key} source inventory drift"),
        )?;
    }
    require(
        key_set(&reference["runtime"])
            == set_of(&[
                "release",
                "release_commit",
                "release_tree",
                "producer_commit",
                "producer_tree",
                "platform",
                "image",
                "binary_sha256",
            ]),
        "runtime source inventory drift",
    )?;
    require(
        key_set(&reference["contracts"])
            == set_of(&[
                "producer",
                "current",
                "shared_semantics",
                "producer_runtime_is_historical",
            ]),
        "contracts source inventory drift",
    )?;
    require(
        key_set(&reference["execution"])
            == set_of(&[
                "poi_workers",
                "poi_batch_size",
                "protobuf_decode_ahead",
                "asynchronous_spool_writers",
                "asynchronous_spool_queue_buffers",
                "allocator",
                "parallel_workers",
            ]),
        "execution source inventory drift",
    )?;
    require(
        key_set(&reference["certification_execution"])
            == set_of(&[
                "source_observations",
                "file_backed_observations",
                "api_backed_observations",
                "raw_source_paths",
                "source_workflow_pods",
                "producer_pods",
                "nonproducer_pods",
                "collector_pods",
                "two_phase_total_pods",
                "workflow_generate_name_prefix",
                "experiment_id_max_length",
                "namespace",
                "source_service_account",
                "collector_service_account",
                "source_observation_contract",
                "pod_topology",
                "source_handoff",
                "workload_contract",
                "images",
                "trust",
                "kubernetes_source_provenance",
                "graphman",
            ]),
        "certification execution inventory drift",
    )?;
    require_strict(
        &reference["scratch"],
        &json!({"namespace": "subgraphs-backfill", "database": "graph_backfill", "schema": "sgd2", "forbidden_schemas": ["sgd1246", "sgd5303"], "starting_head": {"block": 33574154, "hash": RESTORE.target_hash}}),
        "scratch safety boundary drift",
    )?;
    require_strict(
        &reference["historical_archive_declaration"],
        &json!({"availability": "unavailable-in-this-certification-path", "acceptance_role": "none", "declared_name": ARCHIVE_NAME, "declared_bytes": 9047, "declared_sha256": ARCHIVE_SHA256, "note": "Historical metadata only; a new live two-phase replay is required to establish a certificate."}),
        "source archive declaration drift",
    )?;
    let current = regular_bytes(
        &root.join(CURRENT_COMPATIBILITY_PATH),
        "current compatibility",
    )?;
    require(
        reference["contracts"]["current"]["sha256"] == json!(sha256(&current)),
        "current compatibility drift",
    )?;
    let producer_lock = locks
        .iter()
        .find(|l| l.local_path == PRODUCER_COMPATIBILITY_NAME)
        .expect("producer lock");
    require(
        reference["contracts"]["producer"]["sha256"] == json!(producer_lock.sha256),
        "producer compatibility drift",
    )?;
    require(
        reference["contracts"]["producer_runtime_is_historical"] == Value::Bool(true),
        "historical producer boundary drift",
    )?;
    let parent = load_json(&root.join(PARENT_CLOSURE_PATH))?;
    require(
        reference["runtime"]["release_commit"] == parent["source"]["commit"],
        "engine release commit drift",
    )?;
    require(
        reference["runtime"]["release_tree"] == parent["source"]["tree"],
        "engine release tree drift",
    )?;
    let pick = |value: &Value| json!({"release": value["release"], "platform": value["platform"], "image": value["image"], "binary_sha256": value["binary_sha256"]});
    require_strict(
        &pick(&reference["runtime"]),
        &pick(&parent["engine"]),
        "engine runtime identity drift",
    )?;
    let observations = load_json_bytes(&payloads[OBSERVATIONS_NAME], "source observations")?;
    let certification = &reference["certification_execution"];
    require(
        certification.is_object(),
        "certification execution contract missing",
    )?;
    let counts = |v: &Value| {
        json!({
            "source_observations": v["source_observations"], "file_backed_observations": v["file_backed_observations"], "api_backed_observations": v["api_backed_observations"],
            "raw_source_paths": v["raw_source_paths"], "source_workflow_pods": v["source_workflow_pods"], "producer_pods": v["producer_pods"], "nonproducer_pods": v["nonproducer_pods"],
            "collector_pods": v["collector_pods"], "two_phase_total_pods": v["two_phase_total_pods"],
        })
    };
    require_strict(
        &counts(certification),
        &json!({"source_observations": 53, "file_backed_observations": 51, "api_backed_observations": 2, "raw_source_paths": 59, "source_workflow_pods": 35, "producer_pods": 20, "nonproducer_pods": 15, "collector_pods": 1, "two_phase_total_pods": 36}),
        "certification execution counts drift",
    )?;
    require_strict(
        &certification["source_observation_contract"],
        &json!({"schema": "pinax.v4-reference-replay-source-observations.v1", "scope": "successful-source-workflow", "path": "fixtures/uniswap-v4-base-v4-reference-source-observations.json", "sha256": sha256(&payloads[OBSERVATIONS_NAME]), "canonical_parameter_sha256": "3be33736079a342318d1674eaa091e260a2b77a05dec91e91f86bb542fa0ef17"}),
        "source-observation reference binding drift",
    )?;
    require_strict(
        &certification["pod_topology"],
        &json!({"schema": "pinax.v4-reference-replay-clean-run-pod-topology.v1", "path": "fixtures/uniswap-v4-base-v4-reference-pod-topology.json", "sha256": sha256(&payloads[TOPOLOGY_NAME])}),
        "pod-topology reference binding drift",
    )?;
    require(
        observations["schema"] == json!("pinax.v4-reference-replay-source-observations.v1"),
        "source-observation schema drift",
    )?;
    require(
        observations["scope"] == json!("successful-source-workflow"),
        "source-observation scope drift",
    )?;
    let entries = observations["observations"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    require(
        observations["count"] == json!(53)
            && observations["observations"].is_array()
            && entries.len() == 53,
        "source-observation inventory drift",
    )?;
    let raw_paths: Vec<&Value> = entries
        .iter()
        .flat_map(|e| {
            e["raw_paths"]
                .as_array()
                .map(|a| a.iter().collect::<Vec<_>>())
                .unwrap_or_default()
        })
        .collect();
    require(raw_paths.len() == 59, "raw-path count drift")?;
    require(
        raw_paths
            .iter()
            .map(|p| p.to_string())
            .collect::<BTreeSet<_>>()
            .len()
            == 58,
        "unique raw-path count drift",
    )?;
    require(
        entries
            .iter()
            .filter(|e| e.get("api_source").is_some())
            .count()
            == 2,
        "API observation count drift",
    )?;
    let topology = load_json_bytes(&payloads[TOPOLOGY_NAME], "pod topology")?;
    require(
        topology["schema"] == json!("pinax.v4-reference-replay-clean-run-pod-topology.v1"),
        "pod-topology schema drift",
    )?;
    require(
        topology["policy"] == json!("exact-clean-run-no-retry-pods"),
        "pod-topology policy drift",
    )?;
    require_strict(
        &topology["roles"],
        &expected_topology_roles(),
        "pod-topology role drift",
    )?;
    require_strict(
        &topology["counts"],
        &json!({"source_workflow_pods": 35, "producer_pods": 20, "nonproducer_pods": 15, "primary_main_containers": 35, "user_sidecars": 14, "user_init_containers": 24}),
        "pod-topology counts drift",
    )?;
    let pods = topology["pods"].as_array().cloned().unwrap_or_default();
    require(
        topology["pods"].is_array() && pods.len() == 35,
        "pod-topology inventory drift",
    )?;
    require(
        pods.iter()
            .filter(|p| p["producer"] == Value::Bool(true))
            .count()
            == 20,
        "producer pod count drift",
    )
}

pub fn verify_with_locks(root: &Path, locks: &[FileLock]) -> Result<()> {
    let capsule = root.join(CAPSULE_DIRECTORY);
    let meta = capsule
        .symlink_metadata()
        .map_err(|e| VerificationError(format!("q8 capsule directory is unavailable: {e}")))?;
    require(
        !meta.file_type().is_symlink(),
        "q8 capsule directory must not be a symlink",
    )?;
    require(meta.is_dir(), "q8 capsule path must be a directory")?;
    let mut observed = BTreeSet::new();
    for entry in std::fs::read_dir(&capsule)
        .map_err(|e| VerificationError(format!("q8 capsule directory is unavailable: {e}")))?
    {
        let entry = entry.map_err(|e| VerificationError(e.to_string()))?;
        let name = entry.file_name().to_string_lossy().to_string();
        let meta = entry
            .path()
            .symlink_metadata()
            .map_err(|e| VerificationError(e.to_string()))?;
        require(
            !meta.file_type().is_symlink(),
            format!("q8 capsule entry must not be a symlink: {name}"),
        )?;
        require(
            meta.is_file(),
            format!("q8 capsule contains an unexpected directory: {name}"),
        )?;
        observed.insert(name);
    }
    let mut expected: BTreeSet<String> = locks.iter().map(|l| l.local_path.to_string()).collect();
    expected.insert("README.md".into());
    expected.insert("closure.json".into());
    expected.insert(ARCHIVE_NAME.into());
    require(observed == expected, "q8 capsule file inventory drift")?;
    let closure = load_json(&root.join(CLOSURE_PATH))?;
    require(closure.is_object(), "closure must be an object")?;
    verify_closure(&closure, locks)?;
    let mut payloads: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    for lock in locks {
        let payload = verify_lock(
            &capsule.join(lock.local_path),
            lock.bytes,
            &lock.sha256,
            &format!("q8 source file {}", lock.local_path),
        )?;
        require(
            git_blob_sha1(&payload) == lock.git_blob,
            format!("q8 source file {} Git blob drift", lock.local_path),
        )?;
        payloads.insert(lock.local_path.to_string(), payload);
    }
    let archive_files = verify_archive(&capsule.join(ARCHIVE_NAME))?;
    let reference = load_json_bytes(&payloads[REFERENCE_NAME], "q8 reference")?;
    require(
        reference["network"] == json!("base") && reference["deployment"] == json!(DEPLOYMENT),
        "reference identity drift",
    )?;
    require_strict(
        &json!({"block": reference["seed"]["block"], "hash": reference["seed"]["hash"], "checkpoint_bytes": reference["seed"]["checkpoint_bytes"], "checkpoint_sha256": reference["seed"]["checkpoint_sha256"]}),
        &json!({"block": SEED_BLOCK, "hash": SEED_HASH, "checkpoint_bytes": SEED_CHECKPOINT_BYTES, "checkpoint_sha256": SEED_CHECKPOINT_SHA256}),
        "reference seed identity drift",
    )?;
    let seed_hash = reference["seed"]["hash"]
        .as_str()
        .unwrap_or_default()
        .to_string();
    let manifests: [(&Segment, &str, &str, u64, String); 2] = [
        (
            &CERTIFIED,
            "uniswap-v4-base-v0.5.0-q8-manifest.json",
            "uniswap-v4-base-v0.5.0-q8-READY.json",
            33374154,
            seed_hash,
        ),
        (
            &RESTORE,
            "uniswap-v4-base-v0.5.0-q8-restore-manifest.json",
            "uniswap-v4-base-v0.5.0-q8-restore-READY.json",
            33474154,
            CERTIFIED.target_hash.to_string(),
        ),
    ];
    for (segment, manifest_name, ready_name, head_block, head_hash) in manifests {
        let source_segment = &reference[segment.key];
        require(
            source_segment.is_object(),
            format!("{} reference missing", segment.key),
        )?;
        for (field, value) in segment.expected_fields() {
            if field != "copy_payload_bytes" {
                require(
                    source_segment[field] == value,
                    format!("{} reference {field} drift", segment.key),
                )?;
            }
        }
        require(
            source_segment["blocks"] == json!(100000),
            format!("{} reference block-count drift", segment.key),
        )?;
        require(
            source_segment["copy_tables"] == json!(19),
            format!("{} reference COPY count drift", segment.key),
        )?;
        require(
            source_segment["seed_preserved_table"] == json!("data_sources$"),
            format!("{} reference seed table drift", segment.key),
        )?;
        let manifest = load_json_bytes(&payloads[manifest_name], manifest_name)?;
        let ready = load_json_bytes(&payloads[ready_name], ready_name)?;
        verify_manifest(
            &manifest,
            &ready,
            segment,
            head_block,
            &head_hash,
            &source_segment["poi"],
        )?;
        let summary = |v: &Value| json!({"inserted_rows": v["inserted_rows"], "clamped_rows": v["clamped_rows"], "new_entities": v["new_entities"]});
        require_strict(
            &summary(source_segment),
            &summary(&manifest["copy"]),
            &format!("{} row-summary cross-reference drift", segment.key),
        )?;
    }
    verify_archive_semantics(&archive_files, &payloads)?;
    verify_reference(root, &reference, &payloads, locks)
}

pub fn verify(root: &Path) -> Result<()> {
    let root = root
        .canonicalize()
        .map_err(|e| VerificationError(format!("root is unavailable: {e}")))?;
    verify_with_locks(&root, &expected_file_locks())
}

pub fn success_json() -> String {
    serde_json::to_string(&json!({
        "archive_sha256": ARCHIVE_SHA256,
        "contract": CONTRACT,
        "criterion_2_complete": false,
        "status": "verified-declared-metadata-only",
        "acceptance_role": "none",
    }))
    .expect("serializes")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
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

    struct Fixture {
        dir: tempfile::TempDir,
        locks: Vec<FileLock>,
    }

    impl Fixture {
        fn new() -> Fixture {
            let dir = tempfile::tempdir().unwrap();
            let parent = Path::new(CAPSULE_DIRECTORY).parent().unwrap();
            copy_dir(&repository().join(parent), &dir.path().join(parent));
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
        fn fixture_path(&self, name: &str) -> PathBuf {
            self.capsule().join(name)
        }
        fn read(&self, path: &Path) -> Value {
            serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
        }
        fn write(&self, path: &Path, value: &Value) {
            fs::write(
                path,
                format!("{}\n", serde_json::to_string_pretty(value).unwrap()),
            )
            .unwrap();
        }
        fn read_fixture(&self, name: &str) -> Value {
            self.read(&self.fixture_path(name))
        }
        fn write_fixture(&self, name: &str, value: &Value) {
            self.write(&self.fixture_path(name), value)
        }
        fn read_closure(&self) -> Value {
            self.read(&self.root().join(CLOSURE_PATH))
        }
        fn write_closure(&self, value: &Value) {
            self.write(&self.root().join(CLOSURE_PATH), value)
        }
        fn bind_reference_contract_sha(&self, contract: &str, fixture: &str) {
            let mut reference = self.read_fixture(REFERENCE_NAME);
            reference["certification_execution"][contract]["sha256"] =
                json!(sha256(&fs::read(self.fixture_path(fixture)).unwrap()));
            self.write_fixture(REFERENCE_NAME, &reference);
        }
        fn accept_modified_source_file(&mut self, name: &str, refresh_blob: bool) {
            let payload = fs::read(self.fixture_path(name)).unwrap();
            let lock = self
                .locks
                .iter_mut()
                .find(|l| l.local_path == name)
                .unwrap();
            lock.bytes = payload.len() as u64;
            lock.sha256 = sha256(&payload);
            if refresh_blob {
                lock.git_blob = git_blob_sha1(&payload);
            }
            let (bytes, sha, blob) = (lock.bytes, lock.sha256.clone(), lock.git_blob.clone());
            let mut closure = self.read_closure();
            for record in closure["files"].as_array_mut().unwrap() {
                if record["local_path"] == json!(name) {
                    record["bytes"] = json!(bytes);
                    record["sha256"] = json!(sha);
                    record["git_blob"] = json!(blob);
                }
            }
            self.write_closure(&closure);
        }
        fn error(&self) -> String {
            verify_with_locks(self.root(), &self.locks)
                .unwrap_err()
                .to_string()
        }
    }

    #[test]
    fn exact_q8_capsule_passes() {
        verify(&repository()).unwrap();
        let f = Fixture::new();
        verify_with_locks(f.root(), &f.locks).unwrap();
    }

    #[test]
    fn tampered_source_fixture_bytes_are_rejected() {
        let f = Fixture::new();
        let path = f.fixture_path(REFERENCE_NAME);
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
    fn source_git_blob_claim_cannot_be_stale_after_digest_move() {
        let mut f = Fixture::new();
        let path = f.fixture_path(REFERENCE_NAME);
        let mut bytes = fs::read(&path).unwrap();
        bytes.push(b'\n');
        fs::write(&path, bytes).unwrap();
        f.accept_modified_source_file(REFERENCE_NAME, false);
        assert!(f.error().contains("Git blob drift"));
    }

    #[test]
    fn tampered_compact_archive_is_rejected() {
        let f = Fixture::new();
        let path = f.fixture_path(ARCHIVE_NAME);
        let mut bytes = fs::read(&path).unwrap();
        bytes.push(0);
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
        fs::write(
            f.capsule().join("execution-complete.json"),
            "{\"criterion_2_complete\":true}\n",
        )
        .unwrap();
        assert!(f.error().contains("file inventory drift"));
    }

    #[test]
    fn unlisted_capsule_directory_is_rejected() {
        let f = Fixture::new();
        let claims = f.capsule().join("claims");
        fs::create_dir_all(&claims).unwrap();
        fs::write(
            claims.join("production.json"),
            "{\"production_ready\":true}\n",
        )
        .unwrap();
        assert!(f.error().contains("unexpected directory"));
    }

    #[test]
    fn symlinked_source_fixture_is_rejected() {
        let f = Fixture::new();
        let path = f.fixture_path("uniswap-v4-base-v0.5.0-q8-READY.json");
        fs::remove_file(&path).unwrap();
        std::os::unix::fs::symlink(
            f.fixture_path("uniswap-v4-base-v0.5.0-q8-restore-READY.json"),
            &path,
        )
        .unwrap();
        assert!(f.error().contains("symlink"));
    }

    #[test]
    fn duplicate_closure_key_is_rejected() {
        let f = Fixture::new();
        let raw = fs::read_to_string(f.root().join(CLOSURE_PATH)).unwrap();
        fs::write(
            f.root().join(CLOSURE_PATH),
            raw.replacen("{\n", "{\n  \"format_version\": 1,\n", 1),
        )
        .unwrap();
        assert!(f.error().contains("duplicate JSON key"));
    }

    #[test]
    fn criterion_2_completion_claim_is_rejected() {
        let f = Fixture::new();
        let mut closure = f.read_closure();
        closure["scope"]["fully_satisfied_acceptance_criteria"] = json!([2]);
        closure["gates"]["criterion_2_complete"] = json!(true);
        f.write_closure(&closure);
        let error = f.error();
        assert!(
            error.contains("acceptance scope drift") || error.contains("operational gate drift"),
            "{error}"
        );
    }

    #[test]
    fn raw_frame_retention_claim_is_rejected() {
        let f = Fixture::new();
        let mut closure = f.read_closure();
        closure["retention"]["raw_frame_payload_bytes"] = json!(true);
        closure["retention"]["raw_frame_stream_digest"] = json!(true);
        f.write_closure(&closure);
        assert!(f.error().contains("retention boundary drift"));
    }

    #[test]
    fn historical_input_shape_cannot_be_relabelled_byte_exact() {
        let f = Fixture::new();
        let mut closure = f.read_closure();
        closure["historical_field_semantics"]["input_stream_exact"]["meaning"] =
            json!("raw-byte-identity");
        closure["historical_field_semantics"]["input_stream_exact"]["raw_byte_identity_proven"] =
            json!(true);
        f.write_closure(&closure);
        assert!(f.error().contains("historical field semantics drift"));
    }

    #[test]
    fn numeric_zero_is_not_accepted_as_false_gate() {
        let f = Fixture::new();
        let mut closure = f.read_closure();
        closure["gates"]["criterion_2_complete"] = json!(0);
        f.write_closure(&closure);
        assert!(f.error().contains("operational gate drift"));
    }

    #[test]
    fn numeric_retention_and_archive_booleans_are_rejected() {
        let f = Fixture::new();
        let mut closure = f.read_closure();
        closure["retention"]["manifest_bytes"] = json!(1);
        closure["recovered_archive"]["source_reference_availability_is_stale"] = json!(1);
        f.write_closure(&closure);
        let error = f.error();
        assert!(
            error.contains("archive closure drift") || error.contains("retention boundary drift"),
            "{error}"
        );
    }

    #[test]
    fn archive_acceptance_role_cannot_be_promoted() {
        let f = Fixture::new();
        let mut closure = f.read_closure();
        closure["recovered_archive"]["acceptance_role"] = json!("criterion-2-oracle");
        f.write_closure(&closure);
        assert!(f.error().contains("archive closure drift"));
    }

    #[test]
    fn non_claim_cannot_be_removed() {
        let f = Fixture::new();
        let mut closure = f.read_closure();
        closure["non_claims"].as_array_mut().unwrap().pop();
        f.write_closure(&closure);
        assert!(f.error().contains("non-claim boundary drift"));
    }

    #[test]
    fn source_unavailable_declaration_cannot_be_silently_rewritten() {
        let mut f = Fixture::new();
        let mut reference = f.read_fixture(REFERENCE_NAME);
        reference["historical_archive_declaration"]["availability"] = json!("repository-retained");
        f.write_fixture(REFERENCE_NAME, &reference);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("source archive declaration drift"));
    }

    #[test]
    fn scratch_schema_cannot_name_protected_source() {
        let mut f = Fixture::new();
        let mut reference = f.read_fixture(REFERENCE_NAME);
        reference["scratch"]["schema"] = json!("sgd1246");
        reference["scratch"]["forbidden_schemas"] = json!([]);
        f.write_fixture(REFERENCE_NAME, &reference);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("scratch safety boundary drift"));
    }

    #[test]
    fn poi_drift_fails_after_reference_hash_move() {
        let mut f = Fixture::new();
        let mut reference = f.read_fixture(REFERENCE_NAME);
        reference["certified_segment"]["poi"]["rows"]["sha256"] = json!("0".repeat(64));
        f.write_fixture(REFERENCE_NAME, &reference);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("PoI rows identity drift"));
    }

    #[test]
    fn source_observation_count_drift_fails_after_hash_move() {
        let mut f = Fixture::new();
        let mut observations = f.read_fixture(OBSERVATIONS_NAME);
        observations["count"] = json!(52);
        f.write_fixture(OBSERVATIONS_NAME, &observations);
        f.bind_reference_contract_sha("source_observation_contract", OBSERVATIONS_NAME);
        f.accept_modified_source_file(OBSERVATIONS_NAME, true);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("source-observation inventory drift"));
    }

    #[test]
    fn source_observation_scope_drift_fails_after_hash_move() {
        let mut f = Fixture::new();
        let mut observations = f.read_fixture(OBSERVATIONS_NAME);
        observations["scope"] = json!("failed-or-incomplete-workflow");
        f.write_fixture(OBSERVATIONS_NAME, &observations);
        f.bind_reference_contract_sha("source_observation_contract", OBSERVATIONS_NAME);
        f.accept_modified_source_file(OBSERVATIONS_NAME, true);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("source-observation scope drift"));
    }

    #[test]
    fn pod_topology_drift_fails_after_hash_move() {
        let mut f = Fixture::new();
        let mut topology = f.read_fixture(TOPOLOGY_NAME);
        topology["counts"]["producer_pods"] = json!(19);
        f.write_fixture(TOPOLOGY_NAME, &topology);
        f.bind_reference_contract_sha("pod_topology", TOPOLOGY_NAME);
        f.accept_modified_source_file(TOPOLOGY_NAME, true);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("pod-topology counts drift"));
    }

    #[test]
    fn pod_topology_policy_drift_fails_after_hash_move() {
        let mut f = Fixture::new();
        let mut topology = f.read_fixture(TOPOLOGY_NAME);
        topology["policy"] = json!("allow-retry-pods");
        f.write_fixture(TOPOLOGY_NAME, &topology);
        f.bind_reference_contract_sha("pod_topology", TOPOLOGY_NAME);
        f.accept_modified_source_file(TOPOLOGY_NAME, true);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("pod-topology policy drift"));
    }

    #[test]
    fn seed_checkpoint_drift_fails_after_reference_hash_move() {
        let mut f = Fixture::new();
        let mut reference = f.read_fixture(REFERENCE_NAME);
        reference["seed"]["checkpoint_bytes"] = json!(1);
        reference["seed"]["checkpoint_sha256"] = json!("0".repeat(64));
        f.write_fixture(REFERENCE_NAME, &reference);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("reference seed identity drift"));
    }

    #[test]
    fn segment_row_summary_drift_fails_after_reference_hash_move() {
        let mut f = Fixture::new();
        let mut reference = f.read_fixture(REFERENCE_NAME);
        for field in ["inserted_rows", "clamped_rows", "new_entities"] {
            reference["certified_segment"][field] = json!(0);
        }
        f.write_fixture(REFERENCE_NAME, &reference);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f
            .error()
            .contains("certified_segment row-summary cross-reference drift"));
    }

    #[test]
    fn nested_operational_claim_is_rejected_after_hash_move() {
        let mut f = Fixture::new();
        let mut reference = f.read_fixture(REFERENCE_NAME);
        reference["certified_segment"]["criterion_2_complete"] = json!(true);
        f.write_fixture(REFERENCE_NAME, &reference);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        let error = f.error();
        assert!(
            error.contains("certified_segment source inventory drift")
                || error.contains("forbidden operational claim key"),
            "{error}"
        );
    }

    #[test]
    fn runtime_binary_drift_fails_after_reference_hash_move() {
        let mut f = Fixture::new();
        let mut reference = f.read_fixture(REFERENCE_NAME);
        reference["runtime"]["binary_sha256"]["state-replay"] = json!("0".repeat(64));
        f.write_fixture(REFERENCE_NAME, &reference);
        f.accept_modified_source_file(REFERENCE_NAME, true);
        assert!(f.error().contains("engine runtime identity drift"));
    }

    #[test]
    fn q8_capsule_root_symlink_is_rejected() {
        let f = Fixture::new();
        let real = f.capsule().with_file_name("q8-real");
        fs::rename(f.capsule(), &real).unwrap();
        std::os::unix::fs::symlink(&real, f.capsule()).unwrap();
        assert!(f.error().contains("directory must not be a symlink"));
    }

    #[test]
    fn current_compatibility_drift_is_rejected() {
        let f = Fixture::new();
        let path = f.root().join(CURRENT_COMPATIBILITY_PATH);
        let mut bytes = fs::read(&path).unwrap();
        bytes.push(b'\n');
        fs::write(&path, bytes).unwrap();
        assert!(f.error().contains("current compatibility drift"));
    }

    #[test]
    fn strict_equal_distinguishes_types() {
        assert!(!strict_equal(&json!(1), &json!(true)));
        assert!(!strict_equal(&json!(1.0), &json!(1)));
        assert!(strict_equal(
            &json!({"a": [1, "x", null]}),
            &json!({"a": [1, "x", null]})
        ));
        assert!(!strict_equal(&json!({"a": 1, "b": 2}), &json!({"a": 1})));
    }
}
