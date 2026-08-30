#!/usr/bin/env python3
"""Verify the bounded runtime capsule for the two modern Uniswap V3 Pool WASMs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/pool-runtime/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-modern-pool-runtime/v1"
BASE_COMMIT = "112fd27745b3cdc252a9df9665481b6fa8257705"
RUNTIME_SOURCE_PATH = Path("scripts/uniswap_v3_wat_runtime.py")
RUNTIME_PATH = REPOSITORY / RUNTIME_SOURCE_PATH
WABT_VERSION = "1.0.35"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


try:
    RUNTIME_SOURCE_BYTES = RUNTIME_PATH.read_bytes()
except OSError as error:
    raise RuntimeError(f"cannot read {RUNTIME_PATH}: {error}") from error
RUNTIME_IMPORT_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_wat_runtime_for_pool_runtime", RUNTIME_PATH
)
if RUNTIME_IMPORT_SPEC is None or RUNTIME_IMPORT_SPEC.loader is None:
    raise RuntimeError(f"cannot import {RUNTIME_PATH}")
RUNTIME = importlib.util.module_from_spec(RUNTIME_IMPORT_SPEC)
sys.modules[RUNTIME_IMPORT_SPEC.name] = RUNTIME
exec(compile(RUNTIME_SOURCE_BYTES, str(RUNTIME_PATH), "exec"), RUNTIME.__dict__)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


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


def bind_candidate_runtime(root: Path) -> str:
    candidate = root.resolve() / RUNTIME_SOURCE_PATH
    try:
        candidate_bytes = candidate.read_bytes()
    except OSError as error:
        raise VerificationError(f"cannot read candidate shared runtime {candidate}: {error}") from error
    require(
        candidate_bytes == RUNTIME_SOURCE_BYTES,
        "candidate-root shared WAT runtime bytes differ from the exact imported runtime bytes",
    )
    return hashlib.sha256(candidate_bytes).hexdigest()


@dataclass(frozen=True)
class WatFunction:
    name: str
    start_line: int
    lines: tuple[str, ...]
    function_index: int

    @property
    def payload(self) -> bytes:
        return ("\n".join(self.lines) + "\n").encode()


@dataclass(frozen=True)
class PoolProfileSpec:
    profile_id: str
    cid: str
    wasm_bytes: int
    wasm_sha256: str
    wat_sha256: str
    start_line_count: int
    start_body_sha256: str
    allocator_floor: int
    initialized_data_end: int
    initialized_data_segment_count: int
    q192_writer_line: int
    ensure_capacity_body_sha256: str
    event_param_get_body_sha256: str


PROFILE_SPECS = (
    PoolProfileSpec(
        profile_id="modern-base",
        cid="QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P",
        wasm_bytes=76_545,
        wasm_sha256="e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c",
        wat_sha256="bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1",
        start_line_count=50,
        start_body_sha256="52a99f58e7904d3ed759bf0a0272101e9e998bdfdb0e2fe93a21aedd6c12d589",
        allocator_floor=20_940,
        initialized_data_end=20_902,
        initialized_data_segment_count=528,
        q192_writer_line=46,
        ensure_capacity_body_sha256="09e6f7222a5ada41dc343ffb5eb297342dd3ff167cd6532bcaeec772f9705578",
        event_param_get_body_sha256="dd7f14070e5643932f0dc9ba5d3e7f9966aa900dc9e171eb213b9aaf4cf6d0c8",
    ),
    PoolProfileSpec(
        profile_id="modern-mainnet",
        cid="QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD",
        wasm_bytes=78_047,
        wasm_sha256="f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970",
        wat_sha256="8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281",
        start_line_count=49,
        start_body_sha256="785ca5348b08a12a9a90b79760beefb3ab8b71130bfc01ee9e48ddefa36c79d3",
        allocator_floor=22_700,
        initialized_data_end=22_662,
        initialized_data_segment_count=558,
        q192_writer_line=45,
        ensure_capacity_body_sha256="90f7a34c6ef281823ee2062d67f72c339ee27b748d82b578348b02c3300a7579",
        event_param_get_body_sha256="d7838efd2a3cd438b05d6d627df4c1ea8ef0a291c02921096b89198d8643de68",
    ),
)

PROFILE_BY_ID = {item.profile_id: item for item in PROFILE_SPECS}
PROFILE_BY_CID = {item.cid: item for item in PROFILE_SPECS}
EXPECTED_ARTIFACT_TUPLES = {
    (item.profile_id, item.cid, item.wasm_sha256, item.wat_sha256)
    for item in PROFILE_SPECS
}

TYPED_MAP_SET_CALL = (
    "~lib/@graphprotocol/graph-ts/common/collections/"
    "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set"
)
TYPED_MAP_GET_CALL = TYPED_MAP_SET_CALL.removesuffix("#set") + "#get"
EVENT_PARAM_GET_CALL = (
    "~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/"
    "ethereum.EventParam>#__get"
)
STUB_NEW_CALL = "~lib/rt/stub/__new"

POOL_COLLECTION_SPEC = RUNTIME.ModernPoolCollectionSpec(
    typed_map_set_call=TYPED_MAP_SET_CALL,
    typed_map_get_call=TYPED_MAP_GET_CALL,
    event_param_get_call=EVENT_PARAM_GET_CALL,
    stub_new_call=STUB_NEW_CALL,
    stub_alloc_body_sha256="a03922d8f65cdc65e9d23c65bae22238c3783fed3294ec8847c2951f45a49c68",
    stub_new_body_sha256="dc15ae7bfd1ff6f9f27d365946a2de6d849b46ed9e08818b80d59c05f97918fa",
    typed_map_set_body_sha256="1e32ff9bb00d137e45c1023931fe103bbe71d7011e2955044d0fb772b88f008b",
    typed_map_get_body_sha256="672fd714a063fdaf09f51b8e3a25c5b01a2124f68f3e8f7fcb587cddeb5999cb",
    entity_constructor_body_sha256="df453669386fdd214d23b561c134fdc0b1fe4e8c9bb46a3b6bec63e22e51d032",
    entity_constructor_type_ids=(25, 27, 29),
    string_eq_body_sha256="f7967b738553ba98aba24f869e968d73e8013f99e83d02e106cad52306aa3c3f",
    profiles={
        item.profile_id: RUNTIME.ModernPoolCollectionProfileSpec(
            ensure_capacity_body_sha256=item.ensure_capacity_body_sha256,
            event_param_get_body_sha256=item.event_param_get_body_sha256,
            memory_fill_body_sha256="3eb4dece783813845638f30ebde64f0ce5c2d10784a724c6b5bcd346e7771390",
            memory_copy_body_sha256="0128a0af41ee62c13df7a14de4648d2e7ac19f230786e447a8736179e36d74a6",
            memcpy_body_sha256="a201b34d93d9bb7e4813134f668fb9436014260ba637d2db39cf7af3dc84a97c",
        )
        for item in PROFILE_SPECS
    },
)

MUTABLE_GLOBALS = (
    "$~started",
    "$~lib/rt/stub/offset",
    "$src/utils/constants/ZERO_BI",
    "$src/utils/constants/ONE_BI",
    "$src/utils/constants/ZERO_BD",
    "$src/utils/constants/ONE_BD",
    "$src/utils/pricing/MINIMUM_ETH_LOCKED",
    "$src/utils/pricing/Q192",
)

TRUE_FLAGS = {
    "exact_two_modern_pool_artifact_tuples_selected",
    "candidate_shared_runtime_bytes_equal_executed_bytes",
    "both_modern_pool_public_collection_capsules_proven",
    "both_modern_pool_77_line_typed_map_setters_proven",
    "both_modern_pool_entity_constructor_type_ids_proven",
    "both_modern_pool_getter_index_and_string_equality_dependencies_proven",
    "both_modern_pool_allocator_return_identities_proven",
    "both_modern_pool_exported_start_and_global_writer_inventories_proven",
    "both_modern_pool_allocator_floors_above_all_initialized_data_proven",
    "both_modern_pool_start_direct_memory_write_absence_proven",
}

FALSE_FLAGS = {
    "all_eight_pool_runtime_capsules_proven",
    "six_legacy_pool_runtime_capsules_proven",
    "pool_initialize_handler_semantics_complete",
    "pool_mint_handler_semantics_complete",
    "pool_burn_handler_semantics_complete",
    "pool_swap_handler_semantics_complete",
    "pool_flash_handler_semantics_complete",
    "pool_complete_entity_history",
    "all_manifest_handler_semantics_complete",
    "actual_historic_event_population_proven",
    "host_functions_cannot_write_arbitrary_linear_memory",
    "aggregate_helper_memory_safety_rederived",
    "boundary_state_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "checkpoint_authority",
    "backfill_ready",
    "production_ready",
    "readiness_complete",
}

DATA_RE = re.compile(r'^  \(data \$\S+ \(i32\.const (\d+)\) "(.*)"\)\)?$')
FUNCTION_RE = re.compile(r"^  \(func \$([^\s]+)")
FUNCTION_IMPORT_RE = re.compile(r'^  \(import "[^"]+" "[^"]+" \(func \$[^\s\)]+')
EXPORT_RE = re.compile(r'^  \(export "([^"]+)" \(func \$([^\s\)]+)\)\)$')
CALL_RE = re.compile(r"\bcall \$([^\s\)]+)")


def decode_wat_string(value: str) -> bytes:
    output = bytearray()
    index = 0
    escapes = {"n": 10, "r": 13, "t": 9, "\\": 92, '"': 34, "'": 39}
    while index < len(value):
        if value[index] != "\\":
            output.extend(value[index].encode())
            index += 1
            continue
        require(index + 1 < len(value), "truncated WAT string escape")
        if (
            index + 2 < len(value)
            and value[index + 1] in "0123456789abcdefABCDEF"
            and value[index + 2] in "0123456789abcdefABCDEF"
        ):
            output.append(int(value[index + 1 : index + 3], 16))
            index += 3
            continue
        escaped = value[index + 1]
        require(escaped in escapes, f"unsupported WAT string escape: {escaped}")
        output.append(escapes[escaped])
        index += 2
    return bytes(output)


def parse_wat(wat: str) -> tuple[dict[str, WatFunction], dict[str, str]]:
    lines = wat.splitlines()
    functions: dict[str, WatFunction] = {}
    function_import_count = sum(FUNCTION_IMPORT_RE.match(line) is not None for line in lines)
    defined_count = 0
    index = 0
    while index < len(lines):
        match = FUNCTION_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        start = index
        balance = 0
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            body.append(line)
            balance += line.count("(") - line.count(")")
            index += 1
            if balance == 0:
                break
        require(balance == 0, f"unterminated WAT function {match.group(1)}")
        name = match.group(1)
        require(name not in functions, f"duplicate WAT function {name}")
        functions[name] = WatFunction(
            name=name,
            start_line=start + 1,
            lines=tuple(body),
            function_index=function_import_count + defined_count,
        )
        defined_count += 1
    require(functions, "WAT contains no named functions")

    exports: dict[str, str] = {}
    for line in lines:
        match = EXPORT_RE.fullmatch(line)
        if match is None:
            continue
        export, target = match.groups()
        require(export not in exports, f"duplicate WAT export {export}")
        require(target in functions, f"WAT export {export} target missing: {target}")
        exports[export] = target
    return functions, exports


def resolve_wasm2wat(candidate: Path | None) -> Path:
    if candidate is None:
        found = shutil.which("wasm2wat")
        require(found is not None, "wasm2wat is required")
        candidate = Path(found)
    require(candidate.is_file(), f"wasm2wat not found: {candidate}")
    version = subprocess.run(
        [str(candidate), "--version"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    require(
        version.returncode == 0 and version.stdout.strip() == WABT_VERSION,
        "wasm2wat version drift",
    )
    return candidate.resolve()


def run_wasm2wat(executable: Path, artifact: Path) -> bytes:
    try:
        result = subprocess.run(
            [str(executable), "--generate-names", str(artifact)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"wasm2wat failed for {artifact.name}: {error}") from error
    require(result.returncode == 0, f"wasm2wat failed for {artifact.name}")
    require(not result.stderr, f"wasm2wat emitted stderr for {artifact.name}")
    try:
        result.stdout.decode()
    except UnicodeDecodeError as error:
        raise VerificationError(f"wasm2wat emitted invalid UTF-8 for {artifact.name}") from error
    return result.stdout


def normalized(line: str) -> str:
    return line.strip().replace("generated/schema/", "src/types/schema/")


def call_name(line: str) -> str | None:
    match = CALL_RE.search(line)
    if match is None:
        return None
    return match.group(1).replace("generated/schema/", "src/types/schema/")


def function_by_suffix(context: dict[str, Any], suffix: str) -> WatFunction:
    if suffix == "~start":
        require("~start" in context["functions"], f"{context['cid']} module start missing")
        return context["functions"]["~start"]
    matches = [
        function
        for name, function in context["functions"].items()
        if name.replace("generated/schema/", "src/types/schema/").endswith(suffix)
    ]
    require(
        len(matches) == 1,
        f"{context['cid']} helper {suffix!r} count drift: {len(matches)}",
    )
    return matches[0]


def runtime_ops() -> Any:
    return RUNTIME.WatRuntimeOps(
        require=require,
        normalized=normalized,
        call_name=call_name,
        function_by_suffix=function_by_suffix,
    )


def initialized_data_inventory(wat: str) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    for line in wat.splitlines():
        match = DATA_RE.fullmatch(line)
        if match is None:
            continue
        offset = int(match.group(1))
        payload = decode_wat_string(match.group(2))
        segments.append(
            {
                "offset": offset,
                "bytes": len(payload),
                "end_exclusive": offset + len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    require(segments, "WAT contains no initialized data segments")
    return {
        "segment_count": len(segments),
        "maximum_end_exclusive": max(item["end_exclusive"] for item in segments),
        "segment_inventory_sha256": canonical_sha256(segments),
    }


def load_context(root: Path, spec: PoolProfileSpec, executable: Path) -> dict[str, Any]:
    artifact_path = (
        root.resolve() / "uniswap-v3/graft-ancestry/v1/artifacts" / spec.cid
    )
    require(artifact_path.is_file(), f"retained Pool artifact missing: {spec.cid}")
    require(artifact_path.stat().st_size == spec.wasm_bytes, f"Pool WASM byte count drift: {spec.cid}")
    require(raw_sha256(artifact_path) == spec.wasm_sha256, f"Pool WASM digest drift: {spec.cid}")
    wat_payload = run_wasm2wat(executable, artifact_path)
    require(
        hashlib.sha256(wat_payload).hexdigest() == spec.wat_sha256,
        f"Pool WAT digest drift: {spec.cid}",
    )
    wat = wat_payload.decode()
    functions, exports = parse_wat(wat)
    return {
        "cid": spec.cid,
        "profile": {"profile_id": spec.profile_id},
        "spec": spec,
        "artifact_path": str(artifact_path.relative_to(root.resolve())),
        "functions": functions,
        "exports": exports,
        "module_text": wat,
        "initialized_data": initialized_data_inventory(wat),
    }


def expected_global_writers(spec: PoolProfileSpec) -> dict[str, list[list[Any]]]:
    return {
        "$~started": [["~start", 7]],
        "$~lib/rt/stub/offset": [
            ["~lib/rt/stub/__alloc", 68],
            ["~lib/array/ensureCapacity", 161],
            ["~lib/array/ensureCapacity", 189],
            ["~start", 9],
        ],
        "$src/utils/constants/ZERO_BI": [["~start", 15]],
        "$src/utils/constants/ONE_BI": [["~start", 18]],
        "$src/utils/constants/ZERO_BD": [["~start", 21]],
        "$src/utils/constants/ONE_BD": [["~start", 24]],
        "$src/utils/pricing/MINIMUM_ETH_LOCKED": [["~start", 40]],
        "$src/utils/pricing/Q192": [["~start", spec.q192_writer_line]],
    }


def prove_start_and_allocator_floor(context: dict[str, Any]) -> dict[str, Any]:
    spec: PoolProfileSpec = context["spec"]
    start = function_by_suffix(context, "~start")
    lines = [normalized(line) for line in start.lines]
    digest = hashlib.sha256(start.payload).hexdigest()
    require(
        len(lines) == spec.start_line_count and digest == spec.start_body_sha256,
        f"{context['cid']} exact Pool start body drift",
    )
    require(
        lines[2:10]
        == [
            "global.get $~started",
            "if $I0",
            "return",
            "end",
            "i32.const 1",
            "global.set $~started",
            f"i32.const {spec.allocator_floor}",
            "global.set $~lib/rt/stub/offset",
        ],
        f"{context['cid']} Pool start idempotence/allocator-floor prelude drift",
    )
    module_state_spec = RUNTIME.ModuleStateSpec(
        initializer_export="_start",
        initializer_function="~start",
        mutable_globals=MUTABLE_GLOBALS,
        expected_global_set_inventory=expected_global_writers(spec),
    )
    module_state = RUNTIME.prove_module_state_invariants(
        context,
        start,
        module_state_spec,
        require=require,
        normalized=normalized,
        canonical_sha256=canonical_sha256,
    )
    direct_writes = [
        index
        for index, line in enumerate(start.lines)
        if RUNTIME.is_direct_memory_write(line, normalized)
    ]
    require(
        direct_writes == [],
        f"{context['cid']} Pool start acquired a direct linear-memory write: {direct_writes}",
    )
    initialized = context["initialized_data"]
    require(
        initialized["segment_count"] == spec.initialized_data_segment_count
        and initialized["maximum_end_exclusive"] == spec.initialized_data_end,
        f"{context['cid']} initialized data inventory drift",
    )
    require(
        spec.initialized_data_end < spec.allocator_floor,
        f"{context['cid']} allocator floor overlaps initialized data",
    )
    return {
        "function": start.name,
        "body_sha256": digest,
        "line_count": len(lines),
        "module_state": module_state,
        "initialized_data": initialized,
        "allocator_floor": spec.allocator_floor,
        "allocator_floor_gap_bytes": spec.allocator_floor - spec.initialized_data_end,
        "direct_memory_write_sites": direct_writes,
        "all_initialized_data_below_allocator_floor_machine_proven": True,
        "start_has_no_direct_linear_memory_write_machine_proven": True,
        "non_start_allocator_writers_are_capsule_bound_but_general_memory_safety_is_not_rederived": True,
    }


def prove_pool_runtime_context(context: dict[str, Any]) -> dict[str, Any]:
    start = prove_start_and_allocator_floor(context)
    capsule = RUNTIME.prove_modern_collection_capsule(
        context, runtime_ops(), POOL_COLLECTION_SPEC
    )
    require(
        capsule["modern_collection_capsule_structurally_closed"] is True,
        f"{context['cid']} modern Pool collection capsule did not close",
    )
    spec: PoolProfileSpec = context["spec"]
    return {
        "profile_id": spec.profile_id,
        "mapping_cid": spec.cid,
        "artifact_selection_tuple": [
            spec.profile_id,
            spec.cid,
            spec.wasm_sha256,
            spec.wat_sha256,
        ],
        "retained_wasm": {
            "path": context["artifact_path"],
            "bytes": spec.wasm_bytes,
            "sha256": spec.wasm_sha256,
            "wat_sha256": spec.wat_sha256,
        },
        "defined_function_count": len(context["functions"]),
        "start_and_allocator_floor": start,
        "public_collection_capsule": capsule,
        "proof_boundaries": {
            "handler_semantics_proven": False,
            "historic_event_population_proven": False,
            "imported_host_functions_assumed_not_to_write_arbitrary_linear_memory": True,
            "complex_allocator_capacity_and_memory_primitive_bodies_are_exact_aggregate_boundaries": True,
            "general_reachable_helper_memory_safety_rederived": False,
        },
        "modern_pool_runtime_facts_only": True,
    }


def expected_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    runtime_sha256 = bind_candidate_runtime(root)
    executable = resolve_wasm2wat(wasm2wat)
    contexts = [load_context(root, spec, executable) for spec in PROFILE_SPECS]
    proofs = [prove_pool_runtime_context(context) for context in contexts]
    observed_tuples = {
        (
            proof["profile_id"],
            proof["mapping_cid"],
            proof["retained_wasm"]["sha256"],
            proof["retained_wasm"]["wat_sha256"],
        )
        for proof in proofs
    }
    require(
        observed_tuples == EXPECTED_ARTIFACT_TUPLES and len(proofs) == 2,
        f"modern Pool artifact tuple selection drift: {sorted(observed_tuples)}",
    )
    truth = {key: True for key in sorted(TRUE_FLAGS)} | {
        key: False for key in sorted(FALSE_FLAGS)
    }
    contract: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "authority_contract": {
            "semantic_authority": "exact retained WASM bytes and checksum-pinned WABT 1.0.35 --generate-names WAT for only the modern Base and modern mainnet Pool mappings",
            "proof_model": "exact artifact tuple selection plus exported initializer/global-writer/data-floor closure and the public modern Pool collection capsule",
            "host_boundary": "imported host functions are assumed not to write arbitrary linear memory; complex capacity and low-level memory bodies retain exact aggregate-body authority",
            "fail_closed_rule": "any candidate runtime, tuple, WAT, export, start, global initializer/writer, allocator floor, data segment, setter/getter/index/equality, Entity type, allocator return, capacity, or low-level memory-body drift leaves every scoped runtime claim false",
        },
        "provenance": {
            "base_commit": BASE_COMMIT,
            "base_commit_verification": "recorded review provenance; Git ancestry is outside this verifier",
            "shared_wat_runtime": {
                "path": RUNTIME_SOURCE_PATH.as_posix(),
                "raw_sha256": runtime_sha256,
                "candidate_bytes_equal_exact_executed_source": True,
            },
            "wabt_version": WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-modern-pool-wasm>"],
        },
        "scope": {
            "pool_mapping_profile_count": 8,
            "newly_closed_modern_runtime_profile_count": 2,
            "residual_legacy_runtime_profile_count": 6,
            "closed_profiles": [item.profile_id for item in PROFILE_SPECS],
            "closed_mapping_cids": [item.cid for item in PROFILE_SPECS],
            "handler_semantics_added": [],
        },
        "modern_pool_runtime_proofs": proofs,
        "truth_boundary": truth,
        "residuals": [
            "six legacy Pool runtime capsules remain unproved",
            "Burn, Mint, Initialize, Swap, and Flash handler semantics are outside this runtime-only certificate",
            "complete Pool entity histories and actual historic event population remain unproved",
            "host memory behavior, boundary continuity, parity, checkpoint, backfill, production, and readiness gates remain false",
        ],
    }
    contract["projection_sha256"] = canonical_sha256(contract)
    return contract


def verify_contract(
    root: Path,
    contract: dict[str, Any] | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    expected = expected_contract(root, wasm2wat)
    committed = contract if contract is not None else load_json(root.resolve() / CONTRACT_PATH)
    require(
        committed == expected,
        "committed modern Pool runtime contract is not the deterministic retained-WAT projection",
    )
    truth = committed["truth_boundary"]
    require(all(type(value) is bool for value in truth.values()), "truth gates must be strict booleans")
    require({key for key, value in truth.items() if value} == TRUE_FLAGS, "true gate set drift")
    require({key for key, value in truth.items() if not value} == FALSE_FLAGS, "false gate set drift")
    projection = dict(committed)
    digest = projection.pop("projection_sha256")
    require(digest == canonical_sha256(projection), "Pool runtime projection digest drift")
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
        contract = (
            write_contract(args.root, args.wasm2wat)
            if args.write
            else verify_contract(args.root, wasm2wat=args.wasm2wat)
        )
    except VerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"verified {contract['contract_version']}: two modern Pool runtime capsules closed; six legacy residual"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
