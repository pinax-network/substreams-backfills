#!/usr/bin/env python3
"""Generate and fail-closed verify bounded Uniswap V3 Pool Flash semantics v1."""

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
CONTRACT_PATH = Path("uniswap-v3/pool-flash/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-flash-semantics/v1"

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

HANDLER_ID = "Pool.handleFlash"
HANDLER_EXPORT = "handleFlash"
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
    "modern-base": (14384, 90, "3a02cdc807fc3a3d525777ac8a12f7362811107ebff9143d0807d92b1053d90d"),
    "modern-mainnet": (14212, 90, "8cbd1bb18c066bb774fc293cfeed0431440ff321f2689072b89d7033352e0b2e"),
    "legacy-mainnet-root": (8521, 24, "9266c00ba5ddc6c250e036b0ece37dba84ae648d62bc09159652aeba091f562d"),
    "legacy-mainnet-qmrv": (8543, 24, "9266c00ba5ddc6c250e036b0ece37dba84ae648d62bc09159652aeba091f562d"),
    "legacy-base-root": (8554, 24, "9266c00ba5ddc6c250e036b0ece37dba84ae648d62bc09159652aeba091f562d"),
    "legacy-mainnet-stable-fee-tier-100": (8546, 24, "9266c00ba5ddc6c250e036b0ece37dba84ae648d62bc09159652aeba091f562d"),
    "legacy-mainnet-stable-fee-tier-1": (8546, 24, "9266c00ba5ddc6c250e036b0ece37dba84ae648d62bc09159652aeba091f562d"),
    "legacy-mainnet-stable": (8537, 24, "9266c00ba5ddc6c250e036b0ece37dba84ae648d62bc09159652aeba091f562d"),
}

EXPECTED_SMART_CALL_HELPER = {
    "modern-base": (60, "ffcc61df9cb20489c5c946669181d1be363cfc6acfd8af393bd821364876ebf3"),
    "modern-mainnet": (60, "663a09ece695ab1cebf46ffbc2fa3f96c5cc4276e68c76a9cee0fee4b5ea80f6"),
    "legacy-mainnet-root": (27, "5047cf6659e8ee768ba413b1c422f99b1e1630c7ad74fdc3dd05035f04a0beb4"),
    "legacy-mainnet-qmrv": (27, "b6302a2239e767d1b2a7cd9288ac7d26c71eb250b74962d98840d78412a584ec"),
    "legacy-base-root": (27, "29d34bf2347cafba41e4963bd1c445a6d6606cfbbea50117890a4aa48c66c637"),
    "legacy-mainnet-stable-fee-tier-100": (27, "9496462a468f01b2f67421b8993f2c2d14c4d77a92f21eb4e12e7e1ee18b70b4"),
    "legacy-mainnet-stable-fee-tier-1": (27, "9496462a468f01b2f67421b8993f2c2d14c4d77a92f21eb4e12e7e1ee18b70b4"),
    "legacy-mainnet-stable": (27, "9496462a468f01b2f67421b8993f2c2d14c4d77a92f21eb4e12e7e1ee18b70b4"),
}

EXPECTED_MUTATION_CLOSURE = {
    "modern-base": (28, "5661230b7760cc01eac7775339e6512d65579faf9e28da9ce1c921d47e372d1e", 144, "7efa073eb123acd96bf02799708123aac889b19c221668bd54b9e7288e2509b1", 2, "7b194c4e2c5822226750a2852621f386d9908766e5afb4384b320d494be8addc"),
    "modern-mainnet": (28, "42a49736497d4b42ed0638ae7f18c55400c5909315445e6d2855ce163ef6b815", 144, "db90333df7b160b267b4c826e5d6d35fd3ceef3d78e06e4009e8e468f3003df8", 2, "7b194c4e2c5822226750a2852621f386d9908766e5afb4384b320d494be8addc"),
    "legacy-mainnet-root": (34, "6942af001d7e56e18a8bdc9635cde8d573c2920c1d0bbe19e93470b3c5f1bccf", 117, "94849d4808db0bbe92e325d6debd8e2b94161d449c64198a0bbe2c8c0c3356f3", 2, "2f9c5e63cb71df2d3161e7714b8385ec7849366d8a116159c30e05b35e799efe"),
    "legacy-mainnet-qmrv": (34, "e9e4f5dd3f2990391856df040a0b5bf8f9c8781c79f50da39eb5a4884066c664", 117, "94849d4808db0bbe92e325d6debd8e2b94161d449c64198a0bbe2c8c0c3356f3", 2, "2f9c5e63cb71df2d3161e7714b8385ec7849366d8a116159c30e05b35e799efe"),
    "legacy-base-root": (34, "e1f08a030196ff5adb636ee5f30f6de7b0e6e6a5b89b65df3dc20fc7c06aa45d", 117, "94849d4808db0bbe92e325d6debd8e2b94161d449c64198a0bbe2c8c0c3356f3", 2, "2f9c5e63cb71df2d3161e7714b8385ec7849366d8a116159c30e05b35e799efe"),
    "legacy-mainnet-stable-fee-tier-100": (34, "31f5e48b2adc0526f196e76deb731715ab99d9e5b7e07ff3155c19e984fe6fa8", 117, "94849d4808db0bbe92e325d6debd8e2b94161d449c64198a0bbe2c8c0c3356f3", 2, "2f9c5e63cb71df2d3161e7714b8385ec7849366d8a116159c30e05b35e799efe"),
    "legacy-mainnet-stable-fee-tier-1": (34, "31f5e48b2adc0526f196e76deb731715ab99d9e5b7e07ff3155c19e984fe6fa8", 117, "94849d4808db0bbe92e325d6debd8e2b94161d449c64198a0bbe2c8c0c3356f3", 2, "2f9c5e63cb71df2d3161e7714b8385ec7849366d8a116159c30e05b35e799efe"),
    "legacy-mainnet-stable": (34, "31f5e48b2adc0526f196e76deb731715ab99d9e5b7e07ff3155c19e984fe6fa8", 117, "94849d4808db0bbe92e325d6debd8e2b94161d449c64198a0bbe2c8c0c3356f3", 2, "2f9c5e63cb71df2d3161e7714b8385ec7849366d8a116159c30e05b35e799efe"),
}

EXPECTED_EFFECT_CLOSURE = {
    "modern-base": (28, 1, ("~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0",), 1, "d4f6b0a975f6782dc1059d48d2ec3a58b75e56738f8f0475c5c03c1581bb0878"),
    "modern-mainnet": (28, 1, ("~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0",), 1, "acd326ffa7046621c913b0e5a1ebcb17355bf6104b4204df54c724299ebe55ae"),
    "legacy-mainnet-root": (34, 0, (), 1, "acd326ffa7046621c913b0e5a1ebcb17355bf6104b4204df54c724299ebe55ae"),
    "legacy-mainnet-qmrv": (34, 0, (), 1, "acd326ffa7046621c913b0e5a1ebcb17355bf6104b4204df54c724299ebe55ae"),
    "legacy-base-root": (34, 0, (), 1, "acd326ffa7046621c913b0e5a1ebcb17355bf6104b4204df54c724299ebe55ae"),
    "legacy-mainnet-stable-fee-tier-100": (34, 0, (), 1, "acd326ffa7046621c913b0e5a1ebcb17355bf6104b4204df54c724299ebe55ae"),
    "legacy-mainnet-stable-fee-tier-1": (34, 0, (), 1, "acd326ffa7046621c913b0e5a1ebcb17355bf6104b4204df54c724299ebe55ae"),
    "legacy-mainnet-stable": (34, 0, (), 1, "acd326ffa7046621c913b0e5a1ebcb17355bf6104b4204df54c724299ebe55ae"),
}

TRUE_FLAGS = (
    "swap_contract_recomputed_and_pinned",
    "mint_contract_recomputed_and_pinned",
    "initialize_contract_recomputed_and_pinned",
    "pool_runtime_contract_recomputed_and_pinned",
    "segment_field_v2_contract_recomputed_and_pinned",
    "segment_writer_matrix_contract_recomputed_and_pinned",
    "all_eight_same_wat_runtime_capsules_recomputed",
    "shared_pool_flash_abi_verified",
    "both_fee_growth_selectors_verified",
    "all_eight_pool_flash_handler_bindings_verified",
    "all_sixteen_ordered_call_decode_flows_verified",
    "all_sixteen_selected_receiver_key_value_flows_verified",
    "all_eight_nontry_null_trap_boundaries_verified",
    "all_eight_same_path_call_setter_save_orders_verified",
    "all_eight_exact_reachable_mutation_inventories_bound",
    "all_eight_exact_transitive_store_inventories_bound",
    "all_eight_reachable_store_targets_exactly_pool",
    "all_eight_required_absent_flash_rows_bound",
    "all_sixteen_segment_field_call_flow_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "cumulative_selected_field_count_remains_36",
    "cumulative_residual_field_count_remains_230",
)

FALSE_FLAGS = (
    "pool_flash_semantics_complete",
    "pool_flash_output_implemented",
    "pool_flash_selected_persistence_proven",
    "no_later_selected_field_overwrites_proven",
    "host_eth_call_semantics_rederived",
    "host_call_block_pointer_semantics_rederived",
    "host_call_error_classification_rederived",
    "graph_store_host_semantics_rederived",
    "graph_handler_rollback_proven_by_retained_wat",
    "post_fatal_execution_modeled",
    "general_heap_alias_semantics_rederived",
    "complete_pool_entity_history",
    "all_manifest_handler_field_semantics_complete",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "runtime_population_complete",
    "writer_package_consumes_projection",
    "both_configured_packages_identical_wasm_bound",
    "boundary_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "checkpoint_authority",
    "issue_37_flash_implementation_criterion_complete",
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


SWAP = load_module("uniswap_v3_pool_swap_core_for_flash", SWAP_VERIFIER_PATH, SWAP_VERIFIER_SHA256)
MINT = SWAP.MINT
INITIALIZE = SWAP.INITIALIZE
POOL_RUNTIME = SWAP.POOL_RUNTIME
V2 = SWAP.V2
MATRIX = V2.MATRIX
WRITER = SWAP.WRITER


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


_KECCAK_ROUNDS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_KECCAK_ROTATIONS = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)
_MASK64 = (1 << 64) - 1


def _rol64(value: int, shift: int) -> int:
    return value if shift == 0 else ((value << shift) | (value >> (64 - shift))) & _MASK64


def _keccak_f1600(state: list[int]) -> None:
    for constant in _KECCAK_ROUNDS:
        columns = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        delta = [columns[(x - 1) % 5] ^ _rol64(columns[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= delta[x]
        rotated = [0] * 25
        for x in range(5):
            for y in range(5):
                rotated[y + 5 * ((2 * x + 3 * y) % 5)] = _rol64(state[x + 5 * y], _KECCAK_ROTATIONS[x][y])
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = rotated[x + 5 * y] ^ ((~rotated[(x + 1) % 5 + 5 * y]) & rotated[(x + 2) % 5 + 5 * y])
        state[0] ^= constant


def keccak256(payload: bytes) -> bytes:
    rate = 136
    padded = bytearray(payload)
    padded.append(0x01)
    padded.extend(b"\x00" * ((rate - len(padded) % rate) % rate))
    padded[-1] |= 0x80
    state = [0] * 25
    for offset in range(0, len(padded), rate):
        block = padded[offset : offset + rate]
        for lane in range(rate // 8):
            state[lane] ^= int.from_bytes(block[lane * 8 : lane * 8 + 8], "little")
        _keccak_f1600(state)
    return b"".join(value.to_bytes(8, "little") for value in state)[:32]


def selector(signature: str) -> str:
    return keccak256(signature.encode())[:4].hex()


require(
    keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
    "Keccak-256 implementation self-check failed",
)


def verify_pool_abi(root: Path) -> dict[str, Any]:
    path = root / POOL_ABI_PATH
    require(path.is_file(), "Pool ABI missing")
    require(path.stat().st_size == POOL_ABI_BYTES, "Pool ABI byte length drift")
    require(raw_sha256(path) == POOL_ABI_SHA256, "Pool ABI digest drift")
    abi = load_json_strict(path)
    event = [item for item in abi if item.get("type") == "event" and item.get("name") == "Flash"]
    expected_event = {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "sender", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "recipient", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount0", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "amount1", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "paid0", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "paid1", "type": "uint256"},
        ],
        "name": "Flash",
        "type": "event",
    }
    require(event == [expected_event], "Pool ABI Flash event drift")
    functions = []
    selectors = []
    for definition in SELECTED_FIELDS.values():
        matches = [item for item in abi if item.get("type") == "function" and item.get("name") == definition["method"]]
        expected = {
            "inputs": [],
            "name": definition["method"],
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        }
        require(matches == [expected], f"Pool ABI {definition['method']} drift")
        actual_selector = selector(definition["abi_signature"])
        require(actual_selector == definition["selector"], f"{definition['method']} selector drift")
        functions.append(expected)
        selectors.append({"abi_signature": definition["abi_signature"], "selector": actual_selector})
    return {
        "cid": POOL_ABI_CID,
        "path": str(POOL_ABI_PATH),
        "bytes": POOL_ABI_BYTES,
        "sha256": POOL_ABI_SHA256,
        "event": expected_event,
        "functions": functions,
        "selectors": selectors,
    }


def flash_context_from_swap(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = WRITER.resolve_handler(context["functions"], context["exports"], HANDLER_EXPORT)
    binding = context["analysis"]["registered_handlers"][HANDLER_EXPORT]
    require(handler.name == context["analysis"]["registered_handler_export_targets"][HANDLER_EXPORT], f"{cid} Flash export target drift")
    require(handler.function_index == binding["wat_function_index"], f"{cid} Flash function index drift")
    require(function_sha256(handler) == binding["body_sha256"], f"{cid} Flash analysis body drift")
    profile = context["profile"]["profile_id"]
    require((handler.start_line, len(handler.lines), function_sha256(handler)) == EXPECTED_HANDLER[profile], f"{cid} exact Flash handler binding drift")
    return {**context, "handler": handler}


def prove_runtime(context: dict[str, Any]) -> dict[str, Any]:
    return SWAP.prove_runtime(context)


def prove_smart_contract_call(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    profile = context["profile"]["profile_id"]
    generation = context["profile"]["control_generation"]
    helper = single_suffix_function(context["functions"], "ethereum.SmartContract#call", f"{cid} SmartContract#call")
    require((len(helper.lines), function_sha256(helper)) == EXPECTED_SMART_CALL_HELPER[profile], f"{cid} exact SmartContract#call helper drift")
    if generation == "modern":
        call, result, check, branch, abort, trap, end, returned = 42, 43, 44, 45, 56, 57, 58, 59
    else:
        call, result, check, branch, abort, trap, end, returned = 9, 10, 11, 12, 23, 24, 25, 26
    require((call_name(helper.lines[call]) or "").endswith("chain/ethereum/ethereum.call"), f"{cid} non-try ethereum.call target")
    require("tryCall" not in (call_name(helper.lines[call]) or ""), f"{cid} unexpected tryCall")
    result_local = local_name(helper.lines[result], "tee")
    require(result_local is not None, f"{cid} SmartContract#call result local")
    require_instruction(helper, check, "i32.eqz", f"{cid} SmartContract#call null check")
    require(normalized(helper.lines[branch]).startswith("if "), f"{cid} SmartContract#call null branch")
    require((call_name(helper.lines[abort]) or "").endswith(("builtins/abort", "env/abort")), f"{cid} SmartContract#call abort")
    require_instruction(helper, trap, "unreachable", f"{cid} SmartContract#call trap")
    require_instruction(helper, end, "end", f"{cid} SmartContract#call null branch end")
    require(normalized(helper.lines[returned]).rstrip(")") == f"local.get {result_local}", f"{cid} SmartContract#call return identity")
    require(INITIALIZE.effect_is_confined_to_closed_trap_branch(helper, abort, returned), f"{cid} call abort not confined to closed trap")
    require(INITIALIZE.effect_is_confined_to_closed_trap_branch(helper, trap, returned), f"{cid} call unreachable not confined to closed trap")
    INITIALIZE.require_no_successful_path_bypass(helper, returned, f"{cid} SmartContract#call successful return")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "ethereum_host_import": call_name(helper.lines[call]),
        "try_call": False,
        "result_local": result_local,
        "null_result_check_relative_wat_line": check,
        "null_result_abort_relative_wat_line": abort,
        "null_result_unreachable_relative_wat_line": trap,
        "nontry_null_path_closed_trap_machine_proven": True,
        "successful_return_preserves_nonzero_result_identity": True,
        "host_eth_call_semantics_rederived": False,
        "host_call_block_pointer_semantics_rederived": False,
        "host_call_error_classification_rederived": False,
    }


def prove_modern_boundary(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    memory = context["memory"]
    require(decoded_constant(handler.lines[2], memory) == "Pool", f"{cid} modern Pool target")
    require_instruction(handler, 3, "local.get $p0", f"{cid} modern Flash event")
    require_instruction(handler, 4, "i32.load", f"{cid} modern Flash event address")
    require_call(handler, 5, "typeConversion.bytesToHex", f"{cid} modern Pool address conversion")
    require_exact_call(handler, 6, STORE_GET, f"{cid} modern Pool store.get")
    pool_local = local_name(handler.lines[7], "tee")
    require(pool_local is not None, f"{cid} modern Pool local")
    require_instruction(handler, 8, "i32.eqz", f"{cid} modern missing Pool check")
    require(normalized(handler.lines[9]).startswith("if "), f"{cid} modern missing Pool branch")
    require_call(handler, 14, "builtins/abort", f"{cid} modern missing Pool abort")
    require_instruction(handler, 15, "unreachable", f"{cid} modern missing Pool trap")
    require_instruction(handler, 16, "end", f"{cid} modern missing Pool branch end")
    require(INITIALIZE.effect_is_confined_to_closed_trap_branch(handler, 14, 89), f"{cid} missing Pool abort branch")
    require(INITIALIZE.effect_is_confined_to_closed_trap_branch(handler, 15, 89), f"{cid} missing Pool unreachable branch")
    require_instruction(handler, 18, "local.get $p0", f"{cid} contract event receiver")
    require_instruction(handler, 19, "i32.load", f"{cid} contract event address")
    require_instruction(handler, 20, "local.set $p0", f"{cid} contract address local")
    require_call(handler, 23, "stub/__new", f"{cid} contract allocation")
    require(decoded_constant(handler.lines[24], memory) == "Pool", f"{cid} contract name")
    require_instruction(handler, 25, "local.get $p0", f"{cid} contract address operand")
    require_call(handler, 26, "SmartContract#constructor", f"{cid} contract constructor")
    contract_local = local_name(handler.lines[27], "tee")
    require(contract_local == "$p0", f"{cid} contract local identity")
    require_instruction(handler, 28, "end", f"{cid} contract result block end")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, pool_local, 7, 89, f"{cid} loaded Pool receiver")
    return {
        "generation": "modern",
        "event_parameter": "$p0",
        "pool_entity_target": "Pool",
        "loaded_pool_local": pool_local,
        "contract_local": contract_local,
        "event_address_to_pool_load_machine_proven": True,
        "event_address_to_contract_bind_machine_proven": True,
        "missing_pool_path_closed_trap_machine_proven": True,
        "successful_continuation_requires_nonzero_pool": True,
        "pool_address_conversion_import": MINT.prove_bytes_to_hex_import(context, call_name(handler.lines[5]) or ""),
    }


def prove_legacy_boundary(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    require_instruction(handler, 2, "local.get $p0", f"{cid} legacy Flash event")
    require_instruction(handler, 3, "i32.load", f"{cid} legacy Flash event address")
    require_call(handler, 4, "typeConversion.bytesToHex", f"{cid} legacy Pool address conversion")
    require_call(handler, 5, "schema/Pool.load", f"{cid} legacy Pool load")
    pool_local = local_name(handler.lines[6], "set")
    require(pool_local == "$l1", f"{cid} legacy Pool local")
    require_instruction(handler, 7, "local.get $p0", f"{cid} legacy contract event")
    require_instruction(handler, 8, "i32.load", f"{cid} legacy contract event address")
    require_call(handler, 9, "Pool.bind", f"{cid} legacy Pool bind")
    contract_local = local_name(handler.lines[10], "tee")
    require(contract_local == "$p0", f"{cid} legacy contract local")
    load = single_suffix_function(context["functions"], "schema/Pool.load", f"{cid} Pool.load")
    require(len(load.lines) == 4 and decoded_constant(load.lines[1], context["memory"]) == "Pool", f"{cid} Pool.load helper")
    require_instruction(load, 2, "local.get $p0", f"{cid} Pool.load id")
    require_call(load, 3, "index/store.get", f"{cid} Pool.load host")
    bind = single_suffix_function(context["functions"], "Pool.bind", f"{cid} Pool.bind")
    require(len(bind.lines) == 4 and normalized(bind.lines[2]) == "local.get $p0", f"{cid} Pool.bind helper")
    require_call(bind, 3, "constructor", f"{cid} Pool.bind constructor")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, pool_local, 6, 23, f"{cid} loaded Pool receiver")
    return {
        "generation": "legacy",
        "event_parameter": "$p0",
        "pool_entity_target": "Pool",
        "loaded_pool_local": pool_local,
        "contract_local": contract_local,
        "pool_load_helper": {"function": load.name, "body_sha256": function_sha256(load)},
        "contract_bind_helper": {"function": bind.name, "body_sha256": function_sha256(bind)},
        "event_address_to_pool_load_machine_proven": True,
        "event_address_to_contract_bind_machine_proven": True,
        "missing_pool_behavior_proven": False,
        "normal_completion_scope_only": True,
        "pool_address_conversion_import": MINT.prove_bytes_to_hex_import(context, call_name(handler.lines[4]) or ""),
    }


def prove_modern_inline_value(context: dict[str, Any], field: str, start: int, local: str, payload_local: str) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    require_instruction(handler, start, f"local.get {local}", f"{cid} {field} payload")
    require_instruction(handler, start + 1, "i64.extend_i32_u", f"{cid} {field} payload widening")
    require_instruction(handler, start + 2, f"local.set {payload_local}", f"{cid} {field} payload local")
    require_instruction(handler, start + 3, "i32.const 16", f"{cid} {field} Value bytes")
    require_call(handler, start + 5, "stub/__new", f"{cid} {field} Value allocation")
    value_local = local_name(handler.lines[start + 6], "tee")
    require(value_local is not None, f"{cid} {field} Value local")
    require_instruction(handler, start + 7, "i32.const 7", f"{cid} {field} Value kind")
    require_instruction(handler, start + 8, "i32.store", f"{cid} {field} Value kind store")
    require_instruction(handler, start + 9, f"local.get {value_local}", f"{cid} {field} payload receiver")
    require_instruction(handler, start + 10, f"local.get {payload_local}", f"{cid} {field} payload value")
    require_instruction(handler, start + 11, "i64.store offset=8", f"{cid} {field} payload store")
    require_instruction(handler, start + 12, f"local.get {value_local}", f"{cid} {field} returned Value")
    return {
        "value_local": value_local,
        "payload_local": payload_local,
        "value_kind": 7,
        "kind_7_pointer_payload_same_object_machine_proven": True,
    }


def prove_modern_flows(context: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    memory = context["memory"]
    pool_local = boundary["loaded_pool_local"]
    contract_local = boundary["contract_local"]
    require(decoded_constant(handler.lines[29], memory) == SELECTED_FIELDS["feeGrowthGlobal0X128"]["method"], f"{cid} fee0 method")
    require(decoded_constant(handler.lines[30], memory) == SELECTED_FIELDS["feeGrowthGlobal0X128"]["wat_signature"], f"{cid} fee0 signature")
    require_instruction(handler, 31, "i32.const 0", f"{cid} fee0 empty args length")
    require_call(handler, 34, "rt/__newArray", f"{cid} fee0 empty args")
    require_call(handler, 35, "SmartContract#call", f"{cid} fee0 call")
    require_instruction(handler, 36, "i32.const 0", f"{cid} fee0 result index")
    require_call(handler, 37, "EventParam>#__get", f"{cid} fee0 result access")
    require_call(handler, 38, "ethereum.Value#toBigInt", f"{cid} fee0 uint256 decode")
    fee0_local = local_name(handler.lines[39], "set")
    require(fee0_local == "$l2", f"{cid} fee0 result local")
    require_instruction(handler, 40, f"local.get {contract_local}", f"{cid} fee1 same contract receiver")
    require(decoded_constant(handler.lines[41], memory) == SELECTED_FIELDS["feeGrowthGlobal1X128"]["method"], f"{cid} fee1 method")
    require(decoded_constant(handler.lines[42], memory) == SELECTED_FIELDS["feeGrowthGlobal1X128"]["wat_signature"], f"{cid} fee1 signature")
    require_instruction(handler, 43, "i32.const 0", f"{cid} fee1 empty args length")
    require_call(handler, 46, "rt/__newArray", f"{cid} fee1 empty args")
    require_call(handler, 47, "SmartContract#call", f"{cid} fee1 call")
    require_instruction(handler, 48, "i32.const 0", f"{cid} fee1 result index")
    require_call(handler, 49, "EventParam>#__get", f"{cid} fee1 result access")
    require_call(handler, 50, "ethereum.Value#toBigInt", f"{cid} fee1 uint256 decode")
    fee1_local = local_name(handler.lines[51], "set")
    require(fee1_local == "$p0", f"{cid} fee1 result local")
    require_instruction(handler, 52, f"local.get {pool_local}", f"{cid} fee0 Pool receiver")
    require(decoded_constant(handler.lines[53], memory) == "feeGrowthGlobal0X128", f"{cid} fee0 key")
    fee0_value = prove_modern_inline_value(context, "feeGrowthGlobal0X128", 55, fee0_local, "$l3")
    require_exact_call(handler, 69, MODERN_MAP_SET, f"{cid} fee0 TypedMap set")
    require_instruction(handler, 70, f"local.get {pool_local}", f"{cid} fee1 Pool receiver")
    require(decoded_constant(handler.lines[71], memory) == "feeGrowthGlobal1X128", f"{cid} fee1 key")
    fee1_value = prove_modern_inline_value(context, "feeGrowthGlobal1X128", 73, fee1_local, "$l3")
    require_exact_call(handler, 87, MODERN_MAP_SET, f"{cid} fee1 TypedMap set")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, fee0_local, 39, 55, f"{cid} fee0 result")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, fee1_local, 51, 73, f"{cid} fee1 result")
    INITIALIZE.require_no_successful_path_bypass(handler, 89, f"{cid} Flash save")
    return {
        "codegen_model": "inline",
        "contract_receiver_local": contract_local,
        "loaded_pool_local": pool_local,
        "call_order": ["feeGrowthGlobal0X128", "feeGrowthGlobal1X128"],
        "setter_order": ["Pool.feeGrowthGlobal0X128", "Pool.feeGrowthGlobal1X128"],
        "setter_indices": [69, 87],
        "fields": {
            "feeGrowthGlobal0X128": {
                "method": SELECTED_FIELDS["feeGrowthGlobal0X128"]["method"],
                "wat_signature": SELECTED_FIELDS["feeGrowthGlobal0X128"]["wat_signature"],
                "selector": SELECTED_FIELDS["feeGrowthGlobal0X128"]["selector"],
                "call_relative_wat_line": 35,
                "decode_index": 0,
                "decode_relative_wat_line": 38,
                "result_local": fee0_local,
                "decoded_field_key": "feeGrowthGlobal0X128",
                "setter_relative_wat_line": 69,
                "value_construction": fee0_value,
                "receiver_key_value_flow_machine_proven": True,
            },
            "feeGrowthGlobal1X128": {
                "method": SELECTED_FIELDS["feeGrowthGlobal1X128"]["method"],
                "wat_signature": SELECTED_FIELDS["feeGrowthGlobal1X128"]["wat_signature"],
                "selector": SELECTED_FIELDS["feeGrowthGlobal1X128"]["selector"],
                "call_relative_wat_line": 47,
                "decode_index": 0,
                "decode_relative_wat_line": 50,
                "result_local": fee1_local,
                "decoded_field_key": "feeGrowthGlobal1X128",
                "setter_relative_wat_line": 87,
                "value_construction": fee1_value,
                "receiver_key_value_flow_machine_proven": True,
            },
        },
        "same_contract_receiver_for_both_calls_machine_proven": True,
        "ordered_call_decode_setter_flow_machine_proven": True,
        "same_path_to_save_machine_proven": True,
        "legacy_symbol_alias_boundary": None,
    }


def prove_legacy_getter(context: dict[str, Any], field: str) -> dict[str, Any]:
    cid = context["mapping_cid"]
    suffix = f"Pool#{field}"
    helper = single_suffix_function(context["functions"], suffix, f"{cid} {field} getter")
    definition = SELECTED_FIELDS[field]
    require(len(helper.lines) == 9, f"{cid} {field} getter shape")
    require_instruction(helper, 1, "local.get $p0", f"{cid} {field} contract receiver")
    require(decoded_constant(helper.lines[2], context["memory"]) == definition["method"], f"{cid} {field} method")
    require(decoded_constant(helper.lines[3], context["memory"]) == definition["wat_signature"], f"{cid} {field} signature")
    require_call(helper, 5, "SmartContract#call", f"{cid} {field} call")
    require_instruction(helper, 6, "i32.const 0", f"{cid} {field} result index")
    require_call(helper, 7, "EventParam>#__get", f"{cid} {field} result access")
    require_call(helper, 8, "ethereum.Value#toBigInt", f"{cid} {field} uint256 decode")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "method": definition["method"],
        "wat_signature": definition["wat_signature"],
        "selector": definition["selector"],
        "decode_index": 0,
        "receiver_to_call_to_result_decode_machine_proven": True,
    }


def prove_legacy_setter(context: dict[str, Any], field: str) -> dict[str, Any]:
    cid = context["mapping_cid"]
    suffix = f"PoolDayData#set:{field}"
    helper = single_suffix_function(context["functions"], suffix, f"{cid} {field} setter")
    require(len(helper.lines) == 6, f"{cid} {field} setter shape")
    require_instruction(helper, 1, "local.get $p0", f"{cid} {field} setter receiver")
    require(decoded_constant(helper.lines[2], context["memory"]) == field, f"{cid} {field} setter key")
    require_instruction(helper, 3, "local.get $p1", f"{cid} {field} setter value")
    require_call(helper, 4, "Value.fromBigInt", f"{cid} {field} Value conversion")
    require_exact_call(helper, 5, LEGACY_MAP_SET, f"{cid} {field} TypedMap set")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "decoded_field_key": field,
        "misleading_deduplicated_symbol_name": True,
        "symbol_name_used_as_semantic_authority": False,
        "receiver_key_value_to_typed_map_set_machine_proven": True,
    }


def prove_value_from_bigint(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    helper = single_suffix_function(context["functions"], "Value.fromBigInt", f"{cid} Value.fromBigInt")
    require(len(helper.lines) == 11, f"{cid} Value.fromBigInt shape")
    require_call(helper, 2, "Value#constructor", f"{cid} Value.fromBigInt allocation")
    value_local = local_name(helper.lines[3], "tee")
    require(value_local is not None, f"{cid} Value.fromBigInt local")
    require_instruction(helper, 4, "i32.const 7", f"{cid} Value.fromBigInt kind")
    require_instruction(helper, 5, "i32.store", f"{cid} Value.fromBigInt kind store")
    require_instruction(helper, 6, f"local.get {value_local}", f"{cid} Value.fromBigInt payload receiver")
    require_instruction(helper, 7, "local.get $p0", f"{cid} Value.fromBigInt payload")
    require_instruction(helper, 9, "i64.store offset=8", f"{cid} Value.fromBigInt payload store")
    require(normalized(helper.lines[10]).rstrip(")") == f"local.get {value_local}", f"{cid} Value.fromBigInt return identity")
    return {
        "function": helper.name,
        "body_sha256": function_sha256(helper),
        "returned_object_local": value_local,
        "kind_7_pointer_payload_same_object_machine_proven": True,
    }


def prove_legacy_flows(context: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    pool_local = boundary["loaded_pool_local"]
    contract_local = boundary["contract_local"]
    require_instruction(handler, 10, f"local.tee {contract_local}", f"{cid} bound contract identity")
    require_call(handler, 11, "Pool#feeGrowthGlobal0X128", f"{cid} fee0 getter")
    fee0_local = local_name(handler.lines[12], "set")
    require(fee0_local == "$l2", f"{cid} fee0 result local")
    require_instruction(handler, 13, f"local.get {contract_local}", f"{cid} fee1 same contract receiver")
    require_call(handler, 14, "Pool#feeGrowthGlobal1X128", f"{cid} fee1 getter")
    fee1_local = local_name(handler.lines[15], "set")
    require(fee1_local == "$p0", f"{cid} fee1 result local")
    require_instruction(handler, 16, f"local.get {pool_local}", f"{cid} fee0 Pool receiver")
    require_instruction(handler, 17, f"local.get {fee0_local}", f"{cid} fee0 value")
    require_call(handler, 18, "PoolDayData#set:feeGrowthGlobal0X128", f"{cid} fee0 setter")
    require_instruction(handler, 19, f"local.get {pool_local}", f"{cid} fee1 Pool receiver")
    require_instruction(handler, 20, f"local.get {fee1_local}", f"{cid} fee1 value")
    require_call(handler, 21, "PoolDayData#set:feeGrowthGlobal1X128", f"{cid} fee1 setter")
    INITIALIZE.require_no_successful_path_local_reassignment(handler, fee0_local, 12, 17, f"{cid} fee0 result")
    INITIALIZE.require_no_successful_path_bypass(handler, 23, f"{cid} Flash save")
    getters = {field: prove_legacy_getter(context, field) for field in SELECTED_FIELDS}
    setters = {field: prove_legacy_setter(context, field) for field in SELECTED_FIELDS}
    return {
        "codegen_model": "wrapper",
        "contract_receiver_local": contract_local,
        "loaded_pool_local": pool_local,
        "call_order": ["feeGrowthGlobal0X128", "feeGrowthGlobal1X128"],
        "setter_order": ["Pool.feeGrowthGlobal0X128", "Pool.feeGrowthGlobal1X128"],
        "setter_indices": [18, 21],
        "fields": {
            "feeGrowthGlobal0X128": {
                "call_relative_wat_line": 11,
                "result_local": fee0_local,
                "setter_relative_wat_line": 18,
                "getter": getters["feeGrowthGlobal0X128"],
                "setter": setters["feeGrowthGlobal0X128"],
                "receiver_key_value_flow_machine_proven": True,
            },
            "feeGrowthGlobal1X128": {
                "call_relative_wat_line": 14,
                "result_local": fee1_local,
                "setter_relative_wat_line": 21,
                "getter": getters["feeGrowthGlobal1X128"],
                "setter": setters["feeGrowthGlobal1X128"],
                "receiver_key_value_flow_machine_proven": True,
            },
        },
        "value_from_bigint": prove_value_from_bigint(context),
        "same_contract_receiver_for_both_calls_machine_proven": True,
        "ordered_call_decode_setter_flow_machine_proven": True,
        "same_path_to_save_machine_proven": True,
        "legacy_symbol_alias_boundary": "decoded method/signature, result index, decoded key, call operands, and receiver identity are authority; deduplicated getter/setter names are not",
    }


def prove_mutation_inventory(context: dict[str, Any]) -> dict[str, Any]:
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
    require(actual == EXPECTED_MUTATION_CLOSURE[profile], f"{context['mapping_cid']} exact reachable Flash mutation inventory drift")
    return {
        "reachable_function_count": actual[0],
        "reachable_function_body_inventory_sha256": actual[1],
        "reachable_direct_memory_write_site_count": actual[2],
        "reachable_direct_memory_write_site_inventory_sha256": actual[3],
        "reachable_typed_map_set_site_count": actual[4],
        "reachable_typed_map_set_site_inventory_sha256": actual[5],
        "selected_receiver_key_value_classified_typed_map_set_sites": 2,
        "unclassified_typed_map_set_site_count": 0,
        "direct_memory_write_sites_without_general_alias_proof": actual[2],
        "exact_retained_reachable_body_authority": True,
        "general_heap_alias_semantics_rederived": False,
    }


def prove_save_and_effects(context: dict[str, Any], flows: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    handler = context["handler"]
    pool_local = flows["loaded_pool_local"]
    saves = [index for index, line in enumerate(handler.lines) if (call_name(line) or "").endswith("schema/Pool#save")]
    require(len(saves) == 1, f"{cid} direct Pool.save count")
    save = saves[0]
    require(flows["setter_indices"][-1] < save, f"{cid} setters/save order")
    require_instruction(handler, save - 1, f"local.get {pool_local}", f"{cid} Pool.save receiver")
    depths = V2.wat_control_depths(handler.lines)
    require(all(depths[index] == 0 for index in (*flows["setter_indices"], save)), f"{cid} call/setter/save control depth")
    INITIALIZE.require_no_successful_path_bypass(handler, save, f"{cid} ordered Flash effects")
    transitive = INITIALIZE.recompute_transitive_store_evidence(context)
    actual = (
        transitive["reachable_function_count"],
        transitive["reachable_call_indirect_instruction_count"],
        tuple(transitive["closed_indirect_table_targets"]),
        transitive["reachable_store_set_site_count"],
        transitive["reachable_store_set_site_ids_sha256"],
    )
    require(actual == EXPECTED_EFFECT_CLOSURE[context["profile"]["profile_id"]], f"{cid} exact transitive Flash store closure drift")
    require(transitive["reachable_store_set_targets"] == ["Pool"], f"{cid} reachable store target drift")
    require(transitive["dynamic_reachable_store_set_target_count"] == 0, f"{cid} dynamic store target")
    require(transitive["unmodelled_store_mutation_host_import_count"] == 0, f"{cid} unmodelled store mutation import")
    require([item["relative_wat_line"] for item in transitive["reachable_pool_save_calls"]] == [save], f"{cid} Pool.save transitive inventory")
    require(len(transitive["reachable_pool_store_set_sites"]) == 1, f"{cid} Pool store.set helper inventory")
    return {
        "direct_pool_save_count": 1,
        "pool_save_relative_wat_line": save,
        "pool_save_wat_line": handler.start_line + save,
        "same_loaded_pool_receiver_for_both_setters_and_save_machine_proven": True,
        "both_setters_precede_pool_save_machine_proven": True,
        "same_path_call_decode_setter_save_machine_proven": True,
        "reachable_in_memory_mutation_inventory": prove_mutation_inventory(context),
        "transitive_store_evidence": transitive,
        "reachable_store_set_targets": ["Pool"],
        "flash_entity_store_target_reachable": False,
        "no_flash_entity_row_machine_bound": True,
        "selected_persistence_proven": False,
        "no_later_selected_field_overwrites_proven": False,
        "rollback_and_post_fatal_semantics_proven": False,
    }


def prove_pool_flash_wat_context(context: dict[str, Any]) -> dict[str, Any]:
    cid = context["mapping_cid"]
    generation = context["profile"]["control_generation"]
    runtime = prove_runtime(context)
    capsule = runtime["public_collection_capsule"]
    boundary = prove_modern_boundary(context) if generation == "modern" else prove_legacy_boundary(context)
    call_boundary = prove_smart_contract_call(context)
    flows = prove_modern_flows(context, boundary) if generation == "modern" else prove_legacy_flows(context, boundary)
    effects = prove_save_and_effects(context, flows)
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
        },
        "pool_runtime_binding": {
            "contract_version": POOL_RUNTIME_CONTRACT_VERSION,
            "artifact_selection_tuple": runtime["artifact_selection_tuple"],
            "same_wat_runtime_proof_sha256": canonical_sha256(runtime),
            "public_collection_capsule_sha256": canonical_sha256(capsule),
            "event_param_array_get": (capsule["indexed_collection"] if generation == "modern" else capsule["indexed_access_and_value"])["event_param_array_get"],
            "typed_map_set": collection["typed_map_set"],
            "same_context_runtime_capsule_recomputed": True,
        },
        "control_and_entity_boundary": boundary,
        "contract_call_failure_boundary": call_boundary,
        "selected_field_flows": flows,
        "save_and_effect_closure": effects,
        "required_absent_flash_row": True,
        "selected_handler_structural_wat_projection_complete": True,
        "complete_pool_flash_handler_semantics": False,
    }


def build_proofs(contexts: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    flash_contexts = {cid: flash_context_from_swap(context) for cid, context in contexts.items()}
    proofs = sorted((prove_pool_flash_wat_context(context) for context in flash_contexts.values()), key=lambda item: item["profile_id"])
    require(len(proofs) == 8 and sum(item["control_generation"] == "legacy" for item in proofs) == 6, "Pool Flash proof population drift")
    return proofs, flash_contexts


def build_segments(matrix: dict[str, Any], v2: dict[str, Any], proofs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    catalog = {(item["entity"], item["field"]): item for item in v2["field_catalog"]}
    results = []
    expected_event = "Flash(indexed address,indexed address,uint256,uint256,uint256,uint256)"
    for segment in matrix["segments"]:
        cid = segment["profile_bindings"]["pool"]["mapping_cid"]
        proof = proof_by_cid[cid]
        handler = next(item for item in segment["handlers"] if item["handler_id"] == HANDLER_ID)
        require(handler["mapping_cid"] == cid and handler["event"] == expected_event, f"{segment['segment_id']} Flash matrix binding")
        require(handler["conservative_entity_writer_reachability"]["reachable_store_set_targets"] == ["Pool"], f"{segment['segment_id']} Flash handler target")
        flash_entity = next(item for item in segment["entity_field_matrix"] if item["entity"] == "Flash")
        population = flash_entity["population_contract"]
        require(population["classification"] == "required_absent" and population["static_writer_absence_certified"] is True, f"{segment['segment_id']} required-absent Flash")
        require(len(flash_entity["fields"]) == 12 and all(item["writer_evidence_status"] == "required_absent_static_certified" for item in flash_entity["fields"]), f"{segment['segment_id']} Flash field absence")
        fields = []
        for field, definition in SELECTED_FIELDS.items():
            inherited = catalog[("Pool", field)]
            require(inherited["complete_selected_handler_projection"] is True and inherited["complete_entity_history"] is False, f"{segment['segment_id']} inherited {field} boundary")
            fields.append({
                "entity": "Pool",
                "field": field,
                "schema_type": definition["schema_type"],
                "population_classification": "conditional",
                "method": definition["method"],
                "wat_signature": definition["wat_signature"],
                "selector": definition["selector"],
                "selected_handler_call_flow_evidence": f"ordered non-try {definition['method']} call result index 0 reaches Pool.{field} and the same-path Pool.save",
                "complete_selected_handler_projection": True,
                "complete_entity_history": False,
                "cumulative_semantic_status": "certified_selected_handler_projection_strengthened_by_flash_same_path",
                "v2_field_record_sha256": canonical_sha256(inherited),
                "residual_history_blocker": "host call semantics, Graph rollback, persistence, later aliases, and other Pool handlers are not closed",
            })
        required_absent = {
            "entity": "Flash",
            "schema_field_count": len(flash_entity["fields"]),
            "population_classification": "required_absent",
            "static_writer_absence_certified": True,
            "handler_transitive_store_target_excludes_flash": True,
            "no_flash_row_synthesized": True,
            "source_entity_record_sha256": canonical_sha256(flash_entity),
        }
        semantic = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": proof["profile_id"],
            "control_generation": proof["control_generation"],
            "control_and_entity_boundary": proof["control_and_entity_boundary"],
            "contract_call_failure_boundary": proof["contract_call_failure_boundary"],
            "selected_field_flows": proof["selected_field_flows"],
            "save_and_effect_closure": proof["save_and_effect_closure"],
            "fields": fields,
            "required_absent_output": required_absent,
            "selected_handler_projection_complete": True,
            "complete_pool_flash_handler_semantics": False,
            "complete_pool_entity_history": False,
        }
        provenance = {
            "mapping_cid": cid,
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "proof_sha256": canonical_sha256(proof),
            "source_handler_record_sha256": canonical_sha256(handler),
            "source_flash_entity_record_sha256": canonical_sha256(flash_entity),
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
    require(len(results) == 8 and sum(len(item["semantic_surface"]["fields"]) for item in results) == 16, "Pool Flash segment-field count")
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
    require(len(results) == 28, "Pool Flash pairwise diff count")
    return results


def truth_boundary() -> dict[str, bool]:
    require(len(TRUE_FLAGS) == len(set(TRUE_FLAGS)) and len(FALSE_FLAGS) == len(set(FALSE_FLAGS)) and set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "Pool Flash truth-boundary declarations")
    return {**{key: True for key in TRUE_FLAGS}, **{key: False for key in FALSE_FLAGS}}


def load_sources(root: Path, *, recompute_wat: bool = True, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    verifier_pins = (
        (SWAP_VERIFIER_PATH, SWAP_VERIFIER_SHA256),
        (MINT_VERIFIER_PATH, MINT_VERIFIER_SHA256),
        (POOL_RUNTIME_VERIFIER_PATH, POOL_RUNTIME_VERIFIER_SHA256),
        (INITIALIZE_VERIFIER_PATH, INITIALIZE_VERIFIER_SHA256),
        (V2_VERIFIER_PATH, V2_VERIFIER_SHA256),
        (MATRIX_VERIFIER_PATH, MATRIX_VERIFIER_SHA256),
    )
    for path, digest in verifier_pins:
        require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    contract_pins = (
        (SWAP_CONTRACT_PATH, SWAP_CONTRACT_SHA256),
        (MINT_CONTRACT_PATH, MINT_CONTRACT_SHA256),
        (POOL_RUNTIME_CONTRACT_PATH, POOL_RUNTIME_CONTRACT_SHA256),
        (INITIALIZE_CONTRACT_PATH, INITIALIZE_CONTRACT_SHA256),
        (V2_CONTRACT_PATH, V2_CONTRACT_SHA256),
        (MATRIX_CONTRACT_PATH, MATRIX_CONTRACT_SHA256),
    )
    for path, digest in contract_pins:
        require((root / path).is_file() and raw_sha256(root / path) == digest, f"contract digest drift: {path}")
    swap_sources = SWAP.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    swap_contract = SWAP.verify_contract(root, sources=swap_sources, recompute_wat=False)
    require(swap_contract["contract_version"] == SWAP_CONTRACT_VERSION, "Swap source contract version drift")
    require(swap_contract["scope"]["cumulative_selected_field_count"] == 36 and swap_contract["scope"]["cumulative_residual_field_count"] == 230, "Swap cumulative boundary drift")
    mint_contract = load_json_strict(root / MINT_CONTRACT_PATH)
    runtime_contract = load_json_strict(root / POOL_RUNTIME_CONTRACT_PATH)
    initialize_contract = load_json_strict(root / INITIALIZE_CONTRACT_PATH)
    v2_contract = load_json_strict(root / V2_CONTRACT_PATH)
    matrix_contract = load_json_strict(root / MATRIX_CONTRACT_PATH)
    require(mint_contract["contract_version"] == MINT_CONTRACT_VERSION, "Mint version drift")
    require(runtime_contract["contract_version"] == POOL_RUNTIME_CONTRACT_VERSION, "Pool runtime version drift")
    require(initialize_contract["contract_version"] == INITIALIZE_CONTRACT_VERSION, "Initialize version drift")
    require(v2_contract["contract_version"] == V2_CONTRACT_VERSION, "v2 version drift")
    require(matrix_contract["contract_version"] == MATRIX_CONTRACT_VERSION, "matrix version drift")
    require(canonical_bytes(mint_contract) == canonical_bytes(swap_sources["mint_contract"]), "direct Mint contract differs from recomputed Swap dependency")
    require(canonical_bytes(runtime_contract) == canonical_bytes(swap_sources["pool_runtime_contract"]), "direct Pool runtime contract differs from recomputed Swap dependency")
    require(canonical_bytes(initialize_contract) == canonical_bytes(swap_sources["initialize_contract"]), "direct Initialize contract differs from recomputed Swap dependency")
    require(canonical_bytes(v2_contract) == canonical_bytes(swap_sources["v2_contract"]), "direct v2 contract differs from recomputed Swap dependency")
    recomputed_matrix = swap_sources["mint_sources"]["burn_sources"]["initialize_sources"]["v2_sources"]["segment_writer_matrix"]
    require(canonical_bytes(matrix_contract) == canonical_bytes(recomputed_matrix), "direct matrix contract differs from recomputed Swap dependency")
    proofs, contexts = build_proofs(swap_sources["pool_wat_contexts"]) if recompute_wat else ([], {})
    return {
        "swap_sources": swap_sources,
        "swap_contract": swap_contract,
        "mint_contract": mint_contract,
        "pool_runtime_contract": runtime_contract,
        "initialize_contract": initialize_contract,
        "v2_contract": v2_contract,
        "matrix_contract": matrix_contract,
        "pool_abi": verify_pool_abi(root),
        "pool_flash_proofs": proofs,
        "pool_wat_contexts": contexts,
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["pool_flash_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 8, "recomputed Pool Flash proofs required")
    segments = build_segments(sources["matrix_contract"], sources["v2_contract"], proofs)
    diffs = build_segment_diffs(segments)
    residuals = {
        proof["profile_id"]: {
            "unclassified_typed_map_set_site_count": proof["save_and_effect_closure"]["reachable_in_memory_mutation_inventory"]["unclassified_typed_map_set_site_count"],
            "direct_memory_write_sites_without_general_alias_proof": proof["save_and_effect_closure"]["reachable_in_memory_mutation_inventory"]["direct_memory_write_sites_without_general_alias_proof"],
        }
        for proof in proofs
    }
    fixtures = [
        {"fixture": "handler export/body/index", "expected_rejection_layer": "canonical handler binding"},
        {"fixture": "ABI Flash event or fee-growth function selector", "expected_rejection_layer": "digest-pinned ABI and Keccak selector"},
        {"fixture": "Pool event-address load/bind or required modern Pool trap", "expected_rejection_layer": "control and entity boundary"},
        {"fixture": "method/signature/call order/contract receiver", "expected_rejection_layer": "ordered SmartContract call operands"},
        {"fixture": "result index or Value#toBigInt decode", "expected_rejection_layer": "ordered result decode flow"},
        {"fixture": "result local overwrite or cross-wire", "expected_rejection_layer": "successful-path result identity"},
        {"fixture": "selected Pool receiver/key/Value kind/payload", "expected_rejection_layer": "selected receiver-key-value flow"},
        {"fixture": "legacy misleading getter/setter symbol substitution", "expected_rejection_layer": "decoded operand/key and exact call flow"},
        {"fixture": "ethereum.call target or null abort/unreachable fallthrough", "expected_rejection_layer": "non-try null closed-trap boundary"},
        {"fixture": "Pool.save count/order/receiver", "expected_rejection_layer": "same-path save-order proof"},
        {"fixture": "reachable helper body/direct write/TypedMap set", "expected_rejection_layer": "exact reachable mutation inventory"},
        {"fixture": "Graph store target/site/indirect closure or Flash target insertion", "expected_rejection_layer": "exact Pool-only transitive store inventory"},
        {"fixture": "contract truth flag/ledger/proof/required absence/diff", "expected_rejection_layer": "deterministic contract projection"},
        {"fixture": "duplicate JSON key", "expected_rejection_layer": "strict JSON loader"},
    ]
    source_contracts = {
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
        "mode": "retained-wat-pool-flash-same-path-effect-closure-certificate",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "pool_mapping_count": 8,
            "handler": HANDLER_ID,
            "selected_fields": [f"Pool.{field}" for field in SELECTED_FIELDS],
            "selected_field_count": 2,
            "segment_field_call_flow_evidence_count": 16,
            "required_absent_entity": "Flash",
            "legacy_profile_count": 6,
            "modern_profile_count": 2,
            "pairwise_scoped_diff_count": 28,
            "inherited_swap_selected_field_count": 36,
            "cumulative_selected_field_count": 36,
            "inherited_swap_residual_field_count": 230,
            "cumulative_residual_field_count": 230,
            "reachable_effect_residuals_by_profile": residuals,
            "claim": "exact retained-WAT Pool.handleFlash call0->decode0->call1->decode1->setter0->setter1->same Pool save path with non-try null traps and required-absent Flash row; host call semantics, candidate output, persistence, and complete Flash remain false",
        },
        "source_contracts": source_contracts,
        "pool_flash_abi": sources["pool_abi"],
        "authority_contract": {
            "semantic_authority": "retained deployed Pool mapping WASM and checksum-pinned WABT 1.0.35 WAT",
            "source_text_role": "corroboration only",
            "legacy_symbol_boundary": "deduplicated legacy getter and setter names can be misleading; decoded method/signature, result index, decoded key, operand sequence, receiver identity, and pinned bodies are authoritative",
            "successful_handler_scope": "same-path structural execution through the one Pool.save when imported host operations return successfully; missing modern Pool and null SmartContract results trap",
            "call_boundary": "the generated non-try helper calls ethereum.call, traps on a null result, and returns the same nonzero result; host call value, block-pointer, and error-classification semantics are not rederived",
            "save_boundary": "both selected setters reach one same-receiver Pool.save without a successful-path bypass; Graph persistence and rollback are not proved by retained WAT",
            "required_absence_boundary": "all-function matrix evidence and the exact handleFlash transitive store closure exclude Flash; no Flash row is synthesized",
            "effect_closure_rule": "pin full reachable function-body, direct-memory-write, TypedMap-set, Graph store, and indirect-target inventories; arbitrary heap alias semantics remain open",
            "canonical_swap_base": "built on exact canonical Pool Swap squash merge 71d554fa9676d8c77437c0366a9859e13834e235 after exact merge-tree verification",
        },
        "toolchain": {
            "name": "WABT wasm2wat and wat2wasm",
            "version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-mapping-wasm>"],
            "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"],
            "selector_derivation": "embedded self-tested Keccak-256 over canonical ABI function signatures",
        },
        "valid_wat_mutation_fixture_layers": fixtures,
        "mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "field_count": 230,
            "pool_flash": [
                "candidate map_extract_data_types and graph_out do not consume this certificate and still disable Flash output",
                "host eth_call value, block-pointer, error classification, rollback, and post-fatal behavior are not rederived",
                "selected persistence, later aliases or overwrites, complete Pool history, and complete handleFlash semantics remain open",
            ],
            "execution": [
                "combined handler and dynamic data-source order, runtime population, boundary continuity, oracle/parity, package identity, checkpoint, backfill, production, and readiness remain false",
                "issue #37 Flash implementation checkbox remains unchecked",
            ],
        },
        "truth_boundary": truth_boundary(),
    }


def verify_contract(root: Path, actual: dict[str, Any] | None = None, *, sources: dict[str, Any] | None = None, recompute_wat: bool = True, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    verified = sources or load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(verified)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"Pool Flash contract missing: {CONTRACT_PATH}")
        actual = load_json_strict(path)
        require(path.read_text() == render(actual), "Pool Flash contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Pool Flash contract differs from generated proof")
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
        "verified Uniswap V3 Pool Flash semantics v1: "
        f"{len(result['mapping_proofs'])} mappings, "
        f"{result['scope']['segment_field_call_flow_evidence_count']} segment-field call-flow evidence records, "
        f"{len(result['segment_diffs'])} diffs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
