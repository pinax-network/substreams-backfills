#!/usr/bin/env python3
"""Build or verify the bounded Uniswap V3 Factory Pool price-init certificate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/factory-pool-price-init/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-factory-pool-price-initialization/v1"
HANDLER_ID = "Factory.handlePoolCreated"
HANDLER_EXPORT = "handlePoolCreated"
SELECTED_FIELDS = ("token0Price", "token1Price")
DIRECT_FIELD_BASES = (("token0Price", 351), ("token1Price", 356))

PARENT_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-factory-pool-bigint-init.py"
PARENT_VERIFIER_SHA256 = "0dca669d82194aedd29254fe7b8d2d79d88bb5d10d43ec93c9953b7bbc3bb9ee"
PARENT_CONTRACT_PATH = Path("uniswap-v3/factory-pool-bigint-init/v1/contract.json")
PARENT_CONTRACT_SHA256 = "75ee8f9891e7f7835108d634d1fca2a74aedecd7e2a2ed1581c63fd8805bea25"
PARENT_CONTRACT_CANONICAL_SHA256 = "2b916bf3df7212604507cc5075f03950fc66b0d75b62924ad32a1923521e5dc6"
PARENT_CONTRACT_VERSION = "uniswap-v3-factory-pool-bigint-initialization/v1"

CANONICAL_BASE = {
    "canonical_merge_commit": "19bbc277006cccaf960647dc0bb3c7344688a07f",
    "canonical_merge_tree": "0afaf69b8446c84b5542453addb0810852387090",
    "canonical_merge_parent": "982dd6f049af265cfed4c7b8edce1a90c936f319",
    "audited_candidate_commit": "0b29c6e53ef42ed98e3413a49ad79a9dcefdbb97",
    "audited_candidate_tree": "0afaf69b8446c84b5542453addb0810852387090",
    "exact_head_ci_run": 33342202456,
    "exact_head_ci_jobs": 6,
    "exact_head_ci_steps": 163,
}


class VerificationError(RuntimeError):
    """Raised when retained evidence does not reproduce exactly."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise VerificationError(f"invalid JSON {path}: {error}") from error


def load_module(name: str, path: Path, digest: str) -> Any:
    require(path.is_file(), f"missing verifier: {path}")
    require(raw_sha256(path) == digest, f"verifier digest drift: {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARENT = load_module(
    "uniswap_v3_factory_pool_bigint_for_price_init",
    PARENT_VERIFIER_PATH,
    PARENT_VERIFIER_SHA256,
)
WRITER = PARENT.WRITER
V2 = PARENT.V2
LEGACY_MAP_SET = PARENT.LEGACY_MAP_SET


def normalized(line: str) -> str:
    return PARENT.normalized(line)


def call_name(line: str) -> str | None:
    return PARENT.call_name(line)


def function_sha256(function: Any) -> str:
    return PARENT.function_sha256(function)


def function_by_suffix(context: dict[str, Any], suffix: str) -> Any:
    return PARENT.function_by_suffix(context, suffix)


def slice_sha256(function: Any, start: int, end: int) -> str:
    return PARENT.slice_sha256(function, start, end)


def decoded_constant(line: str, memory: bytearray) -> str | None:
    return PARENT.decoded_constant(line, memory)


def decoded_normalized_sha256(
    lines: list[str] | tuple[str, ...], memory: bytearray
) -> str:
    return PARENT.decoded_normalized_sha256(lines, memory)


EXPECTED: dict[str, dict[str, Any]] = {
    "legacy-base-root": {
        "cid": "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj",
        "key_pointers": [4080, 4112],
        "direct_concat_raw_sha256": "6dbe6e414441fa6df4a02cd8137f068485556ad23aba29ca3ae574441707e8ca",
        "through_save_raw_sha256": "73efa76ca1f108771e060723b144c1af15f0b0cc5f343238e2543bdfeb93ed8f",
    },
    "legacy-mainnet-qmrv": {
        "cid": "QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV",
        "key_pointers": [6472, 6504],
        "direct_concat_raw_sha256": "1d2b6bfe9129010ca7f17fe18ed0b9e435271a8c5a2028296b97f18bb290727c",
        "through_save_raw_sha256": "c8e9d98707c9eb79a50ae2722afc0783b480859c4aece956917998ca31c2b8d8",
    },
    "legacy-mainnet-root": {
        "cid": "QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr",
        "key_pointers": [6384, 6416],
        "direct_concat_raw_sha256": "447779da95797e5cf903d7ebb2602da754c328a84e76921d3954795f3b490ade",
        "through_save_raw_sha256": "e3adfcd5063ec2026464904c74050dd3a07013a09bb3109dfb13ababeb309ac8",
    },
    "legacy-mainnet-stable": {
        "cid": "QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL",
        "key_pointers": [6512, 6544],
        "direct_concat_raw_sha256": "ea0ba12575f7acaaf60dfc0381a563fd003b53e9b3ad0ffe8872f7b8e5aa2681",
        "through_save_raw_sha256": "65ba47a1886cf207794dc86a23797b1ef1c081f4760779fe98adacba2ab54a80",
    },
}

DIRECT_CONCAT_DECODED_NORMALIZED_SHA256 = "3f22dabad50f6fa72e41d3e4711e6c1610aec087b4b47feeadf5efb4ed8cb102"
THROUGH_SAVE_DECODED_NORMALIZED_SHA256 = "6a42100ae5ccc46d0a656b19743ed0b4f9b5cfad599fb29eea0207d1c166e898"
G4_ORIGIN_RAW_SHA256 = "031932bfc1fa2e80e619f4c0ef405027f0588a82335ab209e2b9972d0204694a"
G4_ORIGIN_DECODED_NORMALIZED_SHA256 = "d58f98aeb90ccdb2975b0d747dfbe9953e74b97f847cdd812d49ee9143ca9ad0"
VALUE_FROM_BIGDECIMAL_SHA256 = "c22dc4c0902b6c3aa5b53bf549c79ccb3b8b5175add4de32117b556c19e54741"
EXPANDED_MAP_WRITE_INVOCATIONS_SHA256 = "e1786369ca1dccbf1328ec9f0534c5f2059851dbc65bc8a2c2a940f85be6b3a9"
NEW_SELECTED_EXPANDED_INDEX_SHA256 = "142249e361d4dd5f0506ac6c81132e7f8afcc645ed18a8a3b62a2b260440104b"
CUMULATIVE_SELECTED_EXPANDED_INDEX_SHA256 = "57d91787e8feb728d7f2e59bdbb366233d649bea59a055a8c7a27c0dd6acb1cf"

TRUE_FLAGS = (
    "factory_pool_bigint_initialization_parent_recomputed_and_pinned",
    "four_exact_legacy_factory_artifacts_and_handlers_inherited",
    "four_big_decimal_from_string_to_g4_pointer_flows_bound",
    "eight_direct_price_setter_call_operand_flows_bound",
    "four_value_from_big_decimal_kind_payload_wrappers_bound",
    "four_same_receiver_price_call_through_pool_save_flows_bound",
    "six_legacy_segment_projections_present",
    "twelve_legacy_segment_field_records_present",
    "two_modern_parent_segment_projections_present",
    "sixteen_total_initialization_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "eight_fully_selected_direct_static_sites_of_forty_four",
    "thirty_six_unclassified_static_sites_retained",
    "nine_selected_expanded_invocations_of_seventy_eight",
    "sixty_nine_expanded_invocations_retained_residual",
    "shared_tx_count_static_site_retained_as_residual",
    "nine_of_sixty_legacy_factory_field_call_flow_capsules_present",
    "cumulative_field_ledger_remains_36_selected_230_residual",
    "cumulative_factory_closure_remains_14_of_18",
)

ADDITIONAL_FALSE_FLAGS = (
    "big_decimal_from_string_numeric_semantics_rederived",
    "g4_pointer_is_proven_numeric_zero",
    "legacy_selected_price_field_mutation_proven",
    "all_nine_legacy_factory_field_contracts_complete",
    "complete_price_history",
)
FALSE_FLAGS = tuple(dict.fromkeys((*PARENT.FALSE_FLAGS, *ADDITIONAL_FALSE_FLAGS)))


def prove_g4_pointer_origin(
    context: dict[str, Any], parent_proof: dict[str, Any]
) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    constants = context["functions"].get("start:src/utils/constants")
    require(constants is not None, f"{profile} constants initializer missing")
    require((constants.start_line, len(constants.lines)) == (492, 25), f"{profile} constants binding drift")
    require(
        [normalized(line) for line in constants.lines[11:14]]
        == [
            "i32.const 312",
            "call $~lib/@graphprotocol/graph-ts/index/bigDecimal.fromString",
            "global.set $g4",
        ],
        f"{profile} string-to-bigDecimal-to-g4 pointer flow drift",
    )
    require(decoded_constant(constants.lines[11], context["memory"]) == "0", f"{profile} g4 source string drift")
    require(slice_sha256(constants, 11, 14) == G4_ORIGIN_RAW_SHA256, f"{profile} g4 origin raw authority drift")
    require(
        decoded_normalized_sha256(constants.lines[11:14], context["memory"])
        == G4_ORIGIN_DECODED_NORMALIZED_SHA256,
        f"{profile} g4 origin normalized authority drift",
    )
    module_imports = [
        line.strip()
        for line in context["wat_text"].splitlines()
        if line.strip().startswith("(import ")
    ]
    expected_import = '(import "index" "bigDecimal.fromString" (func $~lib/@graphprotocol/graph-ts/index/bigDecimal.fromString (type $t1)))'
    require(module_imports.count(expected_import) == 1, f"{profile} bigDecimal.fromString import drift")
    parent_native = parent_proof["native_start_and_g2"]
    parent_writers = parent_native["complete_global_set_inventory"]
    writers: dict[str, list[list[Any]]] = {name: [] for name in parent_writers}
    for function_name, function in context["functions"].items():
        for index, raw_line in enumerate(function.lines):
            match = re.fullmatch(r"global\.set (\$g\d+)\)?", normalized(raw_line))
            if match is not None:
                require(match.group(1) in writers, f"{profile} unexpected global writer target")
                writers[match.group(1)].append([function_name, index])
    require(writers == parent_writers, f"{profile} complete global writer inventory drift")
    require(writers["$g4"] == [["start:src/utils/constants", 13]], f"{profile} g4 writer inventory drift")
    return {
        "constants_function": constants.name,
        "constants_wat_start_line": constants.start_line,
        "source_relative_wat_lines": [11, 13],
        "source_absolute_wat_lines": [constants.start_line + 11, constants.start_line + 13],
        "decoded_source_string": "0",
        "big_decimal_from_string_import": expected_import,
        "destination_global": "$g4",
        "raw_slice_sha256": G4_ORIGIN_RAW_SHA256,
        "decoded_string_normalized_sha256": G4_ORIGIN_DECODED_NORMALIZED_SHA256,
        "complete_global_set_inventory_sha256": parent_native["complete_global_set_inventory_sha256"],
        "g4_unique_internal_writer_machine_proven": True,
        "pointer_returned_by_imported_call_stored_in_g4_machine_proven": True,
        "big_decimal_from_string_numeric_semantics_rederived": False,
        "g4_pointer_is_proven_numeric_zero": False,
        "imported_host_semantics_rederived": False,
    }


def prove_value_from_bigdecimal(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    function = function_by_suffix(context, "Value.fromBigDecimal")
    require((function.start_line, len(function.lines)) == (2791, 11), f"{profile} Value.fromBigDecimal binding drift")
    lines = [normalized(line) for line in function.lines]
    require(call_name(function.lines[2]) == "~lib/@graphprotocol/graph-ts/index/Value#constructor", f"{profile} Value allocation target drift")
    result_match = re.fullmatch(r"local\.tee (\$l\d+)", lines[3])
    require(result_match is not None, f"{profile} Value result local drift")
    result_local = result_match.group(1)
    require(
        lines[4:11]
        == [
            "i32.const 2",
            "i32.store",
            f"local.get {result_local}",
            "local.get $p0",
            "i64.extend_i32_u",
            "i64.store offset=8",
            f"local.get {result_local})",
        ],
        f"{profile} Value kind/payload/return identity drift",
    )
    require(function_sha256(function) == VALUE_FROM_BIGDECIMAL_SHA256, f"{profile} Value.fromBigDecimal body drift")
    return {
        "function": function.name,
        "wat_start_line": function.start_line,
        "body_sha256": function_sha256(function),
        "value_kind": 2,
        "payload_input": "$p0",
        "payload_offset": 8,
        "same_constructor_return_pointer_receives_kind_payload_and_is_returned_machine_proven": True,
        "value_constructor_allocation_semantics_rederived": False,
        "fresh_value_allocation_proven": False,
    }


def prove_direct_price_groups(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    handler = context["handler"]
    memory = context["memory"]
    records: list[dict[str, Any]] = []
    raw_lines: list[str] = []
    for ordinal, (field, base) in enumerate(DIRECT_FIELD_BASES):
        pointer = expected["key_pointers"][ordinal]
        lines = list(handler.lines[base : base + 5])
        require(
            [normalized(line) for line in lines]
            == [
                "local.get $l1",
                f"i32.const {pointer}",
                "global.get $g4",
                "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigDecimal",
                f"call ${LEGACY_MAP_SET}",
            ],
            f"{profile} Pool.{field} direct receiver/key/g4/Value/set flow drift",
        )
        require(decoded_constant(lines[1], memory) == field, f"{profile} Pool.{field} decoded key drift")
        raw_lines.extend(lines)
        records.append(
            {
                "entity": "Pool",
                "field": field,
                "schema_type": "BigDecimal!",
                "receiver_local": "$l1",
                "decoded_key": field,
                "key_pointer": pointer,
                "value_global": "$g4",
                "value_wrapper": "Value.fromBigDecimal",
                "value_kind": 2,
                "setter": LEGACY_MAP_SET,
                "setter_relative_wat_line": base + 4,
                "setter_absolute_wat_line": handler.start_line + base + 4,
                "direct_static_typed_map_set_site_fully_selected": True,
                "receiver_key_value_to_typed_map_set_call_machine_proven": True,
                "selected_field_mutation_proven": False,
            }
        )
    require(
        hashlib.sha256(("\n".join(raw_lines) + "\n").encode()).hexdigest()
        == expected["direct_concat_raw_sha256"],
        f"{profile} direct price group raw authority drift",
    )
    require(
        decoded_normalized_sha256(raw_lines, memory)
        == DIRECT_CONCAT_DECODED_NORMALIZED_SHA256,
        f"{profile} direct price group normalized authority drift",
    )
    return {
        "selected_fields": records,
        "direct_group_relative_wat_ranges": [[base, base + 4] for _, base in DIRECT_FIELD_BASES],
        "direct_group_raw_concat_sha256": expected["direct_concat_raw_sha256"],
        "direct_group_decoded_string_normalized_sha256": DIRECT_CONCAT_DECODED_NORMALIZED_SHA256,
        "direct_static_typed_map_set_site_count": 2,
        "legacy_selected_field_mutation_proven": False,
    }


def prove_same_receiver_through_save(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    handler = context["handler"]
    forbidden: list[dict[str, Any]] = []
    for index in range(351, 421):
        instruction = normalized(handler.lines[index])
        opcode = instruction.split(maxsplit=1)[0].lstrip("(").rstrip(")") if instruction else ""
        if opcode in {"return", "br", "br_if", "br_table", "if", "else", "end", "block", "loop", "select"}:
            forbidden.append({"relative_wat_line": index, "instruction": instruction})
    receiver_writes = [
        [index, normalized(handler.lines[index])]
        for index in range(90, 421)
        if normalized(handler.lines[index]) in {"local.set $l1", "local.tee $l1"}
    ]
    require(forbidden == [], f"{profile} price-through-save control bypass drift")
    require(receiver_writes == [], f"{profile} Pool receiver reassignment before save drift")
    require(normalized(handler.lines[419]) == "local.get $l1", f"{profile} Pool save receiver drift")
    require(call_name(handler.lines[420]) == "src/types/schema/Pool#save", f"{profile} Pool save call drift")
    depths = V2.wat_control_depths(handler.lines)
    selected_calls = [355, 360, 420]
    require(all(depths[index] == 0 for index in selected_calls), f"{profile} price selected call control depth drift")
    require(slice_sha256(handler, 351, 421) == expected["through_save_raw_sha256"], f"{profile} price-through-save raw authority drift")
    require(
        decoded_normalized_sha256(handler.lines[351:421], context["memory"])
        == THROUGH_SAVE_DECODED_NORMALIZED_SHA256,
        f"{profile} price-through-save normalized authority drift",
    )
    return {
        "selected_region_relative_wat_lines": [351, 420],
        "selected_region_absolute_wat_lines": [handler.start_line + 351, handler.start_line + 420],
        "selected_region_raw_sha256": expected["through_save_raw_sha256"],
        "selected_region_decoded_string_normalized_sha256": THROUGH_SAVE_DECODED_NORMALIZED_SHA256,
        "selected_call_relative_wat_lines": selected_calls,
        "forbidden_bypass_instructions": forbidden,
        "selected_pool_receiver_reassignments_after_origin_before_save": receiver_writes,
        "same_receiver_for_two_selected_flows_and_pool_save_call_machine_proven": True,
        "conditional_normal_continuation_to_selected_region_only": True,
        "selected_persistence_proven": False,
        "no_later_selected_field_overwrites_proven": False,
    }


def prove_residual_accounting(
    context: dict[str, Any], parent_proof: dict[str, Any]
) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    functions = context["functions"]
    handler = context["handler"]
    reachable = sorted(WRITER.reachable_functions(functions, handler, tuple(context["indirect"])))
    static_sites = [
        [name, index]
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if call_name(line) == LEGACY_MAP_SET
    ]
    require(len(static_sites) == 44, f"{profile} reachable static TypedMap#set count drift")
    inherited = parent_proof["residual_accounting"]
    require(
        inherited["fully_selected_direct_static_site_relative_wat_lines"]
        == [327, 335, 340, 345, 350, 365]
        and inherited["fully_selected_direct_static_site_count"] == 6
        and inherited["unclassified_static_typed_map_set_site_count"] == 38,
        f"{profile} BigInt parent direct static-site accounting drift",
    )
    fully_selected_direct = [327, 335, 340, 345, 350, 355, 360, 365]
    fully_selected_sites = [[handler.name, index] for index in fully_selected_direct]
    require(all(site in static_sites for site in fully_selected_sites), f"{profile} cumulative direct static-site inventory drift")
    shared_site = inherited["shared_tx_count_static_site"]
    require(shared_site in static_sites and shared_site not in fully_selected_sites, f"{profile} shared txCount site classification drift")

    expanded: list[int] = []
    for index, line in enumerate(handler.lines):
        target = call_name(line)
        if target == LEGACY_MAP_SET or (
            target in functions
            and any(call_name(candidate) == LEGACY_MAP_SET for candidate in functions[target].lines)
        ):
            expanded.append(index)
    require(len(expanded) == 78, f"{profile} expanded map-write invocation count drift")
    require(canonical_sha256(expanded) == EXPANDED_MAP_WRITE_INVOCATIONS_SHA256, f"{profile} expanded map-write invocation digest drift")
    newly_selected = [355, 360]
    cumulative_selected = [327, 330, 335, 340, 345, 350, 355, 360, 365]
    require(all(index in expanded for index in cumulative_selected), f"{profile} selected expanded invocation missing")
    require(canonical_sha256(newly_selected) == NEW_SELECTED_EXPANDED_INDEX_SHA256, f"{profile} new selected invocation digest drift")
    require(canonical_sha256(cumulative_selected) == CUMULATIVE_SELECTED_EXPANDED_INDEX_SHA256, f"{profile} cumulative selected invocation digest drift")
    require(
        inherited["expanded_map_write_invocation_count"] == 78
        and inherited["cumulative_selected_expanded_invocation_count"] == 7
        and inherited["residual_expanded_invocation_count"] == 71
        and inherited["shared_tx_count_static_site_remains_residual"] is True,
        f"{profile} BigInt parent expanded accounting drift",
    )
    return {
        "reachable_static_typed_map_set_site_count": 44,
        "new_fully_selected_direct_static_site_relative_wat_lines": newly_selected,
        "fully_selected_direct_static_site_relative_wat_lines": fully_selected_direct,
        "fully_selected_direct_static_site_count": 8,
        "unclassified_static_typed_map_set_site_count": 36,
        "shared_tx_count_static_site": shared_site,
        "shared_tx_count_static_site_remains_residual": True,
        "expanded_map_write_invocation_count": 78,
        "new_selected_expanded_invocation_relative_wat_lines": newly_selected,
        "new_selected_expanded_invocation_count": 2,
        "cumulative_selected_expanded_invocation_relative_wat_lines": cumulative_selected,
        "cumulative_selected_expanded_invocation_count": 9,
        "residual_expanded_invocation_count": 69,
        "expanded_map_write_invocations_sha256": canonical_sha256(expanded),
        "direct_memory_write_sites_without_selected_payload_alias_proof": inherited["direct_memory_write_sites_without_selected_payload_alias_proof"],
        "reachable_graph_store_targets": inherited["reachable_graph_store_targets"],
        "all_other_reachable_typed_map_receiver_key_value_semantics_classified": False,
        "general_heap_alias_semantics_rederived": False,
    }


def prove_legacy_context(
    context: dict[str, Any], parent_proof: dict[str, Any]
) -> dict[str, Any]:
    require(parent_proof["mapping_cid"] == context["cid"], "Factory BigInt parent mapping mismatch")
    g4 = prove_g4_pointer_origin(context, parent_proof)
    wrapper = prove_value_from_bigdecimal(context)
    direct = prove_direct_price_groups(context)
    through_save = prove_same_receiver_through_save(context)
    residual = prove_residual_accounting(context, parent_proof)
    selected_by_field = {item["field"]: item for item in direct["selected_fields"]}
    require(set(selected_by_field) == set(SELECTED_FIELDS), "legacy selected price field set drift")
    require(parent_proof["typed_map_set"]["selected_field_mutation_proven"] is False, "parent TypedMap mutation boundary drift")
    return {
        "profile_id": context["profile"]["profile_id"],
        "mapping_cid": context["cid"],
        "control_generation": "legacy",
        "factory_pool_bigint_parent_proof_sha256": canonical_sha256(parent_proof),
        "pool_entity_receiver_origin": parent_proof["pool_entity_receiver_origin"],
        "big_decimal_from_string_to_g4": g4,
        "value_from_bigdecimal": wrapper,
        "typed_map_set": parent_proof["typed_map_set"],
        "direct_price_groups": direct,
        "selected_fields": [selected_by_field[field] for field in SELECTED_FIELDS],
        "same_receiver_through_pool_save": through_save,
        "pool_save_capsule": parent_proof["pool_save_capsule"],
        "guard_and_return_boundaries": parent_proof["guard_and_return_boundaries"],
        "residual_accounting": residual,
        "selected_price_initialization_call_operand_flow_machine_proven": True,
        "legacy_selected_price_field_mutation_proven": False,
        "selected_persistence_proven": False,
        "complete_static_handler_contract": False,
        "complete_pool_or_factory_history": False,
    }


def _bind_source_file(root: Path, relative: Path, digest: str) -> None:
    path = root / relative
    require(path.is_file() and raw_sha256(path) == digest, f"source file digest drift: {relative}")


def load_sources(
    root: Path,
    *,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    _bind_source_file(root, PARENT_VERIFIER_PATH.relative_to(REPOSITORY), PARENT_VERIFIER_SHA256)
    _bind_source_file(root, PARENT_CONTRACT_PATH, PARENT_CONTRACT_SHA256)
    parent_sources = PARENT.load_sources(root, recompute_wat=True, wasm2wat=wasm2wat)
    parent_contract = PARENT.verify_contract(
        root,
        sources=parent_sources,
        recompute_wat=False,
        wasm2wat=wasm2wat,
    )
    require(parent_contract["contract_version"] == PARENT_CONTRACT_VERSION, "Factory Pool BigInt parent version drift")
    require(canonical_sha256(parent_contract) == PARENT_CONTRACT_CANONICAL_SHA256, "Factory Pool BigInt canonical contract digest drift")
    parent_scope = parent_contract["scope"]
    require(
        parent_scope["cumulative_selected_field_count"] == 36
        and parent_scope["cumulative_residual_field_count"] == 230,
        "parent 36/230 field ledger drift",
    )
    require(
        parent_scope["factory_paths_closed_before_and_after"] == 14
        and parent_scope["factory_paths_residual_before_and_after"] == 4,
        "parent 14/18 Factory closure drift",
    )
    require(
        parent_scope["cumulative_fully_selected_direct_static_site_count"] == 6
        and parent_scope["cumulative_unclassified_static_site_count"] == 38
        and parent_scope["cumulative_selected_expanded_invocation_count"] == 7
        and parent_scope["cumulative_residual_expanded_invocation_count"] == 71
        and parent_scope["shared_tx_count_static_site_remains_residual"] is True,
        "parent direct-site/shared-invocation accounting drift",
    )
    contexts = parent_sources["legacy_contexts"]
    parent_proofs = parent_sources["legacy_proofs"]
    require(len(contexts) == 4 and len(parent_proofs) == 4, "four legacy parent contexts/proofs required")
    parent_by_cid = {proof["mapping_cid"]: proof for proof in parent_proofs}
    require(set(parent_by_cid) == {context["cid"] for context in contexts}, "legacy parent/context CID set drift")
    proofs = [prove_legacy_context(context, parent_by_cid[context["cid"]]) for context in contexts] if recompute_wat else []
    return {
        "factory_pool_bigint_parent_contract": parent_contract,
        "parent_sources": parent_sources,
        "legacy_contexts": contexts,
        "legacy_proofs": proofs,
    }


def _field_catalog_binding(v2_contract: dict[str, Any], field: str) -> dict[str, Any]:
    matches = [
        item
        for item in v2_contract["field_catalog"]
        if item["entity"] == "Pool" and item["field"] == field
    ]
    require(len(matches) == 1 and matches[0]["type"] == "BigDecimal!", f"v2 Pool.{field} catalog binding drift")
    return matches[0]


def _modern_selected_flows(proof: dict[str, Any]) -> dict[str, dict[str, Any]]:
    selected = {
        item["field"]: item
        for item in proof["field_contract"]["simple_global_value_flows"]
        if item["entity"] == "Pool" and item["field"] in SELECTED_FIELDS
    }
    require(set(selected) == set(SELECTED_FIELDS), f"{proof['profile_id']} modern selected price flow set drift")
    for field, flow in selected.items():
        require(
            flow["value"] == "ZERO_BD"
            and flow["value_kind"] == "BigDecimal"
            and flow["machine_proven"] is True
            and flow["set_binding"]["field_key"] == field
            and flow["set_binding"]["entity_receiver"] == "$l6"
            and flow["set_binding"]["value_kind_tag"] == 2
            and flow["set_binding"]["exact_receiver_key_kind_payload_final_operand_and_set_call_proven"] is True,
            f"{proof['profile_id']} modern Pool.{field} flow drift",
        )
    return selected


def build_segments(
    matrix_contract: dict[str, Any],
    v2_contract: dict[str, Any],
    legacy_proofs: list[dict[str, Any]],
    modern_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    legacy_by_cid = {proof["mapping_cid"]: proof for proof in legacy_proofs}
    modern_by_cid = {proof["mapping_cid"]: proof for proof in modern_contract["modern_factory_static_proofs"]}
    require(len(legacy_by_cid) == 4 and len(modern_by_cid) == 2, "Factory price proof mapping inventory drift")
    catalog = {field: _field_catalog_binding(v2_contract, field) for field in SELECTED_FIELDS}
    results: list[dict[str, Any]] = []
    legacy_count = 0
    modern_count = 0
    for segment in matrix_contract["segments"]:
        handlers = [item for item in segment["handlers"] if item["handler_id"] == HANDLER_ID]
        require(len(handlers) == 1, f"{segment['segment_id']} Factory handler binding drift")
        handler = handlers[0]
        cid = handler["mapping_cid"]
        if cid in legacy_by_cid:
            proof = legacy_by_cid[cid]
            flows = {item["field"]: item for item in proof["selected_fields"]}
            generation = "legacy"
            profile_id = proof["profile_id"]
            proof_sha256 = canonical_sha256(proof)
            complete_static = False
            legacy_count += 1
            origin = proof["pool_entity_receiver_origin"]
            save = proof["pool_save_capsule"]
        else:
            require(cid in modern_by_cid, f"{segment['segment_id']} Factory mapping has no price proof: {cid}")
            proof = modern_by_cid[cid]
            flows = _modern_selected_flows(proof)
            generation = "modern"
            profile_id = proof["profile_id"]
            proof_sha256 = canonical_sha256(proof)
            complete_static = True
            modern_count += 1
            origin = proof["field_contract"]["entity_receiver_origins"]["Pool"]
            save = {
                "parent_complete_static_handler_contract": True,
                "selected_field_flows_are_part_of_parent_59_written_fields": True,
                "selected_persistence_proven": False,
            }
        fields: list[dict[str, Any]] = []
        for field in SELECTED_FIELDS:
            inherited = catalog[field]
            fields.append(
                {
                    "entity": "Pool",
                    "field": field,
                    "schema_type": "BigDecimal!",
                    "population_classification": "conditional",
                    "initialization_value_source": (
                        'pointer returned by bigDecimal.fromString("0") and stored in $g4, via Value.fromBigDecimal'
                        if generation == "legacy"
                        else "ZERO_BD"
                    ),
                    "selected_factory_initialization_call_operand_flow_machine_proven": True,
                    "selected_field_mutation_proven": generation == "modern",
                    "selected_persistence_proven": False,
                    "complete_entity_history": False,
                    "selected_flow_sha256": canonical_sha256(flows[field]),
                    "v2_field_catalog_record_sha256": canonical_sha256(inherited),
                    "residual_history_blocker": "host/store/reset semantics, persistence, complete Factory and Pool histories, combined scheduling, boundary/oracle/parity, backfill, and production remain open",
                }
            )
        semantic = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": profile_id,
            "control_generation": generation,
            "pool_receiver_origin": origin,
            "selected_field_flows": flows,
            "selected_save_boundary": save,
            "fields": fields,
            "selected_factory_initialization_call_operand_flow_machine_proven": True,
            "selected_field_mutation_proven": generation == "modern",
            "complete_static_handler_contract": complete_static,
            "selected_persistence_proven": False,
            "complete_factory_entity_history": False,
            "complete_pool_entity_history": False,
        }
        provenance = {
            "mapping_cid": cid,
            "profile_id": profile_id,
            "generation": generation,
            "proof_sha256": proof_sha256,
            "source_handler_record_sha256": canonical_sha256(handler),
            "factory_pool_bigint_parent_contract_sha256": PARENT_CONTRACT_SHA256,
            "factory_pool_bigint_parent_contract_canonical_sha256": PARENT_CONTRACT_CANONICAL_SHA256,
        }
        results.append(
            {
                "segment_id": segment["segment_id"],
                "network": segment["network"],
                "deployment": segment["deployment"],
                "start_block_inclusive": segment["start_block_inclusive"],
                "end_block_inclusive": segment["end_block_inclusive"],
                "semantic_surface": semantic,
                "semantic_surface_sha256": canonical_sha256(semantic),
                "provenance_surface": provenance,
                "provenance_surface_sha256": canonical_sha256(provenance),
                "execution_model": "undecided",
                "backfill_allowed": False,
            }
        )
    require(len(results) == 8, "Factory price initialization segment count drift")
    require(legacy_count == 6 and modern_count == 2, "legacy/modern Factory price segment count drift")
    require(sum(len(item["semantic_surface"]["fields"]) for item in results) == 16, "Factory price field-record count drift")
    require(
        [
            (item["network"], item["start_block_inclusive"], item["end_block_inclusive"])
            for item in results
            if item["semantic_surface"]["control_generation"] == "legacy"
        ]
        == [
            ("mainnet", 12369621, 13450880),
            ("mainnet", 13450881, 13498328),
            ("mainnet", 13498329, 13591197),
            ("mainnet", 13591198, 13605860),
            ("mainnet", 13605861, 19470000),
            ("base", 1371679, 19852000),
        ],
        "six legacy Factory segment ranges drift",
    )
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = PARENT.PARENT.FEE_GROWTH.INITIALIZE.json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = PARENT.PARENT.FEE_GROWTH.INITIALIZE.json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        results.append(
            {
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "scoped_semantic_equal": not semantic_paths,
                "scoped_semantic_diff_paths": semantic_paths,
                "provenance_equal": not provenance_paths,
                "provenance_diff_paths": provenance_paths,
                "left_semantic_surface_sha256": left["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right["semantic_surface_sha256"],
                "left_provenance_surface_sha256": left["provenance_surface_sha256"],
                "right_provenance_surface_sha256": right["provenance_surface_sha256"],
                "complete_writer_semantics_compared": False,
                "boundary_state_compared": False,
                "graph_oracle_compared": False,
            }
        )
    require(len(results) == 28, "Factory price initialization pairwise diff count drift")
    return results


def truth_boundary() -> dict[str, bool]:
    require(len(TRUE_FLAGS) == len(set(TRUE_FLAGS)), "duplicate true truth gate")
    require(len(FALSE_FLAGS) == len(set(FALSE_FLAGS)), "duplicate false truth gate")
    require(set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "truth gate overlap")
    return {**{name: True for name in TRUE_FLAGS}, **{name: False for name in FALSE_FLAGS}}


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["legacy_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 4, "four recomputed legacy price proofs required")
    parent_sources = sources["parent_sources"]["parent_sources"]
    segments = build_segments(
        parent_sources["matrix_contract"],
        parent_sources["v2_contract"],
        proofs,
        parent_sources["modern_factory_static_contract"],
    )
    diffs = build_segment_diffs(segments)
    residuals = {
        proof["profile_id"]: {
            "fully_selected_direct_static_site_count": proof["residual_accounting"]["fully_selected_direct_static_site_count"],
            "unclassified_static_typed_map_set_site_count": proof["residual_accounting"]["unclassified_static_typed_map_set_site_count"],
            "selected_expanded_invocation_count": proof["residual_accounting"]["cumulative_selected_expanded_invocation_count"],
            "residual_expanded_invocation_count": proof["residual_accounting"]["residual_expanded_invocation_count"],
            "shared_tx_count_static_site_remains_residual": proof["residual_accounting"]["shared_tx_count_static_site_remains_residual"],
            "direct_memory_write_sites_without_selected_payload_alias_proof": proof["residual_accounting"]["direct_memory_write_sites_without_selected_payload_alias_proof"],
            "reachable_graph_store_targets": proof["residual_accounting"]["reachable_graph_store_targets"],
        }
        for proof in proofs
    }
    fixtures = [
        {"fixture": "parent verifier/contract, canonical digest, canonical merge, CID, WASM/WAT, or handler authority", "expected_rejection_layer": "canonical parent and retained-artifact authority"},
        {"fixture": "g4 source string, bigDecimal.fromString import/call, destination global, or unique writer", "expected_rejection_layer": "g4 pointer provenance"},
        {"fixture": "Value.fromBigDecimal constructor, kind, payload, or returned local", "expected_rejection_layer": "Value wrapper operand identity"},
        {"fixture": "price key, receiver, g4 global, Value wrapper, group order, or set target", "expected_rejection_layer": "two direct price call-operand flows"},
        {"fixture": "return, structured control, receiver reassignment, later region drift, or Pool save drift", "expected_rejection_layer": "same-receiver selected flow through Pool.save"},
        {"fixture": "static-site or expanded-invocation count, selected index, shared-site classification, reachable helper, direct write, or store target", "expected_rejection_layer": "direct-site/shared-invocation residual accounting"},
        {"fixture": "missing, duplicate, or mis-profiled segment/field/diff record", "expected_rejection_layer": "eight-segment deterministic projection"},
        {"fixture": "promoted numeric semantics, mutation, persistence, issue, readiness, 36/230, or 14/18 gate", "expected_rejection_layer": "strict truth and refusal boundary"},
        {"fixture": "duplicate JSON key", "expected_rejection_layer": "strict JSON loader"},
    ]
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "retained-wat-factory-pool-price-initialization-call-flow-certificate",
        "scope": {
            "networks": ["mainnet", "base"],
            "handler": HANDLER_ID,
            "unique_legacy_mapping_count": 4,
            "legacy_mapping_field_flow_count": 8,
            "legacy_segment_count": 6,
            "legacy_segment_field_call_flow_record_count": 12,
            "modern_parent_segment_count": 2,
            "modern_parent_field_record_count": 4,
            "segment_count": 8,
            "selected_fields": [f"Pool.{field}" for field in SELECTED_FIELDS],
            "selected_field_count": 2,
            "total_initialization_record_count": 16,
            "pairwise_scoped_diff_count": 28,
            "legacy_factory_field_call_flow_capsules_before": 7,
            "legacy_factory_field_call_flow_capsules_after": 9,
            "legacy_factory_fields_without_call_flow_capsules_after": 51,
            "all_sixty_complete_legacy_field_contracts_proven": False,
            "cumulative_selected_field_count": 36,
            "cumulative_residual_field_count": 230,
            "factory_upstream_path_count": 18,
            "factory_paths_closed_before_and_after": 14,
            "factory_paths_residual_before_and_after": 4,
            "legacy_complete_static_paths_newly_closed": 0,
            "retained_static_typed_map_set_site_count": 44,
            "cumulative_fully_selected_direct_static_site_count": 8,
            "cumulative_unclassified_static_site_count": 36,
            "retained_expanded_map_write_invocation_count": 78,
            "cumulative_selected_expanded_invocation_count": 9,
            "cumulative_residual_expanded_invocation_count": 69,
            "shared_tx_count_static_site_remains_residual": True,
            "reachable_effect_residuals_by_profile": residuals,
            "claim": "exact retained-WAT conditional Factory.handlePoolCreated event-pool receiver, two direct Pool BigDecimal g4-to-Value-to-TypedMap#set call-operand flows, imported bigDecimal.fromString pointer provenance for g4, Value kind/payload identity, and same-receiver Pool.save path across four unique legacy mappings projected to six legacy segments, composed with the recomputed two-segment modern parent; numeric BigDecimal semantics, legacy mutation, persistence, complete static semantics, history, host behavior, and readiness remain false",
        },
        "source_contracts": {
            "factory_pool_bigint_initialization": {
                "path": PARENT_CONTRACT_PATH.as_posix(),
                "raw_sha256": PARENT_CONTRACT_SHA256,
                "canonical_sha256": PARENT_CONTRACT_CANONICAL_SHA256,
                "contract_version": PARENT_CONTRACT_VERSION,
            },
            "factory_pool_bigint_initialization_verifier": {
                "path": PARENT_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(),
                "raw_sha256": PARENT_VERIFIER_SHA256,
            },
        },
        "authority_contract": {
            "semantic_authority": "four exact retained deployed legacy Factory WASM artifacts, checksum-pinned WABT 1.0.35 WAT projections, and the recomputed canonical Factory Pool BigInt initialization parent",
            "source_text_role": "corroboration only",
            "g4_boundary": 'the decoded AssemblyScript string "0" is passed to imported bigDecimal.fromString and its returned pointer is uniquely stored in $g4; imported numeric semantics and a numeric-zero claim are not rederived',
            "value_boundary": "Value.fromBigDecimal stores kind tag 2 and the exact g4 pointer payload into the same constructor-return local, while constructor allocation and freshness semantics remain open",
            "normal_continuation_boundary": "the selected flow is conditional on bypassing the excluded-pool return, both decimals returns, and all helper/import traps",
            "save_boundary": "both selected call flows and Pool.save receive the same unreassigned entity local without a return, branch, structured control, or select in the selected pre-save region; legacy TypedMap mutation semantics, Graph persistence, and later overwrites remain open",
            "accounting_boundary": "eight direct static TypedMap#set sites are fully selected after composing the fee-growth, BigInt, and price slices; the shared txCount static site remains among 36 residual sites; nine of 78 expanded invocations are selected and 69 remain residual",
            "canonical_base": dict(CANONICAL_BASE),
        },
        "toolchain": {
            "name": "WABT wasm2wat and wat2wasm",
            "version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-factory-wasm>"],
            "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"],
        },
        "valid_wat_mutation_fixture_layers": fixtures,
        "legacy_mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "field_count": 230,
            "factory": [
                "all four legacy complete-static paths and all 60 complete legacy stored-field contracts remain unproved",
                "bigDecimal.fromString is imported: only its decoded string operand, returned pointer, and unique g4 storage are bound, not numeric BigDecimal semantics",
                "the shared txCount static TypedMap#set site remains residual because its Factory, token0, and token1 invocations are outside the selected Pool flow",
                "legacy static arrays retain six leading holes, and legacy totalSupply passes a CallResult pointer rather than decoding ERC20 return data",
                "host/reset/numeric/store behavior, persistence, later overwrites, historic outcomes, runtime population, and complete Factory/Pool histories remain open",
            ],
            "execution": [
                "combined handler/dynamic-datasource order, package identity, continuity, oracle/parity, checkpoint, backfill, deployment, production, and readiness remain false",
                "issues #37 and #38 gain no completed acceptance checkbox from this bounded initialization call-flow slice",
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
        require(path.is_file(), f"Factory Pool price initialization contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "Factory Pool price initialization contract byte rendering drift")
    require(actual == expected, "Factory Pool price initialization contract does not reproduce")
    return expected


def write_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    sources = load_sources(root, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(sources)
    destination = root / CONTRACT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(expected))
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write-contract", action="store_true")
    arguments = parser.parse_args()
    try:
        contract = (
            write_contract(arguments.root, arguments.wasm2wat)
            if arguments.write_contract
            else verify_contract(arguments.root, wasm2wat=arguments.wasm2wat)
        )
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        VerificationError,
        PARENT.VerificationError,
        PARENT.PARENT.VerificationError,
        PARENT.PARENT.MODERN.VerificationError,
        PARENT.PARENT.FEE_GROWTH.VerificationError,
        PARENT.PARENT.EFFECTS.VerificationError,
        V2.VerificationError,
        WRITER.VerificationError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 Factory Pool price initialization v1: "
        f"{len(contract['legacy_mapping_proofs'])} unique legacy mappings, "
        f"{contract['scope']['legacy_segment_field_call_flow_record_count']} legacy and "
        f"{contract['scope']['total_initialization_record_count']} total initialization records, "
        f"{len(contract['segment_diffs'])} diffs; "
        f"{contract['scope']['cumulative_fully_selected_direct_static_site_count']} fully selected direct sites of "
        f"{contract['scope']['retained_static_typed_map_set_site_count']} reachable static sites and "
        f"{contract['scope']['cumulative_selected_expanded_invocation_count']}/"
        f"{contract['scope']['retained_expanded_map_write_invocation_count']} expanded invocations selected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
