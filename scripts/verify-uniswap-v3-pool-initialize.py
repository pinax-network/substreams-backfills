#!/usr/bin/env python3
"""Generate and fail-closed verify Uniswap V3 Pool Initialize semantics v1."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/pool-initialize/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-initialize-semantics/v1"

V2_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
V2_VERIFIER_SHA256 = "e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec"
V2_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
V2_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
V2_CONTRACT_VERSION = "uniswap-v3-segment-field-semantics/v2"

POOL_ABI_CID = "QmULRc8Ac1J6YFy11z7JRpyThb6f7nmL5mMTQvN7LKj2Vy"
POOL_ABI_PATH = Path(f"uniswap-v3/graft-ancestry/v1/artifacts/{POOL_ABI_CID}")
POOL_ABI_SHA256 = "df8064cbe381e7a929aa4e1a658ce3617daed0e871883bf29ced54112fdfdbfd"
POOL_ABI_BYTES = 19_634

HANDLER_ID = "Pool.handleInitialize"
HANDLER_EXPORT = "handleInitialize"
STORE_HOST_IMPORT_RE = re.compile(
    r'^\s*\(import "index" "(store\.[^"]+)" \(func \$([^\s\)]+)'
)
EXPECTED_STORE_HOST_IMPORTS = {
    "store.get": "~lib/@graphprotocol/graph-ts/index/store.get",
    "store.set": "~lib/@graphprotocol/graph-ts/index/store.set",
}
EVENT_PARAM_ARRAY_GET_CALL = (
    "~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get"
)
LEGACY_BIGINT_BYTE_SET_CALL = "~lib/internal/typedarray/TypedArray<u8>#__set"
MODERN_BIGINT_BYTE_SET_CALL = "~lib/typedarray/Uint8Array#__set"
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
SELECTED_FIELDS = {
    "sqrtPrice": {
        "schema_type": "BigInt!",
        "event_parameter_index": 0,
        "event_parameter_name": "sqrtPriceX96",
        "event_parameter_type": "uint160",
    },
    "tick": {
        "schema_type": "BigInt",
        "event_parameter_index": 1,
        "event_parameter_name": "tick",
        "event_parameter_type": "int24",
    },
}

TRUE_FLAGS = (
    "v2_contract_recomputed_and_pinned",
    "shared_pool_initialize_abi_verified",
    "all_eight_pool_mapping_wat_bindings_verified",
    "all_eight_pool_load_identities_proven",
    "all_eight_pool_initialize_field_value_flows_proven",
    "all_eight_pool_initialize_setter_receiver_flows_proven",
    "all_three_saving_profiles_same_pool_save_after_both_setters_proven",
    "all_five_no_save_profiles_have_no_transitive_pool_store",
    "pool_initialize_selected_handler_projection_complete",
    "all_sixteen_segment_field_projection_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "cumulative_selected_field_count_is_36",
    "cumulative_residual_field_count_is_230",
)

FALSE_FLAGS = (
    "pool_non_flash_handler_semantics_complete",
    "pool_mint_semantics_complete",
    "pool_burn_semantics_complete",
    "pool_swap_semantics_complete",
    "pool_complete_entity_history",
    "all_manifest_handler_field_semantics_complete",
    "all_stored_fields_exact",
    "all_pairwise_complete_writer_semantic_diffs_present",
    "contract_call_semantics_complete_for_all_handlers",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "post_fatal_execution_modeled",
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


V2 = load_module(
    "uniswap_v3_segment_field_semantics_v2_for_pool_initialize",
    V2_VERIFIER_PATH,
    V2_VERIFIER_SHA256,
)
WRITER = V2.WRITER


def normalized(line: str) -> str:
    return V2.normalized_wat_line(line)


def call_name(line: str) -> str | None:
    return V2.wat_call_name(line)


def local_name(line: str, operation: str = "get") -> str | None:
    value = normalized(line)
    if value.endswith(")"):
        value = value[:-1]
    match = re.fullmatch(rf"local\.{operation} (\$[^\s]+)", value)
    return match.group(1) if match is not None else None


def decoded_constant(line: str, memory: bytearray) -> str | None:
    return V2.decoded_wat_constant(line, memory)


def function_sha256(function: Any) -> str:
    return hashlib.sha256(function.payload).hexdigest()


def wat_slice_sha256(function: Any, start: int, end_inclusive: int) -> str:
    return V2.wat_slice_sha256(function, start, end_inclusive)


def json_diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    return V2.json_diff_paths(left, right, path)


def single_call(function: Any, suffix: str, field: str) -> int:
    matches = [
        index
        for index, line in enumerate(function.lines)
        if (call_name(line) or "").endswith(suffix)
    ]
    require(len(matches) == 1, f"{field} call count drift: {len(matches)}")
    return matches[0]


def single_suffix_function(functions: dict[str, Any], suffix: str, field: str) -> Any:
    matches = [function for name, function in functions.items() if name.endswith(suffix)]
    require(len(matches) == 1, f"{field} function count drift: {len(matches)}")
    return matches[0]


def require_instruction(function: Any, index: int, expected: str, field: str) -> None:
    require(
        0 <= index < len(function.lines) and normalized(function.lines[index]) == expected,
        f"{field} instruction drift at relative line {index}",
    )


def require_call(function: Any, index: int, suffix: str, field: str) -> None:
    require(
        0 <= index < len(function.lines)
        and (call_name(function.lines[index]) or "").endswith(suffix),
        f"{field} call drift at relative line {index}",
    )


def require_exact_call(function: Any, index: int, target: str, field: str) -> None:
    require(
        0 <= index < len(function.lines) and call_name(function.lines[index]) == target,
        f"{field} exact call target drift at relative line {index}",
    )


def require_no_local_reassignment(
    function: Any,
    local: str,
    start_exclusive: int,
    end_exclusive: int,
    field: str,
) -> None:
    assignments = [
        index
        for index in range(start_exclusive + 1, end_exclusive)
        if local_name(function.lines[index], "set") == local
        or local_name(function.lines[index], "tee") == local
    ]
    require(not assignments, f"{field} local {local} is reassigned at {assignments}")


def require_no_successful_path_bypass(function: Any, terminal: int, field: str) -> None:
    depths = V2.wat_control_depths(function.lines)
    for index in range(1, terminal):
        instruction = normalized(function.lines[index])
        require(
            instruction != "return"
            and re.match(r"^br(?:_if|_table)?\b", instruction) is None,
            f"{field} can bypass its terminal effect at relative line {index}",
        )
        require(
            instruction != "unreachable" or depths[index] > 0,
            f"{field} has a top-level trap before its terminal effect",
        )
    require_fatal_effects_confined_to_closed_trap_branches(function, terminal, field)


def effect_is_confined_to_closed_trap_branch(
    function: Any,
    effect: int,
    terminal: int,
) -> bool:
    depths = V2.wat_control_depths(function.lines)
    effect_depth = depths[effect]
    for start in range(1, effect):
        if not normalized(function.lines[start]).startswith("if "):
            continue
        end = V2.matching_wat_end(function.lines, start, "fatal effect trap branch")
        if not (start < effect < end < terminal):
            continue
        body = [normalized(line) for line in function.lines[start + 1 : end]]
        if any(
            item == "else"
            or item == "return"
            or re.match(r"^br(?:_if|_table)?\b", item)
            for item in body
        ):
            continue
        aborts = [
            index
            for index in range(start + 1, end)
            if depths[index] == effect_depth
            and (call_name(function.lines[index]) or "").endswith(
                ("builtins/abort", "env/abort")
            )
        ]
        unreachable = [
            index
            for index in range(start + 1, end)
            if depths[index] == effect_depth
            and normalized(function.lines[index]) == "unreachable"
        ]
        if any(abort < trap for abort in aborts for trap in unreachable):
            return True
    return False


def require_fatal_effects_confined_to_closed_trap_branches(
    function: Any,
    terminal: int,
    field: str,
) -> None:
    fatal_effects = [
        index
        for index in range(1, terminal)
        if normalized(function.lines[index]) == "unreachable"
        or (call_name(function.lines[index]) or "").endswith(
            ("builtins/abort", "env/abort")
        )
    ]
    unsafe = [
        index
        for index in fatal_effects
        if not effect_is_confined_to_closed_trap_branch(function, index, terminal)
    ]
    require(not unsafe, f"{field} has fatal effects outside a closed trap branch: {unsafe}")


def assignment_is_confined_to_trap_path(
    function: Any,
    assignment: int,
    terminal: int,
) -> bool:
    depths = V2.wat_control_depths(function.lines)
    assignment_depth = depths[assignment]
    for start in range(1, assignment):
        if not normalized(function.lines[start]).startswith("if "):
            continue
        end = V2.matching_wat_end(function.lines, start, "local assignment trap branch")
        if not (start < assignment < end < terminal):
            continue
        body = [normalized(line) for line in function.lines[assignment + 1 : end]]
        if any(
            item == "else"
            or item == "return"
            or re.match(r"^br(?:_if|_table)?\b", item)
            for item in body
        ):
            continue
        aborts = [
            index
            for index in range(assignment + 1, end)
            if depths[index] == assignment_depth
            and (call_name(function.lines[index]) or "").endswith(
                ("builtins/abort", "env/abort")
            )
        ]
        if any(
            any(
                normalized(function.lines[index]) == "unreachable"
                and depths[index] == assignment_depth
                for index in range(abort + 1, end)
            )
            for abort in aborts
        ):
            return True
    return False


def require_no_successful_path_local_reassignment(
    function: Any,
    local: str,
    start_exclusive: int,
    terminal_exclusive: int,
    field: str,
) -> None:
    assignments = [
        index
        for index in range(start_exclusive + 1, terminal_exclusive)
        if local_name(function.lines[index], "set") == local
        or local_name(function.lines[index], "tee") == local
    ]
    unsafe = [
        index
        for index in assignments
        if not assignment_is_confined_to_trap_path(function, index, terminal_exclusive)
    ]
    require(not unsafe, f"{field} local {local} can be reassigned on a successful path: {unsafe}")


def verify_pool_abi(root: Path, ancestry: dict[str, Any]) -> dict[str, Any]:
    path = root / POOL_ABI_PATH
    require(path.is_file(), f"Pool ABI artifact missing: {POOL_ABI_PATH}")
    require(path.stat().st_size == POOL_ABI_BYTES, "Pool ABI byte length drift")
    require(raw_sha256(path) == POOL_ABI_SHA256, "Pool ABI digest drift")
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    require(POOL_ABI_CID in artifacts, "Pool ABI missing from ancestry artifact closure")
    artifact = artifacts[POOL_ABI_CID]
    require(
        (artifact["path"], artifact["sha256"], artifact["bytes"])
        == (str(POOL_ABI_PATH), POOL_ABI_SHA256, POOL_ABI_BYTES),
        "Pool ABI ancestry binding drift",
    )
    value = load_json_strict(path)
    require(isinstance(value, list), "Pool ABI must be a JSON array")
    matches = [item for item in value if item.get("type") == "event" and item.get("name") == "Initialize"]
    require(len(matches) == 1, "Pool ABI Initialize event count drift")
    expected = {
        "anonymous": False,
        "inputs": [
            {
                "indexed": False,
                "internalType": "uint160",
                "name": "sqrtPriceX96",
                "type": "uint160",
            },
            {
                "indexed": False,
                "internalType": "int24",
                "name": "tick",
                "type": "int24",
            },
        ],
        "name": "Initialize",
        "type": "event",
    }
    require(matches[0] == expected, "Pool ABI Initialize signature drift")
    return {
        "cid": POOL_ABI_CID,
        "path": str(POOL_ABI_PATH),
        "bytes": POOL_ABI_BYTES,
        "sha256": POOL_ABI_SHA256,
        "event": expected,
    }


def resolve_tool(candidate: Path | None, executable: str) -> Path:
    if candidate is None:
        found = shutil.which(executable)
        require(found is not None, f"{executable} is required")
        candidate = Path(found)
    require(candidate.is_file(), f"{executable} not found: {candidate}")
    try:
        result = subprocess.run(
            [str(candidate), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"cannot execute {executable}: {error}") from error
    require(result.returncode == 0, f"{executable} --version failed")
    require(result.stdout.strip() == WRITER.WABT_VERSION, f"{executable} version drift")
    return candidate.resolve()


def load_pool_wat_context(
    root: Path,
    mapping_cid: str,
    writer: dict[str, Any],
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    analyses = {item["cid"]: item for item in writer["mapping_analyses"]}
    profiles = {
        item["mapping_cid"]: item
        for item in writer["pool_writer_contract"]["mapping_bindings"]
    }
    require(mapping_cid in analyses and mapping_cid in profiles, f"Pool mapping missing: {mapping_cid}")
    analysis = analyses[mapping_cid]
    profile = profiles[mapping_cid]
    require(analysis["component"] == "Pool", f"non-Pool mapping in Initialize proof: {mapping_cid}")
    artifact = root / f"uniswap-v3/graft-ancestry/v1/artifacts/{mapping_cid}"
    require(artifact.is_file(), f"retained Pool mapping missing: {mapping_cid}")
    require(raw_sha256(artifact) == analysis["sha256"], f"Pool WASM digest drift: {mapping_cid}")
    require(artifact.stat().st_size == analysis["bytes"], f"Pool WASM bytes drift: {mapping_cid}")
    executable = WRITER.resolve_wasm2wat(wasm2wat)
    payload = WRITER.run_wasm2wat(executable, artifact)
    require(
        hashlib.sha256(payload).hexdigest() == analysis["wat_sha256"],
        f"Pool WAT digest drift: {mapping_cid}",
    )
    wat_text = payload.decode()
    memory, functions, indirect_targets, exports = WRITER.parse_wat(wat_text)
    handler = WRITER.resolve_handler(functions, exports, HANDLER_EXPORT)
    require(
        handler.name == analysis["registered_handler_export_targets"][HANDLER_EXPORT],
        f"Initialize export target drift: {mapping_cid}",
    )
    binding = analysis["registered_handlers"][HANDLER_EXPORT]
    require(function_sha256(handler) == binding["body_sha256"], f"Initialize body drift: {mapping_cid}")
    require(handler.function_index == binding["wat_function_index"], f"Initialize function index drift: {mapping_cid}")
    return {
        "mapping_cid": mapping_cid,
        "analysis": analysis,
        "profile": profile,
        "artifact_path": str(artifact.relative_to(root)),
        "memory": memory,
        "functions": functions,
        "indirect_targets": indirect_targets,
        "exports": exports,
        "handler": handler,
        "wat_text": wat_text,
        "wasm2wat": executable,
    }


def prove_legacy_pool_load(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    functions = context["functions"]
    memory = context["memory"]
    load = single_call(handler, "schema/Pool.load", f"{cid} legacy Pool.load")
    require(load >= 3 and load + 1 < len(handler.lines), f"{cid} legacy Pool.load bounds drift")
    require_instruction(handler, load - 3, "local.get $p0", f"{cid} Pool event address")
    require_instruction(handler, load - 2, "i32.load", f"{cid} Pool event address")
    require_call(handler, load - 1, "typeConversion.bytesToHex", f"{cid} Pool event address")
    pool_local = local_name(handler.lines[load + 1], "tee")
    require(pool_local is not None, f"{cid} legacy Pool load result is not local-bound")
    require_no_local_reassignment(
        handler,
        "$p0",
        0,
        load - 3,
        f"{cid} original Initialize event",
    )
    depths = V2.wat_control_depths(handler.lines)
    require(depths[load] == depths[load + 1] == 0, f"{cid} legacy Pool load is conditional")

    helper = single_suffix_function(functions, "schema/Pool.load", f"{cid} Pool.load helper")
    require(len(helper.lines) == 4, f"{cid} Pool.load helper body shape drift")
    require(decoded_constant(helper.lines[1], memory) == "Pool", f"{cid} Pool.load target drift")
    require_instruction(helper, 2, "local.get $p0", f"{cid} Pool.load id")
    require_call(helper, 3, "index/store.get", f"{cid} Pool.load store.get")
    return {
        "generation": "legacy",
        "event_parameter": "$p0",
        "event_address_load": "i32.load offset 0",
        "address_conversion": call_name(handler.lines[load - 1]),
        "entity_target": "Pool",
        "pool_entity_local": pool_local,
        "handler_load_wat_line": handler.start_line + load,
        "helper_function": helper.name,
        "helper_body_sha256": function_sha256(helper),
        "helper_slice_sha256": wat_slice_sha256(helper, 1, 3),
        "event_address_to_pool_load_machine_proven": True,
    }


def prove_modern_pool_load(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    memory = context["memory"]
    candidates: list[int] = []
    for index, line in enumerate(handler.lines):
        if (call_name(line) or "").endswith("index/store.get") and index >= 4:
            if decoded_constant(handler.lines[index - 4], memory) == "Pool":
                candidates.append(index)
    require(len(candidates) == 1, f"{cid} modern Pool store.get count drift")
    load = candidates[0]
    require_instruction(handler, load - 3, "local.get $p0", f"{cid} Pool event address")
    require_instruction(handler, load - 2, "i32.load", f"{cid} Pool event address")
    require_call(handler, load - 1, "typeConversion.bytesToHex", f"{cid} Pool event address")
    pool_local = local_name(handler.lines[load + 1], "tee")
    require(pool_local is not None, f"{cid} modern Pool load result is not local-bound")
    require_no_local_reassignment(
        handler,
        "$p0",
        0,
        load - 3,
        f"{cid} original Initialize event",
    )
    require_instruction(handler, load + 2, "i32.eqz", f"{cid} missing Pool branch")
    require(normalized(handler.lines[load + 3]).startswith("if "), f"{cid} missing Pool branch absent")
    branch_end = V2.matching_wat_end(handler.lines, load + 3, f"{cid} missing Pool branch")
    branch = [normalized(line) for line in handler.lines[load + 4 : branch_end]]
    require(any((call_name(line) or "").endswith("builtins/abort") for line in handler.lines[load + 4 : branch_end]), f"{cid} missing Pool branch does not abort")
    require("unreachable" in branch, f"{cid} missing Pool branch can continue")
    require(
        not any(item == "else" or item == "return" or re.match(r"^br(?:_if|_table)?\b", item) for item in branch),
        f"{cid} missing Pool branch can bypass abort",
    )
    depths = V2.wat_control_depths(handler.lines)
    require(depths[load] == depths[branch_end] == 0, f"{cid} modern Pool load control depth drift")
    return {
        "generation": "modern",
        "event_parameter": "$p0",
        "event_address_load": "i32.load offset 0",
        "address_conversion": call_name(handler.lines[load - 1]),
        "entity_target": "Pool",
        "pool_entity_local": pool_local,
        "handler_load_wat_line": handler.start_line + load,
        "missing_pool_branch_wat_lines": [
            handler.start_line + load + 2,
            handler.start_line + branch_end,
        ],
        "missing_pool_branch_aborts_before_normal_continuation": True,
        "event_address_to_pool_load_machine_proven": True,
    }


def prove_value_from_bigint(functions: dict[str, Any], memory: bytearray, cid: str) -> dict[str, Any]:
    function = single_suffix_function(functions, "Value.fromBigInt", f"{cid} Value.fromBigInt")
    require(len(function.lines) == 11, f"{cid} Value.fromBigInt body shape drift")
    result_local = local_name(function.lines[3], "tee")
    require(result_local is not None, f"{cid} Value.fromBigInt result local missing")
    require_call(function, 2, "Value#constructor", f"{cid} Value.fromBigInt constructor")
    require_instruction(function, 4, "i32.const 7", f"{cid} Value.fromBigInt kind")
    require_instruction(function, 5, "i32.store", f"{cid} Value.fromBigInt kind store")
    require(local_name(function.lines[6]) == result_local, f"{cid} Value.fromBigInt payload receiver drift")
    require_instruction(function, 7, "local.get $p0", f"{cid} Value.fromBigInt input")
    require_instruction(function, 8, "i64.extend_i32_u", f"{cid} Value.fromBigInt pointer widening")
    require_instruction(function, 9, "i64.store offset=8", f"{cid} Value.fromBigInt payload store")
    require(local_name(function.lines[10]) == result_local, f"{cid} Value.fromBigInt return drift")
    return {
        "function": function.name,
        "body_sha256": function_sha256(function),
        "value_kind": 7,
        "input_parameter": "$p0",
        "returned_value_local": result_local,
        "input_to_bigint_value_payload_machine_proven": True,
    }


def prove_i32_bigint_conversion(
    functions: dict[str, Any],
    cid: str,
    generation: str,
) -> dict[str, Any]:
    suffix = "BigInt.fromI32" if generation == "modern" else "ByteArray.fromI32"
    function = single_suffix_function(functions, suffix, f"{cid} signed i32 BigInt conversion")
    require(len(function.lines) == 33, f"{cid} signed i32 conversion body shape drift")
    result_local = local_name(function.lines[4], "tee")
    require(result_local is not None, f"{cid} signed i32 conversion result local missing")
    require_instruction(function, 2, "i32.const 0", f"{cid} signed i32 constructor input")
    require_call(function, 3, "ByteArray#constructor", f"{cid} signed i32 constructor")
    expected_sets = [9, 17, 25, 31]
    byte_set_call = (
        MODERN_BIGINT_BYTE_SET_CALL
        if generation == "modern"
        else LEGACY_BIGINT_BYTE_SET_CALL
    )
    for index in expected_sets:
        require_exact_call(function, index, byte_set_call, f"{cid} signed i32 byte setter")
    require_instruction(function, 5, "i32.const 0", f"{cid} signed i32 byte 0 index")
    require_instruction(function, 6, "local.get $p0", f"{cid} signed i32 byte 0 input")
    require_instruction(function, 7, "i32.const 255", f"{cid} signed i32 byte 0 mask")
    require_instruction(function, 8, "i32.and", f"{cid} signed i32 byte 0 mask")
    for base, byte_index, shift in ((10, 1, 8), (18, 2, 16), (26, 3, 24)):
        require(local_name(function.lines[base]) == result_local, f"{cid} signed i32 byte receiver drift")
        require_instruction(function, base + 1, f"i32.const {byte_index}", f"{cid} signed i32 byte index")
        require_instruction(function, base + 2, "local.get $p0", f"{cid} signed i32 shifted input")
        require_instruction(function, base + 3, f"i32.const {shift}", f"{cid} signed i32 shift")
        require_instruction(function, base + 4, "i32.shr_s", f"{cid} signed i32 arithmetic shift")
        if byte_index < 3:
            require_instruction(function, base + 5, "i32.const 255", f"{cid} signed i32 shifted mask")
            require_instruction(function, base + 6, "i32.and", f"{cid} signed i32 shifted mask")
    require(local_name(function.lines[32]) == result_local, f"{cid} signed i32 conversion return drift")
    return {
        "function": function.name,
        "body_sha256": function_sha256(function),
        "input_parameter": "$p0",
        "returned_bigint_local": result_local,
        "little_endian_signed_byte_count": 4,
        "input_to_returned_bigint_machine_proven": True,
    }


def prove_legacy_schema_setter(
    context: dict[str, Any],
    field: str,
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    functions = context["functions"]
    memory = context["memory"]
    function = single_suffix_function(functions, f"schema/Pool#set:{field}", f"{cid} Pool.{field} setter")
    if field == "sqrtPrice":
        require(len(function.lines) == 6, f"{cid} Pool.sqrtPrice setter body shape drift")
        require_instruction(function, 1, "local.get $p0", f"{cid} Pool.sqrtPrice receiver")
        require(decoded_constant(function.lines[2], memory) == field, f"{cid} Pool.sqrtPrice key drift")
        require_instruction(function, 3, "local.get $p1", f"{cid} Pool.sqrtPrice value")
        require_call(function, 4, "Value.fromBigInt", f"{cid} Pool.sqrtPrice serialization")
        require_exact_call(function, 5, LEGACY_ENTITY_MAP_SET_CALL, f"{cid} Pool.sqrtPrice setter")
        value_conversion = prove_value_from_bigint(functions, memory, cid)
        return {
            "function": function.name,
            "body_sha256": function_sha256(function),
            "field_key": field,
            "receiver_parameter": "$p0",
            "value_parameter": "$p1",
            "value_conversion": value_conversion,
            "receiver_key_value_to_typed_map_set_machine_proven": True,
        }

    require(field == "tick", f"unsupported legacy Pool setter field: {field}")
    require(len(function.lines) == 13, f"{cid} Pool.tick setter body shape drift")
    require_instruction(function, 1, "local.get $p1", f"{cid} Pool.tick nullable branch input")
    require(normalized(function.lines[2]).startswith("if "), f"{cid} Pool.tick nullable branch drift")
    require_instruction(function, 3, "local.get $p0", f"{cid} Pool.tick receiver")
    require(decoded_constant(function.lines[4], memory) == field, f"{cid} Pool.tick key drift")
    require_instruction(function, 5, "local.get $p1", f"{cid} Pool.tick value")
    require_call(function, 6, "Value.fromBigInt", f"{cid} Pool.tick serialization")
    require_exact_call(function, 7, LEGACY_ENTITY_MAP_SET_CALL, f"{cid} Pool.tick setter")
    require_instruction(function, 8, "else", f"{cid} Pool.tick nullable else")
    require_instruction(function, 9, "local.get $p0", f"{cid} Pool.tick unset receiver")
    require(decoded_constant(function.lines[10], memory) == field, f"{cid} Pool.tick unset key drift")
    require_call(function, 11, "Entity#unset", f"{cid} Pool.tick unset")
    return {
        "function": function.name,
        "body_sha256": function_sha256(function),
        "field_key": field,
        "receiver_parameter": "$p0",
        "value_parameter": "$p1",
        "non_null_value_path": "Value.fromBigInt then TypedMap.set",
        "null_value_path": "Entity.unset",
        "receiver_key_value_to_nullable_setter_machine_proven": True,
    }


def prove_modern_tick_setter(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    functions = context["functions"]
    memory = context["memory"]
    function = single_suffix_function(functions, "schema/Pool#set:tick", f"{cid} Pool.tick setter")
    require(len(function.lines) == 39, f"{cid} modern Pool.tick setter body shape drift")
    require_instruction(function, 2, "local.get $p1", f"{cid} modern Pool.tick nullable input")
    require(normalized(function.lines[3]).startswith("if "), f"{cid} modern Pool.tick branch drift")
    set_calls = [
        index
        for index, line in enumerate(function.lines)
        if call_name(line) == MODERN_ENTITY_MAP_SET_CALL
    ]
    require(set_calls == [21, 37], f"{cid} modern Pool.tick setter callsite drift")
    require_instruction(function, 4, "local.get $p0", f"{cid} modern Pool.tick receiver")
    require(decoded_constant(function.lines[5], memory) == "tick", f"{cid} modern Pool.tick key drift")
    require_instruction(function, 7, "local.get $p1", f"{cid} modern Pool.tick value")
    require_instruction(function, 8, "i64.extend_i32_u", f"{cid} modern Pool.tick payload widening")
    payload_local = local_name(function.lines[9], "set")
    require(payload_local is not None, f"{cid} modern Pool.tick payload local missing")
    require_instruction(function, 10, "i32.const 16", f"{cid} modern Pool.tick Value bytes")
    require_instruction(function, 11, "i32.const 26", f"{cid} modern Pool.tick Value runtime id")
    require_call(function, 12, "__new", f"{cid} modern Pool.tick Value allocation")
    result_local = local_name(function.lines[13], "tee")
    require(result_local is not None, f"{cid} modern Pool.tick Value local missing")
    require_instruction(function, 14, "i32.const 7", f"{cid} modern Pool.tick Value kind")
    require_instruction(function, 15, "i32.store", f"{cid} modern Pool.tick Value kind store")
    require(local_name(function.lines[16]) == result_local, f"{cid} modern Pool.tick payload receiver drift")
    require(local_name(function.lines[17]) == payload_local, f"{cid} modern Pool.tick payload source drift")
    require_no_local_reassignment(
        function,
        payload_local,
        9,
        17,
        f"{cid} modern Pool.tick payload",
    )
    require_instruction(function, 18, "i64.store offset=8", f"{cid} modern Pool.tick payload store")
    require(local_name(function.lines[19]) == result_local, f"{cid} modern Pool.tick Value result drift")
    require_instruction(function, 20, "end", f"{cid} modern Pool.tick Value block")
    require_instruction(function, 22, "else", f"{cid} modern Pool.tick nullable else")
    require_instruction(function, 23, "local.get $p0", f"{cid} modern Pool.tick null receiver")
    require(decoded_constant(function.lines[24], memory) == "tick", f"{cid} modern Pool.tick null key drift")
    require_instruction(function, 30, "i32.const 5", f"{cid} modern Pool.tick null Value kind")
    return {
        "function": function.name,
        "body_sha256": function_sha256(function),
        "field_key": "tick",
        "receiver_parameter": "$p0",
        "value_parameter": "$p1",
        "payload_local": payload_local,
        "non_null_value_kind": 7,
        "null_value_kind": 5,
        "receiver_key_value_to_nullable_setter_machine_proven": True,
    }


def prove_legacy_initialize_params_constructor(
    functions: dict[str, Any],
    cid: str,
) -> dict[str, Any]:
    function = single_suffix_function(
        functions,
        "Initialize__Params#constructor",
        f"{cid} Initialize parameter wrapper constructor",
    )
    require(len(function.lines) == 11, f"{cid} Initialize parameter wrapper body shape drift")
    require_instruction(function, 2, "i32.const 4", f"{cid} Initialize wrapper bytes")
    require_call(function, 3, "__memory_allocate", f"{cid} Initialize wrapper allocation")
    wrapper_local = local_name(function.lines[4], "tee")
    require(wrapper_local is not None, f"{cid} Initialize wrapper local missing")
    require_instruction(function, 5, "i32.const 0", f"{cid} Initialize wrapper initialization")
    require_instruction(function, 6, "i32.store", f"{cid} Initialize wrapper initialization store")
    require(local_name(function.lines[7]) == wrapper_local, f"{cid} Initialize wrapper receiver drift")
    require_instruction(function, 8, "local.get $p0", f"{cid} Initialize wrapper event source")
    require_instruction(function, 9, "i32.store", f"{cid} Initialize wrapper event binding")
    require(local_name(function.lines[10]) == wrapper_local, f"{cid} Initialize wrapper return drift")
    return {
        "function": function.name,
        "body_sha256": function_sha256(function),
        "event_parameter": "$p0",
        "returned_wrapper_local": wrapper_local,
        "event_to_returned_wrapper_machine_proven": True,
    }


def prove_legacy_initialize_fields(
    context: dict[str, Any],
    load: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    functions = context["functions"]
    pool_local = load["pool_entity_local"]
    params_constructor = prove_legacy_initialize_params_constructor(functions, cid)
    sqrt_set = single_call(handler, "schema/Pool#set:sqrtPrice", f"{cid} Initialize sqrtPrice")
    require(sqrt_set >= 9, f"{cid} Initialize sqrtPrice bounds drift")
    require(local_name(handler.lines[sqrt_set - 9], "tee") == pool_local, f"{cid} sqrtPrice receiver is not loaded Pool")
    require_instruction(handler, sqrt_set - 8, "local.get $p0", f"{cid} sqrtPrice event")
    require_call(handler, sqrt_set - 7, "Initialize__Params#constructor", f"{cid} sqrtPrice params")
    require_instruction(handler, sqrt_set - 6, "i32.load", f"{cid} sqrtPrice params")
    require_instruction(handler, sqrt_set - 5, "i32.load offset=24", f"{cid} sqrtPrice params array")
    require_instruction(handler, sqrt_set - 4, "i32.const 0", f"{cid} sqrtPrice parameter index")
    require_exact_call(
        handler,
        sqrt_set - 3,
        EVENT_PARAM_ARRAY_GET_CALL,
        f"{cid} sqrtPrice parameter lookup",
    )
    require_instruction(handler, sqrt_set - 2, "i32.load offset=4", f"{cid} sqrtPrice event value")
    require_call(handler, sqrt_set - 1, "ethereum.Value#toBigInt", f"{cid} sqrtPrice conversion")
    sqrt_helper = prove_legacy_schema_setter(context, "sqrtPrice")

    tick_set = single_call(handler, "schema/Pool#set:tick", f"{cid} Initialize tick")
    require(tick_set >= 5, f"{cid} Initialize tick bounds drift")
    require(local_name(handler.lines[tick_set - 5]) == pool_local, f"{cid} tick receiver is not loaded Pool")
    require_instruction(handler, tick_set - 4, "local.get $p0", f"{cid} tick event")
    require_call(handler, tick_set - 3, "Initialize__Params#constructor", f"{cid} tick params")
    require_call(handler, tick_set - 2, "Initialize__Params#get:tick", f"{cid} tick getter")
    require_call(handler, tick_set - 1, "ByteArray.fromI32", f"{cid} tick BigInt conversion")
    getter = single_suffix_function(functions, "Initialize__Params#get:tick", f"{cid} Initialize tick getter")
    require(len(getter.lines) == 8, f"{cid} Initialize tick getter body shape drift")
    require_instruction(getter, 1, "local.get $p0", f"{cid} tick getter input")
    require_instruction(getter, 2, "i32.load", f"{cid} tick getter event")
    require_instruction(getter, 3, "i32.load offset=24", f"{cid} tick getter params")
    require_instruction(getter, 4, "i32.const 1", f"{cid} tick parameter index")
    require_exact_call(
        getter,
        5,
        EVENT_PARAM_ARRAY_GET_CALL,
        f"{cid} tick parameter lookup",
    )
    require_instruction(getter, 6, "i32.load offset=4", f"{cid} tick event value")
    require_call(getter, 7, "ethereum.Value#toI32", f"{cid} tick scalar conversion")
    bigint = prove_i32_bigint_conversion(functions, cid, "legacy")
    tick_helper = prove_legacy_schema_setter(context, "tick")

    depths = V2.wat_control_depths(handler.lines)
    require(depths[sqrt_set] == depths[tick_set] == 0, f"{cid} Initialize setters are conditional")
    require(sqrt_set < tick_set, f"{cid} Initialize setter order drift")
    load_result = int(load["handler_load_wat_line"]) - handler.start_line + 1
    require(sqrt_set - 9 == load_result, f"{cid} loaded Pool is not the direct sqrtPrice receiver")
    require_no_local_reassignment(handler, pool_local, load_result, tick_set, f"{cid} loaded Pool")
    require_no_local_reassignment(handler, "$p0", 0, tick_set, f"{cid} original Initialize event")
    require_no_successful_path_bypass(handler, tick_set, f"{cid} Initialize field projection")
    return {
        "event_parameter_wrapper": params_constructor,
        "sqrtPrice": {
            "event_parameter_index": 0,
            "event_parameter_name": "sqrtPriceX96",
            "event_parameter_type": "uint160",
            "handler_setter_wat_line": handler.start_line + sqrt_set,
            "setter": sqrt_helper,
            "loaded_pool_receiver_and_event_value_machine_proven": True,
        },
        "tick": {
            "event_parameter_index": 1,
            "event_parameter_name": "tick",
            "event_parameter_type": "int24",
            "handler_setter_wat_line": handler.start_line + tick_set,
            "getter_function": getter.name,
            "getter_body_sha256": function_sha256(getter),
            "signed_bigint_conversion": bigint,
            "setter": tick_helper,
            "loaded_pool_receiver_and_event_value_machine_proven": True,
        },
        "setter_order": ["Pool.sqrtPrice", "Pool.tick"],
        "both_setters_same_loaded_pool_machine_proven": True,
        "sqrt_set_index": sqrt_set,
        "tick_set_index": tick_set,
    }


def prove_modern_initialize_fields(
    context: dict[str, Any],
    load: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    memory = context["memory"]
    functions = context["functions"]
    pool_local = load["pool_entity_local"]

    sqrt_literals = [
        index for index, line in enumerate(handler.lines) if decoded_constant(line, memory) == "sqrtPrice"
    ]
    require(len(sqrt_literals) == 1, f"{cid} modern sqrtPrice field literal count drift")
    sqrt_literal = sqrt_literals[0]
    require(local_name(handler.lines[sqrt_literal - 1]) == pool_local, f"{cid} modern sqrtPrice receiver drift")
    value_local = local_name(handler.lines[sqrt_literal + 1])
    require(value_local is not None, f"{cid} modern sqrtPrice Value local missing")
    require_exact_call(
        handler,
        sqrt_literal + 2,
        MODERN_ENTITY_MAP_SET_CALL,
        f"{cid} modern sqrtPrice setter",
    )

    to_bigint = single_call(handler, "ethereum.Value#toBigInt", f"{cid} modern sqrtPrice conversion")
    require_instruction(handler, to_bigint - 6, "local.get $l3", f"{cid} modern sqrtPrice params object")
    params_local = local_name(handler.lines[to_bigint - 6])
    require(params_local is not None, f"{cid} modern sqrtPrice params local missing")
    require_instruction(handler, to_bigint - 5, "i32.load", f"{cid} modern sqrtPrice params object")
    require_instruction(handler, to_bigint - 4, "i32.load offset=24", f"{cid} modern sqrtPrice params array")
    require_instruction(handler, to_bigint - 3, "i32.const 0", f"{cid} modern sqrtPrice parameter index")
    require_exact_call(
        handler,
        to_bigint - 2,
        EVENT_PARAM_ARRAY_GET_CALL,
        f"{cid} modern sqrtPrice parameter lookup",
    )
    require_instruction(handler, to_bigint - 1, "i32.load offset=4", f"{cid} modern sqrtPrice event value")
    require(to_bigint >= 15, f"{cid} modern sqrtPrice params construction bounds drift")
    require_call(handler, to_bigint - 13, "__new", f"{cid} modern params allocation")
    require(local_name(handler.lines[to_bigint - 12], "tee") == params_local, f"{cid} modern params allocation local drift")
    require_instruction(handler, to_bigint - 9, f"local.get {params_local}", f"{cid} modern params event receiver")
    require_instruction(handler, to_bigint - 8, "local.get $p0", f"{cid} modern params event source")
    require_instruction(handler, to_bigint - 7, "i32.store", f"{cid} modern params event binding")
    bigint_local = local_name(handler.lines[to_bigint + 2], "set")
    require_instruction(handler, to_bigint + 1, "i64.extend_i32_u", f"{cid} modern sqrtPrice pointer widening")
    require(bigint_local is not None, f"{cid} modern sqrtPrice BigInt local missing")
    value_tee = next(
        (
            index
            for index in range(to_bigint + 3, sqrt_literal)
            if local_name(handler.lines[index], "tee") == value_local
        ),
        None,
    )
    require(value_tee is not None and value_tee >= 3, f"{cid} modern sqrtPrice Value allocation missing")
    require_instruction(handler, value_tee - 3, "i32.const 16", f"{cid} modern sqrtPrice Value bytes")
    require_instruction(handler, value_tee - 2, "i32.const 26", f"{cid} modern sqrtPrice Value runtime id")
    require_call(handler, value_tee - 1, "__new", f"{cid} modern sqrtPrice Value allocation")
    require_instruction(handler, value_tee + 1, "i32.const 7", f"{cid} modern sqrtPrice Value kind")
    require_instruction(handler, value_tee + 2, "i32.store", f"{cid} modern sqrtPrice Value kind store")
    require(local_name(handler.lines[value_tee + 3]) == value_local, f"{cid} modern sqrtPrice payload receiver drift")
    require(local_name(handler.lines[value_tee + 4]) == bigint_local, f"{cid} modern sqrtPrice payload source drift")
    require_no_local_reassignment(
        handler,
        bigint_local,
        to_bigint + 2,
        value_tee + 4,
        f"{cid} modern sqrtPrice BigInt",
    )
    require_instruction(handler, value_tee + 5, "i64.store offset=8", f"{cid} modern sqrtPrice payload store")
    require(value_tee + 9 == sqrt_literal + 2, f"{cid} modern sqrtPrice setter path is not contiguous")

    tick_set = single_call(handler, "schema/Pool#set:tick", f"{cid} modern Initialize tick")
    require(tick_set >= 18, f"{cid} modern tick bounds drift")
    require(local_name(handler.lines[tick_set - 9]) == pool_local, f"{cid} modern tick receiver drift")
    tick_params = local_name(handler.lines[tick_set - 8])
    require(tick_params is not None, f"{cid} modern tick params local missing")
    require_instruction(handler, tick_set - 7, "i32.load", f"{cid} modern tick params object")
    require_instruction(handler, tick_set - 6, "i32.load offset=24", f"{cid} modern tick params array")
    require_instruction(handler, tick_set - 5, "i32.const 1", f"{cid} modern tick parameter index")
    require_exact_call(
        handler,
        tick_set - 4,
        EVENT_PARAM_ARRAY_GET_CALL,
        f"{cid} modern tick parameter lookup",
    )
    require_instruction(handler, tick_set - 3, "i32.load offset=4", f"{cid} modern tick event value")
    require_call(handler, tick_set - 2, "ethereum.Value#toI32", f"{cid} modern tick scalar conversion")
    require_call(handler, tick_set - 1, "BigInt.fromI32", f"{cid} modern tick BigInt conversion")
    require_call(handler, tick_set - 16, "__new", f"{cid} modern tick params allocation")
    require(local_name(handler.lines[tick_set - 15], "tee") == tick_params, f"{cid} modern tick params allocation local drift")
    require_instruction(handler, tick_set - 12, f"local.get {tick_params}", f"{cid} modern tick params event receiver")
    require_instruction(handler, tick_set - 11, "local.get $p0", f"{cid} modern tick params event source")
    require_instruction(handler, tick_set - 10, "i32.store", f"{cid} modern tick params event binding")
    bigint = prove_i32_bigint_conversion(functions, cid, "modern")
    tick_helper = prove_modern_tick_setter(context)

    sqrt_set = sqrt_literal + 2
    depths = V2.wat_control_depths(handler.lines)
    require(depths[sqrt_set] == depths[tick_set] == 0, f"{cid} modern Initialize setters are conditional")
    require(sqrt_set < tick_set, f"{cid} modern Initialize setter order drift")
    require_no_local_reassignment(handler, pool_local, int(load["handler_load_wat_line"]) - handler.start_line + 1, tick_set, f"{cid} loaded Pool")
    require_no_local_reassignment(handler, "$p0", 0, tick_set, f"{cid} original Initialize event")
    require_no_successful_path_bypass(handler, tick_set, f"{cid} modern Initialize field projection")
    return {
        "event_parameter_wrapper": {
            "generation": "modern-inline",
            "sqrt_price_wrapper_local": params_local,
            "tick_wrapper_local": tick_params,
            "original_event_parameter": "$p0",
            "inline_event_to_wrapper_bindings_machine_proven": True,
        },
        "sqrtPrice": {
            "event_parameter_index": 0,
            "event_parameter_name": "sqrtPriceX96",
            "event_parameter_type": "uint160",
            "handler_setter_wat_line": handler.start_line + sqrt_set,
            "field_key_wat_line": handler.start_line + sqrt_literal,
            "value_kind": 7,
            "setter": {
                "function": call_name(handler.lines[sqrt_set]),
                "receiver_local": pool_local,
                "value_local": value_local,
                "inline_receiver_key_value_to_typed_map_set_machine_proven": True,
            },
            "loaded_pool_receiver_and_event_value_machine_proven": True,
        },
        "tick": {
            "event_parameter_index": 1,
            "event_parameter_name": "tick",
            "event_parameter_type": "int24",
            "handler_setter_wat_line": handler.start_line + tick_set,
            "signed_bigint_conversion": bigint,
            "setter": tick_helper,
            "loaded_pool_receiver_and_event_value_machine_proven": True,
        },
        "setter_order": ["Pool.sqrtPrice", "Pool.tick"],
        "both_setters_same_loaded_pool_machine_proven": True,
        "sqrt_set_index": sqrt_set,
        "tick_set_index": tick_set,
    }


def prove_pool_save_helper(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    functions = context["functions"]
    memory = context["memory"]
    helper = single_suffix_function(functions, "schema/Pool#save", f"{cid} Pool.save helper")
    store_set = single_call(helper, WRITER.STORE_SET_CALL, f"{cid} Pool.save store.set")
    require(store_set >= 4, f"{cid} Pool.save store.set bounds drift")
    require(decoded_constant(helper.lines[store_set - 4], memory) == "Pool", f"{cid} Pool.save target drift")
    id_local = local_name(helper.lines[store_set - 3])
    require(id_local is not None, f"{cid} Pool.save id local missing")
    require_call(helper, store_set - 2, "Value#toString", f"{cid} Pool.save id conversion")
    require_instruction(helper, store_set - 1, "local.get $p0", f"{cid} Pool.save entity argument")
    id_literals = [
        index for index, line in enumerate(helper.lines[:store_set]) if decoded_constant(line, memory) == "id"
    ]
    require(len(id_literals) == 1, f"{cid} Pool.save id field literal count drift")
    id_literal = id_literals[0]
    require_instruction(helper, id_literal - 1, "local.get $p0", f"{cid} Pool.save id receiver")
    map_get_call = (
        MODERN_ENTITY_MAP_GET_CALL
        if context["profile"]["control_generation"] == "modern"
        else LEGACY_ENTITY_MAP_GET_CALL
    )
    require_exact_call(helper, id_literal + 1, map_get_call, f"{cid} Pool.save id getter")
    require(local_name(helper.lines[id_literal + 2], "tee") == id_local, f"{cid} Pool.save id result local drift")
    require_instruction(helper, id_literal + 3, "i32.eqz", f"{cid} Pool.save missing-id check")
    require(normalized(helper.lines[id_literal + 4]).startswith("if "), f"{cid} Pool.save missing-id branch drift")
    missing_end = V2.matching_wat_end(helper.lines, id_literal + 4, f"{cid} Pool.save missing-id branch")
    missing_branch = [normalized(line) for line in helper.lines[id_literal + 5 : missing_end]]
    require(
        any(
            (call_name(line) or "").endswith(("builtins/abort", "env/abort"))
            for line in helper.lines[id_literal + 5 : missing_end]
        )
        and "unreachable" in missing_branch,
        f"{cid} Pool.save missing-id branch can continue",
    )
    require_no_successful_path_local_reassignment(
        helper,
        id_local,
        id_literal + 2,
        store_set,
        f"{cid} Pool.save id Value",
    )
    depths = V2.wat_control_depths(helper.lines)
    require(depths[store_set] in {0, 1}, f"{cid} Pool.save store.set control depth drift")
    if depths[store_set] == 1:
        enclosing_if = next(
            (
                index
                for index in range(missing_end + 1, store_set)
                if normalized(helper.lines[index]).startswith("if ")
                and V2.matching_wat_end(
                    helper.lines,
                    index,
                    f"{cid} Pool.save present-id branch",
                )
                > store_set
            ),
            None,
        )
        require(
            enclosing_if is not None,
            f"{cid} Pool.save conditional store has no enclosing present-id branch",
        )
        require(
            local_name(helper.lines[enclosing_if - 1]) == id_local,
            f"{cid} Pool.save present-id branch input drift",
        )
        require_no_local_reassignment(
            helper,
            id_local,
            missing_end,
            enclosing_if,
            f"{cid} Pool.save id",
        )
    before = [normalized(line) for line in helper.lines[id_literal + 3 : store_set]]
    require(
        not any(
            item in {"else", "return"}
            or re.match(r"^br(?:_if|_table)?\b", item)
            for item in before
        ),
        f"{cid} Pool.save can bypass store.set on normal execution",
    )
    require_fatal_effects_confined_to_closed_trap_branches(
        helper,
        store_set,
        f"{cid} Pool.save store path",
    )
    require_no_successful_path_local_reassignment(
        helper,
        "$p0",
        0,
        store_set,
        f"{cid} Pool.save original entity parameter",
    )
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "entity_target": "Pool",
        "id_field": "id",
        "entity_parameter": "$p0",
        "entity_parameter_preserved_on_all_normal_store_paths": True,
        "store_set_wat_line": helper.start_line + store_set,
        "normal_execution_reaches_store_set": True,
        "id_and_entity_argument_dataflow_machine_proven": True,
    }


def verify_store_host_imports(context: dict[str, Any]) -> list[dict[str, str]]:
    cid = context["mapping_cid"]
    matches = [
        match.groups()
        for line in context["wat_text"].splitlines()
        if (match := STORE_HOST_IMPORT_RE.match(line)) is not None
    ]
    names = [name for name, _symbol in matches]
    require(len(names) == len(set(names)), f"{cid} duplicate Graph store host import")
    imports = dict(matches)
    require(
        imports == EXPECTED_STORE_HOST_IMPORTS,
        f"{cid} Graph store host import surface drift: {sorted(imports)}",
    )
    return [
        {"module": "index", "name": name, "function": imports[name]}
        for name in sorted(imports)
    ]


def recompute_transitive_store_evidence(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    functions = context["functions"]
    memory = context["memory"]
    handler = context["handler"]
    indirect_targets = tuple(context["indirect_targets"])
    store_host_imports = verify_store_host_imports(context)
    callsites = WRITER.extract_store_set_callsites(functions, memory)
    WRITER.require_fixed_callsites(callsites, f"{cid} recomputed Initialize closure")
    reachable = WRITER.reachable_functions(functions, handler, indirect_targets)
    pool_save_helper = single_suffix_function(
        functions,
        "schema/Pool#save",
        f"{cid} Pool.save reachable-call inventory",
    )
    pool_save_call_target = pool_save_helper.name.replace(
        "generated/schema/", "src/types/schema/"
    )
    reachable_indirect_count = sum(
        line.count("call_indirect")
        for name in reachable
        for line in functions[name].lines
    )
    sites = [item for item in callsites if item["function"] in reachable]
    pool_sites = [item for item in sites if item["target"] == "Pool"]
    pool_save_calls = [
        {
            "function": name,
            "relative_wat_line": index,
            "wat_line": functions[name].start_line + index,
        }
        for name in sorted(reachable)
        for index, line in enumerate(functions[name].lines)
        if call_name(line) == pool_save_call_target
    ]
    require(not any(item["target"] is None for item in sites), f"{cid} dynamic Initialize store target")
    return {
        "reachable_function_count": len(reachable),
        "reachable_call_indirect_instruction_count": reachable_indirect_count,
        "closed_indirect_table_targets": list(indirect_targets) if reachable_indirect_count else [],
        "reachable_store_set_site_count": len(sites),
        "reachable_store_set_targets": sorted({item["target"] for item in sites}),
        "reachable_store_set_site_ids": [item["site_id"] for item in sites],
        "reachable_store_set_site_ids_sha256": canonical_sha256([item["site_id"] for item in sites]),
        "reachable_pool_store_set_sites": [
            {
                "site_id": item["site_id"],
                "function": item["function"],
                "wat_line": item["wat_line"],
            }
            for item in pool_sites
        ],
        "reachable_pool_save_calls": pool_save_calls,
        "dynamic_reachable_store_set_target_count": 0,
        "store_host_imports": store_host_imports,
        "unmodelled_store_mutation_host_import_count": 0,
        "recomputed_from_current_wat_functions": True,
    }


def prove_initialize_persistence(
    context: dict[str, Any],
    load: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    profile = context["profile"]
    pool_local = load["pool_entity_local"]
    tick_set = fields["tick_set_index"]
    sqrt_set = fields["sqrt_set_index"]
    saves = [
        index
        for index, line in enumerate(handler.lines)
        if (call_name(line) or "").endswith("schema/Pool#save")
    ]
    transitive = recompute_transitive_store_evidence(context)
    expected = bool(profile["initialize_persists_pool"])
    if expected:
        require(len(saves) == 1, f"{cid} Initialize direct Pool.save count drift")
        save = saves[0]
        require(save == tick_set + 2, f"{cid} Pool.save is not immediately after tick setter")
        require(local_name(handler.lines[save - 1]) == pool_local, f"{cid} Pool.save receiver drift")
        depths = V2.wat_control_depths(handler.lines)
        require(depths[sqrt_set] == depths[tick_set] == depths[save] == 0, f"{cid} Pool save path is conditional")
        require_no_local_reassignment(handler, pool_local, sqrt_set, save, f"{cid} Pool save receiver")
        helper = prove_pool_save_helper(context)
        require("Pool" in transitive["reachable_store_set_targets"], f"{cid} saving profile lacks Pool store")
        require(
            transitive["reachable_pool_save_calls"]
            == [
                {
                    "function": handler.name,
                    "relative_wat_line": save,
                    "wat_line": handler.start_line + save,
                }
            ],
            f"{cid} saving profile has an additional reachable Pool.save",
        )
        require(
            transitive["reachable_pool_store_set_sites"]
            == [
                {
                    "site_id": f"{helper['function']}#1",
                    "function": helper["function"],
                    "wat_line": helper["store_set_wat_line"],
                }
            ],
            f"{cid} saving profile has an additional reachable Pool store.set",
        )
        return {
            "profile_expected_to_persist": True,
            "direct_pool_save_count": 1,
            "handler_save_wat_line": handler.start_line + save,
            "effect_order": ["Pool.sqrtPrice set", "Pool.tick set", "Pool.save"],
            "saved_entity_local": pool_local,
            "save_helper": helper,
            "transitive_store_evidence": transitive,
            "same_loaded_pool_save_after_both_setters_machine_proven": True,
            "no_transitive_pool_store_machine_proven": False,
            "persisted_selected_handler_effect": "set Pool.sqrtPrice and Pool.tick from Initialize event parameters",
        }

    require(not saves, f"{cid} historical no-save profile has direct Pool.save")
    require("Pool" not in transitive["reachable_store_set_targets"], f"{cid} historical no-save profile reaches Pool store")
    require(not transitive["reachable_pool_save_calls"], f"{cid} historical profile reaches Pool.save")
    require(not transitive["reachable_pool_store_set_sites"], f"{cid} historical profile reaches Pool store.set")
    return {
        "profile_expected_to_persist": False,
        "direct_pool_save_count": 0,
        "handler_save_wat_line": None,
        "effect_order": ["Pool.sqrtPrice in-memory set", "Pool.tick in-memory set", "no Pool store"],
        "saved_entity_local": None,
        "save_helper": None,
        "transitive_store_evidence": transitive,
        "same_loaded_pool_save_after_both_setters_machine_proven": False,
        "no_transitive_pool_store_machine_proven": True,
        "persisted_selected_handler_effect": "no persisted Pool field change",
    }


def prove_pool_initialize_wat_context(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile = context["profile"]
    generation = profile["control_generation"]
    require(generation in {"legacy", "modern"}, f"{cid} Pool generation drift")
    load = prove_legacy_pool_load(context) if generation == "legacy" else prove_modern_pool_load(context)
    fields = (
        prove_legacy_initialize_fields(context, load)
        if generation == "legacy"
        else prove_modern_initialize_fields(context, load)
    )
    persistence = prove_initialize_persistence(context, load, fields)
    upstream = profile["initialize_persistence_observation"]
    require(upstream["same_path_machine_proven"] is False, f"{cid} upstream persistence gap already closed")
    require(
        upstream["lexical_pool_save_callsite_present"] is persistence["profile_expected_to_persist"],
        f"{cid} upstream persistence classification drift",
    )
    handler = context["handler"]
    return {
        "mapping_cid": cid,
        "profile_id": profile["profile_id"],
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
        },
        "pool_load_identity": load,
        "field_value_and_setter_flow": {
            "event_parameter_wrapper": fields["event_parameter_wrapper"],
            "sqrtPrice": fields["sqrtPrice"],
            "tick": fields["tick"],
            "setter_order": fields["setter_order"],
            "both_setters_same_loaded_pool_machine_proven": fields[
                "both_setters_same_loaded_pool_machine_proven"
            ],
        },
        "persistence": persistence,
        "closed_upstream_control_dataflow_paths": [
            "$.initialize_persistence_observation.same_path_machine_proven"
        ],
        "selected_handler_projection_complete": True,
        "complete_pool_handler_semantics": False,
    }


def build_pool_initialize_proofs(
    root: Path,
    writer: dict[str, Any],
    wasm2wat: Path | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    cids = sorted(
        item["mapping_cid"]
        for item in writer["pool_writer_contract"]["mapping_bindings"]
    )
    require(len(cids) == 8 and len(set(cids)) == 8, "Pool mapping count drift")
    contexts = {cid: load_pool_wat_context(root, cid, writer, wasm2wat) for cid in cids}
    proofs = [prove_pool_initialize_wat_context(contexts[cid]) for cid in cids]
    require(sum(item["persistence"]["profile_expected_to_persist"] for item in proofs) == 3, "saving Pool profile count drift")
    require(sum(item["persistence"]["no_transitive_pool_store_machine_proven"] for item in proofs) == 5, "no-save Pool profile count drift")
    require(sum(len(item["closed_upstream_control_dataflow_paths"]) for item in proofs) == 8, "closed Pool persistence path count drift")
    return proofs, contexts


def selected_v2_fields(v2: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_identity = {(item["entity"], item["field"]): item for item in v2["field_catalog"]}
    records = tuple(by_identity[("Pool", field)] for field in SELECTED_FIELDS)
    for record in records:
        require(record["semantic_status"] == "digest_bound_reviewed_incomplete", f"v2 selected Pool field status drift: {record['field']}")
        require(record["complete_selected_handler_projection"] is False, f"v2 selected Pool field already complete: {record['field']}")
        require(record["complete_entity_history"] is False, f"v2 Pool history unexpectedly complete: {record['field']}")
    return records  # type: ignore[return-value]


def build_segments(
    matrix: dict[str, Any],
    v2: dict[str, Any],
    proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    v2_fields = {item["field"]: item for item in selected_v2_fields(v2)}
    results: list[dict[str, Any]] = []
    for segment in matrix["segments"]:
        binding = segment["profile_bindings"]["pool"]
        cid = binding["mapping_cid"]
        require(cid in proof_by_cid, f"Pool Initialize proof missing for segment: {segment['segment_id']}")
        proof = proof_by_cid[cid]
        handler = next(item for item in segment["handlers"] if item["handler_id"] == HANDLER_ID)
        require(handler["event"] == "Initialize(uint160,int24)", f"Initialize handler event drift: {segment['segment_id']}")
        require(handler["mapping_cid"] == cid, f"Initialize handler mapping drift: {segment['segment_id']}")
        saving = proof["persistence"]["profile_expected_to_persist"]
        fields: list[dict[str, Any]] = []
        for field, definition in SELECTED_FIELDS.items():
            v2_record = v2_fields[field]
            fields.append(
                {
                    "entity": "Pool",
                    "field": field,
                    "schema_type": definition["schema_type"],
                    "event_parameter_index": definition["event_parameter_index"],
                    "event_parameter_name": definition["event_parameter_name"],
                    "event_parameter_type": definition["event_parameter_type"],
                    "population_classification": "conditional",
                    "selected_handler_projection": (
                        f"set to Initialize.{definition['event_parameter_name']}"
                        if saving
                        else "preserve persisted value because this handler has no transitive Pool store"
                    ),
                    "complete_selected_handler_projection": True,
                    "complete_entity_history": False,
                    "cumulative_semantic_status": "certified_selected_handler_projection",
                    "v2_field_record_sha256": canonical_sha256(v2_record),
                    "residual_history_blocker": (
                        "Factory creation and Pool Mint, Burn, Swap, and Flash contributions remain incomplete"
                    ),
                }
            )
        semantic_surface = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "pool_load_identity": proof["pool_load_identity"],
            "field_value_and_setter_flow": proof["field_value_and_setter_flow"],
            "persistence": proof["persistence"],
            "fields": fields,
            "selected_handler_projection_complete": True,
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
    require(len(results) == 8 and len({item["segment_id"] for item in results}) == 8, "segment projection count drift")
    require(sum(len(item["semantic_surface"]["fields"]) for item in results) == 16, "segment-field projection count drift")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = json_diff_paths(left["provenance_surface"], right["provenance_surface"])
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
    require(len(results) == 28, "Pool Initialize pairwise diff count drift")
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
    v2_contract_path = root / V2_CONTRACT_PATH
    require(v2_contract_path.is_file(), f"v2 field contract missing: {V2_CONTRACT_PATH}")
    require(raw_sha256(v2_contract_path) == V2_CONTRACT_SHA256, "v2 field contract digest drift")
    v2_sources = V2.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    v2_contract = V2.verify_contract(
        root,
        sources=v2_sources,
        recompute_wat=False,
    )
    require(v2_contract["contract_version"] == V2_CONTRACT_VERSION, "v2 field contract version drift")
    abi = verify_pool_abi(root, v2_sources["ancestry"])
    if recompute_wat:
        proofs, contexts = build_pool_initialize_proofs(
            root,
            v2_sources["writer_compatibility"],
            wasm2wat,
        )
    else:
        proofs = []
        contexts = {}
    return {
        "v2_sources": v2_sources,
        "v2_contract": v2_contract,
        "pool_abi": abi,
        "pool_initialize_proofs": proofs,
        "pool_wat_contexts": contexts,
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    v2 = sources["v2_contract"]
    v2_sources = sources["v2_sources"]
    proofs = sources["pool_initialize_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 8, "recomputed Pool Initialize proofs are required")
    segments = build_segments(v2_sources["segment_writer_matrix"], v2, proofs)
    diffs = build_segment_diffs(segments)
    inherited_selected = sum(item["complete_selected_handler_projection"] for item in v2["field_catalog"])
    require(inherited_selected == 34, "inherited v2 selected-field count drift")
    cumulative_selected = inherited_selected + len(SELECTED_FIELDS)
    require(cumulative_selected == 36, "cumulative selected-field count drift")
    residual = v2["scope"]["remaining_conditional_field_count"] - len(SELECTED_FIELDS)
    require(residual == 230, "cumulative residual-field count drift")
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "retained-wat-selected-handler-persistence-supplement",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "pool_mapping_count": 8,
            "handler": HANDLER_ID,
            "selected_fields": ["Pool.sqrtPrice", "Pool.tick"],
            "selected_field_count": 2,
            "segment_field_projection_count": 16,
            "saving_profile_count": 3,
            "no_save_profile_count": 5,
            "pairwise_scoped_diff_count": 28,
            "upstream_persistence_paths_closed": 8,
            "inherited_v2_selected_field_count": inherited_selected,
            "cumulative_selected_field_count": cumulative_selected,
            "inherited_v2_residual_field_count": v2["scope"]["remaining_conditional_field_count"],
            "cumulative_residual_field_count": residual,
            "claim": (
                "exact retained-WAT Pool.handleInitialize selected-handler projection for "
                "Pool.sqrtPrice and Pool.tick; complete Pool histories remain false"
            ),
        },
        "source_contracts": {
            "segment_field_semantics_v2": {
                "path": str(V2_CONTRACT_PATH),
                "contract_version": V2_CONTRACT_VERSION,
                "raw_sha256": V2_CONTRACT_SHA256,
            },
            "segment_field_semantics_v2_verifier": {
                "path": str(V2_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": V2_VERIFIER_SHA256,
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
        "pool_initialize_abi": sources["pool_abi"],
        "authority_contract": {
            "semantic_authority": (
                "retained deployed Pool mapping WASM and checksum-pinned WABT 1.0.35 WAT"
            ),
            "source_text_role": "corroboration only and not used to promote this proof",
            "successful_handler_scope": (
                "field and persistence projection applies only to a normally completed handler; "
                "Graph rollback and post-fatal execution remain outside this retained-WAT proof"
            ),
            "positive_persistence_rule": (
                "the proven handler call is the sole reachable Pool.save and its generated "
                "store.set is the sole reachable Pool write in each saving profile"
            ),
            "negative_persistence_rule": (
                "pin the Graph store host-import surface, recompute the complete Initialize "
                "transitive call closure, and reject any unmodelled mutation import or dynamic, "
                "indirectly unclosed, direct, dormant, or helper-reachable Pool write"
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
                "Mint, Burn, and Swap field formulas and helper side effects remain incomplete",
                "Factory, Mint, Burn, Swap, and Flash contributions keep Pool.sqrtPrice and Pool.tick complete histories false",
                "contract-call failure, handler rollback, and post-fatal Graph execution are not retained-WAT claims",
            ],
            "execution": [
                "combined component scheduling and dynamic-data-source stages remain unimplemented",
                "runtime population, boundary continuity, oracle, parity, package consumption, checkpoint, backfill, and production gates remain false",
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
        require(path.is_file(), f"Pool Initialize contract missing: {CONTRACT_PATH}")
        value = load_json_strict(path)
        require(isinstance(value, dict), "Pool Initialize contract must be one JSON object")
        actual = value
        require(path.read_text() == render(actual), "Pool Initialize contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Pool Initialize contract differs from generated proof")
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "Pool Initialize truth-boundary key drift")
    for field in TRUE_FLAGS:
        require(truth[field] is True, f"proved Pool Initialize gate drift: {field}")
    for field in FALSE_FLAGS:
        require(truth[field] is False, f"unproved Pool completion gate promoted: {field}")
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
    except (OSError, VerificationError, V2.VerificationError) as error:
        print(f"Pool Initialize semantics verification failed: {error}", file=sys.stderr)
        return 1
    digest = raw_sha256(args.root.resolve() / CONTRACT_PATH)
    print(
        "verified Uniswap V3 Pool Initialize semantics: "
        f"{contract['scope']['pool_mapping_count']} mappings, "
        f"{contract['scope']['segment_field_projection_count']} segment-field projections, "
        f"{contract['scope']['pairwise_scoped_diff_count']} diffs, sha256 {digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
