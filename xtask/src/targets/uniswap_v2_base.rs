//! Rust port of the retired `scripts/verify-uniswap-v2-base-target.py` (#110): the
//! immutable Uniswap V2 Base target, its layout profile, its target binding,
//! the bounded M8 roadmap entry, and the fail-closed behavioral-source and
//! generic-extractor baselines.
//!
//! Like the Python entry point, source mode takes the behavioral candidate
//! (`--source-root`) and the generic extractor (`--generic-source-root`)
//! together; `scripts/verify-uniswap-v2-base-source.sh` materializes both.

use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::de::{self, DeserializeSeed, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{json, Map, Value};

use crate::target_common::sha256_hex;

pub const LOCK_PATH: &str = "docs/provenance/uniswap-v2-base-target.json";

const DEPLOYMENT: &str = "QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8";
const SCHEMA_CID: &str = "QmeyYQ8ZJnzuQsoXnizGXLyFSt7mcuRNkmNQxMv3pXiMnW";
const FACTORY: &str = "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6";
const START_BLOCK: u64 = 6_601_915;
const BINDING_PATH: &str = "uniswap-v2-base/QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8.yaml";
const SOURCE_COMMIT: &str = "6fba1a6f7304df83c08c3555bc90a38028f1435c";
const SOURCE_TREE: &str = "c80a1d0ddfb378a1fd7e9177e59a94420b01bd5e";
const GENERIC_COMMIT: &str = "970a665e15619de8ad7f686bd89412a1030d46dc";
const GENERIC_TREE: &str = "eac7466daba7f89a8c3b2e4742fcf24a155a2c24";
const LOGICAL_SHA256: &str = "7d249e34390b4eaaeca84e0fd5638e071fcd812a10813a03d284cf94a0dff5a2";
const PROFILE_CANONICAL_SHA256: &str =
    "cb27545302d5f3ae7c80c3651d828f9c800dd4f48eef7cf87c8de19bf155b6c8";
const TARGET_SCHEMA_SHA256: &str =
    "310d8ce01f22505f20f8654e60fb67ac29a0a0c11d7e4fc19d57f5c23b4f1d97";

/// Ordered exactly like the Python `LOCK_SECTION_SHA256` dict: the first
/// mismatching section names the failure.
const LOCK_SECTION_SHA256: [(&str, &str); 7] = [
    (
        "deployment",
        "4b5085167331ac007aa70edd24b325a123df87a364e556c8718a92fa564148bb",
    ),
    (
        "artifact_lock",
        "41b89c98b1e558718fa8c1cf424294f9ed9148ea91dc7feaf6386e6ae4da503c",
    ),
    (
        "layout_profile",
        "d7d4eb9f40302b97460e2e1dcd800df0e585098e4ab5416b5de3573792a6d9c5",
    ),
    (
        "logical_contract",
        "ab160572d11461936d229de50910e257ed89b62dd83f5a21a81f1d7091397083",
    ),
    (
        "source_evidence",
        "127a0ace05b87311c10af806d3a6f3259162b5d14caccdd7c85f1c0f560b7ea7",
    ),
    (
        "generic_event_extractor",
        "addec4e3e33a3658712102a5c45e94d381f44513a65bc86107fc0c26bde1efcc",
    ),
    (
        "truth_gates",
        "7a4da0d932f4fcebe4a3f2fbd92a279ff1f6a26e9b8c2dc8af6316771780aa65",
    ),
];

const EXPECTED_ROLES: [&str; 9] = [
    "deployment",
    "schema",
    "factory_abi",
    "erc20_abi",
    "erc20_symbol_bytes_abi",
    "erc20_name_bytes_abi",
    "pair_abi",
    "factory_mapping_wasm",
    "pair_mapping_wasm",
];

const EXPECTED_FACTORY_HANDLER: [(&str, &str); 1] = [(
    "handleNewPair",
    "PairCreated(indexed address,indexed address,address,uint256)",
)];

const EXPECTED_PAIR_HANDLERS: [(&str, &str); 5] = [
    ("handleMint", "Mint(indexed address,uint256,uint256)"),
    (
        "handleBurn",
        "Burn(indexed address,uint256,uint256,indexed address)",
    ),
    (
        "handleSwap",
        "Swap(indexed address,uint256,uint256,uint256,uint256,indexed address)",
    ),
    (
        "handleTransfer",
        "Transfer(indexed address,indexed address,uint256)",
    ),
    ("handleSync", "Sync(uint112,uint112)"),
];

const EXPECTED_ENTITIES: [&str; 15] = [
    "Bundle",
    "Burn",
    "Mint",
    "Pair",
    "PairDayData",
    "PairHourData",
    "PairTokenLookup",
    "Swap",
    "Token",
    "TokenDayData",
    "TokenHourData",
    "Transaction",
    "UniswapDayData",
    "UniswapFactory",
    "User",
];

const FALSE_GATE_NAMES: [&str; 17] = [
    "eligibility_complete",
    "source_revision_pinned",
    "source_reproducible",
    "implementation_complete",
    "runtime_complete",
    "runtime_parity",
    "logical_parity",
    "history_complete",
    "physical_profile_complete",
    "physical_parity",
    "poi_parity",
    "backfill_ready",
    "production_ready",
    "readiness",
    "issue_87_complete",
    "issue_89_complete",
    "issue_93_complete",
];

const TARGET_FILES: [&str; 12] = [
    "README.md",
    "QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8.yaml",
    "layout-profile-v1.json",
    "reference/abis/ERC20.json",
    "reference/abis/ERC20NameBytes.json",
    "reference/abis/ERC20SymbolBytes.json",
    "reference/abis/factory.json",
    "reference/abis/pair.json",
    "reference/deployment.yaml",
    "reference/mappings/Factory.wasm",
    "reference/mappings/Pair.wasm",
    "reference/schema.graphql",
];

const EXPECTED_M8_ROADMAP: &str =
    "8. **M8 — Uniswap V2 Base** (`QmQmz5kh…`): complete the immutable target and M0
   eligibility work in [#87](https://github.com/pinax-network/substreams-backfills/issues/87),
   then the target-specific implementation in
   [#89](https://github.com/pinax-network/substreams-backfills/issues/89), then differential
   certification and paused landing in
   [#93](https://github.com/pinax-network/substreams-backfills/issues/93). M8 orders work
   only: the generic V2 extractor is decoder prior art, not a Graph-compatible writer, and
   implementation, compute, and load stop whenever either independently selected minimum
   24-hour or 72-hour ETA across all viable healthy copies is at or below 28 days.";

const ISSUE_URL_PREFIX: &str = "https://github.com/pinax-network/substreams-backfills/issues/";

fn false_gates() -> Value {
    Value::Object(
        FALSE_GATE_NAMES
            .iter()
            .map(|name| ((*name).to_string(), Value::Bool(false)))
            .collect(),
    )
}

fn expected_market_snapshot() -> Value {
    json!({
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 780_953,
        "query_fees_grt_24h": "954.416540",
        "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
    })
}

fn expected_eligibility() -> Value {
    json!({
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
}

fn expected_eligibility_contract() -> Value {
    json!({
        "policy": "graph-node-net-catchup-v1",
        "threshold_days": 28,
        "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
        "copy_inventory": "every_current_copy_or_fresh_structural_absence_proof",
        "copy_selection": "independent_minimum_per_window_across_all_viable_healthy_copies",
        "required_windows": ["24h", "72h"],
        "eligible_when": "independently_selected_minimum_24h_and_72h_etas_exceed_28_days_or_are_non_converging",
        "stop_when": "either_independently_selected_minimum_eta_is_at_or_below_28_days",
        "no_viable_copy": "eligible_only_with_fresh_structural_absence_proof_from_both_required_clusters",
        "stopped_actions": ["implementation", "compute", "load"],
        "current_decision": "indeterminate_no_fresh_evidence",
    })
}

fn expected_remaining_gates() -> Value {
    json!([
        "M0: fully account for both required clusters by inventorying every current copy or fresh structural absence proof; when viable healthy copies exist, independently select the minimum stable same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all viable copies, which may be different copies, and require both minima to exceed 28 days or be non-converging; with no viable copy, require fresh structural absence proof from both clusters.",
        "M0 stop: if either independently selected minimum ETA is at or below 28 days, stop implementation, compute, and load; native Graph Node syncing continues.",
        "Freeze the exact ordered handler and failure contract.",
        "Implement the target-specific runtime.",
        "Prove fixed-range logical and physical differential parity.",
        "Certify VID, PoI, failure, and PostgreSQL restore semantics.",
        "Validate a paused backfill load only after every preceding gate passes.",
        "Obtain separate production activation approval.",
    ])
}

fn expected_derived() -> BTreeMap<String, Vec<String>> {
    BTreeMap::from([
        (
            "Pair".to_string(),
            vec![
                "burns".to_string(),
                "mints".to_string(),
                "pairHourData".to_string(),
                "swaps".to_string(),
            ],
        ),
        (
            "Token".to_string(),
            vec![
                "pairBase".to_string(),
                "pairDayDataBase".to_string(),
                "pairDayDataQuote".to_string(),
                "pairQuote".to_string(),
                "tokenDayData".to_string(),
            ],
        ),
    ])
}

fn fail<T>(message: impl Into<String>) -> Result<T, String> {
    Err(message.into())
}

static NULL: Value = Value::Null;

/// Python `mapping.get(key)`: a missing key and an explicit `null` are one value.
fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    value.get(key).unwrap_or(&NULL)
}

// ---------------------------------------------------------------------------
// Python-compatible rendering and canonical JSON
// ---------------------------------------------------------------------------

/// `repr()` of a value decoded from JSON or YAML, used verbatim in the Python
/// failure texts. Object key order follows `serde_json`'s sorted map rather
/// than Python's insertion order.
fn py_repr(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
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

/// Python `str()` of a decoded value: strings pass through, everything else
/// renders as its `repr()`.
fn py_str(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        other => py_repr(other),
    }
}

fn py_list_repr<'a>(items: impl IntoIterator<Item = &'a String>) -> String {
    let rendered: Vec<String> = items.into_iter().map(|item| py_repr_str(item)).collect();
    format!("[{}]", rendered.join(", "))
}

/// `json.dumps(value, sort_keys=True, separators=(",", ":"))`, including the
/// default `ensure_ascii=True` escaping.
fn canonical_json(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(number) => out.push_str(&number.to_string()),
        Value::String(text) => canonical_json_str(text, out),
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                canonical_json(item, out);
            }
            out.push(']');
        }
        Value::Object(entries) => {
            // `serde_json::Map` without `preserve_order` is already sorted.
            out.push('{');
            for (index, (key, item)) in entries.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                canonical_json_str(key, out);
                out.push(':');
                canonical_json(item, out);
            }
            out.push('}');
        }
    }
}

fn canonical_json_str(text: &str, out: &mut String) {
    out.push('"');
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (' '..='~').contains(&c) => out.push(c),
            c => {
                let mut buffer = [0u16; 2];
                for unit in c.encode_utf16(&mut buffer) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
        }
    }
    out.push('"');
}

fn canonical_sha256(value: &Value) -> String {
    let mut payload = String::new();
    canonical_json(value, &mut payload);
    sha256_hex(payload.as_bytes())
}

// ---------------------------------------------------------------------------
// Duplicate-rejecting JSON and YAML loaders
// ---------------------------------------------------------------------------

#[derive(Default)]
struct DuplicateSlot(RefCell<Option<String>>);

struct UniqueSeed<'a>(&'a DuplicateSlot);

impl<'de> DeserializeSeed<'de> for UniqueSeed<'_> {
    type Value = Value;

    fn deserialize<D>(self, deserializer: D) -> Result<Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(UniqueVisitor(self.0))
    }
}

struct UniqueVisitor<'a>(&'a DuplicateSlot);

impl<'de> Visitor<'de> for UniqueVisitor<'_> {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
        formatter.write_str("any duplicate-free JSON or YAML value")
    }

    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }

    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(Value::from(value))
    }

    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(Value::from(value))
    }

    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Value, E> {
        Ok(Value::from(value))
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_string()))
    }

    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_none<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        UniqueSeed(self.0).deserialize(deserializer)
    }

    fn visit_seq<A>(self, mut access: A) -> Result<Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut items = Vec::new();
        while let Some(item) = access.next_element_seed(UniqueSeed(self.0))? {
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
            let item = access.next_value_seed(UniqueSeed(self.0))?;
            if entries.contains_key(&key) {
                *self.0 .0.borrow_mut() = Some(key.clone());
                return Err(de::Error::custom(format!("duplicate key: {key}")));
            }
            entries.insert(key, item);
        }
        Ok(Value::Object(entries))
    }
}

fn read_text(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_bytes(path: &Path) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))
}

/// Port of the Python `load_json`: duplicate keys at any depth are rejected
/// and the document must be an object.
fn load_json(path: &Path) -> Result<Value, String> {
    let text = read_text(path)?;
    let slot = DuplicateSlot::default();
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let parsed = UniqueSeed(&slot)
        .deserialize(&mut deserializer)
        .and_then(|value| deserializer.end().map(|()| value));
    let value = match parsed {
        Ok(value) => value,
        Err(error) => {
            let duplicate = slot.0.borrow_mut().take();
            return match duplicate {
                Some(key) => fail(format!("duplicate JSON key in {}: {key}", path.display())),
                None => fail(format!("cannot parse {}: {error}", path.display())),
            };
        }
    };
    if !value.is_object() {
        return fail(format!("{} must contain an object", path.display()));
    }
    Ok(value)
}

/// Port of the Python `load_yaml` with its `UniqueKeyLoader`.
fn load_yaml(path: &Path) -> Result<Value, String> {
    let text = read_text(path)?;
    let slot = DuplicateSlot::default();
    let deserializer = serde_yaml::Deserializer::from_str(&text);
    let value = match UniqueSeed(&slot).deserialize(deserializer) {
        Ok(value) => value,
        Err(error) => {
            let duplicate = slot.0.borrow_mut().take();
            return match duplicate {
                Some(key) => fail(format!("duplicate YAML key: {key}")),
                None => fail(format!("cannot parse {}: {error}", path.display())),
            };
        }
    };
    if !value.is_object() {
        return fail(format!("{} must contain an object", path.display()));
    }
    Ok(value)
}

// ---------------------------------------------------------------------------
// Path, CID, and event helpers
// ---------------------------------------------------------------------------

/// `Path.resolve()`: symlink-resolving where the path exists, lexical
/// otherwise, because Python resolves non-strictly.
fn resolve(path: &Path) -> PathBuf {
    if let Ok(resolved) = path.canonicalize() {
        return resolved;
    }
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

fn repository_path(root: &Path, value: &Value, label: &str) -> Result<PathBuf, String> {
    let text = match value.as_str() {
        Some(text)
            if !text.starts_with('/')
                && !Path::new(text)
                    .components()
                    .any(|component| component == std::path::Component::ParentDir) =>
        {
            text
        }
        _ => {
            return fail(format!(
                "invalid repository path for {label}: {}",
                py_repr(value)
            ));
        }
    };
    let path = resolve(&root.join(text));
    let root = resolve(root);
    if !path.starts_with(&root) {
        return fail(format!("repository path escapes root for {label}: {text}"));
    }
    Ok(path)
}

/// `{"/": "/ipfs/Qm…"}` → `Qm…`, with the Python failure texts.
fn cid(value: &Value) -> Result<String, String> {
    let entries = match value.as_object() {
        Some(entries) if entries.len() == 1 && entries.contains_key("/") => entries,
        _ => return fail(format!("invalid IPFS object: {}", py_repr(value))),
    };
    let location = &entries["/"];
    match location.as_str() {
        Some(text) if text.starts_with("/ipfs/Qm") => {
            Ok(text.strip_prefix("/ipfs/").unwrap_or(text).to_string())
        }
        _ => fail(format!("invalid IPFS path: {}", py_repr(location))),
    }
}

fn normalize_event(value: &Value) -> Result<String, String> {
    match value.as_str() {
        Some(text) => Ok(normalize_event_str(text)),
        None => fail("event signature must be a string"),
    }
}

fn normalize_event_str(value: &str) -> String {
    value.chars().filter(|c| !c.is_whitespace()).collect()
}

fn is_base58(text: &str) -> bool {
    const ALPHABET: &str = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    text.chars().all(|c| ALPHABET.contains(c))
}

fn verify_false_gates(value: &Value, label: &str) -> Result<(), String> {
    if *value != false_gates() {
        return fail(format!(
            "{label} must retain the complete false truth-gate inventory"
        ));
    }
    Ok(())
}

fn key_set(value: &Value) -> Option<BTreeSet<&str>> {
    value
        .as_object()
        .map(|entries| entries.keys().map(String::as_str).collect())
}

// ---------------------------------------------------------------------------
// Provenance lock
// ---------------------------------------------------------------------------

fn verify_lock(lock: &Value) -> Result<(), String> {
    let mut expected: BTreeSet<&str> = BTreeSet::from(["format_version", "family"]);
    expected.extend(LOCK_SECTION_SHA256.iter().map(|(section, _)| *section));
    if key_set(lock) != Some(expected) {
        return fail("provenance top-level field set drift");
    }
    if field(lock, "format_version") != &json!(1)
        || field(lock, "family") != &json!("uniswap-v2-base")
    {
        return fail("provenance identity drift");
    }
    for (section, expected_digest) in LOCK_SECTION_SHA256 {
        if canonical_sha256(field(lock, section)) != expected_digest {
            return fail(format!("provenance {section} contract drift"));
        }
    }
    verify_false_gates(field(lock, "truth_gates"), "provenance truth_gates")
}

// ---------------------------------------------------------------------------
// Vendored artifacts
// ---------------------------------------------------------------------------

fn normalize(payload: &[u8], mode: &Value) -> Result<Vec<u8>, String> {
    match mode.as_str() {
        Some("identity") => Ok(payload.to_vec()),
        Some("remove_one_trailing_lf") => {
            if !payload.ends_with(b"\n") || payload.ends_with(b"\n\n") {
                return fail("normalization requires exactly one trailing LF");
            }
            Ok(payload[..payload.len() - 1].to_vec())
        }
        _ => fail(format!(
            "unsupported artifact normalization: {}",
            py_repr(mode)
        )),
    }
}

fn read_uleb(payload: &[u8], offset: usize) -> Result<(u128, usize), String> {
    let mut value: u128 = 0;
    let mut shift: u32 = 0;
    let mut offset = offset;
    loop {
        if offset >= payload.len() || shift > 63 {
            return fail("invalid WASM unsigned LEB128 value");
        }
        let byte = payload[offset];
        offset += 1;
        value |= u128::from(byte & 0x7f) << shift;
        if byte < 0x80 {
            return Ok((value, offset));
        }
        shift += 7;
    }
}

fn wasm_function_exports(payload: &[u8]) -> Result<Vec<String>, String> {
    if payload.len() < 8 || &payload[..8] != b"\x00asm\x01\x00\x00\x00" {
        return fail("invalid WASM header");
    }
    let mut offset = 8usize;
    let mut function_exports: Vec<String> = Vec::new();
    while offset < payload.len() {
        let section_id = payload[offset];
        offset += 1;
        let (section_size, next) = read_uleb(payload, offset)?;
        offset = next;
        let section_end =
            offset.saturating_add(usize::try_from(section_size).unwrap_or(usize::MAX));
        if section_end > payload.len() {
            return fail("WASM section extends beyond payload");
        }
        if section_id == 7 {
            let (count, next) = read_uleb(payload, offset)?;
            offset = next;
            for _ in 0..count {
                let (name_size, next) = read_uleb(payload, offset)?;
                offset = next;
                let name_end =
                    offset.saturating_add(usize::try_from(name_size).unwrap_or(usize::MAX));
                if name_end > section_end {
                    return fail("WASM export name extends beyond section");
                }
                let Ok(name) = std::str::from_utf8(&payload[offset..name_end]) else {
                    return fail("WASM export name is not UTF-8");
                };
                let name = name.to_string();
                offset = name_end;
                if offset >= section_end {
                    return fail("WASM export is missing kind");
                }
                let kind = payload[offset];
                offset += 1;
                let (_, next) = read_uleb(payload, offset)?;
                offset = next;
                if kind == 0 {
                    function_exports.push(name);
                }
            }
            if offset != section_end {
                return fail("WASM export section has trailing bytes");
            }
        }
        offset = section_end;
    }
    if offset != payload.len() {
        return fail("WASM section parsing did not consume payload");
    }
    Ok(function_exports)
}

fn verify_artifacts(root: &Path, lock: &Value) -> Result<BTreeMap<String, Value>, String> {
    let Some(records) = field(lock, "artifact_lock").as_array() else {
        return fail("artifact_lock must be a list");
    };
    let mut by_role: BTreeMap<String, Value> = BTreeMap::new();
    for item in records {
        if !item.is_object() || !field(item, "role").is_string() {
            return fail("invalid artifact record");
        }
        let role = py_str(field(item, "role"));
        if by_role.contains_key(&role) {
            return fail(format!("duplicate artifact role: {role}"));
        }
        by_role.insert(role.clone(), item.clone());

        let valid_cid = match field(item, "cid").as_str() {
            Some(text) => text.len() == 46 && text.starts_with("Qm") && is_base58(&text[2..]),
            None => false,
        };
        if !valid_cid {
            return fail(format!("invalid artifact CID for {role}"));
        }

        if item.get("vendored_path").is_none() {
            return fail(format!(
                "offline target closure is missing vendored artifact {role}"
            ));
        }

        let path = repository_path(root, field(item, "vendored_path"), &role)?;
        let payload = read_bytes(&path)?;
        if field(item, "vendored_bytes") != &json!(payload.len()) {
            return fail(format!("vendored byte count drift for {role}"));
        }
        if field(item, "vendored_sha256") != &json!(sha256_hex(&payload)) {
            return fail(format!("vendored digest drift for {role}"));
        }
        let source_payload = normalize(&payload, field(item, "normalization"))?;
        if field(item, "source_bytes") != &json!(source_payload.len()) {
            return fail(format!("source byte count drift for {role}"));
        }
        if field(item, "source_sha256") != &json!(sha256_hex(&source_payload)) {
            return fail(format!("source digest drift for {role}"));
        }
        if role.ends_with("_abi") {
            let decoded: Value = serde_json::from_slice(&source_payload)
                .map_err(|error| format!("cannot parse ABI artifact {role}: {error}"))?;
            if !decoded.is_array() {
                return fail(format!("ABI artifact must be a JSON array: {role}"));
            }
        }
        if role.ends_with("_mapping_wasm") {
            let handler_exports: Vec<Value> = wasm_function_exports(&source_payload)?
                .into_iter()
                .filter(|name| name.starts_with("handle"))
                .map(Value::String)
                .collect();
            if field(item, "exports") != &Value::Array(handler_exports) {
                return fail(format!("mapping handler export drift for {role}"));
            }
        }
    }

    let present: BTreeSet<String> = by_role.keys().cloned().collect();
    let expected: BTreeSet<String> = EXPECTED_ROLES
        .iter()
        .map(|role| (*role).to_string())
        .collect();
    if present != expected {
        let difference: Vec<String> = present.symmetric_difference(&expected).cloned().collect();
        return fail(format!(
            "artifact role inventory drift: {}",
            py_list_repr(&difference)
        ));
    }
    Ok(by_role)
}

// ---------------------------------------------------------------------------
// Deployment manifest
// ---------------------------------------------------------------------------

fn abi_contract(mapping: &Value) -> Result<Vec<(String, String)>, String> {
    let Some(abis) = field(mapping, "abis").as_array() else {
        return fail("mapping ABI inventory must be a list");
    };
    let mut result = Vec::new();
    for item in abis {
        if !item.is_object() {
            return fail("mapping ABI entry must be an object");
        }
        result.push((py_str(field(item, "name")), cid(field(item, "file"))?));
    }
    Ok(result)
}

fn handler_contract(mapping: &Value) -> Result<Vec<(String, String)>, String> {
    let Some(handlers) = field(mapping, "eventHandlers").as_array() else {
        return fail("eventHandlers must be a list");
    };
    let mut result = Vec::new();
    for item in handlers {
        if key_set(item) != Some(BTreeSet::from(["event", "handler"])) {
            return fail("event handler field set drift");
        }
        result.push((
            py_str(field(item, "handler")),
            normalize_event(field(item, "event"))?,
        ));
    }
    Ok(result)
}

fn verify_manifest(root: &Path, artifacts: &BTreeMap<String, Value>) -> Result<(), String> {
    let deployment = artifacts
        .get("deployment")
        .ok_or("missing deployment artifact record")?;
    let path = repository_path(root, field(deployment, "vendored_path"), "deployment")?;
    let manifest = load_yaml(&path)?;
    if key_set(&manifest)
        != Some(BTreeSet::from([
            "dataSources",
            "description",
            "repository",
            "schema",
            "specVersion",
            "templates",
        ]))
    {
        return fail("manifest top-level shape drift");
    }
    if field(&manifest, "specVersion") != &json!("0.0.8") {
        return fail("manifest specVersion drift");
    }
    if field(&manifest, "repository") != &json!("https://github.com/Uniswap/uniswap-v2-subgraph") {
        return fail("manifest repository identity drift");
    }
    let schema = field(&manifest, "schema");
    let schema_ok = key_set(schema) == Some(BTreeSet::from(["file"]))
        && cid(field(schema, "file")).is_ok_and(|value| value == SCHEMA_CID);
    if !schema_ok {
        return fail("manifest schema binding drift");
    }

    let data_sources = field(&manifest, "dataSources");
    let templates = field(&manifest, "templates");
    let Some([factory]) = data_sources.as_array().map(Vec::as_slice) else {
        return fail("manifest must contain exactly one Factory data source");
    };
    let Some([pair]) = templates.as_array().map(Vec::as_slice) else {
        return fail("manifest must contain exactly one Pair template");
    };
    if !factory.is_object() || !pair.is_object() {
        return fail("manifest components must be objects");
    }
    let component_fields = BTreeSet::from(["kind", "mapping", "name", "network", "source"]);
    if key_set(factory) != Some(component_fields.clone()) {
        return fail("Factory data-source shape drift");
    }
    if key_set(pair) != Some(component_fields) {
        return fail("Pair template shape drift");
    }
    if field(factory, "kind") != &json!("ethereum/contract")
        || field(factory, "name") != &json!("Factory")
        || field(factory, "network") != &json!("base")
    {
        return fail("Factory data-source identity drift");
    }
    if field(factory, "source")
        != &json!({"abi": "Factory", "address": FACTORY, "startBlock": START_BLOCK})
    {
        return fail("Factory address/start-block binding drift");
    }
    if field(pair, "kind") != &json!("ethereum/contract")
        || field(pair, "name") != &json!("Pair")
        || field(pair, "network") != &json!("base")
        || field(pair, "source") != &json!({"abi": "Pair"})
    {
        return fail("Pair dynamic-template identity drift");
    }

    let factory_mapping = field(factory, "mapping");
    let pair_mapping = field(pair, "mapping");
    if !factory_mapping.is_object() || !pair_mapping.is_object() {
        return fail("mapping records must be objects");
    }
    let mapping_fields = BTreeSet::from([
        "abis",
        "apiVersion",
        "entities",
        "eventHandlers",
        "file",
        "kind",
        "language",
    ]);
    if key_set(factory_mapping) != Some(mapping_fields.clone())
        || key_set(pair_mapping) != Some(mapping_fields)
    {
        return fail("mapping field set drift");
    }
    for (name, mapping) in [("Factory", factory_mapping), ("Pair", pair_mapping)] {
        if field(mapping, "apiVersion") != &json!("0.0.7")
            || field(mapping, "entities") != &json!(["Pair", "Token"])
            || field(mapping, "kind") != &json!("ethereum/events")
            || field(mapping, "language") != &json!("wasm/assemblyscript")
        {
            return fail(format!("{name} mapping shape drift"));
        }
    }

    let artifact_cid = |role: &str| -> String {
        artifacts
            .get(role)
            .map(|record| py_str(field(record, "cid")))
            .unwrap_or_else(|| "None".to_string())
    };
    if abi_contract(factory_mapping)?
        != [
            ("Factory".to_string(), artifact_cid("factory_abi")),
            ("ERC20".to_string(), artifact_cid("erc20_abi")),
            (
                "ERC20SymbolBytes".to_string(),
                artifact_cid("erc20_symbol_bytes_abi"),
            ),
            (
                "ERC20NameBytes".to_string(),
                artifact_cid("erc20_name_bytes_abi"),
            ),
        ]
    {
        return fail("Factory ABI inventory drift");
    }
    if abi_contract(pair_mapping)?
        != [
            ("Pair".to_string(), artifact_cid("pair_abi")),
            ("Factory".to_string(), artifact_cid("factory_abi")),
        ]
    {
        return fail("Pair ABI inventory drift");
    }
    if cid(field(factory_mapping, "file"))? != artifact_cid("factory_mapping_wasm") {
        return fail("Factory mapping CID drift");
    }
    if cid(field(pair_mapping, "file"))? != artifact_cid("pair_mapping_wasm") {
        return fail("Pair mapping CID drift");
    }
    let expected_factory: Vec<(String, String)> = EXPECTED_FACTORY_HANDLER
        .iter()
        .map(|(name, event)| ((*name).to_string(), normalize_event_str(event)))
        .collect();
    if handler_contract(factory_mapping)? != expected_factory {
        return fail("Factory handler contract drift");
    }
    let expected_pair: Vec<(String, String)> = EXPECTED_PAIR_HANDLERS
        .iter()
        .map(|(name, event)| ((*name).to_string(), normalize_event_str(event)))
        .collect();
    if handler_contract(pair_mapping)? != expected_pair {
        return fail("Pair handler order or signature drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// GraphQL schema
// ---------------------------------------------------------------------------

/// Family-local schema parse: unlike `target_common::parse_schema` this one
/// rejects duplicate entities and fields and collects `@derivedFrom` fields.
struct SchemaContract {
    entities: BTreeMap<String, BTreeMap<String, String>>,
    immutable: BTreeSet<String>,
    mutable: BTreeSet<String>,
    derived: BTreeMap<String, Vec<String>>,
}

fn take_ident(text: &str) -> Option<(&str, &str)> {
    let first = text.chars().next()?;
    if !(first == '_' || first.is_ascii_alphabetic()) {
        return None;
    }
    let end = text
        .char_indices()
        .find(|(_, c)| !(*c == '_' || c.is_ascii_alphanumeric()))
        .map(|(index, _)| index)
        .unwrap_or(text.len());
    Some((&text[..end], &text[end..]))
}

/// `^type\s+([_A-Za-z][_0-9A-Za-z]*)\s+@entity(?:\(immutable:\s*(true|false)\))?\s*\{`
fn parse_declaration(line: &str) -> Option<(String, Option<bool>)> {
    let rest = line.strip_prefix("type")?;
    let after_keyword = rest.trim_start();
    if after_keyword.len() == rest.len() {
        return None;
    }
    let (name, rest) = take_ident(after_keyword)?;
    let after_name = rest.trim_start();
    if after_name.len() == rest.len() {
        return None;
    }
    let rest = after_name.strip_prefix("@entity")?;
    let (immutable, rest) = match rest.strip_prefix("(immutable:") {
        Some(inner) => {
            let inner = inner.trim_start();
            let (flag, tail) = match inner.strip_prefix("true") {
                Some(tail) => (true, tail),
                None => (false, inner.strip_prefix("false")?),
            };
            (Some(flag), tail.strip_prefix(')')?)
        }
        None => (None, rest),
    };
    if !rest.trim_start().starts_with('{') {
        return None;
    }
    Some((name.to_string(), immutable))
}

/// `^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)`
fn parse_field(line: &str) -> Option<(String, String)> {
    let (name, rest) = take_ident(line)?;
    let rest = rest.trim_start().strip_prefix(':')?.trim_start();
    let end = rest
        .char_indices()
        .find(|(_, c)| !(c.is_ascii_alphanumeric() || matches!(c, '[' | ']' | '!' | '_')))
        .map(|(index, _)| index)
        .unwrap_or(rest.len());
    if end == 0 {
        return None;
    }
    Some((name.to_string(), rest[..end].to_string()))
}

fn parse_schema(path: &Path) -> Result<SchemaContract, String> {
    let text = read_text(path)?;
    let mut contract = SchemaContract {
        entities: BTreeMap::new(),
        immutable: BTreeSet::new(),
        mutable: BTreeSet::new(),
        derived: BTreeMap::new(),
    };
    let mut current: Option<String> = None;
    for raw_line in text.lines() {
        let line = raw_line.split('#').next().unwrap_or_default().trim();
        if let Some((name, immutable)) = parse_declaration(line) {
            if contract.entities.contains_key(&name) {
                return fail(format!("duplicate schema entity: {name}"));
            }
            contract.entities.insert(name.clone(), BTreeMap::new());
            if immutable == Some(true) {
                contract.immutable.insert(name.clone());
            } else {
                contract.mutable.insert(name.clone());
            }
            current = Some(name);
            continue;
        }
        let Some(entity) = current.clone() else {
            continue;
        };
        if line == "}" {
            current = None;
            continue;
        }
        if let Some((name, kind)) = parse_field(line) {
            let fields = contract
                .entities
                .get_mut(&entity)
                .expect("current entity exists");
            if fields.contains_key(&name) {
                return fail(format!("duplicate schema field: {entity}.{name}"));
            }
            fields.insert(name.clone(), kind);
            if line.contains("@derivedFrom") {
                contract.derived.entry(entity).or_default().push(name);
            }
        }
    }
    for names in contract.derived.values_mut() {
        names.sort();
    }
    Ok(contract)
}

fn verify_schema(
    root: &Path,
    artifacts: &BTreeMap<String, Value>,
    lock: &Value,
) -> Result<(), String> {
    let record = artifacts
        .get("schema")
        .ok_or("missing schema artifact record")?;
    let path = repository_path(root, field(record, "vendored_path"), "schema")?;
    let contract = parse_schema(&path)?;

    let entities = Value::Object(
        contract
            .entities
            .iter()
            .map(|(entity, fields)| {
                (
                    entity.clone(),
                    Value::Object(
                        fields
                            .iter()
                            .map(|(name, kind)| (name.clone(), Value::String(kind.clone())))
                            .collect(),
                    ),
                )
            })
            .collect(),
    );
    let logical = canonical_sha256(&entities);

    let logical_contract = field(lock, "logical_contract");
    if !logical_contract.is_object() {
        return fail("logical contract must be an object");
    }
    let names: Vec<&str> = contract.entities.keys().map(String::as_str).collect();
    if names != EXPECTED_ENTITIES || contract.entities.len() != 15 {
        return fail("schema entity inventory drift");
    }
    if contract.entities.values().map(BTreeMap::len).sum::<usize>() != 157 {
        return fail("schema field count drift");
    }
    if logical != LOGICAL_SHA256 || field(logical_contract, "logical_sha256") != &json!(logical) {
        return fail("schema logical digest drift");
    }
    let immutable: Vec<&str> = contract.immutable.iter().map(String::as_str).collect();
    let mutable: Vec<&str> = contract.mutable.iter().map(String::as_str).collect();
    let expected_mutable: Vec<&str> = EXPECTED_ENTITIES
        .iter()
        .copied()
        .filter(|name| *name != "PairTokenLookup")
        .collect();
    if immutable != ["PairTokenLookup"] || mutable != expected_mutable {
        return fail("schema mutability drift");
    }
    if contract.derived != expected_derived() {
        return fail("schema derived-field contract drift");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Layout profile, target binding, roadmap, file inventory
// ---------------------------------------------------------------------------

fn verify_profile(root: &Path, lock: &Value) -> Result<(), String> {
    let record = field(lock, "layout_profile");
    if !record.is_object() {
        return fail("layout_profile lock must be an object");
    }
    let path = repository_path(root, field(record, "path"), "layout profile")?;
    let payload = read_bytes(&path)?;
    if field(record, "bytes") != &json!(payload.len())
        || field(record, "sha256") != &json!(sha256_hex(&payload))
    {
        return fail("layout profile byte lock drift");
    }
    let profile = load_json(&path)?;
    if canonical_sha256(&profile) != PROFILE_CANONICAL_SHA256 {
        return fail("layout profile semantic contract drift");
    }
    if key_set(&profile)
        != Some(BTreeSet::from([
            "format_version",
            "family",
            "deployment",
            "target",
            "schema",
            "mapping_behavior",
            "generic_event_extractor",
            "eligibility_contract",
            "remaining_gates",
            "truth_gates",
        ]))
    {
        return fail("layout profile top-level inventory drift");
    }
    if field(&profile, "format_version") != &json!(1)
        || field(&profile, "deployment") != &json!(DEPLOYMENT)
        || field(&profile, "family") != &json!("uniswap-v2-base")
        || field(&profile, "eligibility_contract") != &expected_eligibility_contract()
        || field(&profile, "remaining_gates") != &expected_remaining_gates()
    {
        return fail("layout profile identity drift");
    }
    let generic = field(&profile, "generic_event_extractor");
    if !generic.is_object() {
        return fail("generic extractor profile must be an object");
    }
    let promoted = [
        "pair_transfer_supported",
        "target_factory_filter_supported",
        "dynamic_pair_membership_filter_supported",
        "target_start_block_bound",
    ]
    .iter()
    .any(|name| field(generic, name) != &Value::Bool(false));
    if promoted {
        return fail("generic event extractor gap was improperly promoted");
    }
    verify_false_gates(field(&profile, "truth_gates"), "layout profile truth_gates")
}

fn verify_binding(root: &Path) -> Result<(), String> {
    let binding = load_yaml(&root.join(BINDING_PATH))?;
    if key_set(&binding)
        != Some(BTreeSet::from([
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
        ]))
    {
        return fail("target binding top-level inventory drift");
    }
    if field(&binding, "deployment") != &json!(DEPLOYMENT)
        || field(&binding, "family") != &json!("uniswap-v2-base")
        || field(&binding, "display_name") != &json!("Uniswap V2 Base")
        || field(&binding, "schema") != &json!(SCHEMA_CID)
        || field(&binding, "chain") != &json!("base")
        || field(&binding, "milestone") != &json!("M8")
        || field(&binding, "market_snapshot") != &expected_market_snapshot()
        || field(&binding, "target_reference")
            != &json!({
                "provenance": LOCK_PATH,
                "deployment_manifest": "uniswap-v2-base/reference/deployment.yaml",
                "status": "immutable_target_pinned_source_revision_unresolved",
            })
    {
        return fail("target binding identity, M8, market snapshot, or source status drift");
    }
    verify_false_gates(field(&binding, "truth_gates"), "binding truth_gates")?;
    if field(&binding, "eligibility") != &expected_eligibility() {
        return fail("target binding must remain fail-closed without fresh M0 evidence");
    }
    Ok(())
}

/// `(?m)^[0-9]+\. \*\*M[0-9]+ — ` — the start offset of the next milestone heading.
fn next_milestone_heading(text: &str) -> Option<usize> {
    let bytes = text.as_bytes();
    for start in 0..=text.len() {
        if !text.is_char_boundary(start) || (start > 0 && bytes[start - 1] != b'\n') {
            continue;
        }
        let rest = &text[start..];
        let digits = rest.len() - rest.trim_start_matches(|c: char| c.is_ascii_digit()).len();
        if digits == 0 {
            continue;
        }
        let Some(rest) = rest[digits..].strip_prefix(". **M") else {
            continue;
        };
        let digits = rest.len() - rest.trim_start_matches(|c: char| c.is_ascii_digit()).len();
        if digits > 0 && rest[digits..].starts_with(" — ") {
            return Some(start);
        }
    }
    None
}

fn issue_numbers(text: &str) -> Vec<String> {
    let mut numbers = Vec::new();
    let mut cursor = 0usize;
    while let Some(found) = text[cursor..].find(ISSUE_URL_PREFIX) {
        let start = cursor + found + ISSUE_URL_PREFIX.len();
        let rest = &text[start..];
        let digits = rest.len() - rest.trim_start_matches(|c: char| c.is_ascii_digit()).len();
        cursor = start + digits;
        if digits > 0 {
            numbers.push(rest[..digits].to_string());
        }
    }
    numbers
}

fn verify_roadmap(root: &Path) -> Result<(), String> {
    let readme = read_text(&root.join("README.md"))?;
    let marker = "8. **M8 — Uniswap V2 Base**";
    if readme.matches(marker).count() != 1 {
        return fail("M8 roadmap entry inventory drift");
    }
    let tail = &readme[readme.find(marker).expect("marker counted once") + marker.len()..];
    let section = match next_milestone_heading(tail) {
        Some(start) => tail[..start].trim_end_matches('\n'),
        None => tail.split("\n\n").next().unwrap_or_default(),
    };
    let actual = format!("{marker}{section}");
    if actual != EXPECTED_M8_ROADMAP || issue_numbers(&actual) != ["87", "89", "93"] {
        return fail("M8 roadmap or #87 -> #89 -> #93 work-item order drift");
    }
    Ok(())
}

fn collect_files(directory: &Path, prefix: &str, out: &mut BTreeSet<String>) -> Result<(), String> {
    let entries = std::fs::read_dir(directory)
        .map_err(|error| format!("cannot read {}: {error}", directory.display()))?;
    for entry in entries {
        let entry =
            entry.map_err(|error| format!("cannot read {}: {error}", directory.display()))?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if name == "__pycache__" {
            continue;
        }
        let relative = if prefix.is_empty() {
            name
        } else {
            format!("{prefix}/{name}")
        };
        let kind = entry
            .file_type()
            .map_err(|error| format!("cannot inspect {}: {error}", entry.path().display()))?;
        if kind.is_dir() {
            collect_files(&entry.path(), &relative, out)?;
        } else if kind.is_file() {
            out.insert(relative);
        }
    }
    Ok(())
}

fn verify_target_file_inventory(root: &Path) -> Result<(), String> {
    let mut files: BTreeSet<String> = BTreeSet::new();
    collect_files(&root.join("uniswap-v2-base"), "", &mut files)?;
    let expected: BTreeSet<String> = TARGET_FILES
        .iter()
        .map(|name| (*name).to_string())
        .collect();
    if files != expected {
        let difference: Vec<String> = files.symmetric_difference(&expected).cloned().collect();
        return fail(format!(
            "target file inventory drift: {}",
            py_list_repr(&difference)
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Pinned behavioral source and generic extractor
// ---------------------------------------------------------------------------

fn git_output(root: &Path, arguments: &[&str]) -> Result<std::process::Output, String> {
    Command::new("git")
        .arg("-C")
        .arg(root)
        .args(arguments)
        .output()
        .map_err(|error| format!("git command failed for {}: {error}", root.display()))
}

fn git_value(root: &Path, arguments: &[&str]) -> Result<String, String> {
    let output = git_output(root, arguments)?;
    if !output.status.success() {
        return fail(format!(
            "git command failed for {}: {}",
            root.display(),
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn git_bytes(root: &Path, arguments: &[&str]) -> Result<Vec<u8>, String> {
    let output = git_output(root, arguments)?;
    if !output.status.success() {
        return fail(format!(
            "git command failed for {}: {}",
            root.display(),
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(output.stdout)
}

fn verify_source_records(root: &Path, records: &Value, label: &str) -> Result<(), String> {
    let records = match records.as_array() {
        Some(records) if !records.is_empty() => records,
        _ => return fail(format!("{label} records must be a non-empty list")),
    };
    for record in records {
        if !record.is_object() {
            return fail(format!("{label} record must be an object"));
        }
        let path = repository_path(root, field(record, "path"), label)?;
        let payload = read_bytes(&path)?;
        if field(record, "bytes") != &json!(payload.len())
            || field(record, "sha256") != &json!(sha256_hex(&payload))
        {
            return fail(format!(
                "{label} source payload drift: {}",
                py_str(field(record, "path"))
            ));
        }
        let hashed = git_value(root, &["hash-object", &path.to_string_lossy()])?;
        if field(record, "git_blob") != &json!(hashed) {
            return fail(format!(
                "{label} Git blob drift: {}",
                py_str(field(record, "path"))
            ));
        }
    }
    Ok(())
}

/// `\bTransfer\s+transfer\s*=`
fn declares_transfer_field(text: &str) -> bool {
    let bytes = text.as_bytes();
    let mut cursor = 0usize;
    while let Some(found) = text[cursor..].find("Transfer") {
        let start = cursor + found;
        cursor = start + "Transfer".len();
        if start > 0 && (bytes[start - 1] == b'_' || bytes[start - 1].is_ascii_alphanumeric()) {
            continue;
        }
        let rest = &text[cursor..];
        let trimmed = rest.trim_start();
        if trimmed.len() == rest.len() {
            continue;
        }
        let Some(rest) = trimmed.strip_prefix("transfer") else {
            continue;
        };
        if rest.trim_start().starts_with('=') {
            return true;
        }
    }
    false
}

fn verify_behavioral_source(root: &Path, lock: &Value) -> Result<(), String> {
    let evidence = field(lock, "source_evidence");
    if !evidence.is_object() {
        return fail("source evidence must be an object");
    }
    if git_value(root, &["rev-parse", "HEAD^{commit}"])? != SOURCE_COMMIT {
        return fail("behavioral source commit drift");
    }
    if git_value(root, &["show", "-s", "--format=%T", "HEAD"])? != SOURCE_TREE {
        return fail("behavioral source tree drift");
    }
    verify_source_records(root, field(evidence, "source_records"), "behavioral source")?;
    if ["yarn.lock", "package-lock.json", "pnpm-lock.yaml"]
        .iter()
        .any(|name| root.join(name).exists())
    {
        return fail("behavioral candidate unexpectedly gained a dependency lockfile");
    }
    let package: Value = serde_json::from_str(&read_text(&root.join("package.json"))?)
        .map_err(|error| format!("cannot parse package.json: {error}"))?;
    let dev_dependencies = field(&package, "devDependencies");
    if field(dev_dependencies, "@graphprotocol/graph-cli") != &json!("^0.64.1") {
        return fail("Graph CLI constraint drift");
    }
    if field(dev_dependencies, "@graphprotocol/graph-ts") != &json!("^0.32.0") {
        return fail("Graph TS constraint drift");
    }
    let config: Value = serde_json::from_str(&read_text(&root.join("config/base/config.json"))?)
        .map_err(|error| format!("cannot parse config/base/config.json: {error}"))?;
    if config
        != json!({
            "network": "base",
            "factory": FACTORY,
            "startblock": START_BLOCK.to_string(),
        })
    {
        return fail("behavioral source Base target config drift");
    }
    let helpers = read_text(&root.join("src/common/helpers.ts"))?;
    if !helpers.contains("ERC20BigDecimals.bind(tokenAddress)")
        || !helpers.contains("BigInt.fromI32(255)")
    {
        return fail("behavioral source decimals overflow guard drift");
    }
    let template = read_text(&root.join("v2-subgraph.template.yaml"))?;
    if !template.contains("name: ERC20BigDecimals") {
        return fail("behavioral source BigDecimals ABI dependency drift");
    }
    let source_schema = read_bytes(&root.join("src/v2/schema.graphql"))?;
    if sha256_hex(&source_schema) == TARGET_SCHEMA_SHA256 {
        return fail("source evidence contradiction disappeared; re-audit before promotion");
    }

    let history = field(evidence, "schema_history_search");
    if !history.is_object() {
        return fail("schema history search must be an object");
    }
    let revisions = match field(history, "revisions").as_array() {
        Some(revisions) if revisions.len() == 7 => revisions.clone(),
        _ => return fail("schema history revision inventory drift"),
    };
    let mut seen_commits: BTreeSet<String> = BTreeSet::new();
    let mut seen_blobs: BTreeSet<String> = BTreeSet::new();
    let mut target_matches: usize = 0;
    for revision in &revisions {
        if !revision.is_object() {
            return fail("schema history revision must be an object");
        }
        let commit = py_str(field(revision, "commit"));
        if seen_commits.contains(&commit) {
            return fail(format!("duplicate schema history commit: {commit}"));
        }
        seen_commits.insert(commit.clone());
        if git_value(root, &["rev-parse", &format!("{commit}^{{commit}}")])? != commit {
            return fail(format!("schema history commit drift: {commit}"));
        }
        let tree = git_value(root, &["show", "-s", "--format=%T", &commit])?;
        if field(revision, "tree") != &json!(tree) {
            return fail(format!("schema history tree drift: {commit}"));
        }
        let blob = git_value(
            root,
            &["rev-parse", &format!("{commit}:src/v2/schema.graphql")],
        )?;
        if field(revision, "schema_git_blob") != &json!(blob) {
            return fail(format!("schema history Git blob drift: {commit}"));
        }
        seen_blobs.insert(blob);
        let payload = git_bytes(root, &["show", &format!("{commit}:src/v2/schema.graphql")])?;
        let digest = sha256_hex(&payload);
        if field(revision, "schema_bytes") != &json!(payload.len())
            || field(revision, "schema_sha256") != &json!(digest)
        {
            return fail(format!("schema history payload drift: {commit}"));
        }
        if digest == TARGET_SCHEMA_SHA256 {
            target_matches += 1;
        }
    }
    if field(history, "unique_blobs_checked") != &json!(seen_blobs.len())
        || field(history, "exact_target_matches") != &json!(target_matches)
    {
        return fail("schema history aggregate drift");
    }
    if field(history, "revisions_checked") != &json!(seen_commits.len()) {
        return fail("schema history revision count drift");
    }
    Ok(())
}

fn verify_generic_source(root: &Path, lock: &Value) -> Result<(), String> {
    let evidence = field(lock, "generic_event_extractor");
    if !evidence.is_object() {
        return fail("generic source evidence must be an object");
    }
    if git_value(root, &["rev-parse", "HEAD^{commit}"])? != GENERIC_COMMIT {
        return fail("generic extractor commit drift");
    }
    if git_value(root, &["show", "-s", "--format=%T", "HEAD"])? != GENERIC_TREE {
        return fail("generic extractor tree drift");
    }
    verify_source_records(root, field(evidence, "records"), "generic extractor")?;
    let lib = read_text(&root.join("dex/uniswap-v2/src/lib.rs"))?;
    let proto = read_text(&root.join("proto/v1/dex/uniswap-v2.proto"))?;
    let yaml_text = read_text(&root.join("dex/uniswap-v2/substreams.yaml"))?;
    for event in ["Swap", "Mint", "Burn", "Sync", "PairCreated"] {
        if !lib.contains(&format!("events::{event}::match_and_decode(log)")) {
            return fail(format!("generic extractor lost {event} decoder"));
        }
    }
    if lib.contains("events::Transfer::match_and_decode") || declares_transfer_field(&proto) {
        return fail("generic extractor unexpectedly gained Pair Transfer; re-audit required");
    }
    if lib.to_lowercase().contains(&FACTORY.to_lowercase())
        || !lib.contains("PairCreated::match_and_decode(log)")
    {
        return fail("generic extractor target Factory scope contract drift");
    }
    if !proto.contains("PairCreated") || proto.contains("Transfer") {
        return fail("generic extractor protobuf event inventory drift");
    }
    if yaml_text.contains("params:") || yaml_text.to_lowercase().contains("store") {
        return fail("generic extractor unexpectedly gained target parameters or store filtering");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

/// `sources` is `(behavioral source root, generic extractor root)`.
pub fn verify(root: &Path, lock: &Path, sources: Option<(&Path, &Path)>) -> Result<String, String> {
    let root = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve {}: {error}", root.display()))?;
    let lock_value = load_json(&root.join(lock))?;
    verify_lock(&lock_value)?;
    let artifacts = verify_artifacts(&root, &lock_value)?;
    verify_manifest(&root, &artifacts)?;
    verify_schema(&root, &artifacts, &lock_value)?;
    verify_profile(&root, &lock_value)?;
    verify_binding(&root)?;
    verify_roadmap(&root)?;
    verify_target_file_inventory(&root)?;

    let mut scope = "target/layout".to_string();
    if let Some((behavioral, generic)) = sources {
        let behavioral = behavioral
            .canonicalize()
            .map_err(|error| format!("cannot resolve {}: {error}", behavioral.display()))?;
        let generic = generic
            .canonicalize()
            .map_err(|error| format!("cannot resolve {}: {error}", generic.display()))?;
        verify_behavioral_source(&behavioral, &lock_value)?;
        verify_generic_source(&generic, &lock_value)?;
        scope.push_str("/behavioral-source/generic-extractor");
    }
    Ok(format!(
        "verified Uniswap V2 Base {scope}: deployment={DEPLOYMENT} \
         entities=15 fields=157 work_milestone=M8 eligibility=M0_indeterminate \
         source_revision_pinned=false source_reproducible=false readiness=false"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Subdirectories the materializer creates when run without arguments.
    const BEHAVIORAL_SOURCE_DIR: &str = "v2-subgraph";
    const GENERIC_SOURCE_DIR: &str = "substreams-evm";

    const SUCCESS: &str = "verified Uniswap V2 Base target/layout: \
         deployment=QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8 entities=15 fields=157 \
         work_milestone=M8 eligibility=M0_indeterminate source_revision_pinned=false \
         source_reproducible=false readiness=false";

    const MANIFEST: &str = "uniswap-v2-base/reference/deployment.yaml";
    const SCHEMA: &str = "uniswap-v2-base/reference/schema.graphql";
    const PROFILE_PATH: &str = "uniswap-v2-base/layout-profile-v1.json";

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    fn copy_tree(from: &Path, to: &Path) {
        std::fs::create_dir_all(to).expect("create destination");
        for entry in std::fs::read_dir(from).expect("read source directory") {
            let entry = entry.expect("directory entry");
            let destination = to.join(entry.file_name());
            if entry.file_type().expect("file type").is_dir() {
                copy_tree(&entry.path(), &destination);
            } else {
                std::fs::copy(entry.path(), &destination).expect("copy file");
            }
        }
    }

    fn assert_error<T: std::fmt::Debug>(result: Result<T, String>, expected: &str) {
        match result {
            Ok(value) => panic!("expected failure {expected:?}, verification returned {value:?}"),
            Err(error) => assert_eq!(error, expected),
        }
    }

    /// Mirror of the Python `setUp`: the family directory, the provenance
    /// lock, and the README copied into a scratch root.
    struct Fixture {
        directory: tempfile::TempDir,
    }

    impl Fixture {
        fn new() -> Self {
            let fixture = Self {
                directory: tempfile::tempdir().expect("temporary directory"),
            };
            std::fs::create_dir_all(fixture.root().join("docs/provenance")).expect("docs tree");
            fixture.reset();
            fixture
        }

        fn root(&self) -> PathBuf {
            self.directory.path().to_path_buf()
        }

        /// Mirror of the Python `setUp_surface_reset`.
        fn reset(&self) {
            let target = self.root().join("uniswap-v2-base");
            if target.exists() {
                std::fs::remove_dir_all(&target).expect("clear target tree");
            }
            copy_tree(&repository().join("uniswap-v2-base"), &target);
            std::fs::copy(repository().join(LOCK_PATH), self.root().join(LOCK_PATH))
                .expect("copy lock");
            std::fs::copy(
                repository().join("README.md"),
                self.root().join("README.md"),
            )
            .expect("copy README");
        }

        fn verify(&self) -> Result<String, String> {
            super::verify(&self.root(), Path::new(LOCK_PATH), None)
        }

        fn read(&self, relative: &str) -> String {
            std::fs::read_to_string(self.root().join(relative)).expect("read fixture file")
        }

        fn write(&self, relative: &str, contents: &str) {
            std::fs::write(self.root().join(relative), contents).expect("write fixture file");
        }

        fn replace(&self, relative: &str, from: &str, to: &str) {
            let text = self.read(relative);
            assert!(text.contains(from), "fixture missing {from:?}");
            self.write(relative, &text.replace(from, to));
        }

        fn load_lock(&self) -> Value {
            serde_json::from_str(&self.read(LOCK_PATH)).expect("lock parses")
        }

        fn write_lock(&self, lock: &Value) {
            self.write(
                LOCK_PATH,
                &(serde_json::to_string_pretty(lock).expect("lock serializes") + "\n"),
            );
        }

        fn load_profile(&self) -> Value {
            serde_json::from_str(&self.read(PROFILE_PATH)).expect("profile parses")
        }

        fn write_profile(&self, profile: &Value) {
            self.write(
                PROFILE_PATH,
                &(serde_json::to_string_pretty(profile).expect("profile serializes") + "\n"),
            );
        }

        /// Mirror of the Python `relock_vendored`.
        fn relock_vendored(&self, role: &str) {
            let mut lock = self.load_lock();
            let records = lock["artifact_lock"].as_array_mut().expect("artifact list");
            let record = records
                .iter_mut()
                .find(|item| item["role"] == json!(role))
                .expect("role present");
            let vendored = record["vendored_path"]
                .as_str()
                .expect("vendored path is a string")
                .to_string();
            let payload =
                std::fs::read(self.root().join(vendored)).expect("read vendored artifact");
            record["vendored_bytes"] = json!(payload.len());
            record["vendored_sha256"] = json!(sha256_hex(&payload));
            let source = if record["normalization"] == json!("remove_one_trailing_lf") {
                &payload[..payload.len() - 1]
            } else {
                &payload[..]
            };
            record["source_bytes"] = json!(source.len());
            record["source_sha256"] = json!(sha256_hex(source));
            self.write_lock(&lock);
        }

        /// Mirror of the Python `relock_profile`.
        fn relock_profile(&self) {
            let payload = std::fs::read(self.root().join(PROFILE_PATH)).expect("read profile");
            let mut lock = self.load_lock();
            lock["layout_profile"]["bytes"] = json!(payload.len());
            lock["layout_profile"]["sha256"] = json!(sha256_hex(&payload));
            self.write_lock(&lock);
        }

        fn binding_text(&self) -> String {
            self.read(BINDING_PATH)
        }

        fn write_binding_text(&self, value: &str) {
            self.write(BINDING_PATH, value);
        }
    }

    // -- Python: test_exact_baseline_passes ---------------------------------

    #[test]
    fn exact_baseline_passes() {
        let fixture = Fixture::new();
        assert_eq!(fixture.verify().expect("baseline verifies"), SUCCESS);
    }

    #[test]
    fn repository_tree_verifies_against_the_real_root() {
        assert_eq!(
            super::verify(&repository(), Path::new(LOCK_PATH), None).expect("repository verifies"),
            SUCCESS
        );
    }

    // -- Python: manifest and schema drift ----------------------------------

    #[test]
    fn manifest_byte_drift_is_rejected() {
        let fixture = Fixture::new();
        let text = fixture.read(MANIFEST);
        fixture.write(MANIFEST, &(text + "\n"));
        assert_error(fixture.verify(), "vendored byte count drift for deployment");
    }

    #[test]
    fn factory_address_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.replace(
            MANIFEST,
            "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
            "0x0000000000000000000000000000000000000001",
        );
        fixture.relock_vendored("deployment");
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    #[test]
    fn pair_handler_reordering_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        let mint = concat!(
            "        - event: Mint(indexed address,uint256,uint256)\n",
            "          handler: handleMint\n"
        );
        let burn = concat!(
            "        - event: Burn(indexed address,uint256,uint256,indexed address)\n",
            "          handler: handleBurn\n"
        );
        fixture.replace(MANIFEST, &format!("{mint}{burn}"), &format!("{burn}{mint}"));
        fixture.relock_vendored("deployment");
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    #[test]
    fn transfer_handler_removal_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.replace(
            MANIFEST,
            concat!(
                "        - event: Transfer(indexed address,indexed address,uint256)\n",
                "          handler: handleTransfer\n"
            ),
            "",
        );
        fixture.relock_vendored("deployment");
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    #[test]
    fn schema_mutability_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.replace(
            SCHEMA,
            "type Swap @entity(immutable: false)",
            "type Swap @entity(immutable: true)",
        );
        fixture.relock_vendored("schema");
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    #[test]
    fn derived_field_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        fixture.replace(
            SCHEMA,
            "mints: [Mint!]! @derivedFrom(field: \"pair\")",
            "mints: [Mint!]!",
        );
        fixture.relock_vendored("schema");
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    // -- Python: generic extractor and runtime promotions --------------------

    fn assert_profile_flag_promotion_is_rejected(name: &str) {
        let fixture = Fixture::new();
        let mut profile = fixture.load_profile();
        profile["generic_event_extractor"][name] = json!(true);
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_error(fixture.verify(), "provenance layout_profile contract drift");
    }

    #[test]
    fn generic_transfer_promotion_is_rejected_after_profile_relock() {
        assert_profile_flag_promotion_is_rejected("pair_transfer_supported");
    }

    #[test]
    fn generic_factory_filter_promotion_is_rejected_after_profile_relock() {
        assert_profile_flag_promotion_is_rejected("target_factory_filter_supported");
    }

    #[test]
    fn generic_dynamic_pair_filter_promotion_is_rejected_after_profile_relock() {
        assert_profile_flag_promotion_is_rejected("dynamic_pair_membership_filter_supported");
    }

    #[test]
    fn runtime_gate_promotion_is_rejected_after_profile_relock() {
        let fixture = Fixture::new();
        let mut profile = fixture.load_profile();
        profile["truth_gates"]["runtime_parity"] = json!(true);
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_error(fixture.verify(), "provenance layout_profile contract drift");
    }

    #[test]
    fn exact_source_reproduction_promotion_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["source_evidence"]["exact_output_reproduction"] = json!(true);
        lock["truth_gates"]["source_reproducible"] = json!(true);
        fixture.write_lock(&lock);
        assert_error(
            fixture.verify(),
            "provenance source_evidence contract drift",
        );
    }

    // -- Python: vendored mapping drift --------------------------------------

    #[test]
    fn mapping_digest_lock_drift_is_rejected() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        let records = lock["artifact_lock"].as_array_mut().expect("artifact list");
        let record = records
            .iter_mut()
            .find(|item| item["role"] == json!("factory_mapping_wasm"))
            .expect("role present");
        record["source_sha256"] = json!("0".repeat(64));
        fixture.write_lock(&lock);
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    #[test]
    fn vendored_mapping_byte_drift_is_rejected() {
        let fixture = Fixture::new();
        let path = fixture
            .root()
            .join("uniswap-v2-base/reference/mappings/Factory.wasm");
        let mut payload = std::fs::read(&path).expect("read mapping");
        let last = payload.len() - 1;
        payload[last] ^= 1;
        std::fs::write(&path, &payload).expect("write mapping");
        assert_error(
            fixture.verify(),
            "vendored digest drift for factory_mapping_wasm",
        );
    }

    #[test]
    fn vendored_mapping_handler_export_drift_is_rejected_even_if_relocked() {
        let fixture = Fixture::new();
        let path = fixture
            .root()
            .join("uniswap-v2-base/reference/mappings/Pair.wasm");
        let payload = std::fs::read(&path).expect("read mapping");
        let position = payload
            .windows("handleTransfer".len())
            .position(|window| window == b"handleTransfer")
            .expect("export name present");
        let mut mutated = payload.clone();
        mutated[position] = b'x';
        assert_ne!(mutated, payload);
        std::fs::write(&path, &mutated).expect("write mapping");
        fixture.relock_vendored("pair_mapping_wasm");
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    // -- Python: target binding ---------------------------------------------

    #[test]
    fn binding_required_field_omission_is_rejected() {
        let fixture = Fixture::new();
        fixture.write_binding_text(
            &fixture
                .binding_text()
                .replace("display_name: Uniswap V2 Base\n", ""),
        );
        assert_error(fixture.verify(), "target binding top-level inventory drift");
    }

    #[test]
    fn binding_unknown_top_level_field_is_rejected() {
        let fixture = Fixture::new();
        fixture.write_binding_text(&(fixture.binding_text() + "runtime_ready: true\n"));
        assert_error(fixture.verify(), "target binding top-level inventory drift");
    }

    #[test]
    fn binding_identity_schema_and_m8_drift_are_rejected() {
        let fixture = Fixture::new();
        let original = fixture.binding_text();
        let replacements = [
            ("display_name: Uniswap V2 Base", "display_name: Invented V2"),
            (
                "schema: QmeyYQ8ZJnzuQsoXnizGXLyFSt7mcuRNkmNQxMv3pXiMnW",
                "schema: Qm11111111111111111111111111111111111111111111",
            ),
            ("milestone: M8", "milestone: M0"),
            (
                "status: immutable_target_pinned_source_revision_unresolved",
                "status: immutable_target_and_source_pinned",
            ),
        ];
        for (from, to) in replacements {
            fixture.write_binding_text(&original.replace(from, to));
            assert_error(
                fixture.verify(),
                "target binding identity, M8, market snapshot, or source status drift",
            );
        }
    }

    // -- Python: market snapshot --------------------------------------------

    #[test]
    fn market_snapshot_omission_is_rejected() {
        let fixture = Fixture::new();
        let block = concat!(
            "market_snapshot:\n",
            "  measured_at: \"2026-08-31T17:20:00Z\"\n",
            "  queries_24h: 780953\n",
            "  query_fees_grt_24h: \"954.416540\"\n",
            "  authority: https://github.com/pinax-network/substreams-backfills/issues/83\n"
        );
        let text = fixture.binding_text();
        assert!(text.contains(block));
        fixture.write_binding_text(&text.replace(block, ""));
        assert_error(fixture.verify(), "target binding top-level inventory drift");
    }

    #[test]
    fn market_snapshot_non_object_is_rejected() {
        let fixture = Fixture::new();
        let text = fixture.binding_text();
        let start = text.find("market_snapshot:\n").expect("snapshot block");
        let end = text.find("target_reference:\n").expect("reference block");
        fixture.write_binding_text(&format!(
            "{}market_snapshot: omitted\n{}",
            &text[..start],
            &text[end..]
        ));
        assert_error(
            fixture.verify(),
            "target binding identity, M8, market snapshot, or source status drift",
        );
    }

    #[test]
    fn market_snapshot_query_count_type_drift_is_rejected() {
        let fixture = Fixture::new();
        let original = fixture.binding_text();
        for replacement in ["  queries_24h: \"780953\"", "  queries_24h: true"] {
            fixture.write_binding_text(&original.replace("  queries_24h: 780953", replacement));
            assert_error(
                fixture.verify(),
                "target binding identity, M8, market snapshot, or source status drift",
            );
        }
    }

    #[test]
    fn market_snapshot_numeric_fee_is_rejected() {
        let fixture = Fixture::new();
        fixture.write_binding_text(&fixture.binding_text().replace(
            "  query_fees_grt_24h: \"954.416540\"",
            "  query_fees_grt_24h: 954.416540",
        ));
        assert_error(
            fixture.verify(),
            "target binding identity, M8, market snapshot, or source status drift",
        );
    }

    #[test]
    fn market_snapshot_precision_drift_is_rejected() {
        let fixture = Fixture::new();
        let original = fixture.binding_text();
        for value in ["954.41654", "954.4165400"] {
            fixture.write_binding_text(&original.replace(
                "  query_fees_grt_24h: \"954.416540\"",
                &format!("  query_fees_grt_24h: \"{value}\""),
            ));
            assert_error(
                fixture.verify(),
                "target binding identity, M8, market snapshot, or source status drift",
            );
        }
    }

    #[test]
    fn market_snapshot_authority_drift_is_rejected() {
        let fixture = Fixture::new();
        fixture.write_binding_text(&fixture.binding_text().replace(
            "authority: https://github.com/pinax-network/substreams-backfills/issues/83",
            "authority: https://github.com/pinax-network/substreams-backfills/issues/87",
        ));
        assert_error(
            fixture.verify(),
            "target binding identity, M8, market snapshot, or source status drift",
        );
    }

    #[test]
    fn market_snapshot_timestamp_or_query_value_drift_is_rejected() {
        let fixture = Fixture::new();
        let original = fixture.binding_text();
        let replacements = [
            ("2026-08-31T17:20:00Z", "2026-08-31T17:20:01Z"),
            ("  queries_24h: 780953", "  queries_24h: 780954"),
        ];
        for (from, to) in replacements {
            fixture.write_binding_text(&original.replace(from, to));
            assert_error(
                fixture.verify(),
                "target binding identity, M8, market snapshot, or source status drift",
            );
        }
    }

    #[test]
    fn market_snapshot_wrong_placement_is_rejected() {
        let fixture = Fixture::new();
        fixture.write_binding_text(
            &fixture
                .binding_text()
                .replace("market_snapshot:", "target_market_snapshot:"),
        );
        assert_error(fixture.verify(), "target binding top-level inventory drift");
    }

    #[test]
    fn legacy_or_flat_market_fields_are_rejected() {
        let fixture = Fixture::new();
        let original = fixture.binding_text();
        for name in [
            "market_qpd",
            "qos_snapshot_at",
            "signal_grt",
            "grt_24h",
            "generic_grt",
            "queries_24h",
            "query_fees_grt_24h",
        ] {
            fixture.write_binding_text(&format!("{original}{name}: 1\n"));
            assert_error(fixture.verify(), "target binding top-level inventory drift");
        }
    }

    // -- Python: truth gates on every surface --------------------------------

    #[test]
    fn truth_gate_omission_is_rejected_on_every_surface() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["truth_gates"]
            .as_object_mut()
            .expect("gate map")
            .remove("poi_parity");
        fixture.write_lock(&lock);
        assert_error(fixture.verify(), "provenance truth_gates contract drift");

        fixture.reset();
        let mut profile = fixture.load_profile();
        profile["truth_gates"]
            .as_object_mut()
            .expect("gate map")
            .remove("poi_parity");
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_error(fixture.verify(), "provenance layout_profile contract drift");

        fixture.reset();
        fixture.write_binding_text(&fixture.binding_text().replace("  poi_parity: false\n", ""));
        assert_error(
            fixture.verify(),
            "binding truth_gates must retain the complete false truth-gate inventory",
        );
    }

    #[test]
    fn truth_gate_extra_is_rejected_on_every_surface() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        lock["truth_gates"]["invented_ready"] = json!(false);
        fixture.write_lock(&lock);
        assert_error(fixture.verify(), "provenance truth_gates contract drift");

        fixture.reset();
        let mut profile = fixture.load_profile();
        profile["truth_gates"]["invented_ready"] = json!(false);
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_error(fixture.verify(), "provenance layout_profile contract drift");

        fixture.reset();
        fixture.write_binding_text(&fixture.binding_text().replace(
            "  eligibility_complete: false\n",
            "  eligibility_complete: false\n  invented_ready: false\n",
        ));
        assert_error(
            fixture.verify(),
            "binding truth_gates must retain the complete false truth-gate inventory",
        );
    }

    #[test]
    fn legacy_truth_gate_name_is_rejected_on_every_surface() {
        let fixture = Fixture::new();
        let mut lock = fixture.load_lock();
        let gates = lock["truth_gates"].as_object_mut().expect("gate map");
        let value = gates
            .remove("implementation_complete")
            .expect("gate exists");
        gates.insert("implementation_started".to_string(), value);
        fixture.write_lock(&lock);
        assert_error(fixture.verify(), "provenance truth_gates contract drift");

        fixture.reset();
        let mut profile = fixture.load_profile();
        let gates = profile["truth_gates"].as_object_mut().expect("gate map");
        let value = gates
            .remove("implementation_complete")
            .expect("gate exists");
        gates.insert("implementation_started".to_string(), value);
        fixture.write_profile(&profile);
        fixture.relock_profile();
        assert_error(fixture.verify(), "provenance layout_profile contract drift");

        fixture.reset();
        fixture.write_binding_text(&fixture.binding_text().replace(
            "  implementation_complete: false",
            "  implementation_started: false",
        ));
        assert_error(
            fixture.verify(),
            "binding truth_gates must retain the complete false truth-gate inventory",
        );
    }

    #[test]
    fn every_false_gate_promotion_is_rejected_on_every_surface() {
        let fixture = Fixture::new();
        for surface in ["provenance", "profile", "binding"] {
            for gate in FALSE_GATE_NAMES {
                fixture.reset();
                let expected = match surface {
                    "provenance" => {
                        let mut lock = fixture.load_lock();
                        lock["truth_gates"][gate] = json!(true);
                        fixture.write_lock(&lock);
                        "provenance truth_gates contract drift"
                    }
                    "profile" => {
                        let mut profile = fixture.load_profile();
                        profile["truth_gates"][gate] = json!(true);
                        fixture.write_profile(&profile);
                        fixture.relock_profile();
                        "provenance layout_profile contract drift"
                    }
                    _ => {
                        fixture.write_binding_text(
                            &fixture
                                .binding_text()
                                .replace(&format!("  {gate}: false"), &format!("  {gate}: true")),
                        );
                        "binding truth_gates must retain the complete false truth-gate inventory"
                    }
                };
                assert_error(fixture.verify(), expected);
            }
        }
    }

    // -- Python: eligibility contract ----------------------------------------

    #[test]
    fn profile_eligibility_contract_drift_is_rejected() {
        let mutations = [
            ("required_clusters", json!(["riv-subgraphs-a"])),
            ("copy_selection", json!("first_copy")),
            ("required_windows", json!(["24h"])),
            ("eligible_when", json!("any_window_exceeds_28_days")),
            ("stop_when", json!("never")),
            ("no_viable_copy", json!("missing_attachment_is_eligible")),
        ];
        let fixture = Fixture::new();
        for (name, value) in mutations {
            fixture.reset();
            let mut profile = fixture.load_profile();
            profile["eligibility_contract"][name] = value;
            fixture.write_profile(&profile);
            fixture.relock_profile();
            assert_error(fixture.verify(), "provenance layout_profile contract drift");
        }
    }

    #[test]
    fn binding_eligibility_policy_or_cluster_drift_is_rejected() {
        let fixture = Fixture::new();
        let original = fixture.binding_text();
        let replacements = [
            (
                "policy: graph-node-net-catchup-v1",
                "policy: invented-policy",
            ),
            (
                "required_clusters: [riv-subgraphs-a, kan-subgraphs-a]",
                "required_clusters: [riv-subgraphs-a]",
            ),
        ];
        for (from, to) in replacements {
            fixture.write_binding_text(&original.replace(from, to));
            assert_error(
                fixture.verify(),
                "target binding must remain fail-closed without fresh M0 evidence",
            );
        }
    }

    #[test]
    fn eligibility_promotion_without_evidence_is_rejected() {
        let fixture = Fixture::new();
        fixture.write_binding_text(
            &fixture
                .binding_text()
                .replace("decision: indeterminate", "decision: eligible"),
        );
        assert_error(
            fixture.verify(),
            "target binding must remain fail-closed without fresh M0 evidence",
        );
    }

    // -- Python: roadmap ------------------------------------------------------

    #[test]
    fn m8_roadmap_is_bounded_and_link_drift_is_rejected() {
        let fixture = Fixture::new();
        let original = fixture.read("README.md");
        let marker = "8. **M8 — Uniswap V2 Base**";

        // A later milestone may change freely: the M8 section is bounded.
        let later_milestone_change = original
            .replacen(
                "`#85 + #94 -> #90 -> #92 -> #95`",
                "`independently verified future DAG`",
                1,
            )
            .replacen(
                "\n\nMorpho Blue Base remains outside implementation",
                concat!(
                    "\n10. **M10 — Future family**: independently verified roadmap entry.",
                    "\n\nMorpho Blue Base remains outside implementation"
                ),
                1,
            );
        assert_ne!(later_milestone_change, original);
        assert!(later_milestone_change.contains("10. **M10 — Future family**"));
        fixture.write("README.md", &later_milestone_change);
        assert_eq!(fixture.verify().expect("bounded section verifies"), SUCCESS);

        let split = original.find(marker).expect("marker present");
        let prefix = &original[..split];
        let section = &original[split + marker.len()..];
        let reordered = section
            .replacen("issues/89", "issues/TEMP", 1)
            .replacen("issues/93", "issues/89", 1)
            .replacen("issues/TEMP", "issues/93", 1);
        let mutations = [
            original.replacen(
                concat!(
                    "[#89](https://github.com/pinax-network/substreams-backfills/issues/89), ",
                    "then differential\n"
                ),
                "differential\n",
                1,
            ),
            original.replacen(
                concat!(
                    "[#93](https://github.com/pinax-network/substreams-backfills/issues/93). ",
                    "M8 orders work\n"
                ),
                concat!(
                    "[#93](https://github.com/pinax-network/substreams-backfills/issues/93), then\n",
                    "   [#999](https://github.com/pinax-network/substreams-backfills/issues/999). ",
                    "M8 orders work\n"
                ),
                1,
            ),
            format!("{prefix}{marker}{reordered}"),
        ];
        for mutated in mutations {
            assert_ne!(mutated, original);
            fixture.write("README.md", &mutated);
            assert_error(
                fixture.verify(),
                "M8 roadmap or #87 -> #89 -> #93 work-item order drift",
            );
        }
    }

    // -- Python: duplicate keys and untracked files ---------------------------

    #[test]
    fn duplicate_manifest_key_is_rejected() {
        let fixture = Fixture::new();
        let text = fixture.read(MANIFEST);
        fixture.write(MANIFEST, &(text + "specVersion: 0.0.8\n"));
        fixture.relock_vendored("deployment");
        assert_error(fixture.verify(), "provenance artifact_lock contract drift");
    }

    /// The manifest loader itself must still reject the duplicate once the
    /// provenance section digest is out of the way.
    #[test]
    fn duplicate_manifest_key_is_rejected_by_the_yaml_loader() {
        let fixture = Fixture::new();
        let text = fixture.read(MANIFEST);
        fixture.write(MANIFEST, &(text + "specVersion: 0.0.8\n"));
        assert_error(
            load_yaml(&fixture.root().join(MANIFEST)),
            "duplicate YAML key: specVersion",
        );
    }

    #[test]
    fn duplicate_provenance_key_is_rejected() {
        let fixture = Fixture::new();
        fixture.replace(
            LOCK_PATH,
            "{\n  \"format_version\": 1,",
            "{\n  \"format_version\": 1,\n  \"format_version\": 1,",
        );
        let resolved = fixture
            .root()
            .canonicalize()
            .expect("root resolves")
            .join(LOCK_PATH);
        assert_error(
            fixture.verify(),
            &format!(
                "duplicate JSON key in {}: format_version",
                resolved.display()
            ),
        );
    }

    #[test]
    fn untracked_target_artifact_is_rejected() {
        let fixture = Fixture::new();
        std::fs::write(
            fixture
                .root()
                .join("uniswap-v2-base/reference/unlocked.wasm"),
            b"not locked",
        )
        .expect("write untracked artifact");
        assert_error(
            fixture.verify(),
            "target file inventory drift: ['reference/unlocked.wasm']",
        );
    }

    // -- Source-root mode -----------------------------------------------------

    #[test]
    fn missing_source_root_trees_fail_closed() {
        let fixture = Fixture::new();
        let source_root = tempfile::tempdir().expect("temporary source root");
        let behavioral = source_root.path().join(BEHAVIORAL_SOURCE_DIR);
        let generic = source_root.path().join(GENERIC_SOURCE_DIR);
        let error = super::verify(
            &fixture.root(),
            Path::new(LOCK_PATH),
            Some((&behavioral, &generic)),
        )
        .expect_err("absent behavioral source must fail closed");
        assert!(
            error.starts_with("cannot resolve "),
            "unexpected error: {error}"
        );
        assert!(
            error.contains(BEHAVIORAL_SOURCE_DIR),
            "unexpected error: {error}"
        );
        std::fs::create_dir_all(&behavioral).expect("create behavioral tree");
        std::fs::create_dir_all(&generic).expect("create generic tree");
        let error = super::verify(
            &fixture.root(),
            Path::new(LOCK_PATH),
            Some((&behavioral, &generic)),
        )
        .expect_err("empty behavioral source must fail closed");
        assert!(
            error.starts_with("git command failed for "),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn behavioral_source_commit_drift_is_rejected() {
        let fixture = Fixture::new();
        let source_root = tempfile::tempdir().expect("temporary source root");
        let behavioral = source_root.path().join(BEHAVIORAL_SOURCE_DIR);
        std::fs::create_dir_all(&behavioral).expect("create behavioral tree");
        std::fs::write(behavioral.join("package.json"), "{}\n").expect("seed file");
        for arguments in [
            vec!["init", "-q"],
            vec!["config", "user.email", "port@example.invalid"],
            vec!["config", "user.name", "Port"],
            vec!["add", "package.json"],
            vec!["commit", "-q", "-m", "seed"],
        ] {
            let status = Command::new("git")
                .arg("-C")
                .arg(&behavioral)
                .args(&arguments)
                .status()
                .expect("git runs");
            assert!(status.success(), "git {arguments:?} failed");
        }
        let lock = load_json(
            &fixture
                .root()
                .canonicalize()
                .expect("root resolves")
                .join(LOCK_PATH),
        )
        .expect("lock loads");
        assert_error(
            verify_behavioral_source(&behavioral, &lock),
            "behavioral source commit drift",
        );
        assert_error(
            verify_generic_source(&behavioral, &lock),
            "generic extractor commit drift",
        );
    }

    // -- Helper coverage ------------------------------------------------------

    #[test]
    fn canonical_json_matches_python_json_dumps() {
        let mut out = String::new();
        canonical_json(
            &json!({"b": 1, "a": [true, false, null], "c": "x\"y\\z\n"}),
            &mut out,
        );
        assert_eq!(out, r#"{"a":[true,false,null],"b":1,"c":"x\"y\\z\n"}"#);
        let mut ascii = String::new();
        canonical_json(&json!("é😀"), &mut ascii);
        // `ensure_ascii=True`: non-ASCII escapes, astral planes as surrogate pairs.
        assert_eq!(ascii, r#""\u00e9\ud83d\ude00""#);
    }

    #[test]
    fn schema_parse_helpers_mirror_the_python_regexes() {
        assert_eq!(
            parse_declaration("type Swap @entity(immutable: false) {"),
            Some(("Swap".to_string(), Some(false)))
        );
        assert_eq!(
            parse_declaration("type Swap @entity {"),
            Some(("Swap".to_string(), None))
        );
        assert_eq!(
            parse_declaration("type Swap @entity(immutable: maybe) {"),
            None
        );
        assert_eq!(parse_declaration("typeSwap @entity {"), None);
        assert_eq!(
            parse_field("mints: [Mint!]! @derivedFrom(field: \"pair\")"),
            Some(("mints".to_string(), "[Mint!]!".to_string()))
        );
        assert_eq!(parse_field("}"), None);
        assert_eq!(
            issue_numbers("issues/12 and issues/x"),
            Vec::<String>::new()
        );
        assert_eq!(
            issue_numbers(&format!("{ISSUE_URL_PREFIX}87 {ISSUE_URL_PREFIX}93")),
            vec!["87".to_string(), "93".to_string()]
        );
        assert!(declares_transfer_field("  Transfer transfer = 4;"));
        assert!(!declares_transfer_field("  PairTransfer transfer = 4;"));
        assert!(!declares_transfer_field("  Transfer other = 4;"));
    }

    #[test]
    fn repository_paths_reject_escapes_and_absolutes() {
        let root = tempfile::tempdir().expect("temporary root");
        assert_error(
            repository_path(root.path(), &json!("/etc/passwd"), "role"),
            "invalid repository path for role: '/etc/passwd'",
        );
        assert_error(
            repository_path(root.path(), &json!("../outside"), "role"),
            "invalid repository path for role: '../outside'",
        );
        assert_error(
            repository_path(root.path(), &Value::Null, "role"),
            "invalid repository path for role: None",
        );
    }

    #[test]
    fn wasm_export_parsing_rejects_malformed_payloads() {
        assert_error(wasm_function_exports(b"not wasm"), "invalid WASM header");
        assert_error(
            wasm_function_exports(b"\x00asm\x01\x00\x00\x00\x07\x7f"),
            "WASM section extends beyond payload",
        );
        let mapping =
            std::fs::read(repository().join("uniswap-v2-base/reference/mappings/Factory.wasm"))
                .expect("read mapping");
        let exports = wasm_function_exports(&mapping).expect("mapping parses");
        assert!(exports.contains(&"handleNewPair".to_string()));
    }

    #[test]
    fn normalization_modes_match_the_python_contract() {
        assert_eq!(
            normalize(b"abc", &json!("identity")).expect("identity"),
            b"abc"
        );
        assert_eq!(
            normalize(b"abc\n", &json!("remove_one_trailing_lf")).expect("single LF"),
            b"abc"
        );
        assert_error(
            normalize(b"abc\n\n", &json!("remove_one_trailing_lf")),
            "normalization requires exactly one trailing LF",
        );
        assert_error(
            normalize(b"abc", &Value::Null),
            "unsupported artifact normalization: None",
        );
    }
}
