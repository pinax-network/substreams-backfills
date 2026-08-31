#!/usr/bin/env python3
"""Build or verify the complete lexical static Pool Swap v2 effect matrix."""

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
CONTRACT_PATH = Path("uniswap-v3/pool-swap/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-swap/v2"
HANDLER_ID = "Pool.handleSwap"
HANDLER_EXPORT = "handleSwap"

IMPLEMENTATION_BASE_COMMIT = "7fdcdc915ab683c1081df307ef867cfde1f1bebd"
IMPLEMENTATION_BASE_TREE = "976d7c858a3f111bd8ca2380ccf12bfdfa6e1ee7"

CORE_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-swap-core.py"
CORE_VERIFIER_SHA256 = "097047f6aac55b169c364cc0b4f51a1b4d655f103b77ed6dcc623a5daa3c77f8"
CORE_CONTRACT_PATH = Path("uniswap-v3/pool-swap-core/v1/contract.json")
CORE_CONTRACT_SHA256 = "5437e87329ae98eaf26e273903e53078a05c068c8be52f19a9673ed41cf4dd8b"
CORE_CONTRACT_CANONICAL_SHA256 = "89ae1e172a8a731e1b7eb5f378883903e93a471272e4867ead740e33084ba578"
CORE_CONTRACT_VERSION = "uniswap-v3-pool-swap-core-semantics/v1"

FEE_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-swap-fee-growth.py"
FEE_VERIFIER_SHA256 = "392fcebecd72abe912af34d256bbc01b42f1ddb4b9b04dab645d6c1669f42932"
FEE_CONTRACT_PATH = Path("uniswap-v3/pool-swap-fee-growth/v1/contract.json")
FEE_CONTRACT_SHA256 = "28e12268ebd6ddf78c4d6e59805967793630c6475ca6f0b332fefcf46c5b6b9b"
FEE_CONTRACT_CANONICAL_SHA256 = "c4ae746eee97af67cc63010bd48791a6196a5711d48c4e30c2d5b57ae02857ce"
FEE_CONTRACT_VERSION = "uniswap-v3-pool-swap-fee-growth-semantics/v1"

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

CORE_SELECTED_FIELDS = ("liquidity", "tick", "sqrtPrice")
FEE_SELECTED_FIELDS = ("feeGrowthGlobal0X128", "feeGrowthGlobal1X128")
NULLABLE_SETTER_BRANCH_IDENTITIES = (
    ("Pool", "tick"),
    ("Swap", "logIndex"),
    ("PoolDayData", "tick"),
    ("PoolHourData", "tick"),
)
SWAP_REQUIRED_FIELDS = (
    "id", "transaction", "timestamp", "pool", "token0", "token1", "sender",
    "recipient", "origin", "amount0", "amount1", "amountUSD", "sqrtPriceX96", "tick",
)
SWAP_NULLABLE_FIELDS = ("logIndex",)
STORE_TARGETS = (
    "Bundle",
    "Factory",
    "Pool",
    "PoolDayData",
    "PoolHourData",
    "Swap",
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

CATEGORY_SETTER = (
    "stored_field_with_exact_setter_and_lexically_later_same_group_store_"
    "receiver_origin_overlap"
)
CATEGORY_NO_SETTER = "stored_field_on_reachable_entity_store_without_exact_schema_setter"
CATEGORY_DERIVED = "derived_field_without_direct_graph_store_transition"
CATEGORY_OUTSIDE = "stored_field_outside_pool_swap_graph_store_closure"

HANDLER_SEQUENCE = (
    *(("Factory", field) for field in (
        "txCount", "totalVolumeETH", "totalVolumeUSD", "untrackedVolumeUSD",
        "totalFeesETH", "totalFeesUSD", "totalValueLockedETH",
    )),
    *(("Pool", field) for field in (
        "volumeToken0", "volumeToken1", "volumeUSD", "untrackedVolumeUSD",
        "feesUSD", "txCount", "liquidity", "tick", "sqrtPrice",
        "totalValueLockedToken0", "totalValueLockedToken1",
    )),
    *(("Token", field) for field in (
        "volume", "totalValueLocked", "volumeUSD", "untrackedVolumeUSD", "feesUSD", "txCount",
    )),
    *(("Token", field) for field in (
        "volume", "totalValueLocked", "volumeUSD", "untrackedVolumeUSD", "feesUSD", "txCount",
    )),
    ("Pool", "token0Price"),
    ("Pool", "token1Price"),
    ("Bundle", "ethPriceUSD"),
    ("Token", "derivedETH"),
    ("Token", "derivedETH"),
    ("Pool", "totalValueLockedETH"),
    ("Pool", "totalValueLockedUSD"),
    ("Factory", "totalValueLockedETH"),
    ("Factory", "totalValueLockedUSD"),
    ("Token", "totalValueLockedUSD"),
    ("Token", "totalValueLockedUSD"),
    *(("Swap", field) for field in (
        "id", "transaction", "timestamp", "pool", "token0", "token1", "sender",
        "origin", "recipient", "amount0", "amount1", "amountUSD", "tick",
        "sqrtPriceX96", "logIndex",
    )),
    ("Pool", "feeGrowthGlobal0X128"),
    ("Pool", "feeGrowthGlobal1X128"),
    ("UniswapDayData", "volumeETH"),
    ("UniswapDayData", "volumeUSD"),
    ("UniswapDayData", "feesUSD"),
    *(("PoolDayData", field) for field in ("volumeUSD", "volumeToken0", "volumeToken1", "feesUSD")),
    *(("PoolHourData", field) for field in ("volumeUSD", "volumeToken0", "volumeToken1", "feesUSD")),
    *(("TokenDayData", field) for field in ("volume", "volumeUSD", "untrackedVolumeUSD", "feesUSD")),
    *(("TokenHourData", field) for field in ("volume", "volumeUSD", "untrackedVolumeUSD", "feesUSD")),
    *(("TokenDayData", field) for field in ("volume", "volumeUSD", "untrackedVolumeUSD", "feesUSD")),
    *(("TokenHourData", field) for field in ("volume", "volumeUSD", "untrackedVolumeUSD", "feesUSD")),
)

GROUP_SEQUENCES: dict[str, tuple[tuple[str, str], ...]] = {
    "handler": tuple(HANDLER_SEQUENCE),
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
    "loadTransaction": ("handler/loadTransaction[0]",),
    "updateTickFeeVarsAndSave": (
        "handler/loadTickUpdateFeeVarsAndSave[0]/updateTickFeeVarsAndSave[0]",
        "handler/loadTickUpdateFeeVarsAndSave[1]/updateTickFeeVarsAndSave[0]",
        "handler/loadTickUpdateFeeVarsAndSave[2]/updateTickFeeVarsAndSave[0]",
    ),
    "updateTickDayData": (
        "handler/loadTickUpdateFeeVarsAndSave[0]/updateTickFeeVarsAndSave[0]/updateTickDayData[0]",
        "handler/loadTickUpdateFeeVarsAndSave[1]/updateTickFeeVarsAndSave[0]/updateTickDayData[0]",
        "handler/loadTickUpdateFeeVarsAndSave[2]/updateTickFeeVarsAndSave[0]/updateTickDayData[0]",
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

DERIVED_CHILD_ASSOCIATIONS = {
    ("Token", "tokenDayData"): ("TokenDayData", "token"),
    ("Pool", "poolHourData"): ("PoolHourData", "pool"),
    ("Pool", "poolDayData"): ("PoolDayData", "pool"),
    ("Pool", "swaps"): ("Swap", "pool"),
    ("Transaction", "swaps"): ("Swap", "transaction"),
}

TRUE_FLAGS = (
    "exact_pool_swap_core_v1_recomputed",
    "exact_pool_swap_fee_growth_v1_recomputed",
    "exact_pool_runtime_v1_recomputed",
    "exact_segment_field_v2_recomputed",
    "exact_schema_source_and_299_field_catalog_recomputed",
    "all_transitive_inputs_digest_bound",
    "all_eight_pool_swap_modules_exactly_bound",
    "all_1404_reachable_function_bodies_and_9968_direct_calls_bound",
    "all_2368_direct_memory_write_sites_inventoried",
    "all_754_physical_typed_map_set_sites_bound",
    "all_1608_physical_site_to_invocation_edges_classified",
    "all_1576_lexical_schema_field_invocations_classified",
    "all_1576_lexical_setter_exact_receiver_flows_bound",
    "all_1576_lexical_setter_invocation_origin_overlap_classifications_bound",
    "all_1720_setter_to_store_receiver_origin_overlap_edges_bound",
    "all_1608_physical_receiver_flow_edges_bound",
    "all_15_returned_helper_store_authority_records_materialized",
    "all_2072_expanded_handler_to_setter_paths_classified",
    "all_163_lexical_104_physical_and_211_expanded_store_paths_bound",
    "all_163_store_exact_target_receiver_flows_bound",
    "all_eight_exact_thirteen_target_store_closures_bound",
    "no_reachable_dynamic_store_target_remove_or_unmodelled_store_mutation",
    "both_modern_two_token_guards_enclose_all_effect_paths",
    "all_profile_specific_handler_store_ledgers_bound",
    "both_modern_duplicate_pool_hour_data_save_local_name_orders_bound",
    "all_eight_144_unique_stored_setter_field_sets_bound",
    "all_eight_segments_have_299_lexical_static_field_outcomes",
    "all_twenty_four_core_and_sixteen_fee_growth_selected_outcomes_present",
    "all_1152_stored_setter_and_lexically_later_origin_overlap_store_outcomes_present",
    "all_360_reachable_store_no_setter_outcomes_present",
    "all_104_derived_outcomes_present",
    "all_776_outside_store_closure_outcomes_present",
    "all_eight_zero_required_absent_overlays_bound",
    "all_eight_swap_fourteen_required_and_one_nullable_fields_bound",
    "all_twenty_eight_recursive_segment_diffs_present",
    "lexical_static_swap_schema_api_matrix_complete",
)

FALSE_FLAGS = (
    "pool_swap_semantics_complete",
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
    "last_writer_semantics_proven",
    "graph_store_host_semantics_complete",
    "graph_store_visibility_or_version_proven",
    "graph_store_persistence_complete",
    "graph_store_persistence_proven",
    "graph_handler_rollback_proven",
    "post_fatal_execution_modeled",
    "setter_store_common_execution_path_proven",
    "setter_store_receiver_must_alias_proven",
    "setter_store_branch_correlation_proven",
    "duplicate_save_common_execution_path_proven",
    "duplicate_save_receiver_must_alias_proven",
    "all_returned_helper_invocations_and_paths_return_stored_receiver_proven",
    "all_successful_constructor_returns_and_control_paths_return_internal_receiver_proven",
    "actual_historic_branch_outcomes_bound",
    "complete_pool_entity_history",
    "complete_swap_entity_history",
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


CORE = load_module("uniswap_v3_pool_swap_core_v1_for_v2", CORE_VERIFIER_PATH, CORE_VERIFIER_SHA256)
FEE = load_module("uniswap_v3_pool_swap_fee_growth_v1_for_v2", FEE_VERIFIER_PATH, FEE_VERIFIER_SHA256)
FIELD = load_module(
    "uniswap_v3_segment_field_semantics_v2_for_pool_swap_v2",
    FIELD_VERIFIER_PATH,
    FIELD_VERIFIER_SHA256,
)
WRITER = FEE.WRITER
json_diff_paths = FEE.INITIALIZE.json_diff_paths

UPSTREAM_ERRORS = tuple(
    dict.fromkeys(
        (
            CORE.VerificationError,
            FEE.VerificationError,
            FEE.INITIALIZE.VerificationError,
            FEE.POOL_RUNTIME.VerificationError,
            FEE.V2.VerificationError,
            FEE.WRITER.VerificationError,
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
    swap_schema = {
        item["field"]: item for item in schema_records if item["entity"] == "Swap"
    }
    require(set(swap_schema) == set(SWAP_REQUIRED_FIELDS) | set(SWAP_NULLABLE_FIELDS), "Swap schema field identity drift")
    require(
        all(swap_schema[field]["type"].endswith("!") for field in SWAP_REQUIRED_FIELDS)
        and all(not swap_schema[field]["type"].endswith("!") for field in SWAP_NULLABLE_FIELDS),
        "Swap required/nullable schema boundary drift",
    )
    return {
        "field_count": len(catalog),
        "entity_count": len(entity_counts),
        "entity_field_counts": dict(sorted(entity_counts.items())),
        "stored_field_count": storage_counts["stored"],
        "derived_field_count": storage_counts["derived"],
        "required_absent_field_count": sum(required_absent.values()),
        "required_absent_entity_field_counts": dict(sorted(required_absent.items())),
        "swap_required_fields": list(SWAP_REQUIRED_FIELDS),
        "swap_required_field_count": len(SWAP_REQUIRED_FIELDS),
        "swap_nullable_fields": list(SWAP_NULLABLE_FIELDS),
        "swap_nullable_field_count": len(SWAP_NULLABLE_FIELDS),
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


VALUE_TYPES = ("i32", "i64", "f32", "f64", "v128", "funcref", "externref")
_LOCAL_VALUE_SNAPSHOT_CACHE: dict[
    tuple[str, str], list[dict[str, frozenset[tuple[str, int]]]]
] = {}
TYPE_LINE_RE = re.compile(r"^\s*\(type \$(\S+) \(func(.*)\)\)$")
IMPORT_FUNCTION_RE = re.compile(
    r'^\s*\(import "[^"]+" "[^"]+" \(func \$([^\s\)]+) \(type \$(\S+)\)\)\)$'
)


def _signature_counts(fragment: str) -> tuple[int, int]:
    def count(kind: str) -> int:
        total = 0
        for clause in re.findall(rf"\({kind}\s+([^\)]*)\)", fragment):
            total += sum(token in VALUE_TYPES for token in clause.split())
        return total

    return count("param"), count("result")


def _wat_signatures(context: dict[str, Any]) -> dict[str, Any]:
    types: dict[str, tuple[int, int]] = {}
    signatures: dict[str, tuple[int, int]] = {}
    for line in context["wat_text"].splitlines():
        if (match := TYPE_LINE_RE.fullmatch(line)) is not None:
            types[match.group(1)] = _signature_counts(match.group(2))
        elif (match := IMPORT_FUNCTION_RE.fullmatch(line)) is not None:
            require(match.group(2) in types, f"unknown imported WAT type: {match.group(2)}")
            signatures[FEE.normalized(match.group(1))] = types[match.group(2)]
    parameters: dict[str, list[str]] = {}
    for name, function in context["functions"].items():
        header = FEE.normalized(function.lines[0])
        type_match = re.search(r"\(type \$(\S+)\)", header)
        require(type_match is not None and type_match.group(1) in types, f"{name} WAT type missing")
        normalized_name = FEE.normalized(name)
        signatures[normalized_name] = types[type_match.group(1)]
        parameters[normalized_name] = [
            item[0]
            for item in re.findall(
                r"\(param\s+(\$[^\s\)]+)\s+(i32|i64|f32|f64|v128|funcref|externref)\)",
                header,
            )
        ]
        require(
            len(parameters[normalized_name]) == signatures[normalized_name][0],
            f"{name} named WAT parameter count drift",
        )
    return {"functions": signatures, "parameters": parameters}


def _instruction_stack_effect(
    line: str,
    signatures: dict[str, tuple[int, int]],
) -> tuple[int, int]:
    normalized = FEE.normalized(line).rstrip(")")
    if (target := FEE.call_name(line)) is not None:
        require(target in signatures, f"call signature missing: {target}")
        return signatures[target]
    opcode = normalized.split()[0]
    if opcode.endswith(".const") or opcode in {"local.get", "global.get", "memory.size", "ref.null"}:
        return 0, 1
    if opcode in {"local.set", "global.set", "drop"}:
        return 1, 0
    if opcode == "local.tee":
        return 1, 1
    if ".load" in opcode:
        return 1, 1
    if ".store" in opcode:
        return 2, 0
    if opcode == "select":
        return 3, 1
    if opcode == "memory.grow":
        return 1, 1
    if opcode in {"memory.copy", "memory.fill", "table.copy", "table.fill"}:
        return 3, 0
    if opcode in {"memory.init", "table.init"}:
        return 3, 0
    if opcode in {"data.drop", "elem.drop", "nop"}:
        return 0, 0
    suffix = opcode.split(".", 1)[-1]
    if suffix in {
        "eqz", "clz", "ctz", "popcnt", "abs", "neg", "ceil", "floor", "trunc",
        "nearest", "sqrt", "wrap_i64", "extend_i32_s", "extend_i32_u", "extend8_s",
        "extend16_s", "extend32_s", "trunc_f32_s", "trunc_f32_u", "trunc_f64_s",
        "trunc_f64_u", "trunc_sat_f32_s", "trunc_sat_f32_u", "trunc_sat_f64_s",
        "trunc_sat_f64_u", "convert_i32_s", "convert_i32_u", "convert_i64_s",
        "convert_i64_u", "demote_f64", "promote_f32", "reinterpret_f32", "reinterpret_f64",
        "reinterpret_i32", "reinterpret_i64", "ref.is_null",
    }:
        return 1, 1
    if suffix in {
        "eq", "ne", "lt_s", "lt_u", "lt", "gt_s", "gt_u", "gt", "le_s", "le_u",
        "le", "ge_s", "ge_u", "ge", "add", "sub", "mul", "div_s", "div_u", "div",
        "rem_s", "rem_u", "and", "or", "xor", "shl", "shr_s", "shr_u", "rotl", "rotr",
        "min", "max", "copysign",
    }:
        return 2, 1
    raise VerificationError(f"unsupported WAT stack instruction in operand proof: {normalized}")


def _structured_expression_start(function: Any, end_index: int) -> tuple[int, int, int]:
    depth = 1
    for index in range(end_index - 1, -1, -1):
        raw = FEE.normalized(function.lines[index])
        normalized = raw.rstrip(")")
        opcode = normalized.split()[0]
        if opcode == "end":
            depth += 1
        elif opcode in {"block", "loop", "if"}:
            depth -= 1
            if depth == 0:
                results = _signature_counts(raw)[1]
                params = _signature_counts(raw)[0]
                if opcode == "if":
                    params += 1
                return index, params, results
    raise VerificationError(f"{function.name} unterminated structured operand expression")


def _previous_operand_expression(
    function: Any,
    end_exclusive: int,
    signatures: dict[str, tuple[int, int]],
) -> dict[str, Any]:
    needed = 1
    cursor = end_exclusive
    while needed:
        require(cursor > 1, f"{function.name} operand expression underflow at {end_exclusive}")
        cursor -= 1
        normalized = FEE.normalized(function.lines[cursor]).rstrip(")")
        opcode = normalized.split()[0]
        if opcode == "end":
            start, consumed, produced = _structured_expression_start(function, cursor)
            require(produced > 0, f"{function.name} non-value block in operand expression")
            cursor = start
        else:
            consumed, produced = _instruction_stack_effect(function.lines[cursor], signatures)
        needed = max(0, needed - produced) + consumed
    lines = [FEE.normalized(line) for line in function.lines[cursor:end_exclusive]]
    return {
        "start_relative_wat_line": cursor,
        "end_relative_wat_line": end_exclusive - 1,
        "normalized_sha256": canonical_sha256(lines),
        "lines": lines,
    }


def _call_operand_expressions(
    function: Any,
    call_index: int,
    arity: int,
    signatures: dict[str, tuple[int, int]],
) -> list[dict[str, Any]]:
    operands: list[dict[str, Any]] = []
    end = call_index
    for _ in range(arity):
        operand = _previous_operand_expression(function, end, signatures)
        operands.append(operand)
        end = operand["start_relative_wat_line"]
    return list(reversed(operands))


def _operand_local(operand: dict[str, Any]) -> str | None:
    terminal = operand["lines"][-1].rstrip(")")
    match = re.fullmatch(r"local\.(?:get|tee) (\$\S+)", terminal)
    return match.group(1) if match is not None else None


def _operand_local_observation_line(operand: dict[str, Any]) -> int:
    terminal = operand["lines"][-1].rstrip(")")
    if re.fullmatch(r"local\.get (\$\S+)", terminal) is not None:
        return operand["end_relative_wat_line"]
    if re.fullmatch(r"local\.tee (\$\S+)", terminal) is not None:
        return operand["end_relative_wat_line"] + 1
    raise VerificationError("operand has no direct terminal local value")


def _operand_decoded_constants(operand: dict[str, Any], memory: bytearray) -> list[str]:
    if len(operand["lines"]) != 1:
        return []
    value = FEE.decoded_constant(operand["lines"][0], memory)
    return [value] if value is not None else []


def _linear_operand_output_provenance(
    operand: dict[str, Any],
    signatures: dict[str, tuple[int, int]],
    entry_parameters: list[str],
) -> tuple[str, str] | None:
    """Return an unchanged terminal local only when stack evaluation proves it."""
    stack: list[tuple[str, str]] = []
    locals_provenance = {
        parameter: ("entry_parameter", parameter)
        for parameter in entry_parameters
    }
    for ordinal, line in enumerate(operand["lines"]):
        normalized = line.rstrip(")")
        opcode = normalized.split()[0]
        if opcode in {"block", "loop", "if", "else", "end", "br", "br_if"}:
            return None
        if (match := re.fullmatch(r"local\.get (\$\S+)", normalized)) is not None:
            stack.append(
                locals_provenance.get(
                    match.group(1),
                    ("unknown_local", match.group(1)),
                )
            )
            continue
        if (match := re.fullmatch(r"local\.tee (\$\S+)", normalized)) is not None:
            if not stack:
                return None
            locals_provenance[match.group(1)] = stack[-1]
            continue
        if (match := re.fullmatch(r"local\.set (\$\S+)", normalized)) is not None:
            if not stack:
                return None
            locals_provenance[match.group(1)] = stack.pop()
            continue
        consumed, produced = _instruction_stack_effect(line, signatures)
        if len(stack) < consumed:
            return None
        if consumed:
            del stack[-consumed:]
        for result_ordinal in range(produced):
            stack.append(("computed", f"{ordinal}:{result_ordinal}:{opcode}"))
    return stack[0] if len(stack) == 1 else None


def _function_parameters(signature_proof: dict[str, Any], function: Any) -> list[str]:
    normalized_name = FEE.normalized(function.name)
    require(
        normalized_name in signature_proof["parameters"],
        f"WAT parameter ledger missing: {normalized_name}",
    )
    return signature_proof["parameters"][normalized_name]


def _local_value_identity_snapshots(
    function: Any,
    signature_proof: dict[str, Any],
) -> list[dict[str, frozenset[tuple[str, int]]]]:
    cache_key = (function.name, FEE.function_sha256(function))
    if cache_key in _LOCAL_VALUE_SNAPSHOT_CACHE:
        return _LOCAL_VALUE_SNAPSHOT_CACHE[cache_key]
    initial: dict[str, frozenset[tuple[str, int]]] = {
        parameter: frozenset({(parameter, -1)})
        for parameter in _function_parameters(signature_proof, function)
    }
    for line in function.lines:
        for local in re.findall(r"\(local (\$\S+) (?:i32|i64|f32|f64|v128)\)", line):
            initial.setdefault(local, frozenset({(local, -1)}))

    def merge(
        left: dict[str, frozenset[tuple[str, int]]],
        right: dict[str, frozenset[tuple[str, int]]],
    ) -> dict[str, frozenset[tuple[str, int]]]:
        merged: dict[str, frozenset[tuple[str, int]]] = {}
        for local in left.keys() | right.keys():
            left_identity = left.get(local, frozenset({(local, -1)}))
            right_identity = right.get(local, frozenset({(local, -1)}))
            merged[local] = frozenset(left_identity | right_identity)
        return merged

    frames: list[dict[str, Any]] = []
    frame_by_start: dict[int, dict[str, Any]] = {}
    frame_by_else: dict[int, dict[str, Any]] = {}
    branch_targets: dict[int, list[dict[str, Any]]] = {}

    def resolve_branch_target(token: str, index: int) -> dict[str, Any]:
        if token.startswith("$"):
            frame = next(
                (item for item in reversed(frames) if item["label"] == token),
                None,
            )
        elif token.isdigit() and int(token) < len(frames):
            frame = frames[-1 - int(token)]
        else:
            frame = None
        require(
            frame is not None,
            f"{function.name} unresolved branch target in local identity proof at "
            f"{index}: {token}",
        )
        return frame

    for index, line in enumerate(function.lines):
        normalized = FEE.normalized(line).rstrip(")")
        opcode = normalized.split()[0]
        if opcode in {"if", "block", "loop"}:
            label_match = re.match(r"(?:if|block|loop) (\$\S+)", normalized)
            frame = {
                "kind": opcode,
                "label": label_match.group(1) if label_match is not None else None,
                "start": index,
                "else": None,
                "end": None,
            }
            frames.append(frame)
            frame_by_start[index] = frame
            continue
        if opcode == "else":
            require(
                frames and frames[-1]["kind"] == "if" and frames[-1]["else"] is None,
                f"{function.name} unmatched else in local identity proof",
            )
            frames[-1]["else"] = index
            frame_by_else[index] = frames[-1]
            continue
        if opcode == "end":
            require(frames, f"{function.name} unmatched end in local identity proof")
            frame = frames.pop()
            frame["end"] = index
            continue
        if opcode in {"br", "br_if", "br_table"}:
            tokens = normalized.split()[1:]
            require(tokens, f"{function.name} branch target missing at {index}")
            branch_targets[index] = [
                resolve_branch_target(token, index) for token in tokens
            ]
            continue
        require(
            not opcode.startswith("br_"),
            f"{function.name} unsupported branch opcode in local identity proof: {opcode}",
        )
    require(not frames, f"{function.name} unterminated control frame in local identity proof")

    def branch_successor(frame: dict[str, Any]) -> int:
        require(
            frame["end"] is not None,
            f"{function.name} branch target has no structured end",
        )
        return frame["start"] + 1 if frame["kind"] == "loop" else frame["end"] + 1

    def successors(index: int) -> list[int]:
        normalized = FEE.normalized(function.lines[index]).rstrip(")")
        opcode = normalized.split()[0]
        fallthrough = index + 1
        if opcode == "if":
            frame = frame_by_start[index]
            require(frame["end"] is not None, f"{function.name} if has no end")
            false_successor = (
                frame["else"] + 1
                if frame["else"] is not None
                else frame["end"] + 1
            )
            return list(dict.fromkeys((fallthrough, false_successor)))
        if opcode == "else":
            frame = frame_by_else[index]
            require(frame["end"] is not None, f"{function.name} else has no end")
            return [frame["end"] + 1]
        if opcode == "br":
            return list(
                dict.fromkeys(branch_successor(frame) for frame in branch_targets[index])
            )
        if opcode == "br_if":
            return list(
                dict.fromkeys(
                    [fallthrough]
                    + [branch_successor(frame) for frame in branch_targets[index]]
                )
            )
        if opcode == "br_table":
            return list(
                dict.fromkeys(branch_successor(frame) for frame in branch_targets[index])
            )
        if opcode in {"return", "unreachable", "throw", "rethrow"} or opcode.startswith(
            "return_call"
        ):
            return []
        return [fallthrough]

    snapshots: list[dict[str, frozenset[tuple[str, int]]] | None] = [
        None for _ in range(len(function.lines) + 1)
    ]
    snapshots[0] = initial
    pending = [0]
    queued = {0}
    while pending:
        index = pending.pop()
        queued.remove(index)
        if index == len(function.lines):
            continue
        state = snapshots[index]
        require(state is not None, f"{function.name} reachable work item lost its state")
        output = dict(state)
        normalized = FEE.normalized(function.lines[index]).rstrip(")")
        match = re.fullmatch(r"local\.(?:set|tee) (\$\S+)", normalized)
        if match is not None:
            destination = match.group(1)
            source = FEE.local_name(function.lines[index - 1], "get") if index else None
            if source is None and index:
                source = FEE.local_name(function.lines[index - 1], "tee")
            output[destination] = (
                state[source]
                if source is not None and source in state
                else frozenset({(destination, index)})
            )
        for successor in successors(index):
            require(
                0 <= successor <= len(function.lines),
                f"{function.name} control-flow successor out of range: {successor}",
            )
            previous = snapshots[successor]
            updated = output if previous is None else merge(previous, output)
            if previous != updated:
                snapshots[successor] = updated
                if successor not in queued:
                    pending.append(successor)
                    queued.add(successor)

    rendered = [dict(state) if state is not None else {} for state in snapshots]
    _LOCAL_VALUE_SNAPSHOT_CACHE[cache_key] = rendered
    return rendered


def _local_value_identity(
    function: Any,
    receiver_local: str,
    observation_line: int,
    signature_proof: dict[str, Any],
) -> dict[str, Any]:
    snapshots = _local_value_identity_snapshots(function, signature_proof)
    require(
        0 <= observation_line < len(snapshots),
        f"{function.name} receiver identity observation line out of range",
    )
    identity = snapshots[observation_line].get(receiver_local)
    require(
        identity is not None,
        f"{function.name} receiver local has no retained value identity: {receiver_local}",
    )
    origins = [
        {
            "origin_local": origin_local,
            "definition_relative_wat_line": definition_line,
        }
        for origin_local, definition_line in sorted(identity)
    ]
    return {
        "origin_local": origins[0]["origin_local"] if len(origins) == 1 else None,
        "definition_relative_wat_line": (
            origins[0]["definition_relative_wat_line"] if len(origins) == 1 else None
        ),
        "value_origins": origins,
        "observed_local": receiver_local,
        "observation_relative_wat_line": observation_line,
    }


def _value_identity_atoms(identity: dict[str, Any]) -> set[tuple[str, int]]:
    return {
        (item["origin_local"], item["definition_relative_wat_line"])
        for item in identity["value_origins"]
    }


def _entry_parameter_value_identity(
    context: dict[str, Any],
    function: Any,
    parameter: str,
    observation_line: int,
    signature_proof: dict[str, Any],
    boundary: str,
) -> dict[str, Any]:
    require(
        parameter in _function_parameters(signature_proof, function),
        f"{context['mapping_cid']} {boundary} is not a retained parameter: {parameter}",
    )
    identity = _local_value_identity(
        function,
        parameter,
        observation_line,
        signature_proof,
    )
    require(
        _value_identity_atoms(identity) == {(parameter, -1)},
        f"{context['mapping_cid']} {boundary} entry-value identity proof failed: "
        f"{parameter} resolved to {sorted(_value_identity_atoms(identity))}",
    )
    return identity


def _prove_named_setter_receiver_flow(
    context: dict[str, Any],
    target: str,
    field: str,
    signature_proof: dict[str, Any],
) -> list[dict[str, Any]]:
    signatures = signature_proof["functions"]
    map_set = (
        FEE.MODERN_MAP_SET
        if context["profile"]["control_generation"] == "modern"
        else FEE.LEGACY_MAP_SET
    )
    root = _resolve_function_name(context, target)
    pending = [root]
    visited: set[str] = set()
    sites: list[dict[str, Any]] = []
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        function = context["functions"][name]
        parameters = _function_parameters(signature_proof, function)
        require(parameters, f"{context['mapping_cid']} setter has no receiver parameter: {name}")
        receiver_parameter = parameters[0]
        for index, line in enumerate(function.lines):
            child = FEE.call_name(line)
            if child == map_set:
                operands = _call_operand_expressions(function, index, 3, signatures)
                receiver_local = _operand_local(operands[0])
                require(
                    receiver_local == receiver_parameter,
                    f"{context['mapping_cid']} local receiver-flow proof failed for {field}: "
                    f"{name}[{index}] uses {receiver_local}, expected {receiver_parameter}",
                )
                receiver_entry_identity = _entry_parameter_value_identity(
                    context,
                    function,
                    receiver_parameter,
                    _operand_local_observation_line(operands[0]),
                    signature_proof,
                    f"setter receiver parameter for {field}",
                )
                keys = _operand_decoded_constants(operands[1], context["memory"])
                require(
                    keys == [field],
                    f"{context['mapping_cid']} local field-key operand proof failed for {field}: "
                    f"{name}[{index}] decoded {keys}",
                )
                sites.append(
                    {
                        "function": name,
                        "relative_wat_line": index,
                        "receiver_parameter": receiver_parameter,
                        "receiver_parameter_entry_value_identity": receiver_entry_identity,
                        "receiver_operand": {key: value for key, value in operands[0].items() if key != "lines"},
                        "field_key_operand": {key: value for key, value in operands[1].items() if key != "lines"},
                    }
                )
            elif child is not None and child.endswith("Entity#unset"):
                require(child in signatures and signatures[child][0] == 2, f"{context['mapping_cid']} Entity#unset signature drift")
                operands = _call_operand_expressions(function, index, 2, signatures)
                child_receiver = _operand_local(operands[0])
                keys = _operand_decoded_constants(operands[1], context["memory"])
                require(
                    child_receiver == receiver_parameter and keys == [field],
                    f"{context['mapping_cid']} nullable local receiver/key proof failed for {field}",
                )
                _entry_parameter_value_identity(
                    context,
                    function,
                    receiver_parameter,
                    _operand_local_observation_line(operands[0]),
                    signature_proof,
                    f"nullable setter receiver parameter for {field}",
                )
                child_name = _resolve_function_name(context, child)
                child_function = context["functions"][child_name]
                child_parameters = _function_parameters(signature_proof, child_function)
                require(len(child_parameters) == 2, f"{context['mapping_cid']} Entity#unset parameters drift")
                physical_sites = [
                    physical_index
                    for physical_index, physical_line in enumerate(child_function.lines)
                    if FEE.call_name(physical_line) == map_set
                ]
                require(len(physical_sites) == 1, f"{context['mapping_cid']} Entity#unset map-set count drift")
                physical_index = physical_sites[0]
                physical_operands = _call_operand_expressions(
                    child_function,
                    physical_index,
                    3,
                    signatures,
                )
                physical_receiver = _operand_local(physical_operands[0])
                key_provenance = _linear_operand_output_provenance(
                    physical_operands[1],
                    signatures,
                    child_parameters,
                )
                require(
                    physical_receiver == child_parameters[0]
                    and key_provenance
                    == ("entry_parameter", child_parameters[1]),
                    f"{context['mapping_cid']} Entity#unset physical receiver/key operand proof failed",
                )
                receiver_entry_identity = _entry_parameter_value_identity(
                    context,
                    child_function,
                    child_parameters[0],
                    _operand_local_observation_line(physical_operands[0]),
                    signature_proof,
                    f"Entity#unset receiver parameter for {field}",
                )
                key_entry_identity = _entry_parameter_value_identity(
                    context,
                    child_function,
                    child_parameters[1],
                    physical_operands[1]["start_relative_wat_line"],
                    signature_proof,
                    f"Entity#unset key parameter for {field}",
                )
                nullable_flow = {
                    "function": child_name,
                    "relative_wat_line": physical_index,
                    "receiver_parameter": child_parameters[0],
                    "key_parameter": child_parameters[1],
                    "receiver_operand": {
                        key: value
                        for key, value in physical_operands[0].items()
                        if key != "lines"
                    },
                    "key_operand": {
                        key: value
                        for key, value in physical_operands[1].items()
                        if key != "lines"
                    },
                    "receiver_parameter_entry_value_identity": receiver_entry_identity,
                    "key_parameter_entry_value_identity": key_entry_identity,
                    "retained_body_sha256": FEE.function_sha256(child_function),
                    "nullable_unset_physical_receiver_key_operands_machine_bound": True,
                }
                sites.append(nullable_flow)
            elif child is not None and "schema/" in child and "#set:" in child:
                child_name = _resolve_function_name(context, child)
                arity = signatures[child][0]
                require(arity >= 1, f"{context['mapping_cid']} nested setter has no receiver")
                operands = _call_operand_expressions(function, index, arity, signatures)
                child_receiver = _operand_local(operands[0])
                require(
                    child_receiver == receiver_parameter,
                    f"{context['mapping_cid']} nested local receiver-flow proof failed for {field}: "
                    f"{name}[{index}] uses {child_receiver}, expected {receiver_parameter}",
                )
                _entry_parameter_value_identity(
                    context,
                    function,
                    receiver_parameter,
                    _operand_local_observation_line(operands[0]),
                    signature_proof,
                    f"nested setter receiver parameter for {field}",
                )
                pending.append(child_name)
    require(sites, f"{context['mapping_cid']} setter receiver flow reaches no TypedMap#set: {field}")
    return sites


def _prove_constructor_receiver_flow(
    context: dict[str, Any],
    target: str,
    field: str,
    signature_proof: dict[str, Any],
) -> dict[str, Any]:
    signatures = signature_proof["functions"]
    map_set = (
        FEE.MODERN_MAP_SET
        if context["profile"]["control_generation"] == "modern"
        else FEE.LEGACY_MAP_SET
    )
    name = _resolve_function_name(context, target)
    function = context["functions"][name]
    sites = [
        index
        for index, line in enumerate(function.lines)
        if FEE.call_name(line) == map_set
    ]
    require(len(sites) == 1, f"{context['mapping_cid']} constructor TypedMap#set count drift")
    index = sites[0]
    operands = _call_operand_expressions(function, index, 3, signatures)
    receiver_local = _operand_local(operands[0])
    keys = _operand_decoded_constants(operands[1], context["memory"])
    require(
        receiver_local is not None and keys == [field],
        f"{context['mapping_cid']} constructor local receiver/key proof failed for {field}",
    )
    internal_receiver_identity = _local_value_identity(
        function,
        receiver_local,
        _operand_local_observation_line(operands[0]),
        signature_proof,
    )
    terminal_index = len(function.lines) - 1
    returned_local = FEE.local_name(function.lines[terminal_index], "get")
    require(
        returned_local == receiver_local,
        f"{context['mapping_cid']} constructor immediate-fallthrough terminal receiver "
        f"proof failed for {field}: "
        f"{returned_local} != {receiver_local}",
    )
    require(
        index + 1 == terminal_index,
        f"{context['mapping_cid']} constructor map-set/terminal return adjacency proof "
        f"failed for {field}: map-set at {index}, terminal get at {terminal_index}",
    )
    returned_receiver_identity = _local_value_identity(
        function,
        returned_local,
        terminal_index,
        signature_proof,
    )
    require(
        _value_identity_atoms(internal_receiver_identity)
        == _value_identity_atoms(returned_receiver_identity),
        f"{context['mapping_cid']} constructor map-set-to-return value identity proof failed "
        f"for {field}",
    )
    return {
        "function": name,
        "relative_wat_line": index,
        "internal_receiver_local": receiver_local,
        "immediate_fallthrough_terminal_receiver_local": returned_local,
        "internal_receiver_value_identity": internal_receiver_identity,
        "immediate_fallthrough_terminal_receiver_value_identity": returned_receiver_identity,
        "internal_map_set_immediately_precedes_terminal_return_get": True,
        "constructor_receiver_on_immediate_normal_fallthrough_to_terminal_get_bound": True,
        "all_successful_constructor_returns_and_control_paths_return_internal_receiver_proven": False,
        "receiver_operand": {key: value for key, value in operands[0].items() if key != "lines"},
        "field_key_operand": {key: value for key, value in operands[1].items() if key != "lines"},
    }


def _setter_receiver_binding(
    context: dict[str, Any],
    function: Any,
    operation: dict[str, Any],
    field: str,
    signature_proof: dict[str, Any],
) -> dict[str, Any]:
    target = operation["call_target"]
    index = operation["relative_wat_line"]
    signatures = signature_proof["functions"]
    map_set = (
        FEE.MODERN_MAP_SET
        if context["profile"]["control_generation"] == "modern"
        else FEE.LEGACY_MAP_SET
    )
    if target == map_set:
        operands = _call_operand_expressions(function, index, 3, signatures)
        receiver_local = _operand_local(operands[0])
        keys = _operand_decoded_constants(operands[1], context["memory"])
        require(
            receiver_local is not None,
            f"{context['mapping_cid']} local receiver operand proof failed for {field}",
        )
        require(
            keys == [field],
            f"{context['mapping_cid']} local field-key operand proof failed for {field}: {keys}",
        )
        physical = [
            {
                "function": function.name,
                "relative_wat_line": index,
                "receiver_local": receiver_local,
                "receiver_operand": {key: value for key, value in operands[0].items() if key != "lines"},
                "field_key_operand": {key: value for key, value in operands[1].items() if key != "lines"},
            }
        ]
        kind = "direct_typed_map_set_receiver_operand"
        observation_line = _operand_local_observation_line(operands[0])
    elif "#constructor" in target:
        require(
            index + 1 < len(function.lines),
            f"{context['mapping_cid']} constructor result binding underflow",
        )
        capture = FEE.normalized(function.lines[index + 1]).rstrip(")")
        match = re.fullmatch(r"local\.(?:set|tee) (\$\S+)", capture)
        require(
            match is not None,
            f"{context['mapping_cid']} local constructor-result receiver proof failed for {field}",
        )
        receiver_local = match.group(1)
        physical = [_prove_constructor_receiver_flow(context, target, field, signature_proof)]
        kind = (
            "constructor_call_result_with_immediate_fallthrough_internal_map_set_"
            "receiver_evidence"
        )
        observation_line = index + 2
    else:
        require(target in signatures, f"{context['mapping_cid']} setter signature missing: {target}")
        arity = signatures[target][0]
        require(arity >= 1, f"{context['mapping_cid']} setter has no callsite receiver: {target}")
        operands = _call_operand_expressions(function, index, arity, signatures)
        receiver_local = _operand_local(operands[0])
        require(
            receiver_local is not None,
            f"{context['mapping_cid']} local caller receiver operand proof failed for {field}",
        )
        physical = _prove_named_setter_receiver_flow(context, target, field, signature_proof)
        kind = "caller_receiver_operand_through_setter_parameter_to_typed_map_set"
        observation_line = _operand_local_observation_line(operands[0])
    receiver_value_identity = _local_value_identity(
        function,
        receiver_local,
        observation_line,
        signature_proof,
    )
    return {
        "receiver_local": receiver_local,
        "receiver_value_identity": receiver_value_identity,
        "receiver_binding_kind": kind,
        "physical_receiver_flow_count": len(physical),
        "physical_receiver_flows": physical,
        "physical_receiver_flow_sha256": canonical_sha256(physical),
    }


def _group_functions(context: dict[str, Any]) -> dict[str, Any]:
    result = {"handler": context["handler"]}
    for group in GROUP_SEQUENCES:
        if group != "handler":
            result[group] = _function_by_suffix(context, group)
    return result


def _logical_operations(context: dict[str, Any], function: Any) -> list[dict[str, Any]]:
    generation = context["profile"]["control_generation"]
    map_set = FEE.MODERN_MAP_SET if generation == "modern" else FEE.LEGACY_MAP_SET
    output: list[dict[str, Any]] = []
    for index, line in enumerate(function.lines):
        target = FEE.call_name(line)
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
                            FEE.normalized(item)
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
            if (FEE.call_name(line) or "").endswith(suffix)
        ]

    load_tick = _function_by_suffix(context, "loadTickUpdateFeeVarsAndSave")
    actual = {
        "loadTransaction": sites(handler, "loadTransaction"),
        "loadTickUpdateFeeVarsAndSave": sites(handler, "loadTickUpdateFeeVarsAndSave"),
        "updateTickFeeVarsAndSave_from_load_helper": sites(load_tick, "updateTickFeeVarsAndSave"),
        "updateTickDayData_from_tick_helper": sites(groups["updateTickFeeVarsAndSave"], "updateTickDayData"),
        "updateUniswapDayData": sites(handler, "updateUniswapDayData"),
        "updatePoolDayData": sites(handler, "updatePoolDayData"),
        "updatePoolHourData": sites(handler, "updatePoolHourData"),
        "updateTokenDayData": sites(handler, "updateTokenDayData"),
        "updateTokenHourData": sites(handler, "updateTokenHourData"),
    }
    expected_counts = {
        "loadTransaction": 1,
        "loadTickUpdateFeeVarsAndSave": 3,
        "updateTickFeeVarsAndSave_from_load_helper": 1,
        "updateTickDayData_from_tick_helper": 1,
        "updateUniswapDayData": 1,
        "updatePoolDayData": 1,
        "updatePoolHourData": 1,
        "updateTokenDayData": 2,
        "updateTokenHourData": 2,
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
        "load_tick_helper_function": load_tick.name,
        "load_tick_helper_body_sha256": FEE.function_sha256(load_tick),
        "helper_fanout_exactly_bound": True,
    }


def _physical_setter_coverage(
    context: dict[str, Any], lexical: list[dict[str, Any]], reachable: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    generation = context["profile"]["control_generation"]
    map_set = FEE.MODERN_MAP_SET if generation == "modern" else FEE.LEGACY_MAP_SET
    sites = [
        {"function": name, "relative_wat_line": index}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if FEE.call_name(line) == map_set
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
                child = FEE.call_name(line)
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
    require(
        len(edges) == len(lexical) + 4,
        f"{context['mapping_cid']} site-to-invocation edge count drift: {len(edges)} != {len(lexical)} + 4",
    )
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


def _direct_store_receiver_binding(
    context: dict[str, Any],
    function: Any,
    index: int,
    signature_proof: dict[str, Any],
) -> dict[str, Any]:
    operands = _call_operand_expressions(
        function,
        index,
        3,
        signature_proof["functions"],
    )
    targets = _operand_decoded_constants(operands[0], context["memory"])
    receiver_local = _operand_local(operands[2])
    require(
        len(targets) == 1 and targets[0] in STORE_TARGETS,
        f"{context['mapping_cid']} direct store target operand proof failed: {targets}",
    )
    require(
        receiver_local is not None,
        f"{context['mapping_cid']} direct store receiver operand proof failed: "
        f"{function.name}[{index}]",
    )
    receiver_observation_line = _operand_local_observation_line(operands[2])
    receiver_value_identity = _local_value_identity(
        function,
        receiver_local,
        receiver_observation_line,
        signature_proof,
    )
    return {
        "function": function.name,
        "relative_wat_line": index,
        "target": targets[0],
        "receiver_local": receiver_local,
        "receiver_observation_relative_wat_line": receiver_observation_line,
        "receiver_value_identity": receiver_value_identity,
        "target_operand": {key: value for key, value in operands[0].items() if key != "lines"},
        "id_operand": {key: value for key, value in operands[1].items() if key != "lines"},
        "receiver_operand": {key: value for key, value in operands[2].items() if key != "lines"},
    }


def _schema_save_receiver_binding(
    context: dict[str, Any],
    caller: Any,
    call_index: int,
    call_target: str,
    signature_proof: dict[str, Any],
) -> dict[str, Any]:
    signatures = signature_proof["functions"]
    require(
        call_target in signatures and signatures[call_target][0] == 1,
        f"{context['mapping_cid']} schema save signature drift: {call_target}",
    )
    caller_operands = _call_operand_expressions(caller, call_index, 1, signatures)
    caller_receiver = _operand_local(caller_operands[0])
    require(
        caller_receiver is not None,
        f"{context['mapping_cid']} schema save caller receiver operand proof failed: "
        f"{caller.name}[{call_index}]",
    )
    save_name = _resolve_function_name(context, call_target)
    save = context["functions"][save_name]
    parameters = _function_parameters(signature_proof, save)
    require(len(parameters) == 1, f"{context['mapping_cid']} schema save parameter drift")
    physical_sites = [
        index
        for index, line in enumerate(save.lines)
        if FEE.call_name(line) == WRITER.STORE_SET_CALL
    ]
    require(len(physical_sites) == 1, f"{context['mapping_cid']} schema save store-set count drift")
    physical = _direct_store_receiver_binding(
        context,
        save,
        physical_sites[0],
        signature_proof,
    )
    require(
        physical["receiver_local"] == parameters[0],
        f"{context['mapping_cid']} local save receiver-flow proof failed for {physical['target']}: "
        f"{physical['receiver_local']} != {parameters[0]}",
    )
    save_parameter_entry_identity = _entry_parameter_value_identity(
        context,
        save,
        parameters[0],
        physical["receiver_observation_relative_wat_line"],
        signature_proof,
        f"save receiver parameter for {physical['target']}",
    )
    caller_receiver_value_identity = _local_value_identity(
        caller,
        caller_receiver,
        _operand_local_observation_line(caller_operands[0]),
        signature_proof,
    )
    symbol_match = re.search(r"schema/([^/#]+)#save", call_target)
    require(symbol_match is not None, f"{context['mapping_cid']} schema save symbol shape drift")
    return {
        "target": physical["target"],
        "receiver_local": caller_receiver,
        "receiver_value_identity": caller_receiver_value_identity,
        "binding_kind": "caller_receiver_operand_through_save_parameter_to_store_value",
        "schema_symbol_target": symbol_match.group(1),
        "caller_receiver_operand": {
            key: value for key, value in caller_operands[0].items() if key != "lines"
        },
        "save_function": save_name,
        "save_receiver_parameter": parameters[0],
        "save_receiver_parameter_entry_value_identity": save_parameter_entry_identity,
        "physical_store_receiver_flow": physical,
        "same_caller_receiver_to_save_parameter_to_store_value_machine_bound": True,
    }


def _store_closure(
    context: dict[str, Any],
    reachable: list[str],
    core_proof: dict[str, Any],
    field_lexical: list[dict[str, Any]],
    signature_proof: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile_id = context["profile"]["profile_id"]
    groups = _group_functions(context)
    lexical: list[dict[str, Any]] = []
    ordinals: Counter[tuple[str, str]] = Counter()
    for group, function in groups.items():
        for index, line in enumerate(function.lines):
            call = FEE.call_name(line)
            if call is None or ("#save" not in call and call != WRITER.STORE_SET_CALL):
                continue
            if "#save" in call:
                binding = _schema_save_receiver_binding(
                    context,
                    function,
                    index,
                    call,
                    signature_proof,
                )
            else:
                physical = _direct_store_receiver_binding(
                    context,
                    function,
                    index,
                    signature_proof,
                )
                binding = {
                    "target": physical["target"],
                    "receiver_local": physical["receiver_local"],
                    "receiver_value_identity": physical["receiver_value_identity"],
                    "binding_kind": "direct_store_target_and_receiver_operands",
                    "schema_symbol_target": None,
                    "caller_receiver_operand": physical["receiver_operand"],
                    "save_function": None,
                    "save_receiver_parameter": None,
                    "physical_store_receiver_flow": physical,
                    "direct_store_exact_target_and_receiver_value_operands_machine_bound": True,
                }
            target = binding["target"]
            receiver_local = binding["receiver_local"]
            ordinal = ordinals[(group, target)]
            ordinals[(group, target)] += 1
            lexical.append(
                {
                    "store_authority_id": f"{group}[{target}:{ordinal}]@{index}",
                    "group": group,
                    "function": function.name,
                    "relative_wat_line": index,
                    "call_target": call,
                    "target": target,
                    "ordinal_in_group_target": ordinal,
                    "receiver_local": receiver_local,
                    "receiver_value_identity": binding["receiver_value_identity"],
                    "receiver_store_authority": binding,
                }
            )

    expected_lexical = (
        23
        if profile_id.startswith("modern-")
        else 22
        if profile_id == "legacy-base-root"
        else 19
    )
    require(len(lexical) == expected_lexical, f"{cid} lexical Graph store count drift")
    for record in lexical:
        authority = record["receiver_store_authority"]
        if authority["binding_kind"] == "direct_store_target_and_receiver_operands":
            require(
                authority.get(
                    "direct_store_exact_target_and_receiver_value_operands_machine_bound"
                )
                is True
                and "same_caller_receiver_to_save_parameter_to_store_value_machine_bound"
                not in authority
                and authority["save_function"] is None
                and authority["save_receiver_parameter"] is None,
                f"{cid} direct-store authority flag-kind invariant failed",
            )
        else:
            require(
                authority["binding_kind"]
                == "caller_receiver_operand_through_save_parameter_to_store_value"
                and authority.get(
                    "same_caller_receiver_to_save_parameter_to_store_value_machine_bound"
                )
                is True
                and "direct_store_exact_target_and_receiver_value_operands_machine_bound"
                not in authority
                and authority["save_function"] is not None
                and authority["save_receiver_parameter"] is not None,
                f"{cid} save-transit authority flag-kind invariant failed",
            )
    handler_targets = Counter(
        item["target"] for item in lexical if item["group"] == "handler"
    )
    expected_handler = Counter(
        {
            "Bundle": 1,
            "Factory": 1,
            "Pool": 2,
            "PoolDayData": 1,
            "Swap": 1,
            "Token": 2,
            "TokenDayData": 2,
            "UniswapDayData": 1,
        }
    )
    if profile_id == "legacy-base-root":
        expected_handler.update({"PoolHourData": 1, "TokenHourData": 2})
    elif profile_id.startswith("modern-"):
        expected_handler.update({"PoolHourData": 2, "TokenHourData": 2})
    require(handler_targets == expected_handler, f"{cid} handler store profile shape drift")

    store_callsites = WRITER.extract_store_set_callsites(context["functions"], context["memory"])
    WRITER.require_fixed_callsites(store_callsites, f"{cid} Pool Swap v2")
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
    require(len(physical) == 13, f"{cid} physical store count drift")
    require(
        sorted(item["target"] for item in physical) == list(STORE_TARGETS),
        f"{cid} physical store target drift",
    )

    expanded = [
        {
            "target": item["target"],
            "lexical_group": item["group"],
            "lexical_store_relative_wat_line": item["relative_wat_line"],
            "path_id": (
                f"{path_id}/{item['target']}.store"
                f"[{item['ordinal_in_group_target']}]"
            ),
        }
        for item in lexical
        for path_id in PATH_IDS[item["group"]]
    ]
    expected_expanded = (
        29
        if profile_id.startswith("modern-")
        else 28
        if profile_id == "legacy-base-root"
        else 25
    )
    require(len(expanded) == expected_expanded, f"{cid} expanded store path drift")

    transitive = core_proof["save_and_effect_closure"]["transitive_store_evidence"]
    require(transitive["reachable_store_set_site_count"] == 13, "core physical store count drift")
    require(transitive["reachable_store_set_targets"] == list(STORE_TARGETS), "core store target drift")
    require(transitive["dynamic_reachable_store_set_target_count"] == 0, "dynamic store target")
    require(transitive["unmodelled_store_mutation_host_import_count"] == 0, "unmodelled store mutation")
    remove_calls = [
        {"function": name, "relative_wat_line": index, "call_target": target}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if (target := FEE.call_name(line)) is not None and "store.remove" in target
    ]
    require(not remove_calls, f"{cid} reachable store.remove")

    handler_pool_saves = [
        item for item in lexical
        if item["group"] == "handler" and item["target"] == "Pool"
    ]
    require(
        len(handler_pool_saves) == 2
        and len({item["receiver_local"] for item in handler_pool_saves}) == 1,
        f"{cid} two same-receiver Pool saves drift",
    )
    handler_pool_hour_saves = [
        item for item in lexical
        if item["group"] == "handler" and item["target"] == "PoolHourData"
    ]
    expected_pool_hour_count = (
        2 if profile_id.startswith("modern-") else 1 if profile_id == "legacy-base-root" else 0
    )
    require(
        len(handler_pool_hour_saves) == expected_pool_hour_count,
        f"{cid} handler PoolHourData save multiplicity drift",
    )
    duplicate_pool_hour = None
    if profile_id.startswith("modern-"):
        first, second = handler_pool_hour_saves
        intervening = [
            item for item in field_lexical
            if item["group"] == "handler"
            and item["entity"] == "PoolHourData"
            and first["relative_wat_line"] < item["relative_wat_line"] < second["relative_wat_line"]
        ]
        require(
            first["receiver_local"] is not None
            and first["receiver_local"] == second["receiver_local"]
            and not intervening,
            f"{cid} duplicate PoolHourData save local-name order boundary drift",
        )
        duplicate_pool_hour = {
            "first_relative_wat_line": first["relative_wat_line"],
            "second_relative_wat_line": second["relative_wat_line"],
            "shared_receiver_operand_local_name": first["receiver_local"],
            "intervening_pool_hour_data_setter_invocation_count": 0,
            "duplicate_save_lexical_order_and_local_name_bound": True,
            "duplicate_save_common_execution_path_proven": False,
            "duplicate_save_receiver_must_alias_proven": False,
            "graph_store_visibility_or_version_proven": False,
            "graph_store_persistence_proven": False,
            "last_writer_semantics_proven": False,
        }

    return {
        "profile_store_shape": (
            "modern-23-lexical-29-expanded-with-duplicate-pool-hour-save"
            if profile_id.startswith("modern-")
            else "legacy-base-22-lexical-28-expanded"
            if profile_id == "legacy-base-root"
            else "legacy-mainnet-19-lexical-25-expanded"
        ),
        "lexical_graph_store_invocation_count": len(lexical),
        "lexical_store_exact_target_receiver_binding_count": len(lexical),
        "lexical_graph_store_invocations": lexical,
        "lexical_graph_store_invocation_inventory_sha256": canonical_sha256(lexical),
        "physical_store_set_site_count": len(physical),
        "physical_store_set_sites": physical,
        "physical_store_set_site_inventory_sha256": canonical_sha256(physical),
        "expanded_store_path_count": len(expanded),
        "expanded_store_paths": expanded,
        "expanded_store_path_inventory_sha256": canonical_sha256(expanded),
        "reachable_store_targets": list(STORE_TARGETS),
        "handler_store_target_multiplicity": dict(sorted(handler_targets.items())),
        "handler_pool_saves": handler_pool_saves,
        "modern_duplicate_pool_hour_data_save": duplicate_pool_hour,
        "dynamic_store_target_count": 0,
        "store_remove_call_count": 0,
        "unmodelled_store_mutation_host_import_count": 0,
        "graph_store_host_semantics_complete": False,
        "graph_store_visibility_or_version_proven": False,
        "graph_store_persistence_proven": False,
        "last_writer_semantics_proven": False,
    }


def _bind_setters_to_store_receiver_origin_overlaps(
    context: dict[str, Any],
    lexical: list[dict[str, Any]],
    store: dict[str, Any],
    signature_proof: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cid = context["mapping_cid"]
    stores = store["lexical_graph_store_invocations"]
    output: list[dict[str, Any]] = []
    helper_authorities: dict[str, dict[str, Any]] = {}
    for item in lexical:
        receiver_local = item["receiver_flow"]["receiver_local"]
        receiver_value_identity = item["receiver_flow"]["receiver_value_identity"]
        identity_atoms = _value_identity_atoms(receiver_value_identity)
        candidates = [
            effect
            for effect in stores
            if effect["group"] == item["group"]
            and _value_identity_atoms(effect["receiver_value_identity"])
            & identity_atoms
        ]
        if not candidates and item["group"] == "handler":
            definition = (
                next(iter(identity_atoms))[1] if len(identity_atoms) == 1 else None
            )
            handler = context["handler"]
            if definition is not None and definition > 0:
                helper_call_line = definition - 1
                helper_target = FEE.call_name(handler.lines[helper_call_line])
                groups = _group_functions(context)
                helper_group = next(
                    (
                        group
                        for group, function in groups.items()
                        if group != "handler"
                        and helper_target is not None
                        and _resolve_function_name(context, helper_target) == function.name
                    ),
                    None,
                )
                if helper_group is not None:
                    helper = groups[helper_group]
                    returned_local = FEE.local_name(helper.lines[-1], "get")
                    if returned_local is not None:
                        returned_identity = _local_value_identity(
                            helper,
                            returned_local,
                            len(helper.lines) - 1,
                            signature_proof,
                        )
                        returned_atoms = _value_identity_atoms(returned_identity)
                        helper_stores = [
                            effect
                            for effect in stores
                            if effect["group"] == helper_group
                            and _value_identity_atoms(effect["receiver_value_identity"])
                            & returned_atoms
                        ]
                        for effect in helper_stores:
                            require(
                                effect["receiver_local"] == returned_local,
                                f"{cid} returned-helper store/terminal return receiver "
                                f"local equality proof failed for {helper_group}: "
                                f"{effect['receiver_local']} != {returned_local}",
                            )
                            require(
                                _value_identity_atoms(
                                    effect["receiver_value_identity"]
                                )
                                == returned_atoms,
                                f"{cid} returned-helper store/return receiver origin-set "
                                f"equality proof failed for {helper_group} at "
                                f"{effect['relative_wat_line']}",
                            )
                            require(
                                effect["relative_wat_line"] + 1
                                == len(helper.lines) - 1,
                                f"{cid} returned-helper internal store/terminal return "
                                f"adjacency proof failed for {helper_group}: store at "
                                f"{effect['relative_wat_line']}, terminal get at "
                                f"{len(helper.lines) - 1}",
                            )
                        handler_return_identity = {
                            **receiver_value_identity,
                            "observation_relative_wat_line": definition + 1,
                        }
                        for effect in helper_stores:
                            helper_authority_id = (
                                f"returned-helper:{helper_group}@{helper_call_line}"
                                f"->{effect['store_authority_id']}"
                            )
                            receiver_store_authority = {
                                "authority_id": helper_authority_id,
                                "binding_kind": (
                                    "returned_helper_receiver_on_immediate_normal_fallthrough_"
                                    "after_internal_store"
                                ),
                                "helper_group": helper_group,
                                "helper_call_relative_wat_line": helper_call_line,
                                "helper_function": helper.name,
                                "helper_returned_receiver_local": returned_local,
                                "helper_returned_receiver_value_identity": returned_identity,
                                "handler_returned_receiver_local": receiver_local,
                                "handler_returned_receiver_value_identity": handler_return_identity,
                                "internal_store_authority_id": effect["store_authority_id"],
                                "internal_store_relative_wat_line": effect["relative_wat_line"],
                                "terminal_return_get_relative_wat_line": len(helper.lines) - 1,
                                "internal_store_authority": effect["receiver_store_authority"],
                                "same_internal_store_receiver_on_immediate_normal_fallthrough_"
                                "to_helper_return_and_caller_local_bound": True,
                                "all_helper_invocations_and_paths_return_stored_receiver_proven": False,
                            }
                            helper_authority = {
                                **effect,
                                "store_authority_id": helper_authority_id,
                                "group": "handler",
                                "relative_wat_line": helper_call_line,
                                "receiver_local": receiver_local,
                                "receiver_value_identity": handler_return_identity,
                                "receiver_store_authority": receiver_store_authority,
                            }
                            if helper_authority_id in helper_authorities:
                                require(
                                    helper_authorities[helper_authority_id]
                                    == helper_authority,
                                    f"{cid} returned-helper authority ID collision",
                                )
                            else:
                                helper_authorities[helper_authority_id] = helper_authority
                            candidates.append(helper_authority)
        require(
            candidates,
            f"{cid} setter/store receiver-origin overlap proof failed for "
            f"{item['expected_entity']}.{item['field']}: no same-group store receiver "
            f"overlaps setter value origins "
            f"{sorted(identity_atoms)}",
        )
        nearest = min(
            candidates,
            key=lambda effect: (
                abs(effect["relative_wat_line"] - item["relative_wat_line"]),
                effect["relative_wat_line"] < item["relative_wat_line"],
                effect["relative_wat_line"],
            ),
        )
        overlap_store_entity = nearest["target"]
        require(
            overlap_store_entity == item["expected_entity"],
            f"{cid} setter/store receiver-origin overlap entity proof failed for "
            f"{item['expected_entity']}.{item['field']}: {receiver_local} overlaps "
            f"nearest {overlap_store_entity} store receiver at "
            f"{nearest['relative_wat_line']}",
        )
        overlaps = [
            effect
            for effect in candidates
            if effect["target"] == overlap_store_entity
        ]
        require(overlaps, f"{cid} same-group store receiver-origin overlap ledger is empty")
        origin_set_relation_kinds = [
            (
                "exact_equal_origin_set"
                if identity_atoms
                == _value_identity_atoms(effect["receiver_value_identity"])
                else "overlap_without_origin_set_equality"
            )
            for effect in overlaps
        ]
        output.append(
            {
                **item,
                "receiver_authority_id": (
                    f"{item['group']}[{item['group_ordinal']}]@{item['relative_wat_line']}"
                ),
                "entity": overlap_store_entity,
                "receiver_local": receiver_local,
                "receiver_value_identity": receiver_value_identity,
                "setter_receiver_bound_by_exact_retained_operand_flow": True,
                "entity_from_nearest_same_group_store_receiver_origin_overlap": overlap_store_entity,
                "nearest_same_group_origin_overlap_store_relative_wat_line": nearest[
                    "relative_wat_line"
                ],
                "same_group_origin_overlap_store_relative_wat_lines": [
                    effect["relative_wat_line"] for effect in overlaps
                ],
                "same_group_origin_overlap_store_receiver_locals": [
                    effect["receiver_local"] for effect in overlaps
                ],
                "same_group_store_receiver_value_origin_overlaps": [
                    [
                        {
                            "origin_local": origin_local,
                            "definition_relative_wat_line": definition_line,
                        }
                        for origin_local, definition_line in sorted(
                            identity_atoms
                            & _value_identity_atoms(effect["receiver_value_identity"])
                        )
                    ]
                    for effect in overlaps
                ],
                "same_group_store_receiver_origin_set_relation_kinds": (
                    origin_set_relation_kinds
                ),
                "all_same_group_store_receiver_origin_sets_equal": all(
                    kind == "exact_equal_origin_set"
                    for kind in origin_set_relation_kinds
                ),
                "has_same_group_store_receiver_origin_overlap_without_set_equality": any(
                    kind == "overlap_without_origin_set_equality"
                    for kind in origin_set_relation_kinds
                ),
                "same_group_origin_overlap_store_flow_kinds": [
                    effect["receiver_store_authority"]["binding_kind"] for effect in overlaps
                ],
                "same_group_origin_overlap_store_authority_ids": [
                    effect["store_authority_id"] for effect in overlaps
                ],
                "returned_helper_store_origin_overlap_invocation": any(
                    effect["receiver_store_authority"]["binding_kind"]
                    == (
                        "returned_helper_receiver_on_immediate_normal_fallthrough_"
                        "after_internal_store"
                    )
                    for effect in overlaps
                ),
                "same_group_origin_overlap_store_authority_inventory_sha256": canonical_sha256(
                    [effect["receiver_store_authority"] for effect in overlaps]
                ),
                "same_group_store_receiver_value_origin_overlap_bound": True,
                "setter_store_common_execution_path_proven": False,
                "setter_store_receiver_must_alias_proven": False,
                "setter_store_branch_correlation_proven": False,
            }
        )
    return output, sorted(
        helper_authorities.values(),
        key=lambda item: item["store_authority_id"],
    )
def _ordering_and_guards(
    context: dict[str, Any],
    core_proof: dict[str, Any],
    fee_proof: dict[str, Any],
    lexical: list[dict[str, Any]],
    groups: dict[str, Any],
    fanout: dict[str, Any],
    store: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile_id = context["profile"]["profile_id"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    store_lexical = store["lexical_graph_store_invocations"]

    invocation_order: list[dict[str, Any]] = []
    for item in lexical:
        overlaps = item["same_group_origin_overlap_store_relative_wat_lines"]
        later = [line for line in overlaps if line > item["relative_wat_line"]]
        earlier = [line for line in overlaps if line < item["relative_wat_line"]]
        invocation_order.append(
            {
                "receiver_authority_id": item["receiver_authority_id"],
                "entity": item["entity"],
                "field": item["field"],
                "earlier_same_group_origin_overlap_store_invocation_count": len(earlier),
                "later_same_group_origin_overlap_store_invocation_count": len(later),
                "has_lexically_later_same_group_origin_overlap_store": bool(later),
            }
        )

    expected_without_later = (
        0
        if profile_id == "legacy-base-root" or profile_id.startswith("modern-")
        else 12
    )
    without_later = [
        item for item in invocation_order
        if not item["has_lexically_later_same_group_origin_overlap_store"]
    ]
    require(len(without_later) == expected_without_later, f"{cid} setter/store order profile drift")
    if expected_without_later:
        require(
            Counter((item["entity"], item["field"]) for item in without_later)
            == Counter(
                {
                    ("PoolHourData", "volumeUSD"): 1,
                    ("PoolHourData", "volumeToken0"): 1,
                    ("PoolHourData", "volumeToken1"): 1,
                    ("PoolHourData", "feesUSD"): 1,
                    ("TokenHourData", "volume"): 2,
                    ("TokenHourData", "volumeUSD"): 2,
                    ("TokenHourData", "untrackedVolumeUSD"): 2,
                    ("TokenHourData", "feesUSD"): 2,
                }
            ),
            f"{cid} post-store setter identity drift",
        )

    ordered_identities = {
        (item["entity"], item["field"])
        for item in invocation_order
        if item["has_lexically_later_same_group_origin_overlap_store"]
    }
    require(len(ordered_identities) == 144, f"{cid} ordered setter identity denominator drift")

    core_effect = core_proof["save_and_effect_closure"]
    core_fields = core_proof["selected_field_flows"]
    require(
        list(core_fields["fields"]) == list(CORE_SELECTED_FIELDS),
        f"{cid} core selected field order drift",
    )
    require(
        core_effect["direct_pool_save_count"] == 2
        and core_effect["same_selected_pool_receiver_for_both_saves_machine_proven"] is True
        and core_effect["first_pool_save_after_all_three_selected_setters_machine_proven"] is True,
        f"{cid} core selected save boundary drift",
    )

    fee_effect = fee_proof["save_and_effect_closure"]
    fee_fields = fee_proof["selected_field_flows"]
    require(
        list(fee_fields["fields"]) == list(FEE_SELECTED_FIELDS)
        and fee_fields["call_order"] == list(FEE_SELECTED_FIELDS)
        and fee_fields["setter_order"]
        == [f"Pool.{field}" for field in FEE_SELECTED_FIELDS]
        and fee_fields["same_contract_receiver_for_both_calls_machine_proven"] is True
        and fee_fields["ordered_call_decode_setter_flow_machine_proven"] is True,
        f"{cid} fee-growth selected field order drift",
    )
    require(
        fee_effect["direct_pool_save_count"] == 2
        and fee_effect["selected_fee_reads_follow_first_pool_save_machine_proven"] is True
        and fee_effect["both_setters_precede_second_pool_save_machine_proven"] is True
        and fee_effect["same_selected_pool_receiver_for_setters_and_second_save_machine_proven"] is True
        and fee_effect["no_return_or_branch_between_second_setter_and_second_save_machine_proven"] is True,
        f"{cid} fee-growth selected save boundary drift",
    )

    if generation == "modern":
        control = core_proof["control_and_entity_boundary"]
        guard_start = control["selected_update_guard_start_index"]
        guard_end = control["selected_update_guard_end_index"]
        handler_field_lines = [
            item["relative_wat_line"] for item in lexical if item["group"] == "handler"
        ]
        handler_store_lines = [
            item["relative_wat_line"] for item in store_lexical if item["group"] == "handler"
        ]
        handler_helper_lines = [
            line
            for key, values in fanout["handler_and_nested_helper_callsites"].items()
            if "_from_" not in key
            for line in values
        ]
        require(
            all(
                guard_start < line < guard_end
                for line in handler_field_lines + handler_store_lines + handler_helper_lines
            ),
            f"{cid} handler effect escaped modern two-token guard",
        )
        require(
            core_effect["modern_guard_dominates_selected_setters_and_both_saves"] is True
            and fee_effect["modern_token_guard_dominates_calls_setters_and_second_save"] is True,
            f"{cid} inherited selected modern guard drift",
        )
        outer_guard = {
            "condition": "Token[Pool.token0] != null && Token[Pool.token1] != null",
            "guard_start_relative_wat_line": guard_start,
            "guard_end_relative_wat_line": guard_end,
            "all_handler_schema_invocations_stores_and_helper_calls_inside_guard": True,
            "missing_either_token_skips_entire_classified_handler_effect_body": True,
        }
    else:
        outer_guard = {
            "condition": "legacy profile has no common outer two-token guard",
            "guard_start_relative_wat_line": None,
            "guard_end_relative_wat_line": None,
            "all_handler_schema_invocations_stores_and_helper_calls_inside_guard": False,
            "missing_either_token_skips_entire_classified_handler_effect_body": False,
        }

    return {
        "relation_scope": (
            "lexical order within one retained function group plus overlap between branch-merged "
            "setter and store receiver value-origin sets; this does not prove a jointly feasible "
            "execution, branch correlation, or receiver must-alias"
        ),
        "common_execution_path_proven": False,
        "receiver_must_alias_proven": False,
        "branch_correlation_proven": False,
        "lexical_setter_store_origin_overlap_order": invocation_order,
        "lexical_setter_store_origin_overlap_order_sha256": canonical_sha256(invocation_order),
        "lexical_setter_invocation_count_with_lexically_later_same_group_origin_overlap_store": (
            len(lexical) - len(without_later)
        ),
        "lexical_setter_invocation_count_without_lexically_later_same_group_origin_overlap_store": len(
            without_later
        ),
        "unique_field_identity_count_with_at_least_one_lexically_later_same_group_origin_overlap_store": len(
            ordered_identities
        ),
        "unique_field_identities_with_at_least_one_lexically_later_same_group_origin_overlap_store": [
            {"entity": entity, "field": field} for entity, field in sorted(ordered_identities)
        ],
        "legacy_mainnet_setter_without_lexically_later_handler_origin_overlap_store": (
            {
                "setter_invocation_count": 12,
                "identities": without_later,
                "common_execution_path_proven": False,
                "receiver_must_alias_proven": False,
                "loaded_field_preservation_proven": False,
                "field_value_unchanged_proven": False,
                "last_writer_semantics_proven": False,
            }
            if expected_without_later
            else None
        ),
        "selected_pool_core_flow": {
            "fields": list(CORE_SELECTED_FIELDS),
            "setter_indices": core_fields["setter_indices"],
            "first_pool_save_relative_wat_line": core_effect["first_pool_save_relative_wat_line"],
            "second_pool_save_relative_wat_line": core_effect["second_pool_save_relative_wat_line"],
            "same_pool_receiver_for_both_saves": True,
            "all_three_setters_precede_first_save": True,
            "numeric_semantics_complete": False,
        },
        "selected_pool_fee_growth_flow": {
            "fields": list(FEE_SELECTED_FIELDS),
            "call_order": fee_fields["call_order"],
            "setter_order": fee_fields["setter_order"],
            "call_indices": fee_fields["call_indices"],
            "decode_indices": fee_fields["decode_indices"],
            "setter_indices": fee_fields["setter_indices"],
            "first_pool_save_relative_wat_line": fee_effect["first_pool_save_relative_wat_line"],
            "second_pool_save_relative_wat_line": fee_effect["second_pool_save_relative_wat_line"],
            "fee_reads_follow_first_save": True,
            "both_setters_follow_both_successful_decodes_and_precede_second_save": True,
            "same_pool_receiver_for_setters_and_second_save": True,
            "host_call_and_numeric_semantics_complete": False,
        },
        "outer_two_token_guard": outer_guard,
        "handler_store_profile_shape": store["profile_store_shape"],
        "modern_duplicate_pool_hour_data_save": store["modern_duplicate_pool_hour_data_save"],
        "imported_numeric_semantics_complete": False,
        "imported_comparator_semantics_complete": False,
        "contract_call_value_semantics_complete": False,
        "graph_store_visibility_or_version_proven": False,
        "graph_store_persistence_proven": False,
        "last_writer_semantics_proven": False,
    }
def prove_complete_context(
    context: dict[str, Any],
    core_proof: dict[str, Any],
    fee_proof: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile = context["profile"]
    profile_id = profile["profile_id"]
    for label, parent in (("core", core_proof), ("fee-growth", fee_proof)):
        require(parent["mapping_cid"] == cid, f"{cid} {label} proof mismatch")
        require(parent["profile_id"] == profile_id, f"{cid} {label} profile mismatch")
        require(
            hashlib.sha256(context["wat_text"].encode()).hexdigest()
            == parent["retained_wasm"]["wat_sha256"],
            f"{cid} {label} retained WAT drift",
        )
        require(
            FEE.function_sha256(context["handler"]) == parent["handler_binding"]["body_sha256"],
            f"{cid} {label} handler body drift",
        )
        require(
            parent["complete_pool_swap_handler_semantics"] is False,
            f"{cid} {label} truth boundary drift",
        )

    reachable = sorted(
        WRITER.reachable_functions(
            context["functions"], context["handler"], tuple(context["indirect_targets"])
        )
    )
    bodies = [
        {
            "function": name,
            "function_index": context["functions"][name].function_index,
            "body_sha256": FEE.function_sha256(context["functions"][name]),
        }
        for name in reachable
    ]
    calls = [
        {"function": name, "relative_wat_line": index, "call_target": target}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if (target := FEE.call_name(line)) is not None
    ]
    direct_writes = [
        {"function": name, "relative_wat_line": index, "instruction": FEE.normalized(line)}
        for name in reachable
        for index, line in enumerate(context["functions"][name].lines)
        if FEE.POOL_RUNTIME.RUNTIME.is_direct_memory_write(line, FEE.normalized)
    ]
    expected_inventory = {
        "legacy-base-root": (197, 1183, 185, 60, 13, 0),
        "legacy-mainnet-qmrv": (197, 1176, 185, 60, 13, 0),
        "legacy-mainnet-root": (197, 1172, 185, 60, 13, 0),
        "legacy-mainnet-stable": (197, 1177, 185, 60, 13, 0),
        "legacy-mainnet-stable-fee-tier-1": (197, 1180, 185, 60, 13, 0),
        "legacy-mainnet-stable-fee-tier-100": (197, 1180, 185, 60, 13, 0),
        "modern-base": (111, 1459, 630, 197, 13, 1),
        "modern-mainnet": (111, 1441, 628, 197, 13, 1),
    }
    require(profile_id in expected_inventory, f"{cid} unknown profile")
    generation = profile["control_generation"]
    map_set = FEE.MODERN_MAP_SET if generation == "modern" else FEE.LEGACY_MAP_SET
    physical_map_sets = [item for item in calls if item["call_target"] == map_set]
    indirect_count = sum(
        "call_indirect" in line
        for name in reachable
        for line in context["functions"][name].lines
    )
    physical_store_count = core_proof["save_and_effect_closure"][
        "transitive_store_evidence"
    ]["reachable_store_set_site_count"]
    actual_inventory = (
        len(reachable),
        len(calls),
        len(direct_writes),
        len(physical_map_sets),
        physical_store_count,
        indirect_count,
    )
    require(actual_inventory == expected_inventory[profile_id], f"{cid} reachable inventory count drift")

    parent_inventory = core_proof["save_and_effect_closure"][
        "reachable_in_memory_mutation_inventory"
    ]
    require(parent_inventory["reachable_function_count"] == len(reachable), "core function count drift")
    require(
        parent_inventory["reachable_direct_memory_write_site_count"] == len(direct_writes),
        "core write count drift",
    )
    require(
        parent_inventory["reachable_typed_map_set_site_count"] == len(physical_map_sets),
        "core setter count drift",
    )

    signature_proof = _wat_signatures(context)
    groups = _group_functions(context)
    fanout = _fanout_proof(context, groups)
    lexical: list[dict[str, Any]] = []
    for group, expected_sequence in GROUP_SEQUENCES.items():
        function = groups[group]
        operations = _logical_operations(context, function)
        require(len(operations) == len(expected_sequence), f"{cid} {group} lexical invocation count drift")
        for ordinal, (operation, (entity, field)) in enumerate(zip(operations, expected_sequence)):
            receiver_flow = _setter_receiver_binding(
                context,
                function,
                operation,
                field,
                signature_proof,
            )
            lexical.append(
                {
                    **operation,
                    "group": group,
                    "group_ordinal": ordinal,
                    "expected_entity": entity,
                    "entity": entity,
                    "field": field,
                    "receiver_flow": receiver_flow,
                    "field_key_bound_by_exact_callsite_and_retained_body": True,
                    "field_value_semantics_complete": False,
                }
            )

    require(len(lexical) == 197, f"{cid} lexical invocation denominator drift")
    expanded = [
        {**item, "path_id": path_id}
        for item in lexical
        for path_id in PATH_IDS[item["group"]]
    ]
    require(len(expanded) == 259, f"{cid} expanded setter path denominator drift")
    sites, coverage = _physical_setter_coverage(context, lexical, reachable)
    require(len(sites) == len(physical_map_sets), f"{cid} physical setter ledger mismatch")
    receiver_flow_edges = Counter(
        (
            item["function"],
            item["relative_wat_line"],
            flow["function"],
            flow["relative_wat_line"],
        )
        for item in lexical
        for flow in item["receiver_flow"]["physical_receiver_flows"]
    )
    coverage_edges = Counter(
        (
            item["via_function"],
            item["via_relative_wat_line"],
            item["site_function"],
            item["site_relative_wat_line"],
        )
        for item in coverage
    )
    require(
        receiver_flow_edges == coverage_edges,
        f"{cid} local receiver-flow edges differ from physical setter coverage",
    )
    store = _store_closure(
        context,
        reachable,
        core_proof,
        lexical,
        signature_proof,
    )
    lexical, returned_helper_store_authorities = _bind_setters_to_store_receiver_origin_overlaps(
        context,
        lexical,
        store,
        signature_proof,
    )
    store["returned_helper_store_authority_record_count"] = len(
        returned_helper_store_authorities
    )
    store["returned_helper_store_authorities"] = returned_helper_store_authorities
    store["returned_helper_store_authority_inventory_sha256"] = canonical_sha256(
        returned_helper_store_authorities
    )
    ordering = _ordering_and_guards(
        context, core_proof, fee_proof, lexical, groups, fanout, store
    )

    catalog_by_identity = {(item["entity"], item["field"]): item for item in catalog}
    catalog_pairs = set(catalog_by_identity)
    unique_pairs = sorted({(item["entity"], item["field"]) for item in lexical})
    require(len(unique_pairs) == 144, f"{cid} unique stored setter field count drift")
    require(set(unique_pairs).issubset(catalog_pairs), f"{cid} setter field missing from catalog")
    require(
        all(catalog_by_identity[identity]["storage"] == "stored" for identity in unique_pairs),
        f"{cid} reachable setter ledger contains a derived schema field",
    )
    expected_unique_counts = {
        "Bundle": 1,
        "Factory": 8,
        "Pool": 17,
        "PoolDayData": 20,
        "PoolHourData": 20,
        "Swap": 15,
        "Tick": 2,
        "TickDayData": 12,
        "Token": 8,
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
    require(
        {
            (item["entity"], item["field"])
            for item in ordering[
                "unique_field_identities_with_at_least_one_lexically_later_same_group_origin_overlap_store"
            ]
        }
        == set(unique_pairs),
        f"{cid} setter/store origin-overlap identity closure drift",
    )
    authority_by_invocation = {
        (item["function"], item["relative_wat_line"]): item for item in lexical
    }
    require(
        len(authority_by_invocation) == len(lexical),
        f"{cid} receiver authority invocation identity collision",
    )
    physical_receiver_flows = [
        flow
        for item in lexical
        for flow in item["receiver_flow"]["physical_receiver_flows"]
    ]
    lexical_authorities = [
        {
            "receiver_authority_id": item["receiver_authority_id"],
            "group": item["group"],
            "group_ordinal": item["group_ordinal"],
            "function": item["function"],
            "relative_wat_line": item["relative_wat_line"],
            "call_target": item["call_target"],
            "entity": item["entity"],
            "field": item["field"],
            "operand_slice_sha256": item["operand_slice_sha256"],
            "receiver_local": item["receiver_local"],
            "receiver_value_identity": item["receiver_value_identity"],
            "receiver_binding_kind": item["receiver_flow"]["receiver_binding_kind"],
            "physical_receiver_flow_count": item["receiver_flow"][
                "physical_receiver_flow_count"
            ],
            "physical_receiver_flow_sha256": item["receiver_flow"][
                "physical_receiver_flow_sha256"
            ],
            "same_group_origin_overlap_store_authority_ids": item[
                "same_group_origin_overlap_store_authority_ids"
            ],
            "same_group_origin_overlap_store_authority_inventory_sha256": item[
                "same_group_origin_overlap_store_authority_inventory_sha256"
            ],
            "field_key_bound_by_exact_callsite_and_retained_body": True,
            "setter_receiver_bound_by_exact_retained_operand_flow": True,
            "same_group_store_receiver_value_origin_overlap_bound": True,
            "field_value_semantics_complete": False,
        }
        for item in lexical
    ]
    coverage_authorities = [
        {
            **edge,
            "receiver_authority_id": authority_by_invocation[
                (edge["via_function"], edge["via_relative_wat_line"])
            ]["receiver_authority_id"],
            "physical_receiver_flow_sha256": authority_by_invocation[
                (edge["via_function"], edge["via_relative_wat_line"])
            ]["receiver_flow"]["physical_receiver_flow_sha256"],
        }
        for edge in coverage
    ]
    expanded_authority_paths = [
        {
            "receiver_authority_id": item["receiver_authority_id"],
            "entity": item["entity"],
            "field": item["field"],
            "path_id": path_id,
        }
        for item in lexical
        for path_id in PATH_IDS[item["group"]]
    ]
    return {
        "mapping_cid": cid,
        "profile_id": profile_id,
        "control_generation": generation,
        "retained_wasm": core_proof["retained_wasm"],
        "handler_binding": core_proof["handler_binding"],
        "pool_swap_core_v1_proof_sha256": canonical_sha256(core_proof),
        "pool_swap_fee_growth_v1_proof_sha256": canonical_sha256(fee_proof),
        "reachable_inventory": {
            "reachable_function_count": len(reachable),
            "reachable_function_body_inventory_sha256": canonical_sha256(bodies),
            "direct_callsite_count": len(calls),
            "direct_callsite_inventory_sha256": canonical_sha256(calls),
            "direct_memory_write_site_count": len(direct_writes),
            "direct_memory_write_site_inventory_sha256": canonical_sha256(direct_writes),
            "physical_typed_map_set_site_count": len(sites),
            "physical_typed_map_set_site_inventory_sha256": canonical_sha256(sites),
            "physical_store_set_site_count": physical_store_count,
            "reachable_call_indirect_count": indirect_count,
            "closed_indirect_targets": list(context["indirect_targets"]),
            "direct_memory_alias_semantics_complete": False,
        },
        "schema_api_invocation_closure": {
            "lexical_field_invocation_count": len(lexical),
            "lexical_setter_exact_receiver_flow_binding_count": len(lexical),
            "lexical_setter_invocation_with_store_receiver_origin_overlap_count": len(lexical),
            "lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count": sum(
                item["all_same_group_store_receiver_origin_sets_equal"] for item in lexical
            ),
            "lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count": sum(
                item[
                    "has_same_group_store_receiver_origin_overlap_without_set_equality"
                ]
                for item in lexical
            ),
            "setter_to_store_receiver_origin_overlap_edge_count": sum(
                len(item["same_group_origin_overlap_store_authority_ids"])
                for item in lexical
            ),
            "setter_to_store_receiver_exact_equal_origin_set_edge_count": sum(
                kind == "exact_equal_origin_set"
                for item in lexical
                for kind in item["same_group_store_receiver_origin_set_relation_kinds"]
            ),
            "setter_to_store_receiver_overlap_without_origin_set_equality_edge_count": sum(
                kind == "overlap_without_origin_set_equality"
                for item in lexical
                for kind in item["same_group_store_receiver_origin_set_relation_kinds"]
            ),
            "physical_receiver_flow_edge_count": sum(
                item["receiver_flow"]["physical_receiver_flow_count"] for item in lexical
            ),
            "returned_helper_store_origin_overlap_invocation_count": sum(
                item["returned_helper_store_origin_overlap_invocation"] for item in lexical
            ),
            "lexical_field_invocations": lexical_authorities,
            "lexical_field_invocation_inventory_sha256": canonical_sha256(
                lexical_authorities
            ),
            "physical_receiver_flow_inventory_sha256": canonical_sha256(
                physical_receiver_flows
            ),
            "physical_site_to_invocation_edge_count": len(coverage_authorities),
            "physical_site_to_invocation_edges": coverage_authorities,
            "physical_site_to_invocation_edge_inventory_sha256": canonical_sha256(
                coverage_authorities
            ),
            "nullable_branch_alternative_count": sum(
                item["nullable_branch_alternative"] for item in coverage
            ),
            "expanded_handler_to_setter_path_count": len(expanded_authority_paths),
            "expanded_handler_to_setter_paths": expanded_authority_paths,
            "expanded_handler_to_setter_path_inventory_sha256": canonical_sha256(
                expanded_authority_paths
            ),
            "unique_stored_setter_field_count": len(unique_pairs),
            "unique_stored_setter_fields": [
                {"entity": entity, "field": field} for entity, field in unique_pairs
            ],
            "unique_stored_setter_entity_counts": expected_unique_counts,
            "unclassified_physical_typed_map_set_site_count": 0,
            "physical_vs_semantic_ledger_warning": (
                "physical TypedMap#set sites, lexical schema-field invocations, nullable branch edges, "
                "and expanded handler paths are distinct denominators; no physical denominator implies "
                "field meaning, persistence, or last-writer behavior"
            ),
        },
        "helper_fanout": fanout,
        "store_closure": store,
        "ordering_and_guards": ordering,
        "complete_lexical_static_swap_schema_api_closure": True,
        "pool_swap_semantics_complete": False,
        "graph_store_visibility_or_version_proven": False,
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
    order_lexical = proof["ordering_and_guards"][
        "lexical_setter_store_origin_overlap_order"
    ]
    written = {(item["entity"], item["field"]) for item in lexical}
    identity = (record["entity"], record["field"])
    category = _field_category(record, written)
    invocations = [
        item for item in lexical if (item["entity"], item["field"]) == identity
    ]
    setter_paths = [
        item for item in expanded if (item["entity"], item["field"]) == identity
    ]
    overlap_relations = [
        item for item in order_lexical if (item["entity"], item["field"]) == identity
    ]
    lexically_ordered_overlap_relations = [
        item for item in overlap_relations
        if item["has_lexically_later_same_group_origin_overlap_store"]
    ]
    child = DERIVED_CHILD_ASSOCIATIONS.get(identity)
    child_paths = (
        [item for item in expanded if (item["entity"], item["field"]) == child]
        if child is not None
        else []
    )
    setter = category == CATEGORY_SETTER
    no_setter = category == CATEGORY_NO_SETTER
    derived = category == CATEGORY_DERIVED
    outside = category == CATEGORY_OUTSIDE
    core_selected = setter and identity in {
        ("Pool", field) for field in CORE_SELECTED_FIELDS
    }
    fee_selected = setter and identity in {
        ("Pool", field) for field in FEE_SELECTED_FIELDS
    }
    require(sum((setter, no_setter, derived, outside)) == 1, "field category overlap")
    if setter:
        require(
            invocations and setter_paths and lexically_ordered_overlap_relations,
            f"missing exact setter flow or lexical store-origin-overlap relation for {identity}",
        )
    else:
        require(
            not invocations and not setter_paths and not overlap_relations,
            f"unexpected exact setter flow for {identity}",
        )
    if child is not None:
        require(derived and child_paths, f"missing derived child setter paths for {identity}")

    return {
        "entity": record["entity"],
        "field": record["field"],
        "type": record["type"],
        "directives": record["directives"],
        "storage": record["storage"],
        "schema_catalog_record_sha256": canonical_sha256(record),
        "lexical_static_category": category,
        "stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap": setter,
        "stored_field_on_reachable_store_without_exact_schema_setter": no_setter,
        "derived_field_without_direct_graph_store_transition": derived,
        "stored_field_outside_pool_swap_store_closure": outside,
        "pool_swap_core_selected_overlay": core_selected,
        "pool_swap_fee_growth_selected_overlay": fee_selected,
        "lexical_setter_invocation_count": len(invocations),
        "lexical_setter_invocation_inventory_sha256": canonical_sha256(invocations),
        "lexical_setter_invocation_count_with_lexically_later_same_group_store_receiver_origin_overlap": len(
            lexically_ordered_overlap_relations
        ),
        "lexical_setter_store_origin_overlap_order_inventory_sha256": canonical_sha256(
            overlap_relations
        ),
        "expanded_setter_path_count": len(setter_paths),
        "expanded_setter_path_inventory_sha256": canonical_sha256(setter_paths),
        "reachable_entity_store_target_for_category": setter or no_setter,
        "no_reachable_exact_schema_api_setter_flow_bound": no_setter,
        "setter_store_common_execution_path_proven": False,
        "setter_store_receiver_must_alias_proven": False,
        "setter_store_branch_correlation_proven": False,
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
        "swap_required_field_overlay": (
            record["entity"] == "Swap" and record["field"] in SWAP_REQUIRED_FIELDS
        ),
        "swap_nullable_field_overlay": (
            record["entity"] == "Swap" and record["field"] in SWAP_NULLABLE_FIELDS
        ),
        "required_absent_overlay": False,
        "static_required_absence_bound": False,
        "lexical_static_outcome_complete": True,
        "field_value_semantics_complete": False,
        "field_value_unchanged_proven": False,
        "loaded_field_preservation_proven": False,
        "numeric_semantics_complete": False,
        "imported_numeric_semantics_complete": False,
        "imported_comparator_semantics_complete": False,
        "general_heap_alias_safety_complete": False,
        "graph_store_host_semantics_complete": False,
        "graph_store_visibility_or_version_proven": False,
        "graph_store_persistence_proven": False,
        "last_writer_semantics_proven": False,
        "complete_entity_history": False,
        "complete_integrated_field_semantics": False,
        "mapping_proof_sha256": canonical_sha256(proof),
    }
def build_segments(
    core_contract: dict[str, Any],
    fee_contract: dict[str, Any],
    catalog: list[dict[str, Any]],
    proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_cid = {item["mapping_cid"]: item for item in proofs}
    core_by_cid = {
        item["semantic_surface"]["mapping_cid"]: item
        for item in core_contract["segments"]
    }
    results: list[dict[str, Any]] = []
    expected_counts = Counter(
        {
            CATEGORY_SETTER: 144,
            CATEGORY_NO_SETTER: 45,
            CATEGORY_DERIVED: 13,
            CATEGORY_OUTSIDE: 97,
        }
    )
    for parent in fee_contract["segments"]:
        cid = parent["semantic_surface"]["mapping_cid"]
        require(cid in by_cid and cid in core_by_cid, f"{parent['segment_id']} missing Swap v2 proof")
        proof = by_cid[cid]
        core_parent = core_by_cid[cid]
        require(parent["semantic_surface"]["profile_id"] == proof["profile_id"], "segment profile drift")
        outcomes = [_field_outcome(record, proof) for record in catalog]
        counts = Counter(item["lexical_static_category"] for item in outcomes)
        require(counts == expected_counts, f"{parent['segment_id']} field category denominator drift")
        required_absent = sum(item["required_absent_overlay"] for item in outcomes)
        swap_required = sum(item["swap_required_field_overlay"] for item in outcomes)
        swap_nullable = sum(item["swap_nullable_field_overlay"] for item in outcomes)
        core_selected = sum(item["pool_swap_core_selected_overlay"] for item in outcomes)
        fee_selected = sum(item["pool_swap_fee_growth_selected_overlay"] for item in outcomes)
        require(
            (required_absent, swap_required, swap_nullable, core_selected, fee_selected)
            == (0, 14, 1, 3, 2),
            f"{parent['segment_id']} overlay denominator drift",
        )
        semantic = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "control_generation": proof["control_generation"],
            "ordering_and_guards": proof["ordering_and_guards"],
            "schema_api_invocation_summary": {
                "physical_typed_map_set_site_count": proof["reachable_inventory"]["physical_typed_map_set_site_count"],
                "lexical_field_invocation_count": proof["schema_api_invocation_closure"]["lexical_field_invocation_count"],
                "lexical_setter_exact_receiver_flow_binding_count": proof["schema_api_invocation_closure"]["lexical_setter_exact_receiver_flow_binding_count"],
                "lexical_setter_invocation_with_store_receiver_origin_overlap_count": proof["schema_api_invocation_closure"]["lexical_setter_invocation_with_store_receiver_origin_overlap_count"],
                "lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count": proof["schema_api_invocation_closure"]["lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count"],
                "lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count": proof["schema_api_invocation_closure"]["lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count"],
                "setter_to_store_receiver_origin_overlap_edge_count": proof["schema_api_invocation_closure"]["setter_to_store_receiver_origin_overlap_edge_count"],
                "setter_to_store_receiver_exact_equal_origin_set_edge_count": proof["schema_api_invocation_closure"]["setter_to_store_receiver_exact_equal_origin_set_edge_count"],
                "setter_to_store_receiver_overlap_without_origin_set_equality_edge_count": proof["schema_api_invocation_closure"]["setter_to_store_receiver_overlap_without_origin_set_equality_edge_count"],
                "physical_receiver_flow_edge_count": proof["schema_api_invocation_closure"]["physical_receiver_flow_edge_count"],
                "returned_helper_store_origin_overlap_invocation_count": proof["schema_api_invocation_closure"]["returned_helper_store_origin_overlap_invocation_count"],
                "physical_site_to_invocation_edge_count": proof["schema_api_invocation_closure"]["physical_site_to_invocation_edge_count"],
                "expanded_handler_to_setter_path_count": proof["schema_api_invocation_closure"]["expanded_handler_to_setter_path_count"],
                "unique_stored_setter_field_count": proof["schema_api_invocation_closure"]["unique_stored_setter_field_count"],
                "unclassified_physical_typed_map_set_site_count": 0,
            },
            "store_closure_summary": {
                "profile_store_shape": proof["store_closure"]["profile_store_shape"],
                "lexical_graph_store_invocation_count": proof["store_closure"]["lexical_graph_store_invocation_count"],
                "lexical_store_exact_target_receiver_binding_count": proof["store_closure"]["lexical_store_exact_target_receiver_binding_count"],
                "returned_helper_store_authority_record_count": proof["store_closure"]["returned_helper_store_authority_record_count"],
                "physical_store_set_site_count": proof["store_closure"]["physical_store_set_site_count"],
                "expanded_store_path_count": proof["store_closure"]["expanded_store_path_count"],
                "reachable_store_targets": list(STORE_TARGETS),
                "modern_duplicate_pool_hour_data_save": proof["store_closure"]["modern_duplicate_pool_hour_data_save"],
            },
            "field_outcome_summary": {
                "field_outcome_count": len(outcomes),
                "stored_field_with_exact_setter_and_lexically_later_origin_overlap_store_count": counts[CATEGORY_SETTER],
                "reachable_store_without_exact_setter_count": counts[CATEGORY_NO_SETTER],
                "derived_without_direct_store_transition_count": counts[CATEGORY_DERIVED],
                "stored_field_outside_pool_swap_store_closure_count": counts[CATEGORY_OUTSIDE],
                "pool_swap_core_selected_overlay_count": core_selected,
                "pool_swap_fee_growth_selected_overlay_count": fee_selected,
                "swap_required_field_count": swap_required,
                "swap_nullable_field_count": swap_nullable,
                "required_absent_overlay_count": required_absent,
                "category_counts_sha256": canonical_sha256(dict(sorted(counts.items()))),
            },
            "field_outcomes": outcomes,
            "lexical_static_pool_swap_schema_api_matrix_complete": True,
            "pool_swap_semantics_complete": False,
            "complete_entity_history": False,
            "graph_store_visibility_or_version_proven": False,
            "graph_store_persistence_proven": False,
        }
        provenance = {
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "pool_swap_core_v1_segment_semantic_sha256": core_parent["semantic_surface_sha256"],
            "pool_swap_core_v1_segment_provenance_sha256": core_parent["provenance_surface_sha256"],
            "pool_swap_fee_growth_v1_segment_semantic_sha256": parent["semantic_surface_sha256"],
            "pool_swap_fee_growth_v1_segment_provenance_sha256": parent["provenance_surface_sha256"],
            "pool_swap_core_v1_complete_proof_sha256": proof["pool_swap_core_v1_proof_sha256"],
            "pool_swap_fee_growth_v1_complete_proof_sha256": proof["pool_swap_fee_growth_v1_proof_sha256"],
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
    require(len(results) == 8, "Pool Swap v2 segment count drift")
    totals = Counter(
        outcome["lexical_static_category"]
        for segment in results
        for outcome in segment["semantic_surface"]["field_outcomes"]
    )
    require(
        totals
        == Counter(
            {
                CATEGORY_SETTER: 1152,
                CATEGORY_NO_SETTER: 360,
                CATEGORY_DERIVED: 104,
                CATEGORY_OUTSIDE: 776,
            }
        ),
        "Pool Swap v2 aggregate category denominator drift",
    )
    require(
        sum(len(item["semantic_surface"]["field_outcomes"]) for item in results) == 2392,
        "field outcome total drift",
    )
    require(
        sum(
            item["semantic_surface"]["field_outcome_summary"]["required_absent_overlay_count"]
            for item in results
        )
        == 0,
        "required-absence total drift",
    )
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
    require(len(results) == 28, "Pool Swap v2 pairwise diff count drift")
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
    require(raw_sha256(CORE_VERIFIER_PATH) == CORE_VERIFIER_SHA256, "Pool Swap core verifier digest drift")
    require(raw_sha256(FEE_VERIFIER_PATH) == FEE_VERIFIER_SHA256, "Pool Swap fee-growth verifier digest drift")
    require(raw_sha256(RUNTIME_VERIFIER_PATH) == RUNTIME_VERIFIER_SHA256, "Pool runtime verifier digest drift")
    require(raw_sha256(FIELD_VERIFIER_PATH) == FIELD_VERIFIER_SHA256, "field-semantics verifier digest drift")
    direct_core = _bind(
        root, CORE_CONTRACT_PATH, CORE_CONTRACT_SHA256, CORE_CONTRACT_CANONICAL_SHA256
    )
    direct_fee = _bind(
        root, FEE_CONTRACT_PATH, FEE_CONTRACT_SHA256, FEE_CONTRACT_CANONICAL_SHA256
    )
    direct_runtime = _bind(
        root, RUNTIME_CONTRACT_PATH, RUNTIME_CONTRACT_SHA256, RUNTIME_CONTRACT_CANONICAL_SHA256
    )
    direct_fields = _bind(
        root, FIELD_CONTRACT_PATH, FIELD_CONTRACT_SHA256, FIELD_CONTRACT_CANONICAL_SHA256
    )
    require(direct_core["contract_version"] == CORE_CONTRACT_VERSION, "Pool Swap core version drift")
    require(direct_fee["contract_version"] == FEE_CONTRACT_VERSION, "Pool Swap fee-growth version drift")
    require(direct_runtime["contract_version"] == RUNTIME_CONTRACT_VERSION, "Pool runtime version drift")
    require(direct_fields["contract_version"] == FIELD_CONTRACT_VERSION, "field-semantics version drift")

    core_sources = CORE.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    recomputed_core = CORE.verify_contract(root, sources=core_sources, recompute_wat=False)
    require(
        canonical_bytes(direct_core) == canonical_bytes(recomputed_core),
        "Pool Swap core direct recomputation drift",
    )
    fee_sources = FEE.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    recomputed_fee = FEE.verify_contract(root, sources=fee_sources, recompute_wat=False)
    require(
        canonical_bytes(direct_fee) == canonical_bytes(recomputed_fee),
        "Pool Swap fee-growth direct recomputation drift",
    )
    require(
        canonical_bytes(direct_core) == canonical_bytes(fee_sources["swap_contract"]),
        "Pool Swap core differs from fee-growth dependency",
    )

    recomputed_runtime = FEE.POOL_RUNTIME.verify_contract(root, wasm2wat=wasm2wat)
    require(
        canonical_bytes(direct_runtime) == canonical_bytes(recomputed_runtime),
        "Pool runtime direct recomputation drift",
    )
    require(
        canonical_bytes(direct_runtime) == canonical_bytes(core_sources["pool_runtime_contract"])
        == canonical_bytes(fee_sources["pool_runtime_contract"]),
        "Pool runtime dependency drift",
    )
    field_sources = FIELD.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    recomputed_fields = FIELD.verify_contract(root, sources=field_sources, recompute_wat=False)
    require(
        canonical_bytes(direct_fields) == canonical_bytes(recomputed_fields),
        "field-semantics direct recomputation drift",
    )
    require(
        canonical_bytes(direct_fields) == canonical_bytes(core_sources["v2_contract"])
        == canonical_bytes(fee_sources["v2_contract"]),
        "field catalog dependency drift",
    )

    schema_records = parse_direct_schema(root / SCHEMA_PATH)
    catalog = direct_fields["field_catalog"]
    catalog_summary = validate_field_catalog(catalog, schema_records)
    contexts = fee_sources["pool_wat_contexts"]
    core_contexts = core_sources["pool_wat_contexts"]
    core_by_cid = {
        item["mapping_cid"]: item for item in core_sources["pool_swap_core_proofs"]
    }
    fee_by_cid = {
        item["mapping_cid"]: item for item in fee_sources["pool_swap_fee_growth_proofs"]
    }
    require(
        recompute_wat
        and set(contexts) == set(core_contexts) == set(core_by_cid) == set(fee_by_cid)
        and len(contexts) == 8,
        "eight matching recomputed Swap contexts required",
    )
    for cid, context in contexts.items():
        require(
            hashlib.sha256(context["wat_text"].encode()).hexdigest()
            == hashlib.sha256(core_contexts[cid]["wat_text"].encode()).hexdigest(),
            f"{cid} core/fee context WAT drift",
        )
    proofs = sorted(
        (
            prove_complete_context(
                context,
                core_by_cid[cid],
                fee_by_cid[cid],
                catalog,
            )
            for cid, context in contexts.items()
        ),
        key=lambda item: item["profile_id"],
    )
    require(
        len(proofs) == 8
        and sum(item["control_generation"] == "legacy" for item in proofs) == 6
        and sum(item["control_generation"] == "modern" for item in proofs) == 2,
        "Pool Swap v2 proof population drift",
    )
    aggregate = Counter()
    for proof in proofs:
        inventory = proof["reachable_inventory"]
        aggregate.update(
            {
                "reachable_functions": inventory["reachable_function_count"],
                "direct_calls": inventory["direct_callsite_count"],
                "direct_writes": inventory["direct_memory_write_site_count"],
                "physical_mapsets": inventory["physical_typed_map_set_site_count"],
                "physical_stores": inventory["physical_store_set_site_count"],
                "indirect_calls": inventory["reachable_call_indirect_count"],
                "lexical_fields": proof["schema_api_invocation_closure"]["lexical_field_invocation_count"],
                "setter_receiver_flows": proof["schema_api_invocation_closure"]["lexical_setter_exact_receiver_flow_binding_count"],
                "setter_invocations_with_store_receiver_origin_overlap": proof["schema_api_invocation_closure"]["lexical_setter_invocation_with_store_receiver_origin_overlap_count"],
                "setter_invocations_with_all_equal_store_receiver_origin_sets": proof["schema_api_invocation_closure"]["lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count"],
                "setter_invocations_with_overlap_only_store_receiver_origin_set": proof["schema_api_invocation_closure"]["lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count"],
                "setter_to_store_receiver_origin_overlap_edges": proof["schema_api_invocation_closure"]["setter_to_store_receiver_origin_overlap_edge_count"],
                "setter_to_store_receiver_exact_equal_origin_set_edges": proof["schema_api_invocation_closure"]["setter_to_store_receiver_exact_equal_origin_set_edge_count"],
                "setter_to_store_receiver_overlap_without_origin_set_equality_edges": proof["schema_api_invocation_closure"]["setter_to_store_receiver_overlap_without_origin_set_equality_edge_count"],
                "receiver_flow_edges": proof["schema_api_invocation_closure"]["physical_receiver_flow_edge_count"],
                "returned_helper_origin_overlap_invocations": proof["schema_api_invocation_closure"]["returned_helper_store_origin_overlap_invocation_count"],
                "returned_helper_authority_records": proof["store_closure"]["returned_helper_store_authority_record_count"],
                "expanded_fields": proof["schema_api_invocation_closure"]["expanded_handler_to_setter_path_count"],
                "lexical_stores": proof["store_closure"]["lexical_graph_store_invocation_count"],
                "store_exact_target_receiver_flows": proof["store_closure"]["lexical_store_exact_target_receiver_binding_count"],
                "expanded_stores": proof["store_closure"]["expanded_store_path_count"],
            }
        )
    require(
        aggregate
        == Counter(
            {
                "reachable_functions": 1404,
                "direct_calls": 9968,
                "direct_writes": 2368,
                "physical_mapsets": 754,
                "physical_stores": 104,
                "indirect_calls": 2,
                "lexical_fields": 1576,
                "setter_receiver_flows": 1576,
                "setter_invocations_with_store_receiver_origin_overlap": 1576,
                "setter_invocations_with_all_equal_store_receiver_origin_sets": 1089,
                "setter_invocations_with_overlap_only_store_receiver_origin_set": 487,
                "setter_to_store_receiver_origin_overlap_edges": 1720,
                "setter_to_store_receiver_exact_equal_origin_set_edges": 1233,
                "setter_to_store_receiver_overlap_without_origin_set_equality_edges": 487,
                "receiver_flow_edges": 1608,
                "returned_helper_origin_overlap_invocations": 60,
                "returned_helper_authority_records": 15,
                "expanded_fields": 2072,
                "lexical_stores": 163,
                "store_exact_target_receiver_flows": 163,
                "expanded_stores": 211,
            }
        ),
        "aggregate physical/schema/store denominator drift",
    )
    return {
        "core_sources": core_sources,
        "core_contract": recomputed_core,
        "fee_sources": fee_sources,
        "fee_contract": recomputed_fee,
        "runtime_contract": recomputed_runtime,
        "field_contract": recomputed_fields,
        "field_sources": field_sources,
        "field_catalog": catalog,
        "field_catalog_summary": catalog_summary,
        "schema_records": schema_records,
        "contexts": contexts,
        "mapping_proofs": proofs,
        "aggregate_inventory": dict(sorted(aggregate.items())),
    }
def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["mapping_proofs"]
    segments = build_segments(
        sources["core_contract"],
        sources["fee_contract"],
        sources["field_catalog"],
        proofs,
    )
    diffs = build_segment_diffs(segments)
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "complete-lexical-static-pool-swap-schema-api-effect-matrix",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "mapping_count": 8,
            "handler": HANDLER_ID,
            "schema_field_count_per_segment": 299,
            "field_outcome_count": 2392,
            "stored_field_with_exact_setter_and_lexically_later_origin_overlap_store_outcome_count": 1152,
            "reachable_store_without_exact_setter_outcome_count": 360,
            "derived_without_direct_store_transition_outcome_count": 104,
            "stored_field_outside_pool_swap_store_closure_outcome_count": 776,
            "pool_swap_core_selected_overlay_count": 24,
            "pool_swap_fee_growth_selected_overlay_count": 16,
            "swap_required_field_overlay_count": 112,
            "swap_nullable_field_overlay_count": 8,
            "required_absent_overlay_count": 0,
            "reachable_function_count": 1404,
            "direct_callsite_count": 9968,
            "direct_memory_write_site_count": 2368,
            "physical_typed_map_set_site_count": 754,
            "physical_site_to_invocation_edge_count": 1608,
            "lexical_schema_field_invocation_count": 1576,
            "lexical_setter_exact_receiver_flow_binding_count": 1576,
            "lexical_setter_invocation_with_store_receiver_origin_overlap_count": 1576,
            "lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count": 1089,
            "lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count": 487,
            "setter_to_store_receiver_origin_overlap_edge_count": 1720,
            "setter_to_store_receiver_exact_equal_origin_set_edge_count": 1233,
            "setter_to_store_receiver_overlap_without_origin_set_equality_edge_count": 487,
            "physical_receiver_flow_edge_count": 1608,
            "returned_helper_store_origin_overlap_invocation_count": 60,
            "returned_helper_store_authority_record_count": 15,
            "expanded_handler_to_setter_path_count": 2072,
            "lexical_graph_store_invocation_count": 163,
            "lexical_store_exact_target_receiver_binding_count": 163,
            "physical_store_set_site_count": 104,
            "expanded_store_path_count": 211,
            "reachable_call_indirect_count": 2,
            "unique_stored_setter_field_count_per_segment": 144,
            "lexical_schema_field_invocation_count_per_mapping": 197,
            "expanded_handler_to_setter_path_count_per_mapping": 259,
            "pairwise_recursive_diff_count": 28,
            "legacy_profile_count": 6,
            "modern_profile_count": 2,
            "issue_acceptance_checkbox_completed": False,
            "claim": (
                "complete lexical static Pool.handleSwap schema-API effect matrix with exact retained-operand "
                "setter receiver flows and exact store target/receiver/value flows; invocation classifications "
                "and their setter-to-store edges prove only same-group lexical order and finite-CFG, "
                "loop-fixed-point "
                "receiver value-origin overlap, not "
                "a common execution, branch correlation, or must-alias; field values, no-setter preservation, "
                "numeric/comparator meaning, general aliases, Graph visibility/persistence, history, "
                "execution, and readiness remain false"
            ),
        },
        "aggregate_inventory": sources["aggregate_inventory"],
        "schema_catalog": sources["field_catalog_summary"],
        "source_contracts": {
            "pool_swap_core_v1_verifier": {
                "path": str(CORE_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": CORE_VERIFIER_SHA256,
            },
            "pool_swap_core_v1": {
                "path": str(CORE_CONTRACT_PATH),
                "contract_version": CORE_CONTRACT_VERSION,
                "raw_sha256": CORE_CONTRACT_SHA256,
                "canonical_sha256": CORE_CONTRACT_CANONICAL_SHA256,
                "recomputed_directly": True,
            },
            "pool_swap_fee_growth_v1_verifier": {
                "path": str(FEE_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": FEE_VERIFIER_SHA256,
            },
            "pool_swap_fee_growth_v1": {
                "path": str(FEE_CONTRACT_PATH),
                "contract_version": FEE_CONTRACT_VERSION,
                "raw_sha256": FEE_CONTRACT_SHA256,
                "canonical_sha256": FEE_CONTRACT_CANONICAL_SHA256,
                "recomputed_directly": True,
                "matches_direct_pool_swap_core_dependency": True,
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
                "matches_core_and_fee_growth_dependencies": True,
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
                "matches_core_and_fee_growth_dependencies": True,
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
            "semantic_authority": (
                "exact retained deployed Pool mapping WASM regenerated through the independently "
                "recomputed Swap core and fee-growth v1 certificates"
            ),
            "schema_authority": (
                "direct schema.graphql plus the independently recomputed 299-field segment-field v2 catalog"
            ),
            "physical_vs_semantic_ledger_boundary": (
                "1,404 reachable functions, 9,968 direct calls, 2,368 direct writes, 754 physical "
                "TypedMap#set sites, 1,608 nullable-expanded site-to-invocation edges, 1,576 lexical field "
                "invocations, and 2,072 expanded setter paths are separate fail-closed denominators"
            ),
            "receiver_flow_and_origin_overlap_boundary": (
                "all 1,576 lexical setters bind their exact retained-WAT receiver operand through any named "
                "setter parameter, or through a constructor's internal map-set receiver to its immediately "
                "following terminal get on normal fallthrough, to 1,608 physical receiver-flow edges; all 163 "
                "lexical stores separately bind exact target, receiver, and stored-value operands. Cross-ledger "
                "classification is limited to same-group finite-CFG, loop-fixed-point receiver-origin overlap. "
                "The worklist models if/else/block/loop, every br/br_if/br_table target, loop backedges, and "
                "return/unreachable termination. At invocation "
                "level, 1,089 classifications have only equal-origin-set store references and 487 have "
                "overlap-only references. Separately, 1,720 setter-to-store edges comprise 1,233 exact-equal "
                "and 487 overlap-only edges. The 60 legacy helper-return invocation classifications reference "
                "15 materialized stable-ID helper records scoped to the internal store's immediate normal "
                "fallthrough into the terminal return get"
            ),
            "constructor_fallthrough_boundary": (
                "constructor receiver evidence covers only an internal map-set immediately followed by a "
                "direct terminal local.get with equal time-scoped receiver origins; it does not prove that "
                "all successful constructor returns or control paths return that receiver"
            ),
            "returned_helper_fallthrough_boundary": (
                "each materialized helper record requires the same receiver local, equal receiver origins, "
                "and immediate internal-store/terminal-get adjacency on normal fallthrough; it does not prove that all helper "
                "invocations or control paths return the stored receiver"
            ),
            "store_profile_boundary": (
                "five legacy-mainnet mappings have 19 lexical and 25 expanded stores; legacy Base "
                "has 22 and 28; both modern mappings have 23 and 29, including two ordered "
                "PoolHourData saves with the same receiver operand local name and no intervening "
                "PoolHourData setter"
            ),
            "duplicate_save_boundary": (
                "the modern duplicate save is retained lexical call order and shared receiver-operand "
                "local-name evidence only; common execution and receiver must-alias remain false, and "
                "Graph visibility, persistence, version, and last-writer semantics remain false"
            ),
            "lexical_origin_overlap_boundary": (
                "a classified stored field needs an exact setter flow plus at least one lexically later "
                "same-group store whose branch-merged receiver origin set overlaps the setter origin set. "
                "This may-alias relation does not establish a jointly feasible continuation, branch "
                "correlation, or receiver must-alias, and the ledger is not one execution trace"
            ),
            "legacy_post_store_boundary": (
                "five legacy-mainnet profiles have twelve handler setters after their helper's "
                "only earlier origin-overlap store and no lexically later handler overlap store; the same "
                "field identities remain classified only because another setter invocation has a lexically "
                "later same-group overlap store"
            ),
            "no_setter_boundary": (
                "45 stored fields per segment have a reachable entity store but no reachable "
                "schema-API setter path; none is described as preserved, unchanged, or value-exact"
            ),
            "derived_boundary": (
                "all thirteen derived fields lack a direct Graph store transition; five have "
                "static child-association setter paths, but query visibility remains unproved"
            ),
            "swap_nullability_boundary": (
                "direct schema authority has fourteen required Swap fields and nullable logIndex; "
                "all fifteen have setter paths and the required-absence overlay is zero"
            ),
            "host_boundary": (
                "numeric, comparator, contract-call, alias, Graph store, persistence, visibility, "
                "rollback, post-fatal, historical, and last-writer semantics are not rederived"
            ),
            "composition_boundary": (
                "Pool Swap core v1, Pool Swap fee-growth v1, Pool runtime v1, segment-field v2, "
                "and direct schema are semantic inputs; Mint v2 and the other complete matrices are ordering-only"
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
                "field values, no-setter preservation, numeric/comparator meaning, arbitrary aliases, and later in-memory overwrite meaning are not characterized",
                "Graph store visibility, version, persistence, rollback, post-fatal behavior, and actual historical branch outcomes remain unproved",
                "complete Pool, Swap, related entity, other-handler, and integrated histories remain false",
            ],
            "execution": [
                "scheduler, runtime population, output, Store, package consumption, source package identity, and combined dynamic-data-source ordering remain unimplemented or unproved",
                "continuity, oracle, logical/physical/PoI parity, checkpoint authority, backfill, deployment, production, and readiness remain false",
                "issue #38 gains a bounded Swap slice only; no issue checkbox is completed",
            ],
        },
        "truth_boundary": truth_boundary(),
    }
def verify_generated_contract(
    actual: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    require(
        canonical_bytes(actual) == canonical_bytes(expected),
        "Pool Swap v2 contract differs from generated proof",
    )
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "Pool Swap v2 truth-boundary key drift")
    for key in TRUE_FLAGS:
        require(truth[key] is True, f"proved Swap v2 gate drift: {key}")
    for key in FALSE_FLAGS:
        require(truth[key] is False, f"unproved Swap v2 gate promoted: {key}")
    return expected


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
        require(path.is_file(), f"Pool Swap v2 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "Pool Swap v2 contract byte rendering drift")
    return verify_generated_contract(actual, expected)


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
        "verified Uniswap V3 Pool Swap semantics v2: "
        f"{len(result['segments'])} segments, "
        f"{result['scope']['field_outcome_count']} field outcomes, "
        f"{len(result['segment_diffs'])} diffs; no issue checkbox completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
