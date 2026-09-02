//! Fail-closed Graph Node catch-up eligibility calculations and validation.
//!
//! Rust port of `scripts/eligibility.py` (issue #110). The contract is the
//! versioned policy in `eligibility/policy-v1.yaml`, the per-deployment
//! binding files, and the evidence documents under `evidence/eligibility/`.
//! Every arithmetic step is integer or exact rational; the only decimal
//! rendering is the six-place, round-half-up quantization the Python tool
//! used, reproduced digit for digit.

use std::collections::BTreeSet;
use std::fmt;
use std::path::{Component, Path, PathBuf};

use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

pub const SECONDS_PER_DAY: i128 = 86_400;
pub const DERIVED_WINDOW_FIELDS: &[&str] = &[
    "duration_seconds",
    "deployment_delta",
    "chain_delta",
    "net_delta",
    "net_rate_blocks_per_day",
    "lag_blocks",
    "eta_days",
    "eta_kind",
];
const LEGACY_MARKET_FIELDS: &[&str] = &["market_qpd", "qos_snapshot_at", "signal_grt"];
const MARKET_AUTHORITY_PREFIX: &str =
    "https://github.com/pinax-network/substreams-backfills/issues/";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EligibilityError(pub String);

impl fmt::Display for EligibilityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for EligibilityError {}

pub type Result<T> = std::result::Result<T, EligibilityError>;

fn err<T>(message: impl Into<String>) -> Result<T> {
    Err(EligibilityError(message.into()))
}

fn mapping<'a>(value: Option<&'a Value>, name: &str) -> Result<&'a Map<String, Value>> {
    match value {
        Some(Value::Object(map)) => Ok(map),
        _ => err(format!("{name} must be an object")),
    }
}

fn list<'a>(value: Option<&'a Value>, name: &str) -> Result<&'a Vec<Value>> {
    match value {
        Some(Value::Array(items)) => Ok(items),
        _ => err(format!("{name} must be an array")),
    }
}

fn string<'a>(value: Option<&'a Value>, name: &str) -> Result<&'a str> {
    match value {
        Some(Value::String(text)) if !text.is_empty() => Ok(text),
        _ => err(format!("{name} must be a non-empty string")),
    }
}

fn integer(value: Option<&Value>, name: &str, minimum: Option<i128>) -> Result<i128> {
    let number = match value {
        Some(Value::Number(number)) => {
            if let Some(v) = number.as_i64() {
                v as i128
            } else if let Some(v) = number.as_u64() {
                v as i128
            } else {
                return err(format!("{name} must be an integer"));
            }
        }
        _ => return err(format!("{name} must be an integer")),
    };
    if let Some(min) = minimum {
        if number < min {
            return err(format!("{name} must be >= {min}"));
        }
    }
    Ok(number)
}

fn is_bool(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Bool(_)))
}

fn keys(map: &Map<String, Value>) -> BTreeSet<&str> {
    map.keys().map(String::as_str).collect()
}

fn key_set<'a>(names: &[&'a str]) -> BTreeSet<&'a str> {
    names.iter().copied().collect()
}

pub fn parse_utc(value: Option<&Value>, name: &str) -> Result<DateTime<Utc>> {
    let text = string(value, name)?;
    if !text.ends_with('Z') {
        return err(format!(
            "{name} must be an RFC3339 UTC timestamp ending in Z"
        ));
    }
    match DateTime::parse_from_rfc3339(text) {
        Ok(parsed) => Ok(parsed.with_timezone(&Utc)),
        Err(_) => err(format!("{name} is not a valid RFC3339 timestamp")),
    }
}

pub fn utc_text(value: &DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn yaml_to_json(value: serde_yaml::Value) -> Result<Value> {
    match value {
        serde_yaml::Value::Null => Ok(Value::Null),
        serde_yaml::Value::Bool(b) => Ok(Value::Bool(b)),
        serde_yaml::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(Value::from(i))
            } else if let Some(u) = n.as_u64() {
                Ok(Value::from(u))
            } else if let Some(f) = n.as_f64() {
                serde_json::Number::from_f64(f)
                    .map(Value::Number)
                    .ok_or_else(|| EligibilityError("non-finite YAML number".into()))
            } else {
                err("unsupported YAML number")
            }
        }
        serde_yaml::Value::String(s) => Ok(Value::String(s)),
        serde_yaml::Value::Sequence(items) => items
            .into_iter()
            .map(yaml_to_json)
            .collect::<Result<Vec<_>>>()
            .map(Value::Array),
        serde_yaml::Value::Mapping(map) => {
            let mut out = Map::new();
            for (k, v) in map {
                let key = match k {
                    serde_yaml::Value::String(s) => s,
                    other => {
                        return err(format!("YAML mapping key must be a string, got {other:?}"))
                    }
                };
                if out.insert(key.clone(), yaml_to_json(v)?).is_some() {
                    return err(format!("duplicate YAML key {key}"));
                }
            }
            Ok(Value::Object(out))
        }
        serde_yaml::Value::Tagged(tagged) => yaml_to_json(tagged.value),
    }
}

pub fn load_yaml(path: &Path) -> Result<Map<String, Value>> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| EligibilityError(format!("cannot read YAML {}: {e}", path.display())))?;
    let parsed: serde_yaml::Value = serde_yaml::from_str(&text)
        .map_err(|e| EligibilityError(format!("cannot read YAML {}: {e}", path.display())))?;
    match yaml_to_json(parsed)? {
        Value::Object(map) => Ok(map),
        _ => err(format!("{} must be an object", path.display())),
    }
}

pub fn load_json(path: &Path) -> Result<Map<String, Value>> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| EligibilityError(format!("cannot read JSON {}: {e}", path.display())))?;
    let parsed: Value = serde_json::from_str(&text)
        .map_err(|e| EligibilityError(format!("cannot read JSON {}: {e}", path.display())))?;
    match parsed {
        Value::Object(map) => Ok(map),
        _ => err(format!("{} must be an object", path.display())),
    }
}

pub type Policy = Map<String, Value>;

pub fn load_policy(path: &Path) -> Result<Policy> {
    let policy = load_yaml(path)?;
    validate_policy(&policy)?;
    Ok(policy)
}

pub fn validate_policy(policy: &Policy) -> Result<()> {
    let expected = key_set(&[
        "format_version",
        "id",
        "threshold_days",
        "windows",
        "sample_max_age_seconds",
        "freshness",
        "required_clusters",
        "healthy_copy",
        "decisions",
        "reasons",
        "structural_blockers",
    ]);
    if keys(policy) != expected {
        return err("policy contains missing or unknown fields");
    }
    if policy.get("format_version") != Some(&Value::from(1)) {
        return err("policy.format_version must be 1");
    }
    string(policy.get("id"), "policy.id")?;
    integer(
        policy.get("threshold_days"),
        "policy.threshold_days",
        Some(1),
    )?;
    let windows = mapping(policy.get("windows"), "policy.windows")?;
    if keys(windows) != key_set(&["24h", "72h"]) {
        return err("policy.windows must contain exactly 24h and 72h");
    }
    for (name, seconds) in windows {
        integer(Some(seconds), &format!("policy.windows.{name}"), Some(1))?;
    }
    integer(
        policy.get("sample_max_age_seconds"),
        "policy.sample_max_age_seconds",
        Some(0),
    )?;
    let freshness = mapping(policy.get("freshness"), "policy.freshness")?;
    if keys(freshness) != key_set(&["implementation-start", "compute-or-load-start"]) {
        return err("policy.freshness has unexpected purposes");
    }
    for (purpose, seconds) in freshness {
        integer(
            Some(seconds),
            &format!("policy.freshness.{purpose}"),
            Some(1),
        )?;
    }
    let clusters = list(policy.get("required_clusters"), "policy.required_clusters")?;
    if clusters.is_empty() {
        return err("policy.required_clusters must be non-empty and unique");
    }
    for (index, cluster) in clusters.iter().enumerate() {
        string(Some(cluster), &format!("policy.required_clusters[{index}]"))?;
    }
    if clusters
        .iter()
        .map(Value::to_string)
        .collect::<BTreeSet<_>>()
        .len()
        != clusters.len()
    {
        return err("policy.required_clusters must be non-empty and unique");
    }
    let healthy = mapping(policy.get("healthy_copy"), "policy.healthy_copy")?;
    if keys(healthy) != key_set(&["health", "status"]) {
        return err("policy.healthy_copy contains missing or unknown fields");
    }
    string(healthy.get("health"), "policy.healthy_copy.health")?;
    string(healthy.get("status"), "policy.healthy_copy.status")?;
    for field in ["decisions", "reasons", "structural_blockers"] {
        let values = list(policy.get(field), &format!("policy.{field}"))?;
        if values.is_empty() {
            return err(format!("policy.{field} must be non-empty and unique"));
        }
        for (index, value) in values.iter().enumerate() {
            string(Some(value), &format!("policy.{field}[{index}]"))?;
        }
        if values
            .iter()
            .map(Value::to_string)
            .collect::<BTreeSet<_>>()
            .len()
            != values.len()
        {
            return err(format!("policy.{field} must be non-empty and unique"));
        }
    }
    Ok(())
}

fn policy_str<'a>(policy: &'a Policy, key: &str) -> &'a str {
    policy.get(key).and_then(Value::as_str).unwrap_or_default()
}

fn policy_int(policy: &Policy, key: &str) -> i128 {
    policy.get(key).and_then(Value::as_i64).unwrap_or_default() as i128
}

fn policy_list<'a>(policy: &'a Policy, key: &str) -> Vec<&'a str> {
    policy
        .get(key)
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default()
}

pub fn sha256_file(path: &Path) -> Result<String> {
    let bytes = std::fs::read(path)
        .map_err(|e| EligibilityError(format!("cannot read {}: {e}", path.display())))?;
    Ok(hex::encode(Sha256::digest(&bytes)))
}

/// `json.dumps(value, indent=2, sort_keys=True) + "\n"`; serde_json maps are
/// sorted, and pretty printing uses the same two-space layout.
pub fn canonical_json(value: &Map<String, Value>) -> Vec<u8> {
    let mut out = serde_json::to_vec_pretty(value).expect("JSON value serializes");
    out.push(b'\n');
    out
}

fn is_fixed_point_decimal(text: &str) -> bool {
    let (int_part, frac_part) = match text.split_once('.') {
        Some((i, f)) => (i, Some(f)),
        None => (text, None),
    };
    let int_ok = int_part == "0"
        || (!int_part.is_empty()
            && !int_part.starts_with('0')
            && int_part.bytes().all(|b| b.is_ascii_digit()));
    let frac_ok = frac_part.is_none_or(|f| !f.is_empty() && f.bytes().all(|b| b.is_ascii_digit()));
    int_ok && frac_ok
}

fn is_issue_authority(text: &str) -> bool {
    match text.strip_prefix(MARKET_AUTHORITY_PREFIX) {
        Some(rest) => {
            !rest.is_empty() && !rest.starts_with('0') && rest.bytes().all(|b| b.is_ascii_digit())
        }
        None => false,
    }
}

pub fn validate_market_metadata(binding: &Map<String, Value>) -> Result<()> {
    let mut ambiguous: Vec<&str> = binding
        .keys()
        .map(String::as_str)
        .filter(|field| {
            *field != "market_snapshot"
                && (LEGACY_MARKET_FIELDS.contains(field)
                    || field.starts_with("market_")
                    || field.starts_with("qos_")
                    || field.starts_with("query_fee")
                    || field.contains("grt")
                    || matches!(*field, "queries_24h" | "query_count_24h" | "fees_24h"))
        })
        .collect();
    ambiguous.sort_unstable();
    if !ambiguous.is_empty() {
        return err(format!(
            "binding contains ambiguous top-level market fields: {}",
            ambiguous.join(", ")
        ));
    }
    let Some(snapshot_value) = binding.get("market_snapshot") else {
        return Ok(());
    };
    let snapshot = mapping(Some(snapshot_value), "binding.market_snapshot")?;
    if keys(snapshot)
        != key_set(&[
            "measured_at",
            "queries_24h",
            "query_fees_grt_24h",
            "authority",
        ])
    {
        return err("binding.market_snapshot contains missing or unknown fields");
    }
    let measured_at = parse_utc(
        snapshot.get("measured_at"),
        "binding.market_snapshot.measured_at",
    )?;
    if Some(utc_text(&measured_at).as_str()) != snapshot.get("measured_at").and_then(Value::as_str)
    {
        return err("binding.market_snapshot.measured_at must use canonical second-precision UTC");
    }
    integer(
        snapshot.get("queries_24h"),
        "binding.market_snapshot.queries_24h",
        Some(0),
    )?;
    let fees = string(
        snapshot.get("query_fees_grt_24h"),
        "binding.market_snapshot.query_fees_grt_24h",
    )?;
    if !is_fixed_point_decimal(fees) {
        return err("binding.market_snapshot.query_fees_grt_24h must be a non-negative fixed-point decimal string");
    }
    let authority = string(
        snapshot.get("authority"),
        "binding.market_snapshot.authority",
    )?;
    if !is_issue_authority(authority) {
        return err("binding.market_snapshot.authority must name a repository issue");
    }
    Ok(())
}

fn is_hex_digest(text: &str, len: usize) -> bool {
    text.len() == len
        && text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

pub fn validate_binding(
    binding: &Map<String, Value>,
    policy: &Policy,
    binding_path: Option<&Path>,
) -> Result<()> {
    for field in ["deployment", "family", "chain"] {
        string(binding.get(field), &format!("binding.{field}"))?;
    }
    let deployment = string(binding.get("deployment"), "binding.deployment")?;
    if let Some(path) = binding_path {
        let file_name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or_default();
        if !file_name.contains(deployment) {
            return err(format!(
                "{}: deployment does not match filename",
                path.display()
            ));
        }
    }
    validate_market_metadata(binding)?;

    let eligibility = mapping(binding.get("eligibility"), "binding.eligibility")?;
    if keys(eligibility) != key_set(&["policy", "required_clusters", "latest"]) {
        return err("binding.eligibility contains missing or unknown fields");
    }
    if eligibility.get("policy").and_then(Value::as_str) != Some(policy_str(policy, "id")) {
        return err("binding eligibility policy does not match policy file");
    }
    let clusters = list(
        eligibility.get("required_clusters"),
        "binding.eligibility.required_clusters",
    )?;
    let mut names = Vec::new();
    for (index, cluster) in clusters.iter().enumerate() {
        names.push(string(
            Some(cluster),
            &format!("binding.eligibility.required_clusters[{index}]"),
        )?);
    }
    let unique: BTreeSet<&str> = names.iter().copied().collect();
    if unique.len() != names.len() {
        return err("binding required_clusters contains duplicates");
    }
    let policy_clusters: BTreeSet<&str> = policy_list(policy, "required_clusters")
        .into_iter()
        .collect();
    if unique != policy_clusters {
        return err("binding required_clusters must cover every policy cluster");
    }

    let latest = mapping(eligibility.get("latest"), "binding.eligibility.latest")?;
    if keys(latest) != key_set(&["decision", "reason", "measured_at", "evidence", "sha256"]) {
        return err("binding eligibility latest contains missing or unknown fields");
    }
    let decision = latest.get("decision").and_then(Value::as_str);
    let reason = latest.get("reason").and_then(Value::as_str);
    if !decision.is_some_and(|d| policy_list(policy, "decisions").contains(&d)) {
        return err("binding latest decision is not allowed by policy");
    }
    if !reason.is_some_and(|r| policy_list(policy, "reasons").contains(&r)) {
        return err("binding latest reason is not allowed by policy");
    }
    let pointer = ["measured_at", "evidence", "sha256"];
    let nulls = pointer
        .iter()
        .filter(|f| matches!(latest.get(**f), None | Some(Value::Null)))
        .count();
    if nulls == pointer.len() {
        if decision != Some("indeterminate") || reason != Some("no_fresh_evidence") {
            return err("an empty evidence pointer must be indeterminate/no_fresh_evidence");
        }
        return Ok(());
    }
    if nulls > 0 {
        return err("measured_at, evidence, and sha256 must all be set together");
    }
    let measured_at = parse_utc(
        latest.get("measured_at"),
        "binding.eligibility.latest.measured_at",
    )?;
    let evidence_path = string(
        latest.get("evidence"),
        "binding.eligibility.latest.evidence",
    )?;
    let parts: Vec<&str> = evidence_path.split('/').collect();
    if parts.len() != 4
        || parts[0] != "evidence"
        || parts[1] != "eligibility"
        || parts[2] != deployment
        || !parts[3].ends_with(".json")
        || parts.contains(&"..")
    {
        return err("binding evidence path must stay under evidence/eligibility");
    }
    let expected_name = measured_at.format("%Y%m%dT%H%M%SZ.json").to_string();
    if parts[3] != expected_name {
        return err("binding evidence filename must match measured_at");
    }
    let digest = string(latest.get("sha256"), "binding.eligibility.latest.sha256")?;
    if !is_hex_digest(digest, 64) {
        return err("binding evidence sha256 must be 64 lowercase hexadecimal characters");
    }
    Ok(())
}

fn seconds_between(later: &DateTime<Utc>, earlier: &DateTime<Utc>) -> Result<i128> {
    let delta = *later - *earlier;
    let millis = delta.num_milliseconds();
    if millis % 1000 != 0 {
        return err("duration must be an exact number of seconds");
    }
    Ok((millis / 1000) as i128)
}

fn abs_seconds(a: &DateTime<Utc>, b: &DateTime<Utc>) -> f64 {
    (*a - *b).num_milliseconds().abs() as f64 / 1000.0
}

/// Render `numerator / denominator` with exactly six decimals, rounding half
/// away from zero, matching `Decimal.quantize(Decimal("0.000001"), ROUND_HALF_UP)`
/// followed by `format(value, "f")`.
pub fn quantize6(numerator: i128, denominator: i128) -> String {
    assert!(denominator != 0, "quantize6 denominator must be nonzero");
    let negative = (numerator < 0) != (denominator < 0) && numerator != 0;
    let num = numerator.unsigned_abs();
    let den = denominator.unsigned_abs();
    let scaled = num * 1_000_000;
    let mut q = scaled / den;
    let r = scaled % den;
    if r * 2 >= den {
        q += 1;
    }
    let int_part = q / 1_000_000;
    let frac_part = q % 1_000_000;
    format!(
        "{}{int_part}.{frac_part:06}",
        if negative { "-" } else { "" }
    )
}

fn take_i128(map: &Map<String, Value>, key: &str) -> i128 {
    map.get(key).and_then(Value::as_i64).unwrap_or_default() as i128
}

/// Recompute one window's derived fields from its raw `start`/`end` points.
/// Returns the calculated window and the sorted, deduplicated condition list.
pub fn calculate_window(
    window: &Map<String, Value>,
    policy: &Policy,
    name: &str,
) -> Result<(Map<String, Value>, Vec<String>)> {
    let raw: Map<String, Value> = window
        .iter()
        .filter(|(k, _)| !DERIVED_WINDOW_FIELDS.contains(&k.as_str()))
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    if keys(&raw) != key_set(&["start", "end"]) {
        return err(format!(
            "{name} must contain start/end plus calculated fields"
        ));
    }
    let start = mapping(raw.get("start"), &format!("{name}.start"))?;
    let end = mapping(raw.get("end"), &format!("{name}.end"))?;
    let point_fields = key_set(&[
        "requested_at",
        "deployment_observed_at",
        "deployment_head",
        "chain_observed_at",
        "chain_head",
    ]);
    if keys(start) != point_fields || keys(end) != point_fields {
        return err(format!(
            "{name} start/end contain missing or unknown fields"
        ));
    }
    let start_requested = parse_utc(
        start.get("requested_at"),
        &format!("{name}.start.requested_at"),
    )?;
    let end_requested = parse_utc(end.get("requested_at"), &format!("{name}.end.requested_at"))?;
    let duration = seconds_between(&end_requested, &start_requested).map_err(|_| {
        EligibilityError(format!(
            "{name} duration must be an exact number of seconds"
        ))
    })?;
    let window_key = name.rsplit('.').next().unwrap_or(name);
    let expected_duration = integer(
        policy.get("windows").and_then(|w| w.get(window_key)),
        &format!("policy window for {name}"),
        None,
    )?;
    if duration != expected_duration {
        return err(format!(
            "{name} duration is {duration}, expected {expected_duration}"
        ));
    }

    let mut conditions: Vec<String> = Vec::new();
    let max_age = policy_int(policy, "sample_max_age_seconds") as f64;
    for (label, point) in [("start", start), ("end", end)] {
        for kind in ["deployment", "chain"] {
            let observed = parse_utc(
                point.get(&format!("{kind}_observed_at")),
                &format!("{name}.{label}.{kind}.observed_at"),
            )?;
            let requested = parse_utc(
                point.get("requested_at"),
                &format!("{name}.{label}.{kind}.requested_at"),
            )?;
            if abs_seconds(&observed, &requested) > max_age {
                conditions.push("stale_or_incomplete_samples".into());
            }
        }
        integer(
            point.get("deployment_head"),
            &format!("{name}.{label}.deployment_head"),
            Some(0),
        )?;
        integer(
            point.get("chain_head"),
            &format!("{name}.{label}.chain_head"),
            Some(0),
        )?;
    }

    let deployment_delta = take_i128(end, "deployment_head") - take_i128(start, "deployment_head");
    let chain_delta = take_i128(end, "chain_head") - take_i128(start, "chain_head");
    if deployment_delta < 0 || chain_delta < 0 {
        conditions.push("head_regression".into());
    }
    let net_delta = deployment_delta - chain_delta;
    let lag = (take_i128(end, "chain_head") - take_i128(end, "deployment_head")).max(0);
    let rate = quantize6(net_delta * SECONDS_PER_DAY, duration);
    let (eta_days, eta_kind) = if net_delta <= 0 {
        (Value::Null, "infinite")
    } else {
        (
            Value::String(quantize6(lag * duration, net_delta * SECONDS_PER_DAY)),
            "finite",
        )
    };

    let mut calculated = raw;
    calculated.insert("duration_seconds".into(), Value::from(duration as i64));
    calculated.insert(
        "deployment_delta".into(),
        Value::from(deployment_delta as i64),
    );
    calculated.insert("chain_delta".into(), Value::from(chain_delta as i64));
    calculated.insert("net_delta".into(), Value::from(net_delta as i64));
    calculated.insert("net_rate_blocks_per_day".into(), Value::String(rate));
    calculated.insert("lag_blocks".into(), Value::from(lag as i64));
    calculated.insert("eta_days".into(), eta_days);
    calculated.insert("eta_kind".into(), Value::String(eta_kind.into()));
    conditions.sort();
    conditions.dedup();
    Ok((calculated, conditions))
}

fn healthy_copy(current: &Map<String, Value>, policy: &Policy) -> bool {
    let healthy = policy.get("healthy_copy").and_then(Value::as_object);
    current.get("active") == Some(&Value::Bool(true))
        && current.get("attached") == Some(&Value::Bool(true))
        && current.get("failed") == Some(&Value::Bool(false))
        && current.get("health").and_then(Value::as_str)
            == healthy
                .and_then(|h| h.get("health"))
                .and_then(Value::as_str)
        && current.get("status").and_then(Value::as_str)
            == healthy
                .and_then(|h| h.get("status"))
                .and_then(Value::as_str)
}

fn eta_exceeds_threshold(window: &Map<String, Value>, threshold_days: i128) -> bool {
    let net_delta = take_i128(window, "net_delta");
    if net_delta <= 0 {
        return true;
    }
    take_i128(window, "lag_blocks") * take_i128(window, "duration_seconds")
        > threshold_days * net_delta * SECONDS_PER_DAY
}

/// Parse a six-decimal string produced by `quantize6` into micro-units.
fn micros(text: &str) -> i128 {
    let (negative, body) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text),
    };
    let (int_part, frac_part) = body.split_once('.').unwrap_or((body, "0"));
    let mut frac = frac_part.to_string();
    while frac.len() < 6 {
        frac.push('0');
    }
    let value = int_part.parse::<i128>().unwrap_or_default() * 1_000_000
        + frac[..6].parse::<i128>().unwrap_or_default();
    if negative {
        -value
    } else {
        value
    }
}

fn fastest(candidates: &[(String, Map<String, Value>)]) -> Value {
    let best = candidates.iter().min_by(|(a_id, a), (b_id, b)| {
        let key = |id: &str, w: &Map<String, Value>| -> (u8, i128, String) {
            if w.get("eta_kind").and_then(Value::as_str) == Some("infinite") {
                (1, 0, id.to_string())
            } else {
                (
                    0,
                    micros(w.get("eta_days").and_then(Value::as_str).unwrap_or("0")),
                    id.to_string(),
                )
            }
        };
        key(a_id, a).cmp(&key(b_id, b))
    });
    match best {
        None => Value::Null,
        Some((copy_id, window)) => {
            let mut out = Map::new();
            out.insert("copy_id".into(), Value::String(copy_id.clone()));
            out.insert(
                "eta_days".into(),
                window.get("eta_days").cloned().unwrap_or(Value::Null),
            );
            out.insert(
                "eta_kind".into(),
                window.get("eta_kind").cloned().unwrap_or(Value::Null),
            );
            Value::Object(out)
        }
    }
}

pub fn build_evidence(
    measurements: &Map<String, Value>,
    binding: &Map<String, Value>,
    policy: &Policy,
) -> Result<Map<String, Value>> {
    if keys(measurements) != key_set(&["measured_at", "collector", "sources", "clusters"]) {
        return err("measurements contains missing or unknown top-level fields");
    }
    let measured_at = parse_utc(measurements.get("measured_at"), "measurements.measured_at")?;
    let collector_value = measurements.get("collector").cloned().unwrap_or_else(|| {
        let mut m = Map::new();
        m.insert("version".into(), Value::from(1));
        m.insert("repository_commit".into(), Value::Null);
        Value::Object(m)
    });
    let sources_value =
        Value::Object(mapping(measurements.get("sources"), "measurements.sources")?.clone());
    let clusters_value =
        Value::Array(list(measurements.get("clusters"), "measurements.clusters")?.clone());

    let mut evidence = Map::new();
    evidence.insert("format_version".into(), Value::from(1));
    evidence.insert(
        "policy".into(),
        Value::String(policy_str(policy, "id").into()),
    );
    for field in ["deployment", "family", "chain"] {
        evidence.insert(
            field.into(),
            binding.get(field).cloned().unwrap_or(Value::Null),
        );
    }
    evidence.insert("measured_at".into(), Value::String(utc_text(&measured_at)));
    evidence.insert("collector".into(), collector_value);
    evidence.insert("sources".into(), sources_value);
    evidence.insert("clusters".into(), clusters_value);

    let collector = mapping(evidence.get("collector"), "measurements.collector")?;
    if keys(collector) != key_set(&["version", "repository_commit"])
        || collector.get("version") != Some(&Value::from(1))
    {
        return err("collector must contain version=1 and repository_commit");
    }
    let commit = string(
        collector.get("repository_commit"),
        "collector.repository_commit",
    )?;
    if !is_hex_digest(commit, 40) {
        return err("collector.repository_commit must be a 40-character lowercase Git commit");
    }
    let sources = mapping(evidence.get("sources"), "measurements.sources")?;
    if keys(sources) != key_set(&["status_api", "victoriametrics", "postgres_inventory"]) {
        return err("sources must contain status_api, victoriametrics, and postgres_inventory");
    }
    let status_sources = list(sources.get("status_api"), "sources.status_api")?;
    if status_sources.is_empty() {
        return err("sources.status_api must retain at least one read-only source record");
    }
    let metrics_sources = mapping(sources.get("victoriametrics"), "sources.victoriametrics")?;
    let metric_queries = list(
        metrics_sources.get("queries"),
        "sources.victoriametrics.queries",
    )?
    .clone();
    let postgres_sources = list(
        sources.get("postgres_inventory"),
        "sources.postgres_inventory",
    )?
    .clone();

    let required_clusters: Vec<String> = binding
        .get("eligibility")
        .and_then(|e| e.get("required_clusters"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    let allowed_blockers: BTreeSet<&str> = policy_list(policy, "structural_blockers")
        .into_iter()
        .collect();
    let max_age = policy_int(policy, "sample_max_age_seconds") as f64;

    let mut cluster_names: Vec<String> = Vec::new();
    let mut candidate_24h: Vec<(String, Map<String, Value>)> = Vec::new();
    let mut candidate_72h: Vec<(String, Map<String, Value>)> = Vec::new();
    let mut conditions: Vec<&str> = Vec::new();
    let mut healthy_seen = false;
    let mut synced_seen = false;
    let mut structural_proof: Map<String, Value> = Map::new();
    let mut blocker_types: Vec<String> = Vec::new();
    let mut copy_ids: BTreeSet<String> = BTreeSet::new();

    let mut clusters = match evidence.remove("clusters") {
        Some(Value::Array(items)) => items,
        _ => unreachable!("clusters inserted above"),
    };
    for (cluster_index, cluster_value) in clusters.iter_mut().enumerate() {
        let cluster = match cluster_value {
            Value::Object(map) => map,
            _ => return err(format!("clusters[{cluster_index}] must be an object")),
        };
        if keys(cluster) != key_set(&["cluster", "accounted", "copies", "structural_blockers"]) {
            return err(format!(
                "clusters[{cluster_index}] contains missing or unknown fields"
            ));
        }
        let cluster_name = string(
            cluster.get("cluster"),
            &format!("clusters[{cluster_index}].cluster"),
        )?
        .to_string();
        cluster_names.push(cluster_name.clone());
        if !is_bool(cluster.get("accounted")) {
            return err(format!(
                "clusters[{cluster_index}].accounted must be boolean"
            ));
        }
        if cluster.get("accounted") != Some(&Value::Bool(true)) {
            conditions.push("missing_required_cluster");
        }
        let blockers = list(
            cluster.get("structural_blockers"),
            &format!("clusters[{cluster_index}].structural_blockers"),
        )?
        .clone();
        let mut structural = false;
        let mut cluster_blocker_types: Vec<String> = Vec::new();
        for (blocker_index, blocker_value) in blockers.iter().enumerate() {
            let blocker = mapping(
                Some(blocker_value),
                &format!("clusters[{cluster_index}].structural_blockers[{blocker_index}]"),
            )?;
            if keys(blocker) != key_set(&["type", "observed_at", "source", "details"]) {
                return err("structural blocker contains missing or unknown fields");
            }
            let blocker_type = blocker
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or_default();
            if !allowed_blockers.contains(blocker_type) {
                return err(format!(
                    "unsupported structural blocker {:?}",
                    blocker.get("type").and_then(Value::as_str).unwrap_or("")
                ));
            }
            let blocker_at =
                parse_utc(blocker.get("observed_at"), "structural blocker observed_at")?;
            if abs_seconds(&blocker_at, &measured_at) > max_age {
                conditions.push("stale_or_incomplete_samples");
            }
            string(blocker.get("source"), "structural blocker source")?;
            string(blocker.get("details"), "structural blocker details")?;
            structural = true;
            blocker_types.push(blocker_type.to_string());
            cluster_blocker_types.push(blocker_type.to_string());
        }
        structural_proof.insert(cluster_name.clone(), Value::Bool(structural));

        let mut cluster_has_healthy = false;
        let mut cluster_has_attached = false;
        let copies = match cluster.get_mut("copies") {
            Some(Value::Array(items)) => items,
            _ => return err(format!("clusters[{cluster_index}].copies must be an array")),
        };
        for (copy_index, copy_value) in copies.iter_mut().enumerate() {
            let copy_item = match copy_value {
                Value::Object(map) => map,
                _ => {
                    return err(format!(
                        "clusters[{cluster_index}].copies[{copy_index}] must be an object"
                    ))
                }
            };
            if keys(copy_item) != key_set(&["copy_id", "selector", "current", "windows"]) {
                return err("copy contains missing or unknown fields");
            }
            let copy_id = string(copy_item.get("copy_id"), "copy.copy_id")?.to_string();
            if !copy_ids.insert(copy_id.clone()) {
                return err(format!("duplicate copy_id {copy_id}"));
            }
            let selector = mapping(
                copy_item.get("selector"),
                &format!("copy {copy_id}.selector"),
            )?;
            if selector.is_empty() || selector.values().any(|v| !v.is_string()) {
                return err(format!(
                    "copy {copy_id} selector must contain string labels"
                ));
            }
            let current =
                mapping(copy_item.get("current"), &format!("copy {copy_id}.current"))?.clone();
            let required_current = key_set(&[
                "observed_at",
                "active",
                "attached",
                "health",
                "status",
                "failed",
                "synced",
            ]);
            let optional_current = key_set(&["deployment_head", "chain_head"]);
            let current_keys = keys(&current);
            if !required_current.is_subset(&current_keys)
                || !current_keys
                    .is_subset(&required_current.union(&optional_current).copied().collect())
            {
                return err(format!(
                    "copy {copy_id} current contains missing or unknown fields"
                ));
            }
            let current_at = parse_utc(
                current.get("observed_at"),
                &format!("copy {copy_id}.current.observed_at"),
            )?;
            for boolean_field in ["active", "attached", "failed", "synced"] {
                if !is_bool(current.get(boolean_field)) {
                    return err(format!(
                        "copy {copy_id}.current.{boolean_field} must be boolean"
                    ));
                }
            }
            string(
                current.get("health"),
                &format!("copy {copy_id}.current.health"),
            )?;
            string(
                current.get("status"),
                &format!("copy {copy_id}.current.status"),
            )?;
            cluster_has_attached =
                cluster_has_attached || current.get("attached") == Some(&Value::Bool(true));
            for head_field in ["deployment_head", "chain_head"] {
                if let Some(value) = current.get(head_field) {
                    if !value.is_null() {
                        integer(
                            Some(value),
                            &format!("copy {copy_id}.current.{head_field}"),
                            Some(0),
                        )?;
                    }
                }
            }
            if !healthy_copy(&current, policy) {
                continue;
            }
            if abs_seconds(&current_at, &measured_at) > max_age {
                conditions.push("stale_or_incomplete_samples");
                continue;
            }
            healthy_seen = true;
            cluster_has_healthy = true;
            if current.get("synced") == Some(&Value::Bool(true)) {
                synced_seen = true;
                continue;
            }
            let windows = match copy_item.get_mut("windows") {
                Some(Value::Object(map)) => map,
                _ => return err(format!("copy {copy_id}.windows must be an object")),
            };
            for window_name in ["24h", "72h"] {
                let Some(window_value) = windows.get(window_name) else {
                    conditions.push("stale_or_incomplete_samples");
                    continue;
                };
                let window = mapping(
                    Some(window_value),
                    &format!("copy {copy_id}.windows.{window_name}"),
                )?
                .clone();
                let (calculated, window_conditions) = calculate_window(
                    &window,
                    policy,
                    &format!("copy {copy_id}.windows.{window_name}"),
                )?;
                for condition in window_conditions {
                    conditions.push(match condition.as_str() {
                        "stale_or_incomplete_samples" => "stale_or_incomplete_samples",
                        "head_regression" => "head_regression",
                        other => return err(format!("unexpected window condition {other}")),
                    });
                }
                let requested_end = parse_utc(
                    calculated.get("end").and_then(|e| e.get("requested_at")),
                    "window end requested_at",
                )?;
                if requested_end != measured_at {
                    conditions.push("stale_or_incomplete_samples");
                }
                windows.insert(window_name.into(), Value::Object(calculated.clone()));
                if window_name == "24h" {
                    candidate_24h.push((copy_id.clone(), calculated));
                } else {
                    candidate_72h.push((copy_id.clone(), calculated));
                }
            }
            if windows.keys().any(|k| k != "24h" && k != "72h") {
                return err(format!("copy {copy_id}.windows contains unknown windows"));
            }
        }
        if cluster_has_healthy {
            if structural {
                conditions.push("conflicting_identity");
            }
        } else if cluster_has_attached
            && cluster_blocker_types
                .iter()
                .any(|t| t == "missing_attached_version")
        {
            conditions.push("conflicting_identity");
        }
    }
    evidence.insert("clusters".into(), Value::Array(clusters));

    let unique_clusters: BTreeSet<&String> = cluster_names.iter().collect();
    if unique_clusters.len() != cluster_names.len() {
        return err("evidence contains duplicate cluster entries");
    }
    let required_set: BTreeSet<&String> = required_clusters.iter().collect();
    if unique_clusters != required_set {
        conditions.push("missing_required_cluster");
    }
    if !healthy_seen
        && required_clusters
            .iter()
            .any(|name| structural_proof.get(name) != Some(&Value::Bool(true)))
    {
        conditions.push("no_healthy_copy");
    }
    if healthy_seen && metric_queries.is_empty() {
        return err("healthy-copy evidence must retain VictoriaMetrics queries");
    }
    if !blocker_types.is_empty() && postgres_sources.is_empty() {
        return err("structural blocker evidence must retain read-only Postgres inventory");
    }

    let fastest_24h = fastest(&candidate_24h);
    let fastest_72h = fastest(&candidate_72h);
    let condition_set: BTreeSet<&str> = conditions.iter().copied().collect();
    let threshold_days = policy_int(policy, "threshold_days");
    let (decision, reason): (&str, &str) = if condition_set.contains("missing_required_cluster") {
        ("indeterminate", "missing_required_cluster")
    } else if condition_set.contains("conflicting_identity") {
        ("indeterminate", "conflicting_identity")
    } else if synced_seen {
        ("complete", "native_sync_complete")
    } else if condition_set.contains("head_regression") {
        ("indeterminate", "head_regression")
    } else if condition_set.contains("stale_or_incomplete_samples") {
        ("indeterminate", "stale_or_incomplete_samples")
    } else if condition_set.contains("no_healthy_copy") {
        ("indeterminate", "no_healthy_copy")
    } else if healthy_seen {
        let all_windows: Vec<&Map<String, Value>> = candidate_24h
            .iter()
            .chain(candidate_72h.iter())
            .map(|(_, w)| w)
            .collect();
        if candidate_24h.is_empty() || candidate_72h.is_empty() {
            ("indeterminate", "stale_or_incomplete_samples")
        } else if all_windows
            .iter()
            .any(|w| !eta_exceeds_threshold(w, threshold_days))
        {
            ("monitor", "fastest_window_at_or_below_threshold")
        } else if all_windows.iter().all(|w| take_i128(w, "net_delta") <= 0) {
            ("eligible", "non_positive_net_rate")
        } else {
            ("eligible", "both_windows_exceed_threshold")
        }
    } else if !blocker_types.is_empty() {
        if blocker_types.iter().any(|t| t == "missing_graft_base") {
            ("eligible", "missing_graft_base")
        } else {
            ("eligible", "missing_attached_version")
        }
    } else {
        ("indeterminate", "no_healthy_copy")
    };

    let mut summary = Map::new();
    summary.insert("decision".into(), Value::String(decision.into()));
    summary.insert("reason".into(), Value::String(reason.into()));
    summary.insert("threshold_days".into(), Value::from(threshold_days as i64));
    summary.insert("fastest_24h".into(), fastest_24h);
    summary.insert("fastest_72h".into(), fastest_72h);
    evidence.insert("summary".into(), Value::Object(summary));
    Ok(evidence)
}

pub fn validate_evidence(
    evidence: &Map<String, Value>,
    binding: &Map<String, Value>,
    policy: &Policy,
) -> Result<()> {
    let expected = key_set(&[
        "format_version",
        "policy",
        "deployment",
        "family",
        "chain",
        "measured_at",
        "collector",
        "sources",
        "clusters",
        "summary",
    ]);
    if keys(evidence) != expected {
        return err("evidence contains missing or unknown top-level fields");
    }
    if evidence.get("format_version") != Some(&Value::from(1))
        || evidence.get("policy").and_then(Value::as_str) != Some(policy_str(policy, "id"))
    {
        return err("evidence format or policy does not match");
    }
    for field in ["deployment", "family", "chain"] {
        if evidence.get(field) != binding.get(field) {
            return err(format!("evidence {field} does not match binding"));
        }
    }
    let mut raw = evidence.clone();
    let recorded_summary = raw.remove("summary");
    let clusters = match raw.get_mut("clusters") {
        Some(Value::Array(items)) => items,
        _ => return err("evidence.clusters must be an array"),
    };
    for cluster in clusters.iter_mut() {
        let copies = match cluster.as_object_mut().and_then(|c| c.get_mut("copies")) {
            Some(Value::Array(items)) => items,
            _ => return err("cluster.copies must be an array"),
        };
        for copy_item in copies.iter_mut() {
            let windows = match copy_item.as_object_mut().and_then(|c| c.get_mut("windows")) {
                Some(Value::Object(map)) => map,
                _ => return err("copy.windows must be an object"),
            };
            for window in windows.values_mut() {
                let Some(window) = window.as_object_mut() else {
                    return err("window must be an object");
                };
                for field in DERIVED_WINDOW_FIELDS {
                    window.remove(*field);
                }
            }
        }
    }
    let mut measurements = Map::new();
    for field in ["measured_at", "collector", "sources", "clusters"] {
        measurements.insert(field.into(), raw.get(field).cloned().unwrap_or(Value::Null));
    }
    let rebuilt = build_evidence(&measurements, binding, policy)?;
    if rebuilt.get("summary") != recorded_summary.as_ref() {
        return err("evidence summary does not match recomputed decision");
    }
    if &rebuilt != evidence {
        return err("evidence calculated fields do not match raw samples");
    }
    Ok(())
}

pub fn resolve_evidence_path(repository_root: &Path, relative: &str) -> Result<PathBuf> {
    let rel = Path::new(relative);
    if rel.is_absolute() || rel.components().any(|c| !matches!(c, Component::Normal(_))) {
        return err("evidence path escapes evidence/eligibility");
    }
    let mut components = rel.components();
    let under = components.next().and_then(|c| c.as_os_str().to_str()) == Some("evidence")
        && components.next().and_then(|c| c.as_os_str().to_str()) == Some("eligibility");
    if !under {
        return err("evidence path escapes evidence/eligibility");
    }
    Ok(repository_root.join(rel))
}

pub fn validate_binding_evidence(
    binding: &Map<String, Value>,
    policy: &Policy,
    repository_root: &Path,
) -> Result<Option<Map<String, Value>>> {
    let latest = binding
        .get("eligibility")
        .and_then(|e| e.get("latest"))
        .and_then(Value::as_object)
        .ok_or_else(|| EligibilityError("binding.eligibility.latest must be an object".into()))?;
    let Some(relative) = latest.get("evidence").and_then(Value::as_str) else {
        return Ok(None);
    };
    let evidence_path = resolve_evidence_path(repository_root, relative)?;
    if !evidence_path.is_file() {
        return err(format!("evidence file does not exist: {relative}"));
    }
    if Some(sha256_file(&evidence_path)?.as_str()) != latest.get("sha256").and_then(Value::as_str) {
        return err(format!("evidence digest mismatch: {relative}"));
    }
    let evidence = load_json(&evidence_path)?;
    validate_evidence(&evidence, binding, policy)?;
    let summary = evidence
        .get("summary")
        .and_then(Value::as_object)
        .ok_or_else(|| EligibilityError("evidence.summary must be an object".into()))?;
    if latest.get("decision") != summary.get("decision")
        || latest.get("reason") != summary.get("reason")
    {
        return err("binding decision/reason does not match evidence summary");
    }
    if latest.get("measured_at") != evidence.get("measured_at") {
        return err("binding measured_at does not match evidence");
    }
    Ok(Some(evidence))
}

pub fn check_fresh_gate(
    binding: &Map<String, Value>,
    evidence: Option<&Map<String, Value>>,
    policy: &Policy,
    purpose: &str,
    now: DateTime<Utc>,
) -> Result<(bool, String)> {
    let Some(max_age) = policy
        .get("freshness")
        .and_then(|f| f.get(purpose))
        .and_then(Value::as_i64)
    else {
        return err(format!("unsupported purpose {purpose:?}"));
    };
    let latest = binding
        .get("eligibility")
        .and_then(|e| e.get("latest"))
        .and_then(Value::as_object)
        .ok_or_else(|| EligibilityError("binding.eligibility.latest must be an object".into()))?;
    let decision = latest
        .get("decision")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let reason = latest
        .get("reason")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let Some(evidence) = evidence else {
        return Ok((false, format!("gate closed: {decision}/{reason}")));
    };
    if decision != "eligible" {
        return Ok((false, format!("gate closed: {decision}/{reason}")));
    }
    let measured_at = parse_utc(evidence.get("measured_at"), "evidence.measured_at")?;
    let age = (now - measured_at).num_seconds();
    if age < 0 {
        return Ok((
            false,
            "gate closed: evidence timestamp is in the future".into(),
        ));
    }
    if age > max_age {
        return Ok((
            false,
            format!("gate closed: evidence age {age}s exceeds {max_age}s for {purpose}"),
        ));
    }
    Ok((
        true,
        format!("gate open: eligible evidence age {age}s for {purpose}"),
    ))
}

/// `validate-targets`: every `*/Qm*.yaml` binding plus its pinned evidence.
pub fn validate_targets(repository: &Path, policy_path: &Path) -> Result<Vec<String>> {
    let policy = load_policy(policy_path)?;
    for schema_name in [
        "target-binding-v1.schema.json",
        "eligibility-evidence-v1.schema.json",
    ] {
        let schema = load_json(&repository.join("schemas").join(schema_name))?;
        if schema.get("$schema").and_then(Value::as_str)
            != Some("https://json-schema.org/draft/2020-12/schema")
        {
            return err(format!("{schema_name} is not a draft 2020-12 schema"));
        }
        if schema
            .get("$id")
            .and_then(Value::as_str)
            .is_none_or(str::is_empty)
        {
            return err(format!("{schema_name} is missing $id"));
        }
    }
    let mut bindings: Vec<PathBuf> = Vec::new();
    for entry in std::fs::read_dir(repository)
        .map_err(|e| EligibilityError(format!("cannot list {}: {e}", repository.display())))?
    {
        let entry = entry.map_err(|e| EligibilityError(e.to_string()))?;
        if !entry.path().is_dir() {
            continue;
        }
        let Ok(children) = std::fs::read_dir(entry.path()) else {
            continue;
        };
        for child in children.flatten() {
            let path = child.path();
            let name = path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or_default();
            if path.is_file() && name.starts_with("Qm") && name.ends_with(".yaml") {
                bindings.push(path);
            }
        }
    }
    bindings.sort();
    if bindings.is_empty() {
        return err("no target bindings found");
    }
    let mut lines = Vec::new();
    for binding_path in &bindings {
        let binding = load_yaml(binding_path)?;
        validate_binding(&binding, &policy, Some(binding_path))?;
        validate_binding_evidence(&binding, &policy, repository)?;
        let latest = binding
            .get("eligibility")
            .and_then(|e| e.get("latest"))
            .and_then(Value::as_object)
            .expect("validated above");
        lines.push(format!(
            "{} {} decision={} reason={}",
            binding
                .get("deployment")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            binding
                .get("chain")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            latest
                .get("decision")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            latest
                .get("reason")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        ));
    }
    lines.push(format!("validated {} target bindings", bindings.len()));
    Ok(lines)
}

pub fn now_utc() -> DateTime<Utc> {
    Utc::now()
}

#[cfg(test)]
pub fn utc(year: i32, month: u32, day: u32, hour: u32, minute: u32, second: u32) -> DateTime<Utc> {
    use chrono::TimeZone;
    Utc.with_ymd_and_hms(year, month, day, hour, minute, second)
        .single()
        .expect("valid timestamp")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Duration;
    use serde_json::json;

    fn measured_at() -> DateTime<Utc> {
        utc(2026, 8, 27, 12, 0, 0)
    }

    fn ts(value: DateTime<Utc>) -> String {
        utc_text(&value)
    }

    fn policy() -> Policy {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
        load_policy(&root.join("eligibility/policy-v1.yaml")).expect("repository policy loads")
    }

    fn obj(value: Value) -> Map<String, Value> {
        match value {
            Value::Object(map) => map,
            other => panic!("expected object, got {other}"),
        }
    }

    fn binding() -> Map<String, Value> {
        obj(json!({
            "deployment": "QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn",
            "family": "exchange-v3-bsc",
            "chain": "bsc",
            "eligibility": {
                "policy": "graph-node-net-catchup-v1",
                "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
                "latest": {
                    "decision": "indeterminate",
                    "reason": "no_fresh_evidence",
                    "measured_at": null,
                    "evidence": null,
                    "sha256": null
                }
            }
        }))
    }

    fn point(
        when: DateTime<Utc>,
        deployment_head: i64,
        chain_head: i64,
        observed_offset: i64,
    ) -> Value {
        let observed = when + Duration::seconds(observed_offset);
        json!({
            "requested_at": ts(when),
            "deployment_observed_at": ts(observed),
            "deployment_head": deployment_head,
            "chain_observed_at": ts(observed),
            "chain_head": chain_head
        })
    }

    fn window(name: &str, lag: i64, net_per_day: i64, stale: bool) -> Value {
        let days: i64 = if name == "24h" { 1 } else { 3 };
        let chain_end = 100_000;
        let deployment_end = chain_end - lag;
        let chain_delta = 100 * days;
        let net_delta = net_per_day * days;
        let deployment_delta = chain_delta + net_delta;
        let start = measured_at() - Duration::days(days);
        let offset = if stale { -601 } else { 0 };
        json!({
            "start": point(start, deployment_end - deployment_delta, chain_end - chain_delta, offset),
            "end": point(measured_at(), deployment_end, chain_end, 0)
        })
    }

    #[derive(Default)]
    struct CopyOpts {
        lag: Option<i64>,
        net_24h: Option<i64>,
        net_72h: Option<i64>,
        synced: bool,
        failed: bool,
        stale_window: bool,
    }

    fn healthy_copy(copy_id: &str, opts: CopyOpts) -> Value {
        let lag = opts.lag.unwrap_or(3_000);
        let net_24h = opts.net_24h.unwrap_or(100);
        let net_72h = opts.net_72h.unwrap_or(100);
        let windows = if opts.synced || opts.failed {
            json!({})
        } else {
            json!({
                "24h": window("24h", lag, net_24h, opts.stale_window),
                "72h": window("72h", lag, net_72h, false)
            })
        };
        json!({
            "copy_id": copy_id,
            "selector": {"pod": copy_id.replace('/', "-")},
            "current": {
                "observed_at": ts(measured_at()),
                "active": true,
                "attached": true,
                "health": if opts.failed { "failed" } else { "healthy" },
                "status": if opts.failed { "failed" } else { "indexing" },
                "failed": opts.failed,
                "synced": opts.synced,
                "deployment_head": 100_000 - lag,
                "chain_head": 100_000
            },
            "windows": windows
        })
    }

    fn copy(copy_id: &str) -> Value {
        healthy_copy(copy_id, CopyOpts::default())
    }

    fn blocker(kind: &str) -> Value {
        json!({
            "type": kind,
            "observed_at": ts(measured_at()),
            "source": "read-only status and deployment inventory",
            "details": "No viable attached version exists in this cluster."
        })
    }

    fn cluster(name: &str, copies: Vec<Value>, blockers: Vec<Value>) -> Value {
        json!({
            "cluster": name,
            "accounted": true,
            "copies": copies,
            "structural_blockers": blockers
        })
    }

    fn measurements(clusters: Vec<Value>) -> Map<String, Value> {
        obj(json!({
            "measured_at": ts(measured_at()),
            "collector": {"version": 1, "repository_commit": "a".repeat(40)},
            "sources": {
                "status_api": ["read-only snapshot"],
                "victoriametrics": {"queries": ["deployment_head", "ethereum_chain_head_number"]},
                "postgres_inventory": ["read-only deployment and graft inventory"]
            },
            "clusters": clusters
        }))
    }

    fn build(clusters: Vec<Value>) -> Map<String, Value> {
        build_evidence(&measurements(clusters), &binding(), &policy()).expect("evidence builds")
    }

    fn summary(evidence: &Map<String, Value>, key: &str) -> Value {
        evidence["summary"][key].clone()
    }

    #[test]
    fn empty_binding_is_fail_closed() {
        validate_binding(&binding(), &policy(), None).unwrap();
    }

    #[test]
    fn exact_market_snapshot_is_valid() {
        let mut candidate = binding();
        candidate.insert(
            "market_snapshot".into(),
            json!({
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 73997,
                "query_fees_grt_24h": "171.957",
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83"
            }),
        );
        validate_binding(&candidate, &policy(), None).unwrap();
    }

    #[test]
    fn ambiguous_legacy_market_fields_are_rejected() {
        for (field, value) in [
            ("market_qpd", json!(1900000)),
            ("qos_snapshot_at", json!("2026-08-31T17:20:00Z")),
            ("signal_grt", json!(14324)),
            ("grt_24h", json!("171.957")),
            ("generic_grt", json!("171.957")),
            ("queries_24h", json!(73997)),
            ("query_fees_grt_24h", json!("171.957")),
        ] {
            let mut candidate = binding();
            candidate.insert(field.into(), value);
            assert!(
                validate_binding(&candidate, &policy(), None).is_err(),
                "{field}"
            );
        }
    }

    #[test]
    fn market_snapshot_shape_and_types_are_fail_closed() {
        let baseline = json!({
            "measured_at": "2026-08-31T17:20:00Z",
            "queries_24h": 73997,
            "query_fees_grt_24h": "171.957",
            "authority": "https://github.com/pinax-network/substreams-backfills/issues/83"
        });
        type Mutation<'a> = Vec<(&'a str, Option<Value>)>;
        let mutations: Vec<(&str, Mutation)> = vec![
            (
                "numeric fees",
                vec![("query_fees_grt_24h", Some(json!(171.957)))],
            ),
            (
                "generic fee label",
                vec![
                    ("query_fees_grt_24h", None),
                    ("grt_24h", Some(json!("171.957"))),
                ],
            ),
            (
                "noncanonical timestamp",
                vec![("measured_at", Some(json!("2026-08-31T17:20:00.000Z")))],
            ),
            (
                "external authority",
                vec![(
                    "authority",
                    Some(json!("https://example.invalid/issues/83")),
                )],
            ),
            ("boolean queries", vec![("queries_24h", Some(json!(true)))]),
        ];
        for (name, mutation) in mutations {
            let mut snapshot = obj(baseline.clone());
            for (key, value) in mutation {
                match value {
                    Some(v) => {
                        snapshot.insert(key.into(), v);
                    }
                    None => {
                        snapshot.remove(key);
                    }
                }
            }
            let mut candidate = binding();
            candidate.insert("market_snapshot".into(), Value::Object(snapshot));
            assert!(
                validate_binding(&candidate, &policy(), None).is_err(),
                "{name}"
            );
        }
    }

    #[test]
    fn both_windows_above_threshold_are_eligible() {
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![copy("riv/copy")], vec![]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "eligible");
        assert_eq!(
            summary(&evidence, "reason"),
            "both_windows_exceed_threshold"
        );
        validate_evidence(&evidence, &binding(), &policy()).unwrap();
    }

    #[test]
    fn exactly_28_days_does_not_qualify() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/copy",
                    CopyOpts {
                        lag: Some(2_800),
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "monitor");
    }

    #[test]
    fn either_fast_window_keeps_native_sync() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/copy",
                    CopyOpts {
                        net_24h: Some(150),
                        net_72h: Some(90),
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "monitor");
    }

    #[test]
    fn non_positive_rates_are_eligible() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/copy",
                    CopyOpts {
                        net_24h: Some(0),
                        net_72h: Some(-10),
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(
            evidence["summary"],
            json!({
                "decision": "eligible",
                "reason": "non_positive_net_rate",
                "threshold_days": 28,
                "fastest_24h": {"copy_id": "riv/copy", "eta_days": null, "eta_kind": "infinite"},
                "fastest_72h": {"copy_id": "riv/copy", "eta_days": null, "eta_kind": "infinite"}
            })
        );
        let window = &evidence["clusters"][0]["copies"][0]["windows"]["72h"];
        assert_eq!(window["net_rate_blocks_per_day"], "-10.000000");
        assert_eq!(window["net_delta"], -30);
    }

    #[test]
    fn fastest_copy_across_clusters_wins() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/slow",
                    CopyOpts {
                        net_24h: Some(50),
                        net_72h: Some(50),
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![healthy_copy(
                    "kan/fast",
                    CopyOpts {
                        net_24h: Some(200),
                        net_72h: Some(200),
                        ..Default::default()
                    },
                )],
                vec![],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "monitor");
        assert_eq!(evidence["summary"]["fastest_24h"]["copy_id"], "kan/fast");
    }

    #[test]
    fn window_minima_are_selected_independently_across_copies() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/fast-24h",
                    CopyOpts {
                        net_24h: Some(200),
                        net_72h: Some(50),
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![healthy_copy(
                    "kan/fast-72h",
                    CopyOpts {
                        net_24h: Some(50),
                        net_72h: Some(200),
                        ..Default::default()
                    },
                )],
                vec![],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "monitor");
        assert_eq!(
            evidence["summary"]["fastest_24h"]["copy_id"],
            "riv/fast-24h"
        );
        assert_eq!(
            evidence["summary"]["fastest_72h"]["copy_id"],
            "kan/fast-72h"
        );
    }

    #[test]
    fn synced_healthy_copy_is_complete() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/synced",
                    CopyOpts {
                        synced: true,
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "complete");
    }

    #[test]
    fn failed_duplicate_does_not_poison_healthy_copy() {
        let mut failed = healthy_copy(
            "riv/failed",
            CopyOpts {
                failed: true,
                ..Default::default()
            },
        );
        failed["current"]["observed_at"] = json!(ts(measured_at() - Duration::days(30)));
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![failed, copy("riv/healthy")], vec![]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "eligible");
    }

    #[test]
    fn failed_copy_in_other_cluster_does_not_poison_healthy_copy() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/failed",
                    CopyOpts {
                        failed: true,
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster("kan-subgraphs-a", vec![copy("kan/healthy")], vec![]),
        ]);
        assert_eq!(summary(&evidence, "decision"), "eligible");
        assert_eq!(evidence["summary"]["fastest_24h"]["copy_id"], "kan/healthy");
    }

    #[test]
    fn stopped_copy_in_other_cluster_does_not_poison_healthy_copy() {
        let mut stopped = copy("riv/stopped");
        stopped["current"]["active"] = json!(false);
        stopped["current"]["status"] = json!("stopped");
        stopped["windows"] = json!({});
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![stopped], vec![]),
            cluster("kan-subgraphs-a", vec![copy("kan/healthy")], vec![]),
        ]);
        assert_eq!(summary(&evidence, "decision"), "eligible");
        assert_eq!(evidence["summary"]["fastest_72h"]["copy_id"], "kan/healthy");
    }

    #[test]
    fn failed_only_copy_does_not_qualify() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/failed",
                    CopyOpts {
                        failed: true,
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "indeterminate");
        assert_eq!(summary(&evidence, "reason"), "no_healthy_copy");
    }

    #[test]
    fn proven_structural_blockers_are_eligible() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![],
                vec![blocker("missing_graft_base")],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_graft_base")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "eligible");
        assert_eq!(summary(&evidence, "reason"), "missing_graft_base");
    }

    #[test]
    fn stale_structural_proof_is_indeterminate() {
        let mut stale = blocker("missing_attached_version");
        stale["observed_at"] = json!(ts(measured_at() - Duration::seconds(601)));
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![], vec![stale]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "indeterminate");
        assert_eq!(summary(&evidence, "reason"), "stale_or_incomplete_samples");
    }

    #[test]
    fn healthy_copy_conflicting_with_structural_absence_is_indeterminate() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![copy("riv/copy")],
                vec![blocker("missing_attached_version")],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "indeterminate");
        assert_eq!(summary(&evidence, "reason"), "conflicting_identity");
    }

    #[test]
    fn failed_attached_copy_conflicts_with_missing_version_claim() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/failed",
                    CopyOpts {
                        failed: true,
                        ..Default::default()
                    },
                )],
                vec![blocker("missing_attached_version")],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "decision"), "indeterminate");
        assert_eq!(summary(&evidence, "reason"), "conflicting_identity");
    }

    #[test]
    fn missing_cluster_is_indeterminate() {
        let evidence = build(vec![cluster(
            "riv-subgraphs-a",
            vec![copy("riv/copy")],
            vec![],
        )]);
        assert_eq!(summary(&evidence, "decision"), "indeterminate");
        assert_eq!(summary(&evidence, "reason"), "missing_required_cluster");
    }

    #[test]
    fn stale_window_is_indeterminate() {
        let evidence = build(vec![
            cluster(
                "riv-subgraphs-a",
                vec![healthy_copy(
                    "riv/copy",
                    CopyOpts {
                        stale_window: true,
                        ..Default::default()
                    },
                )],
                vec![],
            ),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "reason"), "stale_or_incomplete_samples");
    }

    #[test]
    fn head_regression_is_indeterminate() {
        let mut item = copy("riv/copy");
        item["windows"]["24h"]["start"]["deployment_head"] = json!(99_000);
        item["windows"]["24h"]["end"]["deployment_head"] = json!(98_000);
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![item], vec![]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        assert_eq!(summary(&evidence, "reason"), "head_regression");
    }

    #[test]
    fn calculation_tampering_is_rejected() {
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![copy("riv/copy")], vec![]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        let mut tampered = evidence.clone();
        tampered["clusters"][0]["copies"][0]["windows"]["24h"]["eta_days"] = json!("1.000000");
        let error = validate_evidence(&tampered, &binding(), &policy()).unwrap_err();
        assert!(error.to_string().contains("calculated fields"), "{error}");
    }

    #[test]
    fn binding_digest_pins_exact_evidence_bytes() {
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![copy("riv/copy")], vec![]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        let repository = tempfile::tempdir().unwrap();
        let relative = format!(
            "evidence/eligibility/{}/20260827T120000Z.json",
            binding()["deployment"].as_str().unwrap()
        );
        let evidence_path = repository.path().join(&relative);
        std::fs::create_dir_all(evidence_path.parent().unwrap()).unwrap();
        let contents = canonical_json(&evidence);
        std::fs::write(&evidence_path, &contents).unwrap();
        let mut target = binding();
        target["eligibility"]["latest"] = json!({
            "decision": evidence["summary"]["decision"],
            "reason": evidence["summary"]["reason"],
            "measured_at": evidence["measured_at"],
            "evidence": relative,
            "sha256": hex::encode(Sha256::digest(&contents))
        });
        validate_binding(&target, &policy(), None).unwrap();
        assert_eq!(
            validate_binding_evidence(&target, &policy(), repository.path()).unwrap(),
            Some(evidence.clone())
        );
        let mut spaced = contents.clone();
        spaced.push(b' ');
        std::fs::write(&evidence_path, &spaced).unwrap();
        let error = validate_binding_evidence(&target, &policy(), repository.path()).unwrap_err();
        assert!(error.to_string().contains("digest mismatch"), "{error}");
    }

    #[test]
    fn binding_evidence_filename_must_match_timestamp() {
        let mut target = binding();
        let deployment = target["deployment"].as_str().unwrap().to_string();
        target["eligibility"]["latest"] = json!({
            "decision": "eligible",
            "reason": "both_windows_exceed_threshold",
            "measured_at": ts(measured_at()),
            "evidence": format!("evidence/eligibility/{deployment}/20260827T120001Z.json"),
            "sha256": "a".repeat(64)
        });
        let error = validate_binding(&target, &policy(), None).unwrap_err();
        assert!(error.to_string().contains("filename must match"), "{error}");
    }

    #[test]
    fn source_provenance_is_required() {
        let mut raw = measurements(vec![
            cluster("riv-subgraphs-a", vec![copy("riv/copy")], vec![]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        raw["sources"]["victoriametrics"]["queries"] = json!([]);
        let error = build_evidence(&raw, &binding(), &policy()).unwrap_err();
        assert!(
            error.to_string().contains("VictoriaMetrics queries"),
            "{error}"
        );
    }

    #[test]
    fn action_gate_expires_without_mutating_history() {
        let evidence = build(vec![
            cluster("riv-subgraphs-a", vec![copy("riv/copy")], vec![]),
            cluster(
                "kan-subgraphs-a",
                vec![],
                vec![blocker("missing_attached_version")],
            ),
        ]);
        let mut target = binding();
        target["eligibility"]["latest"] = json!({
            "decision": evidence["summary"]["decision"],
            "reason": evidence["summary"]["reason"],
            "measured_at": evidence["measured_at"],
            "evidence": format!("evidence/eligibility/{}/20260827T120000Z.json", binding()["deployment"].as_str().unwrap()),
            "sha256": "a".repeat(64)
        });
        let (allowed, _) = check_fresh_gate(
            &target,
            Some(&evidence),
            &policy(),
            "implementation-start",
            measured_at() + Duration::seconds(3_600),
        )
        .unwrap();
        assert!(allowed);
        let (allowed, message) = check_fresh_gate(
            &target,
            Some(&evidence),
            &policy(),
            "compute-or-load-start",
            measured_at() + Duration::seconds(3_601),
        )
        .unwrap();
        assert!(!allowed);
        assert!(message.contains("exceeds"), "{message}");
        let (allowed, _) = check_fresh_gate(
            &target,
            None,
            &policy(),
            "implementation-start",
            measured_at(),
        )
        .unwrap();
        assert!(!allowed);
        assert!(check_fresh_gate(
            &target,
            Some(&evidence),
            &policy(),
            "activation",
            measured_at()
        )
        .is_err());
    }

    #[test]
    fn quantize_matches_decimal_half_up_formatting() {
        assert_eq!(quantize6(100 * SECONDS_PER_DAY, 86_400), "100.000000");
        assert_eq!(quantize6(-10 * 3 * SECONDS_PER_DAY, 259_200), "-10.000000");
        assert_eq!(quantize6(1, 3), "0.333333");
        assert_eq!(quantize6(2, 3), "0.666667");
        assert_eq!(quantize6(-1, 3), "-0.333333");
        assert_eq!(quantize6(0, 7), "0.000000");
        assert_eq!(quantize6(1, 2_000_000), "0.000001");
        assert_eq!(
            quantize6(3_000 * 86_400, 100 * SECONDS_PER_DAY),
            "30.000000"
        );
    }

    #[test]
    fn canonical_json_matches_python_layout() {
        let value = obj(json!({"b": [1, 2], "a": {"z": null, "y": "s"}, "c": {}}));
        let rendered = String::from_utf8(canonical_json(&value)).unwrap();
        assert_eq!(rendered, "{\n  \"a\": {\n    \"y\": \"s\",\n    \"z\": null\n  },\n  \"b\": [\n    1,\n    2\n  ],\n  \"c\": {}\n}\n");
    }
}

#[cfg(test)]
mod market_snapshot_tests {
    use super::*;
    use serde_json::json;

    const AUTHORITY: &str = "https://github.com/pinax-network/substreams-backfills/issues/83";

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    #[test]
    fn exact_august_31_snapshots_are_locked() {
        let expected = [
            (
                "uniswap-v2-base/QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8.yaml",
                780953,
                "954.416540",
            ),
            (
                "uniswap-v3-matic/QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3.yaml",
                386433,
                "471.970",
            ),
            (
                "pancakeswap-infinity-cl-bsc/QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz.yaml",
                25405,
                "30.041",
            ),
            (
                "exchange-v3-bsc/QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn.yaml",
                73997,
                "171.957",
            ),
        ];
        for (path, queries, fees) in expected {
            let binding = load_yaml(&repository().join(path)).unwrap();
            assert_eq!(
                binding.get("market_snapshot"),
                Some(&json!({
                    "measured_at": "2026-08-31T17:20:00Z",
                    "queries_24h": queries,
                    "query_fees_grt_24h": fees,
                    "authority": AUTHORITY
                })),
                "{path}"
            );
            for legacy in LEGACY_MARKET_FIELDS {
                assert!(!binding.contains_key(*legacy), "{path} carries {legacy}");
            }
        }
    }

    #[test]
    fn unattributed_historical_estimates_are_not_promoted() {
        for path in [
            "morpho-blue-base/QmWSfh5qnidd1tBd6FY6eDvbSQUPTNhNG7o8CUGenvbaht.yaml",
            "uniswap-v3/QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7.yaml",
            "uniswap-v3/Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP.yaml",
        ] {
            let binding = load_yaml(&repository().join(path)).unwrap();
            assert!(!binding.contains_key("market_snapshot"), "{path}");
            for legacy in LEGACY_MARKET_FIELDS {
                assert!(!binding.contains_key(*legacy), "{path} carries {legacy}");
            }
        }
    }
}
