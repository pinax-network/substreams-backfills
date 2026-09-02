//! Verify the immutable Exchange V3 BSC target and exact-source contract.
//!
//! Fail-closed Rust port of the retired `scripts/verify-exchange-v3-bsc-target.py` (#110).
//! Every Python `fail(...)` becomes an `Err` carrying the same text, and every
//! I/O, JSON, or YAML error is surfaced as an `Err` rather than a panic.

use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Component, Path, PathBuf};

use serde::de::{DeserializeSeed, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{json, Map, Value};

use crate::target_common::{
    cid_from_file, git_blob_hash, logical_hash, normalize_event, read_yaml, sha256_hex,
    unixfs_file_cidv0,
};

pub const LOCK_PATH: &str = "docs/provenance/exchange-v3-bsc-target.json";
const PROFILE_PATH: &str = "exchange-v3-bsc/layout-profile-v1.json";
const BINDING_PATH: &str = "exchange-v3-bsc/QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn.yaml";
const EXPECTED_DEPLOYMENT: &str = "QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn";
const EXPECTED_SCHEMA: &str = "QmP9xqULGJzQE7SFKyzkgD8LEkjoy1aChCJnbNkCT4VDRi";
const EXPECTED_SOURCE_COMMIT: &str = "1da7ba61abb26633ff819ce8cdfe945be8770a92";
const EXPECTED_SOURCE_TREE: &str = "a2a113c9eedd7ed0e6fdcaea275153233223c95d";
const EXPECTED_SOURCE_PARENT: &str = "e2019f716f4310f4ce28addc4439980804d9e413";
const EXPECTED_PROFILE_BYTES: u64 = 10851;
const EXPECTED_PROFILE_SHA256: &str =
    "c59a680bd09958d1397872280451750b7f650fd78093b99c99fb135310c29af1";

/// The exact success line the Python verifier prints.
pub const SUCCESS_LINE: &str = "verified all eleven Exchange V3 CIDv0 artifacts, legacy manifest \
and 20-entity mutable schema, implementation-gap profile, exact source commit/tree/parent and \
toolchain reproduction, and fail-closed M6 binding";

const EXPECTED_M0_GATE: &str = "M0: fully account for both required clusters by inventorying \
every current copy or fresh structural absence proof; when viable healthy copies exist, \
independently select the minimum stable same-pod 24-hour ETA and minimum stable same-pod \
72-hour ETA across all viable copies, which may be different copies, and require both minima \
to exceed 28 days or be non-converging; either minimum at or below 28 days stops \
implementation, compute, and load; with no viable copy, require fresh structural \
absence proof from both clusters.";

const EXPECTED_PROFILE_REMAINING_GATES: [&str; 4] = [
    EXPECTED_M0_GATE,
    "generic_loader_legacy_spec_0_0_2_physical_schema_and_metadata_proof",
    "certified_uniswap_v3_runtime_functional_gap_after_issues_5_and_9",
    "paused_restore_differential_validation_and_separate_operational_activation_approval",
];

const EXPECTED_LOCK_REMAINING_GATES: [&str; 4] = [
    EXPECTED_M0_GATE,
    "Prove the generic loader handles spec-0.0.2-derived physical schema and metadata.",
    "Complete the certified runtime functional gap after issues 5 and 9.",
    "Produce a paused differential certificate and obtain separate operational approval before activation.",
];

type HandlerContract = (&'static str, &'static str, &'static str);

const EXPECTED_PROFILE_HANDLERS: [(&str, &[HandlerContract]); 3] = [
    (
        "Factory",
        &[(
            "handlePoolCreated",
            "PoolCreated(address,address,uint24,int24,address)",
            "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
        )],
    ),
    (
        "NonfungiblePositionManager",
        &[
            (
                "handleIncreaseLiquidity",
                "IncreaseLiquidity(uint256,uint128,uint256,uint256)",
                "0x3067048beee31b25b2f1681f88dac838c8bba36af25bfb2b7cf7473a5847e35f",
            ),
            (
                "handleDecreaseLiquidity",
                "DecreaseLiquidity(uint256,uint128,uint256,uint256)",
                "0x26f6a048ee9138f2c0ce266f322cb99228e8d619ae2bff30c67f8dcf9d2377b4",
            ),
            (
                "handleCollect",
                "Collect(uint256,address,uint256,uint256)",
                "0x40d0efd1a53d60ecbf40971b9daf7dc90178c3aadc7aab1765632738fa8b8f01",
            ),
            (
                "handleTransfer",
                "Transfer(address,address,uint256)",
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            ),
        ],
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
                "Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)",
                "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83",
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
                "handleFlash",
                "Flash(address,address,uint256,uint256,uint256,uint256)",
                "0xbdbdb71d7860376ba52b25a5028beea23581364a40522f6bcfb86bb1f2dca633",
            ),
            (
                "handleCollect",
                "Collect(address,address,int24,int24,uint128,uint128)",
                "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0",
            ),
            (
                "handleCollectProtocol",
                "CollectProtocol(address,address,uint128,uint128)",
                "0x596b573906218d3411850b26a6b437d6c4522fdb43d2d2386263f86d50b8b151",
            ),
        ],
    ),
];

const EXPECTED_REQUIRED_CHANGES: [&str; 10] = [
    "profile_driven_legacy_spec_0_0_2_physical_schema_and_metadata_support",
    "bsc_factory_position_manager_and_dynamic_pool_component_routing",
    "pancake_swap_decoder_with_two_protocol_fee_amounts",
    "packed_fee_protocol_defaults_and_collect_protocol_semantics",
    "all_mutable_twenty_entity_layout_and_pancake_day_aggregate",
    "protocol_fee_fields_aggregates_and_source_compatibility_quirks",
    "bsc_pricing_stable_pool_whitelist_and_minimum_liquidity_configuration",
    "target_specific_packages_module_hashes_and_initial_blocks",
    "bsc_canonical_event_metadata_and_reducer_fixtures",
    "exact_graph_node_schema_poi_vid_and_postgresql_parity_certification",
];

fn fail<T>(message: impl Into<String>) -> Result<T, String> {
    Err(message.into())
}

/// `value[key]`; a missing key mirrors the Python `KeyError` text.
fn index<'a>(value: &'a Value, key: &str) -> Result<&'a Value, String> {
    value.get(key).ok_or_else(|| format!("'{key}'"))
}

/// `repr(value)` for the messages that interpolate `{value!r}`.
fn py_repr(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => "None".to_string(),
        Some(Value::Bool(true)) => "True".to_string(),
        Some(Value::Bool(false)) => "False".to_string(),
        Some(Value::String(text)) => format!("'{text}'"),
        Some(other) => other.to_string(),
    }
}

/// `str(value)` for the checks the Python performs on stringified JSON.
fn py_str(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => "None".to_string(),
        Some(Value::Bool(true)) => "True".to_string(),
        Some(Value::Bool(false)) => "False".to_string(),
        Some(Value::String(text)) => text.clone(),
        Some(other) => other.to_string(),
    }
}

fn is_lowercase_hex(text: &str, length: usize) -> bool {
    text.len() == length
        && text
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// Python's `int == number` comparison against a byte or entity count.
fn equals_number(value: Option<&Value>, expected: u64) -> bool {
    match value {
        Some(Value::Number(number)) => number.as_f64() == Some(expected as f64),
        _ => false,
    }
}

fn contains_bytes(haystack: &[u8], needle: &[u8]) -> bool {
    needle.is_empty()
        || haystack
            .windows(needle.len())
            .any(|window| window == needle)
}

fn read_bytes(path: &Path) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_text(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))
}

// ---------------------------------------------------------------------------
// JSON loading that rejects duplicate keys, matching the Python
// `object_pairs_hook`. `serde_json` keeps the last duplicate silently.
// ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
struct UniqueKeys<'a> {
    duplicate: &'a RefCell<Option<String>>,
}

impl<'de> DeserializeSeed<'de> for UniqueKeys<'_> {
    type Value = Value;

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        deserializer.deserialize_any(self)
    }
}

impl<'de> Visitor<'de> for UniqueKeys<'_> {
    type Value = Value;

    fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        formatter.write_str("any JSON value")
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

    fn visit_unit<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_none<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_some<D: Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        deserializer.deserialize_any(self)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut access: A) -> Result<Value, A::Error> {
        let mut items = Vec::new();
        while let Some(item) = access.next_element_seed(self)? {
            items.push(item);
        }
        Ok(Value::Array(items))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut access: A) -> Result<Value, A::Error> {
        let mut entries = Map::new();
        while let Some(key) = access.next_key::<String>()? {
            let value = access.next_value_seed(self)?;
            if entries.insert(key.clone(), value).is_some() && self.duplicate.borrow().is_none() {
                *self.duplicate.borrow_mut() = Some(key);
            }
        }
        Ok(Value::Object(entries))
    }
}

fn load_json(path: &Path) -> Result<Value, String> {
    let text = read_text(path)?;
    let duplicate = RefCell::new(None);
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let value = UniqueKeys {
        duplicate: &duplicate,
    }
    .deserialize(&mut deserializer)
    .map_err(|error| format!("cannot parse {}: {error}", path.display()))?;
    deserializer
        .end()
        .map_err(|error| format!("cannot parse {}: {error}", path.display()))?;
    if let Some(key) = duplicate.into_inner() {
        return fail(format!("duplicate JSON key in {}: {key}", path.display()));
    }
    Ok(value)
}

// ---------------------------------------------------------------------------
// Artifacts
// ---------------------------------------------------------------------------

/// `Path.resolve()` without requiring the target to exist: canonicalize when
/// possible, otherwise normalize `.` and `..` lexically.
fn resolve(path: &Path) -> PathBuf {
    if let Ok(canonical) = path.canonicalize() {
        return canonical;
    }
    let mut resolved = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            other => resolved.push(other.as_os_str()),
        }
    }
    resolved
}

fn verify_artifacts(root: &Path, lock: &Value) -> Result<BTreeMap<String, Value>, String> {
    let Some(records) = lock.get("artifact_lock").and_then(Value::as_array) else {
        return fail("artifact_lock must be a list");
    };

    let mut by_role: BTreeMap<String, Value> = BTreeMap::new();
    for record in records {
        if !record.is_object() {
            return fail("artifact record must be an object");
        }
        let role = record.get("role");
        let Some(Value::String(role)) = role else {
            return fail(format!(
                "duplicate or invalid artifact role: {}",
                py_repr(role)
            ));
        };
        if by_role.contains_key(role) {
            return fail(format!("duplicate or invalid artifact role: '{role}'"));
        }
        let cid = match record.get("cid") {
            Some(Value::String(cid)) if cid.starts_with("Qm") => cid.clone(),
            other => return fail(format!("invalid CID for {role}: {}", py_repr(other))),
        };
        by_role.insert(role.clone(), record.clone());

        let Some(Value::String(vendored_path)) = record.get("vendored_path") else {
            return fail(format!("invalid vendored path for {role}"));
        };
        let path = resolve(&root.join(vendored_path));
        if !path.ancestors().skip(1).any(|ancestor| ancestor == root) {
            return fail(format!("vendored path escapes repository root for {role}"));
        }
        let payload = read_bytes(&path)?;
        if !equals_number(record.get("source_bytes"), payload.len() as u64) {
            return fail(format!("vendored byte count drift for {role}"));
        }
        if record.get("source_sha256") != Some(&json!(sha256_hex(&payload))) {
            return fail(format!("vendored digest drift for {role}"));
        }
        if unixfs_file_cidv0(&payload)? != cid {
            return fail(format!("vendored CIDv0 drift for {role}"));
        }
        if role.ends_with("_abi") {
            serde_json::from_slice::<Value>(&payload)
                .map_err(|error| format!("cannot parse ABI for {role}: {error}"))?;
        }
        if role.ends_with("_mapping_wasm") {
            let exports = record.get("exports");
            if !payload.starts_with(b"\0asm\x01\0\0\0") {
                return fail(format!("vendored mapping is not WebAssembly v1 for {role}"));
            }
            let Some(exports) = exports
                .and_then(Value::as_array)
                .filter(|list| !list.is_empty())
            else {
                return fail(format!("mapping export lock missing for {role}"));
            };
            if exports.iter().any(|name| match name {
                Value::String(name) => !contains_bytes(&payload, name.as_bytes()),
                _ => true,
            }) {
                return fail(format!(
                    "vendored mapping is missing a locked handler export for {role}"
                ));
            }
        }
    }

    let expected_roles: BTreeSet<&str> = BTreeSet::from([
        "deployment",
        "schema",
        "factory_abi",
        "erc20_abi",
        "erc20_symbol_bytes_abi",
        "erc20_name_bytes_abi",
        "pool_abi",
        "position_manager_abi",
        "factory_mapping_wasm",
        "position_manager_mapping_wasm",
        "pool_mapping_wasm",
    ]);
    let actual_roles: BTreeSet<&str> = by_role.keys().map(String::as_str).collect();
    if actual_roles != expected_roles {
        let drift: Vec<String> = actual_roles
            .symmetric_difference(&expected_roles)
            .map(|role| format!("'{role}'"))
            .collect();
        return fail(format!("artifact roles drift: [{}]", drift.join(", ")));
    }

    let expected_exports: [(&str, &[&str]); 3] = [
        ("factory_mapping_wasm", &["handlePoolCreated"]),
        (
            "position_manager_mapping_wasm",
            &[
                "handleIncreaseLiquidity",
                "handleDecreaseLiquidity",
                "handleCollect",
                "handleTransfer",
            ],
        ),
        (
            "pool_mapping_wasm",
            &[
                "handleInitialize",
                "handleSwap",
                "handleMint",
                "handleBurn",
                "handleFlash",
                "handleCollect",
                "handleCollectProtocol",
            ],
        ),
    ];
    for (role, exports) in expected_exports {
        if by_role[role].get("exports") != Some(&json!(exports)) {
            return fail(format!("mapping export inventory drift for {role}"));
        }
    }
    if index(&by_role["deployment"], "cid")? != &json!(EXPECTED_DEPLOYMENT) {
        return fail("deployment CID lock drift");
    }
    if index(&by_role["schema"], "cid")? != &json!(EXPECTED_SCHEMA) {
        return fail("schema CID lock drift");
    }
    Ok(by_role)
}

// ---------------------------------------------------------------------------
// Manifest
// ---------------------------------------------------------------------------

/// `[(abi.name, cid)]` for a mapping's `abis` list. Kept local rather than
/// shared because this family's failure text says "contract", not "inventory".
fn abi_contract(mapping: &Value) -> Result<Vec<(String, String)>, String> {
    let Some(entries) = mapping.get("abis").and_then(Value::as_array) else {
        return fail("mapping ABI contract must be a list");
    };
    entries
        .iter()
        .map(|entry| {
            Ok((
                py_str(entry.get("name")),
                cid_from_file(entry.get("file").unwrap_or(&Value::Null))?,
            ))
        })
        .collect()
}

fn verify_mapping_common(mapping: &Value, expected_cid: &str) -> Result<(), String> {
    if mapping.get("apiVersion") != Some(&json!("0.0.4")) {
        return fail("mapping apiVersion drift");
    }
    if mapping.get("kind") != Some(&json!("ethereum/events"))
        || mapping.get("language") != Some(&json!("wasm/assemblyscript"))
    {
        return fail("mapping runtime shape drift");
    }
    if mapping.get("entities") != Some(&json!(["Pool", "Token"])) {
        return fail("mapping entity declaration drift");
    }
    if cid_from_file(mapping.get("file").unwrap_or(&Value::Null))? != expected_cid {
        return fail("mapping CID drift");
    }
    Ok(())
}

fn verify_handlers(
    mapping: &Value,
    expected: &[(&str, &str)],
    component: &str,
) -> Result<(), String> {
    let Some(handlers) = mapping.get("eventHandlers").and_then(Value::as_array) else {
        return fail(format!("{component} handlers must be a list"));
    };
    let empty = Value::String(String::new());
    let actual: Vec<(String, String)> = handlers
        .iter()
        .map(|entry| {
            (
                py_str(entry.get("handler")),
                normalize_event(&py_str(Some(entry.get("event").unwrap_or(&empty)))),
            )
        })
        .collect();
    let normalized: Vec<(String, String)> = expected
        .iter()
        .map(|(handler, event)| ((*handler).to_string(), normalize_event(event)))
        .collect();
    if actual != normalized {
        return fail(format!("{component} handler order or signature drift"));
    }
    Ok(())
}

fn cid_of(artifacts: &BTreeMap<String, Value>, role: &str) -> String {
    py_str(artifacts.get(role).and_then(|item| item.get("cid")))
}

fn vendored_path(artifacts: &BTreeMap<String, Value>, role: &str) -> String {
    py_str(
        artifacts
            .get(role)
            .and_then(|item| item.get("vendored_path")),
    )
}

fn verify_manifest(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let manifest = read_yaml(&root.join(vendored_path(artifacts, "deployment")))?;
    let deployment = index(lock, "deployment")?;
    if manifest.get("specVersion") != Some(&json!("0.0.2")) {
        return fail("manifest specVersion drift");
    }
    if manifest.get("repository") != Some(&json!("https://github.com/pancakeswap/pancake-subgraph"))
    {
        return fail("manifest repository drift");
    }
    if manifest.get("features") != Some(&json!(["nonFatalErrors"]))
        || manifest.get("graft").is_some()
    {
        return fail("manifest feature/graft contract drift");
    }
    if cid_from_file(index(index(&manifest, "schema")?, "file")?)? != EXPECTED_SCHEMA {
        return fail("manifest schema CID drift");
    }

    let data_sources = manifest.get("dataSources").and_then(Value::as_array);
    let templates = manifest.get("templates").and_then(Value::as_array);
    let Some(data_sources) = data_sources.filter(|list| list.len() == 2) else {
        return fail("expected Factory and NonfungiblePositionManager data sources");
    };
    let Some(templates) = templates.filter(|list| list.len() == 1) else {
        return fail("expected exactly one Pool template");
    };

    let factory = &data_sources[0];
    let factory_mapping = index(factory, "mapping")?;
    if factory.get("kind") != Some(&json!("ethereum/contract"))
        || factory.get("name") != Some(&json!("Factory"))
        || factory.get("network") != Some(&json!("bsc"))
        || factory.get("source")
            != Some(&json!({
                "abi": "Factory",
                "address": "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
                "startBlock": 26956207,
            }))
    {
        return fail("Factory source contract drift");
    }
    verify_mapping_common(factory_mapping, &cid_of(artifacts, "factory_mapping_wasm"))?;
    if abi_contract(factory_mapping)?
        != [
            ("Factory".to_string(), cid_of(artifacts, "factory_abi")),
            ("ERC20".to_string(), cid_of(artifacts, "erc20_abi")),
            (
                "ERC20SymbolBytes".to_string(),
                cid_of(artifacts, "erc20_symbol_bytes_abi"),
            ),
            (
                "ERC20NameBytes".to_string(),
                cid_of(artifacts, "erc20_name_bytes_abi"),
            ),
            ("Pool".to_string(), cid_of(artifacts, "pool_abi")),
        ]
    {
        return fail("Factory ABI inventory drift");
    }
    verify_handlers(
        factory_mapping,
        &[(
            "handlePoolCreated",
            "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)",
        )],
        "Factory",
    )?;

    let position_manager = &data_sources[1];
    let position_mapping = index(position_manager, "mapping")?;
    if position_manager.get("kind") != Some(&json!("ethereum/contract"))
        || position_manager.get("name") != Some(&json!("NonfungiblePositionManager"))
        || position_manager.get("network") != Some(&json!("bsc"))
        || position_manager.get("source")
            != Some(&json!({
                "abi": "NonfungiblePositionManager",
                "address": "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364",
                "startBlock": 26931961,
            }))
    {
        return fail("NonfungiblePositionManager source contract drift");
    }
    verify_mapping_common(
        position_mapping,
        &cid_of(artifacts, "position_manager_mapping_wasm"),
    )?;
    if abi_contract(position_mapping)?
        != [
            (
                "NonfungiblePositionManager".to_string(),
                cid_of(artifacts, "position_manager_abi"),
            ),
            ("Pool".to_string(), cid_of(artifacts, "pool_abi")),
            ("Factory".to_string(), cid_of(artifacts, "factory_abi")),
            ("ERC20".to_string(), cid_of(artifacts, "erc20_abi")),
        ]
    {
        return fail("NonfungiblePositionManager ABI inventory drift");
    }
    verify_handlers(
        position_mapping,
        &[
            (
                "handleIncreaseLiquidity",
                "IncreaseLiquidity(indexed uint256,uint128,uint256,uint256)",
            ),
            (
                "handleDecreaseLiquidity",
                "DecreaseLiquidity(indexed uint256,uint128,uint256,uint256)",
            ),
            (
                "handleCollect",
                "Collect(indexed uint256,address,uint256,uint256)",
            ),
            (
                "handleTransfer",
                "Transfer(indexed address,indexed address,indexed uint256)",
            ),
        ],
        "NonfungiblePositionManager",
    )?;

    let pool = &templates[0];
    let pool_mapping = index(pool, "mapping")?;
    if pool.get("kind") != Some(&json!("ethereum/contract"))
        || pool.get("name") != Some(&json!("Pool"))
        || pool.get("network") != Some(&json!("bsc"))
        || pool.get("source") != Some(&json!({"abi": "Pool"}))
    {
        return fail("Pool template contract drift");
    }
    verify_mapping_common(pool_mapping, &cid_of(artifacts, "pool_mapping_wasm"))?;
    if abi_contract(pool_mapping)?
        != [
            ("Pool".to_string(), cid_of(artifacts, "pool_abi")),
            ("Factory".to_string(), cid_of(artifacts, "factory_abi")),
            ("ERC20".to_string(), cid_of(artifacts, "erc20_abi")),
        ]
    {
        return fail("Pool ABI inventory drift");
    }
    verify_handlers(
        pool_mapping,
        &[
            ("handleInitialize", "Initialize(uint160,int24)"),
            (
                "handleSwap",
                "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24,uint128,uint128)",
            ),
            (
                "handleMint",
                "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
            ),
            (
                "handleBurn",
                "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
            ),
            (
                "handleFlash",
                "Flash(indexed address,indexed address,uint256,uint256,uint256,uint256)",
            ),
            (
                "handleCollect",
                "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)",
            ),
            (
                "handleCollectProtocol",
                "CollectProtocol(indexed address,indexed address,uint128,uint128)",
            ),
        ],
        "Pool",
    )?;

    let expected_deployment = json!({
        "cid": EXPECTED_DEPLOYMENT,
        "chain": "bsc",
        "spec_version": "0.0.2",
        "mapping_api_version": "0.0.4",
        "repository": "https://github.com/pancakeswap/pancake-subgraph",
        "features": ["nonFatalErrors"],
        "data_sources": [
            {
                "name": "Factory",
                "address": "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
                "start_block": 26956207,
                "mapping_role": "factory_mapping_wasm",
            },
            {
                "name": "NonfungiblePositionManager",
                "address": "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364",
                "start_block": 26931961,
                "mapping_role": "position_manager_mapping_wasm",
            },
        ],
        "templates": [{"name": "Pool", "mapping_role": "pool_mapping_wasm"}],
    });
    if deployment != &expected_deployment {
        return fail("machine-readable deployment profile drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

type Entities = BTreeMap<String, BTreeMap<String, String>>;

fn take_ident(text: &str) -> Option<(&str, &str)> {
    let first = text.chars().next()?;
    if !(first == '_' || first.is_ascii_alphabetic()) {
        return None;
    }
    let end = text
        .char_indices()
        .find(|(_, character)| !(*character == '_' || character.is_ascii_alphanumeric()))
        .map(|(index, _)| index)
        .unwrap_or(text.len());
    Some((&text[..end], &text[end..]))
}

/// `^type\s+(ident)\s+@entity\s*(?:\(immutable:\s*(true|false)\))?\s*\{`
fn match_declaration(line: &str) -> Option<(String, Option<bool>)> {
    let rest = line.strip_prefix("type")?;
    let rest = {
        let trimmed = rest.trim_start();
        if trimmed.len() == rest.len() {
            return None;
        }
        trimmed
    };
    let (name, rest) = take_ident(rest)?;
    let rest = {
        let trimmed = rest.trim_start();
        if trimmed.len() == rest.len() {
            return None;
        }
        trimmed
    };
    let rest = rest.strip_prefix("@entity")?.trim_start();
    let (directive, tail) = match rest.strip_prefix("(immutable:") {
        Some(inner) => {
            let inner = inner.trim_start();
            let (flag, after) = match inner.strip_prefix("true") {
                Some(after) => (true, after),
                None => (false, inner.strip_prefix("false")?),
            };
            (Some(flag), after.strip_prefix(')')?)
        }
        None => (None, rest),
    };
    if !tail.trim_start().starts_with('{') {
        return None;
    }
    Some((name.to_string(), directive))
}

/// `^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)`
fn match_field(line: &str) -> Option<(String, String)> {
    let (name, rest) = take_ident(line)?;
    let rest = rest.trim_start().strip_prefix(':')?.trim_start();
    let end = rest
        .char_indices()
        .find(|(_, character)| {
            !(character.is_ascii_alphanumeric() || matches!(character, '[' | ']' | '!' | '_'))
        })
        .map(|(index, _)| index)
        .unwrap_or(rest.len());
    if end == 0 {
        return None;
    }
    Some((name.to_string(), rest[..end].to_string()))
}

/// The family-local `parse_schema`: unlike the shared helper, every entity that
/// is not declared `@entity(immutable: true)` counts as mutable, including
/// entities carrying no directive at all.
fn parse_schema(path: &Path) -> Result<(Entities, BTreeSet<String>, BTreeSet<String>), String> {
    let text = read_text(path)?;
    let mut entities: Entities = BTreeMap::new();
    let mut immutable: BTreeSet<String> = BTreeSet::new();
    let mut mutable: BTreeSet<String> = BTreeSet::new();
    let mut current: Option<String> = None;
    for raw_line in text.lines() {
        let line = raw_line.split('#').next().unwrap_or_default().trim();
        if let Some((name, directive)) = match_declaration(line) {
            if directive == Some(true) {
                immutable.insert(name.clone());
            } else {
                mutable.insert(name.clone());
            }
            entities.insert(name.clone(), BTreeMap::new());
            current = Some(name);
            continue;
        }
        let Some(name) = current.clone() else {
            continue;
        };
        if line == "}" {
            current = None;
            continue;
        }
        if let Some((field, kind)) = match_field(line) {
            entities
                .get_mut(&name)
                .ok_or_else(|| format!("'{name}'"))?
                .insert(field, kind);
        }
    }
    Ok((entities, immutable, mutable))
}

fn field_differences(exchange: &Entities, uniswap: &Entities) -> Value {
    let mut differences = Map::new();
    for (entity, exchange_fields) in exchange {
        let Some(uniswap_fields) = uniswap.get(entity) else {
            continue;
        };
        let mut entry = Map::new();
        let missing: Vec<&String> = uniswap_fields
            .keys()
            .filter(|field| !exchange_fields.contains_key(*field))
            .collect();
        let extra: Vec<&String> = exchange_fields
            .keys()
            .filter(|field| !uniswap_fields.contains_key(*field))
            .collect();
        let mut type_differences = Map::new();
        for (field, exchange_type) in exchange_fields {
            if let Some(uniswap_type) = uniswap_fields.get(field) {
                if exchange_type != uniswap_type {
                    type_differences.insert(field.clone(), json!([exchange_type, uniswap_type]));
                }
            }
        }
        if !missing.is_empty() {
            entry.insert("missing_from_exchange".into(), json!(missing));
        }
        if !extra.is_empty() {
            entry.insert("extra_in_exchange".into(), json!(extra));
        }
        if !type_differences.is_empty() {
            entry.insert("type_differences".into(), Value::Object(type_differences));
        }
        if !entry.is_empty() {
            differences.insert(entity.clone(), Value::Object(entry));
        }
    }
    Value::Object(differences)
}

fn sorted_names<'a>(names: impl IntoIterator<Item = &'a String>) -> Value {
    json!(names.into_iter().collect::<BTreeSet<&String>>())
}

fn verify_schema(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let contract = index(lock, "logical_contract")?;
    let (exchange, exchange_immutable, exchange_mutable) =
        parse_schema(&root.join(vendored_path(artifacts, "schema")))?;
    let (uniswap, uniswap_immutable, _) =
        parse_schema(&root.join("uniswap-v3/source/schema.graphql"))?;

    if !equals_number(contract.get("entity_count"), exchange.len() as u64)
        || contract.get("entities") != Some(&sorted_names(exchange.keys()))
    {
        return fail("Exchange V3 entity inventory drift");
    }
    if contract.get("logical_sha256") != Some(&json!(logical_hash(&exchange))) {
        return fail("Exchange V3 logical schema digest drift");
    }
    if contract.get("immutable_entities") != Some(&sorted_names(&exchange_immutable)) {
        return fail("Exchange V3 immutable-entity contract drift");
    }
    if contract.get("mutable_entities") != Some(&sorted_names(&exchange_mutable)) {
        return fail("Exchange V3 mutable-entity contract drift");
    }

    let reference = index(contract, "frozen_uniswap_v3")?;
    if !equals_number(reference.get("entity_count"), uniswap.len() as u64)
        || reference.get("logical_sha256") != Some(&json!(logical_hash(&uniswap)))
    {
        return fail("frozen Uniswap V3 schema reference drift");
    }
    let missing_from_exchange =
        sorted_names(uniswap.keys().filter(|name| !exchange.contains_key(*name)));
    if reference.get("missing_from_exchange") != Some(&missing_from_exchange) {
        return fail("Exchange V3 missing-entity profile drift");
    }
    let extra_in_exchange =
        sorted_names(exchange.keys().filter(|name| !uniswap.contains_key(*name)));
    if reference.get("extra_in_exchange") != Some(&extra_in_exchange) {
        return fail("Exchange V3 extra-entity profile drift");
    }
    let mutability_gap = sorted_names(
        uniswap_immutable
            .iter()
            .filter(|name| !exchange_immutable.contains(*name)),
    );
    if reference.get("immutable_in_uniswap_but_mutable_in_exchange") != Some(&mutability_gap) {
        return fail("Exchange V3 mutability gap profile drift");
    }
    if reference.get("field_differences") != Some(&field_differences(&exchange, &uniswap)) {
        return fail("Exchange V3 static field gap profile drift");
    }
    if reference.get("scope") != Some(&json!("static_schema_only_pending_certified_runtime_gap")) {
        return fail("static schema comparison scope drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Layout profile
// ---------------------------------------------------------------------------

fn verify_profile(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let profile_payload = read_bytes(&root.join(PROFILE_PATH))?;
    if profile_payload.len() as u64 != EXPECTED_PROFILE_BYTES
        || sha256_hex(&profile_payload) != EXPECTED_PROFILE_SHA256
    {
        return fail("machine-readable Exchange V3 layout profile digest drift");
    }
    if lock.get("layout_profile")
        != Some(&json!({
            "path": PROFILE_PATH,
            "bytes": EXPECTED_PROFILE_BYTES,
            "sha256": EXPECTED_PROFILE_SHA256,
        }))
    {
        return fail("Exchange V3 layout profile provenance lock drift");
    }
    let profile = load_json(&root.join(PROFILE_PATH))?;
    if !profile.is_object() {
        return fail("Exchange V3 layout profile must be an object");
    }
    if profile.get("format_version") != Some(&json!(1))
        || profile.get("profile_id") != Some(&json!("exchange-v3-bsc-QmY67iZD"))
        || profile.get("status") != Some(&json!("immutable_target_and_exact_source_contract_only"))
        || profile.get("runtime_parity") != Some(&Value::Bool(false))
        || profile.get("eligibility_decision") != Some(&json!("indeterminate_no_fresh_evidence"))
        || profile.get("family") != Some(&json!("exchange-v3-bsc"))
        || profile.get("chain") != Some(&json!("bsc"))
    {
        return fail("Exchange V3 layout profile identity or baseline-only status drift");
    }
    if profile.get("deployment")
        != Some(&json!({
            "cid": EXPECTED_DEPLOYMENT,
            "spec_version": "0.0.2",
            "mapping_api_version": "0.0.4",
            "module_initial_block": 26931961,
            "graft": null,
            "features": ["nonFatalErrors"],
        }))
    {
        return fail("Exchange V3 profile deployment contract drift");
    }

    let expected_component_contracts: [(&str, Value); 3] = [
        (
            "Factory",
            json!({
                "kind": "data_source",
                "address": "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
                "start_block": 26956207,
                "mapping_cid": index(&artifacts["factory_mapping_wasm"], "cid")?,
            }),
        ),
        (
            "NonfungiblePositionManager",
            json!({
                "kind": "data_source",
                "address": "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364",
                "start_block": 26931961,
                "mapping_cid": index(&artifacts["position_manager_mapping_wasm"], "cid")?,
            }),
        ),
        (
            "Pool",
            json!({
                "kind": "template",
                "created_by": "Factory.handlePoolCreated",
                "mapping_cid": index(&artifacts["pool_mapping_wasm"], "cid")?,
            }),
        ),
    ];

    let components = profile.get("components").and_then(Value::as_array);
    let inventory_ok = components.is_some_and(|items| {
        items.iter().all(Value::is_object)
            && items
                .iter()
                .map(|item| item.get("name"))
                .collect::<Vec<_>>()
                == vec![
                    Some(&json!("Factory")),
                    Some(&json!("NonfungiblePositionManager")),
                    Some(&json!("Pool")),
                ]
    });
    if !inventory_ok {
        return fail("Exchange V3 profile component inventory or order drift");
    }
    for component in components.expect("component inventory validated above") {
        let Some(fields) = component.as_object() else {
            return fail("Exchange V3 profile component must be an object");
        };
        let name = py_str(component.get("name"));
        let handlers = component.get("handlers");
        let contract: Map<String, Value> = fields
            .iter()
            .filter(|(key, _)| key.as_str() != "name" && key.as_str() != "handlers")
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        let expected_contract = expected_component_contracts
            .iter()
            .find(|(key, _)| *key == name)
            .map(|(_, value)| value)
            .ok_or_else(|| format!("'{name}'"))?;
        if &Value::Object(contract) != expected_contract {
            return fail(format!(
                "Exchange V3 profile component contract drift: {name}"
            ));
        }
        let expected_handlers: Vec<Value> = EXPECTED_PROFILE_HANDLERS
            .iter()
            .find(|(key, _)| *key == name)
            .map(|(_, value)| *value)
            .ok_or_else(|| format!("'{name}'"))?
            .iter()
            .map(|(handler, signature, topic0)| json!([handler, signature, topic0]))
            .collect();
        let actual_handlers: Option<Vec<Value>> = handlers.and_then(Value::as_array).map(|list| {
            list.iter()
                .filter(|handler| handler.is_object())
                .map(|handler| {
                    json!([
                        handler.get("name"),
                        handler.get("signature"),
                        handler.get("topic0"),
                    ])
                })
                .collect()
        });
        if actual_handlers.as_deref() != Some(expected_handlers.as_slice()) {
            return fail(format!(
                "Exchange V3 profile handler/topic contract drift: {name}"
            ));
        }
    }

    if profile.get("pool_creation")
        != Some(&json!({
            "pool_id": "lowercase_pool_address_hex",
            "token_ids": "lowercase_token_address_hex",
            "factory_entity_id": "factory_address",
            "bundle_entity_id": "1",
            "fee_tier_source": "PoolCreated.fee",
            "dynamic_pool_template_created": true,
            "missing_token_decimals_behavior": "return_without_pool_token_or_factory_saves",
        }))
    {
        return fail("Exchange V3 pool-creation contract drift");
    }
    if profile.get("fee_and_protocol")
        != Some(&json!({
            "tick_spacing_by_fee_tier": {"100": 1, "500": 10, "2500": 50, "10000": 200},
            "default_packed_fee_protocol_by_fee_tier": {
                "100": 216272100,
                "500": 222825800,
                "2500": 209718400,
                "10000": 209718400,
                "fallback": 209718400,
            },
            "swap_protocol_fee_inputs": ["protocolFeesToken0", "protocolFeesToken1"],
            "swap_amount_fee_usd": "combined_adjusted_protocol_fee_usd",
            "protocol_fee_aggregates": [
                "Factory.totalProtocolFeesETH",
                "Factory.totalProtocolFeesUSD",
                "Pool.protocolFeesUSD",
                "Token.protocolFeesUSD",
                "PancakeDayData.protocolFeesUSD",
                "PoolDayData.protocolFeesUSD",
                "PoolHourData.protocolFeesUSD",
                "TokenDayData.protocolFeesUSD",
                "TokenHourData.protocolFeesUSD",
            ],
            "collect_protocol_behavior":
                "subtract_amounts_from_pool_and_token_tvl_increment_tx_counts_without_event_entity",
            "flash_behavior": "refresh_pool_fee_growth_globals_only",
        }))
    {
        return fail("Exchange V3 fee/protocol behavior contract drift");
    }
    if profile.get("positions")
        != Some(&json!({
            "position_id": "decimal_token_id_string",
            "lazy_source": "NonfungiblePositionManager.try_positions",
            "pool_source": "Factory.getPool_token0_token1_fee",
            "initial_owner": "zero_address_until_transfer",
            "transfer_updates_owner": true,
            "burn_delete": false,
            "snapshot_id": "position_id_hash_block_number",
            "snapshot_written_by": [
                "IncreaseLiquidity",
                "DecreaseLiquidity",
                "Collect",
                "Transfer",
            ],
            "fee_growth_refreshed_by": ["IncreaseLiquidity", "DecreaseLiquidity", "Collect"],
            "source_compatibility_quirk":
                "position_manager_collect_adds_amount0_to_both_collected_fee_token_fields",
        }))
    {
        return fail("Exchange V3 position behavior contract drift");
    }

    let logical_contract = index(lock, "logical_contract")?;
    if profile.get("entity_layout")
        != Some(&json!({
            "entity_count": index(logical_contract, "entity_count")?,
            "all_entities_mutable": true,
            "immutable_entities": index(logical_contract, "immutable_entities")?,
            "entities": index(logical_contract, "entities")?,
        }))
    {
        return fail("Exchange V3 profile entity layout drift");
    }
    if profile.get("aggregates")
        != Some(&json!({
            "swap_amounts": "absolute_token_deltas",
            "tracked_volume_divisor": 2,
            "untracked_volume_divisor": 2,
            "lp_fee_formula": "tracked_swap_volume_times_pool_fee_tier_div_1000000",
            "protocol_fee_formula": "adjusted_event_protocol_fee_amounts",
            "intervals": [
                "pancake_day",
                "pool_day",
                "pool_hour",
                "token_day",
                "token_hour",
                "tick_day",
                "tick_hour",
            ],
            "tick_crossing_update_cap": 100,
            "pool_collect_tvl_change": "none_to_avoid_double_counting_burn",
            "pool_collect_protocol_tvl_change": "subtract_collected_protocol_amounts",
        }))
    {
        return fail("Exchange V3 aggregate behavior contract drift");
    }

    let chain = index(index(lock, "exact_source")?, "chain_configuration")?;
    if profile.get("pricing")
        != Some(&json!({
            "wrapped_native_address": index(chain, "wrapped_native")?,
            "stablecoin_wrapped_native_pool": index(chain, "wrapped_native_stable_pool")?,
            "stablecoin_is_token0": index(chain, "stable_is_token0")?,
            "minimum_native_locked": index(chain, "minimum_native_locked")?,
            "stablecoin_addresses": index(chain, "stable_coins")?,
            "whitelist_tokens": index(chain, "whitelist_tokens")?,
            "static_token_definitions": [],
            "pools_to_skip": [],
            "pool_mappings": [],
        }))
    {
        return fail("Exchange V3 BSC pricing configuration drift");
    }
    if profile.get("metadata")
        != Some(&json!({
            "symbol_and_name_fallback": "string_then_bytes32_then_static_definition_then_unknown",
            "static_definitions_enabled": false,
            "total_supply_call": true,
            "decimals_call": "uint8_with_static_definition_fallback",
            "null_bytes32_sentinel_handling": true,
        }))
    {
        return fail("Exchange V3 token metadata behavior contract drift");
    }

    let reference = index(logical_contract, "frozen_uniswap_v3")?;
    let Some(reference_differences) = index(reference, "field_differences")?.as_object() else {
        return fail("Exchange V3 frozen Uniswap V3 gap profile drift");
    };
    let mut expected_extra_fields = Map::new();
    for (entity, difference) in reference_differences {
        expected_extra_fields.insert(
            entity.clone(),
            index(difference, "extra_in_exchange")?.clone(),
        );
    }
    if profile.get("frozen_uniswap_v3_static_gap")
        != Some(&json!({
            "entity_rename": {"UniswapDayData": "PancakeDayData"},
            "immutable_in_uniswap_but_mutable_in_exchange":
                index(reference, "immutable_in_uniswap_but_mutable_in_exchange")?,
            "extra_exchange_fields": Value::Object(expected_extra_fields),
            "scope": "static_schema_and_exact_source_semantics_pending_certified_runtime_gap",
        }))
    {
        return fail("Exchange V3 frozen Uniswap V3 gap profile drift");
    }
    if profile.get("required_target_changes") != Some(&json!(EXPECTED_REQUIRED_CHANGES)) {
        return fail("Exchange V3 required target-change inventory drift");
    }
    if profile.get("remaining_gates") != Some(&json!(EXPECTED_PROFILE_REMAINING_GATES)) {
        return fail("Exchange V3 remaining-gate profile drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Exact source pin
// ---------------------------------------------------------------------------

fn verify_source_pin(lock: &Value, artifacts: &BTreeMap<String, Value>) -> Result<(), String> {
    let Some(source) = lock.get("exact_source").filter(|value| value.is_object()) else {
        return fail("exact_source must be an object");
    };
    if source.get("status") != Some(&json!("exact_reproduction")) {
        return fail("Exchange V3 source must remain bound to the exact reproduction");
    }
    if source.get("repository") != Some(&json!("https://github.com/pancakeswap/pancake-subgraph")) {
        return fail("exact source repository drift");
    }
    if source.get("branch") != Some(&json!("v3")) {
        return fail("exact source branch drift");
    }
    if source.get("earliest_exact_commit") != Some(&json!(EXPECTED_SOURCE_COMMIT)) {
        return fail("earliest exact source commit drift");
    }
    if source.get("tree") != Some(&json!(EXPECTED_SOURCE_TREE)) {
        return fail("exact source tree drift");
    }
    if source.get("parent") != Some(&json!(EXPECTED_SOURCE_PARENT)) {
        return fail("exact source parent drift");
    }
    if ["earliest_exact_commit", "tree", "parent"]
        .iter()
        .any(|key| match source.get(*key) {
            None => true,
            other => !is_lowercase_hex(&py_str(other), 40),
        })
    {
        return fail("invalid exact source commit, tree, or parent");
    }

    if source.get("toolchain")
        != Some(&json!({
            "source_ci_node_range": "14.x",
            "reproduction_node": "14.21.3",
            "reproduction_yarn": "1.22.22",
            "graph_cli": "0.21.0",
            "graph_ts": "0.20.1",
            "assemblyscript": "0.6.0",
            "assemblyscript_git_commit": "3ed76a97f05335504166fce1653da75f4face28f",
        }))
    {
        return fail("exact source toolchain drift");
    }

    let expected_source_paths: BTreeSet<&str> = BTreeSet::from([
        "package.json",
        "yarn.lock",
        ".github/workflows/build.yml",
        "config/bsc.js",
        "subgraphs/exchange-v3/template/package.json",
        "subgraphs/exchange-v3/template/subgraph.template.yaml",
        "subgraphs/exchange-v3/template/schema.graphql",
        "subgraphs/exchange-v3/template/mappings/factory.ts",
        "subgraphs/exchange-v3/template/mappings/position-manager.ts",
        "subgraphs/exchange-v3/template/mappings/core.ts",
        "subgraphs/exchange-v3/template/utils/pricing.template.ts",
    ]);
    let Some(source_files) = source.get("source_files").and_then(Value::as_array) else {
        return fail("exact source file inventory drift");
    };
    let actual_source_paths: BTreeSet<String> = source_files
        .iter()
        .filter(|entry| entry.is_object())
        .map(|entry| match entry.get("path") {
            Some(Value::String(path)) => path.clone(),
            // Prefix a non-string path so it can never match a locked path.
            other => format!("\u{0}{}", py_repr(other)),
        })
        .collect();
    if actual_source_paths
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<&str>>()
        != expected_source_paths
    {
        return fail("exact source file inventory drift");
    }
    for entry in source_files {
        let valid = entry.is_object()
            && entry
                .get("bytes")
                .is_some_and(|value| value.is_i64() || value.is_u64())
            && is_lowercase_hex(&py_str(entry.get("sha256")), 64)
            && is_lowercase_hex(&py_str(entry.get("git_blob")), 40);
        if !valid {
            return fail("invalid exact source file record");
        }
    }

    if source.get("install_transport_override")
        != Some(&json!({
            "reason": "The lock's deleted concat-stream GitHub fork tarball now returns 404.",
            "locked_request": "concat-stream@github:hugomrdias/concat-stream#feat/smaller",
            "dead_url": "https://codeload.github.com/hugomrdias/concat-stream/tar.gz/057bc7b5d6d8df26c8cf00a3f151b6721a0a8034",
            "replacement": "https://registry.yarnpkg.com/concat-stream/-/concat-stream-2.0.0.tgz#414cf5af790a48c60ab9be4527d56d5e41133cb1",
            "replacement_integrity": "sha512-MWufYdFw53ccGjCA+Ol7XJYpAlW6/prSMzuPOTRnJGcGzuhLn4Scrz7qf6o8bROZ514ltazcIFJZevcfbo0x7A==",
            "scope": "install_transport_only_graph_cli_ipfs_client_not_compiler",
            "original_lock_restored_before_validation": true,
        }))
    {
        return fail("install transport override drift");
    }

    let build = source.get("build");
    let build_ok = build.is_some_and(|value| {
        value.is_object()
            && value.get("result") == Some(&json!("byte_exact_to_all_deployed_mapping_objects"))
    });
    if !build_ok {
        return fail("exact source build result drift");
    }
    let build = build.expect("build validated above");
    for (prefix, role) in [
        ("factory", "factory_mapping_wasm"),
        ("position_manager", "position_manager_mapping_wasm"),
        ("pool", "pool_mapping_wasm"),
    ] {
        if build.get(format!("{prefix}_wasm_bytes"))
            != Some(index(&artifacts[role], "source_bytes")?)
        {
            return fail(format!("{prefix} exact source byte count drift"));
        }
        if build.get(format!("{prefix}_wasm_sha256"))
            != Some(index(&artifacts[role], "source_sha256")?)
        {
            return fail(format!("{prefix} exact source digest drift"));
        }
    }

    let boundary = source.get("earliest_exact_boundary");
    let boundary_ok = boundary.is_some_and(|value| {
        value.is_object()
            && value.get("previous_commit")
                == Some(&json!("e2019f716f4310f4ce28addc4439980804d9e413"))
    });
    if !boundary_ok {
        return fail("earliest exact source boundary drift");
    }
    if boundary.and_then(|value| value.get("exact_change"))
        != Some(&json!("Set BSC v3.minETHLocked from 60 to 10."))
    {
        return fail("earliest exact source change drift");
    }

    let chain_ok = source.get("chain_configuration").is_some_and(|value| {
        value.is_object() && value.get("minimum_native_locked") == Some(&json!("10"))
    });
    if !chain_ok {
        return fail("exact BSC chain configuration drift");
    }
    if lock.get("remaining_gates") != Some(&json!(EXPECTED_LOCK_REMAINING_GATES)) {
        return fail("remaining Exchange V3 gates must stay explicit");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Exact source build (`--exact-source-root`)
// ---------------------------------------------------------------------------

fn local_path_from_file(value: &Value) -> Result<String, String> {
    let escapes = match value {
        Value::String(path) => {
            path.starts_with('/')
                || Path::new(path)
                    .components()
                    .any(|component| component == Component::ParentDir)
        }
        _ => true,
    };
    if escapes {
        return fail(format!(
            "unexpected generated-manifest path: {}",
            py_repr(Some(value))
        ));
    }
    Ok(value.as_str().expect("string validated above").to_string())
}

fn replace_generated_files_with_cids(value: &Value, build_root: &Path) -> Result<Value, String> {
    match value {
        Value::Object(fields) => {
            let mut output = Map::new();
            for (key, item) in fields {
                if key == "file" {
                    let relative = local_path_from_file(item)?;
                    let payload = read_bytes(&build_root.join(relative))?;
                    output.insert(
                        key.clone(),
                        json!({"/": format!("/ipfs/{}", unixfs_file_cidv0(&payload)?)}),
                    );
                } else {
                    output.insert(
                        key.clone(),
                        replace_generated_files_with_cids(item, build_root)?,
                    );
                }
            }
            Ok(Value::Object(output))
        }
        Value::Array(items) => items
            .iter()
            .map(|item| replace_generated_files_with_cids(item, build_root))
            .collect::<Result<Vec<Value>, String>>()
            .map(Value::Array),
        other => Ok(other.clone()),
    }
}

fn verify_exact_source_build(
    root: &Path,
    source_root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let source = index(lock, "exact_source")?;
    let records = index(source, "source_files")?
        .as_array()
        .ok_or("exact source file inventory drift")?;
    for record in records {
        let path = py_str(Some(index(record, "path")?));
        let payload = read_bytes(&source_root.join(&path))?;
        if !equals_number(record.get("bytes"), payload.len() as u64)
            || index(record, "sha256")? != &json!(sha256_hex(&payload))
            || index(record, "git_blob")? != &json!(git_blob_hash(&payload))
        {
            return fail(format!("exact source file drift: {path}"));
        }
    }

    let build_root = source_root.join("subgraphs/exchange-v3/template/build");
    let deployed_manifest = read_yaml(&root.join(vendored_path(artifacts, "deployment")))?;
    let built_manifest = read_yaml(&build_root.join("subgraph.yaml"))?;
    if replace_generated_files_with_cids(&built_manifest, &build_root)? != deployed_manifest {
        return fail("exact source generated manifest does not resolve to the deployed CID graph");
    }

    let built_artifacts: [(&str, &str); 10] = [
        ("schema", "schema.graphql"),
        ("factory_abi", "Factory/abis/factory.json"),
        ("erc20_abi", "Factory/abis/ERC20.json"),
        (
            "erc20_symbol_bytes_abi",
            "Factory/abis/ERC20SymbolBytes.json",
        ),
        ("erc20_name_bytes_abi", "Factory/abis/ERC20NameBytes.json"),
        ("pool_abi", "Factory/abis/pool.json"),
        (
            "position_manager_abi",
            "NonfungiblePositionManager/abis/NonfungiblePositionManager.json",
        ),
        ("factory_mapping_wasm", "Factory/Factory.wasm"),
        (
            "position_manager_mapping_wasm",
            "NonfungiblePositionManager/NonfungiblePositionManager.wasm",
        ),
        ("pool_mapping_wasm", "templates/Pool/Pool.wasm"),
    ];
    for (role, relative_path) in built_artifacts {
        let payload = read_bytes(&build_root.join(relative_path))?;
        let deployed_payload = read_bytes(&root.join(vendored_path(artifacts, role)))?;
        if payload != deployed_payload {
            return fail(format!(
                "exact source build is not byte-identical for {role}"
            ));
        }
        if !equals_number(artifacts[role].get("source_bytes"), payload.len() as u64) {
            return fail(format!("exact source build byte count drift for {role}"));
        }
        if artifacts[role].get("source_sha256") != Some(&json!(sha256_hex(&payload))) {
            return fail(format!("exact source build digest drift for {role}"));
        }
    }

    let toolchain = index(source, "toolchain")?;
    for (key, package) in [
        (
            "graph_cli",
            "node_modules/@graphprotocol/graph-cli/package.json",
        ),
        (
            "graph_ts",
            "node_modules/@graphprotocol/graph-ts/package.json",
        ),
        ("assemblyscript", "node_modules/assemblyscript/package.json"),
    ] {
        let installed = load_json(&source_root.join(package))?;
        if index(&installed, "version")? != index(toolchain, key)? {
            return fail(format!("installed exact source toolchain drift: {key}"));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Binding
// ---------------------------------------------------------------------------

fn verify_binding(root: &Path) -> Result<(), String> {
    const DRIFT: &str =
        "Exchange V3 target binding, M6 market snapshot, or fail-closed eligibility drift";
    let binding = read_yaml(&root.join(BINDING_PATH))?;
    let Some(fields) = binding.as_object() else {
        return fail(DRIFT);
    };
    if binding.get("deployment") != Some(&json!(EXPECTED_DEPLOYMENT))
        || binding.get("family") != Some(&json!("exchange-v3-bsc"))
        || binding.get("schema") != Some(&json!(EXPECTED_SCHEMA))
        || binding.get("chain") != Some(&json!("bsc"))
        || binding.get("milestone") != Some(&json!("M6"))
        || binding.get("market_snapshot")
            != Some(&json!({
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 73997,
                "query_fees_grt_24h": "171.957",
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
            }))
        || fields.keys().any(|field| {
            field != "market_snapshot"
                && (field.starts_with("market_")
                    || field.starts_with("qos_")
                    || field.starts_with("query_fee")
                    || field.contains("grt")
                    || matches!(
                        field.as_str(),
                        "queries_24h" | "query_count_24h" | "fees_24h"
                    ))
        })
    {
        return fail(DRIFT);
    }
    let latest = binding
        .get("eligibility")
        .and_then(|value| value.get("latest"));
    if latest.and_then(|value| value.get("decision")) != Some(&json!("indeterminate"))
        || latest.and_then(|value| value.get("reason")) != Some(&json!("no_fresh_evidence"))
    {
        return fail(DRIFT);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

/// Verify the pinned Exchange V3 BSC target under `root`, with `lock` relative
/// to it. `exact_source_root` additionally re-checks a materialized source tree
/// produced by `scripts/verify-exchange-v3-bsc-source.sh`.
pub fn verify(
    root: &Path,
    lock: &Path,
    exact_source_root: Option<&Path>,
) -> Result<String, String> {
    let root = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve {}: {error}", root.display()))?;
    let lock_value = load_json(&root.join(lock))?;
    if !lock_value.is_object() || lock_value.get("format_version") != Some(&json!(1)) {
        return fail("unsupported Exchange V3 BSC target lock");
    }
    if lock_value.get("family") != Some(&json!("exchange-v3-bsc"))
        || lock_value.get("implementation_status")
            != Some(&json!("immutable_target_and_exact_source_baseline_only"))
        || lock_value.get("runtime_parity") != Some(&Value::Bool(false))
        || lock_value.get("eligibility_decision") != Some(&json!("indeterminate_no_fresh_evidence"))
        || lock_value.get("remaining_gates") != Some(&json!(EXPECTED_LOCK_REMAINING_GATES))
    {
        return fail(
            "Exchange V3 baseline status, runtime-parity refusal, or remaining gates drift",
        );
    }
    let deployment_ok = lock_value.get("deployment").is_some_and(|value| {
        value.is_object() && value.get("cid") == Some(&json!(EXPECTED_DEPLOYMENT))
    });
    if !deployment_ok {
        return fail("deployment identity drift");
    }
    let artifacts = verify_artifacts(&root, &lock_value)?;
    verify_manifest(&root, &lock_value, &artifacts)?;
    verify_schema(&root, &lock_value, &artifacts)?;
    verify_profile(&root, &lock_value, &artifacts)?;
    verify_source_pin(&lock_value, &artifacts)?;
    verify_binding(&root)?;
    if let Some(source_root) = exact_source_root {
        let source_root = source_root
            .canonicalize()
            .map_err(|error| format!("cannot resolve {}: {error}", source_root.display()))?;
        verify_exact_source_build(&root, &source_root, &lock_value, &artifacts)?;
    }
    Ok(SUCCESS_LINE.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    const BINDING_NAME: &str = "QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn.yaml";

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    fn copy_tree(from: &Path, to: &Path) {
        fs::create_dir_all(to).unwrap();
        for entry in fs::read_dir(from).unwrap() {
            let entry = entry.unwrap();
            let target = to.join(entry.file_name());
            if entry.file_type().unwrap().is_dir() {
                copy_tree(&entry.path(), &target);
            } else {
                fs::copy(entry.path(), &target).unwrap();
            }
        }
    }

    /// The Python test fixture: the family directory, the frozen Uniswap V3
    /// schema, and the lock copied into a scratch root.
    struct Fixture {
        _temporary: tempfile::TempDir,
        root: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let temporary = tempfile::tempdir().unwrap();
            let root = temporary.path().to_path_buf();
            let repository = repository();
            copy_tree(
                &repository.join("exchange-v3-bsc"),
                &root.join("exchange-v3-bsc"),
            );
            fs::create_dir_all(root.join("uniswap-v3/source")).unwrap();
            fs::copy(
                repository.join("uniswap-v3/source/schema.graphql"),
                root.join("uniswap-v3/source/schema.graphql"),
            )
            .unwrap();
            fs::create_dir_all(root.join("docs/provenance")).unwrap();
            fs::copy(repository.join(LOCK_PATH), root.join(LOCK_PATH)).unwrap();
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

        fn load_lock(&self) -> Value {
            serde_json::from_str(&fs::read_to_string(self.path(LOCK_PATH)).unwrap()).unwrap()
        }

        fn write_lock(&self, lock: &Value) {
            fs::write(
                self.path(LOCK_PATH),
                serde_json::to_string_pretty(lock).unwrap() + "\n",
            )
            .unwrap();
        }

        fn replace_once(&self, relative: &str, from: &str, to: &str) {
            let path = self.path(relative);
            let text = fs::read_to_string(&path).unwrap();
            assert!(text.contains(from), "fixture text {from} not found");
            fs::write(&path, text.replacen(from, to, 1)).unwrap();
        }

        fn relock_artifact(&self, role: &str) {
            let mut lock = self.load_lock();
            let record = lock["artifact_lock"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|item| item["role"] == json!(role))
                .unwrap();
            let payload =
                fs::read(self.root.join(record["vendored_path"].as_str().unwrap())).unwrap();
            record["source_bytes"] = json!(payload.len());
            record["source_sha256"] = json!(sha256_hex(&payload));
            self.write_lock(&lock);
        }
    }

    #[test]
    fn real_repository_tree_verifies() {
        assert_eq!(
            super::verify(&repository(), Path::new(LOCK_PATH), None),
            Ok(SUCCESS_LINE.to_string())
        );
    }

    #[test]
    fn exact_baseline_passes() {
        assert_eq!(Fixture::new().verify(), Ok(SUCCESS_LINE.to_string()));
    }

    #[test]
    fn artifact_byte_drift_is_rejected() {
        let fixture = Fixture::new();
        fixture.replace_once(
            "exchange-v3-bsc/reference/schema.graphql",
            "type Bundle",
            "type BundleDrift",
        );
        assert_eq!(
            fixture.verify(),
            Err("vendored byte count drift for schema".into())
        );
    }

    #[test]
    fn semantic_manifest_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.replace_once(
            "exchange-v3-bsc/reference/deployment.yaml",
            "network: bsc",
            "network: mainnet",
        );
        fixture.relock_artifact("deployment");
        assert_eq!(
            fixture.verify(),
            Err("vendored CIDv0 drift for deployment".into())
        );
    }

    #[test]
    fn mapping_byte_drift_is_rejected() {
        let fixture = Fixture::new();
        let path = fixture.path("exchange-v3-bsc/reference/mappings/Pool.wasm");
        let mut payload = fs::read(&path).unwrap();
        let last = payload.len() - 1;
        payload[last] ^= 1;
        fs::write(&path, payload).unwrap();
        assert_eq!(
            fixture.verify(),
            Err("vendored digest drift for pool_mapping_wasm".into())
        );
    }

    #[test]
    fn profile_semantic_drift_is_rejected_after_provenance_relock() {
        let fixture = Fixture::new();
        let profile_path = fixture.path(PROFILE_PATH);
        let mut profile: Value =
            serde_json::from_str(&fs::read_to_string(&profile_path).unwrap()).unwrap();
        profile["fee_and_protocol"]["swap_amount_fee_usd"] = json!("ignored");
        fs::write(
            &profile_path,
            serde_json::to_string_pretty(&profile).unwrap() + "\n",
        )
        .unwrap();
        let payload = fs::read(&profile_path).unwrap();
        let mut lock = fixture.load_lock();
        lock["layout_profile"]["bytes"] = json!(payload.len());
        lock["layout_profile"]["sha256"] = json!(sha256_hex(&payload));
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("machine-readable Exchange V3 layout profile digest drift".into())
        );
    }

    #[test]
    fn uniswap_schema_reference_drift_is_rejected() {
        let fixture = Fixture::new();
        fixture.replace_once(
            "uniswap-v3/source/schema.graphql",
            "type Position ",
            "type PositionDrift ",
        );
        assert_eq!(
            fixture.verify(),
            Err("frozen Uniswap V3 schema reference drift".into())
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
            Err("Exchange V3 source must remain bound to the exact reproduction".into())
        );
    }

    #[test]
    fn exact_source_parent_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["exact_source"]["parent"] = json!("0".repeat(40));
        fixture.write_lock(&lock);
        assert_eq!(fixture.verify(), Err("exact source parent drift".into()));
    }

    #[test]
    fn exact_source_mapping_output_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["exact_source"]["build"]["pool_wasm_sha256"] = json!("0".repeat(64));
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("pool exact source digest drift".into())
        );
    }

    #[test]
    fn install_transport_override_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["exact_source"]["install_transport_override"]["replacement"] = json!("unreviewed");
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("install transport override drift".into())
        );
    }

    #[test]
    fn runtime_parity_claim_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["runtime_parity"] = json!(true);
        lock["implementation_status"] = json!("runtime_complete");
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err(
                "Exchange V3 baseline status, runtime-parity refusal, or remaining gates drift"
                    .into()
            )
        );
    }

    #[test]
    fn same_length_eligibility_metadata_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["eligibility_decision"] = json!("awaiting_same_pod_72_hour_evidence");
        lock["remaining_gates"][0] = json!("one fastest copy exceeds 28 days");
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err(
                "Exchange V3 baseline status, runtime-parity refusal, or remaining gates drift"
                    .into()
            )
        );
    }

    #[test]
    fn m4_milestone_regression_is_rejected() {
        let fixture = Fixture::new();
        fixture.replace_once(
            &format!("exchange-v3-bsc/{BINDING_NAME}"),
            "milestone: M6",
            "milestone: M4",
        );
        assert_eq!(
            fixture.verify(),
            Err(
                "Exchange V3 target binding, M6 market snapshot, or fail-closed eligibility drift"
                    .into()
            )
        );
    }

    #[test]
    fn market_snapshot_contract_drift_is_rejected() {
        let fixture = Fixture::new();
        fixture.replace_once(
            &format!("exchange-v3-bsc/{BINDING_NAME}"),
            "chain: bsc",
            "chain: bsc\ngrt_24h: \"171.957\"",
        );
        assert_eq!(
            fixture.verify(),
            Err(
                "Exchange V3 target binding, M6 market snapshot, or fail-closed eligibility drift"
                    .into()
            )
        );
    }

    // The exact-source tree is materialized by
    // `scripts/verify-exchange-v3-bsc-source.sh` and is unavailable offline, so
    // the build gate is exercised with synthetic trees.
    #[test]
    fn exact_source_build_rejects_a_drifted_source_tree() {
        let fixture = Fixture::new();
        let source_root = tempfile::tempdir().unwrap();
        fs::write(source_root.path().join("package.json"), b"drifted\n").unwrap();
        let error = super::verify(
            &fixture.root,
            Path::new(LOCK_PATH),
            Some(source_root.path()),
        )
        .unwrap_err();
        assert_eq!(error, "exact source file drift: package.json");
    }

    #[test]
    fn exact_source_build_rejects_a_missing_source_tree() {
        let fixture = Fixture::new();
        let source_root = tempfile::tempdir().unwrap();
        let error = super::verify(
            &fixture.root,
            Path::new(LOCK_PATH),
            Some(source_root.path()),
        )
        .unwrap_err();
        assert!(error.starts_with("cannot read "), "{error}");
        assert!(error.contains("package.json"), "{error}");
    }

    #[test]
    fn duplicate_lock_keys_are_rejected() {
        let fixture = Fixture::new();
        let text = fs::read_to_string(fixture.path(LOCK_PATH)).unwrap();
        let drifted = text.replacen(
            "\"format_version\": 1,",
            "\"format_version\": 1,\n  \"family\": \"other\",",
            1,
        );
        assert_ne!(drifted, text, "lock fixture no longer starts as expected");
        fs::write(fixture.path(LOCK_PATH), drifted).unwrap();
        let error = fixture.verify().unwrap_err();
        assert!(error.starts_with("duplicate JSON key in "), "{error}");
        assert!(error.ends_with(": family"), "{error}");
    }

    #[test]
    fn vendored_paths_may_not_escape_the_repository_root() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["artifact_lock"][0]["vendored_path"] = json!("../escaped.yaml");
        fixture.write_lock(&lock);
        assert_eq!(
            fixture.verify(),
            Err("vendored path escapes repository root for deployment".into())
        );
    }

    #[test]
    fn local_schema_parser_treats_undecorated_entities_as_mutable() {
        let temporary = tempfile::tempdir().unwrap();
        let path = temporary.path().join("schema.graphql");
        fs::write(
            &path,
            "type A @entity {\n  id: ID!\n  amount: BigInt! # trailing\n}\n\
             type B @entity(immutable: true) {\n  id: Bytes!\n}\n\
             type C @entity(immutable: false) {\n  refs: [A!]!\n}\n\
             type D @entity(unsupported: true) {\n  id: ID!\n}\n",
        )
        .unwrap();
        let (entities, immutable, mutable) = parse_schema(&path).unwrap();
        assert_eq!(entities.len(), 3);
        assert_eq!(entities["A"]["amount"], "BigInt!");
        assert_eq!(entities["C"]["refs"], "[A!]!");
        assert_eq!(immutable, BTreeSet::from(["B".to_string()]));
        assert_eq!(mutable, BTreeSet::from(["A".to_string(), "C".to_string()]));
    }
}
