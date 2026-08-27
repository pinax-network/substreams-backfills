#!/usr/bin/env python3
"""Fail-closed Graph Node catch-up eligibility calculations and validation."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml


SECONDS_PER_DAY = 86_400
DERIVED_WINDOW_FIELDS = {
    "duration_seconds",
    "deployment_delta",
    "chain_delta",
    "net_delta",
    "net_rate_blocks_per_day",
    "lag_blocks",
    "eta_days",
    "eta_kind",
}


class EligibilityError(ValueError):
    """Raised when a binding or evidence document violates the contract."""


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EligibilityError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise EligibilityError(f"{name} must be an array")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise EligibilityError(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EligibilityError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise EligibilityError(f"{name} must be >= {minimum}")
    return value


def parse_utc(value: Any, name: str) -> datetime:
    text = _string(value, name)
    if not text.endswith("Z"):
        raise EligibilityError(f"{name} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise EligibilityError(f"{name} is not a valid RFC3339 timestamp") from error
    if parsed.tzinfo != timezone.utc:
        raise EligibilityError(f"{name} must use UTC")
    return parsed


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise EligibilityError(f"cannot read YAML {path}: {error}") from error
    return _mapping(value, str(path))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EligibilityError(f"cannot read JSON {path}: {error}") from error
    return _mapping(value, str(path))


def load_policy(path: Path) -> dict[str, Any]:
    policy = load_yaml(path)
    expected_fields = {
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
    }
    if set(policy) != expected_fields:
        raise EligibilityError("policy contains missing or unknown fields")
    if policy.get("format_version") != 1:
        raise EligibilityError("policy.format_version must be 1")
    _string(policy.get("id"), "policy.id")
    _integer(policy.get("threshold_days"), "policy.threshold_days", minimum=1)
    windows = _mapping(policy.get("windows"), "policy.windows")
    if set(windows) != {"24h", "72h"}:
        raise EligibilityError("policy.windows must contain exactly 24h and 72h")
    for name, seconds in windows.items():
        _integer(seconds, f"policy.windows.{name}", minimum=1)
    _integer(policy.get("sample_max_age_seconds"), "policy.sample_max_age_seconds", minimum=0)
    freshness = _mapping(policy.get("freshness"), "policy.freshness")
    if set(freshness) != {"implementation-start", "compute-or-load-start"}:
        raise EligibilityError("policy.freshness has unexpected purposes")
    for purpose, seconds in freshness.items():
        _integer(seconds, f"policy.freshness.{purpose}", minimum=1)
    clusters = _list(policy.get("required_clusters"), "policy.required_clusters")
    if not clusters:
        raise EligibilityError("policy.required_clusters must be non-empty and unique")
    for index, cluster in enumerate(clusters):
        _string(cluster, f"policy.required_clusters[{index}]")
    if len(clusters) != len(set(clusters)):
        raise EligibilityError("policy.required_clusters must be non-empty and unique")
    healthy_copy = _mapping(policy.get("healthy_copy"), "policy.healthy_copy")
    if set(healthy_copy) != {"health", "status"}:
        raise EligibilityError("policy.healthy_copy contains missing or unknown fields")
    _string(healthy_copy.get("health"), "policy.healthy_copy.health")
    _string(healthy_copy.get("status"), "policy.healthy_copy.status")
    for field in ("decisions", "reasons", "structural_blockers"):
        values = _list(policy.get(field), f"policy.{field}")
        if not values:
            raise EligibilityError(f"policy.{field} must be non-empty and unique")
        for index, value in enumerate(values):
            _string(value, f"policy.{field}[{index}]")
        if len(values) != len(set(values)):
            raise EligibilityError(f"policy.{field} must be non-empty and unique")
    return policy


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validate_binding(
    binding: dict[str, Any],
    policy: dict[str, Any],
    *,
    binding_path: Path | None = None,
) -> None:
    for field in ("deployment", "family", "chain"):
        _string(binding.get(field), f"binding.{field}")
    if binding_path is not None and binding["deployment"] not in binding_path.name:
        raise EligibilityError(f"{binding_path}: deployment does not match filename")

    eligibility = _mapping(binding.get("eligibility"), "binding.eligibility")
    if set(eligibility) != {"policy", "required_clusters", "latest"}:
        raise EligibilityError("binding.eligibility contains missing or unknown fields")
    if eligibility.get("policy") != policy["id"]:
        raise EligibilityError("binding eligibility policy does not match policy file")

    clusters = _list(eligibility.get("required_clusters"), "binding.eligibility.required_clusters")
    for index, cluster in enumerate(clusters):
        _string(cluster, f"binding.eligibility.required_clusters[{index}]")
    if len(clusters) != len(set(clusters)):
        raise EligibilityError("binding required_clusters contains duplicates")
    if set(clusters) != set(policy["required_clusters"]):
        raise EligibilityError("binding required_clusters must cover every policy cluster")

    latest = _mapping(eligibility.get("latest"), "binding.eligibility.latest")
    required_latest = {"decision", "reason", "measured_at", "evidence", "sha256"}
    if set(latest) != required_latest:
        raise EligibilityError("binding eligibility latest contains missing or unknown fields")
    if latest.get("decision") not in policy["decisions"]:
        raise EligibilityError("binding latest decision is not allowed by policy")
    if latest.get("reason") not in policy["reasons"]:
        raise EligibilityError("binding latest reason is not allowed by policy")

    empty_pointer = all(latest.get(field) is None for field in ("measured_at", "evidence", "sha256"))
    if empty_pointer:
        if latest.get("decision") != "indeterminate" or latest.get("reason") != "no_fresh_evidence":
            raise EligibilityError("an empty evidence pointer must be indeterminate/no_fresh_evidence")
        return
    if any(latest.get(field) is None for field in ("measured_at", "evidence", "sha256")):
        raise EligibilityError("measured_at, evidence, and sha256 must all be set together")
    measured_at = parse_utc(latest["measured_at"], "binding.eligibility.latest.measured_at")
    evidence_path = _string(latest["evidence"], "binding.eligibility.latest.evidence")
    evidence_parts = Path(evidence_path).parts
    if (
        len(evidence_parts) != 4
        or evidence_parts[:2] != ("evidence", "eligibility")
        or evidence_parts[2] != binding["deployment"]
        or not evidence_parts[3].endswith(".json")
        or ".." in evidence_parts
    ):
        raise EligibilityError("binding evidence path must stay under evidence/eligibility")
    expected_name = measured_at.strftime("%Y%m%dT%H%M%SZ.json")
    if evidence_parts[3] != expected_name:
        raise EligibilityError("binding evidence filename must match measured_at")
    digest = _string(latest["sha256"], "binding.eligibility.latest.sha256")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise EligibilityError("binding evidence sha256 must be 64 lowercase hexadecimal characters")


def _sample_age_seconds(observed: Any, requested: Any, name: str) -> float:
    observed_at = parse_utc(observed, f"{name}.observed_at")
    requested_at = parse_utc(requested, f"{name}.requested_at")
    return abs((observed_at - requested_at).total_seconds())


def calculate_window(window: dict[str, Any], policy: dict[str, Any], name: str) -> tuple[dict[str, Any], list[str]]:
    raw = {key: copy.deepcopy(value) for key, value in window.items() if key not in DERIVED_WINDOW_FIELDS}
    if set(raw) != {"start", "end"}:
        raise EligibilityError(f"{name} must contain start/end plus calculated fields")
    start = _mapping(raw["start"], f"{name}.start")
    end = _mapping(raw["end"], f"{name}.end")
    point_fields = {
        "requested_at",
        "deployment_observed_at",
        "deployment_head",
        "chain_observed_at",
        "chain_head",
    }
    if set(start) != point_fields or set(end) != point_fields:
        raise EligibilityError(f"{name} start/end contain missing or unknown fields")

    start_requested = parse_utc(start["requested_at"], f"{name}.start.requested_at")
    end_requested = parse_utc(end["requested_at"], f"{name}.end.requested_at")
    duration_value = (end_requested - start_requested).total_seconds()
    if not duration_value.is_integer():
        raise EligibilityError(f"{name} duration must be an exact number of seconds")
    duration = int(duration_value)
    expected_duration = _integer(policy["windows"].get(name.rsplit(".", 1)[-1]), f"policy window for {name}")
    if duration != expected_duration:
        raise EligibilityError(f"{name} duration is {duration}, expected {expected_duration}")

    conditions: list[str] = []
    max_age = policy["sample_max_age_seconds"]
    for label, point in (("start", start), ("end", end)):
        for kind in ("deployment", "chain"):
            observed_key = f"{kind}_observed_at"
            age = _sample_age_seconds(point[observed_key], point["requested_at"], f"{name}.{label}.{kind}")
            if age > max_age:
                conditions.append("stale_or_incomplete_samples")
        _integer(point["deployment_head"], f"{name}.{label}.deployment_head", minimum=0)
        _integer(point["chain_head"], f"{name}.{label}.chain_head", minimum=0)

    deployment_delta = end["deployment_head"] - start["deployment_head"]
    chain_delta = end["chain_head"] - start["chain_head"]
    if deployment_delta < 0 or chain_delta < 0:
        conditions.append("head_regression")
    net_delta = deployment_delta - chain_delta
    lag = max(end["chain_head"] - end["deployment_head"], 0)
    rate = (Decimal(net_delta) * Decimal(SECONDS_PER_DAY) / Decimal(duration)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    if net_delta <= 0:
        eta_days: str | None = None
        eta_kind = "infinite"
    else:
        eta = (Decimal(lag) * Decimal(duration) / (Decimal(net_delta) * Decimal(SECONDS_PER_DAY))).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        eta_days = format(eta, "f")
        eta_kind = "finite"

    calculated = copy.deepcopy(raw)
    calculated.update(
        {
            "duration_seconds": duration,
            "deployment_delta": deployment_delta,
            "chain_delta": chain_delta,
            "net_delta": net_delta,
            "net_rate_blocks_per_day": format(rate, "f"),
            "lag_blocks": lag,
            "eta_days": eta_days,
            "eta_kind": eta_kind,
        }
    )
    return calculated, sorted(set(conditions))


def _healthy_copy(current: dict[str, Any], policy: dict[str, Any]) -> bool:
    return (
        current.get("active") is True
        and current.get("attached") is True
        and current.get("failed") is False
        and current.get("health") == policy["healthy_copy"]["health"]
        and current.get("status") == policy["healthy_copy"]["status"]
    )


def _eta_exceeds_threshold(window: dict[str, Any], threshold_days: int) -> bool:
    net_delta = window["net_delta"]
    if net_delta <= 0:
        return True
    return (
        window["lag_blocks"] * window["duration_seconds"]
        > threshold_days * net_delta * SECONDS_PER_DAY
    )


def _fastest(candidates: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    def key(item: tuple[str, dict[str, Any]]) -> tuple[int, Decimal, str]:
        copy_id, window = item
        if window["eta_kind"] == "infinite":
            return (1, Decimal(0), copy_id)
        return (0, Decimal(window["eta_days"]), copy_id)

    copy_id, window = min(candidates, key=key)
    return {
        "copy_id": copy_id,
        "eta_days": window["eta_days"],
        "eta_kind": window["eta_kind"],
    }


def build_evidence(
    measurements: dict[str, Any], binding: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    if set(measurements) != {"measured_at", "collector", "sources", "clusters"}:
        raise EligibilityError("measurements contains missing or unknown top-level fields")
    measured_at = parse_utc(measurements.get("measured_at"), "measurements.measured_at")
    evidence: dict[str, Any] = {
        "format_version": 1,
        "policy": policy["id"],
        "deployment": binding["deployment"],
        "family": binding["family"],
        "chain": binding["chain"],
        "measured_at": utc_text(measured_at),
        "collector": copy.deepcopy(measurements.get("collector", {"version": 1, "repository_commit": None})),
        "sources": copy.deepcopy(_mapping(measurements.get("sources"), "measurements.sources")),
        "clusters": copy.deepcopy(_list(measurements.get("clusters"), "measurements.clusters")),
    }
    collector = _mapping(evidence["collector"], "measurements.collector")
    if set(collector) != {"version", "repository_commit"} or collector.get("version") != 1:
        raise EligibilityError("collector must contain version=1 and repository_commit")
    collector_commit = _string(collector.get("repository_commit"), "collector.repository_commit")
    if len(collector_commit) != 40 or any(character not in "0123456789abcdef" for character in collector_commit):
        raise EligibilityError("collector.repository_commit must be a 40-character lowercase Git commit")

    sources = _mapping(evidence["sources"], "measurements.sources")
    if set(sources) != {"status_api", "victoriametrics", "postgres_inventory"}:
        raise EligibilityError("sources must contain status_api, victoriametrics, and postgres_inventory")
    status_sources = _list(sources["status_api"], "sources.status_api")
    if not status_sources:
        raise EligibilityError("sources.status_api must retain at least one read-only source record")
    metrics_sources = _mapping(sources["victoriametrics"], "sources.victoriametrics")
    metric_queries = _list(metrics_sources.get("queries"), "sources.victoriametrics.queries")
    postgres_sources = _list(sources["postgres_inventory"], "sources.postgres_inventory")

    required_clusters = binding["eligibility"]["required_clusters"]
    cluster_names: list[str] = []
    candidate_windows: dict[str, list[tuple[str, dict[str, Any]]]] = {"24h": [], "72h": []}
    conditions: list[str] = []
    healthy_seen = False
    synced_seen = False
    structural_proof: dict[str, bool] = {}
    blocker_types: list[str] = []
    copy_ids: set[str] = set()

    for cluster_index, cluster_value in enumerate(evidence["clusters"]):
        cluster = _mapping(cluster_value, f"clusters[{cluster_index}]")
        if set(cluster) != {"cluster", "accounted", "copies", "structural_blockers"}:
            raise EligibilityError(f"clusters[{cluster_index}] contains missing or unknown fields")
        cluster_name = _string(cluster.get("cluster"), f"clusters[{cluster_index}].cluster")
        cluster_names.append(cluster_name)
        if not isinstance(cluster.get("accounted"), bool):
            raise EligibilityError(f"clusters[{cluster_index}].accounted must be boolean")
        if cluster.get("accounted") is not True:
            conditions.append("missing_required_cluster")
        blockers = _list(cluster.get("structural_blockers"), f"clusters[{cluster_index}].structural_blockers")
        allowed_blockers = set(policy["structural_blockers"])
        structural = False
        cluster_blocker_types: list[str] = []
        for blocker_index, blocker_value in enumerate(blockers):
            blocker = _mapping(blocker_value, f"clusters[{cluster_index}].structural_blockers[{blocker_index}]")
            if set(blocker) != {"type", "observed_at", "source", "details"}:
                raise EligibilityError("structural blocker contains missing or unknown fields")
            blocker_type = blocker.get("type")
            if blocker_type not in allowed_blockers:
                raise EligibilityError(f"unsupported structural blocker {blocker_type!r}")
            blocker_at = parse_utc(blocker.get("observed_at"), "structural blocker observed_at")
            if abs((blocker_at - measured_at).total_seconds()) > policy["sample_max_age_seconds"]:
                conditions.append("stale_or_incomplete_samples")
            _string(blocker.get("source"), "structural blocker source")
            _string(blocker.get("details"), "structural blocker details")
            structural = True
            blocker_types.append(blocker_type)
            cluster_blocker_types.append(blocker_type)
        structural_proof[cluster_name] = structural

        cluster_has_healthy = False
        cluster_has_attached = False
        for copy_index, copy_value in enumerate(_list(cluster.get("copies"), f"clusters[{cluster_index}].copies")):
            copy_item = _mapping(copy_value, f"clusters[{cluster_index}].copies[{copy_index}]")
            if set(copy_item) != {"copy_id", "selector", "current", "windows"}:
                raise EligibilityError("copy contains missing or unknown fields")
            copy_id = _string(copy_item.get("copy_id"), "copy.copy_id")
            if copy_id in copy_ids:
                raise EligibilityError(f"duplicate copy_id {copy_id}")
            copy_ids.add(copy_id)
            selector = _mapping(copy_item.get("selector"), f"copy {copy_id}.selector")
            if not selector or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in selector.items()
            ):
                raise EligibilityError(f"copy {copy_id} selector must contain string labels")
            current = _mapping(copy_item.get("current"), f"copy {copy_id}.current")
            required_current = {"observed_at", "active", "attached", "health", "status", "failed", "synced"}
            optional_current = {"deployment_head", "chain_head"}
            if not required_current.issubset(current) or not set(current).issubset(
                required_current | optional_current
            ):
                raise EligibilityError(f"copy {copy_id} current contains missing or unknown fields")
            current_at = parse_utc(current.get("observed_at"), f"copy {copy_id}.current.observed_at")
            for boolean_field in ("active", "attached", "failed", "synced"):
                if not isinstance(current.get(boolean_field), bool):
                    raise EligibilityError(f"copy {copy_id}.current.{boolean_field} must be boolean")
            _string(current.get("health"), f"copy {copy_id}.current.health")
            _string(current.get("status"), f"copy {copy_id}.current.status")
            cluster_has_attached = cluster_has_attached or current.get("attached") is True
            for head_field in optional_current:
                if head_field in current and current[head_field] is not None:
                    _integer(current[head_field], f"copy {copy_id}.current.{head_field}", minimum=0)

            if not _healthy_copy(current, policy):
                continue
            if abs((current_at - measured_at).total_seconds()) > policy["sample_max_age_seconds"]:
                conditions.append("stale_or_incomplete_samples")
                continue
            healthy_seen = True
            cluster_has_healthy = True
            if current.get("synced") is True:
                synced_seen = True
                continue

            windows = _mapping(copy_item.get("windows"), f"copy {copy_id}.windows")
            for window_name in ("24h", "72h"):
                if window_name not in windows:
                    conditions.append("stale_or_incomplete_samples")
                    continue
                calculated, window_conditions = calculate_window(
                    _mapping(windows[window_name], f"copy {copy_id}.windows.{window_name}"),
                    policy,
                    f"copy {copy_id}.windows.{window_name}",
                )
                windows[window_name] = calculated
                conditions.extend(window_conditions)
                requested_end = parse_utc(calculated["end"]["requested_at"], "window end requested_at")
                if requested_end != measured_at:
                    conditions.append("stale_or_incomplete_samples")
                candidate_windows[window_name].append((copy_id, calculated))
            if set(windows) - {"24h", "72h"}:
                raise EligibilityError(f"copy {copy_id}.windows contains unknown windows")
        if cluster_has_healthy:
            if structural:
                conditions.append("conflicting_identity")
        elif cluster_has_attached and "missing_attached_version" in cluster_blocker_types:
            conditions.append("conflicting_identity")

    if len(cluster_names) != len(set(cluster_names)):
        raise EligibilityError("evidence contains duplicate cluster entries")
    if set(cluster_names) != set(required_clusters):
        conditions.append("missing_required_cluster")
    if not healthy_seen and any(
        not structural_proof.get(cluster_name, False)
        for cluster_name in required_clusters
    ):
        conditions.append("no_healthy_copy")

    if healthy_seen and not metric_queries:
        raise EligibilityError("healthy-copy evidence must retain VictoriaMetrics queries")
    if blocker_types and not postgres_sources:
        raise EligibilityError("structural blocker evidence must retain read-only Postgres inventory")

    fastest_24h = _fastest(candidate_windows["24h"])
    fastest_72h = _fastest(candidate_windows["72h"])
    condition_set = set(conditions)
    if "missing_required_cluster" in condition_set:
        decision, reason = "indeterminate", "missing_required_cluster"
    elif "conflicting_identity" in condition_set:
        decision, reason = "indeterminate", "conflicting_identity"
    elif synced_seen:
        decision, reason = "complete", "native_sync_complete"
    elif "head_regression" in condition_set:
        decision, reason = "indeterminate", "head_regression"
    elif "stale_or_incomplete_samples" in condition_set:
        decision, reason = "indeterminate", "stale_or_incomplete_samples"
    elif "no_healthy_copy" in condition_set:
        decision, reason = "indeterminate", "no_healthy_copy"
    elif healthy_seen:
        all_windows = candidate_windows["24h"] + candidate_windows["72h"]
        if len(candidate_windows["24h"]) == 0 or len(candidate_windows["72h"]) == 0:
            decision, reason = "indeterminate", "stale_or_incomplete_samples"
        elif any(not _eta_exceeds_threshold(window, policy["threshold_days"]) for _, window in all_windows):
            decision, reason = "monitor", "fastest_window_at_or_below_threshold"
        elif all(window["net_delta"] <= 0 for _, window in all_windows):
            decision, reason = "eligible", "non_positive_net_rate"
        else:
            decision, reason = "eligible", "both_windows_exceed_threshold"
    elif blocker_types:
        decision = "eligible"
        reason = "missing_graft_base" if "missing_graft_base" in blocker_types else "missing_attached_version"
    else:
        decision, reason = "indeterminate", "no_healthy_copy"

    evidence["summary"] = {
        "decision": decision,
        "reason": reason,
        "threshold_days": policy["threshold_days"],
        "fastest_24h": fastest_24h,
        "fastest_72h": fastest_72h,
    }
    return evidence


def validate_evidence(
    evidence: dict[str, Any], binding: dict[str, Any], policy: dict[str, Any]
) -> None:
    expected_top = {
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
    }
    if set(evidence) != expected_top:
        raise EligibilityError("evidence contains missing or unknown top-level fields")
    if evidence.get("format_version") != 1 or evidence.get("policy") != policy["id"]:
        raise EligibilityError("evidence format or policy does not match")
    for field in ("deployment", "family", "chain"):
        if evidence.get(field) != binding.get(field):
            raise EligibilityError(f"evidence {field} does not match binding")

    raw = copy.deepcopy(evidence)
    recorded_summary = raw.pop("summary")
    for cluster in _list(raw.get("clusters"), "evidence.clusters"):
        for copy_item in _list(_mapping(cluster, "cluster").get("copies"), "cluster.copies"):
            for window in _mapping(_mapping(copy_item, "copy").get("windows"), "copy.windows").values():
                for field in DERIVED_WINDOW_FIELDS:
                    _mapping(window, "window").pop(field, None)
    measurements = {
        "measured_at": raw["measured_at"],
        "collector": raw["collector"],
        "sources": raw["sources"],
        "clusters": raw["clusters"],
    }
    rebuilt = build_evidence(measurements, binding, policy)
    if rebuilt.get("summary") != recorded_summary:
        raise EligibilityError("evidence summary does not match recomputed decision")
    if rebuilt != evidence:
        raise EligibilityError("evidence calculated fields do not match raw samples")


def resolve_evidence_path(repository_root: Path, relative: str) -> Path:
    root = repository_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root / "evidence" / "eligibility")
    except ValueError as error:
        raise EligibilityError("evidence path escapes evidence/eligibility") from error
    return candidate


def validate_binding_evidence(
    binding: dict[str, Any], policy: dict[str, Any], repository_root: Path
) -> dict[str, Any] | None:
    latest = binding["eligibility"]["latest"]
    if latest["evidence"] is None:
        return None
    evidence_path = resolve_evidence_path(repository_root, latest["evidence"])
    if not evidence_path.is_file():
        raise EligibilityError(f"evidence file does not exist: {latest['evidence']}")
    if sha256_file(evidence_path) != latest["sha256"]:
        raise EligibilityError(f"evidence digest mismatch: {latest['evidence']}")
    evidence = load_json(evidence_path)
    validate_evidence(evidence, binding, policy)
    summary = evidence["summary"]
    if latest["decision"] != summary["decision"] or latest["reason"] != summary["reason"]:
        raise EligibilityError("binding decision/reason does not match evidence summary")
    if latest["measured_at"] != evidence["measured_at"]:
        raise EligibilityError("binding measured_at does not match evidence")
    return evidence


def check_fresh_gate(
    binding: dict[str, Any],
    evidence: dict[str, Any] | None,
    policy: dict[str, Any],
    purpose: str,
    now: datetime,
) -> tuple[bool, str]:
    if purpose not in policy["freshness"]:
        raise EligibilityError(f"unsupported purpose {purpose!r}")
    latest = binding["eligibility"]["latest"]
    if latest["decision"] != "eligible" or evidence is None:
        return False, f"gate closed: {latest['decision']}/{latest['reason']}"
    measured_at = parse_utc(evidence["measured_at"], "evidence.measured_at")
    age = (now.astimezone(timezone.utc) - measured_at).total_seconds()
    if age < 0:
        return False, "gate closed: evidence timestamp is in the future"
    max_age = policy["freshness"][purpose]
    if age > max_age:
        return False, f"gate closed: evidence age {int(age)}s exceeds {max_age}s for {purpose}"
    return True, f"gate open: eligible evidence age {int(age)}s for {purpose}"
