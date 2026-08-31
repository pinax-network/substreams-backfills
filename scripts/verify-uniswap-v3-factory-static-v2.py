#!/usr/bin/env python3
"""Build or verify the complete bounded Uniswap V3 Factory static v2 contract."""

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
CONTRACT_PATH = Path("uniswap-v3/factory-static/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-factory-static/v2"
HANDLER_ID = "Factory.handlePoolCreated"
HANDLER_EXPORT = "handlePoolCreated"

PRICE_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-factory-pool-price-init.py"
PRICE_VERIFIER_SHA256 = "41f8a7b09fb628bf94dcffd702a7eabdb9ecb0faf9d43b3898b6590024e61786"
PRICE_CONTRACT_PATH = Path("uniswap-v3/factory-pool-price-init/v1/contract.json")
PRICE_CONTRACT_SHA256 = "fe441948746b6bf7b7fd8f0872ebc58c8297412a643ed4fe1fd0120dca14e56a"
PRICE_CONTRACT_CANONICAL_SHA256 = "6578d2ed23f60d3535ac7970030f30a4f8ea0b9605576d3a7a5c69e535751f34"
PRICE_CONTRACT_VERSION = "uniswap-v3-factory-pool-price-initialization/v1"
RUNTIME_PATH = Path("scripts/uniswap_v3_wat_runtime.py")
RUNTIME_SHA256 = "bd555b5d44bed144777e35b361fcb63e275d7f21b774db3ffe0e08bef3bf4411"

BASE_COMMIT = "20b3864656bfa1fabb48cfeaba08518b26e81532"
BASE_TREE = "3c04abbd9319d340d41230fc7a06d6a3b44f2453"


class VerificationError(RuntimeError):
    """Raised when retained evidence cannot reproduce the exact claim."""


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


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error


def load_module(name: str, path: Path, digest: str) -> Any:
    require(path.is_file(), f"required verifier missing: {path}")
    require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PRICE = load_module("uniswap_v3_factory_price_for_static_v2", PRICE_VERIFIER_PATH, PRICE_VERIFIER_SHA256)
RUNTIME = PRICE.PARENT.RUNTIME
WRITER = PRICE.WRITER
V2 = PRICE.V2
FEE_INIT = PRICE.PARENT.PARENT
EFFECTS = FEE_INIT.EFFECTS
LEGACY_MAP_SET = PRICE.LEGACY_MAP_SET


def normalized(line: str) -> str:
    return PRICE.normalized(line)


def call_name(line: str) -> str | None:
    return PRICE.call_name(line)


def function_sha256(function: Any) -> str:
    return PRICE.function_sha256(function)


def function_by_suffix(context: dict[str, Any], suffix: str) -> Any:
    return PRICE.function_by_suffix(context, suffix)


def runtime_ops() -> Any:
    return RUNTIME.WatRuntimeOps(
        require=require,
        normalized=normalized,
        call_name=call_name,
        function_by_suffix=function_by_suffix,
    )


# Factory mappings share the algorithms but not the Pool verifier's declaration/type-index
# profile.  These are the exact retained Factory collection bodies and abort-source pointers.
COLLECTION_PROFILES: dict[str, dict[str, Any]] = {
    "legacy-base-root": {
        "value_constructor": "83da7dfece45c6640a6a6be4a0b26f837e0d4e1b419b4ccceb7336f930d1f981",
        "array_constructor": "192d1ff7da7296b6a811b24db446df7791d924d3627c8e155c585d3006822b6b",
        "array_push": "87749c0ce2274c7380891581461cff548ab6081d72510c843c1941f708665066",
        "array_abort": 1176,
        "string_allocate": "f8d00488aea4ba33754b326fa8892d1633539d50d21929bec075e5d895b0dbb1",
        "string_abort": 992,
    },
    "legacy-mainnet-qmrv": {
        "value_constructor": "cd53cf2b3995acd931c26b1626f6b24ab0d96fd51d74b2c7939933adfa74f460",
        "array_constructor": "f691269d03d500541c02563b91e2c8f16412238df14d5baf02eb9166bc0d5cfe",
        "array_push": "54d35ec2b0b90c59542200ab07abfbf3f067d1f512ecbefec5cefea5b7b4244d",
        "array_abort": 2944,
        "string_allocate": "09144b2e4b6c1838a10b6a1d9465ffa3e10bfeab9869ce32ac221d9290a441fc",
        "string_abort": 2760,
    },
    "legacy-mainnet-root": {
        "value_constructor": "cd53cf2b3995acd931c26b1626f6b24ab0d96fd51d74b2c7939933adfa74f460",
        "array_constructor": "66f7403959061f9c8f255be7235663242b1bbf7e40c222dc7b86eae8a50971d0",
        "array_push": "0dc700f27172f3dd83820e18394ad64175381919eb8f44e4a7535fbc97a86d78",
        "array_abort": 2856,
        "string_allocate": "634dc9d6639b239ee9b3007a1ccca8408cf03f1a64d373a35e977524499af12e",
        "string_abort": 2672,
    },
    "legacy-mainnet-stable": {
        "value_constructor": "cd53cf2b3995acd931c26b1626f6b24ab0d96fd51d74b2c7939933adfa74f460",
        "array_constructor": "448b2e844c927e480024bdbbb54944555f3fe9812107f8d0c54aa6ca01cce101",
        "array_push": "c1e6879ebbb94f94a8b3f2bbef95469a07d096d4dbc28869c6b6e561e43d746f",
        "array_abort": 2984,
        "string_allocate": "138686962d4f9e405d9627f0787116b0d089920d52bc1b01956da9a630bfd47b",
        "string_abort": 2800,
    },
}

DIRECT_FIELDS = {
    25: ("Factory", "totalVolumeETH", "BigDecimal"),
    30: ("Factory", "totalVolumeUSD", "BigDecimal"),
    38: ("Factory", "totalFeesUSD", "BigDecimal"),
    43: ("Factory", "totalFeesETH", "BigDecimal"),
    57: ("Factory", "totalValueLockedETHUntracked", "BigDecimal"),
    65: ("Factory", "owner", "String"),
    72: ("Bundle", "ethPriceUSD", "BigDecimal"),
    289: ("Pool", "token0", "String"),
    295: ("Pool", "token1", "String"),
    308: ("Pool", "feeTier", "BigInt"),
    315: ("Pool", "createdAtTimestamp", "BigInt"),
    322: ("Pool", "createdAtBlockNumber", "BigInt"),
    327: ("Pool", "liquidityProviderCount", "BigInt"),
    335: ("Pool", "liquidity", "BigInt"),
    340: ("Pool", "sqrtPrice", "BigInt"),
    345: ("Pool", "feeGrowthGlobal0X128", "BigInt"),
    350: ("Pool", "feeGrowthGlobal1X128", "BigInt"),
    355: ("Pool", "token0Price", "BigDecimal"),
    360: ("Pool", "token1Price", "BigDecimal"),
    365: ("Pool", "observationIndex", "BigInt"),
    370: ("Pool", "totalValueLockedToken0", "BigDecimal"),
    375: ("Pool", "totalValueLockedToken1", "BigDecimal"),
    389: ("Pool", "volumeToken0", "BigDecimal"),
    394: ("Pool", "volumeToken1", "BigDecimal"),
    408: ("Pool", "collectedFeesToken0", "BigDecimal"),
    413: ("Pool", "collectedFeesToken1", "BigDecimal"),
    418: ("Pool", "collectedFeesUSD", "BigDecimal"),
}

HELPER_FIELDS = {
    "src/types/schema/Factory#constructor": ("id", "String"),
    "src/types/schema/Factory#set:poolCount": ("poolCount", "BigInt"),
    "src/types/schema/Factory#set:untrackedVolumeUSD": ("untrackedVolumeUSD", "BigDecimal"),
    "src/types/schema/Factory#set:totalValueLockedETH": ("totalValueLockedETH", "BigDecimal"),
    "src/types/schema/Factory#set:totalValueLockedUSD": ("totalValueLockedUSD", "BigDecimal"),
    "src/types/schema/Factory#set:totalValueLockedUSDUntracked": ("totalValueLockedUSDUntracked", "BigDecimal"),
    "src/types/schema/Factory#set:txCount": ("txCount", "BigInt"),
    "src/types/schema/Token#set:symbol": ("symbol", "String"),
    "src/types/schema/Token#set:name": ("name", "String"),
    "src/types/schema/Token#set:totalSupply": ("totalSupply", "BigInt"),
    "src/types/schema/Token#set:decimals": ("decimals", "BigInt"),
    "src/types/schema/Token#set:derivedETH": ("derivedETH", "BigDecimal"),
    "src/types/schema/Token#set:volume": ("volume", "BigDecimal"),
    "src/types/schema/Token#set:volumeUSD": ("volumeUSD", "BigDecimal"),
    "src/types/schema/Token#set:feesUSD": ("feesUSD", "BigDecimal"),
    "src/types/schema/Token#set:totalValueLocked": ("totalValueLocked", "BigDecimal"),
    "src/types/schema/Token#set:whitelistPools": ("whitelistPools", "StringArray"),
}

INVOCATION_ROWS = (
    (17, "Factory", "id"), (20, "Factory", "poolCount"),
    (25, "Factory", "totalVolumeETH"), (30, "Factory", "totalVolumeUSD"),
    (33, "Factory", "untrackedVolumeUSD"), (38, "Factory", "totalFeesUSD"),
    (43, "Factory", "totalFeesETH"), (46, "Factory", "totalValueLockedETH"),
    (49, "Factory", "totalValueLockedUSD"), (52, "Factory", "totalValueLockedUSDUntracked"),
    (57, "Factory", "totalValueLockedETHUntracked"), (60, "Factory", "txCount"),
    (65, "Factory", "owner"), (67, "Bundle", "id"), (72, "Bundle", "ethPriceUSD"),
    (83, "Factory", "poolCount"), (88, "Pool", "id"),
    (109, "Token", "id"), (115, "Token", "symbol"), (121, "Token", "name"),
    (127, "Token", "totalSupply"), (141, "Token", "decimals"),
    (144, "Token", "derivedETH"), (147, "Token", "volume"),
    (150, "Token", "volumeUSD"), (153, "Token", "feesUSD"),
    (156, "Token", "untrackedVolumeUSD"), (159, "Token", "totalValueLocked"),
    (162, "Token", "totalValueLockedUSD"), (165, "Token", "totalValueLockedUSDUntracked"),
    (168, "Token", "txCount"), (171, "Token", "poolCount"),
    (174, "Token", "whitelistPools"), (183, "Token", "id"),
    (189, "Token", "symbol"), (195, "Token", "name"),
    (201, "Token", "totalSupply"), (215, "Token", "decimals"),
    (218, "Token", "derivedETH"), (221, "Token", "volume"),
    (224, "Token", "volumeUSD"), (227, "Token", "untrackedVolumeUSD"),
    (230, "Token", "feesUSD"), (233, "Token", "totalValueLocked"),
    (236, "Token", "totalValueLockedUSD"), (239, "Token", "totalValueLockedUSDUntracked"),
    (242, "Token", "txCount"), (245, "Token", "poolCount"),
    (248, "Token", "whitelistPools"), (265, "Token", "whitelistPools"),
    (282, "Token", "whitelistPools"), (289, "Pool", "token0"),
    (295, "Pool", "token1"), (308, "Pool", "feeTier"),
    (315, "Pool", "createdAtTimestamp"), (322, "Pool", "createdAtBlockNumber"),
    (327, "Pool", "liquidityProviderCount"), (330, "Pool", "txCount"),
    (335, "Pool", "liquidity"), (340, "Pool", "sqrtPrice"),
    (345, "Pool", "feeGrowthGlobal0X128"), (350, "Pool", "feeGrowthGlobal1X128"),
    (355, "Pool", "token0Price"), (360, "Pool", "token1Price"),
    (365, "Pool", "observationIndex"), (370, "Pool", "totalValueLockedToken0"),
    (375, "Pool", "totalValueLockedToken1"), (378, "Pool", "totalValueLockedUSD"),
    (381, "Pool", "totalValueLockedETH"), (384, "Pool", "totalValueLockedUSDUntracked"),
    (389, "Pool", "volumeToken0"), (394, "Pool", "volumeToken1"),
    (397, "Pool", "volumeUSD"), (400, "Pool", "feesUSD"),
    (403, "Pool", "untrackedVolumeUSD"), (408, "Pool", "collectedFeesToken0"),
    (413, "Pool", "collectedFeesToken1"), (418, "Pool", "collectedFeesUSD"),
)

EXPECTED_INVOCATION_INDEX_SHA256 = "e1786369ca1dccbf1328ec9f0534c5f2059851dbc65bc8a2c2a940f85be6b3a9"
EXPECTED_STATIC_SITE_LEDGER_SHA256 = "b7e5d817b3ceabd3349a1611c3571aa53c5d1eba624eca289fa57d927f62d8e5"
EXPECTED_INVOCATION_LEDGER_SHA256 = {
    "legacy-base-root": "36afdbec42f75058e00867441146a1d41884d273edb59c467c436d577bec63c1",
    "legacy-mainnet-qmrv": "b2ef1d198065f2a7690e96cbc38bae14e30fb1a28d17f6a022b4f5f01016d1f4",
    "legacy-mainnet-root": "9b0a18cffd76fcfa16fcda58b2c4202826b7ea4d845688a9875c71f08086c19f",
    "legacy-mainnet-stable": "3348bd8915afc55e66c5c7dcd5825cdd29010b336fc84fe94903ce649b46c12c",
}

CONSTRUCTOR_FLOW = {
    17: (16, 18, "$l4", "static Factory id string"),
    67: (66, 68, "$l1", "static Bundle id string"),
    88: (84, 89, "$l1", "bytesToHex(event.pool)"),
    109: (105, 110, "$l2", "bytesToHex(event.token0)"),
    183: (179, 184, "$l3", "bytesToHex(event.token1)"),
}

COMPLEX_HELPER_FLOW = {
    83: (76, 76),
    115: (110, 110),
    121: (116, 116),
    127: (122, 122),
    141: (128, 139),
    189: (184, 184),
    195: (190, 190),
    201: (196, 196),
    215: (202, 213),
    265: (257, 263),
    282: (274, 280),
}


def _receiver_contract(index: int, entity: str) -> tuple[str, str]:
    if index in CONSTRUCTOR_FLOW:
        local = CONSTRUCTOR_FLOW[index][2]
        instance = {17: "Factory", 67: "Bundle", 88: "Pool", 109: "Token[token0]", 183: "Token[token1]"}[index]
        return instance, local
    if entity == "Factory":
        return "Factory", "$l4"
    if entity == "Bundle":
        return "Bundle", "$l1"
    if entity == "Pool":
        return "Pool", "$l1"
    require(entity == "Token", f"unknown invocation entity: {entity}")
    if index < 183 or index == 282:
        return "Token[token0]", "$l2"
    return "Token[token1]", "$l3"


def _payload_source(index: int, entity: str, field: str) -> str:
    if index in CONSTRUCTOR_FLOW:
        return CONSTRUCTOR_FLOW[index][3]
    special = {
        65: "static zero-address string",
        83: "bigInt.plus(Factory.poolCount, ONE_BI)",
        115: "fetchTokenSymbol(event.token0)",
        121: "fetchTokenName(event.token0)",
        127: "fetchTokenTotalSupply(event.token0) CallResult-pointer quirk",
        141: "non-null fetchTokenDecimals(event.token0) pointer",
        174: "profile-pinned empty token0 whitelist array pointer",
        189: "fetchTokenSymbol(event.token1)",
        195: "fetchTokenName(event.token1)",
        201: "fetchTokenTotalSupply(event.token1) CallResult-pointer quirk",
        215: "non-null fetchTokenDecimals(event.token1) pointer",
        248: "profile-pinned empty token1 whitelist array pointer",
        265: "token1 whitelist backing array after append(Pool.id)",
        282: "token0 whitelist backing array after append(Pool.id)",
        289: "Token[token0].id",
        295: "Token[token1].id",
        308: "ByteArray.fromI32(event.params[2].toI32())",
        315: "event.block.timestamp",
        322: "event.block.number",
    }
    if index in special:
        return special[index]
    if field in {
        "poolCount", "txCount", "liquidityProviderCount", "liquidity", "sqrtPrice",
        "feeGrowthGlobal0X128", "feeGrowthGlobal1X128", "observationIndex",
    }:
        return "ZERO_BI pointer from ByteArray.fromI32(0) in $g2"
    if field in {
        "totalVolumeETH", "totalVolumeUSD", "untrackedVolumeUSD", "totalFeesUSD",
        "totalFeesETH", "totalValueLockedETH", "totalValueLockedUSD",
        "totalValueLockedUSDUntracked", "totalValueLockedETHUntracked", "ethPriceUSD",
        "derivedETH", "volume", "volumeUSD", "feesUSD", "totalValueLocked",
        "token0Price", "token1Price", "totalValueLockedToken0", "totalValueLockedToken1",
        "volumeToken0", "volumeToken1", "collectedFeesToken0", "collectedFeesToken1",
        "collectedFeesUSD",
    }:
        return 'pointer returned by imported bigDecimal.fromString("0") in $g4'
    require(False, f"unclassified payload source at invocation {index}: {entity}.{field}")
    raise AssertionError("unreachable")

FALSE_FLAGS = (
    "actual_historic_handler_outcomes_bound",
    "imported_host_semantics_rederived",
    "big_decimal_numeric_semantics_rederived",
    "static_array_safe",
    "total_supply_erc20_result_data_decoded",
    "graph_store_persistence_proven",
    "graph_handler_rollback_proven_by_retained_wat",
    "complete_pool_or_factory_history",
    "combined_execution_order_proven",
    "source_package_identity_proven",
    "boundary_continuity_proven",
    "parity_proven",
    "live_evidence_complete",
    "backfill_ready",
    "production_ready",
    "readiness_complete",
    "issue_37_acceptance_criterion_complete",
    "issue_38_acceptance_criterion_complete",
    "issue_checkbox_completed",
)


def _factory_collection_spec(profile_id: str) -> Any:
    profile = COLLECTION_PROFILES[profile_id]
    profile_spec = RUNTIME.LegacyCollectionProfileSpec(
        group_id=profile_id,
        start_body_sha256="unused-factory-split-start",
        start_floor=0,
        start_data_literal_pointer=0,
        start_result_globals=("$g9", "$g10"),
        array_constructor_body_sha256=profile["array_constructor"],
        array_abort_source_pointer=profile["array_abort"],
        array_push_body_sha256=profile["array_push"],
        string_allocate_body_sha256=profile["string_allocate"],
        string_abort_source_pointer=profile["string_abort"],
    )
    return RUNTIME.LegacyCollectionSpec(
        constants_start_body_sha256="unused",
        byte_array_from_i32_body_sha256="unused",
        factory_constructor_body_sha256="unused",
        native_math_pow_body_sha256="unused",
        arena_allocate_body_sha256="a623541999e809e36b28e93c8f51c112db4522793a991befaf70302b2e8536d3",
        compute_size_body_sha256="1e18ac493de5e2cdb5602df7e2836274ead1cebc6b6d4f8109e2b330400aa27c",
        allocate_unsafe_body_sha256="e682646c4f45c8ead7d44af5369332c44fc80c348547bbec4a91a2cb6f0d2cf0",
        reallocate_unsafe_body_sha256="143cb92ce81c3e40c7403e38bca744cd74a5a3c38f737898e824d699d7d99b4f",
        event_param_get_body_sha256="fc0df8b86d252ba211dab70c151a7e02b70d6ffd6ed5020a5c03b107e62cd124",
        value_constructor_body_sha256=profile["value_constructor"],
        value_from_big_decimal_body_sha256="c22dc4c0902b6c3aa5b53bf549c79ccb3b8b5175add4de32117b556c19e54741",
        typed_map_get_body_sha256="10c6b7fd4cd1bc0ba3d0f10aed3d6c935831228c31e7363ce4360e496517839a",
        typed_map_get_entry_body_sha256="7252de05e0d18971d8914753ca4f0d39b5984d81ef160014463b3c7212616c50",
        typed_map_set_body_sha256="5ab31969af87a734b8fb29f32ae0046b68dade3b74c24b320bab0fbdd4fde923",
        entry_constructor_body_sha256="77a5c0d652ef661a5abf6c119ff0aa3fb6ff18dce62e9afb86d540988856535c",
        string_eq_body_sha256="13098aa1b32179fca6ed0194087ebd6d83dc2c8f5eee03d97bcf6e2f7aa247a4",
        compare_unsafe_body_sha256="203ddf43add8c0f8f0bddde6136f4a67d1a6a04b331e87bd87d87e40fad1b14d",
        memcpy_body_sha256="b84e9b1f9c3394c4495fd02fa0c1445d46b6988ec8c6fb9799dcda5164617c67",
        memmove_body_sha256="c15a394bae33d7b2489e53bbabf806c9367a6bcf00dfa2e88ebcfec87b3906b6",
        memset_body_sha256="5ab77ca4fcf5e856690cd82342cdf5dbb857f1ff6dae3fdd2ddbcd19896e5b04",
        memory_allocate_body_sha256="ae57abfa142d50c8539b89b63ec1790b25722d7ecdda61aee91a97026daf237d",
        memory_reset_body_sha256="9767c060a0ccee2ec358b573bf2c7334e08e0cca9e14f7618c01cffa39d50c1c",
        function_declarations={},
        profiles={profile_id: profile_spec},
    )


def prove_factory_collection_capsule(context: dict[str, Any]) -> dict[str, Any]:
    """Factory-owned aggregate for its split 7-line start / 25-line constants topology."""

    profile_id = context["profile"]["profile_id"]
    spec = _factory_collection_spec(profile_id)
    ops = runtime_ops()
    allocator = RUNTIME._prove_legacy_allocator_dependencies(context, ops, spec)
    indexed_value = RUNTIME._prove_legacy_indexed_and_value_dependencies(context, ops, spec)
    strings = RUNTIME._prove_legacy_string_dependencies(context, ops, spec)
    arrays = RUNTIME._prove_legacy_array_dependencies(context, ops, spec)
    typed_map = RUNTIME._prove_legacy_typed_map_dependencies(context, ops, spec)
    return {
        "factory_split_start_parent_proof": "factory-fee-growth-init native_start_and_g2",
        "allocator_and_arraybuffer": allocator,
        "indexed_access_and_value": indexed_value,
        "string_runtime": strings,
        "entry_array_runtime": arrays,
        "typed_map_runtime": typed_map,
        "shared_runtime_source_sha256": RUNTIME_SHA256,
        "legacy_collection_capsule_structurally_closed": True,
        "low_level_memory_semantics_rederived": False,
        "imported_host_behavior_rederived": False,
    }


def _wrapper_kind(function: Any, kind: str, tag: int) -> dict[str, Any]:
    lines = [normalized(line) for line in function.lines]
    require(len(lines) == 11, f"Value.from{kind} length drift")
    require(
        lines[2:11] == [
            "call $~lib/@graphprotocol/graph-ts/index/Value#constructor",
            "local.tee $l1",
            f"i32.const {tag}",
            "i32.store",
            "local.get $l1",
            "local.get $p0",
            "i64.extend_i32_u",
            "i64.store offset=8",
            "local.get $l1)",
        ],
        f"Value.from{kind} kind/payload/return flow drift",
    )
    return {"function": function.name, "body_sha256": function_sha256(function), "kind_tag": tag}


def prove_value_and_entity_runtime(context: dict[str, Any]) -> dict[str, Any]:
    entity = function_by_suffix(context, "index/Entity#constructor")
    entity_lines = [normalized(line) for line in entity.lines]
    require(len(entity_lines) == 23, "Entity constructor length drift")
    require(entity_lines[15:23] == [
        "local.get $p0", "i32.const 0", "i32.store", "local.get $p0",
        "i32.const 0",
        "call $~lib/array/Array<~lib/@graphprotocol/graph-ts/index/TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#constructor",
        "i32.store", "local.get $p0)",
    ], "Entity backing-array construction drift")
    wrappers = {
        "String": _wrapper_kind(function_by_suffix(context, "index/Value.fromString"), "String", 0),
        "BigDecimal": _wrapper_kind(function_by_suffix(context, "index/Value.fromBigDecimal"), "BigDecimal", 2),
        "BigInt": _wrapper_kind(function_by_suffix(context, "index/Value.fromBigInt"), "BigInt", 7),
    }
    string_array = function_by_suffix(context, "index/Value.fromStringArray")
    array_lines = [normalized(line) for line in string_array.lines]
    require(len(array_lines) == 35, "Value.fromStringArray length drift")
    require(array_lines[26:35] == [
        "call $~lib/@graphprotocol/graph-ts/index/Value#constructor", "local.tee $p0",
        "i32.const 4", "i32.store", "local.get $p0", "local.get $l2",
        "i64.extend_i32_u", "i64.store offset=8", "local.get $p0)",
    ], "Value.fromStringArray kind/payload/return flow drift")
    wrappers["StringArray"] = {
        "function": string_array.name,
        "body_sha256": function_sha256(string_array),
        "kind_tag": 4,
        "ordered_element_conversion_and_array_payload_structurally_proven": True,
    }
    return {
        "entity_constructor": {
            "function": entity.name,
            "body_sha256": function_sha256(entity),
            "fresh_zero_length_entry_array_backing_structurally_proven": True,
        },
        "value_wrappers": wrappers,
        "constructor_allocation_freshness_bound_by_collection_capsule": True,
    }


def prove_literal_payloads(context: dict[str, Any]) -> dict[str, Any]:
    handler = context["handler"]
    memory = context["memory"]

    def constant_at(index: int) -> int:
        line = normalized(handler.lines[index])
        require(line.startswith("i32.const "), f"literal payload constant missing at {index}")
        return int(line.split()[1])

    factory_id = V2.decoded_wat_constant(handler.lines[16], memory)
    require(factory_id in (
        "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    ), "Factory ID literal drift")
    require(V2.decoded_wat_constant(handler.lines[63], memory) == "0x0000000000000000000000000000000000000000", "Factory owner literal drift")
    require(V2.decoded_wat_constant(handler.lines[66], memory) == "1", "Bundle ID literal drift")
    empty_arrays = []
    for call_index, pointer_index, token in ((174, 173, "token0"), (248, 247, "token1")):
        pointer = constant_at(pointer_index)
        require(pointer + 8 <= len(memory), f"{token} whitelist array header out of bounds")
        backing = int.from_bytes(memory[pointer:pointer + 4], "little")
        length = int.from_bytes(memory[pointer + 4:pointer + 8], "little")
        require(backing == pointer - 8 and length == 0, f"{token} whitelist initializer is not the pinned empty array")
        empty_arrays.append({
            "invocation_relative_wat_line": call_index,
            "pointer": pointer,
            "backing_pointer": backing,
            "length": length,
            "header_sha256": hashlib.sha256(bytes(memory[pointer:pointer + 8])).hexdigest(),
            "empty_array_object_structurally_proven": True,
        })
    return {
        "factory_id": factory_id,
        "factory_owner": "0x0000000000000000000000000000000000000000",
        "bundle_id": "1",
        "empty_whitelist_initializers": empty_arrays,
        "literal_and_empty_array_payloads_structurally_proven": True,
    }


def prove_static_site_closure(context: dict[str, Any]) -> dict[str, Any]:
    functions = context["functions"]
    reachable = WRITER.reachable_functions(functions, context["handler"], tuple(context["indirect"]))
    sites: list[dict[str, Any]] = []
    for name in sorted(reachable):
        function = functions[name]
        for index, line in enumerate(function.lines):
            if call_name(line) != LEGACY_MAP_SET:
                continue
            if name == context["handler"].name:
                require(index in DIRECT_FIELDS, f"unclassified direct handler TypedMap#set site: {index}")
                entity, field, kind = DIRECT_FIELDS[index]
                key_candidates = [
                    candidate_index
                    for candidate_index in range(max(0, index - 20), index)
                    if V2.decoded_wat_constant(function.lines[candidate_index], context["memory"]) == field
                ]
                require(len(key_candidates) == 1, f"direct {entity}.{field} key operand drift")
                key_line = key_candidates[0]
                receiver_instance, receiver_local = _receiver_contract(index, entity)
                require(normalized(function.lines[key_line - 1]) in (f"local.get {receiver_local}", f"local.tee {receiver_local}"), f"direct {entity}.{field} receiver operand drift")
                expected_wrapper = f"index/Value.from{kind}"
                require(call_name(function.lines[index - 1]).endswith(expected_wrapper), f"direct {entity}.{field} wrapper drift")
                sites.append({
                    "function": name,
                    "relative_wat_line": index,
                    "entity": receiver_instance,
                    "receiver_operand": receiver_local,
                    "decoded_key": field,
                    "key_operand_relative_wat_line": key_line,
                    "value_kind": kind,
                    "payload_source": _payload_source(index, entity, field),
                    "receiver_key_kind_payload_and_set_call_classified": True,
                })
                continue
            require(name in HELPER_FIELDS, f"unclassified reachable TypedMap#set helper: {name}")
            field, kind = HELPER_FIELDS[name]
            require(index in (5, 9), f"{name} map-set position drift")
            decoded = [V2.decoded_wat_constant(candidate, context["memory"]) for candidate in function.lines]
            require(field in decoded, f"{name} decoded key drift")
            wrapper = call_name(function.lines[index - 1])
            require(wrapper is not None and wrapper.endswith(f"index/Value.from{kind}"), f"{name} Value wrapper drift")
            is_constructor = name.endswith("#constructor")
            sites.append({
                "function": name,
                "relative_wat_line": index,
                "receiver_operand": "$l1 (fresh Entity constructor result)" if is_constructor else "$p0",
                "decoded_key": field,
                "value_kind": kind,
                "payload_operand": "$p0" if is_constructor else "$p1",
                "receiver_key_kind_payload_and_set_call_classified": True,
            })
    require(len(sites) == 44, f"reachable static TypedMap#set site count drift: {len(sites)}")
    require(sum(item["function"] == context["handler"].name for item in sites) == 27, "direct static site count drift")
    require(len({item["function"] for item in sites if item["function"] != context["handler"].name}) == 17, "helper static site count drift")
    require(canonical_sha256(sites) == EXPECTED_STATIC_SITE_LEDGER_SHA256, "complete static setter semantic ledger drift")
    return {
        "reachable_static_typed_map_set_site_count": 44,
        "direct_handler_site_count": 27,
        "helper_site_count": 17,
        "all_reachable_static_typed_map_set_sites_classified": True,
        "site_inventory_sha256": canonical_sha256(sites),
        "sites": sites,
    }


def _kind_for_invocation(index: int, field: str) -> str:
    if index in DIRECT_FIELDS:
        return DIRECT_FIELDS[index][2]
    target_field_kinds = {field_name: kind for field_name, kind in HELPER_FIELDS.values()}
    require(field in target_field_kinds, f"invocation field has no helper kind: {field}")
    return target_field_kinds[field]


def prove_invocation_ledger(context: dict[str, Any], expected_written: list[str]) -> dict[str, Any]:
    handler = context["handler"]
    functions = context["functions"]
    expanded = []
    for index, line in enumerate(handler.lines):
        target = call_name(line)
        if target == LEGACY_MAP_SET or (
            target in functions and any(call_name(candidate) == LEGACY_MAP_SET for candidate in functions[target].lines)
        ):
            expanded.append(index)
    require(len(expanded) == 78, "expanded map-write invocation count drift")
    require(canonical_sha256(expanded) == EXPECTED_INVOCATION_INDEX_SHA256, "expanded map-write invocation index drift")
    require(expanded == [item[0] for item in INVOCATION_ROWS], "reviewed invocation ledger index drift")
    rows: list[dict[str, Any]] = []
    for index, entity, field in INVOCATION_ROWS:
        target = call_name(handler.lines[index])
        receiver_instance, receiver_local = _receiver_contract(index, entity)
        if index in DIRECT_FIELDS:
            require(target == LEGACY_MAP_SET, f"direct invocation target drift at {index}")
            key_candidates = [
                candidate_index
                for candidate_index in range(max(0, index - 20), index)
                if V2.decoded_wat_constant(handler.lines[candidate_index], context["memory"]) == field
            ]
            require(len(key_candidates) == 1, f"direct decoded key drift at {index}")
            key_line = key_candidates[0]
            receiver_line = key_line - 1
            slice_start = receiver_line
            require(normalized(handler.lines[receiver_line]) in (f"local.get {receiver_local}", f"local.tee {receiver_local}"), f"direct receiver drift at {index}")
            key_authority = {"kind": "direct decoded constant", "relative_wat_line": key_line}
        elif field == "id":
            require(target == "src/types/schema/Factory#constructor", f"constructor target drift at {index}")
            slice_start, receiver_line, expected_local, _source = CONSTRUCTOR_FLOW[index]
            require(expected_local == receiver_local, f"constructor receiver-local authority drift at {index}")
            require(
                normalized(handler.lines[receiver_line]) in (f"local.tee {receiver_local}", f"local.set {receiver_local}"),
                f"constructor result receiver drift at {index}",
            )
            key_authority = {"kind": "constructor helper decoded constant", "helper": target}
        else:
            require(target in HELPER_FIELDS and HELPER_FIELDS[target][0] == field, f"helper target/field drift at {index}")
            slice_start, receiver_line = COMPLEX_HELPER_FLOW.get(index, (index - 2, index - 2))
            require(
                normalized(handler.lines[receiver_line]) in (f"local.get {receiver_local}", f"local.tee {receiver_local}"),
                f"helper receiver drift at {index}",
            )
            key_authority = {"kind": "helper decoded constant", "helper": target}
        operand_slice = [normalized(line) for line in handler.lines[slice_start:index + 1]]
        require(operand_slice, f"empty operand slice at {index}")
        rows.append({
            "relative_wat_line": index,
            "entity": entity,
            "entity_instance": receiver_instance,
            "receiver_local": receiver_local,
            "receiver_instruction_relative_wat_line": receiver_line,
            "field": field,
            "decoded_key": field,
            "key_authority": key_authority,
            "value_kind": _kind_for_invocation(index, field),
            "payload_source": _payload_source(index, entity, field),
            "operand_slice_relative_wat_lines": [slice_start, index],
            "operand_slice_normalized_sha256": canonical_sha256(operand_slice),
            "call_target": target,
            "exact_receiver_key_kind_payload_and_call_target_structurally_bound": True,
            "potential_lexical_path_not_simultaneous_write": True,
        })
    written = sorted({f"{item['entity']}.{item['field']}" for item in rows})
    require(written == expected_written, "legacy 59-written-field set differs from modern v1 authority")
    require("Pool.tick" not in written, "Pool.tick unexpectedly acquired a setter invocation")
    profile = context["profile"]["profile_id"]
    require(canonical_sha256(rows) == EXPECTED_INVOCATION_LEDGER_SHA256[profile], f"{profile} complete invocation semantic ledger drift")
    return {
        "expanded_map_write_invocation_count": 78,
        "expanded_map_write_invocation_indices_sha256": canonical_sha256(expanded),
        "invocation_semantic_ledger_sha256": canonical_sha256(rows),
        "all_expanded_invocations_classified": True,
        "all_expanded_invocation_receiver_key_kind_payload_flows_structurally_bound": True,
        "written_field_count": len(written),
        "written_fields": written,
        "required_absent_fields": ["Pool.tick"],
        "pool_tick_required_absence_machine_proven": True,
        "invocations": rows,
    }


def prove_legacy_context(
    context: dict[str, Any],
    price_proof: dict[str, Any],
    fee_proof: dict[str, Any],
    upstream_effect: dict[str, Any],
    expected_written: list[str],
) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    require(price_proof["mapping_cid"] == fee_proof["mapping_cid"] == upstream_effect["mapping_cid"] == context["cid"], "legacy proof CID mismatch")
    authority = fee_proof["artifact_and_handler_authority"]
    require(authority["handler_line_count"] == 443, f"{profile} handler length drift")
    require(
        function_sha256(context["handler"]) == authority["handler_body_sha256"],
        f"{profile} handler body authority drift",
    )
    reachable = sorted(
        WRITER.reachable_functions(
            context["functions"], context["handler"], tuple(context["indirect"])
        )
    )
    body_bindings = [
        {"function": name, "body_sha256": function_sha256(context["functions"][name])}
        for name in reachable
    ]
    require(
        canonical_sha256(body_bindings)
        == upstream_effect["reachable_effect_closure"]["reachable_function_body_bindings_sha256"],
        f"{profile} complete reachable body authority drift",
    )
    collection = prove_factory_collection_capsule(context)
    runtime = prove_value_and_entity_runtime(context)
    literal_payloads = prove_literal_payloads(context)
    sites = prove_static_site_closure(context)
    ledger = prove_invocation_ledger(context, expected_written)
    static = fee_proof["legacy_static_residual_boundary"]
    require(static["static_array_safe"] is False, f"{profile} static-array safety boundary drift")
    require(static["total_supply_helper"]["erc20_result_data_decoded"] is False, f"{profile} totalSupply decode boundary drift")
    require(
        upstream_effect["effect_trace_proof"]["all_handler_local_normal_and_explicit_trap_exits_machine_checked"] is True
        and upstream_effect["effect_trace_proof"]["same_path_and_order_machine_proven"] is True,
        f"{profile} effect-path parent drift",
    )
    return {
        "profile_id": profile,
        "mapping_cid": context["cid"],
        "control_generation": "legacy",
        "artifact_and_handler_authority": authority,
        "complete_reachable_body_authority": {
            "reachable_function_count": len(reachable),
            "reachable_function_body_bindings_sha256": canonical_sha256(body_bindings),
            "all_reachable_function_bodies_bound": True,
        },
        "factory_native_start_and_global_inventory": fee_proof["native_start_and_g2"],
        "public_factory_collection_capsule": collection,
        "entity_and_value_runtime": runtime,
        "literal_payloads": literal_payloads,
        "static_typed_map_set_closure": sites,
        "handler_invocation_ledger": ledger,
        "guard_and_return_boundaries": fee_proof["guard_and_return_boundaries"],
        "normal_return_and_partial_effect_contract": {
            "generation_frontend": upstream_effect["generation_frontend"],
            "effect_trace_proof": upstream_effect["effect_trace_proof"],
            "reviewed_effect_order": upstream_effect["reviewed_effect_order"],
            "graph_handler_rollback_proven_by_retained_wat": False,
        },
        "legacy_static_quirks": {
            "parent_stage_complete_static_handler_contract": static["complete_static_handler_contract"],
            "static_array_profile": static["static_array_profile"],
            "static_array_safe": static["static_array_safe"],
            "total_supply_helper": static["total_supply_helper"],
        },
        "price_parent_proof_sha256": canonical_sha256(price_proof),
        "fee_growth_initialization_parent_proof_sha256": canonical_sha256(fee_proof),
        "upstream_effect_proof_sha256": canonical_sha256(upstream_effect),
        "stored_field_contract_count": 60,
        "written_field_count": 59,
        "required_absent_fields": ["Pool.tick"],
        "all_59_written_field_transitions_statically_classified": True,
        "complete_static_handler_contract": True,
        "actual_historic_handler_outcomes_bound": False,
        "selected_persistence_proven": False,
        "complete_pool_or_factory_history": False,
    }


def _bind_source(root: Path, relative: Path, digest: str) -> None:
    path = root / relative
    require(path.is_file() and raw_sha256(path) == digest, f"source digest drift: {relative}")


def bind_transitive_input_manifest(root: Path, root_contract: Path) -> list[dict[str, Any]]:
    """Recursively bind every source-contract record below one pinned contract root."""

    pending = [root_contract]
    visited_contracts: set[str] = set()
    records: dict[str, dict[str, Any]] = {}
    while pending:
        contract_path = pending.pop()
        contract_key = contract_path.as_posix()
        if contract_key in visited_contracts:
            continue
        visited_contracts.add(contract_key)
        contract = load_json(root / contract_path)
        require(isinstance(contract, dict), f"transitive contract is not an object: {contract_path}")
        for name, record in sorted(contract.get("source_contracts", {}).items()):
            require(isinstance(record, dict) and isinstance(record.get("path"), str), f"invalid source-contract record: {contract_path}:{name}")
            relative = Path(record["path"])
            require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe transitive input path: {relative}")
            digest = record.get("raw_sha256")
            require(isinstance(digest, str) and len(digest) == 64, f"missing transitive raw digest: {relative}")
            _bind_source(root, relative, digest)
            canonical = record.get("canonical_sha256")
            if canonical is not None:
                require(canonical_sha256(load_json(root / relative)) == canonical, f"transitive canonical digest drift: {relative}")
            existing = records.get(relative.as_posix())
            material = {"path": relative.as_posix(), "raw_sha256": digest}
            if canonical is not None:
                material["canonical_sha256"] = canonical
            if "contract_version" in record:
                material["contract_version"] = record["contract_version"]
            if existing is None:
                records[relative.as_posix()] = {**material, "declared_by": [[contract_key, name]]}
            else:
                require(existing["path"] == material["path"] and existing["raw_sha256"] == material["raw_sha256"], f"conflicting transitive input authority: {relative}")
                for optional in ("canonical_sha256", "contract_version"):
                    if optional in existing and optional in material:
                        require(existing[optional] == material[optional], f"conflicting transitive {optional}: {relative}")
                    elif optional in material:
                        existing[optional] = material[optional]
                existing["declared_by"].append([contract_key, name])
            if relative.suffix == ".json":
                candidate = load_json(root / relative)
                if isinstance(candidate, dict) and "source_contracts" in candidate:
                    pending.append(relative)
    output = [records[key] for key in sorted(records)]
    require(len(output) >= 30, "transitive input manifest unexpectedly incomplete")
    return output


def load_sources(root: Path, *, recompute_wat: bool = True, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    _bind_source(root, PRICE_VERIFIER_PATH.relative_to(REPOSITORY), PRICE_VERIFIER_SHA256)
    _bind_source(root, PRICE_CONTRACT_PATH, PRICE_CONTRACT_SHA256)
    _bind_source(root, RUNTIME_PATH, RUNTIME_SHA256)
    price_sources = PRICE.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    price_contract = PRICE.verify_contract(root, sources=price_sources, recompute_wat=False, wasm2wat=wasm2wat)
    require(price_contract["contract_version"] == PRICE_CONTRACT_VERSION, "price parent version drift")
    require(canonical_sha256(price_contract) == PRICE_CONTRACT_CANONICAL_SHA256, "price parent canonical digest drift")
    fee_sources = price_sources["parent_sources"]["parent_sources"]
    modern_contract = fee_sources["modern_factory_static_contract"]
    modern_proofs = modern_contract["modern_factory_static_proofs"]
    require(len(modern_proofs) == 2, "two modern static proofs required")
    modern_written = modern_proofs[0]["field_contract"]["written_fields"]
    require(len(modern_written) == 59 and all(proof["field_contract"]["written_fields"] == modern_written for proof in modern_proofs), "modern written-field authority drift")
    require(all(proof["field_contract"]["stored_field_contract_count"] == 60 for proof in modern_proofs), "modern 60-field authority drift")
    transitive_inputs = bind_transitive_input_manifest(root, PRICE_CONTRACT_PATH)
    contexts = price_sources["legacy_contexts"]
    price_by_cid = {proof["mapping_cid"]: proof for proof in price_sources["legacy_proofs"]}
    fee_by_cid = {proof["mapping_cid"]: proof for proof in fee_sources["legacy_proofs"]}
    effect_by_cid = fee_sources["upstream_factory_effects"]
    require(len(contexts) == len(price_by_cid) == len(fee_by_cid) == len(effect_by_cid) == 4, "four legacy proof contexts required")
    proofs = [
        prove_legacy_context(context, price_by_cid[context["cid"]], fee_by_cid[context["cid"]], effect_by_cid[context["cid"]], modern_written)
        for context in contexts
    ] if recompute_wat else []
    return {
        "price_parent_contract": price_contract,
        "price_sources": price_sources,
        "fee_sources": fee_sources,
        "modern_contract": modern_contract,
        "modern_proofs": modern_proofs,
        "legacy_contexts": contexts,
        "legacy_proofs": proofs,
        "written_fields": modern_written,
        "transitive_inputs": transitive_inputs,
    }


def build_segments(sources: dict[str, Any]) -> list[dict[str, Any]]:
    legacy = {proof["mapping_cid"]: proof for proof in sources["legacy_proofs"]}
    modern = {proof["mapping_cid"]: proof for proof in sources["modern_proofs"]}
    results = []
    for segment in sources["fee_sources"]["matrix_contract"]["segments"]:
        handlers = [item for item in segment["handlers"] if item["handler_id"] == HANDLER_ID]
        require(len(handlers) == 1, f"{segment['segment_id']} Factory handler binding drift")
        cid = handlers[0]["mapping_cid"]
        require(cid in legacy or cid in modern, f"{segment['segment_id']} Factory proof missing")
        proof = legacy.get(cid) or modern[cid]
        generation = "legacy" if cid in legacy else "modern"
        complete = proof["complete_static_handler_contract"]
        require(complete is True, f"{segment['segment_id']} static proof is incomplete")
        semantic = {
            "handler_id": HANDLER_ID,
            "stored_field_contract_count": 60,
            "written_field_count": 59,
            "written_fields": sources["written_fields"],
            "required_absent_fields": ["Pool.tick"],
            "complete_static_handler_contract": True,
            "actual_historic_handler_outcomes_bound": False,
            "graph_store_persistence_proven": False,
            "complete_pool_or_factory_history": False,
        }
        provenance = {"mapping_cid": cid, "control_generation": generation, "profile_id": proof["profile_id"], "proof_sha256": canonical_sha256(proof)}
        results.append({
            "segment_id": segment["segment_id"], "network": segment["network"], "deployment": segment["deployment"],
            "start_block_inclusive": segment["start_block_inclusive"], "end_block_inclusive": segment["end_block_inclusive"],
            "semantic_surface": semantic, "semantic_surface_sha256": canonical_sha256(semantic),
            "provenance_surface": provenance, "provenance_surface_sha256": canonical_sha256(provenance),
            "execution_model": "undecided", "backfill_allowed": False,
        })
    require(len(results) == 8, "eight Factory segments required")
    require(sum(item["provenance_surface"]["control_generation"] == "legacy" for item in results) == 6, "six legacy segment projections required")
    return results


def build_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for left, right in itertools.combinations(segments, 2):
        results.append({
            "left_segment_id": left["segment_id"], "right_segment_id": right["segment_id"],
            "scoped_semantic_equal": left["semantic_surface"] == right["semantic_surface"],
            "left_semantic_surface_sha256": left["semantic_surface_sha256"],
            "right_semantic_surface_sha256": right["semantic_surface_sha256"],
            "provenance_equal": left["provenance_surface"] == right["provenance_surface"],
            "left_provenance_surface_sha256": left["provenance_surface_sha256"],
            "right_provenance_surface_sha256": right["provenance_surface_sha256"],
        })
    require(len(results) == 28, "28 pairwise segment diffs required")
    return results


def truth_boundary() -> dict[str, bool]:
    value = {key: False for key in FALSE_FLAGS}
    value.update({
        "four_exact_legacy_factory_artifacts_recomputed": True,
        "four_legacy_factory_collection_capsules_closed": True,
        "all_44_reachable_static_typed_map_set_sites_classified": True,
        "all_78_expanded_map_write_invocations_classified": True,
        "all_59_written_field_transitions_statically_classified": True,
        "pool_tick_required_absence_machine_proven": True,
        "all_18_factory_static_paths_closed": True,
        "scoped_factory_static_semantics_complete": True,
    })
    return value


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["legacy_proofs"]
    require(len(proofs) == 4, "legacy proofs must be recomputed")
    segments = build_segments(sources)
    diffs = build_diffs(segments)
    price_contract = sources["price_parent_contract"]
    transitive = sources["transitive_inputs"]
    return {
        "format_version": 2,
        "contract_version": CONTRACT_VERSION,
        "authority_contract": {
            "semantic_authority": "four exact retained deployed legacy Factory WASMs and two exact modern v1 Factory proofs, projected through the eight-segment writer matrix",
            "claim": "path-qualified complete static Factory.handlePoolCreated contract: all 60 stored fields are classified as 59 written fields plus required absence of Pool.tick; imported host outcomes, persistence, histories, parity, backfill, and readiness are excluded",
            "legacy_quirk_boundary": "Base retains six leading empty static-definition slots; mainnet retains six leading empty slots plus six entries; totalSupply success passes the CallResult pointer and revert passes zero to ByteArray.fromI32",
            "base_commit": BASE_COMMIT,
            "base_tree": BASE_TREE,
        },
        "scope": {
            "factory_upstream_path_count": 18,
            "factory_paths_closed_before": 14,
            "factory_paths_closed_after": 18,
            "factory_paths_residual_after": 0,
            "stored_field_contract_count": 60,
            "written_field_count": 59,
            "required_absent_field_count": 1,
            "required_absent_fields": ["Pool.tick"],
            "reachable_static_typed_map_set_site_count": 44,
            "classified_static_typed_map_set_site_count": 44,
            "expanded_map_write_invocation_count": 78,
            "classified_expanded_map_write_invocation_count": 78,
            "legacy_mapping_count": 4,
            "legacy_segment_count": 6,
            "modern_segment_count": 2,
            "issue_acceptance_checkbox_completed": False,
        },
        "source_contracts": {
            "factory_pool_price_initialization": {
                "path": PRICE_CONTRACT_PATH.as_posix(), "raw_sha256": PRICE_CONTRACT_SHA256,
                "canonical_sha256": PRICE_CONTRACT_CANONICAL_SHA256, "contract_version": PRICE_CONTRACT_VERSION,
                "transitive_input_count": len(transitive),
                "transitive_input_manifest_sha256": canonical_sha256(transitive),
            },
            "factory_pool_price_initialization_verifier": {
                "path": PRICE_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(), "raw_sha256": PRICE_VERIFIER_SHA256,
            },
            "shared_wat_runtime": {"path": RUNTIME_PATH.as_posix(), "raw_sha256": RUNTIME_SHA256},
        },
        "toolchain": {
            "name": "WABT wasm2wat and wat2wasm",
            "version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-factory-wasm>"],
            "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"],
        },
        "transitive_input_manifest": transitive,
        "legacy_mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "live_authority": [
                "required-nonempty runtime population and CID/block-bound samples on both sides of each graft boundary",
                "target Graph Node deployment identity plus entity-count, VID, and PoI evidence",
                "live repaired-vs-legacy parity and release evidence",
            ],
            "static_truth_boundaries": [
                "imported host and numeric semantics are not rederived",
                "static metadata arrays remain unsafe and totalSupply decoding remains incorrect",
                "Graph store persistence, rollback, full histories, scheduling, continuity, parity, backfill, production, and readiness remain false",
                "issues #37 and #38 gain no completed acceptance checkbox from this offline slice",
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
        require(path.is_file(), f"Factory static v2 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "Factory static v2 byte rendering drift")
    require(actual == expected, "Factory static v2 contract does not reproduce")
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
    errors = tuple(dict.fromkeys((VerificationError, PRICE.VerificationError, PRICE.PARENT.VerificationError, FEE_INIT.VerificationError, EFFECTS.VerificationError, V2.VerificationError, WRITER.VerificationError)))
    try:
        contract = write_contract(arguments.root, arguments.wasm2wat) if arguments.write_contract else verify_contract(arguments.root, wasm2wat=arguments.wasm2wat)
    except (OSError, KeyError, TypeError, ValueError, *errors) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 Factory static v2: "
        f"{contract['scope']['legacy_mapping_count']} legacy mappings / {contract['scope']['legacy_segment_count']} legacy segments, "
        f"{contract['scope']['classified_static_typed_map_set_site_count']}/{contract['scope']['reachable_static_typed_map_set_site_count']} static sites, "
        f"{contract['scope']['classified_expanded_map_write_invocation_count']}/{contract['scope']['expanded_map_write_invocation_count']} expanded invocations, "
        f"{contract['scope']['written_field_count']} written + {contract['scope']['required_absent_field_count']} required absent, "
        f"{len(contract['segment_diffs'])} diffs; no issue checkbox completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
