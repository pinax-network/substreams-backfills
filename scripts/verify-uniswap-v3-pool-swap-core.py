#!/usr/bin/env python3
"""Generate and fail-closed verify bounded Uniswap V3 Pool Swap core state v1."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/pool-swap-core/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-swap-core-semantics/v1"

MINT_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-mint.py"
MINT_VERIFIER_SHA256 = "a84e24fbff7449ca3ebbe94ef93ee1c6ab2d81ab4b9085c441108f587604be9d"
MINT_CONTRACT_PATH = Path("uniswap-v3/pool-mint/v1/contract.json")
MINT_CONTRACT_SHA256 = "1040c821093b4f5afff3e99df58aa0e4b8021c643226d42dabd1255587fbf14c"
MINT_CONTRACT_VERSION = "uniswap-v3-pool-mint-semantics/v1"
POOL_RUNTIME_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-runtime.py"
POOL_RUNTIME_VERIFIER_SHA256 = "a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67"
POOL_RUNTIME_CONTRACT_PATH = Path("uniswap-v3/pool-runtime/v1/contract.json")
POOL_RUNTIME_CONTRACT_SHA256 = "66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53"
POOL_RUNTIME_CONTRACT_VERSION = "uniswap-v3-pool-runtime/v1"
INITIALIZE_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-initialize.py"
INITIALIZE_VERIFIER_SHA256 = "5de73a42431c0d26dea48c6c570a58626532be14288cd16da20bcd1f2710d21d"
INITIALIZE_CONTRACT_PATH = Path("uniswap-v3/pool-initialize/v1/contract.json")
INITIALIZE_CONTRACT_SHA256 = "63bbec1b3190f1ccd54f9c9cb9a29bbd5a7d730be0165a2277412ea0b3adea14"
INITIALIZE_CONTRACT_VERSION = "uniswap-v3-pool-initialize-semantics/v1"

POOL_ABI_CID = "QmULRc8Ac1J6YFy11z7JRpyThb6f7nmL5mMTQvN7LKj2Vy"
POOL_ABI_PATH = Path(f"uniswap-v3/graft-ancestry/v1/artifacts/{POOL_ABI_CID}")
POOL_ABI_SHA256 = "df8064cbe381e7a929aa4e1a658ce3617daed0e871883bf29ced54112fdfdbfd"
POOL_ABI_BYTES = 19_634

HANDLER_ID = "Pool.handleSwap"
HANDLER_EXPORT = "handleSwap"
LEGACY_MAP_SET = (
    "~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_"
    "~lib/@graphprotocol/graph-ts/index/Value>#set"
)
MODERN_MAP_SET = (
    "~lib/@graphprotocol/graph-ts/common/collections/TypedMap<~lib/string/String_"
    "~lib/@graphprotocol/graph-ts/common/value/Value>#set"
)
STORE_GET = "~lib/@graphprotocol/graph-ts/index/store.get"

SELECTED_FIELDS = {
    "liquidity": {
        "schema_type": "BigInt!",
        "event_parameter_index": 5,
        "event_parameter_name": "liquidity",
        "event_parameter_type": "uint128",
    },
    "tick": {
        "schema_type": "BigInt",
        "event_parameter_index": 6,
        "event_parameter_name": "tick",
        "event_parameter_type": "int24",
    },
    "sqrtPrice": {
        "schema_type": "BigInt!",
        "event_parameter_index": 4,
        "event_parameter_name": "sqrtPriceX96",
        "event_parameter_type": "uint160",
    },
}

EXPECTED_HANDLER = {
    "modern-base": (11423, 2961, "8a8979c7c57f0f36a3ac9a8331fc70f76e9160be417f905babfdd34bc9043ca6"),
    "modern-mainnet": (11422, 2790, "1c8e5d0b6057b4ab06677f3f0508faecc8d654d04c7dd73aa46bbe563d1da66e"),
    "legacy-mainnet-root": (7730, 791, "75b9903a7813d81a4a0315600426b9d1f238077b5f6480058ea66185ff915e92"),
    "legacy-mainnet-qmrv": (7752, 791, "ef1161336dbe8acf23bebacd3bcaad85b1045dd5738d5c914f39a865dd199873"),
    "legacy-base-root": (7757, 797, "88e5f3b60c48bea65a62164a6ac7685539bf8c40f922bbb1fa3d2661ca6a5d7b"),
    "legacy-mainnet-stable-fee-tier-100": (7755, 791, "65b44d7cc4df2fbb0d963111e6525358961d126bcd64c0654d8f8aad22ab2fa0"),
    "legacy-mainnet-stable-fee-tier-1": (7755, 791, "65b44d7cc4df2fbb0d963111e6525358961d126bcd64c0654d8f8aad22ab2fa0"),
    "legacy-mainnet-stable": (7746, 791, "65b44d7cc4df2fbb0d963111e6525358961d126bcd64c0654d8f8aad22ab2fa0"),
}

EXPECTED_MUTATION_CLOSURE = {
    "modern-base": (111, "8d9c50fd41009f6853a1e0f131fae525a8ca3f47e3453106311e42277cba7c87", 630, "14696acbe20c11204e7ae76c0230e73cd0dfeca8e705364a90cdcfc1c3c8b12e", 197, "af107606b765c57b0ad2e7016eec87c5889ed2d5006287040e987029d29f2b75"),
    "modern-mainnet": (111, "a024b3dfd9436fec76fda018f677fb3a3d3a447e34a5239af77e0913253e5eb4", 628, "10b599c4e4d2f76f80adc1930ed052b956009fb023db5955ba288230c2867896", 197, "06652f3a81ca5eb1fedd588ba8f7700d8e67f1ebab12c6462954e861cce02940"),
    "legacy-mainnet-root": (197, "049f52cbd9cc75d2b7c7539e17329b602b6e4cb5d5d1ae6b3b023b4e9ce0754f", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "0bc76d26cc5d5fa9c2e34ef0f424d145ba65ddd376a967d9f6a1ae9a0d150aa2"),
    "legacy-mainnet-qmrv": (197, "f058a3f84680e3d9a81c048de89ce33cb4d9a824e1c8ed8235a241143ddb5c26", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-base-root": (197, "dadda3c6c582d663832b29ab217717779306574ccc568f88dbf993e6a8a4c538", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-mainnet-stable-fee-tier-100": (197, "ca8707860c31c53c6be4b8b5e0b01b505d1ba4f8df76e6ac3120f739e0cc6115", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-mainnet-stable-fee-tier-1": (197, "99e336dc1d28185f3f3bdd1805965666500f60c6c9645cfbabe450692202b9df", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-mainnet-stable": (197, "f08e06f0d1ac427f6bd75e153d31b00e3abd1100fa35710b7841bb610db33d1d", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
}

EXPECTED_EFFECT_CLOSURE = {
    "modern-base": (111, 1, ("~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0",), 13, "3a2411c427b0ad2cf81f370c46425169c905585c4869a970763c7624e0afb4f4"),
    "modern-mainnet": (111, 1, ("~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0",), 13, "cee21c754467ea204176b7366fdcc0894e66d50d850637d1b90a36d4e319c98e"),
    "legacy-base-root": (197, 0, (), 13, "553b9368fefa8150e27c2c9f95a25a844414bab9dec5afbcebfd5fef87c63663"),
    "legacy-mainnet-root": (197, 0, (), 13, "d03c3b0429b86a0d19eeea3e74eec2994b1caae454cbbf2fa69146b29a7a233d"),
    "legacy-mainnet-qmrv": (197, 0, (), 13, "d03c3b0429b86a0d19eeea3e74eec2994b1caae454cbbf2fa69146b29a7a233d"),
    "legacy-mainnet-stable": (197, 0, (), 13, "d03c3b0429b86a0d19eeea3e74eec2994b1caae454cbbf2fa69146b29a7a233d"),
    "legacy-mainnet-stable-fee-tier-1": (197, 0, (), 13, "d03c3b0429b86a0d19eeea3e74eec2994b1caae454cbbf2fa69146b29a7a233d"),
    "legacy-mainnet-stable-fee-tier-100": (197, 0, (), 13, "d03c3b0429b86a0d19eeea3e74eec2994b1caae454cbbf2fa69146b29a7a233d"),
}

EXPECTED_LEGACY_SETTERS = {
    "legacy-mainnet-root": ("e4ebfe9196b2f37282703607f04ec5f6e529bc864b4cfdfcb77398e1a25ff602", "0e52309e9c2a98cdfd797263f5794f7d353c8e8220b92925648ae9fe1a5ba8b2", "0154820de85e2316b6e94da02a833506c57417c77e4f998fb81e251ebcd980b8"),
    "legacy-mainnet-qmrv": ("36422954d0881649468da70bc28e37097ddfa37c0248b8d900c99c8913281fc2", "dd722ca4ae61967479ef107f1ac9e11a13ffd74fab59db352afbf9676db59481", "f861a3419435c181039d3989b6678888793ddad75563083535dbdc2e09ced822"),
    "legacy-base-root": ("1c9ba30b87b3ac05d83b1160f32a810b1e68318d5e8418b00ba79cbfc80b9889", "582805de9c3a85518ad1d721aaf5196482fec48b7e1bb1dfd084cb8c7b3bca0d", "710f1c7d132e048b102c1db5e2531363e439898131a58e473c1b239c76d9f891"),
    "legacy-mainnet-stable": ("63208d319819bbe78cd5e0c5053f694ca8232b3e9830921796d627a30280c8d4", "83154bc67ef4a698611d6e5c6a2e066024a5995e3aa0d00257a93253c3a771be", "d11ea8e1f487171d79c0c39a78d5fb1a7a1302367e728daef6fb9f083acb5f6e"),
    "legacy-mainnet-stable-fee-tier-1": ("63208d319819bbe78cd5e0c5053f694ca8232b3e9830921796d627a30280c8d4", "83154bc67ef4a698611d6e5c6a2e066024a5995e3aa0d00257a93253c3a771be", "d11ea8e1f487171d79c0c39a78d5fb1a7a1302367e728daef6fb9f083acb5f6e"),
    "legacy-mainnet-stable-fee-tier-100": ("63208d319819bbe78cd5e0c5053f694ca8232b3e9830921796d627a30280c8d4", "83154bc67ef4a698611d6e5c6a2e066024a5995e3aa0d00257a93253c3a771be", "d11ea8e1f487171d79c0c39a78d5fb1a7a1302367e728daef6fb9f083acb5f6e"),
}

TRUE_FLAGS = (
    "mint_contract_recomputed_and_pinned",
    "initialize_contract_recomputed_and_pinned",
    "pool_runtime_contract_recomputed_and_pinned",
    "all_eight_same_wat_runtime_capsules_recomputed",
    "shared_pool_swap_abi_verified",
    "all_eight_pool_swap_handler_bindings_verified",
    "all_twenty_four_selected_parameter_indices_verified",
    "all_twenty_four_selected_receiver_key_value_flows_verified",
    "all_eight_first_pool_save_orders_verified",
    "both_modern_required_prefix_traps_verified",
    "both_modern_two_token_guard_skip_paths_verified",
    "all_eight_exact_reachable_mutation_inventories_bound",
    "all_eight_exact_transitive_store_inventories_bound",
    "all_twenty_four_segment_field_call_flow_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "cumulative_selected_field_count_remains_36",
    "cumulative_residual_field_count_remains_230",
)

FALSE_FLAGS = (
    "pool_swap_semantics_complete",
    "pool_swap_core_state_projection_complete",
    "pool_swap_selected_persistence_proven",
    "no_later_selected_field_overwrites_proven",
    "legacy_deduplicated_symbol_names_are_semantic_authority",
    "general_heap_alias_semantics_rederived",
    "direct_selected_payload_alias_safety_rederived",
    "bytes_to_hex_host_semantics_rederived",
    "numeric_host_semantics_rederived",
    "graph_store_host_semantics_rederived",
    "imported_host_semantics_rederived",
    "graph_handler_rollback_proven_by_retained_wat",
    "post_fatal_execution_modeled",
    "complete_pool_entity_history",
    "all_manifest_handler_field_semantics_complete",
    "all_stored_fields_exact",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
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
    "readiness_complete",
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


MINT = load_module("uniswap_v3_pool_mint_for_swap_core", MINT_VERIFIER_PATH, MINT_VERIFIER_SHA256)
INITIALIZE = MINT.INITIALIZE
POOL_RUNTIME = MINT.POOL_RUNTIME
V2 = MINT.V2
WRITER = MINT.WRITER


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


def single_suffix_function(functions: dict[str, Any], suffix: str, field: str) -> Any:
    return INITIALIZE.single_suffix_function(functions, suffix, field)


def single_call(function: Any, suffix: str, field: str) -> int:
    return INITIALIZE.single_call(function, suffix, field)


def require_instruction(function: Any, index: int, expected: str, field: str) -> None:
    INITIALIZE.require_instruction(function, index, expected, field)


def require_call(function: Any, index: int, suffix: str, field: str) -> None:
    INITIALIZE.require_call(function, index, suffix, field)


def verify_pool_abi(root: Path) -> dict[str, Any]:
    path = root / POOL_ABI_PATH
    require(path.is_file(), "Pool ABI missing")
    require(path.stat().st_size == POOL_ABI_BYTES, "Pool ABI byte length drift")
    require(raw_sha256(path) == POOL_ABI_SHA256, "Pool ABI digest drift")
    events = [item for item in load_json_strict(path) if item.get("type") == "event" and item.get("name") == "Swap"]
    expected = {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "sender", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "recipient", "type": "address"},
            {"indexed": False, "internalType": "int256", "name": "amount0", "type": "int256"},
            {"indexed": False, "internalType": "int256", "name": "amount1", "type": "int256"},
            {"indexed": False, "internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"indexed": False, "internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"indexed": False, "internalType": "int24", "name": "tick", "type": "int24"},
        ],
        "name": "Swap",
        "type": "event",
    }
    require(events == [expected], "Pool ABI Swap signature drift")
    return {"cid": POOL_ABI_CID, "path": str(POOL_ABI_PATH), "bytes": POOL_ABI_BYTES, "sha256": POOL_ABI_SHA256, "event": expected}


def swap_context_from_mint(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = WRITER.resolve_handler(context["functions"], context["exports"], HANDLER_EXPORT)
    binding = context["analysis"]["registered_handlers"][HANDLER_EXPORT]
    require(handler.name == context["analysis"]["registered_handler_export_targets"][HANDLER_EXPORT], f"{cid} Swap export target drift")
    require(handler.function_index == binding["wat_function_index"], f"{cid} Swap function index drift")
    require(function_sha256(handler) == binding["body_sha256"], f"{cid} Swap analysis body drift")
    profile = context["profile"]["profile_id"]
    require((handler.start_line, len(handler.lines), function_sha256(handler)) == EXPECTED_HANDLER[profile], f"{cid} exact Swap handler binding drift")
    return {**context, "handler": handler}


def prove_runtime(context: dict[str, Any]) -> dict[str, Any]:
    return MINT.prove_runtime_for_mint_context(context)


def prove_event_value_to_i32(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    helper = single_suffix_function(context["functions"], "ethereum.Value#toI32", f"{cid} Value#toI32")
    require(len(helper.lines) == (26 if generation == "modern" else 28), f"{cid} Value#toI32 shape")
    offset = 0 if generation == "modern" else 1
    require_instruction(helper, 1 + offset, "local.get $p0", f"{cid} toI32 receiver")
    require_instruction(helper, 2 + offset, "i32.load", f"{cid} toI32 kind load")
    require_instruction(helper, 3 + offset, "i32.const 3", f"{cid} toI32 uint kind")
    require_instruction(helper, 4 + offset, "i32.eq", f"{cid} toI32 uint comparison")
    require(any(normalized(line) == "i32.const 4" for line in helper.lines), f"{cid} toI32 int kind")
    require(any(normalized(line) == "unreachable" for line in helper.lines), f"{cid} toI32 invalid-kind trap")
    require_instruction(helper, len(helper.lines) - 4, "local.get $p0", f"{cid} toI32 payload receiver")
    require_instruction(helper, len(helper.lines) - 3, "i64.load offset=8", f"{cid} toI32 payload load")
    require(normalized(helper.lines[-2]).startswith("i32.wrap_i64"), f"{cid} toI32 pointer narrowing")
    require_call(helper, len(helper.lines) - 1, "ByteArray#toI32", f"{cid} toI32 signed decode")
    return {"function": helper.name, "body_sha256": function_sha256(helper), "accepted_event_value_kinds": [3, 4], "invalid_kind_branch_traps": True, "payload_decode": "i64.load offset=8; i32.wrap_i64; ByteArray#toI32", "signed_i32_decode_machine_proven": True}


def prove_i32_to_bigint_object(
    context: dict[str, Any], suffix: str, expected_sha256: str
) -> dict[str, Any]:
    """Bind the four-byte signed-i32 operand sequence and returned object identity."""
    cid = context["mapping_cid"]
    helper = single_suffix_function(context["functions"], suffix, f"{cid} {suffix}")
    require(len(helper.lines) == 33, f"{cid} {suffix} shape")
    require(function_sha256(helper) == expected_sha256, f"{cid} {suffix} digest drift")
    require_call(helper, 3, "ByteArray#constructor", f"{cid} {suffix} allocation")
    result_local = local_name(helper.lines[4], "tee")
    require(result_local is not None, f"{cid} {suffix} result local")
    for position in (6, 12, 20, 28):
        require_instruction(helper, position, "local.get $p0", f"{cid} {suffix} input operand")
    for position, shift in ((13, 8), (21, 16), (29, 24)):
        require_instruction(helper, position, f"i32.const {shift}", f"{cid} {suffix} signed shift")
        require_instruction(helper, position + 1, "i32.shr_s", f"{cid} {suffix} signed shift operator")
    require(
        normalized(helper.lines[32]).startswith(f"local.get {result_local}"),
        f"{cid} {suffix} returned object",
    )
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "input_parameter": "$p0",
        "returned_object_local": result_local,
        "little_endian_byte_shifts": [0, 8, 16, 24],
        "signed_i32_operand_and_return_identity_machine_proven": True,
        "nonzero_object_continuation_inherited_from_same_wat_runtime_allocator": True,
    }


def prove_legacy_getter(context: dict[str, Any], suffix: str, index: int, conversion: str, misleading: bool) -> dict[str, Any]:
    cid = context["mapping_cid"]
    helper = single_suffix_function(context["functions"], suffix, f"{cid} legacy parameter getter")
    require(len(helper.lines) == 8, f"{cid} legacy parameter getter shape")
    for position, instruction in ((1, "local.get $p0"), (2, "i32.load"), (3, "i32.load offset=24"), (4, f"i32.const {index}")):
        require_instruction(helper, position, instruction, f"{cid} legacy parameter getter")
    require_call(helper, 5, "EventParam>#__get", f"{cid} legacy parameter array access")
    require_instruction(helper, 6, "i32.load offset=4", f"{cid} legacy parameter Value")
    require_call(helper, 7, f"Value#{conversion}", f"{cid} legacy parameter conversion")
    return {"function": helper.name, "body_sha256": function_sha256(helper), "decoded_event_parameter_index": index, "conversion": conversion, "misleading_deduplicated_symbol_name": misleading, "symbol_name_used_as_semantic_authority": False, "wrapper_index_value_flow_machine_proven": True}


def prove_legacy_setter(context: dict[str, Any], suffix: str, field: str, expected_hash: str, nullable: bool, misleading: bool) -> dict[str, Any]:
    cid = context["mapping_cid"]
    helper = single_suffix_function(context["functions"], suffix, f"{cid} {field} setter")
    require(function_sha256(helper) == expected_hash, f"{cid} {field} setter digest drift")
    if nullable:
        require(len(helper.lines) == 13, f"{cid} nullable tick setter shape")
        require_instruction(helper, 1, "local.get $p1", f"{cid} tick value guard")
        require(normalized(helper.lines[2]).startswith("if "), f"{cid} tick nonzero branch")
        receiver, key, value, convert, set_index = 3, 4, 5, 6, 7
        require_call(helper, 11, "Entity#unset", f"{cid} tick null unset")
    else:
        require(len(helper.lines) == 6, f"{cid} {field} setter shape")
        receiver, key, value, convert, set_index = 1, 2, 3, 4, 5
    require_instruction(helper, receiver, "local.get $p0", f"{cid} {field} receiver")
    require(decoded_constant(helper.lines[key], context["memory"]) == field, f"{cid} {field} decoded key")
    require_instruction(helper, value, "local.get $p1", f"{cid} {field} value")
    require_call(helper, convert, "Value.fromBigInt", f"{cid} {field} Value conversion")
    require(call_name(helper.lines[set_index]) == LEGACY_MAP_SET, f"{cid} {field} TypedMap set")
    return {"function": helper.name, "body_sha256": function_sha256(helper), "decoded_field_key": field, "nullable_nonzero_set_branch": nullable, "misleading_deduplicated_symbol_name": misleading, "symbol_name_used_as_semantic_authority": False, "receiver_key_value_to_typed_map_set_machine_proven": True}


def prove_modern_prefix_and_guard(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    memory = context["memory"]
    entity_sites = {"Bundle": 4, "Factory": 17, "Pool": 32}
    locals_by_entity: dict[str, str] = {}
    traps = []
    for entity, site in entity_sites.items():
        require(call_name(handler.lines[site]) == STORE_GET, f"{cid} {entity} store.get")
        constant_index = site - (4 if entity == "Pool" else 2)
        require(decoded_constant(handler.lines[constant_index], memory) == entity, f"{cid} {entity} target")
        if entity == "Pool":
            require_instruction(handler, site - 3, "local.get $p0", f"{cid} Pool event address")
            require_instruction(handler, site - 2, "i32.load", f"{cid} Pool event address load")
            require_call(handler, site - 1, "typeConversion.bytesToHex", f"{cid} Pool address conversion")
        entity_local = local_name(handler.lines[site + 1], "tee")
        require(entity_local is not None, f"{cid} {entity} result local")
        locals_by_entity[entity] = entity_local
        require_instruction(handler, site + 2, "i32.eqz", f"{cid} {entity} missing check")
        require(normalized(handler.lines[site + 3]).startswith("if "), f"{cid} {entity} missing branch")
        end = V2.matching_wat_end(handler.lines, site + 3, f"{cid} {entity} missing branch")
        branch = [normalized(line) for line in handler.lines[site + 4:end]]
        require(len(branch) == 6 and branch[-1] == "unreachable", f"{cid} {entity} closed trap shape")
        require(sum((call_name(handler.lines[i]) or "").endswith(("builtins/abort", "env/abort")) for i in range(site + 4, end)) == 1, f"{cid} {entity} abort count")
        traps.append({"entity": entity, "store_get_relative_wat_line": site, "result_local": entity_local, "missing_path_closed_trap": True, "successful_continuation_requires_nonzero_entity": True})
    pool_local = locals_by_entity["Pool"]
    require_instruction(handler, 43, f"local.get {pool_local}", f"{cid} excluded Pool receiver")
    require_call(handler, 44, "Pool#get:id", f"{cid} excluded Pool id")
    require(decoded_constant(handler.lines[45], memory) == "0x9663f2ca0454accad3e094448ea6f77443880454", f"{cid} excluded Pool ID")
    require_call(handler, 46, "String.__eq", f"{cid} excluded Pool comparison")
    require(normalized(handler.lines[47]).startswith("if ") and normalized(handler.lines[48]) == "return", f"{cid} excluded Pool early return")
    require(decoded_constant(handler.lines[50], memory) == "Token" and decoded_constant(handler.lines[55], memory) == "Token", f"{cid} Token targets")
    require(call_name(handler.lines[53]) == STORE_GET and call_name(handler.lines[58]) == STORE_GET, f"{cid} Token loads")
    token0 = local_name(handler.lines[54], "set")
    token1 = local_name(handler.lines[59], "tee")
    require(token0 is not None and token1 is not None, f"{cid} Token locals")
    require_instruction(handler, 60, "i32.const 0", f"{cid} Token guard zero")
    require_instruction(handler, 61, f"local.get {token0}", f"{cid} Token0 guard")
    require_instruction(handler, 62, "select", f"{cid} two-token select")
    require(normalized(handler.lines[63]).startswith("if "), f"{cid} selected update guard")
    guard_end = V2.matching_wat_end(handler.lines, 63, f"{cid} selected update guard")
    require(normalized(handler.lines[guard_end - 1]) != "else", f"{cid} token guard acquired else")
    return {"required_entity_traps": traps, "loaded_pool_local": pool_local, "pool_address_conversion_import": MINT.prove_bytes_to_hex_import(context, call_name(handler.lines[31]) or ""), "excluded_pool_early_return": True, "excluded_pool_id": "0x9663f2ca0454accad3e094448ea6f77443880454", "token0_local": token0, "token1_local": token1, "selected_update_guard_start_index": 63, "selected_update_guard_end_index": guard_end, "missing_either_token_skips_selected_body_on_normal_return": True}


def prove_legacy_prefix(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    require_instruction(handler, 6, "local.get $p0", f"{cid} event address")
    require_instruction(handler, 7, "i32.load", f"{cid} event address load")
    require_call(handler, 8, "typeConversion.bytesToHex", f"{cid} address conversion")
    require_call(handler, 9, "schema/Pool.load", f"{cid} Pool load")
    pool_local = local_name(handler.lines[10], "tee")
    require(pool_local is not None, f"{cid} Pool local")
    require_call(handler, 11, "Pool#get:id", f"{cid} excluded Pool id")
    require(decoded_constant(handler.lines[12], context["memory"]) == "0x9663f2ca0454accad3e094448ea6f77443880454", f"{cid} excluded Pool ID")
    require_call(handler, 13, "String.__eq", f"{cid} excluded Pool compare")
    require(normalized(handler.lines[14]).startswith("if ") and normalized(handler.lines[15]) == "return", f"{cid} excluded Pool return")
    return {"loaded_pool_local": pool_local, "pool_address_conversion_import": MINT.prove_bytes_to_hex_import(context, call_name(handler.lines[8]) or ""), "event_address_to_pool_load_machine_proven": True, "excluded_pool_early_return": True, "missing_pool_behavior_proven": False, "missing_token_behavior_proven": False, "normal_completion_scope_only": True}


def prove_modern_fields(context: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    memory = context["memory"]
    pool_loaded = control["loaded_pool_local"]
    liquidity_key = next(
        (i for i, line in enumerate(handler.lines) if decoded_constant(line, memory) == "liquidity"),
        None,
    )
    sqrt_key = next(
        (i for i, line in enumerate(handler.lines) if decoded_constant(line, memory) == "sqrtPrice"),
        None,
    )
    require(liquidity_key is not None, f"{cid} selected liquidity key missing")
    require(sqrt_key is not None, f"{cid} selected sqrtPrice key missing")
    liquidity_set = liquidity_key + 2
    sqrt_set = sqrt_key + 2
    tick_set = single_call(handler, "schema/Pool#set:tick", f"{cid} selected tick setter")
    require((liquidity_set, tick_set, sqrt_set) == (784, 803, 834), f"{cid} selected setter positions")
    pool_local = local_name(handler.lines[liquidity_set - 3])
    require(pool_local is not None, f"{cid} selected Pool local")
    identity = next((i for i in range(1, liquidity_set) if normalized(handler.lines[i]) == f"local.get {pool_loaded}" and local_name(handler.lines[i + 1], "tee") == pool_local), None)
    require(identity is not None, f"{cid} loaded Pool to selected Pool identity copy")
    require_instruction(handler, liquidity_set - 3, f"local.get {pool_local}", f"{cid} liquidity receiver")
    require(call_name(handler.lines[liquidity_set]) == MODERN_MAP_SET, f"{cid} liquidity TypedMap set")
    require_instruction(handler, tick_set - 9, f"local.get {pool_local}", f"{cid} tick receiver")
    require_instruction(handler, sqrt_set - 3, f"local.get {pool_local}", f"{cid} sqrtPrice receiver")
    require(call_name(handler.lines[sqrt_set]) == MODERN_MAP_SET, f"{cid} sqrtPrice TypedMap set")
    specs = {
        "liquidity": (liquidity_set, 5, "toBigInt", liquidity_set - 17, liquidity_set - 15),
        "tick": (tick_set, 6, "toI32", tick_set - 4, tick_set - 2),
        "sqrtPrice": (sqrt_set, 4, "toBigInt", sqrt_set - 17, sqrt_set - 15),
    }
    wrapper_shapes = {
        "liquidity": (754, 757, 761, 762, 763),
        "tick": (785, 788, 792, 793, 795),
        "sqrtPrice": (804, 807, 811, 812, 813),
    }
    fields: dict[str, Any] = {}
    for field, (setter, param, conversion, get_index, conversion_index) in specs.items():
        allocation, wrapper_tee, event_get, event_store, array_source = wrapper_shapes[field]
        require_instruction(handler, allocation, "i32.const 4", f"{cid} {field} wrapper size")
        require_call(handler, allocation + 2, "~lib/rt/stub/__new", f"{cid} {field} wrapper allocation")
        wrapper_local = local_name(handler.lines[wrapper_tee], "tee")
        require(wrapper_local is not None, f"{cid} {field} wrapper local")
        require_instruction(handler, event_get, "local.get $p0", f"{cid} {field} original event")
        require_instruction(handler, event_store, "i32.store", f"{cid} {field} event into wrapper")
        require_instruction(handler, array_source, f"local.get {wrapper_local}", f"{cid} {field} wrapper array source")
        require_instruction(handler, get_index - 3, "i32.load", f"{cid} {field} wrapper event load")
        require_instruction(handler, get_index - 2, "i32.load offset=24", f"{cid} {field} event parameters load")
        require_instruction(handler, get_index - 1, f"i32.const {param}", f"{cid} {field} parameter index")
        require_call(handler, get_index, "EventParam>#__get", f"{cid} {field} parameter access")
        require_instruction(handler, get_index + 1, "i32.load offset=4", f"{cid} {field} EventParam Value")
        require_call(handler, conversion_index, f"Value#{conversion}", f"{cid} {field} conversion")
        fields[field] = {"event_parameter_index": param, "event_parameter_name": SELECTED_FIELDS[field]["event_parameter_name"], "event_parameter_type": SELECTED_FIELDS[field]["event_parameter_type"], "handler_parameter_get_wat_line": handler.start_line + get_index, "event_value_conversion": conversion, "wrapper_allocation_relative_wat_line": allocation, "fresh_wrapper_local": wrapper_local, "original_event_to_wrapper_to_parameter_array_machine_proven": True, "handler_setter_wat_line": handler.start_line + setter, "decoded_field_key": field, "selected_pool_local": pool_local, "loaded_pool_to_selected_receiver_identity_machine_proven": True, "receiver_key_value_flow_machine_proven": True}
    require_call(handler, tick_set - 1, "BigInt.fromI32", f"{cid} tick BigInt conversion")
    for setter in (liquidity_set, sqrt_set):
        require_instruction(handler, setter - 8, "i32.const 7", f"{cid} selected BigInt Value kind")
        require_instruction(handler, setter - 7, "i32.store", f"{cid} selected Value kind store")
        require_instruction(handler, setter - 4, "i64.store offset=8", f"{cid} selected Value payload store")
    tick_helper = single_suffix_function(context["functions"], "schema/Pool#set:tick", f"{cid} modern tick setter")
    expected_tick_hash = "c95e31c6de723b8d05f8767b1780d7d8f89db9ccae60769a517dd437603669a6" if context["profile"]["profile_id"] == "modern-base" else "d803f00c7d5a8d5155ab112239fa85cafd8bb2ef04879fd5d1bf8538658272e4"
    require(function_sha256(tick_helper) == expected_tick_hash and decoded_constant(tick_helper.lines[5], memory) == "tick", f"{cid} modern tick setter body")
    INITIALIZE.require_no_successful_path_local_reassignment(
        handler,
        pool_local,
        identity + 1,
        2602,
        f"{cid} selected Pool receiver",
    )
    return {"fields": fields, "setter_order": ["Pool.liquidity", "Pool.tick", "Pool.sqrtPrice"], "setter_indices": [liquidity_set, tick_set, sqrt_set], "loaded_pool_local": pool_loaded, "selected_pool_local": pool_local, "pool_identity_copy_relative_wat_line": identity, "event_value_to_bigint": MINT.prove_event_value_to_bigint(context), "event_value_to_i32": prove_event_value_to_i32(context), "tick_integer_conversion": prove_i32_to_bigint_object(context, "BigInt.fromI32", "4c114555a1593f084d3017c8c8505e8f8bfd8e7a8e20409c995ba021c7178803"), "legacy_symbol_alias_boundary": None}


def prove_legacy_fields(context: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    pool_local = control["loaded_pool_local"]
    require((single_call(handler, "PoolDayData#set:liquidity", f"{cid} liquidity alias"), single_call(handler, "schema/Pool#set:tick", f"{cid} tick"), single_call(handler, "schema/Pool#set:sqrtPrice", f"{cid} sqrt")) == (222, 228, 233), f"{cid} selected setter positions")
    wrappers = [220, 225, 231]
    for wrapper in wrappers:
        require_instruction(handler, wrapper - 1, "local.get $p0", f"{cid} wrapper event")
        require_call(handler, wrapper, "Initialize__Params#constructor", f"{cid} wrapper allocation")
    require_instruction(handler, 218, f"local.get {pool_local}", f"{cid} liquidity receiver")
    require_instruction(handler, 223, f"local.get {pool_local}", f"{cid} tick receiver")
    require_instruction(handler, 229, f"local.get {pool_local}", f"{cid} sqrt receiver")
    require_call(handler, 221, "Mint__Params#get:amount0", f"{cid} liquidity misleading getter")
    require_call(handler, 226, "Swap__Params#get:tick", f"{cid} tick getter")
    require_call(handler, 227, "ByteArray.fromI32", f"{cid} tick BigInt conversion")
    require_call(handler, 232, "Mint__Params#get:amount", f"{cid} sqrt misleading getter")
    getter_specs = {
        "liquidity": prove_legacy_getter(context, "Mint__Params#get:amount0", 5, "toBigInt", True),
        "tick": prove_legacy_getter(context, "Swap__Params#get:tick", 6, "toI32", False),
        "sqrtPrice": prove_legacy_getter(context, "Mint__Params#get:amount", 4, "toBigInt", True),
    }
    hashes = EXPECTED_LEGACY_SETTERS[context["profile"]["profile_id"]]
    setters = {
        "liquidity": prove_legacy_setter(context, "PoolDayData#set:liquidity", "liquidity", hashes[0], False, True),
        "tick": prove_legacy_setter(context, "schema/Pool#set:tick", "tick", hashes[1], True, False),
        "sqrtPrice": prove_legacy_setter(context, "schema/Pool#set:sqrtPrice", "sqrtPrice", hashes[2], False, False),
    }
    value = single_suffix_function(context["functions"], "Value.fromBigInt", f"{cid} Value.fromBigInt")
    bytearray = single_suffix_function(context["functions"], "ByteArray.fromI32", f"{cid} ByteArray.fromI32")
    require(function_sha256(value) == "d6229f3af9fbb690bcb4820127a2aaf953eebcf9785a26d7c01be7517973cc6b", f"{cid} Value.fromBigInt")
    require(len(value.lines) == 11, f"{cid} Value.fromBigInt shape")
    require_call(value, 2, "Value#constructor", f"{cid} Value.fromBigInt allocation")
    value_local = local_name(value.lines[3], "tee")
    require(value_local is not None, f"{cid} Value.fromBigInt result local")
    require_instruction(value, 4, "i32.const 7", f"{cid} Value.fromBigInt kind")
    require_instruction(value, 5, "i32.store", f"{cid} Value.fromBigInt kind store")
    require_instruction(value, 6, f"local.get {value_local}", f"{cid} Value.fromBigInt payload receiver")
    require_instruction(value, 7, "local.get $p0", f"{cid} Value.fromBigInt payload")
    require_instruction(value, 9, "i64.store offset=8", f"{cid} Value.fromBigInt payload store")
    require(
        normalized(value.lines[10]).startswith(f"local.get {value_local}"),
        f"{cid} Value.fromBigInt returned object",
    )
    INITIALIZE.require_no_local_reassignment(handler, pool_local, 10, 699, f"{cid} loaded Pool receiver")
    fields = {}
    for ordinal, field in enumerate(SELECTED_FIELDS):
        fields[field] = {"event_parameter_index": SELECTED_FIELDS[field]["event_parameter_index"], "event_parameter_name": SELECTED_FIELDS[field]["event_parameter_name"], "event_parameter_type": SELECTED_FIELDS[field]["event_parameter_type"], "handler_parameter_get_wat_line": handler.start_line + (221, 226, 232)[ordinal], "handler_setter_wat_line": handler.start_line + (222, 228, 233)[ordinal], "decoded_field_key": field, "selected_pool_local": pool_local, "parameter_getter": getter_specs[field], "setter": setters[field], "receiver_key_value_flow_machine_proven": True}
    return {"fields": fields, "setter_order": ["Pool.liquidity", "Pool.tick", "Pool.sqrtPrice"], "setter_indices": [222, 228, 233], "loaded_pool_local": pool_local, "selected_pool_local": pool_local, "event_value_to_bigint": MINT.prove_event_value_to_bigint(context), "event_value_to_i32": prove_event_value_to_i32(context), "tick_integer_conversion": prove_i32_to_bigint_object(context, "ByteArray.fromI32", "3ef30704c311054beff2e7feaec737e977c9f55e3128f77007ef5a8d138c8f1f"), "value_from_bigint": {"function": value.name, "body_sha256": function_sha256(value), "returned_object_local": value_local, "kind_7_pointer_payload_same_object_machine_proven": True}, "legacy_symbol_alias_boundary": "decoded operand indices, decoded keys, call operands, and receiver identity are authority; deduplicated getter/setter symbol names are not"}


def prove_mutation_inventory(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    functions = context["functions"]
    reachable = sorted(WRITER.reachable_functions(functions, context["handler"], tuple(context["indirect_targets"])))
    bodies = [{"function": name, "body_sha256": function_sha256(functions[name])} for name in reachable]
    writes = [{"function": name, "relative_wat_line": index, "instruction": normalized(line)} for name in reachable for index, line in enumerate(functions[name].lines) if POOL_RUNTIME.RUNTIME.is_direct_memory_write(line, normalized)]
    sets = [{"function": name, "relative_wat_line": index, "target": call_name(line)} for name in reachable for index, line in enumerate(functions[name].lines) if call_name(line) in {LEGACY_MAP_SET, MODERN_MAP_SET}]
    actual = (len(reachable), canonical_sha256(bodies), len(writes), canonical_sha256(writes), len(sets), canonical_sha256(sets))
    require(actual == EXPECTED_MUTATION_CLOSURE[profile], f"{context['mapping_cid']} exact reachable Swap mutation inventory drift")
    return {"reachable_function_count": actual[0], "reachable_function_body_inventory_sha256": actual[1], "reachable_direct_memory_write_site_count": actual[2], "reachable_direct_memory_write_site_inventory_sha256": actual[3], "reachable_typed_map_set_site_count": actual[4], "reachable_typed_map_set_site_inventory_sha256": actual[5], "selected_receiver_key_value_classified_typed_map_set_sites": 3, "unclassified_typed_map_set_site_count": actual[4] - 3, "direct_memory_write_sites_without_selected_payload_alias_proof": actual[2], "exact_retained_reachable_body_authority": True, "general_heap_alias_semantics_rederived": False}


def prove_saves_and_effects(context: dict[str, Any], fields: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    pool_local = fields["selected_pool_local"]
    saves = [i for i, line in enumerate(handler.lines) if (call_name(line) or "").endswith("schema/Pool#save")]
    require(len(saves) == 2, f"{cid} direct Pool.save count")
    first, second = saves
    require(fields["setter_indices"][-1] < first < second, f"{cid} selected/first/second save order")
    require_instruction(handler, first - 1, f"local.get {pool_local}", f"{cid} first Pool.save receiver")
    require_instruction(handler, second - 1, f"local.get {pool_local}", f"{cid} second Pool.save receiver")
    depths = V2.wat_control_depths(handler.lines)
    expected_depth = 1 if context["profile"]["control_generation"] == "modern" else 0
    require(all(depths[i] == expected_depth for i in (*fields["setter_indices"], first, second)), f"{cid} selected/save control path")
    if expected_depth:
        require(control["selected_update_guard_start_index"] < fields["setter_indices"][0] < first < second < control["selected_update_guard_end_index"], f"{cid} selected/save guard dominance")
    transitive = INITIALIZE.recompute_transitive_store_evidence(context)
    actual = (transitive["reachable_function_count"], transitive["reachable_call_indirect_instruction_count"], tuple(transitive["closed_indirect_table_targets"]), transitive["reachable_store_set_site_count"], transitive["reachable_store_set_site_ids_sha256"])
    require(actual == EXPECTED_EFFECT_CLOSURE[context["profile"]["profile_id"]], f"{cid} exact transitive Swap store closure drift")
    expected_targets = ["Bundle", "Factory", "Pool", "PoolDayData", "PoolHourData", "Swap", "Tick", "TickDayData", "Token", "TokenDayData", "TokenHourData", "Transaction", "UniswapDayData"]
    require(transitive["reachable_store_set_targets"] == expected_targets and transitive["dynamic_reachable_store_set_target_count"] == 0 and transitive["unmodelled_store_mutation_host_import_count"] == 0, f"{cid} reachable store target drift")
    require([item["relative_wat_line"] for item in transitive["reachable_pool_save_calls"]] == saves, f"{cid} reachable Pool.save inventory")
    require(len(transitive["reachable_pool_store_set_sites"]) == 1, f"{cid} Pool store.set helper inventory")
    mutation = prove_mutation_inventory(context)
    return {"direct_pool_save_count": 2, "first_pool_save_relative_wat_line": first, "first_pool_save_wat_line": handler.start_line + first, "second_pool_save_relative_wat_line": second, "second_pool_save_wat_line": handler.start_line + second, "same_selected_pool_receiver_for_both_saves_machine_proven": True, "first_pool_save_after_all_three_selected_setters_machine_proven": True, "modern_guard_dominates_selected_setters_and_both_saves": expected_depth == 1, "reachable_in_memory_mutation_inventory": mutation, "transitive_store_evidence": transitive, "reachable_store_set_targets": expected_targets, "no_later_selected_field_overwrites_proven": False, "selected_persistence_proven": False, "rollback_and_post_fatal_semantics_proven": False}


def prove_pool_swap_core_wat_context(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    runtime = prove_runtime(context)
    capsule = runtime["public_collection_capsule"]
    control = prove_modern_prefix_and_guard(context) if generation == "modern" else prove_legacy_prefix(context)
    fields = prove_modern_fields(context, control) if generation == "modern" else prove_legacy_fields(context, control)
    effects = prove_saves_and_effects(context, fields, control)
    collection = capsule["typed_map_collection_runtime"] if generation == "modern" else capsule["typed_map_runtime"]
    return {"mapping_cid": cid, "profile_id": context["profile"]["profile_id"], "control_generation": generation, "retained_wasm": {"path": context["artifact_path"], "bytes": context["analysis"]["bytes"], "sha256": context["analysis"]["sha256"], "wat_sha256": context["analysis"]["wat_sha256"]}, "handler_binding": {"export": HANDLER_EXPORT, "exact_wat_export_target": context["handler"].name, "numeric_function_index": context["handler"].function_index, "body_sha256": function_sha256(context["handler"]), "wat_start_line": context["handler"].start_line, "wat_body_line_count": len(context["handler"].lines)}, "pool_runtime_binding": {"contract_version": POOL_RUNTIME_CONTRACT_VERSION, "artifact_selection_tuple": runtime["artifact_selection_tuple"], "same_wat_runtime_proof_sha256": canonical_sha256(runtime), "public_collection_capsule_sha256": canonical_sha256(capsule), "event_param_array_get": (capsule["indexed_collection"] if generation == "modern" else capsule["indexed_access_and_value"])["event_param_array_get"], "typed_map_set": collection["typed_map_set"], "same_context_runtime_capsule_recomputed": True}, "control_and_entity_boundary": control, "selected_field_flows": fields, "save_and_effect_closure": effects, "selected_handler_structural_wat_projection_complete": False, "complete_pool_swap_handler_semantics": False}


def build_proofs(contexts: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    swap_contexts = {cid: swap_context_from_mint(context) for cid, context in contexts.items()}
    proofs = sorted((prove_pool_swap_core_wat_context(context) for context in swap_contexts.values()), key=lambda item: item["profile_id"])
    require(len(proofs) == 8 and sum(item["control_generation"] == "legacy" for item in proofs) == 6, "Pool Swap proof population drift")
    return proofs, swap_contexts


def build_segments(matrix: dict[str, Any], v2: dict[str, Any], proofs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    catalog = {(item["entity"], item["field"]): item for item in v2["field_catalog"]}
    results = []
    expected_event = "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24)"
    for segment in matrix["segments"]:
        cid = segment["profile_bindings"]["pool"]["mapping_cid"]
        proof = proof_by_cid[cid]
        handler = next(item for item in segment["handlers"] if item["handler_id"] == HANDLER_ID)
        require(handler["mapping_cid"] == cid and handler["event"] == expected_event, f"{segment['segment_id']} Swap matrix binding")
        fields = []
        for field, definition in SELECTED_FIELDS.items():
            inherited = catalog[("Pool", field)]
            fields.append({"entity": "Pool", "field": field, "schema_type": definition["schema_type"], "event_parameter_index": definition["event_parameter_index"], "event_parameter_name": definition["event_parameter_name"], "event_parameter_type": definition["event_parameter_type"], "population_classification": "conditional", "selected_handler_call_flow_evidence": (f"if both Token entities exist, assign Swap.{definition['event_parameter_name']} to Pool.{field} and later call the first Pool.save; otherwise skip the guarded body" if proof["control_generation"] == "modern" else f"on normal legacy completion, assign decoded parameter {definition['event_parameter_index']} to Pool.{field} and later call the first Pool.save"), "complete_selected_handler_projection": False, "complete_entity_history": False, "cumulative_semantic_status": "digest_bound_swap_core_call_flow_evidence_incomplete", "v2_field_record_sha256": canonical_sha256(inherited), "residual_history_blocker": "later Swap effects, dynamic aliases, Graph rollback, and other Pool handlers are not closed"})
        semantic = {"handler_id": HANDLER_ID, "mapping_cid": cid, "profile_id": proof["profile_id"], "control_generation": proof["control_generation"], "control_and_entity_boundary": proof["control_and_entity_boundary"], "selected_field_flows": proof["selected_field_flows"], "save_and_effect_closure": proof["save_and_effect_closure"], "fields": fields, "selected_handler_projection_complete": False, "complete_pool_swap_handler_semantics": False, "complete_pool_entity_history": False}
        provenance = {"mapping_cid": cid, "retained_wasm": proof["retained_wasm"], "handler_binding": proof["handler_binding"], "proof_sha256": canonical_sha256(proof), "source_handler_record_sha256": canonical_sha256(handler)}
        results.append({"segment_id": segment["segment_id"], "network": segment["network"], "deployment": segment["deployment"], "start_block_inclusive": segment["start_block_inclusive"], "end_block_inclusive": segment["end_block_inclusive"], "semantic_surface": semantic, "semantic_surface_sha256": canonical_sha256(semantic), "provenance_surface": provenance, "provenance_surface_sha256": canonical_sha256(provenance), "execution_model": "undecided", "backfill_allowed": False})
    require(len(results) == 8 and sum(len(item["semantic_surface"]["fields"]) for item in results) == 24, "Pool Swap segment-field count")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = INITIALIZE.json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = INITIALIZE.json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        results.append({"left_segment_id": left["segment_id"], "right_segment_id": right["segment_id"], "scoped_semantic_equal": not semantic_paths, "scoped_semantic_diff_paths": semantic_paths, "provenance_equal": not provenance_paths, "provenance_diff_paths": provenance_paths, "left_semantic_surface_sha256": left["semantic_surface_sha256"], "right_semantic_surface_sha256": right["semantic_surface_sha256"], "left_provenance_surface_sha256": left["provenance_surface_sha256"], "right_provenance_surface_sha256": right["provenance_surface_sha256"], "complete_writer_semantics_compared": False, "boundary_state_compared": False, "graph_oracle_compared": False})
    require(len(results) == 28, "Pool Swap pairwise diff count")
    return results


def truth_boundary() -> dict[str, bool]:
    require(len(TRUE_FLAGS) == len(set(TRUE_FLAGS)) and len(FALSE_FLAGS) == len(set(FALSE_FLAGS)) and set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "Pool Swap truth-boundary declarations")
    return {**{key: True for key in TRUE_FLAGS}, **{key: False for key in FALSE_FLAGS}}


def load_sources(root: Path, *, recompute_wat: bool = True, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    pins = ((MINT_VERIFIER_PATH, MINT_VERIFIER_SHA256), (POOL_RUNTIME_VERIFIER_PATH, POOL_RUNTIME_VERIFIER_SHA256), (INITIALIZE_VERIFIER_PATH, INITIALIZE_VERIFIER_SHA256))
    for path, digest in pins:
        require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    contracts = ((MINT_CONTRACT_PATH, MINT_CONTRACT_SHA256), (POOL_RUNTIME_CONTRACT_PATH, POOL_RUNTIME_CONTRACT_SHA256), (INITIALIZE_CONTRACT_PATH, INITIALIZE_CONTRACT_SHA256))
    for path, digest in contracts:
        require((root / path).is_file() and raw_sha256(root / path) == digest, f"contract digest drift: {path}")
    mint_sources = MINT.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    mint_contract = MINT.verify_contract(root, sources=mint_sources, recompute_wat=False)
    require(mint_contract["contract_version"] == MINT_CONTRACT_VERSION and mint_contract["scope"]["cumulative_selected_field_count"] == 36 and mint_contract["scope"]["cumulative_residual_field_count"] == 230, "Mint source contract boundary drift")
    runtime_contract = load_json_strict(root / POOL_RUNTIME_CONTRACT_PATH)
    initialize_contract = load_json_strict(root / INITIALIZE_CONTRACT_PATH)
    require(runtime_contract["contract_version"] == POOL_RUNTIME_CONTRACT_VERSION, "Pool runtime version drift")
    require(initialize_contract["contract_version"] == INITIALIZE_CONTRACT_VERSION, "Initialize version drift")
    require(
        canonical_bytes(runtime_contract)
        == canonical_bytes(mint_sources["pool_runtime_contract"]),
        "direct Pool runtime contract differs from recomputed Mint dependency",
    )
    require(
        canonical_bytes(initialize_contract)
        == canonical_bytes(mint_sources["burn_sources"]["initialize_contract"]),
        "direct Pool Initialize contract differs from recomputed Mint dependency",
    )
    proofs, contexts = build_proofs(mint_sources["pool_wat_contexts"]) if recompute_wat else ([], {})
    return {"mint_sources": mint_sources, "mint_contract": mint_contract, "pool_runtime_contract": runtime_contract, "initialize_contract": initialize_contract, "v2_contract": mint_sources["v2_contract"], "pool_abi": verify_pool_abi(root), "pool_swap_core_proofs": proofs, "pool_wat_contexts": contexts}


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["pool_swap_core_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 8, "recomputed Pool Swap proofs required")
    mint_sources = sources["mint_sources"]
    matrix = mint_sources["burn_sources"]["initialize_sources"]["v2_sources"]["segment_writer_matrix"]
    segments = build_segments(matrix, sources["v2_contract"], proofs)
    diffs = build_segment_diffs(segments)
    residuals = {proof["profile_id"]: {"unclassified_typed_map_set_site_count": proof["save_and_effect_closure"]["reachable_in_memory_mutation_inventory"]["unclassified_typed_map_set_site_count"], "direct_memory_write_sites_without_selected_payload_alias_proof": proof["save_and_effect_closure"]["reachable_in_memory_mutation_inventory"]["direct_memory_write_sites_without_selected_payload_alias_proof"]} for proof in proofs}
    fixtures = [
        {"fixture": "handler export/body/index", "expected_rejection_layer": "canonical handler binding"},
        {"fixture": "ABI Swap parameter order/type", "expected_rejection_layer": "digest-pinned ABI signature"},
        {"fixture": "modern Bundle/Factory/Pool trap", "expected_rejection_layer": "required-entity closed-trap proof"},
        {"fixture": "modern excluded-Pool return or two-Token select", "expected_rejection_layer": "modern control boundary"},
        {"fixture": "parameter indices 5/6/4 or EventParam access", "expected_rejection_layer": "generation-specific parameter flow"},
        {"fixture": "legacy misleading getter/setter symbol substitution", "expected_rejection_layer": "decoded operand/key and exact call flow"},
        {"fixture": "selected receiver, key, Value kind, payload, or integer conversion", "expected_rejection_layer": "selected receiver-key-value flow"},
        {"fixture": "first/second Pool.save count/order/receiver", "expected_rejection_layer": "save-order and receiver proof"},
        {"fixture": "reachable helper body/direct write/TypedMap set", "expected_rejection_layer": "exact reachable mutation inventory"},
        {"fixture": "Graph store target/site/indirect closure", "expected_rejection_layer": "exact transitive store inventory"},
        {"fixture": "contract truth flag/count/proof/diff", "expected_rejection_layer": "deterministic contract projection"},
        {"fixture": "duplicate JSON key", "expected_rejection_layer": "strict JSON loader"},
    ]
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "retained-wat-selected-handler-call-flow-evidence-supplement",
        "scope": {"networks": ["mainnet", "base"], "segment_count": 8, "pool_mapping_count": 8, "handler": HANDLER_ID, "selected_fields": [f"Pool.{field}" for field in SELECTED_FIELDS], "selected_field_count": 3, "segment_field_call_flow_evidence_count": 24, "legacy_profile_count": 6, "modern_guarded_profile_count": 2, "pairwise_scoped_diff_count": 28, "inherited_mint_selected_field_count": 36, "cumulative_selected_field_count": 36, "inherited_mint_residual_field_count": 230, "cumulative_residual_field_count": 230, "reachable_effect_residuals_by_profile": residuals, "claim": "exact retained-WAT Pool.handleSwap call-flow evidence for liquidity<-parameter5, tick<-parameter6, and sqrtPrice<-parameter4 through the first Pool.save; complete Swap and persistence remain false"},
        "source_contracts": {
            "pool_mint": {"path": str(MINT_CONTRACT_PATH), "contract_version": MINT_CONTRACT_VERSION, "raw_sha256": MINT_CONTRACT_SHA256},
            "pool_mint_verifier": {"path": str(MINT_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": MINT_VERIFIER_SHA256},
            "pool_runtime": {"path": str(POOL_RUNTIME_CONTRACT_PATH), "contract_version": POOL_RUNTIME_CONTRACT_VERSION, "raw_sha256": POOL_RUNTIME_CONTRACT_SHA256},
            "pool_runtime_verifier": {"path": str(POOL_RUNTIME_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": POOL_RUNTIME_VERIFIER_SHA256},
            "pool_initialize": {"path": str(INITIALIZE_CONTRACT_PATH), "contract_version": INITIALIZE_CONTRACT_VERSION, "raw_sha256": INITIALIZE_CONTRACT_SHA256},
            "pool_initialize_verifier": {"path": str(INITIALIZE_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": INITIALIZE_VERIFIER_SHA256},
        },
        "pool_swap_abi": sources["pool_abi"],
        "authority_contract": {"semantic_authority": "retained deployed Pool mapping WASM and checksum-pinned WABT 1.0.35 WAT", "source_text_role": "corroboration only", "legacy_symbol_boundary": "deduplicated legacy function names can be misleading; only decoded indices, decoded keys, operand sequences, receiver identity, and pinned bodies are authoritative", "successful_handler_scope": "legacy evidence is normal-completion call flow; modern selected flow is guarded by both Token entities and follows required Bundle/Factory/Pool nonzero continuations", "save_boundary": "the first Pool.save follows the selected setters, but a second Pool.save and many later effects remain reachable", "effect_closure_rule": "pin the full reachable function-body, direct-memory-write, TypedMap-set, Graph store, and indirect-target inventories; unclassified baseline effects prevent persistence promotion", "host_boundary": "bytesToHex, numeric, Graph store, rollback, and post-fatal host semantics are not rederived", "mint_merge_base": "built on exact Pool Mint squash merge fa1c8d842712e53d363615062ecf1374e52bb854 after exact-head and merge-tree verification"},
        "toolchain": {"name": "WABT wasm2wat and wat2wasm", "version": WRITER.WABT_VERSION, "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-mapping-wasm>"], "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"]},
        "valid_wat_mutation_fixture_layers": fixtures,
        "mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {"field_count": 230, "pool": ["complete Swap semantics and all later effects are not classified", "two Pool saves are reachable; first-save order is call-flow evidence, not persistence", "dynamic keys, receiver aliases, direct-memory aliases, rollback, and post-fatal behavior remain open", "Factory creation and Pool Initialize, Mint, Burn, Flash, and Swap histories remain incomplete"], "execution": ["runtime population, boundary continuity, oracle/parity, package consumption, checkpoint, backfill, production, and readiness remain false"]},
        "truth_boundary": truth_boundary(),
    }


def verify_contract(root: Path, actual: dict[str, Any] | None = None, *, sources: dict[str, Any] | None = None, recompute_wat: bool = True, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    verified = sources or load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(verified)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"Pool Swap core contract missing: {CONTRACT_PATH}")
        actual = load_json_strict(path)
        require(path.read_text() == render(actual), "Pool Swap core contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Pool Swap core contract differs from generated proof")
    return expected


def write_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    sources = load_sources(root.resolve(), recompute_wat=True, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(sources)
    path = root.resolve() / CONTRACT_PATH
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
        result = write_contract(args.root, args.wasm2wat) if args.write_contract else verify_contract(args.root, wasm2wat=args.wasm2wat)
    except (VerificationError, MINT.VerificationError, INITIALIZE.VerificationError, POOL_RUNTIME.VerificationError, V2.VerificationError, WRITER.VerificationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"verified Uniswap V3 Pool Swap core state v1: {len(result['mapping_proofs'])} mappings, {result['scope']['segment_field_call_flow_evidence_count']} segment-field call-flow evidence records, {len(result['segment_diffs'])} diffs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
