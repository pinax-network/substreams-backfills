//! Rust port of the retired `scripts/verify-pancakeswap-infinity-cl-bsc-target.py`
//! (#110): the immutable PancakeSwap Infinity CL BSC target and exact-source
//! baseline verifier. Every Python `fail(...)` becomes an `Err` carrying the
//! identical message, and every I/O, JSON, or YAML error also fails closed.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Component, Path, PathBuf};

use serde_json::{json, Value};

use crate::target_common::{
    abi_contract, cid_from_file, git_blob_hash, logical_hash, normalize_event, parse_schema,
    read_json, read_yaml, sha256_hex, unixfs_file_cidv0,
};

pub const LOCK_PATH: &str = "docs/provenance/pancakeswap-infinity-cl-bsc-target.json";

const PROFILE_PATH: &str = "pancakeswap-infinity-cl-bsc/layout-profile-v1.json";
const BINDING_PATH: &str =
    "pancakeswap-infinity-cl-bsc/QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz.yaml";
const PARENT_SCHEMA_PATH: &str =
    "uniswap-v4/artifacts/deployment/QmS1ehFzXTD9eA1f1EgjZvdyAj2EHtVNMrEN91H3pLuHMy/schema.graphql";
const CHILD_SCHEMA_PATH: &str =
    "uniswap-v4/artifacts/deployment/Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB/schema.graphql";

const EXPECTED_DEPLOYMENT: &str = "QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz";
const EXPECTED_SCHEMA: &str = "QmcWb81VRk9SycZYgLyr9i6tYCnHsVsPTyTvfNpywDRJfr";
const EXPECTED_SOURCE_REPOSITORY: &str = "https://github.com/NgoKimPhu/infinity-cl-subgraph";
const EXPECTED_SOURCE_COMMIT: &str = "40b0021be04cda3e32dde8e3cf0c3397863fc0c0";
const EXPECTED_SOURCE_TREE: &str = "b7a7778bc5c7f316cc46913b7b1d54ffcfa07c22";
const EXPECTED_SOURCE_PARENT: &str = "e53351269ab0bb9a265ab04d71189156f3fa03a8";
const EXPECTED_PROFILE_BYTES: usize = 9514;
const EXPECTED_PROFILE_SHA256: &str =
    "1429527858c3d3e38a760b5739f83a7020203ad8cdac099fdde3fa0e0ee365e2";

const EXPECTED_M0_GATE: &str = concat!(
    "M0: fully account for both required clusters by inventorying every current copy ",
    "or fresh structural absence proof; when viable healthy copies exist, independently ",
    "select the minimum stable same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all ",
    "viable copies, which may be different copies, and require both minima to exceed 28 ",
    "days or be non-converging; either minimum at or below 28 days stops implementation, ",
    "compute, and load; with no viable copy, require fresh structural absence proof from ",
    "both clusters.",
);

const EXPECTED_PROFILE_REMAINING_GATES: [&str; 4] = [
    EXPECTED_M0_GATE,
    "profile_driven_decoder_store_reducer_poi_writer_and_schema_implementation",
    "canonical_bsc_fixture_and_full_graph_node_differential_certification",
    "paused_restore_validation_and_separate_operational_activation_approval",
];

const EXPECTED_LOCK_REMAINING_GATES: [&str; 4] = [
    EXPECTED_M0_GATE,
    concat!(
        "Implement the profile-driven Pancake decoder, protobuf contract, Store ",
        "packages, reducer, POI, temporal writer, seed/replay, and schema paths ",
        "without changing the certified Uniswap V4 deployment.",
    ),
    concat!(
        "Capture canonical BSC event and metadata fixtures and prove complete Graph ",
        "Node entity, save-order, POI, VID, block-range, and PostgreSQL parity.",
    ),
    concat!(
        "Restore only into a disposable paused target and require separate operational ",
        "approval before allocation or activation.",
    ),
];

/// The six `reproduction_toolchain` keys re-checked against the installed
/// `package-lock.json` tree, in the Python dict's insertion order.
const TOOLCHAIN_PACKAGES: [(&str, &str, &str); 6] = [
    (
        "graph_cli",
        "node_modules/@graphprotocol/graph-cli",
        "0.64.1",
    ),
    ("graph_ts", "node_modules/@graphprotocol/graph-ts", "0.32.0"),
    ("assemblyscript", "node_modules/assemblyscript", "0.19.23"),
    (
        "binaryen",
        "node_modules/binaryen",
        "102.0.0-nightly.20211028",
    ),
    ("typescript", "node_modules/typescript", "3.9.9"),
    ("npm_run_all", "node_modules/npm-run-all", "4.1.5"),
];

fn expected_toolchain() -> Value {
    json!({
        "node": "24.13.1",
        "npm": "11.11.0",
        "package_lock_version": 3,
        "graph_cli": "0.64.1",
        "graph_ts": "0.32.0",
        "assemblyscript": "0.19.23",
        "binaryen": "102.0.0-nightly.20211028",
        "typescript": "3.9.9",
        "npm_run_all": "4.1.5",
        "relationship_to_historical_ci": "independent_byte_exact_reproduction_not_original_deployment_toolchain",
    })
}

fn expected_historical_source_ci() -> Value {
    json!({
        "workflow": ".github/workflows/CI.yml",
        "node": "18.x",
        "dependency_install": "yarn install",
        "build": "yarn build",
        "package_manager_version": Value::Null,
        "immutable_toolchain": false,
    })
}

/// `path -> (bytes, sha256, git_blob)`, in the Python dict's insertion order.
const EXPECTED_SOURCE_FILES: [(&str, u64, &str, &str); 8] = [
    (
        "package.json",
        1547,
        "216d2b1e9fe7f1fa853a50c325b715ef0c3aac180d6ebc4d07590349b806396d",
        "85349919ed10c0ef119d103285ad4af675dfa896",
    ),
    (
        "package-lock.json",
        402813,
        "2c6ef0c4e651cb9082ce64e3c9b7bb2f67728880a038190e1328a97808cf4c9e",
        "38f8e12ad7568140da676b9da965f7556c9bf464",
    ),
    (
        "yarn.lock",
        231900,
        "00635b81287cddc5eae332d71786ae352245f89c0682260fa53ed7d9e26e53a7",
        "a9af8809688e371a0fba18161785cbe24d0d0c36",
    ),
    (
        ".yarnrc.yml",
        25,
        "473e6def86fc03638120e0c01d0c8bbab095677256460fa4ea763e5d4697f270",
        "3186f3f0795ab612d5508593672dc9ad94bccca0",
    ),
    (
        "subgraph.yaml",
        2145,
        "6bcbee5032de14963e9c05a39fb2458a92c392705f000c9d9ee54cb4e82c0ecc",
        "c50ab98eb077325a335de3290cefbe78ab81d2bb",
    ),
    (
        "schema.graphql",
        13473,
        "af4a4495ef03ac1cb0228cc81b9d6033965715fca5b7ceaa039416fff8d02219",
        "17dfca6dee452ec2be30dbf756b67dbf2c9efc02",
    ),
    (
        "networks.json",
        262,
        "df96a2d83f1de3aec01d4f8b775b46c677a260e1dcc8c4066e8087fc82f08ef7",
        "f443cbcb5288e70b33ef1f7334820cb3a17acc7b",
    ),
    (
        ".github/workflows/CI.yml",
        1974,
        "497280d4df95f856f203161f757376f2f67e609b2ad8dd624c689a66e8c4eba6",
        "4b8a9ec86d2b261dfdee50360bae491c5b815d5f",
    ),
];

/// `path -> (bytes, sha256)`, in the Python dict's insertion order.
const EXPECTED_SOURCE_ABIS: [(&str, u64, &str); 5] = [
    (
        "abis/ERC20.json",
        3686,
        "929f801517d474eae12c45fc263502bc0644364854379f46a7bb273354d96d2e",
    ),
    (
        "abis/ERC20NameBytes.json",
        269,
        "f2931748c6851e1636b458030361de258db60441c353351e7eb4616c90039bce",
    ),
    (
        "abis/ERC20SymbolBytes.json",
        271,
        "6e114ca21ff78fcae5364358aec454862cdcef2cebdb541752e45ee84d38ace9",
    ),
    (
        "abis/PoolManager.json",
        28147,
        "4b09ffd628dca73228fdf699fbcbba11f6c5495cf5bdaf5922c1685bbe559392",
    ),
    (
        "abis/PositionManager.json",
        28827,
        "21d4794971609c029d880140151507b9f51e645667d487d4d34749a0e882d56e",
    ),
];

const EXPECTED_POOL_MANAGER_HANDLERS: [(&str, &str); 3] = [
    (
        "handleInitialize",
        "Initialize(indexed bytes32,indexed address,indexed address,address,uint24,bytes32,uint160,int24)",
    ),
    (
        "handleModifyLiquidity",
        "ModifyLiquidity(indexed bytes32,indexed address,int24,int24,int256,bytes32)",
    ),
    (
        "handleSwap",
        "Swap(indexed bytes32,indexed address,int128,int128,uint160,uint128,int24,uint24,uint16)",
    ),
];

const EXPECTED_POSITION_MANAGER_HANDLERS: [(&str, &str); 3] = [
    (
        "handleSubscription",
        "Subscription(indexed uint256,indexed address)",
    ),
    (
        "handleUnsubscription",
        "Unsubscription(indexed uint256,indexed address)",
    ),
    (
        "handleTransfer",
        "Transfer(indexed address,indexed address,indexed uint256)",
    ),
];

const EXPECTED_TOPICS: [(&str, &str); 6] = [
    (
        "handleInitialize",
        "0x426cc62fe6a33a40ba2788c2c87a9c34ee4582b95bc9fa5a7bb7ae70b750b99c",
    ),
    (
        "handleModifyLiquidity",
        "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec",
    ),
    (
        "handleSwap",
        "0x04206ad2b7c0f463bff3dd4f33c5735b0f2957a351e4f79763a4fa9e775dd237",
    ),
    (
        "handleSubscription",
        "0x9709492381f90bdc5938bb4e3b8e35b7e0eac8af058619e27191c5a40ce79fa9",
    ),
    (
        "handleUnsubscription",
        "0xa0ebb1de82db929a9153472f37d3a66dbede4436258311ad0f52a35a2c91d150",
    ),
    (
        "handleTransfer",
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
    ),
];

const EXPECTED_REQUIRED_CHANGES: [&str; 11] = [
    "profile_driven_network_deployment_address_and_start_block_validation",
    "pancake_initialize_and_swap_abi_decoders",
    "protobuf_fields_for_raw_parameters_hooks_registration_and_protocol_fee",
    "pool_state_poi_writer_and_seed_fields_for_parameters_and_hooks_registration",
    "bsc_native_token_stable_pool_whitelist_and_minimum_liquidity_configuration",
    "static_initialize_fee_policy_and_intentional_swap_fee_protocol_fee_ignores",
    "remove_base_arrakis_and_creator_content_hook_semantics",
    "make_all_seventeen_target_entities_temporal_and_mutable",
    "target_specific_substreams_packages_module_hashes_and_initial_blocks",
    "bsc_canonical_event_metadata_and_reducer_fixtures",
    "exact_graph_node_schema_poi_vid_and_postgresql_parity_certification",
];

const EXPECTED_MAPPING_EXPORTS: [&str; 6] = [
    "handleInitialize",
    "handleModifyLiquidity",
    "handleSubscription",
    "handleSwap",
    "handleTransfer",
    "handleUnsubscription",
];

const EXPECTED_ROLES: [&str; 8] = [
    "deployment",
    "schema",
    "erc20_abi",
    "erc20_name_bytes_abi",
    "erc20_symbol_bytes_abi",
    "pool_manager_abi",
    "position_manager_abi",
    "mapping_wasm",
];

/// The exact line the Python verifier printed on success.
pub const SUCCESS_LINE: &str = concat!(
    "verified all eight CIDv0 artifacts, exact manifest and 17-entity mutable schema, ",
    "V4 implementation-gap profile, exact source pin, historical-CI/reproduction ",
    "toolchain distinction, and fail-closed M5 binding",
);

fn fail<T>(message: impl Into<String>) -> Result<T, String> {
    Err(message.into())
}

static NULL: Value = Value::Null;

/// Python `mapping.get(key)`: a missing key and an explicit `null` both read
/// as `None`, and a non-object never carries the key.
fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    value.as_object().and_then(|m| m.get(key)).unwrap_or(&NULL)
}

/// Python `key in mapping` / `mapping.get(key, default)`, distinguishing an
/// absent key from one present and null.
fn lookup<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.as_object().and_then(|m| m.get(key))
}

/// Python `str(value)` for the scalar shapes a manifest can hold.
fn py_str(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::String(text) => text.clone(),
        other => other.to_string(),
    }
}

/// Python `repr` of a sorted list of strings; only the artifact-role drift
/// message embeds one.
fn py_repr_list(items: &BTreeSet<String>) -> String {
    let rendered: Vec<String> = items.iter().map(|item| format!("'{item}'")).collect();
    format!("[{}]", rendered.join(", "))
}

fn read_bytes(path: &Path) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_text(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))
}

/// Lexical stand-in for `Path.resolve()` on a path that need not exist:
/// `.` is dropped and `..` pops, so the root-escape check can run before the
/// read that would otherwise fail first.
fn resolve_lexical(base: &Path, relative: &str) -> PathBuf {
    let mut resolved = PathBuf::new();
    for component in base.join(relative).components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            Component::Prefix(prefix) => resolved = PathBuf::from(prefix.as_os_str()),
            Component::RootDir => resolved.push(Component::RootDir.as_os_str()),
            Component::Normal(part) => resolved.push(part),
        }
    }
    resolved
}

/// Python `root in path.parents`: `root` must be a strict ancestor.
fn is_strict_ancestor(root: &Path, path: &Path) -> bool {
    path.ancestors().skip(1).any(|ancestor| ancestor == root)
}

fn verify_artifact_lock(root: &Path, lock: &Value) -> Result<BTreeMap<String, Value>, String> {
    let Some(records) = lookup(lock, "artifact_lock").and_then(Value::as_array) else {
        return fail("artifact_lock must be a list");
    };
    let expected_roles: BTreeSet<String> =
        EXPECTED_ROLES.iter().map(|role| role.to_string()).collect();
    let mut artifacts: BTreeMap<String, Value> = BTreeMap::new();
    for record in records {
        let Some(role) = field(record, "role").as_str().map(str::to_string) else {
            return fail("artifact record must have a string role");
        };
        if artifacts.contains_key(&role) {
            return fail(format!("duplicate artifact role: {role}"));
        }
        artifacts.insert(role.clone(), record.clone());
        let Some(relative) = field(record, "path").as_str() else {
            return fail(format!("artifact path missing for {role}"));
        };
        let path = resolve_lexical(root, relative);
        if !is_strict_ancestor(root, &path) {
            return fail(format!("artifact path escapes root for {role}"));
        }
        let payload = read_bytes(&path)?;
        if &json!(payload.len()) != field(record, "bytes") {
            return fail(format!("artifact byte count drift for {role}"));
        }
        if &json!(sha256_hex(&payload)) != field(record, "sha256") {
            return fail(format!("artifact SHA-256 drift for {role}"));
        }
        if &json!(unixfs_file_cidv0(&payload)?) != field(record, "cid") {
            return fail(format!("artifact CIDv0 drift for {role}"));
        }
        if role.ends_with("_abi") {
            serde_json::from_slice::<Value>(&payload)
                .map_err(|error| format!("artifact {role} is not valid JSON: {error}"))?;
        }
        if role == "mapping_wasm" {
            if !payload.starts_with(b"\0asm\x01\0\0\0") {
                return fail("mapping artifact is not a WebAssembly v1 module");
            }
            if field(record, "exports") != &json!(EXPECTED_MAPPING_EXPORTS) {
                return fail("mapping export lock drift");
            }
            let missing_export = EXPECTED_MAPPING_EXPORTS.iter().any(|name| {
                !payload
                    .windows(name.len())
                    .any(|window| window == name.as_bytes())
            });
            if missing_export {
                return fail("mapping artifact is missing a locked handler export");
            }
        }
    }
    let present: BTreeSet<String> = artifacts.keys().cloned().collect();
    if present != expected_roles {
        let difference: BTreeSet<String> = present
            .symmetric_difference(&expected_roles)
            .cloned()
            .collect();
        return fail(format!(
            "artifact role drift: {}",
            py_repr_list(&difference)
        ));
    }
    if field(&artifacts["deployment"], "cid") != &json!(EXPECTED_DEPLOYMENT) {
        return fail("deployment CID lock drift");
    }
    if field(&artifacts["schema"], "cid") != &json!(EXPECTED_SCHEMA) {
        return fail("schema CID lock drift");
    }
    Ok(artifacts)
}

fn artifact_path(artifacts: &BTreeMap<String, Value>, role: &str) -> String {
    py_str(field(&artifacts[role], "path"))
}

fn verify_manifest(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let manifest = read_yaml(&root.join(artifact_path(artifacts, "deployment")))?;
    let deployment = field(lock, "deployment");
    if !manifest.is_object() || !deployment.is_object() {
        return fail("deployment manifests must be objects");
    }
    if field(&manifest, "specVersion") != &json!("0.0.4")
        || field(&manifest, "repository") != &json!(EXPECTED_SOURCE_REPOSITORY)
    {
        return fail("manifest identity drift");
    }
    if field(&manifest, "features") != &json!(["nonFatalErrors", "grafting"])
        || lookup(&manifest, "graft").is_some()
    {
        return fail("manifest feature or concrete-graft contract drift");
    }
    if cid_from_file(field(field(&manifest, "schema"), "file"))? != EXPECTED_SCHEMA {
        return fail("manifest schema CID drift");
    }
    let Some(data_sources) = lookup(&manifest, "dataSources").and_then(Value::as_array) else {
        return fail("manifest data-source order or inventory drift");
    };
    let names: Vec<&Value> = data_sources
        .iter()
        .map(|source| field(source, "name"))
        .collect();
    if names != vec![&json!("PoolManager"), &json!("PositionManager")] {
        return fail("manifest data-source order or inventory drift");
    }

    let expected_sources = json!({
        "PoolManager": {
            "abi": "PoolManager",
            "address": "0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b",
            "startBlock": 47214308,
        },
        "PositionManager": {
            "abi": "PositionManager",
            "address": "0x55f4c8abA71A1e923edC303eb4fEfF14608cC226",
            "startBlock": 47215015,
        },
    });
    let expected_abis: BTreeMap<&str, Vec<(String, String)>> = BTreeMap::from([
        (
            "PoolManager",
            vec![
                (
                    "ERC20".to_string(),
                    py_str(field(&artifacts["erc20_abi"], "cid")),
                ),
                (
                    "ERC20SymbolBytes".to_string(),
                    py_str(field(&artifacts["erc20_symbol_bytes_abi"], "cid")),
                ),
                (
                    "ERC20NameBytes".to_string(),
                    py_str(field(&artifacts["erc20_name_bytes_abi"], "cid")),
                ),
                (
                    "PoolManager".to_string(),
                    py_str(field(&artifacts["pool_manager_abi"], "cid")),
                ),
            ],
        ),
        (
            "PositionManager",
            vec![(
                "PositionManager".to_string(),
                py_str(field(&artifacts["position_manager_abi"], "cid")),
            )],
        ),
    ]);
    let expected_entities = json!({
        "PoolManager": ["Pool", "Token"],
        "PositionManager": ["Position"],
    });
    let expected_handlers: BTreeMap<&str, &[(&str, &str)]> = BTreeMap::from([
        ("PoolManager", &EXPECTED_POOL_MANAGER_HANDLERS[..]),
        ("PositionManager", &EXPECTED_POSITION_MANAGER_HANDLERS[..]),
    ]);

    for data_source in data_sources {
        let name = py_str(field(data_source, "name"));
        let mapping = field(data_source, "mapping");
        if field(data_source, "kind") != &json!("ethereum/contract")
            || field(data_source, "network") != &json!("bsc")
            || field(data_source, "source") != &expected_sources[&name]
            || !mapping.is_object()
        {
            return fail(format!("{name} source contract drift"));
        }
        if field(mapping, "kind") != &json!("ethereum/events")
            || field(mapping, "apiVersion") != &json!("0.0.7")
            || field(mapping, "language") != &json!("wasm/assemblyscript")
            || field(mapping, "entities") != &expected_entities[&name]
            || cid_from_file(field(mapping, "file"))?
                != py_str(field(&artifacts["mapping_wasm"], "cid"))
            || abi_contract(mapping)? != expected_abis[name.as_str()]
        {
            return fail(format!("{name} mapping contract drift"));
        }
        let actual_handlers: Vec<(Value, String)> = match field(mapping, "eventHandlers") {
            Value::Array(entries) => entries
                .iter()
                .map(|entry| {
                    let event = lookup(entry, "event").map(py_str).unwrap_or_default();
                    (field(entry, "handler").clone(), normalize_event(&event))
                })
                .collect(),
            _ => Vec::new(),
        };
        let expected: Vec<(Value, String)> = expected_handlers[name.as_str()]
            .iter()
            .map(|(handler, event)| (json!(handler), normalize_event(event)))
            .collect();
        if actual_handlers != expected {
            return fail(format!("{name} handler order or signature drift"));
        }
    }

    let expected_deployment_sources = json!([
        {
            "name": "PoolManager",
            "address": "0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b",
            "start_block": 47214308,
        },
        {
            "name": "PositionManager",
            "address": "0x55f4c8abA71A1e923edC303eb4fEfF14608cC226",
            "start_block": 47215015,
        },
    ]);
    if field(deployment, "cid") != &json!(EXPECTED_DEPLOYMENT)
        || field(deployment, "chain") != &json!("bsc")
        || field(deployment, "spec_version") != &json!("0.0.4")
        || field(deployment, "mapping_api_version") != &json!("0.0.7")
        || field(deployment, "features") != &json!(["nonFatalErrors", "grafting"])
        || !field(deployment, "concrete_graft").is_null()
        || field(deployment, "data_sources") != &expected_deployment_sources
    {
        return fail("provenance deployment contract drift");
    }
    Ok(())
}

fn verify_schema_contract(
    root: &Path,
    lock: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let target = parse_schema(&read_text(&root.join(artifact_path(artifacts, "schema")))?);
    let parent = parse_schema(&read_text(&root.join(PARENT_SCHEMA_PATH))?);
    let child = parse_schema(&read_text(&root.join(CHILD_SCHEMA_PATH))?);
    let contract = field(lock, "logical_contract");
    if !contract.is_object() {
        return fail("logical_contract must be an object");
    }
    if target.entities.len() != 17
        || logical_hash(&target.entities)
            != "e9bdfc5b10be66cd3c0ebead32cd31497ba3e0ad380e5ddffd9c1ecdc455641e"
    {
        return fail("Pancake logical schema drift");
    }
    let target_names: BTreeSet<String> = target.entities.keys().cloned().collect();
    if !target.immutable.is_empty() || target.explicit_mutable != target_names {
        return fail("all 17 Pancake entities must remain explicitly mutable");
    }
    if parent.entities.len() != 17
        || logical_hash(&parent.entities)
            != "caf9ba372feb9e9e1370d866f1b48d08cc8f10fb261075dc516e9e6e96e65e53"
    {
        return fail("imported Uniswap V4 parent logical reference drift");
    }
    let parent_names: BTreeSet<String> = parent.entities.keys().cloned().collect();
    if target_names != parent_names {
        return fail("Pancake and imported V4 parent entity sets diverged");
    }
    let mut differences: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::new();
    for (entity, fields) in &target.entities {
        let parent_fields = &parent.entities[entity];
        let added: BTreeMap<String, String> = fields
            .iter()
            .filter(|(key, _)| !parent_fields.contains_key(*key))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        let missing = parent_fields.keys().any(|key| !fields.contains_key(key));
        let changed = fields
            .iter()
            .any(|(key, value)| parent_fields.get(key).is_some_and(|other| other != value));
        if missing || changed {
            return fail(format!(
                "unexpected Pancake/V4 parent field or type difference in {entity}"
            ));
        }
        if !added.is_empty() {
            differences.insert(entity.clone(), added);
        }
    }
    let expected_gap: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::from([(
        "Pool".to_string(),
        BTreeMap::from([
            ("parameters".to_string(), "Bytes!".to_string()),
            ("hooksRegistration".to_string(), "Bytes!".to_string()),
        ]),
    )]);
    if differences != expected_gap {
        return fail("Pancake/V4 parent schema gap drift");
    }
    let child_names: BTreeSet<String> = child.entities.keys().cloned().collect();
    let child_only: BTreeSet<&String> = child_names.difference(&parent_names).collect();
    let parent_only: BTreeSet<&String> = parent_names.difference(&child_names).collect();
    let arrakis = "ArrakisHook".to_string();
    if child_only != BTreeSet::from([&arrakis]) || !parent_only.is_empty() {
        return fail("imported V4 child ArrakisHook reference drift");
    }
    let expected_immutable: BTreeSet<String> = [
        "Transaction",
        "Swap",
        "ModifyLiquidity",
        "Subscribe",
        "Unsubscribe",
        "Transfer",
    ]
    .iter()
    .map(|name| name.to_string())
    .collect();
    if child.immutable != expected_immutable {
        return fail("imported V4 child immutable-event reference drift");
    }
    let mutability_difference: BTreeSet<String> =
        match lookup(contract, "runtime_critical_mutability_difference") {
            None => BTreeSet::new(),
            Some(Value::Array(items)) => items.iter().map(py_str).collect(),
            Some(_) => return fail("provenance logical schema contract drift"),
        };
    if field(contract, "entity_count") != &json!(17)
        || field(contract, "logical_sha256") != &json!(logical_hash(&target.entities))
        || field(contract, "immutable_entities") != &json!([])
        || field(contract, "all_entities_mutable") != &Value::Bool(true)
        || mutability_difference != expected_immutable
    {
        return fail("provenance logical schema contract drift");
    }
    Ok(())
}

fn verify_profile(root: &Path, lock: &Value) -> Result<(), String> {
    let profile_payload = read_bytes(&root.join(PROFILE_PATH))?;
    if profile_payload.len() != EXPECTED_PROFILE_BYTES
        || sha256_hex(&profile_payload) != EXPECTED_PROFILE_SHA256
    {
        return fail("machine-readable layout profile digest drift");
    }
    if field(lock, "layout_profile")
        != &json!({
            "path": PROFILE_PATH,
            "bytes": EXPECTED_PROFILE_BYTES,
            "sha256": EXPECTED_PROFILE_SHA256,
        })
    {
        return fail("layout profile provenance lock drift");
    }
    let profile: Value = serde_json::from_slice(&profile_payload)
        .map_err(|error| format!("cannot parse {PROFILE_PATH}: {error}"))?;
    if field(&profile, "format_version") != &json!(1)
        || field(&profile, "status") != &json!("immutable_target_contract_only")
        || field(field(&profile, "deployment"), "cid") != &json!(EXPECTED_DEPLOYMENT)
        || !field(field(&profile, "deployment"), "graft").is_null()
    {
        return fail("layout profile identity or status drift");
    }
    let mut profile_handlers: BTreeMap<String, Value> = BTreeMap::new();
    if let Some(sources) = field(&profile, "data_sources").as_array() {
        for source in sources {
            let Some(handlers) = field(source, "handlers").as_array() else {
                continue;
            };
            for handler in handlers {
                let (Some(name), Some(topic)) =
                    (lookup(handler, "name"), lookup(handler, "topic0"))
                else {
                    return fail("layout profile handler entry is missing name or topic0");
                };
                profile_handlers.insert(py_str(name), topic.clone());
            }
        }
    }
    let expected_topics: BTreeMap<String, Value> = EXPECTED_TOPICS
        .iter()
        .map(|(name, topic)| (name.to_string(), json!(topic)))
        .collect();
    if profile_handlers != expected_topics {
        return fail("layout profile event-topic contract drift");
    }
    let pool_key = field(&profile, "pool_key");
    let parameters = field(pool_key, "parameters");
    if field(pool_key, "pool_id_strategy") != &json!("authoritative_initialize_event_id_bytes32")
        || field(pool_key, "recompute_pool_id") != &Value::Bool(false)
        || field(pool_key, "contract_tuple_fields")
            != &json!([
                "currency0",
                "currency1",
                "hooks",
                "poolManager",
                "fee",
                "parameters"
            ])
        || field(field(parameters, "hooks_registration"), "byte_slice") != &json!([30, 32])
        || field(field(parameters, "tick_spacing"), "byte_slice") != &json!([27, 30])
        || field(field(parameters, "tick_spacing"), "operation")
            != &json!("reverse_then_graph_bigint_from_byte_array")
    {
        return fail("Pancake PoolKey or parameter decoding contract drift");
    }
    if field(&profile, "fee_and_protocol")
        != &json!({
            "pool_fee_tier_source": "initialize.fee",
            "swap_event_fee": "decoded_for_signature_but_ignored_by_mapping",
            "swap_protocol_fee": "decoded_for_signature_but_ignored_by_mapping",
            "dynamic_lp_fee_updated_handler": false,
            "protocol_fee_updated_handler": false,
            "fee_amount_formula": "tracked_swap_amount_times_pool_fee_tier_div_1000000",
            "protocol_fee_entity_or_aggregate": false,
        })
    {
        return fail("Pancake fee/protocol behavior contract drift");
    }
    let positions = field(&profile, "positions");
    if field(positions, "created_by") != &json!("first_position_manager_transfer")
        || field(positions, "owner_update") != &json!("every_position_manager_transfer_to_address")
        || field(positions, "burn_delete") != &Value::Bool(false)
        || field(positions, "subscription_mutates_position") != &Value::Bool(false)
        || field(positions, "unsubscription_mutates_position") != &Value::Bool(false)
        || field(positions, "position_manager_modify_liquidity_handler") != &Value::Bool(false)
    {
        return fail("Pancake position/subscription/transfer behavior contract drift");
    }
    let pricing = field(&profile, "pricing");
    if field(pricing, "stablecoin_wrapped_native_pool_id")
        != &json!("0x752e76950f6167b8dbb0495b957d264d61724dfa26e3dd6fad1ba820862ce9cf")
        || field(pricing, "stablecoin_is_token0") != &Value::Bool(false)
        || field(pricing, "wrapped_native_address")
            != &json!("0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c")
        || field(pricing, "minimum_native_locked") != &json!("10")
        || field(pricing, "native_token")
            != &json!({"symbol": "BNB", "name": "Binance Coin", "decimals": 18})
    {
        return fail("Pancake BSC pricing configuration drift");
    }
    if field(
        field(&profile, "uniswap_v4_prior_art"),
        "required_target_changes",
    ) != &json!(EXPECTED_REQUIRED_CHANGES)
    {
        return fail("complete Pancake implementation-gap list drift");
    }
    if field(&profile, "remaining_gates") != &json!(EXPECTED_PROFILE_REMAINING_GATES) {
        return fail("Pancake remaining gate list drift");
    }
    Ok(())
}

fn verify_source_pin(lock: &Value, artifacts: &BTreeMap<String, Value>) -> Result<(), String> {
    let source = field(lock, "exact_source");
    if !source.is_object() {
        return fail("exact_source must be an object");
    }
    if field(source, "status") != &json!("exact_reproduction")
        || field(source, "repository") != &json!(EXPECTED_SOURCE_REPOSITORY)
        || field(source, "commit") != &json!(EXPECTED_SOURCE_COMMIT)
        || field(source, "tree") != &json!(EXPECTED_SOURCE_TREE)
        || field(source, "parent") != &json!(EXPECTED_SOURCE_PARENT)
        || field(source, "tracked_file_count") != &json!(58)
        || field(source, "historical_source_ci") != &expected_historical_source_ci()
        || field(source, "reproduction_toolchain") != &expected_toolchain()
    {
        return fail("exact source commit/tree/toolchain lock drift");
    }
    let mut actual_source_files: BTreeMap<String, (Value, Value, Value)> = BTreeMap::new();
    if let Some(items) = field(source, "source_files").as_array() {
        for item in items {
            actual_source_files.insert(
                py_str(field(item, "path")),
                (
                    field(item, "bytes").clone(),
                    field(item, "sha256").clone(),
                    field(item, "git_blob").clone(),
                ),
            );
        }
    }
    let expected_source_files: BTreeMap<String, (Value, Value, Value)> = EXPECTED_SOURCE_FILES
        .iter()
        .map(|(path, bytes, digest, blob)| {
            (path.to_string(), (json!(bytes), json!(digest), json!(blob)))
        })
        .collect();
    if actual_source_files != expected_source_files {
        return fail("exact source key-file lock drift");
    }
    let mut actual_source_abis: BTreeMap<String, (Value, Value)> = BTreeMap::new();
    if let Some(items) = field(source, "source_abi_payloads").as_array() {
        for item in items {
            actual_source_abis.insert(
                py_str(field(item, "path")),
                (field(item, "bytes").clone(), field(item, "sha256").clone()),
            );
        }
    }
    let expected_source_abis: BTreeMap<String, (Value, Value)> = EXPECTED_SOURCE_ABIS
        .iter()
        .map(|(path, bytes, digest)| (path.to_string(), (json!(bytes), json!(digest))))
        .collect();
    if actual_source_abis != expected_source_abis {
        return fail("exact source ABI lock drift");
    }
    let build = field(source, "build");
    if field(build, "method") != &json!("independent_byte_exact_reproduction")
        || field(build, "commands")
            != &json!([
                "npm ci --legacy-peer-deps --ignore-scripts",
                "npm run build"
            ])
        || field(build, "generated_manifest_bytes") != &json!(2195)
        || field(build, "generated_manifest_sha256")
            != &json!("3d466cb0e39c5d02c9204feae156192984f735ef00488577d0660b8d15343ada")
        || field(build, "mapping_bytes") != field(&artifacts["mapping_wasm"], "bytes")
        || field(build, "mapping_sha256") != field(&artifacts["mapping_wasm"], "sha256")
        || field(build, "result") != &json!("byte_exact_to_all_deployed_child_artifacts")
    {
        return fail("exact source build lock drift");
    }
    Ok(())
}

fn local_path_from_file(value: &Value) -> Result<String, String> {
    let accepted = value.as_str().filter(|text| {
        !text.starts_with('/')
            && !Path::new(text)
                .components()
                .any(|component| component == Component::ParentDir)
    });
    match accepted {
        Some(text) => Ok(text.to_string()),
        None => fail(format!(
            "unexpected generated-manifest path: {}",
            match value {
                Value::String(text) => format!("'{text}'"),
                other => py_str(other),
            }
        )),
    }
}

fn replace_generated_files_with_cids(value: &Value, source_root: &Path) -> Result<Value, String> {
    match value {
        Value::Object(entries) => {
            let mut output = serde_json::Map::new();
            for (key, item) in entries {
                if key == "file" {
                    let relative = local_path_from_file(item)?;
                    let payload = read_bytes(&source_root.join("build").join(&relative))?;
                    output.insert(
                        key.clone(),
                        json!({ "/": format!("/ipfs/{}", unixfs_file_cidv0(&payload)?) }),
                    );
                } else {
                    output.insert(
                        key.clone(),
                        replace_generated_files_with_cids(item, source_root)?,
                    );
                }
            }
            Ok(Value::Object(output))
        }
        Value::Array(items) => items
            .iter()
            .map(|item| replace_generated_files_with_cids(item, source_root))
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
    let source = field(lock, "exact_source");
    for (relative, bytes, digest, blob) in EXPECTED_SOURCE_FILES {
        let payload = read_bytes(&source_root.join(relative))?;
        if payload.len() as u64 != bytes
            || sha256_hex(&payload) != digest
            || git_blob_hash(&payload) != blob
        {
            return fail(format!("exact source key-file mismatch: {relative}"));
        }
    }
    for (relative, bytes, digest) in EXPECTED_SOURCE_ABIS {
        let payload = read_bytes(&source_root.join(relative))?;
        if payload.len() as u64 != bytes || sha256_hex(&payload) != digest {
            return fail(format!("exact source ABI mismatch: {relative}"));
        }
    }

    let built_manifest_payload = read_bytes(&source_root.join("build/subgraph.yaml"))?;
    let build = field(source, "build");
    if &json!(built_manifest_payload.len()) != field(build, "generated_manifest_bytes")
        || &json!(sha256_hex(&built_manifest_payload)) != field(build, "generated_manifest_sha256")
    {
        return fail("generated exact-source manifest byte drift");
    }
    let built_manifest = read_yaml(&source_root.join("build/subgraph.yaml"))?;
    let deployed_manifest = read_yaml(&root.join(artifact_path(artifacts, "deployment")))?;
    if replace_generated_files_with_cids(&built_manifest, source_root)? != deployed_manifest {
        return fail("generated manifest does not resolve exactly to deployed artifact links");
    }

    let built_artifacts: [(&str, &str); 7] = [
        ("schema", "build/schema.graphql"),
        ("erc20_abi", "build/PoolManager/abis/ERC20.json"),
        (
            "erc20_name_bytes_abi",
            "build/PoolManager/abis/ERC20NameBytes.json",
        ),
        (
            "erc20_symbol_bytes_abi",
            "build/PoolManager/abis/ERC20SymbolBytes.json",
        ),
        (
            "pool_manager_abi",
            "build/PoolManager/abis/PoolManager.json",
        ),
        (
            "position_manager_abi",
            "build/PositionManager/abis/PositionManager.json",
        ),
        ("mapping_wasm", "build/PoolManager/PoolManager.wasm"),
    ];
    for (role, relative) in built_artifacts {
        let built_payload = read_bytes(&source_root.join(relative))?;
        let deployed_payload = read_bytes(&root.join(artifact_path(artifacts, role)))?;
        if built_payload != deployed_payload {
            return fail(format!(
                "exact source build is not byte-identical for {role}"
            ));
        }
    }
    let normalized_abis: [(&str, &str); 5] = [
        ("abis/ERC20.json", "erc20_abi"),
        ("abis/ERC20NameBytes.json", "erc20_name_bytes_abi"),
        ("abis/ERC20SymbolBytes.json", "erc20_symbol_bytes_abi"),
        ("abis/PoolManager.json", "pool_manager_abi"),
        ("abis/PositionManager.json", "position_manager_abi"),
    ];
    for (relative, deployed_role) in normalized_abis {
        let source_payload = read_bytes(&source_root.join(relative))?;
        let mut deployed_payload = read_bytes(&root.join(artifact_path(artifacts, deployed_role)))?;
        deployed_payload.push(b'\n');
        if source_payload != deployed_payload {
            return fail(format!(
                "Graph CLI one-trailing-LF ABI normalization drift: {relative}"
            ));
        }
    }

    let package_lock = read_json(&source_root.join("package-lock.json"))?;
    if !package_lock.is_object() || field(&package_lock, "lockfileVersion") != &json!(3) {
        return fail("exact source package-lock version drift");
    }
    let packages = field(&package_lock, "packages");
    let mut installed: Vec<(&str, Value, &str)> = Vec::new();
    for (key, module, expected) in TOOLCHAIN_PACKAGES {
        let Some(entry) = lookup(packages, module) else {
            return fail(format!("exact source package-lock entry missing: {module}"));
        };
        let Some(version) = lookup(entry, "version") else {
            return fail(format!(
                "exact source package-lock version missing: {module}"
            ));
        };
        installed.push((key, version.clone(), expected));
    }
    for (key, actual, expected) in installed {
        if actual != json!(expected) {
            return fail(format!("locked exact-source package drift: {key}"));
        }
    }
    Ok(())
}

fn verify_binding(root: &Path) -> Result<(), String> {
    let binding = read_yaml(&root.join(BINDING_PATH))?;
    let leaked_market_field = binding.as_object().is_some_and(|fields| {
        fields.keys().any(|name| {
            name != "market_snapshot"
                && (name.starts_with("market_")
                    || name.starts_with("qos_")
                    || name.starts_with("query_fee")
                    || name.contains("grt")
                    || matches!(
                        name.as_str(),
                        "queries_24h" | "query_count_24h" | "fees_24h"
                    ))
        })
    });
    let latest = field(field(&binding, "eligibility"), "latest");
    if !binding.is_object()
        || field(&binding, "deployment") != &json!(EXPECTED_DEPLOYMENT)
        || field(&binding, "family") != &json!("pancakeswap-infinity-cl-bsc")
        || field(&binding, "chain") != &json!("bsc")
        || field(&binding, "milestone") != &json!("M5")
        || field(&binding, "market_snapshot")
            != &json!({
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 25405,
                "query_fees_grt_24h": "30.041",
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
            })
        || leaked_market_field
        || field(latest, "decision") != &json!("indeterminate")
        || field(latest, "reason") != &json!("no_fresh_evidence")
    {
        return fail(
            "Pancake target binding, M5 market snapshot, or fail-closed eligibility drift",
        );
    }
    Ok(())
}

/// Verify the pinned PancakeSwap Infinity CL BSC target baseline rooted at
/// `root`, with `lock` relative to it. When `exact_source_root` is supplied,
/// the byte-exact source reproduction checks run as well against the tree
/// materialized by `scripts/verify-pancakeswap-infinity-cl-bsc-source.sh`.
pub fn verify(
    root: &Path,
    lock: &Path,
    exact_source_root: Option<&Path>,
) -> Result<String, String> {
    let root = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve {}: {error}", root.display()))?;
    let lock_value = read_json(&root.join(lock))?;
    if !lock_value.is_object() || field(&lock_value, "format_version") != &json!(1) {
        return fail("unsupported Pancake target lock");
    }
    if field(&lock_value, "family") != &json!("pancakeswap-infinity-cl-bsc")
        || field(&lock_value, "implementation_status")
            != &json!("immutable_target_and_exact_source_baseline_only")
        || field(&lock_value, "runtime_parity") != &Value::Bool(false)
        || field(&lock_value, "eligibility_decision") != &json!("indeterminate_no_fresh_evidence")
        || field(&lock_value, "remaining_gates") != &json!(EXPECTED_LOCK_REMAINING_GATES)
    {
        return fail("Pancake baseline status, runtime-parity refusal, or remaining gates drift");
    }
    let artifacts = verify_artifact_lock(&root, &lock_value)?;
    verify_manifest(&root, &lock_value, &artifacts)?;
    verify_schema_contract(&root, &lock_value, &artifacts)?;
    verify_profile(&root, &lock_value)?;
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

    const BINDING_NAME: &str = "QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz.yaml";
    const PARENT_DEPLOYMENT: &str = "QmS1ehFzXTD9eA1f1EgjZvdyAj2EHtVNMrEN91H3pLuHMy";
    const CHILD_DEPLOYMENT: &str = "Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB";
    const STATUS_DRIFT: &str =
        "Pancake baseline status, runtime-parity refusal, or remaining gates drift";
    const BINDING_DRIFT: &str =
        "Pancake target binding, M5 market snapshot, or fail-closed eligibility drift";
    const SOURCE_PIN_DRIFT: &str = "exact source commit/tree/toolchain lock drift";

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    fn copy_tree(from: &Path, to: &Path) {
        fs::create_dir_all(to).expect("create destination");
        for entry in fs::read_dir(from).expect("read source directory") {
            let entry = entry.expect("directory entry");
            let destination = to.join(entry.file_name());
            if entry.file_type().expect("entry type").is_dir() {
                copy_tree(&entry.path(), &destination);
            } else {
                fs::copy(entry.path(), &destination).expect("copy file");
            }
        }
    }

    /// Mirror of the Python suite's `setUp`: the family directory, both
    /// imported Uniswap V4 reference schemas, and the provenance lock.
    fn fixture() -> tempfile::TempDir {
        let temporary = tempfile::tempdir().expect("temporary directory");
        let root = temporary.path();
        let repository = repository();
        copy_tree(
            &repository.join("pancakeswap-infinity-cl-bsc"),
            &root.join("pancakeswap-infinity-cl-bsc"),
        );
        for deployment in [PARENT_DEPLOYMENT, CHILD_DEPLOYMENT] {
            let destination = root
                .join("uniswap-v4/artifacts/deployment")
                .join(deployment);
            fs::create_dir_all(&destination).expect("create deployment directory");
            fs::copy(
                repository
                    .join("uniswap-v4/artifacts/deployment")
                    .join(deployment)
                    .join("schema.graphql"),
                destination.join("schema.graphql"),
            )
            .expect("copy reference schema");
        }
        fs::create_dir_all(root.join("docs/provenance")).expect("create provenance directory");
        fs::copy(repository.join(LOCK_PATH), root.join(LOCK_PATH)).expect("copy lock");
        temporary
    }

    fn run(root: &Path) -> Result<String, String> {
        verify(root, Path::new(LOCK_PATH), None)
    }

    fn load_lock(root: &Path) -> Value {
        serde_json::from_str(&fs::read_to_string(root.join(LOCK_PATH)).expect("read lock"))
            .expect("parse lock")
    }

    fn write_lock(root: &Path, lock: &Value) {
        let rendered = format!(
            "{}\n",
            serde_json::to_string_pretty(lock).expect("render lock")
        );
        fs::write(root.join(LOCK_PATH), rendered).expect("write lock");
    }

    fn rewrite(path: &Path, from: &str, to: &str, once: bool) {
        let text = fs::read_to_string(path).expect("read file");
        let replaced = if once {
            text.replacen(from, to, 1)
        } else {
            text.replace(from, to)
        };
        assert_ne!(text, replaced, "drift injection matched nothing: {from}");
        fs::write(path, replaced).expect("write file");
    }

    #[test]
    fn exact_baseline_passes() {
        assert_eq!(run(&repository()), Ok(SUCCESS_LINE.to_string()));
    }

    #[test]
    fn artifact_byte_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        rewrite(
            &root.join("pancakeswap-infinity-cl-bsc/reference/schema.graphql"),
            "type Bundle",
            "type BundleDrift",
            true,
        );
        assert_eq!(
            run(root),
            Err("artifact byte count drift for schema".to_string())
        );
    }

    #[test]
    fn manifest_semantic_drift_is_rejected_after_digest_relock() {
        let fixture = fixture();
        let root = fixture.path();
        let manifest = root.join("pancakeswap-infinity-cl-bsc/reference/deployment.yaml");
        rewrite(&manifest, "network: bsc", "network: mainnet", true);
        let payload = fs::read(&manifest).expect("read manifest");
        let mut lock = load_lock(root);
        let record = lock["artifact_lock"]
            .as_array_mut()
            .expect("artifact list")
            .iter_mut()
            .find(|item| item["role"] == json!("deployment"))
            .expect("deployment record");
        record["bytes"] = json!(payload.len());
        record["sha256"] = json!(sha256_hex(&payload));
        write_lock(root, &lock);
        // Only the byte count and SHA-256 are relocked, so the edit is caught
        // at the CIDv0 recomputation before any semantic check can run.
        assert_eq!(
            run(root),
            Err("artifact CIDv0 drift for deployment".to_string())
        );
    }

    #[test]
    fn profile_fee_policy_drift_is_rejected_after_provenance_relock() {
        let fixture = fixture();
        let root = fixture.path();
        let profile_path = root.join(PROFILE_PATH);
        let mut profile: Value =
            serde_json::from_str(&fs::read_to_string(&profile_path).expect("read profile"))
                .expect("parse profile");
        profile["fee_and_protocol"]["swap_event_fee"] = json!("used_as_effective_fee");
        fs::write(
            &profile_path,
            format!(
                "{}\n",
                serde_json::to_string_pretty(&profile).expect("render profile")
            ),
        )
        .expect("write profile");
        let payload = fs::read(&profile_path).expect("read profile bytes");
        let mut lock = load_lock(root);
        lock["layout_profile"]["bytes"] = json!(payload.len());
        lock["layout_profile"]["sha256"] = json!(sha256_hex(&payload));
        write_lock(root, &lock);
        assert_eq!(
            run(root),
            Err("machine-readable layout profile digest drift".to_string())
        );
    }

    #[test]
    fn imported_v4_prior_art_schema_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        rewrite(
            &root
                .join("uniswap-v4/artifacts/deployment")
                .join(PARENT_DEPLOYMENT)
                .join("schema.graphql"),
            "type Position ",
            "type PositionDrift ",
            true,
        );
        assert_eq!(
            run(root),
            Err("imported Uniswap V4 parent logical reference drift".to_string())
        );
    }

    #[test]
    fn runtime_parity_claim_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let mut lock = load_lock(root);
        lock["runtime_parity"] = json!(true);
        lock["implementation_status"] = json!("runtime_complete");
        write_lock(root, &lock);
        assert_eq!(run(root), Err(STATUS_DRIFT.to_string()));
    }

    #[test]
    fn eligibility_metadata_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let mut lock = load_lock(root);
        lock["eligibility_decision"] = json!("awaiting_same_pod_72_hour_evidence");
        lock["remaining_gates"][0] = json!("one fastest copy exceeds 28 days");
        write_lock(root, &lock);
        assert_eq!(run(root), Err(STATUS_DRIFT.to_string()));
    }

    #[test]
    fn exact_source_status_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let mut lock = load_lock(root);
        lock["exact_source"]["status"] = json!("candidate");
        write_lock(root, &lock);
        assert_eq!(run(root), Err(SOURCE_PIN_DRIFT.to_string()));
    }

    #[test]
    fn historical_ci_cannot_be_conflated_with_reproduction_toolchain() {
        let fixture = fixture();
        let root = fixture.path();
        let mut lock = load_lock(root);
        lock["exact_source"]["historical_source_ci"]["node"] = json!("24.13.1");
        lock["exact_source"]["historical_source_ci"]["dependency_install"] =
            json!("npm ci --legacy-peer-deps --ignore-scripts");
        write_lock(root, &lock);
        assert_eq!(run(root), Err(SOURCE_PIN_DRIFT.to_string()));
    }

    #[test]
    fn m4_milestone_regression_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        rewrite(
            &root.join("pancakeswap-infinity-cl-bsc").join(BINDING_NAME),
            "milestone: M5",
            "milestone: M4",
            false,
        );
        assert_eq!(run(root), Err(BINDING_DRIFT.to_string()));
    }

    #[test]
    fn market_snapshot_contract_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        rewrite(
            &root.join("pancakeswap-infinity-cl-bsc").join(BINDING_NAME),
            "chain: bsc",
            "chain: bsc\ngeneric_grt: \"30.041\"",
            true,
        );
        assert_eq!(run(root), Err(BINDING_DRIFT.to_string()));
    }

    // Coverage the Python suite never reached: the exact-source tree is
    // materialized out of band by the source shell script, so only synthetic
    // failure cases can be exercised here.

    #[test]
    fn missing_exact_source_root_fails_closed() {
        let fixture = fixture();
        let root = fixture.path();
        let absent = root.join("no-such-source-tree");
        let outcome = verify(root, Path::new(LOCK_PATH), Some(&absent));
        assert!(
            outcome
                .as_ref()
                .err()
                .is_some_and(|message| message.starts_with("cannot resolve ")),
            "unexpected outcome: {outcome:?}"
        );
    }

    #[test]
    fn synthetic_exact_source_tree_is_rejected_on_the_first_key_file() {
        let fixture = fixture();
        let root = fixture.path();
        let source_root = root.join("synthetic-source");
        fs::create_dir_all(&source_root).expect("create synthetic source root");
        fs::write(source_root.join("package.json"), b"{}\n").expect("write package.json");
        assert_eq!(
            verify(root, Path::new(LOCK_PATH), Some(&source_root)),
            Err("exact source key-file mismatch: package.json".to_string())
        );
    }

    #[test]
    fn artifact_paths_may_not_escape_the_root() {
        let fixture = fixture();
        let root = fixture.path();
        let mut lock = load_lock(root);
        lock["artifact_lock"][0]["path"] = json!("../outside/deployment.yaml");
        write_lock(root, &lock);
        assert_eq!(
            run(root),
            Err("artifact path escapes root for deployment".to_string())
        );
    }

    #[test]
    fn generated_manifest_paths_reject_traversal_and_absolutes() {
        assert_eq!(
            local_path_from_file(&json!("PoolManager/PoolManager.wasm")),
            Ok("PoolManager/PoolManager.wasm".to_string())
        );
        assert_eq!(
            local_path_from_file(&json!("/etc/passwd")),
            Err("unexpected generated-manifest path: '/etc/passwd'".to_string())
        );
        assert_eq!(
            local_path_from_file(&json!("../escape.json")),
            Err("unexpected generated-manifest path: '../escape.json'".to_string())
        );
        assert_eq!(
            local_path_from_file(&Value::Null),
            Err("unexpected generated-manifest path: None".to_string())
        );
    }
}
