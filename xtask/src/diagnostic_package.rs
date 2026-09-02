//! Structural verification of the evidence-only Uniswap V3 package.
//!
//! Port of the retired `scripts/verify-uniswap-v3-diagnostic-package.py`. The package bytes are
//! deliberately *not* pinned; only the declared shape reported by `substreams info --json`
//! is checked. Failure texts are byte-identical to the Python original, including its
//! `repr()` formatting, so the two implementations stay interchangeable in CI logs.

use std::collections::BTreeSet;
use std::path::Path;
use std::process::Command;

use serde_json::Value;

/// The 22 modules the evidence-only package must declare, in sorted order.
const EXPECTED_MODULES: [&str; 22] = [
    "graph_out",
    "map_extract_data_types",
    "map_pools_created",
    "map_tokens_whitelist_pools",
    "store_derived_factory_tvl",
    "store_derived_tvl",
    "store_eth_prices",
    "store_max_windows",
    "store_min_windows",
    "store_native_amounts",
    "store_pool_count",
    "store_pool_liquidities",
    "store_pool_sqrt_price",
    "store_pools_created",
    "store_positions",
    "store_prices",
    "store_swaps_volume",
    "store_ticks_liquidities",
    "store_token_tvl",
    "store_tokens",
    "store_tokens_whitelist_pools",
    "store_total_tx_counts",
];

const EXPECTED_INITIAL_BLOCK: i64 = 12_369_621;
const EXPECTED_NAME: &str = "uniswap_v3";
const EXPECTED_VERSION: &str = "v0.2.11";
const EXPECTED_NETWORK: &str = "mainnet";
const EXPECTED_GRAPH_OUT_TYPE: &str = "proto:sf.substreams.entity.v1.EntityChanges";

/// The exact line the Python verifier prints on success.
pub const SUCCESS_LINE: &str = "verified evidence-only Uniswap V3 package: uniswap_v3 v0.2.11, mainnet, 22 modules, graph_out EntityChanges, initial block 12369621";

/// Run `substreams info --json <package>` and parse its stdout.
pub fn inspect(package_path: &Path) -> Result<Value, String> {
    let display = package_path.display();
    let output = Command::new("substreams")
        .arg("info")
        .arg("--json")
        .arg(package_path)
        .output()
        .map_err(|error| format!("cannot run substreams info --json {display}: {error}"))?;
    if !output.status.success() {
        let code = output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "signal".to_string());
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stderr = stderr.trim();
        return Err(format!(
            "substreams info --json {display} exited with status {code}{}",
            if stderr.is_empty() {
                String::new()
            } else {
                format!(": {stderr}")
            }
        ));
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("substreams info --json {display} produced invalid JSON: {error}"))
}

/// Verify the parsed `substreams info --json` output of the evidence-only V3 package.
pub fn verify(package: &Value) -> Result<(), String> {
    check_identity(package, "name", EXPECTED_NAME)?;
    check_identity(package, "version", EXPECTED_VERSION)?;
    check_identity(package, "network", EXPECTED_NETWORK)?;

    let modules = match package.get("modules") {
        Some(Value::Array(modules)) => modules,
        _ => return Err("package modules are missing".to_string()),
    };
    if !modules.iter().all(Value::is_object) {
        return Err("package modules must be objects".to_string());
    }

    // `by_name` keeps the declaration order of the manifest so the drift report below
    // matches Python's insertion-ordered dict repr.
    let mut by_name: Vec<(&str, &Value)> = Vec::with_capacity(modules.len());
    for module in modules {
        match module.get("name").and_then(Value::as_str) {
            Some(name) => by_name.push((name, module)),
            None => return Err("every package module must have a string name".to_string()),
        }
    }

    let present: BTreeSet<&str> = by_name.iter().map(|(name, _)| *name).collect();
    if present.len() != by_name.len() {
        return Err("package contains duplicate module names".to_string());
    }

    let expected: BTreeSet<&str> = EXPECTED_MODULES.into_iter().collect();
    if present != expected {
        let missing: Vec<&str> = expected.difference(&present).copied().collect();
        let unexpected: Vec<&str> = present.difference(&expected).copied().collect();
        return Err(format!(
            "module set drift: missing={}, unexpected={}",
            py_repr_str_list(&missing),
            py_repr_str_list(&unexpected)
        ));
    }

    let wrong_starts: Vec<(&str, &Value)> = by_name
        .iter()
        .map(|(name, module)| (*name, module.get("initial_block").unwrap_or(&Value::Null)))
        .filter(|(_, initial_block)| !is_expected_initial_block(initial_block))
        .collect();
    if !wrong_starts.is_empty() {
        return Err(format!(
            "initial block drift: {}",
            py_repr_pairs(&wrong_starts)
        ));
    }

    let graph_out = by_name
        .iter()
        .find(|(name, _)| *name == "graph_out")
        .map(|(_, module)| *module)
        .expect("module set equality guarantees graph_out is present");
    let kind = graph_out.get("kind").unwrap_or(&Value::Null);
    if kind.as_str() != Some("map") {
        return Err(format!("graph_out kind is {}", py_repr(kind)));
    }
    let output_type = graph_out.get("output_type").unwrap_or(&Value::Null);
    if output_type.as_str() != Some(EXPECTED_GRAPH_OUT_TYPE) {
        return Err(format!("graph_out output is {}", py_repr(output_type)));
    }

    Ok(())
}

fn check_identity(package: &Value, field: &str, expected: &str) -> Result<(), String> {
    let value = package.get(field).unwrap_or(&Value::Null);
    if value.as_str() == Some(expected) {
        return Ok(());
    }
    Err(format!("unexpected package {field} {}", py_repr(value)))
}

/// Python compares `module.get("initial_block") != EXPECTED_INITIAL_BLOCK`, so a JSON float
/// that happens to equal the integer also passes; booleans never do.
fn is_expected_initial_block(value: &Value) -> bool {
    match value {
        Value::Number(number) => {
            number.as_i64() == Some(EXPECTED_INITIAL_BLOCK)
                || number.as_u64() == Some(EXPECTED_INITIAL_BLOCK as u64)
                || number.as_f64() == Some(EXPECTED_INITIAL_BLOCK as f64)
        }
        _ => false,
    }
}

/// `repr()` of a Python list of `str`.
fn py_repr_str_list(items: &[&str]) -> String {
    let body: Vec<String> = items.iter().map(|item| py_repr_str(item)).collect();
    format!("[{}]", body.join(", "))
}

/// `repr()` of a Python dict whose keys are `str`, in the given (insertion) order.
fn py_repr_pairs(pairs: &[(&str, &Value)]) -> String {
    let body: Vec<String> = pairs
        .iter()
        .map(|(key, value)| format!("{}: {}", py_repr_str(key), py_repr(value)))
        .collect();
    format!("{{{}}}", body.join(", "))
}

/// `repr()` of a JSON value as CPython would render the object `json.loads` builds from it.
fn py_repr(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Number(number) => py_repr_number(number),
        Value::String(text) => py_repr_str(text),
        Value::Array(items) => {
            let body: Vec<String> = items.iter().map(py_repr).collect();
            format!("[{}]", body.join(", "))
        }
        Value::Object(map) => {
            let body: Vec<String> = map
                .iter()
                .map(|(key, value)| format!("{}: {}", py_repr_str(key), py_repr(value)))
                .collect();
            format!("{{{}}}", body.join(", "))
        }
    }
}

fn py_repr_number(number: &serde_json::Number) -> String {
    if number.is_i64() || number.is_u64() {
        return number.to_string();
    }
    let float = number.as_f64().unwrap_or(f64::NAN);
    if float.is_finite() && float.fract() == 0.0 && float.abs() < 1e16 {
        // Python renders integral floats with a trailing `.0`.
        format!("{float:.1}")
    } else {
        format!("{float}")
    }
}

/// `repr()` of a Python `str`: single quotes unless the text contains `'` but no `"`.
fn py_repr_str(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(text.len() + 2);
    out.push(quote);
    for ch in text.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            ch if ch == quote => {
                out.push('\\');
                out.push(ch);
            }
            ch if (ch as u32) < 0x20 || ch as u32 == 0x7f => {
                out.push_str(&format!("\\x{:02x}", ch as u32));
            }
            ch => out.push(ch),
        }
    }
    out.push(quote);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Map};

    fn module(name: &str) -> Value {
        let mut entry = Map::new();
        entry.insert("name".into(), json!(name));
        entry.insert(
            "kind".into(),
            json!(if name == "graph_out" { "map" } else { "store" }),
        );
        entry.insert("initial_block".into(), json!(EXPECTED_INITIAL_BLOCK));
        if name == "graph_out" {
            entry.insert("output_type".into(), json!(EXPECTED_GRAPH_OUT_TYPE));
        }
        Value::Object(entry)
    }

    fn valid_package() -> Value {
        json!({
            "name": EXPECTED_NAME,
            "version": EXPECTED_VERSION,
            "network": EXPECTED_NETWORK,
            "modules": EXPECTED_MODULES.iter().map(|name| module(name)).collect::<Vec<_>>(),
        })
    }

    fn modules_mut(package: &mut Value) -> &mut Vec<Value> {
        package
            .get_mut("modules")
            .and_then(Value::as_array_mut)
            .expect("modules array")
    }

    fn find_mut<'a>(package: &'a mut Value, name: &str) -> &'a mut Value {
        modules_mut(package)
            .iter_mut()
            .find(|module| module.get("name").and_then(Value::as_str) == Some(name))
            .expect("module present")
    }

    fn error(package: &Value) -> String {
        verify(package).expect_err("expected verification to fail")
    }

    #[test]
    fn expected_modules_are_sorted_and_unique() {
        let mut sorted = EXPECTED_MODULES.to_vec();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted, EXPECTED_MODULES.to_vec());
    }

    #[test]
    fn exact_structure_passes() {
        assert_eq!(verify(&valid_package()), Ok(()));
    }

    #[test]
    fn success_line_matches_the_python_verifier() {
        assert_eq!(
            SUCCESS_LINE,
            "verified evidence-only Uniswap V3 package: uniswap_v3 v0.2.11, mainnet, 22 modules, graph_out EntityChanges, initial block 12369621"
        );
    }

    #[test]
    fn name_drift_is_rejected() {
        let mut package = valid_package();
        package["name"] = json!("uniswap_v4");
        assert_eq!(error(&package), "unexpected package name 'uniswap_v4'");
    }

    #[test]
    fn missing_name_is_rejected() {
        let mut package = valid_package();
        package.as_object_mut().expect("object").remove("name");
        assert_eq!(error(&package), "unexpected package name None");
    }

    #[test]
    fn version_drift_is_rejected() {
        let mut package = valid_package();
        package["version"] = json!("v0.2.12");
        assert_eq!(error(&package), "unexpected package version 'v0.2.12'");
    }

    #[test]
    fn missing_version_is_rejected() {
        let mut package = valid_package();
        package.as_object_mut().expect("object").remove("version");
        assert_eq!(error(&package), "unexpected package version None");
    }

    #[test]
    fn network_drift_is_rejected() {
        let mut package = valid_package();
        package["network"] = json!("polygon");
        assert_eq!(error(&package), "unexpected package network 'polygon'");
    }

    #[test]
    fn missing_network_is_rejected() {
        let mut package = valid_package();
        package.as_object_mut().expect("object").remove("network");
        assert_eq!(error(&package), "unexpected package network None");
    }

    #[test]
    fn missing_modules_is_rejected() {
        let mut package = valid_package();
        package.as_object_mut().expect("object").remove("modules");
        assert_eq!(error(&package), "package modules are missing");
    }

    #[test]
    fn non_list_modules_is_rejected() {
        let mut package = valid_package();
        package["modules"] = json!({});
        assert_eq!(error(&package), "package modules are missing");
    }

    #[test]
    fn non_object_modules_are_rejected() {
        let mut package = valid_package();
        package["modules"] = json!([{"name": "graph_out"}, "nope"]);
        assert_eq!(error(&package), "package modules must be objects");
    }

    #[test]
    fn module_without_a_name_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")
            .as_object_mut()
            .expect("object")
            .remove("name");
        assert_eq!(
            error(&package),
            "every package module must have a string name"
        );
    }

    #[test]
    fn module_with_a_non_string_name_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")["name"] = json!(7);
        assert_eq!(
            error(&package),
            "every package module must have a string name"
        );
    }

    #[test]
    fn duplicate_module_is_rejected() {
        let mut package = valid_package();
        let first = modules_mut(&mut package)[0].clone();
        modules_mut(&mut package).push(first);
        assert_eq!(error(&package), "package contains duplicate module names");
    }

    #[test]
    fn dropping_the_last_module_is_rejected() {
        let mut package = valid_package();
        modules_mut(&mut package).pop();
        assert_eq!(
            error(&package),
            "module set drift: missing=['store_total_tx_counts'], unexpected=[]"
        );
    }

    #[test]
    fn dropping_two_modules_reports_sorted_missing_names() {
        let mut package = valid_package();
        modules_mut(&mut package).drain(0..2);
        assert_eq!(
            error(&package),
            "module set drift: missing=['graph_out', 'map_extract_data_types'], unexpected=[]"
        );
    }

    #[test]
    fn renaming_a_module_reports_missing_and_unexpected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")["name"] = json!("extra_module");
        assert_eq!(
            error(&package),
            "module set drift: missing=['graph_out'], unexpected=['extra_module']"
        );
    }

    #[test]
    fn initial_block_drift_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")["initial_block"] = json!(EXPECTED_INITIAL_BLOCK + 1);
        assert_eq!(
            error(&package),
            "initial block drift: {'graph_out': 12369622}"
        );
    }

    #[test]
    fn initial_block_drift_reports_every_module_in_declaration_order() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")["initial_block"] = json!(EXPECTED_INITIAL_BLOCK + 1);
        find_mut(&mut package, "map_tokens_whitelist_pools")["initial_block"] = json!(0);
        assert_eq!(
            error(&package),
            "initial block drift: {'graph_out': 12369622, 'map_tokens_whitelist_pools': 0}"
        );
    }

    #[test]
    fn missing_initial_block_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")
            .as_object_mut()
            .expect("object")
            .remove("initial_block");
        assert_eq!(error(&package), "initial block drift: {'graph_out': None}");
    }

    #[test]
    fn graph_out_kind_drift_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")["kind"] = json!("store");
        assert_eq!(error(&package), "graph_out kind is 'store'");
    }

    #[test]
    fn missing_graph_out_kind_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")
            .as_object_mut()
            .expect("object")
            .remove("kind");
        assert_eq!(error(&package), "graph_out kind is None");
    }

    #[test]
    fn graph_out_output_type_drift_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")["output_type"] = json!("proto:example.Drift");
        assert_eq!(error(&package), "graph_out output is 'proto:example.Drift'");
    }

    #[test]
    fn missing_graph_out_output_type_is_rejected() {
        let mut package = valid_package();
        find_mut(&mut package, "graph_out")
            .as_object_mut()
            .expect("object")
            .remove("output_type");
        assert_eq!(error(&package), "graph_out output is None");
    }

    #[test]
    fn py_repr_matches_cpython_for_the_shapes_the_verifier_can_emit() {
        assert_eq!(py_repr(&Value::Null), "None");
        assert_eq!(py_repr(&json!(true)), "True");
        assert_eq!(py_repr(&json!(false)), "False");
        assert_eq!(py_repr(&json!(12_369_621_i64)), "12369621");
        assert_eq!(py_repr(&json!(-3)), "-3");
        assert_eq!(py_repr(&json!(1.0)), "1.0");
        assert_eq!(py_repr(&json!(1.5)), "1.5");
        assert_eq!(py_repr(&json!("plain")), "'plain'");
        assert_eq!(py_repr(&json!("it's")), "\"it's\"");
        assert_eq!(py_repr(&json!("it's a \"quote\"")), "'it\\'s a \"quote\"'");
        assert_eq!(
            py_repr(&json!("tab\tnew\nback\\")),
            "'tab\\tnew\\nback\\\\'"
        );
        assert_eq!(py_repr(&json!("\u{1}")), "'\\x01'");
        assert_eq!(py_repr(&json!([])), "[]");
        assert_eq!(py_repr(&json!(["a", "b"])), "['a', 'b']");
        assert_eq!(py_repr(&json!({})), "{}");
        assert_eq!(py_repr(&json!({"graph_out": null})), "{'graph_out': None}");
        assert_eq!(
            py_repr(&json!({"a": 1, "b": [2, "c"]})),
            "{'a': 1, 'b': [2, 'c']}"
        );
    }
}
