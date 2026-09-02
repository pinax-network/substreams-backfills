//! Verify the retained, fail-closed Uniswap V3 logical-oracle snapshot.
//!
//! A direct port of the retired `scripts/verify-uniswap-v3-logical-oracle.py` (#110). Every
//! digest, byte count, deployment CID, path, and failure message is carried over
//! unchanged; each Python `VerificationError` becomes an `Err(String)` with the
//! identical text, and I/O or JSON errors fail closed instead of panicking.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Component, Path, PathBuf};

use serde_json::{json, Value};

use crate::target_common::sha256_hex;

const CONTRACT_VERSION: &str = "uniswap-v3-logical-oracle/v1";
const ORACLE_DIRECTORY: &str = "uniswap-v3/oracle/v1";
const CONTRACT_PATH: &str = "uniswap-v3/oracle/v1/contract.json";

const MAINNET_DEPLOYMENT: &str = "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7";
const BASE_DEPLOYMENT: &str = "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP";

/// Exact stdout line the Python verifier prints on success.
pub const SUCCESS_LINE: &str = "verified 9 retained oracle files, exact deployment echoes, current-head absence/positive smokes, mainnet boundary response, Base expected refusal, and 13 fail-closed promotion gates";

/// `EXPECTED_FILE_LOCKS`, in Python insertion order (that order decides which
/// byte or digest drift is reported first).
const EXPECTED_FILE_LOCKS: &[(&str, u64, &str)] = &[
    (
        "discovery/base-boundary-error.json",
        168,
        "cc4435ae749ffcd8b413eaaff19881a6dc2c3caa7b0c40076d2f27bb82291e32",
    ),
    (
        "discovery/base-query-response.json",
        729,
        "34f272caa00a96ef1f4cea9d96371f986b14630a7e3cece64c27208be9f1eb20",
    ),
    (
        "discovery/base-status-response.json",
        1316,
        "6257a9db0e4fb15c4679e23fa591c41699803b267b4944a35b36a9e0882441ee",
    ),
    (
        "discovery/mainnet-boundary-response.json",
        1792,
        "95ab94ae8e98bd04727b6e4c06ffa6ba1de9734a2c80f5cc089a08da9d7950d1",
    ),
    (
        "discovery/mainnet-query-response.json",
        800,
        "b0cf42260add535bd5056a3fa52a3467a9b0c3576ea0ab079ee2681cf03b3964",
    ),
    (
        "discovery/mainnet-status-response.json",
        3873,
        "4b3d7d13a63872fdf09df05a667175ac567b46365e3e513f1e40c0a9c450b7ff",
    ),
    (
        "discovery/manifest.json",
        2288,
        "cfc36b7248bae8a802d27a558fc76c8570c79f914dcd6b7c994ff41a394b024a",
    ),
    (
        "queries/current-and-required-absence.graphql",
        609,
        "8a5eeffeab5213d043ad43c8a09df6352c0be17a49d92a9dc5e8012d54196eac",
    ),
    (
        "queries/graft-boundary-state.graphql",
        1262,
        "93baa390e0b6a9aedde30a97b11b43bce02368e2ece21b409ee171433e0d906a",
    ),
];

/// One retained-byte lock; owned so a negative test can move a single lock the
/// way the Python test mutates `MODULE.EXPECTED_FILE_LOCKS`.
#[derive(Clone, Debug, PartialEq, Eq)]
struct FileLock {
    path: &'static str,
    bytes: u64,
    sha256: String,
}

fn expected_file_locks() -> Vec<FileLock> {
    EXPECTED_FILE_LOCKS
        .iter()
        .map(|(path, bytes, sha256)| FileLock {
            path,
            bytes: *bytes,
            sha256: sha256.to_string(),
        })
        .collect()
}

fn expected_source_identity() -> Value {
    json!({
        "observed_origin": "https://www.lodestar-dashboard.com",
        "repository": "https://github.com/nightswatchhq/lodestar",
        "revision": "18c8e56189309b1b4948bfb4992cbe12df8e4879",
        "tree": "70f3383207170dc3687628f21366c731c78ec343",
        "committed_at_utc": "2026-08-28T11:00:59Z",
        "production_revision_attested": false,
        "source_matches_observed_behavior_only": true,
        "files": [
            {
                "path": "src/app/api/indexing-status/[hash]/route.ts",
                "git_blob": "c59cfb7ec86aa0ca716e8e9466cdf6a14d54c920",
                "sha256": "4119918a86d4e8c315abb6be14e82a566252038ec3c9c1d354031e96c3eb4e11",
            },
            {
                "path": "src/app/api/subgraph-playground/[hash]/route.ts",
                "git_blob": "b928cb7d504bef2cec3daf06ded9fad2b2b43931",
                "sha256": "f1bf4cbec99d46323260c0d0a51f133485f1d1da26502719893f153dde6c34b4",
            },
            {
                "path": "src/lib/indexing-status.ts",
                "git_blob": "0329344dbd1b04bf358df6a96ffa316db7126412",
                "sha256": "93c4d61a934e4304e1b3b2c1dc92555248c1d6487779641ce1edea8b2dbb2b81",
            },
        ],
    })
}

fn expected_observed_capabilities() -> Value {
    json!({
        "deployment_scoped_gateway_query_succeeded": true,
        "deployment_echo_matched": true,
        "current_head_required_absence_smoke_observed": true,
        "mainnet_current_deployment_boundary_query_succeeded": true,
        "base_current_deployment_boundary_query_succeeded": false,
        "indexer_status_discovery_succeeded": true,
    })
}

fn expected_promotion_gates() -> Value {
    json!({
        "production_revision_attested": false,
        "per_query_indexer_pinned": false,
        "graph_node_version_pinned": false,
        "canonical_historic_block_hash_sidecar_retained": false,
        "ancestor_deployment_query_access": false,
        "base_historical_boundary_query_access": false,
        "authoritative_logical_oracle": false,
        "required_absence_certified": false,
        "logical_history_parity": false,
        "physical_history_parity": false,
        "proof_of_indexing_parity": false,
        "final_parity_package": false,
        "production_backfill_allowed": false,
    })
}

fn expected_networks() -> Value {
    json!({
        "mainnet": {
            "deployment": MAINNET_DEPLOYMENT,
            "current_response": "discovery/mainnet-query-response.json",
            "status_response": "discovery/mainnet-status-response.json",
            "current_empty_entity_smoke": ["Collect", "Flash", "TickHourData"],
            "current_positive_entity_smoke": ["TickDayData", "Position", "Pool"],
            "boundary": {
                "status": "observed_without_canonical_hash_or_timestamp",
                "before": 19470000,
                "after": 19470001,
                "response": "discovery/mainnet-boundary-response.json",
            },
        },
        "base": {
            "deployment": BASE_DEPLOYMENT,
            "current_response": "discovery/base-query-response.json",
            "status_response": "discovery/base-status-response.json",
            "current_empty_entity_smoke": ["Collect", "Flash", "TickHourData"],
            "current_positive_entity_smoke": ["TickDayData", "Position", "Pool"],
            "boundary": {
                "status": "expected_refusal_missing_pruned_block",
                "before": 19852000,
                "after": 19852001,
                "response": "discovery/base-boundary-error.json",
                "required_error_fragment": "missing block: 19852000",
            },
        },
    })
}

const EXPECTED_MAINNET_INDEXERS: &[&str] = &[
    "0xf92f430dd8567b0d466358c79594ab58d919a6d4",
    "0x1b7e0068ca1d7929c8c56408d766e1510e54d98d",
    "0x326c584e0f0eab1f1f83c93cc6ae1acc0feba0bc",
    "0x4e5c87772c29381bcabc58c3f182b6633b5a274a",
    "0xfeff9093f6b32d0e5cddba743b06a1fedb87c004",
];
const EXPECTED_BASE_INDEXERS: &[&str] = &["0xf92f430dd8567b0d466358c79594ab58d919a6d4"];

fn expected_indexers(network: &str) -> &'static [&'static str] {
    if network == "mainnet" {
        EXPECTED_MAINNET_INDEXERS
    } else {
        EXPECTED_BASE_INDEXERS
    }
}

/// `EXPECTED_HEALTH_COUNTS`: (total, healthy, unhealthy).
fn expected_health_counts(network: &str) -> (i64, i64, i64) {
    if network == "mainnet" {
        (5, 4, 1)
    } else {
        (1, 1, 0)
    }
}

const CURRENT_QUERY_TOKENS: &[&str] = &[
    "query CurrentAndRequiredAbsence",
    "_meta",
    "deployment",
    "hasIndexingErrors",
    "collects(first: 1",
    "flashes(first: 1",
    "tickHourDatas(first: 1",
    "tickDayDatas(first: 1",
    "positions(first: 1",
    "pools(first: 1",
    "feeGrowthGlobal0X128",
    "feeGrowthGlobal1X128",
];

const BOUNDARY_QUERY_TOKENS: &[&str] = &[
    "query GraftBoundaryState($before: Int!, $after: Int!)",
    "beforeMeta: _meta(block: { number: $before })",
    "afterMeta: _meta(block: { number: $after })",
    "beforePools: pools(",
    "afterPools: pools(",
    "beforePositions: positions(",
    "afterPositions: positions(",
    "block: { number: $before }",
    "block: { number: $after }",
];

// ---------------------------------------------------------------------------
// Python-shaped helpers
// ---------------------------------------------------------------------------

/// `repr()` of a Python `str`.
fn py_repr_str(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(text.len() + 2);
    out.push(quote);
    for character in text.chars() {
        match character {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `repr()` of a Python `list[str]`, as `sorted(...)` renders inside f-strings.
fn py_list_repr<'a>(items: impl IntoIterator<Item = &'a str>) -> String {
    let rendered: Vec<String> = items.into_iter().map(py_repr_str).collect();
    format!("[{}]", rendered.join(", "))
}

/// `str()` of a decoded JSON value: strings pass through, everything else
/// renders the way Python would print the decoded object.
fn py_str(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Null => "None".to_string(),
        Value::Number(number) => number.to_string(),
        other => other.to_string(),
    }
}

/// `type(value) is int`: a JSON integer, never a bool and never a float.
fn python_int(value: &Value) -> Option<i128> {
    match value {
        Value::Number(number) => number
            .as_i64()
            .map(i128::from)
            .or_else(|| number.as_u64().map(i128::from)),
        _ => None,
    }
}

/// `HEX_HASH_RE.fullmatch`.
fn is_hex_hash(text: &str) -> bool {
    let bytes = text.as_bytes();
    bytes.len() == 66
        && text.starts_with("0x")
        && bytes[2..]
            .iter()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

/// `INTEGER_STRING_RE.fullmatch`.
fn is_integer_string(text: &str) -> bool {
    let digits = text.strip_prefix('-').unwrap_or(text);
    !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit())
}

/// `re.fullmatch(r"2026-08-28T11:[0-9]{2}:[0-9]{2}Z", value)`.
fn is_observed_at(text: &str) -> bool {
    let bytes = text.as_bytes();
    bytes.len() == 20
        && text.starts_with("2026-08-28T11:")
        && bytes[14].is_ascii_digit()
        && bytes[15].is_ascii_digit()
        && bytes[16] == b':'
        && bytes[17].is_ascii_digit()
        && bytes[18].is_ascii_digit()
        && bytes[19] == b'Z'
}

/// The first repeated object key in a JSON document, at any depth. serde_json
/// keeps the last duplicate silently, so the raw text is scanned the way
/// `object_pairs_hook=reject_duplicate_keys` rejects it during parsing.
fn first_duplicate_key(text: &str) -> Option<String> {
    struct Frame {
        is_object: bool,
        keys: BTreeSet<String>,
        expecting_key: bool,
    }
    let bytes = text.as_bytes();
    let mut stack: Vec<Frame> = Vec::new();
    let mut index = 0usize;
    while index < bytes.len() {
        match bytes[index] {
            b'{' | b'[' => {
                let is_object = bytes[index] == b'{';
                stack.push(Frame {
                    is_object,
                    keys: BTreeSet::new(),
                    expecting_key: is_object,
                });
                index += 1;
            }
            b'}' | b']' => {
                stack.pop();
                index += 1;
            }
            b',' => {
                if let Some(frame) = stack.last_mut() {
                    if frame.is_object {
                        frame.expecting_key = true;
                    }
                }
                index += 1;
            }
            b'"' => {
                let mut cursor = index + 1;
                let mut literal = String::new();
                while cursor < bytes.len() && bytes[cursor] != b'"' {
                    if bytes[cursor] == b'\\' {
                        cursor += 1;
                    }
                    if cursor < bytes.len() {
                        literal.push(bytes[cursor] as char);
                    }
                    cursor += 1;
                }
                if let Some(frame) = stack.last_mut() {
                    if frame.is_object && frame.expecting_key {
                        frame.expecting_key = false;
                        if !frame.keys.insert(literal.clone()) {
                            return Some(literal);
                        }
                    }
                }
                index = cursor + 1;
            }
            _ => index += 1,
        }
    }
    None
}

/// `load_json`: strict UTF-8 read plus a duplicate-key-rejecting parse.
fn load_json(path: &Path) -> Result<Value, String> {
    let text = read_text(path)?;
    let value: Value = serde_json::from_str(&text)
        .map_err(|error| format!("invalid JSON in {}: {error}", path.display()))?;
    if let Some(key) = first_duplicate_key(&text) {
        return Err(format!("duplicate JSON key: {key}"));
    }
    Ok(value)
}

/// `path.read_text(encoding="utf-8")`, failing closed on I/O and encoding errors.
fn read_text(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path).map_err(|error| os_error(path, &error))
}

/// Python's `str(OSError)`: `[Errno N] strerror: 'path'`.
fn os_error(path: &Path, error: &std::io::Error) -> String {
    let Some(code) = error.raw_os_error() else {
        return format!("{}: {error}", path.display());
    };
    let rendered = error.to_string();
    let message = rendered
        .strip_suffix(&format!(" (os error {code})"))
        .unwrap_or(&rendered);
    format!("[Errno {code}] {message}: '{}'", path.display())
}

fn require_exact_keys(value: &Value, expected: &[&str], context: &str) -> Result<(), String> {
    let Some(map) = value.as_object() else {
        return Err(format!("{context} must be an object"));
    };
    let actual: BTreeSet<&str> = map.keys().map(String::as_str).collect();
    let expected_set: BTreeSet<&str> = expected.iter().copied().collect();
    if actual == expected_set {
        return Ok(());
    }
    let missing = py_list_repr(expected_set.difference(&actual).copied());
    let extra = py_list_repr(actual.difference(&expected_set).copied());
    Err(format!(
        "{context} keys drift: missing={missing}, extra={extra}"
    ))
}

/// `Path.resolve()` for a path that may not exist yet.
fn resolve(path: &Path) -> PathBuf {
    if let Ok(resolved) = path.canonicalize() {
        return resolved;
    }
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .unwrap_or_else(|_| PathBuf::from("."))
            .join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            other => normalized.push(other),
        }
    }
    normalized
}

/// `regular_file`: a retained path must stay inside `base` and resolve to a
/// regular, non-symlink file.
fn regular_file(base: &Path, relative: &str) -> Result<PathBuf, String> {
    let relative_path = Path::new(relative);
    if relative_path.is_absolute()
        || relative_path
            .components()
            .any(|component| matches!(component, Component::ParentDir))
    {
        return Err(format!("unsafe retained path: {relative}"));
    }
    let path = base.join(relative_path);
    let metadata = match path.symlink_metadata() {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(format!("missing retained file: {relative}"));
        }
        Err(error) => return Err(os_error(&path, &error)),
    };
    let file_type = metadata.file_type();
    if file_type.is_symlink() || !file_type.is_file() {
        return Err(format!(
            "retained path must be a regular non-symlink file: {relative}"
        ));
    }
    let resolved = resolve(&path);
    if !resolved.starts_with(resolve(base)) {
        return Err(format!(
            "retained path escapes oracle directory: {relative}"
        ));
    }
    Ok(path)
}

// ---------------------------------------------------------------------------
// Verification stages
// ---------------------------------------------------------------------------

fn verify_inventory_closure(oracle: &Path, locks: &[FileLock]) -> Result<(), String> {
    let metadata = match oracle.symlink_metadata() {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(format!("missing oracle directory: {}", oracle.display()));
        }
        Err(error) => return Err(os_error(oracle, &error)),
    };
    let file_type = metadata.file_type();
    if file_type.is_symlink() || !file_type.is_dir() {
        return Err("oracle directory must be a non-symlink directory".to_string());
    }

    let mut expected_files: BTreeSet<String> = locks
        .iter()
        .map(|lock| lock.path.to_string())
        .collect::<BTreeSet<String>>();
    expected_files.insert("contract.json".to_string());
    let expected_directories: BTreeSet<String> = ["discovery", "queries"]
        .iter()
        .map(|d| d.to_string())
        .collect();
    let mut observed_files: BTreeSet<String> = BTreeSet::new();
    let mut observed_directories: BTreeSet<String> = BTreeSet::new();
    walk_inventory(oracle, "", &mut observed_files, &mut observed_directories)?;

    if observed_files != expected_files {
        return Err(format!(
            "oracle file inventory drift: missing={}, extra={}",
            py_list_repr(
                expected_files
                    .difference(&observed_files)
                    .map(String::as_str)
            ),
            py_list_repr(
                observed_files
                    .difference(&expected_files)
                    .map(String::as_str)
            ),
        ));
    }
    if observed_directories != expected_directories {
        return Err(format!(
            "oracle directory inventory drift: missing={}, extra={}",
            py_list_repr(
                expected_directories
                    .difference(&observed_directories)
                    .map(String::as_str)
            ),
            py_list_repr(
                observed_directories
                    .difference(&expected_directories)
                    .map(String::as_str)
            ),
        ));
    }
    Ok(())
}

/// `oracle.rglob("*")`, walked in sorted order for a deterministic first failure.
fn walk_inventory(
    directory: &Path,
    prefix: &str,
    files: &mut BTreeSet<String>,
    directories: &mut BTreeSet<String>,
) -> Result<(), String> {
    let mut entries: Vec<PathBuf> = std::fs::read_dir(directory)
        .map_err(|error| os_error(directory, &error))?
        .map(|entry| {
            entry
                .map(|entry| entry.path())
                .map_err(|error| os_error(directory, &error))
        })
        .collect::<Result<Vec<PathBuf>, String>>()?;
    entries.sort();
    for entry in entries {
        let name = entry
            .file_name()
            .map(|name| name.to_string_lossy().to_string())
            .unwrap_or_default();
        let relative = if prefix.is_empty() {
            name
        } else {
            format!("{prefix}/{name}")
        };
        let metadata = entry
            .symlink_metadata()
            .map_err(|error| os_error(&entry, &error))?;
        let file_type = metadata.file_type();
        if file_type.is_symlink() {
            return Err(format!(
                "oracle inventory must not contain symlinks: {relative}"
            ));
        }
        if file_type.is_dir() {
            directories.insert(relative.clone());
            walk_inventory(&entry, &relative, files, directories)?;
        } else if file_type.is_file() {
            files.insert(relative);
        } else {
            return Err(format!("unsupported oracle inventory entry: {relative}"));
        }
    }
    Ok(())
}

fn verify_file_locks(oracle: &Path, contract: &Value, locks: &[FileLock]) -> Result<(), String> {
    let expected_records = Value::Array(
        locks
            .iter()
            .map(|lock| json!({"path": lock.path, "bytes": lock.bytes, "sha256": lock.sha256}))
            .collect(),
    );
    if contract["files"] != expected_records {
        return Err("retained file lock inventory drift".to_string());
    }
    for lock in locks {
        let path = regular_file(oracle, lock.path)?;
        let payload = std::fs::read(&path).map_err(|error| os_error(&path, &error))?;
        if payload.len() as u64 != lock.bytes {
            return Err(format!("byte length drift for {}", lock.path));
        }
        let actual_digest = sha256_hex(&payload);
        if actual_digest != lock.sha256 {
            return Err(format!("SHA-256 drift for {}: {actual_digest}", lock.path));
        }
    }
    Ok(())
}

fn verify_queries(oracle: &Path) -> Result<(), String> {
    let current = read_text(&regular_file(
        oracle,
        "queries/current-and-required-absence.graphql",
    )?)?;
    let boundary = read_text(&regular_file(
        oracle,
        "queries/graft-boundary-state.graphql",
    )?)?;
    for token in CURRENT_QUERY_TOKENS {
        if !current.contains(token) {
            return Err(format!("current query contract missing token: {token}"));
        }
    }
    for token in BOUNDARY_QUERY_TOKENS {
        if !boundary.contains(token) {
            return Err(format!("boundary query contract missing token: {token}"));
        }
    }
    Ok(())
}

fn verify_current_response(oracle: &Path, network: &str) -> Result<i128, String> {
    let networks = expected_networks();
    let network_contract = &networks[network];
    let response_path = network_contract["current_response"]
        .as_str()
        .unwrap_or_default();
    let payload = load_json(&regular_file(oracle, response_path)?)?;
    require_exact_keys(&payload, &["data"], &format!("{network} current response"))?;
    let data = &payload["data"];
    require_exact_keys(
        data,
        &[
            "_meta",
            "collects",
            "flashes",
            "tickHourDatas",
            "tickDayDatas",
            "positions",
            "pools",
        ],
        &format!("{network} current data"),
    )?;

    let meta = &data["_meta"];
    require_exact_keys(
        meta,
        &["block", "deployment", "hasIndexingErrors"],
        &format!("{network} _meta"),
    )?;
    if meta["deployment"] != network_contract["deployment"] {
        return Err(format!("{network} current deployment echo mismatch"));
    }
    if meta["hasIndexingErrors"] != Value::Bool(false) {
        return Err(format!("{network} current response has indexing errors"));
    }
    let block = &meta["block"];
    require_exact_keys(
        block,
        &["number", "hash", "timestamp"],
        &format!("{network} current block"),
    )?;
    let number = match python_int(&block["number"]) {
        Some(number) if number > 0 => number,
        _ => return Err(format!("{network} current block number is invalid")),
    };
    if !block["hash"].as_str().is_some_and(is_hex_hash) {
        return Err(format!("{network} current block hash is invalid"));
    }
    if !python_int(&block["timestamp"]).is_some_and(|timestamp| timestamp > 0) {
        return Err(format!("{network} current block timestamp is invalid"));
    }

    for entity in network_contract["current_empty_entity_smoke"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default()
    {
        let field = match entity.as_str().unwrap_or_default() {
            "Collect" => "collects",
            "Flash" => "flashes",
            "TickHourData" => "tickHourDatas",
            other => return Err(format!("unknown empty entity smoke: {other}")),
        };
        if data[field] != json!([]) {
            return Err(format!(
                "{network} {} current-head absence smoke drift",
                py_str(entity)
            ));
        }
    }

    for entity in network_contract["current_positive_entity_smoke"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default()
    {
        let field = match entity.as_str().unwrap_or_default() {
            "TickDayData" => "tickDayDatas",
            "Position" => "positions",
            "Pool" => "pools",
            other => return Err(format!("unknown positive entity smoke: {other}")),
        };
        let rows = data[field].as_array();
        if rows.is_none_or(|rows| rows.is_empty()) {
            return Err(format!(
                "{network} {} positive smoke is empty",
                py_str(entity)
            ));
        }
    }

    let pool = &data["pools"][0];
    require_exact_keys(
        pool,
        &["id", "feeGrowthGlobal0X128", "feeGrowthGlobal1X128"],
        &format!("{network} Pool smoke"),
    )?;
    for field in ["feeGrowthGlobal0X128", "feeGrowthGlobal1X128"] {
        if !pool[field].as_str().is_some_and(is_integer_string) {
            return Err(format!("{network} Pool {field} is not an integer string"));
        }
    }
    Ok(number)
}

fn verify_status_response(oracle: &Path, network: &str, current_block: i128) -> Result<(), String> {
    let networks = expected_networks();
    let network_contract = &networks[network];
    let response_path = network_contract["status_response"]
        .as_str()
        .unwrap_or_default();
    let payload = load_json(&regular_file(oracle, response_path)?)?;
    require_exact_keys(&payload, &["data"], &format!("{network} status response"))?;
    let data = &payload["data"];
    require_exact_keys(
        data,
        &[
            "deploymentId",
            "ipfsHash",
            "displayName",
            "signalledTokens",
            "stakedTokens",
            "indexers",
            "totalIndexers",
            "totalAllocations",
            "syncedCount",
            "healthyCount",
            "unhealthyCount",
            "failedCount",
            "unreachableCount",
            "servability",
        ],
        &format!("{network} status data"),
    )?;
    if data["ipfsHash"] != network_contract["deployment"] {
        return Err(format!("{network} status deployment mismatch"));
    }
    let (total, healthy, unhealthy) = expected_health_counts(network);
    if data["totalIndexers"] != json!(total)
        || data["syncedCount"] != json!(total)
        || data["healthyCount"] != json!(healthy)
        || data["unhealthyCount"] != json!(unhealthy)
    {
        return Err(format!("{network} retained status counts drift"));
    }
    if data["failedCount"] != json!(0) || data["unreachableCount"] != json!(0) {
        return Err(format!("{network} retained status unexpectedly failed"));
    }

    let indexers = data["indexers"].as_array();
    let Some(indexers) = indexers.filter(|rows| rows.len() as i64 == total) else {
        return Err(format!("{network} retained indexer list length drift"));
    };
    let expected_set: BTreeSet<String> = expected_indexers(network)
        .iter()
        .map(|indexer| json!(indexer).to_string())
        .collect();
    let actual_indexers: BTreeSet<String> = indexers
        .iter()
        .filter_map(Value::as_object)
        .map(|item| item.get("indexerId").unwrap_or(&Value::Null).to_string())
        .collect();
    if actual_indexers != expected_set {
        return Err(format!("{network} retained indexer identities drift"));
    }

    let indexer_keys = [
        "indexerId",
        "indexerName",
        "url",
        "allocatedTokens",
        "status",
        "health",
        "synced",
        "chainHeadBlock",
        "latestBlock",
        "network",
        "entityCount",
        "nonFatalErrorCount",
        "syncProgress",
        "blocksBehind",
        "serveProbe",
        "servable",
        "networkChainHead",
    ];
    for indexer in indexers {
        require_exact_keys(indexer, &indexer_keys, &format!("{network} indexer"))?;
        if indexer["network"] != json!(network) {
            return Err(format!("{network} indexer network mismatch"));
        }
        if indexer["status"] != json!("synced") || indexer["synced"] != Value::Bool(true) {
            return Err(format!("{network} indexer is not retained as synced"));
        }
        if indexer["serveProbe"] != json!("alive_paid") || indexer["servable"] != Value::Bool(true)
        {
            return Err(format!("{network} indexer is not retained as servable"));
        }
        // A non-integer head cannot be ordered against the retained query head;
        // Python raises TypeError there, so fail closed on the same evidence.
        if !python_int(&indexer["networkChainHead"]).is_some_and(|head| head >= current_block) {
            return Err(format!(
                "{network} status head predates retained query head"
            ));
        }
    }
    Ok(())
}

fn verify_mainnet_boundary(oracle: &Path) -> Result<(), String> {
    let networks = expected_networks();
    let boundary = &networks["mainnet"]["boundary"];
    let payload = load_json(&regular_file(
        oracle,
        boundary["response"].as_str().unwrap_or_default(),
    )?)?;
    require_exact_keys(&payload, &["data"], "mainnet boundary response")?;
    let data = &payload["data"];
    require_exact_keys(
        data,
        &[
            "beforeMeta",
            "afterMeta",
            "beforePools",
            "afterPools",
            "beforePositions",
            "afterPositions",
        ],
        "mainnet boundary data",
    )?;
    for (name, expected_number) in [
        ("beforeMeta", &boundary["before"]),
        ("afterMeta", &boundary["after"]),
    ] {
        let meta = &data[name];
        require_exact_keys(meta, &["block", "deployment", "hasIndexingErrors"], name)?;
        if meta["deployment"] != json!(MAINNET_DEPLOYMENT)
            || meta["hasIndexingErrors"] != Value::Bool(false)
        {
            return Err(format!("{name} deployment or error state drift"));
        }
        let block = &meta["block"];
        require_exact_keys(
            block,
            &["number", "hash", "timestamp"],
            &format!("{name} block"),
        )?;
        if *block != json!({"number": expected_number, "hash": null, "timestamp": null}) {
            return Err(format!("{name} retained historic block shape drift"));
        }
    }

    for entity in ["Pools", "Positions"] {
        let before = &data[format!("before{entity}")];
        let after = &data[format!("after{entity}")];
        if before.as_array().is_none_or(|rows| rows.is_empty()) {
            return Err(format!("mainnet boundary {entity} sample is empty"));
        }
        if before != after {
            return Err(format!("mainnet retained {entity} sample continuity drift"));
        }
    }
    Ok(())
}

fn verify_base_boundary_refusal(oracle: &Path) -> Result<(), String> {
    let networks = expected_networks();
    let boundary = &networks["base"]["boundary"];
    let payload = load_json(&regular_file(
        oracle,
        boundary["response"].as_str().unwrap_or_default(),
    )?)?;
    require_exact_keys(&payload, &["errors"], "Base boundary refusal")?;
    let errors = payload["errors"].as_array();
    let Some(errors) = errors.filter(|rows| rows.len() == 1) else {
        return Err("Base boundary refusal must retain exactly one error".to_string());
    };
    require_exact_keys(&errors[0], &["message"], "Base boundary error")?;
    let message = errors[0]["message"].as_str().unwrap_or_default();
    for fragment in [
        boundary["required_error_fragment"]
            .as_str()
            .unwrap_or_default(),
        "0xf92f430dd8567b0d466358c79594ab58d919a6d4",
        "Unavailable",
    ] {
        if !message.contains(fragment) {
            return Err(format!(
                "Base boundary refusal missing fragment: {fragment}"
            ));
        }
    }
    Ok(())
}

fn verify_manifest(oracle: &Path) -> Result<(), String> {
    let networks = expected_networks();
    let manifest = load_json(&regular_file(oracle, "discovery/manifest.json")?)?;
    require_exact_keys(
        &manifest,
        &["format_version", "contract_version", "observations"],
        "discovery manifest",
    )?;
    if manifest["format_version"] != json!(1)
        || manifest["contract_version"] != json!(CONTRACT_VERSION)
    {
        return Err("discovery manifest identity drift".to_string());
    }
    let observations = manifest["observations"].as_array();
    let Some(observations) = observations.filter(|rows| rows.len() == 6) else {
        return Err("discovery manifest must retain six observations".to_string());
    };

    // `{item.get("id"): item for item in observations if isinstance(item, dict)}`:
    // insertion order of first occurrence, last value wins on a repeated id.
    let mut order: Vec<String> = Vec::new();
    let mut by_id: BTreeMap<String, &Value> = BTreeMap::new();
    for item in observations.iter().filter(|item| item.is_object()) {
        let key = item
            .as_object()
            .and_then(|map| map.get("id"))
            .unwrap_or(&Value::Null)
            .to_string();
        if by_id.insert(key.clone(), item).is_none() {
            order.push(key);
        }
    }
    let expected_ids: BTreeSet<String> = [
        "mainnet-current-and-required-absence",
        "base-current-and-required-absence",
        "mainnet-indexer-status",
        "base-indexer-status",
        "mainnet-current-graft-boundary",
        "base-current-graft-boundary-refusal",
    ]
    .iter()
    .map(|id| json!(id).to_string())
    .collect();
    let actual_ids: BTreeSet<String> = by_id.keys().cloned().collect();
    if actual_ids != expected_ids || by_id.len() != observations.len() {
        return Err("discovery observation identities drift".to_string());
    }

    for key in &order {
        let observation = by_id[key];
        let observation_id = py_str(&observation["id"]);
        let network = &observation["network"];
        let Some(network_contract) = networks.get(network.as_str().unwrap_or_default()) else {
            return Err(format!("unknown observation network: {}", py_str(network)));
        };
        if observation["deployment"] != network_contract["deployment"] {
            return Err(format!("{observation_id} deployment mismatch"));
        }
        if observation["http_status"] != json!(200) {
            return Err(format!("{observation_id} HTTP status drift"));
        }
        if !observation["observed_at_utc"]
            .as_str()
            .is_some_and(is_observed_at)
        {
            return Err(format!("{observation_id} observation timestamp drift"));
        }
    }

    for network in ["mainnet", "base"] {
        let current = by_id[&json!(format!("{network}-current-and-required-absence")).to_string()];
        if current["request_path"] != json!("queries/current-and-required-absence.graphql") {
            return Err(format!("{network} current request path drift"));
        }
        if current["response_path"] != networks[network]["current_response"] {
            return Err(format!("{network} current response path drift"));
        }
        let status = by_id[&json!(format!("{network}-indexer-status")).to_string()];
        if status["response_path"] != networks[network]["status_response"] {
            return Err(format!("{network} status response path drift"));
        }
    }

    let mainnet_boundary = by_id[&json!("mainnet-current-graft-boundary").to_string()];
    let base_boundary = by_id[&json!("base-current-graft-boundary-refusal").to_string()];
    for (network, observation) in [("mainnet", mainnet_boundary), ("base", base_boundary)] {
        let expected = &networks[network]["boundary"];
        if observation["request_path"] != json!("queries/graft-boundary-state.graphql") {
            return Err(format!("{network} boundary request path drift"));
        }
        if observation["variables"]
            != json!({"before": expected["before"], "after": expected["after"]})
        {
            return Err(format!("{network} boundary variables drift"));
        }
        if observation["response_path"] != expected["response"] {
            return Err(format!("{network} boundary response path drift"));
        }
    }
    Ok(())
}

/// Verify the retained snapshot under `root`, returning the success line.
pub fn verify(root: &Path) -> Result<String, String> {
    verify_with_locks(root, &expected_file_locks())
}

fn verify_with_locks(root: &Path, locks: &[FileLock]) -> Result<String, String> {
    let root = resolve(root);
    let oracle = root.join(ORACLE_DIRECTORY);
    let contract_path = regular_file(&root, CONTRACT_PATH)?;
    let contract = load_json(&contract_path)?;
    require_exact_keys(
        &contract,
        &[
            "format_version",
            "contract_version",
            "evidence_class",
            "purpose",
            "source_identity",
            "files",
            "observed_capabilities",
            "promotion_gates",
            "networks",
        ],
        "oracle contract",
    )?;
    if contract["format_version"] != json!(1)
        || contract["contract_version"] != json!(CONTRACT_VERSION)
    {
        return Err("oracle contract identity drift".to_string());
    }
    if contract["evidence_class"] != json!("retained_discovery_snapshot") {
        return Err("oracle evidence class drift".to_string());
    }
    if contract["purpose"]
        != json!(
            "Retain a fail-closed discovery snapshot for deployment-scoped logical queries \
             without promoting it to an authoritative parity oracle."
        )
    {
        return Err("oracle purpose drift".to_string());
    }
    if contract["source_identity"] != expected_source_identity() {
        return Err("oracle source identity drift".to_string());
    }
    if contract["observed_capabilities"] != expected_observed_capabilities() {
        return Err("observed capability boundary drift".to_string());
    }
    if contract["promotion_gates"] != expected_promotion_gates() {
        return Err("promotion gate drift; every gate must remain false".to_string());
    }
    if contract["promotion_gates"]
        .as_object()
        .is_some_and(|gates| gates.values().any(|gate| gate != &Value::Bool(false)))
    {
        return Err("promotion gate must not be true in discovery evidence".to_string());
    }
    if contract["networks"] != expected_networks() {
        return Err("network oracle contract drift".to_string());
    }

    verify_inventory_closure(&oracle, locks)?;
    verify_file_locks(&oracle, &contract, locks)?;
    verify_queries(&oracle)?;
    verify_manifest(&oracle)?;
    let mut current_blocks: Vec<(&str, i128)> = Vec::new();
    for network in ["mainnet", "base"] {
        current_blocks.push((network, verify_current_response(&oracle, network)?));
    }
    for (network, current_block) in current_blocks {
        verify_status_response(&oracle, network, current_block)?;
    }
    verify_mainnet_boundary(&oracle)?;
    verify_base_boundary_refusal(&oracle)?;
    Ok(SUCCESS_LINE.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

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
            copy_dir(
                &repository().join(ORACLE_DIRECTORY),
                &dir.path().join(ORACLE_DIRECTORY),
            );
            Fixture {
                dir,
                locks: expected_file_locks(),
            }
        }

        fn root(&self) -> &Path {
            self.dir.path()
        }

        fn oracle(&self) -> PathBuf {
            self.root().join(ORACLE_DIRECTORY)
        }

        fn contract_path(&self) -> PathBuf {
            self.root().join(CONTRACT_PATH)
        }

        fn read_contract(&self) -> Value {
            serde_json::from_str(&fs::read_to_string(self.contract_path()).unwrap()).unwrap()
        }

        fn write_contract(&self, contract: &Value) {
            fs::write(
                self.contract_path(),
                serde_json::to_string_pretty(contract).unwrap() + "\n",
            )
            .unwrap();
        }

        fn read_response(&self, relative: &str) -> Value {
            serde_json::from_str(&fs::read_to_string(self.oracle().join(relative)).unwrap())
                .unwrap()
        }

        fn write_response(&self, relative: &str, value: &Value) {
            fs::write(
                self.oracle().join(relative),
                serde_json::to_string_pretty(value).unwrap() + "\n",
            )
            .unwrap();
        }

        /// `accept_modified_retained_bytes`: move the byte lock so a negative
        /// test reaches semantic validation.
        fn accept_modified_retained_bytes(&mut self, relative: &str) {
            let payload = fs::read(self.oracle().join(relative)).unwrap();
            let bytes = payload.len() as u64;
            let sha256 = sha256_hex(&payload);
            for lock in self.locks.iter_mut() {
                if lock.path == relative {
                    lock.bytes = bytes;
                    lock.sha256.clone_from(&sha256);
                }
            }
            let mut contract = self.read_contract();
            for record in contract["files"].as_array_mut().unwrap() {
                if record["path"] == json!(relative) {
                    record["bytes"] = json!(bytes);
                    record["sha256"] = json!(sha256);
                }
            }
            self.write_contract(&contract);
        }

        fn verify(&self) -> Result<String, String> {
            verify_with_locks(self.root(), &self.locks)
        }

        fn error(&self) -> String {
            self.verify().unwrap_err()
        }
    }

    #[test]
    fn exact_snapshot_passes() {
        let fixture = Fixture::new();
        assert_eq!(fixture.verify(), Ok(SUCCESS_LINE.to_string()));
    }

    #[test]
    fn real_tree_snapshot_passes() {
        assert_eq!(verify(&repository()), Ok(SUCCESS_LINE.to_string()));
        assert_eq!(
            SUCCESS_LINE,
            "verified 9 retained oracle files, exact deployment echoes, current-head \
             absence/positive smokes, mainnet boundary response, Base expected refusal, \
             and 13 fail-closed promotion gates"
        );
    }

    #[test]
    fn tampered_response_bytes_are_rejected() {
        let fixture = Fixture::new();
        let path = fixture
            .oracle()
            .join("discovery/mainnet-query-response.json");
        let mut payload = fs::read(&path).unwrap();
        payload.push(b'\n');
        fs::write(&path, payload).unwrap();
        assert_eq!(
            fixture.error(),
            "byte length drift for discovery/mainnet-query-response.json"
        );
    }

    #[test]
    fn unlisted_oracle_artifact_is_rejected() {
        let fixture = Fixture::new();
        fs::write(
            fixture
                .oracle()
                .join("discovery/authoritative-promotion.json"),
            "{\"final_parity_package\":true,\"production_backfill_allowed\":true}\n",
        )
        .unwrap();
        assert_eq!(
            fixture.error(),
            "oracle file inventory drift: missing=[], extra=['discovery/authoritative-promotion.json']"
        );
    }

    #[test]
    fn source_identity_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut contract = fixture.read_contract();
        contract["source_identity"]["revision"] = json!("0".repeat(40));
        fixture.write_contract(&contract);
        assert_eq!(fixture.error(), "oracle source identity drift");
    }

    #[test]
    fn query_shape_drift_is_rejected_even_with_a_moved_byte_lock() {
        let mut fixture = Fixture::new();
        let relative = "queries/current-and-required-absence.graphql";
        let path = fixture.oracle().join(relative);
        let query = fs::read_to_string(&path).unwrap();
        assert!(query.contains("query CurrentAndRequiredAbsence"));
        fs::write(
            &path,
            query.replacen("query CurrentAndRequiredAbsence", "query Weakened", 1),
        )
        .unwrap();
        fixture.accept_modified_retained_bytes(relative);
        assert_eq!(
            fixture.error(),
            "current query contract missing token: query CurrentAndRequiredAbsence"
        );
    }

    #[test]
    fn any_promotion_gate_is_rejected() {
        let fixture = Fixture::new();
        let mut contract = fixture.read_contract();
        contract["promotion_gates"]["final_parity_package"] = json!(true);
        fixture.write_contract(&contract);
        assert_eq!(
            fixture.error(),
            "promotion gate drift; every gate must remain false"
        );
    }

    #[test]
    fn base_refusal_removal_is_rejected_even_with_a_moved_byte_lock() {
        let mut fixture = Fixture::new();
        let relative = "discovery/base-boundary-error.json";
        fs::write(fixture.oracle().join(relative), "{\"data\": {}}\n").unwrap();
        fixture.accept_modified_retained_bytes(relative);
        assert_eq!(
            fixture.error(),
            "Base boundary refusal keys drift: missing=['errors'], extra=['data']"
        );
    }

    #[test]
    fn mainnet_deployment_mismatch_is_rejected_with_a_moved_byte_lock() {
        let mut fixture = Fixture::new();
        let relative = "discovery/mainnet-query-response.json";
        let mut response = fixture.read_response(relative);
        response["data"]["_meta"]["deployment"] = json!(BASE_DEPLOYMENT);
        fixture.write_response(relative, &response);
        fixture.accept_modified_retained_bytes(relative);
        assert_eq!(fixture.error(), "mainnet current deployment echo mismatch");
    }

    #[test]
    fn json_booleans_are_not_valid_block_metadata() {
        let mut fixture = Fixture::new();
        let relative = "discovery/mainnet-query-response.json";
        let mut response = fixture.read_response(relative);
        response["data"]["_meta"]["block"]["number"] = json!(true);
        response["data"]["_meta"]["block"]["timestamp"] = json!(true);
        fixture.write_response(relative, &response);
        fixture.accept_modified_retained_bytes(relative);
        assert_eq!(fixture.error(), "mainnet current block number is invalid");
    }

    #[test]
    fn indexer_identity_drift_is_rejected_with_a_moved_byte_lock() {
        let mut fixture = Fixture::new();
        let relative = "discovery/base-status-response.json";
        let mut response = fixture.read_response(relative);
        response["data"]["indexers"][0]["indexerId"] = json!(format!("0x{}", "0".repeat(40)));
        fixture.write_response(relative, &response);
        fixture.accept_modified_retained_bytes(relative);
        assert_eq!(fixture.error(), "base retained indexer identities drift");
    }

    /// A pointer edit applied to one retained response before its byte lock is
    /// moved, mirroring the capture harness run against the Python verifier.
    enum Op {
        Set(Value),
        Truncate,
    }

    fn apply(document: &mut Value, pointer: &str, op: &Op) {
        let target = document.pointer_mut(pointer).expect("pointer resolves");
        match op {
            Op::Set(value) => *target = value.clone(),
            Op::Truncate => {
                target.as_array_mut().expect("array").pop();
            }
        }
    }

    #[test]
    fn semantic_drift_messages_match_the_python_verifier() {
        let cases: Vec<(&str, &str, Op, &str)> = vec![
            (
                "discovery/mainnet-query-response.json",
                "/data/_meta/block/hash",
                Op::Set(json!("0x00")),
                "mainnet current block hash is invalid",
            ),
            (
                "discovery/mainnet-query-response.json",
                "/data/_meta/block/timestamp",
                Op::Set(json!(0)),
                "mainnet current block timestamp is invalid",
            ),
            (
                "discovery/base-query-response.json",
                "/data/collects",
                Op::Set(json!([{}])),
                "base Collect current-head absence smoke drift",
            ),
            (
                "discovery/mainnet-query-response.json",
                "/data/positions",
                Op::Set(json!([])),
                "mainnet Position positive smoke is empty",
            ),
            (
                "discovery/mainnet-query-response.json",
                "/data/pools/0/feeGrowthGlobal0X128",
                Op::Set(json!("abc")),
                "mainnet Pool feeGrowthGlobal0X128 is not an integer string",
            ),
            (
                "discovery/mainnet-query-response.json",
                "/data/_meta/hasIndexingErrors",
                Op::Set(json!(true)),
                "mainnet current response has indexing errors",
            ),
            (
                "discovery/base-status-response.json",
                "/data/ipfsHash",
                Op::Set(json!("QmXX")),
                "base status deployment mismatch",
            ),
            (
                "discovery/mainnet-status-response.json",
                "/data/healthyCount",
                Op::Set(json!(3)),
                "mainnet retained status counts drift",
            ),
            (
                "discovery/base-status-response.json",
                "/data/failedCount",
                Op::Set(json!(1)),
                "base retained status unexpectedly failed",
            ),
            (
                "discovery/mainnet-status-response.json",
                "/data/indexers",
                Op::Truncate,
                "mainnet retained indexer list length drift",
            ),
            (
                "discovery/mainnet-status-response.json",
                "/data/indexers/0/status",
                Op::Set(json!("syncing")),
                "mainnet indexer is not retained as synced",
            ),
            (
                "discovery/base-status-response.json",
                "/data/indexers/0/serveProbe",
                Op::Set(json!("dead")),
                "base indexer is not retained as servable",
            ),
            (
                "discovery/base-status-response.json",
                "/data/indexers/0/networkChainHead",
                Op::Set(json!(1)),
                "base status head predates retained query head",
            ),
            (
                "discovery/mainnet-status-response.json",
                "/data/indexers/0/network",
                Op::Set(json!("base")),
                "mainnet indexer network mismatch",
            ),
            (
                "discovery/mainnet-boundary-response.json",
                "/data/beforeMeta/block/hash",
                Op::Set(json!("0xab")),
                "beforeMeta retained historic block shape drift",
            ),
            (
                "discovery/mainnet-boundary-response.json",
                "/data/beforePools",
                Op::Set(json!([])),
                "mainnet boundary Pools sample is empty",
            ),
            (
                "discovery/mainnet-boundary-response.json",
                "/data/afterPools/0/id",
                Op::Set(json!("0xdead")),
                "mainnet retained Pools sample continuity drift",
            ),
            (
                "discovery/mainnet-boundary-response.json",
                "/data/afterMeta/deployment",
                Op::Set(json!("QmXX")),
                "afterMeta deployment or error state drift",
            ),
            (
                "discovery/base-boundary-error.json",
                "/errors/0/message",
                Op::Set(json!(
                    "Unavailable 0xf92f430dd8567b0d466358c79594ab58d919a6d4"
                )),
                "Base boundary refusal missing fragment: missing block: 19852000",
            ),
            (
                "discovery/manifest.json",
                "/observations/0/http_status",
                Op::Set(json!(500)),
                "mainnet-current-and-required-absence HTTP status drift",
            ),
            (
                "discovery/manifest.json",
                "/observations/0/observed_at_utc",
                Op::Set(json!("2026-08-28T12:00:00Z")),
                "mainnet-current-and-required-absence observation timestamp drift",
            ),
            (
                "discovery/manifest.json",
                "/observations/0/network",
                Op::Set(json!("polygon")),
                "unknown observation network: polygon",
            ),
            (
                "discovery/manifest.json",
                "/observations/2/deployment",
                Op::Set(json!("QmXX")),
                "mainnet-indexer-status deployment mismatch",
            ),
            (
                "discovery/manifest.json",
                "/observations/4/variables/before",
                Op::Set(json!(1)),
                "mainnet boundary variables drift",
            ),
            (
                "discovery/manifest.json",
                "/observations/0/response_path",
                Op::Set(json!("x")),
                "mainnet current response path drift",
            ),
            (
                "discovery/manifest.json",
                "/observations/1/request_path",
                Op::Set(json!("x")),
                "base current request path drift",
            ),
            (
                "discovery/manifest.json",
                "/observations/3/response_path",
                Op::Set(json!("x")),
                "base status response path drift",
            ),
            (
                "discovery/manifest.json",
                "/observations/5/request_path",
                Op::Set(json!("x")),
                "base boundary request path drift",
            ),
            (
                "discovery/manifest.json",
                "/observations/4/response_path",
                Op::Set(json!("x")),
                "mainnet boundary response path drift",
            ),
            (
                "discovery/manifest.json",
                "/observations",
                Op::Truncate,
                "discovery manifest must retain six observations",
            ),
            (
                "discovery/manifest.json",
                "/observations/0/id",
                Op::Set(json!("renamed")),
                "discovery observation identities drift",
            ),
            (
                "discovery/manifest.json",
                "/format_version",
                Op::Set(json!(2)),
                "discovery manifest identity drift",
            ),
        ];
        for (relative, pointer, op, expected) in cases {
            let mut fixture = Fixture::new();
            let mut document = fixture.read_response(relative);
            apply(&mut document, pointer, &op);
            fixture.write_response(relative, &document);
            fixture.accept_modified_retained_bytes(relative);
            assert_eq!(fixture.error(), expected, "{relative} {pointer}");
        }
    }

    #[test]
    fn duplicate_json_keys_are_rejected() {
        let fixture = Fixture::new();
        fs::write(
            fixture.contract_path(),
            "{\"format_version\": 1, \"format_version\": 1}\n",
        )
        .unwrap();
        assert_eq!(fixture.error(), "duplicate JSON key: format_version");
    }
}
