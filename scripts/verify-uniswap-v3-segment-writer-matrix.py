#!/usr/bin/env python3
"""Build or verify the hermetic Uniswap V3 segment writer matrix."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
WRITER_VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-writer-semantics.py"
WRITER_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_writer_semantics_for_segment_matrix", WRITER_VERIFIER
)
if WRITER_SPEC is None or WRITER_SPEC.loader is None:
    raise RuntimeError(f"cannot import {WRITER_VERIFIER}")
WRITER = importlib.util.module_from_spec(WRITER_SPEC)
sys.modules[WRITER_SPEC.name] = WRITER
WRITER_SPEC.loader.exec_module(WRITER)
ANCESTRY = WRITER.ANCESTRY


CONTRACT_VERSION = "uniswap-v3-segment-writer-matrix/v1"
CONTRACT_PATH = Path("uniswap-v3/segment-writer-matrix/v1/contract.json")
ANCESTRY_RAW_SHA256 = (
    "ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e"
)
WRITER_RAW_SHA256 = (
    "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
)
NETWORK_ORDER = ("mainnet", "base")
COMPONENT_ORDER = ("Factory", "NonfungiblePositionManager", "Pool")
REQUIRED_ABSENT = frozenset(("Collect", "Flash", "TickHourData"))
NAMED_SETTER_RE = re.compile(
    r"(?:generated/schema|src/types/schema)/([^/#]+)#set:([^/#]+)$"
)


TRUE_FLAGS = (
    "source_contract_raw_bytes_bound",
    "retained_manifest_schema_abi_wasm_bindings_complete",
    "retained_wat_and_handler_body_bindings_complete",
    "all_eight_segment_matrices_present",
    "all_manifest_handlers_present",
    "conservative_handler_entity_reachability_complete",
    "conservative_handler_contract_call_reachability_complete",
    "schema_entity_and_field_inventory_complete",
    "population_classification_inventory_complete",
    "required_absence_static_evidence_bound",
    "all_pairwise_segment_diffs_present",
    "execution_model_selection_records_complete",
)
FALSE_FLAGS = (
    "field_writer_semantics_complete",
    "full_handler_semantics_complete",
    "named_setter_candidates_are_complete_field_outputs",
    "contract_call_semantics_complete",
    "exclusion_control_flow_complete",
    "ordering_runtime_identity_bound",
    "required_nonempty_certified",
    "conditional_runtime_population_certified",
    "runtime_population_complete",
    "target_graph_node_runtime_identity_bound",
    "boundary_state_continuity_complete",
    "boundary_samples_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "segment_execution_models_decided",
    "writer_runtime_consumes_this_matrix",
    "backfill_ready",
    "production_ready",
)


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: object) -> str:
    return WRITER.canonical_sha256(value)


def render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def artifact_binding(artifact: dict[str, object]) -> dict[str, object]:
    return {
        "cid": artifact["cid"],
        "path": artifact["path"],
        "media_type": artifact["media_type"],
        "bytes": artifact["bytes"],
        "sha256": artifact["sha256"],
    }


def component_record(segment: dict[str, object], name: str) -> dict[str, object]:
    matches = [
        item for item in segment["manifest"]["components"] if item["name"] == name
    ]
    require(len(matches) == 1, f"{segment['deployment']} component {name} drift")
    return matches[0]


def selected_segments(ancestry: dict[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for network in NETWORK_ORDER:
        for segment in ancestry["networks"][network]["segments"]:
            result.append({"network": network, **segment})
    require(len(result) == 8, "segment ancestry count drift")
    return result


def schema_catalogs(
    ancestry: dict[str, object],
) -> tuple[dict[str, dict[str, object]], dict[str, set[str]]]:
    catalogs = {item["cid"]: item for item in ancestry["schema_inventories"]}
    require(len(catalogs) == 3, "schema catalog count drift")
    field_names: dict[str, set[str]] = {}
    normalized: list[list[tuple[str, tuple[tuple[str, str, str], ...]]]] = []
    for catalog in catalogs.values():
        current: list[tuple[str, tuple[tuple[str, str, str], ...]]] = []
        for entity in catalog["entities"]:
            names = {field["name"] for field in entity["fields"]}
            require(
                len(names) == len(entity["fields"]),
                f"schema {catalog['cid']} repeats {entity['name']} fields",
            )
            if entity["name"] in field_names:
                require(
                    field_names[entity["name"]] == names,
                    f"schema field-name drift for {entity['name']}",
                )
            else:
                field_names[entity["name"]] = names
            current.append(
                (
                    entity["name"],
                    tuple(
                        (field["name"], field["type"], field["storage"])
                        for field in entity["fields"]
                    ),
                )
            )
        normalized.append(current)
    require(
        all(item == normalized[0] for item in normalized[1:]),
        "retained schemas do not share one normalized entity/field contract",
    )
    require(len(field_names) == 20, "schema entity count drift")
    require(
        sum(len(fields) for fields in field_names.values()) == 299,
        "schema field count drift",
    )
    return catalogs, field_names


def recompute_handler_evidence(
    root: Path,
    wasm2wat: Path,
    ancestry: dict[str, object],
    writer: dict[str, object],
    schema_fields: dict[str, set[str]],
) -> dict[str, dict[str, dict[str, object]]]:
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    stored_analyses = {item["cid"]: item for item in writer["mapping_analyses"]}
    result: dict[str, dict[str, dict[str, object]]] = {}
    for mapping in ancestry["mapping_writer_inventories"]:
        cid = mapping["cid"]
        fresh, functions, _ = WRITER.analyze_mapping(
            root, wasm2wat, mapping, artifacts[cid]
        )
        require(
            fresh == stored_analyses[cid],
            f"{cid} matrix WAT analysis drift from bound writer v3",
        )
        mapping_handlers: dict[str, dict[str, object]] = {}
        for handler in fresh["registered_handlers"]:
            reachability = WRITER.critical_reachability(fresh, functions, handler)
            root_function = WRITER.resolve_handler(
                functions, fresh["registered_handler_export_targets"], handler
            )
            reachable = WRITER.reachable_functions(
                functions,
                root_function,
                tuple(fresh["call_indirect_table_targets"]),
            )
            named_setter_sites: list[dict[str, str]] = []
            ethereum_call_sites: list[dict[str, object]] = []
            for function_name in sorted(reachable):
                calls = WRITER.function_calls(functions[function_name])
                ethereum_call_count = calls.count(WRITER.ETHEREUM_CALL)
                if ethereum_call_count:
                    ethereum_call_sites.append(
                        {
                            "reachable_function": function_name,
                            "function_body_sha256": sha256_bytes(
                                functions[function_name].payload
                            ),
                            "ethereum_call_count": ethereum_call_count,
                        }
                    )
                for call in calls:
                    match = NAMED_SETTER_RE.search(call)
                    if match is None:
                        continue
                    entity, field = match.groups()
                    if entity not in schema_fields or field not in schema_fields[entity]:
                        continue
                    named_setter_sites.append(
                        {
                            "entity_field": f"{entity}.{field}",
                            "reachable_function": function_name,
                            "setter_call": call,
                        }
                    )
            named_setter_sites = [
                dict(item)
                for item in {
                    (item["entity_field"], item["reachable_function"], item["setter_call"]): item
                    for item in named_setter_sites
                }.values()
            ]
            named_setter_sites.sort(
                key=lambda item: (
                    item["entity_field"],
                    item["reachable_function"],
                    item["setter_call"],
                )
            )
            compact = WRITER.compact_reachability(reachability)
            mapping_handlers[handler] = {
                "body_binding": copy.deepcopy(fresh["registered_handlers"][handler]),
                "numeric_export_function_index": fresh[
                    "registered_handler_export_function_indices"
                ][handler],
                "exact_wat_export_target": fresh["registered_handler_export_targets"][
                    handler
                ],
                "conservative_entity_writer_reachability": compact,
                "conservative_named_schema_setter_candidates": sorted(
                    {item["entity_field"] for item in named_setter_sites}
                ),
                "named_schema_setter_site_count": len(named_setter_sites),
                "named_schema_setter_sites_sha256": canonical_sha256(
                    named_setter_sites
                ),
                "named_setter_candidates_are_complete_field_outputs": False,
                "conservative_ethereum_call_reachability": {
                    "reachable_callsite_count": sum(
                        item["ethereum_call_count"] for item in ethereum_call_sites
                    ),
                    "reachable_functions": ethereum_call_sites,
                    "reachable_functions_sha256": canonical_sha256(
                        ethereum_call_sites
                    ),
                    "complete_conservative_call_graph_closure": True,
                    "actual_execution_or_call_value_semantics_proven": False,
                },
            }
        result[cid] = mapping_handlers
    require(len(result) == 20, "matrix mapping evidence count drift")
    require(
        sum(len(item) for item in result.values()) == 70,
        "matrix unique mapping-handler evidence count drift",
    )
    return result


def factory_field_categories(writer: dict[str, object]) -> dict[str, str]:
    contract = writer["factory_writer_contract"]["common"]["field_writer_contract"]
    result: dict[str, str] = {}
    for category, values in contract.items():
        if category in {"coverage", "entity_id_sources"}:
            continue
        for entity_field in values:
            require(entity_field not in result, f"Factory field category repeats {entity_field}")
            result[entity_field] = category
    for entity_field in contract["entity_id_sources"]:
        require(entity_field not in result, f"Factory ID field category repeats {entity_field}")
        result[entity_field] = "entity_id_sources"
    return result


def writer_indexes(writer: dict[str, object]) -> dict[str, dict[str, object]]:
    npm: dict[str, object] = {}
    for profile in writer["npm_semantic_profiles"]:
        for evidence in profile["mapping_evidence"]:
            npm[evidence["mapping_cid"]] = evidence
    return {
        "analysis": {item["cid"]: item for item in writer["mapping_analyses"]},
        "factory": {
            item["mapping_cid"]: item
            for item in writer["factory_writer_contract"]["mapping_bindings"]
        },
        "npm": npm,
        "pool": {
            item["mapping_cid"]: item
            for item in writer["pool_writer_contract"]["mapping_bindings"]
        },
        "flash": {item["mapping_cid"]: item for item in writer["pool_flash_evidence"]},
        "segment": {item["deployment"]: item for item in writer["segments"]},
        "segment_contract": {
            item["deployment"]: item for item in writer["segment_writer_contracts"]
        },
    }


def reviewed_handler_semantics(
    component: str,
    handler: str,
    factory: dict[str, object],
    npm: dict[str, object],
    pool: dict[str, object],
    flash: dict[str, object],
) -> dict[str, object]:
    if component == "Factory":
        return {
            "evidence_level": "digest_bound_reviewed_with_partial_lexical_checks",
            "field_contract_scope": "all stored Factory, Bundle, Token, and Pool fields during PoolCreated",
            "excluded_pool_guard": factory["excluded_pool_guard_observation"],
            "effect_order": factory["pool_created_effect_order_observation"],
            "pool_tick_write": factory["pool_tick_write"],
            "pool_created_event_row_write": factory["pool_created_event_row_write"],
            "complete": False,
        }
    if component == "NonfungiblePositionManager":
        common = {
            "evidence_level": "digest_bound_reviewed_with_machine_checked_reachability",
            "snapshot_written": handler in npm["snapshot_handlers"],
            "fee_refresh": handler in npm["fee_refresh_handlers"],
            "excluded_pool_guard_reviewed": handler in npm["excluded_pool_handlers"],
            "historical_block_guard": next(
                (item for item in npm["block_guard_proofs"] if item["handler"] == handler),
                None,
            ),
            "complete": False,
        }
        if handler == "handleIncreaseLiquidity":
            common["operation"] = npm["increase_update_mode"]
            common["token_missing_policy"] = npm[
                "increase_decrease_token_missing_policy"
            ]
        elif handler == "handleDecreaseLiquidity":
            common["operation"] = npm["decrease_update_mode"]
            common["token_missing_policy"] = npm[
                "increase_decrease_token_missing_policy"
            ]
        elif handler == "handleCollect":
            common["operation"] = npm["collect_write_model"]
            common["collected_fees_token0"] = npm[
                "collect_final_collected_fees_token0"
            ]
            common["collected_fees_token1"] = npm[
                "collect_final_collected_fees_token1"
            ]
            common["token_missing_policy"] = npm["collect_token_missing_policy"]
        elif handler == "handleTransfer":
            common["operation"] = npm["transfer_model"]
        return common
    observation = pool["handlers"][handler]
    result = {
        "evidence_level": "digest_bound_reviewed_with_machine_checked_reachability",
        "event_row": observation["event_row"],
        "observed_fields": observation["observed_fields"],
        "observation": observation["reviewed_observation"],
        "complete": False,
    }
    if handler == "handleInitialize":
        result["persistence"] = pool["initialize_persistence_observation"]
    elif handler == "handleSwap":
        result["fee_spacing"] = pool["fee_spacing_evidence"]
        result["tick_day_relation"] = pool["tick_day_relation_evidence"]
        result["hour_resaves"] = pool["hour_resave_evidence"]
    elif handler in {"handleMint", "handleBurn"}:
        result["pool_tick_calls"] = pool["mint_burn_tick_calls"]
    elif handler == "handleFlash":
        result["flash"] = {
            "contract_call_kind": flash["contract_call_kind"],
            "reviewed_call_order": flash["reviewed_call_order"],
            "field_flow_evidence": flash["field_flow_evidence"],
        }
    return result


def handler_matrix(
    segment: dict[str, object],
    evidence: dict[str, dict[str, dict[str, object]]],
    indexes: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    factory_cid = component_record(segment, "Factory")["mapping"]["wasm_cid"]
    npm_cid = component_record(segment, "NonfungiblePositionManager")["mapping"][
        "wasm_cid"
    ]
    pool_cid = component_record(segment, "Pool")["mapping"]["wasm_cid"]
    selected = {
        "Factory": indexes["factory"][factory_cid],
        "NonfungiblePositionManager": indexes["npm"][npm_cid],
        "Pool": indexes["pool"][pool_cid],
    }
    result: list[dict[str, object]] = []
    for component_name in COMPONENT_ORDER:
        component = component_record(segment, component_name)
        mapping_cid = component["mapping"]["wasm_cid"]
        for manifest_handler in component["mapping"]["handlers"]:
            handler = manifest_handler["handler"]
            proof = evidence[mapping_cid][handler]
            reviewed = reviewed_handler_semantics(
                component_name,
                handler,
                selected["Factory"],
                selected["NonfungiblePositionManager"],
                selected["Pool"],
                indexes["flash"][pool_cid],
            )
            result.append(
                {
                    "handler_id": f"{component_name}.{handler}",
                    "component": component_name,
                    "component_type": component["component_type"],
                    "event": manifest_handler["event"],
                    "mapping_cid": mapping_cid,
                    **copy.deepcopy(proof),
                    "reviewed_semantics": reviewed,
                    "complete_field_output_semantics": False,
                }
            )
    require(len(result) == 10, f"{segment['deployment']} handler count drift")
    require(
        len({item["handler_id"] for item in result}) == 10,
        f"{segment['deployment']} handler identity repeats",
    )
    return result


def component_artifact_bindings(
    segment: dict[str, object],
    handlers: list[dict[str, object]],
    artifacts: dict[str, dict[str, object]],
    indexes: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name in COMPONENT_ORDER:
        component = component_record(segment, name)
        cid = component["mapping"]["wasm_cid"]
        analysis = indexes["analysis"][cid]
        component_handlers = [item for item in handlers if item["component"] == name]
        result.append(
            {
                "name": name,
                "component_type": component["component_type"],
                "kind": component["kind"],
                "source": copy.deepcopy(component["source"]),
                "mapping_api_version": component["mapping"]["api_version"],
                "mapping_kind": component["mapping"]["kind"],
                "mapping_language": component["mapping"]["language"],
                "declared_entities": copy.deepcopy(
                    component["mapping"]["declared_entities"]
                ),
                "abi_artifacts": [
                    {
                        "name": item["name"],
                        "artifact": artifact_binding(artifacts[item["cid"]]),
                    }
                    for item in component["mapping"]["abis"]
                ],
                "mapping_artifact": artifact_binding(artifacts[cid]),
                "mapping_wat_sha256": analysis["wat_sha256"],
                "mapping_analysis_sha256": canonical_sha256(analysis),
                "handlers_in_manifest_order": [
                    {
                        "event": item["event"],
                        "handler": item["handler_id"].split(".", 1)[1],
                        "numeric_export_function_index": item[
                            "numeric_export_function_index"
                        ],
                        "exact_wat_export_target": item["exact_wat_export_target"],
                        "body_binding": copy.deepcopy(item["body_binding"]),
                    }
                    for item in component_handlers
                ],
            }
        )
    return result


def factory_field_evidence(
    entity_field: str, categories: dict[str, str]
) -> list[dict[str, object]]:
    if entity_field not in categories:
        return []
    return [
        {
            "kind": "digest_bound_reviewed_factory_field_category",
            "category": categories[entity_field],
            "source_path": "$.factory_writer_contract.common.field_writer_contract",
            "machine_proven_value_semantics": False,
        }
    ]


def entity_field_matrix(
    schema: dict[str, object],
    handlers: list[dict[str, object]],
    factory_categories: dict[str, str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for entity in schema["entities"]:
        entity_name = entity["name"]
        writer_handlers = [
            item["handler_id"]
            for item in handlers
            if entity_name
            in item["conservative_entity_writer_reachability"][
                "reachable_store_set_targets"
            ]
        ]
        field_rows: list[dict[str, object]] = []
        for field in entity["fields"]:
            entity_field = f"{entity_name}.{field['name']}"
            evidence: list[dict[str, object]] = []
            if field["storage"] == "derived":
                status = "derived_query_field_not_stored"
            elif entity_name in REQUIRED_ABSENT:
                status = "required_absent_static_certified"
            else:
                evidence.extend(factory_field_evidence(entity_field, factory_categories))
                named_handlers = [
                    item["handler_id"]
                    for item in handlers
                    if entity_field
                    in item["conservative_named_schema_setter_candidates"]
                ]
                if named_handlers:
                    evidence.append(
                        {
                            "kind": "conservative_named_setter_reachability",
                            "handlers": named_handlers,
                            "definite_execution_or_complete_coverage": False,
                        }
                    )
                pool_handlers = [
                    item["handler_id"]
                    for item in handlers
                    if item["component"] == "Pool"
                    and entity_field
                    in item["reviewed_semantics"].get("observed_fields", [])
                ]
                if pool_handlers:
                    evidence.append(
                        {
                            "kind": "digest_bound_reviewed_pool_observation",
                            "handlers": pool_handlers,
                            "machine_proven_value_semantics": False,
                        }
                    )
                if any(
                    item["kind"] == "digest_bound_reviewed_factory_field_category"
                    for item in evidence
                ):
                    status = "digest_bound_reviewed_value_semantics"
                elif evidence:
                    status = "partial_writer_evidence_only"
                elif writer_handlers:
                    status = "entity_writer_reachable_field_semantics_unproven"
                else:
                    status = "no_writer_reachability_or_field_semantics_proven"
            field_rows.append(
                {
                    "name": field["name"],
                    "type": field["type"],
                    "storage": field["storage"],
                    "directives": field["directives"],
                    "writer_evidence_status": status,
                    "writer_evidence": evidence,
                    "complete_value_semantics": False,
                }
            )
        required_absent = entity_name in REQUIRED_ABSENT
        require(
            not required_absent or not writer_handlers,
            f"required-absent entity {entity_name} has reachable writer",
        )
        result.append(
            {
                "entity": entity_name,
                "schema_directives": entity["directives"],
                "conservative_writer_handlers": writer_handlers,
                "population_contract": {
                    "classification": (
                        "required_absent" if required_absent else "conditional"
                    ),
                    "required_nonempty": False,
                    "conditional": not required_absent,
                    "required_absent": required_absent,
                    "static_writer_presence_bound": bool(writer_handlers),
                    "static_writer_absence_certified": required_absent,
                    "runtime_population_certified": False,
                    "basis": (
                        "all-function fixed-target writer closure proves no writer"
                        if required_absent
                        else "a conservative handler-to-writer path exists, but no oracle proves a row must exist"
                    ),
                },
                "fields": field_rows,
                "complete_field_writer_semantics": False,
            }
        )
    require(len(result) == 20, "segment entity matrix count drift")
    require(
        sum(len(item["fields"]) for item in result) == 299,
        "segment field matrix count drift",
    )
    return result


def call_contract(
    factory: dict[str, object],
    npm: dict[str, object],
    pool: dict[str, object],
    flash: dict[str, object],
) -> dict[str, object]:
    return {
        "observations": [
            {
                "handlers": ["Factory.handlePoolCreated"],
                "kind": "token_metadata_and_total_supply_calls",
                "model": factory["metadata_evidence"]["total_supply_model"],
                "evidence_level": "helper_shape_machine_checked_and_digest_bound_reviewed",
            },
            {
                "handlers": [
                    f"NonfungiblePositionManager.{handler}"
                    for handler in npm["fee_refresh_handlers"]
                ],
                "kind": "position_manager_positions_try_call",
                "model": npm["fee_refresh_call_kind"],
                "temporal_source_model": npm["contract_call_temporal_source_model"],
                "evidence_level": "call_presence_machine_checked_and_digest_bound_reviewed",
            },
            {
                "handlers": ["Pool.handleMint", "Pool.handleBurn"],
                "kind": "pool_ticks_non_try_calls",
                "model": pool["mint_burn_tick_calls"],
                "evidence_level": "digest_bound_reviewed",
            },
            {
                "handlers": ["Pool.handleSwap"],
                "kind": "pool_fee_growth_refresh_calls",
                "model": "refresh Pool.feeGrowthGlobal0X128 and Pool.feeGrowthGlobal1X128 during Swap",
                "evidence_level": "digest_bound_reviewed",
            },
            {
                "handlers": ["Pool.handleFlash"],
                "kind": "pool_fee_growth_non_try_calls",
                "model": flash["contract_call_kind"],
                "temporal_source_model": flash["contract_call_temporal_source_model"],
                "reviewed_call_order": flash["reviewed_call_order"],
                "same_path_machine_proven": False,
                "evidence_level": "partial_lexical_machine_checks_and_digest_bound_review",
            },
        ],
        "complete_call_inventory_and_value_semantics": False,
    }


def exclusion_contract(
    factory: dict[str, object], npm: dict[str, object], pool: dict[str, object]
) -> dict[str, object]:
    return {
        "observations": [
            {
                "handlers": ["Factory.handlePoolCreated"],
                "address": factory["excluded_pool"],
                "literal_present_machine_checked": factory[
                    "excluded_pool_guard_observation"
                ]["literal_present_machine_checked"],
                "equality_present_machine_checked": factory[
                    "excluded_pool_guard_observation"
                ]["some_equality_call_present_machine_checked"],
                "event_to_early_return_control_flow_machine_proven": False,
            },
            {
                "handlers": [
                    f"NonfungiblePositionManager.{handler}"
                    for handler in npm["excluded_pool_handlers"]
                ],
                "address": npm["excluded_pool"],
                "literal_and_equality_reachable_machine_checked": True,
                "event_to_early_return_control_flow_machine_proven": False,
            },
            {
                "handlers": ["Pool.handleSwap"],
                "address": pool["swap_excluded_pool"],
                "evidence_level": "digest_bound_reviewed_profile_axis",
                "event_to_early_return_control_flow_machine_proven": False,
            },
        ],
        "complete_exclusion_control_flow": False,
    }


def ordering_contract(
    source_segment: dict[str, object],
    handlers: list[dict[str, object]],
    factory: dict[str, object],
    flash: dict[str, object],
) -> dict[str, object]:
    by_component = {
        component: [
            item["handler_id"] for item in handlers if item["component"] == component
        ]
        for component in COMPONENT_ORDER
    }
    return {
        "manifest_handlers_in_declared_order": by_component,
        "global_log_trigger_order_source_model": source_segment[
            "trigger_order_source_model"
        ],
        "target_runtime_identity_bound": False,
        "factory_effect_order_observation": factory[
            "pool_created_effect_order_observation"
        ],
        "flash_call_order_observation": {
            "reviewed_call_order": flash["reviewed_call_order"],
            "lexical_call_setter_save_order_checked": flash["field_flow_evidence"][
                "lexical_call_setter_save_order_checked"
            ],
            "same_path_machine_proven": False,
        },
        "same_block_dynamic_data_source_causality_certified": False,
        "complete_runtime_ordering_contract": False,
    }


def quirk_contract(
    source_segment: dict[str, object],
    factory: dict[str, object],
    npm: dict[str, object],
    pool: dict[str, object],
) -> dict[str, object]:
    pool_axes = (
        "control_generation",
        "pricing_profile",
        "tracked_amount_threshold",
        "whitelist_cardinality_gate",
        "stable_shortcut",
        "initialize_persists_pool",
        "tick_day_tick_relation_mode",
        "fee_spacing_mode",
        "explicit_hour_resaves",
    )
    return {
        "factory": {
            "profile_id": factory["profile_id"],
            "metadata_generation": factory["metadata_generation"],
            "static_metadata_profile": factory["static_metadata_profile"],
            "initial_array_slots": factory["initial_array_slots"],
            "appended_static_entries": factory["appended_static_entries"],
            "safe_literal_array": factory["safe_literal_array"],
            "total_supply_model": factory["metadata_evidence"]["total_supply_model"],
            "pool_tick_write": factory["pool_tick_write"],
            "whitelist_pool_update": factory["whitelist_pool_update"],
            "complete_semantics": False,
        },
        "nonfungible_position_manager": {
            "profile_id": npm["profile_id"],
            "collect_write_model": npm["collect_write_model"],
            "collected_fees_token0": npm["collect_final_collected_fees_token0"],
            "collected_fees_token1": npm["collect_final_collected_fees_token1"],
            "block_guard_handlers": npm["block_guard_handlers"],
            "historical_guard_in_segment": {
                "block": source_segment["historical_guard"]["block"],
                "present_in_mapping": source_segment["historical_guard"][
                    "present_in_mapping"
                ],
                "handler_proofs": source_segment["historical_guard"][
                    "handler_proofs"
                ],
                "effective_in_segment": source_segment["historical_guard"][
                    "effective_in_segment"
                ],
            },
            "snapshot_id_model": npm["snapshot_id_model"],
            "complete_semantics": False,
        },
        "pool": {
            **{key: pool[key] for key in pool_axes},
            "token_day_hour_untracked_volume_quirk_reviewed": True,
            "complete_semantics": False,
        },
        "silent_normalization_allowed": False,
        "all_profile_axes_machine_proven": False,
    }


def profile_bindings(
    factory: dict[str, object],
    npm: dict[str, object],
    pool: dict[str, object],
    flash: dict[str, object],
) -> dict[str, object]:
    return {
        "factory": {
            "mapping_cid": factory["mapping_cid"],
            "profile_id": factory["profile_id"],
            "source_record_sha256": canonical_sha256(factory),
        },
        "nonfungible_position_manager": {
            "mapping_cid": npm["mapping_cid"],
            "profile_id": npm["profile_id"],
            "source_record_sha256": canonical_sha256(npm),
        },
        "pool": {
            "mapping_cid": pool["mapping_cid"],
            "profile_id": pool["profile_id"],
            "source_record_sha256": canonical_sha256(pool),
            "flash_record_sha256": canonical_sha256(flash),
        },
    }


FACTORY_EFFECT_OPERATION = {
    "Pool.save": "persist_pool",
    "PoolTemplate.create": "create_pool_dynamic_data_source",
    "Token[token0].save": "persist_token0",
    "Token[token1].save": "persist_token1",
    "Factory.save": "persist_factory",
}
FLASH_OPERATION = {
    "feeGrowthGlobal0X128": "read_fee_growth_global_0",
    "feeGrowthGlobal1X128": "read_fee_growth_global_1",
    "set both Pool fields": "assign_both_pool_fee_growth_fields",
    "save Pool": "persist_pool",
}


def normalized_operations(
    values: list[str], mapping: dict[str, str], field: str
) -> list[str]:
    require(
        all(value in mapping for value in values),
        f"unknown implementation spelling in reviewed {field}",
    )
    return [mapping[value] for value in values]


def normalized_total_supply_model(model: str) -> str:
    if "CallResult pointer/allocation" in model:
        return "use_call_result_pointer_or_allocation_instead_of_decoded_erc20_result"
    if model == "decode the ERC20 totalSupply result as BigInt":
        return "use_decoded_erc20_total_supply_result"
    raise VerificationError(f"unknown total-supply model: {model}")


def normalized_handler_semantics(handler: dict[str, object]) -> dict[str, object]:
    reviewed = handler["reviewed_semantics"]
    result: dict[str, object] = {
        "handler_id": handler["handler_id"],
        "event": handler["event"],
        "complete_field_output_semantics": False,
    }
    component = handler["component"]
    name = handler["handler_id"].split(".", 1)[1]
    if component == "Factory":
        result.update(
            {
                "field_contract_scope": reviewed["field_contract_scope"],
                "pool_tick_write": reviewed["pool_tick_write"],
                "pool_created_event_row_write": reviewed[
                    "pool_created_event_row_write"
                ],
                "reviewed_effect_order": normalized_operations(
                    reviewed["effect_order"]["reviewed_order"],
                    FACTORY_EFFECT_OPERATION,
                    "Factory effect order",
                ),
            }
        )
    elif component == "NonfungiblePositionManager":
        for key in (
            "snapshot_written",
            "fee_refresh",
            "excluded_pool_guard_reviewed",
            "operation",
            "token_missing_policy",
            "collected_fees_token0",
            "collected_fees_token1",
        ):
            if key in reviewed:
                result[key] = reviewed[key]
        guard = reviewed["historical_block_guard"]
        result["historical_block_guard"] = (
            None
            if guard is None
            else {
                "block": guard["block"],
                "conditional_early_return": guard["conditional_early_return"],
            }
        )
    elif component == "Pool":
        result.update(
            {
                "event_row": reviewed["event_row"],
                "observed_fields": reviewed["observed_fields"],
                "reviewed_operation": reviewed["observation"],
            }
        )
        if name == "handleInitialize":
            result["pool_persistence_reviewed"] = reviewed["persistence"][
                "lexical_pool_save_callsite_present"
            ]
        elif name == "handleSwap":
            result.update(
                {
                    "fee_spacing_mode": reviewed["fee_spacing"]["mode"],
                    "fee_tier_to_tick_spacing": reviewed["fee_spacing"][
                        "fee_tier_to_tick_spacing"
                    ],
                    "tick_day_relation_mode": reviewed["tick_day_relation"][
                        "mode"
                    ],
                    "explicit_hour_resaves": reviewed["hour_resaves"][
                        "explicit_hour_resaves_observed"
                    ],
                }
            )
        elif name in {"handleMint", "handleBurn"}:
            result["pool_tick_call_failure_model"] = (
                "non_try_pool_tick_read_failure_aborts_and_rolls_back_handler"
            )
        elif name == "handleFlash":
            result.update(
                {
                    "call_mode": "non_try_fee_growth_reads_abort_on_failure",
                    "reviewed_operation_order": normalized_operations(
                        reviewed["flash"]["reviewed_call_order"],
                        FLASH_OPERATION,
                        "Flash operation order",
                    ),
                }
            )
    return result


def normalized_call_semantics(calls: dict[str, object]) -> dict[str, object]:
    result: list[dict[str, object]] = []
    for observation in calls["observations"]:
        kind = observation["kind"]
        record: dict[str, object] = {
            "handlers": observation["handlers"],
            "kind": kind,
        }
        if kind == "token_metadata_and_total_supply_calls":
            record["total_supply_result_model"] = normalized_total_supply_model(
                observation["model"]
            )
        elif kind == "position_manager_positions_try_call":
            record.update(
                {
                    "call_mode": "try",
                    "on_revert": "preserve_prior_fee_growth_fields",
                    "temporal_source_model": observation[
                        "temporal_source_model"
                    ],
                }
            )
        elif kind == "pool_ticks_non_try_calls":
            record["call_mode"] = "non_try_abort_and_roll_back_handler_on_failure"
        elif kind == "pool_fee_growth_refresh_calls":
            record["fields"] = [
                "Pool.feeGrowthGlobal0X128",
                "Pool.feeGrowthGlobal1X128",
            ]
        elif kind == "pool_fee_growth_non_try_calls":
            record.update(
                {
                    "call_mode": "non_try_abort_and_roll_back_handler_on_failure",
                    "fields": [
                        "Pool.feeGrowthGlobal0X128",
                        "Pool.feeGrowthGlobal1X128",
                    ],
                    "temporal_source_model": observation[
                        "temporal_source_model"
                    ],
                    "reviewed_operation_order": normalized_operations(
                        observation["reviewed_call_order"],
                        FLASH_OPERATION,
                        "Flash call contract order",
                    ),
                }
            )
        else:
            raise VerificationError(f"unknown reviewed call contract kind: {kind}")
        result.append(record)
    return {
        "observations": result,
        "complete_call_inventory_and_value_semantics": False,
    }


def normalized_exclusion_semantics(exclusions: dict[str, object]) -> dict[str, object]:
    return {
        "observations": [
            {
                "handlers": item["handlers"],
                "address": item["address"],
            }
            for item in exclusions["observations"]
        ],
        "complete_exclusion_control_flow": False,
    }


def normalized_ordering_semantics(ordering: dict[str, object]) -> dict[str, object]:
    return {
        "manifest_handlers_in_declared_order": ordering[
            "manifest_handlers_in_declared_order"
        ],
        "global_log_trigger_order_source_model": ordering[
            "global_log_trigger_order_source_model"
        ],
        "factory_effect_order": normalized_operations(
            ordering["factory_effect_order_observation"]["reviewed_order"],
            FACTORY_EFFECT_OPERATION,
            "Factory ordering contract",
        ),
        "flash_operation_order": normalized_operations(
            ordering["flash_call_order_observation"]["reviewed_call_order"],
            FLASH_OPERATION,
            "Flash ordering contract",
        ),
        "complete_runtime_ordering_contract": False,
    }


def normalized_quirk_semantics(quirks: dict[str, object]) -> dict[str, object]:
    factory = quirks["factory"]
    npm = quirks["nonfungible_position_manager"]
    pool = quirks["pool"]
    historical_guard = npm["historical_guard_in_segment"]
    return {
        "factory": {
            "metadata_generation": factory["metadata_generation"],
            "static_metadata_profile": factory["static_metadata_profile"],
            "initial_array_slots": factory["initial_array_slots"],
            "appended_static_entries": factory["appended_static_entries"],
            "safe_literal_array": factory["safe_literal_array"],
            "total_supply_result_model": normalized_total_supply_model(
                factory["total_supply_model"]
            ),
            "pool_tick_write": factory["pool_tick_write"],
            "whitelist_pool_update": factory["whitelist_pool_update"],
            "complete_semantics": False,
        },
        "nonfungible_position_manager": {
            "collect_write_model": npm["collect_write_model"],
            "collected_fees_token0": npm["collected_fees_token0"],
            "collected_fees_token1": npm["collected_fees_token1"],
            "block_guard_handlers": npm["block_guard_handlers"],
            "historical_guard_in_segment": {
                "block": historical_guard["block"],
                "present_in_mapping": historical_guard["present_in_mapping"],
                "handlers": [
                    item["handler"] for item in historical_guard["handler_proofs"]
                ],
                "effective_in_segment": historical_guard["effective_in_segment"],
            },
            "snapshot_id_model": npm["snapshot_id_model"],
            "complete_semantics": False,
        },
        "pool": copy.deepcopy(pool),
        "silent_normalization_allowed": False,
        "all_profile_axes_machine_proven": False,
    }


SEMANTIC_FORBIDDEN_EXACT_KEYS = {
    "wat_line",
    "site_id",
    "profile_id",
    "call",
    "setter_call",
    "function",
    "source_path",
}


def semantic_evidence_coordinate_paths(
    value: object, path: str = "$"
) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if (
                key in SEMANTIC_FORBIDDEN_EXACT_KEYS
                or key.endswith("_wat_line")
                or key.endswith("_wat_lines")
                or key.endswith("_sha256")
            ):
                result.append(child)
            result.extend(semantic_evidence_coordinate_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(semantic_evidence_coordinate_paths(item, f"{path}[{index}]"))
    return result


def provenance_surface(segment: dict[str, object]) -> dict[str, object]:
    return {
        "handlers": [
            {
                "handler_id": item["handler_id"],
                "entity_outputs": item["conservative_entity_writer_reachability"][
                    "reachable_store_set_targets"
                ],
                "named_field_setter_candidates": item[
                    "conservative_named_schema_setter_candidates"
                ],
                "named_schema_setter_sites_sha256": item[
                    "named_schema_setter_sites_sha256"
                ],
                "conservative_ethereum_call_reachability": item[
                    "conservative_ethereum_call_reachability"
                ],
                "reviewed_evidence": item["reviewed_semantics"],
            }
            for item in segment["handlers"]
        ],
        "entity_field_matrix": segment["entity_field_matrix"],
        "profile_bindings": segment["profile_bindings"],
        "calls": segment["calls"],
        "exclusions": segment["exclusions"],
        "ordering": segment["ordering"],
        "quirks": segment["quirks"],
    }


def semantic_surface(segment: dict[str, object]) -> dict[str, object]:
    result = {
        "handlers": [normalized_handler_semantics(item) for item in segment["handlers"]],
        "calls": normalized_call_semantics(segment["calls"]),
        "exclusions": normalized_exclusion_semantics(segment["exclusions"]),
        "ordering": normalized_ordering_semantics(segment["ordering"]),
        "quirks": normalized_quirk_semantics(segment["quirks"]),
        "deterministic_handler_error_policy_under_source_model": segment[
            "deterministic_handler_error_policy_under_source_model"
        ],
    }
    require(
        not semantic_evidence_coordinate_paths(result),
        "semantic surface contains artifact/provenance coordinates",
    )
    return result


def segment_matrix(
    segment: dict[str, object],
    ancestry: dict[str, object],
    writer: dict[str, object],
    evidence: dict[str, dict[str, dict[str, object]]],
    catalogs: dict[str, dict[str, object]],
    indexes: dict[str, dict[str, object]],
    categories: dict[str, str],
) -> dict[str, object]:
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    source_segment = indexes["segment"][segment["deployment"]]
    source_contract = indexes["segment_contract"][segment["deployment"]]
    handlers = handler_matrix(segment, evidence, indexes)
    factory_cid = component_record(segment, "Factory")["mapping"]["wasm_cid"]
    npm_cid = component_record(segment, "NonfungiblePositionManager")["mapping"][
        "wasm_cid"
    ]
    pool_cid = component_record(segment, "Pool")["mapping"]["wasm_cid"]
    factory = indexes["factory"][factory_cid]
    npm = indexes["npm"][npm_cid]
    pool = indexes["pool"][pool_cid]
    flash = indexes["flash"][pool_cid]
    schema_cid = segment["manifest"]["schema_cid"]
    bindings = {
        "manifest": artifact_binding(artifacts[segment["manifest_cid"]]),
        "schema": artifact_binding(artifacts[schema_cid]),
        "components": component_artifact_bindings(
            segment, handlers, artifacts, indexes
        ),
    }
    result = {
        "segment_id": f"{segment['network']}:{segment['deployment']}",
        "network": segment["network"],
        "deployment": segment["deployment"],
        "start_block_inclusive": segment["start_block_inclusive"],
        "end_block_inclusive": segment["end_block_inclusive"],
        "graft": copy.deepcopy(segment["graft"]),
        "manifest_features": copy.deepcopy(segment["manifest"]["features"]),
        "artifact_bindings": bindings,
        "artifact_bindings_sha256": canonical_sha256(bindings),
        "source_writer_segment_contract_sha256": canonical_sha256(source_contract),
        "source_writer_semantic_contract_sha256": source_contract[
            "semantic_contract_sha256"
        ],
        "profile_bindings": profile_bindings(factory, npm, pool, flash),
        "handlers": handlers,
        "entity_field_matrix": entity_field_matrix(
            catalogs[schema_cid], handlers, categories
        ),
        "calls": call_contract(factory, npm, pool, flash),
        "exclusions": exclusion_contract(factory, npm, pool),
        "ordering": ordering_contract(source_segment, handlers, factory, flash),
        "quirks": quirk_contract(source_segment, factory, npm, pool),
        "deterministic_handler_error_policy_under_source_model": source_segment[
            "deterministic_handler_error_policy_under_source_model"
        ],
        "target_runtime_identity_bound": False,
        "boundary_state_continuity_certified": False,
        "graph_oracle_evidence_bound": False,
        "execution_model": "undecided",
        "backfill_allowed": False,
        "complete_field_writer_semantics": False,
    }
    provenance = provenance_surface(result)
    surface = semantic_surface(result)
    result["provenance_surface_sha256"] = canonical_sha256(provenance)
    result["semantic_surface_sha256"] = canonical_sha256(surface)
    result["matrix_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in result.items()
            if key not in {"matrix_sha256"}
        }
    )
    return result


def build_diffs(segments: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for left, right in itertools.combinations(segments, 2):
        if left["network"] != right["network"]:
            relation = "cross_network"
            boundary = None
        elif (
            left["end_block_inclusive"] is not None
            and right["start_block_inclusive"] == left["end_block_inclusive"] + 1
        ):
            relation = "adjacent_graft"
            boundary = left["end_block_inclusive"]
        else:
            relation = "same_network_nonadjacent"
            boundary = None
        left_surface = semantic_surface(left)
        right_surface = semantic_surface(right)
        left_provenance = provenance_surface(left)
        right_provenance = provenance_surface(right)
        artifact_paths = WRITER.json_diff_paths(
            left["artifact_bindings"], right["artifact_bindings"]
        )
        provenance_paths = WRITER.json_diff_paths(left_provenance, right_provenance)
        semantic_paths = WRITER.json_diff_paths(left_surface, right_surface)
        result.append(
            {
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "relation": relation,
                "boundary_block": boundary,
                "artifact_equal": not artifact_paths,
                "writer_provenance_equal": not provenance_paths,
                "semantic_surface_equal": not semantic_paths,
                "artifact_diff_paths": artifact_paths,
                "writer_provenance_diff_paths": provenance_paths,
                "semantic_diff_paths": semantic_paths,
                "left_artifact_bindings_sha256": left[
                    "artifact_bindings_sha256"
                ],
                "right_artifact_bindings_sha256": right[
                    "artifact_bindings_sha256"
                ],
                "left_provenance_surface_sha256": left[
                    "provenance_surface_sha256"
                ],
                "right_provenance_surface_sha256": right[
                    "provenance_surface_sha256"
                ],
                "left_semantic_surface_sha256": left["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right["semantic_surface_sha256"],
                "boundary_state_compared": False,
                "graph_oracle_compared": False,
            }
        )
    return result


def execution_model_contract(segments: list[dict[str, object]]) -> dict[str, object]:
    blockers = [
        "complete handler and field value semantics are not proved",
        "target Graph Node runtime identity is not bound",
        "boundary state continuity and samples are absent",
        "logical, physical, and proof-of-indexing parity are absent",
    ]
    return {
        "allowed_models": [
            {
                "model": "emulate_deployed_segment_writers",
                "description": "execute a segment-selected implementation of every deployed writer quirk",
                "eligible": False,
                "blockers": blockers,
            },
            {
                "model": "certified_boundary_seed_then_current_writer",
                "description": "seed exact certified graft-boundary state, then execute the current segment writer only",
                "eligible": False,
                "blockers": blockers,
            },
        ],
        "segment_selections": [
            {
                "segment_id": item["segment_id"],
                "selected_model": "undecided",
                "selection_certified": False,
                "backfill_allowed": False,
                "blockers": blockers,
            }
            for item in segments
        ],
        "all_segments_decided": False,
    }


def build_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    ancestry_path = root / ANCESTRY.CONTRACT_PATH
    writer_path = root / WRITER.CONTRACT_PATH
    require(
        sha256_bytes(ancestry_path.read_bytes()) == ANCESTRY_RAW_SHA256,
        "segment matrix v1 requires the exact ancestry v2 raw bytes",
    )
    require(
        sha256_bytes(writer_path.read_bytes()) == WRITER_RAW_SHA256,
        "segment matrix v1 requires the exact writer v3 raw bytes",
    )
    executable = WRITER.resolve_wasm2wat(wasm2wat)
    ancestry = ANCESTRY.verify(root)
    writer = WRITER.verify(root, writer_path, executable)
    catalogs, schema_fields = schema_catalogs(ancestry)
    evidence = recompute_handler_evidence(
        root, executable, ancestry, writer, schema_fields
    )
    indexes = writer_indexes(writer)
    categories = factory_field_categories(writer)
    segments = [
        segment_matrix(
            segment,
            ancestry,
            writer,
            evidence,
            catalogs,
            indexes,
            categories,
        )
        for segment in selected_segments(ancestry)
    ]
    diffs = build_diffs(segments)
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "source_contracts": {
            "ancestry": {
                "path": ANCESTRY.CONTRACT_PATH.as_posix(),
                "contract_version": ancestry["contract_version"],
                "raw_sha256": ANCESTRY_RAW_SHA256,
            },
            "writer": {
                "path": WRITER.CONTRACT_PATH.as_posix(),
                "contract_version": writer["contract_version"],
                "raw_sha256": WRITER_RAW_SHA256,
            },
        },
        "derivation_toolchain": copy.deepcopy(writer["toolchain"]),
        "population_taxonomy": {
            "allowed_classifications": [
                "required_nonempty",
                "conditional",
                "required_absent",
            ],
            "required_nonempty_certified_entities": [],
            "conditional_entities": sorted(set(ANCESTRY.ENTITIES) - REQUIRED_ABSENT),
            "required_absent_entities": sorted(REQUIRED_ABSENT),
            "runtime_population_certified": False,
        },
        "segments": segments,
        "segment_diffs": diffs,
        "execution_model_contract": execution_model_contract(segments),
        "truth_boundary": {
            **{field: True for field in TRUE_FLAGS},
            **{field: False for field in FALSE_FLAGS},
        },
    }


TOP_LEVEL_KEYS = {
    "format_version",
    "contract_version",
    "source_contracts",
    "derivation_toolchain",
    "population_taxonomy",
    "segments",
    "segment_diffs",
    "execution_model_contract",
    "truth_boundary",
}


def validate_internal_contract(
    contract: object,
    ancestry: dict[str, object] | None = None,
    writer: dict[str, object] | None = None,
    root: Path = REPOSITORY,
) -> dict[str, object]:
    root = root.resolve()
    ancestry = ancestry or ANCESTRY.verify(root)
    writer = writer or WRITER.validate_internal_contract(
        ANCESTRY.load_json(root / WRITER.CONTRACT_PATH), ancestry, root
    )
    contract = ANCESTRY.exact_keys(contract, TOP_LEVEL_KEYS, "segment writer matrix")
    require(contract["format_version"] == 1, "segment matrix format version drift")
    require(contract["contract_version"] == CONTRACT_VERSION, "segment matrix version drift")
    require(
        contract["source_contracts"]
        == {
            "ancestry": {
                "path": ANCESTRY.CONTRACT_PATH.as_posix(),
                "contract_version": ancestry["contract_version"],
                "raw_sha256": ANCESTRY_RAW_SHA256,
            },
            "writer": {
                "path": WRITER.CONTRACT_PATH.as_posix(),
                "contract_version": writer["contract_version"],
                "raw_sha256": WRITER_RAW_SHA256,
            },
        },
        "segment matrix source contract binding drift",
    )
    require(
        sha256_bytes((root / ANCESTRY.CONTRACT_PATH).read_bytes())
        == ANCESTRY_RAW_SHA256,
        "segment matrix ancestry raw-byte binding drift",
    )
    require(
        sha256_bytes((root / WRITER.CONTRACT_PATH).read_bytes()) == WRITER_RAW_SHA256,
        "segment matrix writer raw-byte binding drift",
    )
    require(
        contract["derivation_toolchain"] == writer["toolchain"],
        "segment matrix WAT toolchain binding drift",
    )
    taxonomy = contract["population_taxonomy"]
    require(
        taxonomy["required_nonempty_certified_entities"] == []
        and taxonomy["required_absent_entities"] == sorted(REQUIRED_ABSENT)
        and taxonomy["conditional_entities"]
        == sorted(set(ANCESTRY.ENTITIES) - REQUIRED_ABSENT)
        and taxonomy["runtime_population_certified"] is False,
        "segment matrix population taxonomy overclaim or drift",
    )
    segments = contract["segments"]
    require(isinstance(segments, list) and len(segments) == 8, "segment matrix count drift")
    expected_anchors = selected_segments(ancestry)
    expected_by_deployment = {item["deployment"]: item for item in expected_anchors}
    source_by_deployment = {
        item["deployment"]: item for item in writer["segment_writer_contracts"]
    }
    indexes = writer_indexes(writer)
    require(
        [item["deployment"] for item in segments]
        == [item["deployment"] for item in expected_anchors],
        "segment matrix missing, repeated, or reordered segment",
    )
    total_handlers = 0
    total_entities = 0
    total_fields = 0
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    for segment in segments:
        anchor = expected_by_deployment[segment["deployment"]]
        require(
            segment["segment_id"]
            == f"{anchor['network']}:{anchor['deployment']}"
            and segment["network"] == anchor["network"]
            and segment["start_block_inclusive"] == anchor["start_block_inclusive"]
            and segment["end_block_inclusive"] == anchor["end_block_inclusive"]
            and segment["graft"] == anchor["graft"]
            and segment["manifest_features"] == anchor["manifest"]["features"],
            "segment matrix ancestry identity or range drift",
        )
        bindings = segment["artifact_bindings"]
        require(
            segment["artifact_bindings_sha256"] == canonical_sha256(bindings),
            "segment matrix artifact binding hash drift",
        )
        require(
            bindings["manifest"] == artifact_binding(artifacts[anchor["manifest_cid"]])
            and bindings["schema"]
            == artifact_binding(artifacts[anchor["manifest"]["schema_cid"]]),
            "segment matrix manifest or schema is not bound to ancestry",
        )
        require(
            len(bindings["components"]) == 3
            and [item["name"] for item in bindings["components"]]
            == list(COMPONENT_ORDER),
            "segment matrix component binding closure drift",
        )
        expected_handler_order: list[tuple[str, dict[str, object], str]] = []
        for bound_component in bindings["components"]:
            source_component = component_record(anchor, bound_component["name"])
            mapping_cid = source_component["mapping"]["wasm_cid"]
            analysis = indexes["analysis"][mapping_cid]
            require(
                bound_component["mapping_artifact"]
                == artifact_binding(artifacts[mapping_cid]),
                "segment matrix mapping artifact is unbound",
            )
            require(
                bound_component["abi_artifacts"]
                == [
                    {
                        "name": item["name"],
                        "artifact": artifact_binding(artifacts[item["cid"]]),
                    }
                    for item in source_component["mapping"]["abis"]
                ],
                "segment matrix ABI artifact is unbound",
            )
            require(
                bound_component["component_type"] == source_component["component_type"]
                and bound_component["kind"] == source_component["kind"]
                and bound_component["source"] == source_component["source"]
                and bound_component["mapping_api_version"]
                == source_component["mapping"]["api_version"]
                and bound_component["mapping_kind"]
                == source_component["mapping"]["kind"]
                and bound_component["mapping_language"]
                == source_component["mapping"]["language"]
                and bound_component["declared_entities"]
                == source_component["mapping"]["declared_entities"]
                and bound_component["mapping_wat_sha256"] == analysis["wat_sha256"]
                and bound_component["mapping_analysis_sha256"]
                == canonical_sha256(analysis),
                "segment matrix component or WAT analysis binding drift",
            )
            manifest_handlers = source_component["mapping"]["handlers"]
            require(
                len(bound_component["handlers_in_manifest_order"])
                == len(manifest_handlers),
                "segment matrix component handler binding count drift",
            )
            for bound_handler, manifest_handler in zip(
                bound_component["handlers_in_manifest_order"],
                manifest_handlers,
                strict=True,
            ):
                handler = manifest_handler["handler"]
                require(
                    bound_handler
                    == {
                        "event": manifest_handler["event"],
                        "handler": handler,
                        "numeric_export_function_index": analysis[
                            "registered_handler_export_function_indices"
                        ][handler],
                        "exact_wat_export_target": analysis[
                            "registered_handler_export_targets"
                        ][handler],
                        "body_binding": analysis["registered_handlers"][handler],
                    },
                    "segment matrix handler body/export binding drift",
                )
                expected_handler_order.append(
                    (bound_component["name"], manifest_handler, mapping_cid)
                )
        handlers = segment["handlers"]
        entities = segment["entity_field_matrix"]
        require(len(handlers) == 10, "segment matrix handler closure drift")
        require(
            len(expected_handler_order) == len(handlers),
            "segment matrix manifest handler closure drift",
        )
        require(len(entities) == 20, "segment matrix entity closure drift")
        require(
            sum(len(item["fields"]) for item in entities) == 299,
            "segment matrix field closure drift",
        )
        total_handlers += len(handlers)
        total_entities += len(entities)
        total_fields += sum(len(item["fields"]) for item in entities)
        factory_cid = component_record(anchor, "Factory")["mapping"]["wasm_cid"]
        npm_cid = component_record(anchor, "NonfungiblePositionManager")["mapping"][
            "wasm_cid"
        ]
        pool_cid = component_record(anchor, "Pool")["mapping"]["wasm_cid"]
        factory = indexes["factory"][factory_cid]
        npm = indexes["npm"][npm_cid]
        pool = indexes["pool"][pool_cid]
        flash = indexes["flash"][pool_cid]
        require(
            segment["profile_bindings"]
            == profile_bindings(factory, npm, pool, flash),
            "segment matrix profile binding drift",
        )
        for handler, expected_handler in zip(
            handlers, expected_handler_order, strict=True
        ):
            component_name, manifest_handler, mapping_cid = expected_handler
            analysis = indexes["analysis"][mapping_cid]
            handler_name = manifest_handler["handler"]
            require(
                handler["handler_id"] == f"{component_name}.{handler_name}"
                and handler["component"] == component_name
                and handler["event"] == manifest_handler["event"]
                and handler["mapping_cid"] == mapping_cid
                and handler["body_binding"]
                == analysis["registered_handlers"][handler_name]
                and handler["numeric_export_function_index"]
                == analysis["registered_handler_export_function_indices"][
                    handler_name
                ]
                and handler["exact_wat_export_target"]
                == analysis["registered_handler_export_targets"][handler_name]
                and handler["reviewed_semantics"]
                == reviewed_handler_semantics(
                    component_name,
                    handler_name,
                    factory,
                    npm,
                    pool,
                    flash,
                ),
                "segment matrix handler identity or reviewed semantics drift",
            )
            require(
                handler["complete_field_output_semantics"] is False
                and handler["named_setter_candidates_are_complete_field_outputs"]
                is False
                and handler["reviewed_semantics"]["complete"] is False,
                "segment handler false semantic claim promoted",
            )
            require(
                handler["conservative_ethereum_call_reachability"][
                    "complete_conservative_call_graph_closure"
                ]
                is True
                and handler["conservative_ethereum_call_reachability"][
                    "actual_execution_or_call_value_semantics_proven"
                ]
                is False,
                "segment handler contract-call reachability overclaim or drift",
            )
        absence = []
        conditional = []
        for entity in entities:
            population = entity["population_contract"]
            require(
                population["required_nonempty"] is False
                and population["runtime_population_certified"] is False
                and entity["complete_field_writer_semantics"] is False,
                "segment entity population or field semantic overclaim",
            )
            require(
                all(field["complete_value_semantics"] is False for field in entity["fields"]),
                "segment field semantic overclaim",
            )
            if population["required_absent"]:
                absence.append(entity["entity"])
                require(
                    population["classification"] == "required_absent"
                    and population["static_writer_absence_certified"] is True
                    and not entity["conservative_writer_handlers"],
                    "segment required-absence contract drift",
                )
            else:
                conditional.append(entity["entity"])
                require(
                    population["classification"] == "conditional"
                    and population["conditional"] is True
                    and population["static_writer_presence_bound"] is True,
                    "segment conditional population contract drift",
                )
        require(sorted(absence) == sorted(REQUIRED_ABSENT), "segment absence inventory drift")
        require(
            sorted(conditional) == sorted(set(ANCESTRY.ENTITIES) - REQUIRED_ABSENT),
            "segment conditional population inventory drift",
        )
        source_contract = source_by_deployment[segment["deployment"]]
        require(
            segment["source_writer_segment_contract_sha256"]
            == canonical_sha256(source_contract)
            and segment["source_writer_semantic_contract_sha256"]
            == source_contract["semantic_contract_sha256"],
            "segment matrix is not bound to source writer semantics",
        )
        source_segment = indexes["segment"][segment["deployment"]]
        require(
            segment["calls"] == call_contract(factory, npm, pool, flash)
            and segment["exclusions"]
            == exclusion_contract(factory, npm, pool)
            and segment["ordering"]
            == ordering_contract(source_segment, handlers, factory, flash)
            and segment["quirks"]
            == quirk_contract(source_segment, factory, npm, pool)
            and segment[
                "deterministic_handler_error_policy_under_source_model"
            ]
            == source_segment[
                "deterministic_handler_error_policy_under_source_model"
            ],
            "segment matrix call, exclusion, ordering, or quirk source drift",
        )
        surface = semantic_surface(segment)
        provenance = provenance_surface(segment)
        require(
            segment["provenance_surface_sha256"] == canonical_sha256(provenance),
            "segment writer provenance surface hash drift",
        )
        require(
            segment["semantic_surface_sha256"] == canonical_sha256(surface),
            "segment semantic surface hash drift",
        )
        require(
            segment["matrix_sha256"]
            == canonical_sha256(
                {key: value for key, value in segment.items() if key != "matrix_sha256"}
            ),
            "segment matrix hash drift",
        )
        require(
            segment["target_runtime_identity_bound"] is False
            and segment["boundary_state_continuity_certified"] is False
            and segment["graph_oracle_evidence_bound"] is False
            and segment["execution_model"] == "undecided"
            and segment["backfill_allowed"] is False
            and segment["complete_field_writer_semantics"] is False,
            "segment matrix execution, oracle, or promotion overclaim",
        )
        require(
            segment["calls"]["complete_call_inventory_and_value_semantics"] is False
            and segment["exclusions"]["complete_exclusion_control_flow"] is False
            and segment["ordering"]["target_runtime_identity_bound"] is False
            and segment["ordering"]["complete_runtime_ordering_contract"] is False
            and segment["quirks"]["silent_normalization_allowed"] is False
            and segment["quirks"]["all_profile_axes_machine_proven"] is False,
            "segment call, exclusion, ordering, or quirk overclaim",
        )
    require(
        (total_handlers, total_entities, total_fields) == (80, 160, 2392),
        "segment matrix aggregate closure drift",
    )
    diffs = contract["segment_diffs"]
    require(len(diffs) == 28, "segment matrix pairwise diff count drift")
    require(diffs == build_diffs(segments), "segment matrix pairwise diff content drift")
    require(
        sum(item["relation"] == "adjacent_graft" for item in diffs) == 6
        and all(
            item["boundary_state_compared"] is False
            and item["graph_oracle_compared"] is False
            for item in diffs
        ),
        "segment matrix boundary diff overclaim",
    )
    execution = contract["execution_model_contract"]
    require(
        len(execution["allowed_models"]) == 2
        and all(item["eligible"] is False for item in execution["allowed_models"])
        and len(execution["segment_selections"]) == 8
        and all(
            item["selected_model"] == "undecided"
            and item["selection_certified"] is False
            and item["backfill_allowed"] is False
            and item["blockers"]
            for item in execution["segment_selections"]
        )
        and execution["all_segments_decided"] is False,
        "segment execution model was falsely selected or promoted",
    )
    truth = ANCESTRY.exact_keys(
        contract["truth_boundary"],
        set(TRUE_FLAGS) | set(FALSE_FLAGS),
        "segment matrix truth boundary",
    )
    for field in TRUE_FLAGS:
        require(truth[field] is True, f"segment matrix proved evidence flag drift: {field}")
    for field in FALSE_FLAGS:
        require(truth[field] is False, f"segment matrix false promotion claim: {field}")
    return contract


def verify(
    root: Path,
    contract_path: Path | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, object]:
    root = root.resolve()
    path = contract_path or root / CONTRACT_PATH
    ancestry = ANCESTRY.verify(root)
    writer = WRITER.validate_internal_contract(
        ANCESTRY.load_json(root / WRITER.CONTRACT_PATH), ancestry, root
    )
    actual = validate_internal_contract(
        ANCESTRY.load_json(path), ancestry, writer, root
    )
    expected = build_contract(root, wasm2wat)
    require(
        actual == expected,
        "segment writer matrix content drift from recomputed retained WAT evidence",
    )
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write-contract", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.write_contract:
            contract = build_contract(root, args.wasm2wat)
            output = args.contract or root / CONTRACT_PATH
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render(contract), encoding="utf-8")
            print(f"wrote {output}")
        else:
            contract = verify(root, args.contract, args.wasm2wat)
            print(
                "verified Uniswap V3 segment writer matrix: "
                f"{len(contract['segments'])} segments, "
                f"{sum(len(item['handlers']) for item in contract['segments'])} handlers, "
                f"{len(contract['segment_diffs'])} pairwise diffs"
            )
        return 0
    except (
        OSError,
        VerificationError,
        WRITER.VerificationError,
        ANCESTRY.VerificationError,
    ) as error:
        print(f"segment writer matrix verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
