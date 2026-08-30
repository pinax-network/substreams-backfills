#!/usr/bin/env python3
"""Prove the six retained Uniswap V3 Factory effect suffixes.

The proof is deliberately bounded to the six checksum-pinned deployed Factory
mappings.  It is not a source-level or proximity proof.  A shared structured
handler-local control-flow, reaching-definition, effect-trace, and heap-write
engine is paired with a complete reachable persistent-effect-site scan.
Separate legacy and modern frontends bind the two AssemblyScript generations
to exact event, entity, ID, template, and reviewed save-helper semantics.

The machine claim ends at invocation of Graph host effects.  Retained WAT does
not prove Graph Node transaction rollback after a later trap.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/factory-effects/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-factory-effects/v1"
V2_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
V2_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
GUARD_CONTRACT_PATH = Path("uniswap-v3/factory-guard/v1/contract.json")
GUARD_CONTRACT_SHA256 = "8b9637519a4debc9d875245ca3318ad8269bc7a440837e716750dd007ffd3216"
BASE_COMMIT = "3d99ce161bfc4703d17c4bb7ccbd6ab7451b567d"
V2_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"

V2_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_segment_field_semantics_v2_for_factory_effects", V2_PATH
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


def normalized(line: str) -> str:
    return line.strip().replace("generated/schema/", "src/types/schema/")


def call_name(line: str) -> str | None:
    value = V2.wat_call_name(line)
    return value.replace("generated/schema/", "src/types/schema/") if value else None


EXPECTED_EFFECT_TRACE = (
    "Pool.save",
    "PoolTemplate.create",
    "Token[token0].save",
    "Token[token1].save",
    "Factory.save",
)


LEGACY_CONTROLS = [
    (7, "if", "$I0"),
    (15, "if", "$I1"),
    (104, "if", "$I2"),
    (134, "if", "$I3"),
    (178, "if", "$I4"),
    (208, "if", "$I5"),
    (256, "if", "$I6"),
    (273, "if", "$I7"),
]
MODERN_CONTROLS = [
    (2, "block", "$B0"),
    (26, "if", "$I1"),
    (44, "if", "$I2"),
    (53, "if", "$I3"),
    (62, "if", "$I4"),
    (83, "loop", "$L5"),
    (92, "if", "$I6"),
    (121, "loop", "$L7"),
    (126, "if", "$I8"),
    (146, "if", "$I9"),
    (154, "if", "$I10"),
    (401, "if", "$I11"),
    (410, "if", "$I12"),
    (413, "if", "$I13"),
    (450, "if", "$I14"),
    (458, "if", "$I15"),
    (474, "if", "$I16"),
    (581, "if", "$I17"),
    (717, "if", "$I18"),
    (914, "if", "$I19"),
    (1050, "if", "$I20"),
    (1248, "if", "$I21"),
    (1264, "if", "$I22"),
    (1330, "if", "$I23"),
    (1339, "if", "$I24"),
    (1357, "if", "$I25"),
    (1375, "loop", "$L26"),
    (1380, "if", "$I27"),
    (1386, "if", "$I28"),
    (1437, "loop", "$L29"),
    (1441, "if", "$I30"),
    (1891, "if", "$I31"),
    (1900, "if", "$I32"),
    (1903, "if", "$I33"),
    (1978, "if", "$I34"),
    (1987, "if", "$I35"),
    (1990, "if", "$I36"),
]


GENERATION_INVENTORY: dict[str, dict[str, Any]] = {
    "legacy": {
        "line_count": 443,
        "controls": LEGACY_CONTROLS,
        "branches": [],
        "returns": [8, 137, 211],
        "unreachable": [],
        "select": [],
        "call_indirect": [],
        "write_count": 15,
        "write_map_sha256": "29e1de5c8913be08cbc7b1afd5454c3f43206f1dfcd3a1c95f7c7945d26fa5fe",
        "memory_store_count": 1,
        "memory_store_sha256": "7d421111cf1b88fcdd826c67299e247dcdf5ad0725049d796c1cc896b303eb06",
        "call_count": 182,
        "call_sites_sha256": "49dbf90ec56d56b8339410698e5bb08389252db4d81ef4ac730c9a1a421c55e8",
        "end_else_count": 8,
        "end_else_sha256": "68a9bd45f6d1cabda51c06e222a1857f2ce7b2322330fa7a66bf3ccda6eb8b6a",
        "effect_indexes": [420, 436, 438, 440, 442],
        "template_literal_index": 425,
        "forced_true_ifs": [],
        "expected_reaching_definitions": {
            "Pool.save": {"local": "$l1", "read": 419, "definitions": [89]},
            "PoolTemplate.create": {"local": "$l1", "read": 435, "definitions": [428]},
            "Token[token0].save": {"local": "$l2", "read": 437, "definitions": [95, 110]},
            "Token[token1].save": {"local": "$l3", "read": 439, "definitions": [101, 184]},
            "Factory.save": {"local": "$l4", "read": 441, "definitions": [13, 18]},
        },
    },
    "modern": {
        "line_count": 2022,
        "controls": MODERN_CONTROLS,
        "branches": [
            (108, "br $L5"),
            (117, "br_if $B0"),
            (135, "br_if $B0"),
            (141, "br $L7"),
            (1403, "br $L26"),
            (1452, "br $L29"),
        ],
        "returns": [147, 725, 1058],
        "unreachable": [36, 407, 437, 464, 480, 1345, 1397, 1897, 1927, 1984, 2014],
        "select": [1371, 1434],
        "call_indirect": [],
        "write_count": 206,
        "write_map_sha256": "f5cb6b4bda25050578b66d4970f6f536ba9add32bacf9334fc5e7e3719eae400",
        "memory_store_count": 183,
        "memory_store_sha256": "fb98debaac81b614ce5717f626b4fe7a94d944cacf29cb26de6d1a763feab49f",
        "call_count": 312,
        "call_sites_sha256": "27cf324034dcdf9c502d61405f92e5e4d14cd308a5e68ebec9eae9ab629bb0d4",
        "end_else_count": 43,
        "end_else_sha256": "60aa26fc51565c2285a87e2c60871b5c01e5493ca805db4f31ef2b37e48acca9",
        "effect_indexes": [1933, 1968, 1970, 1972, 2020],
        "template_literal_index": 1966,
        "forced_true_ifs": [1900, 1987],
        "expected_reaching_definitions": {
            "Pool.save": {"local": "$l6", "read": 1932, "definitions": [522]},
            "Pool.save.id": {"local": "$l1", "read": 1930, "definitions": [1889]},
            "PoolTemplate.create": {"local": "$l1", "read": 1967, "definitions": [1956]},
            "Token[token0].save": {"local": "$l3", "read": 1969, "definitions": [558, 600]},
            "Token[token1].save": {"local": "$l5", "read": 1971, "definitions": [578, 933]},
            "Factory.save": {"local": "$l4", "read": 2019, "definitions": [152, 159]},
            "Factory.save.id": {"local": "$p0", "read": 2017, "definitions": [1976]},
        },
    },
}


EXPECTED_ARTIFACTS: dict[str, dict[str, Any]] = {
    "QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV": {
        "profile_id": "legacy-mainnet-qmrv",
        "generation": "legacy",
        "wasm_sha256": "c90c4b86b184d8ffed606f3264d6f3b921421ef7dce2cb35484dd7faaf452cd4",
        "wat_sha256": "4263d51999d58769c06bef6da1aed4c24c1c846f4b0aaed9142bf3bd912ecf9b",
        "handler_sha256": "e28b09377fd2e7fa10dfa0a7afaccd7f120b35d4b9be5f4be6a5c6c819a41f2c",
        "handler_start": 4087,
        "factory_id": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "effect_suffix_sha256": "551eac873df42d04fa48227ab9c921a0917aa2e88c922333d606ae6e43bd9233",
        "helper_sha256": {
            "Pool": "d9e40b5591d57db0db268e836ba92ca92370a47bbc18705d416f41329dfe7323",
            "Token": "58cc0df17c1b17349b9cc5700352f2cf6033563223a207958de4571d4d654fe1",
            "Factory": "812fba7f76cb220015fc832e7f745b2ae31e592d9bf30f2431d4ce306fb2ad9f",
        },
        "reachable_function_count": 103,
        "reachable_body_bindings_sha256": "c7296eae5fd3e6d462ef9a1c00c6eff2af2f0b780ea56b94c165a987ae0f3d88",
    },
    "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj": {
        "profile_id": "legacy-base-root",
        "generation": "legacy",
        "wasm_sha256": "0855ce1d5260cd8395628dfac2e18db063909168c58e7d5de118612fee9f9a4e",
        "wat_sha256": "c2e7425784b498481ee8a822be18b59edd7aa6dd27712d8d093696cf0b8b1684",
        "handler_sha256": "8c2c0b729892664f7f57430de9a933ec594899ce14d17a70ad0eee8b28b1c006",
        "handler_start": 4000,
        "factory_id": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "effect_suffix_sha256": "deb707003e724038e5a19323f32d6de270404c0617e8ba2548e89d1869925b51",
        "helper_sha256": {
            "Pool": "c718f4d0f930b733fbf3212321702fa2364c52c117c15c21efed55ec9468044d",
            "Token": "a9e18df79cfc8e8874c6b50e38409c70960f071456ebb5ad390789bf6e201aa7",
            "Factory": "8295b2edb3a01487e36682684eb1eba70322d5d899d1bd7ea535f61f27bef769",
        },
        "reachable_function_count": 101,
        "reachable_body_bindings_sha256": "1cdcdf861ec9dfaf3373ebf04a48882e8a71dbdea6b3b9daf9fe870d3d73a4c4",
    },
    "QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr": {
        "profile_id": "legacy-mainnet-root",
        "generation": "legacy",
        "wasm_sha256": "ab7c84297665ab608ce3c6b8cc71f1c584ae7f2a94ebe674993b069d6b8b5c98",
        "wat_sha256": "1fbcd7b7305dd0e0eb2e9de2e64ecb023e9aa5abe29f7562be4dad72bf561f4d",
        "handler_sha256": "266f6faad4b727316ecdb49a8fd0994fb9f33a0d007dad32c6308a6305529417",
        "handler_start": 4087,
        "factory_id": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "effect_suffix_sha256": "40715084bfe0336b5c9f4c9e02b92c77aca2c2773ea2cd774abbe3dede74e6bf",
        "helper_sha256": {
            "Pool": "1c51965d0530b2abf946b398e383aae4fe60b575270b91b7ff815789c49bd4a1",
            "Token": "aa8fe896abbf447b77b79dd01146546a07a6b1e1cbed3e4e9f22e02a8129c022",
            "Factory": "9c64309e133c66671393d5e1f915b3e2b441e06626ec336fae7deda7007c5364",
        },
        "reachable_function_count": 103,
        "reachable_body_bindings_sha256": "3ae22ab5bc71f14befb82a144d54d0e45c7b001f4d84ea690048fdea69c59f29",
    },
    "QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr": {
        "profile_id": "modern-base",
        "generation": "modern",
        "wasm_sha256": "296eb1ad59dca0ef5000e7e48971cb4c39ce8a3d8cfeb7541f6e8b924d049694",
        "wat_sha256": "ea8185d6d94ff68dbb041684f29d23d528c6784a3396542657f9708d73d70972",
        "handler_sha256": "485b7aab032b388184d0fe5535d40cd80176f0bc5cfd2682676824eff3f98dc8",
        "handler_start": 4482,
        "factory_id": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "effect_suffix_sha256": "2c84db80958a7ed4556198980487cf67486b940e310aa66c599849ec4c8ea41d",
        "helper_sha256": {"Token": "2d97dc677c65092502aeda69100d6373450d45dbdff809a178a4188cbafc6905"},
        "reachable_function_count": 56,
        "reachable_body_bindings_sha256": "1f256219acf2667e6f51d25dac435e1f33af4d2f5570cdfd7c12fc2ce7925fa0",
        "display_data_sha256": "74c5cf848280460ef1cf31b48612d39c8df85ababf82d40e1573193dfc7c819b",
    },
    "QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb": {
        "profile_id": "modern-mainnet",
        "generation": "modern",
        "wasm_sha256": "9a33e52667ce538278f9ab88ac9818f5442021e8a2ddb22fd5994a9643148887",
        "wat_sha256": "84064b99fa818216ac5090dcf2a8f6b16acfe5f93edcc9819d0cb88d84526449",
        "handler_sha256": "245ffe7ad61554106f9a5c748bb2cd629287a4fb0ecffa72c956d94915272dd5",
        "handler_start": 4617,
        "factory_id": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "effect_suffix_sha256": "00fdcfa79a387a568c21b254b630072c45187545fa0d24aa23d7f3b6bcf3c079",
        "helper_sha256": {"Token": "86f2bbb199d22ef54b7a5de58551b2c4bcc4bf6448b4a18d852de878f012931b"},
        "reachable_function_count": 57,
        "reachable_body_bindings_sha256": "3832b4a8cefe2dbe6dad6603f102f5a2bec89cfc4a9651a747a6b7b610a3e2e6",
        "display_data_sha256": "2b1872bac3eaa024ca504f0a0f38ff5edaf1440929bcecb1bf66d3da0c1caa73",
    },
    "QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL": {
        "profile_id": "legacy-mainnet-stable",
        "generation": "legacy",
        "wasm_sha256": "1bde476d96fd4ba7720246a351c4de0f129693d838f9a39a660097c85d1edead",
        "wat_sha256": "d44ed8c0bbd1bdf62635871b475fbe1a22c8d3a4b88e5d77e6827e3e61b70f81",
        "handler_sha256": "cfaa881acf0c9a45f3f71af203c0587f86bad622083db6c15c2c4f77a8274a09",
        "handler_start": 4087,
        "factory_id": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "effect_suffix_sha256": "cd8bdbd841717cdb918f1ee6e7ac2a0e60da6a31d0c5c725f47cc3dcb77a8c96",
        "helper_sha256": {
            "Pool": "04167d2b1470287c00c69402ae80ca14018c2c407f41f875e52ec3a2621e0c05",
            "Token": "0bf2d1b35cfe30aff749597dcd39291bc2cbdc9907581b315078149b166d073c",
            "Factory": "387eaad9ffd731486ec9b86b7daaae4cfd50d76c3788ba512d27a063d8854f69",
        },
        "reachable_function_count": 103,
        "reachable_body_bindings_sha256": "55f3f553c2cc35606ffd8b725291c4e28d832c8d44f865f69729d2f6df2ea1c1",
    },
}


TRUE_FLAGS = {
    "exact_v2_and_modern_guard_contract_bytes_pinned",
    "exact_six_factory_wasm_wat_and_handlers_pinned",
    "complete_handler_control_local_call_and_heap_write_inventories_bound",
    "all_six_factory_normal_return_effect_order_and_arguments_proven",
    "all_six_factory_effect_same_path_proven",
    "all_six_factory_effect_argument_identity_proven",
    "all_six_factory_template_identity_and_pool_argument_proven",
    "exactly_six_factory_effect_paths_closed",
    "cumulative_factory_paths_closed_is_12_of_18",
    "cumulative_factory_paths_residual_is_6_of_18",
}


FALSE_FLAGS = {
    "graph_handler_rollback_proven_by_retained_wat",
    "factory_total_supply_success_failure_dataflow_proven",
    "factory_complete_static_handler_contract_proven",
    "factory_all_initialized_field_values_proven",
    "factory_handler_semantics_complete",
    "full_factory_entity_histories_complete",
    "runtime_population_complete",
    "writer_runtime_consumes_this_contract",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "post_fatal_execution_modeled",
    "graph_execution_trace_complete",
    "target_runtime_identity_bound",
    "boundary_state_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "backfill_ready",
    "production_ready",
}


CONTROL_RE = re.compile(r"^(block|loop|if)(?: (\$\S+))?(?: \(result ([if]\d+)\))?$")
LOCAL_WRITE_RE = re.compile(r"^local\.(set|tee) (\$\S+)$")
LOCAL_READ_RE = re.compile(r"^local\.get (\$\S+)$")
MEMORY_STORE_RE = re.compile(r"^(?:i32|i64|f32|f64)\.store(?:8|16|32)?(?:\s|$)")
BRANCH_RE = re.compile(r"^(br|br_if) (\$\S+)$")


def observed_instruction_inventory(handler: Any) -> dict[str, Any]:
    """Return the complete handler-local syntax inventory without trusting pins."""
    lines = [normalized(line) for line in handler.lines]
    writes: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        match = LOCAL_WRITE_RE.fullmatch(line)
        if match:
            writes.setdefault(match.group(2), []).append(index)
    memory_stores = [
        (index, line.split()[0])
        for index, line in enumerate(lines)
        if MEMORY_STORE_RE.match(line)
    ]
    calls = [
        (index, name)
        for index, line in enumerate(handler.lines)
        if (name := call_name(line)) is not None
    ]
    controls = [
        (index, match.group(1), match.group(2))
        for index, line in enumerate(lines)
        if (match := CONTROL_RE.fullmatch(line)) is not None
    ]
    branches = [
        (index, line)
        for index, line in enumerate(lines)
        if BRANCH_RE.fullmatch(line)
    ]
    end_else = [(index, line) for index, line in enumerate(lines) if line in {"else", "end"}]
    exits = {
        "returns": [index for index, line in enumerate(lines) if line == "return"],
        "unreachable": [index for index, line in enumerate(lines) if line == "unreachable"],
        "select": [index for index, line in enumerate(lines) if line == "select"],
        "call_indirect": [index for index, line in enumerate(lines) if line.startswith("call_indirect")],
    }
    return {
        "line_count": len(lines),
        "controls": controls,
        "branches": branches,
        **exits,
        "write_count": sum(map(len, writes.values())),
        "write_map_sha256": canonical_sha256(writes),
        "memory_store_count": len(memory_stores),
        "memory_store_sha256": canonical_sha256(memory_stores),
        "call_count": len(calls),
        "call_sites_sha256": canonical_sha256(calls),
        "end_else_count": len(end_else),
        "end_else_sha256": canonical_sha256(end_else),
    }


def instruction_inventory(handler: Any, generation: str) -> dict[str, Any]:
    expected = GENERATION_INVENTORY[generation]
    observed = observed_instruction_inventory(handler)
    require(observed["line_count"] == expected["line_count"], f"{generation} handler line-count drift")
    require(observed["controls"] == expected["controls"], f"{generation} structured-control start inventory drift")
    require(observed["branches"] == expected["branches"], f"{generation} branch inventory drift")
    for key in ("returns", "unreachable", "select", "call_indirect"):
        require(observed[key] == expected[key], f"{generation} {key} inventory drift")
    require(observed["write_count"] == expected["write_count"], f"{generation} local write count drift")
    require(observed["write_map_sha256"] == expected["write_map_sha256"], f"{generation} local SSA inventory drift")
    require(observed["memory_store_count"] == expected["memory_store_count"], f"{generation} heap-store count drift")
    require(observed["memory_store_sha256"] == expected["memory_store_sha256"], f"{generation} heap-store inventory drift")
    require(observed["call_count"] == expected["call_count"], f"{generation} call count drift")
    require(observed["call_sites_sha256"] == expected["call_sites_sha256"], f"{generation} call-site inventory drift")
    require(observed["end_else_count"] == expected["end_else_count"], f"{generation} else/end count drift")
    require(observed["end_else_sha256"] == expected["end_else_sha256"], f"{generation} else/end inventory drift")
    return {
        "handler_instruction_count": observed["line_count"],
        "structured_control_start_count": len(observed["controls"]),
        "structured_control_starts_sha256": canonical_sha256(observed["controls"]),
        "branch_site_count": len(observed["branches"]),
        "branch_sites_sha256": canonical_sha256(observed["branches"]),
        "normal_return_sites": observed["returns"],
        "explicit_unreachable_sites": observed["unreachable"],
        "select_sites": observed["select"],
        "handler_call_indirect_sites": observed["call_indirect"],
        "local_write_count": expected["write_count"],
        "local_write_inventory_sha256": expected["write_map_sha256"],
        "direct_heap_store_count": expected["memory_store_count"],
        "direct_heap_store_inventory_sha256": expected["memory_store_sha256"],
        "direct_call_count": expected["call_count"],
        "direct_call_inventory_sha256": expected["call_sites_sha256"],
        "all_handler_local_control_local_call_and_heap_write_sites_accounted": True,
    }


def parse_structured_control(lines: list[str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    frames: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = CONTROL_RE.fullmatch(line)
        if match is not None:
            kind, label, result_type = match.groups()
            require(label is not None, f"unnamed structured control at WAT line {index}")
            frame = {
                "kind": kind,
                "label": label,
                "start": index,
                "else": None,
                "end": None,
                "result_type": result_type,
                "parent": stack[-1]["label"] if stack else None,
            }
            frames.append(frame)
            stack.append(frame)
        elif line == "else":
            require(stack and stack[-1]["kind"] == "if", f"orphan else at WAT line {index}")
            require(stack[-1]["else"] is None, f"duplicate else at WAT line {index}")
            stack[-1]["else"] = index
        elif line in {"end", "end)"}:
            require(stack, f"orphan end at WAT line {index}")
            stack.pop()["end"] = index
    require(not stack, "structured-control stack does not close")
    require(all(frame["end"] is not None for frame in frames), "unterminated structured control")
    by_label = {frame["label"]: frame for frame in frames}
    require(len(by_label) == len(frames), "duplicate structured-control label")
    return frames, by_label


NORMAL_EXIT = -1
TRAP_EXIT = -2


def build_cfg(
    lines: list[str],
    frames: list[dict[str, Any]],
    by_label: dict[str, dict[str, Any]],
    forced_true_ifs: Iterable[int] = (),
) -> dict[int, tuple[int, ...]]:
    frame_by_start = {frame["start"]: frame for frame in frames}
    frame_by_else = {frame["else"]: frame for frame in frames if frame["else"] is not None}
    forced = set(forced_true_ifs)
    cfg: dict[int, tuple[int, ...]] = {}
    last = len(lines) - 1
    for index, line in enumerate(lines):
        next_node = NORMAL_EXIT if index == last else index + 1
        if line == "return":
            successors = (NORMAL_EXIT,)
        elif line == "unreachable":
            successors = (TRAP_EXIT,)
        elif line.startswith("br_table"):
            raise VerificationError(f"unmodeled br_table at WAT line {index}")
        elif (branch := BRANCH_RE.fullmatch(line)) is not None:
            kind, label = branch.groups()
            require(label in by_label, f"unknown branch label {label} at WAT line {index}")
            target_frame = by_label[label]
            target = target_frame["start"] + 1 if target_frame["kind"] == "loop" else target_frame["end"] + 1
            successors = (target,) if kind == "br" else (next_node, target)
        elif index in frame_by_start and frame_by_start[index]["kind"] == "if":
            frame = frame_by_start[index]
            false_target = frame["else"] + 1 if frame["else"] is not None else frame["end"] + 1
            successors = (index + 1,) if index in forced else (index + 1, false_target)
        elif index in frame_by_else:
            successors = (frame_by_else[index]["end"] + 1,)
        elif line.endswith(")") and index == last:
            successors = (NORMAL_EXIT,)
        else:
            successors = (next_node,)
        cfg[index] = tuple(dict.fromkeys(successors))
    return cfg


def local_names(handler: Any) -> list[str]:
    header = " ".join(normalized(line) for line in handler.lines[:2])
    return sorted(set(re.findall(r"\$(?:p|l)\d+", header)))


def reaching_definitions(
    handler: Any,
    cfg: dict[int, tuple[int, ...]],
    start: int,
) -> list[dict[str, frozenset[int]] | None]:
    lines = [normalized(line) for line in handler.lines]
    names = local_names(handler)
    entry = {name: frozenset({-1}) for name in names}
    states: list[dict[str, frozenset[int]] | None] = [None for _ in lines]
    states[start] = entry
    queue: deque[int] = deque([start])
    while queue:
        index = queue.popleft()
        incoming = states[index]
        require(incoming is not None, "reaching-definition worklist corruption")
        outgoing = dict(incoming)
        if (write := LOCAL_WRITE_RE.fullmatch(lines[index])) is not None:
            outgoing[write.group(2)] = frozenset({index})
        for successor in cfg[index]:
            if successor < 0:
                continue
            current = states[successor]
            if current is None:
                merged = dict(outgoing)
            else:
                merged = {
                    name: current[name] | outgoing[name]
                    for name in names
                }
            if current != merged:
                states[successor] = merged
                queue.append(successor)
    return states


def verify_reaching_definitions(
    handler: Any,
    states: list[dict[str, frozenset[int]] | None],
    generation: str,
) -> list[dict[str, Any]]:
    lines = [normalized(line) for line in handler.lines]
    output: list[dict[str, Any]] = []
    for identity, expected in GENERATION_INVENTORY[generation]["expected_reaching_definitions"].items():
        read = expected["read"]
        local = expected["local"]
        require(lines[read] == f"local.get {local}", f"{generation} {identity} argument read drift")
        state = states[read]
        require(state is not None, f"{generation} {identity} argument became unreachable")
        definitions = sorted(state[local])
        require(definitions == expected["definitions"], f"{generation} {identity} mutable-local dataflow drift")
        output.append(
            {
                "identity": identity,
                "argument_local": local,
                "argument_read_wat_line": read,
                "reaching_definition_wat_lines": definitions,
            }
        )
    return output


def require_call_suffix(handler: Any, index: int, suffix: str, label: str) -> str:
    target = call_name(handler.lines[index]) or ""
    require(target.endswith(suffix), f"{label} call target drift")
    return target


def reaching_definition_map(definitions: list[dict[str, Any]]) -> dict[str, list[int]]:
    return {
        item["identity"]: item["reaching_definition_wat_lines"]
        for item in definitions
    }


def prove_legacy_argument_definition_identities(
    context: dict[str, Any],
    definitions: list[dict[str, Any]],
    constructor_certificate: dict[str, Any],
) -> dict[str, Any]:
    """Bind every legacy save-receiver phi alternative to its immutable ID."""
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    definition_map = reaching_definition_map(definitions)
    require(
        definition_map
        == {
            "Pool.save": [89],
            "PoolTemplate.create": [428],
            "Token[token0].save": [95, 110],
            "Token[token1].save": [101, 184],
            "Factory.save": [13, 18],
        },
        "legacy receiver reaching-definition alternatives drift",
    )

    def event_definition(
        identity: str,
        field: str,
        start: int,
        definition: int,
        assignment: str,
        local: str,
        terminal_suffix: str,
        kind: str,
    ) -> dict[str, Any]:
        require(definition == start + 5, f"legacy {identity} definition window drift")
        require(lines[start] == "local.get $p0", f"legacy {identity} event receiver drift")
        require_call_suffix(handler, start + 1, "PoolCreated__Params#constructor", f"legacy {identity} event wrapper")
        require_call_suffix(handler, start + 2, f"PoolCreated__Params#get:{field}", f"legacy {identity} event field")
        require_call_suffix(handler, start + 3, "typeConversion.bytesToHex", f"legacy {identity} ID conversion")
        terminal = require_call_suffix(handler, start + 4, terminal_suffix, f"legacy {identity} entity source")
        require(lines[definition] == f"local.{assignment} {local}", f"legacy {identity} receiver definition drift")
        return {
            "identity": identity,
            "receiver_local": local,
            "reaching_definition_wat_line": definition,
            "definition_kind": kind,
            "immutable_id_source": f"bytesToHex(PoolCreated.event.{field})",
            "terminal_call": terminal,
            "binding_slice_sha256": V2.wat_slice_sha256(handler, start, definition),
        }

    alternatives = [
        event_definition("Pool.save", "pool", 84, 89, "set", "$l1", "schema/Factory#constructor", "constructor"),
        event_definition("Token[token0].save", "token0", 90, 95, "set", "$l2", "schema/Token.load", "store.get"),
        event_definition("Token[token0].save", "token0", 105, 110, "tee", "$l2", "schema/Factory#constructor", "constructor"),
        event_definition("Token[token1].save", "token1", 96, 101, "set", "$l3", "schema/Token.load", "store.get"),
        event_definition("Token[token1].save", "token1", 179, 184, "tee", "$l3", "schema/Factory#constructor", "constructor"),
    ]

    expected_factory_id = context["expected"]["factory_id"]
    require(V2.decoded_wat_constant(handler.lines[10], context["memory"]) == "Factory", "legacy Factory store.get target drift")
    require(V2.decoded_wat_constant(handler.lines[11], context["memory"]) == expected_factory_id, "legacy Factory store.get ID drift")
    require_call_suffix(handler, 12, "index/store.get", "legacy Factory store.get")
    require(lines[13:16] == ["local.tee $l4", "i32.eqz", "if $I1"], "legacy Factory load/constructor phi drift")
    require(V2.decoded_wat_constant(handler.lines[16], context["memory"]) == expected_factory_id, "legacy Factory constructor ID drift")
    factory_constructor = require_call_suffix(handler, 17, "schema/Factory#constructor", "legacy Factory constructor")
    require(lines[18] == "local.tee $l4", "legacy Factory constructor receiver definition drift")
    alternatives.extend(
        [
            {
                "identity": "Factory.save",
                "receiver_local": "$l4",
                "reaching_definition_wat_line": 13,
                "definition_kind": "store.get",
                "immutable_id_source": expected_factory_id,
                "terminal_call": call_name(handler.lines[12]),
                "binding_slice_sha256": V2.wat_slice_sha256(handler, 10, 13),
            },
            {
                "identity": "Factory.save",
                "receiver_local": "$l4",
                "reaching_definition_wat_line": 18,
                "definition_kind": "constructor",
                "immutable_id_source": expected_factory_id,
                "terminal_call": factory_constructor,
                "binding_slice_sha256": V2.wat_slice_sha256(handler, 16, 18),
            },
        ]
    )
    for alternative in alternatives:
        if alternative["definition_kind"] == "constructor":
            alternative["constructor_body_certificate"] = {
                "function": constructor_certificate["function"],
                "body_sha256": constructor_certificate["body_sha256"],
                "same_input_id_encoded_in_map_value": constructor_certificate["same_input_id_encoded_in_map_value"],
                "same_fresh_receiver_used_for_map_set_and_return": constructor_certificate["same_fresh_receiver_used_for_map_set_and_return"],
                "constructor_id_and_receiver_machine_proven": constructor_certificate["constructor_id_and_receiver_machine_proven"],
            }
    proved = {
        (item["identity"], item["reaching_definition_wat_line"])
        for item in alternatives
    }
    required = {
        (identity, line)
        for identity, lines_ in definition_map.items()
        if identity != "PoolTemplate.create"
        for line in lines_
    }
    require(proved == required, "legacy not every effect receiver definition acquired an identity proof")
    constructor_alternatives = [
        item for item in alternatives if item["definition_kind"] == "constructor"
    ]
    require(
        constructor_alternatives
        and all(
            item["constructor_body_certificate"]["constructor_id_and_receiver_machine_proven"]
            for item in constructor_alternatives
        ),
        "legacy constructor alternative lacks a body-level ID/receiver proof",
    )
    return {
        "receiver_definition_proofs": alternatives,
        "constructor_body_certificate": constructor_certificate,
        "every_constructor_alternative_body_semantics_proven": True,
        "every_alternative_reaching_definition_identity_proven": True,
    }


def prove_modern_argument_definition_identities(
    context: dict[str, Any],
    definitions: list[dict[str, Any]],
    base_identities: dict[str, Any],
    token_constructor_certificate: dict[str, Any],
) -> dict[str, Any]:
    """Bind every modern save receiver and direct-store ID phi alternative."""
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    definition_map = reaching_definition_map(definitions)
    require(
        definition_map
        == {
            "Pool.save": [522],
            "Pool.save.id": [1889],
            "PoolTemplate.create": [1956],
            "Token[token0].save": [558, 600],
            "Token[token1].save": [578, 933],
            "Factory.save": [152, 159],
            "Factory.save.id": [1976],
        },
        "modern receiver reaching-definition alternatives drift",
    )

    alternatives: list[dict[str, Any]] = [
        {
            "identity": "Pool.save",
            "receiver_local": "$l6",
            "reaching_definition_wat_line": 522,
            "definition_kind": "constructor-and-id-field-set",
            "immutable_id_source": "bytesToHex(PoolCreated.event[4])",
            "binding_slice_sha256": base_identities["pool_id_binding_slice_sha256"],
        }
    ]

    def token_definition(
        identity: str,
        event_index: int,
        definition: int,
        local: str,
        kind: str,
    ) -> dict[str, Any]:
        is_store_get = kind == "store.get"
        wrapper_start = definition - (19 if is_store_get else 18)
        wrapper_local = V2.wat_local(handler.lines[wrapper_start + 3], "tee")
        require(wrapper_local is not None, f"modern {identity} {kind} event-wrapper local drift")
        require(
            lines[wrapper_start : wrapper_start + 9]
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
            f"modern {identity} {kind} event-wrapper flow drift",
        )
        cursor = wrapper_start + 9
        if is_store_get:
            require(V2.decoded_wat_constant(handler.lines[cursor], context["memory"]) == "Token", f"modern {identity} store.get target drift")
            cursor += 1
        require(
            lines[cursor : cursor + 4]
            == [
                f"local.get {wrapper_local}",
                "i32.load",
                "i32.load offset=24",
                f"i32.const {event_index}",
            ],
            f"modern {identity} {kind} event-index flow drift",
        )
        require_call_suffix(handler, cursor + 4, "ethereum.EventParam>#__get", f"modern {identity} event getter")
        require(lines[cursor + 5] == "i32.load offset=4", f"modern {identity} event value load drift")
        require_call_suffix(handler, cursor + 6, "ethereum.Value#toAddress", f"modern {identity} address conversion")
        require_call_suffix(handler, cursor + 7, "typeConversion.bytesToHex", f"modern {identity} hex conversion")
        terminal_suffix = "index/store.get" if is_store_get else "schema/Token#constructor"
        terminal = require_call_suffix(handler, cursor + 8, terminal_suffix, f"modern {identity} entity source")
        assignment = "set" if is_store_get else "tee"
        require(lines[definition] == f"local.{assignment} {local}", f"modern {identity} {kind} receiver definition drift")
        require(definition == cursor + 9, f"modern {identity} {kind} definition window drift")
        return {
            "identity": identity,
            "receiver_local": local,
            "reaching_definition_wat_line": definition,
            "definition_kind": kind,
            "immutable_id_source": f"bytesToHex(PoolCreated.event[{event_index}])",
            "terminal_call": terminal,
            "binding_slice_sha256": V2.wat_slice_sha256(handler, wrapper_start, definition),
        }

    alternatives.extend(
        [
            token_definition("Token[token0].save", 0, 558, "$l3", "store.get"),
            token_definition("Token[token0].save", 0, 600, "$l3", "constructor"),
            token_definition("Token[token1].save", 1, 578, "$l5", "store.get"),
            token_definition("Token[token1].save", 1, 933, "$l5", "constructor"),
        ]
    )
    for alternative in alternatives:
        if alternative["definition_kind"] == "constructor":
            alternative["constructor_body_certificate"] = {
                "function": token_constructor_certificate["function"],
                "body_sha256": token_constructor_certificate["body_sha256"],
                "same_input_id_encoded_in_string_value_payload": token_constructor_certificate["same_input_id_encoded_in_string_value_payload"],
                "same_fresh_receiver_used_for_map_set_and_return": token_constructor_certificate["same_fresh_receiver_used_for_map_set_and_return"],
                "constructor_id_and_receiver_machine_proven": token_constructor_certificate["constructor_id_and_receiver_machine_proven"],
            }
        elif alternative["definition_kind"] == "constructor-and-id-field-set":
            alternative["inline_constructor_id_and_receiver_machine_proven"] = True

    expected_factory_id = context["expected"]["factory_id"]
    require(V2.decoded_wat_constant(handler.lines[149], context["memory"]) == "Factory", "modern Factory store.get target drift")
    require(V2.decoded_wat_constant(handler.lines[150], context["memory"]) == expected_factory_id, "modern Factory store.get ID drift")
    require_call_suffix(handler, 151, "index/store.get", "modern Factory store.get")
    require(lines[152:155] == ["local.tee $l4", "i32.eqz", "if $I10"], "modern Factory load/constructor phi drift")
    require(
        lines[155:160]
        == [
            "i32.const 4",
            "i32.const 25",
            "call $~lib/rt/stub/__new",
            "call $~lib/@graphprotocol/graph-ts/common/collections/Entity#constructor",
            "local.set $l4",
        ],
        "modern Factory constructor receiver drift",
    )
    factory_pointer = re.fullmatch(r"i32\.const (\d+)", lines[150])
    require(factory_pointer is not None, "modern Factory literal pointer drift")
    require(
        lines[160:173]
        == [
            "i32.const 16",
            "i32.const 27",
            "call $~lib/rt/stub/__new",
            "local.tee $l1",
            "i32.const 0",
            "i32.store",
            "local.get $l1",
            f"i64.const {factory_pointer.group(1)}",
            "i64.store offset=8",
            "local.get $l4",
            lines[170],
            "local.get $l1",
            lines[172],
        ]
        and V2.decoded_wat_constant(handler.lines[170], context["memory"]) == "id"
        and (call_name(handler.lines[172]) or "").endswith("TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set"),
        "modern Factory constructor ID field flow drift",
    )
    alternatives.extend(
        [
            {
                "identity": "Factory.save",
                "receiver_local": "$l4",
                "reaching_definition_wat_line": 152,
                "definition_kind": "store.get",
                "immutable_id_source": expected_factory_id,
                "terminal_call": call_name(handler.lines[151]),
                "binding_slice_sha256": V2.wat_slice_sha256(handler, 149, 152),
            },
            {
                "identity": "Factory.save",
                "receiver_local": "$l4",
                "reaching_definition_wat_line": 159,
                "definition_kind": "constructor-and-id-field-set",
                "immutable_id_source": expected_factory_id,
                "terminal_call": call_name(handler.lines[158]),
                "binding_slice_sha256": V2.wat_slice_sha256(handler, 155, 172),
                "inline_constructor_id_and_receiver_machine_proven": True,
            },
        ]
    )
    proved = {
        (item["identity"], item["reaching_definition_wat_line"])
        for item in alternatives
    }
    required = {
        (identity, line)
        for identity, lines_ in definition_map.items()
        if identity in {"Pool.save", "Token[token0].save", "Token[token1].save", "Factory.save"}
        for line in lines_
    }
    require(proved == required, "modern not every effect receiver definition acquired an identity proof")
    constructor_alternatives = [
        item for item in alternatives if "constructor" in item["definition_kind"]
    ]
    require(
        constructor_alternatives
        and all(
            item.get("inline_constructor_id_and_receiver_machine_proven")
            or item.get("constructor_body_certificate", {}).get("constructor_id_and_receiver_machine_proven")
            for item in constructor_alternatives
        ),
        "modern constructor alternative lacks a body-level or inline ID/receiver proof",
    )
    return {
        "receiver_definition_proofs": alternatives,
        "token_constructor_body_certificate": token_constructor_certificate,
        "every_constructor_alternative_body_or_inline_semantics_proven": True,
        "direct_store_id_reaching_definitions": {
            "Pool.save.id": definition_map["Pool.save.id"],
            "Factory.save.id": definition_map["Factory.save.id"],
        },
        "every_alternative_reaching_definition_identity_proven": True,
    }


def direct_store_arguments(context: dict[str, Any], call_index: int) -> dict[str, str]:
    handler = context["handler"]
    require(call_index >= 4, "direct store argument window underflow")
    target = V2.decoded_wat_constant(handler.lines[call_index - 4], context["memory"])
    id_local = V2.wat_local(handler.lines[call_index - 3])
    entity_local = V2.wat_local(handler.lines[call_index - 1])
    require(target is not None, f"dynamic direct store target at WAT line {call_index}")
    require(id_local is not None and entity_local is not None, f"direct store local argument drift at {call_index}")
    require((call_name(handler.lines[call_index - 2]) or "").endswith("Value#toString"), f"direct store ID conversion drift at {call_index}")
    return {"target": target, "id_value_local": id_local, "entity_local": entity_local}


def prove_present_id_branch(
    context: dict[str, Any],
    entity: str,
    entity_local: str,
    id_local: str,
    lookup_start: int,
    missing_if: int,
    present_if: int,
    wrong_type_if: int,
    store_index: int,
) -> dict[str, Any]:
    lines = [normalized(line) for line in context["handler"].lines]
    frames, _ = parse_structured_control(lines)
    frame_at = {frame["start"]: frame for frame in frames}
    require(
        lines[lookup_start : lookup_start + 5]
        == [
            f"local.get {entity_local}",
            lines[lookup_start + 1],
            lines[lookup_start + 2],
            f"local.tee {id_local}",
            "i32.eqz",
        ],
        f"{entity} ID lookup operand flow drift",
    )
    require(V2.decoded_wat_constant(context["handler"].lines[lookup_start + 1], context["memory"]) == "id", f"{entity} ID key drift")
    require((call_name(context["handler"].lines[lookup_start + 2]) or "").endswith("TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#get"), f"{entity} ID getter drift")
    require(frame_at[missing_if]["else"] is None, f"{entity} missing-ID branch gained else")
    missing_body = lines[missing_if + 1 : frame_at[missing_if]["end"]]
    require(missing_body[-1] == "unreachable" and any((call_name(context["handler"].lines[i]) or "").endswith("abort") for i in range(missing_if + 1, frame_at[missing_if]["end"])), f"{entity} missing-ID path no longer traps")
    require(
        present_if == frame_at[missing_if]["end"] + 2
        and lines[frame_at[missing_if]["end"] + 1] == f"local.get {id_local}"
        and lines[present_if].startswith("if $"),
        f"{entity} present-ID condition acquired a transform or non-SSA operand",
    )
    require(frame_at[present_if]["else"] is None and frame_at[present_if]["end"] >= store_index, f"{entity} present-ID store branch drift")
    require(frame_at[wrong_type_if]["else"] is None, f"{entity} wrong-type branch gained else")
    wrong_body = lines[wrong_type_if + 1 : frame_at[wrong_type_if]["end"]]
    require(wrong_body[-1] == "unreachable", f"{entity} wrong-type path no longer traps")
    require(store_index < frame_at[present_if]["end"], f"{entity} store escaped present branch")
    return {
        "entity": entity,
        "entity_local": entity_local,
        "id_value_local": id_local,
        "id_lookup_wat_line": lookup_start + 2,
        "missing_id_if_wat_line": missing_if,
        "present_id_if_wat_line": present_if,
        "wrong_type_if_wat_line": wrong_type_if,
        "store_wat_line": store_index,
        "missing_and_wrong_type_paths_trap": True,
        "same_ssa_id_value_forces_present_branch": True,
    }


def resolve_suffix(functions: dict[str, Any], suffix: str, label: str) -> Any:
    matches = [function for name, function in functions.items() if name.replace("generated/schema/", "src/types/schema/").endswith(suffix)]
    require(len(matches) == 1, f"{label} helper resolution drift")
    return matches[0]


def prove_save_helper(
    context: dict[str, Any],
    entity: str,
    expected_sha256: str,
) -> dict[str, Any]:
    function = resolve_suffix(context["functions"], f"schema/{entity}#save", entity)
    lines = [normalized(line) for line in function.lines]
    generation = context["expected"]["generation"]
    frames, _ = parse_structured_control(lines)
    require(
        not any(frame["else"] is not None for frame in frames),
        f"{generation} {entity} save helper acquired an alternative branch",
    )
    require(
        not any(line == "return" for line in lines),
        f"{generation} {entity} save helper acquired an early normal return",
    )
    require(
        not any(BRANCH_RE.fullmatch(line) or line.startswith("br_table") for line in lines),
        f"{generation} {entity} save helper acquired a branch bypass",
    )
    require(
        not any(line == "select" or line.startswith("call_indirect") for line in lines),
        f"{generation} {entity} save helper acquired dynamic control",
    )
    helper_store_calls = [
        index
        for index, raw_line in enumerate(function.lines)
        if call_name(raw_line) == WRITER.STORE_SET_CALL
    ]
    require(
        len(helper_store_calls) == 1,
        f"{generation} {entity} save helper persistent-store count drift",
    )
    if generation == "legacy":
        require(len(lines) == 32, f"legacy {entity} save length drift")
        require(lines[2] == "local.get $p0" and lines[5] == "local.tee $l1", f"legacy {entity} receiver/ID binding drift")
        require(lines[6:8] == ["i32.eqz", "if $I0"], f"legacy {entity} missing-ID guard drift")
        require(lines[13:18] == ["unreachable", "end", "local.get $l1", "i32.load", "if $I1"], f"legacy {entity} type guard drift")
        require(lines[25:31] == ["unreachable", "end", lines[27], "local.get $l1", lines[29], "local.get $p0"], f"legacy {entity} normal store path drift")
        id_key = V2.decoded_wat_constant(function.lines[3], context["memory"])
        target = V2.decoded_wat_constant(function.lines[27], context["memory"])
        store_index = 31
        trap_sites = [13, 25]
    else:
        require(entity == "Token", "modern Pool and Factory stores are inlined")
        require(len(lines) == 51, "modern Token save length drift")
        require(lines[2] == "local.get $p0" and lines[5] == "local.tee $l1", "modern Token receiver/ID binding drift")
        require(lines[6:8] == ["i32.eqz", "if $I0"], "modern Token missing-ID guard drift")
        require(lines[13:20] == ["unreachable", "end", "local.get $l1", "if $I1", "local.get $l1", "i32.load", "if $I2"], "modern Token required-ID/type guard drift")
        require(lines[43:50] == ["unreachable", "end", lines[45], "local.get $l1", lines[47], "local.get $p0", lines[49]], "modern Token normal store path drift")
        id_key = V2.decoded_wat_constant(function.lines[3], context["memory"])
        target = V2.decoded_wat_constant(function.lines[45], context["memory"])
        store_index = 49
        trap_sites = [13, 43]
    require(id_key == "id", f"{generation} {entity} save ID key drift")
    require(target == entity, f"{generation} {entity} save target drift")
    require((call_name(function.lines[store_index - 2]) or "").endswith("Value#toString"), f"{generation} {entity} save ID conversion drift")
    require(call_name(function.lines[store_index]) == WRITER.STORE_SET_CALL, f"{generation} {entity} save call target drift")
    body_sha256 = hashlib.sha256(function.payload).hexdigest()
    require(body_sha256 == expected_sha256, f"{generation} {entity} save helper digest drift")
    return {
        "entity": entity,
        "function": function.name,
        "body_sha256": body_sha256,
        "instruction_count": len(lines),
        "receiver_parameter": "$p0",
        "required_id_key": id_key,
        "target": target,
        "trap_sites": trap_sites,
        "store_site": store_index,
        "normal_return_requires_exactly_one_store": True,
        "trap_before_store_is_allowed": True,
        "same_receiver_used_for_id_lookup_and_store": True,
    }


def prove_legacy_entity_constructor(context: dict[str, Any]) -> dict[str, Any]:
    """Prove the shared legacy constructor returns the entity carrying `$p0` as `id`."""
    function = resolve_suffix(context["functions"], "schema/Factory#constructor", "legacy entity constructor")
    lines = [normalized(line) for line in function.lines]
    require(len(lines) == 11, "legacy entity constructor instruction count drift")
    require(
        lines[0].startswith("(func ")
        and "(param $p0 i32)" in lines[0]
        and "(result i32)" in lines[0]
        and lines[1] == "(local $l1 i32)",
        "legacy entity constructor signature drift",
    )
    require(
        lines[2] == "i32.const 4"
        and (call_name(function.lines[3]) or "").endswith("allocator/arena/__memory_allocate")
        and (call_name(function.lines[4]) or "").endswith("Entity#constructor")
        and lines[5] == "local.tee $l1",
        "legacy entity constructor fresh receiver flow drift",
    )
    require(
        V2.decoded_wat_constant(function.lines[6], context["memory"]) == "id",
        "legacy entity constructor ID key drift",
    )
    require(lines[7] == "local.get $p0", "legacy entity constructor ID input drift")
    require_call_suffix(function, 8, "Value.fromString", "legacy entity constructor ID value")
    require_call_suffix(
        function,
        9,
        "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>#set",
        "legacy entity constructor ID map.set",
    )
    require(lines[10] == "local.get $l1)", "legacy entity constructor did not return the same receiver")
    body_sha256 = hashlib.sha256(function.payload).hexdigest()
    return {
        "function": function.name,
        "body_sha256": body_sha256,
        "input_id_parameter": "$p0",
        "fresh_entity_local": "$l1",
        "id_key": "id",
        "id_value_constructor": call_name(function.lines[8]),
        "id_map_set_call": call_name(function.lines[9]),
        "returned_entity_local": "$l1",
        "same_input_id_encoded_in_map_value": True,
        "same_fresh_receiver_used_for_map_set_and_return": True,
        "constructor_id_and_receiver_machine_proven": True,
    }


def prove_modern_token_constructor(context: dict[str, Any]) -> dict[str, Any]:
    """Prove the modern Token constructor embeds `$p0` in the returned entity's `id`."""
    function = resolve_suffix(context["functions"], "schema/Token#constructor", "modern Token constructor")
    lines = [normalized(line) for line in function.lines]
    require(len(lines) == 25, "modern Token constructor instruction count drift")
    require(
        lines[0].startswith("(func ")
        and "(param $p0 i32)" in lines[0]
        and "(result i32)" in lines[0]
        and lines[1] == "(local $l1 i32) (local $l2 i64)",
        "modern Token constructor signature drift",
    )
    require(
        lines[2:7]
        == [
            "i32.const 4",
            "i32.const 37",
            "call $~lib/rt/stub/__new",
            "call $~lib/@graphprotocol/graph-ts/common/collections/Entity#constructor",
            "local.tee $l1",
        ],
        "modern Token constructor fresh receiver flow drift",
    )
    require(
        V2.decoded_wat_constant(function.lines[7], context["memory"]) == "id",
        "modern Token constructor ID key drift",
    )
    require(
        lines[8:23]
        == [
            "block $B0 (result i32)",
            "local.get $p0",
            "i64.extend_i32_u",
            "local.set $l2",
            "i32.const 16",
            "i32.const 27",
            "call $~lib/rt/stub/__new",
            "local.tee $p0",
            "i32.const 0",
            "i32.store",
            "local.get $p0",
            "local.get $l2",
            "i64.store offset=8",
            "local.get $p0",
            "end",
        ],
        "modern Token constructor ID String-Value payload/kind flow drift",
    )
    require_call_suffix(
        function,
        23,
        "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set",
        "modern Token constructor ID map.set",
    )
    require(lines[24] == "local.get $l1)", "modern Token constructor did not return the same receiver")
    body_sha256 = hashlib.sha256(function.payload).hexdigest()
    return {
        "function": function.name,
        "body_sha256": body_sha256,
        "input_id_parameter": "$p0",
        "preserved_input_id_local": "$l2",
        "fresh_entity_local": "$l1",
        "id_key": "id",
        "value_kind_tag": 0,
        "id_map_set_call": call_name(function.lines[23]),
        "returned_entity_local": "$l1",
        "same_input_id_encoded_in_string_value_payload": True,
        "same_fresh_receiver_used_for_map_set_and_return": True,
        "constructor_id_and_receiver_machine_proven": True,
    }


def prove_template(
    context: dict[str, Any],
    pool_index: int,
    create_index: int,
) -> dict[str, Any]:
    generation = context["expected"]["generation"]
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    argument_local = V2.wat_local(handler.lines[create_index - 1])
    require(argument_local is not None, "template argument local missing")
    try:
        base = V2.prove_template_event_pool_argument(
            context["cid"], generation, handler, context["memory"], pool_index, create_index, argument_local
        )
    except V2.VerificationError as error:
        raise VerificationError(str(error)) from error
    if generation == "legacy":
        require(
            [index for index in range(pool_index + 1, create_index) if LOCAL_WRITE_RE.fullmatch(lines[index])]
            == [424, 428, 431],
            "legacy template SSA write inventory drift",
        )
        stores = [index for index in range(pool_index + 1, create_index) if MEMORY_STORE_RE.match(lines[index])]
        require(stores == [434], "legacy template heap-write inventory drift")
        heap = {
            "array_allocation_wat_line": 427,
            "array_local_definition_wat_line": 428,
            "event_pool_definition_wat_line": 424,
            "converted_pool_definition_wat_line": 431,
            "backing_slot_write_wat_line": 434,
        }
    else:
        require(
            [index for index in range(pool_index + 1, create_index) if LOCAL_WRITE_RE.fullmatch(lines[index])]
            == [1938, 1951, 1956, 1961],
            "modern template SSA write inventory drift",
        )
        stores = [index for index in range(pool_index + 1, create_index) if MEMORY_STORE_RE.match(lines[index])]
        require(stores == [1940, 1943, 1965], "modern template heap-write inventory drift")
        heap = {
            "event_wrapper_definition_wat_line": 1938,
            "event_wrapper_heap_writes": [1940, 1943],
            "event_pool_definition_wat_line": 1951,
            "array_allocation_wat_line": 1955,
            "array_local_definition_wat_line": 1956,
            "converted_pool_definition_wat_line": 1961,
            "backing_slot_write_wat_line": 1965,
        }
    literal_index = GENERATION_INVENTORY[generation]["template_literal_index"]
    require(V2.decoded_wat_constant(handler.lines[literal_index], context["memory"]) == "Pool", "active Pool template literal drift")
    require(not any(MEMORY_STORE_RE.match(lines[index]) for index in range(heap["backing_slot_write_wat_line"] + 1, create_index)), "template array changed after active event.pool write")
    return {
        "name": "Pool",
        "active_literal_wat_line": literal_index,
        "argument_array_local": argument_local,
        "argument_count": 1,
        "argument_zero": "bytesToHex(PoolCreated.event.pool)",
        "event_parameter": base["event_parameter"],
        "event_value_local": base["event_value_local"],
        "converted_value_local": base["converted_value_local"],
        "heap_alias_certificate": heap,
        "fresh_array_and_backing_slot_machine_proven": True,
        "no_post_write_alias_mutation_before_create": True,
        "template_identity_and_argument_machine_proven": True,
    }


def scan_reachable_effects(context: dict[str, Any]) -> dict[str, Any]:
    functions = context["functions"]
    normalized_functions: dict[str, Any] = {}
    for name, function in functions.items():
        key = name.replace("generated/schema/", "src/types/schema/")
        require(key not in normalized_functions, f"normalized function collision: {key}")
        normalized_functions[key] = function
    start = context["handler"].name.replace("generated/schema/", "src/types/schema/")
    queue: deque[str] = deque([start])
    visited: set[str] = set()
    store_sites: list[dict[str, Any]] = []
    datasource_sites: list[dict[str, Any]] = []
    indirect_sites: list[dict[str, Any]] = []
    indirect_targets = tuple(name.replace("generated/schema/", "src/types/schema/") for name in context["indirect"])
    while queue:
        name = queue.popleft()
        if name in visited:
            continue
        require(name in normalized_functions, f"reachable function missing: {name}")
        visited.add(name)
        function = normalized_functions[name]
        for index, raw_line in enumerate(function.lines):
            line = normalized(raw_line)
            target = call_name(raw_line)
            if target is not None:
                if target in normalized_functions and target not in visited:
                    queue.append(target)
                if target == WRITER.STORE_SET_CALL:
                    require(index >= 4, f"store.set argument window underflow in {name}")
                    entity = V2.decoded_wat_constant(function.lines[index - 4], context["memory"])
                    require(entity in {"Bundle", "Pool", "Token", "Factory"}, f"dynamic or unexpected store.set target in {name}")
                    store_sites.append({"function": name, "wat_line": index, "target": entity})
                elif target.endswith("dataSource.create"):
                    datasource_sites.append({"function": name, "wat_line": index})
            elif line.startswith("call_indirect"):
                indirect_sites.append({"function": name, "wat_line": index, "instruction": line})
                for target_name in indirect_targets:
                    require(target_name in normalized_functions, f"indirect target missing: {target_name}")
                    if target_name not in visited:
                        queue.append(target_name)
    store_sites.sort(key=lambda item: (item["function"], item["wat_line"], item["target"]))
    datasource_sites.sort(key=lambda item: (item["function"], item["wat_line"]))
    indirect_sites.sort(key=lambda item: (item["function"], item["wat_line"]))
    require(len(visited) == context["expected"]["reachable_function_count"], f"{context['cid']} reachable function closure drift")
    body_bindings = [
        {
            "function": name,
            "body_sha256": hashlib.sha256(normalized_functions[name].payload).hexdigest(),
        }
        for name in sorted(visited)
    ]
    body_bindings_sha256 = canonical_sha256(body_bindings)
    require(len(store_sites) == 4, f"{context['cid']} reachable store.set site count drift")
    require({item["target"] for item in store_sites} == {"Bundle", "Pool", "Token", "Factory"}, f"{context['cid']} reachable store target drift")
    require(len(datasource_sites) == 1 and datasource_sites[0]["function"] == start, f"{context['cid']} dataSource.create closure drift")
    if context["expected"]["generation"] == "modern":
        require(len(indirect_sites) == 1, f"{context['cid']} modern indirect-call closure drift")
        require(indirect_targets == ("~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0",), f"{context['cid']} modern table target drift")
        anonymous = normalized_functions[indirect_targets[0]]
        require(hashlib.sha256(anonymous.payload).hexdigest() == "6fb605d529034f97280ed1434922273df6b572f2052ff3d5fdc38acda17059d0", f"{context['cid']} indirect target body drift")
        display = normalized_functions["~lib/@graphprotocol/graph-ts/common/value/Value#displayData"]
        require(hashlib.sha256(display.payload).hexdigest() == context["expected"]["display_data_sha256"], f"{context['cid']} displayData body drift")
        require(not any(site["function"] in {indirect_targets[0], "~lib/@graphprotocol/graph-ts/common/value/Value#displayData"} for site in store_sites + datasource_sites), f"{context['cid']} indirect target acquired persistent effect")
    else:
        require(not indirect_sites, f"{context['cid']} legacy reachable indirect call drift")
        require(indirect_targets in {(), ("null",)}, f"{context['cid']} legacy inert table inventory drift")
    require(
        body_bindings_sha256 == context["expected"]["reachable_body_bindings_sha256"],
        f"{context['cid']} reachable helper body closure drift",
    )
    return {
        "reachable_function_count": len(visited),
        "reachable_function_body_bindings_sha256": body_bindings_sha256,
        "reachable_store_set_sites": store_sites,
        "reachable_store_set_targets": sorted({item["target"] for item in store_sites}),
        "reachable_data_source_create_sites": datasource_sites,
        "reachable_call_indirect_sites": indirect_sites,
        "conservative_indirect_targets": list(indirect_targets),
        "dynamic_persistent_target_count": 0,
        "complete_direct_and_indirect_effect_site_scan": True,
    }


def observed_selected_handler_effects(context: dict[str, Any]) -> list[tuple[int, str]]:
    handler = context["handler"]
    sites: list[tuple[int, str]] = []
    token_count = 0
    for index, raw_line in enumerate(handler.lines):
        target = call_name(raw_line)
        if target is None:
            continue
        if target.endswith("schema/Pool#save"):
            sites.append((index, "Pool.save"))
        elif target.endswith("dataSource.create"):
            sites.append((index, "PoolTemplate.create"))
        elif target.endswith("schema/Token#save"):
            identity = "Token[token0].save" if token_count == 0 else "Token[token1].save"
            token_count += 1
            sites.append((index, identity))
        elif target.endswith("schema/Factory#save"):
            sites.append((index, "Factory.save"))
        elif target == WRITER.STORE_SET_CALL:
            arguments = direct_store_arguments(context, index)
            if arguments["target"] in {"Pool", "Factory"}:
                sites.append((index, f"{arguments['target']}.save"))
            elif arguments["target"] == "Token":
                raise VerificationError("unexpected direct Token store in Factory handler")
    return sites


def discover_selected_handler_effects(context: dict[str, Any]) -> dict[int, str]:
    generation = context["expected"]["generation"]
    expected_indexes = GENERATION_INVENTORY[generation]["effect_indexes"]
    sites = observed_selected_handler_effects(context)
    require([index for index, _ in sites] == expected_indexes, f"{context['cid']} selected effect-site positions drift")
    require(tuple(identity for _, identity in sites) == EXPECTED_EFFECT_TRACE, f"{context['cid']} selected effect order drift")
    return dict(sites)


def prove_handler_effect_region_policy(
    context: dict[str, Any],
    effect_sites: dict[int, str],
) -> dict[str, Any]:
    """Reject dynamic bypasses and direct raw stores through live entity receivers."""
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    first_effect = min(effect_sites)
    trailing_returns = [index for index in range(first_effect, len(lines)) if lines[index] == "return"]
    trailing_selects = [index for index in range(first_effect, len(lines)) if lines[index] == "select"]
    handler_indirect = [index for index, line in enumerate(lines) if line.startswith("call_indirect")]
    require(not trailing_returns, f"{context['cid']} selected effect region acquired a normal-return bypass")
    require(not trailing_selects, f"{context['cid']} selected effect region acquired select-based identity control")
    require(not handler_indirect, f"{context['cid']} handler acquired call_indirect control")

    generation = context["expected"]["generation"]
    receiver_ranges = (
        [("Pool.save", "$l1", 89, 419), ("Token[token0].save", "$l2", 95, 437), ("Token[token1].save", "$l3", 101, 439), ("Factory.save", "$l4", 13, 441)]
        if generation == "legacy"
        else [("Pool.save", "$l6", 522, 1932), ("Token[token0].save", "$l3", 558, 1969), ("Token[token1].save", "$l5", 578, 1971), ("Factory.save", "$l4", 152, 2019)]
    )
    raw_alias_sites: list[dict[str, Any]] = []
    for identity, local, start, read in receiver_ranges:
        for store_index in range(start + 1, min(read, len(lines))):
            if not MEMORY_STORE_RE.match(lines[store_index]):
                continue
            window_start = max(start + 1, store_index - 6)
            if f"local.get {local}" in lines[window_start:store_index]:
                raw_alias_sites.append(
                    {
                        "identity": identity,
                        "receiver_local": local,
                        "store_wat_line": store_index,
                        "producer_window_start": window_start,
                    }
                )
    require(not raw_alias_sites, f"{context['cid']} live entity receiver acquired a direct raw heap-store alias")
    return {
        "effect_region_start_wat_line": first_effect,
        "normal_return_bypass_sites": trailing_returns,
        "select_identity_control_sites": trailing_selects,
        "handler_call_indirect_sites": handler_indirect,
        "direct_raw_receiver_heap_store_alias_sites": raw_alias_sites,
        "handler_local_effect_region_bypasses_machine_checked": True,
        "bounded_direct_receiver_heap_aliases_machine_checked": True,
    }


def prove_typed_effect_operands(
    context: dict[str, Any],
    effect_sites: dict[int, str],
) -> list[dict[str, Any]]:
    """Validate the exact i32 operand stack at each selected invocation."""
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    generation = context["expected"]["generation"]
    header = " ".join(lines[:2])
    local_types = {
        local: value_type
        for local, value_type in re.findall(r"\((?:param|local) (\$\S+) ([if]\d+)\)", header)
    }
    output: list[dict[str, Any]] = []
    for index, identity in effect_sites.items():
        target = call_name(handler.lines[index])
        require(target is not None, f"{identity} call target missing")
        if generation == "legacy":
            if identity == "PoolTemplate.create":
                require(index == 436 and lines[425].startswith("i32.const ") and lines[435] == "local.get $l1", "legacy template typed-stack operands drift")
                operands = ["i32:static-string(Pool)", "i32:fresh-array(event.pool)"]
            else:
                local = V2.wat_local(handler.lines[index - 1])
                require(local is not None, f"legacy {identity} receiver operand drift")
                require(local_types.get(local) == "i32", f"legacy {identity} receiver type drift")
                operands = [f"i32:entity-ref({local})"]
        elif identity in {"Pool.save", "Factory.save"}:
            arguments = direct_store_arguments(context, index)
            require(local_types.get(arguments["id_value_local"]) == "i32" and local_types.get(arguments["entity_local"]) == "i32", f"modern {identity} local operand type drift")
            require(lines[index - 4].startswith("i32.const "), f"modern {identity} target operand drift")
            operands = [
                f"i32:static-string({arguments['target']})",
                f"i32:id-string({arguments['id_value_local']})",
                f"i32:entity-ref({arguments['entity_local']})",
            ]
        elif identity == "PoolTemplate.create":
            require(index == 1968 and lines[1966].startswith("i32.const ") and lines[1967] == "local.get $l1", "modern template typed-stack operands drift")
            operands = ["i32:static-string(Pool)", "i32:fresh-array(event.pool)"]
        else:
            local = V2.wat_local(handler.lines[index - 1])
            require(local is not None, f"modern {identity} receiver operand drift")
            require(local_types.get(local) == "i32", f"modern {identity} receiver type drift")
            operands = [f"i32:entity-ref({local})"]
        output.append(
            {
                "effect": identity,
                "wat_line": index,
                "call": target,
                "operands_bottom_to_top": operands,
                "operand_count": len(operands),
                "all_operand_wasm_types": "i32",
            }
        )
    require(tuple(item["effect"] for item in output) == EXPECTED_EFFECT_TRACE, "typed effect operand order drift")
    return output


def prove_effect_traces(
    handler: Any,
    cfg: dict[int, tuple[int, ...]],
    effect_sites: dict[int, str],
    helper_effect_sites: set[int],
) -> dict[str, Any]:
    start = 2
    queue: deque[tuple[int, tuple[str, ...]]] = deque([(start, ())])
    visited: set[tuple[int, tuple[str, ...]]] = set()
    normal_traces: set[tuple[str, ...]] = set()
    trap_traces: set[tuple[str, ...]] = set()
    observed: set[str] = set()
    expected = EXPECTED_EFFECT_TRACE
    while queue:
        node, trace = queue.popleft()
        state = (node, trace)
        if state in visited:
            continue
        visited.add(state)
        require(node >= 0, "effect-trace worklist contains an unclassified exit")
        next_trace = trace
        if node in effect_sites:
            identity = effect_sites[node]
            observed.add(identity)
            require(len(trace) < len(expected), f"duplicate or extra selected effect at WAT line {node}")
            require(identity == expected[len(trace)], f"reordered selected effect at WAT line {node}")
            if node in helper_effect_sites:
                trap_traces.add(trace)
            next_trace = trace + (identity,)
        for successor in cfg[node]:
            if successor == NORMAL_EXIT:
                if normalized(handler.lines[node]) == "return":
                    require(not next_trace, f"explicit normal return after selected effect at WAT line {node}")
                else:
                    require(next_trace == expected, f"normal fallthrough bypasses selected effect suffix at WAT line {node}")
                normal_traces.add(next_trace)
            elif successor == TRAP_EXIT:
                trap_traces.add(next_trace)
            else:
                queue.append((successor, next_trace))
    require(observed == set(expected), "not every selected effect is reachable")
    require(normal_traces <= {(), expected}, f"partial or reordered normal-return trace: {sorted(normal_traces)}")
    require(expected in normal_traces, "complete Factory effect trace has no normal exit")
    require(all(trace == expected[: len(trace)] for trace in trap_traces), f"trap trace is not an ordered prefix: {sorted(trap_traces)}")
    return {
        "projection": list(expected),
        "normal_exit_traces": [list(trace) for trace in sorted(normal_traces, key=lambda item: (len(item), item))],
        "modeled_trap_boundary_traces": [list(trace) for trace in sorted(trap_traces, key=lambda item: (len(item), item))],
        "normal_exit_trace_rule": "empty or the exact five-effect sequence once",
        "modeled_trap_boundary_trace_rule": "an ordered prefix only",
        "modeled_trap_boundary_scope": "handler-local explicit unreachable exits plus reviewed save-helper pre-store trap boundaries",
        "all_handler_local_normal_and_explicit_trap_exits_machine_checked": True,
        "reviewed_save_helper_pre_store_trap_boundaries_projected": True,
        "same_path_and_order_machine_proven": True,
    }


def prove_legacy_frontend(context: dict[str, Any], states: list[dict[str, frozenset[int]] | None]) -> dict[str, Any]:
    try:
        identities = V2.legacy_factory_identity_locals(context["cid"], context["handler"], context["memory"])
    except V2.VerificationError as error:
        raise VerificationError(str(error)) from error
    require(identities["pool"] == "$l1" and identities["token0"] == "$l2" and identities["token1"] == "$l3" and identities["factory"] == "$l4", f"{context['cid']} legacy entity local drift")
    require(identities["factory_id"] == context["expected"]["factory_id"], f"{context['cid']} Factory ID drift")
    definitions = verify_reaching_definitions(context["handler"], states, "legacy")
    constructor = prove_legacy_entity_constructor(context)
    definition_identities = prove_legacy_argument_definition_identities(
        context, definitions, constructor
    )
    helpers = [
        prove_save_helper(context, entity, context["expected"]["helper_sha256"][entity])
        for entity in ("Pool", "Token", "Factory")
    ]
    template = prove_template(context, 420, 436)
    return {
        "frontend": "legacy-named-event-getters-and-generated-save-helpers",
        "entity_identity_locals": identities,
        "effect_argument_reaching_definitions": definitions,
        "effect_argument_definition_identities": definition_identities,
        "shared_entity_constructor_proof": constructor,
        "save_helper_proofs": helpers,
        "template": template,
        "exact_receiver_and_id_bindings_machine_proven": True,
        "argument_identity_machine_proven": True,
    }


def prove_modern_frontend(context: dict[str, Any], states: list[dict[str, frozenset[int]] | None]) -> dict[str, Any]:
    pool_arguments = direct_store_arguments(context, 1933)
    factory_arguments = direct_store_arguments(context, 2020)
    require(pool_arguments == {"target": "Pool", "id_value_local": "$l1", "entity_local": "$l6"}, f"{context['cid']} Pool direct-store operands drift")
    require(factory_arguments == {"target": "Factory", "id_value_local": "$p0", "entity_local": "$l4"}, f"{context['cid']} Factory direct-store operands drift")
    try:
        identities = V2.modern_factory_identity_locals(context["cid"], context["handler"], context["memory"], "$l6")
    except V2.VerificationError as error:
        raise VerificationError(str(error)) from error
    require(identities["pool"] == "$l6" and identities["token0"] == "$l3" and identities["token1"] == "$l5" and identities["factory"] == "$l4", f"{context['cid']} modern entity local drift")
    require(identities["factory_id"] == context["expected"]["factory_id"], f"{context['cid']} Factory ID drift")
    definitions = verify_reaching_definitions(context["handler"], states, "modern")
    token_constructor = prove_modern_token_constructor(context)
    definition_identities = prove_modern_argument_definition_identities(
        context, definitions, identities, token_constructor
    )
    id_branches = [
        prove_present_id_branch(context, "Pool", "$l6", "$l1", 1886, 1891, 1900, 1903, 1933),
        prove_present_id_branch(context, "Factory", "$l4", "$p0", 1973, 1978, 1987, 1990, 2020),
    ]
    token = prove_save_helper(context, "Token", context["expected"]["helper_sha256"]["Token"])
    template = prove_template(context, 1933, 1968)
    return {
        "frontend": "modern-indexed-event-entities-inlined-stores-and-token-helper",
        "entity_identity_locals": identities,
        "effect_argument_reaching_definitions": definitions,
        "effect_argument_definition_identities": definition_identities,
        "token_constructor_proof": token_constructor,
        "required_id_branch_proofs": id_branches,
        "token_save_helper_proof": token,
        "template": template,
        "exact_receiver_and_id_bindings_machine_proven": True,
        "argument_identity_machine_proven": True,
    }


def verify_factory_authority(context: dict[str, Any]) -> dict[str, Any]:
    """Bind one context to its exact artifact, WAT, handler, and profile pins."""
    cid = context["cid"]
    require(cid in EXPECTED_ARTIFACTS, f"unexpected Factory artifact: {cid}")
    expected = EXPECTED_ARTIFACTS[cid]
    context["expected"] = expected
    require(context["profile"]["profile_id"] == expected["profile_id"], f"{cid} profile drift")
    require(context["profile"]["metadata_generation"] == expected["generation"], f"{cid} generation drift")
    require(context["analysis"]["sha256"] == expected["wasm_sha256"], f"{cid} WASM digest drift")
    require(context["analysis"]["wat_sha256"] == expected["wat_sha256"], f"{cid} WAT digest drift")
    require(context["analysis"]["registered_handlers"]["handlePoolCreated"]["body_sha256"] == expected["handler_sha256"], f"{cid} handler authority drift")
    require(hashlib.sha256(context["handler"].payload).hexdigest() == expected["handler_sha256"], f"{cid} actual handler body digest drift")
    require(context["handler"].start_line == expected["handler_start"], f"{cid} handler WAT start drift")
    return expected


def prove_factory_effects(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["cid"]
    expected = verify_factory_authority(context)
    generation = expected["generation"]
    inventory = instruction_inventory(context["handler"], generation)
    lines = [normalized(line) for line in context["handler"].lines]
    frames, by_label = parse_structured_control(lines)
    require([(frame["start"], frame["kind"], frame["label"]) for frame in frames] == GENERATION_INVENTORY[generation]["controls"], f"{cid} structured frame order drift")
    cfg = build_cfg(lines, frames, by_label, GENERATION_INVENTORY[generation]["forced_true_ifs"])
    states = reaching_definitions(context["handler"], cfg, 2)
    frontend = prove_legacy_frontend(context, states) if generation == "legacy" else prove_modern_frontend(context, states)
    definition_identity_proof = frontend["effect_argument_definition_identities"]
    constructor_semantics_proven = (
        definition_identity_proof.get("every_constructor_alternative_body_semantics_proven")
        or definition_identity_proof.get("every_constructor_alternative_body_or_inline_semantics_proven")
    )
    require(
        definition_identity_proof["every_alternative_reaching_definition_identity_proven"]
        and constructor_semantics_proven is True,
        f"{cid} receiver-definition identity proof did not close",
    )
    effect_sites = discover_selected_handler_effects(context)
    effect_region_policy = prove_handler_effect_region_policy(context, effect_sites)
    typed_effect_operands = prove_typed_effect_operands(context, effect_sites)
    helper_effect_sites = {420, 438, 440, 442} if generation == "legacy" else {1970, 1972}
    traces = prove_effect_traces(context["handler"], cfg, effect_sites, helper_effect_sites)
    closure = scan_reachable_effects(context)
    first, last = GENERATION_INVENTORY[generation]["effect_indexes"][0], GENERATION_INVENTORY[generation]["effect_indexes"][-1]
    suffix_sha256 = V2.wat_slice_sha256(context["handler"], first, last)
    require(suffix_sha256 == expected["effect_suffix_sha256"], f"{cid} exact effect suffix digest drift")
    return {
        "profile_id": expected["profile_id"],
        "mapping_cid": cid,
        "generation": generation,
        "authority": {
            "wasm_sha256": expected["wasm_sha256"],
            "wat_sha256": expected["wat_sha256"],
            "handler_function": context["handler"].name,
            "handler_body_sha256": expected["handler_sha256"],
            "handler_wat_start_line": expected["handler_start"],
            "effect_suffix_sha256": suffix_sha256,
            "wabt_version": WRITER.WABT_VERSION,
        },
        "instruction_and_ssa_inventory": inventory,
        "structured_control": {
            "node_count": len(frames),
            "graph_sha256": canonical_sha256(frames),
            "forced_true_path_predicate_ifs": GENERATION_INVENTORY[generation]["forced_true_ifs"],
            "all_handler_local_edges_branch_targets_and_explicit_exits_machine_checked": True,
        },
        "generation_frontend": frontend,
        "typed_effect_operand_stack": typed_effect_operands,
        "handler_effect_region_policy": effect_region_policy,
        "effect_trace_proof": traces,
        "reachable_effect_closure": closure,
        "reviewed_effect_order": list(EXPECTED_EFFECT_TRACE),
        "same_path_or_dataflow_machine_proven": True,
        "argument_identity_machine_proven": definition_identity_proof["every_alternative_reaching_definition_identity_proven"] and constructor_semantics_proven is True,
        "template_identity_and_argument_machine_proven": True,
        "graph_handler_rollback_proven_by_retained_wat": False,
    }


def load_contexts(root: Path, wasm2wat: Path | None = None) -> list[dict[str, Any]]:
    root = root.resolve()
    v2_path = root / V2_CONTRACT_PATH
    guard_path = root / GUARD_CONTRACT_PATH
    require(v2_path.is_file() and raw_sha256(v2_path) == V2_CONTRACT_SHA256, "pinned v2 contract raw digest drift")
    require(guard_path.is_file() and raw_sha256(guard_path) == GUARD_CONTRACT_SHA256, "pinned modern guard contract raw digest drift")
    v2 = load_json(v2_path)
    guard = load_json(guard_path)
    require(v2.get("contract_version") == "uniswap-v3-segment-field-semantics/v2", "v2 contract version drift")
    require(guard.get("contract_version") == "uniswap-v3-factory-guard/v1", "modern guard contract version drift")
    require(guard["scope"]["cumulative_closed_after_this_supplement"] == 6 and guard["scope"]["residual_after_this_supplement"] == 12, "modern guard closure scope drift")
    writer = load_json(root / "uniswap-v3/graft-ancestry/v2/writer-compatibility.json")
    profiles = {item["mapping_cid"]: item for item in writer["factory_writer_contract"]["mapping_bindings"]}
    require(set(profiles) == set(EXPECTED_ARTIFACTS), "Factory mapping set drift")
    contexts: list[dict[str, Any]] = []
    for cid in sorted(EXPECTED_ARTIFACTS, key=lambda item: EXPECTED_ARTIFACTS[item]["profile_id"]):
        context = V2.load_factory_wat_context(root, cid, writer, wasm2wat)
        context["indirect"] = tuple(context["analysis"]["call_indirect_table_targets"])
        contexts.append(context)
    return contexts


def expected_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    proofs = [prove_factory_effects(context) for context in load_contexts(root, wasm2wat)]
    require(len(proofs) == 6, "Factory effect proof count drift")
    require(all(proof["same_path_or_dataflow_machine_proven"] and proof["argument_identity_machine_proven"] and proof["template_identity_and_argument_machine_proven"] for proof in proofs), "Factory effect proof did not close")
    require(not any(proof["graph_handler_rollback_proven_by_retained_wat"] for proof in proofs), "rollback overclaim")
    truth = {key: True for key in sorted(TRUE_FLAGS)} | {key: False for key in sorted(FALSE_FLAGS)}
    return {
        "contract_version": CONTRACT_VERSION,
        "authority_contract": {
            "semantic_authority": "the six exact retained deployed Factory WASM artifacts and checksum-pinned WABT 1.0.35 --generate-names WAT projections",
            "proof_model": "shared structured CFG, typed i32 call operands, SSA reaching definitions, path predicates, bounded heap aliases, interprocedural save-helper summaries, and complete direct/indirect persistent-effect closure with separate legacy and modern frontends",
            "normal_trace_rule": "every handler-local normal exit projects to empty or exactly Pool.save, Pool template create, Token0.save, Token1.save, Factory.save once",
            "modeled_trap_boundary_rule": "handler-local explicit unreachable exits and reviewed save-helper pre-store trap boundaries project only to ordered prefixes",
            "fail_closed_rule": "any unmodeled control edge, local definition, heap write, call target, helper body, table target, persistent effect, receiver, ID, template name, or template argument leaves the claims false",
            "host_boundary": "the proof reaches Graph host-effect invocation; import/helper traps outside the reviewed save-helper boundaries, Graph Node transaction rollback, and host memory behavior are not projected by retained WAT",
        },
        "provenance": {
            "base_commit": BASE_COMMIT,
            "v2_contract": {"path": V2_CONTRACT_PATH.as_posix(), "raw_sha256": V2_CONTRACT_SHA256, "contract_version": "uniswap-v3-segment-field-semantics/v2"},
            "modern_guard_contract": {"path": GUARD_CONTRACT_PATH.as_posix(), "raw_sha256": GUARD_CONTRACT_SHA256, "contract_version": "uniswap-v3-factory-guard/v1"},
            "wabt_version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-factory-wasm>"],
        },
        "scope": {
            "factory_upstream_path_count": 18,
            "closed_before_this_supplement": 6,
            "newly_closed_factory_effect_paths": 6,
            "cumulative_closed_after_this_supplement": 12,
            "residual_after_this_supplement": 6,
            "newly_closed_path": "$.pool_created_effect_order_observation.same_path_or_dataflow_machine_proven",
            "residual_path": "$.complete_static_handler_contract",
            "mapping_count": 6,
            "legacy_mapping_count": 4,
            "modern_mapping_count": 2,
        },
        "factory_effect_proofs": proofs,
        "truth_boundary": truth,
        "residuals": [
            "retained WAT does not prove Graph handler transaction rollback after a later trap",
            "the trace engine is handler-local and does not claim a complete interprocedural trap projection across host imports or unreviewed helpers",
            "all six complete static Factory handler contracts and all initialized field values remain unproved",
            "all six totalSupply success/failure value flows remain unproved",
            "the optional earlier Bundle write is inventoried but is outside the reviewed five-effect suffix projection",
            "no runtime consumes this proof and no scheduling, continuity, oracle, parity, proof-of-indexing, backfill, or production gate is promoted",
        ],
    }


def verify_contract(
    root: Path,
    contract: dict[str, Any] | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    expected = expected_contract(root, wasm2wat)
    committed = contract if contract is not None else load_json(root.resolve() / CONTRACT_PATH)
    require(committed == expected, "committed Factory effects contract is not the deterministic retained-WAT projection")
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
        f"verified {contract['contract_version']}: six Factory effect paths closed; "
        "Factory paths 12/18 closed and 6/18 residual"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
