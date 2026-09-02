//! Rust port of the retired `scripts/verify-messari-v3-targets.py` (#110): the immutable
//! Messari V3 BSC/Base target and source boundary. Fail-closed — every Python
//! `require(...)` becomes an `Err` carrying the same message, and every I/O,
//! JSON, or YAML error is an `Err` as well.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::path::{Path, PathBuf};

use serde::de::{self, Deserialize, DeserializeSeed, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{json, Map, Value};

use crate::target_common::{sha256_hex, unixfs_file_cidv0};

pub const CONTRACT_PATH: &str = "docs/provenance/messari-v3-targets-v1.json";
pub const PROFILE_PATH: &str = "messari-v3/layout-profile-v1.json";
const SOURCE_PROVENANCE_PATH: &str = "docs/provenance/messari-v3-source.md";
const ROOT_README_PATH: &str = "README.md";
const TARGET_README_PATH: &str = "messari-v3/README.md";
const PROVENANCE_INDEX_PATH: &str = "docs/provenance/README.md";
const SOURCE_PROVENANCE_BYTES: usize = 2907;
const SOURCE_PROVENANCE_SHA256: &str =
    "758d4c34ee7b4028a8bbebe80d554110a7dcec7159db8c1a4e7e0dee814c02f4";

const TARGET_ORDER: [&str; 2] = ["pancakeswap-v3-bsc", "uniswap-v3-base"];
const FAMILY_ISSUES: [i64; 5] = [85, 90, 92, 94, 95];
const ROOT_M9_ISSUE_LINK_ORDER: [i64; 5] = [85, 94, 90, 92, 95];
const TARGET_M9_TRACEABILITY_ARRAYS: [[i64; 3]; 2] = [[85, 90, 92], [94, 90, 95]];

const REFERENCE_ROOT: &str = "messari-v3/reference";

// ---------------------------------------------------------------------------
// Failure plumbing
// ---------------------------------------------------------------------------

type R<T> = Result<T, String>;

fn fail<T>(message: impl Into<String>) -> R<T> {
    Err(message.into())
}

fn require(condition: bool, message: impl Into<String>) -> R<()> {
    if condition {
        Ok(())
    } else {
        fail(message)
    }
}

// ---------------------------------------------------------------------------
// Canonical / rendered JSON, byte-identical with Python `json.dumps`
// ---------------------------------------------------------------------------

/// `json.dumps(..., ensure_ascii=True)` string escaping.
fn escape_json_string(out: &mut String, value: &str) {
    out.push('"');
    for character in value.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c if (c as u32) < 0x7f => out.push(c),
            c => {
                let code = c as u32;
                if code > 0xffff {
                    let adjusted = code - 0x1_0000;
                    out.push_str(&format!("\\u{:04x}", 0xd800 + (adjusted >> 10)));
                    out.push_str(&format!("\\u{:04x}", 0xdc00 + (adjusted & 0x3ff)));
                } else {
                    out.push_str(&format!("\\u{code:04x}"));
                }
            }
        }
    }
    out.push('"');
}

/// `json.dumps(value, sort_keys=True, ensure_ascii=True)` with either the
/// compact `(",", ":")` separators or a two-space indent. `serde_json::Map` is
/// a `BTreeMap`, whose UTF-8 byte order equals Python's code-point order.
fn write_json(out: &mut String, value: &Value, indent: bool, level: usize) {
    let pad = |out: &mut String, depth: usize| {
        if indent {
            out.push('\n');
            for _ in 0..depth * 2 {
                out.push(' ');
            }
        }
    };
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(number) => out.push_str(&number.to_string()),
        Value::String(text) => escape_json_string(out, text),
        Value::Array(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                pad(out, level + 1);
                write_json(out, item, indent, level + 1);
            }
            pad(out, level);
            out.push(']');
        }
        Value::Object(entries) => {
            if entries.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (index, (key, item)) in entries.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                pad(out, level + 1);
                escape_json_string(out, key);
                out.push(':');
                if indent {
                    out.push(' ');
                }
                write_json(out, item, indent, level + 1);
            }
            pad(out, level);
            out.push('}');
        }
    }
}

fn canonical_text(value: &Value) -> String {
    let mut out = String::new();
    write_json(&mut out, value, false, 0);
    out
}

fn canonical_bytes(value: &Value) -> Vec<u8> {
    canonical_text(value).into_bytes()
}

fn canonical_sha256(value: &Value) -> String {
    sha256_hex(&canonical_bytes(value))
}

/// `json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"`.
fn render(value: &Value) -> String {
    let mut out = String::new();
    write_json(&mut out, value, true, 0);
    out.push('\n');
    out
}

// ---------------------------------------------------------------------------
// Duplicate-key-rejecting JSON and YAML loaders
// ---------------------------------------------------------------------------

const DUPLICATE_JSON_KEY: &str = "duplicate JSON key: ";
const DUPLICATE_YAML_KEY: &str = "duplicate YAML key: ";

struct UniqueValue(Value);

struct UniqueVisitor {
    yaml: bool,
}

impl<'de> Visitor<'de> for UniqueVisitor {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("any valid value")
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
        Ok(serde_json::Number::from_f64(value).map_or(Value::Null, Value::Number))
    }

    fn visit_str<E>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_string()))
    }

    fn visit_string<E>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }

    fn visit_unit<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_none<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_some<D: Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        deserializer.deserialize_any(UniqueVisitor { yaml: self.yaml })
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut access: A) -> Result<Value, A::Error> {
        let mut items = Vec::new();
        while let Some(item) = access.next_element_seed(UniqueSeed { yaml: self.yaml })? {
            items.push(item);
        }
        Ok(Value::Array(items))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut access: A) -> Result<Value, A::Error> {
        let mut entries = Map::new();
        while let Some(key) = access.next_key_seed(UniqueSeed { yaml: self.yaml })? {
            let name = match &key {
                Value::String(text) => text.clone(),
                Value::Array(_) | Value::Object(_) => {
                    return Err(de::Error::custom(format!(
                        "unhashable YAML key: {}",
                        canonical_text(&key)
                    )));
                }
                other => {
                    return Err(de::Error::custom(format!(
                        "non-string mapping key: {}",
                        canonical_text(other)
                    )));
                }
            };
            if entries.contains_key(&name) {
                let label = if self.yaml {
                    DUPLICATE_YAML_KEY
                } else {
                    DUPLICATE_JSON_KEY
                };
                return Err(de::Error::custom(format!("{label}{name}")));
            }
            let value = access.next_value_seed(UniqueSeed { yaml: self.yaml })?;
            entries.insert(name, value);
        }
        Ok(Value::Object(entries))
    }
}

struct UniqueSeed {
    yaml: bool,
}

impl<'de> de::DeserializeSeed<'de> for UniqueSeed {
    type Value = Value;

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        deserializer.deserialize_any(UniqueVisitor { yaml: self.yaml })
    }
}

impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer
            .deserialize_any(UniqueVisitor { yaml: false })
            .map(UniqueValue)
    }
}

/// Rewrite the serde-decorated duplicate-key message into the Python phrasing.
fn duplicate_message(error: &str, label: &str, path: &Path, kind: &str) -> Option<String> {
    let start = error.find(label)?;
    let tail = &error[start + label.len()..];
    let key = tail.split(" at line ").next().unwrap_or(tail);
    Some(match kind {
        "json" => format!("duplicate JSON key in {}: {key}", path.display()),
        _ => format!("duplicate YAML key: '{key}'"),
    })
}

/// Python `load_json`: rejects duplicate object keys.
fn load_json(path: &Path) -> R<Value> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    match UniqueValue::deserialize(&mut deserializer) {
        Ok(UniqueValue(value)) => {
            deserializer
                .end()
                .map_err(|error| format!("cannot parse {}: {error}", path.display()))?;
            Ok(value)
        }
        Err(error) => {
            let text = error.to_string();
            Err(duplicate_message(&text, DUPLICATE_JSON_KEY, path, "json")
                .unwrap_or_else(|| format!("cannot parse {}: {text}", path.display())))
        }
    }
}

/// Python `load_yaml_unique`: `yaml.safe_load` with duplicate keys rejected.
fn load_yaml_unique(path: &Path) -> R<Value> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let deserializer = serde_yaml::Deserializer::from_str(&text);
    match (UniqueSeed { yaml: true }).deserialize(deserializer) {
        Ok(value) => Ok(value),
        Err(error) => {
            let text = error.to_string();
            Err(duplicate_message(&text, DUPLICATE_YAML_KEY, path, "yaml")
                .unwrap_or_else(|| format!("cannot parse {}: {text}", path.display())))
        }
    }
}

fn read_bytes(path: &Path) -> R<Vec<u8>> {
    std::fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn read_text(path: &Path) -> R<String> {
    std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))
}

fn static_json(text: &str) -> Value {
    serde_json::from_str(text).expect("pinned constant JSON parses")
}

// ---------------------------------------------------------------------------
// Small Python-value helpers
// ---------------------------------------------------------------------------

fn py_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(flag) => *flag,
        Value::Number(number) => number.as_f64().is_some_and(|value| value != 0.0),
        Value::String(text) => !text.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::Object(entries) => !entries.is_empty(),
    }
}

/// Python `str(value)` for the scalars these manifests can hold.
fn py_str(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => text.clone(),
        other => canonical_text(other),
    }
}

fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    value.get(key).unwrap_or(&Value::Null)
}

fn as_str(value: &Value) -> R<&str> {
    value
        .as_str()
        .ok_or_else(|| format!("expected a string, found {}", canonical_text(value)))
}

fn object_keys(value: &Value) -> BTreeSet<String> {
    value
        .as_object()
        .map(|entries| entries.keys().cloned().collect())
        .unwrap_or_default()
}

fn key_set(names: &[&str]) -> BTreeSet<String> {
    names.iter().map(|name| (*name).to_string()).collect()
}

// ---------------------------------------------------------------------------
// Pinned constants, copied verbatim from the Python verifier
// ---------------------------------------------------------------------------

const FAMILY_ISSUES_SEMANTICS: &str = "ordered exhaustive unique M9 issue set: BSC target #85, shared implementation #90, BSC certification #92, Base target #94, Base certification #95";
const M9_DEPENDENCY_DAG: &str = "#85 + #94 -> #90 -> #92 -> #95";
const M9_DEPENDENCY_ORDER: &str = "Both target locks precede shared implementation, and BSC certification precedes Base certification.";
const ROOT_M9_SECTION: &str = "9. **M9 — Messari V3 BSC + Base**: the dependency DAG is\n   `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared\n   implementation, and BSC certification precedes Base certification. Complete the\n   PancakeSwap V3 BSC target lock in\n   [#85](https://github.com/pinax-network/substreams-backfills/issues/85) and the\n   Uniswap V3 Base target lock in\n   [#94](https://github.com/pinax-network/substreams-backfills/issues/94) before the shared\n   implementation and target adapters in\n   [#90](https://github.com/pinax-network/substreams-backfills/issues/90); then certify and\n   land BSC first in [#92](https://github.com/pinax-network/substreams-backfills/issues/92),\n   followed by Base in [#95](https://github.com/pinax-network/substreams-backfills/issues/95).\n   Shared schema shape never substitutes for the separate target locks,\n   eligibility decisions, adapters, certifications, or paused landings.";
const TARGET_M9_SECTION: &str = "The provenance contract's top-level `issues` list is the ordered, exhaustive\nunique M9 issue set: BSC target #85, shared implementation #90, BSC\ncertification #92, Base target #94, and Base certification #95. The target\nbindings retain target-local traceability associations, `[85, 90, 92]` and\n`[94, 90, 95]`; they are not independently executable chains. The dependency\nDAG is `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared\nimplementation, and BSC certification precedes Base certification.";
const PROVENANCE_M9_SECTION: &str = "[`messari-v3-targets-v1.json`](messari-v3-targets-v1.json) is the combined M9\ntarget contract for PancakeSwap V3 BSC and Uniswap V3 Base. It locks all 26\ndeployed artifacts, exact manifest/schema/ABI/WASM structure, cross-target\ndifferences, and all-false operational gates. Its ordered top-level `issues`\nlist is exhaustive for M9; the per-target bindings retain distinct BSC and Base\ntraceability associations, not independently executable chains. The dependency\nDAG is `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared\nimplementation, and BSC certification precedes Base certification. The accompanying\n[`messari-v3-source.md`](messari-v3-source.md) records the nearest pinned source\nanchors, matching malformed manifest metadata, unreproducible deleted gluegun\ndependency, and the strict source-to-WASM refusal boundary.";

const FALSE_GATES: [&str; 19] = [
    "source_revision_pinned",
    "source_reproducible",
    "source_to_wasm_build_reproduced",
    "eligibility_24_hour_passed",
    "eligibility_72_hour_passed",
    "eligibility_complete",
    "implementation_complete",
    "handler_semantics_complete",
    "runtime_behavior_complete",
    "graph_store_order_complete",
    "error_behavior_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "vid_parity_complete",
    "poi_parity_complete",
    "backfill_ready",
    "deployment_ready",
    "production_ready",
    "readiness_complete",
];

/// target, role, target-relative path, CIDv0, bytes, raw SHA-256
const ARTIFACT_ROWS: [(&str, &str, &str, &str, usize, &str); 26] = [
    (
        "pancakeswap-v3-bsc",
        "deployment",
        "deployment.yaml",
        "QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3",
        5193,
        "b63daebd56e0044dcf997534a412ff1e0e9ef803f30cf44affd0f2d7329859b6",
    ),
    (
        "pancakeswap-v3-bsc",
        "schema",
        "schema.graphql",
        "QmSY3DAk44RGNbywjXt8PznikJkNMpoNjM8UVde3Hnhocg",
        47054,
        "efdc8cc4dd6838a065ec573e28cc9218d73e9ad8858694eb836acae0f977c64a",
    ),
    (
        "pancakeswap-v3-bsc",
        "abi/ERC20",
        "abis/ERC20.json",
        "QmXuTbDkNrN27VydxbS2huvKRk62PMgUTdPDWkxcr2w7j2",
        3684,
        "4b83c6645aed2df5e4e9a1d11f372453fc052ac8575348c8c04a33ceacd0ae90",
    ),
    (
        "pancakeswap-v3-bsc",
        "abi/ERC20NameBytes",
        "abis/ERC20NameBytes.json",
        "QmQCP6Pdp1MqpwRv2qoPHuUTwZGy7Q3eDHg4w5kzwE9mBj",
        268,
        "b874c853ffa5309e4b7fbf4934c1efdb4fe31e1a65f7041e67f4a7f2258ffb77",
    ),
    (
        "pancakeswap-v3-bsc",
        "abi/ERC20SymbolBytes",
        "abis/ERC20SymbolBytes.json",
        "QmbHnhUFZa6qqqRyubUYhXntox1TCBxqryaBM1iNGqVJzT",
        270,
        "9ccb9b5d95394b2ffb4ced54cffa0c5ea282917f4eec36c121ce28c257965193",
    ),
    (
        "pancakeswap-v3-bsc",
        "abi/Factory",
        "abis/Factory.json",
        "QmYxaKG6NxTFjcWvF4VSb9Wk9F4TKLEQZidX9aC89E5CLd",
        8559,
        "6040aedf8e250e4824078449f1d6957e6db1c5a03a070db0988d00d13177448a",
    ),
    (
        "pancakeswap-v3-bsc",
        "abi/NonFungiblePositionManager",
        "abis/NonFungiblePositionManager.json",
        "QmaWAco4g2iX7B9ar65RhWXUSWSs8yQCpLxBVipzcsDycb",
        24646,
        "a06cac5c70cae9069812dce3f9d8c746a3f6988bcbb76332340509049ed0c7e6",
    ),
    (
        "pancakeswap-v3-bsc",
        "abi/Pool",
        "abis/Pool.json",
        "QmabUZX7w3JJ8QaYnpuNaZ1iHteB9LfvVwk98YATUg4hVt",
        20622,
        "d11de4a76e9daeac0998eac4b36f17fc307193ce299d54b031940b88b61fecfc",
    ),
    (
        "pancakeswap-v3-bsc",
        "abi/TickLens",
        "abis/TickLens.json",
        "Qmcew9GU9kikcwYqemJ3x6UqXq5aMs2RBJxqUPeD5Ld5dF",
        909,
        "f99008073f8d236d60d63fcc2b17d8f084e0f6e1ec02d0ec8fd8017a152a2252",
    ),
    (
        "pancakeswap-v3-bsc",
        "mapping/Factory",
        "mappings/Factory.wasm",
        "QmNyz8Cw8ZQCMcrGA9k64TJSpxsxY6duzkJhKdz2amUQ7i",
        145347,
        "653f582fb473f29d94e16624f3714f43ac05c4d44044fc4c9e03ace1100c8f57",
    ),
    (
        "pancakeswap-v3-bsc",
        "mapping/NonFungiblePositionManager",
        "mappings/NonFungiblePositionManager.wasm",
        "QmeaUSU4caeboxKLNfeMy4mjJyEND5ht3y7aAUqUnS3CoT",
        93924,
        "89f92d94e83ee622c8b9a97288c6a1124a160ac21edc0b9ee3c917ddc3c5b6b5",
    ),
    (
        "pancakeswap-v3-bsc",
        "mapping/Pool",
        "mappings/Pool.wasm",
        "QmZ8ncasTQBiLBzb9j7KKCV3Xc1zLLaqKUM9R3VkuS8f1L",
        136709,
        "2e3a917c868d739d96a7f102d6872d110e3c09e80ca0a8ab039e3ffde61ece54",
    ),
    (
        "pancakeswap-v3-bsc",
        "mapping/PancakeSwapPool",
        "mappings/PancakeSwapPool.wasm",
        "QmZh9pwyqnVEknPgTWraJweuyy1qbwzhA2rrSq43xmdgHL",
        41036,
        "cd4d3e44fd7b749ab40baf691099dc6a67d206666f3016dd82bcf2164b41c136",
    ),
    (
        "uniswap-v3-base",
        "deployment",
        "deployment.yaml",
        "QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh",
        5068,
        "d19dd5c0aa86c78161306a1beb7df754f2a5eeb066e33d99aece4251732e868b",
    ),
    (
        "uniswap-v3-base",
        "schema",
        "schema.graphql",
        "QmVrng7WZwwCMkcGuay4yEbwepyPFDJjamwmsBcC18Ef2o",
        47061,
        "e93bf39c118446d0695291d03cd1cbe959010d0b00e18d610e5739711fb3411c",
    ),
    (
        "uniswap-v3-base",
        "abi/ERC20",
        "abis/ERC20.json",
        "QmXuTbDkNrN27VydxbS2huvKRk62PMgUTdPDWkxcr2w7j2",
        3684,
        "4b83c6645aed2df5e4e9a1d11f372453fc052ac8575348c8c04a33ceacd0ae90",
    ),
    (
        "uniswap-v3-base",
        "abi/ERC20NameBytes",
        "abis/ERC20NameBytes.json",
        "QmQCP6Pdp1MqpwRv2qoPHuUTwZGy7Q3eDHg4w5kzwE9mBj",
        268,
        "b874c853ffa5309e4b7fbf4934c1efdb4fe31e1a65f7041e67f4a7f2258ffb77",
    ),
    (
        "uniswap-v3-base",
        "abi/ERC20SymbolBytes",
        "abis/ERC20SymbolBytes.json",
        "QmbHnhUFZa6qqqRyubUYhXntox1TCBxqryaBM1iNGqVJzT",
        270,
        "9ccb9b5d95394b2ffb4ced54cffa0c5ea282917f4eec36c121ce28c257965193",
    ),
    (
        "uniswap-v3-base",
        "abi/Factory",
        "abis/Factory.json",
        "QmTU8eKx6pCgtff6Uvc7srAwR8BPiM3jTMBw9ahrXBjRzY",
        3703,
        "daa769db333fa28d331cc0d866a666ebb98c995a915cb44828a801608ab0d1c1",
    ),
    (
        "uniswap-v3-base",
        "abi/NonFungiblePositionManager",
        "abis/NonFungiblePositionManager.json",
        "QmaxxqQ7xzbGDPWu184uoq2g5sofazB9B9tEDrpPjmRZ8q",
        23334,
        "456c1726a11497a2b12e719111381203a1e96178ea4547af63e8947dc19490cd",
    ),
    (
        "uniswap-v3-base",
        "abi/Pool",
        "abis/Pool.json",
        "QmQ5rynzbQYpebSAUFfnTYm9KDUumWYF5eQb9QRwRLPfwB",
        19599,
        "11ea051e74b9a1bbfa9263dcd28dd4bd9df4898d7b02a79b7fcf545e732dcd4d",
    ),
    (
        "uniswap-v3-base",
        "abi/TickLens",
        "abis/TickLens.json",
        "Qmcew9GU9kikcwYqemJ3x6UqXq5aMs2RBJxqUPeD5Ld5dF",
        909,
        "f99008073f8d236d60d63fcc2b17d8f084e0f6e1ec02d0ec8fd8017a152a2252",
    ),
    (
        "uniswap-v3-base",
        "mapping/Factory",
        "mappings/Factory.wasm",
        "QmUJsAqcUbk4CpQxvQyJ7igo5PQknNJgAj1cupLiW21Ejc",
        148830,
        "2bbbd2960df7e0e3761b08fac5fbb2d966dcda0c017c5ff1f22107131b895708",
    ),
    (
        "uniswap-v3-base",
        "mapping/NonFungiblePositionManager",
        "mappings/NonFungiblePositionManager.wasm",
        "Qmb3aYhcaVXLT3ouQypKqvC9b62SsdkQwznuabnhdmYLd5",
        97112,
        "f79d4563dbe0e0cef8bf4ff28bfc2e84b6e89e18e4ae39262f5deac18f767e6e",
    ),
    (
        "uniswap-v3-base",
        "mapping/Pool",
        "mappings/Pool.wasm",
        "QmS9917TbXgmD87MaTpE3asELcn86umKBLJbJUENnZasaz",
        140823,
        "a4df46dfbea334093106d21c1eb9553a8bfa65eb6ff3262c3cff0286a7cf6e96",
    ),
    (
        "uniswap-v3-base",
        "mapping/UniswapPool",
        "mappings/UniswapPool.wasm",
        "QmXExJr8roifEnTDRLWx8AvooEQ7EzdrWTnLi4qVfvFh9f",
        41790,
        "e997b968a6e656d5c57af1016510ed8cdbf4ee980bc4446dd87f6c01d6dc261f",
    ),
];

/// (target, role) -> (export count, export-table canonical SHA-256, handler export order)
const EXPECTED_WASM_EXPORTS: [(&str, &str, usize, &str, &[&str]); 8] = [
    (
        "pancakeswap-v3-bsc",
        "mapping/Factory",
        170,
        "65b3cd9491855f2343c3d26761ee557057a0aea6976ef9a26dce850d28e4547a",
        &["handlePoolCreated"],
    ),
    (
        "pancakeswap-v3-bsc",
        "mapping/NonFungiblePositionManager",
        173,
        "4844a2787ab3aeb78fe4bcfb6eac8f6674515737ffa6f4fd7d228484fdc34cb3",
        &[
            "handleIncreaseLiquidity",
            "handleDecreaseLiquidity",
            "handleTransfer",
        ],
    ),
    (
        "pancakeswap-v3-bsc",
        "mapping/Pool",
        174,
        "0d40fcc7551dc2809e2bd9dbc1cf7fabaeebf83431eabd0276eec243d583cbb6",
        &[
            "handleInitialize",
            "handleMint",
            "handleBurn",
            "handleSwap",
            "handleCollectPool",
        ],
    ),
    (
        "pancakeswap-v3-bsc",
        "mapping/PancakeSwapPool",
        170,
        "c1ec6e69f4417cff0edf9fc282c0ec4da00928fe3df9fd7efb0375747ef6ce24",
        &["handleSetFeeProtocol"],
    ),
    (
        "uniswap-v3-base",
        "mapping/Factory",
        172,
        "e2ff41cc934187de9c320eba6b220dde316ceefd098a77c0fe8129090848468f",
        &["handlePoolCreated"],
    ),
    (
        "uniswap-v3-base",
        "mapping/NonFungiblePositionManager",
        175,
        "8cd6408cbc8d7b9af50b6eb543f1dcce83ad994f14947723aed1dbeba4e742aa",
        &[
            "handleIncreaseLiquidity",
            "handleDecreaseLiquidity",
            "handleTransfer",
        ],
    ),
    (
        "uniswap-v3-base",
        "mapping/Pool",
        176,
        "167c34cbc4468a36cf7a0f87e1c5cfe0f40b7f92116a028a6d0167aa45a60977",
        &[
            "handleInitialize",
            "handleMint",
            "handleBurn",
            "handleSwap",
            "handleCollectPool",
        ],
    ),
    (
        "uniswap-v3-base",
        "mapping/UniswapPool",
        172,
        "d2176ed3a0944f05c0229de38f6e996e14a34ad8ea3d549e99992c0983a72d29",
        &["handleSetFeeProtocol"],
    ),
];

const SOURCE_ANCHORS_JSON: &str = r#"{
  "pancakeswap-v3-bsc": {
    "abi_result": "Factory, NonFungiblePositionManager, Pool, and TickLens JSON values are semantically identical; deployed formatting remains independently locked",
    "commit": "0c4618d6343b5011742a59ec308dd7ce07b9908b",
    "committed_at": "2023-05-30T20:55:00Z",
    "parent": "6af451686c1dc783f823e51b28686ef95d219c16",
    "repository": "https://github.com/messari/subgraphs",
    "schema_byte_identical": true,
    "schema_source_path": "subgraphs/uniswap-v3-forks/schema.graphql",
    "source_template_entity_metadata_matches_deployment": true,
    "tree": "1a309dcd6e8827db41a00634eaab6d1e1ed70da6"
  },
  "uniswap-v3-base": {
    "abi_result": "Factory, NonFungiblePositionManager, and Pool match after removing one repository trailing LF; deployed TickLens remains independently locked",
    "commit": "2c60bd10b5e1a090f6e3b55f0634f2a15ec91dbe",
    "committed_at": "2023-08-14T15:07:15Z",
    "parent": "b16e506a84247a178a9eae09e799bc75787f4275",
    "repository": "https://github.com/messari/subgraphs",
    "schema_byte_identical": true,
    "schema_source_path": "subgraphs/uniswap-v3-forks/schema.graphql",
    "source_template_entity_metadata_matches_deployment": true,
    "tree": "3a2ff3eec89f6ab6f1f61d3c10a546c231c3f06b"
  }
}"#;

const SOURCE_REPRODUCTION_JSON: &str = r#"{
  "boundary": "source commits are behavioral anchors, not exact mapping-WASM reproduction workspaces",
  "deleted_dependency": {
    "available": false,
    "checked_at": "2026-08-31",
    "commit": "b34b9003d7bf556836da41b57ef36eb21570620a",
    "frozen_npm_install_succeeded": false,
    "frozen_yarn_install_succeeded": false,
    "repository": "https://github.com/edgeandnode/gluegun"
  },
  "deployed_manifest_spec_version": "0.0.4",
  "source_template_mapping_entity_metadata": {
    "duplicate_multiplicity_by_role": {
      "Factory": {},
      "NonFungiblePositionManager": {},
      "fee_only_template": {},
      "primary_pool": {
        "Token": 2
      }
    },
    "matches_deployed_manifests_by_role": true,
    "missing_from_schema_type_declarations_by_role": {
      "Factory": [
        "_PricesUSD",
        "_TokenTracker"
      ],
      "NonFungiblePositionManager": [],
      "fee_only_template": [
        "LiqudityPool"
      ],
      "primary_pool": [
        "LiqudityPool",
        "PoolDailySnapshot",
        "_PricesUSD",
        "_Account",
        "_DailyActiveAccount",
        "_TokenTracker"
      ]
    },
    "normalization_allowed": false
  },
  "source_template_spec_version": "0.0.2",
  "spec_version_mismatch": true
}"#;

const MISSING_MAPPING_ENTITIES_BY_ROLE_JSON: &str = r#"{
  "Factory": [
    "_PricesUSD",
    "_TokenTracker"
  ],
  "NonFungiblePositionManager": [],
  "fee_only_template": [
    "LiqudityPool"
  ],
  "primary_pool": [
    "LiqudityPool",
    "PoolDailySnapshot",
    "_PricesUSD",
    "_Account",
    "_DailyActiveAccount",
    "_TokenTracker"
  ]
}"#;

const DUPLICATE_MAPPING_ENTITIES_BY_ROLE_JSON: &str = r#"{
  "Factory": {},
  "NonFungiblePositionManager": {},
  "fee_only_template": {},
  "primary_pool": {
    "Token": 2
  }
}"#;

const EXPECTED_BINDINGS_JSON: &str = r#"{
  "pancakeswap-v3-bsc": {
    "bytes": 624,
    "path": "messari-v3/QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3.yaml",
    "sha256": "966aaac1fa23254e0704caf5337e827ea62e1ab5d6d0d5c9ca49eff92ac5c3c0",
    "value": {
      "chain": "bsc",
      "deployment": "QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3",
      "eligibility": {
        "latest": {
          "decision": "indeterminate",
          "evidence": null,
          "measured_at": null,
          "reason": "no_fresh_evidence",
          "sha256": null
        },
        "policy": "graph-node-net-catchup-v1",
        "required_clusters": [
          "riv-subgraphs-a",
          "kan-subgraphs-a"
        ]
      },
      "family": "messari-v3",
      "issues": [
        85,
        90,
        92
      ],
      "market_snapshot": {
        "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 143319,
        "query_fees_grt_24h": "170.760"
      },
      "milestone": "M9",
      "schema": "QmSY3DAk44RGNbywjXt8PznikJkNMpoNjM8UVde3Hnhocg",
      "variant": "pancakeswap-v3-bsc"
    }
  },
  "uniswap-v3-base": {
    "bytes": 620,
    "path": "messari-v3/QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh.yaml",
    "sha256": "686be8c73a8ef4be78f0eb88c64f665ef40b22bfb9ba080f13f692b578673d0b",
    "value": {
      "chain": "base",
      "deployment": "QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh",
      "eligibility": {
        "latest": {
          "decision": "indeterminate",
          "evidence": null,
          "measured_at": null,
          "reason": "no_fresh_evidence",
          "sha256": null
        },
        "policy": "graph-node-net-catchup-v1",
        "required_clusters": [
          "riv-subgraphs-a",
          "kan-subgraphs-a"
        ]
      },
      "family": "messari-v3",
      "issues": [
        94,
        90,
        95
      ],
      "market_snapshot": {
        "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 17568,
        "query_fees_grt_24h": "21.000"
      },
      "milestone": "M9",
      "schema": "QmVrng7WZwwCMkcGuay4yEbwepyPFDJjamwmsBcC18Ef2o",
      "variant": "uniswap-v3-base"
    }
  }
}"#;

const TARGET_EXPECTATIONS_JSON: &str = r#"{
  "pancakeswap-v3-bsc": {
    "chain": "bsc",
    "components": [
      [
        "data_source",
        "Factory",
        {
          "abi": "Factory",
          "address": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
          "startBlock": 26956207
        },
        "mapping/Factory"
      ],
      [
        "data_source",
        "NonFungiblePositionManager",
        {
          "abi": "NonFungiblePositionManager",
          "address": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
          "startBlock": 26931961
        },
        "mapping/NonFungiblePositionManager"
      ],
      [
        "template",
        "Pool",
        {
          "abi": "Pool"
        },
        "mapping/Pool"
      ],
      [
        "template",
        "PancakeSwapPool",
        {
          "abi": "Pool"
        },
        "mapping/PancakeSwapPool"
      ]
    ],
    "deployment": "QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3",
    "handlers": {
      "Factory": [
        [
          "handlePoolCreated",
          "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)"
        ]
      ],
      "NonFungiblePositionManager": [
        [
          "handleIncreaseLiquidity",
          "IncreaseLiquidity(indexed uint256,uint128,uint256,uint256)"
        ],
        [
          "handleDecreaseLiquidity",
          "DecreaseLiquidity(indexed uint256,uint128,uint256,uint256)"
        ],
        [
          "handleTransfer",
          "Transfer(indexed address,indexed address,indexed uint256)"
        ]
      ],
      "PancakeSwapPool": [
        [
          "handleSetFeeProtocol",
          "SetFeeProtocol(uint32,uint32,uint32,uint32)"
        ]
      ],
      "Pool": [
        [
          "handleInitialize",
          "Initialize(uint160,int24)"
        ],
        [
          "handleSetFeeProtocol",
          "SetFeeProtocol(uint32,uint32,uint32,uint32)"
        ],
        [
          "handleCollectPool",
          "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)"
        ],
        [
          "handleSwap",
          "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24,uint128,uint128)"
        ],
        [
          "handleMint",
          "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"
        ],
        [
          "handleBurn",
          "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"
        ]
      ]
    },
    "manifest_semantic_sha256": "9c436b233668a744805d509c32a5c05ad3c698db7adca89eb9958e2cf035cfe0",
    "schema": "QmSY3DAk44RGNbywjXt8PznikJkNMpoNjM8UVde3Hnhocg"
  },
  "uniswap-v3-base": {
    "chain": "base",
    "components": [
      [
        "data_source",
        "Factory",
        {
          "abi": "Factory",
          "address": "0x33128a8fc17869897dce68ed026d694621f6fdfd",
          "startBlock": 1371670
        },
        "mapping/Factory"
      ],
      [
        "data_source",
        "NonFungiblePositionManager",
        {
          "abi": "NonFungiblePositionManager",
          "address": "0x03a520b32c04bf3beef7beb72e919cf822ed34f1",
          "startBlock": 1371704
        },
        "mapping/NonFungiblePositionManager"
      ],
      [
        "template",
        "Pool",
        {
          "abi": "Pool"
        },
        "mapping/Pool"
      ],
      [
        "template",
        "UniswapPool",
        {
          "abi": "Pool"
        },
        "mapping/UniswapPool"
      ]
    ],
    "deployment": "QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh",
    "handlers": {
      "Factory": [
        [
          "handlePoolCreated",
          "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)"
        ]
      ],
      "NonFungiblePositionManager": [
        [
          "handleIncreaseLiquidity",
          "IncreaseLiquidity(indexed uint256,uint128,uint256,uint256)"
        ],
        [
          "handleDecreaseLiquidity",
          "DecreaseLiquidity(indexed uint256,uint128,uint256,uint256)"
        ],
        [
          "handleTransfer",
          "Transfer(indexed address,indexed address,indexed uint256)"
        ]
      ],
      "Pool": [
        [
          "handleInitialize",
          "Initialize(uint160,int24)"
        ],
        [
          "handleCollectPool",
          "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)"
        ],
        [
          "handleSwap",
          "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24)"
        ],
        [
          "handleMint",
          "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"
        ],
        [
          "handleBurn",
          "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"
        ]
      ],
      "UniswapPool": [
        [
          "handleSetFeeProtocol",
          "SetFeeProtocol(uint8,uint8,uint8,uint8)"
        ]
      ]
    },
    "manifest_semantic_sha256": "e3475a732c94ab2985ae39c8bf058b80e411b5d6fbaf3a9f2f9aee29792e19bc",
    "schema": "QmVrng7WZwwCMkcGuay4yEbwepyPFDJjamwmsBcC18Ef2o"
  }
}"#;

const EXPECTED_ENTRY_LEDGERS_JSON: &str = r#"{
  "Factory": {
    "entry_identities_only_base": [],
    "entry_identities_only_pancakeswap": [
      "constructor:constructor(address)",
      "event:FeeAmountExtraInfoUpdated(uint24,bool,bool)",
      "event:SetLmPoolDeployer(address)",
      "event:WhiteListAdded(address,bool)",
      "function:collectProtocol(address,address,uint128,uint128)",
      "function:feeAmountTickSpacingExtraInfo(uint24)",
      "function:lmPoolDeployer()",
      "function:poolDeployer()",
      "function:setFeeAmountExtraInfo(uint24,bool,bool)",
      "function:setFeeProtocol(address,uint32,uint32)",
      "function:setLmPool(address,address)",
      "function:setLmPoolDeployer(address)",
      "function:setWhiteListAddress(address,bool)"
    ],
    "field_difference_paths": {
      "function:feeAmountTickSpacing(uint24)": [
        "/inputs/0/name"
      ],
      "function:getPool(address,address,uint24)": [
        "/inputs/0/name",
        "/inputs/1/name",
        "/inputs/2/name",
        "/outputs/0/name"
      ]
    },
    "metadata_difference_identities": [
      "function:feeAmountTickSpacing(uint24)",
      "function:getPool(address,address,uint24)"
    ],
    "semantic_difference_identities": []
  },
  "NonFungiblePositionManager": {
    "entry_identities_only_base": [
      "constructor:constructor(address,address,address)",
      "function:collect(uint256,address,uint128,uint128)",
      "function:decreaseLiquidity(uint256,uint128,uint256,uint256,uint256)",
      "function:increaseLiquidity(uint256,uint256,uint256,uint256,uint256,uint256)",
      "function:uniswapV3MintCallback(uint256,uint256,bytes)"
    ],
    "entry_identities_only_pancakeswap": [
      "constructor:constructor(address,address,address,address)",
      "function:collect((uint256,address,uint128,uint128))",
      "function:decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))",
      "function:deployer()",
      "function:increaseLiquidity((uint256,uint256,uint256,uint256,uint256,uint256))",
      "function:pancakeV3MintCallback(uint256,uint256,bytes)",
      "function:refundETH()"
    ],
    "field_difference_paths": {
      "function:createAndInitializePoolIfNecessary(address,address,uint24,uint160)": [
        "/inputs/0/name",
        "/inputs/1/name"
      ]
    },
    "metadata_difference_identities": [
      "function:createAndInitializePoolIfNecessary(address,address,uint24,uint160)"
    ],
    "semantic_difference_identities": []
  },
  "Pool": {
    "entry_identities_only_base": [
      "event:SetFeeProtocol(uint8,uint8,uint8,uint8)",
      "event:Swap(address,address,int256,int256,uint160,uint128,int24)",
      "function:setFeeProtocol(uint8,uint8)"
    ],
    "entry_identities_only_pancakeswap": [
      "event:SetFeeProtocol(uint32,uint32,uint32,uint32)",
      "event:SetLmPoolEvent(address)",
      "event:Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)",
      "function:lmPool()",
      "function:setFeeProtocol(uint32,uint32)",
      "function:setLmPool(address)"
    ],
    "field_difference_paths": {
      "event:Burn(address,int24,int24,uint128,uint256,uint256)": [
        "/inputs/4/internalType"
      ],
      "function:observations(uint256)": [
        "/inputs/0/name"
      ],
      "function:positions(bytes32)": [
        "/inputs/0/name",
        "/outputs/0/name"
      ],
      "function:slot0()": [
        "/outputs/5/internalType",
        "/outputs/5/type"
      ],
      "function:tickBitmap(int16)": [
        "/inputs/0/name"
      ],
      "function:ticks(int24)": [
        "/inputs/0/name"
      ]
    },
    "metadata_difference_identities": [
      "event:Burn(address,int24,int24,uint128,uint256,uint256)",
      "function:observations(uint256)",
      "function:positions(bytes32)",
      "function:slot0()",
      "function:tickBitmap(int16)",
      "function:ticks(int24)"
    ],
    "semantic_difference_identities": [
      "function:slot0()"
    ]
  }
}"#;

const EXPECTED_INDEX_DIFFERENCES_JSON: &str = r#"{
  "Factory": [
    [
      "TypeId.ArweaveBlock",
      "global",
      183,
      185
    ],
    [
      "TypeId.ArweaveProofOfAccess",
      "global",
      184,
      186
    ],
    [
      "TypeId.ArweaveTag",
      "global",
      185,
      187
    ],
    [
      "TypeId.ArweaveTagArray",
      "global",
      186,
      188
    ],
    [
      "TypeId.ArweaveTransaction",
      "global",
      187,
      189
    ],
    [
      "TypeId.ArweaveTransactionArray",
      "global",
      188,
      190
    ],
    [
      "TypeId.ArweaveTransactionWithBlockPtr",
      "global",
      189,
      191
    ],
    [
      "__rtti_base",
      "global",
      190,
      192
    ]
  ],
  "NonFungiblePositionManager": [
    [
      "TypeId.ArweaveBlock",
      "global",
      176,
      178
    ],
    [
      "TypeId.ArweaveProofOfAccess",
      "global",
      177,
      179
    ],
    [
      "TypeId.ArweaveTag",
      "global",
      178,
      180
    ],
    [
      "TypeId.ArweaveTagArray",
      "global",
      179,
      181
    ],
    [
      "TypeId.ArweaveTransaction",
      "global",
      180,
      182
    ],
    [
      "TypeId.ArweaveTransactionArray",
      "global",
      181,
      183
    ],
    [
      "TypeId.ArweaveTransactionWithBlockPtr",
      "global",
      182,
      184
    ],
    [
      "__collect",
      "function",
      138,
      136
    ],
    [
      "__rtti_base",
      "global",
      183,
      185
    ],
    [
      "__unpin",
      "function",
      137,
      135
    ],
    [
      "_start",
      "function",
      143,
      141
    ],
    [
      "allocate",
      "function",
      136,
      134
    ],
    [
      "handleDecreaseLiquidity",
      "function",
      133,
      131
    ],
    [
      "handleIncreaseLiquidity",
      "function",
      132,
      130
    ],
    [
      "handleTransfer",
      "function",
      134,
      132
    ],
    [
      "id_of_type",
      "function",
      135,
      133
    ]
  ],
  "fee_only_pool": [
    [
      "TypeId.ArweaveBlock",
      "global",
      169,
      171
    ],
    [
      "TypeId.ArweaveProofOfAccess",
      "global",
      170,
      172
    ],
    [
      "TypeId.ArweaveTag",
      "global",
      171,
      173
    ],
    [
      "TypeId.ArweaveTagArray",
      "global",
      172,
      174
    ],
    [
      "TypeId.ArweaveTransaction",
      "global",
      173,
      175
    ],
    [
      "TypeId.ArweaveTransactionArray",
      "global",
      174,
      176
    ],
    [
      "TypeId.ArweaveTransactionWithBlockPtr",
      "global",
      175,
      177
    ],
    [
      "__collect",
      "function",
      48,
      49
    ],
    [
      "__rtti_base",
      "global",
      176,
      178
    ],
    [
      "__unpin",
      "function",
      47,
      48
    ],
    [
      "_start",
      "function",
      50,
      51
    ],
    [
      "allocate",
      "function",
      46,
      47
    ],
    [
      "handleSetFeeProtocol",
      "function",
      44,
      45
    ],
    [
      "id_of_type",
      "function",
      45,
      46
    ]
  ],
  "primary_pool": [
    [
      "TypeId.ArweaveBlock",
      "global",
      177,
      179
    ],
    [
      "TypeId.ArweaveProofOfAccess",
      "global",
      178,
      180
    ],
    [
      "TypeId.ArweaveTag",
      "global",
      179,
      181
    ],
    [
      "TypeId.ArweaveTagArray",
      "global",
      180,
      182
    ],
    [
      "TypeId.ArweaveTransaction",
      "global",
      181,
      183
    ],
    [
      "TypeId.ArweaveTransactionArray",
      "global",
      182,
      184
    ],
    [
      "TypeId.ArweaveTransactionWithBlockPtr",
      "global",
      183,
      185
    ],
    [
      "__rtti_base",
      "global",
      184,
      186
    ]
  ]
}"#;

const EXPECTED_BASE_ONLY_JSON: &str = r#"[
  {
    "kind": "global",
    "name": "TypeId.CosmosMessageData"
  },
  {
    "kind": "global",
    "name": "TypeId.CosmosTransactionContext"
  }
]"#;

const EXPECTED_PRIMARY_ENTITIES_JSON: &str = r#"[
  "LiqudityPool",
  "Token",
  "Deposit",
  "Withdraw",
  "Swap",
  "LiquidityPool",
  "DexAmmProtocol",
  "Token",
  "UsageMetricsDailySnapshot",
  "FinancialsDailySnapshot",
  "PoolDailySnapshot",
  "_PricesUSD",
  "_Account",
  "_DailyActiveAccount",
  "_TokenTracker",
  "_LiquidityPoolAmount"
]"#;

// ---------------------------------------------------------------------------
// Hand-rolled equivalents of the verifier's regular expressions
// ---------------------------------------------------------------------------

fn is_ident_start(c: char) -> bool {
    c == '_' || c.is_ascii_alphabetic()
}

fn is_ident_char(c: char) -> bool {
    c == '_' || c.is_ascii_alphanumeric()
}

fn is_word_char(c: char) -> bool {
    c == '_' || c.is_ascii_alphanumeric()
}

/// `[_A-Za-z][_0-9A-Za-z]*` anchored at the start of `text`.
fn take_ident(text: &str) -> Option<(&str, &str)> {
    let first = text.chars().next()?;
    if !is_ident_start(first) {
        return None;
    }
    let end = text
        .char_indices()
        .find(|(_, c)| !is_ident_char(*c))
        .map_or(text.len(), |(index, _)| index);
    Some((&text[..end], &text[end..]))
}

fn take_digits(text: &str) -> Option<(&str, &str)> {
    let end = text
        .char_indices()
        .find(|(_, c)| !c.is_ascii_digit())
        .map_or(text.len(), |(index, _)| index);
    if end == 0 {
        None
    } else {
        Some((&text[..end], &text[end..]))
    }
}

/// `" ".join(value.split())`, matching `re.sub(r"\s+", " ", value).strip()`.
fn collapse_whitespace(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn strip_whitespace(text: &str) -> String {
    text.chars().filter(|c| !c.is_whitespace()).collect()
}

/// Python `normalize_event`.
fn normalize_event(value: &Value) -> R<String> {
    let text = value
        .as_str()
        .ok_or("manifest event signature must be a string")?;
    Ok(collapse_whitespace(text))
}

/// `re.findall(r"@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?", value)`, whitespace stripped.
fn normalized_directives(text: &str) -> Vec<String> {
    let mut result = Vec::new();
    let bytes = text.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] != b'@' {
            index += 1;
            continue;
        }
        let rest = &text[index + 1..];
        let Some((name, after)) = take_ident(rest) else {
            index += 1;
            continue;
        };
        let mut end = index + 1 + name.len();
        if after.starts_with('(') {
            if let Some(close) = after.find(')') {
                end += close + 1;
            }
        }
        result.push(strip_whitespace(&text[index..end]));
        index = end;
    }
    result
}

/// `^type\s+([_A-Za-z][_0-9A-Za-z]*)(.*?)\{\s*$` against one stripped line.
fn type_declaration(line: &str) -> Option<(String, String)> {
    let rest = line.strip_prefix("type")?;
    if !rest.starts_with(char::is_whitespace) {
        return None;
    }
    let rest = rest.trim_start();
    let (name, tail) = take_ident(rest)?;
    // Non-greedy `.*?`: the first `{` whose suffix is entirely whitespace.
    for (offset, character) in tail.char_indices() {
        if character == '{' && tail[offset + 1..].chars().all(char::is_whitespace) {
            return Some((name.to_string(), tail[..offset].to_string()));
        }
    }
    None
}

/// `^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)`.
fn field_declaration(line: &str) -> Option<(String, String)> {
    let (name, tail) = take_ident(line)?;
    let tail = tail.trim_start().strip_prefix(':')?.trim_start();
    let end = tail
        .char_indices()
        .find(|(_, c)| !(c.is_ascii_alphanumeric() || matches!(c, '[' | ']' | '!' | '_')))
        .map_or(tail.len(), |(index, _)| index);
    if end == 0 {
        return None;
    }
    Some((name.to_string(), tail[..end].to_string()))
}

/// `re.search(r"^# Version: ([0-9.]+)$", text, re.MULTILINE)`.
fn schema_version_marker(text: &str) -> Option<String> {
    for line in text.split('\n') {
        if let Some(rest) = line.strip_prefix("# Version: ") {
            if !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit() || c == '.') {
                return Some(rest.to_string());
            }
        }
    }
    None
}

/// `re.search(r"enum Network\s*\{(.*?)\n\}", text, re.DOTALL)`, group 1.
fn network_enum_body(text: &str) -> Option<&str> {
    let mut search = 0;
    while let Some(offset) = text[search..].find("enum Network") {
        let start = search + offset + "enum Network".len();
        let body = text[start..].trim_start();
        if let Some(inner) = body.strip_prefix('{') {
            if let Some(end) = inner.find("\n}") {
                return Some(&inner[..end]);
            }
        }
        search = search + offset + 1;
    }
    None
}

/// `re.fullmatch(r"[_A-Z][_A-Z0-9]*", value)`.
fn is_network_enum_value(value: &str) -> bool {
    let mut characters = value.chars();
    let Some(first) = characters.next() else {
        return false;
    };
    if !(first == '_' || first.is_ascii_uppercase()) {
        return false;
    }
    characters.all(|c| c == '_' || c.is_ascii_uppercase() || c.is_ascii_digit())
}

const TYPE_KEYWORDS: [&str; 6] = ["type", "interface", "enum", "scalar", "input", "union"];

/// `re.findall(r"^(?:type|interface|enum|scalar|input|union)\s+([_A-Za-z][_0-9A-Za-z]*)",
/// text, re.MULTILINE)`; `\s` spans newlines, so this scans the whole text.
fn declared_type_names(text: &str) -> Vec<String> {
    let mut names = BTreeSet::new();
    for start in line_starts(text) {
        let rest = &text[start..];
        for keyword in TYPE_KEYWORDS {
            let Some(tail) = rest.strip_prefix(keyword) else {
                continue;
            };
            if !tail.starts_with(char::is_whitespace) {
                continue;
            }
            if let Some((name, _)) = take_ident(tail.trim_start()) {
                names.insert(name.to_string());
                break;
            }
        }
    }
    names.into_iter().collect()
}

fn line_starts(text: &str) -> Vec<usize> {
    let mut starts = vec![0];
    starts.extend(
        text.char_indices()
            .filter(|(_, c)| *c == '\n')
            .map(|(index, _)| index + 1)
            .filter(|index| *index <= text.len()),
    );
    starts
}

/// `re.compile(r"(?m)^[0-9]+\. \*\*M[0-9]+ — ").search(tail)` start offset.
fn milestone_heading_start(text: &str) -> Option<usize> {
    for start in line_starts(text) {
        let rest = &text[start..];
        let Some((_, tail)) = take_digits(rest) else {
            continue;
        };
        let Some(tail) = tail.strip_prefix(". **M") else {
            continue;
        };
        let Some((_, tail)) = take_digits(tail) else {
            continue;
        };
        if tail.starts_with(" — ") {
            return Some(start);
        }
    }
    None
}

/// `ISSUE_HREF_PATTERN.findall(section)`.
fn issue_hrefs(section: &str) -> Vec<i64> {
    const PREFIX: &str = "https://github.com/pinax-network/substreams-backfills/issues/";
    let mut result = Vec::new();
    let mut search = 0;
    while let Some(offset) = section[search..].find(PREFIX) {
        let start = search + offset + PREFIX.len();
        match take_digits(&section[start..]) {
            Some((digits, _)) => {
                if let Ok(value) = digits.parse::<i64>() {
                    result.push(value);
                }
                search = start + digits.len();
            }
            None => search = search + offset + 1,
        }
    }
    result
}

/// `TRACEABILITY_ARRAY_PATTERN.findall(section)` parsed into integer tuples.
fn traceability_arrays(section: &str) -> Vec<Vec<i64>> {
    let mut result = Vec::new();
    let bytes = section.as_bytes();
    let mut index = 0;
    while index + 1 < bytes.len() {
        if bytes[index] != b'`' || bytes[index + 1] != b'[' {
            index += 1;
            continue;
        }
        let mut cursor = &section[index + 2..];
        let mut values = Vec::new();
        let matched = loop {
            let Some((digits, rest)) = take_digits(cursor) else {
                break false;
            };
            let Ok(value) = digits.parse::<i64>() else {
                break false;
            };
            values.push(value);
            cursor = rest;
            if let Some(rest) = cursor.strip_prefix(", ") {
                cursor = rest;
                continue;
            }
            break cursor.starts_with("]`");
        };
        if matched {
            let consumed = section.len() - cursor.len() + 2;
            result.push(values);
            index = consumed;
        } else {
            index += 1;
        }
    }
    result
}

/// `ISSUE_DAG_PATTERN.findall(normalized)`.
fn issue_dags(text: &str) -> Vec<String> {
    let mut result = Vec::new();
    let bytes = text.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] != b'#' {
            index += 1;
            continue;
        }
        let Some((_, mut cursor)) = take_digits(&text[index + 1..]) else {
            index += 1;
            continue;
        };
        let mut repetitions = 0;
        loop {
            let trimmed = cursor.trim_start();
            let after = match trimmed.strip_prefix("->") {
                Some(rest) => rest,
                None => match trimmed.strip_prefix('+') {
                    Some(rest) => rest,
                    None => break,
                },
            };
            let after = after.trim_start();
            let Some(after) = after.strip_prefix('#') else {
                break;
            };
            let Some((_, rest)) = take_digits(after) else {
                break;
            };
            repetitions += 1;
            cursor = rest;
        }
        if repetitions > 0 {
            let end = text.len() - cursor.len();
            result.push(text[index..end].to_string());
            index = end;
        } else {
            index += 1;
        }
    }
    result
}

/// The four `CONTRADICTORY_M9_ORDERING_PATTERNS`, expanded to literals.
fn contradictory_phrases() -> Vec<String> {
    let mut phrases = Vec::new();
    for verb in ["precedes", "comes before", "must precede"] {
        phrases.push(format!("base certification {verb} bsc certification"));
    }
    for verb in ["follows", "comes after", "must follow"] {
        phrases.push(format!("bsc certification {verb} base certification"));
    }
    for verb in ["precedes", "comes before", "must precede"] {
        for prefix in ["", "both "] {
            phrases.push(format!("shared implementation {verb} {prefix}target locks"));
        }
    }
    for verb in ["follow", "come after", "must follow"] {
        for prefix in ["", "both "] {
            phrases.push(format!("{prefix}target locks {verb} shared implementation"));
        }
    }
    phrases
}

/// Case-insensitive search with `\b` boundaries at both ends.
fn contains_bounded(haystack_lower: &str, needle: &str) -> bool {
    let mut search = 0;
    while let Some(offset) = haystack_lower[search..].find(needle) {
        let start = search + offset;
        let end = start + needle.len();
        let before_ok = haystack_lower[..start]
            .chars()
            .next_back()
            .is_none_or(|c| !is_word_char(c));
        let after_ok = haystack_lower[end..]
            .chars()
            .next()
            .is_none_or(|c| !is_word_char(c));
        if before_ok && after_ok {
            return true;
        }
        search = start + 1;
    }
    false
}

// ---------------------------------------------------------------------------
// IPFS, WebAssembly, and ABI primitives
// ---------------------------------------------------------------------------

/// Python `cid_from_file`: `{"/": "/ipfs/Qm…"}` → `Qm…`.
fn cid_from_file(value: &Value) -> R<String> {
    let object = value
        .as_object()
        .filter(|entries| entries.len() == 1 && entries.contains_key("/"));
    let Some(entries) = object else {
        return fail(format!(
            "invalid IPFS file object: {}",
            canonical_text(value)
        ));
    };
    let location = &entries["/"];
    match location.as_str() {
        Some(text) if text.starts_with("/ipfs/Qm") => Ok(text["/ipfs/".len()..].to_string()),
        _ => fail(format!("invalid IPFS path: {}", canonical_text(location))),
    }
}

fn read_uleb(payload: &[u8], mut offset: usize) -> R<(u64, usize)> {
    let mut value: u64 = 0;
    let mut shift = 0;
    for _ in 0..5 {
        require(offset < payload.len(), "truncated WebAssembly ULEB128")?;
        let byte = payload[offset];
        offset += 1;
        value |= u64::from(byte & 0x7f) << shift;
        if byte < 0x80 {
            return Ok((value, offset));
        }
        shift += 7;
    }
    fail("oversized WebAssembly ULEB128")
}

/// Python `wasm_export_table`.
fn wasm_export_table(payload: &[u8]) -> R<Vec<Value>> {
    require(
        payload.len() >= 8 && &payload[..8] == b"\0asm\x01\0\0\0",
        "mapping is not WebAssembly v1",
    )?;
    let mut offset = 8;
    let mut export_table: Option<Vec<Value>> = None;
    while offset < payload.len() {
        let section_id = payload[offset];
        offset += 1;
        let (section_size, next) = read_uleb(payload, offset)?;
        offset = next;
        let section_end = offset.saturating_add(section_size as usize);
        require(
            section_end <= payload.len(),
            "WebAssembly section exceeds payload",
        )?;
        if section_id == 7 {
            require(
                export_table.is_none(),
                "duplicate WebAssembly export section",
            )?;
            let (count, mut cursor) = read_uleb(payload, offset)?;
            let mut table = Vec::new();
            let mut seen: BTreeSet<String> = BTreeSet::new();
            for _ in 0..count {
                let (length, next) = read_uleb(payload, cursor)?;
                cursor = next;
                let end = cursor.saturating_add(length as usize);
                require(end <= section_end, "truncated WebAssembly export name")?;
                let name = std::str::from_utf8(&payload[cursor..end])
                    .map_err(|_| "non-UTF8 WebAssembly export".to_string())?
                    .to_string();
                cursor = end;
                require(cursor < section_end, "truncated WebAssembly export kind")?;
                let kind = payload[cursor];
                cursor += 1;
                let (index, next) = read_uleb(payload, cursor)?;
                cursor = next;
                let label = match kind {
                    0 => "function",
                    1 => "table",
                    2 => "memory",
                    3 => "global",
                    other => return fail(format!("unknown WebAssembly export kind: {other}")),
                };
                require(
                    !seen.contains(&name),
                    format!("duplicate WebAssembly export: {name}"),
                )?;
                seen.insert(name.clone());
                table.push(json!({"name": name, "kind": label, "index": index}));
            }
            require(
                cursor == section_end,
                "WebAssembly export section trailing bytes",
            )?;
            export_table = Some(table);
        }
        offset = section_end;
    }
    require(offset == payload.len(), "WebAssembly trailing bytes")?;
    export_table.ok_or_else(|| "WebAssembly export section missing".to_string())
}

/// Python `_canonical_abi_type`.
fn canonical_abi_type(item: &Value) -> R<String> {
    let kind = py_str(get(item, "type"));
    let Some(suffix) = kind.strip_prefix("tuple") else {
        return Ok(kind);
    };
    let components = get(item, "components")
        .as_array()
        .ok_or("tuple ABI input is missing components")?
        .clone();
    let mut parts = Vec::new();
    for component in &components {
        parts.push(canonical_abi_type(component)?);
    }
    Ok(format!("({}){suffix}", parts.join(",")))
}

/// Python `_abi_signature`.
fn abi_signature(entry: &Value) -> R<String> {
    let name = match entry.get("name") {
        Some(value) => value.clone(),
        None => get(entry, "type").clone(),
    };
    let inputs = match entry.get("inputs") {
        Some(value) => value.clone(),
        None => Value::Array(Vec::new()),
    };
    require(name.is_string() && inputs.is_array(), "invalid ABI entry")?;
    let mut parts = Vec::new();
    for item in inputs.as_array().unwrap_or(&Vec::new()) {
        parts.push(canonical_abi_type(item)?);
    }
    Ok(format!(
        "{}({})",
        name.as_str().unwrap_or_default(),
        parts.join(",")
    ))
}

/// Python `_abi_entry_identity`.
fn abi_entry_identity(entry: &Value) -> R<String> {
    let kind = get(entry, "type");
    require(kind.is_string(), "ABI entry type is missing")?;
    Ok(format!(
        "{}:{}",
        kind.as_str().unwrap_or_default(),
        abi_signature(entry)?
    ))
}

/// Python `_abi_component_semantics`.
fn abi_component_semantics(component: &Value) -> R<Value> {
    require(component.is_object(), "ABI component must be an object")?;
    let mut result = Map::new();
    result.insert("type".into(), Value::String(canonical_abi_type(component)?));
    if let Some(indexed) = component.get("indexed") {
        result.insert("indexed".into(), Value::Bool(py_truthy(indexed)));
    }
    Ok(Value::Object(result))
}

/// Python `_abi_entry_semantics`.
fn abi_entry_semantics(entry: &Value) -> R<Value> {
    let mut result = Map::new();
    result.insert("type".into(), get(entry, "type").clone());
    if let Some(name) = entry.get("name") {
        require(name.is_string(), "ABI entry name must be a string")?;
        result.insert("name".into(), name.clone());
    }
    for field in ["inputs", "outputs"] {
        if let Some(items) = entry.get(field) {
            let items = items
                .as_array()
                .ok_or_else(|| format!("ABI entry {field} must be a list"))?;
            let mut projected = Vec::new();
            for component in items {
                projected.push(abi_component_semantics(component)?);
            }
            result.insert(field.into(), Value::Array(projected));
        }
    }
    for field in ["stateMutability", "anonymous", "payable", "constant"] {
        if let Some(value) = entry.get(field) {
            result.insert(field.into(), value.clone());
        }
    }
    Ok(Value::Object(result))
}

/// Python `_abi_entry_catalog`.
fn abi_entry_catalog(value: &Value) -> R<(Vec<String>, BTreeMap<String, Value>)> {
    let entries = value.as_array().ok_or("ABI must be a JSON array")?;
    let mut order = Vec::new();
    let mut catalog: BTreeMap<String, Value> = BTreeMap::new();
    for entry in entries {
        require(entry.is_object(), "ABI entry must be an object")?;
        let identity = abi_entry_identity(entry)?;
        require(
            !catalog.contains_key(&identity),
            format!("duplicate ABI entry identity: {identity}"),
        )?;
        order.push(identity.clone());
        catalog.insert(identity, entry.clone());
    }
    Ok((order, catalog))
}

fn json_pointer_token(value: &str) -> String {
    value.replace('~', "~0").replace('/', "~1")
}

/// Python `_json_field_differences`.
fn json_field_differences(left: &Value, right: &Value, path: &str) -> Vec<Value> {
    if canonical_bytes(left) == canonical_bytes(right) {
        return Vec::new();
    }
    if let (Value::Object(left_map), Value::Object(right_map)) = (left, right) {
        let mut result = Vec::new();
        let mut keys: BTreeSet<&String> = left_map.keys().collect();
        keys.extend(right_map.keys());
        for key in keys {
            let child = format!("{path}/{}", json_pointer_token(key));
            match (left_map.get(key), right_map.get(key)) {
                (Some(left_value), Some(right_value)) => {
                    result.extend(json_field_differences(left_value, right_value, &child));
                }
                (left_value, right_value) => {
                    let mut record = Map::new();
                    record.insert("path".into(), Value::String(child));
                    record.insert(
                        "pancakeswap_present".into(),
                        Value::Bool(left_value.is_some()),
                    );
                    record.insert("base_present".into(), Value::Bool(right_value.is_some()));
                    if let Some(value) = left_value {
                        record.insert("pancakeswap".into(), value.clone());
                    }
                    if let Some(value) = right_value {
                        record.insert("base".into(), value.clone());
                    }
                    result.push(Value::Object(record));
                }
            }
        }
        return result;
    }
    if let (Value::Array(left_items), Value::Array(right_items)) = (left, right) {
        let mut result = Vec::new();
        for index in 0..left_items.len().max(right_items.len()) {
            let child = format!("{path}/{index}");
            match (left_items.get(index), right_items.get(index)) {
                (Some(left_value), Some(right_value)) => {
                    result.extend(json_field_differences(left_value, right_value, &child));
                }
                (left_value, right_value) => {
                    let mut record = Map::new();
                    record.insert("path".into(), Value::String(child));
                    record.insert(
                        "pancakeswap_present".into(),
                        Value::Bool(left_value.is_some()),
                    );
                    record.insert("base_present".into(), Value::Bool(right_value.is_some()));
                    if let Some(value) = left_value {
                        record.insert("pancakeswap".into(), value.clone());
                    }
                    if let Some(value) = right_value {
                        record.insert("base".into(), value.clone());
                    }
                    result.push(Value::Object(record));
                }
            }
        }
        return result;
    }
    vec![json!({
        "path": if path.is_empty() { "/" } else { path },
        "pancakeswap_present": true,
        "base_present": true,
        "pancakeswap": left.clone(),
        "base": right.clone(),
    })]
}

/// Python `_exclusive_abi_entries`.
fn exclusive_abi_entries(
    identities: &BTreeSet<String>,
    catalog: &BTreeMap<String, Value>,
) -> Vec<Value> {
    identities
        .iter()
        .map(|identity| {
            let entry = &catalog[identity];
            json!({
                "identity": identity,
                "canonical_sha256": canonical_sha256(entry),
                "entry": entry.clone(),
            })
        })
        .collect()
}

/// Python `abi_summary`.
fn abi_summary(value: &Value) -> R<Value> {
    let entries = value.as_array().ok_or("ABI must be a JSON array")?;
    require(
        entries
            .iter()
            .all(|item| item.is_object() && get(item, "type").is_string()),
        "ABI entries must be objects with a type",
    )?;
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut events = Vec::new();
    let mut functions = Vec::new();
    for item in entries {
        let kind = py_str(get(item, "type"));
        *counts.entry(kind.clone()).or_default() += 1;
        if kind == "event" {
            let inputs = match item.get("inputs") {
                Some(value) => value.clone(),
                None => Value::Array(Vec::new()),
            };
            let inputs = inputs
                .as_array()
                .ok_or("event ABI inputs must be a list")?
                .clone();
            events.push(json!({
                "signature": abi_signature(item)?,
                "indexed": inputs
                    .iter()
                    .map(|component| Value::Bool(py_truthy(get(component, "indexed"))))
                    .collect::<Vec<_>>(),
                "anonymous": py_truthy(get(item, "anonymous")),
            }));
        } else if kind == "function" {
            functions.push(Value::String(abi_signature(item)?));
        }
    }
    let counts: Map<String, Value> = counts
        .into_iter()
        .map(|(key, value)| (key, Value::from(value)))
        .collect();
    Ok(json!({
        "entry_count": entries.len(),
        "entry_type_counts": Value::Object(counts),
        "canonical_sha256": canonical_sha256(value),
        "events": events,
        "function_signatures": functions,
    }))
}

// ---------------------------------------------------------------------------
// Retained artifact lock
// ---------------------------------------------------------------------------

fn expected_wasm_export(
    target: &str,
    role: &str,
) -> Option<(usize, &'static str, &'static [&'static str])> {
    EXPECTED_WASM_EXPORTS
        .iter()
        .find(|(candidate_target, candidate_role, _, _, _)| {
            *candidate_target == target && *candidate_role == role
        })
        .map(|(_, _, count, sha, handlers)| (*count, *sha, *handlers))
}

/// `rglob("*")` over a directory, as root-relative POSIX paths; a missing
/// directory yields an empty set, exactly as `Path.rglob` does.
fn walk_relative_files(root: &Path, directory: &Path) -> R<BTreeSet<String>> {
    fn walk(root: &Path, directory: &Path, out: &mut BTreeSet<String>) -> R<()> {
        let entries = match std::fs::read_dir(directory) {
            Ok(entries) => entries,
            Err(_) => return Ok(()),
        };
        for entry in entries {
            let entry =
                entry.map_err(|error| format!("cannot list {}: {error}", directory.display()))?;
            let path = entry.path();
            let metadata = std::fs::metadata(&path)
                .map_err(|error| format!("cannot stat {}: {error}", path.display()))?;
            if metadata.is_dir() {
                walk(root, &path, out)?;
            } else {
                let relative = path
                    .strip_prefix(root)
                    .map_err(|_| format!("path escapes root: {}", path.display()))?;
                out.insert(
                    relative
                        .components()
                        .map(|component| component.as_os_str().to_string_lossy().to_string())
                        .collect::<Vec<_>>()
                        .join("/"),
                );
            }
        }
        Ok(())
    }
    let mut out = BTreeSet::new();
    walk(root, directory, &mut out)?;
    Ok(out)
}

struct Artifacts {
    records: Vec<Value>,
    by_target: BTreeMap<String, BTreeMap<String, Value>>,
}

/// Python `verify_artifacts`.
fn verify_artifacts(root: &Path) -> R<Artifacts> {
    require(
        ARTIFACT_ROWS.len() == 26,
        "artifact lock must contain exactly 26 records",
    )?;
    let expected_paths: BTreeSet<String> = ARTIFACT_ROWS
        .iter()
        .map(|(target, _, relative, _, _, _)| format!("{REFERENCE_ROOT}/{target}/{relative}"))
        .collect();
    let actual_paths = walk_relative_files(root, &root.join(REFERENCE_ROOT))?;
    require(
        actual_paths == expected_paths,
        "Messari V3 retained artifact path closure drift",
    )?;
    let mut records: Vec<Value> = Vec::new();
    let mut by_target: BTreeMap<String, BTreeMap<String, Value>> = TARGET_ORDER
        .iter()
        .map(|target| ((*target).to_string(), BTreeMap::new()))
        .collect();
    for (target, role, relative, cid, expected_bytes, expected_sha) in ARTIFACT_ROWS {
        require(
            by_target
                .get(target)
                .is_some_and(|roles| !roles.contains_key(role)),
            format!("duplicate artifact role: {target}/{role}"),
        )?;
        let vendored = format!("{REFERENCE_ROOT}/{target}/{relative}");
        let resolved = root
            .join(&vendored)
            .canonicalize()
            .map_err(|error| format!("cannot resolve {vendored}: {error}"))?;
        require(
            resolved.starts_with(root) && resolved != root,
            format!("artifact escapes root: {vendored}"),
        )?;
        let payload = read_bytes(&resolved)?;
        require(
            payload.len() == expected_bytes,
            format!("artifact byte count drift: {target}/{role}"),
        )?;
        require(
            sha256_hex(&payload) == expected_sha,
            format!("artifact SHA-256 drift: {target}/{role}"),
        )?;
        require(
            unixfs_file_cidv0(&payload)? == cid,
            format!("artifact CIDv0 drift: {target}/{role}"),
        )?;
        let mut record = json!({
            "target": target,
            "role": role,
            "cid": cid,
            "bytes": expected_bytes,
            "sha256": expected_sha,
            "vendored_path": vendored,
        });
        if role.starts_with("abi/") {
            record["abi"] = abi_summary(&load_json(&resolved)?)?;
        } else if role.starts_with("mapping/") {
            let exports = wasm_export_table(&payload)?;
            let function_exports: Vec<Value> = exports
                .iter()
                .filter(|item| get(item, "kind") == "function")
                .map(|item| get(item, "name").clone())
                .collect();
            let handler_exports: Vec<Value> = function_exports
                .iter()
                .filter(|name| name.as_str().is_some_and(|text| text.starts_with("handle")))
                .cloned()
                .collect();
            let export_table = Value::Array(exports.clone());
            let export_table_sha256 = canonical_sha256(&export_table);
            let (expected_count, expected_table_sha256, expected_handlers) =
                expected_wasm_export(target, role).ok_or_else(|| {
                    format!("WebAssembly export expectation closure drift: {target}/{role}")
                })?;
            require(
                exports.len() == expected_count,
                format!("WebAssembly export count drift: {target}/{role}"),
            )?;
            require(
                export_table_sha256 == expected_table_sha256,
                format!("WebAssembly export table drift: {target}/{role}"),
            )?;
            require(
                handler_exports
                    == expected_handlers
                        .iter()
                        .map(|name| Value::String((*name).to_string()))
                        .collect::<Vec<_>>(),
                format!("WebAssembly handler export order drift: {target}/{role}"),
            )?;
            record["export_count"] = Value::from(exports.len());
            record["export_table_sha256"] = Value::String(export_table_sha256);
            record["function_exports"] = Value::Array(function_exports);
            record["handler_exports"] = Value::Array(handler_exports);
            record["export_table"] = export_table;
        }
        by_target
            .get_mut(target)
            .ok_or_else(|| format!("duplicate artifact role: {target}/{role}"))?
            .insert(role.to_string(), record.clone());
        records.push(record);
    }
    require(
        TARGET_ORDER
            .iter()
            .all(|target| by_target[*target].len() == 13),
        "each target must retain 13 artifacts",
    )?;
    let expected_pairs: BTreeSet<(String, String)> = EXPECTED_WASM_EXPORTS
        .iter()
        .map(|(target, role, _, _, _)| ((*target).to_string(), (*role).to_string()))
        .collect();
    let observed_pairs: BTreeSet<(String, String)> = TARGET_ORDER
        .iter()
        .flat_map(|target| {
            by_target[*target]
                .keys()
                .filter(|role| role.starts_with("mapping/"))
                .map(move |role| ((*target).to_string(), role.clone()))
        })
        .collect();
    require(
        expected_pairs == observed_pairs,
        "WebAssembly export expectation closure drift",
    )?;
    Ok(Artifacts { records, by_target })
}

// ---------------------------------------------------------------------------
// Deployment manifest projection
// ---------------------------------------------------------------------------

/// Python `manifest_profile`.
fn manifest_profile(
    target: &str,
    manifest: &Value,
    artifacts: &BTreeMap<String, Value>,
) -> R<Value> {
    let expectations = static_json(TARGET_EXPECTATIONS_JSON);
    let expectation = get(&expectations, target).clone();
    require(
        manifest.is_object(),
        format!("{target} manifest must be a mapping"),
    )?;
    require(
        canonical_sha256(manifest) == *get(&expectation, "manifest_semantic_sha256"),
        format!("{target} manifest semantic projection drift"),
    )?;
    require(
        object_keys(manifest)
            == key_set(&[
                "dataSources",
                "repository",
                "schema",
                "specVersion",
                "templates",
            ]),
        format!("{target} manifest root keys drift"),
    )?;
    require(
        get(manifest, "repository") == "https://github.com/messari/subgraphs",
        format!("{target} repository drift"),
    )?;
    require(
        get(manifest, "specVersion") == "0.0.4",
        format!("{target} deployed specVersion drift"),
    )?;
    require(
        cid_from_file(get(get(manifest, "schema"), "file"))?
            == *as_str(get(&expectation, "schema"))?,
        format!("{target} schema CID drift"),
    )?;
    let empty = Vec::new();
    let data_sources = get(manifest, "dataSources").as_array().cloned();
    let templates = get(manifest, "templates").as_array().cloned();
    require(
        data_sources.as_ref().is_some_and(|items| items.len() == 2),
        format!("{target} data-source count drift"),
    )?;
    require(
        templates.as_ref().is_some_and(|items| items.len() == 2),
        format!("{target} template count drift"),
    )?;
    let data_sources = data_sources.unwrap_or(empty.clone());
    let templates = templates.unwrap_or(empty);
    let mut components: Vec<Value> = Vec::new();
    let mut referenced_cids: BTreeSet<String> = BTreeSet::new();
    referenced_cids.insert(as_str(get(&expectation, "schema"))?.to_string());
    let expected_components = get(&expectation, "components")
        .as_array()
        .cloned()
        .unwrap_or_default();
    for (index, expected) in expected_components.iter().enumerate() {
        let kind = as_str(&expected[0])?.to_string();
        let name = as_str(&expected[1])?.to_string();
        let source = expected[2].clone();
        let mapping_role = as_str(&expected[3])?.to_string();
        let component = if kind == "data_source" {
            data_sources.get(index).cloned().unwrap_or(Value::Null)
        } else {
            templates
                .get(index - data_sources.len())
                .cloned()
                .unwrap_or(Value::Null)
        };
        require(
            object_keys(&component) == key_set(&["kind", "mapping", "name", "network", "source"]),
            format!("{target}/{name} component keys drift"),
        )?;
        require(
            get(&component, "kind") == "ethereum/contract" && get(&component, "name") == &name[..],
            format!("{target}/{name} identity drift"),
        )?;
        require(
            get(&component, "network") == get(&expectation, "chain")
                && *get(&component, "source") == source,
            format!("{target}/{name} source drift"),
        )?;
        let mapping = get(&component, "mapping").clone();
        require(
            mapping.is_object()
                && object_keys(&mapping)
                    == key_set(&[
                        "abis",
                        "apiVersion",
                        "entities",
                        "eventHandlers",
                        "file",
                        "kind",
                        "language",
                    ]),
            format!("{target}/{name} mapping keys drift"),
        )?;
        require(
            get(&mapping, "apiVersion") == "0.0.6",
            format!("{target}/{name} apiVersion drift"),
        )?;
        require(
            get(&mapping, "kind") == "ethereum/events"
                && get(&mapping, "language") == "wasm/assemblyscript",
            format!("{target}/{name} runtime drift"),
        )?;
        let mapping_cid = cid_from_file(get(&mapping, "file"))?;
        let mapping_record = artifacts
            .get(&mapping_role)
            .ok_or_else(|| format!("{target}/{name} mapping CID drift"))?;
        require(
            get(mapping_record, "cid") == &mapping_cid[..],
            format!("{target}/{name} mapping CID drift"),
        )?;
        let mut abi_bindings: Vec<Value> = Vec::new();
        let abis = get(&mapping, "abis")
            .as_array()
            .cloned()
            .ok_or_else(|| format!("{target}/{name} ABI binding shape drift"))?;
        for entry in &abis {
            require(
                entry.is_object() && object_keys(entry) == key_set(&["file", "name"]),
                format!("{target}/{name} ABI binding shape drift"),
            )?;
            let abi_cid = cid_from_file(get(entry, "file"))?;
            require(
                artifacts.iter().any(|(role, record)| {
                    get(record, "cid") == &abi_cid[..] && role.starts_with("abi/")
                }),
                format!("{target}/{name} references an unretained ABI"),
            )?;
            referenced_cids.insert(abi_cid.clone());
            abi_bindings.push(json!({"name": get(entry, "name").clone(), "cid": abi_cid}));
        }
        let source_abi = get(get(&component, "source"), "abi").clone();
        let source_bindings: Vec<&Value> = abi_bindings
            .iter()
            .filter(|entry| *get(entry, "name") == source_abi)
            .collect();
        require(
            source_bindings.len() == 1,
            format!("{target}/{name} source ABI alias does not resolve exact-case"),
        )?;
        let source_abi_cid = get(source_bindings[0], "cid").clone();
        let source_abi_records: Vec<&Value> = artifacts
            .iter()
            .filter(|(role, record)| {
                role.starts_with("abi/") && *get(record, "cid") == source_abi_cid
            })
            .map(|(_, record)| record)
            .collect();
        require(
            source_abi_records.len() == 1,
            format!("{target}/{name} source ABI artifact resolution drift"),
        )?;
        let event_handlers = get(&mapping, "eventHandlers")
            .as_array()
            .cloned()
            .ok_or_else(|| format!("{target}/{name} handler order or signature drift"))?;
        let mut handlers: Vec<Value> = Vec::new();
        for item in &event_handlers {
            handlers.push(json!({
                "handler": get(item, "handler").clone(),
                "event": normalize_event(get(item, "event"))?,
            }));
        }
        let expected_handlers: Vec<Value> = get(get(&expectation, "handlers"), &name)
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .map(|pair| json!({"handler": pair[0].clone(), "event": pair[1].clone()}))
            .collect();
        require(
            handlers == expected_handlers,
            format!("{target}/{name} handler order or signature drift"),
        )?;
        let source_events: BTreeSet<String> = get(get(source_abi_records[0], "abi"), "events")
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .filter_map(|event| get(event, "signature").as_str().map(str::to_string))
            .collect();
        require(
            handlers.iter().all(|item| {
                get(item, "event")
                    .as_str()
                    .is_some_and(|event| source_events.contains(&event.replace("indexed ", "")))
            }),
            format!("{target}/{name} declares an event absent from its exact source ABI"),
        )?;
        referenced_cids.insert(mapping_cid.clone());
        let exports = get(mapping_record, "handler_exports").clone();
        let exports_list = exports.as_array().cloned().unwrap_or_default();
        let declared: Vec<Value> = handlers
            .iter()
            .map(|item| get(item, "handler").clone())
            .collect();
        components.push(json!({
            "kind": kind,
            "name": name,
            "network": get(&component, "network").clone(),
            "source": get(&component, "source").clone(),
            "mapping_role": mapping_role,
            "mapping_cid": mapping_cid,
            "mapping_api_version": get(&mapping, "apiVersion").clone(),
            "mapping_kind": get(&mapping, "kind").clone(),
            "mapping_language": get(&mapping, "language").clone(),
            "abi_bindings": abi_bindings,
            "source_abi_binding": {
                "alias": source_abi,
                "cid": source_abi_cid,
                "exact_case_resolved": true,
                "all_declared_events_present": true,
            },
            "entities": get(&mapping, "entities").clone(),
            "event_handlers": handlers,
            "handler_exports": exports,
            "missing_declared_handler_exports": declared
                .iter()
                .filter(|handler| !exports_list.contains(handler))
                .cloned()
                .collect::<Vec<_>>(),
            "undeclared_handler_exports": exports_list
                .iter()
                .filter(|handler| !declared.contains(handler))
                .cloned()
                .collect::<Vec<_>>(),
        }));
    }
    let retained_non_deployment_cids: BTreeSet<String> = artifacts
        .iter()
        .filter(|(role, _)| *role != "deployment")
        .filter_map(|(_, record)| get(record, "cid").as_str().map(str::to_string))
        .collect();
    require(
        referenced_cids == retained_non_deployment_cids,
        format!("{target} retained/referenced artifact closure drift"),
    )?;
    let primary = components[2].clone();
    let expected_primary_entities = static_json(EXPECTED_PRIMARY_ENTITIES_JSON);
    require(
        *get(&primary, "entities") == expected_primary_entities,
        format!("{target} primary Pool entity metadata drift"),
    )?;
    let primary_entities = get(&primary, "entities")
        .as_array()
        .cloned()
        .unwrap_or_default();
    require(
        primary_entities
            .iter()
            .filter(|entity| *entity == "Token")
            .count()
            == 2
            && primary_entities
                .iter()
                .any(|entity| entity == "LiqudityPool"),
        format!("{target} template quirks normalized"),
    )?;
    require(
        *get(&components[3], "entities") == json!(["LiqudityPool"]),
        format!("{target} fee-template entity metadata drift"),
    )?;
    if target == "pancakeswap-v3-bsc" {
        require(
            *get(&primary, "missing_declared_handler_exports") == json!(["handleSetFeeProtocol"]),
            "BSC primary Pool missing-export boundary drift",
        )?;
        require(
            *get(&primary, "handler_exports")
                == json!([
                    "handleInitialize",
                    "handleMint",
                    "handleBurn",
                    "handleSwap",
                    "handleCollectPool"
                ]),
            "BSC primary Pool export order drift",
        )?;
        require(
            get(&components[3], "mapping_cid") == "QmZh9pwyqnVEknPgTWraJweuyy1qbwzhA2rrSq43xmdgHL"
                && *get(&components[3], "handler_exports") == json!(["handleSetFeeProtocol"]),
            "BSC fee mapping export drift",
        )?;
    } else {
        require(
            *get(&primary, "missing_declared_handler_exports") == json!([]),
            "Base primary Pool invented missing export",
        )?;
        require(
            *get(&components[3], "handler_exports") == json!(["handleSetFeeProtocol"]),
            "Base fee mapping export drift",
        )?;
    }
    Ok(json!({
        "deployment_cid": get(&expectation, "deployment").clone(),
        "schema_cid": get(&expectation, "schema").clone(),
        "chain": get(&expectation, "chain").clone(),
        "repository": get(manifest, "repository").clone(),
        "spec_version": get(manifest, "specVersion").clone(),
        "manifest_semantic_sha256": canonical_sha256(manifest),
        "components": components,
    }))
}

// ---------------------------------------------------------------------------
// GraphQL schema projection
// ---------------------------------------------------------------------------

/// Python `schema_profile`.
fn schema_profile(path: &Path) -> R<Value> {
    let text = read_text(path)?;
    let version = schema_version_marker(&text).ok_or("schema version marker missing")?;
    let mut entities: Map<String, Value> = Map::new();
    let mut current: Option<String> = None;
    for raw_line in text.split('\n') {
        let line = raw_line.split('#').next().unwrap_or_default().trim();
        let declaration = type_declaration(line);
        if let Some((name, directives)) = &declaration {
            if directives.contains("@entity") {
                require(
                    !entities.contains_key(name),
                    format!("duplicate schema entity: {name}"),
                )?;
                entities.insert(
                    name.clone(),
                    json!({
                        "directives": normalized_directives(directives),
                        "fields": Vec::<Value>::new(),
                    }),
                );
                current = Some(name.clone());
                continue;
            }
        }
        let Some(name) = current.clone() else {
            continue;
        };
        if line == "}" {
            current = None;
            continue;
        }
        if let Some((field, field_type)) = field_declaration(line) {
            let entity = entities
                .get_mut(&name)
                .ok_or_else(|| format!("duplicate schema entity: {name}"))?;
            let fields = entity["fields"].as_array().cloned().unwrap_or_default();
            require(
                !fields
                    .iter()
                    .any(|item| get(item, "name").as_str() == Some(field.as_str())),
                format!("duplicate schema field: {name}.{field}"),
            )?;
            let mut fields = fields;
            fields.push(json!({"name": field, "type": field_type}));
            entity["fields"] = Value::Array(fields);
        }
    }
    let enum_body = network_enum_body(&text).ok_or("Network enum missing")?;
    let mut network_values: Vec<Value> = Vec::new();
    for raw_line in enum_body.split('\n') {
        let value = raw_line.split('#').next().unwrap_or_default().trim();
        if value.is_empty() {
            continue;
        }
        require(
            is_network_enum_value(value),
            format!("invalid Network enum value: {value}"),
        )?;
        network_values.push(Value::String(value.to_string()));
    }
    let field_catalog: Map<String, Value> = entities
        .iter()
        .map(|(name, item)| (name.clone(), get(item, "fields").clone()))
        .collect();
    let directives: Map<String, Value> = entities
        .iter()
        .map(|(name, item)| (name.clone(), get(item, "directives").clone()))
        .collect();
    let field_count: usize = entities
        .values()
        .map(|item| get(item, "fields").as_array().map_or(0, Vec::len))
        .sum();
    Ok(json!({
        "schema_version": version,
        "entity_count": entities.len(),
        "field_count": field_count,
        "field_catalog_sha256": canonical_sha256(&Value::Object(field_catalog)),
        "entity_directives_sha256": canonical_sha256(&Value::Object(directives)),
        "network_values": network_values,
        "declared_type_names": declared_type_names(&text),
        "entities": Value::Object(entities),
    }))
}

/// Python `verify_schema_pair`.
fn verify_schema_pair(profiles: &BTreeMap<String, Value>) -> R<Value> {
    let bsc = profiles
        .get("pancakeswap-v3-bsc")
        .ok_or("pancakeswap-v3-bsc schema profile missing")?;
    let base = profiles
        .get("uniswap-v3-base")
        .ok_or("uniswap-v3-base schema profile missing")?;
    for (target, profile, version) in [
        ("pancakeswap-v3-bsc", bsc, "4.0.0"),
        ("uniswap-v3-base", base, "4.0.1"),
    ] {
        require(
            get(profile, "schema_version") == version,
            format!("{target} schema version drift"),
        )?;
        require(
            get(profile, "entity_count") == 24 && get(profile, "field_count") == 388,
            format!("{target} schema denominator drift"),
        )?;
    }
    require(
        get(bsc, "field_catalog_sha256") == get(base, "field_catalog_sha256")
            && get(bsc, "field_catalog_sha256")
                == "76ac4b0b03cb16e9cf6112335feff2a94d2a559132f8895842c9f5a5e5678840",
        "schema field catalog drift",
    )?;
    let bsc_entities = get(bsc, "entities").clone();
    let base_entities = get(base, "entities").clone();
    let mut names: BTreeSet<String> = object_keys(&bsc_entities);
    names.extend(object_keys(&base_entities));
    let mut directive_diff = Map::new();
    for entity in names {
        let left = bsc_entities
            .get(&entity)
            .map_or(Value::Null, |item| get(item, "directives").clone());
        let right = base_entities
            .get(&entity)
            .map_or(Value::Null, |item| get(item, "directives").clone());
        if left != right {
            directive_diff.insert(
                entity,
                json!({"pancakeswap-v3-bsc": left, "uniswap-v3-base": right}),
            );
        }
    }
    require(
        Value::Object(directive_diff.clone())
            == json!({
                "PositionSnapshot": {
                    "pancakeswap-v3-bsc": ["@entity(immutable:true)", "@regularPolling"],
                    "uniswap-v3-base": ["@entity(immutable:true)", "@hourlySnapshot"],
                }
            }),
        "schema directive diff drift",
    )?;
    let bsc_networks: BTreeSet<String> = get(bsc, "network_values")
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter_map(|value| value.as_str().map(str::to_string))
        .collect();
    let base_networks: BTreeSet<String> = get(base, "network_values")
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter_map(|value| value.as_str().map(str::to_string))
        .collect();
    require(
        base_networks
            .difference(&bsc_networks)
            .cloned()
            .collect::<Vec<_>>()
            == vec!["BASE".to_string()],
        "Network.BASE addition drift",
    )?;
    require(
        bsc_networks.difference(&base_networks).next().is_none(),
        "unexpected BSC-only Network values",
    )?;
    Ok(json!({
        "field_catalog_identical": true,
        "field_catalog_sha256": get(bsc, "field_catalog_sha256").clone(),
        "schema_versions": {"pancakeswap-v3-bsc": "4.0.0", "uniswap-v3-base": "4.0.1"},
        "base_only_network_values": ["BASE"],
        "entity_directive_differences": Value::Object(directive_diff),
    }))
}

// ---------------------------------------------------------------------------
// Cross-target ABI and WebAssembly ledgers
// ---------------------------------------------------------------------------

fn signature_set(summary: &Value, key: &str) -> BTreeSet<String> {
    let items = get(summary, key).as_array().cloned().unwrap_or_default();
    if key == "events" {
        items
            .iter()
            .filter_map(|item| get(item, "signature").as_str().map(str::to_string))
            .collect()
    } else {
        items
            .iter()
            .filter_map(|item| item.as_str().map(str::to_string))
            .collect()
    }
}

fn sorted_strings(values: &BTreeSet<String>) -> Vec<Value> {
    values
        .iter()
        .map(|item| Value::String(item.clone()))
        .collect()
}

/// Python `_full_abi_entry_diff`.
fn full_abi_entry_diff(left_value: &Value, right_value: &Value) -> R<Vec<(String, Value)>> {
    let (left_order, left) = abi_entry_catalog(left_value)?;
    let (right_order, right) = abi_entry_catalog(right_value)?;
    let left_keys: BTreeSet<String> = left.keys().cloned().collect();
    let right_keys: BTreeSet<String> = right.keys().cloned().collect();
    let mut shared_metadata_differences: Vec<Value> = Vec::new();
    let mut shared_semantic_differences: Vec<Value> = Vec::new();
    for identity in left_keys.intersection(&right_keys) {
        let left_entry = &left[identity];
        let right_entry = &right[identity];
        let left_sha = canonical_sha256(left_entry);
        let right_sha = canonical_sha256(right_entry);
        if left_sha == right_sha {
            continue;
        }
        let left_semantics = abi_entry_semantics(left_entry)?;
        let right_semantics = abi_entry_semantics(right_entry)?;
        let semantic_equal = canonical_bytes(&left_semantics) == canonical_bytes(&right_semantics);
        let field_differences = json_field_differences(left_entry, right_entry, "");
        shared_metadata_differences.push(json!({
            "identity": identity,
            "pancakeswap_canonical_sha256": left_sha,
            "base_canonical_sha256": right_sha,
            "semantic_equal": semantic_equal,
            "field_differences": field_differences.clone(),
        }));
        if !semantic_equal {
            shared_semantic_differences.push(json!({
                "identity": identity,
                "pancakeswap": left_semantics,
                "base": right_semantics,
                "field_differences": field_differences,
            }));
        }
    }
    let only_left: BTreeSet<String> = left_keys.difference(&right_keys).cloned().collect();
    let only_right: BTreeSet<String> = right_keys.difference(&left_keys).cloned().collect();
    Ok(vec![
        (
            "entry_order_sha256".to_string(),
            json!({
                "pancakeswap-v3-bsc": canonical_sha256(&json!(left_order)),
                "uniswap-v3-base": canonical_sha256(&json!(right_order)),
            }),
        ),
        (
            "entry_identities_only_pancakeswap".to_string(),
            Value::Array(sorted_strings(&only_left)),
        ),
        (
            "entry_identities_only_base".to_string(),
            Value::Array(sorted_strings(&only_right)),
        ),
        (
            "entries_only_pancakeswap".to_string(),
            Value::Array(exclusive_abi_entries(&only_left, &left)),
        ),
        (
            "entries_only_base".to_string(),
            Value::Array(exclusive_abi_entries(&only_right, &right)),
        ),
        (
            "shared_identity_metadata_differences".to_string(),
            Value::Array(shared_metadata_differences),
        ),
        (
            "shared_identity_semantic_differences".to_string(),
            Value::Array(shared_semantic_differences),
        ),
    ])
}

const ABI_NAMES: [&str; 7] = [
    "ERC20",
    "ERC20NameBytes",
    "ERC20SymbolBytes",
    "Factory",
    "NonFungiblePositionManager",
    "Pool",
    "TickLens",
];

/// Python `build_abi_diff`.
fn build_abi_diff(root: &Path, by_target: &BTreeMap<String, BTreeMap<String, Value>>) -> R<Value> {
    let bsc = &by_target["pancakeswap-v3-bsc"];
    let base = &by_target["uniswap-v3-base"];
    let mut shared: Vec<Value> = Vec::new();
    let mut differing_order: Vec<String> = Vec::new();
    let mut differing: Map<String, Value> = Map::new();
    for name in ABI_NAMES {
        let role = format!("abi/{name}");
        let left_record = bsc
            .get(&role)
            .ok_or_else(|| format!("retained ABI missing: pancakeswap-v3-bsc/{role}"))?;
        let right_record = base
            .get(&role)
            .ok_or_else(|| format!("retained ABI missing: uniswap-v3-base/{role}"))?;
        let left = get(left_record, "abi").clone();
        let right = get(right_record, "abi").clone();
        if get(&left, "canonical_sha256") == get(&right, "canonical_sha256") {
            shared.push(Value::String(name.to_string()));
            continue;
        }
        let left_value = load_json(&root.join(as_str(get(left_record, "vendored_path"))?))?;
        let right_value = load_json(&root.join(as_str(get(right_record, "vendored_path"))?))?;
        let mut entry = Map::new();
        entry.insert(
            "pancakeswap_entry_count".into(),
            get(&left, "entry_count").clone(),
        );
        entry.insert(
            "base_entry_count".into(),
            get(&right, "entry_count").clone(),
        );
        entry.insert(
            "pancakeswap_canonical_sha256".into(),
            get(&left, "canonical_sha256").clone(),
        );
        entry.insert(
            "base_canonical_sha256".into(),
            get(&right, "canonical_sha256").clone(),
        );
        let left_events = signature_set(&left, "events");
        let right_events = signature_set(&right, "events");
        let left_functions = signature_set(&left, "function_signatures");
        let right_functions = signature_set(&right, "function_signatures");
        entry.insert(
            "events_only_pancakeswap".into(),
            Value::Array(sorted_strings(
                &left_events.difference(&right_events).cloned().collect(),
            )),
        );
        entry.insert(
            "events_only_base".into(),
            Value::Array(sorted_strings(
                &right_events.difference(&left_events).cloned().collect(),
            )),
        );
        entry.insert(
            "functions_only_pancakeswap".into(),
            Value::Array(sorted_strings(
                &left_functions
                    .difference(&right_functions)
                    .cloned()
                    .collect(),
            )),
        );
        entry.insert(
            "functions_only_base".into(),
            Value::Array(sorted_strings(
                &right_functions
                    .difference(&left_functions)
                    .cloned()
                    .collect(),
            )),
        );
        for (key, value) in full_abi_entry_diff(&left_value, &right_value)? {
            entry.insert(key, value);
        }
        differing_order.push(name.to_string());
        differing.insert(name.to_string(), Value::Object(entry));
    }
    require(
        shared
            == vec![
                Value::String("ERC20".into()),
                Value::String("ERC20NameBytes".into()),
                Value::String("ERC20SymbolBytes".into()),
                Value::String("TickLens".into()),
            ],
        "shared ABI set drift",
    )?;
    require(
        differing_order == vec!["Factory", "NonFungiblePositionManager", "Pool"],
        "differing ABI set drift",
    )?;
    require(
        *get(&differing["Factory"], "events_only_pancakeswap")
            == json!([
                "FeeAmountExtraInfoUpdated(uint24,bool,bool)",
                "SetLmPoolDeployer(address)",
                "WhiteListAdded(address,bool)"
            ]),
        "Factory event diff drift",
    )?;
    require(
        *get(&differing["Pool"], "events_only_pancakeswap")
            == json!([
                "SetFeeProtocol(uint32,uint32,uint32,uint32)",
                "SetLmPoolEvent(address)",
                "Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)"
            ]),
        "Pool BSC event diff drift",
    )?;
    require(
        *get(&differing["Pool"], "events_only_base")
            == json!([
                "SetFeeProtocol(uint8,uint8,uint8,uint8)",
                "Swap(address,address,int256,int256,uint160,uint128,int24)"
            ]),
        "Pool Base event diff drift",
    )?;
    let expected_entry_ledgers = static_json(EXPECTED_ENTRY_LEDGERS_JSON);
    for name in ["Factory", "NonFungiblePositionManager", "Pool"] {
        let expected = get(&expected_entry_ledgers, name);
        let observed = &differing[name];
        require(
            get(observed, "entry_identities_only_pancakeswap")
                == get(expected, "entry_identities_only_pancakeswap"),
            format!("{name} full-entry BSC-only ABI diff drift"),
        )?;
        require(
            get(observed, "entry_identities_only_base")
                == get(expected, "entry_identities_only_base"),
            format!("{name} full-entry Base-only ABI diff drift"),
        )?;
        let identities = |key: &str| -> Value {
            Value::Array(
                get(observed, key)
                    .as_array()
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .map(|item| get(item, "identity").clone())
                    .collect(),
            )
        };
        require(
            identities("entries_only_pancakeswap")
                == *get(expected, "entry_identities_only_pancakeswap"),
            format!("{name} full BSC-only ABI entry projection drift"),
        )?;
        require(
            identities("entries_only_base") == *get(expected, "entry_identities_only_base"),
            format!("{name} full Base-only ABI entry projection drift"),
        )?;
        require(
            identities("shared_identity_metadata_differences")
                == *get(expected, "metadata_difference_identities"),
            format!("{name} same-identity ABI metadata diff drift"),
        )?;
        require(
            identities("shared_identity_semantic_differences")
                == *get(expected, "semantic_difference_identities"),
            format!("{name} same-identity ABI semantic diff drift"),
        )?;
        let observed_paths: Map<String, Value> =
            get(observed, "shared_identity_metadata_differences")
                .as_array()
                .cloned()
                .unwrap_or_default()
                .iter()
                .map(|item| {
                    (
                        py_str(get(item, "identity")),
                        Value::Array(
                            get(item, "field_differences")
                                .as_array()
                                .cloned()
                                .unwrap_or_default()
                                .iter()
                                .map(|field| get(field, "path").clone())
                                .collect(),
                        ),
                    )
                })
                .collect();
        require(
            Value::Object(observed_paths) == *get(expected, "field_difference_paths"),
            format!("{name} exact ABI field-difference path drift"),
        )?;
    }
    Ok(json!({
        "byte_and_semantic_identical_abis": shared,
        "differing_abis": Value::Object(differing),
    }))
}

/// Python `build_wasm_diff`.
fn build_wasm_diff(by_target: &BTreeMap<String, BTreeMap<String, Value>>) -> R<Value> {
    let bsc = &by_target["pancakeswap-v3-bsc"];
    let base = &by_target["uniswap-v3-base"];
    let pairs = [
        ("Factory", "mapping/Factory", "mapping/Factory"),
        (
            "NonFungiblePositionManager",
            "mapping/NonFungiblePositionManager",
            "mapping/NonFungiblePositionManager",
        ),
        ("primary_pool", "mapping/Pool", "mapping/Pool"),
        (
            "fee_only_pool",
            "mapping/PancakeSwapPool",
            "mapping/UniswapPool",
        ),
    ];
    let expected_base_only = static_json(EXPECTED_BASE_ONLY_JSON);
    let expected_index_differences = static_json(EXPECTED_INDEX_DIFFERENCES_JSON);
    let mut result = Map::new();
    let mut observed_roles: BTreeSet<(String, String)> = BTreeSet::new();
    for (name, bsc_role, base_role) in pairs {
        let left = bsc
            .get(bsc_role)
            .ok_or_else(|| format!("{name} paired handler export drift"))?;
        let right = base
            .get(base_role)
            .ok_or_else(|| format!("{name} paired handler export drift"))?;
        let catalog = |record: &Value| -> BTreeMap<String, Value> {
            get(record, "export_table")
                .as_array()
                .cloned()
                .unwrap_or_default()
                .iter()
                .map(|item| (py_str(get(item, "name")), item.clone()))
                .collect()
        };
        let left_catalog = catalog(left);
        let right_catalog = catalog(right);
        let left_names: BTreeSet<String> = left_catalog.keys().cloned().collect();
        let right_names: BTreeSet<String> = right_catalog.keys().cloned().collect();
        let only_bsc: Vec<Value> = left_names
            .difference(&right_names)
            .map(|export| json!({"name": export, "kind": get(&left_catalog[export], "kind").clone()}))
            .collect();
        let only_base: Vec<Value> = right_names
            .difference(&left_names)
            .map(|export| json!({"name": export, "kind": get(&right_catalog[export], "kind").clone()}))
            .collect();
        let kind_differences: Vec<Value> = left_names
            .intersection(&right_names)
            .filter(|export| {
                get(&left_catalog[*export], "kind") != get(&right_catalog[*export], "kind")
            })
            .map(|export| {
                json!({
                    "name": export,
                    "pancakeswap_kind": get(&left_catalog[export], "kind").clone(),
                    "base_kind": get(&right_catalog[export], "kind").clone(),
                })
            })
            .collect();
        let index_differences: Vec<Value> = left_names
            .intersection(&right_names)
            .filter(|export| {
                get(&left_catalog[*export], "index") != get(&right_catalog[*export], "index")
            })
            .map(|export| {
                json!({
                    "name": export,
                    "kind": get(&left_catalog[export], "kind").clone(),
                    "pancakeswap_index": get(&left_catalog[export], "index").clone(),
                    "base_index": get(&right_catalog[export], "index").clone(),
                })
            })
            .collect();
        require(
            only_bsc.is_empty(),
            format!("{name} unexpected BSC-only WebAssembly export"),
        )?;
        require(
            Value::Array(only_base.clone()) == expected_base_only,
            format!("{name} Base-only Cosmos TypeId export drift"),
        )?;
        require(
            kind_differences.is_empty(),
            format!("{name} shared WebAssembly export kind drift"),
        )?;
        let observed_indexes: Vec<Value> = index_differences
            .iter()
            .map(|item| {
                json!([
                    get(item, "name").clone(),
                    get(item, "kind").clone(),
                    get(item, "pancakeswap_index").clone(),
                    get(item, "base_index").clone(),
                ])
            })
            .collect();
        require(
            Value::Array(observed_indexes) == *get(&expected_index_differences, name),
            format!("{name} shared WebAssembly export index diff drift"),
        )?;
        require(
            get(left, "handler_exports") == get(right, "handler_exports"),
            format!("{name} paired handler export drift"),
        )?;
        observed_roles.insert((bsc_role.to_string(), base_role.to_string()));
        result.insert(
            name.to_string(),
            json!({
                "pancakeswap_mapping_role": bsc_role,
                "base_mapping_role": base_role,
                "pancakeswap_cid": get(left, "cid").clone(),
                "base_cid": get(right, "cid").clone(),
                "pancakeswap_sha256": get(left, "sha256").clone(),
                "base_sha256": get(right, "sha256").clone(),
                "pancakeswap_export_count": get(left, "export_count").clone(),
                "base_export_count": get(right, "export_count").clone(),
                "pancakeswap_export_table_sha256": get(left, "export_table_sha256").clone(),
                "base_export_table_sha256": get(right, "export_table_sha256").clone(),
                "exports_only_pancakeswap": only_bsc,
                "exports_only_base": only_base,
                "shared_export_kind_differences": kind_differences,
                "shared_export_index_differences": index_differences,
                "handler_exports": get(left, "handler_exports").clone(),
                "handler_exports_identical": true,
            }),
        );
    }
    let expected_roles: BTreeSet<(String, String)> = [
        ("mapping/Factory", "mapping/Factory"),
        (
            "mapping/NonFungiblePositionManager",
            "mapping/NonFungiblePositionManager",
        ),
        ("mapping/Pool", "mapping/Pool"),
        ("mapping/PancakeSwapPool", "mapping/UniswapPool"),
    ]
    .iter()
    .map(|(left, right)| ((*left).to_string(), (*right).to_string()))
    .collect();
    require(
        observed_roles == expected_roles,
        "paired WebAssembly mapping-role closure drift",
    )?;
    Ok(json!({
        "pairing_complete": true,
        "base_only_cosmos_type_id_globals": expected_base_only,
        "runtime_equivalence_claimed": false,
        "pairs": Value::Object(result),
    }))
}

// ---------------------------------------------------------------------------
// Target bindings, source provenance, and mapping entity metadata
// ---------------------------------------------------------------------------

/// Python `verify_bindings`.
fn verify_bindings(root: &Path) -> R<Vec<Value>> {
    let expected_bindings = static_json(EXPECTED_BINDINGS_JSON);
    let expected_paths: BTreeSet<String> = TARGET_ORDER
        .iter()
        .map(|target| py_str(get(get(&expected_bindings, target), "path")))
        .collect();
    let mut actual_paths: BTreeSet<String> = BTreeSet::new();
    if let Ok(entries) = std::fs::read_dir(root.join("messari-v3")) {
        for entry in entries {
            let entry = entry.map_err(|error| format!("cannot list messari-v3: {error}"))?;
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with("Qm") && name.ends_with(".yaml") && path.is_file() {
                actual_paths.insert(format!("messari-v3/{name}"));
            }
        }
    }
    require(
        actual_paths == expected_paths,
        "Messari V3 target binding path closure drift",
    )?;
    let mut result = Vec::new();
    for target in TARGET_ORDER {
        let expected = get(&expected_bindings, target).clone();
        let path = root.join(as_str(get(&expected, "path"))?);
        let payload = read_bytes(&path)?;
        require(
            get(&expected, "bytes").as_u64() == Some(payload.len() as u64),
            format!("{target} binding byte count drift"),
        )?;
        require(
            sha256_hex(&payload) == py_str(get(&expected, "sha256")),
            format!("{target} binding SHA-256 drift"),
        )?;
        require(
            load_yaml_unique(&path)? == *get(&expected, "value"),
            format!("{target} binding semantic drift"),
        )?;
        result.push(json!({
            "target": target,
            "path": get(&expected, "path").clone(),
            "bytes": get(&expected, "bytes").clone(),
            "sha256": get(&expected, "sha256").clone(),
            "value": get(&expected, "value").clone(),
        }));
    }
    Ok(result)
}

/// Python `verify_source_document`.
fn verify_source_document(root: &Path) -> R<()> {
    let payload = read_bytes(&root.join(SOURCE_PROVENANCE_PATH))?;
    require(
        payload.len() == SOURCE_PROVENANCE_BYTES,
        "source provenance byte count drift",
    )?;
    require(
        sha256_hex(&payload) == SOURCE_PROVENANCE_SHA256,
        "source provenance SHA-256 drift",
    )?;
    let text = String::from_utf8(payload)
        .map_err(|error| format!("source provenance is not UTF-8: {error}"))?;
    let anchors = static_json(SOURCE_ANCHORS_JSON);
    let reproduction = static_json(SOURCE_REPRODUCTION_JSON);
    for target in TARGET_ORDER {
        let anchor = get(&anchors, target);
        for key in ["repository", "commit", "tree", "parent"] {
            let value = py_str(get(anchor, key));
            require(
                text.contains(&value),
                format!("source provenance omits {key} {value}"),
            )?;
        }
    }
    let dependency = get(&reproduction, "deleted_dependency");
    require(
        text.contains(&py_str(get(dependency, "repository")))
            && text.contains(&py_str(get(dependency, "commit"))),
        "source provenance omits deleted gluegun dependency",
    )?;
    require(
        text.contains("spec `0.0.2`") && text.contains("deployed manifests declare `0.0.4`"),
        "source provenance omits spec mismatch",
    )?;
    let missing_by_role = static_json(MISSING_MAPPING_ENTITIES_BY_ROLE_JSON);
    for role in [
        "Factory",
        "NonFungiblePositionManager",
        "primary_pool",
        "fee_only_template",
    ] {
        for name in get(&missing_by_role, role)
            .as_array()
            .cloned()
            .unwrap_or_default()
        {
            let name = py_str(&name);
            require(
                text.contains(&format!("`{name}`")),
                format!("source provenance omits mapping.entities defect {name}"),
            )?;
        }
    }
    require(
        text.contains("`Token` exactly twice"),
        "source provenance omits primary Pool Token multiplicity",
    )?;
    require(
        text.contains("`Protocol`") && text.contains("declared interface"),
        "source provenance misclassifies or omits Protocol",
    )
}

/// Python `bind_manifest_entity_metadata`.
fn bind_manifest_entity_metadata(target: &str, manifest: &mut Value, schema: &Value) -> R<()> {
    let declared: BTreeSet<String> = get(schema, "declared_type_names")
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(py_str)
        .collect();
    let missing_by_role = static_json(MISSING_MAPPING_ENTITIES_BY_ROLE_JSON);
    let duplicate_by_role = static_json(DUPLICATE_MAPPING_ENTITIES_BY_ROLE_JSON);
    let fee_template = if target == "pancakeswap-v3-bsc" {
        "PancakeSwapPool"
    } else {
        "UniswapPool"
    };
    let role_for = |name: &str| -> Option<&'static str> {
        match name {
            "Factory" => Some("Factory"),
            "NonFungiblePositionManager" => Some("NonFungiblePositionManager"),
            "Pool" => Some("primary_pool"),
            other if other == fee_template => Some("fee_only_template"),
            _ => None,
        }
    };
    let components = manifest
        .get_mut("components")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| format!("{target} manifest components drift"))?;
    for component in components.iter_mut() {
        let name = py_str(get(component, "name"));
        let entities: Vec<String> = get(component, "entities")
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .map(py_str)
            .collect();
        let mut missing: Vec<String> = Vec::new();
        for entity in &entities {
            if !declared.contains(entity) && !missing.contains(entity) {
                missing.push(entity.clone());
            }
        }
        let mut counts: BTreeMap<String, usize> = BTreeMap::new();
        for entity in &entities {
            *counts.entry(entity.clone()).or_default() += 1;
        }
        let duplicates: Map<String, Value> = counts
            .into_iter()
            .filter(|(_, count)| *count > 1)
            .map(|(name, count)| (name, Value::from(count)))
            .collect();
        let role = role_for(&name)
            .ok_or_else(|| format!("{target}/{name} missing mapping.entities inventory drift"))?;
        require(
            json!(missing) == *get(&missing_by_role, role),
            format!("{target}/{name} missing mapping.entities inventory drift"),
        )?;
        require(
            Value::Object(duplicates.clone()) == *get(&duplicate_by_role, role),
            format!("{target}/{name} mapping.entities multiplicity drift"),
        )?;
        component["entity_metadata_contract"] = json!({
            "declared_order": get(component, "entities").clone(),
            "missing_from_schema_type_declarations": missing,
            "duplicate_multiplicity": Value::Object(duplicates),
            "normalization_allowed": false,
        });
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Assembled state, profile, and contract
// ---------------------------------------------------------------------------

struct State {
    bindings: Vec<Value>,
    artifact_records: Vec<Value>,
    by_target: BTreeMap<String, BTreeMap<String, Value>>,
    manifests: BTreeMap<String, Value>,
    schemas: BTreeMap<String, Value>,
    schema_diff: Value,
    abi_diff: Value,
    wasm_diff: Value,
}

/// Python `build_state`.
fn build_state(root: &Path) -> R<State> {
    let bindings = verify_bindings(root)?;
    let Artifacts {
        records: artifact_records,
        by_target,
    } = verify_artifacts(root)?;
    let mut manifests: BTreeMap<String, Value> = BTreeMap::new();
    let mut schemas: BTreeMap<String, Value> = BTreeMap::new();
    for target in TARGET_ORDER {
        let artifacts = &by_target[target];
        let deployment_path = root.join(as_str(get(&artifacts["deployment"], "vendored_path"))?);
        let mut manifest =
            manifest_profile(target, &load_yaml_unique(&deployment_path)?, artifacts)?;
        let schema_path = root.join(as_str(get(&artifacts["schema"], "vendored_path"))?);
        let schema = schema_profile(&schema_path)?;
        bind_manifest_entity_metadata(target, &mut manifest, &schema)?;
        manifests.insert(target.to_string(), manifest);
        schemas.insert(target.to_string(), schema);
    }
    let schema_diff = verify_schema_pair(&schemas)?;
    let abi_diff = build_abi_diff(root, &by_target)?;
    let wasm_diff = build_wasm_diff(&by_target)?;
    verify_source_document(root)?;
    Ok(State {
        bindings,
        artifact_records,
        by_target,
        manifests,
        schemas,
        schema_diff,
        abi_diff,
        wasm_diff,
    })
}

/// Python `truth_boundary`.
fn truth_boundary() -> Value {
    Value::Object(
        FALSE_GATES
            .iter()
            .map(|gate| ((*gate).to_string(), Value::Bool(false)))
            .collect(),
    )
}

/// Python `build_cross_target_diff`.
fn build_cross_target_diff(state: &State) -> R<Value> {
    let bsc = &state.manifests["pancakeswap-v3-bsc"];
    let base = &state.manifests["uniswap-v3-base"];
    let component = |manifest: &Value, index: usize| -> Value {
        get(manifest, "components")
            .as_array()
            .and_then(|items| items.get(index))
            .cloned()
            .unwrap_or(Value::Null)
    };
    for (role, index) in [
        ("Factory", 0),
        ("NonFungiblePositionManager", 1),
        ("primary_pool", 2),
        ("fee_only_template", 3),
    ] {
        let left = component(bsc, index);
        let right = component(base, index);
        require(
            *get(&left, "entity_metadata_contract") == *get(&right, "entity_metadata_contract"),
            format!("cross-target {role} mapping.entities metadata drift"),
        )?;
    }
    let expectations = static_json(TARGET_EXPECTATIONS_JSON);
    let handler_event = |target: &str, index: usize| -> Value {
        get(get(get(&expectations, target), "handlers"), "Pool")
            .as_array()
            .and_then(|items| items.get(index))
            .and_then(|pair| pair.get(1))
            .cloned()
            .unwrap_or(Value::Null)
    };
    Ok(json!({
        "exact": true,
        "deployment_cids": {
            "pancakeswap-v3-bsc": get(bsc, "deployment_cid").clone(),
            "uniswap-v3-base": get(base, "deployment_cid").clone(),
        },
        "chains": {"pancakeswap-v3-bsc": "bsc", "uniswap-v3-base": "base"},
        "factory_sources": {
            "pancakeswap-v3-bsc": get(&component(bsc, 0), "source").clone(),
            "uniswap-v3-base": get(&component(base, 0), "source").clone(),
        },
        "position_manager_sources": {
            "pancakeswap-v3-bsc": get(&component(bsc, 1), "source").clone(),
            "uniswap-v3-base": get(&component(base, 1), "source").clone(),
        },
        "schema": state.schema_diff.clone(),
        "abis": state.abi_diff.clone(),
        "wasm_exports": state.wasm_diff.clone(),
        "primary_pool": {
            "pancakeswap_swap": handler_event("pancakeswap-v3-bsc", 3),
            "base_swap": handler_event("uniswap-v3-base", 2),
            "pancakeswap_set_fee_protocol": "SetFeeProtocol(uint32,uint32,uint32,uint32)",
            "base_set_fee_protocol": "SetFeeProtocol(uint8,uint8,uint8,uint8)",
            "pancakeswap_declared_missing_export": "handleSetFeeProtocol",
            "pancakeswap_separate_fee_mapping_exports_handler": true,
            "base_primary_pool_declares_set_fee_protocol": false,
            "base_separate_fee_mapping_exports_handler": true,
        },
        "shared_manifest_quirks": {
            "misspelled_template_entity": "LiqudityPool",
            "primary_pool_token_entity_occurrences": 2,
            "metadata_identical_across_targets_by_role": true,
            "missing_from_schema_type_declarations_by_role":
                static_json(MISSING_MAPPING_ENTITIES_BY_ROLE_JSON),
            "duplicate_multiplicity_by_role":
                static_json(DUPLICATE_MAPPING_ENTITIES_BY_ROLE_JSON),
            "normalization_allowed": false,
        },
        "runtime_equivalence_claimed": false,
    }))
}

/// Python `build_profile`.
fn build_profile(state: &State) -> R<Value> {
    let anchors = static_json(SOURCE_ANCHORS_JSON);
    let mut targets = Vec::new();
    for target in TARGET_ORDER {
        let artifact_map = &state.by_target[target];
        let binding = state
            .bindings
            .iter()
            .find(|item| get(item, "target") == target)
            .ok_or_else(|| format!("{target} binding lock missing"))?
            .clone();
        let abis: Map<String, Value> = artifact_map
            .iter()
            .filter(|(role, _)| role.starts_with("abi/"))
            .map(|(role, record)| {
                (
                    role.trim_start_matches("abi/").to_string(),
                    get(record, "abi").clone(),
                )
            })
            .collect();
        let mappings: Map<String, Value> = artifact_map
            .iter()
            .filter(|(role, _)| role.starts_with("mapping/"))
            .map(|(role, record)| {
                (
                    role.trim_start_matches("mapping/").to_string(),
                    json!({
                        "cid": get(record, "cid").clone(),
                        "bytes": get(record, "bytes").clone(),
                        "sha256": get(record, "sha256").clone(),
                        "export_count": get(record, "export_count").clone(),
                        "export_table_sha256": get(record, "export_table_sha256").clone(),
                        "function_exports": get(record, "function_exports").clone(),
                        "handler_exports": get(record, "handler_exports").clone(),
                        "export_table": get(record, "export_table").clone(),
                    }),
                )
            })
            .collect();
        targets.push(json!({
            "target": target,
            "binding": binding,
            "deployment": state.manifests[target].clone(),
            "schema": state.schemas[target].clone(),
            "abis": Value::Object(abis),
            "mappings": Value::Object(mappings),
            "source_anchor": get(&anchors, target).clone(),
        }));
    }
    Ok(json!({
        "format_version": 1,
        "profile_id": "messari-v3-targets/v1",
        "status": "immutable_deployed_artifact_and_static_layout_baseline_only",
        "family": "messari-v3",
        "milestone": "M9",
        "artifact_count": 26,
        "targets": targets,
        "cross_target_diff": build_cross_target_diff(state)?,
        "source_reproduction": static_json(SOURCE_REPRODUCTION_JSON),
        "truth_boundary": truth_boundary(),
    }))
}

/// Python `_contract_artifact_record`.
fn contract_artifact_record(record: &Value) -> Value {
    let mut result = Map::new();
    for key in ["target", "role", "cid", "bytes", "sha256", "vendored_path"] {
        result.insert(key.to_string(), get(record, key).clone());
    }
    if let Some(abi) = record.get("abi") {
        result.insert("abi".to_string(), abi.clone());
    }
    if record.get("export_count").is_some() {
        for key in [
            "export_count",
            "export_table_sha256",
            "function_exports",
            "handler_exports",
        ] {
            result.insert(key.to_string(), get(record, key).clone());
        }
    }
    Value::Object(result)
}

/// Python `build_contract`.
fn build_contract(state: &State, profile: &Value) -> R<Value> {
    let rendered_profile = render(profile);
    Ok(json!({
        "format_version": 1,
        "contract_id": "messari-v3-targets/v1",
        "status": "immutable_target_baseline_only",
        "family": "messari-v3",
        "milestone": "M9",
        "issues": FAMILY_ISSUES.to_vec(),
        "issues_semantics": FAMILY_ISSUES_SEMANTICS,
        "artifact_count": 26,
        "target_count": 2,
        "artifact_lock": state
            .artifact_records
            .iter()
            .map(contract_artifact_record)
            .collect::<Vec<_>>(),
        "binding_lock": state.bindings.clone(),
        "layout_profile": {
            "path": PROFILE_PATH,
            "bytes": rendered_profile.len(),
            "sha256": sha256_hex(rendered_profile.as_bytes()),
            "canonical_sha256": canonical_sha256(profile),
        },
        "source_provenance": {
            "path": SOURCE_PROVENANCE_PATH,
            "bytes": SOURCE_PROVENANCE_BYTES,
            "sha256": SOURCE_PROVENANCE_SHA256,
            "anchors": static_json(SOURCE_ANCHORS_JSON),
            "reproduction": static_json(SOURCE_REPRODUCTION_JSON),
        },
        "cross_target_diff": build_cross_target_diff(state)?,
        "eligibility": {
            "policy": "graph-node-net-catchup-v1",
            "decision_scope": "evaluated_independently_per_target_binding",
            "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
            "copy_inventory": "every_current_copy_or_fresh_structural_absence_proof_per_required_cluster",
            "copy_selection": "independent_minimum_per_window_across_all_viable_healthy_copies",
            "required_forecast_windows_hours": [24, 72],
            "minimum_eta_days_exclusive": 28,
            "minima_may_belong_to_different_copies": true,
            "eligible_when": "independently_selected_minimum_24h_and_72h_etas_exceed_28_days_or_are_non_converging",
            "stop_when": "either_independently_selected_minimum_eta_is_at_or_below_28_days",
            "stopped_actions": ["implementation", "compute", "load"],
            "no_viable_copy": "eligible_only_with_fresh_structural_absence_proof_from_both_required_clusters",
            "current_decision": "indeterminate",
            "reason": "no_fresh_evidence",
        },
        "boundary": "the contract binds deployed bytes and static layout differences only; source-to-WASM reproduction, handler semantics, runtime behavior, store/error order, parity, backfill, deployment, production, and readiness remain unproved",
        "truth_boundary": truth_boundary(),
    }))
}

/// Python `verify_committed`.
fn verify_committed(root: &Path, state: &State) -> R<(Value, Value)> {
    let expected_profile = build_profile(state)?;
    let profile_path = root.join(PROFILE_PATH);
    let actual_profile = load_json(&profile_path)?;
    require(
        read_text(&profile_path)? == render(&actual_profile),
        "Messari V3 layout profile byte rendering drift",
    )?;
    require(
        canonical_bytes(&actual_profile) == canonical_bytes(&expected_profile),
        "Messari V3 layout profile differs from retained artifacts",
    )?;
    let expected_contract = build_contract(state, &expected_profile)?;
    let contract_path = root.join(CONTRACT_PATH);
    let actual_contract = load_json(&contract_path)?;
    require(
        read_text(&contract_path)? == render(&actual_contract),
        "Messari V3 provenance contract byte rendering drift",
    )?;
    require(
        *get(&actual_contract, "issues") == json!(FAMILY_ISSUES.to_vec()),
        "Messari V3 exhaustive family issue linkage drift",
    )?;
    require(
        get(&actual_contract, "issues_semantics") == FAMILY_ISSUES_SEMANTICS,
        "Messari V3 family issue linkage semantics drift",
    )?;
    require(
        canonical_bytes(&actual_contract) == canonical_bytes(&expected_contract),
        "Messari V3 provenance contract differs from retained artifacts",
    )?;
    require(
        FALSE_GATES
            .iter()
            .all(|gate| get(get(&actual_contract, "truth_boundary"), gate) == &Value::Bool(false)),
        "Messari V3 false gate promoted",
    )?;
    Ok((expected_contract, expected_profile))
}

// ---------------------------------------------------------------------------
// Dependency documentation
// ---------------------------------------------------------------------------

/// Python `extract_milestone_section`.
fn extract_milestone_section(text: &str, marker: &str, label: &str) -> R<String> {
    require(
        text.matches(marker).count() == 1,
        format!("Messari V3 {label} marker inventory drift"),
    )?;
    let offset = text.find(marker).unwrap_or(0) + marker.len();
    let tail = &text[offset..];
    let section = match milestone_heading_start(tail) {
        Some(start) => &tail[..start],
        None => tail.split("\n\n").next().unwrap_or(tail),
    };
    Ok(format!("{marker}{}", section.trim_end_matches('\n')))
}

/// Python `extract_paragraph`.
fn extract_paragraph(text: &str, marker: &str, label: &str) -> R<String> {
    require(
        text.matches(marker).count() == 1,
        format!("Messari V3 {label} marker inventory drift"),
    )?;
    let offset = text.find(marker).unwrap_or(0) + marker.len();
    let tail = &text[offset..];
    Ok(format!(
        "{marker}{}",
        tail.split("\n\n")
            .next()
            .unwrap_or(tail)
            .trim_end_matches('\n')
    ))
}

/// Python `verify_dependency_documentation`.
fn verify_dependency_documentation(root: &Path) -> R<()> {
    let documents = [
        ("root roadmap", read_text(&root.join(ROOT_README_PATH))?),
        ("target README", read_text(&root.join(TARGET_README_PATH))?),
        (
            "provenance index",
            read_text(&root.join(PROVENANCE_INDEX_PATH))?,
        ),
    ];
    let sections = [
        (
            "root roadmap",
            extract_milestone_section(
                &documents[0].1,
                "9. **M9 — Messari V3 BSC + Base**",
                "root roadmap M9",
            )?,
            ROOT_M9_SECTION,
        ),
        (
            "target README",
            extract_paragraph(
                &documents[1].1,
                "The provenance contract's top-level `issues` list",
                "target README M9",
            )?,
            TARGET_M9_SECTION,
        ),
        (
            "provenance index",
            extract_paragraph(
                &documents[2].1,
                "[`messari-v3-targets-v1.json`](messari-v3-targets-v1.json)",
                "provenance index M9",
            )?,
            PROVENANCE_M9_SECTION,
        ),
    ];
    for (label, section, expected) in &sections {
        require(
            section == expected,
            format!("Messari V3 {label} exact bounded M9 section drift"),
        )?;
    }
    require(
        issue_hrefs(&sections[0].1) == ROOT_M9_ISSUE_LINK_ORDER.to_vec(),
        "Messari V3 root roadmap exact M9 issue-link order drift",
    )?;
    require(
        traceability_arrays(&sections[1].1)
            == TARGET_M9_TRACEABILITY_ARRAYS
                .iter()
                .map(|values| values.to_vec())
                .collect::<Vec<_>>(),
        "Messari V3 target README exact traceability-array order drift",
    )?;
    for (label, section, _) in &sections {
        let normalized = collapse_whitespace(section);
        require(
            issue_dags(&normalized) == vec![M9_DEPENDENCY_DAG.to_string()],
            format!("Messari V3 {label} exact dependency DAG inventory drift"),
        )?;
        require(
            normalized.matches(M9_DEPENDENCY_ORDER).count() == 1,
            format!("Messari V3 {label} exact dependency order inventory drift"),
        )?;
    }
    let phrases = contradictory_phrases();
    for (label, text) in &documents {
        let normalized = collapse_whitespace(text).to_lowercase();
        require(
            !phrases
                .iter()
                .any(|phrase| contains_bounded(&normalized, phrase)),
            format!("Messari V3 {label} contradictory dependency ordering"),
        )?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

/// Python `write_contracts`.
fn write_contracts(root: &Path) -> R<(Value, Value)> {
    let state = build_state(root)?;
    let profile = build_profile(&state)?;
    let contract = build_contract(&state, &profile)?;
    for (relative, value) in [(PROFILE_PATH, &profile), (CONTRACT_PATH, &contract)] {
        let path = root.join(relative);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| format!("cannot create {}: {error}", parent.display()))?;
        }
        std::fs::write(&path, render(value))
            .map_err(|error| format!("cannot write {}: {error}", path.display()))?;
    }
    Ok((contract, profile))
}

/// Verify (or, with `write_contract`, regenerate) the pinned Messari V3
/// BSC/Base target baseline. Returns the Python verifier's success line.
pub fn verify(root: &Path, write_contract: bool) -> Result<String, String> {
    let root: PathBuf = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve {}: {error}", root.display()))?;
    verify_dependency_documentation(&root)?;
    let (contract, profile) = if write_contract {
        write_contracts(&root)?
    } else {
        let state = build_state(&root)?;
        verify_committed(&root, &state)?
    };
    let entity_bindings: u64 = get(&profile, "targets")
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter_map(|target| get(get(target, "schema"), "entity_count").as_u64())
        .sum();
    Ok(format!(
        "verified Messari V3 M9 target baseline: {} targets, {} artifacts, {entity_bindings} entity bindings, all runtime/parity/backfill/readiness gates false",
        get(&contract, "target_count"),
        get(&contract, "artifact_count"),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap as Map2;

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    fn copy_dir(from: &Path, to: &Path) {
        std::fs::create_dir_all(to).expect("create destination");
        for entry in std::fs::read_dir(from).expect("read source") {
            let entry = entry.expect("entry");
            let target = to.join(entry.file_name());
            if entry.path().is_dir() {
                copy_dir(&entry.path(), &target);
            } else {
                std::fs::copy(entry.path(), &target).expect("copy file");
            }
        }
    }

    /// Python `setUp`: a temporary root holding `messari-v3/`, the contract,
    /// the source provenance document, and the two READMEs.
    fn fixture() -> tempfile::TempDir {
        let source = repository();
        let temporary = tempfile::tempdir().expect("temporary directory");
        let root = temporary.path();
        copy_dir(&source.join("messari-v3"), &root.join("messari-v3"));
        for relative in [
            CONTRACT_PATH,
            SOURCE_PROVENANCE_PATH,
            ROOT_README_PATH,
            PROVENANCE_INDEX_PATH,
        ] {
            let destination = root.join(relative);
            std::fs::create_dir_all(destination.parent().expect("parent")).expect("create parent");
            std::fs::copy(source.join(relative), destination).expect("copy file");
        }
        temporary
    }

    fn run(root: &Path) -> Result<String, String> {
        verify(root, false)
    }

    fn error(root: &Path) -> String {
        run(root).expect_err("verification must fail")
    }

    fn load(root: &Path, relative: &str) -> Value {
        load_json(&root.join(relative)).expect("committed JSON parses")
    }

    fn store(root: &Path, relative: &str, value: &Value) {
        std::fs::write(root.join(relative), render(value)).expect("write JSON");
    }

    fn relock_profile_in_contract(root: &Path) {
        let profile = load(root, PROFILE_PATH);
        let payload = std::fs::read(root.join(PROFILE_PATH)).expect("read profile");
        let mut contract = load(root, CONTRACT_PATH);
        contract["layout_profile"]["bytes"] = Value::from(payload.len());
        contract["layout_profile"]["sha256"] = Value::String(sha256_hex(&payload));
        contract["layout_profile"]["canonical_sha256"] = Value::String(canonical_sha256(&profile));
        store(root, CONTRACT_PATH, &contract);
    }

    /// Named drift injections applied to the committed layout profile.
    type Mutations<'a> = Vec<(&'a str, fn(&mut Value))>;

    fn assert_relocked_profile_mutations_rejected(root: &Path, mutations: Mutations<'_>) {
        let original_profile = std::fs::read(root.join(PROFILE_PATH)).expect("read profile");
        let original_contract = std::fs::read(root.join(CONTRACT_PATH)).expect("read contract");
        for (name, mutate) in mutations {
            std::fs::write(root.join(PROFILE_PATH), &original_profile).expect("restore profile");
            std::fs::write(root.join(CONTRACT_PATH), &original_contract).expect("restore contract");
            let mut profile = load(root, PROFILE_PATH);
            mutate(&mut profile);
            store(root, PROFILE_PATH, &profile);
            relock_profile_in_contract(root);
            let message = error(root);
            assert!(
                message.contains("layout profile differs from retained artifacts"),
                "{name}: {message}"
            );
        }
        std::fs::write(root.join(PROFILE_PATH), &original_profile).expect("restore profile");
        std::fs::write(root.join(CONTRACT_PATH), &original_contract).expect("restore contract");
    }

    fn assert_contract_mutations_rejected(root: &Path, mutations: Mutations<'_>) {
        let original = std::fs::read(root.join(CONTRACT_PATH)).expect("read contract");
        for (name, mutate) in mutations {
            std::fs::write(root.join(CONTRACT_PATH), &original).expect("restore contract");
            let mut contract = load(root, CONTRACT_PATH);
            mutate(&mut contract);
            store(root, CONTRACT_PATH, &contract);
            let message = error(root);
            assert!(
                message.contains("provenance contract differs from retained artifacts"),
                "{name}: {message}"
            );
        }
        std::fs::write(root.join(CONTRACT_PATH), &original).expect("restore contract");
    }

    fn targets_by_name(profile: &Value) -> Map2<String, Value> {
        get(profile, "targets")
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .map(|target| (py_str(get(target, "target")), target.clone()))
            .collect()
    }

    #[test]
    fn exact_baseline_passes() {
        let fixture = fixture();
        let line = run(fixture.path()).expect("baseline verifies");
        assert!(
            line.contains("2 targets, 26 artifacts, 48 entity bindings"),
            "{line}"
        );
        assert_eq!(
            line,
            "verified Messari V3 M9 target baseline: 2 targets, 26 artifacts, 48 entity bindings, all runtime/parity/backfill/readiness gates false"
        );
    }

    #[test]
    fn real_repository_tree_verifies() {
        let line = verify(&repository(), false).expect("repository verifies");
        assert!(line.contains("48 entity bindings"), "{line}");
    }

    #[test]
    fn root_m9_section_is_bounded_from_a_future_m10_dag() {
        let fixture = fixture();
        let document = fixture.path().join(ROOT_README_PATH);
        let original = std::fs::read_to_string(&document).expect("read README");
        let updated = original.replacen(
            "\n\nMorpho Blue Base remains outside implementation",
            "\n10. **M10 — Future family**: independent dependency DAG is `#100 -> #101`.\n\nMorpho Blue Base remains outside implementation",
            1,
        );
        assert_ne!(updated, original);
        std::fs::write(&document, updated).expect("write README");
        run(fixture.path()).expect("bounded section still verifies");
    }

    #[test]
    fn family_issue_linkage_is_exact_ordered_and_exhaustive() {
        let fixture = fixture();
        let contract = load(fixture.path(), CONTRACT_PATH);
        assert_eq!(*get(&contract, "issues"), json!([85, 90, 92, 94, 95]));
        assert_eq!(get(&contract, "issues_semantics"), FAMILY_ISSUES_SEMANTICS);
        let bindings: Map2<String, Value> = get(&contract, "binding_lock")
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .map(|item| {
                (
                    py_str(get(item, "target")),
                    get(get(item, "value"), "issues").clone(),
                )
            })
            .collect();
        assert_eq!(bindings["pancakeswap-v3-bsc"], json!([85, 90, 92]));
        assert_eq!(bindings["uniswap-v3-base"], json!([94, 90, 95]));
    }

    #[test]
    fn family_issue_linkage_omission_reordering_and_extra_are_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let original = std::fs::read(root.join(CONTRACT_PATH)).expect("read contract");
        for (name, issues) in [
            ("omission", json!([85, 90, 92, 94])),
            ("reordering", json!([85, 92, 90, 94, 95])),
            ("extra", json!([85, 90, 92, 94, 95, 83])),
        ] {
            std::fs::write(root.join(CONTRACT_PATH), &original).expect("restore contract");
            let mut contract = load(root, CONTRACT_PATH);
            contract["issues"] = issues;
            store(root, CONTRACT_PATH, &contract);
            let message = error(root);
            assert!(
                message.contains("exhaustive family issue linkage drift"),
                "{name}: {message}"
            );
        }
    }

    #[test]
    fn dependency_dag_and_order_are_exact_across_all_docs() {
        let fixture = fixture();
        let root = fixture.path();
        let wrong_dag = "#85 -> #90 -> #92 -> #94 -> #95";
        for relative in [ROOT_README_PATH, TARGET_README_PATH, PROVENANCE_INDEX_PATH] {
            let document = root.join(relative);
            let original = std::fs::read_to_string(&document).expect("read document");
            let mutations = [
                (
                    "wrong DAG",
                    original.replacen(M9_DEPENDENCY_DAG, wrong_dag, 1),
                ),
                ("omitted DAG", original.replacen(M9_DEPENDENCY_DAG, "", 1)),
                (
                    "extra DAG",
                    original.replacen(
                        M9_DEPENDENCY_DAG,
                        &format!("{M9_DEPENDENCY_DAG} and {wrong_dag}"),
                        1,
                    ),
                ),
                (
                    "wrong order",
                    original.replacen(
                        "BSC certification precedes Base certification",
                        "Base certification precedes BSC certification",
                        1,
                    ),
                ),
            ];
            for (name, mutated) in mutations {
                assert_ne!(mutated, original, "{relative} {name}");
                std::fs::write(&document, &mutated).expect("write document");
                let message = error(root);
                assert!(message.contains("drift"), "{relative} {name}: {message}");
                std::fs::write(&document, &original).expect("restore document");
            }
        }
    }

    #[test]
    fn root_m9_issue_links_reject_substitution_omission_extra_and_reorder() {
        let fixture = fixture();
        let root = fixture.path();
        let document = root.join(ROOT_README_PATH);
        let original = std::fs::read_to_string(&document).expect("read README");
        let link = |issue: i64| {
            format!(
                "[#{issue}](https://github.com/pinax-network/substreams-backfills/issues/{issue})"
            )
        };
        let reordered = original
            .replacen(&link(85), "M9_ISSUE_TEMP", 1)
            .replacen(&link(94), &link(85), 1)
            .replacen("M9_ISSUE_TEMP", &link(94), 1);
        let mutations = [
            (
                "href substitution",
                original.replacen(
                    "substreams-backfills/issues/85",
                    "substreams-backfills/issues/999",
                    1,
                ),
            ),
            ("omission", original.replacen(&link(90), "", 1)),
            (
                "extra",
                original.replacen(
                    &link(95),
                    &format!(
                        "{} and [#999](https://github.com/pinax-network/substreams-backfills/issues/999)",
                        link(95)
                    ),
                    1,
                ),
            ),
            ("reorder", reordered),
        ];
        for (name, mutated) in mutations {
            assert_ne!(mutated, original, "{name}");
            std::fs::write(&document, &mutated).expect("write README");
            let message = error(root);
            assert!(message.contains("root roadmap"), "{name}: {message}");
            std::fs::write(&document, &original).expect("restore README");
        }
    }

    #[test]
    fn target_traceability_arrays_reject_all_order_and_inventory_drift() {
        let fixture = fixture();
        let root = fixture.path();
        let document = root.join(TARGET_README_PATH);
        let original = std::fs::read_to_string(&document).expect("read README");
        let mutations = [
            ("BSC substitution", "`[85, 90, 92]`", "`[85, 90, 999]`"),
            ("BSC omission", "`[85, 90, 92]`", "`[85, 90]`"),
            ("BSC extra", "`[85, 90, 92]`", "`[85, 90, 92, 999]`"),
            ("BSC reorder", "`[85, 90, 92]`", "`[90, 85, 92]`"),
            ("Base substitution", "`[94, 90, 95]`", "`[94, 90, 999]`"),
            ("Base omission", "`[94, 90, 95]`", "`[94, 90]`"),
            ("Base extra", "`[94, 90, 95]`", "`[94, 90, 95, 999]`"),
            ("Base reorder", "`[94, 90, 95]`", "`[90, 94, 95]`"),
            (
                "traceability semantics",
                "traceability associations",
                "distinct execution chains",
            ),
        ];
        for (name, current, replacement) in mutations {
            assert!(original.contains(current), "{name}");
            std::fs::write(&document, original.replacen(current, replacement, 1))
                .expect("write README");
            let message = error(root);
            assert!(message.contains("target README"), "{name}: {message}");
            std::fs::write(&document, &original).expect("restore README");
        }
    }

    #[test]
    fn contradictory_ordering_prose_is_rejected_across_all_docs() {
        let fixture = fixture();
        let root = fixture.path();
        for relative in [ROOT_README_PATH, TARGET_README_PATH, PROVENANCE_INDEX_PATH] {
            let document = root.join(relative);
            let original = std::fs::read_to_string(&document).expect("read document");
            std::fs::write(
                &document,
                format!("{original}\n\nBase certification precedes BSC certification.\n"),
            )
            .expect("write document");
            let message = error(root);
            assert!(
                message.contains("contradictory dependency ordering"),
                "{relative}: {message}"
            );
            std::fs::write(&document, &original).expect("restore document");
        }
    }

    #[test]
    fn contract_generation_is_byte_deterministic() {
        let fixture = fixture();
        let root = fixture.path();
        let before: Vec<(&str, Vec<u8>)> = [CONTRACT_PATH, PROFILE_PATH]
            .iter()
            .map(|relative| {
                (
                    *relative,
                    std::fs::read(root.join(relative)).expect("read committed file"),
                )
            })
            .collect();
        verify(root, true).expect("regeneration succeeds");
        for (relative, payload) in before {
            assert_eq!(
                std::fs::read(root.join(relative)).expect("read regenerated file"),
                payload,
                "{relative}"
            );
        }
    }

    #[test]
    fn all_26_artifacts_have_exact_cid_bytes_and_sha() {
        let fixture = fixture();
        let root = fixture.path();
        let contract = load(root, CONTRACT_PATH);
        let records = get(&contract, "artifact_lock")
            .as_array()
            .cloned()
            .unwrap_or_default();
        assert_eq!(records.len(), 26);
        for target in TARGET_ORDER {
            assert_eq!(
                records
                    .iter()
                    .filter(|record| get(record, "target") == target)
                    .count(),
                13,
                "{target}"
            );
        }
        for record in &records {
            let payload =
                std::fs::read(root.join(py_str(get(record, "vendored_path")))).expect("artifact");
            assert_eq!(Value::from(payload.len()), *get(record, "bytes"));
            assert_eq!(sha256_hex(&payload), py_str(get(record, "sha256")));
            assert_eq!(
                unixfs_file_cidv0(&payload).expect("CID"),
                py_str(get(record, "cid"))
            );
        }
    }

    #[test]
    fn exact_component_sources_abi_order_and_handlers() {
        let fixture = fixture();
        let profile = load(fixture.path(), PROFILE_PATH);
        let targets = targets_by_name(&profile);
        let expected_sources = [
            (
                "pancakeswap-v3-bsc",
                json!([
                    [
                        "Factory",
                        "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
                        26956207
                    ],
                    [
                        "NonFungiblePositionManager",
                        "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
                        26931961
                    ],
                    ["Pool", null, null],
                    ["PancakeSwapPool", null, null]
                ]),
            ),
            (
                "uniswap-v3-base",
                json!([
                    [
                        "Factory",
                        "0x33128a8fc17869897dce68ed026d694621f6fdfd",
                        1371670
                    ],
                    [
                        "NonFungiblePositionManager",
                        "0x03a520b32c04bf3beef7beb72e919cf822ed34f1",
                        1371704
                    ],
                    ["Pool", null, null],
                    ["UniswapPool", null, null]
                ]),
            ),
        ];
        let expected_abis = [
            (
                "pancakeswap-v3-bsc",
                json!([
                    [
                        "Pool",
                        "Factory",
                        "TickLens",
                        "ERC20",
                        "ERC20SymbolBytes",
                        "ERC20NameBytes"
                    ],
                    ["Pool", "Factory", "NonFungiblePositionManager", "ERC20"],
                    ["Pool", "Factory", "ERC20"],
                    ["Pool"]
                ]),
            ),
            (
                "uniswap-v3-base",
                json!([
                    [
                        "Pool",
                        "Factory",
                        "TickLens",
                        "ERC20",
                        "ERC20SymbolBytes",
                        "ERC20NameBytes"
                    ],
                    ["pool", "Factory", "NonFungiblePositionManager", "ERC20"],
                    ["Pool", "Factory", "ERC20"],
                    ["Pool"]
                ]),
            ),
        ];
        let expected_handlers = [
            (
                "pancakeswap-v3-bsc",
                json!([
                    ["handlePoolCreated"],
                    [
                        "handleIncreaseLiquidity",
                        "handleDecreaseLiquidity",
                        "handleTransfer"
                    ],
                    [
                        "handleInitialize",
                        "handleSetFeeProtocol",
                        "handleCollectPool",
                        "handleSwap",
                        "handleMint",
                        "handleBurn"
                    ],
                    ["handleSetFeeProtocol"]
                ]),
            ),
            (
                "uniswap-v3-base",
                json!([
                    ["handlePoolCreated"],
                    [
                        "handleIncreaseLiquidity",
                        "handleDecreaseLiquidity",
                        "handleTransfer"
                    ],
                    [
                        "handleInitialize",
                        "handleCollectPool",
                        "handleSwap",
                        "handleMint",
                        "handleBurn"
                    ],
                    ["handleSetFeeProtocol"]
                ]),
            ),
        ];
        for (index, (target, expected)) in expected_sources.iter().enumerate() {
            let deployment = get(&targets[*target], "deployment").clone();
            assert_eq!(get(&deployment, "spec_version"), "0.0.4");
            let components = get(&deployment, "components")
                .as_array()
                .cloned()
                .unwrap_or_default();
            let actual_sources: Vec<Value> = components
                .iter()
                .map(|item| {
                    json!([
                        get(item, "name").clone(),
                        get(get(item, "source"), "address").clone(),
                        get(get(item, "source"), "startBlock").clone(),
                    ])
                })
                .collect();
            assert_eq!(Value::Array(actual_sources), *expected, "{target}");
            let actual_abis: Vec<Value> = components
                .iter()
                .map(|item| {
                    Value::Array(
                        get(item, "abi_bindings")
                            .as_array()
                            .cloned()
                            .unwrap_or_default()
                            .iter()
                            .map(|binding| get(binding, "name").clone())
                            .collect(),
                    )
                })
                .collect();
            assert_eq!(
                Value::Array(actual_abis),
                expected_abis[index].1,
                "{target}"
            );
            let actual_handlers: Vec<Value> = components
                .iter()
                .map(|item| {
                    Value::Array(
                        get(item, "event_handlers")
                            .as_array()
                            .cloned()
                            .unwrap_or_default()
                            .iter()
                            .map(|handler| get(handler, "handler").clone())
                            .collect(),
                    )
                })
                .collect();
            assert_eq!(
                Value::Array(actual_handlers),
                expected_handlers[index].1,
                "{target}"
            );
            assert!(components.iter().all(|item| {
                get(item, "mapping_api_version") == "0.0.6"
                    && get(get(item, "source_abi_binding"), "exact_case_resolved") == &json!(true)
                    && get(
                        get(item, "source_abi_binding"),
                        "all_declared_events_present",
                    ) == &json!(true)
            }));
        }
    }

    #[test]
    fn schema_denominators_and_exact_directive_diff() {
        let fixture = fixture();
        let profile = load(fixture.path(), PROFILE_PATH);
        let targets = targets_by_name(&profile);
        for target in TARGET_ORDER {
            let schema = get(&targets[target], "schema").clone();
            assert_eq!(get(&schema, "entity_count"), 24, "{target}");
            assert_eq!(get(&schema, "field_count"), 388, "{target}");
        }
        let diff = get(get(&profile, "cross_target_diff"), "schema").clone();
        assert_eq!(
            get(&diff, "field_catalog_sha256"),
            "76ac4b0b03cb16e9cf6112335feff2a94d2a559132f8895842c9f5a5e5678840"
        );
        assert_eq!(*get(&diff, "base_only_network_values"), json!(["BASE"]));
        assert_eq!(
            *get(&diff, "entity_directive_differences"),
            json!({
                "PositionSnapshot": {
                    "pancakeswap-v3-bsc": ["@entity(immutable:true)", "@regularPolling"],
                    "uniswap-v3-base": ["@entity(immutable:true)", "@hourlySnapshot"],
                }
            })
        );
    }

    #[test]
    fn exact_full_abi_entry_ledgers_and_slot0_semantics() {
        let fixture = fixture();
        let profile = load(fixture.path(), PROFILE_PATH);
        let abis = get(get(&profile, "cross_target_diff"), "abis").clone();
        assert_eq!(
            *get(&abis, "byte_and_semantic_identical_abis"),
            json!(["ERC20", "ERC20NameBytes", "ERC20SymbolBytes", "TickLens"])
        );
        let differing = get(&abis, "differing_abis").clone();
        assert_eq!(
            object_keys(&differing),
            key_set(&["Factory", "NonFungiblePositionManager", "Pool"])
        );
        let expected = static_json(EXPECTED_ENTRY_LEDGERS_JSON);
        let counts = [
            ("Factory", 22, 9),
            ("NonFungiblePositionManager", 47, 45),
            ("Pool", 39, 36),
        ];
        for (name, bsc_count, base_count) in counts {
            let observed = get(&differing, name).clone();
            let ledger = get(&expected, name).clone();
            assert_eq!(
                get(&observed, "pancakeswap_entry_count"),
                bsc_count,
                "{name}"
            );
            assert_eq!(get(&observed, "base_entry_count"), base_count, "{name}");
            assert_eq!(
                get(&observed, "entry_identities_only_pancakeswap"),
                get(&ledger, "entry_identities_only_pancakeswap"),
                "{name}"
            );
            assert_eq!(
                get(&observed, "entry_identities_only_base"),
                get(&ledger, "entry_identities_only_base"),
                "{name}"
            );
            let identities = |key: &str| -> Value {
                Value::Array(
                    get(&observed, key)
                        .as_array()
                        .cloned()
                        .unwrap_or_default()
                        .iter()
                        .map(|item| get(item, "identity").clone())
                        .collect(),
                )
            };
            assert_eq!(
                identities("entries_only_pancakeswap"),
                *get(&ledger, "entry_identities_only_pancakeswap"),
                "{name}"
            );
            assert_eq!(
                identities("entries_only_base"),
                *get(&ledger, "entry_identities_only_base"),
                "{name}"
            );
            for side in ["entries_only_pancakeswap", "entries_only_base"] {
                for item in get(&observed, side).as_array().cloned().unwrap_or_default() {
                    assert_eq!(
                        get(&item, "canonical_sha256"),
                        &Value::String(canonical_sha256(get(&item, "entry"))),
                        "{name}/{side}"
                    );
                }
            }
            assert_eq!(
                identities("shared_identity_metadata_differences"),
                *get(&ledger, "metadata_difference_identities"),
                "{name}"
            );
            assert_eq!(
                identities("shared_identity_semantic_differences"),
                *get(&ledger, "semantic_difference_identities"),
                "{name}"
            );
        }
        let slot0 = get(
            get(&differing, "Pool"),
            "shared_identity_semantic_differences",
        )
        .as_array()
        .cloned()
        .unwrap_or_default();
        assert_eq!(slot0.len(), 1);
        assert_eq!(get(&slot0[0], "identity"), "function:slot0()");
        assert_eq!(
            *get(&slot0[0], "field_differences"),
            json!([
                {
                    "base": "uint8",
                    "base_present": true,
                    "pancakeswap": "uint32",
                    "pancakeswap_present": true,
                    "path": "/outputs/5/internalType",
                },
                {
                    "base": "uint8",
                    "base_present": true,
                    "pancakeswap": "uint32",
                    "pancakeswap_present": true,
                    "path": "/outputs/5/type",
                }
            ])
        );
        let output_types = |side: &str| -> Value {
            Value::Array(
                get(get(&slot0[0], side), "outputs")
                    .as_array()
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .map(|output| get(output, "type").clone())
                    .collect(),
            )
        };
        assert_eq!(
            output_types("pancakeswap"),
            json!(["uint160", "int24", "uint16", "uint16", "uint16", "uint32", "bool"])
        );
        assert_eq!(
            output_types("base"),
            json!(["uint160", "int24", "uint16", "uint16", "uint16", "uint8", "bool"])
        );
        let npm = get(&differing, "NonFungiblePositionManager").clone();
        let constructor = |side: &str| -> Value {
            get(&npm, side)
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .find(|item| py_str(get(item, "identity")).starts_with("constructor:"))
                .expect("constructor entry")
        };
        let names = |entry: &Value| -> Value {
            Value::Array(
                get(get(entry, "entry"), "inputs")
                    .as_array()
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .map(|item| get(item, "name").clone())
                    .collect(),
            )
        };
        assert_eq!(
            names(&constructor("entries_only_pancakeswap")),
            json!(["_deployer", "_factory", "_WETH9", "_tokenDescriptor_"])
        );
        assert_eq!(
            names(&constructor("entries_only_base")),
            json!(["_factory", "_WETH9", "_tokenDescriptor_"])
        );
    }

    #[test]
    fn full_wasm_export_tables_are_bound() {
        let fixture = fixture();
        let profile = load(fixture.path(), PROFILE_PATH);
        for target in get(&profile, "targets")
            .as_array()
            .cloned()
            .unwrap_or_default()
        {
            let name = py_str(get(&target, "target"));
            let mappings = get(&target, "mappings").clone();
            for (mapping_name, mapping) in mappings.as_object().expect("mappings object") {
                let (count, table_sha, handlers) =
                    expected_wasm_export(&name, &format!("mapping/{mapping_name}"))
                        .expect("pinned expectation");
                assert_eq!(get(mapping, "export_count"), count, "{name}/{mapping_name}");
                assert_eq!(
                    get(mapping, "export_count"),
                    &Value::from(get(mapping, "export_table").as_array().map_or(0, Vec::len)),
                    "{name}/{mapping_name}"
                );
                assert_eq!(
                    get(mapping, "export_table_sha256"),
                    table_sha,
                    "{name}/{mapping_name}"
                );
                assert_eq!(
                    canonical_sha256(get(mapping, "export_table")),
                    table_sha,
                    "{name}/{mapping_name}"
                );
                assert_eq!(
                    *get(mapping, "handler_exports"),
                    json!(handlers),
                    "{name}/{mapping_name}"
                );
            }
        }
    }

    #[test]
    fn exact_paired_wasm_cosmos_globals_and_export_index_ledgers() {
        let fixture = fixture();
        let profile = load(fixture.path(), PROFILE_PATH);
        let wasm = get(get(&profile, "cross_target_diff"), "wasm_exports").clone();
        let cosmos = json!([
            {"kind": "global", "name": "TypeId.CosmosMessageData"},
            {"kind": "global", "name": "TypeId.CosmosTransactionContext"}
        ]);
        let expected_indexes = static_json(EXPECTED_INDEX_DIFFERENCES_JSON);
        assert_eq!(get(&wasm, "pairing_complete"), &json!(true));
        assert_eq!(get(&wasm, "runtime_equivalence_claimed"), &json!(false));
        assert_eq!(*get(&wasm, "base_only_cosmos_type_id_globals"), cosmos);
        assert_eq!(
            object_keys(get(&wasm, "pairs")),
            object_keys(&expected_indexes)
        );
        for (role, expected) in expected_indexes.as_object().expect("expectations") {
            let pair = get(get(&wasm, "pairs"), role).clone();
            assert_eq!(*get(&pair, "exports_only_pancakeswap"), json!([]), "{role}");
            assert_eq!(*get(&pair, "exports_only_base"), cosmos, "{role}");
            assert_eq!(
                *get(&pair, "shared_export_kind_differences"),
                json!([]),
                "{role}"
            );
            assert_eq!(
                get(&pair, "handler_exports_identical"),
                &json!(true),
                "{role}"
            );
            let observed: Vec<Value> = get(&pair, "shared_export_index_differences")
                .as_array()
                .cloned()
                .unwrap_or_default()
                .iter()
                .map(|item| {
                    json!([
                        get(item, "name").clone(),
                        get(item, "kind").clone(),
                        get(item, "pancakeswap_index").clone(),
                        get(item, "base_index").clone(),
                    ])
                })
                .collect();
            assert_eq!(Value::Array(observed), *expected, "{role}");
        }
    }

    #[test]
    fn bsc_missing_handler_and_separate_fee_mapping_are_distinct() {
        let fixture = fixture();
        let profile = load(fixture.path(), PROFILE_PATH);
        let targets = targets_by_name(&profile);
        let components = |target: &str| -> Vec<Value> {
            get(get(&targets[target], "deployment"), "components")
                .as_array()
                .cloned()
                .unwrap_or_default()
        };
        let bsc = components("pancakeswap-v3-bsc");
        assert_eq!(
            *get(&bsc[2], "missing_declared_handler_exports"),
            json!(["handleSetFeeProtocol"])
        );
        assert!(!get(&bsc[2], "handler_exports")
            .as_array()
            .cloned()
            .unwrap_or_default()
            .contains(&json!("handleSetFeeProtocol")));
        assert_eq!(
            get(&bsc[3], "mapping_cid"),
            "QmZh9pwyqnVEknPgTWraJweuyy1qbwzhA2rrSq43xmdgHL"
        );
        assert_eq!(
            *get(&bsc[3], "handler_exports"),
            json!(["handleSetFeeProtocol"])
        );
        let base = components("uniswap-v3-base");
        assert_eq!(
            *get(&base[2], "missing_declared_handler_exports"),
            json!([])
        );
        assert_eq!(
            *get(&base[3], "handler_exports"),
            json!(["handleSetFeeProtocol"])
        );
    }

    #[test]
    fn mapping_entity_defects_and_multiplicity_are_exact_for_both_targets() {
        let fixture = fixture();
        let profile = load(fixture.path(), PROFILE_PATH);
        let expected_missing = json!({
            "Factory": ["_PricesUSD", "_TokenTracker"],
            "NonFungiblePositionManager": [],
            "primary_pool": ["LiqudityPool", "PoolDailySnapshot", "_PricesUSD", "_Account", "_DailyActiveAccount", "_TokenTracker"],
            "fee_only_template": ["LiqudityPool"],
        });
        let expected_duplicates = json!({
            "Factory": {},
            "NonFungiblePositionManager": {},
            "primary_pool": {"Token": 2},
            "fee_only_template": {},
        });
        let quirks = get(get(&profile, "cross_target_diff"), "shared_manifest_quirks").clone();
        assert_eq!(
            get(&quirks, "metadata_identical_across_targets_by_role"),
            &json!(true)
        );
        assert_eq!(
            *get(&quirks, "missing_from_schema_type_declarations_by_role"),
            expected_missing
        );
        assert_eq!(
            *get(&quirks, "duplicate_multiplicity_by_role"),
            expected_duplicates
        );
        for target in get(&profile, "targets")
            .as_array()
            .cloned()
            .unwrap_or_default()
        {
            let components = get(get(&target, "deployment"), "components")
                .as_array()
                .cloned()
                .unwrap_or_default();
            for (role, index) in [
                ("Factory", 0),
                ("NonFungiblePositionManager", 1),
                ("primary_pool", 2),
                ("fee_only_template", 3),
            ] {
                let contract = get(&components[index], "entity_metadata_contract").clone();
                assert_eq!(
                    get(&contract, "missing_from_schema_type_declarations"),
                    get(&expected_missing, role),
                    "{role}"
                );
                assert_eq!(
                    get(&contract, "duplicate_multiplicity"),
                    get(&expected_duplicates, role),
                    "{role}"
                );
                assert_eq!(get(&contract, "normalization_allowed"), &json!(false));
            }
            assert_eq!(
                get(&components[2], "entities")
                    .as_array()
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .filter(|entity| *entity == "Token")
                    .count(),
                2
            );
            assert!(!get(
                get(&components[0], "entity_metadata_contract"),
                "missing_from_schema_type_declarations"
            )
            .as_array()
            .cloned()
            .unwrap_or_default()
            .contains(&json!("Protocol")));
        }
    }

    #[test]
    fn source_anchors_reproduction_refusal_and_false_gates_are_exact() {
        let fixture = fixture();
        let root = fixture.path();
        let contract = load(root, CONTRACT_PATH);
        let source = get(&contract, "source_provenance").clone();
        let payload = std::fs::read(root.join(SOURCE_PROVENANCE_PATH)).expect("source document");
        assert_eq!(get(&source, "bytes"), &Value::from(payload.len()));
        assert_eq!(get(&source, "sha256"), &Value::String(sha256_hex(&payload)));
        let anchors = get(&source, "anchors").clone();
        for (target, commit, tree, parent) in [
            (
                "pancakeswap-v3-bsc",
                "0c4618d6343b5011742a59ec308dd7ce07b9908b",
                "1a309dcd6e8827db41a00634eaab6d1e1ed70da6",
                "6af451686c1dc783f823e51b28686ef95d219c16",
            ),
            (
                "uniswap-v3-base",
                "2c60bd10b5e1a090f6e3b55f0634f2a15ec91dbe",
                "3a2ff3eec89f6ab6f1f61d3c10a546c231c3f06b",
                "b16e506a84247a178a9eae09e799bc75787f4275",
            ),
        ] {
            let anchor = get(&anchors, target).clone();
            assert_eq!(get(&anchor, "commit"), commit);
            assert_eq!(get(&anchor, "tree"), tree);
            assert_eq!(get(&anchor, "parent"), parent);
        }
        let reproduction = get(&source, "reproduction").clone();
        assert_eq!(get(&reproduction, "source_template_spec_version"), "0.0.2");
        assert_eq!(
            get(&reproduction, "deployed_manifest_spec_version"),
            "0.0.4"
        );
        assert_eq!(get(&reproduction, "spec_version_mismatch"), &json!(true));
        let dependency = get(&reproduction, "deleted_dependency").clone();
        assert_eq!(
            get(&dependency, "commit"),
            "b34b9003d7bf556836da41b57ef36eb21570620a"
        );
        assert_eq!(get(&dependency, "available"), &json!(false));
        assert_eq!(
            get(&dependency, "frozen_yarn_install_succeeded"),
            &json!(false)
        );
        assert_eq!(
            get(&dependency, "frozen_npm_install_succeeded"),
            &json!(false)
        );
        let gates = get(&contract, "truth_boundary").clone();
        assert_eq!(object_keys(&gates), key_set(&FALSE_GATES));
        assert!(gates
            .as_object()
            .expect("gates object")
            .values()
            .all(|value| *value == json!(false)));
    }

    #[test]
    fn source_provenance_prose_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join(SOURCE_PROVENANCE_PATH);
        let text = std::fs::read_to_string(&path).expect("source document");
        std::fs::write(&path, text.replacen("do not replace", "do now replace", 1))
            .expect("write source document");
        let message = error(root);
        assert!(
            message.contains("source provenance SHA-256 drift"),
            "{message}"
        );
    }

    #[test]
    fn duplicate_contract_json_key_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join(CONTRACT_PATH);
        let text = std::fs::read_to_string(&path).expect("contract");
        std::fs::write(
            &path,
            text.replacen(
                "  \"artifact_count\": 26,",
                "  \"artifact_count\": 26,\n  \"artifact_count\": 26,",
                1,
            ),
        )
        .expect("write contract");
        let message = error(root);
        assert!(message.contains("duplicate JSON key"), "{message}");
    }

    #[test]
    fn duplicate_manifest_yaml_key_is_rejected() {
        let fixture = fixture();
        let path = fixture
            .path()
            .join("messari-v3/reference/uniswap-v3-base/deployment.yaml");
        let text = std::fs::read_to_string(&path).expect("manifest");
        std::fs::write(&path, format!("specVersion: 0.0.4\n{text}")).expect("write manifest");
        let message = load_yaml_unique(&path).expect_err("duplicate key must fail");
        assert!(message.contains("duplicate YAML key"), "{message}");
    }

    #[test]
    fn duplicate_abi_json_key_is_rejected() {
        let fixture = fixture();
        let path = fixture
            .path()
            .join("messari-v3/reference/uniswap-v3-base/abis/Pool.json");
        let text = std::fs::read_to_string(&path).expect("ABI");
        std::fs::write(
            &path,
            text.replacen(
                "    \"anonymous\": false,",
                "    \"anonymous\": false,\n    \"anonymous\": false,",
                1,
            ),
        )
        .expect("write ABI");
        let message = load_json(&path).expect_err("duplicate key must fail");
        assert!(message.contains("duplicate JSON key"), "{message}");
    }

    #[test]
    fn artifact_byte_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join("messari-v3/reference/pancakeswap-v3-bsc/schema.graphql");
        let mut payload = std::fs::read(&path).expect("schema");
        let index = payload.len() - 2;
        payload[index] ^= 1;
        std::fs::write(&path, payload).expect("write schema");
        run(root).expect_err("byte drift must fail");
    }

    #[test]
    fn unexpected_retained_artifact_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        std::fs::write(
            root.join("messari-v3/reference/uniswap-v3-base/abis/Unexpected.json"),
            "[]\n",
        )
        .expect("write artifact");
        let message = error(root);
        assert!(message.contains("artifact path closure drift"), "{message}");
    }

    #[test]
    fn unexpected_target_binding_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        std::fs::write(
            root.join("messari-v3/QmUnexpected.yaml"),
            "deployment: QmUnexpected\n",
        )
        .expect("write binding");
        let message = error(root);
        assert!(message.contains("binding path closure drift"), "{message}");
    }

    #[test]
    fn contract_relock_cannot_hide_artifact_drift() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join("messari-v3/reference/uniswap-v3-base/schema.graphql");
        let mut payload = std::fs::read(&path).expect("schema");
        let index = payload.len() - 2;
        payload[index] ^= 1;
        std::fs::write(&path, &payload).expect("write schema");
        let mut contract = load(root, CONTRACT_PATH);
        let records = contract["artifact_lock"]
            .as_array_mut()
            .expect("artifact lock");
        let record = records
            .iter_mut()
            .find(|item| get(item, "target") == "uniswap-v3-base" && get(item, "role") == "schema")
            .expect("schema record");
        record["bytes"] = Value::from(payload.len());
        record["sha256"] = Value::String(sha256_hex(&payload));
        record["cid"] = Value::String(unixfs_file_cidv0(&payload).expect("CID"));
        store(root, CONTRACT_PATH, &contract);
        run(root).expect_err("relocked drift must fail");
    }

    #[test]
    fn binding_semantic_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join("messari-v3/QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3.yaml");
        let text = std::fs::read_to_string(&path).expect("binding");
        std::fs::write(
            &path,
            text.replacen("queries_24h: 143319", "queries_24h: 143320", 1),
        )
        .expect("write binding");
        run(root).expect_err("binding drift must fail");
    }

    #[test]
    fn market_snapshots_are_exact_and_not_mislabeled_as_signal() {
        let fixture = fixture();
        let contract = load(fixture.path(), CONTRACT_PATH);
        let bindings: Map2<String, Value> = get(&contract, "binding_lock")
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .map(|item| (py_str(get(item, "target")), get(item, "value").clone()))
            .collect();
        assert_eq!(
            *get(&bindings["pancakeswap-v3-bsc"], "market_snapshot"),
            json!({
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 143319,
                "query_fees_grt_24h": "170.760",
            })
        );
        assert_eq!(
            *get(&bindings["uniswap-v3-base"], "market_snapshot"),
            json!({
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 17568,
                "query_fees_grt_24h": "21.000",
            })
        );
        let forbidden = key_set(&[
            "market_qpd",
            "qos_snapshot_at",
            "placement",
            "signal_grt",
            "grt",
            "generic_grt",
        ]);
        for binding in bindings.values() {
            let snapshot = get(binding, "market_snapshot").clone();
            assert!(get(&snapshot, "query_fees_grt_24h").is_string());
            assert!(object_keys(binding)
                .intersection(&forbidden)
                .next()
                .is_none());
            assert!(object_keys(&snapshot)
                .intersection(&forbidden)
                .next()
                .is_none());
        }
    }

    #[test]
    fn market_snapshot_legacy_numeric_unattributed_and_signal_forms_are_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join("messari-v3/QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3.yaml");
        let original = std::fs::read_to_string(&path).expect("binding");
        let mutations: [(&str, &str, &str); 8] = [
            (
                "legacy market_qpd",
                "market_snapshot:\n",
                "market_qpd: 143319\nmarket_snapshot:\n",
            ),
            (
                "numeric fee",
                "query_fees_grt_24h: \"170.760\"",
                "query_fees_grt_24h: 170.760",
            ),
            ("wrong authority", "issues/83", "issues/82"),
            (
                "missing authority",
                "  authority: https://github.com/pinax-network/substreams-backfills/issues/83\n",
                "",
            ),
            (
                "wrong timestamp",
                "2026-08-31T17:20:00Z",
                "2026-08-31T17:21:00Z",
            ),
            (
                "missing timestamp",
                "  measured_at: \"2026-08-31T17:20:00Z\"\n",
                "",
            ),
            (
                "signal GRT",
                "  authority:",
                "  signal_grt: \"170.760\"\n  authority:",
            ),
            (
                "generic GRT",
                "  authority:",
                "  grt: \"170.760\"\n  authority:",
            ),
        ];
        for (name, current, replacement) in mutations {
            let mutated = original.replacen(current, replacement, 1);
            assert_ne!(mutated, original, "{name}");
            std::fs::write(&path, &mutated).expect("write binding");
            run(root).expect_err(name);
        }
        std::fs::write(&path, &original).expect("restore binding");
    }

    #[test]
    fn manifest_semantic_drift_is_rejected_beyond_raw_lock() {
        let fixture = fixture();
        let root = fixture.path().canonicalize().expect("canonical root");
        let artifacts = verify_artifacts(&root).expect("artifacts verify");
        let by_target = &artifacts.by_target["uniswap-v3-base"];
        let path = root.join(py_str(get(&by_target["deployment"], "vendored_path")));
        let mut manifest = load_yaml_unique(&path).expect("manifest parses");
        manifest["dataSources"][0]["network"] = Value::String("mainnet".into());
        let message = manifest_profile("uniswap-v3-base", &manifest, by_target)
            .expect_err("semantic drift must fail");
        assert!(message.contains("semantic projection drift"), "{message}");
    }

    #[test]
    fn profile_metadata_normalization_is_rejected_after_contract_relock() {
        let fixture = fixture();
        let root = fixture.path();
        let mut profile = load(root, PROFILE_PATH);
        let primary = &mut profile["targets"][0]["deployment"]["components"][2];
        for pointer in [
            "/entities",
            "/entity_metadata_contract/declared_order",
            "/entity_metadata_contract/missing_from_schema_type_declarations",
        ] {
            let target = primary.pointer_mut(pointer).expect("pointer resolves");
            let items = target.as_array_mut().expect("array");
            let index = items
                .iter()
                .position(|item| item == "LiqudityPool")
                .expect("LiqudityPool present");
            items.remove(index);
        }
        store(root, PROFILE_PATH, &profile);
        relock_profile_in_contract(root);
        run(root).expect_err("normalized metadata must fail");
    }

    #[test]
    fn abi_ledger_omissions_are_rejected_after_profile_relock() {
        let fixture = fixture();
        fn remove_slot0_semantics(profile: &mut Value) {
            profile["cross_target_diff"]["abis"]["differing_abis"]["Pool"]
                ["shared_identity_semantic_differences"] = json!([]);
        }
        fn remove_constructor_identity(profile: &mut Value) {
            remove_string(
                &mut profile["cross_target_diff"]["abis"]["differing_abis"]["Factory"]
                    ["entry_identities_only_pancakeswap"],
                "constructor:constructor(address)",
            );
        }
        fn remove_exclusive_entry(profile: &mut Value) {
            remove_string(
                &mut profile["cross_target_diff"]["abis"]["differing_abis"]["Pool"]
                    ["entry_identities_only_pancakeswap"],
                "function:lmPool()",
            );
        }
        assert_relocked_profile_mutations_rejected(
            fixture.path(),
            vec![
                ("slot0 semantic difference removed", remove_slot0_semantics),
                ("constructor identity removed", remove_constructor_identity),
                ("exclusive ABI entry removed", remove_exclusive_entry),
            ],
        );
    }

    fn remove_string(value: &mut Value, needle: &str) {
        let items = value.as_array_mut().expect("array");
        let index = items
            .iter()
            .position(|item| item == needle)
            .unwrap_or_else(|| panic!("{needle} present"));
        items.remove(index);
    }

    #[test]
    fn wasm_pair_omissions_and_equivalence_promotion_are_rejected_after_profile_relock() {
        let fixture = fixture();
        fn remove_cosmos_global(profile: &mut Value) {
            let items = profile["cross_target_diff"]["wasm_exports"]["pairs"]["Factory"]
                ["exports_only_base"]
                .as_array_mut()
                .expect("array");
            let index = items
                .iter()
                .position(|item| {
                    *item == json!({"kind": "global", "name": "TypeId.CosmosMessageData"})
                })
                .expect("Cosmos global present");
            items.remove(index);
        }
        fn change_export_index_delta(profile: &mut Value) {
            profile["cross_target_diff"]["wasm_exports"]["pairs"]["Factory"]
                ["shared_export_index_differences"][0]["base_index"] = Value::from(184);
        }
        fn promote_runtime_equivalence(profile: &mut Value) {
            profile["cross_target_diff"]["wasm_exports"]["runtime_equivalence_claimed"] =
                Value::Bool(true);
        }
        assert_relocked_profile_mutations_rejected(
            fixture.path(),
            vec![
                ("Base-only Cosmos global removed", remove_cosmos_global),
                (
                    "shared export index delta changed",
                    change_export_index_delta,
                ),
                (
                    "WASM runtime equivalence promoted",
                    promote_runtime_equivalence,
                ),
            ],
        );
    }

    #[test]
    fn malformed_wasm_is_rejected_by_the_direct_parser() {
        for (payload, expected) in [
            (b"not wasm".to_vec(), "mapping is not WebAssembly v1"),
            (
                b"\0asm\x01\0\0\0".to_vec(),
                "WebAssembly export section missing",
            ),
        ] {
            let message = wasm_export_table(&payload).expect_err("malformed module must fail");
            assert!(message.contains(expected), "{message}");
        }
    }

    #[test]
    fn eligibility_policy_and_empty_evidence_are_exact() {
        let fixture = fixture();
        let contract = load(fixture.path(), CONTRACT_PATH);
        assert_eq!(
            *get(&contract, "eligibility"),
            json!({
                "copy_inventory": "every_current_copy_or_fresh_structural_absence_proof_per_required_cluster",
                "copy_selection": "independent_minimum_per_window_across_all_viable_healthy_copies",
                "current_decision": "indeterminate",
                "decision_scope": "evaluated_independently_per_target_binding",
                "eligible_when": "independently_selected_minimum_24h_and_72h_etas_exceed_28_days_or_are_non_converging",
                "minimum_eta_days_exclusive": 28,
                "minima_may_belong_to_different_copies": true,
                "no_viable_copy": "eligible_only_with_fresh_structural_absence_proof_from_both_required_clusters",
                "policy": "graph-node-net-catchup-v1",
                "reason": "no_fresh_evidence",
                "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
                "required_forecast_windows_hours": [24, 72],
                "stop_when": "either_independently_selected_minimum_eta_is_at_or_below_28_days",
                "stopped_actions": ["implementation", "compute", "load"],
            })
        );
        for record in get(&contract, "binding_lock")
            .as_array()
            .cloned()
            .unwrap_or_default()
        {
            let eligibility = get(get(&record, "value"), "eligibility").clone();
            assert_eq!(
                *get(&eligibility, "required_clusters"),
                json!(["riv-subgraphs-a", "kan-subgraphs-a"])
            );
            assert_eq!(
                *get(&eligibility, "latest"),
                json!({
                    "decision": "indeterminate",
                    "evidence": null,
                    "measured_at": null,
                    "reason": "no_fresh_evidence",
                    "sha256": null,
                })
            );
        }
    }

    #[test]
    fn eligibility_cluster_order_and_undigested_evidence_are_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join("messari-v3/QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3.yaml");
        let original = std::fs::read_to_string(&path).expect("binding");
        let mutations: [(&str, &str, &str); 3] = [
            (
                "required cluster removed",
                "required_clusters: [riv-subgraphs-a, kan-subgraphs-a]",
                "required_clusters: [riv-subgraphs-a]",
            ),
            (
                "required cluster order changed",
                "required_clusters: [riv-subgraphs-a, kan-subgraphs-a]",
                "required_clusters: [kan-subgraphs-a, riv-subgraphs-a]",
            ),
            (
                "evidence added without digest",
                "    evidence: null\n    sha256: null",
                "    evidence: docs/eligibility/unverified.json\n    sha256: null",
            ),
        ];
        for (name, current, replacement) in mutations {
            let mutated = original.replacen(current, replacement, 1);
            assert_ne!(mutated, original, "{name}");
            std::fs::write(&path, &mutated).expect("write binding");
            run(root).expect_err(name);
        }
        std::fs::write(&path, &original).expect("restore binding");
    }

    #[test]
    fn eligibility_window_exclusive_threshold_and_truth_promotion_are_rejected() {
        let fixture = fixture();
        fn drift_window(contract: &mut Value) {
            contract["eligibility"]["required_forecast_windows_hours"] = json!([24, 48]);
        }
        fn weaken_exclusive_threshold(contract: &mut Value) {
            contract["eligibility"]["minimum_eta_days_exclusive"] = Value::from(27);
        }
        fn couple_window_selection(contract: &mut Value) {
            contract["eligibility"]["copy_selection"] =
                Value::String("one_fastest_copy_for_both_windows".into());
        }
        fn couple_target_decisions(contract: &mut Value) {
            contract["eligibility"]["decision_scope"] = Value::String("family_wide".into());
        }
        fn deny_cross_copy_minima(contract: &mut Value) {
            contract["eligibility"]["minima_may_belong_to_different_copies"] = Value::Bool(false);
        }
        fn weaken_eligible_condition(contract: &mut Value) {
            contract["eligibility"]["eligible_when"] =
                Value::String("either_window_exceeds_28_days".into());
        }
        fn disable_stop_condition(contract: &mut Value) {
            contract["eligibility"]["stop_when"] = Value::String("never".into());
        }
        fn weaken_no_viable_copy_rule(contract: &mut Value) {
            contract["eligibility"]["no_viable_copy"] =
                Value::String("failed_copy_is_eligible".into());
        }
        fn remove_stopped_action(contract: &mut Value) {
            remove_string(
                &mut contract["eligibility"]["stopped_actions"],
                "implementation",
            );
        }
        fn promote_eligibility_truth(contract: &mut Value) {
            contract["truth_boundary"]["eligibility_complete"] = Value::Bool(true);
        }
        assert_contract_mutations_rejected(
            fixture.path(),
            vec![
                ("forecast window drift", drift_window),
                (
                    "exclusive greater-than-28-day rule drift",
                    weaken_exclusive_threshold,
                ),
                (
                    "24-hour and 72-hour minima coupled to one copy",
                    couple_window_selection,
                ),
                (
                    "target decisions coupled across the family",
                    couple_target_decisions,
                ),
                ("different-copy minima forbidden", deny_cross_copy_minima),
                ("eligibility condition weakened", weaken_eligible_condition),
                (
                    "eligibility stop condition disabled",
                    disable_stop_condition,
                ),
                (
                    "no-viable-copy structural proof weakened",
                    weaken_no_viable_copy_rule,
                ),
                (
                    "implementation omitted from stopped actions",
                    remove_stopped_action,
                ),
                ("eligibility truth promoted", promote_eligibility_truth),
            ],
        );
    }

    #[test]
    fn cross_target_diff_drift_is_rejected_after_contract_relock() {
        let fixture = fixture();
        let root = fixture.path();
        let mut profile = load(root, PROFILE_PATH);
        profile["cross_target_diff"]["runtime_equivalence_claimed"] = Value::Bool(true);
        store(root, PROFILE_PATH, &profile);
        relock_profile_in_contract(root);
        run(root).expect_err("promoted equivalence must fail");
    }

    #[test]
    fn source_anchor_drift_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let mut contract = load(root, CONTRACT_PATH);
        contract["source_provenance"]["anchors"]["uniswap-v3-base"]["tree"] =
            Value::String("0".repeat(40));
        store(root, CONTRACT_PATH, &contract);
        run(root).expect_err("anchor drift must fail");
    }

    #[test]
    fn truth_gate_promotion_is_rejected() {
        let fixture = fixture();
        let root = fixture.path();
        let mut contract = load(root, CONTRACT_PATH);
        contract["truth_boundary"]["backfill_ready"] = Value::Bool(true);
        store(root, CONTRACT_PATH, &contract);
        run(root).expect_err("promoted gate must fail");
    }

    #[test]
    fn source_document_metadata_evidence_is_byte_locked() {
        let fixture = fixture();
        let root = fixture.path();
        let path = root.join(SOURCE_PROVENANCE_PATH);
        let text = std::fs::read_to_string(&path).expect("source document");
        std::fs::write(
            &path,
            text.replacen("`Token` exactly twice", "`Token` twice", 1),
        )
        .expect("write source document");
        let message = error(root);
        assert!(
            message.contains("source provenance byte count drift"),
            "{message}"
        );
    }

    #[test]
    fn verifier_has_no_network_or_subprocess_imports() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("src/targets/messari_v3.rs"),
        )
        .expect("module source");
        // Scan only the verifier itself; the test module names the forbidden
        // crates in order to look for them.
        let verifier = source.split("#[cfg(test)]").next().expect("verifier body");
        for forbidden in ["ur", "std::proc", "std::n", "reqw", "Command::n"] {
            let needle = match forbidden {
                "ur" => format!("{forbidden}eq"),
                "std::proc" => format!("{forbidden}ess"),
                "std::n" => format!("{forbidden}et"),
                "reqw" => format!("{forbidden}est"),
                _ => format!("{forbidden}ew"),
            };
            assert!(!verifier.contains(&needle), "{needle}");
        }
    }
}
