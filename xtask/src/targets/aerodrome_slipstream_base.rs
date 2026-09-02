//! Verify the fail-closed Aerodrome Slipstream CL Base target baseline.
//!
//! Direct port of the retired `scripts/verify-aerodrome-slipstream-base-target.py`. Every
//! Python `fail(...)` becomes an `Err` carrying the identical message, and every
//! I/O, JSON, or YAML error also becomes an `Err` so the check stays fail-closed.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Component, Path, PathBuf};

use serde_json::{json, Value};

use crate::target_common::{
    logical_hash, normalize_event, parse_schema, read_json, sha256_hex, unixfs_file_cidv0,
};

pub const LOCK_PATH: &str = "docs/provenance/aerodrome-slipstream-base-target.json";
const PROFILE_PATH: &str = "aerodrome-slipstream-base/layout-profile-v1.json";
const BINDING_PATH: &str =
    "aerodrome-slipstream-base/QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV.yaml";
const QMA8_SCHEMA_PATH: &str =
    "uniswap-v3/graft-ancestry/v1/artifacts/Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru";

const EXPECTED_DEPLOYMENT: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
const EXPECTED_SCHEMA: &str = "QmTiEqVtfjTDY8DRkj17eLKSAyajHNz8r7Yg9cRgXwrWfF";
const EXPECTED_MANIFEST_REPOSITORY: &str = "https://github.com/Uniswap/uniswap-v3-subgraph";
const EXPECTED_PROFILE_BYTES: usize = 17350;
const EXPECTED_PROFILE_SHA256: &str =
    "8f07982c2787d3ed0d23ab833f90eb8fdf0a9bbddf8ce8fa593ad7f5ff299740";
const EXPECTED_QMA8_BYTES: usize = 19034;
const EXPECTED_QMA8_SHA256: &str =
    "ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c";
const EXPECTED_QMA8_LOGICAL: &str =
    "6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d";
const EXPECTED_TARGET_LOGICAL: &str =
    "c072c3a609441de370bcb7340814b4e9dd9687043d7088f53a0dcb92ee8b23a0";

const EMPTY_VALUES: &[Value] = &[];

/// One `EXPECTED_ARTIFACTS` entry. `exports` is empty for the roles the Python
/// dictionary declares without an `exports` key.
struct ExpectedArtifact {
    role: &'static str,
    cid: &'static str,
    path: &'static str,
    bytes: usize,
    sha256: &'static str,
    exports: &'static [&'static str],
}

impl ExpectedArtifact {
    /// `{"role": role, **expected}` exactly as the Python literal builds it.
    fn record(&self) -> Value {
        let mut record = json!({
            "role": self.role,
            "cid": self.cid,
            "path": self.path,
            "bytes": self.bytes,
            "sha256": self.sha256,
        });
        if !self.exports.is_empty() {
            record["exports"] = json!(self.exports);
        }
        record
    }
}

/// Insertion-ordered port of the Python `EXPECTED_ARTIFACTS` dictionary; the
/// order decides which drift message a multi-role failure reports first.
const EXPECTED_ARTIFACTS: &[ExpectedArtifact] = &[
    ExpectedArtifact {
        role: "deployment",
        cid: EXPECTED_DEPLOYMENT,
        path: "aerodrome-slipstream-base/reference/deployment.yaml",
        bytes: 5371,
        sha256: "d93714e7ba268a91278f5c7c6a5b4ef71920d13b7e8d517f3542fb4a2edf6b20",
        exports: &[],
    },
    ExpectedArtifact {
        role: "schema",
        cid: EXPECTED_SCHEMA,
        path: "aerodrome-slipstream-base/reference/schema.graphql",
        bytes: 18598,
        sha256: "09d7c40167fc27c3aa2de0ec003fe7b0b469e132943cc26dcd4db6064769d0e8",
        exports: &[],
    },
    ExpectedArtifact {
        role: "factory_abi",
        cid: "QmamyiWBuT1kyYy6r97DamQ7eowheMw7nfGZUFdAmaFRG8",
        path: "aerodrome-slipstream-base/reference/abis/Factory.json",
        bytes: 10875,
        sha256: "7dac7fd7c4ff807498cb7dcbf503474d13b1207852bb8b2b3687a7e8cfb6d979",
        exports: &[],
    },
    ExpectedArtifact {
        role: "erc20_abi",
        cid: "QmXuTbDkNrN27VydxbS2huvKRk62PMgUTdPDWkxcr2w7j2",
        path: "aerodrome-slipstream-base/reference/abis/ERC20.json",
        bytes: 3684,
        sha256: "4b83c6645aed2df5e4e9a1d11f372453fc052ac8575348c8c04a33ceacd0ae90",
        exports: &[],
    },
    ExpectedArtifact {
        role: "erc20_name_bytes_abi",
        cid: "QmQCP6Pdp1MqpwRv2qoPHuUTwZGy7Q3eDHg4w5kzwE9mBj",
        path: "aerodrome-slipstream-base/reference/abis/ERC20NameBytes.json",
        bytes: 268,
        sha256: "b874c853ffa5309e4b7fbf4934c1efdb4fe31e1a65f7041e67f4a7f2258ffb77",
        exports: &[],
    },
    ExpectedArtifact {
        role: "erc20_symbol_bytes_abi",
        cid: "QmbHnhUFZa6qqqRyubUYhXntox1TCBxqryaBM1iNGqVJzT",
        path: "aerodrome-slipstream-base/reference/abis/ERC20SymbolBytes.json",
        bytes: 270,
        sha256: "9ccb9b5d95394b2ffb4ced54cffa0c5ea282917f4eec36c121ce28c257965193",
        exports: &[],
    },
    ExpectedArtifact {
        role: "pool_abi",
        cid: "QmVszVJj4c73MuQGv5Bi9Kje5tpGijPCDXie7fXTqGAFi9",
        path: "aerodrome-slipstream-base/reference/abis/Pool.json",
        bytes: 25037,
        sha256: "46588c2f4ad0b91f64e7b43b03190c5422d3f46f2759c53412a3f3279f816760",
        exports: &[],
    },
    ExpectedArtifact {
        role: "npm_abi",
        cid: "QmdAXZw3wWJx7uRuzBmNPqgV6hqE3Cx3ZBvXEVRoThdPDL",
        path: "aerodrome-slipstream-base/reference/abis/NonfungiblePositionManager.json",
        bytes: 26032,
        sha256: "6109c87c3dfd051c5fa283e71463d29d4c31a40339223ea3015ea0bcdd602c00",
        exports: &[],
    },
    ExpectedArtifact {
        role: "factory_mapping_wasm",
        cid: "QmZQVsukQt6nXKctyy2WSMWN5grVXKph5fR7ahxS11Uebs",
        path: "aerodrome-slipstream-base/reference/mappings/Factory.wasm",
        bytes: 50419,
        sha256: "0072f4d819db1fce30c4e2a926008ce2e7180157dd9e4e42ddf3416eb7d64d17",
        exports: &["handlePoolCreated"],
    },
    ExpectedArtifact {
        role: "npm_mapping_wasm",
        cid: "QmcoeFHridxYBRFnrZ33v3PRAgvqunBfxe9gsCPhJQB4dy",
        path: "aerodrome-slipstream-base/reference/mappings/NonfungiblePositionManager.wasm",
        bytes: 49615,
        sha256: "5547847305e52793ed505edb98cdfd542e97031d869d504d0de434548fa2c63e",
        exports: &[
            "handleIncreaseLiquidity",
            "handleDecreaseLiquidity",
            "handleCollect",
            "handleTransfer",
        ],
    },
    ExpectedArtifact {
        role: "pool_mapping_wasm",
        cid: "QmQgC18iXqZc5Jp78KZs6wNpk2oZvgbe9TeMQnH9K7eMah",
        path: "aerodrome-slipstream-base/reference/mappings/Pool.wasm",
        bytes: 77470,
        sha256: "778944cb5de130d35dd76718a2642a338e5637d1d3d58d5b64d7cdf096ed8272",
        exports: &[
            "handleInitialize",
            "handleMint",
            "handleBurn",
            "handleSwap",
            "handleFlash",
        ],
    },
];

fn expected_artifact(role: &str) -> &'static ExpectedArtifact {
    EXPECTED_ARTIFACTS
        .iter()
        .find(|artifact| artifact.role == role)
        .expect("role is one of the pinned artifact roles")
}

fn false_gates() -> Value {
    json!({
        "eligibility_complete": false,
        "source_revision_pinned": false,
        "source_reproducible": false,
        "implementation_complete": false,
        "runtime_complete": false,
        "runtime_parity": false,
        "logical_parity": false,
        "history_complete": false,
        "physical_profile_complete": false,
        "physical_parity": false,
        "poi_parity": false,
        "backfill_ready": false,
        "production_ready": false,
        "readiness": false,
        "issue_86_complete": false,
    })
}

const EXPECTED_REQUIRED_CHANGES: &[&str] = &[
    "resolve_exact_source_revision_or_produce_complete_retained_wasm_semantic_specification",
    "add_slipstream_factory_decoder_without_canonical_fee_argument",
    "resolve_tick_spacing_to_fee_semantics_and_pool_fee_tier_authority",
    "add_slipstream_npm_positions_int24_tick_spacing_adapter_and_four_handlers",
    "preserve_manifest_contract_call_inputs_for_npm_positions_ticks_and_fee_growth",
    "implement_token_version_and_missing_whitelist_pool_semantics",
    "preserve_flash_fee_growth_only_behavior_and_absent_flash_rows",
    "implement_all_twenty_mutable_entities_and_three_target_only_fields",
    "bind_base_addresses_start_blocks_pricing_constants_and_dynamic_pool_creation",
    "produce_target_specific_substreams_package_store_reducer_poi_and_temporal_writer",
    "capture_adversarial_factory_npm_pool_metadata_revert_and_flash_fixtures",
    "prove_graph_node_entity_value_order_failure_poi_vid_block_range_and_postgresql_parity",
];

const EXPECTED_EMBEDDED_ADDRESSES: &[&str] = &[
    "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
    "0x4200000000000000000000000000000000000006",
    "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631",
    "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248",
    "0x9663f2ca0454accad3e094448ea6f77443880454",
];

fn expected_source_search_scope() -> Value {
    json!({
        "observed_at": "2026-08-31",
        "public_code_search": [
            "deployment CID QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",
            "Factory mapping CID QmZQVsukQt6nXKctyy2WSMWN5grVXKph5fR7ahxS11Uebs",
            "NonfungiblePositionManager mapping CID QmcoeFHridxYBRFnrZ33v3PRAgvqunBfxe9gsCPhJQB4dy",
            "Pool mapping CID QmQgC18iXqZc5Jp78KZs6wNpk2oZvgbe9TeMQnH9K7eMah",
            "unique helper name addMissingWhitelistedPools",
        ],
        "repository_history_inspected": "https://github.com/Uniswap/v3-subgraph",
        "result": "no_exact_deployed_slipstream_source_match",
    })
}

const EXPECTED_REMAINING_GATES: &[&str] = &[
    concat!(
        "M0: fully account for both required clusters by inventorying every current ",
        "copy or fresh structural absence proof; when viable healthy copies exist, ",
        "independently select the minimum stable same-pod 24-hour ETA and minimum ",
        "stable same-pod 72-hour ETA across all viable copies, which may be different copies, and ",
        "require both minima to exceed 28 days or be non-converging; either minimum ",
        "at or below 28 days stops implementation, compute, and load; with no viable ",
        "copy, require fresh structural absence proof from both clusters."
    ),
    concat!(
        "Resolve the exact Slipstream source revision and build toolchain, or replace ",
        "them with a complete independently reviewed retained-WASM behavior specification."
    ),
    concat!(
        "Implement the target-specific decoder, call inputs, stores, reducer, PoI, ",
        "temporal writer, package, and schema without promoting any parity gate."
    ),
    concat!(
        "Prove canonical Base fixture, Graph Node differential, failure, save-order, ",
        "PoI, VID, block-range, and PostgreSQL parity."
    ),
    concat!(
        "Validate only on a disposable paused target; compute, load, Kubernetes ",
        "mutation, allocation, activation, and production require separate authorization."
    ),
];

const SUCCESS_LINE: &str = concat!(
    "verified 11 CIDv0 artifacts, exact Base manifest/ABIs/handlers/call inputs, ",
    "20-entity/302-field Qma8 delta, retained-WASM behavior boundary, bounded ",
    "unresolved-source provenance, and complete false M7 truth gates"
);

fn fail<T>(message: impl Into<String>) -> Result<T, String> {
    Err(message.into())
}

/// Python `str(value)` for the JSON scalars these documents carry.
fn py_str(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => "None".to_string(),
        Some(Value::String(text)) => text.clone(),
        Some(Value::Bool(true)) => "True".to_string(),
        Some(Value::Bool(false)) => "False".to_string(),
        Some(other) => other.to_string(),
    }
}

/// Best-effort `repr()` for the two IPFS diagnostics that interpolate a value.
fn py_repr(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::String(text) => format!("'{text}'"),
        Value::Number(number) => number.to_string(),
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(py_repr).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(map) => format!(
            "{{{}}}",
            map.iter()
                .map(|(key, item)| format!("'{key}': {}", py_repr(item)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// Python `re.sub(r"\s+", " ", str(value)).strip()`.
fn normalize_call(value: Option<&Value>) -> String {
    py_str(value)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn contains_subslice(haystack: &[u8], needle: &[u8]) -> bool {
    needle.is_empty()
        || haystack
            .windows(needle.len())
            .any(|window| window == needle)
}

fn utf16le(value: &str) -> Vec<u8> {
    value
        .encode_utf16()
        .flat_map(|unit| unit.to_le_bytes())
        .collect()
}

/// Lexical `Path.resolve()`: `..` pops, `.` is dropped, and an absolute
/// component restarts the path, matching how `pathlib` normalizes a joined
/// path that need not exist on disk.
fn resolve_lexically(root: &Path, value: &str) -> PathBuf {
    let mut resolved = root.to_path_buf();
    for component in Path::new(value).components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            Component::RootDir | Component::Prefix(_) => {
                resolved = PathBuf::from(component.as_os_str());
            }
            Component::Normal(part) => resolved.push(part),
        }
    }
    resolved
}

/// Port of `repository_path`: a non-empty relative path that resolves strictly
/// beneath the repository root.
fn repository_path(root: &Path, value: Option<&Value>, label: &str) -> Result<PathBuf, String> {
    let relative = match value {
        Some(Value::String(text)) if !text.is_empty() && !Path::new(text).is_absolute() => {
            text.as_str()
        }
        _ => {
            return fail(format!(
                "{label} must be a non-empty repository-relative path"
            ));
        }
    };
    let candidate = resolve_lexically(root, relative);
    if !candidate.ancestors().skip(1).any(|parent| parent == root) {
        return fail(format!("{label} escapes the repository root"));
    }
    Ok(candidate)
}

fn repository_path_str(root: &Path, value: &str, label: &str) -> Result<PathBuf, String> {
    repository_path(root, Some(&Value::String(value.to_string())), label)
}

fn read_bytes(path: &Path) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_text(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_yaml_value(path: &Path) -> Result<Value, String> {
    let text = read_text(path)?;
    let parsed: serde_yaml::Value = serde_yaml::from_str(&text)
        .map_err(|error| format!("cannot parse {}: {error}", path.display()))?;
    serde_json::to_value(parsed)
        .map_err(|error| format!("cannot convert {}: {error}", path.display()))
}

/// `{"/": "/ipfs/Qm…"}` → `Qm…`, reporting the Python messages verbatim.
fn cid_from_file(value: Option<&Value>) -> Result<String, String> {
    let map = match value {
        Some(Value::Object(map)) if map.len() == 1 && map.contains_key("/") => map,
        other => {
            return fail(format!(
                "unexpected IPFS file value: {}",
                py_repr(other.unwrap_or(&Value::Null))
            ));
        }
    };
    match &map["/"] {
        Value::String(text) if text.starts_with("/ipfs/Qm") => {
            Ok(text.trim_start_matches("/ipfs/").to_string())
        }
        other => fail(format!("unexpected IPFS location: {}", py_repr(other))),
    }
}

fn key_set(value: &Value) -> Option<BTreeSet<String>> {
    Some(value.as_object()?.keys().cloned().collect())
}

fn expected_key_set(keys: &[&str]) -> Option<BTreeSet<String>> {
    Some(keys.iter().map(|key| (*key).to_string()).collect())
}

fn verify_false_gates(value: Option<&Value>, label: &str) -> Result<(), String> {
    if value.unwrap_or(&Value::Null) != &false_gates() {
        return fail(format!(
            "{label} must retain the complete false truth-gate inventory"
        ));
    }
    Ok(())
}

fn verify_artifacts(root: &Path, lock: &Value) -> Result<BTreeMap<String, Value>, String> {
    let records = match lock.get("artifact_lock") {
        Some(Value::Array(records)) => records,
        _ => return fail("artifact_lock must be a list"),
    };
    let mut actual: BTreeMap<String, Value> = BTreeMap::new();
    for record in records {
        let role = match record.get("role") {
            Some(Value::String(role)) => role.clone(),
            _ => return fail("artifact records require a string role"),
        };
        if actual.contains_key(&role) {
            return fail(format!("duplicate artifact role: {role}"));
        }
        actual.insert(role, record.clone());
    }
    let expected_roles: BTreeSet<String> = EXPECTED_ARTIFACTS
        .iter()
        .map(|artifact| artifact.role.to_string())
        .collect();
    if actual.keys().cloned().collect::<BTreeSet<String>>() != expected_roles {
        return fail("artifact role inventory drift");
    }
    for expected in EXPECTED_ARTIFACTS {
        let role = expected.role;
        let record = &actual[role];
        if record != &expected.record() {
            return fail(format!("artifact metadata drift for {role}"));
        }
        let artifact_path = repository_path(root, record.get("path"), &format!("{role} path"))?;
        let payload = read_bytes(&artifact_path)?;
        if payload.len() != expected.bytes || sha256_hex(&payload) != expected.sha256 {
            return fail(format!("artifact byte lock drift for {role}"));
        }
        if unixfs_file_cidv0(&payload)? != expected.cid {
            return fail(format!("artifact CIDv0 drift for {role}"));
        }
        if role.ends_with("_abi") {
            let parsed: Value = serde_json::from_slice(&payload)
                .map_err(|error| format!("cannot parse {}: {error}", artifact_path.display()))?;
            if !parsed.is_array() {
                return fail(format!("ABI payload must be a list for {role}"));
            }
        }
        if role.ends_with("_mapping_wasm") {
            if !payload.starts_with(b"\0asm\x01\0\0\0") {
                return fail(format!("mapping is not a WebAssembly v1 module for {role}"));
            }
            for export in expected.exports {
                if !contains_subslice(&payload, export.as_bytes()) {
                    return fail(format!("mapping export missing for {role}: {export}"));
                }
            }
        }
    }
    Ok(actual)
}

fn abi_inventory(mapping: &Value) -> Result<Vec<(String, String)>, String> {
    let abis = match mapping.get("abis") {
        Some(Value::Array(abis)) => abis,
        _ => return fail("mapping ABI inventory must be a list"),
    };
    abis.iter()
        .map(|item| Ok((py_str(item.get("name")), cid_from_file(item.get("file"))?)))
        .collect()
}

type Handler = (String, String, BTreeMap<String, String>);

fn handler_inventory(mapping: &Value) -> Result<Vec<Handler>, String> {
    let handlers = match mapping.get("eventHandlers") {
        Some(Value::Array(handlers)) => handlers,
        _ => return fail("mapping handler inventory must be a list"),
    };
    let mut output = Vec::new();
    for entry in handlers {
        if !entry.is_object() {
            return fail("handler entries must be objects");
        }
        // `handler.get("calls", {})`: an absent key defaults to an empty map,
        // while an explicit non-object (including null) is rejected.
        let calls = match entry.get("calls") {
            None => serde_json::Map::new(),
            Some(Value::Object(calls)) => calls.clone(),
            Some(_) => return fail("handler calls must be an object"),
        };
        output.push((
            py_str(entry.get("handler")),
            normalize_event(&py_str(entry.get("event"))),
            calls
                .iter()
                .map(|(key, value)| (key.clone(), normalize_call(Some(value))))
                .collect(),
        ));
    }
    Ok(output)
}

fn handler(name: &str, event: &str, calls: &[(&str, &str)]) -> Handler {
    (
        name.to_string(),
        event.to_string(),
        calls
            .iter()
            .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
            .collect(),
    )
}

fn named(values: &[(&str, &str)]) -> Vec<(String, String)> {
    values
        .iter()
        .map(|(name, cid)| ((*name).to_string(), (*cid).to_string()))
        .collect()
}

fn verify_manifest(root: &Path, artifacts: &BTreeMap<String, Value>) -> Result<(), String> {
    let manifest_path =
        repository_path(root, artifacts["deployment"].get("path"), "manifest path")?;
    let manifest = read_yaml_value(&manifest_path)?;
    if !manifest.is_object() {
        return fail("manifest must be an object");
    }
    if manifest.get("specVersion") != Some(&json!("1.2.0"))
        || manifest.get("repository") != Some(&json!(EXPECTED_MANIFEST_REPOSITORY))
        || manifest.get("features") != Some(&json!(["nonFatalErrors", "grafting"]))
        || manifest.get("graft").is_some()
        || {
            let file = manifest
                .get("schema")
                .filter(|schema| schema.is_object())
                .and_then(|schema| schema.get("file"));
            cid_from_file(file)? != EXPECTED_SCHEMA
        }
    {
        return fail("manifest identity, feature, graft, or schema drift");
    }

    let sources = match manifest.get("dataSources") {
        Some(Value::Array(sources)) => &sources[..],
        _ => return fail("manifest data-source order or inventory drift"),
    };
    let source_names: Vec<Value> = sources
        .iter()
        .map(|item| item.get("name").cloned().unwrap_or(Value::Null))
        .collect();
    if source_names != vec![json!("Factory"), json!("NonfungiblePositionManager")] {
        return fail("manifest data-source order or inventory drift");
    }
    let templates = match manifest.get("templates") {
        Some(Value::Array(templates)) => &templates[..],
        _ => return fail("manifest template order or inventory drift"),
    };
    let template_names: Vec<Value> = templates
        .iter()
        .map(|item| item.get("name").cloned().unwrap_or(Value::Null))
        .collect();
    if template_names != vec![json!("Pool")] {
        return fail("manifest template order or inventory drift");
    }

    let factory_mapping = sources[0].get("mapping").unwrap_or(&Value::Null);
    if sources[0].get("kind") != Some(&json!("ethereum/contract"))
        || sources[0].get("network") != Some(&json!("base"))
        || sources[0].get("source")
            != Some(&json!({
                "abi": "Factory",
                "address": "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
                "startBlock": 13843704,
            }))
        || !factory_mapping.is_object()
        || cid_from_file(factory_mapping.get("file"))?
            != expected_artifact("factory_mapping_wasm").cid
        || factory_mapping.get("entities") != Some(&json!(["Pool", "Token"]))
        || abi_inventory(factory_mapping)?
            != named(&[
                ("Factory", expected_artifact("factory_abi").cid),
                ("ERC20", expected_artifact("erc20_abi").cid),
                (
                    "ERC20SymbolBytes",
                    expected_artifact("erc20_symbol_bytes_abi").cid,
                ),
                (
                    "ERC20NameBytes",
                    expected_artifact("erc20_name_bytes_abi").cid,
                ),
                ("Pool", expected_artifact("pool_abi").cid),
            ])
        || handler_inventory(factory_mapping)?
            != vec![handler(
                "handlePoolCreated",
                "PoolCreated(indexedaddress,indexedaddress,indexedint24,address)",
                &[],
            )]
    {
        return fail("Factory source, ABI, mapping, or handler contract drift");
    }

    let npm_mapping = sources[1].get("mapping").unwrap_or(&Value::Null);
    let npm_call = "NonfungiblePositionManager[event.address].positions(event.params.tokenId)";
    if sources[1].get("kind") != Some(&json!("ethereum/contract"))
        || sources[1].get("network") != Some(&json!("base"))
        || sources[1].get("source")
            != Some(&json!({
                "abi": "NonfungiblePositionManager",
                "address": "0x827922686190790b37229fd06084350e74485b72",
                "startBlock": 13843719,
            }))
        || !npm_mapping.is_object()
        || cid_from_file(npm_mapping.get("file"))? != expected_artifact("npm_mapping_wasm").cid
        || npm_mapping.get("entities") != Some(&json!(["Pool", "Token"]))
        || abi_inventory(npm_mapping)?
            != named(&[
                (
                    "NonfungiblePositionManager",
                    expected_artifact("npm_abi").cid,
                ),
                ("Pool", expected_artifact("pool_abi").cid),
                ("Factory", expected_artifact("factory_abi").cid),
                ("ERC20", expected_artifact("erc20_abi").cid),
            ])
        || handler_inventory(npm_mapping)?
            != vec![
                handler(
                    "handleIncreaseLiquidity",
                    "IncreaseLiquidity(indexeduint256,uint128,uint256,uint256)",
                    &[("positions", npm_call)],
                ),
                handler(
                    "handleDecreaseLiquidity",
                    "DecreaseLiquidity(indexeduint256,uint128,uint256,uint256)",
                    &[("positions", npm_call)],
                ),
                handler(
                    "handleCollect",
                    "Collect(indexeduint256,address,uint256,uint256)",
                    &[("positions", npm_call)],
                ),
                handler(
                    "handleTransfer",
                    "Transfer(indexedaddress,indexedaddress,indexeduint256)",
                    &[("positions", npm_call)],
                ),
            ]
    {
        return fail("NPM source, ABI, mapping, call-input, or handler contract drift");
    }

    let pool_mapping = templates[0].get("mapping").unwrap_or(&Value::Null);
    let tick_lower = "Pool[event.address].ticks(event.params.tickLower)";
    let tick_upper = "Pool[event.address].ticks(event.params.tickUpper)";
    let fee_growth: &[(&str, &str)] = &[
        (
            "feeGrowthGlobal0X128",
            "Pool[event.address].feeGrowthGlobal0X128()",
        ),
        (
            "feeGrowthGlobal1X128",
            "Pool[event.address].feeGrowthGlobal1X128()",
        ),
    ];
    if templates[0].get("kind") != Some(&json!("ethereum/contract"))
        || templates[0].get("network") != Some(&json!("base"))
        || templates[0].get("source") != Some(&json!({"abi": "Pool"}))
        || !pool_mapping.is_object()
        || cid_from_file(pool_mapping.get("file"))? != expected_artifact("pool_mapping_wasm").cid
        || pool_mapping.get("entities") != Some(&json!(["Pool", "Token"]))
        || abi_inventory(pool_mapping)?
            != named(&[
                ("Pool", expected_artifact("pool_abi").cid),
                ("Factory", expected_artifact("factory_abi").cid),
                ("ERC20", expected_artifact("erc20_abi").cid),
            ])
        || handler_inventory(pool_mapping)?
            != vec![
                handler("handleInitialize", "Initialize(uint160,int24)", &[]),
                handler(
                    "handleSwap",
                    "Swap(indexedaddress,indexedaddress,int256,int256,uint160,uint128,int24)",
                    fee_growth,
                ),
                handler(
                    "handleMint",
                    "Mint(address,indexedaddress,indexedint24,indexedint24,uint128,uint256,uint256)",
                    &[("poolTickLower", tick_lower), ("poolTickUpper", tick_upper)],
                ),
                handler(
                    "handleBurn",
                    "Burn(indexedaddress,indexedint24,indexedint24,uint128,uint256,uint256)",
                    &[("poolTickLower", tick_lower), ("poolTickUpper", tick_upper)],
                ),
                handler(
                    "handleFlash",
                    "Flash(indexedaddress,indexedaddress,uint256,uint256,uint256,uint256)",
                    fee_growth,
                ),
            ]
    {
        return fail("Pool template, ABI, mapping, call-input, or handler contract drift");
    }
    for mapping in [factory_mapping, npm_mapping, pool_mapping] {
        if mapping.get("kind") != Some(&json!("ethereum/events"))
            || mapping.get("apiVersion") != Some(&json!("0.0.7"))
            || mapping.get("language") != Some(&json!("wasm/assemblyscript"))
        {
            return fail("mapping runtime contract drift");
        }
    }
    Ok(())
}

fn abi_items(
    root: &Path,
    artifacts: &BTreeMap<String, Value>,
    role: &str,
) -> Result<Vec<Value>, String> {
    let path = repository_path(root, artifacts[role].get("path"), &format!("{role} path"))?;
    match read_json(&path)? {
        Value::Array(items) if items.iter().all(Value::is_object) => Ok(items),
        _ => fail(format!("invalid ABI inventory for {role}")),
    }
}

type EventShape = Vec<(String, String, bool)>;

fn event_shape(items: &[Value], name: &str) -> Result<EventShape, String> {
    let matches: Vec<&Value> = items
        .iter()
        .filter(|item| {
            item.get("type") == Some(&json!("event")) && item.get("name") == Some(&json!(name))
        })
        .collect();
    if matches.len() != 1 {
        return fail(format!("expected exactly one ABI event {name}"));
    }
    let inputs = match matches[0].get("inputs") {
        None => EMPTY_VALUES,
        Some(Value::Array(inputs)) => &inputs[..],
        Some(_) => return fail(format!("ABI event inputs must be a list for {name}")),
    };
    Ok(inputs
        .iter()
        .map(|item| {
            (
                py_str(item.get("name")),
                py_str(item.get("type")),
                item.get("indexed") == Some(&Value::Bool(true)),
            )
        })
        .collect())
}

type FunctionShape = (Vec<String>, Vec<String>, String);

fn function_shapes(items: &[Value], name: &str) -> Result<Vec<FunctionShape>, String> {
    let mut output = Vec::new();
    for item in items {
        if item.get("type") != Some(&json!("function")) || item.get("name") != Some(&json!(name)) {
            continue;
        }
        let types = |key: &str| -> Result<Vec<String>, String> {
            match item.get(key) {
                None => Ok(Vec::new()),
                Some(Value::Array(values)) => Ok(values
                    .iter()
                    .map(|value| py_str(value.get("type")))
                    .collect()),
                Some(_) => fail(format!("ABI function {key} must be a list for {name}")),
            }
        };
        output.push((
            types("inputs")?,
            types("outputs")?,
            py_str(item.get("stateMutability")),
        ));
    }
    Ok(output)
}

fn shape(entries: &[(&str, &str, bool)]) -> EventShape {
    entries
        .iter()
        .map(|(name, kind, indexed)| ((*name).to_string(), (*kind).to_string(), *indexed))
        .collect()
}

fn single_function(inputs: &[&str], outputs: &[&str], mutability: &str) -> Vec<FunctionShape> {
    vec![(
        inputs.iter().map(|value| (*value).to_string()).collect(),
        outputs.iter().map(|value| (*value).to_string()).collect(),
        mutability.to_string(),
    )]
}

fn verify_abi_contracts(root: &Path, artifacts: &BTreeMap<String, Value>) -> Result<(), String> {
    let factory = abi_items(root, artifacts, "factory_abi")?;
    let npm = abi_items(root, artifacts, "npm_abi")?;
    let pool = abi_items(root, artifacts, "pool_abi")?;
    if event_shape(&factory, "PoolCreated")?
        != shape(&[
            ("token0", "address", true),
            ("token1", "address", true),
            ("tickSpacing", "int24", true),
            ("pool", "address", false),
        ])
    {
        return fail("Slipstream Factory PoolCreated ABI drift");
    }
    if function_shapes(&factory, "getPool")?
        != single_function(&["address", "address", "int24"], &["address"], "view")
    {
        return fail("Slipstream Factory getPool ABI drift");
    }
    let npm_events: [(&str, EventShape); 4] = [
        (
            "IncreaseLiquidity",
            shape(&[
                ("tokenId", "uint256", true),
                ("liquidity", "uint128", false),
                ("amount0", "uint256", false),
                ("amount1", "uint256", false),
            ]),
        ),
        (
            "DecreaseLiquidity",
            shape(&[
                ("tokenId", "uint256", true),
                ("liquidity", "uint128", false),
                ("amount0", "uint256", false),
                ("amount1", "uint256", false),
            ]),
        ),
        (
            "Collect",
            shape(&[
                ("tokenId", "uint256", true),
                ("recipient", "address", false),
                ("amount0", "uint256", false),
                ("amount1", "uint256", false),
            ]),
        ),
        (
            "Transfer",
            shape(&[
                ("from", "address", true),
                ("to", "address", true),
                ("tokenId", "uint256", true),
            ]),
        ),
    ];
    for (name, expected) in npm_events {
        if event_shape(&npm, name)? != expected {
            return fail(format!("Slipstream NPM {name} ABI drift"));
        }
    }
    if function_shapes(&npm, "positions")?
        != single_function(
            &["uint256"],
            &[
                "uint96", "address", "address", "address", "int24", "int24", "int24", "uint128",
                "uint256", "uint256", "uint128", "uint128",
            ],
            "view",
        )
    {
        return fail("Slipstream NPM positions ABI drift");
    }
    let pool_events: [(&str, EventShape); 3] = [
        (
            "Initialize",
            shape(&[("sqrtPriceX96", "uint160", false), ("tick", "int24", false)]),
        ),
        (
            "Swap",
            shape(&[
                ("sender", "address", true),
                ("recipient", "address", true),
                ("amount0", "int256", false),
                ("amount1", "int256", false),
                ("sqrtPriceX96", "uint160", false),
                ("liquidity", "uint128", false),
                ("tick", "int24", false),
            ]),
        ),
        (
            "Flash",
            shape(&[
                ("sender", "address", true),
                ("recipient", "address", true),
                ("amount0", "uint256", false),
                ("amount1", "uint256", false),
                ("paid0", "uint256", false),
                ("paid1", "uint256", false),
            ]),
        ),
    ];
    for (name, expected) in pool_events {
        if event_shape(&pool, name)? != expected {
            return fail(format!("Slipstream Pool {name} ABI drift"));
        }
    }
    let pool_markers: [(&str, Vec<FunctionShape>); 4] = [
        ("gauge", single_function(&[], &["address"], "view")),
        (
            "rewardGrowthGlobalX128",
            single_function(&[], &["uint256"], "view"),
        ),
        (
            "stakedLiquidity",
            single_function(&[], &["uint128"], "view"),
        ),
        ("unstakedFee", single_function(&[], &["uint24"], "view")),
    ];
    for (name, expected) in pool_markers {
        if function_shapes(&pool, name)? != expected {
            return fail(format!("Slipstream-specific Pool marker drift: {name}"));
        }
    }
    Ok(())
}

fn verify_schema(
    root: &Path,
    artifacts: &BTreeMap<String, Value>,
    lock: &Value,
) -> Result<(), String> {
    let target_path = repository_path(root, artifacts["schema"].get("path"), "target schema path")?;
    let qma8_path = repository_path_str(root, QMA8_SCHEMA_PATH, "Qma8 schema path")?;
    let qma8_payload = read_bytes(&qma8_path)?;
    if qma8_payload.len() != EXPECTED_QMA8_BYTES
        || sha256_hex(&qma8_payload) != EXPECTED_QMA8_SHA256
    {
        return fail("retained Qma8 schema byte lock drift");
    }
    let target = parse_schema(&read_text(&target_path)?);
    let qma8 = parse_schema(&read_text(&qma8_path)?);
    if target.entities.len() != 20
        || target.entities.values().map(BTreeMap::len).sum::<usize>() != 302
        || logical_hash(&target.entities) != EXPECTED_TARGET_LOGICAL
        || !target.immutable.is_empty()
        || !target.explicit_mutable.is_empty()
    {
        return fail("Slipstream 20-entity/302-field all-mutable schema drift");
    }
    if qma8.entities.len() != 20
        || qma8.entities.values().map(BTreeMap::len).sum::<usize>() != 299
        || logical_hash(&qma8.entities) != EXPECTED_QMA8_LOGICAL
        || !qma8.immutable.is_empty()
        || !qma8.explicit_mutable.is_empty()
    {
        return fail("retained Qma8 logical schema drift");
    }
    if target.entities.keys().collect::<BTreeSet<_>>() != qma8.entities.keys().collect() {
        return fail("Slipstream/Qma8 entity inventory drift");
    }
    let mut differences: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::new();
    for (entity, target_fields) in &target.entities {
        let qma8_fields = &qma8.entities[entity];
        let missing = qma8_fields
            .keys()
            .any(|field| !target_fields.contains_key(field));
        let changed = qma8_fields
            .iter()
            .any(|(field, kind)| target_fields.get(field).is_some_and(|other| other != kind));
        if missing || changed {
            return fail(format!(
                "unexpected Slipstream/Qma8 field or type difference in {entity}"
            ));
        }
        let added: BTreeMap<String, String> = target_fields
            .iter()
            .filter(|(field, _)| !qma8_fields.contains_key(*field))
            .map(|(field, kind)| (field.clone(), kind.clone()))
            .collect();
        if !added.is_empty() {
            differences.insert(entity.clone(), added);
        }
    }
    if serde_json::to_value(&differences).map_err(|error| error.to_string())?
        != json!({
            "Token": {"version": "Int"},
            "Position": {
                "collectedToken0": "BigDecimal!",
                "collectedToken1": "BigDecimal!",
            },
        })
    {
        return fail("Slipstream/Qma8 exact three-field gap drift");
    }
    if lock.get("logical_contract").unwrap_or(&Value::Null)
        != &json!({
            "entity_count": 20,
            "field_count": 302,
            "logical_sha256": EXPECTED_TARGET_LOGICAL,
            "all_entities_mutable": true,
            "immutable_entities": [],
            "retained_qma8": {
                "cid": "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru",
                "path": QMA8_SCHEMA_PATH,
                "bytes": EXPECTED_QMA8_BYTES,
                "sha256": EXPECTED_QMA8_SHA256,
                "entity_count": 20,
                "field_count": 299,
                "logical_sha256": EXPECTED_QMA8_LOGICAL,
            },
            "bidirectional_gap": {
                "missing_entities": [],
                "extra_entities": [],
                "missing_fields": [],
                "extra_fields": [
                    "Position.collectedToken0:BigDecimal!",
                    "Position.collectedToken1:BigDecimal!",
                    "Token.version:Int",
                ],
                "type_differences": [],
                "mutability_differences": [],
            },
        })
    {
        return fail("provenance logical contract or bidirectional schema gap drift");
    }
    Ok(())
}

/// `(profile component, artifact role, repository-path label)`, in the order
/// the Python dictionary lists them.
const WASM_COMPONENTS: [(&str, &str, &str); 3] = [
    ("Factory", "factory_mapping_wasm", "Factory WASM path"),
    (
        "NonfungiblePositionManager",
        "npm_mapping_wasm",
        "NPM WASM path",
    ),
    ("Pool", "pool_mapping_wasm", "Pool WASM path"),
];

fn verify_wasm_static_evidence(
    root: &Path,
    artifacts: &BTreeMap<String, Value>,
    profile: &Value,
) -> Result<(), String> {
    let mut wasm: Vec<(&str, Vec<u8>)> = Vec::new();
    for (component, role, label) in WASM_COMPONENTS {
        let path = repository_path(root, artifacts[role].get("path"), label)?;
        wasm.push((component, read_bytes(&path)?));
    }
    let module = |component: &str| -> &[u8] {
        &wasm
            .iter()
            .find(|(name, _)| *name == component)
            .expect("component is one of the three retained modules")
            .1
    };
    let evidence = profile
        .get("retained_wasm_static_behavior")
        .unwrap_or(&Value::Null);
    if !evidence.is_object()
        || evidence.get("proof_scope")
            != Some(&json!(
                "static_presence_and_binding_only_not_complete_values_order_branches_failure_or_persistence"
            ))
    {
        return fail("retained-WASM proof boundary drift");
    }
    for (component, role, _) in WASM_COMPONENTS {
        let record = evidence.get(component).unwrap_or(&Value::Null);
        if !record.is_object()
            || record.get("exports") != Some(&json!(expected_artifact(role).exports))
        {
            return fail(format!(
                "profile WASM export inventory drift for {component}"
            ));
        }
        for (key, message) in [
            ("named_target_helpers", "retained WASM named helper missing"),
            ("host_capabilities", "retained WASM host capability missing"),
        ] {
            let values = match record.get(key) {
                None => EMPTY_VALUES,
                Some(Value::Array(values)) => &values[..],
                Some(_) => return fail(format!("profile {key} must be a list for {component}")),
            };
            for value in values {
                let present = value
                    .as_str()
                    .is_some_and(|text| contains_subslice(module(component), text.as_bytes()));
                if !present {
                    return fail(format!(
                        "{message} for {component}: {}",
                        py_str(Some(value))
                    ));
                }
            }
        }
    }
    if evidence.get("embedded_address_constants") != Some(&json!(EXPECTED_EMBEDDED_ADDRESSES)) {
        return fail("embedded address constant inventory drift");
    }
    let combined: Vec<u8> = wasm
        .iter()
        .flat_map(|(_, bytes)| bytes.iter().copied())
        .collect();
    for value in EXPECTED_EMBEDDED_ADDRESSES
        .iter()
        .copied()
        .chain(["0.01", "1.0001", "1000000"])
    {
        if !contains_subslice(&combined, &utf16le(value)) {
            return fail(format!("retained WASM embedded constant missing: {value}"));
        }
    }
    let flash_observation = evidence
        .get("Pool")
        .and_then(|pool| pool.get("flash_static_observation"));
    if flash_observation
        != Some(&json!(concat!(
            "loads Pool, calls feeGrowthGlobal0X128 and feeGrowthGlobal1X128, sets both Pool ",
            "fields, saves Pool; no Flash constructor or Flash save is present"
        )))
    {
        return fail("bounded Flash static observation drift");
    }
    Ok(())
}

fn verify_profile(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let profile_path = repository_path_str(root, PROFILE_PATH, "profile path")?;
    let profile_payload = read_bytes(&profile_path)?;
    if profile_payload.len() != EXPECTED_PROFILE_BYTES
        || sha256_hex(&profile_payload) != EXPECTED_PROFILE_SHA256
    {
        return fail("machine-readable layout profile digest drift");
    }
    if lock.get("layout_profile").unwrap_or(&Value::Null)
        != &json!({
            "path": PROFILE_PATH,
            "bytes": EXPECTED_PROFILE_BYTES,
            "sha256": EXPECTED_PROFILE_SHA256,
        })
    {
        return fail("layout profile provenance lock drift");
    }
    let profile: Value = serde_json::from_slice(&profile_payload)
        .map_err(|error| format!("cannot parse {}: {error}", profile_path.display()))?;
    if profile.get("format_version") != Some(&json!(1))
        || profile.get("profile_id") != Some(&json!("aerodrome-slipstream-base-QmasYjyp"))
        || profile.get("status")
            != Some(&json!("immutable_target_and_static_behavior_profile_only"))
        || profile.get("family") != Some(&json!("aerodrome-slipstream-base"))
        || profile.get("protocol") != Some(&json!("aerodrome-slipstream-cl"))
        || profile.get("chain") != Some(&json!("base"))
        || profile.get("implementation_status") != Some(&json!("not_started"))
        || profile.get("eligibility_decision") != Some(&json!("indeterminate_no_fresh_evidence"))
    {
        return fail("layout profile identity or status drift");
    }
    if profile.get("deployment").unwrap_or(&Value::Null)
        != &json!({
            "cid": EXPECTED_DEPLOYMENT,
            "spec_version": "1.2.0",
            "mapping_api_version": "0.0.7",
            "features": ["nonFatalErrors", "grafting"],
            "graft": null,
            "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
            "manifest_repository_is_protocol_identity": false,
        })
    {
        return fail("profile deployment or metadata-lineage boundary drift");
    }
    verify_false_gates(profile.get("truth_gates"), "profile truth_gates")?;
    if profile.get("required_target_changes") != Some(&json!(EXPECTED_REQUIRED_CHANGES)) {
        return fail("complete Slipstream implementation-gap inventory drift");
    }
    if profile.get("remaining_gates") != Some(&json!(EXPECTED_REMAINING_GATES)) {
        return fail("Slipstream remaining-gate inventory drift");
    }
    let source = profile.get("source_provenance").unwrap_or(&Value::Null);
    if !source.is_object()
        || source
            != &json!({
                "status": "unresolved_exact_revision_and_toolchain",
                "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
                "search_scope": expected_source_search_scope(),
                "exact_repository": null,
                "exact_commit": null,
                "exact_tree": null,
                "exact_toolchain": null,
                "byte_reproduction": false,
                "reason": concat!(
                    "No public revision containing the deployed Slipstream Factory/NPM/Pool ",
                    "modifications was found; manifest metadata alone is insufficient authority."
                ),
            })
    {
        return fail("profile unresolved-source boundary drift");
    }
    let prior_art = profile
        .get("public_prior_art_assessment")
        .unwrap_or(&Value::Null);
    let nested = |group: &str, key: &str| -> bool {
        prior_art
            .get(group)
            .filter(|value| value.is_object())
            .and_then(|value| value.get(key))
            == Some(&Value::Bool(false))
    };
    if !prior_art.is_object()
        || prior_art.get("drop_in_package_safe") != Some(&Value::Bool(false))
        || !nested("aerodrome_module", "slipstream_factory_compatible")
        || !nested("uniswap_v3_module", "slipstream_factory_compatible")
        || !nested("uniswap_v3_module", "npm_handlers_present")
        || !nested("uniswap_v3_module", "graph_entity_writer")
    {
        return fail("public prior-art refusal boundary drift");
    }
    verify_wasm_static_evidence(root, artifacts, &profile)
}

fn verify_source_boundary(lock: &Value) -> Result<(), String> {
    if lock.get("source_provenance").unwrap_or(&Value::Null)
        != &json!({
            "status": "unresolved_exact_revision_and_toolchain",
            "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
            "manifest_repository_is_exact_source_authority": false,
            "search_scope": expected_source_search_scope(),
            "exact_repository": null,
            "exact_commit": null,
            "exact_tree": null,
            "exact_parent": null,
            "exact_toolchain": null,
            "byte_reproduction": false,
            "reproduction_attempted": false,
            "blocker": concat!(
                "The deployed IPFS closure does not name a source revision, and no public ",
                "revision containing the exact Slipstream Factory/NPM/Pool modifications ",
                "was identified."
            ),
            "public_lineage_probe": {
                "repository": "https://github.com/Uniswap/v3-subgraph",
                "probed_head_commit": "b4a0e8d34b8238482cadd3929ae88d3426a7067b",
                "probed_head_tree": "6b32ebf65ca9fafc5fb3c04e3aa5247f1bdb6e21",
                "nearest_schema_only_commit": "c63cb398075b1bb6d4acf9876f3561afdfd18d4e",
                "nearest_schema_only_tree": "7be31c24df808f076d49ec7a03547bb8eb6db523",
                "nearest_schema_only_relationship": concat!(
                    "Its 20-entity/299-field logical schema matches retained Qma8, but it ",
                    "lacks the three Slipstream target fields and is not evidence of the ",
                    "deployed fork or build."
                ),
                "exact_deployment_cid_search_match": false,
                "exact_mapping_cid_search_match": false,
                "unique_add_missing_whitelisted_pools_source_match": false,
            },
        })
    {
        return fail("unsupported source revision, toolchain, or reproduction promotion");
    }
    Ok(())
}

fn verify_binding(root: &Path) -> Result<(), String> {
    let binding_path = repository_path_str(root, BINDING_PATH, "binding path")?;
    let binding = read_yaml_value(&binding_path)?;
    if !binding.is_object() {
        return fail("target binding must be an object");
    }
    if key_set(&binding)
        != expected_key_set(&[
            "deployment",
            "family",
            "display_name",
            "schema",
            "chain",
            "milestone",
            "market_snapshot",
            "target_reference",
            "truth_gates",
            "eligibility",
        ])
    {
        return fail("target binding top-level inventory drift");
    }
    if binding.get("deployment") != Some(&json!(EXPECTED_DEPLOYMENT))
        || binding.get("family") != Some(&json!("aerodrome-slipstream-base"))
        || binding.get("display_name") != Some(&json!("Aerodrome Slipstream CL Base"))
        || binding.get("schema") != Some(&json!(EXPECTED_SCHEMA))
        || binding.get("chain") != Some(&json!("base"))
        || binding.get("milestone") != Some(&json!("M7"))
        || binding.get("target_reference")
            != Some(&json!({
                "provenance": LOCK_PATH,
                "deployment_manifest": expected_artifact("deployment").path,
                "status": "immutable_target_pinned_source_revision_unresolved",
            }))
        || binding.get("market_snapshot")
            != Some(&json!({
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 962722,
                "query_fees_grt_24h": "1154.657",
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
            }))
    {
        return fail("target binding identity, M7, market snapshot, or source status drift");
    }
    verify_false_gates(binding.get("truth_gates"), "binding truth_gates")?;
    if binding.get("eligibility").unwrap_or(&Value::Null)
        != &json!({
            "policy": "graph-node-net-catchup-v1",
            "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
            "latest": {
                "decision": "indeterminate",
                "reason": "no_fresh_evidence",
                "measured_at": null,
                "evidence": null,
                "sha256": null,
            },
        })
    {
        return fail("target binding eligibility must remain fail-closed without fresh evidence");
    }
    Ok(())
}

/// Verify the pinned Aerodrome Slipstream CL Base baseline rooted at `root`.
///
/// `lock` is the repository-relative provenance path. This family has no
/// exact-source reproduction mode, so `exact_source_root` must be `None`.
pub fn verify(
    root: &Path,
    lock: &Path,
    exact_source_root: Option<&Path>,
) -> Result<String, String> {
    if exact_source_root.is_some() {
        return fail("Aerodrome Slipstream Base has no exact-source reproduction mode");
    }
    if lock != Path::new(LOCK_PATH) {
        return fail("Aerodrome Slipstream provenance must remain under docs/provenance");
    }
    let resolved_root = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve {}: {error}", root.display()))?;
    let root = resolved_root.as_path();
    let lock_path = repository_path_str(root, &lock.to_string_lossy(), "provenance path")?;
    let lock = read_json(&lock_path)?;
    if !lock.is_object() || lock.get("format_version") != Some(&json!(1)) {
        return fail("unsupported Aerodrome Slipstream target lock");
    }
    if key_set(&lock)
        != expected_key_set(&[
            "format_version",
            "family",
            "protocol",
            "implementation_status",
            "eligibility_decision",
            "deployment",
            "artifact_lock",
            "protocol_identity",
            "source_provenance",
            "logical_contract",
            "layout_profile",
            "external_prior_art",
            "kubernetes_evidence",
            "truth_gates",
            "remaining_gates",
        ])
    {
        return fail("provenance top-level inventory drift");
    }
    if lock.get("family") != Some(&json!("aerodrome-slipstream-base"))
        || lock.get("protocol") != Some(&json!("aerodrome-slipstream-cl"))
        || lock.get("implementation_status")
            != Some(&json!("immutable_target_and_static_behavior_baseline_only"))
        || lock.get("eligibility_decision") != Some(&json!("indeterminate_no_fresh_evidence"))
        || lock.get("remaining_gates") != Some(&json!(EXPECTED_REMAINING_GATES))
    {
        return fail("baseline identity, status, eligibility, or remaining-gate drift");
    }
    verify_false_gates(lock.get("truth_gates"), "provenance truth_gates")?;
    if lock.get("deployment").unwrap_or(&Value::Null)
        != &json!({
            "cid": EXPECTED_DEPLOYMENT,
            "chain": "base",
            "spec_version": "1.2.0",
            "mapping_api_version": "0.0.7",
            "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
            "manifest_repository_is_protocol_identity": false,
            "features": ["nonFatalErrors", "grafting"],
            "concrete_graft": null,
            "data_sources": [
                {
                    "kind": "data_source",
                    "name": "Factory",
                    "address": "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
                    "start_block": 13843704,
                    "mapping_cid": expected_artifact("factory_mapping_wasm").cid,
                },
                {
                    "kind": "data_source",
                    "name": "NonfungiblePositionManager",
                    "address": "0x827922686190790b37229fd06084350e74485b72",
                    "start_block": 13843719,
                    "mapping_cid": expected_artifact("npm_mapping_wasm").cid,
                },
                {
                    "kind": "template",
                    "name": "Pool",
                    "address": null,
                    "start_block": null,
                    "mapping_cid": expected_artifact("pool_mapping_wasm").cid,
                },
            ],
        })
    {
        return fail("provenance deployment or metadata-lineage boundary drift");
    }
    if lock.get("protocol_identity").unwrap_or(&Value::Null)
        != &json!({
            "authority": "deployed_addresses_manifest_event_signatures_and_abi_shape",
            "classification": "aerodrome_slipstream_cl_base_not_canonical_uniswap_v3",
            "factory_pool_created":
                "PoolCreated(indexed address,indexed address,indexed int24,address)",
            "canonical_v3_pool_created":
                "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)",
            "pool_abi_specific_markers": [
                "gauge():(address)",
                "rewardGrowthGlobalX128():(uint256)",
                "stakedLiquidity():(uint128)",
                "unstakedFee():(uint24)",
            ],
        })
    {
        return fail("provenance protocol identity drift");
    }
    if lock.get("external_prior_art").unwrap_or(&Value::Null)
        != &json!({
            "repository": "https://github.com/pinax-network/substreams-evm",
            "revision": "970a665e15619de8ad7f686bd89412a1030d46dc",
            "tree": "eac7466daba7f89a8c3b2e4742fcf24a155a2c24",
            "aerodrome_module":
                "Solidly V2 event extractor; wrong PoolCreated ABI and no Graph entity writer",
            "uniswap_v3_module": concat!(
                "Canonical V3 event extractor; wrong Factory ABI, no NPM handlers/call ",
                "inputs, and no Graph entity writer"
            ),
            "drop_in_package_safe": false,
        })
    {
        return fail("provenance public prior-art assessment drift");
    }
    if lock.get("kubernetes_evidence").unwrap_or(&Value::Null)
        != &json!({
            "repository": "https://github.com/pinax-network/k8s-subgraphs",
            "revision": "272b5babcc2717682e7becd7e3374b054063ee93",
            "tree": "f3b343d9123adb3204d5a565dabfea414b9cfd96",
            "path": "core/kan/graph-node-aerodrome.yaml",
            "scope": "read_only_identity_and_current_placement_evidence_only",
            "mutated": false,
        })
    {
        return fail("provenance Kubernetes evidence boundary drift");
    }
    let artifacts = verify_artifacts(root, &lock)?;
    verify_manifest(root, &artifacts)?;
    verify_abi_contracts(root, &artifacts)?;
    verify_schema(root, &artifacts, &lock)?;
    verify_profile(root, &lock, &artifacts)?;
    verify_source_boundary(&lock)?;
    verify_binding(root)?;
    Ok(SUCCESS_LINE.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    const FAMILY: &str = "aerodrome-slipstream-base";
    const BINDING_NAME: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV.yaml";

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    fn copy_tree(source: &Path, destination: &Path) {
        std::fs::create_dir_all(destination).unwrap();
        for entry in std::fs::read_dir(source).unwrap() {
            let entry = entry.unwrap();
            let target = destination.join(entry.file_name());
            if entry.file_type().unwrap().is_dir() {
                copy_tree(&entry.path(), &target);
            } else {
                std::fs::copy(entry.path(), target).unwrap();
            }
        }
    }

    /// Port of the Python `setUp`: the family directory, the retained Qma8
    /// schema, and the provenance lock copied into a disposable root.
    fn fixture() -> tempfile::TempDir {
        let repository = repository();
        let temporary = tempfile::tempdir().unwrap();
        let root = temporary.path();
        copy_tree(&repository.join(FAMILY), &root.join(FAMILY));
        let qma8 = root.join(QMA8_SCHEMA_PATH);
        std::fs::create_dir_all(qma8.parent().unwrap()).unwrap();
        std::fs::copy(repository.join(QMA8_SCHEMA_PATH), qma8).unwrap();
        let lock = root.join(LOCK_PATH);
        std::fs::create_dir_all(lock.parent().unwrap()).unwrap();
        std::fs::copy(repository.join(LOCK_PATH), lock).unwrap();
        temporary
    }

    fn run(root: &Path) -> Result<String, String> {
        verify(root, Path::new(LOCK_PATH), None)
    }

    fn read_value(root: &Path, relative: &str) -> Value {
        serde_json::from_str(&std::fs::read_to_string(root.join(relative)).unwrap()).unwrap()
    }

    fn write_json(root: &Path, relative: &str, value: &Value) {
        std::fs::write(
            root.join(relative),
            serde_json::to_string_pretty(value).unwrap() + "\n",
        )
        .unwrap();
    }

    fn replace_once(root: &Path, relative: &str, from: &str, to: &str) {
        let path = root.join(relative);
        let text = std::fs::read_to_string(&path).unwrap();
        assert!(text.contains(from), "fixture text {from} is not present");
        std::fs::write(&path, text.replacen(from, to, 1)).unwrap();
    }

    fn binding_relative() -> String {
        format!("{FAMILY}/{BINDING_NAME}")
    }

    #[test]
    fn exact_baseline_passes() {
        assert_eq!(run(&repository()).unwrap(), SUCCESS_LINE);
    }

    #[test]
    fn the_copied_fixture_root_also_passes() {
        let temporary = fixture();
        assert_eq!(run(temporary.path()).unwrap(), SUCCESS_LINE);
    }

    #[test]
    fn artifact_byte_drift_is_rejected() {
        let temporary = fixture();
        let mapping = temporary
            .path()
            .join(FAMILY)
            .join("reference/mappings/Pool.wasm");
        let mut payload = std::fs::read(&mapping).unwrap();
        let last = payload.len() - 1;
        payload[last] ^= 1;
        std::fs::write(&mapping, payload).unwrap();
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "artifact byte lock drift for pool_mapping_wasm"
        );
    }

    #[test]
    fn manifest_target_drift_is_rejected() {
        let temporary = fixture();
        replace_once(
            temporary.path(),
            &format!("{FAMILY}/reference/deployment.yaml"),
            "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
            "0x0000000000000000000000000000000000000000",
        );
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "artifact byte lock drift for deployment"
        );
    }

    #[test]
    fn retained_qma8_schema_drift_is_rejected() {
        let temporary = fixture();
        replace_once(
            temporary.path(),
            QMA8_SCHEMA_PATH,
            "type Bundle",
            "type BundleDrift",
        );
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "retained Qma8 schema byte lock drift"
        );
    }

    #[test]
    fn binding_eligibility_promotion_is_rejected() {
        let temporary = fixture();
        replace_once(
            temporary.path(),
            &binding_relative(),
            "decision: indeterminate",
            "decision: eligible",
        );
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "target binding eligibility must remain fail-closed without fresh evidence"
        );
    }

    #[test]
    fn binding_runtime_gate_promotion_is_rejected() {
        let temporary = fixture();
        replace_once(
            temporary.path(),
            &binding_relative(),
            "runtime_complete: false",
            "runtime_complete: true",
        );
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "binding truth_gates must retain the complete false truth-gate inventory"
        );
    }

    #[test]
    fn gateway_query_fees_cannot_be_mislabeled_as_generic_grt() {
        let temporary = fixture();
        replace_once(
            temporary.path(),
            &binding_relative(),
            "query_fees_grt_24h",
            "grt_24h",
        );
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "target binding identity, M7, market snapshot, or source status drift"
        );
    }

    #[test]
    fn fabricated_source_revision_and_reproduction_are_rejected() {
        let temporary = fixture();
        let mut lock = read_value(temporary.path(), LOCK_PATH);
        let source = lock
            .get_mut("source_provenance")
            .and_then(Value::as_object_mut)
            .unwrap();
        source.insert(
            "exact_repository".into(),
            json!("https://example.invalid/fork"),
        );
        source.insert("exact_commit".into(), json!("0".repeat(40)));
        source.insert("exact_tree".into(), json!("1".repeat(40)));
        source.insert("exact_toolchain".into(), json!({"node": "invented"}));
        source.insert("byte_reproduction".into(), json!(true));
        source.insert("reproduction_attempted".into(), json!(true));
        write_json(temporary.path(), LOCK_PATH, &lock);
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "unsupported source revision, toolchain, or reproduction promotion"
        );
    }

    #[test]
    fn source_search_scope_drift_is_rejected() {
        let temporary = fixture();
        let mut lock = read_value(temporary.path(), LOCK_PATH);
        lock["source_provenance"]["search_scope"]["result"] = json!("exact_source_found");
        write_json(temporary.path(), LOCK_PATH, &lock);
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "unsupported source revision, toolchain, or reproduction promotion"
        );
    }

    #[test]
    fn profile_source_and_runtime_promotion_is_rejected() {
        let temporary = fixture();
        let mut profile = read_value(temporary.path(), PROFILE_PATH);
        profile["source_provenance"]["status"] = json!("reproducible");
        profile["source_provenance"]["exact_commit"] = json!("0".repeat(40));
        profile["source_provenance"]["byte_reproduction"] = json!(true);
        profile["truth_gates"]["source_reproducible"] = json!(true);
        profile["truth_gates"]["runtime_complete"] = json!(true);
        write_json(temporary.path(), PROFILE_PATH, &profile);
        // Rewriting the profile also breaks its pinned byte digest, which the
        // Python verifier reports before reading any promoted field.
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "machine-readable layout profile digest drift"
        );
    }

    #[test]
    fn incomplete_truth_gate_inventory_is_rejected() {
        let temporary = fixture();
        let mut lock = read_value(temporary.path(), LOCK_PATH);
        lock.get_mut("truth_gates")
            .and_then(Value::as_object_mut)
            .unwrap()
            .remove("poi_parity");
        write_json(temporary.path(), LOCK_PATH, &lock);
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "provenance truth_gates must retain the complete false truth-gate inventory"
        );
    }

    #[test]
    fn unrecognized_provenance_promotion_is_rejected() {
        let temporary = fixture();
        let mut lock = read_value(temporary.path(), LOCK_PATH);
        lock.as_object_mut()
            .unwrap()
            .insert("runtime_ready".into(), json!(true));
        write_json(temporary.path(), LOCK_PATH, &lock);
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "provenance top-level inventory drift"
        );
    }

    #[test]
    fn wrong_protocol_identity_is_rejected() {
        let temporary = fixture();
        let mut lock = read_value(temporary.path(), LOCK_PATH);
        lock["protocol"] = json!("uniswap-v3");
        lock["protocol_identity"]["classification"] = json!("canonical_uniswap_v3");
        write_json(temporary.path(), LOCK_PATH, &lock);
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "baseline identity, status, eligibility, or remaining-gate drift"
        );
    }

    #[test]
    fn artifact_path_escape_is_rejected() {
        let temporary = fixture();
        let mut lock = read_value(temporary.path(), LOCK_PATH);
        for record in lock["artifact_lock"].as_array_mut().unwrap() {
            if record["role"] == json!("schema") {
                record["path"] = json!("../../schema.graphql");
            }
        }
        write_json(temporary.path(), LOCK_PATH, &lock);
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "artifact metadata drift for schema"
        );
    }

    #[test]
    fn an_escaping_path_that_survives_metadata_is_refused_by_the_root_guard() {
        let temporary = fixture();
        assert_eq!(
            repository_path_str(temporary.path(), "../../schema.graphql", "schema path")
                .unwrap_err(),
            "schema path escapes the repository root"
        );
        assert_eq!(
            repository_path_str(temporary.path(), "/etc/passwd", "schema path").unwrap_err(),
            "schema path must be a non-empty repository-relative path"
        );
        assert_eq!(
            repository_path(temporary.path(), None, "schema path").unwrap_err(),
            "schema path must be a non-empty repository-relative path"
        );
    }

    #[test]
    fn m7_milestone_drift_is_rejected() {
        let temporary = fixture();
        replace_once(
            temporary.path(),
            &binding_relative(),
            "milestone: M7",
            "milestone: M8",
        );
        assert_eq!(
            run(temporary.path()).unwrap_err(),
            "target binding identity, M7, market snapshot, or source status drift"
        );
    }

    #[test]
    fn a_lock_outside_docs_provenance_is_rejected() {
        assert_eq!(
            verify(&repository(), Path::new("docs/other.json"), None).unwrap_err(),
            "Aerodrome Slipstream provenance must remain under docs/provenance"
        );
    }

    #[test]
    fn an_exact_source_root_is_refused_for_this_family() {
        assert_eq!(
            verify(&repository(), Path::new(LOCK_PATH), Some(Path::new("/"))).unwrap_err(),
            "Aerodrome Slipstream Base has no exact-source reproduction mode"
        );
    }

    #[test]
    fn python_helper_semantics_are_preserved() {
        assert_eq!(normalize_call(Some(&json!("  a   b\nc  "))), "a b c");
        assert_eq!(normalize_call(None), "None");
        assert_eq!(py_str(Some(&json!(true))), "True");
        assert_eq!(py_str(Some(&Value::Null)), "None");
        assert_eq!(
            cid_from_file(Some(&json!({"/": "/ipfs/QmAbc"}))).unwrap(),
            "QmAbc"
        );
        assert_eq!(
            cid_from_file(Some(&json!({"/": "/ipfs/bafy"}))).unwrap_err(),
            "unexpected IPFS location: '/ipfs/bafy'"
        );
        assert_eq!(
            cid_from_file(None).unwrap_err(),
            "unexpected IPFS file value: None"
        );
        assert_eq!(utf16le("0.01"), b"0\x00.\x000\x001\x00");
        assert!(contains_subslice(b"abcdef", b"cde"));
        assert!(!contains_subslice(b"abcdef", b"ceg"));
    }
}
