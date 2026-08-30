#!/usr/bin/env python3
"""Prove the two retained modern Uniswap V3 Factory static handler contracts.

The retained deployed WASM is the semantic authority.  This supplement reuses
the exact modern guard and six-mapping effect-suffix proofs, then closes only
the modern Base and modern mainnet ``complete_static_handler_contract`` paths.

The proof is symbolic over the exact token-call helper outcomes.  It proves
how every such outcome is written, which normal returns occur, and which Graph
host effects have been invoked.  It does not supply historic call results,
Graph Node rollback, runtime population, continuity, or parity authority.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import struct
import sys
from collections import deque
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/factory-static/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-modern-factory-static/v1"
EFFECTS_PATH = REPOSITORY / "scripts/verify-uniswap-v3-factory-effects.py"
RUNTIME_SOURCE_PATH = Path("scripts/uniswap_v3_wat_runtime.py")
RUNTIME_PATH = REPOSITORY / RUNTIME_SOURCE_PATH
EFFECTS_CONTRACT_PATH = Path("uniswap-v3/factory-effects/v1/contract.json")
EFFECTS_CONTRACT_SHA256 = "f737d67550721ed418d8b5fb83424a55e429dceea7596643c69748458c5ac892"
BASE_COMMIT = "699c9feeea3b1ed89c7f62dc86a46cf8ff1e7f03"

EFFECTS_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_factory_effects_for_modern_static", EFFECTS_PATH
)
if EFFECTS_SPEC is None or EFFECTS_SPEC.loader is None:
    raise RuntimeError(f"cannot import {EFFECTS_PATH}")
EFFECTS = importlib.util.module_from_spec(EFFECTS_SPEC)
sys.modules[EFFECTS_SPEC.name] = EFFECTS
EFFECTS_SPEC.loader.exec_module(EFFECTS)
V2 = EFFECTS.V2
WRITER = EFFECTS.WRITER

RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_wat_runtime_for_modern_factory_static", RUNTIME_PATH
)
if RUNTIME_SPEC is None or RUNTIME_SPEC.loader is None:
    raise RuntimeError(f"cannot import {RUNTIME_PATH}")
try:
    RUNTIME_SOURCE_BYTES = RUNTIME_PATH.read_bytes()
except OSError as error:
    raise RuntimeError(f"cannot read {RUNTIME_PATH}: {error}") from error
RUNTIME = importlib.util.module_from_spec(RUNTIME_SPEC)
sys.modules[RUNTIME_SPEC.name] = RUNTIME
exec(
    compile(RUNTIME_SOURCE_BYTES, str(RUNTIME_PATH), "exec"),
    RUNTIME.__dict__,
)


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_candidate_runtime(root: Path) -> str:
    """Require candidate-root bytes to equal the exact source imported above."""

    candidate_path = root.resolve() / RUNTIME_SOURCE_PATH
    try:
        candidate_bytes = candidate_path.read_bytes()
    except OSError as error:
        raise VerificationError(
            f"cannot read candidate-root shared WAT runtime {candidate_path}: {error}"
        ) from error
    require(
        candidate_bytes == RUNTIME_SOURCE_BYTES,
        "candidate-root shared WAT runtime bytes differ from the exact imported runtime bytes",
    )
    return hashlib.sha256(candidate_bytes).hexdigest()


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


def normalized(line: str) -> str:
    return EFFECTS.normalized(line)


def call_name(line: str) -> str | None:
    return EFFECTS.call_name(line)


MODERN_CIDS = (
    "QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr",
    "QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb",
)


EXPECTED_HELPERS: dict[str, dict[str, Any]] = {
    "modern-base": {
        "start": ("~start", 65, "03a9880de5c636da605722c9de980a9d8b831bd818f1ee932150410aceb58f04"),
        "symbol": ("/fetchTokenSymbol", 113, "96e3c6a30f1a578ee73fb0728502be0d664c45ae00ae81950a4205efebd63005"),
        "name": ("/fetchTokenName", 113, "9c9d2d6f5b2f57cf6dea0c883b94c10ee85cbdea1936a3217b5f5e273103ee86"),
        "total_supply": ("/fetchTokenTotalSupply", 52, "f81e091e27097d63c781cbe34253e50b5bdaca99120aad68fbbccd3b51934036"),
        "decimals": ("/fetchTokenDecimals", 270, "a7d58596c9cb914b93bf95ce0a4737475dab9d152e13d5ea1ef61d34c08dd394"),
        "static_definition": ("StaticTokenDefinition.fromAddress", 36, "92bc949a17ab31a22ee3f81a5ff1bc20878df57af3af314ee542ad1c103aa8ef"),
        "whitelist_membership": ("Array<~lib/string/String>#includes", 44, "fd7533a73510430897d69bce95502409898dccffd1eb01592089dbec82bfdc86"),
        "whitelist_getter": ("schema/Token#get:whitelistPools", 103, "346159ad6af19879530e3cd0b2eb2d2deb6bd6b1beb6166da50c2abd24dd8ebd"),
        "pool_id_getter": ("schema/Pool#get:id", 24, "082572dceb0673ebc1ba252ecc46e579316e6b34afeba9f7d9861849e5e26493"),
        "token_id_getter": ("schema/Token#get:id", 24, "fa5baf7f95cc0c79730a34e04262e54730f53798b851866f2135f7976d18c9ba"),
        "string_array_value": ("Value.fromStringArray", 103, "a5bcd2f19ae7d650900aa231b50aee26423f702f3f1f21aa069080c8fa3a3662"),
        "static_profile": "base-safe-empty",
        "static_definitions": [],
    },
    "modern-mainnet": {
        "start": ("~start", 49, "82f696b281a1321a3b9fb5a98645ede19e925b0f3a10525624a093509885fd76"),
        "symbol": ("/fetchTokenSymbol", 113, "4f09a6bf9196de9bb7574e45b49e04e6998b40e02df2603ca33a7732a4714ed9"),
        "name": ("/fetchTokenName", 113, "f760179a543ed09dc1a37c9bb0909376ec26c812b8917f55775e2fcd3bb607bd"),
        "total_supply": ("/fetchTokenTotalSupply", 52, "3feccb548d20c8961a76b9da3ca4e441ffdb90df4034d08b38814864371fb405"),
        "decimals": ("/fetchTokenDecimals", 270, "6b4849eab563bdf783203bf2541fd1687e652f51f2fd4c9b5cf0b3362d8653f5"),
        "static_definition": ("StaticTokenDefinition.fromAddress", 152, "9b4a566cea79a2ce18a1bdbe6d6add7fc42b13e3b2ecfb3ef4cbeeac669451bf"),
        "whitelist_membership": ("Array<~lib/string/String>#includes", 44, "c2fcbe1f72c5178a09100ce46a209a2a47e7c9d7780f7c7eafa5fed6f054ba2e"),
        "whitelist_getter": ("schema/Token#get:whitelistPools", 103, "74ffe9096e8964cffc2f1dc62cd89e1f126681936d0e71a245d64eb917afabd1"),
        "pool_id_getter": ("schema/Pool#get:id", 24, "c3bf64291589c98b778f00f5c611241724cf1a66b65077d067f06b4e7e37ad31"),
        "token_id_getter": ("schema/Token#get:id", 24, "929754fb22ba5daae26dfe0fb012b63cea986e258a470a3c75beed6202849731"),
        "string_array_value": ("Value.fromStringArray", 103, "b458f9ce24317d5c56af74ecc8eedc179bc0a9c2816953c2d8e87f24f31d3b43"),
        "static_profile": "mainnet-safe-six",
        "static_definitions": [
            ["0xe0b7927c4af23765cb51314a0e0521a9645f0e2a", "DGD", "DGD", 9],
            ["0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9", "AAVE", "Aave Token", 18],
            ["0xeb9951021698b42e4399f9cbb6267aa35f82d59d", "LIF", "Lif", 18],
            ["0xbdeb4b83251fb146687fa19d1c660f99411eefe3", "SVD", "savedroid", 18],
            ["0xbb9bc244d798123fde783fcc1c72d3bb8c189413", "TheDAO", "TheDAO", 16],
            ["0x38c6a68304cdefb9bec48bbfaaba5c5b47818bb2", "HPB", "HPBCoin", 18],
        ],
    },
}


TYPED_MAP_SET_CALL = (
    "~lib/@graphprotocol/graph-ts/common/collections/"
    "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set"
)
TYPED_MAP_GET_CALL = TYPED_MAP_SET_CALL.removesuffix("#set") + "#get"
STUB_NEW_CALL = "~lib/rt/stub/__new"
EVENT_PARAM_GET_CALL = (
    "~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/"
    "ethereum.EventParam>#__get"
)
VALUE_TO_ADDRESS_CALL = (
    "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value#toAddress"
)
VALUE_FROM_STRING_ARRAY_CALL = (
    "~lib/@graphprotocol/graph-ts/common/value/Value.fromStringArray"
)
STRING_EQ_BODY_SHA256 = (
    "f7967b738553ba98aba24f869e968d73e8013f99e83d02e106cad52306aa3c3f"
)
FIXED_RUNTIME_BODY_SHA256 = {
    "stub_alloc": "a03922d8f65cdc65e9d23c65bae22238c3783fed3294ec8847c2951f45a49c68",
    "ensure_capacity": {
        "modern-base": "c3f2f8562d0bd486d33a84bbf0ad08f72a291947d1bc7f65f9dc4c2b19df1c69",
        "modern-mainnet": "5686a840f52807e6c35015e015e0f9589342779719d970157ce4b42973be91e8",
    },
    "memory_fill": "a95fecf1bd14d1ab88b6c6374397793361e50f6f7c6a292e2fe0ac71dc667ad0",
    "memory_copy": "fd525c8864117cf67304d6896524aa816b1949797f64ee28f43b6448e82ae2f4",
    "memcpy": "0da0c6a704b3c3d86e0a9a7ab3d441f3d44556c811ab4d35acfc3604d2db9a90",
}

# This is an exact normalized instruction-slice closure over the inlined
# ethereum.Value BigInt-to-i32 conversion used by Pool.feeTier.  Structural
# checks below independently bind the event Value payload, sign extension,
# byte copy, byte-order reconstruction, and final BigInt.fromI32 call, so this
# digest is retained-artifact authority rather than a substitute for dataflow.
EXPECTED_FEE_TIER_SLICE_SHA256 = {
    "modern-base": "2a63a66ed9dc95965e56fa204c683233a00045532c5d8cef09675bce8c3d2882",
    "modern-mainnet": "b624329a49f47c04f6b8203072ff91a8a04d5de32c54a32ed4808ae694cebcf7",
}

EXPECTED_WHITELIST_MEMBERS = {
    "modern-base": [
        "0x4200000000000000000000000000000000000006",
        "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    ],
    "modern-mainnet": [
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        "0x6b175474e89094c44da98b954eedeac495271d0f",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "0xdac17f958d2ee523a2206206994597c13d831ec7",
        "0x0000000000085d4780b73119b644ae5ecd22b376",
        "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
        "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
        "0x39aa39c021dfbae8fac545936693ac917d5e7563",
        "0x86fadb80d8d2cff3c3680819e4da99c10232ba0f",
        "0x57ab1ec28d129707052df4df418d58a2d46d5f51",
        "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2",
        "0xc00e94cb662c3520282e6f5717214004a7f26888",
        "0x514910771af9ca656af840dff83e8264ecf986ca",
        "0xc011a73ee8576fb46f5e1c5751ca3b9fe0af2a6f",
        "0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e",
        "0x111111111117dc0aa78b770fa6a738034120c302",
        "0xdf5e0e81dff6faf3a7e52ba697820c5e32d806a8",
        "0x956f47f50a910163d8bf957cf5846d573e7f87ca",
        "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0",
        "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9",
        "0xfe2e637202056d30016725477c5da089ab0a043a",
    ],
}

# Direct instruction structure for the complete signed BigInt comparison used
# by fetchTokenDecimals.  This is intentionally not a digest: every operand,
# local definition, sign/length normalization loop, unsigned byte comparison,
# branch result, and successful return is compared structurally after helper
# body authority is checked.
DECIMALS_COMPARISON_STRUCTURE = tuple(
    """
local.get $l5
i32.load
if $I2
block $B3 (result i32)
local.get $l5
call $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.CallResult<~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value>>#get:value
local.set $l3
i32.const 255
call $~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32
local.set $l4
local.get $l3
i32.load offset=8
i32.const 0
i32.gt_s
local.tee $p0
if $I4
local.get $l3
local.get $l3
i32.load offset=8
i32.const 1
i32.sub
call $~lib/typedarray/Uint8Array#__get
i32.const 7
i32.shr_u
i32.const 1
i32.eq
local.set $p0
end
i32.const 1
i32.const 0
block $B5 (result i32)
local.get $l4
i32.load offset=8
i32.const 0
i32.gt_s
local.tee $l1
if $I6
local.get $l4
local.get $l4
i32.load offset=8
i32.const 1
i32.sub
call $~lib/typedarray/Uint8Array#__get
i32.const 7
i32.shr_u
i32.const 1
i32.eq
local.set $l1
end
local.get $l1
end
local.get $p0
select
br_if $B3
drop
i32.const -1
local.get $l1
i32.const 1
local.get $p0
select
i32.eqz
br_if $B3
drop
local.get $l3
i32.load offset=8
local.set $l2
loop $L7
local.get $l2
i32.const 0
i32.gt_s
if $I8 (result i32)
local.get $p0
if $I9 (result i32)
i32.const 1
else
local.get $l3
local.get $l2
i32.const 1
i32.sub
call $~lib/typedarray/Uint8Array#__get
end
if $I10 (result i32)
local.get $p0
if $I11 (result i32)
local.get $l3
local.get $l2
i32.const 1
i32.sub
call $~lib/typedarray/Uint8Array#__get
i32.const 255
i32.eq
else
i32.const 0
end
else
i32.const 1
end
else
i32.const 0
end
if $I12
local.get $l2
i32.const 1
i32.sub
local.set $l2
br $L7
end
end
local.get $l4
i32.load offset=8
local.set $l6
loop $L13
local.get $l6
i32.const 0
i32.gt_s
if $I14 (result i32)
local.get $l1
if $I15 (result i32)
i32.const 1
else
local.get $l4
local.get $l6
i32.const 1
i32.sub
call $~lib/typedarray/Uint8Array#__get
end
if $I16 (result i32)
local.get $l1
if $I17 (result i32)
local.get $l4
local.get $l6
i32.const 1
i32.sub
call $~lib/typedarray/Uint8Array#__get
i32.const 255
i32.eq
else
i32.const 0
end
else
i32.const 1
end
else
i32.const 0
end
if $I18
local.get $l6
i32.const 1
i32.sub
local.set $l6
br $L13
end
end
i32.const -1
i32.const 1
local.get $p0
select
local.get $l2
local.get $l6
i32.gt_s
br_if $B3
drop
i32.const 1
i32.const -1
local.get $p0
select
local.get $l2
local.get $l6
i32.lt_s
br_if $B3
drop
i32.const 1
local.set $p0
loop $L19
local.get $p0
local.get $l2
i32.le_s
if $I20
i32.const -1
local.get $l3
local.get $l2
local.get $p0
i32.sub
local.tee $l1
call $~lib/typedarray/Uint8Array#__get
local.get $l4
local.get $l1
call $~lib/typedarray/Uint8Array#__get
i32.lt_u
br_if $B3
drop
i32.const 1
local.get $l3
local.get $l2
local.get $p0
i32.sub
local.tee $l1
call $~lib/typedarray/Uint8Array#__get
local.get $l4
local.get $l1
call $~lib/typedarray/Uint8Array#__get
i32.gt_u
br_if $B3
drop
local.get $p0
i32.const 1
i32.add
local.set $p0
br $L19
end
end
i32.const 0
end
i32.const -1
i32.eq
if $I21
local.get $l5
call $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.CallResult<~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value>>#get:value
return
""".strip().splitlines()
)


TRUE_FLAGS = {
    "exact_factory_effects_contract_bytes_pinned",
    "exact_two_modern_factory_wasm_wat_and_handlers_pinned",
    "both_modern_factory_complete_static_handler_contracts_proven",
    "both_modern_factory_all_sixty_stored_field_contracts_proven",
    "both_modern_factory_fifty_nine_written_field_transitions_proven",
    "both_modern_factory_pool_tick_required_absence_proven",
    "both_modern_factory_early_return_partial_effects_proven",
    "both_modern_factory_total_supply_success_failure_dataflow_proven",
    "both_modern_factory_symbol_name_and_decimals_helpers_bound",
    "both_modern_factory_symbol_name_success_fallback_dataflows_proven",
    "both_modern_factory_decimals_threshold_and_static_fallback_dataflows_proven",
    "both_modern_factory_static_metadata_profiles_bound",
    "both_modern_factory_whitelist_update_direction_proven",
    "exactly_two_complete_static_handler_paths_closed",
    "cumulative_factory_paths_closed_is_14_of_18",
    "cumulative_factory_paths_residual_is_4_of_18",
    "modern_segment_field_projection_count_is_120",
    "global_v2_selected_and_residual_counts_unchanged_by_partial_profile_closure",
}


FALSE_FLAGS = {
    "all_six_factory_complete_static_handler_contracts_proven",
    "legacy_factory_complete_static_handler_contracts_proven",
    "factory_complete_entity_histories_proven",
    "all_stored_fields_exact",
    "all_manifest_handler_field_semantics_complete",
    "all_pairwise_complete_writer_semantic_diffs_present",
    "graph_handler_rollback_proven_by_retained_wat",
    "actual_historic_contract_call_outcomes_bound",
    "runtime_population_complete",
    "writer_runtime_consumes_this_contract",
    "combined_handler_order_implemented",
    "dynamic_datasource_stage_order_implemented",
    "post_fatal_execution_modeled",
    "graph_execution_trace_complete",
    "target_runtime_identity_bound",
    "boundary_state_continuity_complete",
    "checkpoint_authority",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "backfill_ready",
    "production_ready",
}


FACTORY_FIELDS = [
    "id", "poolCount", "txCount", "totalVolumeUSD", "totalVolumeETH",
    "totalFeesUSD", "totalFeesETH", "untrackedVolumeUSD",
    "totalValueLockedUSD", "totalValueLockedETH",
    "totalValueLockedUSDUntracked", "totalValueLockedETHUntracked", "owner",
]
BUNDLE_FIELDS = ["id", "ethPriceUSD"]
TOKEN_FIELDS = [
    "id", "symbol", "name", "decimals", "totalSupply", "volume", "volumeUSD",
    "untrackedVolumeUSD", "feesUSD", "txCount", "poolCount",
    "totalValueLocked", "totalValueLockedUSD", "totalValueLockedUSDUntracked",
    "derivedETH", "whitelistPools",
]
POOL_FIELDS = [
    "id", "createdAtTimestamp", "createdAtBlockNumber", "token0", "token1",
    "feeTier", "liquidity", "sqrtPrice", "feeGrowthGlobal0X128",
    "feeGrowthGlobal1X128", "token0Price", "token1Price", "tick",
    "observationIndex", "volumeToken0", "volumeToken1", "volumeUSD",
    "untrackedVolumeUSD", "feesUSD", "txCount", "collectedFeesToken0",
    "collectedFeesToken1", "collectedFeesUSD", "totalValueLockedToken0",
    "totalValueLockedToken1", "totalValueLockedETH", "totalValueLockedUSD",
    "totalValueLockedUSDUntracked", "liquidityProviderCount",
]


# Every handler-local TypedMap#set call.  Token.id is proved in Token#constructor;
# Pool.tick has no set site and is the one required-absence field.
EXPECTED_SET_SITES: dict[int, tuple[str, str]] = {
    172: ("Factory", "id"), 188: ("Factory", "poolCount"),
    204: ("Factory", "totalVolumeETH"), 220: ("Factory", "totalVolumeUSD"),
    236: ("Factory", "untrackedVolumeUSD"), 252: ("Factory", "totalFeesUSD"),
    268: ("Factory", "totalFeesETH"), 284: ("Factory", "totalValueLockedETH"),
    300: ("Factory", "totalValueLockedUSD"),
    316: ("Factory", "totalValueLockedUSDUntracked"),
    332: ("Factory", "totalValueLockedETHUntracked"), 348: ("Factory", "txCount"),
    361: ("Factory", "owner"), 379: ("Bundle", "id"),
    395: ("Bundle", "ethPriceUSD"), 499: ("Factory", "poolCount"),
    538: ("Pool", "id"), 633: ("Token[token0]", "symbol"),
    665: ("Token[token0]", "name"), 697: ("Token[token0]", "totalSupply"),
    742: ("Token[token0]", "decimals"), 758: ("Token[token0]", "derivedETH"),
    774: ("Token[token0]", "volume"), 790: ("Token[token0]", "volumeUSD"),
    806: ("Token[token0]", "feesUSD"),
    822: ("Token[token0]", "untrackedVolumeUSD"),
    838: ("Token[token0]", "totalValueLocked"),
    854: ("Token[token0]", "totalValueLockedUSD"),
    870: ("Token[token0]", "totalValueLockedUSDUntracked"),
    886: ("Token[token0]", "txCount"), 902: ("Token[token0]", "poolCount"),
    910: ("Token[token0]", "whitelistPools"),
    966: ("Token[token1]", "symbol"), 998: ("Token[token1]", "name"),
    1030: ("Token[token1]", "totalSupply"),
    1075: ("Token[token1]", "decimals"),
    1091: ("Token[token1]", "derivedETH"), 1107: ("Token[token1]", "volume"),
    1123: ("Token[token1]", "volumeUSD"),
    1139: ("Token[token1]", "untrackedVolumeUSD"),
    1155: ("Token[token1]", "feesUSD"),
    1171: ("Token[token1]", "totalValueLocked"),
    1187: ("Token[token1]", "totalValueLockedUSD"),
    1203: ("Token[token1]", "totalValueLockedUSDUntracked"),
    1219: ("Token[token1]", "txCount"), 1235: ("Token[token1]", "poolCount"),
    1243: ("Token[token1]", "whitelistPools"),
    1259: ("Token[token1]", "whitelistPools"),
    1275: ("Token[token0]", "whitelistPools"), 1293: ("Pool", "token0"),
    1310: ("Pool", "token1"), 1497: ("Pool", "feeTier"),
    1515: ("Pool", "createdAtTimestamp"),
    1533: ("Pool", "createdAtBlockNumber"),
    1549: ("Pool", "liquidityProviderCount"), 1565: ("Pool", "txCount"),
    1581: ("Pool", "liquidity"), 1597: ("Pool", "sqrtPrice"),
    1613: ("Pool", "feeGrowthGlobal0X128"),
    1629: ("Pool", "feeGrowthGlobal1X128"),
    1645: ("Pool", "token0Price"), 1661: ("Pool", "token1Price"),
    1677: ("Pool", "observationIndex"),
    1693: ("Pool", "totalValueLockedToken0"),
    1709: ("Pool", "totalValueLockedToken1"),
    1725: ("Pool", "totalValueLockedUSD"),
    1741: ("Pool", "totalValueLockedETH"),
    1757: ("Pool", "totalValueLockedUSDUntracked"),
    1773: ("Pool", "volumeToken0"), 1789: ("Pool", "volumeToken1"),
    1805: ("Pool", "volumeUSD"), 1821: ("Pool", "feesUSD"),
    1837: ("Pool", "untrackedVolumeUSD"),
    1853: ("Pool", "collectedFeesToken0"),
    1869: ("Pool", "collectedFeesToken1"),
    1885: ("Pool", "collectedFeesUSD"),
}


ZERO_BI_SITES = {
    188, 348, 886, 902, 1219, 1235, 1549, 1565, 1581, 1597, 1613, 1629,
    1677,
}
ZERO_BD_SITES = {
    204, 220, 236, 252, 268, 284, 300, 316, 332, 395,
    758, 774, 790, 806, 822, 838, 854, 870,
    1091, 1107, 1123, 1139, 1155, 1171, 1187, 1203,
    1645, 1661, 1693, 1709, 1725, 1741, 1757, 1773, 1789, 1805, 1821,
    1837, 1853, 1869, 1885,
}


def function_by_suffix(context: dict[str, Any], suffix: str) -> Any:
    if suffix == "~start":
        require("~start" in context["functions"], f"{context['cid']} module start missing")
        return context["functions"]["~start"]
    matches = [
        function
        for name, function in context["functions"].items()
        if name.replace("generated/schema/", "src/types/schema/").endswith(suffix)
    ]
    require(len(matches) == 1, f"{context['cid']} helper {suffix!r} count drift: {len(matches)}")
    return matches[0]


def runtime_ops() -> Any:
    """Bind contract-local parsing and failure semantics to shared WAT proofs."""

    return RUNTIME.WatRuntimeOps(
        require=require,
        normalized=normalized,
        call_name=call_name,
        function_by_suffix=function_by_suffix,
    )


MODERN_COLLECTION_SPEC = RUNTIME.ModernCollectionSpec(
    typed_map_set_call=TYPED_MAP_SET_CALL,
    typed_map_get_call=TYPED_MAP_GET_CALL,
    event_param_get_call=EVENT_PARAM_GET_CALL,
    stub_new_call=STUB_NEW_CALL,
    stub_alloc_body_sha256=FIXED_RUNTIME_BODY_SHA256["stub_alloc"],
    ensure_capacity_body_sha256=FIXED_RUNTIME_BODY_SHA256["ensure_capacity"],
    memory_fill_body_sha256=FIXED_RUNTIME_BODY_SHA256["memory_fill"],
    memory_copy_body_sha256=FIXED_RUNTIME_BODY_SHA256["memory_copy"],
    memcpy_body_sha256=FIXED_RUNTIME_BODY_SHA256["memcpy"],
    string_eq_body_sha256=STRING_EQ_BODY_SHA256,
)


def decoded_i64_string(line: str, memory: bytearray) -> str | None:
    match = re.fullmatch(r"\s*i64\.const (\d+)\s*", line)
    if not match:
        return None
    return WRITER.decode_assemblyscript_string(memory, int(match.group(1)))


MUTABLE_GLOBALS = (
    "$~started",
    "$~lib/rt/stub/offset",
    "$src/utils/constants/ZERO_BI",
    "$src/utils/constants/ONE_BI",
    "$src/utils/constants/ZERO_BD",
)


def prove_module_state_invariants(
    context: dict[str, Any], start_function: Any
) -> dict[str, Any]:
    """Bind initializer dispatch, zero initial state, and every critical global writer."""
    expected = {
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
    }
    spec = RUNTIME.ModuleStateSpec(
        initializer_export="_start",
        initializer_function=start_function.name,
        mutable_globals=MUTABLE_GLOBALS,
        expected_global_set_inventory=expected,
    )
    return RUNTIME.prove_module_state_invariants(
        context,
        start_function,
        spec,
        require=require,
        normalized=normalized,
        canonical_sha256=canonical_sha256,
    )


def is_direct_memory_write(raw_line: str) -> bool:
    """Recognize every retained-WAT opcode that can directly alter linear memory."""

    return RUNTIME.is_direct_memory_write(raw_line, normalized)


def prove_start_protected_memory_invariance(
    context: dict[str, Any], function: Any
) -> dict[str, Any]:
    """Prove retained start code cannot overwrite the captured whitelist data."""

    profile = context["profile"]["profile_id"]
    lines = [normalized(line) for line in function.lines]
    pointer_slot, length_slot = {
        "modern-base": (2788, 2796),
        "modern-mainnet": (4756, 4764),
    }[profile]
    array_pointer = pointer_slot - 4
    memory = context["memory"]
    backing_pointer = struct.unpack_from("<I", memory, pointer_slot)[0]
    length = struct.unpack_from("<I", memory, length_slot)[0]
    member_pointers = [
        struct.unpack_from("<I", memory, backing_pointer + index * 4)[0]
        for index in range(length)
    ]
    members = [
        WRITER.decode_assemblyscript_string(memory, pointer)
        for pointer in member_pointers
    ]
    require(
        members == EXPECTED_WHITELIST_MEMBERS[profile],
        f"{context['cid']} module-start protected whitelist members drift",
    )
    protected_regions = [
        {"label": "captured_array_object", "start": array_pointer, "end": array_pointer + 16},
        {
            "label": "captured_array_backing",
            "start": backing_pointer,
            "end": backing_pointer + length * 4,
        },
    ]
    for index, (pointer, member) in enumerate(zip(member_pointers, members, strict=True)):
        encoded_length = struct.unpack_from("<I", memory, pointer - 4)[0]
        require(
            encoded_length == len(member.encode("utf-16-le")),
            f"{context['cid']} whitelist member {index} encoded length drift",
        )
        protected_regions.append(
            {
                "label": f"captured_member_{index}",
                "start": pointer - 4,
                "end": pointer + encoded_length,
            }
        )
    allocator_floor_match = re.fullmatch(r"i32\.const (\d+)", lines[8])
    require(
        allocator_floor_match is not None
        and lines[9] == "global.set $~lib/rt/stub/offset",
        f"{context['cid']} module-start allocator floor drift",
    )
    allocator_floor = int(allocator_floor_match.group(1))
    require(
        max(region["end"] for region in protected_regions) < allocator_floor,
        f"{context['cid']} module-start allocator floor overlaps protected whitelist memory",
    )
    calls = [call_name(line) for line in function.lines if call_name(line) is not None]
    expected_calls = {
        "modern-base": [
            "~lib/rt/stub/__alloc",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigDecimal.fromString",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigDecimal.fromString",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/conversion/typeConversion.stringToH160",
            "~lib/rt/stub/__new",
            "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#constructor",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigDecimal.fromString",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigInt.pow",
            "~lib/rt/stub/__new",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/rt/stub/__alloc",
        ],
        "modern-mainnet": [
            "~lib/rt/stub/__alloc",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigDecimal.fromString",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigDecimal.fromString",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/conversion/typeConversion.stringToH160",
            "~lib/rt/stub/__new",
            "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#constructor",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigDecimal.fromString",
            "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
            "~lib/@graphprotocol/graph-ts/common/numbers/bigInt.pow",
            "~lib/rt/stub/__alloc",
        ],
    }[profile]
    require(
        calls == expected_calls
        and not any(line.startswith("call_indirect") for line in lines),
        f"{context['cid']} module-start protected-memory call inventory drift",
    )
    memory_write_sites = [
        (index, line)
        for index, line in enumerate(lines)
        if is_direct_memory_write(line)
    ]
    if profile == "modern-mainnet":
        require(
            memory_write_sites == [],
            f"{context['cid']} module-start acquired a direct protected-memory write: {memory_write_sites}",
        )
    else:
        require(
            memory_write_sites
            == [
                (51, "i32.store"),
                (54, "i32.store offset=4"),
                (57, "i32.store"),
                (61, "i32.store offset=4"),
            ]
            and lines[46:62]
            == [
                "i32.const 8", "i32.const 7", lines[48], "local.tee $l0",
                "i32.const 0", "i32.store", "local.get $l0", "i32.const 0",
                "i32.store offset=4", "local.get $l0", "local.get $l1", "i32.store",
                "local.get $l0", "i32.const 0", lines[60], "i32.store offset=4",
            ]
            and call_name(function.lines[48]) == STUB_NEW_CALL
            and (call_name(function.lines[60]) or "").endswith("BigInt.fromI32"),
            f"{context['cid']} module-start direct memory-write receiver/operand inventory drift",
        )
    return {
        "allocator_floor": allocator_floor,
        "protected_regions": protected_regions,
        "protected_regions_sha256": canonical_sha256(protected_regions),
        "direct_memory_write_sites": [index for index, _line in memory_write_sites],
        "exact_direct_call_inventory": calls,
        "module_start_direct_memory_writes_cannot_reach_protected_whitelist_memory": True,
        "imported_host_functions_assumed_not_to_write_arbitrary_linear_memory": True,
        "reachable_helper_memory_writes_bound_by_aggregate_body_authority_not_rederived": True,
    }


def prove_start_constants(context: dict[str, Any]) -> dict[str, Any]:
    expected = EXPECTED_HELPERS[context["profile"]["profile_id"]]["start"]
    function = function_by_suffix(context, expected[0])
    digest = hashlib.sha256(function.payload).hexdigest()
    require(
        len(function.lines) == expected[1] and digest == expected[2],
        f"{context['cid']} module-start constant semantic body drift",
    )
    lines = [normalized(line) for line in function.lines]
    require(
        lines[2:10]
        == [
            "global.get $~started",
            "if $I0",
            "return",
            "end",
            "i32.const 1",
            "global.set $~started",
            lines[8],
            "global.set $~lib/rt/stub/offset",
        ],
        f"{context['cid']} exported initializer idempotence/floor prelude drift",
    )
    required = [
        ["i32.const 0", "call $~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32", "global.set $src/utils/constants/ZERO_BI"],
        ["i32.const 1", "call $~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32", "global.set $src/utils/constants/ONE_BI"],
    ]
    for sequence in required:
        require(
            any(lines[index : index + len(sequence)] == sequence for index in range(len(lines))),
            f"{context['cid']} module-start BigInt constant flow drift",
        )
    zero_bd = next(
        (
            index
            for index, line in enumerate(function.lines[:-2])
            if V2.decoded_wat_constant(line, context["memory"]) == "0"
            and (call_name(function.lines[index + 1]) or "").endswith("bigDecimal.fromString")
            and normalized(function.lines[index + 2]) == "global.set $src/utils/constants/ZERO_BD"
        ),
        None,
    )
    require(zero_bd is not None, f"{context['cid']} module-start ZERO_BD flow drift")
    require(
        WRITER.decode_assemblyscript_string(context["memory"], 1600)
        == "0x0000000000000000000000000000000000000000",
        f"{context['cid']} ADDRESS_ZERO literal drift",
    )
    module_state = prove_module_state_invariants(context, function)
    protected_memory = prove_start_protected_memory_invariance(context, function)
    return {
        "function": function.name,
        "body_sha256": digest,
        "zero_bi": "BigInt.fromI32(0)",
        "one_bi": "BigInt.fromI32(1)",
        "zero_bd": "BigDecimal.fromString(0)",
        "address_zero": "0x0000000000000000000000000000000000000000",
        "module_state_invariants": module_state,
        "protected_whitelist_memory": protected_memory,
        "constant_flows_machine_proven": True,
    }


def prove_static_definitions(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED_HELPERS[profile]
    suffix, line_count, body_sha256 = expected["static_definition"]
    function = function_by_suffix(context, suffix)
    digest = hashlib.sha256(function.payload).hexdigest()
    require(
        len(function.lines) == line_count and digest == body_sha256,
        f"{context['cid']} static-definition semantic body drift",
    )
    definitions = expected["static_definitions"]
    lines = [normalized(line) for line in function.lines]
    constructor_sites = [
        index
        for index, line in enumerate(function.lines)
        if (call_name(line) or "").endswith("StaticTokenDefinition#constructor")
    ]
    require(
        len(constructor_sites) == len(definitions),
        f"{context['cid']} static-definition count drift",
    )
    if not definitions:
        require(
            lines[2:6] == ["i32.const 0", "i32.const 49", "i32.const 9184", lines[5]]
            and (call_name(function.lines[5]) or "").endswith("~lib/rt/__newArray")
            and lines[6:19]
            == [
                "local.set $l2", "local.get $p0", lines[8], "local.set $l3",
                "loop $L0", "local.get $l2", "i32.load offset=12", "local.get $l1",
                "i32.gt_s", "if $I1", "local.get $l2", "local.get $l1", lines[18],
            ]
            and (call_name(function.lines[8]) or "").endswith("typeConversion.bytesToHex")
            and call_name(function.lines[18]) == EVENT_PARAM_GET_CALL
            and lines[19:35]
            == [
                "local.tee $p0", "i32.load", lines[21], "local.get $l3", lines[23],
                "if $I2", "local.get $p0", "return", "end", "local.get $l1",
                "i32.const 1", "i32.add", "local.set $l1", "br $L0", "end", "end",
            ]
            and (call_name(function.lines[21]) or "").endswith("typeConversion.bytesToHex")
            and call_name(function.lines[23]) == "~lib/string/String.__eq"
            and lines[35].removesuffix(")") == "i32.const 0"
            and local_write_sites(lines, 2, 35, "$l1") == [31],
            f"{context['cid']} empty static-definition array/input-loop/null-return drift",
        )
    for site, (address, symbol, name, decimals) in zip(
        constructor_sites, definitions, strict=True
    ):
        require(
            lines[site + 1] == "local.tee $l3"
            and V2.decoded_wat_constant(function.lines[site + 2], context["memory"])
            == address
            and (call_name(function.lines[site + 3]) or "").endswith("stringToH160")
            and lines[site + 4 : site + 6] == ["i32.store", "local.get $l3"]
            and V2.decoded_wat_constant(function.lines[site + 6], context["memory"])
            == symbol
            and lines[site + 7 : site + 9]
            == ["i32.store offset=4", "local.get $l3"]
            and V2.decoded_wat_constant(function.lines[site + 9], context["memory"])
            == name
            and lines[site + 10 : site + 12]
            == ["i32.store offset=8", "local.get $l3"]
            and lines[site + 12] == f"i32.const {decimals}"
            and (call_name(function.lines[site + 13]) or "").endswith("BigInt.fromI32")
            and lines[site + 14] == "i32.store offset=12",
            f"{context['cid']} static-definition semantic tuple drift for {address}",
        )
    if definitions:
        constructor = function_by_suffix(
            context, "StaticTokenDefinition#constructor"
        )
        constructor_lines = [normalized(line) for line in constructor.lines]
        require(
            len(constructor_lines) == 18
            and constructor_lines[2:18]
            == [
                "i32.const 16",
                "i32.const 48",
                constructor_lines[4],
                "local.tee $l0",
                "i32.const 0",
                "i32.store",
                "local.get $l0",
                "i32.const 0",
                "i32.store offset=4",
                "local.get $l0",
                "i32.const 0",
                "i32.store offset=8",
                "local.get $l0",
                "i32.const 0",
                "i32.store offset=12",
                "local.get $l0)",
            ]
            and call_name(constructor.lines[4]) == STUB_NEW_CALL,
            f"{context['cid']} StaticTokenDefinition constructor allocation/zeroing/return drift",
        )
        require(
            lines[2:6] == ["i32.const 6", "i32.const 49", "i32.const 0", lines[5]]
            and (call_name(function.lines[5]) or "").endswith("~lib/rt/__newArray")
            and lines[6:9] == ["local.tee $l1", "i32.load offset=4", "drop"],
            f"{context['cid']} mainnet static-definition six-entry array allocation drift",
        )
        for index, site in enumerate(constructor_sites):
            slot_site = site + 15
            store = "i32.store" if index == 0 else f"i32.store offset={index * 4}"
            require(
                lines[slot_site : slot_site + 4]
                == ["local.get $l1", "i32.load offset=4", "local.get $l3", store],
                f"{context['cid']} static-definition tuple slot {index} placement drift",
            )
        require(
            lines[123:126] == ["local.get $p0", lines[124], "local.set $p0"]
            and (call_name(function.lines[124]) or "").endswith("typeConversion.bytesToHex")
            and lines[126:140]
            == [
                "loop $L0", "local.get $l1", "i32.load offset=12", "local.get $l2",
                "i32.gt_s", "if $I1", "local.get $l1", "local.get $l2", lines[134],
                "local.tee $l3", "i32.load", lines[137], "local.get $p0", lines[139],
            ]
            and call_name(function.lines[134]) == EVENT_PARAM_GET_CALL
            and (call_name(function.lines[137]) or "").endswith("typeConversion.bytesToHex")
            and call_name(function.lines[139]) == "~lib/string/String.__eq"
            and lines[140:152]
            == [
                "if $I2", "local.get $l3", "return", "end", "local.get $l2",
                "i32.const 1", "i32.add", "local.set $l2", "br $L0", "end", "end",
                "i32.const 0)",
            ]
            and local_write_sites(lines, 6, 123, "$l1") == [6]
            and local_write_sites(lines, 2, 152, "$l2") == [147],
            f"{context['cid']} static-definition input-address/loop/compare/return/null drift",
        )
    return {
        "profile": expected["static_profile"],
        "function": function.name,
        "body_sha256": digest,
        "safe_literal_array": True,
        "definition_count": len(definitions),
        "definitions": definitions,
        "fresh_zeroed_constructor_structurally_proven_when_reachable": True,
        "exact_profile_body_and_literals_bound": True,
        "array_length_tuple_slots_input_compare_loop_and_null_return_structurally_proven": True,
    }


def prove_helper_body(
    context: dict[str, Any], key: str, outcome_model: dict[str, Any]
) -> dict[str, Any]:
    suffix, line_count, body_sha256 = EXPECTED_HELPERS[context["profile"]["profile_id"]][key]
    function = function_by_suffix(context, suffix)
    digest = hashlib.sha256(function.payload).hexdigest()
    require(
        len(function.lines) == line_count and digest == body_sha256,
        f"{context['cid']} {key.replace('_', '-')} helper semantic body drift",
    )
    return {
        "function": function.name,
        "body_sha256": digest,
        "line_count": len(function.lines),
        "outcome_model": outcome_model,
        "exact_helper_body_bound": True,
    }


def call_ends(function: Any, index: int, suffix: str) -> bool:
    return (call_name(function.lines[index]) or "").endswith(suffix)


def prove_value_payload_decoder(
    context: dict[str, Any], suffix: str, accepted_kinds: tuple[int, ...]
) -> dict[str, Any]:
    """Prove a Value decoder's exact kind gate and same-receiver payload result."""

    function = function_by_suffix(context, suffix)
    lines = [normalized(line) for line in function.lines]
    if len(accepted_kinds) == 1:
        kind = accepted_kinds[0]
        gate = (
            ["local.get $p0", "i32.load", "if $I0"]
            if kind == 0
            else [
                "local.get $p0",
                "i32.load",
                f"i32.const {kind}",
                "i32.ne",
                "if $I0",
            ]
        )
        gate_start = 1
        abort_site = 8 if kind == 0 else 10
    else:
        first, second = accepted_kinds
        gate = [
            "local.get $p0",
            "i32.load",
            f"i32.const {first}",
            "i32.eq",
            "if $I0 (result i32)",
            "i32.const 1",
            "else",
            "local.get $p0",
            "i32.load",
            f"i32.const {second}",
            "i32.eq",
            "end",
            "i32.eqz",
            "if $I1",
        ]
        gate_start = 1
        abort_site = 19
    expected_line_count = 14 if accepted_kinds == (0,) else 16 if len(accepted_kinds) == 1 else 25
    require(
        len(lines) == expected_line_count
        and lines[gate_start : gate_start + len(gate)] == gate
        and (call_name(function.lines[abort_site]) or "").endswith("builtins/abort")
        and lines[abort_site + 1] == "unreachable"
        and lines[-4:]
        == ["end", "local.get $p0", "i64.load offset=8", "i32.wrap_i64)"],
        f"{context['cid']} {suffix} exact kind gate/same Value payload return drift",
    )
    require(
        not any(
            call_name(line) in {TYPED_MAP_SET_CALL, WRITER.STORE_SET_CALL}
            or normalized(line).startswith("call_indirect")
            for line in function.lines
        )
        and not local_write_sites(lines, 1, len(lines), "$p0"),
        f"{context['cid']} {suffix} payload return/side-effect drift",
    )
    return {
        "function": function.name,
        "accepted_value_kinds": list(accepted_kinds),
        "same_receiver_payload_offset_8_returned": True,
        "kind_gate_and_payload_structurally_proven": True,
    }


def prove_allocator_identity(context: dict[str, Any]) -> dict[str, Any]:
    """Return allocator evidence from the complete public collection capsule."""

    capsule = RUNTIME.prove_modern_collection_capsule(
        context, runtime_ops(), MODERN_COLLECTION_SPEC
    )
    return capsule["typed_map_collection_runtime"]["allocator"]


def prove_typed_map_collection_runtime(context: dict[str, Any]) -> dict[str, Any]:
    """Return TypedMap evidence from the complete public collection capsule."""

    capsule = RUNTIME.prove_modern_collection_capsule(
        context, runtime_ops(), MODERN_COLLECTION_SPEC
    )
    return capsule["typed_map_collection_runtime"]


def prove_shared_runtime_primitives(context: dict[str, Any]) -> dict[str, Any]:
    """Close the retained library primitives used by the semantic wrappers."""

    collection_capsule = RUNTIME.prove_modern_collection_capsule(
        context, runtime_ops(), MODERN_COLLECTION_SPEC
    )
    collection_runtime = collection_capsule["typed_map_collection_runtime"]
    indexed_collection = collection_capsule["indexed_collection"]
    smart_contract = function_by_suffix(context, "ethereum.SmartContract#constructor")
    lines = [normalized(line) for line in smart_contract.lines]
    require(
        len(lines) == 22
        and lines[1:22]
        == [
            "local.get $p0", "i32.eqz", "if $I0", "i32.const 8", "i32.const 11",
            lines[6], "local.set $p0", "end", "local.get $p0", "i32.const 0",
            "i32.store", "local.get $p0", "i32.const 0", "i32.store offset=4",
            "local.get $p0", "local.get $p1", "i32.store", "local.get $p0",
            "local.get $p2", "i32.store offset=4", "local.get $p0)",
        ]
        and call_name(smart_contract.lines[6]) == STUB_NEW_CALL,
        f"{context['cid']} SmartContract constructor name/address/receiver drift",
    )

    new_array = function_by_suffix(context, "~lib/rt/__newArray")
    lines = [normalized(line) for line in new_array.lines]
    require(
        len(lines) == 32
        and lines[2:32]
        == [
            "local.get $p0", "i32.const 2", "i32.shl", "local.tee $l4",
            "i32.const 0", lines[7], "local.set $l3", "local.get $p2", "if $I0",
            "local.get $l3", "local.get $p2", "local.get $l4", lines[14], "end",
            "i32.const 16", "local.get $p1", lines[18], "local.tee $p1",
            "local.get $l3", "i32.store", "local.get $p1", "local.get $l3",
            "i32.store offset=4", "local.get $p1", "local.get $l4",
            "i32.store offset=8", "local.get $p1", "local.get $p0",
            "i32.store offset=12", "local.get $p1)",
        ]
        and call_name(new_array.lines[7]) == STUB_NEW_CALL
        and (call_name(new_array.lines[14]) or "").endswith("memory.copy")
        and call_name(new_array.lines[18]) == STUB_NEW_CALL,
        f"{context['cid']} __newArray length/backing/copy/return drift",
    )

    byte_array = function_by_suffix(context, "common/collections/ByteArray#constructor")
    byte_lines = [normalized(line) for line in byte_array.lines]
    require(
        len(byte_lines) == 62
        and byte_lines[2:35]
        == [
            "local.get $p0", "i32.eqz", "if $I0", "i32.const 12", "i32.const 6",
            byte_lines[7], "local.set $p0", "end", "local.get $p0", "i32.eqz",
            "if $I1", "i32.const 12", "i32.const 5", byte_lines[15],
            "local.set $p0", "end", "local.get $p0", "i32.eqz", "if $I2",
            "i32.const 12", "i32.const 2", byte_lines[23], "local.set $p0", "end",
            "local.get $p0", "i32.const 0", "i32.store", "local.get $p0",
            "i32.const 0", "i32.store offset=4", "local.get $p0", "i32.const 0",
            "i32.store offset=8",
        ]
        and all(call_name(byte_array.lines[index]) == STUB_NEW_CALL for index in (7, 15, 23))
        and byte_lines[35:62]
        == [
            "local.get $p1", "i32.const 1073741820", "i32.gt_u", "if $I3",
            byte_lines[39], byte_lines[40], "i32.const 19", "i32.const 57",
            byte_lines[43], "unreachable", "end", "local.get $p1", "i32.const 0",
            byte_lines[48], "local.tee $l2", "local.get $p1", byte_lines[51],
            "local.get $p0", "local.get $l2", "i32.store", "local.get $p0",
            "local.get $l2", "i32.store offset=4", "local.get $p0",
            "local.get $p1", "i32.store offset=8", "local.get $p0)",
        ]
        and (call_name(byte_array.lines[43]) or "").endswith("builtins/abort")
        and call_name(byte_array.lines[48]) == STUB_NEW_CALL
        and (call_name(byte_array.lines[51]) or "").endswith("memory.fill"),
        f"{context['cid']} ByteArray constructor length/backing/return drift",
    )

    uint8_set = function_by_suffix(context, "~lib/typedarray/Uint8Array#__set")
    uint8_lines = [normalized(line) for line in uint8_set.lines]
    require(
        len(uint8_lines) == 19
        and uint8_lines[1:6]
        == ["local.get $p0", "i32.load offset=8", "local.get $p1", "i32.le_u", "if $I0"]
        and (call_name(uint8_set.lines[10]) or "").endswith("builtins/abort")
        and uint8_lines[11:19]
        == [
            "unreachable", "end", "local.get $p1", "local.get $p0",
            "i32.load offset=4", "i32.add", "local.get $p2", "i32.store8)",
        ],
        f"{context['cid']} Uint8Array#__set receiver/index/value drift",
    )

    uint8_get = function_by_suffix(context, "~lib/typedarray/Uint8Array#__get")
    uint8_get_lines = [normalized(line) for line in uint8_get.lines]
    require(
        len(uint8_get_lines) == 18
        and uint8_get_lines[1:6]
        == ["local.get $p0", "i32.load offset=8", "local.get $p1", "i32.le_u", "if $I0"]
        and (call_name(uint8_get.lines[10]) or "").endswith("builtins/abort")
        and uint8_get_lines[11:18]
        == [
            "unreachable", "end", "local.get $p1", "local.get $p0",
            "i32.load offset=4", "i32.add", "i32.load8_u)",
        ],
        f"{context['cid']} Uint8Array#__get receiver/index/byte result drift",
    )

    bigint = function_by_suffix(context, "BigInt.fromI32")
    bigint_lines = [normalized(line) for line in bigint.lines]
    require(
        len(bigint_lines) == 34
        and bigint_lines[2:34]
        == [
            "i32.const 0", "i32.const 4", bigint_lines[4], "local.tee $l1",
            "i32.const 0", "local.get $p0", "i32.const 255", "i32.and",
            bigint_lines[10], "local.get $l1", "i32.const 1", "local.get $p0",
            "i32.const 8", "i32.shr_s", "i32.const 255", "i32.and",
            bigint_lines[18], "local.get $l1", "i32.const 2", "local.get $p0",
            "i32.const 16", "i32.shr_s", "i32.const 255", "i32.and",
            bigint_lines[26], "local.get $l1", "i32.const 3", "local.get $p0",
            "i32.const 24", "i32.shr_s", bigint_lines[32], "local.get $l1)",
        ]
        and (call_name(bigint.lines[4]) or "").endswith("ByteArray#constructor")
        and all(
            (call_name(bigint.lines[index]) or "").endswith("Uint8Array#__set")
            for index in (10, 18, 26, 32)
        ),
        f"{context['cid']} BigInt.fromI32 exact four-byte signed encoding drift",
    )

    try_call = function_by_suffix(context, "ethereum.SmartContract#tryCall")
    call_lines = [normalized(line) for line in try_call.lines]
    require(
        len(call_lines) == 80
        and call_lines[2:8]
        == [
            "local.get $p0", "i32.load", "local.set $l4", "local.get $p0",
            "i32.load offset=4", "local.set $l5",
        ]
        and call_lines[8:26]
        == [
            "i32.const 20", "i32.const 45", call_lines[10], "local.tee $p0",
            "i32.const 0", "i32.store", "local.get $p0", "i32.const 0",
            "i32.store offset=4", "local.get $p0", "i32.const 0",
            "i32.store offset=8", "local.get $p0", "i32.const 0",
            "i32.store offset=12", "local.get $p0", "i32.const 0",
            "i32.store offset=16",
        ]
        and call_name(try_call.lines[10]) == STUB_NEW_CALL
        and call_lines[26:43]
        == [
            "local.get $p0", "local.get $l4", "i32.store", "local.get $p0",
            "local.get $l5", "i32.store offset=4", "local.get $p0", "local.get $p1",
            "i32.store offset=8", "local.get $p0", "local.get $p2",
            "i32.store offset=12", "local.get $p0", "local.get $p3",
            "i32.store offset=16", "local.get $p0", call_lines[42],
        ]
        and (call_name(try_call.lines[42]) or "").endswith("ethereum.call")
        and call_lines[43:58]
        == [
            "local.tee $p0", "i32.eqz", "if $I0", "i32.const 4", "i32.const 43",
            call_lines[48], "local.tee $p0", "i32.const 0", "i32.store",
            "local.get $p0", "i32.const 0", "i32.store", "local.get $p0", "return", "end",
        ]
        and call_name(try_call.lines[48]) == STUB_NEW_CALL
        and call_lines[58:80]
        == [
            "i32.const 4", "i32.const 43", call_lines[60], "local.tee $p1",
            "i32.const 0", "i32.store", "local.get $p1", "i32.const 0", "i32.store",
            "i32.const 4", "i32.const 44", call_lines[69], "local.tee $p2",
            "i32.const 0", "i32.store", "local.get $p2", "local.get $p0", "i32.store",
            "local.get $p1", "local.get $p2", "i32.store", "local.get $p1)",
        ]
        and call_name(try_call.lines[60]) == STUB_NEW_CALL
        and call_name(try_call.lines[69]) == STUB_NEW_CALL,
        f"{context['cid']} SmartContract#tryCall receiver/selectors/args/host-result drift",
    )

    call_result_get = function_by_suffix(context, "CallResult<~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value>>#get:value")
    result_lines = [normalized(line) for line in call_result_get.lines]
    require(
        len(result_lines) == 17
        and result_lines[1:5] == ["local.get $p0", "i32.load", "i32.eqz", "if $I0"]
        and (call_name(call_result_get.lines[7]) or "").endswith("String#concat")
        and (call_name(call_result_get.lines[11]) or "").endswith("builtins/abort")
        and result_lines[12:17]
        == ["unreachable", "end", "local.get $p0", "i32.load", "i32.load)"],
        f"{context['cid']} CallResult#get:value success gate/payload drift",
    )

    result_wrappers: dict[str, dict[str, Any]] = {}
    for label, suffix, outer_type, inner_type in (
        ("string", "CallResult.fromValue<~lib/string/String>", 40, 41),
        ("bytes", "CallResult.fromValue<~lib/@graphprotocol/graph-ts/common/collections/Bytes>", 46, 47),
        ("big_int", "CallResult.fromValue<~lib/@graphprotocol/graph-ts/common/numbers/BigInt>", 51, 52),
    ):
        wrapper = function_by_suffix(context, suffix)
        wrapper_lines = [normalized(line) for line in wrapper.lines]
        require(
            len(wrapper_lines) == 24
            and wrapper_lines[2:24]
            == [
                "i32.const 4", f"i32.const {outer_type}", wrapper_lines[4], "local.tee $l1",
                "i32.const 0", "i32.store", "local.get $l1", "i32.const 0",
                "i32.store", "i32.const 4", f"i32.const {inner_type}", wrapper_lines[13],
                "local.tee $l2", "i32.const 0", "i32.store", "local.get $l2",
                "local.get $p0", "i32.store", "local.get $l1", "local.get $l2",
                "i32.store", "local.get $l1)",
            ]
            and call_name(wrapper.lines[4]) == STUB_NEW_CALL
            and call_name(wrapper.lines[13]) == STUB_NEW_CALL,
            f"{context['cid']} {suffix} same input payload wrapper drift",
        )
        result_wrappers[label] = {
            "function": wrapper.name,
            "same_input_payload_wrapped_and_returned": True,
        }

    decoders = {
        "entity_string": prove_value_payload_decoder(
            context, "common/value/Value#toString", (0,)
        ),
        "entity_array": prove_value_payload_decoder(
            context, "common/value/Value#toArray", (4,)
        ),
        "ethereum_string": prove_value_payload_decoder(
            context, "chain/ethereum/ethereum.Value#toString", (6,)
        ),
        "ethereum_bytes": prove_value_payload_decoder(
            context, "chain/ethereum/ethereum.Value#toBytes", (1, 2)
        ),
        "ethereum_big_int": prove_value_payload_decoder(
            context, "chain/ethereum/ethereum.Value#toBigInt", (3, 4)
        ),
    }
    return {
        "typed_map_collection_runtime": collection_runtime,
        "smart_contract_constructor": {
            "same_name_and_address_stored_on_same_receiver": True,
            "same_receiver_returned": True,
        },
        "new_array": {
            "same_length_controls_backing_size_and_length_slot": True,
            "same_initialized_backing_and_receiver_returned": True,
        },
        "big_int_from_i32": {
            "same_i32_encoded_as_four_little_endian_bytes": True,
            "byte_array_constructor_and_uint8_get_set_structurally_proven": True,
        },
        "type_erased_array_get_set": indexed_collection[
            "type_erased_array_get_set"
        ],
        "typed_map_get": indexed_collection["typed_map_get"],
        "smart_contract_try_call": {
            "same_contract_name_address_selectors_and_arguments_enter_host_call": True,
            "host_result_success_failure_wrapping_structurally_proven": True,
        },
        "call_result": {
            "same_success_payload_getter_structurally_proven": True,
            "from_value_wrappers": result_wrappers,
        },
        "string_equality": collection_capsule["string_equality"],
        "value_payload_decoders": decoders,
        "shared_runtime_semantics_structurally_closed": True,
    }


def prove_token_smart_contract_source(
    context: dict[str, Any], key: str
) -> dict[str, Any]:
    suffix = {
        "symbol": "/fetchTokenSymbol",
        "name": "/fetchTokenName",
        "total_supply": "/fetchTokenTotalSupply",
        "decimals": "/fetchTokenDecimals",
    }[key]
    field = "totalSupply" if key == "total_supply" else key
    function = function_by_suffix(context, suffix)
    lines = [normalized(line) for line in function.lines]
    memory = context["memory"]
    constructor = (
        "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#constructor"
    )
    try_call = (
        "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#tryCall"
    )
    if key in {"symbol", "name"}:
        bytes_contract = "ERC20SymbolBytes" if key == "symbol" else "ERC20NameBytes"
        type_id = 39 if key == "symbol" else 50
        require(
            lines[2:16]
            == [
                "i32.const 8", "i32.const 38", lines[4], lines[5],
                "local.get $p0", lines[7], "local.set $l1", "i32.const 8",
                f"i32.const {type_id}", lines[11], lines[12], "local.get $p0",
                lines[14], "local.set $l2",
            ]
            and call_name(function.lines[4]) == STUB_NEW_CALL
            and V2.decoded_wat_constant(function.lines[5], memory) == "ERC20"
            and call_name(function.lines[7]) == constructor
            and call_name(function.lines[11]) == STUB_NEW_CALL
            and V2.decoded_wat_constant(function.lines[12], memory) == bytes_contract
            and call_name(function.lines[14]) == constructor
            and not local_write_sites(lines, 2, 16, "$p0"),
            f"{context['cid']} {field} exact input-address SmartContract construction drift",
        )
        require(
            lines[17] == "local.get $l1"
            and V2.decoded_wat_constant(function.lines[18], memory) == field
            and V2.decoded_wat_constant(function.lines[19], memory)
            == f"{field}():(string)"
            and lines[20:23] == ["i32.const 0", "i32.const 42", lines[22]]
            and call_ends(function, 23, "rt/__newArray")
            and call_name(function.lines[24]) == try_call
            and lines[55] == "local.get $l2"
            and V2.decoded_wat_constant(function.lines[56], memory) == field
            and V2.decoded_wat_constant(function.lines[57], memory)
            == f"{field}():(bytes32)"
            and lines[58:61] == ["i32.const 0", "i32.const 42", lines[60]]
            and call_ends(function, 61, "rt/__newArray")
            and call_name(function.lines[62]) == try_call,
            f"{context['cid']} {field} exact constructed receivers/selectors/argument arrays drift",
        )
        receivers = ["$l1", "$l2"]
        selectors = [f"{field}():(string)", f"{field}():(bytes32)"]
    else:
        constructor_input_site = 6 if key == "total_supply" else 7
        require(
            lines[2 if key == "total_supply" else 3 : constructor_input_site + 2]
            == (
                [
                    "i32.const 8", "i32.const 38", lines[4], lines[5],
                    "local.get $p0", lines[7],
                ]
                if key == "total_supply"
                else [
                    "i32.const 8", "i32.const 38", lines[5], lines[6],
                    "local.get $p0", lines[8],
                ]
            )
            and call_name(function.lines[constructor_input_site - 2]) == STUB_NEW_CALL
            and V2.decoded_wat_constant(
                function.lines[constructor_input_site - 1], memory
            )
            == "ERC20"
            and call_name(function.lines[constructor_input_site + 1]) == constructor,
            f"{context['cid']} {field} exact input-address SmartContract construction drift",
        )
        receiver_site = 13 if key == "total_supply" else 8
        selector_site = 14 if key == "total_supply" else 9
        signature_site = selector_site + 1
        args_start = selector_site + 2
        array_call_site = selector_site + 5
        try_call_site = selector_site + 6
        if key == "total_supply":
            require(
                lines[8] == "local.set $p0" and lines[receiver_site] == "local.get $p0",
                f"{context['cid']} totalSupply constructed receiver local drift",
            )
        expected_signature = (
            f"{field}():(uint256)" if key == "total_supply" else f"{field}():(uint32)"
        )
        require(
            V2.decoded_wat_constant(function.lines[selector_site], memory) == field
            and V2.decoded_wat_constant(function.lines[signature_site], memory)
            == expected_signature,
            f"{context['cid']} {field} selector/signature drift",
        )
        require(
            lines[args_start : args_start + 3]
            == ["i32.const 0", "i32.const 42", lines[args_start + 2]]
            and call_ends(function, array_call_site, "rt/__newArray")
            and call_name(function.lines[try_call_site]) == try_call,
            f"{context['cid']} {field} exact tryCall selector/empty arguments drift",
        )
        if key == "decimals":
            require(
                lines[receiver_site] == lines[8]
                and call_name(function.lines[receiver_site]) == constructor,
                f"{context['cid']} decimals constructor result is not the tryCall receiver",
            )
            receivers = ["SmartContract#constructor stack result"]
        else:
            receivers = ["$p0"]
        selectors = [expected_signature]
    return {
        "helper": field,
        "input_address_local": "$p0",
        "try_call_receivers": receivers,
        "selectors": selectors,
        "argument_arrays": "exact empty arrays",
        "input_address_to_contract_to_tryCall_structurally_proven": True,
    }


def prove_string_metadata_helper(
    context: dict[str, Any], key: str, static_field_offset: int
) -> dict[str, Any]:
    field = "symbol" if key == "symbol" else "name"
    proof = prove_helper_body(context, key, {})
    contract_source = prove_token_smart_contract_source(context, key)
    function = function_by_suffix(context, f"/fetchToken{field.title()}")
    lines = [normalized(line) for line in function.lines]
    memory = context["memory"]
    require(
        lines[16].startswith("block $")
        and lines[17] == "local.get $l1"
        and V2.decoded_wat_constant(function.lines[18], memory) == field
        and V2.decoded_wat_constant(function.lines[19], memory)
        == f"{field}():(string)"
        and lines[20] == "i32.const 0"
        and call_ends(function, 23, "~lib/rt/__newArray")
        and call_ends(function, 24, "ethereum.SmartContract#tryCall")
        and lines[25:29]
        == ["local.tee $l1", "i32.load", "i32.eqz", "if $I1"],
        f"{context['cid']} {field} helper primary try-call flow drift",
    )
    require(
        lines[38:41] == ["local.get $l1", "br $B0", "end"]
        and lines[41] == "local.get $l1"
        and call_ends(function, 42, "#get:value")
        and lines[43] == "i32.const 0"
        and call_ends(function, 44, "ethereum.EventParam>#__get")
        and call_ends(function, 45, "ethereum.Value#toString")
        and call_ends(function, 46, "CallResult.fromValue<~lib/string/String>")
        and lines[47:54]
        == [
            "end", "local.tee $l1", "i32.load", "if $I2 (result i32)",
            "local.get $l1", lines[52], "else",
        ]
        and call_ends(function, 52, "#get:value"),
        f"{context['cid']} {field} helper primary success/fallback flow drift",
    )
    require(
        lines[54].startswith("block $")
        and lines[55] == "local.get $l2"
        and V2.decoded_wat_constant(function.lines[56], memory) == field
        and V2.decoded_wat_constant(function.lines[57], memory)
        == f"{field}():(bytes32)"
        and lines[58] == "i32.const 0"
        and call_ends(function, 61, "~lib/rt/__newArray")
        and call_ends(function, 62, "ethereum.SmartContract#tryCall")
        and lines[63:67]
        == ["local.tee $l1", "i32.load", "i32.eqz", "if $I4"],
        f"{context['cid']} {field} helper bytes try-call flow drift",
    )
    require(
        lines[76:79] == ["local.get $l1", "br $B3", "end"]
        and lines[79] == "local.get $l1"
        and call_ends(function, 80, "#get:value")
        and lines[81] == "i32.const 0"
        and call_ends(function, 82, "ethereum.EventParam>#__get")
        and call_ends(function, 83, "ethereum.Value#toBytes")
        and "CallResult.fromValue" in (call_name(function.lines[84]) or "")
        and lines[85:89]
        == ["end", "local.tee $l1", "i32.load", "if $I5 (result i32)"],
        f"{context['cid']} {field} helper bytes success/fallback flow drift",
    )
    require(
        lines[89] == "local.get $l1"
        and call_ends(function, 90, "#get:value")
        and call_ends(function, 91, "bytesToHex")
        and V2.decoded_wat_constant(function.lines[92], memory)
        == "0x0000000000000000000000000000000000000000000000000000000000000001"
        and call_ends(function, 93, "String.__eq")
        and lines[94:100]
        == [
            "if $I6 (result i32)", "local.get $p0", lines[96],
            "local.tee $p0", "if $I7 (result i32)", "local.get $p0",
        ]
        and call_ends(function, 96, "StaticTokenDefinition.fromAddress")
        and lines[100] == f"i32.load offset={static_field_offset}"
        and lines[101] == "else"
        and V2.decoded_wat_constant(function.lines[102], memory) == "unknown"
        and lines[103:106] == ["end", "else", "local.get $l1"]
        and call_ends(function, 106, "#get:value")
        and call_ends(function, 107, "bytesToString")
        and lines[108:110] == ["end", "else"]
        and V2.decoded_wat_constant(function.lines[110], memory) == "unknown"
        and lines[111:113] == ["end", "end)"]
        and local_write_sites(lines, 2, len(lines), "$p0") == [97],
        f"{context['cid']} {field} helper fallback outcome drift",
    )
    proof["outcome_model"] = {
        "primary_string_call_success": "decoded string result",
        "primary_failure_bytes_call_success_non_sentinel": "decoded bytes32 string",
        "primary_failure_bytes_call_success_sentinel_static_match": f"profile-pinned static {field}",
        "primary_failure_bytes_call_success_sentinel_no_static_match": "unknown",
        "both_calls_fail": "unknown",
    }
    proof["primary_and_bytes_try_call_dataflow_machine_proven"] = True
    proof["sentinel_static_fallback_dataflow_machine_proven"] = True
    proof["smart_contract_source"] = contract_source
    return proof


def prove_decimals_helper(context: dict[str, Any]) -> dict[str, Any]:
    proof = prove_helper_body(context, "decimals", {})
    contract_source = prove_token_smart_contract_source(context, "decimals")
    function = function_by_suffix(context, "/fetchTokenDecimals")
    lines = [normalized(line) for line in function.lines]
    memory = context["memory"]
    require(
        lines[2].startswith("block $")
        and V2.decoded_wat_constant(function.lines[9], memory) == "decimals"
        and V2.decoded_wat_constant(function.lines[10], memory)
        == "decimals():(uint32)"
        and lines[11] == "i32.const 0"
        and call_ends(function, 14, "~lib/rt/__newArray")
        and call_ends(function, 15, "ethereum.SmartContract#tryCall")
        and lines[16:20]
        == ["local.tee $l1", "i32.load", "i32.eqz", "if $I1"],
        f"{context['cid']} decimals helper try-call flow drift",
    )
    require(
        lines[29:32] == ["br $B0", "end", "local.get $l1"]
        and call_ends(function, 32, "#get:value")
        and lines[33] == "i32.const 0"
        and call_ends(function, 34, "ethereum.EventParam>#__get")
        and call_ends(function, 35, "ethereum.Value#toBigInt")
        and "CallResult.fromValue" in (call_name(function.lines[36]) or "")
        and lines[37:46]
        == [
            "local.set $l5", "end", "local.get $l5", "i32.load", "if $I2",
            "block $B3 (result i32)", "local.get $l5", lines[44], "local.set $l3",
        ]
        and call_ends(function, 44, "#get:value"),
        f"{context['cid']} decimals helper successful-result decode flow drift",
    )
    require(
        lines[46] == "i32.const 255"
        and call_ends(function, 47, "BigInt.fromI32")
        and lines[48] == "local.set $l4"
        and lines[250:259]
        == [
            "i32.const 0", "end", "i32.const -1", "i32.eq", "if $I21",
            "local.get $l5", lines[256], "return", "end",
        ]
        and call_ends(function, 256, "#get:value"),
        f"{context['cid']} decimals helper less-than-255 return flow drift",
    )
    require(
        lines[259:264]
        == ["else", "local.get $p0", lines[261], "local.tee $p0", "if $I22"]
        and call_ends(function, 261, "StaticTokenDefinition.fromAddress")
        and lines[264:270]
        == ["local.get $p0", "i32.load offset=12", "return", "end", "end", "i32.const 0)"],
        f"{context['cid']} decimals helper static/null fallback flow drift",
    )
    require(
        lines[39:258] == list(DECIMALS_COMPARISON_STRUCTURE),
        f"{context['cid']} decimals complete signed BigInt comparison/dataflow drift",
    )
    require(
        local_write_sites(lines, 2, len(lines), "$p0") == [53, 65, 211, 246, 262]
        and local_write_sites(lines, 2, len(lines), "$l3") == [45]
        and local_write_sites(lines, 2, len(lines), "$l4") == [48]
        and lines[41] == "if $I2"
        and lines[258:261] == ["end", "else", "local.get $p0"],
        f"{context['cid']} decimals success locals/failure-path original address stability drift",
    )
    proof["outcome_model"] = {
        "call_success_below_255": "the decoded BigInt result",
        "call_success_at_or_above_255": None,
        "call_failure_static_match": "profile-pinned static decimals",
        "call_failure_without_static_match": None,
    }
    proof["successful_result_decode_and_threshold_return_machine_proven"] = True
    proof["static_or_null_failure_fallback_machine_proven"] = True
    proof["comparison_body_sha256"] = canonical_sha256(lines[42:254])
    proof["smart_contract_source"] = contract_source
    proof["complete_comparison_instruction_structure_machine_proven"] = True
    proof["decoded_result_and_threshold_locals_stable_through_comparison"] = True
    proof["failure_path_uses_original_input_address"] = True
    return proof


def prove_token_helpers(context: dict[str, Any]) -> dict[str, Any]:
    shared_runtime = prove_shared_runtime_primitives(context)
    symbol = prove_string_metadata_helper(context, "symbol", 4)
    name = prove_string_metadata_helper(context, "name", 8)
    decimals = prove_decimals_helper(context)
    total_supply_function = function_by_suffix(context, "/fetchTokenTotalSupply")
    total_supply_contract_source = prove_token_smart_contract_source(
        context, "total_supply"
    )
    expected_supply = EXPECTED_HELPERS[context["profile"]["profile_id"]]["total_supply"]
    require(
        len(total_supply_function.lines) == expected_supply[1]
        and hashlib.sha256(total_supply_function.payload).hexdigest() == expected_supply[2],
        f"{context['cid']} total-supply helper semantic body drift",
    )
    try:
        total_supply = V2.prove_factory_total_supply_helper(
            context["cid"], "modern", total_supply_function, context["functions"]
        )
    except V2.VerificationError as error:
        raise VerificationError(str(error)) from error
    require(
        total_supply["success_failure_dataflow_machine_proven"]
        and total_supply["success_result_decode_is_contiguous_into_value_wrapper"]
        and total_supply["outcomes"]["erc20_result_value_decoded"],
        f"{context['cid']} total-supply outcome proof did not close",
    )
    total_supply["smart_contract_source"] = total_supply_contract_source
    static = prove_static_definitions(context)
    support: dict[str, Any] = {
        "whitelist_membership": prove_whitelist_membership_helper(context),
        "whitelist_getter": prove_whitelist_getter_helper(context),
        "pool_id_getter": prove_id_getter_helper(
            context, "pool_id_getter", "schema/Pool#get:id"
        ),
        "token_id_getter": prove_id_getter_helper(
            context, "token_id_getter", "schema/Token#get:id"
        ),
    }
    return {
        "symbol": symbol,
        "name": name,
        "total_supply": total_supply,
        "decimals": decimals,
        "static_definitions": static,
        "whitelist_and_id_support": support,
        "shared_runtime_primitives": shared_runtime,
        "all_exact_symbol_name_decimals_and_total_supply_helpers_bound": True,
    }


def normalized_slice_sha256(function: Any, start: int, end: int) -> str:
    payload = "\n".join(normalized(line) for line in function.lines[start:end]) + "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def local_write_sites(
    lines: list[str], start: int, end: int, local: str
) -> list[int]:
    writes = {f"local.set {local}", f"local.tee {local}"}
    return [index for index in range(start, end) if lines[index] in writes]


def require_no_local_writes(
    context: dict[str, Any], start: int, end: int, local: str, label: str
) -> None:
    writes = local_write_sites(
        [normalized(line) for line in context["handler"].lines], start, end, local
    )
    require(
        not writes,
        f"{context['cid']} {label} successful-path local reassignment drift: {writes}",
    )


def prove_value_set_binding(
    context: dict[str, Any],
    site: int,
    receiver: str,
    value_kind: int,
    *,
    payload_local: str | None = None,
    payload_string: str | None = None,
) -> dict[str, Any]:
    """Bind one inline Value allocation continuously into one exact map set.

    The twelve instructions immediately before the setter are the complete
    allocation/kind/payload/receiver/key/final-operand sequence.  A producer
    proof must separately bind ``payload_local`` or ``payload_string`` to its
    semantic source.
    """

    require(
        (payload_local is None) != (payload_string is None),
        "exactly one Value payload authority must be supplied",
    )
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    entity, field = EXPECTED_SET_SITES[site]
    label = f"{context['cid']} {entity}.{field}"
    require(
        call_name(handler.lines[site]) == TYPED_MAP_SET_CALL,
        f"{label} exact TypedMap set call drift",
    )
    require(
        lines[site - 3] == f"local.get {receiver}",
        f"{label} exact entity receiver drift",
    )
    require(
        V2.decoded_wat_constant(handler.lines[site - 2], context["memory"]) == field,
        f"{label} exact decoded field key drift",
    )
    wrapper = lines[site - 9].removeprefix("local.tee ")
    expected_wrapper = (
        "$l3" if site in {379, 395} else "$l7" if site in {633, 966} else "$l1"
    )
    require(
        wrapper == expected_wrapper
        and lines[site - 12 : site - 10] == ["i32.const 16", "i32.const 27"]
        and call_name(handler.lines[site - 10]) == STUB_NEW_CALL
        and lines[site - 9] == f"local.tee {wrapper}",
        f"{label} exact Value allocation/identity drift",
    )
    require(
        lines[site - 8 : site - 6] == [f"i32.const {value_kind}", "i32.store"],
        f"{label} exact Value kind drift",
    )
    require(
        lines[site - 6] == f"local.get {wrapper}"
        and lines[site - 4] == "i64.store offset=8",
        f"{label} exact Value payload receiver/store drift",
    )
    if payload_local is not None:
        require(
            lines[site - 5] == f"local.get {payload_local}",
            f"{label} exact Value payload operand drift",
        )
    else:
        require(
            decoded_i64_string(handler.lines[site - 5], context["memory"])
            == payload_string,
            f"{label} exact decoded Value payload drift",
        )
    require(
        lines[site - 1] == f"local.get {wrapper}",
        f"{label} exact final Value operand drift",
    )
    return {
        "entity_receiver": receiver,
        "field_key": field,
        "value_kind_tag": value_kind,
        "payload_operand": payload_local or payload_string,
        "value_wrapper_local": wrapper,
        "exact_site_wrapper_local": expected_wrapper,
        "exact_receiver_key_kind_payload_final_operand_and_set_call_proven": True,
        "payload_and_wrapper_contiguous_without_reassignment": True,
    }


def prove_handler_entry_local_stability(context: dict[str, Any]) -> dict[str, Any]:
    """Prove entry-event and zero-initialized fee-copy locals stay authoritative."""

    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    p0_writes = local_write_sites(lines, 2, len(lines), "$p0")
    require(
        p0_writes == [416, 1906, 1951, 1961, 1976, 1996],
        f"{context['cid']} handler entry event $p0 write inventory drift: {p0_writes}",
    )
    require(
        lines[409:417]
        == [
            "local.get $l3", "if $I12", "local.get $l3", "i32.load", "if $I13",
            "local.get $l3", lines[415], "local.set $p0",
        ]
        and (call_name(handler.lines[415]) or "").endswith("Value#displayData")
        and (call_name(handler.lines[436]) or "").endswith("builtins/abort")
        and lines[437:439] == ["unreachable", "end"]
        and not any(
            line == "return" or line.startswith("br ") or line.startswith("br_if ")
            for line in lines[417:438]
        ),
        f"{context['cid']} sole pre-read $p0 write is not confined to the trap-only display path",
    )
    event_reads = [10, 507, 546, 566, 589, 609, 641, 673, 705, 922, 942, 974, 1006, 1038, 1318, 1498, 1516]
    pre_effect_p0_reads = [
        index for index in range(2, 1906) if lines[index] == "local.get $p0"
    ]
    require(
        all(lines[index] == "local.get $p0" for index in event_reads)
        and all(index < 1906 for index in event_reads),
        f"{context['cid']} handler event/block read inventory drift",
    )
    require(
        pre_effect_p0_reads == [10, 421, *event_reads[1:]],
        f"{context['cid']} complete pre-effect $p0 read inventory drift: {pre_effect_p0_reads}",
    )
    l2_writes = local_write_sites(lines, 2, len(lines), "$l2")
    require(
        l2_writes == [1451, 1460, 1468, 1476]
        and lines[1437:1453]
        == [
            "loop $L29", "local.get $l2", "local.get $l8", "i32.lt_s", "if $I30",
            "local.get $l1", "local.get $l2", "local.get $l7", "local.get $l2",
            lines[1446], lines[1447], "local.get $l2", "i32.const 1", "i32.add",
            "local.set $l2", "br $L29",
        ]
        and (call_name(handler.lines[1446]) or "").endswith("Uint8Array#__get")
        and (call_name(handler.lines[1447]) or "").endswith("Uint8Array#__set"),
        f"{context['cid']} feeTier zero-initialized $l2 copy-index flow drift",
    )
    return {
        "entry_event_local": "$p0",
        "event_and_block_read_sites": event_reads,
        "complete_pre_effect_entry_local_read_sites": pre_effect_p0_reads,
        "pre_read_write_sites": [416],
        "pre_read_write_is_trap_only": True,
        "post_read_write_sites": p0_writes[1:],
        "fee_copy_index_local": "$l2",
        "fee_copy_index_first_write_site": 1451,
        "entry_event_and_zero_copy_index_reaching_definitions_proven": True,
    }


def prove_entity_receiver_origins(context: dict[str, Any]) -> dict[str, Any]:
    """Bind each setter receiver local to the entity allocated for that role."""

    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    entity_constructor = (
        "~lib/@graphprotocol/graph-ts/common/collections/Entity#constructor"
    )
    for start, type_id, receiver, label in (
        (155, 25, "$l4", "Factory"),
        (362, 31, "$l1", "Bundle"),
        (518, 36, "$l6", "Pool"),
    ):
        require(
            lines[start : start + 2] == ["i32.const 4", f"i32.const {type_id}"]
            and call_name(handler.lines[start + 2]) == STUB_NEW_CALL
            and call_name(handler.lines[start + 3]) == entity_constructor
            and lines[start + 4] == f"local.set {receiver}",
            f"{context['cid']} {label} exact entity receiver origin drift",
        )
    token_sources = (
        (591, 0, "$l3", 600, "$l1", 601, 634, "Token[token0]"),
        (924, 1, "$l5", 933, "$l1", 934, 967, "Token[token1]"),
    )
    for start, event_index, entity_local, tee_site, alias_local, alias_site, alias_end, label in token_sources:
        require(
            lines[start : start + 4]
            == ["local.get $l1", "i32.load", "i32.load offset=24", f"i32.const {event_index}"]
            and call_name(handler.lines[start + 4]) == EVENT_PARAM_GET_CALL
            and lines[start + 5] == "i32.load offset=4"
            and call_name(handler.lines[start + 6]) == VALUE_TO_ADDRESS_CALL
            and (call_name(handler.lines[start + 7]) or "").endswith("typeConversion.bytesToHex")
            and call_name(handler.lines[start + 8]) == "src/types/schema/Token#constructor"
            and lines[tee_site] == f"local.tee {entity_local}"
            and lines[alias_site] == f"local.set {alias_local}",
            f"{context['cid']} {label} exact constructor receiver/source drift",
        )
        require_no_local_writes(
            context, alias_site + 1, alias_end, alias_local, f"{label} constructor alias"
        )
    require_no_local_writes(context, 160, 2021, "$l4", "Factory receiver")
    require_no_local_writes(context, 367, 396, "$l1", "Bundle receiver")
    require_no_local_writes(context, 523, 1934, "$l6", "Pool receiver")
    require_no_local_writes(context, 601, 912, "$l3", "Token[token0] receiver")
    require_no_local_writes(context, 934, 1244, "$l5", "Token[token1] receiver")
    return {
        "Factory": "$l4",
        "Bundle": "$l1",
        "Token[token0]": {"primary": "$l3", "constructor_alias": "$l1"},
        "Token[token1]": {"primary": "$l5", "constructor_alias": "$l1"},
        "Pool": "$l6",
        "exact_constructor_source_receiver_and_no_reassignment_proven": True,
    }


def prove_string_array_value_helper(context: dict[str, Any]) -> dict[str, Any]:
    proof = prove_helper_body(
        context,
        "string_array_value",
        {"input": "String[]", "output": "Value(kind=StringArray, payload=same ordered strings)"},
    )
    function = function_by_suffix(context, "Value.fromStringArray")
    lines = [normalized(line) for line in function.lines]
    require(
        lines[2:5] == ["local.get $p0", "i32.load offset=12", "local.set $l5"]
        and lines[5:20]
        == [
            "i32.const 16", "i32.const 33", lines[7], "local.tee $l1",
            "i32.const 0", "i32.store", "local.get $l1", "i32.const 0",
            "i32.store offset=4", "local.get $l1", "i32.const 0",
            "i32.store offset=8", "local.get $l1", "i32.const 0",
            "i32.store offset=12",
        ]
        and call_name(function.lines[7]) == STUB_NEW_CALL
        and lines[20:24]
        == ["local.get $l5", "i32.const 268435455", "i32.gt_u", "if $I0"]
        and (call_name(function.lines[28]) or "").endswith("builtins/abort")
        and lines[29:31] == ["unreachable", "end"]
        and lines[31:45]
        == [
            "local.get $l5", "i32.const 8", "local.get $l5", "i32.const 8",
            "i32.gt_u", "select", "i32.const 2", "i32.shl", "local.tee $l3",
            "i32.const 0", lines[41], "local.tee $l4", "local.get $l3", lines[44],
        ]
        and call_name(function.lines[41]) == STUB_NEW_CALL
        and (call_name(function.lines[44]) or "").endswith("memory.fill")
        and lines[45:57]
        == [
            "local.get $l1", "local.get $l4", "i32.store", "local.get $l1",
            "local.get $l4", "i32.store offset=4", "local.get $l1",
            "local.get $l3", "i32.store offset=8", "local.get $l1",
            "local.get $l5", "i32.store offset=12",
        ],
        f"{context['cid']} StringArray Value allocation/buffer/capacity/length drift",
    )
    require(
        lines[58:68]
        == [
            "local.get $p0", "i32.load offset=12", "local.get $l2", "i32.gt_s",
            "if $I2", "local.get $l1", "local.get $l2", "block $B3 (result i32)",
            "local.get $p0", "local.get $l2",
        ]
        and call_name(function.lines[68]) == EVENT_PARAM_GET_CALL
        and lines[69:81]
        == [
            "i64.extend_i32_u", "local.set $l6", "i32.const 16", "i32.const 27",
            lines[73], "local.tee $l3", "i32.const 0", "i32.store",
            "local.get $l3", "local.get $l6", "i64.store offset=8", "local.get $l3",
        ]
        and call_name(function.lines[73]) == STUB_NEW_CALL
        and (call_name(function.lines[82]) or "").endswith(
            "Array<~lib/@graphprotocol/graph-ts/common/value/Value>#__set"
        )
        and lines[83:88]
        == ["local.get $l2", "i32.const 1", "i32.add", "local.set $l2", "br $L1"],
        f"{context['cid']} StringArray Value ordered payload conversion drift",
    )
    require(
        lines[90:102]
        == [
            "local.get $l1", "i64.extend_i32_u", "local.set $l6", "i32.const 16",
            "i32.const 27", lines[95], "local.tee $p0", "i32.const 4",
            "i32.store", "local.get $p0", "local.get $l6",
            "i64.store offset=8",
        ]
        and lines[102].removesuffix(")") == "local.get $p0"
        and call_name(function.lines[95]) == STUB_NEW_CALL
        and local_write_sites(lines, 2, len(lines), "$p0") == [96]
        and local_write_sites(lines, 2, len(lines), "$l1") == [8]
        and local_write_sites(lines, 2, len(lines), "$l2") == [86]
        and local_write_sites(lines, 2, len(lines), "$l4") == [42]
        and local_write_sites(lines, 2, len(lines), "$l5") == [4],
        f"{context['cid']} StringArray Value exact kind/payload/return drift",
    )
    proof.update(
        {
            "value_kind_tag": 4,
            "same_ordered_input_strings_encoded_in_payload": True,
            "same_value_receiver_used_for_payload_and_return": True,
            "structural_kind_payload_and_return_machine_proven": True,
        }
    )
    return proof


def prove_whitelist_membership_helper(context: dict[str, Any]) -> dict[str, Any]:
    proof = prove_helper_body(
        context,
        "whitelist_membership",
        {"input": "needle String", "output": "needle equals one exact profile member"},
    )
    function = function_by_suffix(context, "Array<~lib/string/String>#includes")
    lines = [normalized(line) for line in function.lines]
    profile = context["profile"]["profile_id"]
    pointer_slot, length_slot = {
        "modern-base": (2788, 2796),
        "modern-mainnet": (4756, 4764),
    }[profile]
    require(
        lines[2:17]
        == [
            "block $B0 (result i32)", "i32.const -1", f"i32.const {length_slot}",
            "i32.load", "local.tee $l2", "i32.const 0", "i32.le_s",
            "i32.const 1", "local.get $l2", "select", "br_if $B0", "drop",
            f"i32.const {pointer_slot}", "i32.load", "local.set $l3",
        ]
        and lines[17:42]
        == [
            "loop $L1", "local.get $l1", "local.get $l2", "i32.lt_s", "if $I2",
            "local.get $l1", "local.get $l1", "i32.const 2", "i32.shl",
            "local.get $l3", "i32.add", "i32.load", "local.get $p0", lines[30],
            "br_if $B0", "drop", "local.get $l1", "i32.const 1", "i32.add",
            "local.set $l1", "br $L1", "end", "end", "i32.const -1", "end",
        ]
        and call_name(function.lines[30]) == "~lib/string/String.__eq"
        and lines[42] == "i32.const 0"
        and lines[43].removesuffix(")") == "i32.ge_s",
        f"{context['cid']} whitelist includes captured-array/input-loop/equality/return drift",
    )
    memory = context["memory"]
    require(
        pointer_slot + 4 <= len(memory) and length_slot + 4 <= len(memory),
        f"{context['cid']} whitelist captured-array slots outside memory",
    )
    backing_pointer = struct.unpack_from("<I", memory, pointer_slot)[0]
    length = struct.unpack_from("<I", memory, length_slot)[0]
    require(
        backing_pointer + length * 4 <= len(memory),
        f"{context['cid']} whitelist captured backing array outside memory",
    )
    member_pointers = [
        struct.unpack_from("<I", memory, backing_pointer + index * 4)[0]
        for index in range(length)
    ]
    members = [WRITER.decode_assemblyscript_string(memory, pointer) for pointer in member_pointers]
    require(
        members == EXPECTED_WHITELIST_MEMBERS[profile],
        f"{context['cid']} whitelist captured member profile drift: {members}",
    )
    require(
        not any(
            call_name(line) in {TYPED_MAP_SET_CALL, WRITER.STORE_SET_CALL}
            or (call_name(line) or "").endswith("dataSource.create")
            for line in function.lines
        )
        and not local_write_sites(lines, 2, len(lines), "$p0")
        and local_write_sites(lines, 2, len(lines), "$l1") == [36]
        and local_write_sites(lines, 2, len(lines), "$l2") == [6]
        and local_write_sites(lines, 2, len(lines), "$l3") == [16],
        f"{context['cid']} whitelist includes acquired a persistent side effect",
    )
    proof.update(
        {
            "captured_backing_pointer_slot": pointer_slot,
            "captured_length_slot": length_slot,
            "captured_backing_pointer": backing_pointer,
            "captured_length": length,
            "decoded_profile_members": members,
            "same_input_needle_compared_to_each_ordered_member": True,
            "loop_equality_and_boolean_return_structurally_proven": True,
        }
    )
    return proof


def prove_whitelist_getter_helper(context: dict[str, Any]) -> dict[str, Any]:
    proof = prove_helper_body(
        context,
        "whitelist_getter",
        {"input": "Token entity", "output": "same ordered whitelistPools strings"},
    )
    function = function_by_suffix(context, "schema/Token#get:whitelistPools")
    lines = [normalized(line) for line in function.lines]
    require(
        lines[2] == "local.get $p0"
        and V2.decoded_wat_constant(function.lines[3], context["memory"])
        == "whitelistPools"
        and call_name(function.lines[4]) == TYPED_MAP_GET_CALL
        and lines[5:14]
        == [
            "local.tee $p0", "if $I0 (result i32)", "local.get $p0", "i32.load",
            "i32.const 5", "i32.eq", "else", "i32.const 1", "end",
        ]
        and lines[14] == "if $I1"
        and (call_name(function.lines[19]) or "").endswith("builtins/abort")
        and lines[20:24] == ["unreachable", "else", "local.get $p0", lines[23]]
        and (call_name(function.lines[23]) or "").endswith("Value#toArray"),
        f"{context['cid']} whitelist getter receiver/key/kind/Value-array source drift",
    )
    require(
        lines[24:42]
        == [
            "local.tee $l3", "i32.load offset=12", "local.set $l4", "i32.const 16",
            "i32.const 3", lines[29], "local.tee $l1", "i32.const 0", "i32.store",
            "local.get $l1", "i32.const 0", "i32.store offset=4", "local.get $l1",
            "i32.const 0", "i32.store offset=8", "local.get $l1", "i32.const 0",
            "i32.store offset=12",
        ]
        and call_name(function.lines[29]) == STUB_NEW_CALL
        and lines[42:46]
        == ["local.get $l4", "i32.const 268435455", "i32.gt_u", "if $I2"]
        and (call_name(function.lines[50]) or "").endswith("builtins/abort")
        and lines[51:53] == ["unreachable", "end"]
        and lines[53:67]
        == [
            "local.get $l4", "i32.const 8", "local.get $l4", "i32.const 8",
            "i32.gt_u", "select", "i32.const 2", "i32.shl", "local.tee $l2",
            "i32.const 0", lines[63], "local.tee $p0", "local.get $l2", lines[66],
        ]
        and call_name(function.lines[63]) == STUB_NEW_CALL
        and (call_name(function.lines[66]) or "").endswith("memory.fill")
        and lines[67:79]
        == [
            "local.get $l1", "local.get $p0", "i32.store", "local.get $l1",
            "local.get $p0", "i32.store offset=4", "local.get $l1", "local.get $l2",
            "i32.store offset=8", "local.get $l1", "local.get $l4",
            "i32.store offset=12",
        ],
        f"{context['cid']} whitelist getter destination allocation/capacity/length drift",
    )
    require(
        lines[79:92]
        == [
            "i32.const 0", "local.set $p0", "loop $L3", "local.get $l3",
            "i32.load offset=12", "local.get $p0", "i32.gt_s", "if $I4",
            "local.get $l1", "local.get $p0", "local.get $l3", "local.get $p0",
            lines[91],
        ]
        and call_name(function.lines[91]) == EVENT_PARAM_GET_CALL
        and (call_name(function.lines[92]) or "").endswith("Value#toString")
        and (call_name(function.lines[93]) or "").endswith(
            "Array<~lib/@graphprotocol/graph-ts/common/value/Value>#__set"
        )
        and lines[94:102]
        == [
            "local.get $p0", "i32.const 1", "i32.add", "local.set $p0", "br $L3",
            "end", "end", "end",
        ]
        and lines[102].removesuffix(")") == "local.get $l1"
        and local_write_sites(lines, 24, 102, "$l1") == [30]
        and local_write_sites(lines, 24, 102, "$l3") == [24]
        and local_write_sites(lines, 26, 102, "$l4") == [26],
        f"{context['cid']} whitelist getter same-length ordered conversion/return drift",
    )
    require(
        not any(call_name(line) == TYPED_MAP_SET_CALL for line in function.lines),
        f"{context['cid']} whitelist getter acquired a map setter",
    )
    proof.update(
        {
            "decoded_key": "whitelistPools",
            "same_source_array_length_written_to_destination_offset_12": True,
            "same_index_Value_toString_conversion_and_ordered_return": True,
            "receiver_key_kind_array_conversion_and_return_structurally_proven": True,
        }
    )
    return proof


def prove_id_getter_helper(
    context: dict[str, Any], helper_key: str, suffix: str
) -> dict[str, Any]:
    proof = prove_helper_body(
        context,
        helper_key,
        {"input": "entity receiver", "output": "same non-null id Value converted to String"},
    )
    function = function_by_suffix(context, suffix)
    lines = [normalized(line) for line in function.lines]
    require(
        lines[1] == "local.get $p0"
        and V2.decoded_wat_constant(function.lines[2], context["memory"]) == "id"
        and call_name(function.lines[3]) == TYPED_MAP_GET_CALL
        and lines[4:14]
        == [
            "local.tee $p0", "if $I0 (result i32)", "local.get $p0", "i32.load",
            "i32.const 5", "i32.eq", "else", "i32.const 1", "end",
            "if $I1 (result i32)",
        ]
        and (call_name(function.lines[18]) or "").endswith("builtins/abort")
        and lines[19:23] == ["unreachable", "else", "local.get $p0", lines[22]]
        and (call_name(function.lines[22]) or "").endswith("Value#toString")
        and lines[23] == "end)"
        and local_write_sites(lines, 1, len(lines), "$p0") == [4],
        f"{context['cid']} {suffix} exact receiver/id/null-kind/same-Value-toString flow drift",
    )
    forbidden = {
        TYPED_MAP_SET_CALL,
        WRITER.STORE_SET_CALL,
    }
    require(
        not any(
            call_name(line) in forbidden
            or (call_name(line) or "").endswith("dataSource.create")
            or normalized(line).startswith("call_indirect")
            for line in function.lines
        ),
        f"{context['cid']} {suffix} acquired setter, host effect, or indirect call",
    )
    proof.update(
        {
            "decoded_key": "id",
            "same_input_receiver_used_for_get": True,
            "same_non_null_non_Null_Value_converted_to_string": True,
            "no_setter_or_persistent_side_effect": True,
            "receiver_key_guard_result_structurally_proven": True,
        }
    )
    return proof


def field_pointer_offset(site: int) -> int:
    if site in {910, 1243}:
        return 6
    if site in {1259, 1275}:
        return 3
    return 2


def observed_set_sites(context: dict[str, Any]) -> dict[int, str | None]:
    output: dict[int, str | None] = {}
    for index, line in enumerate(context["handler"].lines):
        if (call_name(line) or "").endswith(
            "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set"
        ):
            offset = field_pointer_offset(index)
            output[index] = V2.decoded_wat_constant(
                context["handler"].lines[index - offset], context["memory"]
            )
    return output


def prove_reachable_typed_map_setter_closure(
    context: dict[str, Any], token_constructor: dict[str, Any]
) -> dict[str, Any]:
    """Conservatively close every direct/indirect handler-reachable map setter."""

    normalized_functions: dict[str, Any] = {}
    for name, function in context["functions"].items():
        normalized_name = name.replace("generated/schema/", "src/types/schema/")
        require(
            normalized_name not in normalized_functions,
            f"{context['cid']} reachable-setter normalized function collision",
        )
        normalized_functions[normalized_name] = function
    root = context["handler"].name.replace(
        "generated/schema/", "src/types/schema/"
    )
    indirect_targets = tuple(
        name.replace("generated/schema/", "src/types/schema/")
        for name in context["indirect"]
    )
    queue: deque[str] = deque([root])
    visited: set[str] = set()
    setters: list[dict[str, Any]] = []
    indirect_sites: list[dict[str, Any]] = []
    while queue:
        name = queue.popleft()
        if name in visited:
            continue
        require(
            name in normalized_functions,
            f"{context['cid']} reachable-setter missing function {name}",
        )
        visited.add(name)
        function = normalized_functions[name]
        for index, raw_line in enumerate(function.lines):
            target = call_name(raw_line)
            if target is not None:
                normalized_target = target.replace(
                    "generated/schema/", "src/types/schema/"
                )
                if normalized_target in normalized_functions:
                    queue.append(normalized_target)
                if target == TYPED_MAP_SET_CALL:
                    setters.append({"function": name, "function_wat_line": index})
            elif normalized(raw_line).startswith("call_indirect"):
                indirect_sites.append(
                    {"function": name, "function_wat_line": index}
                )
                for target in indirect_targets:
                    require(
                        target in normalized_functions,
                        f"{context['cid']} reachable-setter indirect target missing: {target}",
                    )
                    queue.append(target)
    setters.sort(key=lambda item: (item["function"], item["function_wat_line"]))
    handler_setters = [
        item["function_wat_line"] for item in setters if item["function"] == root
    ]
    helper_setters = [item for item in setters if item["function"] != root]
    require(
        handler_setters == sorted(EXPECTED_SET_SITES),
        f"{context['cid']} reachable handler TypedMap#set inventory drift: {handler_setters}",
    )
    require(
        helper_setters
        == [
            {
                "function": "src/types/schema/Token#constructor",
                "function_wat_line": 23,
            }
        ],
        f"{context['cid']} reachable helper TypedMap#set inventory drift: {helper_setters}",
    )
    require(
        token_constructor["id_key"] == "id"
        and token_constructor["same_input_id_encoded_in_string_value_payload"]
        and token_constructor["same_fresh_receiver_used_for_map_set_and_return"]
        and token_constructor["constructor_id_and_receiver_machine_proven"],
        f"{context['cid']} sole reachable helper setter lacks Token.id certificate",
    )
    require(
        len(visited) == context["expected"]["reachable_function_count"]
        and len(setters) == 77
        and len(indirect_sites) == 1,
        f"{context['cid']} reachable direct/indirect setter closure cardinality drift",
    )
    return {
        "reachable_function_count": len(visited),
        "reachable_call_indirect_sites": indirect_sites,
        "conservative_indirect_targets": list(indirect_targets),
        "handler_typed_map_set_sites": handler_setters,
        "certified_helper_typed_map_set_sites": helper_setters,
        "complete_typed_map_set_site_count": len(setters),
        "complete_typed_map_set_sites_sha256": canonical_sha256(setters),
        "no_other_reachable_typed_map_setter": True,
        "complete_direct_and_indirect_typed_map_setter_closure_proven": True,
    }


def prove_simple_global_set(
    context: dict[str, Any], site: int, global_name: str, value_kind: int
) -> dict[str, Any]:
    lines = [normalized(line) for line in context["handler"].lines]
    entity, field = EXPECTED_SET_SITES[site]
    receiver = {
        "Factory": "$l4",
        "Bundle": "$l1",
        "Token[token0]": "$l3",
        "Token[token1]": "$l5",
        "Pool": "$l6",
    }[entity]
    require(
        lines[site - 15] == f"global.get $src/utils/constants/{global_name}"
        and lines[site - 14 : site - 11]
        == ["i64.extend_i32_u", "local.set $l9", "i32.const 16"],
        f"{context['cid']} {entity}.{field} {global_name} exact payload source drift",
    )
    binding = prove_value_set_binding(
        context, site, receiver, value_kind, payload_local="$l9"
    )
    return {
        "entity": entity,
        "field": field,
        "value": global_name,
        "value_kind": "BigInt" if value_kind == 7 else "BigDecimal",
        "wat_line": context["handler"].start_line + site,
        "set_binding": binding,
        "machine_proven": True,
    }


def prove_helper_field_set(
    context: dict[str, Any], site: int, helper_site: int, event_index: int,
    helper_suffix: str, value_kind: int, receiver: str
) -> dict[str, Any]:
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    entity, field = EXPECTED_SET_SITES[site]
    require(
        lines[helper_site - 7 : helper_site]
        == [
            "local.get $l7" if helper_site in {618, 951} else "local.get $l1",
            "i32.load",
            "i32.load offset=24",
            f"i32.const {event_index}",
            lines[helper_site - 3],
            "i32.load offset=4",
            lines[helper_site - 1],
        ]
        and call_name(handler.lines[helper_site - 3]) == EVENT_PARAM_GET_CALL
        and call_name(handler.lines[helper_site - 1]) == VALUE_TO_ADDRESS_CALL
        and call_name(handler.lines[helper_site]) == f"src/utils/token/{helper_suffix}",
        f"{context['cid']} {entity}.{field} event/helper argument flow drift",
    )
    if helper_suffix.endswith("fetchTokenDecimals"):
        expected_return = 725 if event_index == 0 else 1058
        require(
            lines[helper_site + 1 : helper_site + 4]
            == ["local.tee $l1", "i32.eqz", lines[helper_site + 3]]
            and lines[helper_site + 3].startswith("if $")
            and lines[expected_return] == "return"
            and lines[expected_return + 1] == "end"
            and lines[site - 15 : site - 12]
            == ["local.get $l1", "i64.extend_i32_u", "local.set $l9"],
            f"{context['cid']} {entity}.{field} null-decimals early-return flow drift",
        )
        require(
            local_write_sites(lines, helper_site + 1, site - 14, "$l1") == [helper_site + 1],
            f"{context['cid']} {entity}.{field} helper result local reassignment drift",
        )
    else:
        require(
            site == helper_site + 15
            and lines[helper_site + 1 : helper_site + 4]
            == ["i64.extend_i32_u", "local.set $l9", "i32.const 16"],
            f"{context['cid']} {entity}.{field} helper result packaging drift",
        )
    binding = prove_value_set_binding(
        context, site, receiver, value_kind, payload_local="$l9"
    )
    return {
        "entity": entity,
        "field": field,
        "value": f"exact {helper_suffix.rsplit('/', 1)[-1]}(event[{event_index}]) outcome",
        "value_kind": "String" if value_kind == 0 else "BigInt",
        "event_index": event_index,
        "wat_line": handler.start_line + site,
        "set_binding": binding,
        "machine_proven": True,
    }


def prove_fee_tier_source(context: dict[str, Any]) -> dict[str, Any]:
    """Bind event[2]'s Value payload through the inlined signed i32 decode."""

    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    profile = context["profile"]["profile_id"]
    digest = normalized_slice_sha256(handler, 1311, 1483)
    require(
        digest == EXPECTED_FEE_TIER_SLICE_SHA256[profile],
        f"{context['cid']} Pool.feeTier exact retained conversion slice drift",
    )
    require(
        lines[1311:1324]
        == [
            "i32.const 4", "i32.const 24", lines[1313], "local.tee $l1",
            "i32.const 0", "i32.store", "local.get $l1", "local.get $p0",
            "i32.store", "local.get $l1", "i32.load", "i32.load offset=24",
            "i32.const 2",
        ]
        and call_name(handler.lines[1313]) == STUB_NEW_CALL
        and call_name(handler.lines[1324]) == EVENT_PARAM_GET_CALL
        and lines[1325] == "i32.load offset=4",
        f"{context['cid']} Pool.feeTier exact event[2] Value source drift",
    )
    require(
        lines[1326:1340]
        == [
            "local.tee $l1", "i32.load", "i32.const 3", "i32.eq",
            "if $I23 (result i32)", "i32.const 1", "else", "local.get $l1",
            "i32.load", "i32.const 4", "i32.eq", "end", "i32.eqz", "if $I24",
        ]
        and (call_name(handler.lines[1344]) or "").endswith("builtins/abort")
        and lines[1345:1347] == ["unreachable", "end"],
        f"{context['cid']} Pool.feeTier exact Value-kind gate drift",
    )
    require(
        lines[1347:1373]
        == [
            "i32.const 255", "i32.const 0", "local.get $l1", "i64.load offset=8",
            "i32.wrap_i64", "local.tee $l7", "i32.load offset=8", "i32.const 0",
            "i32.gt_s", "local.tee $l1", "if $I25 (result i32)", "local.get $l7",
            "local.get $l7", "i32.load offset=8", "i32.const 1", "i32.sub",
            "call $~lib/typedarray/Uint8Array#__get", "i32.const 7", "i32.shr_u",
            "i32.const 1", "i32.eq", "else", "local.get $l1", "end", "select",
            "local.set $l8",
        ],
        f"{context['cid']} Pool.feeTier exact Value payload/sign source drift",
    )
    require(
        lines[1373:1387]
        == [
            "i32.const 4", "local.set $l1", "loop $L26", "local.get $l7",
            "i32.load offset=8", "local.get $l1", "i32.gt_s", "if $I27",
            "local.get $l7", "local.get $l1",
            "call $~lib/typedarray/Uint8Array#__get", "local.get $l8", "i32.ne",
            "if $I28",
        ]
        and lines[1399:1455]
        == [
            "local.get $l1", "i32.const 1", "i32.add", "local.set $l1", "br $L26",
            "end", "end", "i32.const 12", "i32.const 9",
            "call $~lib/rt/stub/__new", "i32.const 4",
            "call $~lib/@graphprotocol/graph-ts/common/collections/ByteArray#constructor",
            "local.tee $l1", "i32.const 0", "local.get $l8",
            "call $~lib/typedarray/Uint8Array#__set", "local.get $l1", "i32.const 1",
            "local.get $l8", "call $~lib/typedarray/Uint8Array#__set",
            "local.get $l1", "i32.const 2", "local.get $l8",
            "call $~lib/typedarray/Uint8Array#__set", "local.get $l1", "i32.const 3",
            "local.get $l8", "call $~lib/typedarray/Uint8Array#__set",
            "local.get $l1", "local.get $l7", "local.get $l1",
            "i32.load offset=8", "local.get $l7", "i32.load offset=8", "i32.lt_s",
            "select", "i32.load offset=8", "local.set $l8", "loop $L29",
            "local.get $l2", "local.get $l8", "i32.lt_s", "if $I30",
            "local.get $l1", "local.get $l2", "local.get $l7", "local.get $l2",
            "call $~lib/typedarray/Uint8Array#__get",
            "call $~lib/typedarray/Uint8Array#__set", "local.get $l2", "i32.const 1",
            "i32.add", "local.set $l2", "br $L29", "end", "end",
        ],
        f"{context['cid']} Pool.feeTier exact sign-extension/byte-copy flow drift",
    )
    require(
        lines[1455:1483]
        == [
            "local.get $l1", "i32.const 3", "call $~lib/typedarray/Uint8Array#__get",
            "i32.const 8", "i32.shl", "local.set $l2", "local.get $l1",
            "i32.const 2", "call $~lib/typedarray/Uint8Array#__get", "local.get $l2",
            "i32.or", "i32.const 8", "i32.shl", "local.set $l2", "local.get $l1",
            "i32.const 1", "call $~lib/typedarray/Uint8Array#__get", "local.get $l2",
            "i32.or", "i32.const 8", "i32.shl", "local.set $l2", "local.get $l1",
            "i32.const 0", "call $~lib/typedarray/Uint8Array#__get", "local.get $l2",
            "i32.or",
            "call $~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
        ]
        and not local_write_sites(lines, 1353, 1483, "$l7"),
        f"{context['cid']} Pool.feeTier exact byte assembly/BigInt source drift",
    )
    return {
        "source": "event[2].value",
        "accepted_source_value_kinds": [3, 4],
        "normalized_conversion_slice_sha256": digest,
        "slice_digest_role": "exact retained-artifact closure over the inlined conversion",
        "event_value_payload_sign_extension_byte_copy_and_i32_assembly_structurally_proven": True,
    }


def prove_special_field_flows(context: dict[str, Any]) -> list[dict[str, Any]]:
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    output: list[dict[str, Any]] = []
    factory_id = EFFECTS.EXPECTED_ARTIFACTS[context["cid"]]["factory_id"]
    binding = prove_value_set_binding(
        context, 172, "$l4", 0, payload_string=factory_id
    )
    output.append(
        {"entity": "Factory", "field": "id", "value": factory_id, "set_binding": binding, "machine_proven": True}
    )
    binding = prove_value_set_binding(
        context, 379, "$l1", 0, payload_string="1"
    )
    output.append(
        {"entity": "Bundle", "field": "id", "value": "1", "set_binding": binding, "machine_proven": True}
    )
    address_zero = "0x0000000000000000000000000000000000000000"
    binding = prove_value_set_binding(
        context, 361, "$l4", 0, payload_string=address_zero
    )
    output.append(
        {"entity": "Factory", "field": "owner", "value": "ADDRESS_ZERO", "set_binding": binding, "machine_proven": True}
    )

    require(
        lines[446] == "local.get $l4"
        and V2.decoded_wat_constant(handler.lines[447], context["memory"]) == "poolCount"
        and call_name(handler.lines[448]) == TYPED_MAP_GET_CALL
        and lines[449:459]
        == [
            "local.tee $l1", "if $I14 (result i32)", "local.get $l1", "i32.load",
            "i32.const 5", "i32.eq", "else", "i32.const 1", "end",
            "if $I15 (result i32)",
        ]
        and (call_name(handler.lines[463]) or "").endswith("builtins/abort")
        and lines[464:469]
        == ["unreachable", "else", "local.get $l1", lines[467], "end"]
        and (call_name(handler.lines[467]) or "").endswith("Value#toBigInt")
        and lines[469:485]
        == [
            "local.set $l1", "global.get $src/utils/constants/ONE_BI", "local.set $l3",
            "local.get $l1", "i32.eqz", "if $I16", lines[475], lines[476],
            "i32.const 185", "i32.const 5", lines[479], "unreachable", "end",
            "local.get $l1", "local.get $l3", lines[484],
        ]
        and (call_name(handler.lines[479]) or "").endswith("builtins/abort")
        and (call_name(handler.lines[484]) or "").endswith("numbers/bigInt.plus")
        and lines[485:487] == ["i64.extend_i32_u", "local.set $l9"]
        and not local_write_sites(lines, 470, 484, "$l1")
        and not local_write_sites(lines, 472, 484, "$l3"),
        f"{context['cid']} Factory.poolCount continuous getter/decode/plus source drift",
    )
    binding = prove_value_set_binding(
        context, 499, "$l4", 7, payload_local="$l9"
    )
    output.append(
        {"entity": "Factory", "field": "poolCount", "value": "old poolCount + ONE_BI", "set_binding": binding, "machine_proven": True}
    )

    require(
        lines[500:513]
        == [
            "i32.const 4", "i32.const 24", lines[502], "local.tee $l1",
            "i32.const 0", "i32.store", "local.get $l1", "local.get $p0",
            "i32.store", "local.get $l1", "i32.load", "i32.load offset=24",
            "i32.const 4",
        ]
        and call_name(handler.lines[502]) == STUB_NEW_CALL
        and call_name(handler.lines[513]) == EVENT_PARAM_GET_CALL
        and lines[514] == "i32.load offset=4"
        and call_name(handler.lines[515]) == VALUE_TO_ADDRESS_CALL
        and (call_name(handler.lines[516]) or "").endswith("typeConversion.bytesToHex")
        and lines[517] == "local.set $l1"
        and lines[518:526]
        == [
            "i32.const 4", "i32.const 36", lines[520], lines[521], "local.set $l6",
            "local.get $l1", "i64.extend_i32_u", "local.set $l9",
        ]
        and call_name(handler.lines[520]) == STUB_NEW_CALL
        and (call_name(handler.lines[521]) or "").endswith("Entity#constructor")
        and not local_write_sites(lines, 518, 523, "$l1"),
        f"{context['cid']} Pool.id continuous event[4]/decode/payload source drift",
    )
    binding = prove_value_set_binding(
        context, 538, "$l6", 0, payload_local="$l9"
    )
    output.append(
        {"entity": "Pool", "field": "id", "value": "bytesToHex(event[4].pool)", "set_binding": binding, "machine_proven": True}
    )

    for site, getter_local in ((1293, "$l3"), (1310, "$l5")):
        entity, field = EXPECTED_SET_SITES[site]
        require(
            lines[site - 16 : site - 12]
            == [f"local.get {getter_local}", lines[site - 15], "i64.extend_i32_u", "local.set $l9"]
            and call_name(handler.lines[site - 15]) == "src/types/schema/Token#get:id",
            f"{context['cid']} Pool.{field} continuous Token.id getter source drift",
        )
        binding = prove_value_set_binding(
            context, site, "$l6", 0, payload_local="$l9"
        )
        output.append(
            {"entity": entity, "field": field, "value": f"Token[{field}].id", "set_binding": binding, "machine_proven": True}
        )

    fee_source = prove_fee_tier_source(context)
    require(
        lines[1483:1485] == ["i64.extend_i32_u", "local.set $l9"],
        f"{context['cid']} Pool.feeTier final BigInt payload local drift",
    )
    binding = prove_value_set_binding(
        context, 1497, "$l6", 7, payload_local="$l9"
    )
    output.append(
        {"entity": "Pool", "field": "feeTier", "value": "BigInt.fromI32(event[2].fee)", "source_proof": fee_source, "set_binding": binding, "machine_proven": True}
    )
    for site, offset, field in (
        (1515, 40, "createdAtTimestamp"),
        (1533, 28, "createdAtBlockNumber"),
    ):
        require(
            lines[site - 17 : site - 12]
            == [
                "local.get $p0", "i32.load offset=16", f"i32.load offset={offset}",
                "i64.extend_i32_u", "local.set $l9",
            ],
            f"{context['cid']} Pool.{field} continuous block-field payload source drift",
        )
        binding = prove_value_set_binding(
            context, site, "$l6", 7, payload_local="$l9"
        )
        output.append(
            {"entity": "Pool", "field": field, "value": f"event.block.offset[{offset}]", "set_binding": binding, "machine_proven": True}
        )
    return output


def prove_empty_whitelist_sets(context: dict[str, Any]) -> list[dict[str, Any]]:
    handler = context["handler"]
    lines = [normalized(line) for line in context["handler"].lines]
    output = []
    for site, receiver in ((910, "$l3"), (1243, "$l5")):
        entity, field = EXPECTED_SET_SITES[site]
        require(
            lines[site - 7] == f"local.get {receiver}"
            and V2.decoded_wat_constant(handler.lines[site - 6], context["memory"])
            == "whitelistPools"
            and lines[site - 5 : site - 3] == ["i32.const 0", "i32.const 3"]
            and lines[site - 3].startswith("i32.const ")
            and (call_name(handler.lines[site - 2]) or "").endswith("rt/__newArray")
            and call_name(handler.lines[site - 1]) == VALUE_FROM_STRING_ARRAY_CALL
            and call_name(handler.lines[site]) == TYPED_MAP_SET_CALL,
            f"{context['cid']} {entity}.whitelistPools exact empty-array receiver/key/Value/set binding drift",
        )
        output.append(
            {
                "entity": entity,
                "field": field,
                "value": [],
                "entity_receiver": receiver,
                "value_kind_tag": 4,
                "same_new_empty_array_is_final_Value_payload_operand": True,
                "exact_receiver_key_Value_helper_and_set_call_proven": True,
                "machine_proven": True,
            }
        )
    return output


def prove_whitelist_updates(context: dict[str, Any]) -> list[dict[str, Any]]:
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    cases = [
        (1245, "$l3", "$l5", 1259, "token0", "token1"),
        (1261, "$l5", "$l3", 1275, "token1", "token0"),
    ]
    output = []
    for start, predicate_token, updated_token, site, predicate_name, updated_name in cases:
        require(
            lines[start] == f"local.get {predicate_token}"
            and call_name(handler.lines[start + 1]) == "src/types/schema/Token#get:id"
            and (call_name(handler.lines[start + 2]) or "").endswith("Array<~lib/string/String>#includes")
            and lines[start + 3].startswith("if $")
            and lines[start + 4] == f"local.get {updated_token}"
            and call_name(handler.lines[start + 5]) == "src/types/schema/Token#get:whitelistPools"
            and lines[start + 6] == "local.tee $l1"
            and lines[start + 7] == "local.get $l6"
            and call_name(handler.lines[start + 8]) == "src/types/schema/Pool#get:id"
            and (call_name(handler.lines[start + 9]) or "").endswith("#push")
            and lines[site - 4] == f"local.get {updated_token}"
            and V2.decoded_wat_constant(handler.lines[site - 3], context["memory"])
            == "whitelistPools"
            and lines[site - 2] == "local.get $l1"
            and call_name(handler.lines[site - 1]) == VALUE_FROM_STRING_ARRAY_CALL
            and call_name(handler.lines[site]) == TYPED_MAP_SET_CALL
            and lines[site + 1] == "end",
            f"{context['cid']} {predicate_name}-to-{updated_name} exact whitelist source/receiver/key/Value/set binding drift",
        )
        require(
            not local_write_sites(lines, start + 7, site - 1, "$l1"),
            f"{context['cid']} {predicate_name}-to-{updated_name} whitelist payload reassignment drift",
        )
        output.append(
            {
                "predicate": f"profile-pinned whitelist includes {predicate_name}.id",
                "updated_entity": f"Token[{updated_name}]",
                "value": f"old whitelistPools appended with Pool.id",
                "wat_line": handler.start_line + site,
                "entity_receiver": updated_token,
                "value_kind_tag": 4,
                "same_mutated_array_is_final_Value_payload_operand": True,
                "exact_receiver_key_Value_helper_and_set_call_proven": True,
                "machine_proven": True,
            }
        )
    return output


def prove_field_contract(
    context: dict[str, Any], token_constructor: dict[str, Any]
) -> dict[str, Any]:
    require(
        token_constructor["id_key"] == "id"
        and token_constructor["value_kind_tag"] == 0
        and token_constructor["same_input_id_encoded_in_string_value_payload"]
        and token_constructor["same_fresh_receiver_used_for_map_set_and_return"]
        and token_constructor["constructor_id_and_receiver_machine_proven"],
        f"{context['cid']} Token.id constructor field flow drift",
    )
    receiver_origins = prove_entity_receiver_origins(context)
    handler_local_stability = prove_handler_entry_local_stability(context)
    reachable_setter_closure = prove_reachable_typed_map_setter_closure(
        context, token_constructor
    )
    string_array_value = prove_string_array_value_helper(context)
    require(
        string_array_value["value_kind_tag"] == 4
        and string_array_value["same_ordered_input_strings_encoded_in_payload"]
        and string_array_value["same_value_receiver_used_for_payload_and_return"]
        and string_array_value["structural_kind_payload_and_return_machine_proven"],
        f"{context['cid']} StringArray Value helper proof did not close",
    )
    observed = observed_set_sites(context)
    require(set(observed) == set(EXPECTED_SET_SITES), f"{context['cid']} complete 76-set inventory drift")
    require(
        "tick" not in observed.values()
        and not any(
            (call_name(line) or "").endswith("Pool#set:tick")
            for line in context["handler"].lines
        ),
        f"{context['cid']} Pool.tick required-absence drift",
    )
    for site, (_entity, expected_field) in EXPECTED_SET_SITES.items():
        require(observed[site] == expected_field, f"{context['cid']} field key drift at handler line {site}: expected {expected_field}, got {observed[site]}")
    simple = []
    for site in sorted(ZERO_BI_SITES):
        simple.append(prove_simple_global_set(context, site, "ZERO_BI", 7))
    for site in sorted(ZERO_BD_SITES):
        simple.append(prove_simple_global_set(context, site, "ZERO_BD", 2))
    helper_sets = [
        prove_helper_field_set(context, 633, 618, 0, "fetchTokenSymbol", 0, "$l1"),
        prove_helper_field_set(context, 665, 650, 0, "fetchTokenName", 0, "$l3"),
        prove_helper_field_set(context, 697, 682, 0, "fetchTokenTotalSupply", 7, "$l3"),
        prove_helper_field_set(context, 742, 714, 0, "fetchTokenDecimals", 7, "$l3"),
        prove_helper_field_set(context, 966, 951, 1, "fetchTokenSymbol", 0, "$l1"),
        prove_helper_field_set(context, 998, 983, 1, "fetchTokenName", 0, "$l5"),
        prove_helper_field_set(context, 1030, 1015, 1, "fetchTokenTotalSupply", 7, "$l5"),
        prove_helper_field_set(context, 1075, 1047, 1, "fetchTokenDecimals", 7, "$l5"),
    ]
    special = prove_special_field_flows(context)
    empty = prove_empty_whitelist_sets(context)
    updates = prove_whitelist_updates(context)
    helper_sites = {633, 665, 697, 742, 966, 998, 1030, 1075}
    special_sites = {172, 361, 379, 499, 538, 1293, 1310, 1497, 1515, 1533}
    whitelist_sites = {910, 1243, 1259, 1275}
    semantic_site_families = (
        ZERO_BI_SITES,
        ZERO_BD_SITES,
        helper_sites,
        special_sites,
        whitelist_sites,
    )
    require(
        sum(len(sites) for sites in semantic_site_families)
        == len(set().union(*semantic_site_families))
        and set().union(*semantic_site_families) == set(EXPECTED_SET_SITES)
        and len(simple) == len(ZERO_BI_SITES) + len(ZERO_BD_SITES)
        and len(helper_sets) == len(helper_sites)
        and len(special) == len(special_sites)
        and len(empty) + len(updates) == len(whitelist_sites),
        f"{context['cid']} complete setter semantic-family coverage drift",
    )
    all_schema_fields = {
        *(f"Factory.{field}" for field in FACTORY_FIELDS),
        *(f"Bundle.{field}" for field in BUNDLE_FIELDS),
        *(f"Token.{field}" for field in TOKEN_FIELDS),
        *(f"Pool.{field}" for field in POOL_FIELDS),
    }
    require(len(all_schema_fields) == 60, "modern Factory stored-field contract count drift")
    written = all_schema_fields - {"Pool.tick"}
    require(len(written) == 59, "modern Factory written-field count drift")
    return {
        "stored_field_contract_count": 60,
        "written_field_count": 59,
        "required_absent_fields": ["Pool.tick"],
        "stored_fields": sorted(all_schema_fields),
        "written_fields": sorted(written),
        "handler_typed_map_set_count": len(observed),
        "handler_typed_map_set_inventory_sha256": canonical_sha256(
            [[site, *EXPECTED_SET_SITES[site]] for site in sorted(EXPECTED_SET_SITES)]
        ),
        "handler_semantic_set_family_coverage_sha256": canonical_sha256(
            [
                [site, *EXPECTED_SET_SITES[site]]
                for site in sorted(set().union(*semantic_site_families))
            ]
        ),
        "simple_global_value_flows": simple,
        "token_helper_field_flows": helper_sets,
        "special_field_flows": special,
        "empty_whitelist_initializers": empty,
        "conditional_whitelist_updates": updates,
        "token_id_constructor_flow": token_constructor,
        "entity_receiver_origins": receiver_origins,
        "handler_entry_local_stability": handler_local_stability,
        "reachable_typed_map_setter_closure": reachable_setter_closure,
        "string_array_value_helper_flow": string_array_value,
        "all_76_handler_map_sets_accounted": True,
        "all_59_written_field_transitions_machine_proven": True,
        "pool_tick_required_absence_machine_proven": True,
    }


FULL_SUFFIX = (
    "Pool.save", "PoolTemplate.create", "Token[token0].save",
    "Token[token1].save", "Factory.save",
)
BUNDLE_EFFECT = "Bundle.save"


def prove_partial_effect_traces(context: dict[str, Any]) -> dict[str, Any]:
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    frames, by_label = EFFECTS.parse_structured_control(lines)
    cfg = EFFECTS.build_cfg(
        lines, frames, by_label, EFFECTS.GENERATION_INVENTORY["modern"]["forced_true_ifs"]
    )
    require(
        call_name(handler.lines[443]) == WRITER.STORE_SET_CALL
        and EFFECTS.direct_store_arguments(context, 443)
        == {"target": "Bundle", "id_value_local": "$l3", "entity_local": "$l1"},
        f"{context['cid']} Bundle partial-effect site/argument drift",
    )
    suffix_sites = EFFECTS.observed_selected_handler_effects(context)
    require(
        suffix_sites
        == [
            (1933, FULL_SUFFIX[0]), (1968, FULL_SUFFIX[1]),
            (1970, FULL_SUFFIX[2]), (1972, FULL_SUFFIX[3]),
            (2020, FULL_SUFFIX[4]),
        ],
        f"{context['cid']} complete effect-suffix site/order drift",
    )
    effect_sites = {
        443: BUNDLE_EFFECT,
        **dict(suffix_sites),
    }
    queue: deque[tuple[int, tuple[str, ...]]] = deque([(2, ())])
    visited: set[tuple[int, tuple[str, ...]]] = set()
    normal: set[tuple[str, ...]] = set()
    traps: set[tuple[str, ...]] = set()
    while queue:
        node, trace = queue.popleft()
        state = (node, trace)
        if state in visited:
            continue
        visited.add(state)
        next_trace = trace + ((effect_sites[node],) if node in effect_sites else ())
        require(
            next_trace in {
                (), (BUNDLE_EFFECT,), FULL_SUFFIX, (BUNDLE_EFFECT,) + FULL_SUFFIX,
                *{FULL_SUFFIX[:index] for index in range(1, len(FULL_SUFFIX))},
                *{(BUNDLE_EFFECT,) + FULL_SUFFIX[:index] for index in range(1, len(FULL_SUFFIX))},
            },
            f"{context['cid']} partial effect sequence drift at handler line {node}: {next_trace}",
        )
        for successor in cfg[node]:
            if successor == EFFECTS.NORMAL_EXIT:
                normal.add(next_trace)
            elif successor == EFFECTS.TRAP_EXIT:
                traps.add(next_trace)
            else:
                queue.append((successor, next_trace))
    expected_normal = {
        (), (BUNDLE_EFFECT,), FULL_SUFFIX, (BUNDLE_EFFECT,) + FULL_SUFFIX,
    }
    require(normal == expected_normal, f"{context['cid']} early-return normal effect traces drift: {sorted(normal)}")
    require(
        lines[147] == lines[725] == lines[1058] == "return"
        and 443 < 725 < 1058 < 1933,
        f"{context['cid']} early-return/effect placement drift",
    )
    return {
        "effect_projection": [BUNDLE_EFFECT, *FULL_SUFFIX],
        "normal_exit_traces": [list(item) for item in sorted(normal, key=lambda item: (len(item), item))],
        "handler_local_explicit_trap_traces": [list(item) for item in sorted(traps, key=lambda item: (len(item), item))],
        "excluded_pool_return_trace": [],
        "decimals_return_when_factory_present": [],
        "decimals_return_when_factory_missing": [BUNDLE_EFFECT],
        "complete_when_factory_present": list(FULL_SUFFIX),
        "complete_when_factory_missing": [BUNDLE_EFFECT, *FULL_SUFFIX],
        "bundle_save_precedes_both_decimals_returns": True,
        "all_handler_local_normal_exits_machine_proven": True,
        "graph_handler_rollback_proven_by_retained_wat": False,
    }


def prove_modern_static(context: dict[str, Any]) -> dict[str, Any]:
    require(context["cid"] in MODERN_CIDS, f"unexpected modern Factory context: {context['cid']}")
    try:
        effects = EFFECTS.prove_factory_effects(context)
    except EFFECTS.VerificationError as error:
        raise VerificationError(str(error)) from error
    require(effects["generation"] == "modern", f"{context['cid']} generation drift")
    start = prove_start_constants(context)
    helpers = prove_token_helpers(context)
    token_constructor = effects["generation_frontend"]["token_constructor_proof"]
    fields = prove_field_contract(context, token_constructor)
    traces = prove_partial_effect_traces(context)
    return {
        "profile_id": context["profile"]["profile_id"],
        "mapping_cid": context["cid"],
        "authority": {
            "wasm_sha256": effects["authority"]["wasm_sha256"],
            "wat_sha256": effects["authority"]["wat_sha256"],
            "handler_function": effects["authority"]["handler_function"],
            "handler_body_sha256": effects["authority"]["handler_body_sha256"],
            "handler_wat_start_line": effects["authority"]["handler_wat_start_line"],
            "wabt_version": WRITER.WABT_VERSION,
        },
        "upstream_effect_proof_sha256": canonical_sha256(effects),
        "module_constants": start,
        "token_call_helpers": helpers,
        "field_contract": fields,
        "normal_return_and_partial_effect_contract": traces,
        "complete_static_handler_contract": True,
        "graph_handler_rollback_proven_by_retained_wat": False,
        "actual_historic_call_outcomes_bound": False,
    }


def load_contexts(root: Path, wasm2wat: Path | None = None) -> list[dict[str, Any]]:
    root = root.resolve()
    effects_path = root / EFFECTS_CONTRACT_PATH
    require(
        effects_path.is_file() and raw_sha256(effects_path) == EFFECTS_CONTRACT_SHA256,
        "pinned Factory effects contract raw digest drift",
    )
    try:
        effects_contract = EFFECTS.verify_contract(root, wasm2wat=wasm2wat)
    except EFFECTS.VerificationError as error:
        raise VerificationError(str(error)) from error
    require(
        effects_contract["scope"]["cumulative_closed_after_this_supplement"] == 12
        and effects_contract["scope"]["residual_after_this_supplement"] == 6,
        "Factory effects closure scope drift",
    )
    contexts = [
        context
        for context in EFFECTS.load_contexts(root, wasm2wat)
        if context["cid"] in MODERN_CIDS
    ]
    require(
        tuple(context["cid"] for context in contexts) == MODERN_CIDS,
        "modern Factory context order/set drift",
    )
    executable = WRITER.resolve_wasm2wat(wasm2wat)
    for context in contexts:
        artifact = (
            root
            / "uniswap-v3/graft-ancestry/v1/artifacts"
            / context["cid"]
        )
        module_payload = WRITER.run_wasm2wat(executable, artifact)
        require(
            hashlib.sha256(module_payload).hexdigest()
            == context["analysis"]["wat_sha256"],
            f"{context['cid']} complete module WAT digest drift",
        )
        _memory, _functions, _indirect, exports = WRITER.parse_wat(
            module_payload.decode()
        )
        context["module_text"] = module_payload.decode()
        context["exports"] = exports
    return contexts


def expected_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    runtime_sha256 = bind_candidate_runtime(root)
    proofs = [prove_modern_static(context) for context in load_contexts(root, wasm2wat)]
    require(len(proofs) == 2, "modern Factory static proof count drift")
    require(
        all(
            proof["complete_static_handler_contract"]
            and proof["field_contract"]["stored_field_contract_count"] == 60
            and proof["field_contract"]["written_field_count"] == 59
            and proof["field_contract"]["required_absent_fields"] == ["Pool.tick"]
            for proof in proofs
        ),
        "modern Factory static proof did not close",
    )
    truth = {key: True for key in sorted(TRUE_FLAGS)} | {
        key: False for key in sorted(FALSE_FLAGS)
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "authority_contract": {
            "semantic_authority": "the exact modern Base and modern mainnet deployed Factory WASM artifacts and checksum-pinned WABT 1.0.35 --generate-names WAT projections",
            "proof_model": "the inherited complete handler CFG/SSA/effect proof plus exact exported-initializer dispatch and critical-global writer inventories, a complete direct/indirect reachable TypedMap#set closure, complete 76-handler-set semantic-family inventory, exact entry/local reaching definitions, exact entity receiver and decoded-key bindings, structural helper/runtime/source-to-payload flows, exact Value kind/payload/final-operand/set-call chains, required absence, and handler-local normal-exit effect traces",
            "symbolic_call_boundary": "token helper outcomes are exact functions of the structurally bound SmartContract receiver, selector, argument, retained call-result wrapper, and Graph ethereum.call result; the imported host call result and which outcomes occurred at historic blocks are not asserted",
            "fail_closed_rule": "any parent-contract, artifact, initializer export, native start section, critical-global initializer or writer, handler, reachable setter, helper or shared runtime primitive, entry-local definition, entity receiver, decoded field key, Value kind, semantic payload source/local, final Value operand, exact map call, event index, early return, persistent effect, static profile, or required-absence drift leaves the scoped claims false",
            "host_boundary": "reachable helper bodies retain aggregate exact-body authority rather than a general protected-memory write proof; the proof reaches Graph host-effect invocation, while imported host memory behavior, Graph Node rollback, and other host behavior are not proved by retained WAT",
        },
        "provenance": {
            "base_commit": BASE_COMMIT,
            "base_commit_verification": "recorded review provenance; Git ancestry is outside the artifact verifier",
            "factory_effects_contract": {
                "path": EFFECTS_CONTRACT_PATH.as_posix(),
                "raw_sha256": EFFECTS_CONTRACT_SHA256,
                "contract_version": "uniswap-v3-factory-effects/v1",
            },
            "shared_wat_runtime": {
                "path": RUNTIME_SOURCE_PATH.as_posix(),
                "raw_sha256": runtime_sha256,
                "authority_boundary": "contract-I/O-free reusable structural algorithms; no Pool artifact or release gate is certified",
            },
            "wabt_version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-modern-factory-wasm>"],
        },
        "scope": {
            "factory_upstream_path_count": 18,
            "closed_before_this_supplement": 12,
            "newly_closed_complete_static_handler_paths": 2,
            "cumulative_closed_after_this_supplement": 14,
            "residual_after_this_supplement": 4,
            "newly_closed_path": "$.complete_static_handler_contract for modern-base and modern-mainnet",
            "residual_path": "$.complete_static_handler_contract for four legacy Factory mappings",
            "modern_mapping_count": 2,
            "modern_segment_count": 2,
            "stored_field_contract_count_per_mapping": 60,
            "written_field_count_per_mapping": 59,
            "required_absent_field_count_per_mapping": 1,
            "modern_segment_field_projection_count": 120,
            "v2_global_selected_field_count_before_and_after": 34,
            "v2_global_residual_conditional_field_count_before_and_after": 232,
            "reason_global_counts_do_not_move": "the same 60-field Factory contract remains unproved for all four legacy mappings",
        },
        "modern_factory_static_proofs": proofs,
        "truth_boundary": truth,
        "residuals": [
            "the four legacy complete-static Factory paths remain false, including their unsafe static-array holes and deployed totalSupply pointer behavior",
            "historic token-call outcomes and actual runtime population are not supplied",
            "retained WAT does not prove Graph Node transaction rollback after a later helper, import, or host trap",
            "complete Factory entity histories require later Pool and other handler contributions",
            "complete writer semantic diffs, integrated scheduling, runtime consumption, boundary continuity, oracle, logical/physical/PoI parity, backfill, and production gates remain false",
            "this bounded supplement completes no tracking-issue acceptance checkbox",
        ],
    }


def verify_contract(
    root: Path, contract: dict[str, Any] | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    expected = expected_contract(root, wasm2wat)
    committed = contract if contract is not None else load_json(root.resolve() / CONTRACT_PATH)
    require(
        committed == expected,
        "committed modern Factory static contract is not the deterministic retained-WAT projection",
    )
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
        contract = (
            write_contract(args.root, args.wasm2wat)
            if args.write
            else verify_contract(args.root, wasm2wat=args.wasm2wat)
        )
    except VerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"verified {contract['contract_version']}: two modern Factory static paths closed; "
        "Factory paths 14/18 closed and 4/18 residual"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
