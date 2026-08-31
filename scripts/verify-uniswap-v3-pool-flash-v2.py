#!/usr/bin/env python3
"""Build or verify the complete path-qualified Pool Flash v2 effect matrix."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/pool-flash/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-flash/v2"
HANDLER_ID = "Pool.handleFlash"
HANDLER_EXPORT = "handleFlash"

IMPLEMENTATION_BASE_COMMIT = "42c6d01f2e719993e41fca9db51be55d33da734c"
IMPLEMENTATION_BASE_TREE = "ba8531df0e102ba71fd30b4df2af2977355dabf3"

FLASH_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-flash.py"
FLASH_VERIFIER_SHA256 = "1ffc7b8d9b6e96b320c7e8323693ce92da5d7f3dc7a0f871b02d2b7855abc81e"
FLASH_CONTRACT_PATH = Path("uniswap-v3/pool-flash/v1/contract.json")
FLASH_CONTRACT_SHA256 = "e90a292497f0771128a3e4859c8950b3496cbee9dcfd431334d19fe44926f696"
FLASH_CONTRACT_CANONICAL_SHA256 = "272caec6c59ff6adcf645a99dad5ac9e950079f88b6bdff4047f4e1f0da6af8f"
FLASH_CONTRACT_VERSION = "uniswap-v3-pool-flash-semantics/v1"

FIELD_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
FIELD_VERIFIER_SHA256 = "e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec"
FIELD_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
FIELD_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
FIELD_CONTRACT_CANONICAL_SHA256 = "28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3"
FIELD_CONTRACT_VERSION = "uniswap-v3-segment-field-semantics/v2"

SELECTED_FIELDS = ("feeGrowthGlobal0X128", "feeGrowthGlobal1X128")
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

CATEGORY_SELECTED = "selected_pool_setter_before_same_pool_save"
CATEGORY_OTHER_POOL = "other_stored_pool_field_without_reachable_schema_setter_before_same_pool_save"
CATEGORY_DERIVED_POOL = "derived_pool_field_without_direct_graph_store_transition"
CATEGORY_OUTSIDE = "field_outside_pool_only_graph_store_closure"

TRUE_FLAGS = (
    "exact_pool_flash_v1_recomputed",
    "exact_299_field_catalog_recomputed_directly",
    "all_transitive_pool_flash_v1_inputs_digest_bound",
    "all_eight_pool_flash_modules_exactly_bound",
    "event_address_pool_load_and_contract_bind_machine_bound",
    "fee0_call_decode_before_fee1_machine_bound",
    "both_setters_after_both_successful_decodes_machine_bound",
    "same_loaded_pool_reaches_sole_save_machine_bound",
    "nontry_null_branches_trap_before_setters_and_save_machine_bound",
    "pool_only_graph_store_closure_machine_bound",
    "all_eight_segments_have_299_path_qualified_field_outcomes",
    "all_sixteen_selected_fee_growth_setter_before_save_outcomes_present",
    "all_216_other_stored_pool_no_other_setter_outcomes_present",
    "all_56_derived_pool_no_direct_store_outcomes_present",
    "all_2104_outside_pool_store_closure_outcomes_present",
    "all_96_flash_required_absent_outcomes_present",
    "all_twenty_eight_recursive_segment_diffs_present",
    "path_qualified_static_flash_schema_api_matrix_complete",
)

FALSE_FLAGS = (
    "pool_flash_semantics_complete",
    "host_call_value_semantics_complete",
    "host_call_block_pointer_semantics_complete",
    "host_call_error_semantics_complete",
    "imported_host_semantics_complete",
    "numeric_semantics_complete",
    "general_heap_alias_safety_complete",
    "graph_store_host_semantics_complete",
    "graph_store_persistence_complete",
    "graph_store_persistence_proven",
    "graph_handler_rollback_proven",
    "post_fatal_execution_modeled",
    "complete_pool_entity_history",
    "complete_flash_entity_history",
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


FLASH = load_module("uniswap_v3_pool_flash_v1_for_v2", FLASH_VERIFIER_PATH, FLASH_VERIFIER_SHA256)
FIELD = load_module(
    "uniswap_v3_segment_field_semantics_v2_for_pool_flash_v2",
    FIELD_VERIFIER_PATH,
    FIELD_VERIFIER_SHA256,
)
WRITER = FLASH.WRITER
json_diff_paths = FLASH.INITIALIZE.json_diff_paths

UPSTREAM_ERRORS = tuple(
    dict.fromkeys(
        (
            FLASH.VerificationError,
            FLASH.SWAP.VerificationError,
            FLASH.MINT.VerificationError,
            FLASH.INITIALIZE.VerificationError,
            FLASH.POOL_RUNTIME.VerificationError,
            FLASH.V2.VerificationError,
            FLASH.WRITER.VerificationError,
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
        require(
            canonical_sha256(value) == canonical_digest,
            f"canonical source digest drift: {relative}",
        )
    return value


def validate_field_catalog(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    require(isinstance(catalog, list) and len(catalog) == 299, "schema field catalog count drift")
    pairs = [(item.get("entity"), item.get("field")) for item in catalog]
    require(len(set(pairs)) == 299, "schema field catalog entity/field uniqueness drift")
    entity_counts = Counter(item.get("entity") for item in catalog)
    require(dict(sorted(entity_counts.items())) == EXPECTED_ENTITY_COUNTS, "schema entity counts drift")
    storage_counts = Counter(item.get("storage") for item in catalog)
    require(storage_counts == Counter({"stored": 286, "derived": 13}), "schema storage counts drift")

    pool = [item for item in catalog if item["entity"] == "Pool"]
    pool_stored = [item for item in pool if item["storage"] == "stored"]
    pool_derived = [item for item in pool if item["storage"] == "derived"]
    require((len(pool), len(pool_stored), len(pool_derived)) == (36, 29, 7), "Pool catalog split drift")
    require(
        {item["field"] for item in pool_stored}.issuperset(SELECTED_FIELDS),
        "selected Pool fields missing from stored catalog",
    )
    require(
        all(item.get("directives", "").startswith("@derivedFrom") for item in pool_derived),
        "Pool derived-field directive drift",
    )

    flash = [item for item in catalog if item["entity"] == "Flash"]
    require(len(flash) == 12 and all(item["storage"] == "stored" for item in flash), "Flash catalog split drift")
    require(
        all(
            item.get("population_classification") == "required_absent"
            and item.get("semantic_status") == "certified_required_absent"
            and item.get("upstream_writer_evidence_statuses") == ["required_absent_static_certified"]
            for item in flash
        ),
        "Flash required-absence catalog drift",
    )
    return {
        "field_count": len(catalog),
        "entity_count": len(entity_counts),
        "entity_field_counts": dict(sorted(entity_counts.items())),
        "stored_field_count": storage_counts["stored"],
        "derived_field_count": storage_counts["derived"],
        "pool_field_count": len(pool),
        "pool_stored_field_count": len(pool_stored),
        "pool_derived_field_count": len(pool_derived),
        "flash_required_absent_field_count": len(flash),
        "field_catalog_sha256": canonical_sha256(catalog),
    }


def _validate_and_project_v1_proof(proof: dict[str, Any]) -> dict[str, Any]:
    cid = proof["mapping_cid"]
    generation = proof["control_generation"]
    require(generation in ("legacy", "modern"), f"{cid} control generation drift")
    boundary = proof["control_and_entity_boundary"]
    require(
        boundary["event_address_to_pool_load_machine_proven"] is True
        and boundary["event_address_to_contract_bind_machine_proven"] is True
        and boundary["pool_entity_target"] == "Pool",
        f"{cid} event-address Pool boundary drift",
    )

    flows = proof["selected_field_flows"]
    require(flows["call_order"] == list(SELECTED_FIELDS), f"{cid} fee call order drift")
    require(
        flows["setter_order"] == [f"Pool.{field}" for field in SELECTED_FIELDS]
        and flows["ordered_call_decode_setter_flow_machine_proven"] is True
        and flows["same_contract_receiver_for_both_calls_machine_proven"] is True
        and flows["same_path_to_save_machine_proven"] is True,
        f"{cid} selected flow boundary drift",
    )
    fee0 = flows["fields"][SELECTED_FIELDS[0]]
    fee1 = flows["fields"][SELECTED_FIELDS[1]]
    require(
        fee0["receiver_key_value_flow_machine_proven"] is True
        and fee1["receiver_key_value_flow_machine_proven"] is True,
        f"{cid} selected receiver/key/value drift",
    )

    save = proof["save_and_effect_closure"]
    save_line = save["pool_save_relative_wat_line"]
    require(
        save["direct_pool_save_count"] == 1
        and save["both_setters_precede_pool_save_machine_proven"] is True
        and save["same_loaded_pool_receiver_for_both_setters_and_save_machine_proven"] is True
        and save["same_path_call_decode_setter_save_machine_proven"] is True,
        f"{cid} same-Pool save boundary drift",
    )
    call0 = fee0["call_relative_wat_line"]
    call1 = fee1["call_relative_wat_line"]
    setter0 = fee0["setter_relative_wat_line"]
    setter1 = fee1["setter_relative_wat_line"]
    if generation == "modern":
        decode0 = fee0["decode_relative_wat_line"]
        decode1 = fee1["decode_relative_wat_line"]
        require(
            call0 < decode0 < call1 < decode1 < setter0 < setter1 < save_line,
            f"{cid} inline normal-success order drift",
        )
        decode_boundary = {
            "model": "inline",
            "fee0_call_relative_wat_line": call0,
            "fee0_decode_relative_wat_line": decode0,
            "fee1_call_relative_wat_line": call1,
            "fee1_decode_relative_wat_line": decode1,
        }
    else:
        for field, selected in ((SELECTED_FIELDS[0], fee0), (SELECTED_FIELDS[1], fee1)):
            getter = selected["getter"]
            require(
                getter["method"] == field
                and getter["decode_index"] == 0
                and getter["receiver_to_call_to_result_decode_machine_proven"] is True,
                f"{cid} {field} wrapper call/decode drift",
            )
        require(call0 < call1 < setter0 < setter1 < save_line, f"{cid} wrapper normal-success order drift")
        decode_boundary = {
            "model": "synchronous_wrapper_return",
            "fee0_getter_call_and_decode_completion_relative_wat_line": call0,
            "fee1_getter_call_and_decode_completion_relative_wat_line": call1,
            "both_getter_returns_require_result_zero_bigint_decode": True,
        }

    call_failure = proof["contract_call_failure_boundary"]
    require(
        call_failure["try_call"] is False
        and call_failure["nontry_null_path_closed_trap_machine_proven"] is True
        and call_failure["null_result_check_relative_wat_line"]
        < call_failure["null_result_abort_relative_wat_line"]
        < call_failure["null_result_unreachable_relative_wat_line"],
        f"{cid} non-try null trap boundary drift",
    )
    require(
        call_failure["host_eth_call_semantics_rederived"] is False
        and call_failure["host_call_block_pointer_semantics_rederived"] is False
        and call_failure["host_call_error_classification_rederived"] is False,
        f"{cid} host call boundary overpromoted",
    )

    mutation = save["reachable_in_memory_mutation_inventory"]
    transitive = save["transitive_store_evidence"]
    require(
        mutation["reachable_typed_map_set_site_count"] == 2
        and mutation["selected_receiver_key_value_classified_typed_map_set_sites"] == 2
        and mutation["unclassified_typed_map_set_site_count"] == 0,
        f"{cid} schema setter closure drift",
    )
    require(
        save["reachable_store_set_targets"] == ["Pool"]
        and save["flash_entity_store_target_reachable"] is False
        and save["no_flash_entity_row_machine_bound"] is True
        and transitive["reachable_store_set_site_count"] == 1
        and transitive["reachable_store_set_targets"] == ["Pool"]
        and transitive["dynamic_reachable_store_set_target_count"] == 0
        and transitive["unmodelled_store_mutation_host_import_count"] == 0,
        f"{cid} Pool-only store closure drift",
    )
    require(
        save["selected_persistence_proven"] is False
        and save["rollback_and_post_fatal_semantics_proven"] is False
        and save["no_later_selected_field_overwrites_proven"] is False,
        f"{cid} persistence/history boundary overpromoted",
    )
    require(
        proof["required_absent_flash_row"] is True
        and proof["complete_pool_flash_handler_semantics"] is False,
        f"{cid} Flash truth boundary drift",
    )

    return {
        "mapping_cid": cid,
        "profile_id": proof["profile_id"],
        "control_generation": generation,
        "retained_wasm": proof["retained_wasm"],
        "handler_binding": proof["handler_binding"],
        "pool_flash_v1_proof_sha256": canonical_sha256(proof),
        "normal_success_ordering": {
            "scope": "normal success only; every imported call and load must return sufficiently for the retained WAT path to continue",
            "event_address_pool_load_machine_bound": True,
            "event_address_contract_bind_machine_bound": True,
            "decode_boundary": decode_boundary,
            "fee0_before_fee1_machine_bound": True,
            "both_setters_after_both_successful_decodes_machine_bound": True,
            "fee0_setter_relative_wat_line": setter0,
            "fee1_setter_relative_wat_line": setter1,
            "same_loaded_pool_reaches_sole_save_machine_bound": True,
            "pool_save_relative_wat_line": save_line,
            "nontry_null_branches_trap_before_setters_and_save_machine_bound": True,
            "host_call_value_semantics_complete": False,
            "host_call_error_semantics_complete": False,
        },
        "schema_api_and_store_closure": {
            "reachable_schema_setter_site_count": 2,
            "selected_schema_setter_site_count": 2,
            "other_reachable_schema_setter_site_count": 0,
            "reachable_graph_store_set_site_count": 1,
            "reachable_graph_store_targets": ["Pool"],
            "reachable_dynamic_store_target_count": 0,
            "flash_entity_store_target_reachable": False,
            "required_absent_flash_row_machine_bound": True,
            "reachable_function_count": mutation["reachable_function_count"],
            "reachable_function_body_inventory_sha256": mutation[
                "reachable_function_body_inventory_sha256"
            ],
            "reachable_typed_map_set_site_inventory_sha256": mutation[
                "reachable_typed_map_set_site_inventory_sha256"
            ],
            "reachable_store_set_site_ids_sha256": transitive[
                "reachable_store_set_site_ids_sha256"
            ],
            "general_heap_alias_safety_complete": False,
            "graph_store_host_semantics_complete": False,
            "graph_store_persistence_proven": False,
        },
        "path_qualified_flash_schema_api_closure_complete": True,
        "complete_pool_flash_handler_semantics": False,
    }


def prove_complete_context(
    context: dict[str, Any],
    field_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_field_catalog(field_catalog)
    return _validate_and_project_v1_proof(FLASH.prove_pool_flash_wat_context(context))


def _field_outcome(record: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
    entity = record["entity"]
    field = record["field"]
    storage = record["storage"]
    selected = entity == "Pool" and field in SELECTED_FIELDS
    other_pool = entity == "Pool" and storage == "stored" and not selected
    derived_pool = entity == "Pool" and storage == "derived"
    outside = entity != "Pool"
    require(sum((selected, other_pool, derived_pool, outside)) == 1, f"field category drift: {entity}.{field}")
    category = (
        CATEGORY_SELECTED
        if selected
        else CATEGORY_OTHER_POOL
        if other_pool
        else CATEGORY_DERIVED_POOL
        if derived_pool
        else CATEGORY_OUTSIDE
    )
    flash_required_absent = entity == "Flash"
    if flash_required_absent:
        require(
            record["population_classification"] == "required_absent"
            and record["semantic_status"] == "certified_required_absent",
            f"Flash required-absence drift: {field}",
        )

    structural_source: dict[str, Any] | None = None
    if selected:
        structural_source = {
            "contract_method": field,
            "decode_index": 0,
            "decoded_kind": "BigInt structural wrapper kind",
            "selector": FLASH.SELECTED_FIELDS[field]["selector"],
            "host_return_value_semantics_complete": False,
        }

    return {
        "entity": entity,
        "field": field,
        "type": record["type"],
        "directives": record["directives"],
        "storage": storage,
        "schema_catalog_record_sha256": canonical_sha256(record),
        "path_qualified_category": category,
        "selected_fee_growth_setter_before_save": selected,
        "other_stored_pool_without_reachable_schema_setter_before_save": other_pool,
        "derived_pool_without_direct_graph_store_transition": derived_pool,
        "outside_pool_only_graph_store_closure": outside,
        "flash_required_absent": flash_required_absent,
        "schema_setter_reachable_for_field": selected,
        "selected_structural_value_flow": structural_source,
        "same_loaded_pool_reaches_sole_save_machine_bound": entity == "Pool",
        "no_reachable_schema_setter_for_field_before_same_pool_save_machine_bound": other_pool,
        "no_direct_graph_store_transition_machine_bound": derived_pool or outside,
        "pool_only_graph_store_target_excludes_entity": outside,
        "static_required_absence_machine_bound": flash_required_absent,
        "normal_success_path_qualified_static_outcome_complete": True,
        "field_value_semantics_complete": False,
        "field_value_unchanged_proven": False,
        "graph_store_host_semantics_complete": False,
        "graph_store_persistence_proven": False,
        "complete_entity_history": False,
        "complete_integrated_field_semantics": False,
        "mapping_proof_sha256": canonical_sha256(proof),
    }


def build_segments(
    flash_contract: dict[str, Any],
    field_catalog: list[dict[str, Any]],
    proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    results = []
    for parent in flash_contract["segments"]:
        cid = parent["semantic_surface"]["mapping_cid"]
        require(cid in proof_by_cid, f"{parent['segment_id']} missing mapping proof")
        proof = proof_by_cid[cid]
        require(
            parent["semantic_surface"]["profile_id"] == proof["profile_id"],
            f"{parent['segment_id']} profile binding drift",
        )
        outcomes = [_field_outcome(record, proof) for record in field_catalog]
        counts = Counter(item["path_qualified_category"] for item in outcomes)
        require(
            counts
            == Counter(
                {
                    CATEGORY_SELECTED: 2,
                    CATEGORY_OTHER_POOL: 27,
                    CATEGORY_DERIVED_POOL: 7,
                    CATEGORY_OUTSIDE: 263,
                }
            ),
            f"{parent['segment_id']} effect category denominator drift",
        )
        require(sum(item["flash_required_absent"] for item in outcomes) == 12, f"{parent['segment_id']} Flash absence denominator drift")
        semantic = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "control_generation": proof["control_generation"],
            "normal_success_ordering": proof["normal_success_ordering"],
            "schema_api_and_store_closure": proof["schema_api_and_store_closure"],
            "field_outcome_summary": {
                "field_outcome_count": len(outcomes),
                "selected_fee_growth_setter_before_save_count": counts[CATEGORY_SELECTED],
                "other_stored_pool_without_reachable_schema_setter_before_save_count": counts[
                    CATEGORY_OTHER_POOL
                ],
                "derived_pool_without_direct_graph_store_transition_count": counts[
                    CATEGORY_DERIVED_POOL
                ],
                "outside_pool_only_graph_store_closure_count": counts[CATEGORY_OUTSIDE],
                "flash_required_absent_count": sum(item["flash_required_absent"] for item in outcomes),
                "category_counts_sha256": canonical_sha256(dict(sorted(counts.items()))),
            },
            "field_outcomes": outcomes,
            "path_qualified_static_flash_schema_api_matrix_complete": True,
            "pool_flash_semantics_complete": False,
            "complete_entity_history": False,
            "graph_store_persistence_proven": False,
        }
        provenance = {
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "pool_flash_v1_segment_semantic_sha256": parent["semantic_surface_sha256"],
            "pool_flash_v1_segment_provenance_sha256": parent["provenance_surface_sha256"],
            "pool_flash_v1_complete_proof_sha256": proof["pool_flash_v1_proof_sha256"],
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

    require(len(results) == 8, "Pool Flash v2 segment count drift")
    require(sum(len(item["semantic_surface"]["field_outcomes"]) for item in results) == 2392, "Pool Flash v2 field outcome total drift")
    require(sum(item["semantic_surface"]["field_outcome_summary"]["selected_fee_growth_setter_before_save_count"] for item in results) == 16, "selected outcome total drift")
    require(sum(item["semantic_surface"]["field_outcome_summary"]["other_stored_pool_without_reachable_schema_setter_before_save_count"] for item in results) == 216, "other stored Pool outcome total drift")
    require(sum(item["semantic_surface"]["field_outcome_summary"]["derived_pool_without_direct_graph_store_transition_count"] for item in results) == 56, "derived Pool outcome total drift")
    require(sum(item["semantic_surface"]["field_outcome_summary"]["outside_pool_only_graph_store_closure_count"] for item in results) == 2104, "outside closure outcome total drift")
    require(sum(item["semantic_surface"]["field_outcome_summary"]["flash_required_absent_count"] for item in results) == 96, "Flash required-absence outcome total drift")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
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
    require(len(results) == 28, "Pool Flash v2 pairwise diff count drift")
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
    require(raw_sha256(FLASH_VERIFIER_PATH) == FLASH_VERIFIER_SHA256, "Pool Flash v1 verifier digest drift")
    require(raw_sha256(FIELD_VERIFIER_PATH) == FIELD_VERIFIER_SHA256, "field-semantics v2 verifier digest drift")
    direct_flash = _bind(root, FLASH_CONTRACT_PATH, FLASH_CONTRACT_SHA256, FLASH_CONTRACT_CANONICAL_SHA256)
    direct_fields = _bind(root, FIELD_CONTRACT_PATH, FIELD_CONTRACT_SHA256, FIELD_CONTRACT_CANONICAL_SHA256)
    require(direct_flash["contract_version"] == FLASH_CONTRACT_VERSION, "Pool Flash v1 version drift")
    require(direct_fields["contract_version"] == FIELD_CONTRACT_VERSION, "field-semantics v2 version drift")

    flash_sources = FLASH.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    recomputed_flash = FLASH.verify_contract(
        root,
        sources=flash_sources,
        recompute_wat=False,
    )
    require(canonical_bytes(direct_flash) == canonical_bytes(recomputed_flash), "direct Pool Flash v1 contract differs from recomputation")
    field_sources = FIELD.load_sources(
        root,
        recompute_wat=recompute_wat,
        wasm2wat=wasm2wat,
    )
    recomputed_fields = FIELD.verify_contract(
        root,
        sources=field_sources,
        recompute_wat=False,
    )
    require(canonical_bytes(direct_fields) == canonical_bytes(recomputed_fields), "direct field catalog contract differs from direct recomputation")
    require(canonical_bytes(recomputed_fields) == canonical_bytes(flash_sources["v2_contract"]), "direct field catalog recomputation differs from Pool Flash v1 dependency")
    catalog = direct_fields["field_catalog"]
    catalog_summary = validate_field_catalog(catalog)
    contexts = flash_sources["pool_wat_contexts"]
    require(recompute_wat and len(contexts) == 8, "eight recomputed Pool Flash WAT contexts required")
    proofs = sorted(
        (prove_complete_context(context, catalog) for context in contexts.values()),
        key=lambda item: item["profile_id"],
    )
    require(len(proofs) == 8 and sum(item["control_generation"] == "legacy" for item in proofs) == 6, "Pool Flash v2 proof population drift")
    return {
        "flash_sources": flash_sources,
        "flash_contract": recomputed_flash,
        "field_contract": direct_fields,
        "field_sources": field_sources,
        "field_catalog": catalog,
        "field_catalog_summary": catalog_summary,
        "contexts": contexts,
        "mapping_proofs": proofs,
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    summary = sources["field_catalog_summary"]
    proofs = sources["mapping_proofs"]
    segments = build_segments(sources["flash_contract"], sources["field_catalog"], proofs)
    diffs = build_segment_diffs(segments)
    flash_source_contracts_sha256 = canonical_sha256(sources["flash_contract"]["source_contracts"])
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "complete-path-qualified-static-pool-flash-schema-api-effect-matrix",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "mapping_count": 8,
            "handler": HANDLER_ID,
            "schema_field_count_per_segment": 299,
            "field_outcome_count": 2392,
            "selected_fee_growth_setter_before_save_outcome_count": 16,
            "other_stored_pool_without_reachable_schema_setter_before_save_outcome_count": 216,
            "derived_pool_without_direct_graph_store_transition_outcome_count": 56,
            "outside_pool_only_graph_store_closure_outcome_count": 2104,
            "flash_required_absent_outcome_count": 96,
            "pairwise_recursive_diff_count": 28,
            "legacy_profile_count": 6,
            "modern_profile_count": 2,
            "issue_acceptance_checkbox_completed": False,
            "claim": "complete normal-success-path-qualified static Pool.handleFlash schema-API effect matrix; only two selected setters and the same loaded Pool's sole save are structurally promoted, while host values, other field values, persistence, history, and readiness remain false",
        },
        "schema_catalog": summary,
        "source_contracts": {
            "pool_flash_v1_verifier": {
                "path": str(FLASH_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": FLASH_VERIFIER_SHA256,
            },
            "pool_flash_v1": {
                "path": str(FLASH_CONTRACT_PATH),
                "contract_version": FLASH_CONTRACT_VERSION,
                "raw_sha256": FLASH_CONTRACT_SHA256,
                "canonical_sha256": FLASH_CONTRACT_CANONICAL_SHA256,
                "transitive_source_contracts_sha256": flash_source_contracts_sha256,
                "recomputed_directly": True,
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
                "field_catalog_sha256": summary["field_catalog_sha256"],
                "recomputed_directly": True,
                "matches_pool_flash_v1_dependency": True,
            },
        },
        "authority_contract": {
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "implementation_base_tree": IMPLEMENTATION_BASE_TREE,
            "semantic_authority": "exact retained deployed Pool mapping WASM regenerated to WAT with checksum-pinned WABT 1.0.35",
            "schema_authority": "exact 299-field segment-field-semantics v2 catalog recomputed through the Pool Flash v1 authority chain",
            "normal_success_boundary": "event-address Pool load and contract bind; fee0 call/decode completes before fee1; both setters occur only after both successful decodes; the same loaded Pool reaches the sole save",
            "null_boundary": "the shared non-try SmartContract helper traps on either null result before control can reach either setter or the Pool save",
            "other_stored_pool_boundary": "the exact reachable schema setter closure has only the two selected fee-growth setters; the other 27 stored Pool fields are classified only as having no other reachable schema setter before the same-Pool save, with no field-value claim",
            "derived_boundary": "the seven Pool @derivedFrom fields have no direct Graph store transition in the Pool-only closure",
            "outside_boundary": "all 263 non-Pool fields are outside the sole Pool store target; the 12 Flash fields retain stronger required-absence evidence",
            "host_boundary": "host return values, error classification, block pointers, Graph store behavior, persistence, rollback, post-fatal behavior, numeric meaning, and arbitrary heap aliases are not rederived",
            "composition_boundary": "Pool Flash v1 and the field catalog are recomputed directly; Factory static v2 is not an input",
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
                "imported eth_call values, block pointers, error classes, numeric meaning, Graph store behavior, persistence, rollback, post-fatal behavior, and arbitrary aliases remain unproved",
                "the other stored Pool fields have no other reachable schema setter before save, but their field values are not characterized",
                "complete Pool, Flash, other-handler, and integrated entity histories remain false",
            ],
            "execution": [
                "scheduler, output, Store, package consumption, dynamic-data-source order, runtime population, and source-package identity remain unimplemented or unproved",
                "continuity, oracle, logical/physical/PoI parity, checkpoint authority, backfill, deployment, production, and readiness remain false",
                "no issue #37 or #38 checkbox is completed",
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
        require(path.is_file(), f"Pool Flash v2 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "Pool Flash v2 contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Pool Flash v2 contract differs from generated proof")
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
        "verified Uniswap V3 Pool Flash semantics v2: "
        f"{len(result['segments'])} segments, "
        f"{result['scope']['field_outcome_count']} field outcomes, "
        f"{len(result['segment_diffs'])} diffs; no issue checkbox completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
