#!/usr/bin/env python3
"""Build or verify the bounded Uniswap V3 Factory Pool bigint-init certificate."""

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
CONTRACT_PATH = Path("uniswap-v3/factory-pool-bigint-init/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-factory-pool-bigint-initialization/v1"
HANDLER_ID = "Factory.handlePoolCreated"
HANDLER_EXPORT = "handlePoolCreated"
SELECTED_FIELDS = (
    "liquidityProviderCount",
    "txCount",
    "liquidity",
    "sqrtPrice",
    "observationIndex",
)
DIRECT_FIELD_BASES = (
    ("liquidityProviderCount", 323),
    ("liquidity", 331),
    ("sqrtPrice", 336),
    ("observationIndex", 361),
)
TX_COUNT_INVOCATIONS = (
    (60, "$l4", False),
    (168, "$l2", False),
    (242, "$l3", False),
    (330, "$l1", True),
)

PARENT_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-factory-fee-growth-init.py"
PARENT_VERIFIER_SHA256 = "1c0ead297e7980f472c11f43032405430b0dafdd63332a9be25c67c3a8267980"
PARENT_CONTRACT_PATH = Path("uniswap-v3/factory-fee-growth-init/v1/contract.json")
PARENT_CONTRACT_SHA256 = "38301b81ae36e346595847c62a0ffc4bf12ce67e0b437abda7790e379e1489d1"
PARENT_CONTRACT_VERSION = "uniswap-v3-factory-fee-growth-initialization/v1"

CANONICAL_BASE = {
    "canonical_merge_commit": "982dd6f049af265cfed4c7b8edce1a90c936f319",
    "canonical_merge_tree": "ffc1ef46913c94a6c7b5bc9738de2389dce38daf",
    "canonical_merge_parent": "cf4d096304c09f150a7ee2ea85de5d479d5ec7ef",
    "audited_candidate_commit": "1c6d90f0cbf7bf80a47555f9f6242d8f7440975e",
    "audited_candidate_tree": "ffc1ef46913c94a6c7b5bc9738de2389dce38daf",
    "exact_head_ci_run": 33337445498,
    "exact_head_ci_jobs": 6,
    "exact_head_ci_steps": 162,
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
    "uniswap_v3_factory_fee_growth_for_pool_bigint_init",
    PARENT_VERIFIER_PATH,
    PARENT_VERIFIER_SHA256,
)
WRITER = PARENT.WRITER
V2 = PARENT.V2
RUNTIME = PARENT.RUNTIME
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


EXPECTED: dict[str, dict[str, Any]] = {
    "legacy-base-root": {
        "cid": "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj",
        "direct_key_pointers": [3888, 3936, 3960, 4144],
        "tx_count_key_pointer": 1632,
        "direct_concat_raw_sha256": "064f1648d8311bd74a5950fcc3cfd24cfddf1069042f098907bf73313833b8bc",
        "tx_helper_raw_sha256": "5e022004bdca5593d0346f836076eb53c3e98df605e7fcce5f24eb638a29ebba",
        "through_save_raw_sha256": "9ee3fd7478f6f84e8f567d60e1a86cf7628424b11468064824f989b71a0fc8ef",
    },
    "legacy-mainnet-qmrv": {
        "cid": "QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV",
        "direct_key_pointers": [6280, 6328, 6352, 6536],
        "tx_count_key_pointer": 3400,
        "direct_concat_raw_sha256": "7756f05a11cd6778fc58483121fc8328a2177c3b2966e7a327f389edd274e329",
        "tx_helper_raw_sha256": "3c70518e7acc06a9b0c1e9d17eab9954fef7d735fdbc30e8b0255bb4746895b0",
        "through_save_raw_sha256": "16a3e3c8803409efe0fd5e97f6eaa7c46bb47162bd80f2c2e046b34dc12e5edd",
    },
    "legacy-mainnet-root": {
        "cid": "QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr",
        "direct_key_pointers": [6192, 6240, 6264, 6448],
        "tx_count_key_pointer": 3312,
        "direct_concat_raw_sha256": "5a2c2c97b3b8c03c2eaef20dfdfa7f0124ae696933546a8b022fea4e34b51310",
        "tx_helper_raw_sha256": "f496b1ab3b05e40f4c4b84c9c4ffb4744db7cd5b945ebb5f52099a7534ade202",
        "through_save_raw_sha256": "6dc9a67e2015df5dc57ef62cc2a27e8fa69e00f28ce0830af91e14438aca1302",
    },
    "legacy-mainnet-stable": {
        "cid": "QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL",
        "direct_key_pointers": [6320, 6368, 6392, 6576],
        "tx_count_key_pointer": 3440,
        "direct_concat_raw_sha256": "a77253839dcae8a2416ccb3ee725938168168db8175b2148ef1e14e0a6f2ef9e",
        "tx_helper_raw_sha256": "437e4bc7e21f2217f30ded6c1be2d3cdb2f1ba68c3994ccc2a648dd46550b6f4",
        "through_save_raw_sha256": "8814b5f6b20dd3be01be7b6b122c2836c2875b5b9a8bcbf205981886180fa359",
    },
}

DIRECT_CONCAT_DECODED_NORMALIZED_SHA256 = "9f21f5981eaf93e4c9bc148c02148695706c95e255d152aeabe78a968fd41475"
TX_HELPER_DECODED_NORMALIZED_SHA256 = "c66a247d0789ccc5317bb647bb0471e03ee9c743bfbc3ec6a3af194b751678c9"
TX_INVOCATION_NORMALIZED_SHA256 = "766a1a59d075f69fce80edf4786e7c39284a482171cb748eaa28291bef6a6408"
THROUGH_SAVE_DECODED_NORMALIZED_SHA256 = "2aae1299579e35b2ef62df758ff5aadd2f620edb9394efe821d9656a132d6fbd"
TX_INVOCATION_INDEX_SHA256 = "8b914a24207681421cdaa033b60647fe0ed4acb87fbe66a71154d14aaa0ffa7c"
NEW_SELECTED_EXPANDED_INDEX_SHA256 = "caddab7f866c983f86f036dee446d1a01d53577991b70303a970de07281846ad"
CUMULATIVE_SELECTED_EXPANDED_INDEX_SHA256 = "4e20adceefbfb06cdd7c63f371d729fe90e424605ea6310995da9b5282252afb"
EXPANDED_MAP_WRITE_INVOCATIONS_SHA256 = "e1786369ca1dccbf1328ec9f0534c5f2059851dbc65bc8a2c2a940f85be6b3a9"

TRUE_FLAGS = (
    "factory_fee_growth_initialization_parent_recomputed_and_pinned",
    "four_exact_legacy_factory_artifacts_and_handlers_inherited",
    "sixteen_direct_bigint_setter_call_operand_flows_bound",
    "four_selected_pool_tx_count_helper_invocations_bound",
    "four_shared_tx_count_helper_bodies_bound",
    "sixteen_total_shared_tx_count_invocations_classified",
    "four_same_receiver_bigint_call_through_pool_save_flows_bound",
    "six_legacy_segment_projections_present",
    "thirty_legacy_segment_field_records_present",
    "two_modern_parent_segment_projections_present",
    "forty_total_initialization_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "six_fully_selected_direct_static_sites_of_forty_four",
    "thirty_eight_unclassified_static_sites_retained",
    "seven_selected_expanded_invocations_of_seventy_eight",
    "seventy_one_expanded_invocations_retained_residual",
    "shared_tx_count_static_site_retained_as_residual",
    "seven_of_sixty_legacy_factory_field_call_flow_capsules_present",
    "cumulative_field_ledger_remains_36_selected_230_residual",
    "cumulative_factory_closure_remains_14_of_18",
)

ADDITIONAL_FALSE_FLAGS = (
    "shared_tx_count_static_site_fully_selected",
    "all_four_shared_tx_count_invocations_selected",
    "factory_set_tx_count_symbol_is_pool_entity_authority",
    "all_seven_legacy_factory_field_contracts_complete",
)
FALSE_FLAGS = tuple(dict.fromkeys((*PARENT.FALSE_FLAGS, *ADDITIONAL_FALSE_FLAGS)))


def decoded_normalized_sha256(lines: list[str] | tuple[str, ...], memory: bytearray) -> str:
    output: list[str] = []
    for raw_line in lines:
        line = raw_line.strip().replace("generated/schema/", "src/types/schema/")
        match = re.fullmatch(r"(i32\.const )(-?\d+)(.*)", line)
        if match is not None:
            value = WRITER.decode_assemblyscript_string(memory, int(match.group(2)))
            if value is not None:
                digest = hashlib.sha256(value.encode()).hexdigest()
                line = f"{match.group(1)}STATIC_STRING_{digest}{match.group(3)}"
        output.append(line)
    return hashlib.sha256(("\n".join(output) + "\n").encode()).hexdigest()


def prove_direct_bigint_groups(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    handler = context["handler"]
    memory = context["memory"]
    records: list[dict[str, Any]] = []
    raw_lines: list[str] = []
    for ordinal, (field, base) in enumerate(DIRECT_FIELD_BASES):
        pointer = expected["direct_key_pointers"][ordinal]
        lines = list(handler.lines[base : base + 5])
        require(
            [normalized(line) for line in lines]
            == [
                "local.get $l1",
                f"i32.const {pointer}",
                "global.get $g2",
                "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigInt",
                f"call ${LEGACY_MAP_SET}",
            ],
            f"{profile} Pool.{field} direct receiver/key/g2/Value/set flow drift",
        )
        require(decoded_constant(lines[1], memory) == field, f"{profile} Pool.{field} decoded key drift")
        raw_lines.extend(lines)
        records.append(
            {
                "entity": "Pool",
                "field": field,
                "schema_type": "BigInt!",
                "receiver_local": "$l1",
                "decoded_key": field,
                "key_pointer": pointer,
                "value_global": "$g2",
                "value_wrapper": "Value.fromBigInt",
                "value_kind": 7,
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
        f"{profile} direct bigint group raw authority drift",
    )
    require(
        decoded_normalized_sha256(raw_lines, memory) == DIRECT_CONCAT_DECODED_NORMALIZED_SHA256,
        f"{profile} direct bigint group normalized authority drift",
    )
    return {
        "selected_fields": records,
        "direct_group_relative_wat_ranges": [[base, base + 4] for _, base in DIRECT_FIELD_BASES],
        "direct_group_raw_concat_sha256": expected["direct_concat_raw_sha256"],
        "direct_group_decoded_string_normalized_sha256": DIRECT_CONCAT_DECODED_NORMALIZED_SHA256,
        "direct_static_typed_map_set_site_count": 4,
        "legacy_selected_field_mutation_proven": False,
    }


def prove_shared_tx_count_helper_and_invocations(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    handler = context["handler"]
    memory = context["memory"]
    helper = function_by_suffix(context, "src/types/schema/Factory#set:txCount")
    pointer = expected["tx_count_key_pointer"]
    require((helper.start_line, len(helper.lines)) == (2826, 6), f"{profile} shared txCount helper binding drift")
    require(
        [normalized(line) for line in helper.lines[1:6]]
        == [
            "local.get $p0",
            f"i32.const {pointer}",
            "local.get $p1",
            "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigInt",
            f"call ${LEGACY_MAP_SET})",
        ],
        f"{profile} shared txCount helper receiver/key/value/set operand drift",
    )
    require(decoded_constant(helper.lines[2], memory) == "txCount", f"{profile} shared txCount decoded key drift")
    require(function_sha256(helper) == expected["tx_helper_raw_sha256"], f"{profile} shared txCount helper body drift")
    require(
        decoded_normalized_sha256(helper.lines, memory) == TX_HELPER_DECODED_NORMALIZED_SHA256,
        f"{profile} shared txCount helper normalized body drift",
    )

    invocation_indexes = [
        index
        for index, line in enumerate(handler.lines)
        if call_name(line) == helper.name
    ]
    require(invocation_indexes == [item[0] for item in TX_COUNT_INVOCATIONS], f"{profile} shared txCount invocation inventory drift")
    require(canonical_sha256(invocation_indexes) == TX_INVOCATION_INDEX_SHA256, f"{profile} shared txCount invocation digest drift")
    invocations: list[dict[str, Any]] = []
    for index, receiver, selected in TX_COUNT_INVOCATIONS:
        require(
            [normalized(line) for line in handler.lines[index - 2 : index + 1]]
            == [f"local.get {receiver}", "global.get $g2", f"call ${helper.name}"],
            f"{profile} shared txCount invocation {index} operands drift",
        )
        invocations.append(
            {
                "call_relative_wat_line": index,
                "call_absolute_wat_line": handler.start_line + index,
                "receiver_local": receiver,
                "value_global": "$g2",
                "selected_pool_invocation": selected,
            }
        )
    require(
        decoded_normalized_sha256(handler.lines[328:331], memory) == TX_INVOCATION_NORMALIZED_SHA256,
        f"{profile} selected Pool txCount invocation normalized drift",
    )
    return {
        "field": {
            "entity": "Pool",
            "field": "txCount",
            "schema_type": "BigInt!",
            "receiver_local": "$l1",
            "decoded_key": "txCount",
            "key_pointer": pointer,
            "value_global": "$g2",
            "value_wrapper": "Value.fromBigInt",
            "value_kind": 7,
            "setter_helper": helper.name,
            "selected_invocation_relative_wat_line": 330,
            "selected_invocation_absolute_wat_line": handler.start_line + 330,
            "receiver_value_to_shared_helper_call_machine_proven": True,
            "helper_parameter_key_wrapper_to_typed_map_set_call_machine_proven": True,
            "selected_field_mutation_proven": False,
        },
        "helper": {
            "function": helper.name,
            "wat_start_line": helper.start_line,
            "line_count": len(helper.lines),
            "body_sha256": function_sha256(helper),
            "decoded_string_normalized_sha256": TX_HELPER_DECODED_NORMALIZED_SHA256,
            "receiver_parameter": "$p0",
            "value_parameter": "$p1",
            "decoded_key": "txCount",
            "symbol_name_is_entity_authority": False,
        },
        "invocations": invocations,
        "invocation_relative_wat_lines_sha256": TX_INVOCATION_INDEX_SHA256,
        "shared_helper_invocation_count": 4,
        "selected_pool_invocation_count": 1,
        "residual_non_pool_invocation_count": 3,
        "shared_static_typed_map_set_site_count": 1,
        "shared_static_typed_map_set_site_fully_selected": False,
        "all_four_shared_tx_count_invocations_selected": False,
        "factory_set_tx_count_symbol_is_pool_entity_authority": False,
        "legacy_selected_field_mutation_proven": False,
    }


def prove_same_receiver_through_save(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    handler = context["handler"]
    forbidden: list[dict[str, Any]] = []
    for index in range(323, 421):
        instruction = normalized(handler.lines[index])
        opcode = instruction.split(maxsplit=1)[0].lstrip("(").rstrip(")") if instruction else ""
        if opcode in {"return", "br", "br_if", "br_table", "if", "else", "end", "block", "loop", "select"}:
            forbidden.append({"relative_wat_line": index, "instruction": instruction})
    receiver_writes = [
        [index, normalized(handler.lines[index])]
        for index in range(90, 421)
        if normalized(handler.lines[index]) in {"local.set $l1", "local.tee $l1"}
    ]
    require(forbidden == [], f"{profile} bigint-through-save control bypass drift")
    require(receiver_writes == [], f"{profile} Pool receiver reassignment before save drift")
    require(normalized(handler.lines[419]) == "local.get $l1", f"{profile} Pool save receiver drift")
    require(call_name(handler.lines[420]) == "src/types/schema/Pool#save", f"{profile} Pool save call drift")
    depths = V2.wat_control_depths(handler.lines)
    selected_calls = [327, 330, 335, 340, 365, 420]
    require(all(depths[index] == 0 for index in selected_calls), f"{profile} bigint selected call control depth drift")
    require(slice_sha256(handler, 323, 421) == expected["through_save_raw_sha256"], f"{profile} bigint-through-save raw authority drift")
    require(
        decoded_normalized_sha256(handler.lines[323:421], context["memory"])
        == THROUGH_SAVE_DECODED_NORMALIZED_SHA256,
        f"{profile} bigint-through-save normalized authority drift",
    )
    return {
        "selected_region_relative_wat_lines": [323, 420],
        "selected_region_absolute_wat_lines": [handler.start_line + 323, handler.start_line + 420],
        "selected_region_raw_sha256": expected["through_save_raw_sha256"],
        "selected_region_decoded_string_normalized_sha256": THROUGH_SAVE_DECODED_NORMALIZED_SHA256,
        "selected_call_relative_wat_lines": selected_calls,
        "forbidden_bypass_instructions": forbidden,
        "selected_pool_receiver_reassignments_after_origin_before_save": receiver_writes,
        "same_receiver_for_five_selected_flows_and_pool_save_call_machine_proven": True,
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
    parent_selected_fields = parent_proof["selected_setter_through_save"]["selected_fields"]
    require(
        [
            (item["field"], item["setter_relative_wat_line"])
            for item in parent_selected_fields
        ]
        == [("feeGrowthGlobal0X128", 345), ("feeGrowthGlobal1X128", 350)],
        f"{profile} parent fee-growth selected direct-site composition drift",
    )
    fully_selected_direct = [[handler.name, index] for index in [327, 335, 340, 345, 350, 365]]
    require(all(site in static_sites for site in fully_selected_direct), f"{profile} fully selected direct static-site inventory drift")
    helper = function_by_suffix(context, "src/types/schema/Factory#set:txCount")
    helper_sites = [[helper.name, index] for index, line in enumerate(helper.lines) if call_name(line) == LEGACY_MAP_SET]
    require(len(helper_sites) == 1 and helper_sites[0] in static_sites, f"{profile} shared txCount static site drift")
    require(helper_sites[0] not in fully_selected_direct, f"{profile} shared txCount site incorrectly fully selected")

    expanded = []
    for index, line in enumerate(handler.lines):
        target = call_name(line)
        if target == LEGACY_MAP_SET or (
            target in functions
            and any(call_name(candidate) == LEGACY_MAP_SET for candidate in functions[target].lines)
        ):
            expanded.append(index)
    require(len(expanded) == 78, f"{profile} expanded map-write invocation count drift")
    require(canonical_sha256(expanded) == EXPANDED_MAP_WRITE_INVOCATIONS_SHA256, f"{profile} expanded map-write invocation digest drift")
    require(
        all(index in expanded for index, _, _ in TX_COUNT_INVOCATIONS),
        f"{profile} shared txCount invocation missing from expanded accounting",
    )
    newly_selected = [327, 330, 335, 340, 365]
    cumulative_selected = [327, 330, 335, 340, 345, 350, 365]
    require(all(index in expanded for index in cumulative_selected), f"{profile} selected expanded invocation missing")
    require(canonical_sha256(newly_selected) == NEW_SELECTED_EXPANDED_INDEX_SHA256, f"{profile} new selected invocation digest drift")
    require(canonical_sha256(cumulative_selected) == CUMULATIVE_SELECTED_EXPANDED_INDEX_SHA256, f"{profile} cumulative selected invocation digest drift")

    inherited = parent_proof["reachable_residual_inventory"]
    require(
        inherited["reachable_typed_map_set_site_count"] == 44
        and inherited["selected_typed_map_set_site_count"] == 2
        and inherited["unclassified_typed_map_set_site_count"] == 42
        and inherited["expanded_lexical_map_write_invocation_count"] == 78,
        f"{profile} parent static/expanded accounting drift",
    )
    expected_writes = 146 if profile == "legacy-base-root" else 154
    require(
        inherited["direct_memory_write_sites_without_selected_payload_alias_proof"] == expected_writes,
        f"{profile} inherited direct-memory residual drift",
    )
    require(inherited["reachable_graph_store_targets"] == ["Bundle", "Factory", "Pool", "Token"], f"{profile} inherited store target drift")
    return {
        "reachable_static_typed_map_set_site_count": 44,
        "fully_selected_direct_static_site_relative_wat_lines": [327, 335, 340, 345, 350, 365],
        "fully_selected_direct_static_site_count": 6,
        "unclassified_static_typed_map_set_site_count": 38,
        "shared_tx_count_static_site": helper_sites[0],
        "shared_tx_count_static_site_remains_residual": True,
        "expanded_map_write_invocation_count": 78,
        "new_selected_expanded_invocation_relative_wat_lines": newly_selected,
        "new_selected_expanded_invocation_count": 5,
        "cumulative_selected_expanded_invocation_relative_wat_lines": cumulative_selected,
        "cumulative_selected_expanded_invocation_count": 7,
        "residual_expanded_invocation_count": 71,
        "expanded_map_write_invocations_sha256": canonical_sha256(expanded),
        "direct_memory_write_sites_without_selected_payload_alias_proof": expected_writes,
        "reachable_graph_store_targets": inherited["reachable_graph_store_targets"],
        "all_other_reachable_typed_map_receiver_key_value_semantics_classified": False,
        "general_heap_alias_semantics_rederived": False,
    }


def prove_legacy_context(
    context: dict[str, Any], parent_proof: dict[str, Any]
) -> dict[str, Any]:
    require(parent_proof["mapping_cid"] == context["cid"], "Factory fee-growth parent mapping mismatch")
    direct = prove_direct_bigint_groups(context)
    shared = prove_shared_tx_count_helper_and_invocations(context)
    through_save = prove_same_receiver_through_save(context)
    residual = prove_residual_accounting(context, parent_proof)
    selected_by_field = {item["field"]: item for item in direct["selected_fields"]}
    selected_by_field["txCount"] = shared["field"]
    require(set(selected_by_field) == set(SELECTED_FIELDS), "legacy selected bigint field set drift")
    parent_native = parent_proof["native_start_and_g2"]
    require(
        parent_native["g2_unique_internal_writer_machine_proven"] is True
        and parent_native["numeric_zero_preserved_across_host_reset_lifecycle"] is False,
        "parent g2 boundary drift",
    )
    require(parent_proof["value_from_bigint"]["value_kind"] == 7, "parent Value.fromBigInt kind drift")
    require(parent_proof["typed_map_set"]["selected_field_mutation_proven"] is False, "parent TypedMap mutation boundary drift")
    return {
        "profile_id": context["profile"]["profile_id"],
        "mapping_cid": context["cid"],
        "control_generation": "legacy",
        "factory_fee_growth_parent_proof_sha256": canonical_sha256(parent_proof),
        "pool_entity_receiver_origin": parent_proof["pool_entity_receiver_origin"],
        "native_start_and_g2": parent_native,
        "value_from_bigint": parent_proof["value_from_bigint"],
        "typed_map_set": parent_proof["typed_map_set"],
        "direct_bigint_groups": direct,
        "shared_tx_count_helper_and_invocations": shared,
        "selected_fields": [selected_by_field[field] for field in SELECTED_FIELDS],
        "same_receiver_through_pool_save": through_save,
        "pool_save_capsule": parent_proof["pool_save_capsule"],
        "guard_and_return_boundaries": parent_proof["guard_and_return_boundaries"],
        "residual_accounting": residual,
        "selected_bigint_initialization_call_operand_flow_machine_proven": True,
        "legacy_selected_field_mutation_proven": False,
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
    require(parent_contract["contract_version"] == PARENT_CONTRACT_VERSION, "Factory fee-growth parent version drift")
    require(
        parent_contract["scope"]["cumulative_selected_field_count"] == 36
        and parent_contract["scope"]["cumulative_residual_field_count"] == 230,
        "parent 36/230 field ledger drift",
    )
    require(
        parent_contract["scope"]["factory_paths_closed_before_and_after"] == 14
        and parent_contract["scope"]["factory_paths_residual_before_and_after"] == 4,
        "parent 14/18 Factory closure drift",
    )
    contexts = parent_sources["legacy_contexts"]
    parent_proofs = parent_sources["legacy_proofs"]
    require(len(contexts) == 4 and len(parent_proofs) == 4, "four legacy parent contexts/proofs required")
    parent_by_cid = {proof["mapping_cid"]: proof for proof in parent_proofs}
    require(set(parent_by_cid) == {context["cid"] for context in contexts}, "legacy parent/context CID set drift")
    proofs = [prove_legacy_context(context, parent_by_cid[context["cid"]]) for context in contexts] if recompute_wat else []
    return {
        "factory_fee_growth_parent_contract": parent_contract,
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
    require(len(matches) == 1 and matches[0]["type"] == "BigInt!", f"v2 Pool.{field} catalog binding drift")
    return matches[0]


def _modern_selected_flows(proof: dict[str, Any]) -> dict[str, dict[str, Any]]:
    selected = {
        item["field"]: item
        for item in proof["field_contract"]["simple_global_value_flows"]
        if item["entity"] == "Pool" and item["field"] in SELECTED_FIELDS
    }
    require(set(selected) == set(SELECTED_FIELDS), f"{proof['profile_id']} modern selected bigint flow set drift")
    for field, flow in selected.items():
        require(
            flow["value"] == "ZERO_BI"
            and flow["value_kind"] == "BigInt"
            and flow["machine_proven"] is True
            and flow["set_binding"]["field_key"] == field
            and flow["set_binding"]["entity_receiver"] == "$l6"
            and flow["set_binding"]["value_kind_tag"] == 7
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
    require(len(legacy_by_cid) == 4 and len(modern_by_cid) == 2, "Factory bigint proof mapping inventory drift")
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
            require(cid in modern_by_cid, f"{segment['segment_id']} Factory mapping has no bigint proof: {cid}")
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
                    "schema_type": "BigInt!",
                    "population_classification": "conditional",
                    "initialization_value_source": (
                        "pointer returned by ByteArray.fromI32(0), stored in $g2, via Value.fromBigInt"
                        if generation == "legacy"
                        else "ZERO_BI"
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
            "factory_fee_growth_parent_contract_sha256": PARENT_CONTRACT_SHA256,
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
    require(len(results) == 8, "Factory bigint initialization segment count drift")
    require(legacy_count == 6 and modern_count == 2, "legacy/modern Factory bigint segment count drift")
    require(sum(len(item["semantic_surface"]["fields"]) for item in results) == 40, "Factory bigint field-record count drift")
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
        semantic_paths = PARENT.FEE_GROWTH.INITIALIZE.json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = PARENT.FEE_GROWTH.INITIALIZE.json_diff_paths(left["provenance_surface"], right["provenance_surface"])
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
    require(len(results) == 28, "Factory bigint initialization pairwise diff count drift")
    return results


def truth_boundary() -> dict[str, bool]:
    require(len(TRUE_FLAGS) == len(set(TRUE_FLAGS)), "duplicate true truth gate")
    require(len(FALSE_FLAGS) == len(set(FALSE_FLAGS)), "duplicate false truth gate")
    require(set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "truth gate overlap")
    return {**{name: True for name in TRUE_FLAGS}, **{name: False for name in FALSE_FLAGS}}


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["legacy_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 4, "four recomputed legacy bigint proofs required")
    parent_sources = sources["parent_sources"]
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
        {"fixture": "parent verifier/contract, canonical merge, CID, WASM/WAT, or handler authority", "expected_rejection_layer": "canonical parent and retained-artifact authority"},
        {"fixture": "direct key, receiver, g2 global, Value wrapper, group order, or set operands", "expected_rejection_layer": "four direct bigint call-operand flows"},
        {"fixture": "shared helper key/wrapper/parameter operands or selected Pool call operands", "expected_rejection_layer": "shared txCount helper and selected invocation"},
        {"fixture": "one of the three residual helper invocations or invocation count/order", "expected_rejection_layer": "complete shared txCount invocation inventory"},
        {"fixture": "return, structured control, receiver reassignment, or Pool save drift", "expected_rejection_layer": "same-receiver selected flow through Pool.save"},
        {"fixture": "static-site or expanded-invocation count, selected index, shared-site classification, reachable helper, direct write, or store target", "expected_rejection_layer": "direct-site/shared-invocation residual accounting"},
        {"fixture": "missing, duplicate, or mis-profiled segment/field/diff record", "expected_rejection_layer": "eight-segment deterministic projection"},
        {"fixture": "promoted mutation, persistence, shared-site, issue, readiness, 36/230, or 14/18 gate", "expected_rejection_layer": "strict truth and refusal boundary"},
        {"fixture": "duplicate JSON key", "expected_rejection_layer": "strict JSON loader"},
    ]
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "retained-wat-factory-pool-bigint-initialization-call-flow-certificate",
        "scope": {
            "networks": ["mainnet", "base"],
            "handler": HANDLER_ID,
            "unique_legacy_mapping_count": 4,
            "legacy_mapping_field_flow_count": 20,
            "legacy_segment_count": 6,
            "legacy_segment_field_call_flow_record_count": 30,
            "modern_parent_segment_count": 2,
            "modern_parent_field_record_count": 10,
            "segment_count": 8,
            "selected_fields": [f"Pool.{field}" for field in SELECTED_FIELDS],
            "selected_field_count": 5,
            "total_initialization_record_count": 40,
            "pairwise_scoped_diff_count": 28,
            "legacy_factory_field_call_flow_capsules_before": 2,
            "legacy_factory_field_call_flow_capsules_after": 7,
            "legacy_factory_fields_without_call_flow_capsules_after": 53,
            "all_sixty_complete_legacy_field_contracts_proven": False,
            "cumulative_selected_field_count": 36,
            "cumulative_residual_field_count": 230,
            "factory_upstream_path_count": 18,
            "factory_paths_closed_before_and_after": 14,
            "factory_paths_residual_before_and_after": 4,
            "legacy_complete_static_paths_newly_closed": 0,
            "retained_static_typed_map_set_site_count": 44,
            "cumulative_fully_selected_direct_static_site_count": 6,
            "cumulative_unclassified_static_site_count": 38,
            "retained_expanded_map_write_invocation_count": 78,
            "cumulative_selected_expanded_invocation_count": 7,
            "cumulative_residual_expanded_invocation_count": 71,
            "shared_tx_count_static_site_remains_residual": True,
            "reachable_effect_residuals_by_profile": residuals,
            "claim": "exact retained-WAT conditional Factory.handlePoolCreated event-pool receiver, four direct Pool bigint g2-to-Value-to-TypedMap#set call-operand flows, one Pool txCount g2-to-shared-helper call whose exact key/wrapper/set operands are bound while its three other invocations and static site remain residual, and same-receiver Pool.save path across four unique legacy mappings projected to six legacy segments, composed with the recomputed two-segment modern parent; legacy mutation, persistence, complete static semantics, history, host behavior, and readiness remain false",
        },
        "source_contracts": {
            "factory_fee_growth_initialization": {
                "path": PARENT_CONTRACT_PATH.as_posix(),
                "raw_sha256": PARENT_CONTRACT_SHA256,
                "contract_version": PARENT_CONTRACT_VERSION,
            },
            "factory_fee_growth_initialization_verifier": {
                "path": PARENT_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(),
                "raw_sha256": PARENT_VERIFIER_SHA256,
            },
        },
        "authority_contract": {
            "semantic_authority": "four exact retained deployed legacy Factory WASM artifacts, checksum-pinned WABT 1.0.35 WAT projections, and the recomputed canonical Factory fee-growth initialization parent",
            "source_text_role": "corroboration only",
            "legacy_symbol_boundary": "the retained Factory#set:txCount symbol locates a linker-shared key/wrapper/set helper; its exact body and the selected $l1 invocation are authority, while the symbol name is not Pool entity authority",
            "g2_boundary": "$g2 has one exact inherited internal writer from ByteArray.fromI32(0), but numeric-zero preservation across host reset/lifecycle behavior is not asserted",
            "normal_continuation_boundary": "the selected flow is conditional on bypassing the excluded-pool return, both decimals returns, and all helper/import traps",
            "save_boundary": "all five selected call flows and Pool.save receive the same unreassigned entity local without a return, branch, structured control, or select in the selected pre-save region; legacy TypedMap mutation semantics, Graph persistence, and later overwrites remain open",
            "accounting_boundary": "six direct static TypedMap#set sites are fully selected after composing the fee-growth parent; the shared txCount static site remains among 38 residual sites because only one of its four expanded handler invocations is selected; seven of 78 expanded invocations are selected and 71 remain residual",
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
                "the shared txCount static TypedMap#set site remains residual because its Factory, token0, and token1 invocations are outside this selected Pool flow",
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
        require(path.is_file(), f"Factory Pool bigint initialization contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "Factory Pool bigint initialization contract byte rendering drift")
    require(actual == expected, "Factory Pool bigint initialization contract does not reproduce")
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
        PARENT.MODERN.VerificationError,
        PARENT.FEE_GROWTH.VerificationError,
        PARENT.EFFECTS.VerificationError,
        V2.VerificationError,
        WRITER.VerificationError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 Factory Pool bigint initialization v1: "
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
