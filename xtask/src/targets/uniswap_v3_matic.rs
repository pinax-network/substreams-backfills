//! Rust port of the retired `scripts/verify-uniswap-v3-matic-target.py` (#110): the
//! immutable Uniswap V3 Matic target, its static layout profile, the retained
//! Qma8 closure, and the exact-source behavior profile. Every Python
//! `fail(...)` becomes an `Err` carrying the identical message; any I/O, JSON,
//! or YAML error also fails closed.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::path::{Component, Path, PathBuf};

use serde::de::{DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde_json::{json, Map, Value};

use crate::target_common::{
    git_blob_hash, logical_hash, normalize_event, parse_schema, sha256_hex,
};

pub const LOCK_PATH: &str = "docs/provenance/uniswap-v3-matic-target.json";
const PROFILE_PATH: &str = "uniswap-v3-matic/layout-profile-v1.json";
const EXPECTED_DEPLOYMENT: &str = "QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3";
const BINDING_PATH: &str = "uniswap-v3-matic/QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3.yaml";
const EXPECTED_SCHEMA: &str = "QmVYKvi799Cpg4WVXjhSWjRXNcNg4p1JQxj1WBdbcfHvoq";
const EXPECTED_QMA8_SCHEMA: &str = "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru";
const EXPECTED_SOURCE_STATUS: &str = "exact_reproduction";
const EXPECTED_SOURCE_COMMIT: &str = "d07374a05719e68a10a339f79cdfbc048807cfdc";
const EXPECTED_SOURCE_TREE: &str = "8f5cefd138068952bee909522a0f1d88fdc87b42";
const EXPECTED_PROFILE_BYTES: usize = 17057;
const EXPECTED_PROFILE_SHA256: &str =
    "dae4b26bf9ba97f4e8a83facf8494adda7f45e3cd6f330929027e73a71c288a0";

/// `(handler, signature, topic0)` for one profile component handler.
type HandlerContract = (&'static str, &'static str, &'static str);

/// The locked handler contract per profile component, in declaration order.
const EXPECTED_PROFILE_HANDLERS: [(&str, &[HandlerContract]); 2] = [
    (
        "Factory",
        &[(
            "handlePoolCreated",
            "PoolCreated(address,address,uint24,int24,address)",
            "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
        )],
    ),
    (
        "Pool",
        &[
            (
                "handleInitialize",
                "Initialize(uint160,int24)",
                "0x98636036cb66a9c19a37435efc1e90142190214e8abeb821bdba3f2990dd4c95",
            ),
            (
                "handleSwap",
                "Swap(address,address,int256,int256,uint160,uint128,int24)",
                "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
            ),
            (
                "handleMint",
                "Mint(address,address,int24,int24,uint128,uint256,uint256)",
                "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde",
            ),
            (
                "handleBurn",
                "Burn(address,int24,int24,uint128,uint256,uint256)",
                "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c",
            ),
            (
                "handleCollect",
                "Collect(address,address,int24,int24,uint128,uint128)",
                "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0",
            ),
        ],
    ),
];

const EXPECTED_BEHAVIOR_SOURCE_PATHS: [&str; 17] = [
    "config/matic/chain.ts",
    "src/common/backfill.ts",
    "src/common/constants.ts",
    "src/common/pricing.ts",
    "src/common/staticTokenDefinition.ts",
    "src/common/token.ts",
    "src/common/utils.ts",
    "src/v3/mappings/burn.ts",
    "src/v3/mappings/collect.ts",
    "src/v3/mappings/core.ts",
    "src/v3/mappings/factory.ts",
    "src/v3/mappings/initialize.ts",
    "src/v3/mappings/intervalUpdates.ts",
    "src/v3/mappings/mint.ts",
    "src/v3/mappings/swap.ts",
    "src/v3/mappings/tick.ts",
    "src/v3/mappings/utils.ts",
];
const EXPECTED_BEHAVIOR_SOURCE_LOCK_SHA256: &str =
    "6444ef3af35d15445a86056f65db9aca24c29d94e468e76c95f018609fcdb0aa";

const EXPECTED_REQUIRED_CHANGES: [&str; 10] = [
    "matic_chain_config_and_factory_start_block",
    "sixteen_entity_graph_out_with_bytes_ids_and_exact_nullability",
    "six_immutable_entity_physical_and_operation_order_support",
    "pool_collect_decode_transaction_tvl_fee_and_interval_semantics",
    "token_pool_count_zero_compatibility",
    "omit_position_snapshot_tick_windows_fee_growth_and_flash_writers",
    "matic_transaction_repeated_save_and_nonfatal_failure_fixtures",
    "exact_handler_save_order_blockchanges_and_poi_projection",
    "target_specific_package_module_hashes_and_initial_block",
    "matic_graph_node_logical_physical_vid_poi_and_postgresql_parity_certification",
];

/// The M0 gate text, shared verbatim by the profile and the provenance lock.
const M0_GATE: &str = "M0: fully account for both required clusters by inventorying every current copy or fresh structural absence proof; when viable healthy copies exist, independently select the minimum stable same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all viable copies, which may be different copies, and require both minima to exceed 28 days or be non-converging; either minimum at or below 28 days stops implementation, compute, and load; with no viable copy, require fresh structural absence proof from both clusters.";

const EXPECTED_REMAINING_GATES: [&str; 7] = [
    M0_GATE,
    "M2_ordered_blockchanges_generic_loader_and_release_contract",
    "M2_matic_physical_profile_and_loader_schema_metadata_proof",
    "M3_certified_qma8_factory_pool_handler_field_and_runtime_contract",
    "Matic_runtime_implementation_and_fixed_range_differential_parity",
    "Matic_physical_vid_poi_failure_and_postgresql_restore_certification",
    "paused_load_validation_and_separate_operational_activation_approval",
];

const EXPECTED_LOCK_REMAINING_GATES: [&str; 7] = [
    M0_GATE,
    "M2 must ship the ordered BlockChanges generic loader and release contract.",
    "M2 must capture and verify the Matic physical schema and loader metadata profile.",
    "M3 must certify the Qma8 Factory/Pool handler, field-writer, runtime-population, and required-absence contract.",
    "The Matic runtime must implement this profile and pass fixed-range differential parity.",
    "Matic physical, VID, PoI, failure, PostgreSQL, and paused-restore certification must pass.",
    "A paused load requires separate operational validation and activation approval.",
];

fn expected_truth_boundary() -> Value {
    json!({
        "static_target_layout_complete": true,
        "qma8_deployed_schema_diff_complete": true,
        "exact_source_transitive_closure_complete": true,
        "static_mapping_behavior_profile_complete": true,
        "reuse_assessment_static_only": true,
        "full_graph_node_runtime_handler_semantics_complete": false,
        "implementation_authorized": false,
        "eligibility_complete": false,
        "runtime_parity": false,
        "logical_parity": false,
        "physical_profile_complete": false,
        "physical_parity": false,
        "poi_parity": false,
        "target_graph_node_runtime_identity_bound": false,
        "backfill_ready": false,
        "production_ready": false,
    })
}

fn expected_market_snapshot() -> Value {
    json!({
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 386433,
        "query_fees_grt_24h": "471.970",
        "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
    })
}

// ---------------------------------------------------------------------------
// Python-shaped primitives
// ---------------------------------------------------------------------------

fn fail<T>(message: impl Into<String>) -> Result<T, String> {
    Err(message.into())
}

static NULL: Value = Value::Null;

/// `value.get(key)` with Python's `None` for both a missing key and a null.
fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    value.get(key).unwrap_or(&NULL)
}

/// `value[key]`; a missing key raises Python's `KeyError`, whose printed form
/// is the quoted key.
fn index<'a>(value: &'a Value, key: &str) -> Result<&'a Value, String> {
    value.get(key).ok_or_else(|| format!("'{key}'"))
}

/// Python `str(value)`.
fn py_str(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(number) => number.to_string(),
        other => py_repr(other),
    }
}

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
            other if other == quote => {
                out.push('\\');
                out.push(other);
            }
            other => out.push(other),
        }
    }
    out.push(quote);
    out
}

/// Python `repr(value)` for a decoded JSON value.
fn py_repr(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => py_repr_str(text),
        Value::Array(items) => {
            let rendered: Vec<String> = items.iter().map(py_repr).collect();
            format!("[{}]", rendered.join(", "))
        }
        Value::Object(entries) => {
            let rendered: Vec<String> = entries
                .iter()
                .map(|(key, item)| format!("{}: {}", py_repr_str(key), py_repr(item)))
                .collect();
            format!("{{{}}}", rendered.join(", "))
        }
    }
}

fn read_bytes(path: &Path) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_text(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_yaml(path: &Path) -> Result<Value, String> {
    let text = read_text(path)?;
    let parsed: serde_yaml::Value = serde_yaml::from_str(&text)
        .map_err(|error| format!("cannot parse {}: {error}", path.display()))?;
    serde_json::to_value(parsed)
        .map_err(|error| format!("cannot convert {}: {error}", path.display()))
}

/// `json.load(..., object_pairs_hook=reject_duplicate_keys)`: a repeated key in
/// any object is rejected rather than silently overwritten.
struct UniqueJson<'a> {
    path: &'a Path,
}

impl<'de> DeserializeSeed<'de> for UniqueJson<'_> {
    type Value = Value;

    fn deserialize<D>(self, deserializer: D) -> Result<Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_any(self)
    }
}

impl<'de> Visitor<'de> for UniqueJson<'_> {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
        formatter.write_str("any JSON value")
    }

    fn visit_unit<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_bool<E>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Value, E> {
        Ok(Value::from(value))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Value, E> {
        Ok(Value::from(value))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Value, E> {
        Ok(Value::from(value))
    }

    fn visit_str<E>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_owned()))
    }

    fn visit_string<E>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }

    fn visit_seq<A>(self, mut access: A) -> Result<Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut items = Vec::new();
        while let Some(item) = access.next_element_seed(UniqueJson { path: self.path })? {
            items.push(item);
        }
        Ok(Value::Array(items))
    }

    fn visit_map<A>(self, mut access: A) -> Result<Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut entries = Map::new();
        while let Some(key) = access.next_key::<String>()? {
            let item = access.next_value_seed(UniqueJson { path: self.path })?;
            if entries.contains_key(&key) {
                return Err(serde::de::Error::custom(format!(
                    "duplicate JSON key in {}: {key}",
                    self.path.display()
                )));
            }
            entries.insert(key, item);
        }
        Ok(Value::Object(entries))
    }
}

fn load_json(path: &Path) -> Result<Value, String> {
    let text = read_text(path)?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let value = UniqueJson { path }
        .deserialize(&mut deserializer)
        .map_err(|error| json_error(path, &error))?;
    deserializer
        .end()
        .map_err(|error| json_error(path, &error))?;
    Ok(value)
}

fn json_error(path: &Path, error: &serde_json::Error) -> String {
    let message = error.to_string();
    if message.starts_with("duplicate JSON key in ") {
        // serde_json appends the input position to visitor errors; the Python
        // `fail(...)` text stops before it.
        return match message.rfind(" at line ") {
            Some(end) => message[..end].to_string(),
            None => message,
        };
    }
    format!("cannot parse {}: {message}", path.display())
}

/// `repository_path`: reject absolute or `..`-bearing values and require the
/// resolved path to sit strictly below `root`.
fn repository_path(root: &Path, value: &Value, label: &str) -> Result<PathBuf, String> {
    let invalid = || format!("invalid repository path for {label}: {}", py_repr(value));
    let text = match value.as_str() {
        Some(text) if !text.starts_with('/') => text,
        _ => return Err(invalid()),
    };
    let components: Vec<Component<'_>> = Path::new(text).components().collect();
    if components
        .iter()
        .any(|component| !matches!(component, Component::Normal(_) | Component::CurDir))
    {
        return Err(invalid());
    }
    let base = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve {}: {error}", root.display()))?;
    let mut resolved = base.clone();
    for component in components {
        if let Component::Normal(part) = component {
            resolved.push(part);
        }
    }
    if resolved == base || !resolved.starts_with(&base) {
        return fail(format!("repository path escapes root for {label}: {text}"));
    }
    Ok(resolved)
}

/// `{"/": "/ipfs/Qm…"}` → `Qm…`, with the Python `repr` failure text.
fn cid_from_file(value: &Value) -> Result<String, String> {
    let entries = match value.as_object() {
        Some(entries) if entries.len() == 1 && entries.contains_key("/") => entries,
        _ => return fail(format!("unexpected IPFS file value: {}", py_repr(value))),
    };
    let location = &entries["/"];
    match location.as_str() {
        Some(text) if text.starts_with("/ipfs/Qm") => Ok(text["/ipfs/".len()..].to_string()),
        _ => fail(format!("unexpected IPFS location: {}", py_repr(location))),
    }
}

fn is_hex(value: &Value, width: usize) -> bool {
    let text = py_str(value);
    text.len() == width
        && text
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
}

fn normalize_source_bytes(payload: &[u8], normalization: &str) -> Result<Vec<u8>, String> {
    match normalization {
        "identity" => Ok(payload.to_vec()),
        "remove_one_trailing_lf" => {
            if !payload.ends_with(b"\n") || payload.ends_with(b"\n\n") {
                return fail("ABI normalization requires exactly one vendored trailing LF");
            }
            Ok(payload[..payload.len() - 1].to_vec())
        }
        other => fail(format!("unknown normalization: {other}")),
    }
}

// ---------------------------------------------------------------------------
// Artifact lock
// ---------------------------------------------------------------------------

const EXPECTED_ARTIFACT_ROLES: [&str; 9] = [
    "deployment",
    "erc20_abi",
    "erc20_name_bytes_abi",
    "erc20_symbol_bytes_abi",
    "factory_abi",
    "factory_mapping_wasm",
    "pool_abi",
    "pool_mapping_wasm",
    "schema",
];

fn verify_artifact_lock(root: &Path, lock: &Value) -> Result<BTreeMap<String, Value>, String> {
    let records = match field(lock, "artifact_lock").as_array() {
        Some(records) => records.clone(),
        None => return fail("artifact_lock must be a list"),
    };

    let mut by_role: BTreeMap<String, Value> = BTreeMap::new();
    for record in &records {
        if !record.is_object() {
            return fail("artifact record must be an object");
        }
        let role_value = field(record, "role");
        let cid_value = field(record, "cid");
        let role = match role_value.as_str() {
            Some(role) if !by_role.contains_key(role) => role.to_string(),
            _ => {
                return fail(format!(
                    "duplicate or invalid artifact role: {}",
                    py_repr(role_value)
                ));
            }
        };
        match cid_value.as_str() {
            Some(cid) if cid.starts_with("Qm") => {}
            _ => {
                return fail(format!("invalid CID for {role}: {}", py_repr(cid_value)));
            }
        }
        by_role.insert(role.clone(), record.clone());

        let vendored_path = field(record, "vendored_path");
        if vendored_path.is_null() {
            for required in ["source_bytes", "source_sha256"] {
                if record.get(required).is_none() {
                    return fail(format!("unvendored {role} is missing {required}"));
                }
            }
            continue;
        }
        if !vendored_path.is_string() {
            return fail(format!("invalid vendored path for {role}"));
        }
        let path = repository_path(root, vendored_path, &role)?;
        let payload = read_bytes(&path)?;
        if json!(payload.len()) != *field(record, "vendored_bytes") {
            return fail(format!("vendored byte count drift for {role}"));
        }
        if json!(sha256_hex(&payload)) != *field(record, "vendored_sha256") {
            return fail(format!("vendored digest drift for {role}"));
        }

        let source_payload =
            normalize_source_bytes(&payload, &py_str(field(record, "normalization")))?;
        if json!(source_payload.len()) != *field(record, "source_bytes") {
            return fail(format!("source byte count drift for {role}"));
        }
        if json!(sha256_hex(&source_payload)) != *field(record, "source_sha256") {
            return fail(format!("source digest drift for {role}"));
        }
        if role.ends_with("_abi") {
            serde_json::from_slice::<Value>(&source_payload)
                .map_err(|error| format!("cannot parse {}: {error}", path.display()))?;
        }
    }

    let expected: BTreeSet<String> = EXPECTED_ARTIFACT_ROLES
        .iter()
        .map(|role| (*role).to_string())
        .collect();
    let present: BTreeSet<String> = by_role.keys().cloned().collect();
    if present != expected {
        let drift: Vec<&String> = present.symmetric_difference(&expected).collect();
        return fail(format!("artifact roles drift: {}", py_repr(&json!(drift))));
    }
    Ok(by_role)
}

fn artifact<'a>(artifacts: &'a BTreeMap<String, Value>, role: &str) -> Result<&'a Value, String> {
    artifacts.get(role).ok_or_else(|| format!("'{role}'"))
}

fn artifact_cid(artifacts: &BTreeMap<String, Value>, role: &str) -> Result<String, String> {
    Ok(py_str(field(artifact(artifacts, role)?, "cid")))
}

/// `[(abi.name, cid)]` for a manifest mapping's `abis` list.
fn abi_contract(mapping: &Value) -> Result<Vec<(String, String)>, String> {
    let entries = match field(mapping, "abis").as_array() {
        Some(entries) => entries.clone(),
        None => return fail("mapping ABI contract must be a list"),
    };
    entries
        .iter()
        .map(|entry| {
            Ok((
                py_str(field(entry, "name")),
                cid_from_file(field(entry, "file"))?,
            ))
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Deployment manifest
// ---------------------------------------------------------------------------

fn verify_manifest(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let path = root.join(py_str(field(
        artifact(artifacts, "deployment")?,
        "vendored_path",
    )));
    let manifest = read_yaml(&path)?;
    let deployment = index(lock, "deployment")?;

    if *field(deployment, "data_sources") != json!(["Factory"])
        || *field(deployment, "templates") != json!(["Pool"])
    {
        return fail("deployment component inventory drift");
    }
    if *field(deployment, "features") != json!(["nonFatalErrors", "grafting"]) {
        return fail("deployment feature lock drift");
    }
    if *field(deployment, "position_manager") != json!(false)
        || *field(deployment, "flash_handler") != json!(false)
    {
        return fail("deployment absence contract drift");
    }

    if field(&manifest, "specVersion") != index(deployment, "spec_version")? {
        return fail("manifest specVersion drift");
    }
    if *field(&manifest, "repository") != json!("https://github.com/Uniswap/uniswap-v3-subgraph") {
        return fail("manifest source repository drift");
    }
    if *field(&manifest, "features") != json!(["nonFatalErrors", "grafting"]) {
        return fail("manifest feature contract drift");
    }
    if manifest.get("graft").is_some() {
        return fail("target manifest unexpectedly gained a concrete graft");
    }
    if cid_from_file(index(index(&manifest, "schema")?, "file")?)? != EXPECTED_SCHEMA {
        return fail("manifest schema CID drift");
    }

    let data_sources = field(&manifest, "dataSources").as_array().cloned();
    let templates = field(&manifest, "templates").as_array().cloned();
    let data_sources = match data_sources {
        Some(list) if list.len() == 1 => list,
        _ => return fail("expected exactly one Factory data source"),
    };
    let templates = match templates {
        Some(list) if list.len() == 1 => list,
        _ => return fail("expected exactly one Pool template"),
    };

    let factory = &data_sources[0];
    let factory_mapping = index(factory, "mapping")?;
    if *field(factory, "name") != json!("Factory")
        || *field(factory, "network") != json!("matic")
        || *field(factory, "kind") != json!("ethereum/contract")
    {
        return fail("Factory data-source identity drift");
    }
    if *index(factory, "source")?
        != json!({
            "abi": "Factory",
            "address": index(deployment, "factory")?,
            "startBlock": index(deployment, "start_block")?,
        })
    {
        return fail("Factory source contract drift");
    }
    if field(factory_mapping, "apiVersion") != index(deployment, "mapping_api_version")? {
        return fail("Factory mapping apiVersion drift");
    }
    if *field(factory_mapping, "kind") != json!("ethereum/events")
        || *field(factory_mapping, "language") != json!("wasm/assemblyscript")
        || *field(factory_mapping, "entities") != json!(["Pool", "Token"])
    {
        return fail("Factory mapping shape drift");
    }
    if abi_contract(factory_mapping)?
        != vec![
            (
                "Factory".to_string(),
                artifact_cid(artifacts, "factory_abi")?,
            ),
            ("ERC20".to_string(), artifact_cid(artifacts, "erc20_abi")?),
            (
                "ERC20SymbolBytes".to_string(),
                artifact_cid(artifacts, "erc20_symbol_bytes_abi")?,
            ),
            (
                "ERC20NameBytes".to_string(),
                artifact_cid(artifacts, "erc20_name_bytes_abi")?,
            ),
            ("Pool".to_string(), artifact_cid(artifacts, "pool_abi")?),
        ]
    {
        return fail("Factory ABI inventory drift");
    }
    if cid_from_file(index(factory_mapping, "file")?)?
        != artifact_cid(artifacts, "factory_mapping_wasm")?
    {
        return fail("Factory mapping CID drift");
    }
    let factory_handlers = match field(factory_mapping, "eventHandlers").as_array() {
        Some(handlers)
            if handlers
                .iter()
                .map(|entry| field(entry, "handler").clone())
                .collect::<Vec<Value>>()
                == vec![json!("handlePoolCreated")] =>
        {
            handlers.clone()
        }
        _ => return fail("Factory handler contract drift"),
    };
    let declared_event = match factory_handlers[0].get("event") {
        Some(event) => py_str(event),
        None => String::new(),
    };
    if normalize_event(&declared_event)
        != normalize_event(
            "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)",
        )
    {
        return fail("Factory event signature drift");
    }

    let pool = &templates[0];
    let pool_mapping = index(pool, "mapping")?;
    if *field(pool, "name") != json!("Pool")
        || *field(pool, "network") != json!("matic")
        || *field(pool, "kind") != json!("ethereum/contract")
    {
        return fail("Pool template identity drift");
    }
    if *field(pool, "source") != json!({"abi": "Pool"}) {
        return fail("Pool source contract drift");
    }
    if field(pool_mapping, "apiVersion") != index(deployment, "mapping_api_version")? {
        return fail("Pool mapping apiVersion drift");
    }
    if *field(pool_mapping, "kind") != json!("ethereum/events")
        || *field(pool_mapping, "language") != json!("wasm/assemblyscript")
        || *field(pool_mapping, "entities") != json!(["Pool", "Token"])
    {
        return fail("Pool mapping shape drift");
    }
    if abi_contract(pool_mapping)?
        != vec![
            ("Pool".to_string(), artifact_cid(artifacts, "pool_abi")?),
            (
                "Factory".to_string(),
                artifact_cid(artifacts, "factory_abi")?,
            ),
            ("ERC20".to_string(), artifact_cid(artifacts, "erc20_abi")?),
        ]
    {
        return fail("Pool ABI inventory drift");
    }
    if cid_from_file(index(pool_mapping, "file")?)? != artifact_cid(artifacts, "pool_mapping_wasm")?
    {
        return fail("Pool mapping CID drift");
    }

    let expected_handlers = json!([
        "handleInitialize",
        "handleSwap",
        "handleMint",
        "handleBurn",
        "handleCollect",
    ]);
    let handlers = match field(pool_mapping, "eventHandlers").as_array() {
        Some(handlers)
            if Value::Array(
                handlers
                    .iter()
                    .map(|entry| field(entry, "handler").clone())
                    .collect(),
            ) == expected_handlers =>
        {
            handlers.clone()
        }
        _ => return fail("Pool handler order or set drift"),
    };
    if handlers
        .iter()
        .any(|entry| *field(entry, "handler") == json!("handleFlash"))
    {
        return fail("target manifest unexpectedly gained Flash");
    }

    let expected_events = [
        "Initialize(uint160,int24)",
        "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24)",
        "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
        "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
        "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)",
    ];
    let mut observed = Vec::new();
    for entry in &handlers {
        observed.push(normalize_event(&py_str(index(entry, "event")?)));
    }
    let expected: Vec<String> = expected_events.iter().map(|e| normalize_event(e)).collect();
    if observed != expected {
        return fail("Pool event signatures drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Schema comparison
// ---------------------------------------------------------------------------

type Entities = BTreeMap<String, BTreeMap<String, String>>;

/// The family's `parse_schema`, which classifies every entity as either
/// `immutable` (declared `@entity(immutable: true)`) or `mutable` (everything
/// else), unlike the shared helper's `explicit_mutable` set.
fn parse_schema_file(
    path: &Path,
) -> Result<(Entities, BTreeSet<String>, BTreeSet<String>), String> {
    let parsed = parse_schema(&read_text(path)?);
    let mutable: BTreeSet<String> = parsed
        .entities
        .keys()
        .filter(|name| !parsed.immutable.contains(*name))
        .cloned()
        .collect();
    Ok((parsed.entities, parsed.immutable, mutable))
}

fn sorted_names(names: &BTreeSet<String>) -> Value {
    Value::Array(names.iter().map(|name| json!(name)).collect())
}

fn contract_diff(matic: &Entities, qma8: &Entities) -> (Value, Value, Value, Value) {
    let missing: Vec<&String> = qma8
        .keys()
        .filter(|key| !matic.contains_key(*key))
        .collect();
    let extra: Vec<&String> = matic
        .keys()
        .filter(|key| !qma8.contains_key(*key))
        .collect();
    let exact: Vec<&String> = matic
        .iter()
        .filter(|(key, fields)| qma8.get(*key) == Some(*fields))
        .map(|(key, _)| key)
        .collect();

    let mut differences = Map::new();
    for (entity, matic_fields) in matic {
        let Some(qma8_fields) = qma8.get(entity) else {
            continue;
        };
        let missing_fields: Vec<&String> = qma8_fields
            .keys()
            .filter(|name| !matic_fields.contains_key(*name))
            .collect();
        let extra_fields: Vec<&String> = matic_fields
            .keys()
            .filter(|name| !qma8_fields.contains_key(*name))
            .collect();
        let mut type_differences = Map::new();
        for (name, matic_type) in matic_fields {
            let Some(qma8_type) = qma8_fields.get(name) else {
                continue;
            };
            if matic_type == qma8_type {
                continue;
            }
            type_differences.insert(
                name.clone(),
                json!({
                    "matic_type": matic_type,
                    "qma8_type": qma8_type,
                    "matic_non_null": matic_type.ends_with('!'),
                    "qma8_non_null": qma8_type.ends_with('!'),
                }),
            );
        }
        if !missing_fields.is_empty() || !extra_fields.is_empty() || !type_differences.is_empty() {
            differences.insert(
                entity.clone(),
                json!({
                    "missing_from_matic": missing_fields,
                    "extra_in_matic": extra_fields,
                    "type_differences": Value::Object(type_differences),
                }),
            );
        }
    }
    (
        json!(missing),
        json!(extra),
        json!(exact),
        Value::Object(differences),
    )
}

// ---------------------------------------------------------------------------
// Retained Qma8 reference closure
// ---------------------------------------------------------------------------

fn verify_repository_records(
    root: &Path,
    records: &Value,
    expected: &Value,
    label: &str,
) -> Result<(), String> {
    if records != expected {
        return fail(format!("{label} inventory or lock drift"));
    }
    for record in expected.as_array().expect("expected records are a list") {
        let role = py_str(index(record, "role")?);
        let payload = read_bytes(&repository_path(root, index(record, "path")?, &role)?)?;
        if json!(payload.len()) != *index(record, "bytes")?
            || json!(sha256_hex(&payload)) != *index(record, "sha256")?
        {
            return fail(format!("{label} payload drift: {role}"));
        }
    }
    Ok(())
}

fn expected_upstream_records() -> Value {
    json!([
        {
            "role": "upstream_provenance",
            "path": "docs/provenance/uniswap-v3-qma8a81t-parity.json",
            "bytes": 3134,
            "sha256": "aafc43562e8867b0e40cfc905065aad14dc72227b7b937d1cf7ccbf6eb8457a8"
        },
        {
            "role": "upstream_file_inventory",
            "path": "docs/provenance/uniswap-v3-qma8a81t-parity-files.json",
            "bytes": 18035,
            "sha256": "177a98f60f230d1b13dfa064f3b98a50163a506d2c7a08432330d47ee2170e60"
        },
        {
            "role": "imported_schema",
            "path": "uniswap-v3/source/schema.graphql",
            "bytes": 18883,
            "sha256": "f234a0e4dc88c923d6ad28a3fcd1ed6093351bd2221d7c18486f0cbde41bb52c"
        },
        {
            "role": "imported_module_graph",
            "path": "uniswap-v3/source/substreams.yaml",
            "bytes": 11178,
            "sha256": "74489e3056ff18760b3cd416fb10558f7fec1481a441b596e2b1e0f526c879a5"
        }
    ])
}

fn expected_m3_records() -> Value {
    json!([
        {
            "role": "graft_ancestry",
            "path": "uniswap-v3/graft-ancestry/v2/contract.json",
            "bytes": 541804,
            "sha256": "ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e"
        },
        {
            "role": "writer_compatibility",
            "path": "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
            "bytes": 517362,
            "sha256": "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
        },
        {
            "role": "segment_writer_matrix",
            "path": "uniswap-v3/segment-writer-matrix/v1/contract.json",
            "bytes": 2785821,
            "sha256": "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
        },
        {
            "role": "execution_order",
            "path": "uniswap-v3/execution-order/v1/contract.json",
            "bytes": 22216,
            "sha256": "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"
        },
        {
            "role": "writer_runtime",
            "path": "uniswap-v3/writer-runtime/contract-v1.json",
            "bytes": 6247,
            "sha256": "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
        },
        {
            "role": "segment_profiles",
            "path": "uniswap-v3/writer-runtime/segment-profiles-v1.json",
            "bytes": 12989,
            "sha256": "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
        },
        {
            "role": "mainnet_chain_config",
            "path": "uniswap-v3/chain-config/configs/mainnet-v1.json",
            "bytes": 3503,
            "sha256": "30f5caf9ee8906a8886dc103e55286b9d5b6dbd8784d1c97d21b9a38b266bb55"
        }
    ])
}

/// Truth-boundary claims that must stay `false` in each retained M3 contract.
const FALSE_TRUTH_CLAIMS: [(&str, &[&str]); 5] = [
    (
        "graft_ancestry",
        &[
            "boundary_state_continuity_complete",
            "field_writer_audit_complete",
            "logical_oracle_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
        ],
    ),
    (
        "writer_compatibility",
        &[
            "backfill_ready",
            "factory_pool_full_field_writer_semantics_complete",
            "full_handler_semantics_complete",
            "logical_oracle_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_population_complete",
            "target_graph_node_runtime_identity_bound",
        ],
    ),
    (
        "segment_writer_matrix",
        &[
            "backfill_ready",
            "field_writer_semantics_complete",
            "full_handler_semantics_complete",
            "logical_parity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_population_complete",
            "target_graph_node_runtime_identity_bound",
        ],
    ),
    (
        "execution_order",
        &[
            "backfill_allowed",
            "combined_handler_order_implemented",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_consumes_contract",
            "target_runtime_identity_bound",
        ],
    ),
    (
        "writer_runtime",
        &[
            "backfill_ready",
            "graph_out_replaced",
            "logical_oracle_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_population_complete",
        ],
    ),
];

fn verify_qma8_reference(root: &Path, lock: &Value) -> Result<Value, String> {
    let reference = field(lock, "qma8_reference");
    if !reference.is_object() || *field(reference, "family") != json!("uniswap-v3-mainnet-base") {
        return fail("Qma8 family reference drift");
    }
    let deployed = field(reference, "deployed_schema");
    let expected_deployed = json!({
        "cid": EXPECTED_QMA8_SCHEMA,
        "path": "uniswap-v3/graft-ancestry/v1/artifacts/Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru",
        "bytes": 19034,
        "sha256": "ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c",
        "entity_count": 20,
        "logical_sha256": "6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d",
        "immutable_entities": [],
    });
    if *deployed != expected_deployed {
        return fail("retained Qma8 deployed-schema identity drift");
    }
    let deployed_payload = read_bytes(&repository_path(
        root,
        index(deployed, "path")?,
        "Qma8 deployed schema",
    )?)?;
    if json!(deployed_payload.len()) != *index(deployed, "bytes")?
        || json!(sha256_hex(&deployed_payload)) != *index(deployed, "sha256")?
    {
        return fail("retained Qma8 deployed-schema payload drift");
    }

    let upstream = field(reference, "upstream_source");
    if !upstream.is_object()
        || json!({
            "repository": field(upstream, "repository"),
            "commit": field(upstream, "commit"),
            "tree": field(upstream, "tree"),
        }) != json!({
            "repository": "pinax-network/substreams-uniswap-v3",
            "commit": "42c7b15345e6df80561b694e52a0eb622b374b96",
            "tree": "a00e882e92d07b46550b74dea279c114d57631ac",
        })
    {
        return fail("Qma8 upstream source identity drift");
    }
    let upstream_records = expected_upstream_records();
    verify_repository_records(
        root,
        field(upstream, "records"),
        &upstream_records,
        "Qma8 upstream",
    )?;
    let upstream_provenance =
        load_json(&root.join("docs/provenance/uniswap-v3-qma8a81t-parity.json"))?;
    if !upstream_provenance.is_object() {
        return fail("Qma8 upstream provenance must be an object");
    }
    let source = field(&upstream_provenance, "source");
    if field(source, "commit") != index(upstream, "commit")? {
        return fail("Qma8 upstream provenance commit drift");
    }
    if field(source, "tree") != index(upstream, "tree")? {
        return fail("Qma8 upstream provenance tree drift");
    }
    if field(field(&upstream_provenance, "target_schema"), "raw_sha256")
        != index(deployed, "sha256")?
    {
        return fail("Qma8 upstream provenance target-schema binding drift");
    }

    let m3_records = expected_m3_records();
    verify_repository_records(
        root,
        field(reference, "m3_contract_closure"),
        &m3_records,
        "Qma8 M3 closure",
    )?;
    if *field(reference, "authority")
        != json!({
            "deployed_schema_is_layout_authority": true,
            "imported_source_schema_is_mutability_authority": false,
            "contract_closure_hashes_imply_m3_certification": false,
            "target_graph_node_runtime_identity_bound": false,
        })
    {
        return fail("Qma8 reference authority boundary drift");
    }

    let by_role: BTreeMap<String, &Value> = m3_records
        .as_array()
        .expect("expected records are a list")
        .iter()
        .map(|record| (py_str(field(record, "role")), record))
        .collect();
    for (role, claims) in FALSE_TRUTH_CLAIMS {
        let record = by_role.get(role).ok_or_else(|| format!("'{role}'"))?;
        let contract = load_json(&root.join(py_str(index(record, "path")?)))?;
        if !contract.is_object() || !field(&contract, "truth_boundary").is_object() {
            return fail(format!("Qma8 M3 truth boundary missing: {role}"));
        }
        let boundary = index(&contract, "truth_boundary")?;
        if claims
            .iter()
            .any(|claim| *field(boundary, claim) != json!(false))
        {
            return fail(format!("Qma8 M3 truth boundary was promoted: {role}"));
        }
    }
    Ok(deployed.clone())
}

fn verify_schema(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
    qma8_reference: &Value,
) -> Result<(), String> {
    let contract = index(lock, "logical_contract")?;
    let (matic, immutable, mutable) = parse_schema_file(&repository_path(
        root,
        field(artifact(artifacts, "schema")?, "vendored_path"),
        "Matic schema",
    )?)?;
    let (qma8, qma8_immutable, qma8_mutable) = parse_schema_file(&repository_path(
        root,
        index(qma8_reference, "path")?,
        "Qma8 deployed schema",
    )?)?;

    let matic_names: Vec<&String> = matic.keys().collect();
    if json!(matic_names) != *index(contract, "entities")?
        || json!(matic.len()) != *index(contract, "entity_count")?
    {
        return fail("Matic entity set drift");
    }
    if json!(logical_hash(&matic)) != *index(contract, "logical_sha256")? {
        return fail("Matic logical schema digest drift");
    }
    if sorted_names(&immutable) != *index(contract, "immutable_entities")? {
        return fail("Matic immutable entity contract drift");
    }
    if sorted_names(&mutable) != *index(contract, "mutable_entities")? {
        return fail("Matic mutable entity contract drift");
    }
    if json!(qma8.len()) != *index(contract, "qma8_entity_count")?
        || json!(logical_hash(&qma8)) != *index(contract, "qma8_logical_sha256")?
    {
        return fail("Qma8 logical reference drift");
    }
    if sorted_names(&qma8_immutable) != *index(contract, "qma8_immutable_entities")? {
        return fail("Qma8 deployed mutability reference drift");
    }
    if qma8_mutable.len() != qma8.len() {
        return fail("Qma8 deployed schema must remain all mutable");
    }

    let (missing, extra, exact, differences) = contract_diff(&matic, &qma8);
    if missing != *index(contract, "missing_from_matic")? {
        return fail("Matic missing-entity gap list drift");
    }
    if extra != *index(contract, "extra_in_matic")? {
        return fail("Matic extra-entity gap list drift");
    }
    if exact != *index(contract, "exact_field_match_entities")? {
        return fail("Matic exact-field entity list drift");
    }
    let immutable_only: BTreeSet<String> = immutable.difference(&qma8_immutable).cloned().collect();
    if sorted_names(&immutable_only) != *index(contract, "immutable_in_matic_but_mutable_in_qma8")?
    {
        return fail("Matic-to-Qma8 immutable/mutable gap drift");
    }
    let qma8_only: BTreeSet<String> = qma8_immutable.difference(&immutable).cloned().collect();
    if sorted_names(&qma8_only) != *index(contract, "mutable_in_matic_but_immutable_in_qma8")? {
        return fail("Qma8-to-Matic immutable/mutable gap drift");
    }
    if differences != *index(contract, "field_differences")? {
        return fail("Matic field/type/nullability gap list drift");
    }
    if *field(contract, "scope")
        != json!("static_deployed_schema_only_pending_runtime_physical_and_poi_comparison")
    {
        return fail("Matic/Qma8 schema comparison scope drift");
    }

    let (imported, imported_immutable, _) =
        parse_schema_file(&root.join("uniswap-v3/source/schema.graphql"))?;
    if logical_hash(&imported) != logical_hash(&qma8) {
        return fail("Qma8 imported source logical schema drift");
    }
    if sorted_names(&imported_immutable) != json!(["Burn", "Mint", "Swap", "Transaction"]) {
        return fail("Qma8 imported source mutability boundary drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Static layout profile
// ---------------------------------------------------------------------------

fn expected_profile_handlers(name: &str) -> Option<Value> {
    EXPECTED_PROFILE_HANDLERS
        .iter()
        .find(|(component, _)| *component == name)
        .map(|(_, handlers)| {
            Value::Array(
                handlers
                    .iter()
                    .map(|(handler, signature, topic0)| json!([handler, signature, topic0]))
                    .collect(),
            )
        })
}

fn expected_mapping_behavior() -> Value {
    json!({
        "evidence": "byte_exact_mapping_reproduction_plus_digest_bound_exact_source_transitive_closure",
        "factory_pool_created": {
            "pool_id": "pool_address_bytes",
            "token_ids": "token_address_bytes",
            "factory_entity_id": "lowercase_factory_address_hex",
            "bundle_entity_id": "1",
            "factory_pool_count_increment": 1,
            "token_pool_count_on_creation": 0,
            "token_pool_count_incremented": false,
            "dynamic_pool_template_created": true,
            "skip_pools": [],
            "pool_mappings": [],
            "missing_token_decimals_behavior": "return_without_pool_token_or_factory_saves; a newly-created Bundle may already have been saved",
            "save_order": ["Pool", "PoolTemplate.create", "Token0", "Token1", "Factory"],
        },
        "initialize": {
            "updates": [
                "Pool.sqrtPrice",
                "Pool.tick",
                "Bundle.ethPriceUSD",
                "PoolDayData",
                "PoolHourData",
                "Token0.derivedETH",
                "Token1.derivedETH",
            ],
            "pool_saved_before_bundle_and_interval_updates": true,
        },
        "mint": {
            "active_liquidity_condition": "tickLower_le_pool_tick_and_tickUpper_gt_pool_tick",
            "pool_and_token_tvl_delta": "add_amounts",
            "tick_liquidity_delta": "lower_gross_and_net_plus; upper_gross_plus_and_net_minus",
            "emits": ["Transaction", "Mint"],
        },
        "burn": {
            "active_liquidity_condition": "tickLower_le_pool_tick_and_tickUpper_gt_pool_tick",
            "pool_and_token_tvl_delta": "none_until_collect",
            "tick_liquidity_delta": "lower_gross_and_net_minus; upper_gross_minus_and_net_plus",
            "emits": ["Transaction", "Burn"],
        },
        "swap": {
            "ignored_pool": "0x9663f2ca0454accad3e094448ea6f77443880454",
            "amounts": "signed_pool_tvl_deltas_and_absolute_volume_amounts",
            "tracked_volume_divisor": 2,
            "untracked_volume_divisor": 2,
            "lp_fee_formula": "tracked_volume_times_fee_tier_div_1000000",
            "pool_saved_before_bundle_price_and_derived_token_price_updates": true,
            "emits": ["Transaction", "Swap"],
        },
        "collect": {
            "component": "Pool",
            "pool_and_token_tvl_delta": "subtract_collected_amounts",
            "collected_fee_aggregates": [
                "Pool.collectedFeesToken0",
                "Pool.collectedFeesToken1",
                "Pool.collectedFeesUSD",
            ],
            "transaction_saved_before_token_presence_check": true,
            "missing_token_behavior": "return_after_transaction_save",
            "emits": ["Transaction", "Collect"],
        },
        "transactions": {
            "id": "lowercase_transaction_hash_hex",
            "helper_saves_on_every_mint_burn_swap_or_collect_call": true,
            "gas_used": "0",
            "gas_price": "event.transaction.gasPrice",
            "immutable_target_entity": true,
            "same_transaction_multi_event_runtime_effect_certified": false,
        },
        "intervals": [
            "uniswap_day",
            "pool_day",
            "pool_hour",
            "token_day",
            "token_hour",
        ],
        "operation_order": {
            "helper_functions_save_entities_internally": true,
            "swap_repeats_pool_hour_save": true,
            "ordered_store_operations_required_for_poi": true,
            "coalesced_final_entity_changes_sufficient": false,
        },
        "writer_absence": {
            "position_manager_component_absent": true,
            "position_entities_absent": ["Position", "PositionSnapshot"],
            "tick_window_entities_absent": ["TickDayData", "TickHourData"],
            "flash_handler_absent": true,
            "flash_entity_static_writer_absent": true,
            "runtime_population_certified": false,
        },
    })
}

fn expected_reuse_assessment() -> Value {
    json!({
        "scope": "static_source_comparison_only",
        "certified_unchanged": [],
        "candidate_reuse_without_internal_algorithm_change": [
            {
                "component": "raw_firehose_block_transport",
                "dependency": "M2 ordered BlockChanges protocol and engine contract"
            },
            {
                "component": "Factory PoolCreated and Pool Initialize/Swap/Mint/Burn ABI decoders",
                "dependency": "Matic address routing, canonical ordinal fixtures, and target package tests"
            },
            {
                "component": "store_pools_created",
                "dependency": "Matic map_pools_created adapter and ERROR_POOL removal"
            },
            {
                "component": "store_pool_count",
                "dependency": "Matic factory identity and PoolCreated acceptance parity"
            },
            {
                "component": "store_pool_sqrt_price",
                "dependency": "Matic event extraction and Initialize/Swap ordinal parity"
            },
            {
                "component": "decimal conversion and sqrt-price math",
                "dependency": "Graph Node decimal normalization and fixed-range differential fixtures"
            }
        ],
        "target_adapter_required": [
            "map_pools_created token RPC failure and metadata fallback behavior",
            "whitelist pool derivation and Matic pricing configuration",
            "pool liquidity and derived TVL routing",
            "day/hour window creation, update, save order, and retention behavior",
            "target initial block and manifest/package configuration"
        ],
        "target_specific_replacement_required": [
            "map_extract_data_types must include Pool Collect and exclude NPM/Flash-only paths",
            "store_tokens must preserve Token.poolCount at zero instead of incrementing per pool",
            "transaction and total tx-count behavior must include Matic Pool Collect ordering",
            "swap volume, fee, TVL, and interval aggregation must reproduce the exact Matic mapping",
            "tick storage must omit TickDayData/TickHourData and the eleven absent Tick fields",
            "graph_out must emit the 16-entity Bytes-ID and six-immutable-entity layout"
        ],
        "components_to_omit": [
            "NonfungiblePositionManager routing",
            "Position and PositionSnapshot reducers",
            "TickDayData and TickHourData writers",
            "Pool fee-growth-global writers",
            "Flash handler and Flash row emission"
        ],
        "reuse_certified": false,
    })
}

fn expected_dependencies() -> Value {
    json!({
        "m2_generic_runtime": [
            "ordered BlockChanges family-to-engine protocol replacing common/src/lib.rs placeholder",
            "legacy schema profile support for Bytes versus ID, nullability, and immutable tables",
            "Graph Node metadata, VID, block-range, block$, decimal, PoI, and failure semantics",
            "target physical-profile capture and certification harness",
            "fail-closed paused load and resume/checkpoint lifecycle"
        ],
        "m3_qma8_artifacts": [
            "uniswap-v3/graft-ancestry/v2/contract.json",
            "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
            "uniswap-v3/segment-writer-matrix/v1/contract.json",
            "uniswap-v3/execution-order/v1/contract.json",
            "uniswap-v3/writer-runtime/contract-v1.json",
            "uniswap-v3/writer-runtime/segment-profiles-v1.json",
            "uniswap-v3/chain-config/configs/mainnet-v1.json"
        ],
        "m3_required_truth": [
            "full Factory and Pool handler/field writer semantics",
            "runtime population and required-absence oracle",
            "boundary continuity and fixed-range logical parity",
            "target Graph Node runtime identity, physical history, VID, PoI, and failure behavior"
        ],
    })
}

fn verify_profile(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
    qma8_reference: &Value,
) -> Result<(), String> {
    let profile_payload = read_bytes(&repository_path(
        root,
        &json!(PROFILE_PATH),
        "Matic layout profile",
    )?)?;
    if profile_payload.len() != EXPECTED_PROFILE_BYTES
        || sha256_hex(&profile_payload) != EXPECTED_PROFILE_SHA256
    {
        return fail("machine-readable Matic layout profile digest drift");
    }
    if *field(lock, "layout_profile")
        != json!({
            "path": PROFILE_PATH,
            "bytes": EXPECTED_PROFILE_BYTES,
            "sha256": EXPECTED_PROFILE_SHA256,
        })
    {
        return fail("Matic layout profile provenance lock drift");
    }
    let profile = load_json(&root.join(PROFILE_PATH))?;
    if !profile.is_object() {
        return fail("Matic layout profile must be an object");
    }
    if *field(&profile, "format_version") != json!(1)
        || *field(&profile, "profile_id") != json!("uniswap-v3-matic-QmWqwrVt")
        || *field(&profile, "status")
            != json!("static_target_layout_and_exact_source_behavior_profile_only")
        || *field(&profile, "implementation_status") != json!("not_started")
        || *field(&profile, "runtime_parity") != json!(false)
        || *field(&profile, "eligibility_decision") != json!("indeterminate_no_fresh_evidence")
        || *field(&profile, "family") != json!("uniswap-v3-matic")
        || *field(&profile, "chain") != json!("matic")
    {
        return fail("Matic layout profile identity or static-only status drift");
    }
    if *field(&profile, "deployment")
        != json!({
            "cid": EXPECTED_DEPLOYMENT,
            "spec_version": "0.0.4",
            "mapping_api_version": "0.0.7",
            "factory_start_block": 22757547,
            "graft": Value::Null,
            "features": ["nonFatalErrors", "grafting"],
        })
    {
        return fail("Matic layout profile deployment contract drift");
    }

    let expected_component_contracts = json!({
        "Factory": {
            "kind": "data_source",
            "address": "0x1f98431c8ad98523631ae4a59f267346ea31f984",
            "start_block": 22757547,
            "mapping_cid": artifact_cid(artifacts, "factory_mapping_wasm")?,
        },
        "Pool": {
            "kind": "template",
            "created_by": "Factory.handlePoolCreated",
            "mapping_cid": artifact_cid(artifacts, "pool_mapping_wasm")?,
        },
    });
    let components = field(&profile, "components").as_array().cloned();
    let components = match components {
        Some(components)
            if components.iter().all(Value::is_object)
                && Value::Array(
                    components
                        .iter()
                        .map(|item| field(item, "name").clone())
                        .collect(),
                ) == json!(["Factory", "Pool"]) =>
        {
            components
        }
        _ => return fail("Matic layout profile component inventory or order drift"),
    };
    for component in &components {
        let name = py_str(field(component, "name"));
        let handlers = field(component, "handlers");
        let contract: Map<String, Value> = component
            .as_object()
            .expect("components are objects")
            .iter()
            .filter(|(key, _)| key.as_str() != "name" && key.as_str() != "handlers")
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        if Value::Object(contract) != *index(&expected_component_contracts, &name)? {
            return fail(format!("Matic profile component contract drift: {name}"));
        }
        let expected = expected_profile_handlers(&name).ok_or_else(|| format!("'{name}'"))?;
        let observed = handlers.as_array().map(|list| {
            Value::Array(
                list.iter()
                    .filter(|handler| handler.is_object())
                    .map(|handler| {
                        json!([
                            field(handler, "name"),
                            field(handler, "signature"),
                            field(handler, "topic0"),
                        ])
                    })
                    .collect(),
            )
        });
        if observed != Some(expected) {
            return fail(format!(
                "Matic profile handler/topic contract drift: {name}"
            ));
        }
    }

    let logical = index(lock, "logical_contract")?;
    if *field(&profile, "entity_layout")
        != json!({
            "entity_count": index(logical, "entity_count")?,
            "logical_sha256": index(logical, "logical_sha256")?,
            "entities": index(logical, "entities")?,
            "immutable_entities": index(logical, "immutable_entities")?,
            "mutable_entities": index(logical, "mutable_entities")?,
            "bytes_id_entities": ["Pool", "Token"],
            "flash_schema_present": true,
            "flash_handler_present": false,
        })
    {
        return fail("Matic profile entity-layout contract drift");
    }
    if *field(&profile, "qma8_deployed_reference")
        != json!({
            "schema_cid": index(qma8_reference, "cid")?,
            "schema_path": index(qma8_reference, "path")?,
            "schema_bytes": index(qma8_reference, "bytes")?,
            "schema_sha256": index(qma8_reference, "sha256")?,
            "entity_count": index(qma8_reference, "entity_count")?,
            "logical_sha256": index(qma8_reference, "logical_sha256")?,
            "immutable_entities": index(qma8_reference, "immutable_entities")?,
            "authority": "retained_deployed_schema_for_entity_field_type_nullability_and_mutability",
            "imported_source_schema_is_mutability_authority": false,
        })
    {
        return fail("Matic profile Qma8 deployed reference drift");
    }
    if *field(&profile, "qma8_static_gap")
        != json!({
            "comparison_direction": "bidirectional_matic_and_retained_qma8_deployed_schema",
            "missing_from_matic": index(logical, "missing_from_matic")?,
            "extra_in_matic": index(logical, "extra_in_matic")?,
            "immutable_in_matic_but_mutable_in_qma8": index(logical, "immutable_in_matic_but_mutable_in_qma8")?,
            "mutable_in_matic_but_immutable_in_qma8": index(logical, "mutable_in_matic_but_immutable_in_qma8")?,
            "exact_field_match_entities": index(logical, "exact_field_match_entities")?,
            "field_differences": index(logical, "field_differences")?,
            "scope": "static_deployed_schema_only_pending_runtime_physical_and_poi_comparison",
        })
    {
        return fail("Matic profile bidirectional Qma8 static gap drift");
    }

    if *field(&profile, "mapping_behavior") != expected_mapping_behavior() {
        return fail("Matic exact-source mapping behavior contract drift");
    }

    let chain = index(index(lock, "exact_source")?, "chain_configuration")?;
    if *field(&profile, "chain_configuration")
        != json!({
            "reference_token": py_str(index(chain, "reference_token")?).to_lowercase(),
            "stable_token_pool": py_str(index(chain, "stable_token_pool")?).to_lowercase(),
            "minimum_native_locked": index(chain, "minimum_native_locked")?,
            "whitelist_tokens": index(chain, "whitelist_tokens")?,
            "stable_coins": index(chain, "stable_coins")?,
            "skip_pools": [],
            "pool_mappings": [],
            "static_token_definitions": [],
        })
    {
        return fail("Matic profile chain configuration drift");
    }

    if *field(&profile, "reuse_assessment") != expected_reuse_assessment() {
        return fail("Matic static reuse assessment drift");
    }
    if *field(&profile, "dependencies") != expected_dependencies() {
        return fail("Matic M2/M3 dependency contract drift");
    }
    if *field(&profile, "required_target_changes") != json!(EXPECTED_REQUIRED_CHANGES) {
        return fail("Matic required target-change inventory drift");
    }
    if *field(&profile, "truth_boundary") != expected_truth_boundary() {
        return fail("Matic profile truth boundary drift");
    }
    if *field(&profile, "remaining_gates") != json!(EXPECTED_REMAINING_GATES) {
        return fail("Matic profile remaining-gate contract drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Exact-source pin
// ---------------------------------------------------------------------------

fn verify_source_pin(lock: &Value, artifacts: &BTreeMap<String, Value>) -> Result<(), String> {
    let source = field(lock, "exact_source");
    if !source.is_object() {
        return fail("exact_source must be an object");
    }
    if *field(source, "status") != json!(EXPECTED_SOURCE_STATUS) {
        return fail("Matic source must remain bound to the exact reproduction");
    }
    if *field(source, "repository") != json!("https://github.com/Uniswap/v3-subgraph") {
        return fail("exact source repository drift");
    }
    if *field(source, "earliest_exact_commit") != json!(EXPECTED_SOURCE_COMMIT) {
        return fail("earliest exact source commit drift");
    }
    if *field(source, "tree") != json!(EXPECTED_SOURCE_TREE) {
        return fail("exact source tree drift");
    }
    for key in [
        "earliest_exact_commit",
        "mainline_equivalent_commit",
        "tree",
    ] {
        let value = source.get(key).cloned().unwrap_or_else(|| json!(""));
        if !is_hex(&value, 40) {
            return fail(format!("invalid exact source {key}"));
        }
    }

    let build = field(source, "build");
    if !build.is_object()
        || *field(build, "result") != json!("byte_exact_to_deployed_mapping_objects")
    {
        return fail("exact source build result drift");
    }
    for (prefix, role) in [
        ("factory", "factory_mapping_wasm"),
        ("pool", "pool_mapping_wasm"),
    ] {
        let record = artifact(artifacts, role)?;
        if *field(build, &format!("{prefix}_wasm_bytes")) != *index(record, "source_bytes")? {
            return fail(format!("{prefix} exact source byte count drift"));
        }
        if *field(build, &format!("{prefix}_wasm_sha256")) != *index(record, "source_sha256")? {
            return fail(format!("{prefix} exact source digest drift"));
        }
    }

    if *field(source, "toolchain")
        != json!({
            "reference_node": "18.18.0",
            "reference_corepack": "0.19.0",
            "yarn": "1.22.22",
            "graph_cli": "0.64.1",
            "graph_ts": "0.38.1",
            "assemblyscript_root": "0.19.23",
            "assemblyscript_graph_ts_nested": "0.27.31",
        })
    {
        return fail("exact source toolchain drift");
    }

    let source_files = match field(source, "source_files").as_array() {
        Some(entries) if entries.len() == 6 => entries.clone(),
        _ => return fail("exact source file lock drift"),
    };
    let declared: BTreeSet<String> = source_files
        .iter()
        .filter(|entry| entry.is_object())
        .map(|entry| py_repr(field(entry, "path")))
        .collect();
    let expected: BTreeSet<String> = [
        "package.json",
        "yarn.lock",
        "script/build.ts",
        "config/matic/chain.ts",
        "config/matic/config.json",
        "src/v3/schema.graphql",
    ]
    .iter()
    .map(|path| py_repr(&json!(path)))
    .collect();
    if declared != expected {
        return fail("exact source file inventory drift");
    }
    for entry in &source_files {
        if !entry.is_object()
            || !field(entry, "path").is_string()
            || !is_integer(field(entry, "bytes"))
            || !is_hex(
                &entry.get("sha256").cloned().unwrap_or_else(|| json!("")),
                64,
            )
        {
            return fail("invalid exact source build-input record");
        }
    }

    let behavior_files = field(source, "behavior_source_files").as_array().cloned();
    let behavior_files = match behavior_files {
        Some(entries)
            if Value::Array(
                entries
                    .iter()
                    .filter(|entry| entry.is_object())
                    .map(|entry| field(entry, "path").clone())
                    .collect(),
            ) == json!(EXPECTED_BEHAVIOR_SOURCE_PATHS) =>
        {
            entries
        }
        _ => return fail("exact source behavior closure inventory or order drift"),
    };
    let behavior_lock_payload = serde_json::to_string(&Value::Array(behavior_files.clone()))
        .map_err(|error| format!("cannot serialize behavior source lock: {error}"))?;
    if sha256_hex(behavior_lock_payload.as_bytes()) != EXPECTED_BEHAVIOR_SOURCE_LOCK_SHA256 {
        return fail("exact source behavior closure lock drift");
    }
    for entry in &behavior_files {
        if !entry.is_object()
            || !is_integer(field(entry, "bytes"))
            || !is_hex(
                &entry.get("sha256").cloned().unwrap_or_else(|| json!("")),
                64,
            )
            || !is_hex(
                &entry.get("git_blob").cloned().unwrap_or_else(|| json!("")),
                40,
            )
        {
            return fail("invalid exact source behavior file record");
        }
    }
    if *field(source, "behavior_source_scope")
        != json!({
            "entrypoints": ["src/v3/mappings/factory.ts", "src/v3/mappings/core.ts"],
            "transitive_local_import_closure_complete": true,
            "generated_bindings_and_node_modules_excluded": true,
            "behavior_claims_require_exact_source_build_match": true,
        })
    {
        return fail("exact source behavior closure scope drift");
    }

    if *field(lock, "truth_boundary") != expected_truth_boundary() {
        return fail("Matic provenance truth boundary drift");
    }
    if *field(lock, "remaining_gates") != json!(EXPECTED_LOCK_REMAINING_GATES) {
        return fail("remaining Matic gates must stay explicit and fail closed");
    }
    Ok(())
}

/// Python `isinstance(value, int)`, which excludes `bool` and floats.
fn is_integer(value: &Value) -> bool {
    value.as_i64().is_some() || value.as_u64().is_some()
}

// ---------------------------------------------------------------------------
// Exact-source build reproduction
// ---------------------------------------------------------------------------

fn manifest_semantic_shape(value: &Value) -> Value {
    match value {
        Value::Object(entries) => Value::Object(
            entries
                .iter()
                .map(|(key, item)| {
                    let shaped = if key == "file" {
                        json!("<content-addressed-artifact>")
                    } else {
                        manifest_semantic_shape(item)
                    };
                    (key.clone(), shaped)
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(manifest_semantic_shape).collect()),
        other => other.clone(),
    }
}

/// `re.findall(r"\bfrom\s+['\"]([^'\"]+)['\"]", payload)`.
fn find_imports(text: &str) -> Vec<String> {
    let bytes = text.as_bytes();
    let mut found = Vec::new();
    let mut position = 0usize;
    while position + 4 <= bytes.len() {
        let boundary = position == 0
            || !(bytes[position - 1].is_ascii_alphanumeric() || bytes[position - 1] == b'_');
        if boundary && &bytes[position..position + 4] == b"from" {
            let mut cursor = position + 4;
            let space = cursor;
            while cursor < bytes.len() && bytes[cursor].is_ascii_whitespace() {
                cursor += 1;
            }
            if cursor > space && cursor < bytes.len() && matches!(bytes[cursor], b'\'' | b'"') {
                let start = cursor + 1;
                let mut end = start;
                while end < bytes.len() && !matches!(bytes[end], b'\'' | b'"') {
                    end += 1;
                }
                if end > start && end < bytes.len() {
                    found.push(text[start..end].to_string());
                    position = end + 1;
                    continue;
                }
            }
        }
        position += 1;
    }
    found
}

/// `posixpath.normpath` for the relative paths this closure walks.
fn posix_normpath(path: &str) -> String {
    let mut parts: Vec<&str> = Vec::new();
    for part in path.split('/') {
        match part {
            "" | "." => {}
            ".." => match parts.last() {
                Some(last) if *last != ".." => {
                    parts.pop();
                }
                _ => parts.push(".."),
            },
            other => parts.push(other),
        }
    }
    if parts.is_empty() {
        ".".to_string()
    } else {
        parts.join("/")
    }
}

/// `pathlib.PurePath(path).suffix`.
fn path_suffix(path: &str) -> &str {
    let name = match path.rsplit_once('/') {
        Some((_, name)) => name,
        None => path,
    };
    match name.rfind('.') {
        Some(dot) if dot > 0 && dot < name.len() - 1 => &name[dot..],
        _ => "",
    }
}

fn exact_behavior_source_closure(
    source_root: &Path,
    entrypoints: &Value,
) -> Result<Vec<String>, String> {
    let entries = entrypoints
        .as_array()
        .ok_or("exact source behavior entrypoints must be a list")?;
    let mut pending: Vec<String> = entries.iter().map(py_str).collect();
    let mut closure: BTreeSet<String> = BTreeSet::new();
    while let Some(current) = pending.pop() {
        if closure.contains(&current) {
            continue;
        }
        let path = repository_path(source_root, &json!(current), "behavior source closure")?;
        let payload = read_text(&path)?;
        closure.insert(current.clone());
        for imported in find_imports(&payload) {
            if !imported.starts_with('.') {
                continue;
            }
            let parent = match current.rsplit_once('/') {
                Some((parent, _)) => parent.to_string(),
                None => String::new(),
            };
            let joined = if parent.is_empty() {
                imported.clone()
            } else {
                format!("{parent}/{imported}")
            };
            let mut resolved = posix_normpath(&joined);
            if path_suffix(&resolved).is_empty() {
                resolved.push_str(".ts");
            }
            if resolved.split('/').any(|part| part == "generated") {
                continue;
            }
            if resolved == "src/common/chain.ts" {
                resolved = "config/matic/chain.ts".to_string();
            }
            if resolved.starts_with("../") {
                return fail(format!(
                    "behavior source import escapes exact source root: {current} -> {imported}"
                ));
            }
            if !closure.contains(&resolved) {
                pending.push(resolved);
            }
        }
    }
    Ok(closure.into_iter().collect())
}

/// `re.subn(rb"@entity\(immutable: (?:true|false)\)", b"@entity", payload)`.
fn normalize_immutable_arguments(payload: &[u8]) -> (Vec<u8>, usize) {
    const PREFIX: &[u8] = b"@entity(immutable: ";
    let mut out = Vec::with_capacity(payload.len());
    let mut replacements = 0usize;
    let mut position = 0usize;
    while position < payload.len() {
        let rest = &payload[position..];
        if rest.starts_with(PREFIX) {
            let tail = &rest[PREFIX.len()..];
            let width = if tail.starts_with(b"true)") {
                Some(5)
            } else if tail.starts_with(b"false)") {
                Some(6)
            } else {
                None
            };
            if let Some(width) = width {
                out.extend_from_slice(b"@entity");
                position += PREFIX.len() + width;
                replacements += 1;
                continue;
            }
        }
        out.push(payload[position]);
        position += 1;
    }
    (out, replacements)
}

const BUILT_ARTIFACTS: [(&str, &str); 7] = [
    ("factory_abi", "build/Factory/abis/factory.json"),
    ("erc20_abi", "build/Factory/abis/ERC20.json"),
    (
        "erc20_symbol_bytes_abi",
        "build/Factory/abis/ERC20SymbolBytes.json",
    ),
    (
        "erc20_name_bytes_abi",
        "build/Factory/abis/ERC20NameBytes.json",
    ),
    ("pool_abi", "build/Factory/abis/pool.json"),
    ("factory_mapping_wasm", "build/Factory/Factory.wasm"),
    ("pool_mapping_wasm", "build/templates/Pool/Pool.wasm"),
];

const INSTALLED_TOOLCHAIN: [(&str, &str); 4] = [
    (
        "graph_cli",
        "node_modules/@graphprotocol/graph-cli/package.json",
    ),
    (
        "graph_ts",
        "node_modules/@graphprotocol/graph-ts/package.json",
    ),
    (
        "assemblyscript_root",
        "node_modules/assemblyscript/package.json",
    ),
    (
        "assemblyscript_graph_ts_nested",
        "node_modules/@graphprotocol/graph-ts/node_modules/assemblyscript/package.json",
    ),
];

fn verify_exact_source_build(
    root: &Path,
    source_root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let source = index(lock, "exact_source")?;
    let closure = exact_behavior_source_closure(
        source_root,
        index(index(source, "behavior_source_scope")?, "entrypoints")?,
    )?;
    if closure != EXPECTED_BEHAVIOR_SOURCE_PATHS {
        return fail("computed exact source behavior import closure drift");
    }
    for record in index(source, "source_files")?
        .as_array()
        .ok_or("exact source build inputs must be a list")?
    {
        let declared = index(record, "path")?;
        let payload = read_bytes(&repository_path(
            source_root,
            declared,
            "exact source input",
        )?)?;
        if json!(payload.len()) != *index(record, "bytes")?
            || json!(sha256_hex(&payload)) != *index(record, "sha256")?
        {
            return fail(format!(
                "exact source build-input drift: {}",
                py_str(declared)
            ));
        }
        if let Some(git_blob) = record.get("git_blob") {
            if json!(git_blob_hash(&payload)) != *git_blob {
                return fail(format!(
                    "exact source build-input Git blob drift: {}",
                    py_str(declared)
                ));
            }
        }
    }
    for record in index(source, "behavior_source_files")?
        .as_array()
        .ok_or("exact source behavior closure must be a list")?
    {
        let declared = index(record, "path")?;
        let payload = read_bytes(&repository_path(source_root, declared, "behavior source")?)?;
        if json!(payload.len()) != *index(record, "bytes")?
            || json!(sha256_hex(&payload)) != *index(record, "sha256")?
            || json!(git_blob_hash(&payload)) != *index(record, "git_blob")?
        {
            return fail(format!(
                "exact source behavior closure drift: {}",
                py_str(declared)
            ));
        }
    }

    let deployed_manifest = read_yaml(&repository_path(
        root,
        field(artifact(artifacts, "deployment")?, "vendored_path"),
        "Matic manifest",
    )?)?;
    let built_manifest = read_yaml(&repository_path(
        source_root,
        &json!("build/subgraph.yaml"),
        "built Matic manifest",
    )?)?;
    if manifest_semantic_shape(&built_manifest) != manifest_semantic_shape(&deployed_manifest) {
        return fail(
            "exact source generated manifest is not semantically identical to the deployment",
        );
    }

    let deployed_schema = read_bytes(&repository_path(
        root,
        field(artifact(artifacts, "schema")?, "vendored_path"),
        "Matic schema",
    )?)?;
    let (normalized_schema, replacements) = normalize_immutable_arguments(&deployed_schema);
    let normalization = index(source, "schema_normalization")?;
    if json!(replacements) != *index(normalization, "remove_explicit_immutable_arguments")? {
        return fail("deployed schema immutable-argument normalization drift");
    }
    if json!(normalized_schema.len()) != *index(normalization, "source_bytes")? {
        return fail("normalized exact source schema byte count drift");
    }
    if json!(sha256_hex(&normalized_schema)) != *index(normalization, "source_sha256")? {
        return fail("normalized exact source schema digest drift");
    }
    for schema_path in ["src/v3/schema.graphql", "build/schema.graphql"] {
        let payload = read_bytes(&repository_path(
            source_root,
            &json!(schema_path),
            "exact source schema",
        )?)?;
        if payload != normalized_schema {
            return fail(format!("exact source schema mismatch: {schema_path}"));
        }
    }

    for (role, relative_path) in BUILT_ARTIFACTS {
        let record = artifact(artifacts, role)?;
        let payload = read_bytes(&repository_path(source_root, &json!(relative_path), role)?)?;
        if json!(payload.len()) != *index(record, "source_bytes")? {
            return fail(format!("exact source build byte count drift for {role}"));
        }
        if json!(sha256_hex(&payload)) != *index(record, "source_sha256")? {
            return fail(format!("exact source build digest drift for {role}"));
        }
    }

    let mut installed = Vec::new();
    for (key, relative_path) in INSTALLED_TOOLCHAIN {
        let manifest = load_json(&source_root.join(relative_path))?;
        installed.push((key, index(&manifest, "version")?.clone()));
    }
    let toolchain = index(source, "toolchain")?;
    for (key, value) in installed {
        if value != *index(toolchain, key)? {
            return fail(format!("installed exact source toolchain drift: {key}"));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Deployment binding
// ---------------------------------------------------------------------------

fn verify_binding(root: &Path) -> Result<(), String> {
    let binding = read_yaml(&root.join(BINDING_PATH))?;
    let leaked = match binding.as_object() {
        Some(entries) => entries.keys().any(|name| {
            name != "market_snapshot"
                && (name.starts_with("market_")
                    || name.starts_with("qos_")
                    || name.starts_with("query_fee")
                    || name.contains("grt")
                    || matches!(
                        name.as_str(),
                        "queries_24h" | "query_count_24h" | "fees_24h"
                    ))
        }),
        None => false,
    };
    let latest = field(field(&binding, "eligibility"), "latest");
    if !binding.is_object()
        || *field(&binding, "deployment") != json!(EXPECTED_DEPLOYMENT)
        || *field(&binding, "family") != json!("uniswap-v3-matic")
        || *field(&binding, "chain") != json!("matic")
        || *field(&binding, "milestone") != json!("M4")
        || *field(&binding, "market_snapshot") != expected_market_snapshot()
        || leaked
        || *field(latest, "decision") != json!("indeterminate")
        || *field(latest, "reason") != json!("no_fresh_evidence")
    {
        return fail("Matic binding, M4 market snapshot, or fail-closed eligibility drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

/// Verify the pinned Uniswap V3 Matic target under `root`. `lock` is relative
/// to `root`; `exact_source_root` enables the exact-source reproduction checks.
pub fn verify(
    root: &Path,
    lock: &Path,
    exact_source_root: Option<&Path>,
) -> Result<String, String> {
    let lock_value = load_json(&root.join(lock))?;
    if !lock_value.is_object() || *field(&lock_value, "format_version") != json!(1) {
        return fail("unsupported Matic target lock");
    }
    let deployment = field(&lock_value, "deployment");
    if !deployment.is_object() || *field(deployment, "cid") != json!(EXPECTED_DEPLOYMENT) {
        return fail("deployment identity drift");
    }
    let artifacts = verify_artifact_lock(root, &lock_value)?;
    verify_manifest(root, &lock_value, &artifacts)?;
    let qma8_reference = verify_qma8_reference(root, &lock_value)?;
    verify_schema(root, &lock_value, &artifacts, &qma8_reference)?;
    verify_profile(root, &lock_value, &artifacts, &qma8_reference)?;
    verify_source_pin(&lock_value, &artifacts)?;
    verify_binding(root)?;
    if let Some(source_root) = exact_source_root {
        let resolved = source_root
            .canonicalize()
            .map_err(|error| format!("cannot resolve {}: {error}", source_root.display()))?;
        verify_exact_source_build(root, &resolved, &lock_value, &artifacts)?;
    }
    Ok(
        "verified immutable Matic deployment/schema/ABI artifacts, exact manifest shape, \
         retained Qma8 closure, bidirectional layout gap, exact-source behavior/reuse \
         profile, false readiness gates, and the exact source/toolchain reproduction"
            .to_string(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    const SUCCESS: &str = "verified immutable Matic deployment/schema/ABI artifacts, exact manifest shape, retained Qma8 closure, bidirectional layout gap, exact-source behavior/reuse profile, false readiness gates, and the exact source/toolchain reproduction";

    const QMA8_REFERENCE_FILES: [&str; 12] = [
        "uniswap-v3/graft-ancestry/v1/artifacts/Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru",
        "docs/provenance/uniswap-v3-qma8a81t-parity.json",
        "docs/provenance/uniswap-v3-qma8a81t-parity-files.json",
        "uniswap-v3/source/schema.graphql",
        "uniswap-v3/source/substreams.yaml",
        "uniswap-v3/graft-ancestry/v2/contract.json",
        "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
        "uniswap-v3/segment-writer-matrix/v1/contract.json",
        "uniswap-v3/execution-order/v1/contract.json",
        "uniswap-v3/writer-runtime/contract-v1.json",
        "uniswap-v3/writer-runtime/segment-profiles-v1.json",
        "uniswap-v3/chain-config/configs/mainnet-v1.json",
    ];

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    fn copy_tree(source: &Path, destination: &Path) {
        std::fs::create_dir_all(destination).expect("create directory");
        for entry in std::fs::read_dir(source).expect("read directory") {
            let entry = entry.expect("directory entry");
            let target = destination.join(entry.file_name());
            if entry.file_type().expect("file type").is_dir() {
                copy_tree(&entry.path(), &target);
            } else {
                std::fs::copy(entry.path(), &target).expect("copy file");
            }
        }
    }

    fn write(path: &Path, contents: &str) {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).expect("create parent");
        }
        std::fs::write(path, contents).expect("write file");
    }

    /// A writable copy of the pinned Matic family plus everything the verifier
    /// reads outside it, mirroring the Python test's `setUp`.
    struct Fixture {
        _temporary: tempfile::TempDir,
        root: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let temporary = tempfile::tempdir().expect("temporary directory");
            let root = temporary.path().to_path_buf();
            copy_tree(
                &repository().join("uniswap-v3-matic"),
                &root.join("uniswap-v3-matic"),
            );
            for relative in QMA8_REFERENCE_FILES {
                let destination = root.join(relative);
                std::fs::create_dir_all(destination.parent().expect("parent"))
                    .expect("create parent");
                std::fs::copy(repository().join(relative), &destination).expect("copy reference");
            }
            let lock = root.join(LOCK_PATH);
            std::fs::create_dir_all(lock.parent().expect("parent")).expect("create parent");
            std::fs::copy(repository().join(LOCK_PATH), &lock).expect("copy lock");
            Self {
                _temporary: temporary,
                root,
            }
        }

        fn verify(&self) -> Result<String, String> {
            super::verify(&self.root, Path::new(LOCK_PATH), None)
        }

        fn path(&self, relative: &str) -> PathBuf {
            self.root.join(relative)
        }

        fn rewrite(&self, relative: &str, from: &str, to: &str) {
            let path = self.path(relative);
            let text = std::fs::read_to_string(&path).expect("read file");
            let replaced = text.replacen(from, to, 1);
            assert_ne!(text, replaced, "fixture rewrite matched nothing: {from}");
            std::fs::write(&path, replaced).expect("write file");
        }

        fn load(&self, relative: &str) -> Value {
            serde_json::from_str(&std::fs::read_to_string(self.path(relative)).expect("read json"))
                .expect("parse json")
        }

        fn store(&self, relative: &str, value: &Value) {
            write(
                &self.path(relative),
                &(serde_json::to_string_pretty(value).expect("serialize") + "\n"),
            );
        }

        fn load_lock(&self) -> Value {
            self.load(LOCK_PATH)
        }

        fn write_lock(&self, lock: &Value) {
            self.store(LOCK_PATH, lock);
        }

        fn load_profile(&self) -> Value {
            self.load(PROFILE_PATH)
        }

        fn write_profile(&self, profile: &Value) {
            self.store(PROFILE_PATH, profile);
        }

        fn relock_profile(&self) {
            let payload = std::fs::read(self.path(PROFILE_PATH)).expect("read profile");
            let mut lock = self.load_lock();
            lock["layout_profile"]["bytes"] = json!(payload.len());
            lock["layout_profile"]["sha256"] = json!(sha256_hex(&payload));
            self.write_lock(&lock);
        }

        fn relock_qma8_reference(&self, role: &str) {
            let mut lock = self.load_lock();
            let pointer = if role == "deployed_schema" {
                "/qma8_reference/deployed_schema".to_string()
            } else {
                let find = |list: &str| {
                    lock.pointer(list)
                        .and_then(Value::as_array)
                        .and_then(|records| {
                            records
                                .iter()
                                .position(|record| record["role"] == json!(role))
                        })
                        .map(|position| format!("{list}/{position}"))
                };
                find("/qma8_reference/upstream_source/records")
                    .or_else(|| find("/qma8_reference/m3_contract_closure"))
                    .expect("role is locked")
            };
            let relative = lock.pointer(&pointer).expect("record")["path"]
                .as_str()
                .expect("path")
                .to_string();
            let payload = std::fs::read(self.path(&relative)).expect("read record");
            let record = lock.pointer_mut(&pointer).expect("record");
            record["bytes"] = json!(payload.len());
            record["sha256"] = json!(sha256_hex(&payload));
            self.write_lock(&lock);
        }

        fn relock_artifact(&self, role: &str) {
            let mut lock = self.load_lock();
            let position = lock["artifact_lock"]
                .as_array()
                .expect("artifact lock")
                .iter()
                .position(|record| record["role"] == json!(role))
                .expect("role is locked");
            let relative = lock["artifact_lock"][position]["vendored_path"]
                .as_str()
                .expect("vendored path")
                .to_string();
            let payload = std::fs::read(self.path(&relative)).expect("read artifact");
            let digest = sha256_hex(&payload);
            let record = &mut lock["artifact_lock"][position];
            record["source_bytes"] = json!(payload.len());
            record["vendored_bytes"] = json!(payload.len());
            record["source_sha256"] = json!(digest);
            record["vendored_sha256"] = json!(digest);
            self.write_lock(&lock);
        }
    }

    #[test]
    fn exact_baseline_passes() {
        assert_eq!(Fixture::new().verify(), Ok(SUCCESS.to_string()));
    }

    #[test]
    fn repository_baseline_passes() {
        assert_eq!(
            super::verify(&repository(), Path::new(LOCK_PATH), None),
            Ok(SUCCESS.to_string())
        );
    }

    #[test]
    fn artifact_byte_drift_is_rejected() {
        let fixture = Fixture::new();
        fixture.rewrite(
            "uniswap-v3-matic/reference/schema.graphql",
            "type Bundle",
            "type BundleDrift",
        );
        assert_eq!(
            fixture.verify(),
            Err("vendored byte count drift for schema".into())
        );
    }

    #[test]
    fn market_snapshot_contract_drift_is_rejected() {
        let fixture = Fixture::new();
        fixture.rewrite(
            "uniswap-v3-matic/QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3.yaml",
            "chain: matic",
            "chain: matic\ngrt_24h: \"471.970\"",
        );
        assert_eq!(
            fixture.verify(),
            Err("Matic binding, M4 market snapshot, or fail-closed eligibility drift".into())
        );
    }

    #[test]
    fn semantic_manifest_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.rewrite(
            "uniswap-v3-matic/reference/deployment.yaml",
            "network: matic",
            "network: mainnet",
        );
        fixture.relock_artifact("deployment");
        assert_eq!(
            fixture.verify(),
            Err("Factory data-source identity drift".into())
        );
    }

    #[test]
    fn retained_qma8_deployed_mutability_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.rewrite(
            QMA8_REFERENCE_FILES[0],
            "type Transaction @entity {",
            "type Transaction @entity(immutable: true) {",
        );
        fixture.relock_qma8_reference("deployed_schema");
        assert_eq!(
            fixture.verify(),
            Err("retained Qma8 deployed-schema identity drift".into())
        );
    }

    #[test]
    fn qma8_upstream_schema_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.rewrite(
            "uniswap-v3/source/schema.graphql",
            "type Position ",
            "type PositionDrift ",
        );
        fixture.relock_qma8_reference("imported_schema");
        assert_eq!(
            fixture.verify(),
            Err("Qma8 upstream inventory or lock drift".into())
        );
    }

    #[test]
    fn m3_contract_promotion_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        let relative = "uniswap-v3/writer-runtime/contract-v1.json";
        let mut contract = fixture.load(relative);
        contract["truth_boundary"]["production_ready"] = json!(true);
        fixture.store(relative, &contract);
        fixture.relock_qma8_reference("writer_runtime");
        assert_eq!(
            fixture.verify(),
            Err("Qma8 M3 closure inventory or lock drift".into())
        );
    }

    #[test]
    fn bidirectional_nullability_gap_drift_is_rejected_after_profile_relock() {
        let fixture = Fixture::new();
        let mut profile = fixture.load_profile();
        profile["qma8_static_gap"]["field_differences"]["Tick"]["type_differences"]
            ["poolAddress"]["qma8_non_null"] = json!(true);
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_eq!(
            fixture.verify(),
            Err("machine-readable Matic layout profile digest drift".into())
        );
    }

    #[test]
    fn collect_behavior_drift_is_rejected_after_profile_relock() {
        let fixture = Fixture::new();
        let mut profile = fixture.load_profile();
        profile["mapping_behavior"]["collect"]["pool_and_token_tvl_delta"] = json!("none");
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_eq!(
            fixture.verify(),
            Err("machine-readable Matic layout profile digest drift".into())
        );
    }

    #[test]
    fn uncertified_reuse_promotion_is_rejected_after_profile_relock() {
        let fixture = Fixture::new();
        let mut profile = fixture.load_profile();
        profile["reuse_assessment"]["certified_unchanged"] = json!(["store_tokens"]);
        profile["reuse_assessment"]["reuse_certified"] = json!(true);
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_eq!(
            fixture.verify(),
            Err("machine-readable Matic layout profile digest drift".into())
        );
    }

    #[test]
    fn runtime_gate_promotion_is_rejected_after_profile_relock() {
        let fixture = Fixture::new();
        let mut profile = fixture.load_profile();
        profile["truth_boundary"]["runtime_parity"] = json!(true);
        profile["runtime_parity"] = json!(true);
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_eq!(
            fixture.verify(),
            Err("machine-readable Matic layout profile digest drift".into())
        );
    }

    #[test]
    fn provenance_gate_promotion_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["truth_boundary"]["physical_profile_complete"] = json!(true);
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("Matic provenance truth boundary drift".into())
        );
    }

    #[test]
    fn behavior_source_closure_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["exact_source"]["behavior_source_files"][0]["sha256"] = json!("0".repeat(64));
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("exact source behavior closure lock drift".into())
        );
    }

    #[test]
    fn exact_source_status_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["exact_source"]["status"] = json!("candidate");
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("Matic source must remain bound to the exact reproduction".into())
        );
    }

    #[test]
    fn exact_source_output_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["exact_source"]["build"]["factory_wasm_sha256"] = json!("0".repeat(64));
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("factory exact source digest drift".into())
        );
    }

    // -- checks the Python suite never exercised ----------------------------

    #[test]
    fn exact_source_root_with_a_short_closure_is_rejected() {
        let fixture = Fixture::new();
        let source = tempfile::tempdir().expect("temporary directory");
        write(
            &source.path().join("src/v3/mappings/factory.ts"),
            "import { handleSwap } from './core'\n",
        );
        write(
            &source.path().join("src/v3/mappings/core.ts"),
            "export {}\n",
        );
        assert_eq!(
            super::verify(&fixture.root, Path::new(LOCK_PATH), Some(source.path())),
            Err("computed exact source behavior import closure drift".into())
        );
    }

    /// The 17 locked behavior paths, wired as the real tree wires them: one
    /// entrypoint importing its siblings, the shared helpers, the `chain.ts`
    /// alias that resolves to the Matic config, and a generated binding that
    /// the closure must skip.
    fn synthetic_source_tree(source: &Path) {
        let mut factory = String::new();
        for sibling in [
            "burn",
            "collect",
            "core",
            "initialize",
            "intervalUpdates",
            "mint",
            "swap",
            "tick",
            "utils",
        ] {
            factory.push_str(&format!("import {{ a }} from './{sibling}'\n"));
        }
        for shared in [
            "backfill",
            "constants",
            "pricing",
            "staticTokenDefinition",
            "token",
            "utils",
        ] {
            factory.push_str(&format!("import {{ b }} from '../../common/{shared}'\n"));
        }
        factory.push_str("import { c } from '../../common/chain'\n");
        factory.push_str("import { Pool } from '../../types/generated/schema'\n");
        for relative in EXPECTED_BEHAVIOR_SOURCE_PATHS {
            let body = if relative == "src/v3/mappings/factory.ts" {
                factory.as_str()
            } else {
                "export {}\n"
            };
            write(&source.join(relative), body);
        }
    }

    #[test]
    fn synthetic_source_tree_reproduces_the_locked_behavior_closure() {
        let source = tempfile::tempdir().expect("temporary directory");
        synthetic_source_tree(source.path());
        assert_eq!(
            exact_behavior_source_closure(
                source.path(),
                &json!(["src/v3/mappings/factory.ts", "src/v3/mappings/core.ts"])
            ),
            Ok(EXPECTED_BEHAVIOR_SOURCE_PATHS
                .iter()
                .map(|path| (*path).to_string())
                .collect::<Vec<String>>())
        );
    }

    #[test]
    fn exact_source_build_inputs_are_digest_checked() {
        let fixture = Fixture::new();
        let source = tempfile::tempdir().expect("temporary directory");
        synthetic_source_tree(source.path());
        for relative in [
            "package.json",
            "yarn.lock",
            "script/build.ts",
            "config/matic/config.json",
            "src/v3/schema.graphql",
        ] {
            write(&source.path().join(relative), "drift\n");
        }
        assert_eq!(
            super::verify(&fixture.root, Path::new(LOCK_PATH), Some(source.path())),
            Err("exact source build-input drift: package.json".into())
        );
    }

    #[test]
    fn schema_normalization_matches_the_locked_exact_source_digest() {
        let deployed =
            std::fs::read(repository().join("uniswap-v3-matic/reference/schema.graphql"))
                .expect("read schema");
        let (normalized, replacements) = normalize_immutable_arguments(&deployed);
        let lock = load_json(&repository().join(LOCK_PATH)).expect("load lock");
        let normalization = &lock["exact_source"]["schema_normalization"];
        assert_eq!(
            json!(replacements),
            normalization["remove_explicit_immutable_arguments"]
        );
        assert_eq!(json!(normalized.len()), normalization["source_bytes"]);
        assert_eq!(
            json!(sha256_hex(&normalized)),
            normalization["source_sha256"]
        );
    }

    #[test]
    fn manifest_semantic_shape_erases_content_addresses() {
        let manifest = read_yaml(&repository().join("uniswap-v3-matic/reference/deployment.yaml"))
            .expect("read manifest");
        let shaped = manifest_semantic_shape(&manifest);
        assert_ne!(shaped, manifest);
        assert_eq!(
            shaped["schema"]["file"],
            json!("<content-addressed-artifact>")
        );
        let mut relabelled = manifest.clone();
        relabelled["schema"]["file"]["/"] = json!("/ipfs/QmDifferentCidEntirely");
        assert_eq!(manifest_semantic_shape(&relabelled), shaped);
    }

    #[test]
    fn behavior_import_escaping_the_source_root_is_rejected() {
        let source = tempfile::tempdir().expect("temporary directory");
        write(
            &source.path().join("src/v3/mappings/factory.ts"),
            "import { x } from \"../../../../outside\"\n",
        );
        assert_eq!(
            exact_behavior_source_closure(source.path(), &json!(["src/v3/mappings/factory.ts"])),
            Err(
                "behavior source import escapes exact source root: src/v3/mappings/factory.ts -> ../../../../outside"
                    .into()
            )
        );
    }

    #[test]
    fn behavior_closure_skips_generated_bindings_and_remaps_the_chain_config() {
        let source = tempfile::tempdir().expect("temporary directory");
        write(
            &source.path().join("src/v3/mappings/factory.ts"),
            "import { Pool } from '../../types/generated/schema'\nimport { WETH } from '../../common/chain'\n",
        );
        write(&source.path().join("config/matic/chain.ts"), "export {}\n");
        assert_eq!(
            exact_behavior_source_closure(source.path(), &json!(["src/v3/mappings/factory.ts"])),
            Ok(vec![
                "config/matic/chain.ts".to_string(),
                "src/v3/mappings/factory.ts".to_string(),
            ])
        );
    }

    #[test]
    fn repository_paths_must_stay_inside_the_root() {
        let root = tempfile::tempdir().expect("temporary directory");
        assert_eq!(
            repository_path(root.path(), &json!("../escape"), "probe"),
            Err("invalid repository path for probe: '../escape'".into())
        );
        assert_eq!(
            repository_path(root.path(), &json!("/etc/passwd"), "probe"),
            Err("invalid repository path for probe: '/etc/passwd'".into())
        );
        assert_eq!(
            repository_path(root.path(), &Value::Null, "probe"),
            Err("invalid repository path for probe: None".into())
        );
        assert_eq!(
            repository_path(root.path(), &json!("."), "probe"),
            Err("repository path escapes root for probe: .".into())
        );
        assert!(repository_path(root.path(), &json!("docs/a.json"), "probe").is_ok());
    }

    #[test]
    fn duplicate_json_keys_are_rejected() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let path = directory.path().join("duplicate.json");
        write(&path, "{\"a\": 1, \"b\": {\"c\": 2, \"c\": 3}}");
        assert_eq!(
            load_json(&path),
            Err(format!("duplicate JSON key in {}: c", path.display()))
        );
    }

    #[test]
    fn helpers_match_their_python_originals() {
        assert_eq!(
            posix_normpath("src/v3/mappings/../common/utils"),
            "src/v3/common/utils"
        );
        assert_eq!(posix_normpath("a/../../b"), "../b");
        assert_eq!(posix_normpath("./a/./b"), "a/b");
        assert_eq!(posix_normpath(""), ".");
        assert_eq!(path_suffix("config/matic/config.json"), ".json");
        assert_eq!(path_suffix("src/common/utils"), "");
        assert_eq!(path_suffix("src/common/.hidden"), "");
        assert_eq!(
            find_imports("import { a } from './core'\nexport * from \"../x\"\nnotfrom 'y'\n"),
            vec!["./core".to_string(), "../x".to_string()]
        );
        assert_eq!(
            normalize_immutable_arguments(b"type A @entity(immutable: true) {\ntype B @entity {"),
            (b"type A @entity {\ntype B @entity {".to_vec(), 1)
        );
        assert_eq!(
            py_repr(&json!({"a": [1, true, null]})),
            "{'a': [1, True, None]}"
        );
        assert_eq!(py_str(&json!(false)), "False");
        assert_eq!(
            normalize_source_bytes(b"{}\n", "remove_one_trailing_lf"),
            Ok(b"{}".to_vec())
        );
        assert_eq!(
            normalize_source_bytes(b"{}\n\n", "remove_one_trailing_lf"),
            Err("ABI normalization requires exactly one vendored trailing LF".into())
        );
        assert_eq!(
            normalize_source_bytes(b"{}", "gzip"),
            Err("unknown normalization: gzip".into())
        );
        assert_eq!(
            cid_from_file(&json!({"/": "/ipfs/QmAbc"})),
            Ok("QmAbc".to_string())
        );
        assert_eq!(
            cid_from_file(&json!({"/": "bafy"})),
            Err("unexpected IPFS location: 'bafy'".into())
        );
    }
}
