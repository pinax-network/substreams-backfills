#!/usr/bin/env python3
"""Generate and fail-closed verify bounded Pool Swap fee-growth semantics v1."""

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
CONTRACT_PATH = Path("uniswap-v3/pool-swap-fee-growth/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-swap-fee-growth-semantics/v1"

FLASH_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-flash.py"
FLASH_VERIFIER_SHA256 = "1ffc7b8d9b6e96b320c7e8323693ce92da5d7f3dc7a0f871b02d2b7855abc81e"
FLASH_CONTRACT_PATH = Path("uniswap-v3/pool-flash/v1/contract.json")
FLASH_CONTRACT_SHA256 = "e90a292497f0771128a3e4859c8950b3496cbee9dcfd431334d19fe44926f696"
FLASH_CONTRACT_VERSION = "uniswap-v3-pool-flash-semantics/v1"

SWAP_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-swap-core.py"
SWAP_VERIFIER_SHA256 = "097047f6aac55b169c364cc0b4f51a1b4d655f103b77ed6dcc623a5daa3c77f8"
SWAP_CONTRACT_PATH = Path("uniswap-v3/pool-swap-core/v1/contract.json")
SWAP_CONTRACT_SHA256 = "5437e87329ae98eaf26e273903e53078a05c068c8be52f19a9673ed41cf4dd8b"
SWAP_CONTRACT_VERSION = "uniswap-v3-pool-swap-core-semantics/v1"

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

V2_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
V2_VERIFIER_SHA256 = "e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec"
V2_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
V2_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
V2_CONTRACT_VERSION = "uniswap-v3-segment-field-semantics/v2"

MATRIX_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-writer-matrix.py"
MATRIX_VERIFIER_SHA256 = "1e9055f66517c1dada37b6dadd4770fddf505f38d2578349c7a07b46e567fc2f"
MATRIX_CONTRACT_PATH = Path("uniswap-v3/segment-writer-matrix/v1/contract.json")
MATRIX_CONTRACT_SHA256 = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
MATRIX_CONTRACT_VERSION = "uniswap-v3-segment-writer-matrix/v1"

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

SELECTED_FIELDS = {
    "feeGrowthGlobal0X128": {
        "schema_type": "BigInt!",
        "method": "feeGrowthGlobal0X128",
        "wat_signature": "feeGrowthGlobal0X128():(uint256)",
        "abi_signature": "feeGrowthGlobal0X128()",
        "selector": "f3058399",
    },
    "feeGrowthGlobal1X128": {
        "schema_type": "BigInt!",
        "method": "feeGrowthGlobal1X128",
        "wat_signature": "feeGrowthGlobal1X128():(uint256)",
        "abi_signature": "feeGrowthGlobal1X128()",
        "selector": "46141319",
    },
}

EXPECTED_HANDLER = {
    "modern-base": (11423, 2961, "8a8979c7c57f0f36a3ac9a8331fc70f76e9160be417f905babfdd34bc9043ca6"),
    "modern-mainnet": (11422, 2790, "1c8e5d0b6057b4ab06677f3f0508faecc8d654d04c7dd73aa46bbe563d1da66e"),
    "legacy-mainnet-root": (7730, 791, "75b9903a7813d81a4a0315600426b9d1f238077b5f6480058ea66185ff915e92"),
    "legacy-mainnet-qmrv": (7752, 791, "ef1161336dbe8acf23bebacd3bcaad85b1045dd5738d5c914f39a865dd199873"),
    "legacy-base-root": (7757, 797, "88e5f3b60c48bea65a62164a6ac7685539bf8c40f922bbb1fa3d2661ca6a5d7b"),
    "legacy-mainnet-stable": (7746, 791, "65b44d7cc4df2fbb0d963111e6525358961d126bcd64c0654d8f8aad22ab2fa0"),
    "legacy-mainnet-stable-fee-tier-1": (7755, 791, "65b44d7cc4df2fbb0d963111e6525358961d126bcd64c0654d8f8aad22ab2fa0"),
    "legacy-mainnet-stable-fee-tier-100": (7755, 791, "65b44d7cc4df2fbb0d963111e6525358961d126bcd64c0654d8f8aad22ab2fa0"),
}

EXPECTED_SELECTED_SLICE = {
    "modern-base": (13122, 13186, "f026e4d986c1f0fe0be2379d39c4385b48ff2343fc5f8bbd22f0c157be67f053"),
    "modern-mainnet": (13121, 13185, "8234c770ec3cd4635fda2acd04ce99a5cc3f063d8395fa53797c9fbd250699ea"),
    "legacy-mainnet-root": (8212, 8226, "5f799e1b6a7833023256eac6abc8d40548e932620d42c96fdf93edc6a4f0f44b"),
    "legacy-mainnet-qmrv": (8234, 8248, "5f799e1b6a7833023256eac6abc8d40548e932620d42c96fdf93edc6a4f0f44b"),
    "legacy-base-root": (8239, 8253, "5f799e1b6a7833023256eac6abc8d40548e932620d42c96fdf93edc6a4f0f44b"),
    "legacy-mainnet-stable": (8228, 8242, "5f799e1b6a7833023256eac6abc8d40548e932620d42c96fdf93edc6a4f0f44b"),
    "legacy-mainnet-stable-fee-tier-1": (8237, 8251, "5f799e1b6a7833023256eac6abc8d40548e932620d42c96fdf93edc6a4f0f44b"),
    "legacy-mainnet-stable-fee-tier-100": (8237, 8251, "5f799e1b6a7833023256eac6abc8d40548e932620d42c96fdf93edc6a4f0f44b"),
}

EXPECTED_MODERN_POINTERS = {
    "modern-base": {
        "contract_local": "$l4",
        "fee0_result_local": "$l5",
        "fee1_result_local": "$l4",
        "payload_local": "$l21",
        "method0": 8304,
        "signature0": 17888,
        "args0": 17984,
        "method1": 8368,
        "signature1": 18016,
        "args1": 18112,
    },
    "modern-mainnet": {
        "contract_local": "$l3",
        "fee0_result_local": "$l4",
        "fee1_result_local": "$l3",
        "payload_local": "$l20",
        "method0": 10320,
        "signature0": 19840,
        "args0": 19936,
        "method1": 10384,
        "signature1": 19968,
        "args1": 20064,
    },
}

EXPECTED_LEGACY_HELPERS = {
    "legacy-base-root": {
        "call": (5244, 27, "29d34bf2347cafba41e4963bd1c445a6d6606cfbbea50117890a4aa48c66c637"),
        "getter0": (7648, 9, "ddcd6b55aca9631d2f2709eb7a2e635ecb5c165286824a71f737cb65ead4cb16"),
        "getter1": (7657, 9, "c25c6477cd7f3363cfa5e43bcb6c52f1fc72db816aeb0a44d1e34d424f8c2ff6"),
        "setter0": (2938, 6, "8e25f0fd3f3125f8c53468e2445f5e5e88badef5b294266ff481c56704b531d5"),
        "setter1": (2944, 6, "625f378d351ba196c744b40cfedbd3c4626210cdad98bb537301d48a5bcdbaec"),
    },
    "legacy-mainnet-root": {
        "call": (5180, 27, "5047cf6659e8ee768ba413b1c422f99b1e1630c7ad74fdc3dd05035f04a0beb4"),
        "getter0": (7630, 9, "b71236b252b9ef8d66a50fabdb69c30b76a81853ea6ee58e4b9777b6f76031bd"),
        "getter1": (7639, 9, "47b18dcd8bbcc211e7633178e91d6feb935eb9847e3ceef53d03c15f6735fd4b"),
        "setter0": (2906, 6, "04b6804f7d20ace523554000e0817edc4ad76af98fa446b167acddc8b6c8ffde"),
        "setter1": (2912, 6, "d7f0b3b59f4e9fa6f7892fa2be4fe672bd7eaf6c1581328f6a470e52cef372ee"),
    },
    "legacy-mainnet-qmrv": {
        "call": (5248, 27, "b6302a2239e767d1b2a7cd9288ac7d26c71eb250b74962d98840d78412a584ec"),
        "getter0": (7652, 9, "13a4f4153de1bde29e8f4b5756c6bcf240925adcc13856d5758b94c2460b2f2b"),
        "getter1": (7661, 9, "a1ddaca0a2cf853e7ba0b70a9a1c7faec02a71fc8af8f0aaa16da2b88b937919"),
        "setter0": (2906, 6, "617085b591dc0bc74f5aaa0b5867a1b07cb8f6d02b86507a09546594e632e2db"),
        "setter1": (2912, 6, "b11d5ed2bc4544630040b99e0cbc32adb85fc6a6bb8f353f1450907a8abcc2ab"),
    },
}
for _stable_profile in (
    "legacy-mainnet-stable",
    "legacy-mainnet-stable-fee-tier-1",
    "legacy-mainnet-stable-fee-tier-100",
):
    EXPECTED_LEGACY_HELPERS[_stable_profile] = {
        "call": (5242, 27, "9496462a468f01b2f67421b8993f2c2d14c4d77a92f21eb4e12e7e1ee18b70b4"),
        "getter0": (7646, 9, "c08775263dd857280e9814820e4ee4a28a504e0320ea9ca03bfa789e1aa31813"),
        "getter1": (7655, 9, "830e8423471b5fc3942a78bd3d46a1b4c49f6852bdcc763d543a7e25acf3cb3a"),
        "setter0": (2906, 6, "d9bdd7bdab8f11b7eee99f7b009ff014cd5d6d0a29ec006878fb425bdd2de83d"),
        "setter1": (2912, 6, "f5f961938fc7a28b9bfc537041f65229f641aeb77a4820fc4b88741c2a075a07"),
    }

EXPECTED_MUTATION_CLOSURE = {
    "modern-base": (111, "8d9c50fd41009f6853a1e0f131fae525a8ca3f47e3453106311e42277cba7c87", 630, "14696acbe20c11204e7ae76c0230e73cd0dfeca8e705364a90cdcfc1c3c8b12e", 197, "af107606b765c57b0ad2e7016eec87c5889ed2d5006287040e987029d29f2b75"),
    "modern-mainnet": (111, "a024b3dfd9436fec76fda018f677fb3a3d3a447e34a5239af77e0913253e5eb4", 628, "10b599c4e4d2f76f80adc1930ed052b956009fb023db5955ba288230c2867896", 197, "06652f3a81ca5eb1fedd588ba8f7700d8e67f1ebab12c6462954e861cce02940"),
    "legacy-base-root": (197, "dadda3c6c582d663832b29ab217717779306574ccc568f88dbf993e6a8a4c538", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-mainnet-root": (197, "049f52cbd9cc75d2b7c7539e17329b602b6e4cb5d5d1ae6b3b023b4e9ce0754f", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "0bc76d26cc5d5fa9c2e34ef0f424d145ba65ddd376a967d9f6a1ae9a0d150aa2"),
    "legacy-mainnet-qmrv": (197, "f058a3f84680e3d9a81c048de89ce33cb4d9a824e1c8ed8235a241143ddb5c26", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-mainnet-stable": (197, "f08e06f0d1ac427f6bd75e153d31b00e3abd1100fa35710b7841bb610db33d1d", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-mainnet-stable-fee-tier-1": (197, "99e336dc1d28185f3f3bdd1805965666500f60c6c9645cfbabe450692202b9df", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
    "legacy-mainnet-stable-fee-tier-100": (197, "ca8707860c31c53c6be4b8b5e0b01b505d1ba4f8df76e6ac3120f739e0cc6115", 185, "00430fdefb56214a0a2195743eeb43070cc273f8bec50cb34da188f07b823e8f", 60, "c74978e5aaa7e5e809601494df61ebd5c0981216fda3a4e3a314ca4352db6998"),
}

STORE_TARGETS = [
    "Bundle", "Factory", "Pool", "PoolDayData", "PoolHourData", "Swap", "Tick",
    "TickDayData", "Token", "TokenDayData", "TokenHourData", "Transaction", "UniswapDayData",
]

TRUE_FLAGS = (
    "flash_contract_recomputed_and_pinned",
    "swap_contract_recomputed_and_pinned",
    "mint_contract_recomputed_and_pinned",
    "initialize_contract_recomputed_and_pinned",
    "pool_runtime_contract_recomputed_and_pinned",
    "segment_field_v2_contract_recomputed_and_pinned",
    "segment_writer_matrix_contract_recomputed_and_pinned",
    "all_eight_same_wat_runtime_capsules_recomputed",
    "shared_pool_swap_abi_verified",
    "both_fee_growth_selectors_verified",
    "all_eight_pool_swap_handler_bindings_verified",
    "all_eight_selected_slice_digests_verified",
    "all_sixteen_ordered_call_decode_flows_verified",
    "all_sixteen_selected_receiver_key_value_flows_verified",
    "all_eight_value_to_bigint_kind_and_trap_shapes_verified",
    "all_eight_nontry_null_trap_boundaries_verified",
    "both_modern_required_prefix_traps_verified",
    "both_modern_two_token_guard_skip_paths_verified",
    "all_eight_excluded_pool_returns_verified",
    "all_eight_second_pool_save_orders_verified",
    "all_eight_no_branch_to_second_save_paths_verified",
    "all_eight_exact_reachable_mutation_inventories_bound",
    "all_eight_exact_transitive_store_inventories_bound",
    "all_eight_reachable_store_target_sets_bound",
    "all_sixteen_segment_field_call_flow_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "cumulative_selected_field_count_remains_36",
    "cumulative_residual_field_count_remains_230",
    "canonical_flash_merge_base_verified",
)

FALSE_FLAGS = (
    "pool_swap_fee_growth_semantics_complete",
    "pool_swap_semantics_complete",
    "pool_swap_fee_growth_output_implemented",
    "selected_persistence_proven",
    "no_later_selected_field_overwrites_proven",
    "complete_pool_entity_history",
    "legacy_factory_initialization_closed",
    "all_stored_fields_exact",
    "bytes_to_hex_host_semantics_rederived",
    "numeric_host_semantics_rederived",
    "imported_host_semantics_rederived",
    "host_eth_call_semantics_rederived",
    "host_call_block_pointer_semantics_rederived",
    "host_call_error_classification_rederived",
    "graph_store_host_semantics_rederived",
    "general_heap_alias_semantics_rederived",
    "direct_payload_alias_safety_proven",
    "graph_handler_rollback_proven_by_retained_wat",
    "post_fatal_execution_modeled",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "runtime_population_complete",
    "writer_package_consumes_projection",
    "configured_package_identity_bound",
    "boundary_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "checkpoint_authority",
    "issue_37_flash_implementation_criterion_complete",
    "issue_38_complete_field_history_criterion_complete",
    "backfill_ready",
    "production_ready",
    "deployment_authority",
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


FLASH = load_module("uniswap_v3_pool_flash_for_swap_fee_growth", FLASH_VERIFIER_PATH, FLASH_VERIFIER_SHA256)
SWAP = FLASH.SWAP
MINT = FLASH.MINT
INITIALIZE = FLASH.INITIALIZE
POOL_RUNTIME = FLASH.POOL_RUNTIME
V2 = FLASH.V2
WRITER = FLASH.WRITER


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


def require_instruction(function: Any, index: int, expected: str, field: str) -> None:
    INITIALIZE.require_instruction(function, index, expected, field)


def require_call(function: Any, index: int, suffix: str, field: str) -> None:
    INITIALIZE.require_call(function, index, suffix, field)


def require_exact_call(function: Any, index: int, target: str, field: str) -> None:
    INITIALIZE.require_exact_call(function, index, target, field)


def require_i32_const(function: Any, index: int, value: int, field: str) -> None:
    require_instruction(function, index, f"i32.const {value}", field)


def read_u32(memory: bytearray, offset: int) -> int:
    require(0 <= offset <= len(memory) - 4, f"memory u32 offset out of range: {offset}")
    return int.from_bytes(memory[offset : offset + 4], "little")


def verify_pool_abi(root: Path) -> dict[str, Any]:
    swap = SWAP.verify_pool_abi(root)
    flash = FLASH.verify_pool_abi(root)
    for key, expected in (
        ("cid", POOL_ABI_CID), ("path", str(POOL_ABI_PATH)),
        ("bytes", POOL_ABI_BYTES), ("sha256", POOL_ABI_SHA256),
    ):
        require(swap[key] == expected and flash[key] == expected, f"Pool ABI {key} drift")
    require([item["name"] for item in flash["functions"]] == list(SELECTED_FIELDS), "fee-growth ABI function order drift")
    require(
        flash["selectors"]
        == [{"abi_signature": value["abi_signature"], "selector": value["selector"]} for value in SELECTED_FIELDS.values()],
        "fee-growth selectors drift",
    )
    return {
        "cid": POOL_ABI_CID,
        "path": str(POOL_ABI_PATH),
        "bytes": POOL_ABI_BYTES,
        "sha256": POOL_ABI_SHA256,
        "event": swap["event"],
        "functions": flash["functions"],
        "selectors": flash["selectors"],
    }


def fee_growth_context_from_swap(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = WRITER.resolve_handler(context["functions"], context["exports"], HANDLER_EXPORT)
    binding = context["analysis"]["registered_handlers"][HANDLER_EXPORT]
    require(handler.name == context["analysis"]["registered_handler_export_targets"][HANDLER_EXPORT], f"{cid} Swap export target drift")
    require(handler.function_index == binding["wat_function_index"], f"{cid} Swap function index drift")
    require(function_sha256(handler) == binding["body_sha256"], f"{cid} Swap analysis body drift")
    profile = context["profile"]["profile_id"]
    require((handler.start_line, len(handler.lines), function_sha256(handler)) == EXPECTED_HANDLER[profile], f"{cid} exact Swap handler drift")
    return {**context, "handler": handler}


def selected_slice_binding(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    handler = context["handler"]
    absolute_start, absolute_end, expected_digest = EXPECTED_SELECTED_SLICE[profile]
    start = absolute_start - handler.start_line
    end = absolute_end - handler.start_line
    require(0 <= start <= end < len(handler.lines), f"{profile} selected slice bounds")
    payload = "\n".join(normalized(line) for line in handler.lines[start : end + 1]) + "\n"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    require(digest == expected_digest, f"{profile} selected slice digest drift")
    return {
        "absolute_wat_start_line": absolute_start,
        "absolute_wat_end_line": absolute_end,
        "relative_wat_start_line": start,
        "relative_wat_end_line": end,
        "line_count": end - start + 1,
        "sha256": digest,
    }


def prove_value_to_bigint(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    helper = single_suffix_function(context["functions"], "ethereum.Value#toBigInt", f"{cid} Value#toBigInt")
    generation = context["profile"]["control_generation"]
    if generation == "modern":
        load0, kind0, compare0, load1, kind1, compare1, invalid, branch, abort, trap, end, payload, wrap = 2, 3, 4, 9, 10, 11, 13, 14, 19, 20, 21, 23, 24
        require(len(helper.lines) == 25, f"{cid} modern Value#toBigInt shape")
    else:
        load0, kind0, compare0, load1, kind1, compare1, invalid, branch, abort, trap, end, payload, wrap = 3, 4, 5, 11, 12, 13, 15, 16, 21, 22, 23, 25, 26
        require(len(helper.lines) == 27, f"{cid} legacy Value#toBigInt shape")
    require_instruction(helper, load0, "i32.load", f"{cid} Value kind 3 load")
    require_i32_const(helper, kind0, 3, f"{cid} Value kind 3")
    require_instruction(helper, compare0, "i32.eq", f"{cid} Value kind 3 compare")
    require_instruction(helper, load1, "i32.load", f"{cid} Value kind 4 load")
    require_i32_const(helper, kind1, 4, f"{cid} Value kind 4")
    require_instruction(helper, compare1, "i32.eq", f"{cid} Value kind 4 compare")
    require_instruction(helper, invalid, "i32.eqz", f"{cid} invalid Value kind")
    require(normalized(helper.lines[branch]).startswith("if "), f"{cid} invalid Value kind branch")
    require((call_name(helper.lines[abort]) or "").endswith(("builtins/abort", "env/abort")), f"{cid} invalid Value abort")
    require_instruction(helper, trap, "unreachable", f"{cid} invalid Value trap")
    require_instruction(helper, end, "end", f"{cid} invalid Value branch end")
    require_instruction(helper, payload, "i64.load offset=8", f"{cid} Value BigInt payload")
    require(normalized(helper.lines[wrap]).rstrip(")") == "i32.wrap_i64", f"{cid} Value BigInt pointer")
    require(INITIALIZE.effect_is_confined_to_closed_trap_branch(helper, abort, payload), f"{cid} Value abort branch")
    require(INITIALIZE.effect_is_confined_to_closed_trap_branch(helper, trap, payload), f"{cid} Value trap branch")
    return {
        "function": helper.name,
        "wat_start_line": helper.start_line,
        "wat_body_line_count": len(helper.lines),
        "body_sha256": function_sha256(helper),
        "accepted_retained_kinds": [3, 4],
        "invalid_kind_closed_abort_unreachable_machine_proven": True,
        "pointer_payload_offset": 8,
        "numeric_host_semantics_rederived": False,
    }


def prove_modern_inline_value(
    context: dict[str, Any],
    field: str,
    start: int,
    result_local: str,
    payload_local: str,
) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    require_instruction(handler, start, f"local.get {result_local}", f"{cid} {field} result payload")
    require_instruction(handler, start + 1, "i64.extend_i32_u", f"{cid} {field} payload widening")
    require_instruction(handler, start + 2, f"local.set {payload_local}", f"{cid} {field} payload local")
    require_i32_const(handler, start + 3, 16, f"{cid} {field} Value bytes")
    require_call(handler, start + 5, "stub/__new", f"{cid} {field} Value allocation")
    value_local = local_name(handler.lines[start + 6], "tee")
    require(value_local is not None, f"{cid} {field} Value local")
    require_i32_const(handler, start + 7, 7, f"{cid} {field} Value kind")
    require_instruction(handler, start + 8, "i32.store", f"{cid} {field} Value kind store")
    require_instruction(handler, start + 9, f"local.get {value_local}", f"{cid} {field} payload receiver")
    require_instruction(handler, start + 10, f"local.get {payload_local}", f"{cid} {field} payload")
    require_instruction(handler, start + 11, "i64.store offset=8", f"{cid} {field} payload store")
    return {
        "value_local": value_local,
        "payload_local": payload_local,
        "value_kind": 7,
        "kind_7_pointer_payload_same_object_machine_proven": True,
    }


def prove_modern_flows(context: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile = context["profile"]["profile_id"]
    handler = context["handler"]
    memory = context["memory"]
    pointers = EXPECTED_MODERN_POINTERS[profile]
    contract_local = pointers["contract_local"]
    payload_local = pointers["payload_local"]
    loaded_pool = control["loaded_pool_local"]
    selected_pool = "$l1"

    require_instruction(handler, 533, f"local.get {loaded_pool}", f"{cid} loaded Pool identity")
    require_instruction(handler, 534, f"local.tee {selected_pool}", f"{cid} selected Pool identity")
    require_instruction(handler, 1699, "local.get $p0", f"{cid} Swap event contract address")
    require_instruction(handler, 1700, "i32.load", f"{cid} Swap event address load")
    require_instruction(handler, 1701, f"local.set {contract_local}", f"{cid} contract address local")
    require_i32_const(handler, 1702, 8, f"{cid} contract bytes")
    require_call(handler, 1704, "stub/__new", f"{cid} contract allocation")
    require(decoded_constant(handler.lines[1705], memory) == "Pool", f"{cid} Pool contract name")
    require_instruction(handler, 1706, f"local.get {contract_local}", f"{cid} Pool contract address")
    require_call(handler, 1707, "SmartContract#constructor", f"{cid} Pool contract constructor")
    require(local_name(handler.lines[1708], "tee") == contract_local, f"{cid} Pool contract local")

    for ordinal, base in enumerate((1709, 1721)):
        field = f"feeGrowthGlobal{ordinal}X128"
        definition = SELECTED_FIELDS[field]
        require_i32_const(handler, base, pointers[f"method{ordinal}"], f"{cid} {field} method pointer")
        require(decoded_constant(handler.lines[base], memory) == definition["method"], f"{cid} {field} method")
        require_i32_const(handler, base + 1, pointers[f"signature{ordinal}"], f"{cid} {field} signature pointer")
        require(decoded_constant(handler.lines[base + 1], memory) == definition["wat_signature"], f"{cid} {field} signature")
        require_i32_const(handler, base + 2, 0, f"{cid} {field} empty argument length")
        require_i32_const(handler, base + 3, 50, f"{cid} {field} argument array type")
        require_i32_const(handler, base + 4, pointers[f"args{ordinal}"], f"{cid} {field} argument array data")
        require_call(handler, base + 5, "rt/__newArray", f"{cid} {field} empty argument array")
        require_call(handler, base + 6, "SmartContract#call", f"{cid} {field} call")
        require_i32_const(handler, base + 7, 0, f"{cid} {field} result index")
        require_call(handler, base + 8, "EventParam>#__get", f"{cid} {field} result access")
        require_call(handler, base + 9, "ethereum.Value#toBigInt", f"{cid} {field} uint256 decode")
    require_instruction(handler, 1720, f"local.get {contract_local}", f"{cid} second call same contract")

    fee0_local = local_name(handler.lines[1719], "set")
    fee1_local = local_name(handler.lines[1731], "set")
    require(fee0_local == pointers["fee0_result_local"], f"{cid} fee0 result local")
    require(fee1_local == pointers["fee1_result_local"], f"{cid} fee1 result local")
    fee0_value = prove_modern_inline_value(context, "feeGrowthGlobal0X128", 1732, fee0_local, payload_local)
    fee1_value = prove_modern_inline_value(context, "feeGrowthGlobal1X128", 1748, fee1_local, payload_local)
    for field, receiver, key, value, setter in (
        ("feeGrowthGlobal0X128", 1744, 1745, 1746, 1747),
        ("feeGrowthGlobal1X128", 1760, 1761, 1762, 1763),
    ):
        require_instruction(handler, receiver, f"local.get {selected_pool}", f"{cid} {field} Pool receiver")
        require(decoded_constant(handler.lines[key], memory) == field, f"{cid} {field} decoded key")
        require_instruction(handler, value, f"local.get {fee0_value['value_local'] if field.endswith('0X128') else fee1_value['value_local']}", f"{cid} {field} Value")
        require_exact_call(handler, setter, MODERN_MAP_SET, f"{cid} {field} TypedMap set")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, fee0_local, 1719, 1732, f"{cid} fee0 result")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, fee1_local, 1731, 1748, f"{cid} fee1 result")
    return {
        "codegen_model": "inline",
        "contract_receiver_local": contract_local,
        "loaded_pool_local": loaded_pool,
        "selected_pool_local": selected_pool,
        "loaded_pool_to_selected_receiver_identity_relative_wat_lines": [533, 534],
        "call_order": list(SELECTED_FIELDS),
        "setter_order": [f"Pool.{field}" for field in SELECTED_FIELDS],
        "call_indices": [1715, 1727],
        "decode_indices": [1718, 1730],
        "setter_indices": [1747, 1763],
        "fields": {
            "feeGrowthGlobal0X128": {
                "method": SELECTED_FIELDS["feeGrowthGlobal0X128"]["method"],
                "wat_signature": SELECTED_FIELDS["feeGrowthGlobal0X128"]["wat_signature"],
                "selector": SELECTED_FIELDS["feeGrowthGlobal0X128"]["selector"],
                "call_relative_wat_line": 1715,
                "decode_index": 0,
                "decode_relative_wat_line": 1718,
                "result_local": fee0_local,
                "decoded_field_key": "feeGrowthGlobal0X128",
                "setter_relative_wat_line": 1747,
                "value_construction": fee0_value,
                "receiver_key_value_flow_machine_proven": True,
            },
            "feeGrowthGlobal1X128": {
                "method": SELECTED_FIELDS["feeGrowthGlobal1X128"]["method"],
                "wat_signature": SELECTED_FIELDS["feeGrowthGlobal1X128"]["wat_signature"],
                "selector": SELECTED_FIELDS["feeGrowthGlobal1X128"]["selector"],
                "call_relative_wat_line": 1727,
                "decode_index": 0,
                "decode_relative_wat_line": 1730,
                "result_local": fee1_local,
                "decoded_field_key": "feeGrowthGlobal1X128",
                "setter_relative_wat_line": 1763,
                "value_construction": fee1_value,
                "receiver_key_value_flow_machine_proven": True,
            },
        },
        "empty_argument_array_descriptors_machine_proven": True,
        "same_contract_receiver_for_both_calls_machine_proven": True,
        "ordered_call_decode_setter_flow_machine_proven": True,
        "legacy_symbol_alias_boundary": None,
    }


def prove_legacy_flows(context: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile = context["profile"]["profile_id"]
    handler = context["handler"]
    pool_local = control["loaded_pool_local"]
    require(pool_local == "$l1", f"{cid} legacy selected Pool local")
    require_instruction(handler, 482, "local.get $p0", f"{cid} Pool contract event")
    require_instruction(handler, 483, "i32.load", f"{cid} Pool contract address")
    require_call(handler, 484, "Pool.bind", f"{cid} Pool contract bind")
    contract_local = local_name(handler.lines[485], "tee")
    require(contract_local == "$l5", f"{cid} bound Pool contract local")
    require_call(handler, 486, "Pool#feeGrowthGlobal0X128", f"{cid} fee0 getter")
    require(local_name(handler.lines[487], "set") == "$l10", f"{cid} fee0 result local")
    require_instruction(handler, 488, f"local.get {contract_local}", f"{cid} fee1 same contract")
    require_call(handler, 489, "Pool#feeGrowthGlobal1X128", f"{cid} fee1 getter")
    require(local_name(handler.lines[490], "set") == "$l5", f"{cid} fee1 result local")
    require_instruction(handler, 491, f"local.get {pool_local}", f"{cid} fee0 Pool receiver")
    require_instruction(handler, 492, "local.get $l10", f"{cid} fee0 value")
    require_call(handler, 493, "PoolDayData#set:feeGrowthGlobal0X128", f"{cid} fee0 setter")
    require_instruction(handler, 494, f"local.get {pool_local}", f"{cid} fee1 Pool receiver")
    require_instruction(handler, 495, "local.get $l5", f"{cid} fee1 value")
    require_call(handler, 496, "PoolDayData#set:feeGrowthGlobal1X128", f"{cid} fee1 setter")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, "$l10", 487, 492, f"{cid} fee0 result")

    getters = {
        field: FLASH.prove_legacy_getter(context, field)
        for field in SELECTED_FIELDS
    }
    setters = {
        field: FLASH.prove_legacy_setter(context, field)
        for field in SELECTED_FIELDS
    }
    expected = EXPECTED_LEGACY_HELPERS[profile]
    for key, proof in (
        ("getter0", getters["feeGrowthGlobal0X128"]),
        ("getter1", getters["feeGrowthGlobal1X128"]),
        ("setter0", setters["feeGrowthGlobal0X128"]),
        ("setter1", setters["feeGrowthGlobal1X128"]),
    ):
        helper = context["functions"][proof["function"]]
        require((helper.start_line, len(helper.lines), function_sha256(helper)) == expected[key], f"{cid} {key} exact helper drift")
    argument_descriptors = []
    for field in SELECTED_FIELDS:
        helper = context["functions"][getters[field]["function"]]
        pointer_line = normalized(helper.lines[4])
        require(pointer_line.startswith("i32.const "), f"{cid} {field} argument pointer")
        pointer = int(pointer_line.split()[1])
        require(read_u32(context["memory"], pointer + 4) == 0, f"{cid} {field} nonempty argument array")
        require(read_u32(context["memory"], pointer) == pointer - 8, f"{cid} {field} argument data descriptor")
        argument_descriptors.append({"field": field, "array_pointer": pointer, "data_pointer": pointer - 8, "length": 0})
    return {
        "codegen_model": "wrapper",
        "contract_receiver_local": contract_local,
        "loaded_pool_local": pool_local,
        "selected_pool_local": pool_local,
        "call_order": list(SELECTED_FIELDS),
        "setter_order": [f"Pool.{field}" for field in SELECTED_FIELDS],
        "call_indices": [486, 489],
        "decode_indices": [8, 8],
        "setter_indices": [493, 496],
        "fields": {
            "feeGrowthGlobal0X128": {
                "call_relative_wat_line": 486,
                "result_local": "$l10",
                "setter_relative_wat_line": 493,
                "getter": getters["feeGrowthGlobal0X128"],
                "setter": setters["feeGrowthGlobal0X128"],
                "receiver_key_value_flow_machine_proven": True,
            },
            "feeGrowthGlobal1X128": {
                "call_relative_wat_line": 489,
                "result_local": "$l5",
                "setter_relative_wat_line": 496,
                "getter": getters["feeGrowthGlobal1X128"],
                "setter": setters["feeGrowthGlobal1X128"],
                "receiver_key_value_flow_machine_proven": True,
            },
        },
        "empty_argument_array_descriptors": argument_descriptors,
        "value_from_bigint": FLASH.prove_value_from_bigint(context),
        "same_contract_receiver_for_both_calls_machine_proven": True,
        "ordered_call_decode_setter_flow_machine_proven": True,
        "legacy_symbol_alias_boundary": "decoded method/signature, result index, decoded key, call operands, and receiver identity are authority; deduplicated getter/setter names are not",
    }


def prove_mutation_inventory(context: dict[str, Any], core: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    functions = context["functions"]
    reachable = sorted(WRITER.reachable_functions(functions, context["handler"], tuple(context["indirect_targets"])))
    bodies = [{"function": name, "body_sha256": function_sha256(functions[name])} for name in reachable]
    writes = [
        {"function": name, "relative_wat_line": index, "instruction": normalized(line)}
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if POOL_RUNTIME.RUNTIME.is_direct_memory_write(line, normalized)
    ]
    sets = [
        {"function": name, "relative_wat_line": index, "target": call_name(line)}
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if call_name(line) in {LEGACY_MAP_SET, MODERN_MAP_SET}
    ]
    actual = (len(reachable), canonical_sha256(bodies), len(writes), canonical_sha256(writes), len(sets), canonical_sha256(sets))
    require(actual == EXPECTED_MUTATION_CLOSURE[profile], f"{context['mapping_cid']} exact reachable Swap mutation inventory drift")
    inherited = core["save_and_effect_closure"]["reachable_in_memory_mutation_inventory"]
    require(inherited["selected_receiver_key_value_classified_typed_map_set_sites"] == 3, f"{profile} inherited Swap core classification drift")
    require(inherited["reachable_typed_map_set_site_count"] == actual[4], f"{profile} inherited TypedMap inventory drift")
    return {
        "reachable_function_count": actual[0],
        "reachable_function_body_inventory_sha256": actual[1],
        "reachable_direct_memory_write_site_count": actual[2],
        "reachable_direct_memory_write_site_inventory_sha256": actual[3],
        "reachable_typed_map_set_site_count": actual[4],
        "reachable_typed_map_set_site_inventory_sha256": actual[5],
        "inherited_swap_core_classified_typed_map_set_sites": 3,
        "selected_fee_growth_classified_typed_map_set_sites": 2,
        "cumulative_classified_typed_map_set_sites": 5,
        "unclassified_typed_map_set_site_count": actual[4] - 5,
        "direct_memory_write_sites_without_selected_payload_alias_proof": actual[2],
        "exact_retained_reachable_body_authority": True,
        "general_heap_alias_semantics_rederived": False,
        "direct_payload_alias_safety_proven": False,
    }


def prove_save_and_effects(context: dict[str, Any], flows: dict[str, Any], core: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    generation = context["profile"]["control_generation"]
    selected_pool = flows["selected_pool_local"]
    saves = [index for index, line in enumerate(handler.lines) if (call_name(line) or "").endswith("schema/Pool#save")]
    if generation == "modern":
        expected_saves = [1193, 2602]
    elif context["profile"]["profile_id"] == "legacy-base-root":
        expected_saves = [334, 705]
    else:
        expected_saves = [334, 699]
    require(saves == expected_saves, f"{cid} direct Pool.save inventory")
    first, second = saves
    require(first < flows["call_indices"][0] < flows["setter_indices"][0] < flows["setter_indices"][1] < second, f"{cid} first/calls/setters/second save order")
    require_instruction(handler, first - 1, f"local.get {selected_pool}", f"{cid} first Pool.save receiver")
    require_instruction(handler, second - 1, f"local.get {selected_pool}", f"{cid} second Pool.save receiver")
    depths = V2.wat_control_depths(handler.lines)
    expected_depth = 1 if generation == "modern" else 0
    selected_indices = (*flows["call_indices"], *flows["setter_indices"], second)
    require(all(depths[index] == expected_depth for index in selected_indices), f"{cid} selected call/setter/save control depth")
    forbidden = []
    for index in range(flows["setter_indices"][-1] + 1, second):
        instruction = normalized(handler.lines[index])
        operation = instruction.split()[0].lstrip("(") if instruction else ""
        if operation in {"return", "br", "br_if", "br_table"}:
            forbidden.append({"relative_wat_line": index, "instruction": instruction})
    require(not forbidden, f"{cid} successful-path bypass before second Pool.save")
    identity_line = 534 if generation == "modern" else 10
    INITIALIZE.require_no_successful_path_local_reassignment(handler, selected_pool, identity_line, second, f"{cid} selected Pool receiver")
    later_literals = [
        {"relative_wat_line": index, "field": decoded_constant(handler.lines[index], context["memory"])}
        for index in range(flows["setter_indices"][-1] + 1, second)
        if decoded_constant(handler.lines[index], context["memory"]) in SELECTED_FIELDS
    ]
    require(not later_literals, f"{cid} later literal fee-growth key before second save")
    if generation == "modern":
        guard_start = core["control_and_entity_boundary"]["selected_update_guard_start_index"]
        guard_end = core["control_and_entity_boundary"]["selected_update_guard_end_index"]
        require(guard_start < first < flows["call_indices"][0] < flows["setter_indices"][-1] < second < guard_end, f"{cid} modern token guard scope")

    transitive = INITIALIZE.recompute_transitive_store_evidence(context)
    actual_effect = (
        transitive["reachable_function_count"],
        transitive["reachable_call_indirect_instruction_count"],
        tuple(transitive["closed_indirect_table_targets"]),
        transitive["reachable_store_set_site_count"],
        transitive["reachable_store_set_site_ids_sha256"],
    )
    require(actual_effect == SWAP.EXPECTED_EFFECT_CLOSURE[context["profile"]["profile_id"]], f"{cid} exact transitive Swap store closure drift")
    require(transitive["reachable_store_set_targets"] == STORE_TARGETS, f"{cid} reachable store target drift")
    require(transitive["dynamic_reachable_store_set_target_count"] == 0, f"{cid} dynamic store target")
    require(transitive["unmodelled_store_mutation_host_import_count"] == 0, f"{cid} unmodelled store mutation import")
    require([item["relative_wat_line"] for item in transitive["reachable_pool_save_calls"]] == saves, f"{cid} Pool.save transitive inventory")
    require(canonical_bytes(transitive) == canonical_bytes(core["save_and_effect_closure"]["transitive_store_evidence"]), f"{cid} inherited transitive proof drift")
    return {
        "direct_pool_save_count": 2,
        "first_pool_save_relative_wat_line": first,
        "first_pool_save_wat_line": handler.start_line + first,
        "second_pool_save_relative_wat_line": second,
        "second_pool_save_wat_line": handler.start_line + second,
        "selected_fee_reads_follow_first_pool_save_machine_proven": True,
        "both_setters_precede_second_pool_save_machine_proven": True,
        "same_selected_pool_receiver_for_setters_and_second_save_machine_proven": True,
        "no_return_or_branch_between_second_setter_and_second_save_machine_proven": True,
        "no_later_literal_selected_field_key_before_second_save_machine_proven": True,
        "modern_token_guard_dominates_calls_setters_and_second_save": generation == "modern",
        "legacy_normal_completion_scope_only": generation == "legacy",
        "reachable_in_memory_mutation_inventory": prove_mutation_inventory(context, core),
        "transitive_store_evidence": transitive,
        "reachable_store_set_targets": STORE_TARGETS,
        "selected_persistence_proven": False,
        "no_later_selected_field_overwrites_proven": False,
        "dynamic_payload_alias_safety_proven": False,
        "rollback_and_post_fatal_semantics_proven": False,
    }


def prove_pool_swap_fee_growth_wat_context(context: dict[str, Any]) -> dict[str, Any]:
    context = fee_growth_context_from_swap(context)
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    core = SWAP.prove_pool_swap_core_wat_context(context)
    runtime = SWAP.prove_runtime(context)
    control = core["control_and_entity_boundary"]
    flows = prove_modern_flows(context, control) if generation == "modern" else prove_legacy_flows(context, control)
    call_boundary = FLASH.prove_smart_contract_call(context)
    if generation == "legacy":
        helper = context["functions"][call_boundary["function"]]
        require((helper.start_line, len(helper.lines), function_sha256(helper)) == EXPECTED_LEGACY_HELPERS[context["profile"]["profile_id"]]["call"], f"{cid} legacy SmartContract#call exact helper drift")
    else:
        expected = (8042, 60, "ffcc61df9cb20489c5c946669181d1be363cfc6acfd8af393bd821364876ebf3") if context["profile"]["profile_id"] == "modern-base" else (8041, 60, "663a09ece695ab1cebf46ffbc2fa3f96c5cc4276e68c76a9cee0fee4b5ea80f6")
        helper = context["functions"][call_boundary["function"]]
        require((helper.start_line, len(helper.lines), function_sha256(helper)) == expected, f"{cid} modern SmartContract#call exact helper drift")
    effects = prove_save_and_effects(context, flows, core)
    capsule = runtime["public_collection_capsule"]
    collection = capsule["typed_map_collection_runtime"] if generation == "modern" else capsule["typed_map_runtime"]
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
            "exact_wat_export_target": context["handler"].name,
            "numeric_function_index": context["handler"].function_index,
            "body_sha256": function_sha256(context["handler"]),
            "wat_start_line": context["handler"].start_line,
            "wat_body_line_count": len(context["handler"].lines),
            "selected_slice": selected_slice_binding(context),
        },
        "dependency_bindings": {
            "pool_swap_core_proof_sha256": canonical_sha256(core),
            "same_wat_runtime_proof_sha256": canonical_sha256(runtime),
            "public_collection_capsule_sha256": canonical_sha256(capsule),
            "event_param_array_get": (capsule["indexed_collection"] if generation == "modern" else capsule["indexed_access_and_value"])["event_param_array_get"],
            "typed_map_set": collection["typed_map_set"],
        },
        "control_and_entity_boundary": control,
        "contract_call_failure_boundary": call_boundary,
        "value_to_bigint_boundary": prove_value_to_bigint(context),
        "selected_field_flows": flows,
        "save_and_effect_closure": effects,
        "selected_fee_growth_structural_projection_machine_proven": True,
        "complete_pool_swap_handler_semantics": False,
        "complete_pool_entity_history": False,
    }


def build_proofs(contexts: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    fee_contexts = {cid: fee_growth_context_from_swap(context) for cid, context in contexts.items()}
    proofs = sorted((prove_pool_swap_fee_growth_wat_context(context) for context in fee_contexts.values()), key=lambda item: item["profile_id"])
    require(len(proofs) == 8 and sum(item["control_generation"] == "legacy" for item in proofs) == 6, "Pool Swap fee-growth proof population drift")
    return proofs, fee_contexts


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
            fields.append({
                "entity": "Pool",
                "field": field,
                "schema_type": definition["schema_type"],
                "population_classification": "conditional",
                "method": definition["method"],
                "wat_signature": definition["wat_signature"],
                "selector": definition["selector"],
                "selected_handler_call_flow_evidence": f"after the first Pool.save, ordered non-try {definition['method']} result index 0 reaches Pool.{field} and the same-receiver second Pool.save",
                "selected_fee_growth_structural_projection_machine_proven": True,
                "selected_persistence_proven": False,
                "complete_entity_history": False,
                "cumulative_semantic_status": "swap_fee_growth_second_save_call_flow_strengthened",
                "v2_field_record_sha256": canonical_sha256(inherited),
                "residual_history_blocker": "host call/store semantics, rollback, persistence, dynamic aliases, complete Swap, and legacy Factory initialization remain open",
            })
        semantic = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "control_generation": proof["control_generation"],
            "control_and_entity_boundary": proof["control_and_entity_boundary"],
            "contract_call_failure_boundary": proof["contract_call_failure_boundary"],
            "value_to_bigint_boundary": proof["value_to_bigint_boundary"],
            "selected_field_flows": proof["selected_field_flows"],
            "save_and_effect_closure": proof["save_and_effect_closure"],
            "fields": fields,
            "selected_fee_growth_structural_projection_machine_proven": True,
            "selected_persistence_proven": False,
            "complete_pool_swap_handler_semantics": False,
            "complete_pool_entity_history": False,
        }
        provenance = {
            "mapping_cid": cid,
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "dependency_bindings": proof["dependency_bindings"],
            "proof_sha256": canonical_sha256(proof),
            "source_handler_record_sha256": canonical_sha256(handler),
        }
        results.append({
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
        })
    require(len(results) == 8 and sum(len(item["semantic_surface"]["fields"]) for item in results) == 16, "Pool Swap fee-growth segment-field count")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = INITIALIZE.json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = INITIALIZE.json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        results.append({
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
        })
    require(len(results) == 28, "Pool Swap fee-growth pairwise diff count")
    return results


def truth_boundary() -> dict[str, bool]:
    require(len(TRUE_FLAGS) == len(set(TRUE_FLAGS)), "duplicate true flag")
    require(len(FALSE_FLAGS) == len(set(FALSE_FLAGS)), "duplicate false flag")
    require(set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "truth-boundary overlap")
    return {**{key: True for key in TRUE_FLAGS}, **{key: False for key in FALSE_FLAGS}}


def load_sources(root: Path, *, recompute_wat: bool = True, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    verifier_pins = (
        (FLASH_VERIFIER_PATH, FLASH_VERIFIER_SHA256), (SWAP_VERIFIER_PATH, SWAP_VERIFIER_SHA256),
        (MINT_VERIFIER_PATH, MINT_VERIFIER_SHA256), (POOL_RUNTIME_VERIFIER_PATH, POOL_RUNTIME_VERIFIER_SHA256),
        (INITIALIZE_VERIFIER_PATH, INITIALIZE_VERIFIER_SHA256), (V2_VERIFIER_PATH, V2_VERIFIER_SHA256),
        (MATRIX_VERIFIER_PATH, MATRIX_VERIFIER_SHA256),
    )
    for path, digest in verifier_pins:
        require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    contract_pins = (
        (FLASH_CONTRACT_PATH, FLASH_CONTRACT_SHA256), (SWAP_CONTRACT_PATH, SWAP_CONTRACT_SHA256),
        (MINT_CONTRACT_PATH, MINT_CONTRACT_SHA256), (POOL_RUNTIME_CONTRACT_PATH, POOL_RUNTIME_CONTRACT_SHA256),
        (INITIALIZE_CONTRACT_PATH, INITIALIZE_CONTRACT_SHA256), (V2_CONTRACT_PATH, V2_CONTRACT_SHA256),
        (MATRIX_CONTRACT_PATH, MATRIX_CONTRACT_SHA256),
    )
    for path, digest in contract_pins:
        require((root / path).is_file() and raw_sha256(root / path) == digest, f"contract digest drift: {path}")
    flash_sources = FLASH.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    flash_contract = FLASH.verify_contract(root, sources=flash_sources, recompute_wat=False)
    require(flash_contract["contract_version"] == FLASH_CONTRACT_VERSION, "Flash source contract version drift")
    swap_sources = flash_sources["swap_sources"]
    swap_contract = flash_sources["swap_contract"]
    require(swap_contract["contract_version"] == SWAP_CONTRACT_VERSION, "Swap source contract version drift")
    require(swap_contract["scope"]["cumulative_selected_field_count"] == 36 and swap_contract["scope"]["cumulative_residual_field_count"] == 230, "Swap cumulative boundary drift")
    mint_contract = flash_sources["mint_contract"]
    runtime_contract = flash_sources["pool_runtime_contract"]
    initialize_contract = flash_sources["initialize_contract"]
    v2_contract = flash_sources["v2_contract"]
    matrix_contract = flash_sources["matrix_contract"]
    require(mint_contract["contract_version"] == MINT_CONTRACT_VERSION, "Mint version drift")
    require(runtime_contract["contract_version"] == POOL_RUNTIME_CONTRACT_VERSION, "Pool runtime version drift")
    require(initialize_contract["contract_version"] == INITIALIZE_CONTRACT_VERSION, "Initialize version drift")
    require(v2_contract["contract_version"] == V2_CONTRACT_VERSION, "v2 version drift")
    require(matrix_contract["contract_version"] == MATRIX_CONTRACT_VERSION, "matrix version drift")
    proofs, contexts = build_proofs(swap_sources["pool_wat_contexts"]) if recompute_wat else ([], {})
    return {
        "flash_sources": flash_sources,
        "flash_contract": flash_contract,
        "swap_sources": swap_sources,
        "swap_contract": swap_contract,
        "mint_contract": mint_contract,
        "pool_runtime_contract": runtime_contract,
        "initialize_contract": initialize_contract,
        "v2_contract": v2_contract,
        "matrix_contract": matrix_contract,
        "pool_abi": verify_pool_abi(root),
        "pool_swap_fee_growth_proofs": proofs,
        "pool_wat_contexts": contexts,
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["pool_swap_fee_growth_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 8, "recomputed Pool Swap fee-growth proofs required")
    segments = build_segments(sources["matrix_contract"], sources["v2_contract"], proofs)
    diffs = build_segment_diffs(segments)
    residuals = {
        proof["profile_id"]: {
            "unclassified_typed_map_set_site_count": proof["save_and_effect_closure"]["reachable_in_memory_mutation_inventory"]["unclassified_typed_map_set_site_count"],
            "direct_memory_write_sites_without_selected_payload_alias_proof": proof["save_and_effect_closure"]["reachable_in_memory_mutation_inventory"]["direct_memory_write_sites_without_selected_payload_alias_proof"],
        }
        for proof in proofs
    }
    fixtures = [
        {"fixture": "artifact, handler export/index/start/count/body, or selected-slice digest", "expected_rejection_layer": "retained artifact and handler binding"},
        {"fixture": "ABI function, return type, signature, selector, or call order", "expected_rejection_layer": "digest-pinned ABI and ordered call flow"},
        {"fixture": "tryCall, changed ethereum.call import, or null-result fallthrough", "expected_rejection_layer": "non-try null closed-trap boundary"},
        {"fixture": "nonempty arguments, array descriptor, or result index", "expected_rejection_layer": "call operand and result access proof"},
        {"fixture": "removed or changed Value#toBigInt", "expected_rejection_layer": "retained kind 3/4 and invalid-kind trap proof"},
        {"fixture": "cross-wired result local, Pool receiver, key, Value kind, or payload", "expected_rejection_layer": "selected receiver-key-value flow"},
        {"fixture": "legacy deduplicated helper name used as authority", "expected_rejection_layer": "decoded operands, keys, and exact helper bodies"},
        {"fixture": "second Pool.save removed, moved, or receiver changed", "expected_rejection_layer": "same-receiver second-save proof"},
        {"fixture": "successful receiver reassignment or branch before second save", "expected_rejection_layer": "successful-path structural closure"},
        {"fixture": "modern required trap, token guard, or excluded-Pool return", "expected_rejection_layer": "inherited Swap control proof"},
        {"fixture": "reachable function, write, TypedMap set, store site, indirect target, or store target", "expected_rejection_layer": "exact full Swap effect inventory"},
        {"fixture": "truth flag, segment/field/diff record, or 36/230 ledger", "expected_rejection_layer": "deterministic contract projection"},
        {"fixture": "duplicate JSON key", "expected_rejection_layer": "strict JSON loader"},
    ]
    source_contracts = {
        "pool_flash": {"path": str(FLASH_CONTRACT_PATH), "contract_version": FLASH_CONTRACT_VERSION, "raw_sha256": FLASH_CONTRACT_SHA256},
        "pool_flash_verifier": {"path": str(FLASH_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": FLASH_VERIFIER_SHA256},
        "pool_swap_core": {"path": str(SWAP_CONTRACT_PATH), "contract_version": SWAP_CONTRACT_VERSION, "raw_sha256": SWAP_CONTRACT_SHA256},
        "pool_swap_core_verifier": {"path": str(SWAP_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": SWAP_VERIFIER_SHA256},
        "pool_mint": {"path": str(MINT_CONTRACT_PATH), "contract_version": MINT_CONTRACT_VERSION, "raw_sha256": MINT_CONTRACT_SHA256},
        "pool_mint_verifier": {"path": str(MINT_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": MINT_VERIFIER_SHA256},
        "pool_runtime": {"path": str(POOL_RUNTIME_CONTRACT_PATH), "contract_version": POOL_RUNTIME_CONTRACT_VERSION, "raw_sha256": POOL_RUNTIME_CONTRACT_SHA256},
        "pool_runtime_verifier": {"path": str(POOL_RUNTIME_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": POOL_RUNTIME_VERIFIER_SHA256},
        "pool_initialize": {"path": str(INITIALIZE_CONTRACT_PATH), "contract_version": INITIALIZE_CONTRACT_VERSION, "raw_sha256": INITIALIZE_CONTRACT_SHA256},
        "pool_initialize_verifier": {"path": str(INITIALIZE_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": INITIALIZE_VERIFIER_SHA256},
        "segment_field_v2": {"path": str(V2_CONTRACT_PATH), "contract_version": V2_CONTRACT_VERSION, "raw_sha256": V2_CONTRACT_SHA256},
        "segment_field_v2_verifier": {"path": str(V2_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": V2_VERIFIER_SHA256},
        "segment_writer_matrix": {"path": str(MATRIX_CONTRACT_PATH), "contract_version": MATRIX_CONTRACT_VERSION, "raw_sha256": MATRIX_CONTRACT_SHA256},
        "segment_writer_matrix_verifier": {"path": str(MATRIX_VERIFIER_PATH.relative_to(REPOSITORY)), "raw_sha256": MATRIX_VERIFIER_SHA256},
    }
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "retained-wat-pool-swap-fee-growth-second-save-call-flow-certificate",
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
            "pairwise_scoped_diff_count": 28,
            "inherited_swap_selected_field_count": 36,
            "cumulative_selected_field_count": 36,
            "inherited_swap_residual_field_count": 230,
            "cumulative_residual_field_count": 230,
            "reachable_effect_residuals_by_profile": residuals,
            "claim": "exact retained-WAT Pool.handleSwap event-address Pool bind, ordered feeGrowthGlobal0X128/1X128 non-try calls, result-zero BigInt decodes, uncrossed same-Pool setters, and same-receiver second Pool.save path across all eight profiles; host semantics, persistence, complete Swap, and readiness remain false",
        },
        "source_contracts": source_contracts,
        "pool_swap_fee_growth_abi": sources["pool_abi"],
        "authority_contract": {
            "semantic_authority": "retained deployed Pool mapping WASM and checksum-pinned WABT 1.0.35 WAT",
            "source_text_role": "corroboration only",
            "legacy_symbol_boundary": "deduplicated legacy getter and setter names can be misleading; decoded method/signature, result index, decoded key, operand sequence, receiver identity, and pinned bodies are authoritative",
            "successful_handler_scope": "normal continuation after non-try host calls; modern calls, setters, and second save are dominated by the two-Token guard and required Bundle/Factory/Pool nonzero paths",
            "call_boundary": "SmartContract#call invokes ethereum.call, traps on a null result, and returns the same nonzero result; imported call value, block-pointer, error, numeric, and rollback semantics are not rederived",
            "save_boundary": "the first Pool.save precedes both reads and the second same-receiver save follows both setters without return or branch; Graph persistence and dynamic aliases remain open",
            "effect_closure_rule": "pin full reachable function-body, direct-memory-write, TypedMap-set, Graph store, and indirect-target inventories; five TypedMap sites are classified cumulatively and all other alias semantics remain open",
            "canonical_flash_base": {
                "commit": "27dc439b150bbade46b6552d9e8611bc3c00da6f",
                "tree": "1345a42221c47c56783fbb0d5f3acbc6707a04ce",
                "status": "exact canonical PR 70 squash merge; merge tree equals the independently audited Flash candidate tree",
            },
        },
        "toolchain": {
            "name": "WABT wasm2wat and wat2wasm",
            "version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-mapping-wasm>"],
            "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"],
        },
        "valid_wat_mutation_fixture_layers": fixtures,
        "mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "field_count": 230,
            "pool_swap_fee_growth": [
                "complete Swap semantics, selected persistence, later dynamic aliases, complete Pool history, and legacy Factory initialization remain open",
                "bytes-to-hex, numeric, imported ethereum.call, Graph store, rollback, and post-fatal host semantics are not rederived",
                "the repository certificate does not itself populate a runtime projection or writer package",
            ],
            "execution": [
                "combined order, package identity, continuity, oracle/parity, checkpoint, backfill, deployment, production, and readiness remain false",
                "issues #37 and #38 gain no completed checkbox from this bounded call-flow slice",
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
        require(path.is_file(), f"Pool Swap fee-growth contract missing: {CONTRACT_PATH}")
        actual = load_json_strict(path)
        require(path.read_text() == render(actual), "Pool Swap fee-growth contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Pool Swap fee-growth contract differs from generated proof")
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
    except (
        VerificationError,
        FLASH.VerificationError,
        SWAP.VerificationError,
        MINT.VerificationError,
        INITIALIZE.VerificationError,
        POOL_RUNTIME.VerificationError,
        V2.VerificationError,
        WRITER.VerificationError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 Pool Swap fee-growth semantics v1: "
        f"{len(result['mapping_proofs'])} mappings, "
        f"{result['scope']['segment_field_call_flow_evidence_count']} segment-field call-flow records, "
        f"{len(result['segment_diffs'])} diffs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
