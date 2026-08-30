#!/usr/bin/env python3
"""Generate and fail-closed verify Uniswap V3 Pool Burn TVL semantics v1."""

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
CONTRACT_PATH = Path("uniswap-v3/pool-burn/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-burn-semantics/v1"

INITIALIZE_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-initialize.py"
INITIALIZE_VERIFIER_SHA256 = "5de73a42431c0d26dea48c6c570a58626532be14288cd16da20bcd1f2710d21d"
INITIALIZE_CONTRACT_PATH = Path("uniswap-v3/pool-initialize/v1/contract.json")
INITIALIZE_CONTRACT_SHA256 = "63bbec1b3190f1ccd54f9c9cb9a29bbd5a7d730be0165a2277412ea0b3adea14"
INITIALIZE_CONTRACT_VERSION = "uniswap-v3-pool-initialize-semantics/v1"
POOL_RUNTIME_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-runtime.py"
POOL_RUNTIME_VERIFIER_SHA256 = "a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67"
POOL_RUNTIME_CONTRACT_PATH = Path("uniswap-v3/pool-runtime/v1/contract.json")
POOL_RUNTIME_CONTRACT_SHA256 = "66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53"
POOL_RUNTIME_CONTRACT_VERSION = "uniswap-v3-pool-runtime/v1"
V2_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
V2_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
V2_CONTRACT_VERSION = "uniswap-v3-segment-field-semantics/v2"

POOL_ABI_CID = "QmULRc8Ac1J6YFy11z7JRpyThb6f7nmL5mMTQvN7LKj2Vy"
POOL_ABI_PATH = Path(f"uniswap-v3/graft-ancestry/v1/artifacts/{POOL_ABI_CID}")
POOL_ABI_SHA256 = "df8064cbe381e7a929aa4e1a658ce3617daed0e871883bf29ced54112fdfdbfd"
POOL_ABI_BYTES = 19_634

HANDLER_ID = "Pool.handleBurn"
HANDLER_EXPORT = "handleBurn"
EVENT_PARAM_ARRAY_GET_CALL = (
    "~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get"
)
LEGACY_ENTITY_MAP_GET_CALL = (
    "~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_"
    "~lib/@graphprotocol/graph-ts/index/Value>#get"
)
LEGACY_ENTITY_MAP_SET_CALL = (
    "~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_"
    "~lib/@graphprotocol/graph-ts/index/Value>#set"
)
MODERN_ENTITY_MAP_GET_CALL = (
    "~lib/@graphprotocol/graph-ts/common/collections/TypedMap<~lib/string/String_"
    "~lib/@graphprotocol/graph-ts/common/value/Value>#get"
)
MODERN_ENTITY_MAP_SET_CALL = (
    "~lib/@graphprotocol/graph-ts/common/collections/TypedMap<~lib/string/String_"
    "~lib/@graphprotocol/graph-ts/common/value/Value>#set"
)
IMPORT_RE = re.compile(
    r'^\s*\(import "([^"]+)" "([^"]+)" '
    r'\(func \$([^\s()]+) \(type \$[^\s()]+\)\)\)$'
)

LEGACY_NUMERIC_HELPER_SHA256 = {
    "ByteArray.fromI32": "3ef30704c311054beff2e7feaec737e977c9f55e3128f77007ef5a8d138c8f1f",
    "BigInt#equals": "ad68b1ce95baa30fec201b599a55aa4f147e80643c516f73bd26c0a09caccf0c",
    "BigInt#lt": "4cd5074083d7356adf5c137f98c8adf77a78d6249577ab6e7c3ed89d8f1fef38",
    "BigInt.compare": "511b692322ede6df7adc6e8825919a41e028a9176eddde9710ce16f9e41d1174",
    "BigInt#plus": "f9096f1036f36d4ccc9af02fcf2f2f13631329de1782655198bec19eda93782c",
    "BigDecimal#constructor": "1cffd647941ea13dfba288a8c6e115a2f144952a3b474ffc9ab43a0cecc81ca2",
    "BigDecimal#times": "f16b6b432620d3c56c4f7550b2eb6ebf0579c99b7dec454a20c0ebf33aaa6e69",
    "BigDecimal#div": "099296ff4334fd7e8006725685302edd3d570f818682a8666675696b2ca73cd1",
    "BigDecimal#minus": "a402f5b8b04aca0b2985485f540da97769b65efa00a313b10f01e3ee8ad08368",
}

MODERN_SHARED_NUMERIC_HELPER_SHA256 = {
    "BigInt.fromI32": "4c114555a1593f084d3017c8c8505e8f8bfd8e7a8e20409c995ba021c7178803",
    "BigInt.compare": "1686709026db196b2177276a59801ae36a7226d4bad1b30a01f48463890d205c",
    "BigInt#toBigDecimal": "cabab8133658475d11ab1e6b7ac72f0bfcb98b0432e4722c6afb9f502ff00d03",
}

MODERN_PROFILE_NUMERIC_HELPER_SHA256 = {
    "modern-base": {
        "BigInt#plus": "ce69e6bea36cffaf55bb3abcd986928a5621feae3c529291d7cb360d5066c686",
        "BigDecimal#times": "d622508697dd0564ddd4e9facdb46e2c88b432844cd4adb238e166b5a58f6717",
        "BigDecimal#div": "7bccf10b6a8371332108ad381e8feafe7a506bbd8b8c13ab6f69bcdefae3db09",
        "BigDecimal#minus": "3b6ab77b2dde01bbf9f374f80a4c6b6a833166dec4ee6a2196403b252b9a991d",
    },
    "modern-mainnet": {
        "BigInt#plus": "c913d145a210b3aca85e0592a0581f0d6b9a781e28a1fb190eb34389da8b995e",
        "BigDecimal#times": "877ff4ba7f342224cdff63df21e2d4a75886242cfda14b53702ee8a875970c46",
        "BigDecimal#div": "cf5f11e6381ed571ab1c21efc19d1ee6c5678f0301478b87f682baa5c3b3c8f0",
        "BigDecimal#minus": "6f692dd396707a6dceb274ae18ff00f9c5f8dc39e03159c2f136a6797efa28e6",
    },
}

SELECTED_FIELDS = {
    "totalValueLockedToken0": {
        "schema_type": "BigDecimal!",
        "event_parameter_index": 4,
        "event_parameter_name": "amount0",
        "event_parameter_type": "uint256",
        "pool_token_field": "token0",
    },
    "totalValueLockedToken1": {
        "schema_type": "BigDecimal!",
        "event_parameter_index": 5,
        "event_parameter_name": "amount1",
        "event_parameter_type": "uint256",
        "pool_token_field": "token1",
    },
}

TRUE_FLAGS = (
    "v2_contract_recomputed_and_pinned",
    "initialize_contract_recomputed_and_pinned",
    "pool_runtime_contract_recomputed_and_pinned",
    "all_eight_pool_runtime_capsules_recomputed_against_same_wat",
    "shared_pool_burn_abi_verified",
    "all_eight_pool_mapping_wat_bindings_verified",
    "all_eight_pool_burn_load_identities_proven",
    "all_eight_pool_burn_token_decimal_flows_proven",
    "all_eight_pool_burn_decimal_conversion_flows_proven",
    "all_eight_pool_burn_old_value_subtraction_flows_proven",
    "all_eight_pool_burn_setter_value_flows_proven",
    "both_modern_two_token_guard_selected_update_skip_paths_proven",
    "all_eight_selected_update_paths_save_same_pool_after_selected_setters_proven",
    "all_sixteen_explicit_selected_setter_callsites_bound",
    "all_eight_reachable_burn_mutation_inventories_bound",
    "all_eight_transitive_pool_store_closures_proven",
    "all_sixteen_segment_field_call_flow_evidence_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "cumulative_selected_field_count_remains_36",
    "cumulative_residual_field_count_remains_230",
)

FALSE_FLAGS = (
    "pool_non_flash_handler_semantics_complete",
    "pool_mint_semantics_complete",
    "pool_burn_semantics_complete",
    "pool_swap_semantics_complete",
    "pool_complete_entity_history",
    "selected_pool_tvl_complete_entity_history",
    "all_manifest_handler_field_semantics_complete",
    "all_stored_fields_exact",
    "all_pairwise_complete_writer_semantic_diffs_present",
    "contract_call_semantics_complete_for_all_handlers",
    "tick_helper_semantics_complete",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "graph_handler_rollback_proven_by_retained_wat",
    "post_fatal_execution_modeled",
    "bytes_to_hex_host_semantics_rederived",
    "numeric_host_semantics_rederived",
    "graph_store_host_semantics_rederived",
    "imported_host_semantics_rederived",
    "general_heap_alias_semantics_rederived",
    "direct_selected_payload_alias_safety_rederived",
    "no_later_selected_field_overwrites_proven",
    "pool_burn_selected_tvl_persistence_proven",
    "pool_burn_selected_tvl_structural_wat_projection_complete",
    "cross_handler_allocator_freshness_proven",
    "runtime_population_complete",
    "boundary_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "writer_package_consumes_projection",
    "checkpoint_authority",
    "backfill_ready",
    "production_ready",
)


class VerificationError(RuntimeError):
    pass


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


def load_json_strict(path: Path) -> Any:
    try:
        return json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error


def load_module(name: str, path: Path, digest: str) -> Any:
    require(path.is_file(), f"required verifier missing: {path}")
    require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INITIALIZE = load_module(
    "uniswap_v3_pool_initialize_for_pool_burn",
    INITIALIZE_VERIFIER_PATH,
    INITIALIZE_VERIFIER_SHA256,
)
POOL_RUNTIME = load_module(
    "uniswap_v3_pool_runtime_for_pool_burn",
    POOL_RUNTIME_VERIFIER_PATH,
    POOL_RUNTIME_VERIFIER_SHA256,
)
V2 = INITIALIZE.V2
WRITER = INITIALIZE.WRITER

POOL_RUNTIME_SPEC_BY_CID = {
    spec.cid: spec
    for spec in (*POOL_RUNTIME.PROFILE_SPECS, *POOL_RUNTIME.LEGACY_PROFILE_SPECS)
}


def normalized(line: str) -> str:
    return INITIALIZE.normalized(line)


def call_name(line: str) -> str | None:
    return INITIALIZE.call_name(line)


def local_name(line: str, operation: str = "get") -> str | None:
    return INITIALIZE.local_name(line, operation)


def decoded_constant(line: str, memory: bytearray) -> str | None:
    return INITIALIZE.decoded_constant(line, memory)


def function_sha256(function: Any) -> str:
    return INITIALIZE.function_sha256(function)


def wat_slice_sha256(function: Any, start: int, end_inclusive: int) -> str:
    return INITIALIZE.wat_slice_sha256(function, start, end_inclusive)


def single_call(function: Any, suffix: str, field: str) -> int:
    return INITIALIZE.single_call(function, suffix, field)


def single_suffix_function(functions: dict[str, Any], suffix: str, field: str) -> Any:
    return INITIALIZE.single_suffix_function(functions, suffix, field)


def require_instruction(function: Any, index: int, expected: str, field: str) -> None:
    INITIALIZE.require_instruction(function, index, expected, field)


def require_call(function: Any, index: int, suffix: str, field: str) -> None:
    INITIALIZE.require_call(function, index, suffix, field)


def require_exact_call(function: Any, index: int, expected: str, field: str) -> None:
    INITIALIZE.require_exact_call(function, index, expected, field)


def no_reassignment(function: Any, local: str, start: int, end: int, field: str) -> None:
    INITIALIZE.require_no_local_reassignment(function, local, start, end, field)


def successful_no_reassignment(
    function: Any, local: str, start: int, end: int, field: str
) -> None:
    INITIALIZE.require_no_successful_path_local_reassignment(
        function, local, start, end, field
    )


def verify_pool_abi(root: Path, ancestry: dict[str, Any]) -> dict[str, Any]:
    path = root / POOL_ABI_PATH
    require(path.is_file(), f"Pool ABI missing: {POOL_ABI_PATH}")
    require(path.stat().st_size == POOL_ABI_BYTES, "Pool ABI byte length drift")
    require(raw_sha256(path) == POOL_ABI_SHA256, "Pool ABI digest drift")
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    require(POOL_ABI_CID in artifacts, "Pool ABI absent from retained ancestry")
    artifact = artifacts[POOL_ABI_CID]
    require(
        (artifact["path"], artifact["sha256"], artifact["bytes"])
        == (str(POOL_ABI_PATH), POOL_ABI_SHA256, POOL_ABI_BYTES),
        "Pool ABI ancestry binding drift",
    )
    value = load_json_strict(path)
    matches = [
        item
        for item in value
        if item.get("type") == "event" and item.get("name") == "Burn"
    ]
    require(len(matches) == 1, "Pool ABI Burn event count drift")
    expected = {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "owner", "type": "address"},
            {"indexed": True, "internalType": "int24", "name": "tickLower", "type": "int24"},
            {"indexed": True, "internalType": "int24", "name": "tickUpper", "type": "int24"},
            {"indexed": False, "internalType": "uint128", "name": "amount", "type": "uint128"},
            {"indexed": False, "internalType": "uint256", "name": "amount0", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "amount1", "type": "uint256"},
        ],
        "name": "Burn",
        "type": "event",
    }
    require(matches[0] == expected, "Pool ABI Burn signature drift")
    return {
        "cid": POOL_ABI_CID,
        "path": str(POOL_ABI_PATH),
        "bytes": POOL_ABI_BYTES,
        "sha256": POOL_ABI_SHA256,
        "event": expected,
    }


def prove_schema_value_decoder(
    context: dict[str, Any], conversion: str, expected_kind: int
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    namespace = (
        "~lib/@graphprotocol/graph-ts/common/value/Value"
        if generation == "modern"
        else "~lib/@graphprotocol/graph-ts/index/Value"
    )
    helper = single_suffix_function(
        context["functions"],
        f"{namespace}#{conversion}",
        f"{cid} schema Value#{conversion}",
    )
    string_decoder = conversion == "toString"
    expected_length = 14 if string_decoder else 16
    require(len(helper.lines) == expected_length, f"{cid} Value#{conversion} shape")
    require_instruction(helper, 1, "local.get $p0", f"{cid} Value#{conversion} kind receiver")
    require_instruction(helper, 2, "i32.load", f"{cid} Value#{conversion} kind load")
    if string_decoder:
        guard = 3
    else:
        require_instruction(
            helper,
            3,
            f"i32.const {expected_kind}",
            f"{cid} Value#{conversion} expected kind",
        )
        require_instruction(helper, 4, "i32.ne", f"{cid} Value#{conversion} kind mismatch")
        guard = 5
    require(normalized(helper.lines[guard]).startswith("if "), f"{cid} Value#{conversion} guard")
    guard_end = V2.matching_wat_end(helper.lines, guard, f"{cid} Value#{conversion} guard")
    payload_start = guard_end + 1
    require(
        payload_start + 2 == len(helper.lines) - 1,
        f"{cid} Value#{conversion} payload position",
    )
    aborts = [
        index
        for index in range(guard + 1, guard_end)
        if (call_name(helper.lines[index]) or "").endswith(
            ("builtins/abort", "env/abort")
        )
    ]
    require(len(aborts) == 1, f"{cid} Value#{conversion} mismatch abort count")
    require(
        INITIALIZE.effect_is_confined_to_closed_trap_branch(
            helper, aborts[0], payload_start
        ),
        f"{cid} Value#{conversion} mismatch branch does not trap",
    )
    require_instruction(
        helper,
        payload_start,
        "local.get $p0",
        f"{cid} Value#{conversion} payload receiver",
    )
    require_instruction(
        helper,
        payload_start + 1,
        "i64.load offset=8",
        f"{cid} Value#{conversion} payload load",
    )
    require(
        normalized(helper.lines[payload_start + 2]).startswith("i32.wrap_i64"),
        f"{cid} Value#{conversion} payload pointer narrowing",
    )
    no_reassignment(helper, "$p0", 0, payload_start, f"{cid} Value#{conversion} receiver")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "expected_value_kind": expected_kind,
        "receiver_parameter": "$p0",
        "mismatch_branch_traps": True,
        "payload_load": "i64.load offset=8 then i32.wrap_i64",
        "typed_value_to_payload_pointer_machine_proven": True,
    }


def prove_event_value_to_bigint(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    helper = single_suffix_function(
        context["functions"],
        "chain/ethereum/ethereum.Value#toBigInt",
        f"{cid} event Value#toBigInt",
    )
    expected_length = 25 if generation == "modern" else 27
    require(len(helper.lines) == expected_length, f"{cid} event Value#toBigInt shape")
    require_instruction(helper, 2 if generation == "legacy" else 1, "local.get $p0", f"{cid} event Value kind receiver")
    kind_start = 3 if generation == "legacy" else 2
    require_instruction(helper, kind_start, "i32.load", f"{cid} event Value kind load")
    require_instruction(helper, kind_start + 1, "i32.const 3", f"{cid} event Value uint kind")
    require_instruction(helper, kind_start + 2, "i32.eq", f"{cid} event Value uint comparison")
    if generation == "legacy":
        require(local_name(helper.lines[6], "tee") is not None, f"{cid} event Value kind local")
        first_guard = 7
        require_instruction(helper, 8, f"local.get {local_name(helper.lines[6], 'tee')}", f"{cid} event Value uint branch")
        signed_receiver = 10
    else:
        first_guard = 5
        require_instruction(helper, 6, "i32.const 1", f"{cid} event Value uint branch")
        signed_receiver = 8
    require(normalized(helper.lines[first_guard]).startswith("if "), f"{cid} event Value kind union")
    first_end = V2.matching_wat_end(helper.lines, first_guard, f"{cid} event Value kind union")
    require_instruction(helper, signed_receiver, "local.get $p0", f"{cid} event Value int receiver")
    require_instruction(helper, signed_receiver + 1, "i32.load", f"{cid} event Value int kind load")
    require_instruction(helper, signed_receiver + 2, "i32.const 4", f"{cid} event Value int kind")
    require_instruction(helper, signed_receiver + 3, "i32.eq", f"{cid} event Value int comparison")
    require(first_end == signed_receiver + 4, f"{cid} event Value kind union end")
    require_instruction(helper, first_end + 1, "i32.eqz", f"{cid} event Value invalid kind")
    trap_guard = first_end + 2
    require(normalized(helper.lines[trap_guard]).startswith("if "), f"{cid} event Value invalid guard")
    trap_end = V2.matching_wat_end(helper.lines, trap_guard, f"{cid} event Value invalid guard")
    payload_start = trap_end + 1
    aborts = [
        index
        for index in range(trap_guard + 1, trap_end)
        if (call_name(helper.lines[index]) or "").endswith(
            ("builtins/abort", "env/abort")
        )
    ]
    require(len(aborts) == 1, f"{cid} invalid event Value abort count")
    require(
        INITIALIZE.effect_is_confined_to_closed_trap_branch(
            helper, aborts[0], payload_start
        ),
        f"{cid} invalid event Value does not trap",
    )
    require(payload_start + 2 == len(helper.lines) - 1, f"{cid} event Value payload position")
    require_instruction(helper, payload_start, "local.get $p0", f"{cid} event Value payload receiver")
    require_instruction(helper, payload_start + 1, "i64.load offset=8", f"{cid} event Value payload load")
    require(
        normalized(helper.lines[payload_start + 2]).startswith("i32.wrap_i64"),
        f"{cid} event Value payload pointer narrowing",
    )
    no_reassignment(helper, "$p0", 0, payload_start, f"{cid} event Value receiver")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "accepted_event_value_kinds": [3, 4],
        "receiver_parameter": "$p0",
        "invalid_kind_branch_traps": True,
        "payload_load": "i64.load offset=8 then i32.wrap_i64",
        "typed_event_value_to_bigint_pointer_machine_proven": True,
    }


def burn_context_from_initialize(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    analysis = context["analysis"]
    handler = WRITER.resolve_handler(context["functions"], context["exports"], HANDLER_EXPORT)
    require(
        handler.name == analysis["registered_handler_export_targets"][HANDLER_EXPORT],
        f"Burn export target drift: {cid}",
    )
    binding = analysis["registered_handlers"][HANDLER_EXPORT]
    require(function_sha256(handler) == binding["body_sha256"], f"Burn body drift: {cid}")
    require(handler.function_index == binding["wat_function_index"], f"Burn index drift: {cid}")
    return {**context, "handler": handler}


def prove_runtime_for_burn_context(context: dict[str, Any]) -> dict[str, Any]:
    """Re-run the public Pool runtime capsule against this exact WAT context."""
    cid = context["mapping_cid"]
    require(cid in POOL_RUNTIME_SPEC_BY_CID, f"{cid} Pool runtime spec missing")
    spec = POOL_RUNTIME_SPEC_BY_CID[cid]
    require(
        context["profile"]["profile_id"] == spec.profile_id,
        f"{cid} Pool runtime profile drift",
    )
    require(
        (
            context["analysis"]["bytes"],
            context["analysis"]["sha256"],
            context["analysis"]["wat_sha256"],
        )
        == (spec.wasm_bytes, spec.wasm_sha256, spec.wat_sha256),
        f"{cid} Pool runtime artifact tuple drift",
    )
    runtime_context = {
        "cid": cid,
        "profile": {"profile_id": spec.profile_id},
        "spec": spec,
        "artifact_path": context["artifact_path"],
        "functions": context["functions"],
        "exports": context["exports"],
        "module_text": context["wat_text"],
        "wat_line_count": len(context["wat_text"].splitlines()),
        "initialized_data": POOL_RUNTIME.initialized_data_inventory(context["wat_text"]),
    }
    proof = (
        POOL_RUNTIME.prove_pool_runtime_context(runtime_context)
        if spec.profile_id.startswith("modern-")
        else POOL_RUNTIME.prove_legacy_pool_runtime_context(runtime_context)
    )
    require(
        proof["artifact_selection_tuple"]
        == [spec.profile_id, cid, spec.wasm_sha256, spec.wat_sha256],
        f"{cid} Pool runtime proof tuple drift",
    )
    capsule = proof["public_collection_capsule"]
    closed_key = (
        "modern_collection_capsule_structurally_closed"
        if spec.profile_id.startswith("modern-")
        else "legacy_collection_capsule_structurally_closed"
    )
    require(capsule[closed_key] is True, f"{cid} Pool runtime capsule not closed")
    return proof


def prove_bytes_to_hex_import(context: dict[str, Any], function: str) -> dict[str, Any]:
    """Bind the exact Graph bytesToHex host import used for Pool identity."""
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    expected = (
        (
            "conversion",
            "typeConversion.bytesToHex",
            "~lib/@graphprotocol/graph-ts/common/conversion/typeConversion.bytesToHex",
        )
        if generation == "modern"
        else (
            "index",
            "typeConversion.bytesToHex",
            "~lib/@graphprotocol/graph-ts/index/typeConversion.bytesToHex",
        )
    )
    matches = [
        match.groups()
        for line in context["wat_text"].splitlines()
        if (match := IMPORT_RE.match(line)) is not None
        and match.group(2) == "typeConversion.bytesToHex"
    ]
    require(matches == [expected], f"{cid} bytesToHex host import drift")
    require(function == expected[2], f"{cid} Pool identity uses a different bytesToHex import")
    return {
        "module": expected[0],
        "name": expected[1],
        "function": expected[2],
        "exact_import_and_call_target_machine_proven": True,
        "host_bytes_to_hex_semantics_rederived": False,
    }


def prove_pool_load(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    memory = context["memory"]
    functions = context["functions"]
    if generation == "legacy":
        load = single_call(handler, "schema/Pool.load", f"{cid} Burn Pool.load")
        require(load >= 4 and load + 1 < len(handler.lines), f"{cid} Pool.load bounds")
        require_instruction(handler, load - 4, "local.get $p0", f"{cid} Burn event address")
        require_instruction(handler, load - 3, "i32.load", f"{cid} Burn event address")
        require_call(handler, load - 2, "typeConversion.bytesToHex", f"{cid} Burn address conversion")
        id_local = local_name(handler.lines[load - 1], "tee")
        require(id_local is not None, f"{cid} Pool ID local missing")
        pool_local = local_name(handler.lines[load + 1], "set")
        require(pool_local is not None, f"{cid} Pool local missing")
        no_reassignment(handler, "$p0", 0, load - 4, f"{cid} original Burn event")
        depths = V2.wat_control_depths(handler.lines)
        require(depths[load] == depths[load + 1] == 0, f"{cid} legacy Pool load conditional")
        helper = single_suffix_function(functions, "schema/Pool.load", f"{cid} Pool.load helper")
        require(len(helper.lines) == 4, f"{cid} Pool.load helper shape")
        require(decoded_constant(helper.lines[1], memory) == "Pool", f"{cid} Pool.load target")
        require_instruction(helper, 2, "local.get $p0", f"{cid} Pool.load ID")
        require_call(helper, 3, "index/store.get", f"{cid} Pool.load store.get")
        return {
            "generation": generation,
            "event_parameter": "$p0",
            "event_address_load": "i32.load offset 0",
            "address_conversion": call_name(handler.lines[load - 2]),
            "address_conversion_import": prove_bytes_to_hex_import(
                context, call_name(handler.lines[load - 2]) or ""
            ),
            "entity_target": "Pool",
            "pool_id_local": id_local,
            "pool_entity_local": pool_local,
            "handler_load_wat_line": handler.start_line + load,
            "helper_function": helper.name,
            "helper_body_sha256": function_sha256(helper),
            "event_address_to_pool_load_machine_proven": True,
            "missing_pool_behavior_proven": False,
        }

    candidates = []
    for index, line in enumerate(handler.lines):
        if (call_name(line) or "").endswith("index/store.get") and index >= 5:
            if decoded_constant(handler.lines[index - 5], memory) == "Pool":
                candidates.append(index)
    require(len(candidates) == 1, f"{cid} modern Pool store.get count")
    load = candidates[0]
    require_instruction(handler, load - 4, "local.get $p0", f"{cid} Burn event address")
    require_instruction(handler, load - 3, "i32.load", f"{cid} Burn event address")
    require_call(handler, load - 2, "typeConversion.bytesToHex", f"{cid} Burn address conversion")
    id_local = local_name(handler.lines[load - 1], "tee")
    require(id_local is not None, f"{cid} modern Pool ID local missing")
    pool_local = local_name(handler.lines[load + 1], "tee")
    require(pool_local is not None, f"{cid} modern Pool local missing")
    require_instruction(handler, load + 2, "i32.eqz", f"{cid} missing Pool check")
    require(normalized(handler.lines[load + 3]).startswith("if "), f"{cid} missing Pool branch")
    branch_end = V2.matching_wat_end(handler.lines, load + 3, f"{cid} missing Pool branch")
    branch = [normalized(line) for line in handler.lines[load + 4 : branch_end]]
    require(
        any((call_name(line) or "").endswith("builtins/abort") for line in handler.lines[load + 4 : branch_end])
        and "unreachable" in branch,
        f"{cid} missing Pool branch can continue",
    )
    require(
        not any(item in {"else", "return"} or re.match(r"^br(?:_if|_table)?\b", item) for item in branch),
        f"{cid} missing Pool branch can bypass abort",
    )
    return {
        "generation": generation,
        "event_parameter": "$p0",
        "event_address_load": "i32.load offset 0",
        "address_conversion": call_name(handler.lines[load - 2]),
        "address_conversion_import": prove_bytes_to_hex_import(
            context, call_name(handler.lines[load - 2]) or ""
        ),
        "entity_target": "Pool",
        "pool_id_local": id_local,
        "pool_entity_local": pool_local,
        "handler_load_wat_line": handler.start_line + load,
        "missing_pool_branch_wat_lines": [handler.start_line + load + 2, handler.start_line + branch_end],
        "missing_pool_branch_aborts_before_normal_continuation": True,
        "event_address_to_pool_load_machine_proven": True,
        "missing_pool_behavior_proven": True,
    }


def prove_schema_string_getter(
    context: dict[str, Any], entity: str, field: str
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    helper = single_suffix_function(
        context["functions"], f"schema/{entity}#get:{field}", f"{cid} {entity}.{field} getter"
    )
    memory = context["memory"]
    require_instruction(helper, 1, "local.get $p0", f"{cid} {entity}.{field} receiver")
    require(decoded_constant(helper.lines[2], memory) == field, f"{cid} {entity}.{field} key")
    map_get = MODERN_ENTITY_MAP_GET_CALL if generation == "modern" else LEGACY_ENTITY_MAP_GET_CALL
    require_exact_call(helper, 3, map_get, f"{cid} {entity}.{field} map get")
    conversion_index = len(helper.lines) - (2 if generation == "modern" else 1)
    require_call(helper, conversion_index, "Value#toString", f"{cid} {entity}.{field} string")
    if generation == "modern":
        require(local_name(helper.lines[4], "tee") == "$p0", f"{cid} {entity}.{field} map value")
        require_instruction(helper, conversion_index - 1, "local.get $p0", f"{cid} {entity}.{field} decoder input")
        successful_no_reassignment(
            helper, "$p0", 4, conversion_index - 1, f"{cid} {entity}.{field} map value"
        )
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "field_key": field,
        "receiver_parameter": "$p0",
        "value_decoder": prove_schema_value_decoder(context, "toString", 0),
        "receiver_key_to_string_machine_proven": True,
    }


def prove_token_loads_and_guard(
    context: dict[str, Any], pool: dict[str, Any]
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    memory = context["memory"]
    pool_local = pool["pool_entity_local"]
    token_getters = {
        field: prove_schema_string_getter(context, "Pool", field)
        for field in ("token0", "token1")
    }
    if generation == "legacy":
        calls: dict[str, int] = {}
        for field in ("token0", "token1"):
            matches = [
                index
                for index, line in enumerate(handler.lines[:-1])
                if (call_name(line) or "").endswith(f"schema/Pool#get:{field}")
                and (call_name(handler.lines[index + 1]) or "").endswith("schema/Token.load")
            ]
            require(len(matches) == 1, f"{cid} Pool.{field} Token.load source count")
            calls[field] = matches[0]
        token_locals: dict[str, str] = {}
        token_assignments: dict[str, int] = {}
        for field in ("token0", "token1"):
            index = calls[field]
            require(local_name(handler.lines[index - 1]) == pool_local, f"{cid} {field} Pool receiver")
            require_call(handler, index + 1, "schema/Token.load", f"{cid} {field} Token.load")
            local = local_name(handler.lines[index + 2], "set")
            require(local is not None, f"{cid} {field} Token local")
            token_locals[field] = local
            token_assignments[field] = index + 2
        helper = single_suffix_function(context["functions"], "schema/Token.load", f"{cid} Token.load")
        require(len(helper.lines) == 4, f"{cid} Token.load shape")
        require(decoded_constant(helper.lines[1], memory) == "Token", f"{cid} Token.load target")
        require_instruction(helper, 2, "local.get $p0", f"{cid} Token.load ID")
        require_call(helper, 3, "index/store.get", f"{cid} Token.load store.get")
        return {
            "token_entity_locals": token_locals,
            "token_entity_assignment_indices": token_assignments,
            "pool_token_getters": token_getters,
            "token_load_helper": {"function": helper.name, "body_sha256": function_sha256(helper)},
            "presence_guard": None,
            "selected_update_guard_start_index": None,
            "selected_update_guard_end_index": None,
            "missing_token_projection": "not proven for legacy mappings",
            "pool_token_id_to_token_load_machine_proven": True,
        }

    token_locals: dict[str, str] = {}
    token_assignments: dict[str, int] = {}
    store_gets: dict[str, int] = {}
    for field in ("token0", "token1"):
        matches = [
            index
            for index, line in enumerate(handler.lines[:-1])
            if (call_name(line) or "").endswith(f"schema/Pool#get:{field}")
            and (call_name(handler.lines[index + 1]) or "").endswith("index/store.get")
            and index >= 2
            and decoded_constant(handler.lines[index - 2], memory) == "Token"
        ]
        require(len(matches) == 1, f"{cid} Pool.{field} Token store.get source count")
        getter = matches[0]
        require(local_name(handler.lines[getter - 1]) == pool_local, f"{cid} {field} Pool receiver")
        require(decoded_constant(handler.lines[getter - 2], memory) == "Token", f"{cid} {field} Token target")
        require_call(handler, getter + 1, "index/store.get", f"{cid} {field} store.get")
        operation = "set" if field == "token0" else "tee"
        local = local_name(handler.lines[getter + 2], operation)
        require(local is not None, f"{cid} {field} Token local")
        token_locals[field] = local
        token_assignments[field] = getter + 2
        store_gets[field] = getter + 1
    token1_bind = store_gets["token1"] + 1
    require_instruction(handler, token1_bind + 1, "i32.const 0", f"{cid} token guard false value")
    require_instruction(handler, token1_bind + 2, f"local.get {token_locals['token0']}", f"{cid} token0 guard")
    require_instruction(handler, token1_bind + 3, "select", f"{cid} two-token select")
    guard_start = token1_bind + 4
    require(normalized(handler.lines[guard_start]).startswith("if "), f"{cid} token guard if")
    guard_end = V2.matching_wat_end(handler.lines, guard_start, f"{cid} two-token guard")
    require(normalized(handler.lines[guard_end]) in {"end", "end)"}, f"{cid} token guard end")
    depths = V2.wat_control_depths(handler.lines)
    require(
        not any(
            normalized(handler.lines[index]) == "else"
            and depths[index] == depths[guard_start] + 1
            for index in range(guard_start + 1, guard_end)
        ),
        f"{cid} token guard has an else effect",
    )
    return {
        "token_entity_locals": token_locals,
        "token_entity_assignment_indices": token_assignments,
        "pool_token_getters": token_getters,
        "token_load_helper": None,
        "presence_guard": {
            "condition": "Token[Pool.token0] != null && Token[Pool.token1] != null",
            "token0_local": token_locals["token0"],
            "token1_local": token_locals["token1"],
            "guard_wat_lines": [handler.start_line + guard_start, handler.start_line + guard_end],
            "missing_either_token_skips_entire_update_body": True,
        },
        "selected_update_guard_start_index": guard_start,
        "selected_update_guard_end_index": guard_end,
        "missing_token_call_flow": "the selected update and Pool.save body is skipped",
        "pool_token_id_to_token_load_machine_proven": True,
    }


def prove_numeric_constant_initializers(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    runtime = context.get("pool_runtime_proof") or prove_runtime_for_burn_context(context)
    if generation == "legacy":
        capsule = runtime["public_collection_capsule"]["native_start_and_constants"]
        state = runtime["native_start_module_state"]
        writers = state["complete_global_state"]["complete_global_set_inventory"]
        require(
            capsule["floor_constants_and_result_globals_structurally_proven"] is True
            and writers["$g2"] == [["start:src/utils/constants", 3]]
            and writers["$g3"] == [["start:src/utils/constants", 6]],
            f"{cid} legacy ZERO/ONE runtime closure drift",
        )
        return {
            "generation": generation,
            "initializer_function": capsule["constants_function"],
            "initializer_body_sha256": capsule["constants_body_sha256"],
            "module_start_function": capsule["native_start_function"],
            "zero_bigint_global": "$g2",
            "one_bigint_global": "$g3",
            "complete_global_writer_inventory_sha256": state["complete_global_state"][
                "complete_global_set_inventory_sha256"
            ],
            "runtime_capsule_authority": POOL_RUNTIME_CONTRACT_VERSION,
            "zero_and_one_initialization_machine_proven": True,
            "zero_and_one_all_writers_machine_proven": True,
        }

    start = runtime["start_and_allocator_floor"]
    state = start["module_state"]
    writers = state["complete_global_set_inventory"]
    require(
        state["critical_global_initializers_and_all_writers_machine_proven"] is True
        and writers["$src/utils/constants/ZERO_BI"] == [["~start", 15]]
        and writers["$src/utils/constants/ONE_BI"] == [["~start", 18]],
        f"{cid} modern ZERO/ONE runtime closure drift",
    )
    return {
        "generation": generation,
        "initializer_function": start["function"],
        "initializer_body_sha256": start["body_sha256"],
        "module_start_export": "_start",
        "zero_bigint_global": "$src/utils/constants/ZERO_BI",
        "one_bigint_global": "$src/utils/constants/ONE_BI",
        "complete_global_writer_inventory_sha256": state[
            "complete_global_set_inventory_sha256"
        ],
        "runtime_capsule_authority": POOL_RUNTIME_CONTRACT_VERSION,
        "zero_and_one_initialization_machine_proven": True,
        "zero_and_one_all_writers_machine_proven": True,
    }


def prove_numeric_trust_closure(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    profile_id = context["profile"]["profile_id"]
    if generation == "legacy":
        expected_helpers = LEGACY_NUMERIC_HELPER_SHA256
        module = "index"
        namespace = "~lib/@graphprotocol/graph-ts/index"
    else:
        expected_helpers = {
            **MODERN_SHARED_NUMERIC_HELPER_SHA256,
            **MODERN_PROFILE_NUMERIC_HELPER_SHA256[profile_id],
        }
        module = "numbers"
        namespace = "~lib/@graphprotocol/graph-ts/common/numbers"
    helpers: dict[str, dict[str, Any]] = {}
    for suffix, expected_digest in expected_helpers.items():
        helper = single_suffix_function(
            context["functions"], suffix, f"{cid} numeric helper {suffix}"
        )
        digest = function_sha256(helper)
        require(digest == expected_digest, f"{cid} numeric helper body drift: {suffix}")
        helpers[suffix] = {"function": helper.name, "body_sha256": digest}

    parsed_imports = [
        match.groups()
        for line in context["wat_text"].splitlines()
        if (match := IMPORT_RE.match(line)) is not None
    ]
    required_names = (
        "bigDecimal.fromString",
        "bigInt.plus",
        "bigDecimal.times",
        "bigDecimal.dividedBy",
        "bigDecimal.minus",
    )
    required_imports: list[dict[str, str]] = []
    for name in required_names:
        expected_symbol = f"{namespace}/{name}"
        matches = [
            symbol
            for found_module, found_name, symbol in parsed_imports
            if found_module == module and found_name == name
        ]
        require(matches == [expected_symbol], f"{cid} numeric host import drift: {name}")
        required_imports.append(
            {"module": module, "name": name, "function": expected_symbol}
        )
    return {
        "helper_bodies": helpers,
        "required_host_imports": required_imports,
        "all_selected_numeric_helper_bodies_digest_closed": True,
        "all_selected_numeric_host_imports_exact": True,
    }


def prove_decimal_conversion(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    functions = context["functions"]
    memory = context["memory"]
    constants = prove_numeric_constant_initializers(context)
    trust_closure = prove_numeric_trust_closure(context)
    conversion = single_suffix_function(
        functions, "src/utils/index/convertTokenToDecimal", f"{cid} decimal conversion"
    )
    exponent = single_suffix_function(
        functions, "src/utils/index/exponentToBigDecimal", f"{cid} exponent conversion"
    )
    division = single_suffix_function(
        functions, "BigDecimal#div", f"{cid} BigDecimal division"
    )
    require_instruction(division, len(division.lines) - 3, "local.get $p0", f"{cid} division left")
    require_instruction(division, len(division.lines) - 2, "local.get $p1", f"{cid} division right")
    require_call(
        division,
        len(division.lines) - 1,
        "bigDecimal.dividedBy",
        f"{cid} division host call",
    )
    require(
        len(division.lines) == (14 if generation == "modern" else 4),
        f"{cid} BigDecimal division shape",
    )
    if generation == "legacy":
        require(len(conversion.lines) == 14, f"{cid} legacy decimal conversion shape")
        require_instruction(conversion, 1, "local.get $p1", f"{cid} decimal exponent")
        require_instruction(
            conversion,
            2,
            f"global.get {constants['zero_bigint_global']}",
            f"{cid} decimal ZERO_BI",
        )
        require_call(conversion, 3, "BigInt#equals", f"{cid} zero decimal comparison")
        require(normalized(conversion.lines[4]).startswith("if "), f"{cid} zero decimal branch")
        require(
            V2.matching_wat_end(conversion.lines, 4, f"{cid} zero decimal branch") == 8,
            f"{cid} zero decimal branch closure",
        )
        require_instruction(conversion, 5, "local.get $p0", f"{cid} zero decimal amount")
        require_call(conversion, 6, "BigDecimal#constructor", f"{cid} zero decimal conversion")
        require_instruction(conversion, 7, "return", f"{cid} zero decimal return")
        require_instruction(conversion, 9, "local.get $p0", f"{cid} scaled decimal amount")
        require_call(conversion, 10, "BigDecimal#constructor", f"{cid} amount BigDecimal")
        require_instruction(conversion, 11, "local.get $p1", f"{cid} exponent input")
        require_call(conversion, 12, "exponentToBigDecimal", f"{cid} exponent helper")
        require_call(conversion, 13, "BigDecimal#div", f"{cid} decimal division")

        require(len(exponent.lines) == 25, f"{cid} legacy exponent helper shape")
        require(decoded_constant(exponent.lines[2], memory) == "1", f"{cid} exponent starts at one")
        require_call(exponent, 3, "bigDecimal.fromString", f"{cid} exponent one conversion")
        result_local = local_name(exponent.lines[4], "set")
        counter_local = local_name(exponent.lines[6], "set")
        require(result_local is not None and counter_local is not None, f"{cid} exponent locals")
        require_instruction(
            exponent,
            5,
            f"global.get {constants['zero_bigint_global']}",
            f"{cid} exponent counter zero",
        )
        require(normalized(exponent.lines[7]).startswith("loop "), f"{cid} exponent loop")
        require_instruction(exponent, 8, f"local.get {counter_local}", f"{cid} exponent counter")
        require_instruction(exponent, 9, "local.get $p0", f"{cid} exponent limit")
        require_call(exponent, 10, "BigInt#lt", f"{cid} exponent comparison")
        predicate_guard = 11
        require(
            normalized(exponent.lines[predicate_guard]).startswith("if "),
            f"{cid} exponent predicate guard",
        )
        predicate_end = V2.matching_wat_end(
            exponent.lines,
            predicate_guard,
            f"{cid} exponent predicate guard",
        )
        loop_end = predicate_end + 1
        require(
            predicate_end == 22
            and loop_end == 23
            and normalized(exponent.lines[loop_end]) == "end",
            f"{cid} exponent predicate/loop closure",
        )
        require(
            not any(
                normalized(line) == "else"
                for line in exponent.lines[predicate_guard + 1 : predicate_end]
            ),
            f"{cid} exponent predicate else path",
        )
        require(decoded_constant(exponent.lines[13], memory) == "10", f"{cid} exponent base ten")
        require_instruction(exponent, 12, f"local.get {result_local}", f"{cid} exponent product left")
        require_call(exponent, 14, "bigDecimal.fromString", f"{cid} exponent ten conversion")
        require_call(exponent, 15, "BigDecimal#times", f"{cid} exponent multiplication")
        require_instruction(exponent, 16, f"local.set {result_local}", f"{cid} exponent product result")
        require_instruction(exponent, 17, f"local.get {counter_local}", f"{cid} exponent increment left")
        require_instruction(
            exponent,
            18,
            f"global.get {constants['one_bigint_global']}",
            f"{cid} exponent counter one",
        )
        require_call(exponent, 19, "BigInt#plus", f"{cid} exponent counter increment")
        require_instruction(exponent, 20, f"local.set {counter_local}", f"{cid} exponent counter result")
        loop_label = normalized(exponent.lines[7]).split()[1]
        require_instruction(exponent, 21, f"br {loop_label}", f"{cid} exponent loop branch")
        require(
            local_name(exponent.lines[24]) == result_local,
            f"{cid} exponent result instruction drift at relative line 24",
        )
    else:
        require(len(conversion.lines) == 15, f"{cid} modern decimal conversion shape")
        require_instruction(conversion, 1, "local.get $p1", f"{cid} decimal exponent")
        require_instruction(
            conversion,
            2,
            f"global.get {constants['zero_bigint_global']}",
            f"{cid} decimal ZERO_BI",
        )
        require_call(conversion, 3, "BigInt.compare", f"{cid} zero decimal comparison")
        require_instruction(conversion, 4, "i32.eqz", f"{cid} zero decimal equality")
        require(normalized(conversion.lines[5]).startswith("if "), f"{cid} zero decimal branch")
        require(
            V2.matching_wat_end(conversion.lines, 5, f"{cid} zero decimal branch") == 9,
            f"{cid} zero decimal branch closure",
        )
        require_instruction(conversion, 6, "local.get $p0", f"{cid} zero decimal amount")
        require_call(conversion, 7, "BigInt#toBigDecimal", f"{cid} zero decimal conversion")
        require_instruction(conversion, 8, "return", f"{cid} zero decimal return")
        require_instruction(conversion, 10, "local.get $p0", f"{cid} scaled amount")
        require_call(conversion, 11, "BigInt#toBigDecimal", f"{cid} amount BigDecimal")
        require_instruction(conversion, 12, "local.get $p1", f"{cid} exponent input")
        require_call(conversion, 13, "exponentToBigDecimal", f"{cid} exponent helper")
        require_call(conversion, 14, "BigDecimal#div", f"{cid} decimal division")

        require(len(exponent.lines) == 27, f"{cid} modern exponent helper shape")
        require(decoded_constant(exponent.lines[2], memory) == "1", f"{cid} exponent starts at one")
        require_call(exponent, 3, "bigDecimal.fromString", f"{cid} exponent one conversion")
        result_local = local_name(exponent.lines[4], "set")
        counter_local = local_name(exponent.lines[6], "set")
        require(result_local is not None and counter_local is not None, f"{cid} exponent locals")
        require_instruction(
            exponent,
            5,
            f"global.get {constants['zero_bigint_global']}",
            f"{cid} exponent counter zero",
        )
        require(normalized(exponent.lines[7]).startswith("loop "), f"{cid} exponent loop")
        require_instruction(exponent, 8, f"local.get {counter_local}", f"{cid} exponent counter")
        require_instruction(exponent, 9, "local.get $p0", f"{cid} exponent limit")
        require_call(exponent, 10, "BigInt.compare", f"{cid} exponent comparison")
        require_instruction(exponent, 11, "i32.const -1", f"{cid} exponent less-than result")
        require_instruction(exponent, 12, "i32.eq", f"{cid} exponent comparison equality")
        predicate_guard = 13
        require(
            normalized(exponent.lines[predicate_guard]).startswith("if "),
            f"{cid} exponent predicate guard",
        )
        predicate_end = V2.matching_wat_end(
            exponent.lines,
            predicate_guard,
            f"{cid} exponent predicate guard",
        )
        loop_end = predicate_end + 1
        require(
            predicate_end == 24
            and loop_end == 25
            and normalized(exponent.lines[loop_end]) == "end",
            f"{cid} exponent predicate/loop closure",
        )
        require(
            not any(
                normalized(line) == "else"
                for line in exponent.lines[predicate_guard + 1 : predicate_end]
            ),
            f"{cid} exponent predicate else path",
        )
        require(decoded_constant(exponent.lines[15], memory) == "10", f"{cid} exponent base ten")
        require_instruction(exponent, 14, f"local.get {result_local}", f"{cid} exponent product left")
        require_call(exponent, 16, "bigDecimal.fromString", f"{cid} exponent ten conversion")
        require_call(exponent, 17, "BigDecimal#times", f"{cid} exponent multiplication")
        require_instruction(exponent, 18, f"local.set {result_local}", f"{cid} exponent product result")
        require_instruction(exponent, 19, f"local.get {counter_local}", f"{cid} exponent increment left")
        require_instruction(
            exponent,
            20,
            f"global.get {constants['one_bigint_global']}",
            f"{cid} exponent counter one",
        )
        require_call(exponent, 21, "BigInt#plus", f"{cid} exponent counter increment")
        require_instruction(exponent, 22, f"local.set {counter_local}", f"{cid} exponent counter result")
        loop_label = normalized(exponent.lines[7]).split()[1]
        require_instruction(exponent, 23, f"br {loop_label}", f"{cid} exponent loop branch")
        require(
            local_name(exponent.lines[26]) == result_local,
            f"{cid} exponent result instruction drift at relative line 26",
        )
    return {
        "conversion_function": conversion.name,
        "conversion_body_sha256": function_sha256(conversion),
        "exponent_function": exponent.name,
        "exponent_body_sha256": function_sha256(exponent),
        "division_function": division.name,
        "division_body_sha256": function_sha256(division),
        "numeric_constants": constants,
        "numeric_trust_closure": trust_closure,
        "predicate_guard_and_loop_exit_machine_proven": True,
        "zero_decimals_projection": "BigInt amount converted directly to BigDecimal",
        "nonzero_decimals_projection": "BigInt amount converted to BigDecimal and divided by 10^decimals",
        "amount_and_decimals_to_decimal_machine_proven": True,
    }


def prove_token_decimals_getter(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    helper = single_suffix_function(
        context["functions"], "schema/Token#get:decimals", f"{cid} Token.decimals getter"
    )
    memory = context["memory"]
    require_instruction(helper, 1, "local.get $p0", f"{cid} decimals receiver")
    require(decoded_constant(helper.lines[2], memory) == "decimals", f"{cid} decimals key")
    map_get = MODERN_ENTITY_MAP_GET_CALL if generation == "modern" else LEGACY_ENTITY_MAP_GET_CALL
    require_exact_call(helper, 3, map_get, f"{cid} decimals map get")
    conversion_index = len(helper.lines) - (2 if generation == "modern" else 1)
    require_call(helper, conversion_index, "Value#toBigInt", f"{cid} decimals BigInt")
    if generation == "legacy":
        require(len(helper.lines) == 5, f"{cid} legacy decimals getter shape")
    else:
        require(len(helper.lines) == 24, f"{cid} modern decimals getter shape")
        require(local_name(helper.lines[4], "tee") == "$p0", f"{cid} decimals map value")
        require_instruction(helper, conversion_index - 1, "local.get $p0", f"{cid} decimals decoder input")
        successful_no_reassignment(
            helper, "$p0", 4, conversion_index - 1, f"{cid} decimals map value"
        )
        require(
            any((call_name(line) or "").endswith("builtins/abort") for line in helper.lines),
            f"{cid} modern required decimals failure branch",
        )
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "field_key": "decimals",
        "receiver_parameter": "$p0",
        "value_decoder": prove_schema_value_decoder(context, "toBigInt", 7),
        "receiver_key_to_bigint_machine_proven": True,
    }


def prove_legacy_params_getter(
    context: dict[str, Any], suffix: str, expected_index: int, field: str
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    helper = single_suffix_function(context["functions"], suffix, f"{cid} Burn {field} getter")
    require(len(helper.lines) == 8, f"{cid} Burn {field} getter shape")
    require_instruction(helper, 1, "local.get $p0", f"{cid} Burn {field} wrapper")
    require_instruction(helper, 2, "i32.load", f"{cid} Burn {field} event")
    require_instruction(helper, 3, "i32.load offset=24", f"{cid} Burn {field} params")
    require_instruction(helper, 4, f"i32.const {expected_index}", f"{cid} Burn {field} index")
    require_exact_call(helper, 5, EVENT_PARAM_ARRAY_GET_CALL, f"{cid} Burn {field} lookup")
    require_instruction(helper, 6, "i32.load offset=4", f"{cid} Burn {field} value")
    require_call(helper, 7, "ethereum.Value#toBigInt", f"{cid} Burn {field} BigInt")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "event_parameter_index": expected_index,
        "event_parameter_name": field,
        "wrapper_to_bigint_machine_proven": True,
    }


def prove_amount_flows(
    context: dict[str, Any], tokens: dict[str, Any], conversion: dict[str, Any]
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    token_locals = tokens["token_entity_locals"]
    decimals = prove_token_decimals_getter(context)
    conversion_calls = [
        index
        for index, line in enumerate(handler.lines)
        if (call_name(line) or "").endswith("src/utils/index/convertTokenToDecimal")
    ]
    require(len(conversion_calls) == 2, f"{cid} Burn decimal conversion call count")
    fields = list(SELECTED_FIELDS)
    results: dict[str, Any] = {}
    if generation == "legacy":
        constructor = single_suffix_function(
            context["functions"],
            "Initialize__Params#constructor",
            f"{cid} Burn parameter wrapper",
        )
        require(len(constructor.lines) == 11, f"{cid} Burn wrapper shape")
        require_instruction(constructor, 2, "i32.const 4", f"{cid} Burn wrapper size")
        require_call(constructor, 3, "__memory_allocate", f"{cid} Burn wrapper allocation")
        wrapper_local = local_name(constructor.lines[4], "tee")
        require(wrapper_local is not None, f"{cid} Burn wrapper local")
        require_instruction(constructor, 5, "i32.const 0", f"{cid} Burn wrapper zero")
        require_instruction(constructor, 6, "i32.store", f"{cid} Burn wrapper initialization")
        require_instruction(
            constructor,
            7,
            f"local.get {wrapper_local}",
            f"{cid} Burn wrapper event-store receiver",
        )
        require_instruction(constructor, 8, "local.get $p0", f"{cid} Burn wrapper event")
        require_instruction(constructor, 9, "i32.store", f"{cid} Burn wrapper event store")
        require(
            local_name(constructor.lines[10]) == wrapper_local,
            f"{cid} Burn wrapper return identity",
        )
        no_reassignment(constructor, "$p0", 0, 9, f"{cid} Burn wrapper original event")
        getter_specs = {
            fields[0]: ("Mint__Params#get:amount", 4),
            fields[1]: ("Mint__Params#get:amount0", 5),
        }
        for ordinal, selected in enumerate(fields):
            call = conversion_calls[ordinal]
            getter_suffix, parameter_index = getter_specs[selected]
            require_instruction(handler, call - 5, "local.get $p0", f"{cid} {selected} event")
            require_call(handler, call - 4, "Initialize__Params#constructor", f"{cid} {selected} wrapper")
            require_call(handler, call - 3, getter_suffix, f"{cid} {selected} getter")
            token_field = SELECTED_FIELDS[selected]["pool_token_field"]
            require_instruction(
                handler,
                call - 2,
                f"local.get {token_locals[token_field]}",
                f"{cid} {selected} token receiver",
            )
            require_call(handler, call - 1, "schema/Token#get:decimals", f"{cid} {selected} decimals")
            successful_no_reassignment(
                handler,
                token_locals[token_field],
                tokens["token_entity_assignment_indices"][token_field],
                call - 2,
                f"{cid} {selected} loaded Token",
            )
            result_local = local_name(handler.lines[call + 1], "set")
            require(result_local is not None, f"{cid} {selected} decimal result local")
            getter = prove_legacy_params_getter(
                context, getter_suffix, parameter_index, SELECTED_FIELDS[selected]["event_parameter_name"]
            )
            results[selected] = {
                "event_parameter_index": parameter_index,
                "event_parameter_name": SELECTED_FIELDS[selected]["event_parameter_name"],
                "event_parameter_type": "uint256",
                "token_field": token_field,
                "token_entity_local": token_locals[token_field],
                "converted_amount_local": result_local,
                "handler_conversion_wat_line": handler.start_line + call,
                "parameter_getter": getter,
                "event_amount_and_matching_token_decimals_to_conversion_machine_proven": True,
            }
        return {
            "generation": generation,
            "event_parameter_wrapper": {
                "function": constructor.name,
                "body_sha256": function_sha256(constructor),
                "original_event_parameter": "$p0",
                "fresh_wrapper_local": wrapper_local,
                "event_to_returned_wrapper_machine_proven": True,
            },
            "token_decimals_getter": decimals,
            "event_value_to_bigint": prove_event_value_to_bigint(context),
            "decimal_conversion": conversion,
            "fields": results,
        }

    for ordinal, selected in enumerate(fields):
        call = conversion_calls[ordinal]
        parameter_index = SELECTED_FIELDS[selected]["event_parameter_index"]
        token_field = SELECTED_FIELDS[selected]["pool_token_field"]
        require_call(handler, call - 3, "ethereum.Value#toBigInt", f"{cid} {selected} BigInt")
        require_instruction(
            handler,
            call - 2,
            f"local.get {token_locals[token_field]}",
            f"{cid} {selected} token receiver",
        )
        require_call(handler, call - 1, "schema/Token#get:decimals", f"{cid} {selected} decimals")
        successful_no_reassignment(
            handler,
            token_locals[token_field],
            tokens["token_entity_assignment_indices"][token_field],
            call - 2,
            f"{cid} {selected} loaded Token",
        )
        event_get = call - 5
        require_exact_call(handler, event_get, EVENT_PARAM_ARRAY_GET_CALL, f"{cid} {selected} lookup")
        require_instruction(handler, event_get - 1, f"i32.const {parameter_index}", f"{cid} {selected} index")
        require_instruction(handler, event_get - 2, "i32.load offset=24", f"{cid} {selected} params")
        require_instruction(handler, event_get - 3, "i32.load", f"{cid} {selected} event")
        wrapper_local = local_name(handler.lines[event_get - 4])
        require(wrapper_local is not None, f"{cid} {selected} wrapper local")
        allocation = next(
            (
                index
                for index in range(max(0, event_get - 16), event_get - 4)
                if local_name(handler.lines[index], "tee") == wrapper_local
            ),
            None,
        )
        require(allocation is not None, f"{cid} {selected} wrapper allocation")
        require_instruction(handler, allocation - 3, "i32.const 4", f"{cid} {selected} wrapper size")
        require_instruction(handler, allocation - 2, "i32.const 54", f"{cid} {selected} wrapper runtime ID")
        require_call(handler, allocation - 1, "__new", f"{cid} {selected} wrapper allocation call")
        event_store = next(
            (
                index
                for index in range(allocation + 1, event_get - 4)
                if normalized(handler.lines[index]) == "local.get $p0"
                and index + 1 < event_get
                and normalized(handler.lines[index + 1]) == "i32.store"
            ),
            None,
        )
        require(event_store is not None, f"{cid} {selected} original event binding")
        successful_no_reassignment(
            handler,
            "$p0",
            0,
            event_store + 1,
            f"{cid} {selected} original event through wrapper store",
        )
        require_instruction(
            handler,
            event_store - 1,
            f"local.get {wrapper_local}",
            f"{cid} {selected} wrapper event-store receiver",
        )
        require_instruction(handler, event_store + 1, "i32.store", f"{cid} {selected} event store")
        require_instruction(
            handler,
            event_get - 4,
            f"local.get {wrapper_local}",
            f"{cid} {selected} wrapper lookup receiver",
        )
        no_reassignment(
            handler,
            wrapper_local,
            allocation,
            event_get - 4,
            f"{cid} {selected} event wrapper",
        )
        result_local = local_name(handler.lines[call + 1], "set")
        require(result_local is not None, f"{cid} {selected} decimal result local")
        results[selected] = {
            "event_parameter_index": parameter_index,
            "event_parameter_name": SELECTED_FIELDS[selected]["event_parameter_name"],
            "event_parameter_type": "uint256",
            "token_field": token_field,
            "token_entity_local": token_locals[token_field],
            "event_wrapper_local": wrapper_local,
            "converted_amount_local": result_local,
            "handler_conversion_wat_line": handler.start_line + call,
            "inline_original_event_to_parameter_bigint_machine_proven": True,
            "event_amount_and_matching_token_decimals_to_conversion_machine_proven": True,
        }
    return {
        "generation": generation,
        "event_parameter_wrapper": {
            "generation": "modern-inline",
            "original_event_parameter": "$p0",
            "inline_event_to_wrapper_bindings_machine_proven": True,
        },
        "token_decimals_getter": decimals,
        "event_value_to_bigint": prove_event_value_to_bigint(context),
        "decimal_conversion": conversion,
        "fields": results,
    }


def prove_bigdecimal_minus(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    helper = single_suffix_function(
        context["functions"], "BigDecimal#minus", f"{cid} BigDecimal subtraction"
    )
    require_instruction(helper, len(helper.lines) - 3, "local.get $p0", f"{cid} subtraction left")
    require_instruction(helper, len(helper.lines) - 2, "local.get $p1", f"{cid} subtraction right")
    require_call(helper, len(helper.lines) - 1, "bigDecimal.minus", f"{cid} subtraction host call")
    if generation == "legacy":
        require(len(helper.lines) == 4, f"{cid} legacy subtraction shape")
    else:
        require(len(helper.lines) == 14, f"{cid} modern subtraction shape")
        require(
            any((call_name(line) or "").endswith("builtins/abort") for line in helper.lines),
            f"{cid} modern null subtraction failure branch",
        )
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "left_parameter": "$p0",
        "right_parameter": "$p1",
        "host_operation": "bigDecimal.minus",
        "left_minus_right_machine_proven": True,
    }


def prove_pool_tvl_getter(context: dict[str, Any], field: str) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    helper = single_suffix_function(
        context["functions"], f"schema/Pool#get:{field}", f"{cid} Pool.{field} getter"
    )
    require_instruction(helper, 1, "local.get $p0", f"{cid} Pool.{field} receiver")
    require(decoded_constant(helper.lines[2], context["memory"]) == field, f"{cid} Pool.{field} key")
    map_get = MODERN_ENTITY_MAP_GET_CALL if generation == "modern" else LEGACY_ENTITY_MAP_GET_CALL
    require_exact_call(helper, 3, map_get, f"{cid} Pool.{field} map get")
    conversion_index = len(helper.lines) - (2 if generation == "modern" else 1)
    require_call(helper, conversion_index, "Value#toBigDecimal", f"{cid} Pool.{field} BigDecimal")
    require(len(helper.lines) == (24 if generation == "modern" else 5), f"{cid} Pool.{field} getter shape")
    if generation == "modern":
        require(local_name(helper.lines[4], "tee") == "$p0", f"{cid} Pool.{field} map value")
        require_instruction(helper, conversion_index - 1, "local.get $p0", f"{cid} Pool.{field} decoder input")
        successful_no_reassignment(
            helper, "$p0", 4, conversion_index - 1, f"{cid} Pool.{field} map value"
        )
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "field_key": field,
        "receiver_parameter": "$p0",
        "value_decoder": prove_schema_value_decoder(context, "toBigDecimal", 2),
        "receiver_key_to_bigdecimal_machine_proven": True,
    }


def prove_value_from_bigdecimal(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    helper = single_suffix_function(
        context["functions"], "Value.fromBigDecimal", f"{cid} Value.fromBigDecimal"
    )
    require(len(helper.lines) == 11, f"{cid} Value.fromBigDecimal shape")
    require_call(helper, 2, "Value#constructor", f"{cid} BigDecimal Value constructor")
    value_local = local_name(helper.lines[3], "tee")
    require(value_local is not None, f"{cid} BigDecimal Value local")
    require_instruction(helper, 4, "i32.const 2", f"{cid} BigDecimal Value kind")
    require_instruction(helper, 5, "i32.store", f"{cid} BigDecimal Value kind store")
    require_instruction(helper, 6, f"local.get {value_local}", f"{cid} BigDecimal Value receiver")
    require_instruction(helper, 7, "local.get $p0", f"{cid} BigDecimal Value payload")
    require_instruction(helper, 8, "i64.extend_i32_u", f"{cid} BigDecimal pointer widening")
    require_instruction(helper, 9, "i64.store offset=8", f"{cid} BigDecimal payload store")
    require(
        local_name(helper.lines[10]) == value_local,
        f"{cid} BigDecimal Value return instruction drift at relative line 10",
    )
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "value_kind": 2,
        "input_parameter": "$p0",
        "input_to_bigdecimal_value_payload_machine_proven": True,
    }


def prove_legacy_pool_setter(context: dict[str, Any], field: str) -> dict[str, Any]:
    cid = context["mapping_cid"]
    helper = single_suffix_function(
        context["functions"], f"schema/Pool#set:{field}", f"{cid} Pool.{field} setter"
    )
    require(len(helper.lines) == 6, f"{cid} Pool.{field} setter shape")
    require_instruction(helper, 1, "local.get $p0", f"{cid} Pool.{field} receiver")
    require(decoded_constant(helper.lines[2], context["memory"]) == field, f"{cid} Pool.{field} key")
    require_instruction(helper, 3, "local.get $p1", f"{cid} Pool.{field} value")
    require_call(helper, 4, "Value.fromBigDecimal", f"{cid} Pool.{field} serialization")
    require_exact_call(helper, 5, LEGACY_ENTITY_MAP_SET_CALL, f"{cid} Pool.{field} map set")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "field_key": field,
        "receiver_parameter": "$p0",
        "value_parameter": "$p1",
        "value_conversion": prove_value_from_bigdecimal(context),
        "receiver_key_value_to_typed_map_set_machine_proven": True,
    }


EXPECTED_POOL_LOCAL_USE_INDICES = {
    "legacy": [
        12,
        16,
        53,
        107,
        108,
        113,
        123,
        134,
        141,
        142,
        150,
        151,
        156,
        157,
        162,
        163,
        168,
        175,
        176,
        185,
        202,
        216,
        220,
        224,
        366,
    ],
    "modern": [
        45,
        50,
        116,
        275,
        290,
        294,
        315,
        354,
        375,
        407,
        412,
        427,
        431,
        446,
        450,
        455,
        472,
        476,
        492,
        498,
        542,
        602,
        619,
        636,
        1041,
    ],
}

EXPECTED_POOL_LOCAL_USE_SHA256 = {
    "legacy-base-root": "80fe2b776f97fee879ca998ce169c4ac828801930ee63836e5b3312dd71d9acb",
    "legacy-mainnet-qmrv": "80fe2b776f97fee879ca998ce169c4ac828801930ee63836e5b3312dd71d9acb",
    "legacy-mainnet-root": "80fe2b776f97fee879ca998ce169c4ac828801930ee63836e5b3312dd71d9acb",
    "legacy-mainnet-stable": "80fe2b776f97fee879ca998ce169c4ac828801930ee63836e5b3312dd71d9acb",
    "legacy-mainnet-stable-fee-tier-1": "80fe2b776f97fee879ca998ce169c4ac828801930ee63836e5b3312dd71d9acb",
    "legacy-mainnet-stable-fee-tier-100": "80fe2b776f97fee879ca998ce169c4ac828801930ee63836e5b3312dd71d9acb",
    "modern-base": "e54565d05246697e8635c3f8f7cced771094490686cb621effb4dce44538752c",
    "modern-mainnet": "4f935214bb5003184982c8102c8185fb2f9340a74208fb86dac397deddff52a8",
}

EXPECTED_EFFECT_CLOSURE = {
    "legacy-base-root": (175, 0, (), 12, "33fbc7243cae8acb61e1e1a992ff2add2d0a98c2102af9b98790b3c179e0d708"),
    "legacy-mainnet-qmrv": (175, 0, (), 12, "2872aeb1632d93f7b92837ef6c0c46f10649a4b8676195b5c9b2b0f7d85715c0"),
    "legacy-mainnet-root": (175, 0, (), 12, "2872aeb1632d93f7b92837ef6c0c46f10649a4b8676195b5c9b2b0f7d85715c0"),
    "legacy-mainnet-stable": (175, 0, (), 12, "2872aeb1632d93f7b92837ef6c0c46f10649a4b8676195b5c9b2b0f7d85715c0"),
    "legacy-mainnet-stable-fee-tier-1": (175, 0, (), 12, "2872aeb1632d93f7b92837ef6c0c46f10649a4b8676195b5c9b2b0f7d85715c0"),
    "legacy-mainnet-stable-fee-tier-100": (175, 0, (), 12, "2872aeb1632d93f7b92837ef6c0c46f10649a4b8676195b5c9b2b0f7d85715c0"),
    "modern-base": (
        95,
        1,
        ("~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0",),
        12,
        "98e7a266ecf9131b97eb2d18dad0fcf6a6f768653e4723e9954f95e5ac60a7b8",
    ),
    "modern-mainnet": (
        95,
        1,
        ("~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0",),
        12,
        "a455a8efef522463c35fbff4ff10b50146a1a21d091b6a166eedcc0ec24eb212",
    ),
}

# Exact retained reachable-body authority for the Burn-only mutation inventory.
# This intentionally does not pretend to be a general heap-alias proof: every
# current reachable body, direct memory-write site, and TypedMap#set site is
# inventoried so a changed or newly reachable effect fails closed. This is
# authority over the retained bytes, not semantic classification of every
# baseline key, receiver, value, or memory alias.
EXPECTED_REACHABLE_MUTATION_CLOSURE = {
    "modern-base": (
        95,
        "c4a0d2cb2773bcab54176af2d63cb275f4bda6f2fe4f9622626bc2b9b24c849d",
        526,
        "98cebe90adb00d11a541ceec7414d4792b91113c19abb3ce45b7de06a52d07e2",
        149,
        "05d572c29f1a9cf45e84e5e1b8ac8519d94f1dcda0f3dcf87546e8a86cdcf36b",
    ),
    "modern-mainnet": (
        95,
        "0255517513eb02e9fdeb80df43b68adbf4da0bb6d6242d893f0bcb43955f45fd",
        526,
        "9078df54993b14c1ac94015168c2515f8286e6ed0ea8f1ab2bae92e7c9370d10",
        149,
        "04dd22e465c928a835009d0d2d8119f7164c5313f5bf33d332ad0cb6633dbd7e",
    ),
    "legacy-mainnet-root": (
        175,
        "cc897cbbb25e818bf3002a99fcdfe73602dd5cc17e6485f45f6481e1993164c9",
        166,
        "f13927e1bb2bd6552f0725bd1a3c59a3cecb67f4cf40f7dc5b0720f631d0e24c",
        54,
        "6233b3d76f6b4c8cfee889d74c07145305cc0ed836951c3d73942fd5159c1679",
    ),
    "legacy-mainnet-qmrv": (
        175,
        "de480808ed955a392c10d13ef41013d3e11a431284e50ffdc49b394ca7bc3c6f",
        166,
        "f13927e1bb2bd6552f0725bd1a3c59a3cecb67f4cf40f7dc5b0720f631d0e24c",
        54,
        "f00d32bd94e01cbd289b3851c28db7cc2efd4451d31d28bfeb034444ab2c5762",
    ),
    "legacy-base-root": (
        175,
        "b37eab136724093275f706b582b4d0de0b634fd6cd4ba24fca9d2da2d5c4d5bd",
        166,
        "f13927e1bb2bd6552f0725bd1a3c59a3cecb67f4cf40f7dc5b0720f631d0e24c",
        54,
        "f00d32bd94e01cbd289b3851c28db7cc2efd4451d31d28bfeb034444ab2c5762",
    ),
    "legacy-mainnet-stable-fee-tier-100": (
        175,
        "712bdcb6bf866e8b64d9dd7ee1e0d3abf3427dd5f545b84da731509b4dd0ec94",
        166,
        "f13927e1bb2bd6552f0725bd1a3c59a3cecb67f4cf40f7dc5b0720f631d0e24c",
        54,
        "f00d32bd94e01cbd289b3851c28db7cc2efd4451d31d28bfeb034444ab2c5762",
    ),
    "legacy-mainnet-stable-fee-tier-1": (
        175,
        "712bdcb6bf866e8b64d9dd7ee1e0d3abf3427dd5f545b84da731509b4dd0ec94",
        166,
        "f13927e1bb2bd6552f0725bd1a3c59a3cecb67f4cf40f7dc5b0720f631d0e24c",
        54,
        "f00d32bd94e01cbd289b3851c28db7cc2efd4451d31d28bfeb034444ab2c5762",
    ),
    "legacy-mainnet-stable": (
        175,
        "712bdcb6bf866e8b64d9dd7ee1e0d3abf3427dd5f545b84da731509b4dd0ec94",
        166,
        "f13927e1bb2bd6552f0725bd1a3c59a3cecb67f4cf40f7dc5b0720f631d0e24c",
        54,
        "f00d32bd94e01cbd289b3851c28db7cc2efd4451d31d28bfeb034444ab2c5762",
    ),
}


def prove_reachable_mutation_inventory(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile_id = context["profile"]["profile_id"]
    functions = context["functions"]
    reachable = sorted(
        WRITER.reachable_functions(
            functions, context["handler"], tuple(context["indirect_targets"])
        )
    )
    bodies = [
        {"function": name, "body_sha256": function_sha256(functions[name])}
        for name in reachable
    ]
    writes = [
        {
            "function": name,
            "relative_wat_line": index,
            "instruction": normalized(line),
        }
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if POOL_RUNTIME.RUNTIME.is_direct_memory_write(line, normalized)
    ]
    set_targets = {LEGACY_ENTITY_MAP_SET_CALL, MODERN_ENTITY_MAP_SET_CALL}
    map_sets = [
        {
            "function": name,
            "relative_wat_line": index,
            "target": call_name(line),
        }
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if call_name(line) in set_targets
    ]
    actual = (
        len(reachable),
        canonical_sha256(bodies),
        len(writes),
        canonical_sha256(writes),
        len(map_sets),
        canonical_sha256(map_sets),
    )
    require(
        actual == EXPECTED_REACHABLE_MUTATION_CLOSURE[profile_id],
        f"{cid} exact reachable Burn mutation inventory drift",
    )
    return {
        "reachable_function_count": len(reachable),
        "reachable_function_body_inventory_sha256": actual[1],
        "reachable_direct_memory_write_site_count": len(writes),
        "reachable_direct_memory_write_site_inventory_sha256": actual[3],
        "reachable_typed_map_set_site_count": len(map_sets),
        "reachable_typed_map_set_site_inventory_sha256": actual[5],
        "exact_retained_reachable_body_authority": True,
        "changed_or_newly_reachable_effect_inventory_drift_rejected": True,
        "baseline_typed_map_set_sites_semantically_classified_for_selected_receiver_key_value": 0,
        "baseline_typed_map_set_sites_without_selected_receiver_key_value_proof": len(map_sets),
        "baseline_direct_memory_write_sites_proven_not_to_alias_selected_payload": 0,
        "baseline_direct_memory_write_sites_without_selected_payload_alias_proof": len(writes),
        "baseline_effect_inventory_semantically_closed_for_selected_fields": False,
        "general_heap_alias_semantics_rederived": False,
        "direct_selected_payload_alias_safety_rederived": False,
    }


def prove_pool_local_use_closure(
    context: dict[str, Any], pool_local: str, save: int
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    uses = [
        index
        for index, line in enumerate(handler.lines)
        if normalized(line) == f"local.get {pool_local}"
    ]
    require(uses == EXPECTED_POOL_LOCAL_USE_INDICES[generation], f"{cid} loaded Pool use ledger drift")
    assignments = [
        index
        for index, line in enumerate(handler.lines)
        if local_name(line, "set") == pool_local or local_name(line, "tee") == pool_local
    ]
    require(len(assignments) == 1, f"{cid} loaded Pool assignment count drift")
    successful_no_reassignment(
        handler,
        pool_local,
        assignments[0],
        save,
        f"{cid} loaded Pool before save",
    )
    normalized_contexts = []
    for index in uses:
        window = [normalized(line) for line in handler.lines[index : min(index + 4, len(handler.lines))]]
        normalized_contexts.append({"relative_wat_line": index, "instruction_window": window})
    use_ledger_sha256 = canonical_sha256(normalized_contexts)
    profile_id = context["profile"]["profile_id"]
    require(
        use_ledger_sha256 == EXPECTED_POOL_LOCAL_USE_SHA256[profile_id],
        f"{cid} loaded Pool use context drift",
    )
    return {
        "pool_entity_local": pool_local,
        "assignment_relative_wat_line": assignments[0],
        "use_relative_wat_lines": uses,
        "use_ledger_sha256": use_ledger_sha256,
        "no_pool_local_reassignment_before_save_machine_proven": True,
        "pool_local_alias_escape_semantics_rederived": False,
    }


def prove_selected_field_flows(
    context: dict[str, Any],
    pool: dict[str, Any],
    tokens: dict[str, Any],
    amounts: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    memory = context["memory"]
    pool_local = pool["pool_entity_local"]
    subtraction = prove_bigdecimal_minus(context)
    fields: dict[str, Any] = {}
    setter_indices: list[int] = []
    for selected in SELECTED_FIELDS:
        getter = prove_pool_tvl_getter(context, selected)
        amount_local = amounts["fields"][selected]["converted_amount_local"]
        conversion_line = amounts["fields"][selected]["handler_conversion_wat_line"] - handler.start_line
        if generation == "legacy":
            setter_index = single_call(handler, f"schema/Pool#set:{selected}", f"{cid} {selected} setter")
            require_instruction(handler, setter_index - 5, f"local.get {pool_local}", f"{cid} {selected} setter receiver")
            require_instruction(handler, setter_index - 4, f"local.get {pool_local}", f"{cid} {selected} getter receiver")
            require_call(handler, setter_index - 3, f"schema/Pool#get:{selected}", f"{cid} {selected} old getter")
            require_instruction(handler, setter_index - 2, f"local.get {amount_local}", f"{cid} {selected} amount")
            require_call(handler, setter_index - 1, "BigDecimal#minus", f"{cid} {selected} subtraction")
            no_reassignment(handler, amount_local, conversion_line + 1, setter_index - 2, f"{cid} {selected} amount")
            setter = prove_legacy_pool_setter(context, selected)
            fields[selected] = {
                **SELECTED_FIELDS[selected],
                "old_value_getter": getter,
                "subtraction": subtraction,
                "setter": setter,
                "handler_setter_wat_line": handler.start_line + setter_index,
                "setter_operand_call_flow": f"old Pool.{selected} minus converted Burn.{SELECTED_FIELDS[selected]['event_parameter_name']}",
                "loaded_pool_old_value_amount_subtraction_and_setter_machine_proven": True,
            }
        else:
            literals = [
                index
                for index, line in enumerate(handler.lines)
                if decoded_constant(line, memory) == selected
            ]
            require(len(literals) == 1, f"{cid} modern {selected} setter literal count")
            literal = literals[0]
            setter_index = literal + 2
            require_call(handler, literal - 15, f"schema/Pool#get:{selected}", f"{cid} {selected} old getter")
            require_instruction(handler, literal - 16, f"local.get {pool_local}", f"{cid} {selected} getter receiver")
            require_instruction(handler, literal - 14, f"local.get {amount_local}", f"{cid} {selected} amount")
            require_call(handler, literal - 13, "BigDecimal#minus", f"{cid} {selected} subtraction")
            require_instruction(handler, literal - 12, "i64.extend_i32_u", f"{cid} {selected} payload widening")
            payload_local = local_name(handler.lines[literal - 11], "set")
            require(payload_local is not None, f"{cid} {selected} payload local")
            require_instruction(handler, literal - 10, "i32.const 16", f"{cid} {selected} Value size")
            require_instruction(handler, literal - 9, "i32.const 26", f"{cid} {selected} Value runtime ID")
            require_call(handler, literal - 8, "__new", f"{cid} {selected} Value allocation")
            value_local = local_name(handler.lines[literal - 7], "tee")
            require(value_local is not None, f"{cid} {selected} Value local")
            require_instruction(handler, literal - 6, "i32.const 2", f"{cid} {selected} Value kind")
            require_instruction(handler, literal - 5, "i32.store", f"{cid} {selected} Value kind store")
            require_instruction(handler, literal - 4, f"local.get {value_local}", f"{cid} {selected} Value receiver")
            require_instruction(handler, literal - 3, f"local.get {payload_local}", f"{cid} {selected} Value payload")
            require_instruction(handler, literal - 2, "i64.store offset=8", f"{cid} {selected} payload store")
            require_instruction(handler, literal - 1, f"local.get {pool_local}", f"{cid} {selected} setter receiver")
            require_instruction(handler, literal + 1, f"local.get {value_local}", f"{cid} {selected} setter value")
            require_exact_call(handler, setter_index, MODERN_ENTITY_MAP_SET_CALL, f"{cid} {selected} map set")
            no_reassignment(handler, amount_local, conversion_line + 1, literal - 14, f"{cid} {selected} amount")
            no_reassignment(handler, payload_local, literal - 11, literal - 3, f"{cid} {selected} payload")
            no_reassignment(handler, value_local, literal - 7, literal + 1, f"{cid} {selected} Value")
            fields[selected] = {
                **SELECTED_FIELDS[selected],
                "old_value_getter": getter,
                "subtraction": subtraction,
                "setter": {
                    "function": call_name(handler.lines[setter_index]),
                    "field_key": selected,
                    "receiver_local": pool_local,
                    "value_local": value_local,
                    "value_kind": 2,
                    "inline_receiver_key_bigdecimal_value_to_typed_map_set_machine_proven": True,
                },
                "handler_setter_wat_line": handler.start_line + setter_index,
                "field_key_wat_line": handler.start_line + literal,
                "setter_operand_call_flow": f"old Pool.{selected} minus converted Burn.{SELECTED_FIELDS[selected]['event_parameter_name']}",
                "loaded_pool_old_value_amount_subtraction_and_setter_machine_proven": True,
            }
        setter_indices.append(setter_index)
    require(setter_indices == sorted(setter_indices), f"{cid} selected setter order")
    depths = V2.wat_control_depths(handler.lines)
    expected_depth = 1 if generation == "modern" else 0
    require(
        all(depths[index] == expected_depth for index in setter_indices),
        f"{cid} selected setter control depth drift",
    )
    if generation == "modern":
        guard_start = tokens["selected_update_guard_start_index"]
        guard_end = tokens["selected_update_guard_end_index"]
        require(
            guard_start is not None
            and guard_end is not None
            and guard_start < setter_indices[0] < setter_indices[1] < guard_end,
            f"{cid} selected setters escaped two-token guard",
        )
    return {
        "fields": fields,
        "setter_order": [f"Pool.{field}" for field in SELECTED_FIELDS],
        "setter_indices": setter_indices,
        "both_setters_same_loaded_pool_machine_proven": True,
    }


def explicit_selected_setter_callsites(
    context: dict[str, Any], fields: dict[str, Any]
) -> list[dict[str, Any]]:
    generation = context["profile"]["control_generation"]
    functions = context["functions"]
    handler = context["handler"]
    reachable = WRITER.reachable_functions(
        functions, handler, tuple(context["indirect_targets"])
    )
    sites: list[dict[str, Any]] = []
    if generation == "legacy":
        targets = {
            single_suffix_function(functions, f"schema/Pool#set:{field}", field).name: field
            for field in SELECTED_FIELDS
        }
        for function_name in sorted(reachable):
            for index, line in enumerate(functions[function_name].lines):
                target = call_name(line)
                if target in targets:
                    sites.append(
                        {
                            "field": targets[target],
                            "function": function_name,
                            "relative_wat_line": index,
                        }
                    )
    else:
        memory = context["memory"]
        for function_name in sorted(reachable):
            function = functions[function_name]
            for index, line in enumerate(function.lines):
                if call_name(line) != MODERN_ENTITY_MAP_SET_CALL or index < 2:
                    continue
                field = decoded_constant(function.lines[index - 2], memory)
                if field in SELECTED_FIELDS:
                    sites.append(
                        {
                            "field": field,
                            "function": function_name,
                            "relative_wat_line": index,
                        }
                    )
    expected = [
        {
            "field": field,
            "function": handler.name,
            "relative_wat_line": fields["setter_indices"][ordinal],
        }
        for ordinal, field in enumerate(SELECTED_FIELDS)
    ]
    require(
        sites == expected,
        f"{context['mapping_cid']} explicit selected setter callsites drift",
    )
    return sites


def prove_failure_dependencies(context: dict[str, Any], selected_end: int, save: int) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    functions = context["functions"]
    update_calls = [
        index
        for index, line in enumerate(handler.lines)
        if (call_name(line) or "").endswith("src/mappings/core/updateTickFeeVarsAndSave")
    ]
    require(len(update_calls) == 2, f"{cid} tick update helper call count")
    require(all(selected_end < index < save for index in update_calls), f"{cid} tick calls order")
    update = single_suffix_function(
        functions, "src/mappings/core/updateTickFeeVarsAndSave", f"{cid} tick update helper"
    )
    ethereum = single_suffix_function(
        functions,
        "ethereum.SmartContract#call",
        f"{cid} non-try contract-call helper",
    )
    if generation == "legacy":
        ticks = single_suffix_function(functions, "Pool#ticks", f"{cid} Pool.ticks helper")
        require(
            any(call_name(line) == ticks.name for line in update.lines),
            f"{cid} tick update does not reach Pool.ticks",
        )
        require(
            any(call_name(line) == ethereum.name for line in ticks.lines),
            f"{cid} Pool.ticks does not reach non-try call",
        )
        tick_guard = "no explicit Tick-presence guard in handleBurn"
    else:
        require(
            any(call_name(line) == ethereum.name for line in update.lines),
            f"{cid} tick update does not reach non-try call",
        )
        depths = V2.wat_control_depths(handler.lines)
        require(all(depths[index] == 2 for index in update_calls), f"{cid} modern tick calls not guarded")
        tick_guard = "both Tick entities must be present; otherwise the tick-update block is skipped"
    require(
        WRITER.ETHEREUM_CALL in WRITER.function_calls(ethereum),
        f"{cid} SmartContract.call host call missing",
    )
    require(
        any((call_name(line) or "").endswith(("builtins/abort", "env/abort")) for line in ethereum.lines)
        and any(normalized(line) == "unreachable" for line in ethereum.lines),
        f"{cid} non-try call failure does not abort",
    )
    pool_store_calls_before_save = [
        index
        for index, line in enumerate(handler.lines[:save])
        if (call_name(line) or "").endswith("schema/Pool#save")
    ]
    require(not pool_store_calls_before_save, f"{cid} Pool saved before failure dependencies")
    return {
        "tick_update_helper": update.name,
        "tick_update_helper_body_sha256": function_sha256(update),
        "handler_tick_update_call_wat_lines": [handler.start_line + index for index in update_calls],
        "tick_presence_behavior": tick_guard,
        "non_try_contract_call_helper": ethereum.name,
        "non_try_contract_call_helper_body_sha256": function_sha256(ethereum),
        "selected_tvl_values_do_not_depend_on_contract_call_results": True,
        "contract_call_failure_occurs_before_pool_store": True,
        "contract_call_success_failure_semantics_complete": False,
    }


def prove_persistence_and_effect_closure(
    context: dict[str, Any],
    pool: dict[str, Any],
    tokens: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    handler = context["handler"]
    pool_local = pool["pool_entity_local"]
    saves = [
        index
        for index, line in enumerate(handler.lines)
        if (call_name(line) or "").endswith("schema/Pool#save")
    ]
    require(len(saves) == 1, f"{cid} Burn direct Pool.save count")
    save = saves[0]
    selected_start, selected_end = fields["setter_indices"]
    require(selected_start < selected_end < save, f"{cid} selected setters not before Pool.save")
    require_instruction(handler, save - 1, f"local.get {pool_local}", f"{cid} Pool.save receiver")
    depths = V2.wat_control_depths(handler.lines)
    expected_depth = 1 if generation == "modern" else 0
    require(
        depths[selected_start] == depths[selected_end] == depths[save] == expected_depth,
        f"{cid} setter/save control-path mismatch",
    )
    if generation == "modern":
        guard_start = tokens["selected_update_guard_start_index"]
        guard_end = tokens["selected_update_guard_end_index"]
        require(
            guard_start is not None and guard_end is not None and guard_start < selected_start < save < guard_end,
            f"{cid} Pool save escaped two-token guard",
        )
    INITIALIZE.require_no_successful_path_bypass(handler, save, f"{cid} Burn save path")
    mutation_inventory = prove_reachable_mutation_inventory(context)
    pool_uses = prove_pool_local_use_closure(context, pool_local, save)
    selected_sites = explicit_selected_setter_callsites(context, fields)
    require(len(selected_sites) == len(SELECTED_FIELDS), f"{cid} explicit selected setter count")
    mutation_inventory[
        "baseline_typed_map_set_sites_semantically_classified_for_selected_receiver_key_value"
    ] = len(selected_sites)
    mutation_inventory[
        "baseline_typed_map_set_sites_without_selected_receiver_key_value_proof"
    ] -= len(selected_sites)
    save_helper = INITIALIZE.prove_pool_save_helper(context)
    transitive = INITIALIZE.recompute_transitive_store_evidence(context)
    require(
        transitive["reachable_pool_save_calls"]
        == [
            {
                "function": handler.name,
                "relative_wat_line": save,
                "wat_line": handler.start_line + save,
            }
        ],
        f"{cid} additional reachable Pool.save",
    )
    require(
        transitive["reachable_pool_store_set_sites"]
        == [
            {
                "site_id": f"{save_helper['function']}#1",
                "function": save_helper["function"],
                "wat_line": save_helper["store_set_wat_line"],
            }
        ],
        f"{cid} additional reachable Pool store.set",
    )
    require(
        transitive["reachable_store_set_targets"]
        == [
            "Burn",
            "Factory",
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
        ],
        f"{cid} Burn reachable store target drift",
    )
    require(transitive["dynamic_reachable_store_set_target_count"] == 0, f"{cid} dynamic store target")
    require(transitive["unmodelled_store_mutation_host_import_count"] == 0, f"{cid} unmodelled store mutation")
    profile_id = context["profile"]["profile_id"]
    expected_closure = EXPECTED_EFFECT_CLOSURE[profile_id]
    actual_closure = (
        transitive["reachable_function_count"],
        transitive["reachable_call_indirect_instruction_count"],
        tuple(transitive["closed_indirect_table_targets"]),
        transitive["reachable_store_set_site_count"],
        transitive["reachable_store_set_site_ids_sha256"],
    )
    require(actual_closure == expected_closure, f"{cid} transitive Burn effect closure drift")
    failure = prove_failure_dependencies(context, selected_end, save)
    if generation == "legacy":
        burn_writes = [
            index
            for index, line in enumerate(handler.lines)
            if (call_name(line) or "").endswith("schema/Burn#save")
        ]
        burn_write_kind = "generated Burn.save call"
    else:
        burn_writes = [
            index
            for index, line in enumerate(handler.lines)
            if call_name(line) == WRITER.STORE_SET_CALL
            and index >= 4
            and decoded_constant(handler.lines[index - 4], context["memory"]) == "Burn"
        ]
        burn_write_kind = "inlined Burn store.set"
    require(len(burn_writes) == 1 and save < burn_writes[0], f"{cid} Burn save ordering drift")
    return {
        "selected_update_path_calls_pool_save_after_both_setters": True,
        "unconditional_normal_completion_save": generation == "legacy",
        "direct_pool_save_count": 1,
        "handler_save_wat_line": handler.start_line + save,
        "effect_order": [
            "Pool.totalValueLockedToken0 set",
            "Pool.totalValueLockedToken1 set",
            "intervening Burn helper effects",
            "Pool.save",
            "Burn.save",
        ],
        "saved_entity_local": pool_local,
        "pool_local_use_closure": pool_uses,
        "reachable_in_memory_mutation_inventory": mutation_inventory,
        "selected_field_write_callsites": selected_sites,
        "explicit_selected_setter_callsites_bound": True,
        "all_other_reachable_typed_map_set_receiver_key_value_semantics_classified": False,
        "no_later_selected_field_overwrites_proven": False,
        "general_heap_alias_no_overwrite_proven": False,
        "save_helper": save_helper,
        "transitive_store_evidence": transitive,
        "failure_dependencies": failure,
        "burn_save_kind": burn_write_kind,
        "burn_save_wat_line": handler.start_line + burn_writes[0],
        "burn_save_after_pool_save_machine_proven": True,
        "same_loaded_pool_save_after_both_selected_setters_on_selected_update_path_machine_proven": True,
        "selected_setter_and_save_call_flow": (
            "pass old matching Pool TVL minus converted Burn amount to each explicit selected setter, "
            "then call Pool.save with the same loaded Pool on the selected-update path"
        ),
        "selected_tvl_persistence_projection_complete": False,
        "post_fatal_or_graph_rollback_projection": "not proved by retained WAT",
    }


def prove_pool_burn_wat_context(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    require(generation in {"legacy", "modern"}, f"{cid} Pool generation")
    runtime = prove_runtime_for_burn_context(context)
    context = {**context, "pool_runtime_proof": runtime}
    handler = context["handler"]
    pool = prove_pool_load(context)
    tokens = prove_token_loads_and_guard(context, pool)
    conversion = prove_decimal_conversion(context)
    amounts = prove_amount_flows(context, tokens, conversion)
    fields = prove_selected_field_flows(context, pool, tokens, amounts)
    persistence = prove_persistence_and_effect_closure(context, pool, tokens, fields)
    capsule = runtime["public_collection_capsule"]
    if generation == "modern":
        typed_map = capsule["typed_map_collection_runtime"]
        indexed = capsule["indexed_collection"]
        collection_facts = {
            "event_param_array_get": indexed["event_param_array_get"],
            "typed_map_get": indexed["typed_map_get"],
            "typed_map_set": typed_map["typed_map_set"],
            "allocator_return_identity_structurally_proven": typed_map["allocator"][
                "allocator_return_identity_structurally_proven"
            ],
            "collection_mutation_chain_structurally_closed": typed_map[
                "collection_mutation_chain_structurally_closed"
            ],
            "freshness_scope": (
                "within one normally executing handler, assuming imported hosts do not "
                "write arbitrary linear memory"
            ),
        }
    else:
        indexed = capsule["indexed_access_and_value"]
        collection_facts = {
            "event_param_array_get": indexed["event_param_array_get"],
            "typed_map_get": capsule["typed_map_runtime"]["typed_map_get"],
            "typed_map_get_entry": capsule["typed_map_runtime"]["typed_map_get_entry"],
            "typed_map_set": capsule["typed_map_runtime"]["typed_map_set"],
            "value_constructor": indexed["value_constructor"],
            "value_from_big_decimal": indexed["value_from_big_decimal"],
            "entry_array_runtime": capsule["entry_array_runtime"],
            "freshness_scope": capsule["allocator_freshness_scope"],
        }
    return {
        "mapping_cid": cid,
        "profile_id": context["profile"]["profile_id"],
        "control_generation": generation,
        "retained_wasm": {
            "path": context["artifact_path"],
            "bytes": context["analysis"]["bytes"],
            "sha256": context["analysis"]["sha256"],
            "wat_sha256": context["analysis"]["wat_sha256"],
        },
        "handler_binding": {
            "export": HANDLER_EXPORT,
            "exact_wat_export_target": handler.name,
            "numeric_function_index": handler.function_index,
            "body_sha256": function_sha256(handler),
            "wat_start_line": handler.start_line,
            "wat_body_line_count": len(handler.lines),
        },
        "pool_runtime_binding": {
            "contract_version": POOL_RUNTIME_CONTRACT_VERSION,
            "artifact_selection_tuple": runtime["artifact_selection_tuple"],
            "same_wat_runtime_proof_sha256": canonical_sha256(runtime),
            "all_defined_function_declarations_sha256": canonical_sha256(
                runtime["all_defined_function_declarations"]
            ),
            "public_collection_capsule_sha256": canonical_sha256(capsule),
            "collection_facts": collection_facts,
            "proof_boundaries": runtime["proof_boundaries"],
            "same_context_runtime_capsule_recomputed": True,
        },
        "pool_load_identity": pool,
        "token_loads_and_presence_control": tokens,
        "event_amount_and_decimal_flows": amounts,
        "field_value_and_setter_flow": {
            "fields": fields["fields"],
            "setter_order": fields["setter_order"],
            "both_setters_same_loaded_pool_machine_proven": fields[
                "both_setters_same_loaded_pool_machine_proven"
            ],
        },
        "persistence_and_effect_closure": persistence,
        "selected_setter_and_save_call_flow_bound": True,
        "selected_handler_structural_wat_projection_complete": False,
        "complete_pool_burn_handler_semantics": False,
    }


def build_pool_burn_proofs(
    initialize_contexts: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    contexts = {
        cid: burn_context_from_initialize(context)
        for cid, context in initialize_contexts.items()
    }
    proofs = [prove_pool_burn_wat_context(context) for context in contexts.values()]
    proofs.sort(key=lambda item: item["profile_id"])
    require(len(proofs) == 8, "Pool Burn proof count drift")
    require(sum(item["control_generation"] == "legacy" for item in proofs) == 6, "legacy Burn count")
    require(sum(item["control_generation"] == "modern" for item in proofs) == 2, "modern Burn count")
    return proofs, contexts


def selected_v2_fields(v2: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_identity = {(item["entity"], item["field"]): item for item in v2["field_catalog"]}
    records = tuple(by_identity[("Pool", field)] for field in SELECTED_FIELDS)
    for record in records:
        require(
            record["semantic_status"] == "digest_bound_reviewed_incomplete",
            f"v2 selected Pool field status drift: {record['field']}",
        )
        require(
            record["complete_selected_handler_projection"] is False,
            f"v2 selected Pool field already complete: {record['field']}",
        )
        require(
            record["complete_entity_history"] is False,
            f"v2 Pool history unexpectedly complete: {record['field']}",
        )
    return records  # type: ignore[return-value]


def build_segments(
    matrix: dict[str, Any],
    v2: dict[str, Any],
    proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    v2_fields = {item["field"]: item for item in selected_v2_fields(v2)}
    results: list[dict[str, Any]] = []
    expected_event = "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"
    for segment in matrix["segments"]:
        binding = segment["profile_bindings"]["pool"]
        cid = binding["mapping_cid"]
        require(cid in proof_by_cid, f"Pool Burn proof missing: {segment['segment_id']}")
        proof = proof_by_cid[cid]
        handler = next(item for item in segment["handlers"] if item["handler_id"] == HANDLER_ID)
        require(handler["event"] == expected_event, f"Burn handler event drift: {segment['segment_id']}")
        require(handler["mapping_cid"] == cid, f"Burn handler mapping drift: {segment['segment_id']}")
        modern = proof["control_generation"] == "modern"
        fields: list[dict[str, Any]] = []
        for field, definition in SELECTED_FIELDS.items():
            v2_record = v2_fields[field]
            call_flow = (
                f"if both Token entities exist, pass old value minus converted Burn.{definition['event_parameter_name']} "
                "to the explicit setter and later call Pool.save; otherwise skip the selected update/save body"
                if modern
                else f"on the normal-completion path, pass old value minus converted Burn.{definition['event_parameter_name']} "
                "to the explicit setter and later call Pool.save"
            )
            fields.append(
                {
                    "entity": "Pool",
                    "field": field,
                    "schema_type": definition["schema_type"],
                    "event_parameter_index": definition["event_parameter_index"],
                    "event_parameter_name": definition["event_parameter_name"],
                    "event_parameter_type": definition["event_parameter_type"],
                    "pool_token_field": definition["pool_token_field"],
                    "population_classification": "conditional",
                    "selected_handler_call_flow_evidence": call_flow,
                    "complete_selected_handler_projection": False,
                    "complete_entity_history": False,
                    "cumulative_semantic_status": "digest_bound_burn_call_flow_evidence_incomplete",
                    "v2_field_record_sha256": canonical_sha256(v2_record),
                    "residual_history_blocker": (
                        "baseline dynamic/helper TypedMap keys and direct-memory aliases are not semantically closed, "
                        "and Factory.handlePoolCreated plus Pool Initialize, Mint, Flash, and Swap last-writer contributions remain incomplete"
                    ),
                }
            )
        semantic_surface = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "control_generation": proof["control_generation"],
            "pool_load_identity": proof["pool_load_identity"],
            "token_loads_and_presence_control": proof["token_loads_and_presence_control"],
            "event_amount_and_decimal_flows": proof["event_amount_and_decimal_flows"],
            "field_value_and_setter_flow": proof["field_value_and_setter_flow"],
            "persistence_and_effect_closure": proof["persistence_and_effect_closure"],
            "fields": fields,
            "selected_setter_and_save_call_flow_bound": True,
            "selected_handler_projection_complete": False,
            "complete_pool_burn_handler_semantics": False,
            "complete_pool_entity_history": False,
        }
        provenance_surface = {
            "mapping_cid": cid,
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "proof_sha256": canonical_sha256(proof),
            "source_handler_record_sha256": canonical_sha256(handler),
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
    require(len(results) == 8, "Pool Burn segment count")
    require(sum(len(item["semantic_surface"]["fields"]) for item in results) == 16, "Burn segment-field count")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = INITIALIZE.json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = INITIALIZE.json_diff_paths(left["provenance_surface"], right["provenance_surface"])
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
    require(len(results) == 28, "Pool Burn pairwise diff count")
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
    init_contract_path = root / INITIALIZE_CONTRACT_PATH
    require(init_contract_path.is_file(), f"Initialize contract missing: {INITIALIZE_CONTRACT_PATH}")
    require(raw_sha256(init_contract_path) == INITIALIZE_CONTRACT_SHA256, "Initialize contract digest drift")
    runtime_contract_path = root / POOL_RUNTIME_CONTRACT_PATH
    require(
        runtime_contract_path.is_file(),
        f"Pool runtime contract missing: {POOL_RUNTIME_CONTRACT_PATH}",
    )
    require(
        raw_sha256(runtime_contract_path) == POOL_RUNTIME_CONTRACT_SHA256,
        "Pool runtime contract digest drift",
    )
    v2_contract_path = root / V2_CONTRACT_PATH
    require(v2_contract_path.is_file(), f"v2 contract missing: {V2_CONTRACT_PATH}")
    require(raw_sha256(v2_contract_path) == V2_CONTRACT_SHA256, "v2 contract digest drift")
    initialize_sources = INITIALIZE.load_sources(
        root, recompute_wat=recompute_wat, wasm2wat=wasm2wat
    )
    initialize_contract = INITIALIZE.verify_contract(
        root,
        sources=initialize_sources,
        recompute_wat=False,
    )
    runtime_contract = POOL_RUNTIME.verify_contract(root, wasm2wat=wasm2wat)
    require(
        runtime_contract["contract_version"] == POOL_RUNTIME_CONTRACT_VERSION,
        "Pool runtime contract version drift",
    )
    runtime_proofs = (
        runtime_contract["modern_pool_runtime_proofs"]
        + runtime_contract["legacy_pool_runtime_proofs"]
    )
    require(len(runtime_proofs) == 8, "Pool runtime proof count drift")
    runtime_proof_by_cid = {item["mapping_cid"]: item for item in runtime_proofs}
    require(len(runtime_proof_by_cid) == 8, "Pool runtime proof CID uniqueness drift")
    require(
        initialize_contract["contract_version"] == INITIALIZE_CONTRACT_VERSION,
        "Initialize contract version drift",
    )
    require(
        initialize_contract["scope"]["cumulative_selected_field_count"] == 36
        and initialize_contract["scope"]["cumulative_residual_field_count"] == 230,
        "Initialize cumulative count drift",
    )
    v2_contract = initialize_sources["v2_contract"]
    require(v2_contract["contract_version"] == V2_CONTRACT_VERSION, "v2 version drift")
    abi = verify_pool_abi(root, initialize_sources["v2_sources"]["ancestry"])
    if recompute_wat:
        proofs, contexts = build_pool_burn_proofs(initialize_sources["pool_wat_contexts"])
        for proof in proofs:
            cid = proof["mapping_cid"]
            require(cid in runtime_proof_by_cid, f"{cid} Pool runtime proof missing")
            require(
                proof["pool_runtime_binding"]["artifact_selection_tuple"]
                == runtime_proof_by_cid[cid]["artifact_selection_tuple"],
                f"{cid} Burn/Pool runtime artifact tuple mismatch",
            )
    else:
        proofs, contexts = [], {}
    return {
        "initialize_sources": initialize_sources,
        "initialize_contract": initialize_contract,
        "pool_runtime_contract": runtime_contract,
        "pool_runtime_proof_by_cid": runtime_proof_by_cid,
        "v2_contract": v2_contract,
        "pool_abi": abi,
        "pool_burn_proofs": proofs,
        "pool_wat_contexts": contexts,
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    initialize = sources["initialize_contract"]
    initialize_sources = sources["initialize_sources"]
    v2 = sources["v2_contract"]
    proofs = sources["pool_burn_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 8, "recomputed Pool Burn proofs required")
    matrix = initialize_sources["v2_sources"]["segment_writer_matrix"]
    segments = build_segments(matrix, v2, proofs)
    diffs = build_segment_diffs(segments)
    inherited_selected = initialize["scope"]["cumulative_selected_field_count"]
    inherited_residual = initialize["scope"]["cumulative_residual_field_count"]
    require((inherited_selected, inherited_residual) == (36, 230), "inherited Initialize counts")
    cumulative_selected = inherited_selected
    residual = inherited_residual
    require((cumulative_selected, residual) == (36, 230), "Burn cumulative counts")
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "retained-wat-selected-handler-call-flow-evidence-supplement",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "pool_mapping_count": 8,
            "handler": HANDLER_ID,
            "selected_fields": [f"Pool.{field}" for field in SELECTED_FIELDS],
            "selected_field_count": 2,
            "segment_field_call_flow_evidence_count": 16,
            "legacy_profile_count": 6,
            "modern_guarded_profile_count": 2,
            "unconditional_normal_completion_saving_profile_count": 6,
            "token_present_selected_update_path_saving_profile_count": 2,
            "pairwise_scoped_diff_count": 28,
            "inherited_initialize_selected_field_count": inherited_selected,
            "cumulative_selected_field_count": cumulative_selected,
            "inherited_initialize_residual_field_count": inherited_residual,
            "cumulative_residual_field_count": residual,
            "claim": (
                "exact retained-WAT Pool.handleBurn selected setter/value/save call-flow evidence for Pool.totalValueLockedToken0 and Pool.totalValueLockedToken1; baseline dynamic-key and memory-alias effects prevent persistence or field-completeness promotion"
            ),
        },
        "source_contracts": {
            "segment_field_semantics_v2": {
                "path": str(V2_CONTRACT_PATH),
                "contract_version": V2_CONTRACT_VERSION,
                "raw_sha256": V2_CONTRACT_SHA256,
            },
            "pool_initialize": {
                "path": str(INITIALIZE_CONTRACT_PATH),
                "contract_version": INITIALIZE_CONTRACT_VERSION,
                "raw_sha256": INITIALIZE_CONTRACT_SHA256,
            },
            "pool_initialize_verifier": {
                "path": str(INITIALIZE_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": INITIALIZE_VERIFIER_SHA256,
            },
            "pool_runtime": {
                "path": str(POOL_RUNTIME_CONTRACT_PATH),
                "contract_version": POOL_RUNTIME_CONTRACT_VERSION,
                "raw_sha256": POOL_RUNTIME_CONTRACT_SHA256,
                "projection_sha256": sources["pool_runtime_contract"]["projection_sha256"],
            },
            "pool_runtime_verifier": {
                "path": str(POOL_RUNTIME_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": POOL_RUNTIME_VERIFIER_SHA256,
            },
            "writer_compatibility": {
                "path": V2.SOURCE_SPECS["writer_compatibility"][0],
                "contract_version": V2.SOURCE_SPECS["writer_compatibility"][1],
                "raw_sha256": V2.SOURCE_SPECS["writer_compatibility"][2],
            },
            "segment_writer_matrix": {
                "path": V2.SOURCE_SPECS["segment_writer_matrix"][0],
                "contract_version": V2.SOURCE_SPECS["segment_writer_matrix"][1],
                "raw_sha256": V2.SOURCE_SPECS["segment_writer_matrix"][2],
            },
        },
        "pool_burn_abi": sources["pool_abi"],
        "authority_contract": {
            "semantic_authority": "retained deployed Pool mapping WASM and checksum-pinned WABT 1.0.35 WAT",
            "source_text_role": "corroboration only and not used to promote this proof",
            "successful_handler_scope": (
                "legacy call-flow evidence applies to the normal-completion path; modern evidence proves the selected update/save body is entered only when both Token entities exist and is skipped otherwise"
            ),
            "selected_call_flow_rule": (
                "the two explicit selected setters use the Pool loaded from the trigger address and the selected-update path later passes the same Pool to the sole reachable Pool.save; this is call-flow evidence, not proof of persisted selected values"
            ),
            "effect_closure_rule": (
                "pin Graph store imports, the complete Burn transitive call/indirect closure, every reachable function body, direct memory-write and TypedMap.set site, and every loaded-Pool local use; inventory drift fails closed, but baseline sites outside the two explicit selected setters are not semantically classified for receiver, key, value, or alias"
            ),
            "in_memory_alias_boundary": (
                "the exact retained reachable-body inventory is authority; general heap-alias semantics and arbitrary direct selected-payload alias safety are not rederived"
            ),
            "host_boundary": (
                "bytesToHex, BigInt/BigDecimal, and Graph store host behavior are not rederived; modern hosts are assumed not to write arbitrary linear memory and legacy hosts are assumed not to reenter exported memory.reset during a handler"
            ),
            "allocator_freshness_boundary": (
                "wrapper, Value, entry, and array allocation identity is inherited from the same-WAT Pool runtime capsule only within one nonreentrant handler; cross-handler freshness remains false"
            ),
            "rollback_boundary": (
                "Pool.save precedes Burn.save; Graph handler atomic rollback and post-fatal persistence are not claimed from retained WAT"
            ),
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
        "residual_blockers": {
            "field_count": residual,
            "pool": [
                "Pool Burn selected TVL persistence remains incomplete because baseline dynamic/helper TypedMap keys, receiver aliases, and direct-memory aliases are not semantically closed",
                "Pool Burn txCount, conditional liquidity, derived ETH/USD values, Tick effects, and other entity writes remain incomplete",
                "Factory creation and Pool Initialize, Mint, Flash, and Swap contributions keep selected TVL complete histories false",
                "non-try tick-call result semantics, handler rollback, and post-fatal Graph execution are not retained-WAT claims",
            ],
            "execution": [
                "combined component ordering, runtime population, boundary continuity, oracle, parity, package consumption, checkpoint, backfill, and production gates remain false"
            ],
            "issue_38_acceptance_criterion_complete": False,
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
    verified_sources = sources or load_sources(
        root, recompute_wat=recompute_wat, wasm2wat=wasm2wat
    )
    expected = expected_contract_from_sources(verified_sources)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"Pool Burn contract missing: {CONTRACT_PATH}")
        value = load_json_strict(path)
        require(isinstance(value, dict), "Pool Burn contract must be one JSON object")
        actual = value
        require(path.read_text() == render(actual), "Pool Burn contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Pool Burn contract differs from generated proof")
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "Pool Burn truth-boundary key drift")
    for field in TRUE_FLAGS:
        require(truth[field] is True, f"proved Pool Burn gate drift: {field}")
    for field in FALSE_FLAGS:
        require(truth[field] is False, f"unproved Pool Burn gate promoted: {field}")
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
    except (
        VerificationError,
        INITIALIZE.VerificationError,
        POOL_RUNTIME.VerificationError,
        V2.VerificationError,
        WRITER.VerificationError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 Pool Burn TVL semantics v1: "
        f"{len(result['mapping_proofs'])} mappings, "
        f"{result['scope']['segment_field_call_flow_evidence_count']} segment-field call-flow evidence records, "
        f"{len(result['segment_diffs'])} diffs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
