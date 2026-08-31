#!/usr/bin/env python3
"""Build or verify the complete path-qualified Uniswap V3 Initialize v2 contract."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/pool-initialize/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-initialize/v2"
HANDLER_ID = "Pool.handleInitialize"
HANDLER_EXPORT = "handleInitialize"

IMPLEMENTATION_BASE_COMMIT = "afaf3af9c25db029091d7699befe557276a442c7"
IMPLEMENTATION_BASE_TREE = "5c2e8f38721448039f09e06b195e019d11332d3f"

FACTORY_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-factory-static-v2.py"
FACTORY_VERIFIER_SHA256 = "f735dc4c90c8b58c68664d2ba5c3c761d9f143b54cd4af9db9e0d8f5e2c94122"
FACTORY_CONTRACT_PATH = Path("uniswap-v3/factory-static/v2/contract.json")
FACTORY_CONTRACT_SHA256 = "7437a95b9b1cff1c248b0685f59ec098a77fffe0ea4166b8f930a32ba6288118"
FACTORY_CONTRACT_CANONICAL_SHA256 = "adcd236a56b7a5627f956b23ba44daaeb6c58630b853ddf232516fec964373ef"
FACTORY_CONTRACT_VERSION = "uniswap-v3-factory-static/v2"

INITIALIZE_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-initialize.py"
INITIALIZE_VERIFIER_SHA256 = "5de73a42431c0d26dea48c6c570a58626532be14288cd16da20bcd1f2710d21d"
INITIALIZE_CONTRACT_PATH = Path("uniswap-v3/pool-initialize/v1/contract.json")
INITIALIZE_CONTRACT_SHA256 = "63bbec1b3190f1ccd54f9c9cb9a29bbd5a7d730be0165a2277412ea0b3adea14"
INITIALIZE_CONTRACT_CANONICAL_SHA256 = "37439929c810e594ab8977a4691e59fcd56ba63733db4ed90ed297505476d602"
INITIALIZE_CONTRACT_VERSION = "uniswap-v3-pool-initialize-semantics/v1"

RUNTIME_PATH = Path("scripts/uniswap_v3_wat_runtime.py")
RUNTIME_SHA256 = "bd555b5d44bed144777e35b361fcb63e275d7f21b774db3ffe0e08bef3bf4411"

TARGET_ENTITY_FIELDS = {
    "Bundle": ("id", "ethPriceUSD"),
    "Pool": (
        "id", "createdAtTimestamp", "createdAtBlockNumber", "token0", "token1",
        "feeTier", "liquidity", "sqrtPrice", "feeGrowthGlobal0X128",
        "feeGrowthGlobal1X128", "token0Price", "token1Price", "tick",
        "observationIndex", "volumeToken0", "volumeToken1", "volumeUSD",
        "untrackedVolumeUSD", "feesUSD", "txCount", "collectedFeesToken0",
        "collectedFeesToken1", "collectedFeesUSD", "totalValueLockedToken0",
        "totalValueLockedToken1", "totalValueLockedETH", "totalValueLockedUSD",
        "totalValueLockedUSDUntracked", "liquidityProviderCount", "poolHourData",
        "poolDayData", "mints", "burns", "swaps", "collects", "ticks",
    ),
    "PoolDayData": (
        "id", "date", "pool", "liquidity", "sqrtPrice", "token0Price",
        "token1Price", "tick", "feeGrowthGlobal0X128", "feeGrowthGlobal1X128",
        "tvlUSD", "volumeToken0", "volumeToken1", "volumeUSD", "feesUSD",
        "txCount", "open", "high", "low", "close",
    ),
    "PoolHourData": (
        "id", "periodStartUnix", "pool", "liquidity", "sqrtPrice",
        "token0Price", "token1Price", "tick", "feeGrowthGlobal0X128",
        "feeGrowthGlobal1X128", "tvlUSD", "volumeToken0", "volumeToken1",
        "volumeUSD", "feesUSD", "txCount", "open", "high", "low", "close",
    ),
    "Token": (
        "id", "symbol", "name", "decimals", "totalSupply", "volume",
        "volumeUSD", "untrackedVolumeUSD", "feesUSD", "txCount", "poolCount",
        "totalValueLocked", "totalValueLockedUSD", "totalValueLockedUSDUntracked",
        "derivedETH", "whitelistPools", "tokenDayData",
    ),
}

DAY_INVOCATIONS = (
    "id", "date", "pool", "volumeToken0", "volumeToken1", "volumeUSD",
    "feesUSD", "txCount", "feeGrowthGlobal0X128", "feeGrowthGlobal1X128",
    "open", "high", "low", "close", "high", "low", "liquidity",
    "sqrtPrice", "feeGrowthGlobal0X128", "feeGrowthGlobal1X128",
    "token0Price", "token1Price", "tick", "tvlUSD", "txCount",
)
HOUR_INVOCATIONS = (
    "id", "periodStartUnix", "pool", "volumeToken0", "volumeToken1",
    "volumeUSD", "txCount", "feesUSD", "feeGrowthGlobal0X128",
    "feeGrowthGlobal1X128", "open", "high", "low", "close", "high", "low",
    "liquidity", "sqrtPrice", "token0Price", "token1Price",
    "feeGrowthGlobal0X128", "feeGrowthGlobal1X128", "close", "tick", "tvlUSD",
    "txCount",
)

WINDOW_ALWAYS = {
    "liquidity": "Pool.liquidity getter result",
    "sqrtPrice": "Pool.sqrtPrice getter result",
    "token0Price": "Pool.token0Price getter result",
    "token1Price": "Pool.token1Price getter result",
    "feeGrowthGlobal0X128": "Pool.feeGrowthGlobal0X128 getter result",
    "feeGrowthGlobal1X128": "Pool.feeGrowthGlobal1X128 getter result",
    "tvlUSD": "Pool.totalValueLockedUSD getter result",
}
DAY_CREATE_ONLY = {
    "id": "hex(event.address) plus '-' plus signed-i32 timestamp quotient by 86400",
    "date": "signed-i32 timestamp quotient by 86400 multiplied by 86400",
    "pool": "Pool.id getter result",
    "volumeToken0": "ZERO_BD",
    "volumeToken1": "ZERO_BD",
    "volumeUSD": "ZERO_BD",
    "feesUSD": "ZERO_BD",
    "open": "Pool.token0Price getter result",
    "close": "Pool.token0Price getter result",
}
HOUR_CREATE_ONLY = {
    "id": "hex(event.address) plus '-' plus signed-i32 timestamp quotient by 3600",
    "periodStartUnix": "signed-i32 timestamp quotient by 3600 multiplied by 3600",
    "pool": "Pool.id getter result",
    "volumeToken0": "ZERO_BD",
    "volumeToken1": "ZERO_BD",
    "volumeUSD": "ZERO_BD",
    "feesUSD": "ZERO_BD",
    "open": "Pool.token0Price getter result",
}

EXPECTED_ENTITY_COUNTS = {
    "Bundle": 2,
    "Pool": 36,
    "PoolDayData": 20,
    "PoolHourData": 20,
    "Token": 17,
}
EXPECTED_SAVE_TARGETS = ("Bundle", "PoolDayData", "PoolHourData", "Token")

TRUE_FLAGS = (
    "exact_factory_v2_root_verified",
    "exact_initialize_v1_root_verified",
    "all_transitive_inputs_digest_bound",
    "all_eight_initialize_modules_exactly_bound",
    "all_reachable_function_bodies_bound",
    "all_reachable_setter_save_remove_helper_and_indirect_sites_accounted",
    "exact_three_save_five_no_pool_save_split_verified",
    "bundle_pool_window_and_token_transition_ledgers_complete",
    "handler_save_and_window_store_get_call_order_bound",
    "high_low_create_and_comparator_return_controlled_write_sites_bound",
    "big_int_plus_write_call_shape_bound",
    "all_twenty_interval_catalog_fields_classified_including_nullable_tick",
    "all_eight_segments_have_299_static_field_outcomes",
    "all_twenty_eight_recursive_segment_diffs_present",
    "path_qualified_complete_static_initialize_contract",
)

FALSE_FLAGS = (
    "imported_host_semantics_rederived",
    "big_decimal_numeric_semantics_rederived",
    "static_array_safe",
    "total_supply_erc20_result_data_decoded",
    "imported_numeric_semantics_complete",
    "imported_big_decimal_comparator_semantics_complete",
    "imported_big_int_plus_numeric_semantics_complete",
    "graph_store_host_semantics_complete",
    "window_helper_pool_store_get_return_visibility_or_version_proven",
    "imported_graph_store_read_after_write_semantics_complete",
    "graph_store_persistence_complete",
    "graph_store_persistence_proven",
    "graph_handler_rollback_proven",
    "graph_handler_rollback_proven_by_retained_wat",
    "actual_historic_handler_outcomes_bound",
    "pool_non_flash_handler_semantics_complete",
    "pool_mint_semantics_complete",
    "pool_burn_semantics_complete",
    "pool_swap_semantics_complete",
    "pool_complete_entity_history",
    "complete_pool_entity_history",
    "complete_bundle_entity_history",
    "complete_token_entity_history",
    "complete_window_entity_history",
    "complete_pool_or_factory_history",
    "all_manifest_handler_field_semantics_complete",
    "all_stored_fields_exact",
    "all_pairwise_complete_writer_semantic_diffs_present",
    "contract_call_semantics_complete_for_all_handlers",
    "combined_handler_order_implemented",
    "combined_execution_order_proven",
    "dynamic_datasource_stage_order_implemented",
    "post_fatal_execution_modeled",
    "source_package_identity_proven",
    "runtime_population_complete",
    "boundary_continuity_complete",
    "boundary_continuity_proven",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "parity_proven",
    "live_evidence_complete",
    "writer_package_consumes_projection",
    "checkpoint_authority",
    "backfill_ready",
    "production_ready",
    "readiness_complete",
    "issue_37_acceptance_criterion_complete",
    "issue_38_acceptance_criterion_complete",
    "issue_checkbox_completed",
    "all_twenty_interval_fields_non_null_or_required",
)


class VerificationError(RuntimeError):
    """Raised when exact retained evidence does not reproduce this contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error


def load_module(name: str, path: Path, digest: str) -> Any:
    require(path.is_file(), f"required verifier missing: {path}")
    require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FACTORY = load_module(
    "uniswap_v3_factory_static_v2_for_pool_initialize_v2",
    FACTORY_VERIFIER_PATH,
    FACTORY_VERIFIER_SHA256,
)
INITIALIZE = load_module(
    "uniswap_v3_pool_initialize_v1_for_v2",
    INITIALIZE_VERIFIER_PATH,
    INITIALIZE_VERIFIER_SHA256,
)
WRITER = INITIALIZE.WRITER
RUNTIME = FACTORY.RUNTIME


def normalized(line: str) -> str:
    return INITIALIZE.normalized(line)


def call_name(line: str) -> str | None:
    return INITIALIZE.call_name(line)


def decoded_constant(line: str, memory: bytearray) -> str | None:
    return INITIALIZE.decoded_constant(line, memory)


def function_sha256(function: Any) -> str:
    return INITIALIZE.function_sha256(function)


def json_diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    return INITIALIZE.json_diff_paths(left, right, path)


def _bind(root: Path, relative: Path, raw_digest: str, canonical_digest: str | None = None) -> Any:
    path = root / relative
    require(path.is_file(), f"required source missing: {relative}")
    require(raw_sha256(path) == raw_digest, f"raw source digest drift: {relative}")
    if canonical_digest is None:
        return None
    value = load_json(path)
    require(canonical_sha256(value) == canonical_digest, f"canonical source digest drift: {relative}")
    return value


def _merge_transitive_inputs(root: Path) -> list[dict[str, Any]]:
    roots = (FACTORY_CONTRACT_PATH, INITIALIZE_CONTRACT_PATH)
    records: dict[str, dict[str, Any]] = {}
    for contract_root in roots:
        pending = [contract_root]
        visited: set[str] = set()
        while pending:
            contract_path = pending.pop()
            contract_key = contract_path.as_posix()
            if contract_key in visited:
                continue
            visited.add(contract_key)
            contract = load_json(root / contract_path)
            require(isinstance(contract, dict), f"transitive contract is not an object: {contract_path}")
            for name, record in sorted(contract.get("source_contracts", {}).items()):
                require(isinstance(record, dict) and isinstance(record.get("path"), str), f"invalid source-contract record: {contract_path}:{name}")
                relative = Path(record["path"])
                require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe transitive input path: {relative}")
                digest = record.get("raw_sha256")
                require(isinstance(digest, str) and len(digest) == 64, f"missing transitive raw digest: {relative}")
                _bind(root, relative, digest, record.get("canonical_sha256"))
                key = relative.as_posix()
                material: dict[str, Any] = {"path": key, "raw_sha256": digest}
                for optional in ("canonical_sha256", "contract_version"):
                    if optional in record:
                        material[optional] = record[optional]
                if key not in records:
                    records[key] = {**material, "declared_by": []}
                else:
                    for material_name, value in material.items():
                        require(records[key].get(material_name, value) == value, f"conflicting transitive authority: {key}:{material_name}")
                        records[key][material_name] = value
                records[key]["declared_by"].append([contract_key, name])
                if relative.suffix == ".json":
                    candidate = load_json(root / relative)
                    if isinstance(candidate, dict) and "source_contracts" in candidate:
                        pending.append(relative)

    direct = (
        (FACTORY_VERIFIER_PATH.relative_to(REPOSITORY), FACTORY_VERIFIER_SHA256, None),
        (FACTORY_CONTRACT_PATH, FACTORY_CONTRACT_SHA256, FACTORY_CONTRACT_CANONICAL_SHA256),
        (INITIALIZE_VERIFIER_PATH.relative_to(REPOSITORY), INITIALIZE_VERIFIER_SHA256, None),
        (INITIALIZE_CONTRACT_PATH, INITIALIZE_CONTRACT_SHA256, INITIALIZE_CONTRACT_CANONICAL_SHA256),
        (RUNTIME_PATH, RUNTIME_SHA256, None),
    )
    for relative, digest, canonical in direct:
        _bind(root, relative, digest, canonical)
        key = relative.as_posix()
        material: dict[str, Any] = {"path": key, "raw_sha256": digest}
        if canonical is not None:
            material["canonical_sha256"] = canonical
        if key in records:
            require(records[key]["raw_sha256"] == digest, f"direct/transitive digest conflict: {key}")
            records[key].update(material)
        else:
            records[key] = {**material, "declared_by": []}
        records[key]["declared_by"].append([CONTRACT_PATH.as_posix(), "direct_root"])

    output = []
    for key in sorted(records):
        record = records[key]
        record["declared_by"] = sorted({tuple(item) for item in record["declared_by"]})
        record["declared_by"] = [list(item) for item in record["declared_by"]]
        output.append(record)
    require(len(output) >= 30, "combined transitive input manifest unexpectedly small")
    return output


def _function_by_suffix(context: dict[str, Any], suffix: str) -> Any:
    matches = [function for name, function in context["functions"].items() if name.endswith(suffix)]
    require(len(matches) == 1, f"{context['mapping_cid']} function suffix count drift: {suffix}")
    return matches[0]


def _last_decoded_before(
    context: dict[str, Any],
    function: Any,
    index: int,
    expected: str,
) -> dict[str, Any]:
    decoded = [
        {
            "relative_wat_line": candidate,
            "value": value,
        }
        for candidate in range(max(0, index - 12), index)
        if (value := decoded_constant(function.lines[candidate], context["memory"])) is not None
    ]
    require(decoded and decoded[-1]["value"] == expected, f"{context['mapping_cid']} {expected} literal binding drift")
    return decoded[-1]


def _pool_store_get_path(
    context: dict[str, Any],
    function: Any,
    entity: str,
) -> dict[str, Any]:
    store_get = "~lib/@graphprotocol/graph-ts/index/store.get"
    generation = context["profile"]["control_generation"]
    helper_store_gets = [
        index
        for index, line in enumerate(function.lines)
        if call_name(line) == store_get
    ]
    if generation == "modern":
        require(len(helper_store_gets) == 2, f"{context['mapping_cid']} {entity} store.get count drift")
        pool_get, interval_get = helper_store_gets
        pool_literal = _last_decoded_before(context, function, pool_get, "Pool")
        interval_literal = _last_decoded_before(context, function, interval_get, entity)
        load_binding: dict[str, Any] | None = None
        path_kind = "direct_helper_store_get"
        pool_get_function = function.name
    else:
        require(len(helper_store_gets) == 1, f"{context['mapping_cid']} {entity} child store.get count drift")
        interval_get = helper_store_gets[0]
        interval_literal = _last_decoded_before(context, function, interval_get, entity)
        pool_load_calls = [
            index
            for index, line in enumerate(function.lines)
            if (call_name(line) or "").endswith("schema/Pool.load")
        ]
        require(len(pool_load_calls) == 1, f"{context['mapping_cid']} {entity} Pool.load count drift")
        pool_load = _function_by_suffix(context, "schema/Pool.load")
        load_store_gets = [
            index
            for index, line in enumerate(pool_load.lines)
            if call_name(line) == store_get
        ]
        require(len(load_store_gets) == 1, f"{context['mapping_cid']} Pool.load store.get count drift")
        pool_get = load_store_gets[0]
        pool_literal = _last_decoded_before(context, pool_load, pool_get, "Pool")
        load_binding = {
            "helper_pool_load_relative_wat_line": pool_load_calls[0],
            "helper_pool_load_call_target": call_name(function.lines[pool_load_calls[0]]),
            "pool_load_function": pool_load.name,
            "pool_load_function_index": pool_load.function_index,
            "pool_load_body_sha256": function_sha256(pool_load),
        }
        path_kind = "helper_pool_load_then_store_get"
        pool_get_function = pool_load.name

    return {
        "path_kind": path_kind,
        "pool_entity_literal": pool_literal,
        "pool_store_get_function": pool_get_function,
        "pool_store_get_relative_wat_line": pool_get,
        "pool_store_get_call_target": store_get,
        "pool_load_binding": load_binding,
        "interval_entity_literal": interval_literal,
        "interval_store_get_relative_wat_line": interval_get,
        "interval_store_get_call_target": store_get,
        "helper_reaches_exact_pool_store_get": True,
        "pool_store_get_return_visibility_or_version_proven": False,
        "imported_graph_store_read_after_write_semantics_complete": False,
    }


def _tick_setter_proof(context: dict[str, Any]) -> dict[str, Any]:
    function = _function_by_suffix(context, "schema/Pool#set:tick")
    generation = context["profile"]["control_generation"]
    calls = [
        {
            "relative_wat_line": index,
            "call_target": target,
        }
        for index, line in enumerate(function.lines)
        if (target := call_name(line)) is not None
    ]
    tick_literals = [
        index
        for index, line in enumerate(function.lines)
        if decoded_constant(line, context["memory"]) == "tick"
    ]
    require(len(tick_literals) == 2, f"{context['mapping_cid']} nullable tick literal count drift")
    branch_candidates = [
        index + 1
        for index in range(len(function.lines) - 1)
        if normalized(function.lines[index]) == "local.get $p1"
        and normalized(function.lines[index + 1]).startswith("if ")
    ]
    require(len(branch_candidates) == 1, f"{context['mapping_cid']} nullable tick branch shape drift")
    branch = branch_candidates[0]
    if generation == "legacy":
        value_calls = [item for item in calls if item["call_target"].endswith("Value.fromBigInt")]
        set_calls = [item for item in calls if item["call_target"].endswith(">#set")]
        null_calls = [item for item in calls if item["call_target"].endswith("Entity#unset")]
        require((len(value_calls), len(set_calls), len(null_calls)) == (1, 1, 1), f"{context['mapping_cid']} legacy tick branch drift")
        null_branch_effect = "generated Entity#unset call for tick"
        null_branch_calls = null_calls
    else:
        map_set = INITIALIZE.MODERN_ENTITY_MAP_SET_CALL
        set_calls = [item for item in calls if item["call_target"] == map_set]
        require(len(set_calls) == 2, f"{context['mapping_cid']} modern tick branch map-set count drift")
        require(not [item for item in calls if "unset" in item["call_target"]], f"{context['mapping_cid']} modern tick unset drift")
        null_branch_effect = "generated null-Value TypedMap#set call for tick"
        null_branch_calls = [set_calls[1]]

    return {
        "function": function.name,
        "function_index": function.function_index,
        "body_sha256": function_sha256(function),
        "branch_relative_wat_line": branch,
        "decoded_tick_literal_relative_wat_lines": tick_literals,
        "non_null_branch_effect": "generated BigInt-Value write for tick",
        "null_branch_effect": null_branch_effect,
        "null_branch_calls": null_branch_calls,
        "nullable_non_null_and_null_or_unset_branches_bound": True,
        "imported_numeric_semantics_complete": False,
        "graph_store_host_semantics_complete": False,
    }


def _window_control_proofs(
    context: dict[str, Any],
    function: Any,
    invocations: list[dict[str, Any]],
    store_path: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    depths = INITIALIZE.V2.wat_control_depths(function.lines)
    interval_get = store_path["interval_store_get_relative_wat_line"]
    require(
        normalized(function.lines[interval_get + 1]).startswith("local.tee ")
        and normalized(function.lines[interval_get + 2]) == "i32.eqz"
        and normalized(function.lines[interval_get + 3]).startswith("if "),
        f"{cid} missing interval-row branch drift",
    )
    missing_if = interval_get + 3
    missing_end = INITIALIZE.V2.matching_wat_end(
        function.lines,
        missing_if,
        f"{cid} missing interval-row branch",
    )

    controls: dict[str, Any] = {}
    if generation == "legacy":
        comparator_targets = {
            "high": "~lib/@graphprotocol/graph-ts/index/BigDecimal#gt",
            "low": "~lib/@graphprotocol/graph-ts/index/BigDecimal#lt",
        }
        comparator_sites = {
            field: [
                index
                for index, line in enumerate(function.lines)
                if call_name(line) == target
            ]
            for field, target in comparator_targets.items()
        }
    else:
        compare_target = "~lib/@graphprotocol/graph-ts/common/numbers/BigDecimal.compare"
        sites = [
            index
            for index, line in enumerate(function.lines)
            if call_name(line) == compare_target
        ]
        require(len(sites) == 2, f"{cid} modern comparator count drift")
        comparator_targets = {"high": compare_target, "low": compare_target}
        comparator_sites = {"high": [sites[0]], "low": [sites[1]]}

    for field, expected_control in (("high", 1), ("low", -1)):
        field_invocations = [item for item in invocations if item["field"] == field]
        require(len(field_invocations) == 2, f"{cid} {field} setter count drift")
        create_setter, later_setter = field_invocations
        require(len(comparator_sites[field]) == 1, f"{cid} {field} comparator count drift")
        comparator = comparator_sites[field][0]
        if generation == "legacy":
            control_if = comparator + 1
            require(normalized(function.lines[control_if]).startswith("if "), f"{cid} {field} comparator control drift")
            return_control = "direct comparator return truthiness"
        else:
            control_if = comparator + 3
            require(
                normalized(function.lines[comparator + 1]) == f"i32.const {expected_control}"
                and normalized(function.lines[comparator + 2]) == "i32.eq"
                and normalized(function.lines[control_if]).startswith("if "),
                f"{cid} {field} comparator equality-control drift",
            )
            return_control = f"comparator return equal to {expected_control}"
        control_end = INITIALIZE.V2.matching_wat_end(
            function.lines,
            control_if,
            f"{cid} {field} comparator-return branch",
        )
        require(
            missing_if < create_setter["relative_wat_line"] < missing_end < comparator
            < later_setter["relative_wat_line"] < control_end,
            f"{cid} {field} create/comparator setter order drift",
        )
        require(
            depths[create_setter["relative_wat_line"]] == depths[missing_if] + 1
            and depths[later_setter["relative_wat_line"]] == depths[control_if] + 1,
            f"{cid} {field} branch nesting drift",
        )
        controls[field] = {
            "missing_row_branch_if_relative_wat_line": missing_if,
            "missing_row_branch_end_relative_wat_line": missing_end,
            "missing_row_create_setter": create_setter,
            "comparator_call_relative_wat_line": comparator,
            "comparator_call_target": comparator_targets[field],
            "comparator_return_control": return_control,
            "comparator_control_if_relative_wat_line": control_if,
            "comparator_control_end_relative_wat_line": control_end,
            "comparator_return_controlled_setter": later_setter,
            "missing_row_create_setter_is_unconditional_within_missing_branch": True,
            "separate_comparator_return_controls_later_setter": True,
            "create_and_later_setter_sites_can_both_occur_on_missing_row_path": True,
            "imported_big_decimal_comparator_semantics_complete": False,
        }

    plus_sites = [
        index
        for index, line in enumerate(function.lines)
        if (call_name(line) or "").endswith("BigInt#plus")
    ]
    tx_count_invocations = [item for item in invocations if item["field"] == "txCount"]
    require(len(plus_sites) == 1 and len(tx_count_invocations) == 2, f"{cid} txCount plus/write count drift")
    plus = plus_sites[0]
    one_bi_operand_instruction = normalized(function.lines[plus - 1])
    require(one_bi_operand_instruction.startswith("global.get "), f"{cid} txCount ONE_BI operand shape drift")
    require(
        tx_count_invocations[0]["relative_wat_line"] < plus < tx_count_invocations[1]["relative_wat_line"],
        f"{cid} txCount plus/write order drift",
    )
    plus_proof = {
        "call_relative_wat_line": plus,
        "call_target": call_name(function.lines[plus]),
        "one_bi_operand_instruction": one_bi_operand_instruction,
        "operand_and_result_slice_sha256": canonical_sha256(
            [normalized(line) for line in function.lines[max(0, plus - 24) : tx_count_invocations[1]["relative_wat_line"] + 1]]
        ),
        "existing_or_zero_read_precedes_call": True,
        "one_bi_operand_precedes_call": True,
        "call_result_written_by_final_tx_count_setter": True,
        "final_tx_count_setter": tx_count_invocations[1],
        "imported_big_int_plus_numeric_semantics_complete": False,
    }
    return controls, plus_proof


def _window_invocations(context: dict[str, Any], entity: str) -> dict[str, Any]:
    suffix = "updatePoolDayData" if entity == "PoolDayData" else "updatePoolHourData"
    expected = DAY_INVOCATIONS if entity == "PoolDayData" else HOUR_INVOCATIONS
    function = _function_by_suffix(context, suffix)
    generation = context["profile"]["control_generation"]
    fields = set(TARGET_ENTITY_FIELDS[entity])
    invocations: list[dict[str, Any]] = []

    if generation == "legacy":
        for index, line in enumerate(function.lines):
            target = call_name(line)
            if target is None:
                continue
            if target.endswith("schema/PoolDayData#constructor"):
                field = "id"
            elif "#set:" in target:
                field = target.rsplit("#set:", 1)[1]
                if field not in fields:
                    continue
            else:
                continue
            invocations.append(
                {
                    "relative_wat_line": index,
                    "field": field,
                    "call_target": target,
                    "receiver_context": entity,
                    "operand_slice_sha256": canonical_sha256(
                        [normalized(item) for item in function.lines[max(0, index - 5) : index + 1]]
                    ),
                }
            )
    else:
        map_set = INITIALIZE.MODERN_ENTITY_MAP_SET_CALL
        for index, line in enumerate(function.lines):
            target = call_name(line)
            field: str | None = None
            if target == map_set:
                candidates = [
                    decoded_constant(candidate, context["memory"])
                    for candidate in function.lines[:index]
                ]
                field = next((candidate for candidate in reversed(candidates) if candidate in fields), None)
                require(field is not None, f"{entity} modern map-set decoded key missing at {index}")
            elif target is not None and target.endswith("schema/Pool#set:tick"):
                field = "tick"
            if field is None:
                continue
            invocations.append(
                {
                    "relative_wat_line": index,
                    "field": field,
                    "call_target": target,
                    "receiver_context": entity,
                    "operand_slice_sha256": canonical_sha256(
                        [normalized(item) for item in function.lines[max(0, index - 20) : index + 1]]
                    ),
                }
            )

    actual = tuple(item["field"] for item in invocations)
    require(actual == expected, f"{context['mapping_cid']} {entity} expanded invocation sequence drift: {actual}")
    save_targets = [
        (index, call_name(line))
        for index, line in enumerate(function.lines)
        if (call_name(line) or "").endswith(f"schema/{entity}#save")
    ]
    require(len(save_targets) == 1, f"{context['mapping_cid']} {entity} save count drift")
    store_path = _pool_store_get_path(context, function, entity)
    high_low_control, plus_proof = _window_control_proofs(
        context,
        function,
        invocations,
        store_path,
    )
    return {
        "entity": entity,
        "function": function.name,
        "function_index": function.function_index,
        "body_sha256": function_sha256(function),
        "expanded_field_invocation_count": len(invocations),
        "expanded_field_invocation_sequence": list(actual),
        "expanded_field_invocation_ledger_sha256": canonical_sha256(invocations),
        "invocations": invocations,
        "potential_lexical_invocation_sites_not_one_execution_trace": True,
        "save_relative_wat_line": save_targets[0][0],
        "save_call_target": save_targets[0][1],
        "pool_store_get_path": store_path,
        "high_low_write_control": high_low_control,
        "tx_count_big_int_plus_write": plus_proof,
        "nullable_tick_setter": _tick_setter_proof(context),
        "create_existing_comparator_and_snapshot_paths_digest_bound": True,
        "imported_numeric_semantics_complete": False,
        "imported_big_decimal_comparator_semantics_complete": False,
        "imported_big_int_plus_numeric_semantics_complete": False,
        "pool_store_get_return_visibility_or_version_proven": False,
    }


def _site_ledgers(context: dict[str, Any], parent_proof: dict[str, Any]) -> dict[str, Any]:
    functions = context["functions"]
    reachable = sorted(
        WRITER.reachable_functions(
            functions,
            context["handler"],
            tuple(context["indirect_targets"]),
        )
    )
    body_bindings = [
        {
            "function": name,
            "function_index": functions[name].function_index,
            "body_sha256": function_sha256(functions[name]),
        }
        for name in reachable
    ]
    calls = [
        {
            "function": name,
            "relative_wat_line": index,
            "call_target": target,
        }
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if (target := call_name(line)) is not None
    ]
    generation = context["profile"]["control_generation"]
    map_set = (
        INITIALIZE.MODERN_ENTITY_MAP_SET_CALL
        if generation == "modern"
        else INITIALIZE.LEGACY_ENTITY_MAP_SET_CALL
    )
    typed_map_sites = [item for item in calls if item["call_target"] == map_set]
    setter_sites = [
        item
        for item in calls
        if "#set:" in item["call_target"] or item["call_target"] == map_set
    ]
    save_sites = [item for item in calls if re.search(r"schema/[^/]+#save$", item["call_target"])]
    helper_sites = [
        item
        for item in calls
        if item["call_target"].startswith(("src/utils/intervalUpdates/", "src/utils/pricing/"))
    ]
    remove_sites = [item for item in calls if "store.remove" in item["call_target"]]
    indirect_sites = [
        {
            "function": name,
            "relative_wat_line": index,
            "instruction": normalized(line),
        }
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if "call_indirect" in line
    ]
    direct_writes = [
        {
            "function": name,
            "relative_wat_line": index,
            "instruction": normalized(line),
        }
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if RUNTIME.is_direct_memory_write(line, normalized)
    ]
    domain_calls = [
        item
        for item in calls
        if item["call_target"].startswith(
            ("src/types/schema/", "generated/schema/", "src/utils/intervalUpdates/", "src/utils/pricing/")
        )
    ]
    ethereum_calls = [item for item in calls if "ethereum.call" in item["call_target"]]
    transitive_store = INITIALIZE.recompute_transitive_store_evidence(context)
    store_callsites = WRITER.extract_store_set_callsites(functions, context["memory"])
    WRITER.require_fixed_callsites(store_callsites, f"{context['mapping_cid']} Initialize v2")
    reachable_store_callsites = [
        {
            "site_id": item["site_id"],
            "function": item["function"],
            "ordinal_in_function": item["ordinal_in_function"],
            "wat_line": item["wat_line"],
            "target": item["target"],
            "target_literal_pointer": item["target_literal_pointer"],
            "target_argument_shape": item["target_argument_shape"],
        }
        for item in store_callsites
        if item["function"] in reachable
    ]
    require(not remove_sites, f"{context['mapping_cid']} reachable store.remove call")
    require(not ethereum_calls, f"{context['mapping_cid']} reachable ethereum.call")
    expected_targets = list(EXPECTED_SAVE_TARGETS)
    if parent_proof["persistence"]["profile_expected_to_persist"]:
        expected_targets.append("Pool")
    require(
        transitive_store["reachable_store_set_targets"] == sorted(expected_targets),
        f"{context['mapping_cid']} reachable store target drift",
    )
    expected_save_count = 6 if "Pool" in expected_targets else 5
    require(len(save_sites) == expected_save_count, f"{context['mapping_cid']} save invocation count drift")
    require(
        len(indirect_sites) == (1 if generation == "modern" else 0),
        f"{context['mapping_cid']} reachable indirect-call count drift",
    )
    require(
        len(context["indirect_targets"]) == 1,
        f"{context['mapping_cid']} closed table target count drift",
    )
    return {
        "reachable_function_count": len(reachable),
        "reachable_function_body_bindings_sha256": canonical_sha256(body_bindings),
        "reachable_function_body_bindings": body_bindings,
        "all_reachable_function_bodies_bound": True,
        "all_direct_callsite_count": len(calls),
        "all_direct_callsite_inventory_sha256": canonical_sha256(calls),
        "typed_map_set_site_count": len(typed_map_sites),
        "typed_map_set_sites": typed_map_sites,
        "schema_setter_and_typed_map_set_site_count": len(setter_sites),
        "schema_setter_and_typed_map_set_sites": setter_sites,
        "schema_save_invocation_count": len(save_sites),
        "schema_save_invocations": save_sites,
        "domain_helper_invocation_count": len(helper_sites),
        "domain_helper_invocations": helper_sites,
        "schema_and_domain_callsite_count": len(domain_calls),
        "schema_and_domain_callsite_inventory_sha256": canonical_sha256(domain_calls),
        "reachable_store_set_site_count": len(reachable_store_callsites),
        "reachable_store_set_sites": reachable_store_callsites,
        "reachable_store_remove_call_count": 0,
        "reachable_store_remove_calls": [],
        "reachable_ethereum_call_count": 0,
        "reachable_ethereum_calls": [],
        "reachable_call_indirect_count": len(indirect_sites),
        "reachable_call_indirect_sites": indirect_sites,
        "closed_indirect_table_targets": list(context["indirect_targets"]),
        "reachable_direct_memory_write_site_count": len(direct_writes),
        "reachable_direct_memory_write_site_inventory_sha256": canonical_sha256(direct_writes),
        "transitive_store_evidence": transitive_store,
        "all_reachable_setter_save_remove_helper_and_indirect_sites_accounted": True,
    }


def _handler_field_invocations(context: dict[str, Any]) -> dict[str, Any]:
    handler = context["handler"]
    generation = context["profile"]["control_generation"]
    fields = {"sqrtPrice", "tick", "ethPriceUSD", "derivedETH"}
    rows: list[dict[str, Any]] = []
    if generation == "legacy":
        for index, line in enumerate(handler.lines):
            target = call_name(line)
            if target is None or "#set:" not in target:
                continue
            field = target.rsplit("#set:", 1)[1]
            if field not in fields:
                continue
            entity = "Pool" if field in {"sqrtPrice", "tick"} else ("Bundle" if field == "ethPriceUSD" else "Token")
            rows.append({"relative_wat_line": index, "entity": entity, "field": field, "call_target": target})
    else:
        map_set = INITIALIZE.MODERN_ENTITY_MAP_SET_CALL
        for index, line in enumerate(handler.lines):
            target = call_name(line)
            field: str | None = None
            if target == map_set:
                candidates = [decoded_constant(candidate, context["memory"]) for candidate in handler.lines[:index]]
                field = next((candidate for candidate in reversed(candidates) if candidate in fields), None)
                require(field is not None, f"{context['mapping_cid']} modern handler field key missing at {index}")
            elif target is not None and target.endswith("schema/Pool#set:tick"):
                field = "tick"
            if field is None:
                continue
            entity = "Pool" if field in {"sqrtPrice", "tick"} else ("Bundle" if field == "ethPriceUSD" else "Token")
            rows.append({"relative_wat_line": index, "entity": entity, "field": field, "call_target": target})
    require(
        [(item["entity"], item["field"]) for item in rows]
        == [
            ("Pool", "sqrtPrice"),
            ("Pool", "tick"),
            ("Bundle", "ethPriceUSD"),
            ("Token", "derivedETH"),
            ("Token", "derivedETH"),
        ],
        f"{context['mapping_cid']} handler field invocation sequence drift",
    )
    return {
        "expanded_field_invocation_count": len(rows),
        "expanded_field_invocation_ledger_sha256": canonical_sha256(rows),
        "invocations": rows,
        "potential_lexical_invocation_sites_not_one_execution_trace": True,
    }


def prove_complete_context(
    context: dict[str, Any],
    parent_proof: dict[str, Any],
    field_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile = context["profile"]
    require(parent_proof["mapping_cid"] == cid, f"{cid} Initialize v1 parent mismatch")
    require(parent_proof["profile_id"] == profile["profile_id"], f"{cid} profile mismatch")
    actual_wat_sha256 = hashlib.sha256(context["wat_text"].encode()).hexdigest()
    require(
        actual_wat_sha256 == parent_proof["retained_wasm"]["wat_sha256"],
        f"{cid} exact retained WAT authority drift",
    )
    require(
        function_sha256(context["handler"]) == parent_proof["handler_binding"]["body_sha256"],
        f"{cid} exact Initialize handler body drift",
    )
    require(parent_proof["complete_pool_handler_semantics"] is False, f"{cid} v1 boundary drift")

    day = _window_invocations(context, "PoolDayData")
    hour_data = _window_invocations(context, "PoolHourData")
    handler_fields = _handler_field_invocations(context)
    closure = _site_ledgers(context, parent_proof)
    handler = context["handler"]
    handler_calls = [
        {"relative_wat_line": index, "call_target": target}
        for index, line in enumerate(handler.lines)
        if (target := call_name(line)) is not None
    ]
    day_calls = [item for item in handler_calls if item["call_target"].endswith("updatePoolDayData")]
    hour_calls = [item for item in handler_calls if item["call_target"].endswith("updatePoolHourData")]
    pool_saves = [item for item in handler_calls if item["call_target"].endswith("schema/Pool#save")]
    token_saves = [item for item in handler_calls if item["call_target"].endswith("schema/Token#save")]
    bundle_saves = [item for item in handler_calls if item["call_target"].endswith("schema/Bundle#save")]
    require((len(day_calls), len(hour_calls), len(token_saves), len(bundle_saves)) == (1, 1, 2, 1), f"{cid} handler effect count drift")
    saving_pool = parent_proof["persistence"]["profile_expected_to_persist"]
    require(len(pool_saves) == (1 if saving_pool else 0), f"{cid} handler Pool.save count drift")
    require(
        day_calls[0]["relative_wat_line"] < hour_calls[0]["relative_wat_line"],
        f"{cid} day/hour helper order drift",
    )
    if saving_pool:
        require(
            pool_saves[0]["relative_wat_line"] < day_calls[0]["relative_wat_line"],
            f"{cid} Pool.save/helper order drift",
        )
    require(
        handler_fields["expanded_field_invocation_count"]
        + day["expanded_field_invocation_count"]
        + hour_data["expanded_field_invocation_count"]
        == 56,
        f"{cid} complete expanded field invocation count drift",
    )

    catalog_counts = Counter(item["entity"] for item in field_catalog)
    for entity, count in EXPECTED_ENTITY_COUNTS.items():
        require(catalog_counts[entity] == count, f"{entity} catalog count drift")
        require(
            tuple(item["field"] for item in field_catalog if item["entity"] == entity)
            == TARGET_ENTITY_FIELDS[entity],
            f"{entity} catalog field order drift",
        )
    interval_catalog: dict[str, Any] = {}
    for entity in ("PoolDayData", "PoolHourData"):
        records = [item for item in field_catalog if item["entity"] == entity]
        non_null = [item["field"] for item in records if item["type"].endswith("!")]
        nullable = [item["field"] for item in records if not item["type"].endswith("!")]
        require(len(records) == 20 and len(non_null) == 19 and nullable == ["tick"], f"{entity} nullability catalog drift")
        interval_catalog[entity] = {
            "catalog_field_count": 20,
            "non_null_field_count": 19,
            "nullable_field_count": 1,
            "nullable_fields": nullable,
            "all_catalog_fields_have_classified_constructor_or_setter_effects": True,
            "all_twenty_fields_non_null_or_required": False,
        }

    save_and_get_order = {
        "pool_save_call_present": bool(pool_saves),
        "pool_save_relative_wat_line": pool_saves[0]["relative_wat_line"] if pool_saves else None,
        "day_helper_call_relative_wat_line": day_calls[0]["relative_wat_line"],
        "hour_helper_call_relative_wat_line": hour_calls[0]["relative_wat_line"],
        "pool_save_call_precedes_both_helpers_when_present": bool(pool_saves),
        "no_pool_save_call_precedes_helpers_when_absent": not pool_saves,
        "day_helper_pool_store_get_path": day["pool_store_get_path"],
        "hour_helper_pool_store_get_path": hour_data["pool_store_get_path"],
        "call_order_and_pool_save_presence_or_absence_bound": True,
        "pool_store_get_return_visibility_or_version_proven": False,
        "imported_graph_store_read_after_write_semantics_complete": False,
    }

    return {
        "profile_id": profile["profile_id"],
        "mapping_cid": cid,
        "control_generation": profile["control_generation"],
        "pricing_profile": profile["pricing_profile"],
        "retained_wasm": parent_proof["retained_wasm"],
        "handler_binding": parent_proof["handler_binding"],
        "initialize_v1_pool_projection": {
            "pool_load_identity": parent_proof["pool_load_identity"],
            "field_value_and_setter_flow": parent_proof["field_value_and_setter_flow"],
            "persistence": parent_proof["persistence"],
            "parent_proof_sha256": canonical_sha256(parent_proof),
        },
        "handler_direct_callsite_count": len(handler_calls),
        "handler_direct_callsite_inventory_sha256": canonical_sha256(handler_calls),
        "handler_required_effect_invocations": {
            "day_update": day_calls[0],
            "hour_update": hour_calls[0],
            "bundle_save": bundle_saves[0],
            "token_saves": token_saves,
        },
        "handler_save_and_window_store_get_order": save_and_get_order,
        "handler_field_invocation_ledger": handler_fields,
        "window_helper_ledgers": {"PoolDayData": day, "PoolHourData": hour_data},
        "interval_field_catalog_nullability": interval_catalog,
        "complete_static_expanded_field_invocation_site_count": (
            handler_fields["expanded_field_invocation_count"]
            + day["expanded_field_invocation_count"]
            + hour_data["expanded_field_invocation_count"]
        ),
        "complete_reachable_mutation_and_call_closure": closure,
        "target_entity_field_contract_count": sum(EXPECTED_ENTITY_COUNTS.values()),
        "complete_path_qualified_static_initialize_contract": True,
        "imported_numeric_semantics_complete": False,
        "imported_big_decimal_comparator_semantics_complete": False,
        "imported_big_int_plus_numeric_semantics_complete": False,
        "graph_store_host_semantics_complete": False,
        "pool_store_get_return_visibility_or_version_proven": False,
        "imported_graph_store_read_after_write_semantics_complete": False,
        "graph_handler_rollback_proven": False,
        "actual_historic_handler_outcomes_bound": False,
    }


def _helper_pool_getter_source(getter: str) -> str:
    return (
        f"{getter} from the Pool object returned by the helper's exact Pool store.get path; "
        "the returned Pool value's visibility/version relative to earlier handler effects is unproved"
    )


def _window_outcome(
    entity: str,
    field: str,
    ledger: dict[str, Any],
) -> tuple[str, str, bool, bool]:
    if field in WINDOW_ALWAYS:
        return ("write_before_entity_save", _helper_pool_getter_source(WINDOW_ALWAYS[field]), True, False)
    if field == "tick":
        tick = ledger["nullable_tick_setter"]
        return (
            "nullable_setter_non_null_write_or_null_or_unset_before_entity_save",
            (
                f"{_helper_pool_getter_source('Pool.tick getter result')} is passed to the exact generated "
                f"nullable tick setter {tick['function']}; its non-null branch performs "
                f"{tick['non_null_branch_effect']} and its null branch performs {tick['null_branch_effect']}; "
                "imported numeric and store-host semantics are unproved"
            ),
            True,
            True,
        )
    if field == "txCount":
        plus = ledger["tx_count_big_int_plus_write"]
        return (
            "big_int_plus_result_write_before_entity_save",
            (
                f"the result returned by exact {plus['call_target']}"
                "(existing-or-zero txCount, ONE_BI) is written by the final txCount setter; "
                "imported BigInt numeric semantics are unproved"
            ),
            True,
            False,
        )
    if entity == "PoolHourData" and field == "close":
        return ("write_before_entity_save", _helper_pool_getter_source("Pool.token0Price getter result"), True, False)
    create_only = DAY_CREATE_ONLY if entity == "PoolDayData" else HOUR_CREATE_ONLY
    if field in create_only:
        source = create_only[field]
        if source.startswith("Pool."):
            source = _helper_pool_getter_source(source)
        return (
            "conditional_create_write_else_preserve",
            source,
            True,
            True,
        )
    if field in {"high", "low"}:
        control = ledger["high_low_write_control"][field]
        return (
            "missing_row_create_write_then_comparator_return_controlled_optional_write_else_preserve",
            (
                f"the missing-row path unconditionally invokes the {field} setter with "
                f"{_helper_pool_getter_source('Pool.token0Price getter result')}; after the create/existing join, "
                f"{control['comparator_return_control']} from exact {control['comparator_call_target']} controls "
                f"a separate {field} setter with the helper-loaded Pool.token0Price getter result; when that "
                f"later setter is not selected the current {field} entry is preserved; imported BigDecimal "
                "comparator semantics are unproved"
            ),
            True,
            True,
        )
    raise VerificationError(f"unclassified {entity}.{field}")


def _field_outcome(
    record: dict[str, Any],
    proof: dict[str, Any],
) -> dict[str, Any]:
    entity = record["entity"]
    field = record["field"]
    saving_pool = proof["initialize_v1_pool_projection"]["persistence"]["profile_expected_to_persist"]
    associated = entity in EXPECTED_ENTITY_COUNTS and (entity != "Pool" or saving_pool)
    direct_stored_association = associated and record["storage"] == "stored"
    potential_write = False
    potential_query_transition = False
    conditional = False

    if record["storage"] == "derived":
        if entity == "Pool" and field in {"poolDayData", "poolHourData"}:
            child = "PoolDayData" if field == "poolDayData" else "PoolHourData"
            outcome = "conditional_child_create_adds_derived_relation_else_preserve"
            source = (
                f"missing {child} creation writes {child}.pool from the Pool.id getter on the object returned by "
                "the helper's exact Pool store.get path; returned visibility/version is unproved; "
                "the existing-row path preserves membership"
            )
            potential_query_transition = True
            conditional = True
        else:
            outcome = "derived_query_field_no_direct_store_transition"
            source = f"reverse relationship declared by {record['directives']}"
    elif entity == "Bundle":
        if field == "ethPriceUSD":
            outcome = "write_before_entity_save"
            source = (
                "reference Pool 0x4c36388be6f416a29c8d8eee81c771ce6be14b18 token1Price, or ZERO_BD when absent"
                if proof["pricing_profile"].startswith("base-")
                else "reference Pool 0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8 token0Price, or ZERO_BD when absent"
            )
            potential_write = True
            potential_query_transition = True
        else:
            outcome = "preserve_loaded_value_on_entity_save"
            source = "loaded Bundle.id"
    elif entity == "Pool":
        if saving_pool and field in {"sqrtPrice", "tick"}:
            outcome = "write_before_entity_save"
            source = "Initialize.sqrtPriceX96" if field == "sqrtPrice" else "Initialize.tick"
            potential_write = True
            potential_query_transition = True
        elif saving_pool:
            outcome = "preserve_loaded_value_on_entity_save"
            source = f"loaded Pool.{field}"
        elif field in {"sqrtPrice", "tick"}:
            outcome = "in_memory_write_without_reachable_pool_store"
            source = "Initialize.sqrtPriceX96" if field == "sqrtPrice" else "Initialize.tick"
        else:
            outcome = "no_reachable_pool_store"
            source = "no persisted Initialize projection"
    elif entity in {"PoolDayData", "PoolHourData"}:
        outcome, source, potential_write, conditional = _window_outcome(
            entity,
            field,
            proof["window_helper_ledgers"][entity],
        )
        potential_query_transition = potential_write
    elif entity == "Token":
        if field == "derivedETH":
            outcome = (
                "conditional_both_tokens_write_else_no_token_store"
                if proof["control_generation"] == "modern"
                else "write_before_both_token_entity_saves_on_successful_non_null_path"
            )
            source = "findEthPerToken(token0) or findEthPerToken(token1)"
            potential_write = True
            potential_query_transition = True
        else:
            outcome = (
                "conditional_both_tokens_preserve_on_save_else_no_token_store"
                if proof["control_generation"] == "modern"
                else "preserve_loaded_value_on_both_token_entity_saves_on_successful_non_null_path"
            )
            source = f"loaded token0/token1 {field}"
        conditional = proof["control_generation"] == "modern"
    else:
        outcome = "no_reachable_entity_store"
        source = "entity is outside the complete Initialize store-target closure"

    return {
        "entity": entity,
        "field": field,
        "schema_type": record["type"],
        "storage": record["storage"],
        "directives": record["directives"],
        "field_catalog_record_sha256": canonical_sha256(record),
        "conservative_entity_writer_association": associated,
        "direct_stored_field_association": direct_stored_association,
        "static_transition": outcome,
        "value_or_preservation_source": source,
        "potential_direct_field_write": potential_write,
        "potential_query_visible_transition": potential_query_transition,
        "conditional_transition": conditional,
        "path_qualifier": "normally completed exact retained handler path; imported host outcomes, rollback, and historical population excluded",
        "complete_path_qualified_static_initialize_outcome": True,
        "complete_entity_history": False,
    }


def build_segments(
    matrix: dict[str, Any],
    field_catalog: list[dict[str, Any]],
    proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_cid = {item["mapping_cid"]: item for item in proofs}
    results: list[dict[str, Any]] = []
    for segment in matrix["segments"]:
        binding = segment["profile_bindings"]["pool"]
        cid = binding["mapping_cid"]
        require(cid in by_cid, f"Initialize v2 proof missing: {segment['segment_id']}")
        proof = by_cid[cid]
        outcomes = [_field_outcome(record, proof) for record in field_catalog]
        require(len(outcomes) == 299, f"{segment['segment_id']} field outcome count drift")
        saving = proof["initialize_v1_pool_projection"]["persistence"]["profile_expected_to_persist"]
        conservative_associated = sum(item["conservative_entity_writer_association"] for item in outcomes)
        direct_stored_associated = sum(item["direct_stored_field_association"] for item in outcomes)
        require(conservative_associated == (95 if saving else 59), f"{segment['segment_id']} conservative association count drift")
        require(direct_stored_associated == (87 if saving else 58), f"{segment['segment_id']} direct stored association count drift")
        require(all(item["complete_entity_history"] is False for item in outcomes), "history gate drift")
        summary = {
            "field_outcome_count": len(outcomes),
            "conservative_entity_writer_association_count": conservative_associated,
            "direct_stored_field_association_count": direct_stored_associated,
            "potential_direct_field_write_count": sum(
                item["potential_direct_field_write"] for item in outcomes
            ),
            "potential_query_visible_transition_count": sum(
                item["potential_query_visible_transition"] for item in outcomes
            ),
            "derived_query_no_direct_store_transition_count": sum(
                item["static_transition"] == "derived_query_field_no_direct_store_transition"
                for item in outcomes
            ),
            "conditional_derived_relation_transition_count": sum(
                item["static_transition"]
                == "conditional_child_create_adds_derived_relation_else_preserve"
                for item in outcomes
            ),
            "conditional_transition_count": sum(item["conditional_transition"] for item in outcomes),
            "no_reachable_entity_store_count": sum(
                item["static_transition"] in {"no_reachable_entity_store", "no_reachable_pool_store"}
                for item in outcomes
            ),
        }
        semantic_surface = {
            "handler_id": HANDLER_ID,
            "profile_id": proof["profile_id"],
            "control_generation": proof["control_generation"],
            "pricing_profile": proof["pricing_profile"],
            "pool_saved": saving,
            "reachable_store_targets": proof["complete_reachable_mutation_and_call_closure"]
            ["transitive_store_evidence"]["reachable_store_set_targets"],
            "field_outcome_summary": summary,
            "field_outcomes": outcomes,
            "complete_path_qualified_static_initialize_contract": True,
            "complete_entity_histories": False,
        }
        provenance_surface = {
            "mapping_cid": cid,
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "mapping_proof_sha256": canonical_sha256(proof),
            "reachable_function_body_bindings_sha256": proof[
                "complete_reachable_mutation_and_call_closure"
            ]["reachable_function_body_bindings_sha256"],
        }
        results.append(
            {
                "segment_id": segment["segment_id"],
                "network": segment["network"],
                "deployment": segment["deployment"],
                "start_block_inclusive": segment["start_block_inclusive"],
                "end_block_inclusive": segment["end_block_inclusive"],
                "semantic_surface": semantic_surface,
                "semantic_surface_sha256": canonical_sha256(semantic_surface),
                "provenance_surface": provenance_surface,
                "provenance_surface_sha256": canonical_sha256(provenance_surface),
                "execution_model": "undecided",
                "backfill_allowed": False,
            }
        )
    require(len(results) == 8 and len({item["segment_id"] for item in results}) == 8, "segment count drift")
    require(sum(len(item["semantic_surface"]["field_outcomes"]) for item in results) == 2392, "total outcome count drift")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        results.append(
            {
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "semantic_equal": not semantic_paths,
                "recursive_semantic_diff_paths": semantic_paths,
                "provenance_equal": not provenance_paths,
                "recursive_provenance_diff_paths": provenance_paths,
                "left_semantic_surface_sha256": left["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right["semantic_surface_sha256"],
                "left_provenance_surface_sha256": left["provenance_surface_sha256"],
                "right_provenance_surface_sha256": right["provenance_surface_sha256"],
                "complete_path_qualified_static_initialize_contract_compared": True,
                "complete_entity_histories_compared": False,
                "boundary_state_compared": False,
                "graph_oracle_compared": False,
            }
        )
    require(len(results) == 28, "recursive Initialize segment diff count drift")
    return results


def truth_boundary() -> dict[str, bool]:
    return {
        **{field: True for field in TRUE_FLAGS},
        **{field: False for field in FALSE_FLAGS},
    }


def load_sources(
    root: Path,
    *,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    _bind(root, FACTORY_VERIFIER_PATH.relative_to(REPOSITORY), FACTORY_VERIFIER_SHA256)
    _bind(root, FACTORY_CONTRACT_PATH, FACTORY_CONTRACT_SHA256, FACTORY_CONTRACT_CANONICAL_SHA256)
    _bind(root, INITIALIZE_VERIFIER_PATH.relative_to(REPOSITORY), INITIALIZE_VERIFIER_SHA256)
    _bind(root, INITIALIZE_CONTRACT_PATH, INITIALIZE_CONTRACT_SHA256, INITIALIZE_CONTRACT_CANONICAL_SHA256)
    _bind(root, RUNTIME_PATH, RUNTIME_SHA256)

    factory_sources = FACTORY.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    factory_contract = FACTORY.verify_contract(
        root,
        sources=factory_sources,
        recompute_wat=False,
        wasm2wat=wasm2wat,
    )
    require(factory_contract["contract_version"] == FACTORY_CONTRACT_VERSION, "Factory v2 version drift")
    require(canonical_sha256(factory_contract) == FACTORY_CONTRACT_CANONICAL_SHA256, "Factory v2 canonical drift")

    initialize_sources = INITIALIZE.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    initialize_contract = INITIALIZE.verify_contract(
        root,
        sources=initialize_sources,
        recompute_wat=False,
        wasm2wat=wasm2wat,
    )
    require(initialize_contract["contract_version"] == INITIALIZE_CONTRACT_VERSION, "Initialize v1 version drift")
    require(canonical_sha256(initialize_contract) == INITIALIZE_CONTRACT_CANONICAL_SHA256, "Initialize v1 canonical drift")

    field_catalog = initialize_sources["v2_contract"]["field_catalog"]
    require(len(field_catalog) == 299, "full schema field catalog count drift")
    contexts = initialize_sources["pool_wat_contexts"]
    parent_by_cid = {item["mapping_cid"]: item for item in initialize_contract["mapping_proofs"]}
    proofs = []
    if recompute_wat:
        require(len(contexts) == len(parent_by_cid) == 8, "Initialize context count drift")
        proofs = [
            prove_complete_context(contexts[cid], parent_by_cid[cid], field_catalog)
            for cid in sorted(contexts)
        ]
        require(sum(item["initialize_v1_pool_projection"]["persistence"]["profile_expected_to_persist"] for item in proofs) == 3, "save profile count drift")
    return {
        "factory_sources": factory_sources,
        "factory_contract": factory_contract,
        "initialize_sources": initialize_sources,
        "initialize_contract": initialize_contract,
        "field_catalog": field_catalog,
        "contexts": contexts,
        "mapping_proofs": proofs,
        "transitive_input_manifest": _merge_transitive_inputs(root),
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["mapping_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 8, "recomputed Initialize v2 proofs required")
    matrix = sources["initialize_sources"]["v2_sources"]["segment_writer_matrix"]
    segments = build_segments(matrix, sources["field_catalog"], proofs)
    diffs = build_segment_diffs(segments)
    transitive = sources["transitive_input_manifest"]
    saving_segments = sum(item["semantic_surface"]["pool_saved"] for item in segments)
    require(saving_segments == 3, "segment save profile count drift")
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "exact-retained-wat-path-qualified-complete-static-initialize",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "mapping_count": 8,
            "handler": HANDLER_ID,
            "schema_field_count": 299,
            "segment_field_outcome_count": 2392,
            "target_entity_field_contract_count": 95,
            "historic_no_pool_save_conservative_association_count": 59,
            "historic_no_pool_save_direct_stored_association_count": 58,
            "saving_profile_conservative_association_count": 95,
            "saving_profile_direct_stored_association_count": 87,
            "saving_profile_count": 3,
            "no_pool_save_profile_count": 5,
            "day_expanded_field_invocation_site_count": 25,
            "hour_expanded_field_invocation_site_count": 26,
            "interval_entity_catalog_field_count_each": 20,
            "interval_entity_non_null_field_count_each": 19,
            "interval_entity_nullable_fields_each": ["tick"],
            "pairwise_recursive_diff_count": 28,
            "pool_store_get_return_visibility_or_version_proven": False,
            "imported_big_decimal_comparator_semantics_complete": False,
            "imported_big_int_plus_numeric_semantics_complete": False,
            "issue_acceptance_checkbox_completed": False,
            "claim": (
                "path-qualified complete static Pool.handleInitialize contract over exact retained WAT: "
                "all reachable calls and mutations are closed, handler save/helper store.get call order is bound, "
                "and every schema field has a segment outcome; returned store visibility, imported comparator and "
                "BigInt numeric meaning, rollback, populations, histories, parity, backfill, and readiness are excluded"
            ),
        },
        "implementation_base": {
            "commit": IMPLEMENTATION_BASE_COMMIT,
            "tree": IMPLEMENTATION_BASE_TREE,
            "relationship": "implemented as the next offline slice directly from the sealed Factory static v2 commit",
        },
        "source_contracts": {
            "factory_static_v2": {
                "path": FACTORY_CONTRACT_PATH.as_posix(),
                "contract_version": FACTORY_CONTRACT_VERSION,
                "raw_sha256": FACTORY_CONTRACT_SHA256,
                "canonical_sha256": FACTORY_CONTRACT_CANONICAL_SHA256,
                "source_contract_declarations_sha256": canonical_sha256(
                    sources["factory_contract"]["source_contracts"]
                ),
            },
            "factory_static_v2_verifier": {
                "path": FACTORY_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(),
                "raw_sha256": FACTORY_VERIFIER_SHA256,
            },
            "pool_initialize_v1": {
                "path": INITIALIZE_CONTRACT_PATH.as_posix(),
                "contract_version": INITIALIZE_CONTRACT_VERSION,
                "raw_sha256": INITIALIZE_CONTRACT_SHA256,
                "canonical_sha256": INITIALIZE_CONTRACT_CANONICAL_SHA256,
                "source_contract_declarations_sha256": canonical_sha256(
                    sources["initialize_contract"]["source_contracts"]
                ),
            },
            "pool_initialize_v1_verifier": {
                "path": INITIALIZE_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(),
                "raw_sha256": INITIALIZE_VERIFIER_SHA256,
            },
            "shared_wat_runtime": {
                "path": RUNTIME_PATH.as_posix(),
                "raw_sha256": RUNTIME_SHA256,
            },
        },
        "transitive_input_manifest_binding": {
            "entry_count": len(transitive),
            "sha256": canonical_sha256(transitive),
        },
        "authority_contract": {
            "semantic_authority": "exact retained deployed Pool mapping WASM and checksum-pinned WABT 1.0.35 WAT",
            "complete_static_meaning": (
                "every reachable function body, direct call, TypedMap setter, schema save, store target, "
                "domain helper, remove path, direct-memory-write inventory, and closed indirect target is bound"
            ),
            "outcome_meaning": (
                "normally completed path-qualified static transition or preservation classification, not an assertion "
                "about imported arithmetic, store success, Graph rollback, or actual historical entity population"
            ),
            "store_read_boundary": (
                "Pool.save call presence or absence and its order before helper Pool store.get paths are proved; "
                "the returned visibility or version is not proved"
            ),
            "comparison_boundary": (
                "missing-row high/low writes and separate comparator-return-controlled setter sites are proved; "
                "the imported comparator's numeric meaning is not proved"
            ),
            "big_int_boundary": (
                "the exact BigInt#plus(existing-or-zero txCount, ONE_BI) result write is proved; imported numeric "
                "meaning is not proved"
            ),
            "interval_nullability_boundary": (
                "all 20 fields are classified as 19 non-null fields plus nullable tick with a non-null or null/unset branch"
            ),
            "field_catalog_authority": "exact 299-field segment-field-semantics v2 catalog",
        },
        "toolchain": {
            "name": "WABT wasm2wat and wat2wasm",
            "version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-mapping-wasm>"],
            "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"],
            "official_linux_archive": WRITER.WABT_LINUX_ARCHIVE,
        },
        "mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "transitive_input_manifest": transitive,
        "issue_checkbox_assessment": {
            "issue_37": {"completed": False, "reason": "integrated population, continuity, and parity evidence remains open"},
            "issue_38": {"completed": False, "reason": "writer consumption, checkpoint, backfill, and production gates remain open"},
        },
        "residual_blockers": {
            "numeric_and_host": [
                "AssemblyScript/Graph imported numeric behavior is not reimplemented by this static WAT contract",
                "Graph store host success/failure and rollback behavior remain external",
                "helper Pool store.get return visibility/version relative to earlier handler calls is unproved",
                "BigDecimal comparator meaning and BigInt#plus numeric meaning are unproved",
            ],
            "history_and_population": [
                "Factory, Mint, Burn, Swap, Flash, and other handlers keep complete entity histories outside this slice",
                "actual historic entity presence and branch outcomes are not reconstructed",
            ],
            "execution_and_readiness": [
                "combined stage order, runtime population, graft-boundary continuity, and oracle comparison remain open",
                "logical, physical, PoI, writer consumption, checkpoint, backfill, production, and readiness gates remain false",
            ],
        },
        "truth_boundary": truth_boundary(),
    }


def verify_contract(
    root: Path,
    actual: dict[str, Any] | None = None,
    *,
    sources: dict[str, Any] | None = None,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    verified_sources = sources or load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(verified_sources)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"Initialize v2 contract missing: {CONTRACT_PATH}")
        value = load_json(path)
        require(isinstance(value, dict), "Initialize v2 contract must be one JSON object")
        actual = value
        require(path.read_text() == render(actual), "Initialize v2 contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Initialize v2 contract differs from generated proof")
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "truth-boundary key drift")
    for field in TRUE_FLAGS:
        require(truth[field] is True, f"proved Initialize v2 gate drift: {field}")
    for field in FALSE_FLAGS:
        require(truth[field] is False, f"unproved Initialize v2 gate promoted: {field}")
    require(actual["scope"]["issue_acceptance_checkbox_completed"] is False, "issue checkbox promoted")
    return expected


def write_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    sources = load_sources(root, recompute_wat=True, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(sources)
    path = root / CONTRACT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(expected))
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write-contract", action="store_true")
    args = parser.parse_args()
    try:
        contract = (
            write_contract(args.root, args.wasm2wat)
            if args.write_contract
            else verify_contract(args.root, wasm2wat=args.wasm2wat)
        )
    except Exception as error:  # parent verifiers expose distinct VerificationError classes
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(f"Pool Initialize v2 verification failed: {error}", file=sys.stderr)
        return 1
    digest = raw_sha256(args.root.resolve() / CONTRACT_PATH)
    print(
        "verified Uniswap V3 Pool Initialize v2: "
        f"{contract['scope']['segment_count']} segments, "
        f"{contract['scope']['segment_field_outcome_count']} field outcomes, "
        f"{contract['scope']['pairwise_recursive_diff_count']} diffs, "
        f"no issue checkbox completed, sha256 {digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
