#!/usr/bin/env python3
"""Verify the retained, fail-closed Uniswap V3 logical-oracle snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "uniswap-v3-logical-oracle/v1"
ORACLE_DIRECTORY = Path("uniswap-v3/oracle/v1")
CONTRACT_PATH = ORACLE_DIRECTORY / "contract.json"

MAINNET_DEPLOYMENT = "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7"
BASE_DEPLOYMENT = "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP"

EXPECTED_FILE_LOCKS = {
    "discovery/base-boundary-error.json": (
        168,
        "cc4435ae749ffcd8b413eaaff19881a6dc2c3caa7b0c40076d2f27bb82291e32",
    ),
    "discovery/base-query-response.json": (
        729,
        "34f272caa00a96ef1f4cea9d96371f986b14630a7e3cece64c27208be9f1eb20",
    ),
    "discovery/base-status-response.json": (
        1316,
        "6257a9db0e4fb15c4679e23fa591c41699803b267b4944a35b36a9e0882441ee",
    ),
    "discovery/mainnet-boundary-response.json": (
        1792,
        "95ab94ae8e98bd04727b6e4c06ffa6ba1de9734a2c80f5cc089a08da9d7950d1",
    ),
    "discovery/mainnet-query-response.json": (
        800,
        "b0cf42260add535bd5056a3fa52a3467a9b0c3576ea0ab079ee2681cf03b3964",
    ),
    "discovery/mainnet-status-response.json": (
        3873,
        "4b3d7d13a63872fdf09df05a667175ac567b46365e3e513f1e40c0a9c450b7ff",
    ),
    "discovery/manifest.json": (
        2288,
        "cfc36b7248bae8a802d27a558fc76c8570c79f914dcd6b7c994ff41a394b024a",
    ),
    "queries/current-and-required-absence.graphql": (
        609,
        "8a5eeffeab5213d043ad43c8a09df6352c0be17a49d92a9dc5e8012d54196eac",
    ),
    "queries/graft-boundary-state.graphql": (
        1262,
        "93baa390e0b6a9aedde30a97b11b43bce02368e2ece21b409ee171433e0d906a",
    ),
}

EXPECTED_SOURCE_IDENTITY = {
    "observed_origin": "https://www.lodestar-dashboard.com",
    "repository": "https://github.com/nightswatchhq/lodestar",
    "revision": "18c8e56189309b1b4948bfb4992cbe12df8e4879",
    "tree": "70f3383207170dc3687628f21366c731c78ec343",
    "committed_at_utc": "2026-08-28T11:00:59Z",
    "production_revision_attested": False,
    "source_matches_observed_behavior_only": True,
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
}

EXPECTED_OBSERVED_CAPABILITIES = {
    "deployment_scoped_gateway_query_succeeded": True,
    "deployment_echo_matched": True,
    "current_head_required_absence_smoke_observed": True,
    "mainnet_current_deployment_boundary_query_succeeded": True,
    "base_current_deployment_boundary_query_succeeded": False,
    "indexer_status_discovery_succeeded": True,
}

EXPECTED_PROMOTION_GATES = {
    "production_revision_attested": False,
    "per_query_indexer_pinned": False,
    "graph_node_version_pinned": False,
    "canonical_historic_block_hash_sidecar_retained": False,
    "ancestor_deployment_query_access": False,
    "base_historical_boundary_query_access": False,
    "authoritative_logical_oracle": False,
    "required_absence_certified": False,
    "logical_history_parity": False,
    "physical_history_parity": False,
    "proof_of_indexing_parity": False,
    "final_parity_package": False,
    "production_backfill_allowed": False,
}

EXPECTED_NETWORKS = {
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
}

EXPECTED_INDEXERS = {
    "mainnet": {
        "0xf92f430dd8567b0d466358c79594ab58d919a6d4",
        "0x1b7e0068ca1d7929c8c56408d766e1510e54d98d",
        "0x326c584e0f0eab1f1f83c93cc6ae1acc0feba0bc",
        "0x4e5c87772c29381bcabc58c3f182b6633b5a274a",
        "0xfeff9093f6b32d0e5cddba743b06a1fedb87c004",
    },
    "base": {"0xf92f430dd8567b0d466358c79594ab58d919a6d4"},
}

EXPECTED_HEALTH_COUNTS = {
    "mainnet": (5, 4, 1),
    "base": (1, 1, 0),
}

CURRENT_QUERY_TOKENS = (
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
)

BOUNDARY_QUERY_TOKENS = (
    "query GraftBoundaryState($before: Int!, $after: Int!)",
    "beforeMeta: _meta(block: { number: $before })",
    "afterMeta: _meta(block: { number: $after })",
    "beforePools: pools(",
    "afterPools: pools(",
    "beforePositions: positions(",
    "afterPositions: positions(",
    "block: { number: $before }",
    "block: { number: $after }",
)

HEX_HASH_RE = re.compile(r"^0x[0-9a-f]{64}$")
INTEGER_STRING_RE = re.compile(r"^-?[0-9]+$")


class VerificationError(ValueError):
    """Raised when retained oracle evidence does not match its contract."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except json.JSONDecodeError as error:
        raise VerificationError(f"invalid JSON in {path}: {error}") from error


def require_exact_keys(value: Any, expected: set[str], context: str) -> None:
    if not isinstance(value, dict):
        raise VerificationError(f"{context} must be an object")
    actual = set(value)
    if actual != expected:
        raise VerificationError(
            f"{context} keys drift: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def regular_file(base: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise VerificationError(f"unsafe retained path: {relative}")
    path = base / relative_path
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise VerificationError(f"missing retained file: {relative}") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise VerificationError(f"retained path must be a regular non-symlink file: {relative}")
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError as error:
        raise VerificationError(f"retained path escapes oracle directory: {relative}") from error
    return path


def verify_file_locks(oracle: Path, contract: dict[str, Any]) -> None:
    expected_records = [
        {"path": path, "bytes": size, "sha256": digest}
        for path, (size, digest) in EXPECTED_FILE_LOCKS.items()
    ]
    if contract["files"] != expected_records:
        raise VerificationError("retained file lock inventory drift")

    for relative, (expected_size, expected_digest) in EXPECTED_FILE_LOCKS.items():
        path = regular_file(oracle, relative)
        payload = path.read_bytes()
        if len(payload) != expected_size:
            raise VerificationError(f"byte length drift for {relative}")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest:
            raise VerificationError(f"SHA-256 drift for {relative}: {actual_digest}")


def verify_queries(oracle: Path) -> None:
    current = regular_file(
        oracle, "queries/current-and-required-absence.graphql"
    ).read_text(encoding="utf-8")
    boundary = regular_file(oracle, "queries/graft-boundary-state.graphql").read_text(
        encoding="utf-8"
    )
    for token in CURRENT_QUERY_TOKENS:
        if token not in current:
            raise VerificationError(f"current query contract missing token: {token}")
    for token in BOUNDARY_QUERY_TOKENS:
        if token not in boundary:
            raise VerificationError(f"boundary query contract missing token: {token}")


def verify_current_response(oracle: Path, network: str) -> int:
    network_contract = EXPECTED_NETWORKS[network]
    payload = load_json(regular_file(oracle, network_contract["current_response"]))
    require_exact_keys(payload, {"data"}, f"{network} current response")
    data = payload["data"]
    require_exact_keys(
        data,
        {
            "_meta",
            "collects",
            "flashes",
            "tickHourDatas",
            "tickDayDatas",
            "positions",
            "pools",
        },
        f"{network} current data",
    )

    meta = data["_meta"]
    require_exact_keys(meta, {"block", "deployment", "hasIndexingErrors"}, f"{network} _meta")
    if meta["deployment"] != network_contract["deployment"]:
        raise VerificationError(f"{network} current deployment echo mismatch")
    if meta["hasIndexingErrors"] is not False:
        raise VerificationError(f"{network} current response has indexing errors")
    block = meta["block"]
    require_exact_keys(block, {"number", "hash", "timestamp"}, f"{network} current block")
    if not isinstance(block["number"], int) or block["number"] <= 0:
        raise VerificationError(f"{network} current block number is invalid")
    if not isinstance(block["hash"], str) or not HEX_HASH_RE.fullmatch(block["hash"]):
        raise VerificationError(f"{network} current block hash is invalid")
    if not isinstance(block["timestamp"], int) or block["timestamp"] <= 0:
        raise VerificationError(f"{network} current block timestamp is invalid")

    empty_fields = {
        "Collect": "collects",
        "Flash": "flashes",
        "TickHourData": "tickHourDatas",
    }
    for entity in network_contract["current_empty_entity_smoke"]:
        if data[empty_fields[entity]] != []:
            raise VerificationError(f"{network} {entity} current-head absence smoke drift")

    positive_fields = {
        "TickDayData": "tickDayDatas",
        "Position": "positions",
        "Pool": "pools",
    }
    for entity in network_contract["current_positive_entity_smoke"]:
        rows = data[positive_fields[entity]]
        if not isinstance(rows, list) or not rows:
            raise VerificationError(f"{network} {entity} positive smoke is empty")

    pool = data["pools"][0]
    require_exact_keys(
        pool,
        {"id", "feeGrowthGlobal0X128", "feeGrowthGlobal1X128"},
        f"{network} Pool smoke",
    )
    for field in ("feeGrowthGlobal0X128", "feeGrowthGlobal1X128"):
        if not isinstance(pool[field], str) or not INTEGER_STRING_RE.fullmatch(pool[field]):
            raise VerificationError(f"{network} Pool {field} is not an integer string")
    return block["number"]


def verify_status_response(oracle: Path, network: str, current_block: int) -> None:
    network_contract = EXPECTED_NETWORKS[network]
    payload = load_json(regular_file(oracle, network_contract["status_response"]))
    require_exact_keys(payload, {"data"}, f"{network} status response")
    data = payload["data"]
    require_exact_keys(
        data,
        {
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
        },
        f"{network} status data",
    )
    if data["ipfsHash"] != network_contract["deployment"]:
        raise VerificationError(f"{network} status deployment mismatch")
    total, healthy, unhealthy = EXPECTED_HEALTH_COUNTS[network]
    if (
        data["totalIndexers"],
        data["syncedCount"],
        data["healthyCount"],
        data["unhealthyCount"],
    ) != (total, total, healthy, unhealthy):
        raise VerificationError(f"{network} retained status counts drift")
    if data["failedCount"] != 0 or data["unreachableCount"] != 0:
        raise VerificationError(f"{network} retained status unexpectedly failed")

    indexers = data["indexers"]
    if not isinstance(indexers, list) or len(indexers) != total:
        raise VerificationError(f"{network} retained indexer list length drift")
    expected_indexers = EXPECTED_INDEXERS[network]
    actual_indexers = {item.get("indexerId") for item in indexers if isinstance(item, dict)}
    if actual_indexers != expected_indexers:
        raise VerificationError(f"{network} retained indexer identities drift")

    indexer_keys = {
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
    }
    for indexer in indexers:
        require_exact_keys(indexer, indexer_keys, f"{network} indexer")
        if indexer["network"] != network:
            raise VerificationError(f"{network} indexer network mismatch")
        if indexer["status"] != "synced" or indexer["synced"] is not True:
            raise VerificationError(f"{network} indexer is not retained as synced")
        if indexer["serveProbe"] != "alive_paid" or indexer["servable"] is not True:
            raise VerificationError(f"{network} indexer is not retained as servable")
        if indexer["networkChainHead"] < current_block:
            raise VerificationError(f"{network} status head predates retained query head")


def verify_mainnet_boundary(oracle: Path) -> None:
    boundary = EXPECTED_NETWORKS["mainnet"]["boundary"]
    payload = load_json(regular_file(oracle, boundary["response"]))
    require_exact_keys(payload, {"data"}, "mainnet boundary response")
    data = payload["data"]
    require_exact_keys(
        data,
        {
            "beforeMeta",
            "afterMeta",
            "beforePools",
            "afterPools",
            "beforePositions",
            "afterPositions",
        },
        "mainnet boundary data",
    )
    for name, expected_number in (
        ("beforeMeta", boundary["before"]),
        ("afterMeta", boundary["after"]),
    ):
        meta = data[name]
        require_exact_keys(meta, {"block", "deployment", "hasIndexingErrors"}, name)
        if meta["deployment"] != MAINNET_DEPLOYMENT or meta["hasIndexingErrors"] is not False:
            raise VerificationError(f"{name} deployment or error state drift")
        block = meta["block"]
        require_exact_keys(block, {"number", "hash", "timestamp"}, f"{name} block")
        if block != {"number": expected_number, "hash": None, "timestamp": None}:
            raise VerificationError(f"{name} retained historic block shape drift")

    for entity in ("Pools", "Positions"):
        before = data[f"before{entity}"]
        after = data[f"after{entity}"]
        if not isinstance(before, list) or not before:
            raise VerificationError(f"mainnet boundary {entity} sample is empty")
        if before != after:
            raise VerificationError(f"mainnet retained {entity} sample continuity drift")


def verify_base_boundary_refusal(oracle: Path) -> None:
    boundary = EXPECTED_NETWORKS["base"]["boundary"]
    payload = load_json(regular_file(oracle, boundary["response"]))
    require_exact_keys(payload, {"errors"}, "Base boundary refusal")
    errors = payload["errors"]
    if not isinstance(errors, list) or len(errors) != 1:
        raise VerificationError("Base boundary refusal must retain exactly one error")
    require_exact_keys(errors[0], {"message"}, "Base boundary error")
    message = errors[0]["message"]
    for fragment in (
        boundary["required_error_fragment"],
        "0xf92f430dd8567b0d466358c79594ab58d919a6d4",
        "Unavailable",
    ):
        if fragment not in message:
            raise VerificationError(f"Base boundary refusal missing fragment: {fragment}")


def verify_manifest(oracle: Path) -> None:
    manifest = load_json(regular_file(oracle, "discovery/manifest.json"))
    require_exact_keys(
        manifest,
        {"format_version", "contract_version", "observations"},
        "discovery manifest",
    )
    if manifest["format_version"] != 1 or manifest["contract_version"] != CONTRACT_VERSION:
        raise VerificationError("discovery manifest identity drift")
    observations = manifest["observations"]
    if not isinstance(observations, list) or len(observations) != 6:
        raise VerificationError("discovery manifest must retain six observations")
    by_id = {item.get("id"): item for item in observations if isinstance(item, dict)}
    expected_ids = {
        "mainnet-current-and-required-absence",
        "base-current-and-required-absence",
        "mainnet-indexer-status",
        "base-indexer-status",
        "mainnet-current-graft-boundary",
        "base-current-graft-boundary-refusal",
    }
    if set(by_id) != expected_ids or len(by_id) != len(observations):
        raise VerificationError("discovery observation identities drift")
    for observation_id, observation in by_id.items():
        network = observation["network"]
        if network not in EXPECTED_NETWORKS:
            raise VerificationError(f"unknown observation network: {network}")
        if observation["deployment"] != EXPECTED_NETWORKS[network]["deployment"]:
            raise VerificationError(f"{observation_id} deployment mismatch")
        if observation["http_status"] != 200:
            raise VerificationError(f"{observation_id} HTTP status drift")
        if not re.fullmatch(r"2026-08-28T11:[0-9]{2}:[0-9]{2}Z", observation["observed_at_utc"]):
            raise VerificationError(f"{observation_id} observation timestamp drift")

    for network in ("mainnet", "base"):
        current = by_id[f"{network}-current-and-required-absence"]
        if current["request_path"] != "queries/current-and-required-absence.graphql":
            raise VerificationError(f"{network} current request path drift")
        if current["response_path"] != EXPECTED_NETWORKS[network]["current_response"]:
            raise VerificationError(f"{network} current response path drift")
        status = by_id[f"{network}-indexer-status"]
        if status["response_path"] != EXPECTED_NETWORKS[network]["status_response"]:
            raise VerificationError(f"{network} status response path drift")

    mainnet_boundary = by_id["mainnet-current-graft-boundary"]
    base_boundary = by_id["base-current-graft-boundary-refusal"]
    for network, observation in (
        ("mainnet", mainnet_boundary),
        ("base", base_boundary),
    ):
        expected = EXPECTED_NETWORKS[network]["boundary"]
        if observation["request_path"] != "queries/graft-boundary-state.graphql":
            raise VerificationError(f"{network} boundary request path drift")
        if observation["variables"] != {"before": expected["before"], "after": expected["after"]}:
            raise VerificationError(f"{network} boundary variables drift")
        if observation["response_path"] != expected["response"]:
            raise VerificationError(f"{network} boundary response path drift")


def verify(root: Path) -> None:
    root = root.resolve()
    oracle = root / ORACLE_DIRECTORY
    contract_path = regular_file(root, str(CONTRACT_PATH))
    contract = load_json(contract_path)
    require_exact_keys(
        contract,
        {
            "format_version",
            "contract_version",
            "evidence_class",
            "purpose",
            "source_identity",
            "files",
            "observed_capabilities",
            "promotion_gates",
            "networks",
        },
        "oracle contract",
    )
    if contract["format_version"] != 1 or contract["contract_version"] != CONTRACT_VERSION:
        raise VerificationError("oracle contract identity drift")
    if contract["evidence_class"] != "retained_discovery_snapshot":
        raise VerificationError("oracle evidence class drift")
    if contract["purpose"] != (
        "Retain a fail-closed discovery snapshot for deployment-scoped logical queries "
        "without promoting it to an authoritative parity oracle."
    ):
        raise VerificationError("oracle purpose drift")
    if contract["source_identity"] != EXPECTED_SOURCE_IDENTITY:
        raise VerificationError("oracle source identity drift")
    if contract["observed_capabilities"] != EXPECTED_OBSERVED_CAPABILITIES:
        raise VerificationError("observed capability boundary drift")
    if contract["promotion_gates"] != EXPECTED_PROMOTION_GATES:
        raise VerificationError("promotion gate drift; every gate must remain false")
    if any(contract["promotion_gates"].values()):
        raise VerificationError("promotion gate must not be true in discovery evidence")
    if contract["networks"] != EXPECTED_NETWORKS:
        raise VerificationError("network oracle contract drift")

    verify_file_locks(oracle, contract)
    verify_queries(oracle)
    verify_manifest(oracle)
    current_blocks = {
        network: verify_current_response(oracle, network)
        for network in ("mainnet", "base")
    }
    for network, current_block in current_blocks.items():
        verify_status_response(oracle, network, current_block)
    verify_mainnet_boundary(oracle)
    verify_base_boundary_refusal(oracle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        verify(args.root)
    except (OSError, VerificationError) as error:
        print(f"Uniswap V3 logical-oracle verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified 9 retained oracle files, exact deployment echoes, current-head "
        "absence/positive smokes, mainnet boundary response, Base expected refusal, "
        "and 13 fail-closed promotion gates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
