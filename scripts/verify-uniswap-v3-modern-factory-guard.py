#!/usr/bin/env python3
"""Verify the two retained modern Factory excluded-pool guards.

This is deliberately a bounded proof, not a general WAT analyzer.  It binds
the complete guard instruction region for the two exact deployed artifacts,
parses every structured-control edge, versions every mutable local write, and
symbolically evaluates both finite loops.  Any instruction outside the
reviewed shape fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/factory-guard/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-factory-guard/v1"
V2_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
V2_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
V2_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
PR59_HEAD = "2eb0cc6db9634f5cb19de30f959b33665b7e6f57"
EXCLUDED_POOL = "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248"

V2_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_segment_field_semantics_v2_for_factory_guard", V2_PATH
)
if V2_SPEC is None or V2_SPEC.loader is None:
    raise RuntimeError(f"cannot import {V2_PATH}")
V2 = importlib.util.module_from_spec(V2_SPEC)
sys.modules[V2_SPEC.name] = V2
V2_SPEC.loader.exec_module(V2)
WRITER = V2.WRITER


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
    output: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in output, f"duplicate JSON key: {key}")
        output[key] = value
    return output


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error
    require(isinstance(value, dict), f"{path} must contain one JSON object")
    return value


EXPECTED_ARTIFACTS: dict[str, dict[str, Any]] = {
    "QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr": {
        "profile_id": "modern-base",
        "wasm_sha256": "296eb1ad59dca0ef5000e7e48971cb4c39ce8a3d8cfeb7541f6e8b924d049694",
        "wat_sha256": "ea8185d6d94ff68dbb041684f29d23d528c6784a3396542657f9708d73d70972",
        "handler_body_sha256": "485b7aab032b388184d0fe5535d40cd80176f0bc5cfd2682676824eff3f98dc8",
        "guard_slice_sha256": "c6599a5353fd1fa4f2c486f36a56ab3919f2214dadfda3e6c5e43df3d9cf72e4",
        "helper_bindings_sha256": "2909591ea7efc260619461f425a399127d06bc2bb3555552725560284d9a0a93",
        "static": {
            "header": 3404,
            "literal": 3408,
            "input": 3520,
            "odd": 3584,
            "source": 3648,
            "x": 3776,
        },
    },
    "QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb": {
        "profile_id": "modern-mainnet",
        "wasm_sha256": "9a33e52667ce538278f9ab88ac9818f5442021e8a2ddb22fd5994a9643148887",
        "wat_sha256": "84064b99fa818216ac5090dcf2a8f6b16acfe5f93edcc9819d0cb88d84526449",
        "handler_body_sha256": "245ffe7ad61554106f9a5c748bb2cd629287a4fb0ecffa72c956d94915272dd5",
        "guard_slice_sha256": "22452dc9c72c8bc1ff4371f5b4805548f7e538c8c99d3645fecf6b27ac75b1a5",
        "helper_bindings_sha256": "f7ce1908669f1f0faad4cb7022de7d7b65402ef7a5b37bd51090d3f7e8b16c54",
        "static": {
            "header": 5420,
            "literal": 5424,
            "input": 5536,
            "odd": 5600,
            "source": 5664,
            "x": 5792,
        },
    },
}


TRUE_FLAGS = {
    "exact_pr59_v2_contract_bytes_pinned",
    "exact_two_modern_factory_wasm_and_wat_artifacts_pinned",
    "all_guard_instructions_and_structured_control_edges_accounted",
    "all_guard_mutable_local_and_heap_writes_accounted",
    "both_modern_event_pool_value_flows_machine_proven",
    "both_modern_excluded_literal_byte_array_flows_machine_proven",
    "both_modern_length_and_byte_comparison_paths_machine_proven",
    "both_modern_equal_only_early_return_directions_machine_proven",
    "exactly_two_modern_factory_guard_paths_closed",
    "cumulative_factory_paths_closed_is_6_of_18",
    "cumulative_factory_paths_residual_is_12_of_18",
}

FALSE_FLAGS = {
    "factory_effect_order_same_path_proven",
    "factory_effect_arguments_proven",
    "factory_template_identity_and_argument_proven",
    "factory_total_supply_success_failure_dataflow_proven",
    "factory_complete_static_handler_contract_proven",
    "factory_all_initialized_field_values_proven",
    "factory_handler_semantics_complete",
    "runtime_population_complete",
    "writer_runtime_consumes_this_contract",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "graph_execution_trace_complete",
    "boundary_state_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "backfill_ready",
    "production_ready",
}


def normalized(line: str) -> str:
    return line.strip().replace("generated/schema/", "src/types/schema/")


def guard_template(static: dict[str, int]) -> list[str]:
    """Return the complete reviewed modern guard region, including return."""
    header = static["header"]
    literal = static["literal"]
    return [
        "(func $src/mappings/factory/handlePoolCreated (type $t5) (param $p0 i32)",
        "(local $l1 i32) (local $l2 i32) (local $l3 i32) (local $l4 i32) (local $l5 i32) (local $l6 i32) (local $l7 i32) (local $l8 i32) (local $l9 i64)",
        "block $B0 (result i32)",
        "i32.const 4",
        "i32.const 24",
        "call $~lib/rt/stub/__new",
        "local.tee $l1",
        "i32.const 0",
        "i32.store",
        "local.get $l1",
        "local.get $p0",
        "i32.store",
        "local.get $l1",
        "i32.load",
        "i32.load offset=24",
        "i32.const 4",
        "call $~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get",
        "i32.load offset=4",
        "call $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value#toAddress",
        "local.set $l1",
        f"i32.const {header}",
        "i32.load",
        "i32.const 1",
        "i32.shr_u",
        "i32.const 1",
        "i32.and",
        "if $I1",
        f"i32.const {static['input']}",
        f"i32.const {literal}",
        "call $~lib/string/String#concat",
        f"i32.const {static['odd']}",
        "call $~lib/string/String#concat",
        f"i32.const {static['source']}",
        "i32.const 75",
        "i32.const 5",
        "call $~lib/builtins/abort",
        "unreachable",
        "end",
        f"i32.const {header}",
        "i32.load",
        "i32.const 1",
        "i32.shr_u",
        "i32.const 2",
        "i32.ge_u",
        "if $I2 (result i32)",
        f"i32.const {literal}",
        "i32.const 0",
        "call $~lib/string/String#charAt",
        "i32.const 2064",
        "call $~lib/string/String.__eq",
        "else",
        "i32.const 0",
        "end",
        "if $I3 (result i32)",
        f"i32.const {literal}",
        "i32.const 1",
        "call $~lib/string/String#charAt",
        f"i32.const {static['x']}",
        "call $~lib/string/String.__eq",
        "else",
        "i32.const 0",
        "end",
        "if $I4 (result i32)",
        f"i32.const {literal}",
        "i32.const 2",
        "i32.const 2147483647",
        "call $~lib/string/String#substr",
        "else",
        f"i32.const {literal}",
        "end",
        "local.tee $l3",
        "i32.const 20",
        "i32.sub",
        "i32.load offset=16",
        "i32.const 2",
        "i32.shr_u",
        "local.set $l5",
        "i32.const 12",
        "i32.const 9",
        "call $~lib/rt/stub/__new",
        "local.get $l5",
        "call $~lib/@graphprotocol/graph-ts/common/collections/ByteArray#constructor",
        "local.set $l5",
        "loop $L5",
        "local.get $l3",
        "i32.const 20",
        "i32.sub",
        "i32.load offset=16",
        "i32.const 1",
        "i32.shr_u",
        "local.get $l4",
        "i32.gt_s",
        "if $I6",
        "local.get $l5",
        "local.get $l4",
        "i32.const 2",
        "i32.div_s",
        "local.get $l3",
        "local.get $l4",
        "i32.const 2",
        "call $~lib/string/String#substr",
        "call $~lib/util/string/strtol<i32>",
        "i32.extend8_s",
        "call $~lib/typedarray/Uint8Array#__set",
        "local.get $l4",
        "i32.const 2",
        "i32.add",
        "local.set $l4",
        "br $L5",
        "end",
        "end",
        "i32.const 0",
        "local.get $l1",
        "i32.load offset=8",
        "local.get $l5",
        "i32.load offset=8",
        "i32.ne",
        "br_if $B0",
        "drop",
        "i32.const 0",
        "local.set $l3",
        "loop $L7",
        "local.get $l1",
        "i32.load offset=8",
        "local.get $l3",
        "i32.gt_s",
        "if $I8",
        "i32.const 0",
        "local.get $l1",
        "local.get $l3",
        "call $~lib/typedarray/Uint8Array#__get",
        "local.get $l5",
        "local.get $l3",
        "call $~lib/typedarray/Uint8Array#__get",
        "i32.ne",
        "br_if $B0",
        "drop",
        "local.get $l3",
        "i32.const 1",
        "i32.add",
        "local.set $l3",
        "br $L7",
        "end",
        "end",
        "i32.const 1",
        "end",
        "if $I9",
        "return",
        "end",
    ]


CONTROL_RE = re.compile(r"^(block|loop|if) (\$\S+)(?: \(result (i32)\))?$")


def parse_structured_control(lines: list[str]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for index in range(2, 149):
        line = lines[index]
        match = CONTROL_RE.fullmatch(line)
        if match is not None:
            kind, label, result_type = match.groups()
            frame = {
                "kind": kind,
                "label": label,
                "start_line": index,
                "else_line": None,
                "end_line": None,
                "result_type": result_type,
                "parent_label": stack[-1]["label"] if stack else None,
            }
            frames.append(frame)
            stack.append(frame)
        elif line == "else":
            require(stack and stack[-1]["kind"] == "if", f"orphan else at {index}")
            require(stack[-1]["else_line"] is None, f"duplicate else at {index}")
            stack[-1]["else_line"] = index
        elif line == "end":
            require(stack, f"orphan end at {index}")
            stack.pop()["end_line"] = index
    require(not stack, "guard structured-control stack does not close")
    expected = [
        ("block", "$B0", 2, None, 145, "i32", None),
        ("if", "$I1", 26, None, 37, None, "$B0"),
        ("if", "$I2", 44, 50, 52, "i32", "$B0"),
        ("if", "$I3", 53, 59, 61, "i32", "$B0"),
        ("if", "$I4", 62, 67, 69, "i32", "$B0"),
        ("loop", "$L5", 83, None, 110, None, "$B0"),
        ("if", "$I6", 92, None, 109, None, "$L5"),
        ("loop", "$L7", 121, None, 143, None, "$B0"),
        ("if", "$I8", 126, None, 142, None, "$L7"),
        ("if", "$I9", 146, None, 148, None, None),
    ]
    actual = [
        (
            frame["kind"],
            frame["label"],
            frame["start_line"],
            frame["else_line"],
            frame["end_line"],
            frame["result_type"],
            frame["parent_label"],
        )
        for frame in frames
    ]
    require(actual == expected, "modern guard structured-control graph drift")
    return frames


def ssa_inventory(lines: list[str]) -> dict[str, Any]:
    writes = [
        (index, line)
        for index, line in enumerate(lines[:149])
        if line.startswith("local.set ") or line.startswith("local.tee ")
    ]
    expected_writes = [
        (6, "local.tee $l1"),
        (19, "local.set $l1"),
        (70, "local.tee $l3"),
        (76, "local.set $l5"),
        (82, "local.set $l5"),
        (107, "local.set $l4"),
        (120, "local.set $l3"),
        (140, "local.set $l3"),
    ]
    require(writes == expected_writes, "modern guard mutable-local write inventory drift")
    expected_reads = {
        "$p0": [10],
        "$l1": [9, 12, 112, 122, 128],
        "$l3": [84, 97, 124, 129, 132, 137],
        "$l4": [90, 94, 98, 104],
        "$l5": [80, 93, 114, 131],
    }
    reads = {
        local: [index for index, line in enumerate(lines[:149]) if line == f"local.get {local}"]
        for local in expected_reads
    }
    require(reads == expected_reads, "modern guard SSA local-use inventory drift")
    stores = [
        (index, line)
        for index, line in enumerate(lines[:149])
        if re.fullmatch(r"(?:i32|i64|f32|f64)\.store(?:\s.*)?", line)
    ]
    require(stores == [(8, "i32.store"), (11, "i32.store")], "guard heap-store inventory drift")
    return {
        "implicit_zero_initialized_locals": ["$l2", "$l4", "$l6", "$l7", "$l8", "$l9"],
        "versions": [
            {"local": "$l1", "version": 1, "wat_line": 6, "value": "fresh event-wrapper allocation"},
            {"local": "$l1", "version": 2, "wat_line": 19, "value": "event.parameters[4].value.toAddress()"},
            {"local": "$l3", "version": 1, "wat_line": 70, "value": "excluded literal without 0x prefix"},
            {"local": "$l5", "version": 1, "wat_line": 76, "value": "excluded parsed byte length 20"},
            {"local": "$l5", "version": 2, "wat_line": 82, "value": "fresh excluded ByteArray length 20"},
            {"local": "$l4", "version": "loop-phi", "wat_line": 107, "value": "parser index + 2 from implicit zero"},
            {"local": "$l3", "version": 2, "wat_line": 120, "value": "byte comparison index 0"},
            {"local": "$l3", "version": "loop-phi", "wat_line": 140, "value": "byte comparison index + 1"},
        ],
        "reads": reads,
        "direct_heap_stores": [{"wat_line": index, "instruction": line} for index, line in stores],
        "modeled_call_heap_write": {
            "wat_line": 103,
            "call": "Uint8Array#__set",
            "target": "excluded ByteArray",
        },
    }


def symbolic_literal_proof() -> dict[str, Any]:
    require(EXCLUDED_POOL.startswith("0x") and len(EXCLUDED_POOL) == 42, "excluded literal shape drift")
    parsed = EXCLUDED_POOL[2:]
    index = 0
    output = bytearray()
    iterations: list[dict[str, Any]] = []
    while len(parsed) > index:
        require(index + 2 <= len(parsed), "excluded parser would read a partial byte")
        chunk = parsed[index : index + 2]
        value = int(chunk, 16)
        output.append(value)
        iterations.append(
            {
                "iteration": len(iterations),
                "string_index": index,
                "byte_index": index // 2,
                "hex_pair": chunk,
                "byte": value,
            }
        )
        index += 2
        require(len(iterations) <= 20, "excluded parser exceeded its reviewed bound")
    require(len(iterations) == 20 and index == 40, "excluded parser iteration closure drift")
    require(output.hex() == EXCLUDED_POOL[2:], "excluded parser output drift")
    return {
        "literal": EXCLUDED_POOL,
        "prefix": "0x",
        "parsed_string": parsed,
        "parsed_string_length": len(parsed),
        "byte_array_hex": output.hex(),
        "byte_array_sha256": hashlib.sha256(output).hexdigest(),
        "byte_array_length": len(output),
        "loop_initial_index": 0,
        "loop_increment": 2,
        "loop_iterations": iterations,
        "literal_to_complete_byte_array_machine_proven": True,
    }


def symbolic_equality_proof(excluded: bytes) -> dict[str, Any]:
    require(len(excluded) == 20, "excluded equality width drift")
    mismatch_paths: list[dict[str, Any]] = [
        {
            "kind": "length_mismatch",
            "constraint": "len(event.pool) != 20",
            "block_result": 0,
            "early_return": False,
        }
    ]
    for index, expected_byte in enumerate(excluded):
        mismatch_paths.append(
            {
                "kind": "first_byte_mismatch",
                "byte_index": index,
                "required_equal_prefix_length": index,
                "expected_byte": expected_byte,
                "block_result": 0,
                "early_return": False,
            }
        )
    require(len(mismatch_paths) == 21, "equality mismatch path count drift")
    return {
        "length_comparison": {
            "left": "len(event.parameters[4].value.toAddress())",
            "right": "len(excluded_pool_bytes)",
            "mismatch_branch": "$B0(0)",
        },
        "byte_comparison_loop": {
            "initial_index": 0,
            "condition": "len(event.pool) > index",
            "increment": 1,
            "iterations_on_equal_length": 20,
            "left": "event.pool[index]",
            "right": "excluded_pool_bytes[index]",
            "mismatch_branch": "$B0(0)",
        },
        "mismatch_paths": mismatch_paths,
        "equal_path": {
            "constraint": "len(event.pool) == 20 and every byte equals excluded_pool_bytes",
            "compared_byte_indexes": list(range(20)),
            "block_result": 1,
            "early_return": True,
        },
        "normal_continuation_path_count": 21,
        "early_return_path_count": 1,
        "length_and_all_byte_paths_machine_proven": True,
        "equal_only_early_return_machine_proven": True,
    }


def first_difference(actual: list[str], expected: list[str]) -> str:
    for index, (left, right) in enumerate(zip(actual, expected)):
        if left != right:
            return f"line {index}: expected {right!r}, found {left!r}"
    return f"line-count expected {len(expected)}, found {len(actual)}"


def helper_bindings(context: dict[str, Any]) -> list[dict[str, str]]:
    names = (
        "~lib/rt/stub/__new",
        "~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get",
        "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value#toAddress",
        "~lib/string/String#charAt",
        "~lib/string/String.__eq",
        "~lib/string/String#substr",
        "~lib/@graphprotocol/graph-ts/common/collections/ByteArray#constructor",
        "~lib/util/string/strtol<i32>",
        "~lib/typedarray/Uint8Array#__set",
        "~lib/typedarray/Uint8Array#__get",
    )
    output = []
    for name in names:
        function = context["functions"].get(name)
        require(function is not None, f"reviewed modern guard helper missing: {name}")
        output.append({"function": name, "body_sha256": hashlib.sha256(function.payload).hexdigest()})
    return output


def prove_modern_guard(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["cid"]
    require(cid in EXPECTED_ARTIFACTS, f"unexpected modern Factory artifact: {cid}")
    expected = EXPECTED_ARTIFACTS[cid]
    require(context["profile"]["profile_id"] == expected["profile_id"], f"profile drift: {cid}")
    require(context["profile"]["metadata_generation"] == "modern", f"not a modern profile: {cid}")
    analysis = context["analysis"]
    require(analysis["sha256"] == expected["wasm_sha256"], f"WASM digest drift: {cid}")
    require(analysis["wat_sha256"] == expected["wat_sha256"], f"WAT digest drift: {cid}")
    handler = context["handler"]
    require(
        analysis["registered_handlers"]["handlePoolCreated"]["body_sha256"]
        == expected["handler_body_sha256"],
        f"pinned handler authority drift: {cid}",
    )
    lines = [normalized(line) for line in handler.lines]
    template = guard_template(expected["static"])
    require(
        lines[: len(template)] == template,
        f"complete modern guard instruction shape drift for {cid}: "
        f"{first_difference(lines[:len(template)], template)}",
    )
    require([index for index, line in enumerate(lines[:149]) if line == "return"] == [147], f"return inventory drift: {cid}")
    guard_hash = V2.wat_slice_sha256(handler, 2, 148)
    require(guard_hash == expected["guard_slice_sha256"], f"guard slice digest drift: {cid}")

    decoded_sites = [
        index
        for index in range(149)
        if V2.decoded_wat_constant(handler.lines[index], context["memory"]) == EXCLUDED_POOL
    ]
    require(decoded_sites == [28, 45, 54, 63, 68], f"excluded literal use inventory drift: {cid}")
    expected_strings = {
        27: "input ",
        30: " has odd length",
        32: "~lib/@graphprotocol/graph-ts/common/collections.ts",
        48: "0",
        57: "x",
    }
    require(
        all(V2.decoded_wat_constant(handler.lines[index], context["memory"]) == value for index, value in expected_strings.items()),
        f"guard static string binding drift: {cid}",
    )

    controls = parse_structured_control(lines)
    ssa = ssa_inventory(lines)
    literal = symbolic_literal_proof()
    equality = symbolic_equality_proof(bytes.fromhex(literal["byte_array_hex"]))
    calls = [V2.wat_call_name(handler.lines[index]) for index in range(149)]
    require(None not in [calls[index] for index in (5, 16, 18, 29, 31, 35, 47, 49, 56, 58, 66, 79, 81, 100, 101, 103, 130, 133)], f"call inventory drift: {cid}")
    require(not any("call_indirect" in line or line.startswith("select") for line in lines[:149]), f"unsupported guard call/control: {cid}")
    effect_calls = [
        call
        for call in calls[:149]
        if call is not None
        and (
            call == WRITER.STORE_SET_CALL
            or call.endswith("dataSource.create")
            or call.endswith("schema/Pool#save")
            or call.endswith("schema/Token#save")
            or call.endswith("schema/Factory#save")
        )
    ]
    require(not effect_calls, f"persistent effect before modern guard return: {cid}")

    helpers = helper_bindings(context)
    require(
        canonical_sha256(helpers) == expected["helper_bindings_sha256"],
        f"reviewed helper body binding drift: {cid}",
    )
    return {
        "profile_id": expected["profile_id"],
        "mapping_cid": cid,
        "authority": {
            "wasm_sha256": expected["wasm_sha256"],
            "wat_sha256": expected["wat_sha256"],
            "handler_function": handler.name,
            "handler_body_sha256": expected["handler_body_sha256"],
            "handler_wat_start_line": handler.start_line,
            "guard_wat_start_line": handler.start_line + 2,
            "guard_wat_end_line": handler.start_line + 148,
            "guard_slice_sha256": guard_hash,
            "wabt_version": WRITER.WABT_VERSION,
        },
        "structured_control": {
            "nodes": controls,
            "node_count": len(controls),
            "all_edges_and_result_arities_machine_checked": True,
            "unsupported_control_count": 0,
        },
        "ssa": ssa,
        "event_pool_value_flow": {
            "wat_lines": [3, 19],
            "source": "handlePoolCreated parameter $p0",
            "flow": [
                "fresh wrapper allocation",
                "wrapper stores $p0",
                "$p0 parameters load at offset 24",
                "parameter index 4",
                "EventParam value load at offset 4",
                "ethereum.Value#toAddress",
                "$l1 version 2",
            ],
            "comparison_length_reads": [112],
            "comparison_byte_reads": [128],
            "event_pool_to_both_comparisons_machine_proven": True,
        },
        "excluded_pool_value_flow": literal,
        "equality_and_return": equality,
        "helper_body_bindings": helpers,
        "helper_body_bindings_sha256": expected["helper_bindings_sha256"],
        "persistent_effect_calls_before_return": [],
        "event_pool_to_comparison_to_early_return_machine_proven": True,
    }


def load_contexts(root: Path, wasm2wat: Path | None = None) -> list[dict[str, Any]]:
    v2_path = root.resolve() / V2_CONTRACT_PATH
    require(v2_path.is_file(), f"v2 contract missing: {v2_path}")
    require(raw_sha256(v2_path) == V2_CONTRACT_SHA256, "pinned v2 contract raw digest drift")
    v2 = load_json(v2_path)
    require(v2.get("contract_version") == "uniswap-v3-segment-field-semantics/v2", "v2 contract version drift")
    writer_path = root.resolve() / "uniswap-v3/graft-ancestry/v2/writer-compatibility.json"
    writer = load_json(writer_path)
    profiles = [
        item
        for item in writer["factory_writer_contract"]["mapping_bindings"]
        if item["metadata_generation"] == "modern"
    ]
    require(
        {item["mapping_cid"] for item in profiles} == set(EXPECTED_ARTIFACTS),
        "modern Factory mapping set drift",
    )
    contexts = [
        V2.load_factory_wat_context(root.resolve(), cid, writer, wasm2wat)
        for cid in sorted(EXPECTED_ARTIFACTS, key=lambda item: EXPECTED_ARTIFACTS[item]["profile_id"])
    ]
    return contexts


def expected_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    proofs = [prove_modern_guard(context) for context in load_contexts(root, wasm2wat)]
    require(len(proofs) == 2, "modern Factory guard proof count drift")
    require(all(item["event_pool_to_comparison_to_early_return_machine_proven"] for item in proofs), "modern guard proof did not close")
    truth = {key: True for key in sorted(TRUE_FLAGS)} | {key: False for key in sorted(FALSE_FLAGS)}
    return {
        "contract_version": CONTRACT_VERSION,
        "authority_contract": {
            "semantic_authority": "the two exact retained deployed modern Factory WASM artifacts and their checksum-pinned WABT 1.0.35 --generate-names projections",
            "proof_model": "complete bounded guard instruction template plus structured-control parsing, SSA local versions, and finite symbolic parser/equality loop execution",
            "fail_closed_rule": "any unmodeled instruction, control edge, local or heap write, call, operand, loop transition, or static value leaves the modern guard claims false",
        },
        "provenance": {
            "base_commit": PR59_HEAD,
            "v2_contract": {
                "path": V2_CONTRACT_PATH.as_posix(),
                "raw_sha256": V2_CONTRACT_SHA256,
                "contract_version": "uniswap-v3-segment-field-semantics/v2",
            },
            "wabt_version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-modern-factory-wasm>"],
        },
        "scope": {
            "factory_upstream_path_count": 18,
            "closed_before_this_supplement": 4,
            "newly_closed_modern_guard_paths": 2,
            "cumulative_closed_after_this_supplement": 6,
            "residual_after_this_supplement": 12,
            "newly_closed_path": "$.excluded_pool_guard_observation.event_pool_to_comparison_to_early_return_machine_proven",
            "modern_mapping_count": 2,
            "guard_instruction_count_per_mapping_including_function_header_and_return_if": 149,
            "guard_structured_control_node_count_per_mapping": 10,
            "guard_symbolic_exit_path_count_per_mapping": 22,
        },
        "modern_factory_guard_proofs": proofs,
        "truth_boundary": truth,
        "residuals": [
            "all six Factory effect-order, exact-argument, template-identity, and rollback paths remain unproved",
            "all six Factory totalSupply success/failure value-dataflow paths remain provenance only",
            "all six complete static Factory handler contracts and all initialized-field values remain unproved",
            "this supplement is not consumed by a runtime and proves no cross-handler or dynamic-data-source scheduling",
            "boundary continuity, oracle, logical, physical, proof-of-indexing, backfill, and production readiness remain false",
        ],
    }


def verify_contract(
    root: Path,
    contract: dict[str, Any] | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    expected = expected_contract(root, wasm2wat)
    committed = contract if contract is not None else load_json(root.resolve() / CONTRACT_PATH)
    require(committed == expected, "committed modern Factory guard contract is not the deterministic retained-WAT projection")
    truth = committed["truth_boundary"]
    require(all(type(value) is bool for value in truth.values()), "truth gates must be strict booleans")
    require({key for key, value in truth.items() if value} == TRUE_FLAGS, "true gate set drift")
    require({key for key, value in truth.items() if not value} == FALSE_FLAGS, "false gate set drift")
    return committed


def write_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    contract = expected_contract(root, wasm2wat)
    destination = root.resolve() / CONTRACT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(contract))
    return contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        contract = write_contract(args.root, args.wasm2wat) if args.write else verify_contract(args.root, wasm2wat=args.wasm2wat)
    except VerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"verified {contract['contract_version']}: two modern guards closed; "
        "Factory paths 6/18 closed and 12/18 residual"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
