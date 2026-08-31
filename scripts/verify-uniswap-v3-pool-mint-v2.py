#!/usr/bin/env python3
"""Build or verify the complete path-qualified Pool Mint v2 effect matrix."""

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
CONTRACT_PATH = Path("uniswap-v3/pool-mint/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-mint/v2"
HANDLER_ID = "Pool.handleMint"
HANDLER_EXPORT = "handleMint"

IMPLEMENTATION_BASE_COMMIT = "54bfab587a55a7c81204a166990c03cb659ae113"
IMPLEMENTATION_BASE_TREE = "29616314b951850d0a8f5003c819e7e29baf216c"

MINT_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-mint.py"
MINT_VERIFIER_SHA256 = "a84e24fbff7449ca3ebbe94ef93ee1c6ab2d81ab4b9085c441108f587604be9d"
MINT_CONTRACT_PATH = Path("uniswap-v3/pool-mint/v1/contract.json")
MINT_CONTRACT_SHA256 = "1040c821093b4f5afff3e99df58aa0e4b8021c643226d42dabd1255587fbf14c"
MINT_CONTRACT_CANONICAL_SHA256 = "d59682e547c339095f5ca2bb3b76a4d2e1aaf19a59e7b04a20608c6fb056fc70"
MINT_CONTRACT_VERSION = "uniswap-v3-pool-mint-semantics/v1"

RUNTIME_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-runtime.py"
RUNTIME_VERIFIER_SHA256 = "a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67"
RUNTIME_CONTRACT_PATH = Path("uniswap-v3/pool-runtime/v1/contract.json")
RUNTIME_CONTRACT_SHA256 = "66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53"
RUNTIME_CONTRACT_CANONICAL_SHA256 = "6b16a0045f6b6947365465200cc8fb46791e6fa8f852f2e4afe25ef6640d5427"
RUNTIME_CONTRACT_VERSION = "uniswap-v3-pool-runtime/v1"

FIELD_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
FIELD_VERIFIER_SHA256 = "e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec"
FIELD_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
FIELD_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
FIELD_CONTRACT_CANONICAL_SHA256 = "28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3"
FIELD_CONTRACT_VERSION = "uniswap-v3-segment-field-semantics/v2"

SCHEMA_PATH = Path("uniswap-v3/source/schema.graphql")
SCHEMA_SHA256 = "f234a0e4dc88c923d6ad28a3fcd1ed6093351bd2221d7c18486f0cbde41bb52c"
SCHEMA_BYTES = 18_883

SELECTED_FIELDS = ("totalValueLockedToken0", "totalValueLockedToken1")
NULLABLE_SETTER_BRANCH_IDENTITIES = (
    ("Mint", "amountUSD"),
    ("Mint", "logIndex"),
    ("PoolDayData", "tick"),
    ("PoolHourData", "tick"),
)
MINT_REQUIRED_FIELDS = (
    "id", "transaction", "timestamp", "pool", "token0", "token1", "owner",
    "origin", "amount", "amount0", "amount1", "tickLower", "tickUpper",
)
MINT_NULLABLE_FIELDS = ("sender", "amountUSD", "logIndex")
STORE_TARGETS = (
    "Factory",
    "Mint",
    "Pool",
    "PoolDayData",
    "PoolHourData",
    "Tick",
    "TickDayData",
    "Token",
    "TokenDayData",
    "TokenHourData",
    "Transaction",
    "UniswapDayData",
)

EXPECTED_ENTITY_COUNTS = {
    "Bundle": 2,
    "Burn": 15,
    "Collect": 11,
    "Factory": 13,
    "Flash": 12,
    "Mint": 16,
    "Pool": 36,
    "PoolDayData": 20,
    "PoolHourData": 20,
    "Position": 17,
    "PositionSnapshot": 16,
    "Swap": 15,
    "Tick": 21,
    "TickDayData": 12,
    "TickHourData": 10,
    "Token": 17,
    "TokenDayData": 14,
    "TokenHourData": 14,
    "Transaction": 10,
    "UniswapDayData": 8,
}

CATEGORY_SETTER = "stored_field_with_reachable_setter_path_before_matching_entity_store"
CATEGORY_NO_SETTER = "stored_field_on_reachable_entity_store_without_reachable_schema_setter_path"
CATEGORY_DERIVED = "derived_field_without_direct_graph_store_transition"
CATEGORY_OUTSIDE = "stored_field_outside_mint_graph_store_closure"

HANDLER_SEQUENCE = (
    ("Factory", "totalValueLockedETH"),
    ("Factory", "txCount"),
    ("Token", "txCount"),
    ("Token", "totalValueLocked"),
    ("Token", "totalValueLockedUSD"),
    ("Token", "txCount"),
    ("Token", "totalValueLocked"),
    ("Token", "totalValueLockedUSD"),
    ("Pool", "txCount"),
    ("Pool", "liquidity"),
    ("Pool", "totalValueLockedToken0"),
    ("Pool", "totalValueLockedToken1"),
    ("Pool", "totalValueLockedETH"),
    ("Pool", "totalValueLockedUSD"),
    ("Factory", "totalValueLockedETH"),
    ("Factory", "totalValueLockedUSD"),
    *(("Mint", field) for field in (
        "id", "transaction", "timestamp", "pool", "token0", "token1", "owner",
        "sender", "origin", "amount", "amount0", "amount1", "amountUSD", "tickLower",
        "tickUpper", "logIndex",
    )),
    ("Tick", "liquidityGross"),
    ("Tick", "liquidityNet"),
    ("Tick", "liquidityGross"),
    ("Tick", "liquidityNet"),
)

GROUP_SEQUENCES: dict[str, tuple[tuple[str, str], ...]] = {
    "handler": tuple(HANDLER_SEQUENCE),
    "createTick": tuple(
        ("Tick", field)
        for field in (
            "id", "tickIdx", "pool", "poolAddress", "createdAtTimestamp",
            "createdAtBlockNumber", "liquidityGross", "liquidityNet",
            "liquidityProviderCount", "price0", "price1", "price0", "price1",
            "volumeToken0", "volumeToken1", "volumeUSD", "feesUSD",
            "untrackedVolumeUSD", "collectedFeesToken0", "collectedFeesToken1",
            "collectedFeesUSD", "liquidityProviderCount", "feeGrowthOutside0X128",
            "feeGrowthOutside1X128",
        )
    ),
    "loadTransaction": tuple(
        ("Transaction", field)
        for field in ("id", "blockNumber", "timestamp", "gasUsed", "gasPrice")
    ),
    "updateTickFeeVarsAndSave": tuple(
        ("Tick", field)
        for field in ("feeGrowthOutside0X128", "feeGrowthOutside1X128")
    ),
    "updateTickDayData": tuple(
        ("TickDayData", field)
        for field in (
            "id", "date", "pool", "tick", "liquidityGross", "liquidityNet",
            "volumeToken0", "volumeToken1", "volumeUSD", "feesUSD",
            "feeGrowthOutside0X128", "feeGrowthOutside1X128",
        )
    ),
    "updateUniswapDayData": tuple(
        ("UniswapDayData", field)
        for field in (
            "id", "date", "volumeETH", "volumeUSD", "volumeUSDUntracked",
            "feesUSD", "tvlUSD", "txCount",
        )
    ),
    "updatePoolDayData": tuple(
        ("PoolDayData", field)
        for field in (
            "id", "date", "pool", "volumeToken0", "volumeToken1", "volumeUSD",
            "feesUSD", "txCount", "feeGrowthGlobal0X128", "feeGrowthGlobal1X128",
            "open", "high", "low", "close", "high", "low", "liquidity",
            "sqrtPrice", "feeGrowthGlobal0X128", "feeGrowthGlobal1X128",
            "token0Price", "token1Price", "tick", "tvlUSD", "txCount",
        )
    ),
    "updatePoolHourData": tuple(
        ("PoolHourData", field)
        for field in (
            "id", "periodStartUnix", "pool", "volumeToken0", "volumeToken1",
            "volumeUSD", "txCount", "feesUSD", "feeGrowthGlobal0X128",
            "feeGrowthGlobal1X128", "open", "high", "low", "close", "high",
            "low", "liquidity", "sqrtPrice", "token0Price", "token1Price",
            "feeGrowthGlobal0X128", "feeGrowthGlobal1X128", "close", "tick",
            "tvlUSD", "txCount",
        )
    ),
    "updateTokenDayData": tuple(
        ("TokenDayData", field)
        for field in (
            "id", "date", "token", "volume", "volumeUSD", "feesUSD",
            "untrackedVolumeUSD", "open", "high", "low", "close", "high",
            "low", "close", "priceUSD", "totalValueLocked", "totalValueLockedUSD",
        )
    ),
    "updateTokenHourData": tuple(
        ("TokenHourData", field)
        for field in (
            "id", "periodStartUnix", "token", "volume", "volumeUSD",
            "untrackedVolumeUSD", "feesUSD", "open", "high", "low", "close",
            "high", "low", "close", "priceUSD", "totalValueLocked",
            "totalValueLockedUSD",
        )
    ),
}

PATH_IDS = {
    "handler": ("handler",),
    "createTick": (
        "handler/createTick[0]",
        "handler/createTick[1]",
    ),
    "loadTransaction": ("handler/loadTransaction[0]",),
    "updateTickFeeVarsAndSave": (
        "handler/updateTickFeeVarsAndSave[0]",
        "handler/updateTickFeeVarsAndSave[1]",
    ),
    "updateTickDayData": (
        "handler/updateTickFeeVarsAndSave[0]/updateTickDayData[0]",
        "handler/updateTickFeeVarsAndSave[1]/updateTickDayData[0]",
    ),
    "updateUniswapDayData": ("handler/updateUniswapDayData[0]",),
    "updatePoolDayData": ("handler/updatePoolDayData[0]",),
    "updatePoolHourData": ("handler/updatePoolHourData[0]",),
    "updateTokenDayData": (
        "handler/updateTokenDayData[0]",
        "handler/updateTokenDayData[1]",
    ),
    "updateTokenHourData": (
        "handler/updateTokenHourData[0]",
        "handler/updateTokenHourData[1]",
    ),
}

STORE_PATH_IDS = {
    "Mint": ("handler/Mint.store[0]",),
    "Factory": ("handler/Factory.store[0]",),
    "Pool": ("handler/Pool.store[0]",),
    "PoolDayData": ("handler/updatePoolDayData[0]/PoolDayData.store[0]",),
    "PoolHourData": ("handler/updatePoolHourData[0]/PoolHourData.store[0]",),
    "Tick": (
        "handler/updateTickFeeVarsAndSave[0]/Tick.store[0]",
        "handler/updateTickFeeVarsAndSave[1]/Tick.store[0]",
    ),
    "TickDayData": (
        "handler/updateTickFeeVarsAndSave[0]/updateTickDayData[0]/TickDayData.store[0]",
        "handler/updateTickFeeVarsAndSave[1]/updateTickDayData[0]/TickDayData.store[0]",
    ),
    "Token": ("handler/Token.store[0]", "handler/Token.store[1]"),
    "TokenDayData": (
        "handler/updateTokenDayData[0]/TokenDayData.store[0]",
        "handler/updateTokenDayData[1]/TokenDayData.store[0]",
    ),
    "TokenHourData": (
        "handler/updateTokenHourData[0]/TokenHourData.store[0]",
        "handler/updateTokenHourData[1]/TokenHourData.store[0]",
    ),
    "Transaction": ("handler/loadTransaction[0]/Transaction.store[0]",),
    "UniswapDayData": ("handler/updateUniswapDayData[0]/UniswapDayData.store[0]",),
}

DERIVED_CHILD_ASSOCIATIONS = {
    ("Token", "tokenDayData"): ("TokenDayData", "token"),
    ("Pool", "poolHourData"): ("PoolHourData", "pool"),
    ("Pool", "poolDayData"): ("PoolDayData", "pool"),
    ("Pool", "mints"): ("Mint", "pool"),
    ("Transaction", "mints"): ("Mint", "transaction"),
}

TRUE_FLAGS = (
    "exact_pool_mint_v1_recomputed",
    "exact_pool_runtime_v1_recomputed",
    "exact_segment_field_v2_recomputed",
    "exact_schema_source_and_299_field_catalog_recomputed",
    "all_transitive_inputs_digest_bound",
    "all_eight_pool_mint_modules_exactly_bound",
    "all_1284_reachable_function_bodies_and_7672_direct_calls_bound",
    "all_2164_direct_memory_write_sites_inventoried",
    "all_738_physical_typed_map_set_sites_bound",
    "all_1408_physical_site_to_invocation_edges_classified",
    "all_1376_lexical_schema_field_invocations_classified",
    "all_1952_expanded_handler_to_setter_paths_classified",
    "all_104_lexical_96_physical_and_136_expanded_store_paths_bound",
    "all_eight_exact_twelve_target_store_closures_bound",
    "no_reachable_dynamic_store_target_remove_or_unmodelled_store_mutation",
    "both_modern_two_token_guards_enclose_all_effect_paths",
    "both_modern_conditional_tick_creation_and_update_paths_bound",
    "all_eight_142_unique_stored_setter_field_sets_bound",
    "all_eight_segments_have_299_path_qualified_field_outcomes",
    "all_sixteen_selected_tvl_setter_before_same_pool_save_outcomes_present",
    "all_1136_stored_setter_path_outcomes_present",
    "all_368_reachable_store_no_setter_outcomes_present",
    "all_104_derived_outcomes_present",
    "all_784_outside_store_closure_outcomes_present",
    "all_eight_zero_required_absent_overlays_bound",
    "all_eight_mint_thirteen_required_and_three_nullable_fields_bound",
    "all_twenty_eight_recursive_segment_diffs_present",
    "path_qualified_static_mint_schema_api_matrix_complete",
)

FALSE_FLAGS = (
    "pool_mint_semantics_complete",
    "field_value_semantics_complete",
    "field_value_unchanged_proven",
    "loaded_field_preservation_proven",
    "bytes_to_hex_host_semantics_rederived",
    "numeric_semantics_complete",
    "imported_numeric_semantics_complete",
    "imported_comparator_semantics_complete",
    "imported_host_semantics_complete",
    "contract_call_value_semantics_complete",
    "contract_call_block_pointer_semantics_complete",
    "contract_call_error_semantics_complete",
    "tick_helper_semantics_complete",
    "general_heap_alias_safety_complete",
    "direct_payload_alias_safety_complete",
    "no_later_field_overwrites_proven",
    "graph_store_host_semantics_complete",
    "graph_store_visibility_or_version_proven",
    "graph_store_persistence_complete",
    "graph_store_persistence_proven",
    "graph_handler_rollback_proven",
    "post_fatal_execution_modeled",
    "actual_historic_branch_outcomes_bound",
    "complete_pool_entity_history",
    "complete_mint_entity_history",
    "complete_entity_history",
    "all_manifest_handler_field_semantics_complete",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "runtime_population_complete",
    "scheduler_implemented",
    "output_implemented",
    "store_implemented",
    "package_implemented",
    "writer_package_consumes_projection",
    "source_package_identity_proven",
    "boundary_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "checkpoint_authority",
    "backfill_ready",
    "deployment_ready",
    "production_ready",
    "readiness_complete",
    "live_provider_evidence_complete",
    "execution_model_decided",
    "issue_37_acceptance_criterion_complete",
    "issue_38_acceptance_criterion_complete",
    "issue_checkbox_completed",
)


class VerificationError(RuntimeError):
    """Raised when retained evidence cannot reproduce the exact v2 claim."""


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
    output: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in output, f"duplicate JSON key: {key}")
        output[key] = value
    return output


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


MINT = load_module("uniswap_v3_pool_mint_v1_for_v2", MINT_VERIFIER_PATH, MINT_VERIFIER_SHA256)
FIELD = load_module(
    "uniswap_v3_segment_field_semantics_v2_for_pool_mint_v2",
    FIELD_VERIFIER_PATH,
    FIELD_VERIFIER_SHA256,
)
WRITER = MINT.WRITER
json_diff_paths = MINT.INITIALIZE.json_diff_paths

UPSTREAM_ERRORS = tuple(
    dict.fromkeys(
        (
            MINT.VerificationError,
            MINT.INITIALIZE.VerificationError,
            MINT.POOL_RUNTIME.VerificationError,
            MINT.V2.VerificationError,
            MINT.WRITER.VerificationError,
            FIELD.VerificationError,
        )
    )
)


def _bind(
    root: Path,
    relative: Path,
    raw_digest: str,
    canonical_digest: str | None = None,
) -> Any:
    path = root / relative
    require(path.is_file(), f"required source missing: {relative}")
    require(raw_sha256(path) == raw_digest, f"raw source digest drift: {relative}")
    value = load_json(path) if canonical_digest is not None else None
    if canonical_digest is not None:
        require(canonical_sha256(value) == canonical_digest, f"canonical source digest drift: {relative}")
    return value


ENTITY_RE = re.compile(r"(?ms)^type\s+(\w+)\s+([^\{]*@entity[^\{]*)\{(.*?)^\}")
FIELD_RE = re.compile(r"^\s*(\w+)\s*:\s*([^\s#]+)(.*)$")


def parse_direct_schema(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"direct schema missing: {path}")
    payload = path.read_bytes()
    require(len(payload) == SCHEMA_BYTES, "direct schema byte length drift")
    require(hashlib.sha256(payload).hexdigest() == SCHEMA_SHA256, "direct schema digest drift")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VerificationError("direct schema is not UTF-8") from error
    records: list[dict[str, str]] = []
    entities: list[str] = []
    for match in ENTITY_RE.finditer(text):
        entity = match.group(1)
        entities.append(entity)
        for line in match.group(3).splitlines():
            field_match = FIELD_RE.match(line)
            if field_match is None:
                continue
            directives = field_match.group(3).split("#", 1)[0].strip()
            records.append(
                {
                    "entity": entity,
                    "field": field_match.group(1),
                    "type": field_match.group(2),
                    "directives": directives,
                    "storage": "derived" if "@derivedFrom" in directives else "stored",
                }
            )
    require(len(entities) == 20 and len(set(entities)) == 20, "direct schema entity count drift")
    require(len(records) == 299, "direct schema field count drift")
    return records


def validate_field_catalog(
    catalog: list[dict[str, Any]], schema_records: list[dict[str, str]]
) -> dict[str, Any]:
    require(isinstance(catalog, list) and len(catalog) == 299, "field catalog count drift")
    pairs = [(item.get("entity"), item.get("field")) for item in catalog]
    require(len(set(pairs)) == 299, "field catalog identity uniqueness drift")
    entity_counts = Counter(item["entity"] for item in catalog)
    require(dict(sorted(entity_counts.items())) == EXPECTED_ENTITY_COUNTS, "field catalog entity count drift")
    storage_counts = Counter(item["storage"] for item in catalog)
    require(storage_counts == Counter({"stored": 286, "derived": 13}), "field storage count drift")
    projected = [
        {
            "entity": item["entity"],
            "field": item["field"],
            "type": item["type"],
            "directives": item["directives"],
            "storage": item["storage"],
        }
        for item in catalog
    ]
    projected_by_identity = {
        (item["entity"], item["field"]): item for item in projected
    }
    schema_by_identity = {
        (item["entity"], item["field"]): item for item in schema_records
    }
    require(
        projected_by_identity == schema_by_identity,
        "field catalog differs from direct schema identity or shape",
    )
    required_absent = Counter(
        item["entity"]
        for item in catalog
        if item["population_classification"] == "required_absent"
    )
    require(
        required_absent == Counter({"Collect": 11, "Flash": 12, "TickHourData": 10}),
        "required-absence denominator drift",
    )
    mint_schema = {
        item["field"]: item for item in schema_records if item["entity"] == "Mint"
    }
    require(set(mint_schema) == set(MINT_REQUIRED_FIELDS) | set(MINT_NULLABLE_FIELDS), "Mint schema field identity drift")
    require(
        all(mint_schema[field]["type"].endswith("!") for field in MINT_REQUIRED_FIELDS)
        and all(not mint_schema[field]["type"].endswith("!") for field in MINT_NULLABLE_FIELDS),
        "Mint required/nullable schema boundary drift",
    )
    return {
        "field_count": len(catalog),
        "entity_count": len(entity_counts),
        "entity_field_counts": dict(sorted(entity_counts.items())),
        "stored_field_count": storage_counts["stored"],
        "derived_field_count": storage_counts["derived"],
        "required_absent_field_count": sum(required_absent.values()),
        "required_absent_entity_field_counts": dict(sorted(required_absent.items())),
        "mint_required_fields": list(MINT_REQUIRED_FIELDS),
        "mint_required_field_count": len(MINT_REQUIRED_FIELDS),
        "mint_nullable_fields": list(MINT_NULLABLE_FIELDS),
        "mint_nullable_field_count": len(MINT_NULLABLE_FIELDS),
        "field_catalog_sha256": canonical_sha256(catalog),
        "direct_schema_projection_sha256": canonical_sha256(schema_records),
        "catalog_order_matches_direct_schema": projected == schema_records,
    }


def _function_by_suffix(context: dict[str, Any], suffix: str) -> Any:
    matches = [function for name, function in context["functions"].items() if name.endswith(suffix)]
    require(len(matches) == 1, f"{context['mapping_cid']} function suffix count drift: {suffix}")
    return matches[0]


def _resolve_function_name(context: dict[str, Any], target: str) -> str:
    if target in context["functions"]:
        return target
    suffix = target.split("schema/", 1)[-1] if "schema/" in target else target
    matches = [name for name in context["functions"] if name.endswith(f"schema/{suffix}")]
    require(len(matches) == 1, f"{context['mapping_cid']} unresolved call target: {target}")
    return matches[0]


def _group_functions(context: dict[str, Any]) -> dict[str, Any]:
    result = {"handler": context["handler"]}
    for group in GROUP_SEQUENCES:
        if group != "handler":
            result[group] = _function_by_suffix(context, group)
    return result


def _logical_operations(context: dict[str, Any], function: Any) -> list[dict[str, Any]]:
    generation = context["profile"]["control_generation"]
    map_set = MINT.MODERN_ENTITY_MAP_SET_CALL if generation == "modern" else MINT.LEGACY_ENTITY_MAP_SET_CALL
    output: list[dict[str, Any]] = []
    for index, line in enumerate(function.lines):
        target = MINT.call_name(line)
        if target is None:
            continue
        if (
            target == map_set
            or "#set:" in target
            or re.search(r"(?:^|/)schema/[^/]+#constructor$", target)
        ):
            output.append(
                {
                    "function": function.name,
                    "relative_wat_line": index,
                    "call_target": target,
                    "operand_slice_sha256": canonical_sha256(
                        [
                            MINT.normalized(item)
                            for item in function.lines[max(0, index - 20) : index + 1]
                        ]
                    ),
                }
            )
    return output


def _fanout_proof(context: dict[str, Any], groups: dict[str, Any]) -> dict[str, Any]:
    handler = context["handler"]

    def sites(function: Any, suffix: str) -> list[int]:
        return [
            index
            for index, line in enumerate(function.lines)
            if (MINT.call_name(line) or "").endswith(suffix)
        ]

    actual = {
        "createTick": sites(handler, "createTick"),
        "loadTransaction": sites(handler, "loadTransaction"),
        "updateTickFeeVarsAndSave": sites(handler, "updateTickFeeVarsAndSave"),
        "updateUniswapDayData": sites(handler, "updateUniswapDayData"),
        "updatePoolDayData": sites(handler, "updatePoolDayData"),
        "updatePoolHourData": sites(handler, "updatePoolHourData"),
        "updateTokenDayData": sites(handler, "updateTokenDayData"),
        "updateTokenHourData": sites(handler, "updateTokenHourData"),
        "updateTickDayData_from_tick_helper": sites(
            groups["updateTickFeeVarsAndSave"], "updateTickDayData"
        ),
    }
    expected_counts = {
        "createTick": 2,
        "loadTransaction": 1,
        "updateTickFeeVarsAndSave": 2,
        "updateUniswapDayData": 1,
        "updatePoolDayData": 1,
        "updatePoolHourData": 1,
        "updateTokenDayData": 2,
        "updateTokenHourData": 2,
        "updateTickDayData_from_tick_helper": 1,
    }
    require(
        {key: len(value) for key, value in actual.items()} == expected_counts,
        f"{context['mapping_cid']} helper fanout drift",
    )
    return {
        "handler_and_nested_helper_callsites": actual,
        "helper_callsite_counts": expected_counts,
        "expanded_multiplicity_by_group": {
            group: len(paths) for group, paths in PATH_IDS.items()
        },
        "helper_fanout_exactly_bound": True,
    }


def _physical_setter_coverage(
    context: dict[str, Any], lexical: list[dict[str, Any]], reachable: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    generation = context["profile"]["control_generation"]
    map_set = MINT.MODERN_ENTITY_MAP_SET_CALL if generation == "modern" else MINT.LEGACY_ENTITY_MAP_SET_CALL
    sites = [
        {"function": name, "relative_wat_line": index}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if MINT.call_name(line) == map_set
    ]
    site_ids = {(item["function"], item["relative_wat_line"]) for item in sites}
    edges: list[dict[str, Any]] = []
    for invocation in lexical:
        target = invocation["call_target"]
        if target == map_set:
            edges.append(
                {
                    "site_function": invocation["function"],
                    "site_relative_wat_line": invocation["relative_wat_line"],
                    "via_function": invocation["function"],
                    "via_relative_wat_line": invocation["relative_wat_line"],
                    "entity": invocation["entity"],
                    "field": invocation["field"],
                    "nullable_branch_alternative": False,
                }
            )
            continue
        pending = [_resolve_function_name(context, target)]
        visited: set[str] = set()
        found: list[tuple[str, int]] = []
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            function = context["functions"][name]
            for index, line in enumerate(function.lines):
                child = MINT.call_name(line)
                if child == map_set:
                    found.append((name, index))
                elif child is not None and (child in context["functions"] or "schema/" in child):
                    try:
                        resolved = _resolve_function_name(context, child)
                    except VerificationError:
                        continue
                    if resolved not in visited:
                        pending.append(resolved)
        require(found, f"{context['mapping_cid']} schema invocation reaches no TypedMap#set")
        for ordinal, (name, index) in enumerate(found):
            edges.append(
                {
                    "site_function": name,
                    "site_relative_wat_line": index,
                    "via_function": invocation["function"],
                    "via_relative_wat_line": invocation["relative_wat_line"],
                    "entity": invocation["entity"],
                    "field": invocation["field"],
                    "nullable_branch_alternative": ordinal > 0,
                }
            )
    covered = {(item["site_function"], item["site_relative_wat_line"]) for item in edges}
    require(covered == site_ids, f"{context['mapping_cid']} unclassified physical TypedMap#set site")
    require(len(edges) == 176, f"{context['mapping_cid']} site-to-invocation edge count drift")
    require(
        sum(item["nullable_branch_alternative"] for item in edges) == 4,
        f"{context['mapping_cid']} nullable branch alternative count drift",
    )
    require(
        Counter(
            (item["entity"], item["field"])
            for item in edges
            if item["nullable_branch_alternative"]
        )
        == Counter(NULLABLE_SETTER_BRANCH_IDENTITIES),
        f"{context['mapping_cid']} nullable branch identity drift",
    )
    return sites, edges


def _store_closure(
    context: dict[str, Any], reachable: list[str], parent_proof: dict[str, Any]
) -> dict[str, Any]:
    groups = _group_functions(context)
    helper_targets = {
        "loadTransaction": "Transaction",
        "updateTickFeeVarsAndSave": "Tick",
        "updateTickDayData": "TickDayData",
        "updateUniswapDayData": "UniswapDayData",
        "updatePoolDayData": "PoolDayData",
        "updatePoolHourData": "PoolHourData",
        "updateTokenDayData": "TokenDayData",
        "updateTokenHourData": "TokenHourData",
    }
    lexical: list[dict[str, Any]] = []
    for group, function in groups.items():
        for index, line in enumerate(function.lines):
            call = MINT.call_name(line)
            if call is None or ("#save" not in call and call != WRITER.STORE_SET_CALL):
                continue
            if "#save" in call:
                match = re.search(r"schema/([^/#]+)#save", call)
                require(match is not None, f"{context['mapping_cid']} unresolved schema save target")
                target = match.group(1)
            else:
                target = "Mint" if group == "handler" else helper_targets.get(group)
                require(target is not None, f"{context['mapping_cid']} unresolved direct store target")
            lexical.append(
                {
                    "group": group,
                    "function": function.name,
                    "relative_wat_line": index,
                    "call_target": call,
                    "target": target,
                }
            )
    require(len(lexical) == 13, f"{context['mapping_cid']} lexical Graph store count drift")
    require(
        Counter(item["target"] for item in lexical)
        == Counter({**{target: 1 for target in STORE_TARGETS}, "Token": 2}),
        f"{context['mapping_cid']} lexical Graph store target multiplicity drift",
    )
    store_callsites = WRITER.extract_store_set_callsites(context["functions"], context["memory"])
    WRITER.require_fixed_callsites(store_callsites, f"{context['mapping_cid']} Pool Mint v2")
    physical = [
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
    require(len(physical) == 12, f"{context['mapping_cid']} physical store count drift")
    require(sorted(item["target"] for item in physical) == list(STORE_TARGETS), f"{context['mapping_cid']} store target drift")
    expanded = [
        {"target": target, "path_id": path_id}
        for target in STORE_TARGETS
        for path_id in STORE_PATH_IDS[target]
    ]
    require(len(expanded) == 17, f"{context['mapping_cid']} expanded store path drift")
    transitive = parent_proof["persistence_and_effect_closure"]["transitive_store_evidence"]
    require(transitive["reachable_store_set_site_count"] == 12, "parent physical store count drift")
    require(transitive["reachable_store_set_targets"] == list(STORE_TARGETS), "parent store target drift")
    require(transitive["dynamic_reachable_store_set_target_count"] == 0, "dynamic store target")
    require(transitive["unmodelled_store_mutation_host_import_count"] == 0, "unmodelled store mutation")
    remove_calls = [
        {"function": name, "relative_wat_line": index, "call_target": target}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if (target := MINT.call_name(line)) is not None and "store.remove" in target
    ]
    require(not remove_calls, f"{context['mapping_cid']} reachable store.remove")
    return {
        "lexical_graph_store_invocation_count": len(lexical),
        "lexical_graph_store_invocations": lexical,
        "lexical_graph_store_invocation_inventory_sha256": canonical_sha256(lexical),
        "physical_store_set_site_count": len(physical),
        "physical_store_set_sites": physical,
        "physical_store_set_site_inventory_sha256": canonical_sha256(physical),
        "expanded_store_path_count": len(expanded),
        "expanded_store_paths": expanded,
        "expanded_store_path_inventory_sha256": canonical_sha256(expanded),
        "reachable_store_targets": list(STORE_TARGETS),
        "dynamic_store_target_count": 0,
        "store_remove_call_count": 0,
        "unmodelled_store_mutation_host_import_count": 0,
        "graph_store_host_semantics_complete": False,
        "graph_store_persistence_proven": False,
    }


def _ordering_and_guards(
    context: dict[str, Any],
    parent_proof: dict[str, Any],
    lexical: list[dict[str, Any]],
    groups: dict[str, Any],
    fanout: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    token_control = parent_proof["token_loads_and_presence_control"]
    persistence = parent_proof["persistence_and_effect_closure"]
    selected_sites = persistence["selected_field_write_callsites"]
    require([item["field"] for item in selected_sites] == list(SELECTED_FIELDS), f"{cid} selected field order drift")
    require(persistence["direct_pool_save_count"] == 1, f"{cid} Pool save count drift")
    require(
        persistence["same_loaded_pool_save_after_both_selected_setters_on_selected_update_path_machine_proven"] is True,
        f"{cid} same Pool save proof drift",
    )

    helper_store_order: dict[str, Any] = {}
    group_entity = {
        "loadTransaction": "Transaction",
        "updateTickFeeVarsAndSave": "Tick",
        "updateTickDayData": "TickDayData",
        "updateUniswapDayData": "UniswapDayData",
        "updatePoolDayData": "PoolDayData",
        "updatePoolHourData": "PoolHourData",
        "updateTokenDayData": "TokenDayData",
        "updateTokenHourData": "TokenHourData",
    }
    for group, entity in group_entity.items():
        function = groups[group]
        operation_lines = [
            item["relative_wat_line"] for item in lexical if item["group"] == group
        ]
        effect_lines = [
            index
            for index, line in enumerate(function.lines)
            if (
                (MINT.call_name(line) or "").endswith(f"schema/{entity}#save")
                or MINT.call_name(line) == WRITER.STORE_SET_CALL
            )
        ]
        require(len(effect_lines) == 1, f"{cid} {group} matching store invocation count drift")
        require(max(operation_lines) < effect_lines[0], f"{cid} {group} setter/store lexical order drift")
        helper_store_order[group] = {
            "entity": entity,
            "last_setter_invocation_relative_wat_line": max(operation_lines),
            "matching_store_invocation_relative_wat_line": effect_lines[0],
            "normal_continuation_setter_before_store_order_bound": True,
        }

    handler_effects: dict[str, list[int]] = {}
    for entity, expected in (("Factory", 1), ("Pool", 1), ("Token", 2), ("Mint", 1)):
        indices = [
            index
            for index, line in enumerate(handler.lines)
            if (
                (MINT.call_name(line) or "").endswith(f"schema/{entity}#save")
                or (
                    MINT.call_name(line) == WRITER.STORE_SET_CALL
                    and index >= 4
                    and MINT.decoded_constant(handler.lines[index - 4], context["memory"]) == entity
                )
            )
        ]
        require(len(indices) == expected, f"{cid} handler {entity} store invocation count drift")
        handler_lines = [
            item["relative_wat_line"]
            for item in lexical
            if item["group"] == "handler" and item["entity"] == entity
        ]
        require(handler_lines and max(handler_lines) < min(indices), f"{cid} handler {entity} setter/store order drift")
        handler_effects[entity] = indices
    tick_handler_lines = [
        item["relative_wat_line"]
        for item in lexical
        if item["group"] == "handler" and item["entity"] == "Tick"
    ]
    create_tick_calls = fanout["handler_and_nested_helper_callsites"]["createTick"]
    tick_calls = fanout["handler_and_nested_helper_callsites"]["updateTickFeeVarsAndSave"]
    require(max(create_tick_calls) < min(tick_handler_lines), f"{cid} createTick/handler Tick order drift")
    require(max(tick_handler_lines) < min(tick_calls), f"{cid} Tick handler/helper order drift")

    if generation == "modern":
        guard_start = token_control["selected_update_guard_start_index"]
        guard_end = token_control["selected_update_guard_end_index"]
        handler_effect_lines = [
            item["relative_wat_line"] for item in lexical if item["group"] == "handler"
        ] + [line for values in handler_effects.values() for line in values] + [
            line
            for key, values in fanout["handler_and_nested_helper_callsites"].items()
            if key != "updateTickDayData_from_tick_helper"
            for line in values
        ]
        require(
            all(guard_start < line < guard_end for line in handler_effect_lines),
            f"{cid} modern effect escaped two-token guard",
        )
        depths = MINT.V2.wat_control_depths(handler.lines)
        require(all(depths[line] == 2 for line in create_tick_calls), f"{cid} createTick guard depth drift")
        require(all(depths[line] == 1 for line in tick_calls), f"{cid} Tick helper guard depth drift")
        outer_guard = {
            "condition": "Token[Pool.token0] != null && Token[Pool.token1] != null",
            "guard_start_relative_wat_line": guard_start,
            "guard_end_relative_wat_line": guard_end,
            "all_handler_effect_callsites_inside_guard": True,
            "missing_either_token_skips_entire_effect_body": True,
        }
        tick_control = {
            "create_tick_call_relative_wat_lines": create_tick_calls,
            "create_tick_call_control_depth": 2,
            "each_create_tick_call_is_inside_its_tick_missing_branch": True,
            "tick_helper_call_relative_wat_lines": tick_calls,
            "tick_helper_control_depth": 1,
            "tick_helpers_execute_after_conditional_tick_creation_inside_outer_token_guard": True,
        }
    else:
        outer_guard = {
            "condition": "legacy normal-completion path only",
            "guard_start_relative_wat_line": None,
            "guard_end_relative_wat_line": None,
            "all_handler_effect_callsites_inside_guard": False,
            "missing_either_token_skips_entire_effect_body": False,
        }
        tick_control = {
            "create_tick_call_relative_wat_lines": create_tick_calls,
            "create_tick_call_control_depth": 1,
            "each_create_tick_call_is_inside_its_tick_missing_branch": True,
            "tick_helper_call_relative_wat_lines": tick_calls,
            "tick_helper_control_depth": 0,
            "tick_helpers_execute_after_conditional_tick_creation_inside_outer_token_guard": False,
        }
    return {
        "path_scope": (
            "potential lexical invocation paths on normal continuation; imported calls, actual branch outcomes, "
            "Graph persistence, rollback, and history are excluded; the ledger is not one execution trace"
        ),
        "selected_pool_flow": {
            "fields": list(SELECTED_FIELDS),
            "selected_setter_callsites": selected_sites,
            "pool_save_wat_line": persistence["handler_save_wat_line"],
            "same_loaded_pool_reaches_save_after_both_selected_setters": True,
        },
        "helper_setter_before_matching_store_order": helper_store_order,
        "handler_store_invocation_relative_wat_lines": handler_effects,
        "create_tick_call_relative_wat_lines": create_tick_calls,
        "both_create_tick_calls_precede_handler_tick_setters": True,
        "handler_tick_setters_precede_tick_helper_calls": True,
        "outer_two_token_guard": outer_guard,
        "tick_creation_and_update_control": tick_control,
        "imported_numeric_semantics_complete": False,
        "imported_comparator_semantics_complete": False,
        "contract_call_value_semantics_complete": False,
        "graph_store_persistence_proven": False,
    }


def prove_complete_context(
    context: dict[str, Any], parent_proof: dict[str, Any], catalog: list[dict[str, Any]]
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile = context["profile"]
    require(parent_proof["mapping_cid"] == cid, f"{cid} parent proof mismatch")
    require(parent_proof["profile_id"] == profile["profile_id"], f"{cid} parent profile mismatch")
    require(
        hashlib.sha256(context["wat_text"].encode()).hexdigest()
        == parent_proof["retained_wasm"]["wat_sha256"],
        f"{cid} retained WAT drift",
    )
    require(
        MINT.function_sha256(context["handler"]) == parent_proof["handler_binding"]["body_sha256"],
        f"{cid} handler body drift",
    )
    require(parent_proof["complete_pool_mint_handler_semantics"] is False, f"{cid} parent truth boundary drift")

    reachable = sorted(
        WRITER.reachable_functions(
            context["functions"], context["handler"], tuple(context["indirect_targets"])
        )
    )
    bodies = [
        {
            "function": name,
            "function_index": context["functions"][name].function_index,
            "body_sha256": MINT.function_sha256(context["functions"][name]),
        }
        for name in reachable
    ]
    calls = [
        {"function": name, "relative_wat_line": index, "call_target": target}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if (target := MINT.call_name(line)) is not None
    ]
    direct_writes = [
        {"function": name, "relative_wat_line": index, "instruction": MINT.normalized(line)}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if MINT.POOL_RUNTIME.RUNTIME.is_direct_memory_write(line, MINT.normalized)
    ]
    generation = profile["control_generation"]
    expected = (96, 1094, 584, 174, 1) if generation == "modern" else (182, 914, 166, 65, 0)
    map_set = MINT.MODERN_ENTITY_MAP_SET_CALL if generation == "modern" else MINT.LEGACY_ENTITY_MAP_SET_CALL
    physical_map_sets = [item for item in calls if item["call_target"] == map_set]
    indirect_count = sum(
        "call_indirect" in line
        for name in reachable
        for line in context["functions"][name].lines
    )
    require(
        (len(reachable), len(calls), len(direct_writes), len(physical_map_sets), indirect_count)
        == expected,
        f"{cid} reachable inventory count drift",
    )
    parent_inventory = parent_proof["persistence_and_effect_closure"][
        "reachable_in_memory_mutation_inventory"
    ]
    require(parent_inventory["reachable_function_count"] == len(reachable), "parent function count drift")
    require(parent_inventory["reachable_direct_memory_write_site_count"] == len(direct_writes), "parent write count drift")
    require(parent_inventory["reachable_typed_map_set_site_count"] == len(physical_map_sets), "parent setter count drift")

    groups = _group_functions(context)
    fanout = _fanout_proof(context, groups)
    lexical: list[dict[str, Any]] = []
    for group, expected_sequence in GROUP_SEQUENCES.items():
        function = groups[group]
        operations = _logical_operations(context, function)
        require(len(operations) == len(expected_sequence), f"{cid} {group} lexical invocation count drift")
        previous_operation_line = -1
        for ordinal, (operation, (entity, field)) in enumerate(zip(operations, expected_sequence)):
            if operation["call_target"] == map_set:
                field_key_lines = [
                    index
                    for index in range(
                        previous_operation_line + 1,
                        operation["relative_wat_line"],
                    )
                    if MINT.decoded_constant(function.lines[index], context["memory"])
                    == field
                ]
            else:
                setter = context["functions"][
                    _resolve_function_name(context, operation["call_target"])
                ]
                field_key_lines = [
                    index
                    for index, line in enumerate(setter.lines)
                    if MINT.decoded_constant(line, context["memory"]) == field
                ]
            require(
                field_key_lines,
                f"{cid} {group}[{ordinal}] exact field key is not bound: {entity}.{field}",
            )
            lexical.append(
                {
                    **operation,
                    "group": group,
                    "group_ordinal": ordinal,
                    "entity": entity,
                    "field": field,
                    "receiver_context_bound_by_exact_caller_and_store_path": True,
                    "field_key_bound_by_exact_callsite_and_retained_body": True,
                    "field_value_semantics_complete": False,
                }
            )
            previous_operation_line = operation["relative_wat_line"]
    require(len(lexical) == 172, f"{cid} lexical invocation denominator drift")
    expanded = [
        {**item, "path_id": path_id}
        for item in lexical
        for path_id in PATH_IDS[item["group"]]
    ]
    require(len(expanded) == 244, f"{cid} expanded setter path denominator drift")
    sites, coverage = _physical_setter_coverage(context, lexical, reachable)
    require(len(sites) == len(physical_map_sets), f"{cid} physical setter ledger mismatch")
    store = _store_closure(context, reachable, parent_proof)
    ordering = _ordering_and_guards(context, parent_proof, lexical, groups, fanout)

    catalog_by_identity = {
        (item["entity"], item["field"]): item for item in catalog
    }
    catalog_pairs = set(catalog_by_identity)
    unique_pairs = sorted({(item["entity"], item["field"]) for item in lexical})
    require(len(unique_pairs) == 142, f"{cid} unique stored setter field count drift")
    require(set(unique_pairs).issubset(catalog_pairs), f"{cid} setter field missing from catalog")
    require(
        all(catalog_by_identity[identity]["storage"] == "stored" for identity in unique_pairs),
        f"{cid} reachable setter ledger contains a derived schema field",
    )
    expected_unique_counts = {
        "Mint": 16,
        "Factory": 3,
        "Pool": 6,
        "PoolDayData": 20,
        "PoolHourData": 20,
        "Tick": 21,
        "TickDayData": 12,
        "Token": 3,
        "TokenDayData": 14,
        "TokenHourData": 14,
        "Transaction": 5,
        "UniswapDayData": 8,
    }
    require(
        dict(sorted(Counter(entity for entity, _field in unique_pairs).items()))
        == expected_unique_counts,
        f"{cid} unique setter entity denominator drift",
    )
    return {
        "mapping_cid": cid,
        "profile_id": profile["profile_id"],
        "control_generation": generation,
        "retained_wasm": parent_proof["retained_wasm"],
        "handler_binding": parent_proof["handler_binding"],
        "pool_mint_v1_proof_sha256": canonical_sha256(parent_proof),
        "reachable_inventory": {
            "reachable_function_count": len(reachable),
            "reachable_function_body_inventory_sha256": canonical_sha256(bodies),
            "direct_callsite_count": len(calls),
            "direct_callsite_inventory_sha256": canonical_sha256(calls),
            "direct_memory_write_site_count": len(direct_writes),
            "direct_memory_write_site_inventory_sha256": canonical_sha256(direct_writes),
            "physical_typed_map_set_site_count": len(sites),
            "physical_typed_map_set_site_inventory_sha256": canonical_sha256(sites),
            "reachable_call_indirect_count": indirect_count,
            "closed_indirect_targets": list(context["indirect_targets"]),
            "direct_memory_alias_semantics_complete": False,
        },
        "schema_api_invocation_closure": {
            "lexical_field_invocation_count": len(lexical),
            "lexical_field_invocations": lexical,
            "lexical_field_invocation_inventory_sha256": canonical_sha256(lexical),
            "physical_site_to_invocation_edge_count": len(coverage),
            "physical_site_to_invocation_edges": coverage,
            "physical_site_to_invocation_edge_inventory_sha256": canonical_sha256(coverage),
            "nullable_branch_alternative_count": sum(
                item["nullable_branch_alternative"] for item in coverage
            ),
            "expanded_handler_to_setter_path_count": len(expanded),
            "expanded_handler_to_setter_paths": expanded,
            "expanded_handler_to_setter_path_inventory_sha256": canonical_sha256(expanded),
            "unique_stored_setter_field_count": len(unique_pairs),
            "unique_stored_setter_fields": [
                {"entity": entity, "field": field} for entity, field in unique_pairs
            ],
            "unique_stored_setter_entity_counts": expected_unique_counts,
            "unclassified_physical_typed_map_set_site_count": 0,
            "physical_vs_semantic_ledger_warning": (
                "physical TypedMap#set sites, lexical schema-field invocations, nullable branch edges, "
                "and expanded handler paths are distinct denominators; physical sites are not the "
                "172 lexical invocation denominator"
            ),
        },
        "helper_fanout": fanout,
        "store_closure": store,
        "ordering_and_guards": ordering,
        "complete_path_qualified_static_mint_schema_api_closure": True,
        "pool_mint_semantics_complete": False,
        "graph_store_persistence_proven": False,
        "complete_entity_history": False,
    }


def _field_category(
    record: dict[str, Any], written: set[tuple[str, str]]
) -> str:
    identity = (record["entity"], record["field"])
    if identity in written:
        return CATEGORY_SETTER
    if record["storage"] == "stored" and record["entity"] in STORE_TARGETS:
        return CATEGORY_NO_SETTER
    if record["storage"] == "derived":
        return CATEGORY_DERIVED
    return CATEGORY_OUTSIDE


def _field_outcome(record: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
    lexical = proof["schema_api_invocation_closure"]["lexical_field_invocations"]
    expanded = proof["schema_api_invocation_closure"]["expanded_handler_to_setter_paths"]
    written = {(item["entity"], item["field"]) for item in lexical}
    identity = (record["entity"], record["field"])
    category = _field_category(record, written)
    invocations = [
        item for item in lexical if (item["entity"], item["field"]) == identity
    ]
    paths = [item for item in expanded if (item["entity"], item["field"]) == identity]
    child = DERIVED_CHILD_ASSOCIATIONS.get(identity)
    child_paths = (
        [item for item in expanded if (item["entity"], item["field"]) == child]
        if child is not None
        else []
    )
    setter = category == CATEGORY_SETTER
    selected = setter and identity in {("Pool", field) for field in SELECTED_FIELDS}
    no_setter = category == CATEGORY_NO_SETTER
    derived = category == CATEGORY_DERIVED
    outside = category == CATEGORY_OUTSIDE
    require(sum((setter, no_setter, derived, outside)) == 1, "field category overlap")
    if setter:
        require(invocations and paths, f"missing setter paths for {identity}")
    else:
        require(not invocations and not paths, f"unexpected setter paths for {identity}")
    if child is not None:
        require(derived, f"child association is not derived: {identity}")
        require(child is not None and child_paths, f"missing derived child setter paths for {identity}")
    selected_flow = None
    if selected:
        parent_fields = next(
            item
            for item in proof["schema_api_invocation_closure"]["lexical_field_invocations"]
            if (item["entity"], item["field"]) == identity
        )
        selected_flow = {
            "event_parameter": "amount0" if record["field"].endswith("Token0") else "amount1",
            "structural_flow": "old matching Pool TVL plus converted Mint event amount",
            "setter_callsite": {
                "function": parent_fields["function"],
                "relative_wat_line": parent_fields["relative_wat_line"],
            },
            "same_loaded_pool_reaches_save_after_both_selected_setters": True,
            "numeric_semantics_complete": False,
        }
    return {
        "entity": record["entity"],
        "field": record["field"],
        "type": record["type"],
        "directives": record["directives"],
        "storage": record["storage"],
        "schema_catalog_record_sha256": canonical_sha256(record),
        "path_qualified_category": category,
        "stored_field_with_setter_path_before_matching_store": setter,
        "selected_pool_tvl_plus_mint_amount_setter_before_same_pool_save": selected,
        "stored_field_on_reachable_store_without_setter_path": no_setter,
        "derived_field_without_direct_graph_store_transition": derived,
        "stored_field_outside_mint_store_closure": outside,
        "lexical_setter_invocation_count": len(invocations),
        "lexical_setter_invocation_inventory_sha256": canonical_sha256(invocations),
        "expanded_setter_path_count": len(paths),
        "expanded_setter_path_inventory_sha256": canonical_sha256(paths),
        "matching_entity_store_target_reachable": setter or no_setter,
        "no_reachable_schema_api_setter_path_bound": no_setter,
        "selected_structural_flow": selected_flow,
        "derived_child_association": (
            {
                "child_entity": child[0],
                "child_field": child[1],
                "child_expanded_setter_path_count": len(child_paths),
                "child_expanded_setter_path_inventory_sha256": canonical_sha256(child_paths),
                "actual_graph_query_visibility_proven": False,
            }
            if child is not None
            else None
        ),
        "mint_required_field_overlay": record["entity"] == "Mint" and record["field"] in MINT_REQUIRED_FIELDS,
        "mint_nullable_field_overlay": record["entity"] == "Mint" and record["field"] in MINT_NULLABLE_FIELDS,
        "required_absent_overlay": False,
        "static_required_absence_bound": False,
        "normal_continuation_path_qualified_static_outcome_complete": True,
        "field_value_semantics_complete": False,
        "field_value_unchanged_proven": False,
        "loaded_field_preservation_proven": False,
        "general_heap_alias_safety_complete": False,
        "graph_store_host_semantics_complete": False,
        "graph_store_persistence_proven": False,
        "complete_entity_history": False,
        "complete_integrated_field_semantics": False,
        "mapping_proof_sha256": canonical_sha256(proof),
    }


def build_segments(
    mint_contract: dict[str, Any], catalog: list[dict[str, Any]], proofs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_cid = {item["mapping_cid"]: item for item in proofs}
    results: list[dict[str, Any]] = []
    expected_counts = Counter(
        {
            CATEGORY_SETTER: 142,
            CATEGORY_NO_SETTER: 46,
            CATEGORY_DERIVED: 13,
            CATEGORY_OUTSIDE: 98,
        }
    )
    for parent in mint_contract["segments"]:
        cid = parent["semantic_surface"]["mapping_cid"]
        require(cid in by_cid, f"{parent['segment_id']} missing Mint v2 proof")
        proof = by_cid[cid]
        require(parent["semantic_surface"]["profile_id"] == proof["profile_id"], "segment profile drift")
        outcomes = [_field_outcome(record, proof) for record in catalog]
        counts = Counter(item["path_qualified_category"] for item in outcomes)
        require(counts == expected_counts, f"{parent['segment_id']} field category denominator drift")
        required_absent = sum(item["required_absent_overlay"] for item in outcomes)
        require(required_absent == 0, f"{parent['segment_id']} required-absence denominator drift")
        mint_required = sum(item["mint_required_field_overlay"] for item in outcomes)
        mint_nullable = sum(item["mint_nullable_field_overlay"] for item in outcomes)
        selected = sum(
            item["selected_pool_tvl_plus_mint_amount_setter_before_same_pool_save"]
            for item in outcomes
        )
        require((mint_required, mint_nullable, selected) == (13, 3, 2), f"{parent['segment_id']} Mint field overlay drift")
        semantic = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "control_generation": proof["control_generation"],
            "ordering_and_guards": proof["ordering_and_guards"],
            "schema_api_invocation_summary": {
                "physical_typed_map_set_site_count": proof["reachable_inventory"]["physical_typed_map_set_site_count"],
                "lexical_field_invocation_count": proof["schema_api_invocation_closure"]["lexical_field_invocation_count"],
                "physical_site_to_invocation_edge_count": proof["schema_api_invocation_closure"]["physical_site_to_invocation_edge_count"],
                "expanded_handler_to_setter_path_count": proof["schema_api_invocation_closure"]["expanded_handler_to_setter_path_count"],
                "unique_stored_setter_field_count": proof["schema_api_invocation_closure"]["unique_stored_setter_field_count"],
                "unclassified_physical_typed_map_set_site_count": 0,
            },
            "store_closure_summary": {
                "lexical_graph_store_invocation_count": proof["store_closure"]["lexical_graph_store_invocation_count"],
                "physical_store_set_site_count": proof["store_closure"]["physical_store_set_site_count"],
                "expanded_store_path_count": proof["store_closure"]["expanded_store_path_count"],
                "reachable_store_targets": list(STORE_TARGETS),
            },
            "field_outcome_summary": {
                "field_outcome_count": len(outcomes),
                "stored_field_with_setter_path_count": counts[CATEGORY_SETTER],
                "reachable_store_without_setter_path_count": counts[CATEGORY_NO_SETTER],
                "derived_without_direct_store_transition_count": counts[CATEGORY_DERIVED],
                "stored_field_outside_mint_store_closure_count": counts[CATEGORY_OUTSIDE],
                "selected_pool_tvl_plus_mint_amount_setter_before_same_pool_save_count": selected,
                "mint_required_field_count": mint_required,
                "mint_nullable_field_count": mint_nullable,
                "required_absent_overlay_count": required_absent,
                "category_counts_sha256": canonical_sha256(dict(sorted(counts.items()))),
            },
            "field_outcomes": outcomes,
            "path_qualified_static_mint_schema_api_matrix_complete": True,
            "pool_mint_semantics_complete": False,
            "complete_entity_history": False,
            "graph_store_persistence_proven": False,
        }
        provenance = {
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "pool_mint_v1_segment_semantic_sha256": parent["semantic_surface_sha256"],
            "pool_mint_v1_segment_provenance_sha256": parent["provenance_surface_sha256"],
            "pool_mint_v1_complete_proof_sha256": proof["pool_mint_v1_proof_sha256"],
            "projected_mapping_proof_sha256": canonical_sha256(proof),
        }
        results.append(
            {
                "segment_id": parent["segment_id"],
                "network": parent["network"],
                "deployment": parent["deployment"],
                "start_block_inclusive": parent["start_block_inclusive"],
                "end_block_inclusive": parent["end_block_inclusive"],
                "semantic_surface": semantic,
                "semantic_surface_sha256": canonical_sha256(semantic),
                "provenance_surface": provenance,
                "provenance_surface_sha256": canonical_sha256(provenance),
                "execution_model": "undecided",
                "backfill_allowed": False,
            }
        )
    require(len(results) == 8, "Pool Mint v2 segment count drift")
    totals = Counter(
        outcome["path_qualified_category"]
        for segment in results
        for outcome in segment["semantic_surface"]["field_outcomes"]
    )
    require(
        totals
        == Counter(
            {
                CATEGORY_SETTER: 1136,
                CATEGORY_NO_SETTER: 368,
                CATEGORY_DERIVED: 104,
                CATEGORY_OUTSIDE: 784,
            }
        ),
        "Pool Mint v2 aggregate category denominator drift",
    )
    require(sum(len(item["semantic_surface"]["field_outcomes"]) for item in results) == 2392, "field outcome total drift")
    require(sum(item["semantic_surface"]["field_outcome_summary"]["required_absent_overlay_count"] for item in results) == 0, "required-absence total drift")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        require(semantic_paths, f"unexpected empty semantic diff: {left['segment_id']}:{right['segment_id']}")
        require(provenance_paths, f"unexpected empty provenance diff: {left['segment_id']}:{right['segment_id']}")
        results.append(
            {
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "recursive_semantic_diff_paths": semantic_paths,
                "recursive_provenance_diff_paths": provenance_paths,
                "left_semantic_surface_sha256": left["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right["semantic_surface_sha256"],
                "left_provenance_surface_sha256": left["provenance_surface_sha256"],
                "right_provenance_surface_sha256": right["provenance_surface_sha256"],
                "complete_entity_histories_compared": False,
                "boundary_state_compared": False,
                "graph_oracle_compared": False,
            }
        )
    require(len(results) == 28, "Pool Mint v2 pairwise diff count drift")
    return results


def truth_boundary() -> dict[str, bool]:
    require(
        len(TRUE_FLAGS) == len(set(TRUE_FLAGS))
        and len(FALSE_FLAGS) == len(set(FALSE_FLAGS))
        and set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS),
        "truth-boundary declaration drift",
    )
    return {**{key: True for key in TRUE_FLAGS}, **{key: False for key in FALSE_FLAGS}}


def load_sources(
    root: Path,
    *,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    require(raw_sha256(MINT_VERIFIER_PATH) == MINT_VERIFIER_SHA256, "Pool Mint v1 verifier digest drift")
    require(raw_sha256(RUNTIME_VERIFIER_PATH) == RUNTIME_VERIFIER_SHA256, "Pool runtime verifier digest drift")
    require(raw_sha256(FIELD_VERIFIER_PATH) == FIELD_VERIFIER_SHA256, "field-semantics verifier digest drift")
    direct_mint = _bind(root, MINT_CONTRACT_PATH, MINT_CONTRACT_SHA256, MINT_CONTRACT_CANONICAL_SHA256)
    direct_runtime = _bind(root, RUNTIME_CONTRACT_PATH, RUNTIME_CONTRACT_SHA256, RUNTIME_CONTRACT_CANONICAL_SHA256)
    direct_fields = _bind(root, FIELD_CONTRACT_PATH, FIELD_CONTRACT_SHA256, FIELD_CONTRACT_CANONICAL_SHA256)
    require(direct_mint["contract_version"] == MINT_CONTRACT_VERSION, "Pool Mint v1 version drift")
    require(direct_runtime["contract_version"] == RUNTIME_CONTRACT_VERSION, "Pool runtime version drift")
    require(direct_fields["contract_version"] == FIELD_CONTRACT_VERSION, "field-semantics version drift")

    mint_sources = MINT.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    recomputed_mint = MINT.verify_contract(root, sources=mint_sources, recompute_wat=False)
    require(canonical_bytes(direct_mint) == canonical_bytes(recomputed_mint), "Pool Mint v1 direct recomputation drift")
    recomputed_runtime = MINT.POOL_RUNTIME.verify_contract(root, wasm2wat=wasm2wat)
    require(canonical_bytes(direct_runtime) == canonical_bytes(recomputed_runtime), "Pool runtime direct recomputation drift")
    require(canonical_bytes(direct_runtime) == canonical_bytes(mint_sources["pool_runtime_contract"]), "Pool runtime differs from Mint dependency")
    field_sources = FIELD.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    recomputed_fields = FIELD.verify_contract(root, sources=field_sources, recompute_wat=False)
    require(canonical_bytes(direct_fields) == canonical_bytes(recomputed_fields), "field-semantics direct recomputation drift")
    require(canonical_bytes(direct_fields) == canonical_bytes(mint_sources["v2_contract"]), "field catalog differs from Mint dependency")

    schema_records = parse_direct_schema(root / SCHEMA_PATH)
    catalog = direct_fields["field_catalog"]
    catalog_summary = validate_field_catalog(catalog, schema_records)
    contexts = mint_sources["pool_wat_contexts"]
    parent_by_cid = {item["mapping_cid"]: item for item in mint_sources["pool_mint_proofs"]}
    require(recompute_wat and len(contexts) == len(parent_by_cid) == 8, "eight recomputed Mint contexts required")
    proofs = sorted(
        (
            prove_complete_context(context, parent_by_cid[cid], catalog)
            for cid, context in contexts.items()
        ),
        key=lambda item: item["profile_id"],
    )
    require(
        len(proofs) == 8
        and sum(item["control_generation"] == "legacy" for item in proofs) == 6
        and sum(item["control_generation"] == "modern" for item in proofs) == 2,
        "Pool Mint v2 proof population drift",
    )
    return {
        "mint_sources": mint_sources,
        "mint_contract": recomputed_mint,
        "runtime_contract": recomputed_runtime,
        "field_contract": recomputed_fields,
        "field_sources": field_sources,
        "field_catalog": catalog,
        "field_catalog_summary": catalog_summary,
        "schema_records": schema_records,
        "contexts": contexts,
        "mapping_proofs": proofs,
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["mapping_proofs"]
    segments = build_segments(sources["mint_contract"], sources["field_catalog"], proofs)
    diffs = build_segment_diffs(segments)
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "complete-path-qualified-static-pool-mint-schema-api-effect-matrix",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "mapping_count": 8,
            "handler": HANDLER_ID,
            "schema_field_count_per_segment": 299,
            "field_outcome_count": 2392,
            "stored_field_with_setter_path_outcome_count": 1136,
            "reachable_store_without_setter_path_outcome_count": 368,
            "derived_without_direct_store_transition_outcome_count": 104,
            "stored_field_outside_mint_store_closure_outcome_count": 784,
            "selected_pool_tvl_plus_mint_amount_setter_before_same_pool_save_outcome_count": 16,
            "mint_required_field_overlay_count": 104,
            "mint_nullable_field_overlay_count": 24,
            "required_absent_overlay_count": 0,
            "physical_typed_map_set_site_count": 738,
            "physical_site_to_invocation_edge_count": 1408,
            "lexical_schema_field_invocation_count": 1376,
            "expanded_handler_to_setter_path_count": 1952,
            "lexical_graph_store_invocation_count": 104,
            "physical_store_set_site_count": 96,
            "expanded_store_path_count": 136,
            "unique_stored_setter_field_count_per_segment": 142,
            "legacy_reachable_function_count_per_mapping": 182,
            "legacy_direct_call_count_per_mapping": 914,
            "legacy_direct_memory_write_count_per_mapping": 166,
            "legacy_physical_typed_map_set_count_per_mapping": 65,
            "modern_reachable_function_count_per_mapping": 96,
            "modern_direct_call_count_per_mapping": 1094,
            "modern_direct_memory_write_count_per_mapping": 584,
            "modern_physical_typed_map_set_count_per_mapping": 174,
            "pairwise_recursive_diff_count": 28,
            "legacy_profile_count": 6,
            "modern_profile_count": 2,
            "issue_acceptance_checkbox_completed": False,
            "claim": (
                "complete normal-continuation path-qualified static Pool.handleMint schema-API effect matrix; "
                "setter/store associations are closed while field values, preservation, aliases, Graph "
                "persistence, history, execution, and readiness remain false"
            ),
        },
        "schema_catalog": sources["field_catalog_summary"],
        "source_contracts": {
            "pool_mint_v1_verifier": {
                "path": str(MINT_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": MINT_VERIFIER_SHA256,
            },
            "pool_mint_v1": {
                "path": str(MINT_CONTRACT_PATH),
                "contract_version": MINT_CONTRACT_VERSION,
                "raw_sha256": MINT_CONTRACT_SHA256,
                "canonical_sha256": MINT_CONTRACT_CANONICAL_SHA256,
                "recomputed_directly": True,
            },
            "pool_runtime_v1_verifier": {
                "path": str(RUNTIME_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": RUNTIME_VERIFIER_SHA256,
            },
            "pool_runtime_v1": {
                "path": str(RUNTIME_CONTRACT_PATH),
                "contract_version": RUNTIME_CONTRACT_VERSION,
                "raw_sha256": RUNTIME_CONTRACT_SHA256,
                "canonical_sha256": RUNTIME_CONTRACT_CANONICAL_SHA256,
                "recomputed_directly": True,
                "matches_pool_mint_v1_dependency": True,
            },
            "segment_field_semantics_v2_verifier": {
                "path": str(FIELD_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": FIELD_VERIFIER_SHA256,
            },
            "segment_field_semantics_v2": {
                "path": str(FIELD_CONTRACT_PATH),
                "contract_version": FIELD_CONTRACT_VERSION,
                "raw_sha256": FIELD_CONTRACT_SHA256,
                "canonical_sha256": FIELD_CONTRACT_CANONICAL_SHA256,
                "field_catalog_sha256": sources["field_catalog_summary"]["field_catalog_sha256"],
                "recomputed_directly": True,
                "matches_pool_mint_v1_dependency": True,
            },
            "direct_schema": {
                "path": str(SCHEMA_PATH),
                "bytes": SCHEMA_BYTES,
                "raw_sha256": SCHEMA_SHA256,
                "projection_sha256": sources["field_catalog_summary"]["direct_schema_projection_sha256"],
                "matches_segment_field_catalog": True,
            },
        },
        "authority_contract": {
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "implementation_base_tree": IMPLEMENTATION_BASE_TREE,
            "semantic_authority": "exact retained deployed Pool mapping WASM regenerated with checksum-pinned WABT 1.0.35",
            "schema_authority": "direct schema.graphql plus the independently recomputed 299-field segment-field v2 catalog",
            "invocation_boundary": (
                "physical TypedMap sites, 172 lexical schema-field invocations, 176 nullable-expanded "
                "site edges, and 244 helper-expanded handler paths are separate fail-closed ledgers"
            ),
            "normal_continuation_boundary": (
                "a classified setter path is paired with a later matching entity store only when its retained "
                "branch executes and control continues normally; this is not one execution trace"
            ),
            "modern_guard_boundary": (
                "all modern effects are inside the two-token presence guard; each createTick call is inside "
                "its corresponding tick-missing branch and Tick updates follow conditional creation"
            ),
            "no_setter_boundary": (
                "46 stored fields have no reachable schema-API setter path despite a reachable entity store; "
                "they are never described as preserved, unchanged, or value-exact"
            ),
            "derived_boundary": (
                "all thirteen derived fields lack a direct Graph store transition; five have matching "
                "child-association setter paths, but Graph query visibility and host behavior are unproved"
            ),
            "mint_nullability_boundary": (
                "direct schema authority has thirteen required Mint fields and nullable sender, amountUSD, "
                "and logIndex; all sixteen have setter paths and the Mint required-absence overlay is zero"
            ),
            "host_boundary": (
                "numeric, comparator, contract-call, alias, Graph store, persistence, visibility, rollback, "
                "post-fatal, and historical semantics are not rederived"
            ),
            "composition_boundary": (
                "Pool Mint v1, Pool runtime v1, segment-field v2, and direct schema are the only semantic "
                "inputs; Burn v2, Flash v2, Factory static v2, and Initialize v2 are ordering-only"
            ),
        },
        "toolchain": {
            "name": "WABT wasm2wat and wat2wasm",
            "version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-mapping-wasm>"],
            "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"],
        },
        "mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "semantic": [
                "other field values, nullable outcomes, numeric/comparator meaning, arbitrary aliases, and later in-memory overwrites are not characterized",
                "Graph store visibility, version, persistence, rollback, post-fatal behavior, and actual historical branch outcomes remain unproved",
                "complete Pool, Mint, related entity, other-handler, and integrated histories remain false",
            ],
            "execution": [
                "scheduler, runtime population, output, Store, package consumption, source package identity, and combined dynamic-data-source ordering remain unimplemented or unproved",
                "continuity, oracle, logical/physical/PoI parity, checkpoint authority, backfill, deployment, production, and readiness remain false",
                "issue #38 gains a bounded Mint slice only; no issue #37 or #38 checkbox is completed",
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
    verified = sources or load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(verified)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"Pool Mint v2 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "Pool Mint v2 contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Pool Mint v2 contract differs from generated proof")
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "Pool Mint v2 truth-boundary key drift")
    for key in TRUE_FLAGS:
        require(truth[key] is True, f"proved Mint v2 gate drift: {key}")
    for key in FALSE_FLAGS:
        require(truth[key] is False, f"unproved Mint v2 gate promoted: {key}")
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
        result = (
            write_contract(args.root, args.wasm2wat)
            if args.write_contract
            else verify_contract(args.root, wasm2wat=args.wasm2wat)
        )
    except (VerificationError, *UPSTREAM_ERRORS) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 Pool Mint semantics v2: "
        f"{len(result['segments'])} segments, "
        f"{result['scope']['field_outcome_count']} field outcomes, "
        f"{len(result['segment_diffs'])} diffs; no issue checkbox completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
