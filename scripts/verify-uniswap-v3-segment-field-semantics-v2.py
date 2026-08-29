#!/usr/bin/env python3
"""Generate and verify the full-inventory Uniswap V3 field-semantics v2 ledger.

The retained deployed WASM is authoritative.  This supplement recursively
recomputes the existing WAT-backed writer and segment-matrix contracts, carries
forward v1's exact selected-handler and required-absence certifications, and
records every remaining field and control/data-flow uncertainty without
promoting reviewed source or prose to executable truth.
"""

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
CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-segment-field-semantics/v2"

MATRIX_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-writer-matrix.py"
MATRIX_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_segment_writer_matrix_for_field_semantics_v2", MATRIX_PATH
)
if MATRIX_SPEC is None or MATRIX_SPEC.loader is None:
    raise RuntimeError(f"cannot import {MATRIX_PATH}")
MATRIX = importlib.util.module_from_spec(MATRIX_SPEC)
sys.modules[MATRIX_SPEC.name] = MATRIX
MATRIX_SPEC.loader.exec_module(MATRIX)

V1_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics.py"
V1_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_segment_field_semantics_v1_for_v2", V1_PATH
)
if V1_SPEC is None or V1_SPEC.loader is None:
    raise RuntimeError(f"cannot import {V1_PATH}")
V1 = importlib.util.module_from_spec(V1_SPEC)
sys.modules[V1_SPEC.name] = V1
V1_SPEC.loader.exec_module(V1)

WRITER = MATRIX.WRITER
ANCESTRY = MATRIX.ANCESTRY

SOURCE_SPECS = {
    "ancestry": (
        "uniswap-v3/graft-ancestry/v2/contract.json",
        "uniswap-v3-graft-ancestry/v2",
        "ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e",
    ),
    "writer_compatibility": (
        "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
        "uniswap-v3-writer-compatibility/v3",
        "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4",
    ),
    "segment_writer_matrix": (
        "uniswap-v3/segment-writer-matrix/v1/contract.json",
        "uniswap-v3-segment-writer-matrix/v1",
        "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161",
    ),
    "execution_order": (
        "uniswap-v3/execution-order/v1/contract.json",
        "uniswap-v3-execution-order/v1",
        "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2",
    ),
    "segment_field_semantics_v1": (
        "uniswap-v3/segment-field-semantics/v1/contract.json",
        "uniswap-v3-segment-field-semantics/v1",
        "4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e",
    ),
}

HANDLER_ORDER = (
    "Factory.handlePoolCreated",
    "NonfungiblePositionManager.handleIncreaseLiquidity",
    "NonfungiblePositionManager.handleDecreaseLiquidity",
    "NonfungiblePositionManager.handleCollect",
    "NonfungiblePositionManager.handleTransfer",
    "Pool.handleInitialize",
    "Pool.handleSwap",
    "Pool.handleMint",
    "Pool.handleBurn",
    "Pool.handleFlash",
)
FACTORY_HANDLER = "Factory.handlePoolCreated"
POOL_NON_FLASH_HANDLERS = (
    "Pool.handleInitialize",
    "Pool.handleSwap",
    "Pool.handleMint",
    "Pool.handleBurn",
)
NPM_HANDLERS = tuple(V1.NPM_HANDLERS)
FLASH_HANDLER = V1.FLASH_HANDLER
REQUIRED_ABSENT = frozenset(V1.REQUIRED_ABSENT_ENTITIES)
POSITION_RELATION_FIELDS = {
    ("Position", "pool"),
    ("Position", "token0"),
    ("Position", "token1"),
    ("Position", "tickLower"),
    ("Position", "tickUpper"),
    ("PositionSnapshot", "pool"),
}
FACTORY_GUARD_UPSTREAM_PATH = (
    "$.excluded_pool_guard_observation."
    "event_pool_to_comparison_to_early_return_machine_proven"
)
FACTORY_EFFECT_UPSTREAM_PATH = (
    "$.pool_created_effect_order_observation.same_path_or_dataflow_machine_proven"
)
FACTORY_STATIC_UPSTREAM_PATH = "$.complete_static_handler_contract"
FACTORY_UPSTREAM_UNRESOLVED_PATHS = {
    FACTORY_GUARD_UPSTREAM_PATH,
    FACTORY_EFFECT_UPSTREAM_PATH,
    FACTORY_STATIC_UPSTREAM_PATH,
}

TRUE_FLAGS = (
    "retained_wasm_authority_recomputed",
    "source_corroboration_explicitly_non_authoritative",
    "all_twenty_entities_and_299_stored_fields_inventoried",
    "all_eight_segments_and_eighty_handlers_inventoried",
    "all_six_factory_and_eight_pool_mapping_profiles_inventoried",
    "all_four_legacy_factory_excluded_pool_guard_cfg_dataflow_proven",
    "factory_upstream_unresolved_paths_closed_count_is_4",
    "all_28_full_evidence_surface_diffs_present",
    "v1_exact_67_field_certifications_preserved",
    "required_absence_field_closure_complete",
    "remaining_232_conditional_fields_fail_closed",
    "factory_pool_upstream_proof_status_ledger_complete",
    "source_artifact_raw_bytes_bound",
)
FALSE_FLAGS = (
    "both_modern_factory_excluded_pool_guard_cfg_dataflow_proven",
    "all_six_factory_normal_return_effect_order_and_arguments_proven",
    "all_six_factory_total_supply_success_failure_profiles_proven",
    "modern_factory_total_supply_success_dataflow_proven",
    "all_manifest_handler_field_semantics_complete",
    "all_stored_fields_exact",
    "factory_handler_semantics_complete",
    "factory_all_initialized_field_values_proven",
    "pool_non_flash_handler_semantics_complete",
    "contract_call_semantics_complete_for_all_handlers",
    "full_entity_histories_complete",
    "full_handler_semantics_complete",
    "all_pairwise_complete_writer_semantic_diffs_present",
    "required_nonempty_certified",
    "runtime_population_complete",
    "writer_runtime_consumes_this_contract",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "post_fatal_execution_modeled",
    "graph_execution_trace_complete",
    "target_runtime_identity_bound",
    "segment_execution_models_decided",
    "boundary_state_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "backfill_ready",
    "production_ready",
)


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error
    require(isinstance(value, dict), f"{path} must contain one JSON object")
    return value


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def json_diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(json_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                paths.append(child)
            else:
                paths.extend(json_diff_paths(left[index], right[index], child))
        return paths
    return [] if left == right else [path]


def source_record(path: str, version: str, digest: str) -> dict[str, str]:
    return {"path": path, "contract_version": version, "raw_sha256": digest}


def load_sources(
    root: Path,
    *,
    recompute_wat: bool,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    values: dict[str, Any] = {}
    for name, (relative, version, digest) in SOURCE_SPECS.items():
        path = root / relative
        require(path.is_file(), f"required source missing: {relative}")
        require(raw_sha256(path) == digest, f"required source raw digest drift: {relative}")
        value = load_json_strict(path)
        require(value.get("contract_version") == version, f"source version drift: {relative}")
        values[name] = value

    if recompute_wat:
        try:
            matrix = MATRIX.verify(root, wasm2wat=wasm2wat)
            v1 = V1.verify_contract(root)
        except (MATRIX.VerificationError, WRITER.VerificationError, ANCESTRY.VerificationError, V1.VerificationError) as error:
            raise VerificationError(f"upstream retained-WASM verification failed: {error}") from error
        require(matrix == values["segment_writer_matrix"], "recomputed segment matrix drift")
        require(v1 == values["segment_field_semantics_v1"], "recomputed v1 field semantics drift")

    writer = values["writer_compatibility"]
    require(writer["toolchain"]["version"] == "1.0.35", "writer WABT version drift")
    require(
        writer["toolchain"]["command"] == ["wasm2wat", "--generate-names", "<mapping-wasm>"],
        "writer WAT command drift",
    )
    require(
        writer["global_store_set_closure"]["mapping_count"] == 20
        and writer["global_store_set_closure"]["complete_all_function_scan"] is True,
        "writer all-function mapping closure drift",
    )
    require(values["execution_order"]["truth_boundary"]["runtime_consumes_contract"] is False, "execution-order runtime overclaim")
    if recompute_wat:
        try:
            values["_factory_wat_proofs"] = build_factory_wat_proofs(
                root, writer, wasm2wat
            )
        except WRITER.VerificationError as error:
            raise VerificationError(
                f"Factory retained-WAT CFG/dataflow verification failed: {error}"
            ) from error
    return values


def proof_boolean_paths(value: Any, expected: bool, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            proof_key = (
                key == "complete"
                or key.startswith("complete_")
                or key.endswith("_complete")
                or "machine_proven" in key
                or "machine_checked" in key
                or key
                in {
                    "actual_execution_or_call_value_semantics_proven",
                    "named_setter_candidates_are_complete_field_outputs",
                    "reachable_from_exact_exported_handle_swap",
                }
            )
            if proof_key and type(child) is bool and child is expected:
                paths.append(child_path)
            paths.extend(proof_boolean_paths(child, expected, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(proof_boolean_paths(child, expected, f"{path}[{index}]"))
    return paths


def normalized_wat_line(line: str) -> str:
    return line.strip().replace("generated/schema/", "src/types/schema/")


def wat_call_name(line: str) -> str | None:
    match = WRITER.CALL_RE.search(line)
    if match is None:
        return None
    return match.group(1).replace("generated/schema/", "src/types/schema/")


def wat_local(line: str, operation: str = "get") -> str | None:
    match = re.fullmatch(rf"local\.{operation} (\$[^\s]+)", normalized_wat_line(line))
    return match.group(1) if match is not None else None


def decoded_wat_constant(line: str, memory: bytearray) -> str | None:
    match = WRITER.I32_CONST_RE.fullmatch(line)
    if match is None:
        return None
    return WRITER.decode_assemblyscript_string(memory, int(match.group(1)))


def wat_slice_sha256(function: Any, start: int, end_inclusive: int) -> str:
    payload = "\n".join(function.lines[start : end_inclusive + 1]) + "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def require_contiguous_wat(
    lines: list[str],
    expected: list[str],
    field: str,
) -> int:
    matches = [
        index
        for index in range(len(lines) - len(expected) + 1)
        if lines[index : index + len(expected)] == expected
    ]
    require(len(matches) == 1, f"{field} contiguous WAT shape count drift: {len(matches)}")
    return matches[0]


def matching_wat_end(lines: tuple[str, ...], start: int, field: str) -> int:
    require(normalized_wat_line(lines[start]).startswith("if "), f"{field} does not begin at an if")
    depth = 0
    for index in range(start, len(lines)):
        instruction = normalized_wat_line(lines[index])
        if re.match(r"^(?:block|loop|if)\b", instruction):
            depth += 1
        if instruction in {"end", "end)"} or instruction.startswith("end "):
            depth -= 1
            if depth == 0:
                return index
    raise VerificationError(f"{field} has no matching end")


def wat_control_depths(lines: tuple[str, ...]) -> list[int]:
    depths: list[int] = []
    depth = 0
    for line in lines:
        instruction = normalized_wat_line(line)
        if instruction in {"end", "end)"} or instruction.startswith("end "):
            depth -= 1
            require(depth >= 0, "WAT structured-control depth underflow")
        depths.append(depth)
        if re.match(r"^(?:block|loop|if)\b", instruction):
            depth += 1
    require(depth == 0, "WAT structured-control depth does not close")
    return depths


def require_local_assignments_trap_before_normal_continuation(
    cid: str,
    lines: tuple[str, ...],
    local: str,
    before: int,
    field: str,
) -> list[dict[str, Any]]:
    """Prove every earlier reassignment of a parameter is confined to a trap path."""
    normalized = [normalized_wat_line(line) for line in lines]
    depths = wat_control_depths(lines)
    proofs: list[dict[str, Any]] = []
    for index in range(1, before):
        if normalized[index] not in {f"local.set {local}", f"local.tee {local}"}:
            continue
        depth = depths[index]
        require(depth > 0, f"{cid} {field} has a top-level {local} reassignment")
        boundary = next(
            (candidate for candidate in range(index + 1, before) if depths[candidate] < depth),
            None,
        )
        require(boundary is not None, f"{cid} {field} reassignment region does not close")
        continuation = normalized[index + 1 : boundary + 1]
        unreachable = next(
            (offset for offset, instruction in enumerate(continuation) if instruction == "unreachable"),
            None,
        )
        require(unreachable is not None, f"{cid} {field} reassignment can continue normally")
        prefix = continuation[:unreachable]
        require(
            not any(
                instruction == "return"
                or instruction == "else"
                or re.match(r"^br(?:_if|_table)?\b", instruction)
                for instruction in prefix
            ),
            f"{cid} {field} reassignment can bypass its trap",
        )
        proofs.append(
            {
                "assignment_wat_line": index,
                "unreachable_wat_line": index + 1 + unreachable,
                "normal_continuation": False,
            }
        )
    return proofs


def prove_legacy_from_hex_string(
    cid: str,
    function: Any,
    memory: bytearray,
) -> dict[str, Any]:
    lines = [normalized_wat_line(line) for line in function.lines]
    require(
        len(lines) == 103 and "(param " not in lines[0],
        f"{cid} legacy excluded-pool helper signature/body drift",
    )
    input_local = wat_local(function.lines[3], "set")
    index_local = wat_local(function.lines[24], "tee")
    bytes_local = wat_local(function.lines[72], "set")
    require(
        input_local is not None
        and index_local is not None
        and bytes_local is not None
        and decoded_wat_constant(function.lines[2], memory) == WRITER.EXCLUDED_POOL
        and lines[3] == f"local.set {input_local}"
        and all(
            decoded_wat_constant(function.lines[index], memory) == WRITER.EXCLUDED_POOL
            for index in (4, 10, 20, 26, 35, 61)
        )
        and decoded_wat_constant(function.lines[9], memory) == "input ",
        f"{cid} legacy excluded-pool helper literal binding drift",
    )
    require(
        lines[61:73]
        == [
            lines[61],
            "i32.const 2",
            f"local.get {index_local}",
            lines[64],
            f"local.set {input_local}",
            "end",
            f"local.get {input_local}",
            "i32.load",
            "i32.const 2",
            "i32.div_s",
            lines[71],
            f"local.set {bytes_local}",
        ]
        and (wat_call_name(function.lines[64]) or "").endswith("String#substr")
        and (wat_call_name(function.lines[71]) or "").endswith("Bytes#constructor"),
        f"{cid} legacy excluded-pool substring/allocation dataflow drift",
    )
    loop_label = lines[75].split()[1] if lines[75].startswith("loop $") else None
    require(
        loop_label is not None
        and lines[73:103]
        == [
            "i32.const 0",
            f"local.set {index_local}",
            f"loop {loop_label}",
            f"local.get {index_local}",
            f"local.get {input_local}",
            "i32.load",
            "i32.lt_s",
            lines[80],
            f"local.get {bytes_local}",
            f"local.get {index_local}",
            "i32.const 2",
            "i32.div_s",
            f"local.get {input_local}",
            f"local.get {index_local}",
            "i32.const 2",
            lines[88],
            lines[89],
            "i32.const 24",
            "i32.shl",
            "i32.const 24",
            "i32.shr_s",
            lines[94],
            f"local.get {index_local}",
            "i32.const 2",
            "i32.add",
            f"local.set {index_local}",
            f"br {loop_label}",
            "end",
            "end",
            lines[102],
        ]
        and lines[80].startswith("if $")
        and (wat_call_name(function.lines[88]) or "").endswith("String#substr")
        and (wat_call_name(function.lines[89]) or "").endswith("parse<i32>")
        and (wat_call_name(function.lines[94]) or "").endswith("TypedArray<u8>#__set")
        and lines[102].rstrip(")") == f"local.get {bytes_local}",
        f"{cid} legacy excluded-pool byte-fill loop dataflow drift",
    )
    literal_sites = [
        index
        for index, line in enumerate(function.lines)
        if decoded_wat_constant(line, memory) == WRITER.EXCLUDED_POOL
    ]
    require(
        literal_sites == [2, 4, 10, 20, 26, 35, 61],
        f"{cid} legacy excluded-pool helper use inventory drift",
    )
    return {
        "function": function.name,
        "body_sha256": hashlib.sha256(function.payload).hexdigest(),
        "takes_parameters": False,
        "excluded_literal_wat_lines": literal_sites,
        "excluded_literal_to_returned_byte_array_machine_proven": True,
    }


def prove_legacy_byte_array_equals(function: Any) -> dict[str, Any]:
    lines = [normalized_wat_line(line) for line in function.lines]
    header = re.fullmatch(
        r"\(func \$[^ ]+ \(type \$[^ ]+\) \(param (\$[^ ]+) i32\) "
        r"\(param (\$[^ ]+) i32\) \(result i32\)",
        lines[0],
    )
    require(header is not None, "legacy ByteArray.equals signature drift")
    left, right = header.groups()
    require(left != right, "legacy ByteArray.equals parameters alias")
    index_local_match = re.search(r"\(local (\$[^ ]+) i32\)", lines[1])
    require(index_local_match is not None, "legacy ByteArray.equals index local drift")
    index_local = index_local_match.group(1)
    require(
        len(lines) == 43
        and lines[2:11]
        == [
            f"local.get {left}",
            "i32.load offset=8",
            f"local.get {right}",
            "i32.load offset=8",
            "i32.ne",
            lines[7],
            "i32.const 0",
            "return",
            "end",
        ]
        and lines[7].startswith("if $"),
        "legacy ByteArray.equals length comparison dataflow drift",
    )
    loop_label = lines[11].split()[1] if lines[11].startswith("loop $") else None
    block_label = lines[12].split()[1] if lines[12].startswith("block $") else None
    require(
        loop_label is not None
        and block_label is not None
        and lines[13:43]
        == [
            f"local.get {index_local}",
            f"local.get {left}",
            "i32.load offset=8",
            "i32.ge_s",
            f"br_if {block_label}",
            f"local.get {left}",
            f"local.get {index_local}",
            lines[20],
            "i32.const 255",
            "i32.and",
            f"local.get {right}",
            f"local.get {index_local}",
            lines[25],
            "i32.const 255",
            "i32.and",
            "i32.ne",
            lines[29],
            "i32.const 0",
            "return",
            "else",
            f"local.get {index_local}",
            "i32.const 1",
            "i32.add",
            f"local.set {index_local}",
            f"br {loop_label}",
            "end",
            "unreachable",
            "end",
            "end",
            lines[42],
        ]
        and (wat_call_name(function.lines[20]) or "").endswith("TypedArray<u8>#__get")
        and lines[25] == lines[20]
        and lines[29].startswith("if $")
        and lines[42].rstrip(")") == "i32.const 1"
        and sum(line == "return" for line in lines) == 2,
        "legacy ByteArray.equals byte comparison/control-flow drift",
    )
    return {
        "function": function.name,
        "body_sha256": hashlib.sha256(function.payload).hexdigest(),
        "left_parameter": left,
        "right_parameter": right,
        "distinct_parameter_dataflow_machine_proven": True,
        "length_mismatch_returns_false": True,
        "byte_mismatch_returns_false": True,
        "all_bytes_equal_returns_true": True,
    }


def prove_factory_excluded_pool_guard(
    cid: str,
    generation: str,
    handler: Any,
    functions: dict[str, Any],
    memory: bytearray,
) -> dict[str, Any]:
    lines = [normalized_wat_line(line) for line in handler.lines]
    first_return = next((index for index, line in enumerate(lines) if line == "return"), None)
    require(first_return is not None, f"{cid} Factory guard has no early return")

    def require_no_effect_before(end_inclusive: int) -> None:
        effects = []
        for index in range(end_inclusive + 1):
            call = wat_call_name(handler.lines[index]) or ""
            if (
                call == WRITER.STORE_SET_CALL
                or call.endswith("dataSource.create")
                or call.endswith("schema/Pool#save")
                or call.endswith("schema/Token#save")
                or call.endswith("schema/Factory#save")
            ):
                effects.append((index, call))
        require(not effects, f"{cid} Factory excluded-pool guard follows an effect")

    if generation == "legacy":
        expected = [
            "local.get $p0",
            "call $src/types/Factory/Factory/PoolCreated__Params#constructor",
            "call $src/types/Factory/Factory/PoolCreated__Params#get:pool",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromHexString",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray#equals",
        ]
        require(lines[2:7] == expected, f"{cid} legacy Factory guard stack dataflow drift")
        require(
            lines[7].startswith("if $")
            and lines[8] == "return"
            and lines[9] == "end",
            f"{cid} legacy Factory guard branch direction drift",
        )
        require(first_return == 8, f"{cid} legacy excluded-pool return is not first")
        constant_helper = functions.get(
            "~lib/@graphprotocol/graph-ts/index/ByteArray.fromHexString"
        )
        equality_helper = functions.get(
            "~lib/@graphprotocol/graph-ts/index/ByteArray#equals"
        )
        require(constant_helper is not None, f"{cid} legacy excluded-pool helper missing")
        require(equality_helper is not None, f"{cid} legacy equality helper missing")
        constant = prove_legacy_from_hex_string(cid, constant_helper, memory)
        equality = prove_legacy_byte_array_equals(equality_helper)
        proof_end = 9
        require_no_effect_before(proof_end)
        return {
            "proof_model": "legacy-direct-stack-call",
            "event_pool_source": "PoolCreated event parameter get:pool",
            "excluded_pool": WRITER.EXCLUDED_POOL,
            "constant_helper": constant,
            "equality_helper": equality,
            "branch_on_equal_returns_before_all_effects": True,
            "event_pool_to_comparison_to_early_return_machine_proven": True,
            "guard_wat_start_line": handler.start_line + 2,
            "guard_wat_end_line": handler.start_line + proof_end,
            "guard_slice_sha256": wat_slice_sha256(handler, 2, proof_end),
        }

    require(generation == "modern", f"{cid} unknown Factory generation: {generation}")
    block_match = re.fullmatch(r"block (\$[^\s]+) \(result i32\)", lines[2])
    require(block_match is not None, f"{cid} modern equality result block drift")
    result_block = block_match.group(1)
    require(first_return >= 4, f"{cid} modern guard return placement drift")
    require(
        lines[first_return - 3] == "i32.const 1"
        and lines[first_return - 2] == "end"
        and lines[first_return - 1].startswith("if $")
        and lines[first_return + 1] == "end",
        f"{cid} modern equality true branch direction drift",
    )

    event_getters = []
    for index in range(3, first_return):
        call = wat_call_name(handler.lines[index])
        if call is None or not call.endswith("ethereum.EventParam>#__get"):
            continue
        if index > 0 and lines[index - 1] == "i32.const 4":
            event_getters.append(index)
    require(len(event_getters) == 1, f"{cid} modern guard event.pool getter drift")
    getter = event_getters[0]
    event_wrapper_local = wat_local(handler.lines[getter - 10], "tee")
    require(
        getter == 16
        and event_wrapper_local is not None
        and lines[3:getter]
        == [
            "i32.const 4",
            "i32.const 24",
            "call $~lib/rt/stub/__new",
            f"local.tee {event_wrapper_local}",
            "i32.const 0",
            "i32.store",
            f"local.get {event_wrapper_local}",
            "local.get $p0",
            "i32.store",
            f"local.get {event_wrapper_local}",
            "i32.load",
            "i32.load offset=24",
            "i32.const 4",
        ]
        and lines[getter + 1] == "i32.load offset=4"
        and wat_call_name(handler.lines[getter + 2]) is not None
        and wat_call_name(handler.lines[getter + 2]).endswith("ethereum.Value#toAddress"),
        f"{cid} modern handler-event.pool address conversion drift",
    )
    pool_local = wat_local(handler.lines[getter + 3], "set")
    require(pool_local is not None, f"{cid} modern event.pool local binding missing")

    excluded_sites = [
        index
        for index in range(3, first_return)
        if decoded_wat_constant(handler.lines[index], memory) == WRITER.EXCLUDED_POOL
    ]
    require(len(excluded_sites) == 5, f"{cid} modern excluded-pool constant use drift")
    constructors = [
        index
        for index in range(3, first_return)
        if (wat_call_name(handler.lines[index]) or "").endswith("ByteArray#constructor")
    ]
    require(len(constructors) == 1, f"{cid} modern excluded ByteArray constructor drift")
    constructor = constructors[0]
    excluded_local = wat_local(handler.lines[constructor + 1], "set")
    require(excluded_local is not None, f"{cid} modern excluded bytes local missing")

    parsed_tee = constructor - 11
    parsed_local = wat_local(handler.lines[parsed_tee], "tee")
    length_local = wat_local(handler.lines[constructor - 5], "set")
    require(
        parsed_local is not None
        and length_local is not None
        and lines[parsed_tee + 1 : constructor + 2]
        == [
            "i32.const 20",
            "i32.sub",
            "i32.load offset=16",
            "i32.const 2",
            "i32.shr_u",
            f"local.set {length_local}",
            "i32.const 12",
            "i32.const 9",
            "call $~lib/rt/stub/__new",
            f"local.get {length_local}",
            "call $~lib/@graphprotocol/graph-ts/common/collections/ByteArray#constructor",
            f"local.set {excluded_local}",
        ],
        f"{cid} modern excluded string-to-byte-array allocation drift",
    )

    parse_end = parsed_tee - 1
    parse_if_candidates = [
        index
        for index in range(3, parse_end)
        if lines[index].startswith("if $")
        and "(result i32)" in lines[index]
        and matching_wat_end(handler.lines, index, f"{cid} modern excluded parser")
        == parse_end
    ]
    require(len(parse_if_candidates) == 1, f"{cid} modern excluded parser branch drift")
    parse_if = parse_if_candidates[0]
    require(
        decoded_wat_constant(handler.lines[parse_if + 1], memory) == WRITER.EXCLUDED_POOL
        and lines[parse_if + 2] == "i32.const 2"
        and lines[parse_if + 3] == "i32.const 2147483647"
        and (wat_call_name(handler.lines[parse_if + 4]) or "").endswith("String#substr")
        and lines[parse_if + 5] == "else"
        and decoded_wat_constant(handler.lines[parse_if + 6], memory) == WRITER.EXCLUDED_POOL
        and lines[parse_if + 7] == "end"
        and parse_if + 7 == parse_end,
        f"{cid} modern excluded parser result is not bound to the excluded literal",
    )

    prefix_checks: list[dict[str, Any]] = []
    expected_prefixes = ((0, "0"), (1, "x"))
    previous_end = parse_if - 1
    for expected_index, expected_character in reversed(expected_prefixes):
        candidates = [
            index
            for index in range(3, previous_end)
            if lines[index].startswith("if $")
            and "(result i32)" in lines[index]
            and matching_wat_end(handler.lines, index, f"{cid} modern excluded prefix")
            == previous_end
        ]
        require(len(candidates) == 1, f"{cid} modern excluded prefix branch drift")
        prefix_if = candidates[0]
        require(
            decoded_wat_constant(handler.lines[prefix_if + 1], memory)
            == WRITER.EXCLUDED_POOL
            and lines[prefix_if + 2] == f"i32.const {expected_index}"
            and (wat_call_name(handler.lines[prefix_if + 3]) or "").endswith("String#charAt")
            and decoded_wat_constant(handler.lines[prefix_if + 4], memory)
            == expected_character
            and (wat_call_name(handler.lines[prefix_if + 5]) or "").endswith("String.__eq")
            and lines[prefix_if + 6 : prefix_if + 9] == ["else", "i32.const 0", "end"]
            and prefix_if + 8 == previous_end,
            f"{cid} modern excluded prefix check is not bound to the excluded literal",
        )
        prefix_checks.append(
            {
                "character_index": expected_index,
                "character": expected_character,
                "wat_start_line": handler.start_line + prefix_if,
            }
        )
        previous_end = prefix_if - 1

    loop_start = constructor + 2
    require(lines[loop_start].startswith("loop $"), f"{cid} modern excluded parser loop missing")
    loop_label = lines[loop_start].split()[1]
    index_local = wat_local(handler.lines[loop_start + 7])
    require(index_local is not None, f"{cid} modern excluded parser index local missing")
    loop_shape = lines[loop_start : loop_start + 28]
    require(
        loop_shape[1:8]
        == [
            f"local.get {parsed_local}",
            "i32.const 20",
            "i32.sub",
            "i32.load offset=16",
            "i32.const 1",
            "i32.shr_u",
            f"local.get {index_local}",
        ]
        and loop_shape[8] == "i32.gt_s"
        and loop_shape[9].startswith("if $")
        and loop_shape[10:14]
        == [
            f"local.get {excluded_local}",
            f"local.get {index_local}",
            "i32.const 2",
            "i32.div_s",
        ]
        and loop_shape[14:17]
        == [f"local.get {parsed_local}", f"local.get {index_local}", "i32.const 2"]
        and (wat_call_name(handler.lines[loop_start + 17]) or "").endswith("String#substr")
        and (wat_call_name(handler.lines[loop_start + 18]) or "").endswith("strtol<i32>")
        and loop_shape[19] == "i32.extend8_s"
        and (wat_call_name(handler.lines[loop_start + 20]) or "").endswith("Uint8Array#__set")
        and loop_shape[21:26]
        == [
            f"local.get {index_local}",
            "i32.const 2",
            "i32.add",
            f"local.set {index_local}",
            f"br {loop_label}",
        ]
        and loop_shape[26:] == ["end", "end"],
        f"{cid} modern excluded byte-array fill dataflow drift",
    )
    require(
        set(excluded_sites)
        == {
            parse_if + 1,
            parse_if + 6,
            *(item["wat_start_line"] - handler.start_line + 1 for item in prefix_checks),
            excluded_sites[0],
        }
        and decoded_wat_constant(handler.lines[excluded_sites[0]], memory)
        == WRITER.EXCLUDED_POOL,
        f"{cid} modern excluded literal semantic/diagnostic use partition drift",
    )

    length_shape = [
        "i32.const 0",
        f"local.get {pool_local}",
        "i32.load offset=8",
        f"local.get {excluded_local}",
        "i32.load offset=8",
        "i32.ne",
        f"br_if {result_block}",
        "drop",
    ]
    require_contiguous_wat(lines[: first_return + 1], length_shape, f"{cid} length equality")
    branches = [
        index for index, line in enumerate(lines[:first_return]) if line == f"br_if {result_block}"
    ]
    require(len(branches) == 2, f"{cid} modern equality failure branch count drift")
    byte_branch = branches[1]
    byte_shape = lines[byte_branch - 8 : byte_branch + 2]
    require(
        byte_shape[0] == "i32.const 0"
        and byte_shape[1] == f"local.get {pool_local}"
        and byte_shape[3].startswith("call $")
        and byte_shape[3].endswith("Uint8Array#__get")
        and byte_shape[4] == f"local.get {excluded_local}"
        and byte_shape[6] == byte_shape[3]
        and byte_shape[7] == "i32.ne"
        and byte_shape[8] == f"br_if {result_block}"
        and byte_shape[9] == "drop",
        f"{cid} modern byte equality dataflow drift",
    )
    require(byte_shape[2] == byte_shape[5], f"{cid} modern byte index local drift")
    require_no_effect_before(first_return + 1)
    return {
        "proof_model": "modern-inlined-length-and-byte-loop",
        "event_pool_source": "PoolCreated event parameter index 4",
        "event_wrapper_local": event_wrapper_local,
        "event_pool_local": pool_local,
        "excluded_pool": WRITER.EXCLUDED_POOL,
        "excluded_pool_byte_array_local": excluded_local,
        "excluded_pool_parsed_string_local": parsed_local,
        "excluded_pool_prefix_checks": sorted(prefix_checks, key=lambda item: item["character_index"]),
        "excluded_pool_literal_to_byte_array_machine_proven": True,
        "length_mismatch_returns_false": True,
        "byte_mismatch_returns_false": True,
        "all_bytes_equal_returns_true": True,
        "branch_on_equal_returns_before_all_effects": True,
        "event_pool_to_comparison_to_early_return_machine_proven": True,
        "guard_wat_start_line": handler.start_line + 2,
        "guard_wat_end_line": handler.start_line + first_return + 1,
        "guard_slice_sha256": wat_slice_sha256(handler, 2, first_return + 1),
    }


def direct_store_arguments(
    cid: str,
    handler: Any,
    memory: bytearray,
    call_index: int,
) -> dict[str, str]:
    require(call_index >= 4, f"{cid} direct store has no argument window")
    window = handler.lines[call_index - 4 : call_index]
    target = decoded_wat_constant(window[0], memory)
    id_local = wat_local(window[1])
    entity_local = wat_local(window[3])
    require(
        target in {"Bundle", "Factory", "Pool", "Token"}
        and id_local is not None
        and (wat_call_name(window[2]) or "").endswith("Value#toString")
        and entity_local is not None,
        f"{cid} direct store argument shape drift at WAT line {handler.start_line + call_index}",
    )
    return {"target": target, "id_value_local": id_local, "entity_local": entity_local}


def prove_mandatory_modern_store(
    cid: str,
    handler: Any,
    memory: bytearray,
    call_index: int,
    arguments: dict[str, str],
) -> dict[str, Any]:
    lines = [normalized_wat_line(line) for line in handler.lines]
    control_depths = wat_control_depths(handler.lines)
    id_local = arguments["id_value_local"]
    entity_local = arguments["entity_local"]
    candidates = [
        index
        for index in range(max(0, call_index - 80), call_index)
        if lines[index] == f"local.tee {id_local}"
        and index + 2 < call_index
        and lines[index + 1] == "i32.eqz"
        and lines[index + 2].startswith("if $")
    ]
    require(candidates, f"{cid} {arguments['target']} required-id guard missing")
    tee = candidates[-1]
    require(
        tee >= 3
        and lines[tee - 1].startswith("call $")
        and lines[tee - 1].endswith("TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#get")
        and decoded_wat_constant(handler.lines[tee - 2], memory) == "id"
        and lines[tee - 3] == f"local.get {entity_local}",
        f"{cid} {arguments['target']} required-id lookup dataflow drift",
    )
    missing_end = matching_wat_end(
        handler.lines,
        tee + 2,
        f"{cid} {arguments['target']} missing-id guard",
    )
    missing_branch = lines[tee + 3 : missing_end]
    require(
        any((wat_call_name(line) or "").endswith("builtins/abort") for line in handler.lines[tee + 3 : missing_end])
        and "unreachable" in missing_branch
        and "else" not in missing_branch,
        f"{cid} {arguments['target']} missing-id guard does not trap",
    )
    require(
        lines[missing_end + 1] == f"local.get {id_local}"
        and lines[missing_end + 2].startswith("if $"),
        f"{cid} {arguments['target']} present-id branch drift",
    )
    present_end = matching_wat_end(
        handler.lines,
        missing_end + 2,
        f"{cid} {arguments['target']} present-id branch",
    )
    require(
        missing_end + 2 < call_index < present_end,
        f"{cid} {arguments['target']} store is not in required present-id branch",
    )
    require(
        control_depths[call_index] == control_depths[missing_end + 2] + 1,
        f"{cid} {arguments['target']} store is conditionally nested inside its present-id branch",
    )
    require(
        "else" not in lines[missing_end + 3 : call_index],
        f"{cid} {arguments['target']} store moved to the absent-id alternative",
    )
    bypasses = [
        instruction
        for instruction in lines[missing_end + 3 : call_index]
        if instruction == "return" or re.match(r"^br(?:_if|_table)?\b", instruction)
    ]
    require(
        not bypasses,
        f"{cid} {arguments['target']} present-id path can bypass its store",
    )
    require(
        "else" not in lines[call_index + 1 : present_end],
        f"{cid} {arguments['target']} store has a post-store alternative branch",
    )
    return {
        "required_id_field": "id",
        "missing_id_traps": True,
        "present_id_executes_store": True,
        "store_is_directly_nested_in_present_id_branch": True,
        "store_preceded_by_no_alternative_branch": True,
        "no_pre_store_branch_or_return_bypass": True,
        "store_entity_local": entity_local,
        "store_id_value_local": id_local,
        "guard_slice_sha256": wat_slice_sha256(handler, tee - 3, present_end),
    }


def legacy_factory_identity_locals(
    cid: str,
    handler: Any,
    memory: bytearray,
) -> dict[str, Any]:
    calls = WRITER.function_call_sites(handler)
    lines = [normalized_wat_line(line) for line in handler.lines]
    bindings: dict[str, dict[str, Any]] = {}

    def event_assignment(parameter: str, terminal_suffix: str, assignment: str) -> str:
        matches: list[str] = []
        for _position, (line_index, call) in enumerate(calls):
            if not call.endswith(f"PoolCreated__Params#get:{parameter}"):
                continue
            if line_index < 2 or line_index + 3 >= len(lines):
                continue
            params_constructor = wat_call_name(handler.lines[line_index - 1]) or ""
            conversion = wat_call_name(handler.lines[line_index + 1]) or ""
            terminal = wat_call_name(handler.lines[line_index + 2]) or ""
            if not (
                lines[line_index - 2] == "local.get $p0"
                and params_constructor.endswith("PoolCreated__Params#constructor")
                and conversion.endswith("typeConversion.bytesToHex")
                and terminal.endswith(terminal_suffix)
            ):
                continue
            local = wat_local(handler.lines[line_index + 3], assignment)
            if local is not None:
                matches.append(local)
                bindings[parameter] = {
                    "event_parameter": parameter,
                    "entity_local": local,
                    "binding_slice_sha256": wat_slice_sha256(
                        handler, line_index - 2, line_index + 3
                    ),
                }
        require(len(matches) == 1, f"{cid} legacy {parameter} identity binding drift")
        return matches[0]

    pool_local = event_assignment("pool", "schema/Factory#constructor", "set")
    token0_local = event_assignment("token0", "schema/Token.load", "set")
    token1_local = event_assignment("token1", "schema/Token.load", "set")
    factory_matches: list[tuple[str, str]] = []
    for line_index, call in calls:
        if call != "~lib/@graphprotocol/graph-ts/index/store.get" or line_index < 2:
            continue
        if decoded_wat_constant(handler.lines[line_index - 2], memory) != "Factory":
            continue
        address = decoded_wat_constant(handler.lines[line_index - 1], memory)
        local = wat_local(handler.lines[line_index + 1], "tee")
        if address is not None and local is not None:
            factory_matches.append((local, address))
    require(len(factory_matches) == 1, f"{cid} legacy Factory identity binding drift")
    return {
        "pool": pool_local,
        "token0": token0_local,
        "token1": token1_local,
        "factory": factory_matches[0][0],
        "factory_id": factory_matches[0][1],
        "pool_event_parameter": "pool",
        "token0_event_parameter": "token0",
        "token1_event_parameter": "token1",
        "event_identity_bindings": bindings,
    }


def modern_factory_identity_locals(
    cid: str,
    handler: Any,
    memory: bytearray,
    pool_entity_local: str,
) -> dict[str, Any]:
    calls = WRITER.function_call_sites(handler)
    lines = [normalized_wat_line(line) for line in handler.lines]
    factory_matches: list[tuple[str, str]] = []
    token_matches: dict[int, str] = {}
    token_bindings: dict[int, dict[str, Any]] = {}
    for line_index, call in calls:
        if call != "~lib/@graphprotocol/graph-ts/index/store.get":
            continue
        if line_index >= 2 and decoded_wat_constant(handler.lines[line_index - 2], memory) == "Factory":
            address = decoded_wat_constant(handler.lines[line_index - 1], memory)
            local = wat_local(handler.lines[line_index + 1], "tee")
            if address is not None and local is not None:
                factory_matches.append((local, address))
            continue
        if line_index < 18 or decoded_wat_constant(handler.lines[line_index - 9], memory) != "Token":
            continue
        getter = line_index - 4
        index_match = re.fullmatch(r"i32\.const ([01])", lines[getter - 1])
        local = wat_local(handler.lines[line_index + 1], "set")
        wrapper_local = wat_local(handler.lines[line_index - 8])
        require(
            index_match is not None
            and local is not None
            and wrapper_local is not None
            and lines[line_index - 8 : line_index + 2]
            == [
                f"local.get {wrapper_local}",
                "i32.load",
                "i32.load offset=24",
                f"i32.const {index_match.group(1)}",
                lines[getter],
                "i32.load offset=4",
                lines[line_index - 2],
                lines[line_index - 1],
                lines[line_index],
                f"local.set {local}",
            ]
            and (wat_call_name(handler.lines[getter]) or "").endswith(
                "ethereum.EventParam>#__get"
            )
            and (wat_call_name(handler.lines[line_index - 2]) or "").endswith(
                "ethereum.Value#toAddress"
            )
            and (wat_call_name(handler.lines[line_index - 1]) or "").endswith(
                "typeConversion.bytesToHex"
            ),
            f"{cid} modern Token store.get event-address dataflow drift",
        )
        wrapper_start = line_index - 18
        require(
            lines[wrapper_start : line_index - 9]
            == [
                "i32.const 4",
                "i32.const 24",
                "call $~lib/rt/stub/__new",
                f"local.tee {wrapper_local}",
                "i32.const 0",
                "i32.store",
                f"local.get {wrapper_local}",
                "local.get $p0",
                "i32.store",
            ],
            f"{cid} modern Token event wrapper dataflow drift",
        )
        parameter_traps = require_local_assignments_trap_before_normal_continuation(
            cid,
            handler.lines,
            "$p0",
            wrapper_start,
            f"Token[{index_match.group(1)}] event parameter",
        )
        token_index = int(index_match.group(1))
        require(token_index not in token_matches, f"{cid} duplicate modern Token binding")
        token_matches[token_index] = local
        token_bindings[token_index] = {
            "event_parameter_index": token_index,
            "event_wrapper_local": wrapper_local,
            "entity_local": local,
            "normal_path_parameter_reassignments": parameter_traps,
            "binding_slice_sha256": wat_slice_sha256(
                handler, wrapper_start, line_index + 1
            ),
        }
    require(len(factory_matches) == 1, f"{cid} modern Factory identity binding drift")
    require(set(token_matches) == {0, 1}, f"{cid} modern Token identity bindings drift")

    pool_constructors = [
        line_index
        for line_index, call in calls
        if call.endswith("collections/Entity#constructor")
        and line_index + 1 < len(handler.lines)
        and wat_local(handler.lines[line_index + 1], "set") == pool_entity_local
    ]
    require(len(pool_constructors) == 1, f"{cid} modern Pool entity constructor drift")
    constructor = pool_constructors[0]
    getter = constructor - 8
    wrapper_start = constructor - 21
    wrapper_local = wat_local(handler.lines[wrapper_start + 3], "tee")
    pool_id_local = wat_local(handler.lines[constructor - 4], "set")
    require(
        wrapper_local is not None
        and pool_id_local is not None
        and lines[wrapper_start : constructor + 2]
        == [
            "i32.const 4",
            "i32.const 24",
            "call $~lib/rt/stub/__new",
            f"local.tee {wrapper_local}",
            "i32.const 0",
            "i32.store",
            f"local.get {wrapper_local}",
            "local.get $p0",
            "i32.store",
            f"local.get {wrapper_local}",
            "i32.load",
            "i32.load offset=24",
            "i32.const 4",
            lines[getter],
            "i32.load offset=4",
            lines[constructor - 6],
            lines[constructor - 5],
            f"local.set {pool_id_local}",
            "i32.const 4",
            "i32.const 36",
            "call $~lib/rt/stub/__new",
            lines[constructor],
            f"local.set {pool_entity_local}",
        ]
        and (wat_call_name(handler.lines[getter]) or "").endswith(
            "ethereum.EventParam>#__get"
        )
        and (wat_call_name(handler.lines[constructor - 6]) or "").endswith(
            "ethereum.Value#toAddress"
        )
        and (wat_call_name(handler.lines[constructor - 5]) or "").endswith(
            "typeConversion.bytesToHex"
        )
        and (wat_call_name(handler.lines[constructor]) or "").endswith(
            "collections/Entity#constructor"
        ),
        f"{cid} modern Pool event.pool-to-entity binding drift",
    )
    id_i64_local = wat_local(handler.lines[constructor + 4], "set")
    id_value_local = wat_local(handler.lines[constructor + 8], "tee")
    require(
        id_i64_local is not None
        and id_value_local is not None
        and lines[constructor + 2 : constructor + 18]
        == [
            f"local.get {pool_id_local}",
            "i64.extend_i32_u",
            f"local.set {id_i64_local}",
            "i32.const 16",
            "i32.const 27",
            "call $~lib/rt/stub/__new",
            f"local.tee {id_value_local}",
            "i32.const 0",
            "i32.store",
            f"local.get {id_value_local}",
            f"local.get {id_i64_local}",
            "i64.store offset=8",
            f"local.get {pool_entity_local}",
            lines[constructor + 15],
            f"local.get {id_value_local}",
            lines[constructor + 17],
        ]
        and decoded_wat_constant(handler.lines[constructor + 15], memory) == "id"
        and (wat_call_name(handler.lines[constructor + 17]) or "").endswith(
            "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set"
        ),
        f"{cid} modern Pool.id field dataflow drift",
    )
    pool_parameter_traps = require_local_assignments_trap_before_normal_continuation(
        cid, handler.lines, "$p0", wrapper_start, "Pool event parameter"
    )
    return {
        "pool": pool_entity_local,
        "token0": token_matches[0],
        "token1": token_matches[1],
        "factory": factory_matches[0][0],
        "factory_id": factory_matches[0][1],
        "pool_event_parameter_index": 4,
        "token0_event_parameter_index": 0,
        "token1_event_parameter_index": 1,
        "pool_id_event_value_local": pool_id_local,
        "pool_id_wrapped_value_local": id_value_local,
        "pool_event_wrapper_local": wrapper_local,
        "pool_normal_path_parameter_reassignments": pool_parameter_traps,
        "pool_id_binding_slice_sha256": wat_slice_sha256(
            handler, wrapper_start, constructor + 17
        ),
        "token_event_store_get_bindings": {
            "token0": token_bindings[0],
            "token1": token_bindings[1],
        },
    }


def prove_missing_entity_assignment(
    cid: str,
    handler: Any,
    local: str,
    constructor_suffixes: tuple[str, ...],
    field: str,
) -> dict[str, Any]:
    lines = [normalized_wat_line(line) for line in handler.lines]
    matches: list[tuple[int, int, int]] = []
    for start in range(len(lines) - 2):
        if not (
            lines[start] in {f"local.get {local}", f"local.tee {local}"}
            and lines[start + 1] == "i32.eqz"
            and lines[start + 2].startswith("if $")
        ):
            continue
        end = matching_wat_end(handler.lines, start + 2, f"{cid} {field} missing branch")
        for call_index in range(start + 3, end):
            call = wat_call_name(handler.lines[call_index]) or ""
            if not any(call.endswith(suffix) for suffix in constructor_suffixes):
                continue
            if call_index + 1 >= end:
                continue
            assigned = wat_local(handler.lines[call_index + 1], "tee") or wat_local(
                handler.lines[call_index + 1], "set"
            )
            if assigned == local:
                matches.append((start, end, call_index))
    require(len(matches) == 1, f"{cid} {field} missing-entity assignment drift")
    start, end, constructor = matches[0]
    return {
        "entity_local": local,
        "missing_branch_constructs_same_local": True,
        "constructor": wat_call_name(handler.lines[constructor]),
        "branch_slice_sha256": wat_slice_sha256(handler, start, end),
    }


def prove_template_event_pool_argument(
    cid: str,
    generation: str,
    handler: Any,
    memory: bytearray,
    pool_call_index: int,
    template_call_index: int,
    template_argument_local: str,
) -> dict[str, Any]:
    lines = [normalized_wat_line(line) for line in handler.lines]
    search = range(pool_call_index + 1, template_call_index)
    template_literals = [
        index
        for index in search
        if decoded_wat_constant(handler.lines[index], memory) == "Pool"
    ]
    require(len(template_literals) == 1, f"{cid} Pool template literal drift")
    if generation == "legacy":
        getters = [
            index
            for index in search
            if (wat_call_name(handler.lines[index]) or "").endswith(
                "PoolCreated__Params#get:pool"
            )
        ]
        require(len(getters) == 1, f"{cid} legacy template event.pool getter drift")
        getter = getters[0]
        pool_value_local = wat_local(handler.lines[getter + 1], "set")
        require(pool_value_local is not None, f"{cid} legacy template pool local missing")
        constructors = [
            index
            for index in search
            if (wat_call_name(handler.lines[index]) or "").endswith(
                "Array<~lib/@graphprotocol/graph-ts/index/TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#constructor"
            )
        ]
        require(len(constructors) == 1, f"{cid} legacy template array constructor drift")
        constructor = constructors[0]
        require(
            constructor >= 2
            and constructor + 1 < template_call_index
            and decoded_wat_constant(handler.lines[constructor - 2], memory) == "Pool"
            and lines[constructor - 1] == "i32.const 1"
            and wat_local(handler.lines[constructor + 1], "tee") == template_argument_local,
            f"{cid} legacy template array identity drift",
        )
        conversions = [
            index
            for index in range(constructor + 2, template_call_index)
            if (wat_call_name(handler.lines[index]) or "").endswith(
                "typeConversion.bytesToHex"
            )
        ]
        require(len(conversions) == 1, f"{cid} legacy template pool conversion drift")
        conversion = conversions[0]
        require(
            lines[conversion - 1] == f"local.get {pool_value_local}",
            f"{cid} legacy template conversion source drift",
        )
        converted_local = wat_local(handler.lines[conversion + 1], "set")
        require(
            converted_local is not None
            and lines[conversion + 2] == "i32.load"
            and lines[conversion + 3] == f"local.get {converted_local}"
            and lines[conversion + 4] == "i32.store offset=8"
            and lines[template_call_index - 1] == f"local.get {template_argument_local}",
            f"{cid} legacy template array value dataflow drift",
        )
        event_parameter = "pool"
        proof_start = getter
    else:
        require(generation == "modern", f"{cid} unknown Factory generation: {generation}")
        getters = [
            index
            for index in search
            if (wat_call_name(handler.lines[index]) or "").endswith(
                "ethereum.EventParam>#__get"
            )
            and lines[index - 1] == "i32.const 4"
        ]
        require(len(getters) == 1, f"{cid} modern template event.pool getter drift")
        getter = getters[0]
        require(
            lines[getter + 1] == "i32.load offset=4"
            and (wat_call_name(handler.lines[getter + 2]) or "").endswith(
                "ethereum.Value#toAddress"
            ),
            f"{cid} modern template event.pool address drift",
        )
        pool_value_local = wat_local(handler.lines[getter + 3], "set")
        require(pool_value_local is not None, f"{cid} modern template pool local missing")
        constructors = [
            index
            for index in search
            if (wat_call_name(handler.lines[index]) or "").endswith("rt/__newArray")
        ]
        require(len(constructors) == 1, f"{cid} modern template array constructor drift")
        constructor = constructors[0]
        require(
            wat_local(handler.lines[constructor + 1], "tee") == template_argument_local,
            f"{cid} modern template array identity drift",
        )
        conversions = [
            index
            for index in range(constructor + 2, template_call_index)
            if (wat_call_name(handler.lines[index]) or "").endswith(
                "typeConversion.bytesToHex"
            )
        ]
        require(len(conversions) == 1, f"{cid} modern template pool conversion drift")
        conversion = conversions[0]
        require(
            lines[conversion - 1] == f"local.get {pool_value_local}",
            f"{cid} modern template conversion source drift",
        )
        converted_local = wat_local(handler.lines[conversion + 1], "set")
        require(
            converted_local is not None
            and lines[conversion + 2] == f"local.get {template_argument_local}"
            and lines[conversion + 3] == "i32.load offset=4"
            and lines[conversion + 4] == f"local.get {converted_local}"
            and lines[conversion + 5] == "i32.store"
            and template_literals[0] == template_call_index - 2
            and lines[template_call_index - 1] == f"local.get {template_argument_local}",
            f"{cid} modern template array value dataflow drift",
        )
        event_parameter = "index 4 (pool)"
        proof_start = getter - 1
    return {
        "name": "Pool",
        "arguments": ["event.pool converted to hex"],
        "event_parameter": event_parameter,
        "event_value_local": pool_value_local,
        "converted_value_local": converted_local,
        "argument_array_local": template_argument_local,
        "literal_wat_line": handler.start_line + template_literals[0],
        "argument_dataflow_machine_proven": True,
        "binding_slice_sha256": wat_slice_sha256(
            handler, proof_start, template_call_index
        ),
    }


def prove_factory_effect_order_and_arguments(
    cid: str,
    generation: str,
    handler: Any,
    memory: bytearray,
) -> dict[str, Any]:
    control_depths = wat_control_depths(handler.lines)
    effects: list[dict[str, Any]] = []
    for line_index, call in WRITER.function_call_sites(handler):
        normalized = call.replace("generated/schema/", "src/types/schema/")
        if normalized.endswith("schema/Pool#save"):
            effects.append(
                {
                    "effect": "Pool.save",
                    "call_index": line_index,
                    "argument_local": wat_local(handler.lines[line_index - 1]),
                    "call": normalized,
                }
            )
        elif normalized.endswith("dataSource.create"):
            effects.append(
                {
                    "effect": "PoolTemplate.create",
                    "call_index": line_index,
                    "argument_local": wat_local(handler.lines[line_index - 1]),
                    "call": normalized,
                }
            )
        elif normalized.endswith("schema/Token#save"):
            effects.append(
                {
                    "effect": "Token.save",
                    "call_index": line_index,
                    "argument_local": wat_local(handler.lines[line_index - 1]),
                    "call": normalized,
                }
            )
        elif normalized.endswith("schema/Factory#save"):
            effects.append(
                {
                    "effect": "Factory.save",
                    "call_index": line_index,
                    "argument_local": wat_local(handler.lines[line_index - 1]),
                    "call": normalized,
                }
            )
        elif normalized == WRITER.STORE_SET_CALL:
            arguments = direct_store_arguments(cid, handler, memory, line_index)
            if arguments["target"] in {"Pool", "Factory"}:
                effects.append(
                    {
                        "effect": f"{arguments['target']}.save",
                        "call_index": line_index,
                        "argument_local": arguments["entity_local"],
                        "call": normalized,
                        "direct_store_arguments": arguments,
                    }
                )
    expected = ["Pool.save", "PoolTemplate.create", "Token.save", "Token.save", "Factory.save"]
    require([item["effect"] for item in effects] == expected, f"{cid} Factory effect sequence drift")
    pool_effect, template_effect, token0_effect, token1_effect, factory_effect = effects

    if generation == "legacy":
        identities = legacy_factory_identity_locals(cid, handler, memory)
        require(
            all(control_depths[item["call_index"]] == 0 for item in effects),
            f"{cid} legacy Factory effects are not top-level",
        )
        mandatory_store_proofs: dict[str, Any] = {}
        missing_entity_proofs = {
            "Factory": prove_missing_entity_assignment(
                cid,
                handler,
                identities["factory"],
                ("schema/Factory#constructor",),
                "Factory",
            ),
            "Token[token0]": prove_missing_entity_assignment(
                cid,
                handler,
                identities["token0"],
                ("schema/Factory#constructor",),
                "Token[token0]",
            ),
            "Token[token1]": prove_missing_entity_assignment(
                cid,
                handler,
                identities["token1"],
                ("schema/Factory#constructor",),
                "Token[token1]",
            ),
        }
    else:
        require(generation == "modern", f"{cid} unknown Factory generation: {generation}")
        pool_arguments = pool_effect["direct_store_arguments"]
        factory_arguments = factory_effect["direct_store_arguments"]
        identities = modern_factory_identity_locals(
            cid,
            handler,
            memory,
            pool_arguments["entity_local"],
        )
        mandatory_store_proofs = {
            "Pool.save": prove_mandatory_modern_store(
                cid, handler, memory, pool_effect["call_index"], pool_arguments
            ),
            "Factory.save": prove_mandatory_modern_store(
                cid, handler, memory, factory_effect["call_index"], factory_arguments
            ),
        }
        require(
            all(
                control_depths[item["call_index"]] == 0
                for item in (template_effect, token0_effect, token1_effect)
            ),
            f"{cid} modern template or Token effect is not top-level",
        )
        missing_entity_proofs = {
            "Factory": prove_missing_entity_assignment(
                cid,
                handler,
                identities["factory"],
                ("collections/Entity#constructor",),
                "Factory",
            ),
            "Token[token0]": prove_missing_entity_assignment(
                cid,
                handler,
                identities["token0"],
                ("schema/Token#constructor",),
                "Token[token0]",
            ),
            "Token[token1]": prove_missing_entity_assignment(
                cid,
                handler,
                identities["token1"],
                ("schema/Token#constructor",),
                "Token[token1]",
            ),
        }

    require(pool_effect["argument_local"] == identities["pool"], f"{cid} Pool.save argument drift")
    require(token0_effect["argument_local"] == identities["token0"], f"{cid} token0 save argument drift")
    require(token1_effect["argument_local"] == identities["token1"], f"{cid} token1 save argument drift")
    require(factory_effect["argument_local"] == identities["factory"], f"{cid} Factory.save argument drift")
    require(template_effect["argument_local"] is not None, f"{cid} template argument array local missing")

    template_binding = prove_template_event_pool_argument(
        cid,
        generation,
        handler,
        memory,
        pool_effect["call_index"],
        template_effect["call_index"],
        template_effect["argument_local"],
    )
    effect_suffix = range(pool_effect["call_index"] + 1, factory_effect["call_index"])
    between = [normalized_wat_line(handler.lines[index]) for index in effect_suffix]
    control_transfers = [
        line
        for line in between
        if line == "return" or re.match(r"^br(?:_if|_table)?\b", line)
    ]
    require(not control_transfers, f"{cid} Factory effect suffix has bypassing control transfer")
    for item in effects:
        item["wat_line"] = handler.start_line + item.pop("call_index")
    return {
        "reviewed_and_machine_proven_order": [
            "Pool.save",
            "PoolTemplate.create",
            "Token[token0].save",
            "Token[token1].save",
            "Factory.save",
        ],
        "effects": effects,
        "entity_identity_locals": identities,
        "missing_entity_initialization_proofs": missing_entity_proofs,
        "template": template_binding,
        "mandatory_inlined_store_proofs": mandatory_store_proofs,
        "same_normal_return_path_machine_proven": True,
        "earlier_effect_dominates_later_effect_on_normal_return": True,
        "argument_identity_machine_proven": True,
        "template_identity_and_argument_machine_proven": True,
        "same_path_or_dataflow_machine_proven": True,
        "trap_or_return_before_an_effect_omits_its_suffix": True,
        "graph_handler_rollback_proven_by_retained_wat": False,
        "effect_suffix_sha256": wat_slice_sha256(
            handler,
            next(index for index, line in enumerate(handler.lines) if handler.start_line + index == effects[0]["wat_line"]),
            next(index for index, line in enumerate(handler.lines) if handler.start_line + index == effects[-1]["wat_line"]),
        ),
    }


def prove_factory_total_supply_helper(
    cid: str,
    generation: str,
    function: Any,
    functions: dict[str, Any],
) -> dict[str, Any]:
    lines = [normalized_wat_line(line) for line in function.lines]
    calls = [name.replace("generated/schema/", "src/types/schema/") for name in WRITER.function_calls(function)]
    if generation == "legacy":
        require(
            len(lines) == 12
            and calls[-3].endswith("ERC20#try_totalSupply")
            and calls[-2].endswith("CallResult<~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value>>#get:reverted")
            and calls[-1].endswith("ByteArray.fromI32")
            and not any(call.endswith("#get:value") for call in calls),
            f"{cid} legacy total-supply helper call model drift",
        )
        result_local = wat_local(function.lines[4], "tee")
        require(
            result_local is not None
            and lines[6].startswith("if $")
            and lines[7] == "i32.const 0"
            and lines[8] == "else"
            and lines[9] == f"local.get {result_local}"
            and lines[10] == "end"
            and lines[11].startswith("call $")
            and lines[11].rstrip(")").endswith("ByteArray.fromI32"),
            f"{cid} legacy total-supply success/failure branch drift",
        )
        model = {
            "reverted": "ByteArray.fromI32(0)",
            "success": "ByteArray.fromI32(CallResult allocation pointer), not decoded ERC20 value",
            "erc20_result_value_decoded": False,
        }
    else:
        require(generation == "modern", f"{cid} unknown Factory generation: {generation}")
        require(
            sum(call.endswith("ethereum.SmartContract#tryCall") for call in calls) == 1
            and sum(call.endswith("CallResult.fromValue<~lib/@graphprotocol/graph-ts/common/numbers/BigInt>") for call in calls) == 1
            and calls[-1].endswith("#get:value"),
            f"{cid} modern total-supply helper call model drift",
        )
        fallback_start = require_contiguous_wat(
            lines,
            [
                "i32.const 0",
                "call $~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
                "local.set $l1",
            ],
            f"{cid} modern total-supply zero fallback",
        )
        require(fallback_start < 20, f"{cid} modern total-supply fallback placement drift")
        try_call = next(
            index
            for index, line in enumerate(function.lines)
            if (wat_call_name(line) or "").endswith("ethereum.SmartContract#tryCall")
        )
        raw_result_local = wat_local(function.lines[try_call + 1], "tee")
        require(
            raw_result_local is not None
            and lines[try_call + 2] == "i32.load"
            and lines[try_call + 3] == "i32.eqz"
            and lines[try_call + 4].startswith("if $")
            and lines[try_call + 8] == f"local.tee {raw_result_local}"
            and lines[try_call + 9 : try_call + 16]
            == [
                "i32.const 0",
                "i32.store",
                f"local.get {raw_result_local}",
                "i32.const 0",
                "i32.store",
                f"local.get {raw_result_local}",
                lines[try_call + 15],
            ]
            and lines[try_call + 15].startswith("br $"),
            f"{cid} modern reverted CallResult construction drift",
        )
        success_value_local = wat_local(function.lines[try_call + 17])
        require(
            success_value_local == raw_result_local
            and lines[try_call + 17 : try_call + 23]
            == [
                f"local.get {raw_result_local}",
                lines[try_call + 18],
                "i32.const 0",
                lines[try_call + 20],
                lines[try_call + 21],
                lines[try_call + 22],
            ]
            and (wat_call_name(function.lines[try_call + 18]) or "").endswith(
                "CallResult<~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value>>#get:value"
            )
            and (wat_call_name(function.lines[try_call + 20]) or "").endswith(
                "Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get"
            )
            and (wat_call_name(function.lines[try_call + 21]) or "").endswith(
                "ethereum.Value#toBigInt"
            )
            and (wat_call_name(function.lines[try_call + 22]) or "").endswith(
                "CallResult.fromValue<~lib/@graphprotocol/graph-ts/common/numbers/BigInt>"
            ),
            f"{cid} modern total-supply successful result decode dataflow drift",
        )
        from_value_name = next(
            call
            for call in calls
            if call.endswith(
                "CallResult.fromValue<~lib/@graphprotocol/graph-ts/common/numbers/BigInt>"
            )
        )
        require(from_value_name in functions, f"{cid} modern CallResult.fromValue helper missing")
        from_value = functions[from_value_name]
        from_value_lines = [normalized_wat_line(line) for line in from_value.lines]
        require(
            len(from_value_lines) >= 20
            and from_value_lines[-7].startswith("local.get $")
            and from_value_lines[-6] == "local.get $p0"
            and from_value_lines[-5] == "i32.store"
            and from_value_lines[-4].startswith("local.get $")
            and from_value_lines[-3].startswith("local.get $")
            and from_value_lines[-2] == "i32.store"
            and from_value_lines[-1].startswith("local.get $"),
            f"{cid} modern CallResult.fromValue value wrapper drift",
        )
        value_wrapper_local = wat_local(from_value.lines[-7])
        outer_local = wat_local(from_value.lines[-4])
        require(
            value_wrapper_local is not None
            and outer_local is not None
            and wat_local(from_value.lines[-3]) == value_wrapper_local
            and normalized_wat_line(from_value.lines[-1]).rstrip(")")
            == f"local.get {outer_local}",
            f"{cid} modern CallResult.fromValue outer/value local drift",
        )
        tail = lines[-8:]
        result_local = wat_local(function.lines[-8], "tee")
        require(
            len(lines) == try_call + 32
            and result_local is not None
            and lines[try_call + 23 :]
            == [
                "end",
                f"local.tee {result_local}",
                "i32.load",
                lines[try_call + 26],
                f"local.get {result_local}",
                lines[try_call + 28],
                "else",
                "local.get $l1",
                lines[try_call + 31],
            ]
            and lines[try_call + 26].startswith("if $")
            and "(result i32)" in lines[try_call + 26]
            and (wat_call_name(function.lines[try_call + 28]) or "").endswith(
                "CallResult<~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value>>#get:value"
            )
            and lines[try_call + 31].startswith("end")
            and tail[1] == "i32.load"
            and tail[2].startswith("if $")
            and tail[3] == f"local.get {result_local}"
            and tail[4].startswith("call $")
            and tail[4].endswith("#get:value")
            and tail[5] == "else"
            and tail[6] == "local.get $l1"
            and tail[7].startswith("end"),
            f"{cid} modern total-supply final success/failure branch drift",
        )
        model = {
            "reverted": "BigInt.fromI32(0)",
            "success": "decoded ERC20 totalSupply CallResult BigInt value",
            "erc20_result_value_decoded": True,
        }
    return {
        "function": function.name,
        "body_sha256": hashlib.sha256(function.payload).hexdigest(),
        "generation": generation,
        "outcomes": model,
        "success_wrapper_body_sha256": (
            hashlib.sha256(from_value.payload).hexdigest()
            if generation == "modern"
            else None
        ),
        "success_result_decode_is_contiguous_into_value_wrapper": generation == "modern",
        "success_failure_dataflow_machine_proven": True,
    }


def load_factory_wat_context(
    root: Path,
    cid: str,
    writer: dict[str, Any],
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    analyses = {item["cid"]: item for item in writer["mapping_analyses"]}
    profiles = {
        item["mapping_cid"]: item
        for item in writer["factory_writer_contract"]["mapping_bindings"]
    }
    require(cid in analyses and cid in profiles, f"unknown Factory mapping: {cid}")
    executable = WRITER.resolve_wasm2wat(wasm2wat)
    artifact = root.resolve() / f"uniswap-v3/graft-ancestry/v1/artifacts/{cid}"
    require(artifact.is_file(), f"retained Factory artifact missing: {cid}")
    require(raw_sha256(artifact) == analyses[cid]["sha256"], f"Factory artifact digest drift: {cid}")
    payload = WRITER.run_wasm2wat(executable, artifact)
    require(
        hashlib.sha256(payload).hexdigest() == analyses[cid]["wat_sha256"],
        f"Factory WAT digest drift: {cid}",
    )
    memory, functions, _indirect, exports = WRITER.parse_wat(payload.decode())
    handler = WRITER.resolve_handler(functions, exports, "handlePoolCreated")
    require(
        handler.name == analyses[cid]["registered_handler_export_targets"]["handlePoolCreated"]
        and hashlib.sha256(handler.payload).hexdigest()
        == analyses[cid]["registered_handlers"]["handlePoolCreated"]["body_sha256"],
        f"Factory handler binding drift: {cid}",
    )
    return {
        "cid": cid,
        "profile": profiles[cid],
        "analysis": analyses[cid],
        "memory": memory,
        "functions": functions,
        "handler": handler,
    }


def prove_factory_wat_context(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["cid"]
    profile = context["profile"]
    generation = profile["metadata_generation"]
    handler = context["handler"]
    functions = context["functions"]
    memory = context["memory"]
    if generation == "legacy":
        guard = prove_factory_excluded_pool_guard(
            cid, generation, handler, functions, memory
        )
        closed = [FACTORY_GUARD_UPSTREAM_PATH]
        remaining = [FACTORY_EFFECT_UPSTREAM_PATH, FACTORY_STATIC_UPSTREAM_PATH]
    else:
        upstream_guard = profile["excluded_pool_guard_observation"]
        guard = {
            "claim_status": "withheld_after_independent_review",
            "evidence_kind": upstream_guard["evidence_kind"],
            "handler_body_sha256": upstream_guard["handler_body_sha256"],
            "literal_present_machine_checked": upstream_guard[
                "literal_present_machine_checked"
            ],
            "some_equality_call_present_machine_checked": upstream_guard[
                "some_equality_call_present_machine_checked"
            ],
            "event_pool_to_comparison_to_early_return_machine_proven": False,
            "residual": (
                "the bounded modern parser/local-flow proof is withdrawn; mutable-local "
                "and structured-control counterexamples require a more general analyzer"
            ),
        }
        closed = []
        remaining = [
            FACTORY_GUARD_UPSTREAM_PATH,
            FACTORY_EFFECT_UPSTREAM_PATH,
            FACTORY_STATIC_UPSTREAM_PATH,
        ]
    upstream_effects = profile["pool_created_effect_order_observation"]
    effects = {
        "claim_status": "withheld_after_independent_review",
        "evidence_kind": upstream_effects["evidence_kind"],
        "handler_body_sha256": upstream_effects["handler_body_sha256"],
        "machine_checked_lexical_tail": upstream_effects["machine_checked_lexical_tail"],
        "reviewed_order": upstream_effects["reviewed_order"],
        "same_path_or_dataflow_machine_proven": False,
        "argument_identity_machine_proven": False,
        "template_identity_and_argument_machine_proven": False,
        "graph_handler_rollback_proven_by_retained_wat": False,
        "residual": (
            "lexical callsites and reviewed order are provenance only; same-path "
            "dominance, exact arguments, template identity, and rollback are unproved"
        ),
    }
    total_supply = WRITER.resolve_suffix_function(
        functions,
        "/fetchTokenTotalSupply",
        f"{cid} total-supply helper",
    )
    upstream_total_supply = profile["metadata_evidence"]["total_supply_helper"]
    require(
        total_supply.name == upstream_total_supply["function"]
        and hashlib.sha256(total_supply.payload).hexdigest()
        == upstream_total_supply["body_sha256"],
        f"{cid} total-supply helper provenance drift",
    )
    total_supply_proof = {
        "claim_status": "withheld_after_independent_review",
        "function": total_supply.name,
        "body_sha256": hashlib.sha256(total_supply.payload).hexdigest(),
        "generation": generation,
        "upstream_model": profile["metadata_evidence"]["total_supply_model"],
        "success_failure_dataflow_machine_proven": False,
        "success_result_decode_is_contiguous_into_value_wrapper": False,
        "residual": (
            "the upstream model is digest-bound provenance only; success/failure value "
            "dataflow is not promoted by v2"
        ),
    }
    handler_total_supply_calls = sum(
        call.endswith("/fetchTokenTotalSupply")
        for call in WRITER.function_calls(handler)
    )
    require(handler_total_supply_calls == 2, f"{cid} Factory total-supply call count drift")
    return {
        "mapping_cid": cid,
        "profile_id": profile["profile_id"],
        "generation": generation,
        "retained_wat_sha256": context["analysis"]["wat_sha256"],
        "handler_body_sha256": hashlib.sha256(handler.payload).hexdigest(),
        "excluded_pool_guard": guard,
        "normal_return_effect_order_and_arguments": effects,
        "initialized_field_value_evidence": {
            "machine_proven_subset": [],
            "total_supply_helper": total_supply_proof,
            "handler_total_supply_call_count": handler_total_supply_calls,
            "complete_all_initialized_field_values_machine_proven": False,
            "residual": (
                "all Factory/Bundle/Token/Pool initialized values, totalSupply value "
                "dataflow, and symbol/name/decimals branches need a broader "
                "interprocedural typed-stack and global-initializer proof"
            ),
        },
        "closed_upstream_unresolved_paths": closed,
        "remaining_upstream_unresolved_paths": remaining,
        "upstream_unresolved_path_count_before": 3,
        "upstream_unresolved_path_count_closed": len(closed),
        "upstream_unresolved_path_count_after": len(remaining),
        "complete_static_handler_contract": False,
    }


def build_factory_wat_proofs(
    root: Path,
    writer: dict[str, Any],
    wasm2wat: Path | None,
) -> list[dict[str, Any]]:
    cids = sorted(
        item["mapping_cid"]
        for item in writer["factory_writer_contract"]["mapping_bindings"]
    )
    require(len(cids) == 6 and len(set(cids)) == 6, "Factory proof mapping count drift")
    proofs = [
        prove_factory_wat_context(load_factory_wat_context(root, cid, writer, wasm2wat))
        for cid in cids
    ]
    require(
        sum(item["upstream_unresolved_path_count_closed"] for item in proofs) == 4,
        "Factory upstream proof closure count drift",
    )
    return proofs


def matrix_field_records(matrix: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for segment in matrix["segments"]:
        for entity in segment["entity_field_matrix"]:
            for field in entity["fields"]:
                result.setdefault((entity["entity"], field["name"]), []).append(field)
    require(len(result) == 299, "schema must contain exactly 299 stored fields")
    require(all(len(records) == 8 for records in result.values()), "field is not present in all eight segments")
    return result


def v1_field_records(v1: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {(item["entity"], item["field"]): item for item in v1["field_catalog"]}
    require(len(result) == 67, "v1 exact field count drift")
    return result


def field_blockers(
    identity: tuple[str, str],
    exact: dict[str, Any] | None,
) -> list[str]:
    entity, _field = identity
    if exact is not None and exact["population_classification"] == "required_absent":
        return []
    blockers: list[str] = []
    if exact is None:
        if identity in POSITION_RELATION_FIELDS:
            blockers.append("exact deployed Graph relation-id serialization is not proved")
        elif entity in {"Transaction", "Pool"}:
            blockers.append("shared field contributions and last-writer history across NPM and Pool handlers are not complete")
        else:
            blockers.append("Factory or non-Flash Pool field value/control dataflow is not machine-proven")
    elif exact["complete_entity_history"] is False:
        blockers.append("selected-handler projection is exact but complete entity history is not certified")
    return blockers


def build_field_catalog(
    matrix: dict[str, Any],
    v1: dict[str, Any],
) -> list[dict[str, Any]]:
    matrix_records = matrix_field_records(matrix)
    exact_records = v1_field_records(v1)
    population = matrix["population_taxonomy"]
    required_absent = set(population["required_absent_entities"])
    conditional = set(population["conditional_entities"])
    require(required_absent == REQUIRED_ABSENT and len(conditional) == 17, "population taxonomy drift")

    catalog: list[dict[str, Any]] = []
    for identity, records in matrix_records.items():
        entity, field = identity
        first = records[0]
        require(
            all(
                (item["type"], item["storage"], item["directives"])
                == (first["type"], first["storage"], first["directives"])
                for item in records
            ),
            f"schema drift across segments: {entity}.{field}",
        )
        exact = exact_records.get(identity)
        classification = "required_absent" if entity in required_absent else "conditional"
        require(
            exact is None or exact["population_classification"] == classification,
            f"v1 population drift: {entity}.{field}",
        )
        statuses = sorted({item["writer_evidence_status"] for item in records})
        handlers = sorted(
            {
                handler
                for segment in matrix["segments"]
                for entity_record in segment["entity_field_matrix"]
                if entity_record["entity"] == entity
                for handler in entity_record["conservative_writer_handlers"]
            }
        )
        if exact is not None:
            semantic_status = (
                "certified_required_absent"
                if classification == "required_absent"
                else "certified_selected_handler_projection"
            )
        elif any("reviewed" in status for status in statuses):
            semantic_status = "digest_bound_reviewed_incomplete"
        else:
            semantic_status = "conservative_reachability_only"
        catalog.append(
            {
                "entity": entity,
                "field": field,
                "type": first["type"],
                "storage": first["storage"],
                "directives": first["directives"],
                "population_classification": classification,
                "conservative_writer_handlers": handlers,
                "upstream_writer_evidence_statuses": statuses,
                "upstream_eight_segment_field_records_sha256": canonical_sha256(records),
                "semantic_status": semantic_status,
                "complete_selected_handler_projection": bool(
                    exact is not None and classification == "conditional"
                ),
                "complete_entity_history": bool(
                    exact is not None and exact["complete_entity_history"] is True
                ),
                "v1_record_sha256": canonical_sha256(exact) if exact is not None else None,
                "blockers": field_blockers(identity, exact),
            }
        )
    require(len(catalog) == 299, "generated field catalog count drift")
    require(
        sum(item["semantic_status"].startswith("certified_") for item in catalog) == 67,
        "v1 certified count drift",
    )
    require(
        sum(
            item["semantic_status"]
            in {"digest_bound_reviewed_incomplete", "conservative_reachability_only"}
            for item in catalog
        )
        == 232,
        "residual field count drift",
    )
    return catalog


def certified_fields_by_handler(v1: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {handler: set() for handler in (*NPM_HANDLERS, FLASH_HANDLER)}
    rules = v1["field_rule_catalog"]
    for field in v1["field_catalog"]:
        if field["population_classification"] != "conditional":
            continue
        identity = f"{field['entity']}.{field['field']}"
        for rule_id in field["rule_ids"]:
            for handler in rules[rule_id]["handlers"]:
                result.setdefault(handler, set()).add(identity)
    return {handler: sorted(fields) for handler, fields in result.items()}


def build_handler_record(
    handler: dict[str, Any],
    certified: dict[str, list[str]],
) -> dict[str, Any]:
    handler_id = handler["handler_id"]
    certified_fields = certified.get(handler_id, [])
    status = (
        "selected_handler_projection_certified_but_full_output_incomplete"
        if certified_fields
        else "retained_wasm_and_reviewed_semantics_bound_control_dataflow_incomplete"
    )
    return {
        "handler_id": handler_id,
        "component": handler["component"],
        "component_type": handler["component_type"],
        "event": handler["event"],
        "mapping_cid": handler["mapping_cid"],
        "numeric_export_function_index": handler["numeric_export_function_index"],
        "exact_wat_export_target": handler["exact_wat_export_target"],
        "body_binding": handler["body_binding"],
        "conservative_entity_writer_reachability": handler["conservative_entity_writer_reachability"],
        "conservative_ethereum_call_reachability": handler["conservative_ethereum_call_reachability"],
        "named_schema_setter_site_count": handler["named_schema_setter_site_count"],
        "named_schema_setter_sites_sha256": handler["named_schema_setter_sites_sha256"],
        "conservative_named_schema_setter_candidates": handler["conservative_named_schema_setter_candidates"],
        "reviewed_semantics": handler["reviewed_semantics"],
        "machine_proven_paths": proof_boolean_paths(handler, True),
        "unresolved_control_dataflow_paths": proof_boolean_paths(handler, False),
        "certified_v1_projection_fields": certified_fields,
        "status": status,
        "complete_field_output_semantics": False,
        "source_handler_record_sha256": canonical_sha256(handler),
    }


def segment_field_matrix(
    matrix_segment: dict[str, Any],
    field_catalog: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entity in matrix_segment["entity_field_matrix"]:
        for field in entity["fields"]:
            identity = (entity["entity"], field["name"])
            catalog = field_catalog[identity]
            result.append(
                {
                    "entity": identity[0],
                    "field": identity[1],
                    "type": field["type"],
                    "population_classification": catalog["population_classification"],
                    "semantic_status": catalog["semantic_status"],
                    "complete_selected_handler_projection": catalog["complete_selected_handler_projection"],
                    "complete_entity_history": catalog["complete_entity_history"],
                    "conservative_writer_handlers": entity["conservative_writer_handlers"],
                    "writer_evidence_status": field["writer_evidence_status"],
                    "writer_evidence": field["writer_evidence"],
                    "source_matrix_field_record_sha256": canonical_sha256(field),
                    "blockers": catalog["blockers"],
                }
            )
    require(len(result) == 299, f"segment field count drift: {matrix_segment['segment_id']}")
    return result


def build_segments(
    matrix: dict[str, Any],
    v1: dict[str, Any],
    catalog: list[dict[str, Any]],
    factory_wat_proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    field_by_identity = {(item["entity"], item["field"]): item for item in catalog}
    certified = certified_fields_by_handler(v1)
    v1_segments = {item["segment_id"]: item for item in v1["segments"]}
    factory_proofs = {item["mapping_cid"]: item for item in factory_wat_proofs}
    require(len(factory_proofs) == 6, "Factory WAT proof binding count drift")
    results: list[dict[str, Any]] = []
    for segment in matrix["segments"]:
        require(segment["segment_id"] in v1_segments, f"v1 segment missing: {segment['segment_id']}")
        handlers = [build_handler_record(item, certified) for item in segment["handlers"]]
        require(
            tuple(item["handler_id"] for item in handlers) == HANDLER_ORDER,
            f"handler order drift: {segment['segment_id']}",
        )
        fields = segment_field_matrix(segment, field_by_identity)
        profiles = {
            component: {
                "mapping_cid": binding["mapping_cid"],
                "profile_id": binding["profile_id"],
                "source_record_sha256": binding["source_record_sha256"],
            }
            for component, binding in segment["profile_bindings"].items()
        }
        factory_cid = profiles["factory"]["mapping_cid"]
        require(factory_cid in factory_proofs, f"Factory WAT proof missing: {factory_cid}")
        factory_wat_proof = factory_proofs[factory_cid]
        semantic_surface = {
            "population_taxonomy": matrix["population_taxonomy"],
            "profiles": profiles,
            "factory_wat_cfg_dataflow": factory_wat_proof,
            "handlers": [
                {
                    "handler_id": item["handler_id"],
                    "status": item["status"],
                    "reviewed_semantics": item["reviewed_semantics"],
                    "certified_v1_projection_fields": item["certified_v1_projection_fields"],
                    "unresolved_control_dataflow_paths": item["unresolved_control_dataflow_paths"],
                }
                for item in handlers
            ],
            "fields": fields,
            "calls": segment["calls"],
            "exclusions": segment["exclusions"],
            "ordering": segment["ordering"],
            "quirks": segment["quirks"],
            "deterministic_handler_error_policy_under_source_model": segment[
                "deterministic_handler_error_policy_under_source_model"
            ],
            "manifest_features": segment["manifest_features"],
        }
        provenance_surface = {
            "source_writer_segment_contract_sha256": segment["source_writer_segment_contract_sha256"],
            "source_writer_semantic_contract_sha256": segment["source_writer_semantic_contract_sha256"],
            "source_matrix_sha256": segment["matrix_sha256"],
            "source_v1_segment_sha256": canonical_sha256(v1_segments[segment["segment_id"]]),
            "artifact_bindings_sha256": segment["artifact_bindings_sha256"],
            "profiles": profiles,
            "factory_wat_cfg_dataflow_sha256": canonical_sha256(factory_wat_proof),
            "handlers": [
                {
                    "handler_id": item["handler_id"],
                    "mapping_cid": item["mapping_cid"],
                    "body_binding": item["body_binding"],
                    "entity_reachability_sha256": canonical_sha256(
                        item["conservative_entity_writer_reachability"]
                    ),
                    "call_reachability_sha256": canonical_sha256(
                        item["conservative_ethereum_call_reachability"]
                    ),
                    "source_handler_record_sha256": item["source_handler_record_sha256"],
                }
                for item in handlers
            ],
        }
        results.append(
            {
                "segment_id": segment["segment_id"],
                "network": segment["network"],
                "deployment": segment["deployment"],
                "start_block_inclusive": segment["start_block_inclusive"],
                "end_block_inclusive": segment["end_block_inclusive"],
                "graft": segment["graft"],
                "semantic_surface": semantic_surface,
                "semantic_surface_sha256": canonical_sha256(semantic_surface),
                "provenance_surface": provenance_surface,
                "provenance_surface_sha256": canonical_sha256(provenance_surface),
                "execution_model": "undecided",
                "backfill_allowed": False,
            }
        )
    require(
        len(results) == 8 and len({item["segment_id"] for item in results}) == 8,
        "segment inventory drift",
    )
    return results


def build_segment_diffs(
    matrix: dict[str, Any],
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    upstream = {
        (item["left_segment_id"], item["right_segment_id"]): item
        for item in matrix["segment_diffs"]
    }
    require(len(upstream) == 28, "upstream segment diff count drift")
    results: list[dict[str, Any]] = []
    for left, right in itertools.combinations(segments, 2):
        pair = (left["segment_id"], right["segment_id"])
        require(pair in upstream, f"upstream diff missing: {pair}")
        source = upstream[pair]
        semantic_paths = json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        results.append(
            {
                "left_segment_id": pair[0],
                "right_segment_id": pair[1],
                "relation": source["relation"],
                "boundary_block": source["boundary_block"],
                "left_semantic_surface_sha256": left["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right["semantic_surface_sha256"],
                "evidence_semantic_equal": not semantic_paths,
                "evidence_semantic_diff_paths": semantic_paths,
                "left_provenance_surface_sha256": left["provenance_surface_sha256"],
                "right_provenance_surface_sha256": right["provenance_surface_sha256"],
                "provenance_equal": not provenance_paths,
                "provenance_diff_paths": provenance_paths,
                "source_artifact_diff_paths": source["artifact_diff_paths"],
                "complete_writer_semantics_compared": False,
                "boundary_state_compared": False,
                "graph_oracle_compared": False,
            }
        )
    require(len(results) == 28, "generated segment diff count drift")
    return results


def control_dataflow_ledger(
    writer: dict[str, Any],
    factory_wat_proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    analyses = {item["cid"]: item for item in writer["mapping_analyses"]}
    sources = {item["mapping_cid"]: item for item in writer["source_provenance_bindings"]}
    factory = [("Factory", item) for item in writer["factory_writer_contract"]["mapping_bindings"]]
    pool = [("Pool", item) for item in writer["pool_writer_contract"]["mapping_bindings"]]
    factory_proofs = {item["mapping_cid"]: item for item in factory_wat_proofs}
    require(len(factory_proofs) == 6, "Factory WAT proof ledger count drift")
    records: list[dict[str, Any]] = []
    for component, profile in [*factory, *pool]:
        cid = profile["mapping_cid"]
        analysis = analyses[cid]
        source = sources[cid]
        require(
            source["artifact_authority"] == "retained_mapping_wasm",
            f"source promoted over WASM: {cid}",
        )
        upstream_unresolved = sorted(proof_boolean_paths(profile, False))
        require(upstream_unresolved, f"profile unexpectedly has no unresolved proof path: {cid}")
        proof = factory_proofs.get(cid) if component == "Factory" else None
        if proof is not None:
            require(
                set(upstream_unresolved) == FACTORY_UPSTREAM_UNRESOLVED_PATHS,
                f"Factory upstream unresolved path set drift: {cid}",
            )
            closed = proof["closed_upstream_unresolved_paths"]
            expected_closed = (
                {FACTORY_GUARD_UPSTREAM_PATH}
                if proof["generation"] == "legacy"
                else set()
            )
            require(set(closed) == expected_closed, f"Factory v2 closed path set drift: {cid}")
            unresolved = [item for item in upstream_unresolved if item not in set(closed)]
            require(
                set(unresolved) == FACTORY_UPSTREAM_UNRESOLVED_PATHS - expected_closed,
                f"Factory residual upstream path drift: {cid}",
            )
        else:
            closed = []
            unresolved = upstream_unresolved
        record = {
                "component": component,
                "mapping_cid": cid,
                "profile_id": profile["profile_id"],
                "retained_wasm": {
                    "path": f"uniswap-v3/graft-ancestry/v1/artifacts/{cid}",
                    "bytes": analysis["bytes"],
                    "sha256": analysis["sha256"],
                    "wat_sha256": analysis["wat_sha256"],
                    "artifact_authority": True,
                },
                "mapping_analysis_sha256": canonical_sha256(analysis),
                "profile_record": profile,
                "profile_record_sha256": canonical_sha256(profile),
                "machine_proven_paths": sorted(
                    proof_boolean_paths(profile, True)
                    + (
                        [
                            f"$.v2_retained_wat_cfg_dataflow{path[1:]}"
                            for path in proof_boolean_paths(proof, True)
                        ]
                        if proof is not None
                        else []
                    )
                ),
                "upstream_unresolved_control_dataflow_paths": upstream_unresolved,
                "v2_closed_upstream_control_dataflow_paths": closed,
                "unresolved_control_dataflow_paths": unresolved,
                "source_corroboration": source,
                "source_corroboration_authoritative": False,
            }
        if proof is not None:
            record["v2_retained_wat_cfg_dataflow"] = proof
            record["v2_additional_unresolved_paths"] = sorted(
                f"$.v2_retained_wat_cfg_dataflow{path[1:]}"
                for path in proof_boolean_paths(proof, False)
            )
            record["status"] = (
                "one_of_three_upstream_factory_proof_paths_closed"
                if proof["generation"] == "legacy"
                else "all_three_upstream_factory_proof_paths_unresolved"
            )
        records.append(record)
    records.sort(key=lambda item: (item["component"], item["mapping_cid"]))
    require(
        sum(item["component"] == "Factory" for item in records) == 6,
        "Factory mapping count drift",
    )
    require(
        sum(item["component"] == "Pool" for item in records) == 8,
        "Pool mapping count drift",
    )
    require(
        sum(len(item["v2_closed_upstream_control_dataflow_paths"]) for item in records) == 4,
        "Factory upstream path closure total drift",
    )
    require(
        sum(
            len(item["unresolved_control_dataflow_paths"])
            for item in records
            if item["component"] == "Factory"
        )
        == 14,
        "Factory residual upstream path total drift",
    )
    return records


def truth_boundary() -> dict[str, bool]:
    return {
        **{field: True for field in TRUE_FLAGS},
        **{field: False for field in FALSE_FLAGS},
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    matrix = sources["segment_writer_matrix"]
    writer = sources["writer_compatibility"]
    v1 = sources["segment_field_semantics_v1"]
    factory_wat_proofs = sources.get("_factory_wat_proofs")
    require(
        isinstance(factory_wat_proofs, list) and len(factory_wat_proofs) == 6,
        "recomputed Factory retained-WAT proofs are required",
    )
    catalog = build_field_catalog(matrix, v1)
    segments = build_segments(matrix, v1, catalog, factory_wat_proofs)
    diffs = build_segment_diffs(matrix, segments)
    ledger = control_dataflow_ledger(writer, factory_wat_proofs)
    require(
        sum(len(item["semantic_surface"]["handlers"]) for item in segments) == 80,
        "handler count drift",
    )
    require(
        sum(len(item["semantic_surface"]["fields"]) for item in segments) == 2392,
        "per-segment field record count drift",
    )
    return {
        "format_version": 2,
        "contract_version": CONTRACT_VERSION,
        "mode": "full-inventory-retained-wasm-proof-ledger",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "handler_count_per_segment": 10,
            "segment_handler_record_count": 80,
            "entity_count": 20,
            "stored_field_count": 299,
            "segment_field_record_count": 2392,
            "v1_exact_selected_or_absent_field_count": 67,
            "remaining_conditional_field_count": 232,
            "factory_mapping_count": 6,
            "factory_upstream_unresolved_path_count_before": 18,
            "factory_upstream_unresolved_path_count_closed_by_v2": 4,
            "factory_upstream_unresolved_path_count_after": 14,
            "pool_mapping_count": 8,
            "segment_pair_count": 28,
            "claim": "complete inventory and proof-status ledger; exact semantics only where retained WASM evidence closes the declared scope",
        },
        "source_contracts": {
            name: source_record(relative, version, digest)
            for name, (relative, version, digest) in SOURCE_SPECS.items()
        },
        "authority_contract": {
            "semantic_authority": "retained deployed mapping WASM and its checksum-pinned WABT 1.0.35 --generate-names projection",
            "source_role": "corroboration only; source anchors never replace or promote a deployed-WASM claim",
            "ambiguous_control_or_dataflow": "record an explicit blocker and keep the corresponding completeness gate false",
        },
        "population_contract": matrix["population_taxonomy"],
        "field_catalog": catalog,
        "factory_pool_control_dataflow_ledger": ledger,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "field_count": 232,
            "position_relation_fields": sorted(f"{entity}.{field}" for entity, field in POSITION_RELATION_FIELDS),
            "factory": [
                "only the four legacy excluded-pool guard paths are closed; both modern guard paths remain withdrawn pending a general mutable-local and structured-control proof",
                "all six normal-return effect order, dominance, exact-argument, and template-identity paths remain provenance-only and false",
                "all six per-profile complete_static_handler_contract paths and every initialized field value remain false and require a broader interprocedural typed-stack and global-initializer analyzer",
                "the modern totalSupply success profile and every success/failure value-dataflow claim are withheld; upstream models remain digest-bound provenance only",
                "Graph handler rollback remains bound to Graph Node source evidence rather than claimed from retained mapping WAT",
            ],
            "pool_non_flash": [
                "Initialize persistence path differs by profile but same-path Pool.save execution is not machine-proven",
                "Mint, Burn, and Swap full field formulas, non-try call failure paths, helper side effects, and handler rollback are not completely machine-proven",
                "Swap TickDay relation dataflow, hour resave reachability, pricing/static profiles, and all fee-spacing branches are not uniformly machine-proven",
            ],
            "shared_histories": [
                "Transaction fields also receive Pool Mint, Burn, and Swap writes, so NPM-only history is incomplete",
                "Pool fields receive Factory creation plus Initialize, Mint, Burn, Swap, and Flash writes, so selected-handler projections do not prove complete last-writer history",
            ],
            "execution": [
                "Factory-created Pool hosts require breadth-first whole-block replay, not a raw global-log flattening",
                "post-fatal triggers, persisted data sources, retryable failures, VID, PoI, and deterministic-error streams are not implemented",
            ],
        },
        "truth_boundary": truth_boundary(),
    }


def verify_contract(
    root: Path,
    actual: dict[str, Any] | None = None,
    *,
    sources: dict[str, dict[str, Any]] | None = None,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    verified_sources = sources or load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(verified_sources)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"v2 field-semantics contract missing: {CONTRACT_PATH}")
        actual = load_json_strict(path)
        require(path.read_text() == render(actual), "v2 contract byte rendering drift")
    require(
        canonical_bytes(actual) == canonical_bytes(expected),
        "v2 contract differs from exact generated proof ledger",
    )
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "truth-boundary key drift")
    for field in TRUE_FLAGS:
        require(truth[field] is True, f"proved evidence gate drift: {field}")
    for field in FALSE_FLAGS:
        require(truth[field] is False, f"unproved completion gate promoted: {field}")
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
    except (OSError, VerificationError) as error:
        print(f"segment field-semantics v2 verification failed: {error}", file=sys.stderr)
        return 1
    digest = raw_sha256(args.root.resolve() / CONTRACT_PATH)
    print(
        "verified Uniswap V3 field-semantics v2 proof ledger: "
        f"{contract['scope']['segment_count']} segments, "
        f"{contract['scope']['segment_handler_record_count']} handlers, "
        f"{contract['scope']['stored_field_count']} fields, "
        f"{contract['scope']['segment_pair_count']} diffs, sha256 {digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
