#!/usr/bin/env python3
"""Verify the fail-closed Aerodrome Slipstream CL Base target baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


LOCK_PATH = Path("docs/provenance/aerodrome-slipstream-base-target.json")
PROFILE_PATH = Path("aerodrome-slipstream-base/layout-profile-v1.json")
BINDING_PATH = Path(
    "aerodrome-slipstream-base/"
    "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV.yaml"
)
QMA8_SCHEMA_PATH = Path(
    "uniswap-v3/graft-ancestry/v1/artifacts/"
    "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru"
)

EXPECTED_DEPLOYMENT = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV"
EXPECTED_SCHEMA = "QmTiEqVtfjTDY8DRkj17eLKSAyajHNz8r7Yg9cRgXwrWfF"
EXPECTED_MANIFEST_REPOSITORY = "https://github.com/Uniswap/uniswap-v3-subgraph"
EXPECTED_PROFILE_BYTES = 16938
EXPECTED_PROFILE_SHA256 = "a47737893c3d9703f458426581878a0ca41ca48e75632a205e38c762f055e6d1"
EXPECTED_QMA8_BYTES = 19034
EXPECTED_QMA8_SHA256 = "ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c"
EXPECTED_QMA8_LOGICAL = "6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d"
EXPECTED_TARGET_LOGICAL = "c072c3a609441de370bcb7340814b4e9dd9687043d7088f53a0dcb92ee8b23a0"

EXPECTED_ARTIFACTS: dict[str, dict[str, Any]] = {
    "deployment": {
        "cid": EXPECTED_DEPLOYMENT,
        "path": "aerodrome-slipstream-base/reference/deployment.yaml",
        "bytes": 5371,
        "sha256": "d93714e7ba268a91278f5c7c6a5b4ef71920d13b7e8d517f3542fb4a2edf6b20",
    },
    "schema": {
        "cid": EXPECTED_SCHEMA,
        "path": "aerodrome-slipstream-base/reference/schema.graphql",
        "bytes": 18598,
        "sha256": "09d7c40167fc27c3aa2de0ec003fe7b0b469e132943cc26dcd4db6064769d0e8",
    },
    "factory_abi": {
        "cid": "QmamyiWBuT1kyYy6r97DamQ7eowheMw7nfGZUFdAmaFRG8",
        "path": "aerodrome-slipstream-base/reference/abis/Factory.json",
        "bytes": 10875,
        "sha256": "7dac7fd7c4ff807498cb7dcbf503474d13b1207852bb8b2b3687a7e8cfb6d979",
    },
    "erc20_abi": {
        "cid": "QmXuTbDkNrN27VydxbS2huvKRk62PMgUTdPDWkxcr2w7j2",
        "path": "aerodrome-slipstream-base/reference/abis/ERC20.json",
        "bytes": 3684,
        "sha256": "4b83c6645aed2df5e4e9a1d11f372453fc052ac8575348c8c04a33ceacd0ae90",
    },
    "erc20_name_bytes_abi": {
        "cid": "QmQCP6Pdp1MqpwRv2qoPHuUTwZGy7Q3eDHg4w5kzwE9mBj",
        "path": "aerodrome-slipstream-base/reference/abis/ERC20NameBytes.json",
        "bytes": 268,
        "sha256": "b874c853ffa5309e4b7fbf4934c1efdb4fe31e1a65f7041e67f4a7f2258ffb77",
    },
    "erc20_symbol_bytes_abi": {
        "cid": "QmbHnhUFZa6qqqRyubUYhXntox1TCBxqryaBM1iNGqVJzT",
        "path": "aerodrome-slipstream-base/reference/abis/ERC20SymbolBytes.json",
        "bytes": 270,
        "sha256": "9ccb9b5d95394b2ffb4ced54cffa0c5ea282917f4eec36c121ce28c257965193",
    },
    "pool_abi": {
        "cid": "QmVszVJj4c73MuQGv5Bi9Kje5tpGijPCDXie7fXTqGAFi9",
        "path": "aerodrome-slipstream-base/reference/abis/Pool.json",
        "bytes": 25037,
        "sha256": "46588c2f4ad0b91f64e7b43b03190c5422d3f46f2759c53412a3f3279f816760",
    },
    "npm_abi": {
        "cid": "QmdAXZw3wWJx7uRuzBmNPqgV6hqE3Cx3ZBvXEVRoThdPDL",
        "path": "aerodrome-slipstream-base/reference/abis/NonfungiblePositionManager.json",
        "bytes": 26032,
        "sha256": "6109c87c3dfd051c5fa283e71463d29d4c31a40339223ea3015ea0bcdd602c00",
    },
    "factory_mapping_wasm": {
        "cid": "QmZQVsukQt6nXKctyy2WSMWN5grVXKph5fR7ahxS11Uebs",
        "path": "aerodrome-slipstream-base/reference/mappings/Factory.wasm",
        "bytes": 50419,
        "sha256": "0072f4d819db1fce30c4e2a926008ce2e7180157dd9e4e42ddf3416eb7d64d17",
        "exports": ["handlePoolCreated"],
    },
    "npm_mapping_wasm": {
        "cid": "QmcoeFHridxYBRFnrZ33v3PRAgvqunBfxe9gsCPhJQB4dy",
        "path": "aerodrome-slipstream-base/reference/mappings/NonfungiblePositionManager.wasm",
        "bytes": 49615,
        "sha256": "5547847305e52793ed505edb98cdfd542e97031d869d504d0de434548fa2c63e",
        "exports": [
            "handleIncreaseLiquidity",
            "handleDecreaseLiquidity",
            "handleCollect",
            "handleTransfer",
        ],
    },
    "pool_mapping_wasm": {
        "cid": "QmQgC18iXqZc5Jp78KZs6wNpk2oZvgbe9TeMQnH9K7eMah",
        "path": "aerodrome-slipstream-base/reference/mappings/Pool.wasm",
        "bytes": 77470,
        "sha256": "778944cb5de130d35dd76718a2642a338e5637d1d3d58d5b64d7cdf096ed8272",
        "exports": [
            "handleInitialize",
            "handleMint",
            "handleBurn",
            "handleSwap",
            "handleFlash",
        ],
    },
}

FALSE_GATES = {
    "eligibility_complete": False,
    "source_revision_pinned": False,
    "source_reproducible": False,
    "implementation_complete": False,
    "runtime_complete": False,
    "runtime_parity": False,
    "logical_parity": False,
    "history_complete": False,
    "physical_profile_complete": False,
    "physical_parity": False,
    "poi_parity": False,
    "backfill_ready": False,
    "production_ready": False,
    "readiness": False,
    "issue_86_complete": False,
}

EXPECTED_REQUIRED_CHANGES = [
    "resolve_exact_source_revision_or_produce_complete_retained_wasm_semantic_specification",
    "add_slipstream_factory_decoder_without_canonical_fee_argument",
    "resolve_tick_spacing_to_fee_semantics_and_pool_fee_tier_authority",
    "add_slipstream_npm_positions_int24_tick_spacing_adapter_and_four_handlers",
    "preserve_manifest_contract_call_inputs_for_npm_positions_ticks_and_fee_growth",
    "implement_token_version_and_missing_whitelist_pool_semantics",
    "preserve_flash_fee_growth_only_behavior_and_absent_flash_rows",
    "implement_all_twenty_mutable_entities_and_three_target_only_fields",
    "bind_base_addresses_start_blocks_pricing_constants_and_dynamic_pool_creation",
    "produce_target_specific_substreams_package_store_reducer_poi_and_temporal_writer",
    "capture_adversarial_factory_npm_pool_metadata_revert_and_flash_fixtures",
    "prove_graph_node_entity_value_order_failure_poi_vid_block_range_and_postgresql_parity",
]

EXPECTED_EMBEDDED_ADDRESSES = [
    "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
    "0x4200000000000000000000000000000000000006",
    "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631",
    "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248",
    "0x9663f2ca0454accad3e094448ea6f77443880454",
]

EXPECTED_SOURCE_SEARCH_SCOPE = {
    "observed_at": "2026-08-31",
    "public_code_search": [
        "deployment CID QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",
        "Factory mapping CID QmZQVsukQt6nXKctyy2WSMWN5grVXKph5fR7ahxS11Uebs",
        (
            "NonfungiblePositionManager mapping CID "
            "QmcoeFHridxYBRFnrZ33v3PRAgvqunBfxe9gsCPhJQB4dy"
        ),
        "Pool mapping CID QmQgC18iXqZc5Jp78KZs6wNpk2oZvgbe9TeMQnH9K7eMah",
        "unique helper name addMissingWhitelistedPools",
    ],
    "repository_history_inspected": "https://github.com/Uniswap/v3-subgraph",
    "result": "no_exact_deployed_slipstream_source_match",
}

EXPECTED_REMAINING_GATES = [
    (
        "Fresh stable-pod 24-hour and 72-hour fastest-healthy-copy forecasts must "
        "both exceed 28 days or be non-converging."
    ),
    (
        "Resolve the exact Slipstream source revision and build toolchain, or replace "
        "them with a complete independently reviewed retained-WASM behavior specification."
    ),
    (
        "Implement the target-specific decoder, call inputs, stores, reducer, PoI, "
        "temporal writer, package, and schema without promoting any parity gate."
    ),
    (
        "Prove canonical Base fixture, Graph Node differential, failure, save-order, "
        "PoI, VID, block-range, and PostgreSQL parity."
    ),
    (
        "Validate only on a disposable paused target; compute, load, Kubernetes "
        "mutation, allocation, activation, and production require separate authorization."
    ),
]


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def repository_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        fail(f"{label} must be a non-empty repository-relative path")
    candidate = (root / value).resolve()
    if root.resolve() not in candidate.parents:
        fail(f"{label} escapes the repository root")
    return candidate


def encode_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def base58btc(payload: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(payload, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    leading_zeroes = len(payload) - len(payload.lstrip(b"\0"))
    return "1" * leading_zeroes + encoded


def unixfs_file_cidv0(payload: bytes) -> str:
    if len(payload) > 262_144:
        fail("CID verifier only accepts a single default IPFS chunk")
    unixfs = b"\x08\x02\x12" + encode_varint(len(payload)) + payload
    unixfs += b"\x18" + encode_varint(len(payload))
    node = b"\x0a" + encode_varint(len(unixfs)) + unixfs
    return base58btc(b"\x12\x20" + hashlib.sha256(node).digest())


def cid_from_file(value: object) -> str:
    if not isinstance(value, dict) or set(value) != {"/"}:
        fail(f"unexpected IPFS file value: {value!r}")
    location = value["/"]
    if not isinstance(location, str) or not location.startswith("/ipfs/Qm"):
        fail(f"unexpected IPFS location: {location!r}")
    return location.removeprefix("/ipfs/")


def normalize_event(value: object) -> str:
    return re.sub(r"\s+", "", str(value))


def normalize_call(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_schema(path: Path) -> tuple[dict[str, dict[str, str]], set[str], set[str]]:
    entities: dict[str, dict[str, str]] = {}
    immutable: set[str] = set()
    explicit_mutable: set[str] = set()
    current: str | None = None
    declaration = re.compile(
        r"^type\s+([_A-Za-z][_0-9A-Za-z]*)\s+@entity\s*"
        r"(?:\(\s*immutable:\s*(true|false)\s*\))?\s*\{"
    )
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        match = declaration.match(line)
        if match:
            current = match.group(1)
            entities[current] = {}
            if match.group(2) == "true":
                immutable.add(current)
            elif match.group(2) == "false":
                explicit_mutable.add(current)
            continue
        if current and line == "}":
            current = None
            continue
        if current:
            field = re.match(
                r"^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)", line
            )
            if field:
                entities[current][field.group(1)] = field.group(2)
    return entities, immutable, explicit_mutable


def logical_hash(entities: dict[str, dict[str, str]]) -> str:
    canonical = json.dumps(entities, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode())


def verify_false_gates(value: object, label: str) -> None:
    if value != FALSE_GATES:
        fail(f"{label} must retain the complete false truth-gate inventory")


def verify_artifacts(root: Path, lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = lock.get("artifact_lock")
    if not isinstance(records, list):
        fail("artifact_lock must be a list")
    actual: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("role"), str):
            fail("artifact records require a string role")
        role = record["role"]
        if role in actual:
            fail(f"duplicate artifact role: {role}")
        actual[role] = record
    if set(actual) != set(EXPECTED_ARTIFACTS):
        fail("artifact role inventory drift")
    for role, expected in EXPECTED_ARTIFACTS.items():
        record = actual[role]
        if record != {"role": role, **expected}:
            fail(f"artifact metadata drift for {role}")
        artifact_path = repository_path(root, record["path"], f"{role} path")
        payload = artifact_path.read_bytes()
        if len(payload) != expected["bytes"] or sha256(payload) != expected["sha256"]:
            fail(f"artifact byte lock drift for {role}")
        if unixfs_file_cidv0(payload) != expected["cid"]:
            fail(f"artifact CIDv0 drift for {role}")
        if role.endswith("_abi"):
            parsed = json.loads(payload)
            if not isinstance(parsed, list):
                fail(f"ABI payload must be a list for {role}")
        if role.endswith("_mapping_wasm"):
            if not payload.startswith(b"\0asm\x01\0\0\0"):
                fail(f"mapping is not a WebAssembly v1 module for {role}")
            for export in expected["exports"]:
                if export.encode() not in payload:
                    fail(f"mapping export missing for {role}: {export}")
    return actual


def abi_inventory(mapping: dict[str, Any]) -> list[tuple[str, str]]:
    abis = mapping.get("abis")
    if not isinstance(abis, list):
        fail("mapping ABI inventory must be a list")
    return [(str(item.get("name")), cid_from_file(item.get("file"))) for item in abis]


def handler_inventory(mapping: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
    handlers = mapping.get("eventHandlers")
    if not isinstance(handlers, list):
        fail("mapping handler inventory must be a list")
    output = []
    for handler in handlers:
        calls = handler.get("calls", {})
        if not isinstance(calls, dict):
            fail("handler calls must be an object")
        output.append(
            (
                str(handler.get("handler")),
                normalize_event(handler.get("event")),
                {str(key): normalize_call(value) for key, value in calls.items()},
            )
        )
    return output


def verify_manifest(root: Path, artifacts: dict[str, dict[str, Any]]) -> None:
    manifest_path = repository_path(root, artifacts["deployment"]["path"], "manifest path")
    manifest = yaml.safe_load(manifest_path.read_text())
    if not isinstance(manifest, dict):
        fail("manifest must be an object")
    if (
        manifest.get("specVersion") != "1.2.0"
        or manifest.get("repository") != EXPECTED_MANIFEST_REPOSITORY
        or manifest.get("features") != ["nonFatalErrors", "grafting"]
        or "graft" in manifest
        or cid_from_file(manifest.get("schema", {}).get("file")) != EXPECTED_SCHEMA
    ):
        fail("manifest identity, feature, graft, or schema drift")

    sources = manifest.get("dataSources")
    templates = manifest.get("templates")
    if not isinstance(sources, list) or [item.get("name") for item in sources] != [
        "Factory",
        "NonfungiblePositionManager",
    ]:
        fail("manifest data-source order or inventory drift")
    if not isinstance(templates, list) or [item.get("name") for item in templates] != ["Pool"]:
        fail("manifest template order or inventory drift")

    factory_mapping = sources[0].get("mapping")
    if (
        sources[0].get("kind") != "ethereum/contract"
        or sources[0].get("network") != "base"
        or sources[0].get("source")
        != {
            "abi": "Factory",
            "address": "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
            "startBlock": 13843704,
        }
        or not isinstance(factory_mapping, dict)
        or cid_from_file(factory_mapping.get("file"))
        != EXPECTED_ARTIFACTS["factory_mapping_wasm"]["cid"]
        or factory_mapping.get("entities") != ["Pool", "Token"]
        or abi_inventory(factory_mapping)
        != [
            ("Factory", EXPECTED_ARTIFACTS["factory_abi"]["cid"]),
            ("ERC20", EXPECTED_ARTIFACTS["erc20_abi"]["cid"]),
            ("ERC20SymbolBytes", EXPECTED_ARTIFACTS["erc20_symbol_bytes_abi"]["cid"]),
            ("ERC20NameBytes", EXPECTED_ARTIFACTS["erc20_name_bytes_abi"]["cid"]),
            ("Pool", EXPECTED_ARTIFACTS["pool_abi"]["cid"]),
        ]
        or handler_inventory(factory_mapping)
        != [
            (
                "handlePoolCreated",
                "PoolCreated(indexedaddress,indexedaddress,indexedint24,address)",
                {},
            )
        ]
    ):
        fail("Factory source, ABI, mapping, or handler contract drift")

    npm_mapping = sources[1].get("mapping")
    npm_call = (
        "NonfungiblePositionManager[event.address].positions(event.params.tokenId)"
    )
    if (
        sources[1].get("kind") != "ethereum/contract"
        or sources[1].get("network") != "base"
        or sources[1].get("source")
        != {
            "abi": "NonfungiblePositionManager",
            "address": "0x827922686190790b37229fd06084350e74485b72",
            "startBlock": 13843719,
        }
        or not isinstance(npm_mapping, dict)
        or cid_from_file(npm_mapping.get("file"))
        != EXPECTED_ARTIFACTS["npm_mapping_wasm"]["cid"]
        or npm_mapping.get("entities") != ["Pool", "Token"]
        or abi_inventory(npm_mapping)
        != [
            ("NonfungiblePositionManager", EXPECTED_ARTIFACTS["npm_abi"]["cid"]),
            ("Pool", EXPECTED_ARTIFACTS["pool_abi"]["cid"]),
            ("Factory", EXPECTED_ARTIFACTS["factory_abi"]["cid"]),
            ("ERC20", EXPECTED_ARTIFACTS["erc20_abi"]["cid"]),
        ]
        or handler_inventory(npm_mapping)
        != [
            (
                "handleIncreaseLiquidity",
                "IncreaseLiquidity(indexeduint256,uint128,uint256,uint256)",
                {"positions": npm_call},
            ),
            (
                "handleDecreaseLiquidity",
                "DecreaseLiquidity(indexeduint256,uint128,uint256,uint256)",
                {"positions": npm_call},
            ),
            (
                "handleCollect",
                "Collect(indexeduint256,address,uint256,uint256)",
                {"positions": npm_call},
            ),
            (
                "handleTransfer",
                "Transfer(indexedaddress,indexedaddress,indexeduint256)",
                {"positions": npm_call},
            ),
        ]
    ):
        fail("NPM source, ABI, mapping, call-input, or handler contract drift")

    pool_mapping = templates[0].get("mapping")
    if (
        templates[0].get("kind") != "ethereum/contract"
        or templates[0].get("network") != "base"
        or templates[0].get("source") != {"abi": "Pool"}
        or not isinstance(pool_mapping, dict)
        or cid_from_file(pool_mapping.get("file"))
        != EXPECTED_ARTIFACTS["pool_mapping_wasm"]["cid"]
        or pool_mapping.get("entities") != ["Pool", "Token"]
        or abi_inventory(pool_mapping)
        != [
            ("Pool", EXPECTED_ARTIFACTS["pool_abi"]["cid"]),
            ("Factory", EXPECTED_ARTIFACTS["factory_abi"]["cid"]),
            ("ERC20", EXPECTED_ARTIFACTS["erc20_abi"]["cid"]),
        ]
        or handler_inventory(pool_mapping)
        != [
            ("handleInitialize", "Initialize(uint160,int24)", {}),
            (
                "handleSwap",
                "Swap(indexedaddress,indexedaddress,int256,int256,uint160,uint128,int24)",
                {
                    "feeGrowthGlobal0X128": "Pool[event.address].feeGrowthGlobal0X128()",
                    "feeGrowthGlobal1X128": "Pool[event.address].feeGrowthGlobal1X128()",
                },
            ),
            (
                "handleMint",
                "Mint(address,indexedaddress,indexedint24,indexedint24,uint128,uint256,uint256)",
                {
                    "poolTickLower": "Pool[event.address].ticks(event.params.tickLower)",
                    "poolTickUpper": "Pool[event.address].ticks(event.params.tickUpper)",
                },
            ),
            (
                "handleBurn",
                "Burn(indexedaddress,indexedint24,indexedint24,uint128,uint256,uint256)",
                {
                    "poolTickLower": "Pool[event.address].ticks(event.params.tickLower)",
                    "poolTickUpper": "Pool[event.address].ticks(event.params.tickUpper)",
                },
            ),
            (
                "handleFlash",
                "Flash(indexedaddress,indexedaddress,uint256,uint256,uint256,uint256)",
                {
                    "feeGrowthGlobal0X128": "Pool[event.address].feeGrowthGlobal0X128()",
                    "feeGrowthGlobal1X128": "Pool[event.address].feeGrowthGlobal1X128()",
                },
            ),
        ]
    ):
        fail("Pool template, ABI, mapping, call-input, or handler contract drift")
    for mapping in (factory_mapping, npm_mapping, pool_mapping):
        if (
            mapping.get("kind") != "ethereum/events"
            or mapping.get("apiVersion") != "0.0.7"
            or mapping.get("language") != "wasm/assemblyscript"
        ):
            fail("mapping runtime contract drift")


def abi_items(root: Path, artifacts: dict[str, dict[str, Any]], role: str) -> list[dict[str, Any]]:
    value = load_json(repository_path(root, artifacts[role]["path"], f"{role} path"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        fail(f"invalid ABI inventory for {role}")
    return value


def event_shape(items: list[dict[str, Any]], name: str) -> list[tuple[str, str, bool]]:
    matches = [item for item in items if item.get("type") == "event" and item.get("name") == name]
    if len(matches) != 1:
        fail(f"expected exactly one ABI event {name}")
    return [
        (str(item.get("name")), str(item.get("type")), item.get("indexed") is True)
        for item in matches[0].get("inputs", [])
    ]


def function_shapes(
    items: list[dict[str, Any]], name: str
) -> list[tuple[list[str], list[str], str]]:
    output = []
    for item in items:
        if item.get("type") == "function" and item.get("name") == name:
            output.append(
                (
                    [str(value.get("type")) for value in item.get("inputs", [])],
                    [str(value.get("type")) for value in item.get("outputs", [])],
                    str(item.get("stateMutability")),
                )
            )
    return output


def verify_abi_contracts(root: Path, artifacts: dict[str, dict[str, Any]]) -> None:
    factory = abi_items(root, artifacts, "factory_abi")
    npm = abi_items(root, artifacts, "npm_abi")
    pool = abi_items(root, artifacts, "pool_abi")
    if event_shape(factory, "PoolCreated") != [
        ("token0", "address", True),
        ("token1", "address", True),
        ("tickSpacing", "int24", True),
        ("pool", "address", False),
    ]:
        fail("Slipstream Factory PoolCreated ABI drift")
    if function_shapes(factory, "getPool") != [
        (["address", "address", "int24"], ["address"], "view")
    ]:
        fail("Slipstream Factory getPool ABI drift")
    for name, shape in {
        "IncreaseLiquidity": [
            ("tokenId", "uint256", True),
            ("liquidity", "uint128", False),
            ("amount0", "uint256", False),
            ("amount1", "uint256", False),
        ],
        "DecreaseLiquidity": [
            ("tokenId", "uint256", True),
            ("liquidity", "uint128", False),
            ("amount0", "uint256", False),
            ("amount1", "uint256", False),
        ],
        "Collect": [
            ("tokenId", "uint256", True),
            ("recipient", "address", False),
            ("amount0", "uint256", False),
            ("amount1", "uint256", False),
        ],
        "Transfer": [
            ("from", "address", True),
            ("to", "address", True),
            ("tokenId", "uint256", True),
        ],
    }.items():
        if event_shape(npm, name) != shape:
            fail(f"Slipstream NPM {name} ABI drift")
    if function_shapes(npm, "positions") != [
        (
            ["uint256"],
            [
                "uint96",
                "address",
                "address",
                "address",
                "int24",
                "int24",
                "int24",
                "uint128",
                "uint256",
                "uint256",
                "uint128",
                "uint128",
            ],
            "view",
        )
    ]:
        fail("Slipstream NPM positions ABI drift")
    expected_pool_events = {
        "Initialize": [("sqrtPriceX96", "uint160", False), ("tick", "int24", False)],
        "Swap": [
            ("sender", "address", True),
            ("recipient", "address", True),
            ("amount0", "int256", False),
            ("amount1", "int256", False),
            ("sqrtPriceX96", "uint160", False),
            ("liquidity", "uint128", False),
            ("tick", "int24", False),
        ],
        "Flash": [
            ("sender", "address", True),
            ("recipient", "address", True),
            ("amount0", "uint256", False),
            ("amount1", "uint256", False),
            ("paid0", "uint256", False),
            ("paid1", "uint256", False),
        ],
    }
    for name, shape in expected_pool_events.items():
        if event_shape(pool, name) != shape:
            fail(f"Slipstream Pool {name} ABI drift")
    for name, shape in {
        "gauge": [([], ["address"], "view")],
        "rewardGrowthGlobalX128": [([], ["uint256"], "view")],
        "stakedLiquidity": [([], ["uint128"], "view")],
        "unstakedFee": [([], ["uint24"], "view")],
    }.items():
        if function_shapes(pool, name) != shape:
            fail(f"Slipstream-specific Pool marker drift: {name}")


def verify_schema(root: Path, artifacts: dict[str, dict[str, Any]], lock: dict[str, Any]) -> None:
    target_path = repository_path(root, artifacts["schema"]["path"], "target schema path")
    qma8_path = repository_path(root, str(QMA8_SCHEMA_PATH), "Qma8 schema path")
    qma8_payload = qma8_path.read_bytes()
    if len(qma8_payload) != EXPECTED_QMA8_BYTES or sha256(qma8_payload) != EXPECTED_QMA8_SHA256:
        fail("retained Qma8 schema byte lock drift")
    target, target_immutable, target_explicit_mutable = parse_schema(target_path)
    qma8, qma8_immutable, qma8_explicit_mutable = parse_schema(qma8_path)
    if (
        len(target) != 20
        or sum(len(fields) for fields in target.values()) != 302
        or logical_hash(target) != EXPECTED_TARGET_LOGICAL
        or target_immutable
        or target_explicit_mutable
    ):
        fail("Slipstream 20-entity/302-field all-mutable schema drift")
    if (
        len(qma8) != 20
        or sum(len(fields) for fields in qma8.values()) != 299
        or logical_hash(qma8) != EXPECTED_QMA8_LOGICAL
        or qma8_immutable
        or qma8_explicit_mutable
    ):
        fail("retained Qma8 logical schema drift")
    if set(target) != set(qma8):
        fail("Slipstream/Qma8 entity inventory drift")
    differences: dict[str, dict[str, str]] = {}
    for entity in target:
        missing = set(qma8[entity]) - set(target[entity])
        changed = {
            field
            for field in set(qma8[entity]) & set(target[entity])
            if qma8[entity][field] != target[entity][field]
        }
        if missing or changed:
            fail(f"unexpected Slipstream/Qma8 field or type difference in {entity}")
        added = {
            field: value
            for field, value in target[entity].items()
            if field not in qma8[entity]
        }
        if added:
            differences[entity] = added
    if differences != {
        "Token": {"version": "Int"},
        "Position": {
            "collectedToken0": "BigDecimal!",
            "collectedToken1": "BigDecimal!",
        },
    }:
        fail("Slipstream/Qma8 exact three-field gap drift")
    contract = lock.get("logical_contract")
    if contract != {
        "entity_count": 20,
        "field_count": 302,
        "logical_sha256": EXPECTED_TARGET_LOGICAL,
        "all_entities_mutable": True,
        "immutable_entities": [],
        "retained_qma8": {
            "cid": "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru",
            "path": str(QMA8_SCHEMA_PATH),
            "bytes": EXPECTED_QMA8_BYTES,
            "sha256": EXPECTED_QMA8_SHA256,
            "entity_count": 20,
            "field_count": 299,
            "logical_sha256": EXPECTED_QMA8_LOGICAL,
        },
        "bidirectional_gap": {
            "missing_entities": [],
            "extra_entities": [],
            "missing_fields": [],
            "extra_fields": [
                "Position.collectedToken0:BigDecimal!",
                "Position.collectedToken1:BigDecimal!",
                "Token.version:Int",
            ],
            "type_differences": [],
            "mutability_differences": [],
        },
    }:
        fail("provenance logical contract or bidirectional schema gap drift")


def verify_wasm_static_evidence(
    root: Path, artifacts: dict[str, dict[str, Any]], profile: dict[str, Any]
) -> None:
    wasm = {
        "Factory": repository_path(
            root, artifacts["factory_mapping_wasm"]["path"], "Factory WASM path"
        ).read_bytes(),
        "NonfungiblePositionManager": repository_path(
            root, artifacts["npm_mapping_wasm"]["path"], "NPM WASM path"
        ).read_bytes(),
        "Pool": repository_path(
            root, artifacts["pool_mapping_wasm"]["path"], "Pool WASM path"
        ).read_bytes(),
    }
    evidence = profile.get("retained_wasm_static_behavior")
    if not isinstance(evidence, dict) or evidence.get("proof_scope") != (
        "static_presence_and_binding_only_not_complete_values_order_branches_failure_or_persistence"
    ):
        fail("retained-WASM proof boundary drift")
    for component, role in {
        "Factory": "factory_mapping_wasm",
        "NonfungiblePositionManager": "npm_mapping_wasm",
        "Pool": "pool_mapping_wasm",
    }.items():
        record = evidence.get(component)
        if not isinstance(record, dict) or record.get("exports") != EXPECTED_ARTIFACTS[role]["exports"]:
            fail(f"profile WASM export inventory drift for {component}")
        for helper in record.get("named_target_helpers", []):
            if not isinstance(helper, str) or helper.encode() not in wasm[component]:
                fail(f"retained WASM named helper missing for {component}: {helper}")
        for capability in record.get("host_capabilities", []):
            if not isinstance(capability, str) or capability.encode() not in wasm[component]:
                fail(f"retained WASM host capability missing for {component}: {capability}")
    if evidence.get("embedded_address_constants") != EXPECTED_EMBEDDED_ADDRESSES:
        fail("embedded address constant inventory drift")
    combined = b"".join(wasm.values())
    for value in EXPECTED_EMBEDDED_ADDRESSES + ["0.01", "1.0001", "1000000"]:
        if value.encode("utf-16le") not in combined:
            fail(f"retained WASM embedded constant missing: {value}")
    flash_observation = evidence.get("Pool", {}).get("flash_static_observation")
    if flash_observation != (
        "loads Pool, calls feeGrowthGlobal0X128 and feeGrowthGlobal1X128, sets both Pool "
        "fields, saves Pool; no Flash constructor or Flash save is present"
    ):
        fail("bounded Flash static observation drift")


def verify_profile(root: Path, lock: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> None:
    profile_payload = repository_path(root, str(PROFILE_PATH), "profile path").read_bytes()
    if len(profile_payload) != EXPECTED_PROFILE_BYTES or sha256(profile_payload) != EXPECTED_PROFILE_SHA256:
        fail("machine-readable layout profile digest drift")
    if lock.get("layout_profile") != {
        "path": str(PROFILE_PATH),
        "bytes": EXPECTED_PROFILE_BYTES,
        "sha256": EXPECTED_PROFILE_SHA256,
    }:
        fail("layout profile provenance lock drift")
    profile = json.loads(profile_payload)
    if (
        profile.get("format_version") != 1
        or profile.get("profile_id") != "aerodrome-slipstream-base-QmasYjyp"
        or profile.get("status") != "immutable_target_and_static_behavior_profile_only"
        or profile.get("family") != "aerodrome-slipstream-base"
        or profile.get("protocol") != "aerodrome-slipstream-cl"
        or profile.get("chain") != "base"
        or profile.get("implementation_status") != "not_started"
        or profile.get("eligibility_decision") != "indeterminate_no_fresh_evidence"
    ):
        fail("layout profile identity or status drift")
    deployment = profile.get("deployment")
    if deployment != {
        "cid": EXPECTED_DEPLOYMENT,
        "spec_version": "1.2.0",
        "mapping_api_version": "0.0.7",
        "features": ["nonFatalErrors", "grafting"],
        "graft": None,
        "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
        "manifest_repository_is_protocol_identity": False,
    }:
        fail("profile deployment or metadata-lineage boundary drift")
    verify_false_gates(profile.get("truth_gates"), "profile truth_gates")
    if profile.get("required_target_changes") != EXPECTED_REQUIRED_CHANGES:
        fail("complete Slipstream implementation-gap inventory drift")
    if profile.get("remaining_gates") != EXPECTED_REMAINING_GATES:
        fail("Slipstream remaining-gate inventory drift")
    source = profile.get("source_provenance")
    if not isinstance(source, dict) or source != {
        "status": "unresolved_exact_revision_and_toolchain",
        "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
        "search_scope": EXPECTED_SOURCE_SEARCH_SCOPE,
        "exact_repository": None,
        "exact_commit": None,
        "exact_tree": None,
        "exact_toolchain": None,
        "byte_reproduction": False,
        "reason": (
            "No public revision containing the deployed Slipstream Factory/NPM/Pool "
            "modifications was found; manifest metadata alone is insufficient authority."
        ),
    }:
        fail("profile unresolved-source boundary drift")
    prior_art = profile.get("public_prior_art_assessment")
    if (
        not isinstance(prior_art, dict)
        or prior_art.get("drop_in_package_safe") is not False
        or prior_art.get("aerodrome_module", {}).get("slipstream_factory_compatible") is not False
        or prior_art.get("uniswap_v3_module", {}).get("slipstream_factory_compatible") is not False
        or prior_art.get("uniswap_v3_module", {}).get("npm_handlers_present") is not False
        or prior_art.get("uniswap_v3_module", {}).get("graph_entity_writer") is not False
    ):
        fail("public prior-art refusal boundary drift")
    verify_wasm_static_evidence(root, artifacts, profile)


def verify_source_boundary(lock: dict[str, Any]) -> None:
    source = lock.get("source_provenance")
    if source != {
        "status": "unresolved_exact_revision_and_toolchain",
        "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
        "manifest_repository_is_exact_source_authority": False,
        "search_scope": EXPECTED_SOURCE_SEARCH_SCOPE,
        "exact_repository": None,
        "exact_commit": None,
        "exact_tree": None,
        "exact_parent": None,
        "exact_toolchain": None,
        "byte_reproduction": False,
        "reproduction_attempted": False,
        "blocker": (
            "The deployed IPFS closure does not name a source revision, and no public "
            "revision containing the exact Slipstream Factory/NPM/Pool modifications "
            "was identified."
        ),
        "public_lineage_probe": {
            "repository": "https://github.com/Uniswap/v3-subgraph",
            "probed_head_commit": "b4a0e8d34b8238482cadd3929ae88d3426a7067b",
            "probed_head_tree": "6b32ebf65ca9fafc5fb3c04e3aa5247f1bdb6e21",
            "nearest_schema_only_commit": "c63cb398075b1bb6d4acf9876f3561afdfd18d4e",
            "nearest_schema_only_tree": "7be31c24df808f076d49ec7a03547bb8eb6db523",
            "nearest_schema_only_relationship": (
                "Its 20-entity/299-field logical schema matches retained Qma8, but it "
                "lacks the three Slipstream target fields and is not evidence of the "
                "deployed fork or build."
            ),
            "exact_deployment_cid_search_match": False,
            "exact_mapping_cid_search_match": False,
            "unique_add_missing_whitelisted_pools_source_match": False,
        },
    }:
        fail("unsupported source revision, toolchain, or reproduction promotion")


def verify_binding(root: Path) -> None:
    binding = yaml.safe_load(repository_path(root, str(BINDING_PATH), "binding path").read_text())
    if not isinstance(binding, dict):
        fail("target binding must be an object")
    if set(binding) != {
        "deployment",
        "family",
        "display_name",
        "schema",
        "chain",
        "milestone",
        "market_snapshot",
        "target_reference",
        "truth_gates",
        "eligibility",
    }:
        fail("target binding top-level inventory drift")
    if (
        binding.get("deployment") != EXPECTED_DEPLOYMENT
        or binding.get("family") != "aerodrome-slipstream-base"
        or binding.get("display_name") != "Aerodrome Slipstream CL Base"
        or binding.get("schema") != EXPECTED_SCHEMA
        or binding.get("chain") != "base"
        or binding.get("milestone") != "M7"
        or binding.get("target_reference")
        != {
            "provenance": str(LOCK_PATH),
            "deployment_manifest": EXPECTED_ARTIFACTS["deployment"]["path"],
            "status": "immutable_target_pinned_source_revision_unresolved",
        }
        or binding.get("market_snapshot")
        != {
            "measured_at": "2026-08-31T17:20:00Z",
            "queries_24h": 962722,
            "query_fees_grt_24h": "1154.657",
            "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
        }
    ):
        fail("target binding identity, M7, market snapshot, or source status drift")
    verify_false_gates(binding.get("truth_gates"), "binding truth_gates")
    if binding.get("eligibility") != {
        "policy": "graph-node-net-catchup-v1",
        "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
        "latest": {
            "decision": "indeterminate",
            "reason": "no_fresh_evidence",
            "measured_at": None,
            "evidence": None,
            "sha256": None,
        },
    }:
        fail("target binding eligibility must remain fail-closed without fresh evidence")


def verify(root: Path, lock_path: Path) -> None:
    if lock_path != LOCK_PATH:
        fail("Aerodrome Slipstream provenance must remain under docs/provenance")
    lock = load_json(repository_path(root, str(lock_path), "provenance path"))
    if not isinstance(lock, dict) or lock.get("format_version") != 1:
        fail("unsupported Aerodrome Slipstream target lock")
    if set(lock) != {
        "format_version",
        "family",
        "protocol",
        "implementation_status",
        "eligibility_decision",
        "deployment",
        "artifact_lock",
        "protocol_identity",
        "source_provenance",
        "logical_contract",
        "layout_profile",
        "external_prior_art",
        "kubernetes_evidence",
        "truth_gates",
        "remaining_gates",
    }:
        fail("provenance top-level inventory drift")
    if (
        lock.get("family") != "aerodrome-slipstream-base"
        or lock.get("protocol") != "aerodrome-slipstream-cl"
        or lock.get("implementation_status")
        != "immutable_target_and_static_behavior_baseline_only"
        or lock.get("eligibility_decision") != "indeterminate_no_fresh_evidence"
        or lock.get("remaining_gates") != EXPECTED_REMAINING_GATES
    ):
        fail("baseline identity, status, eligibility, or remaining-gate drift")
    verify_false_gates(lock.get("truth_gates"), "provenance truth_gates")
    if lock.get("deployment") != {
        "cid": EXPECTED_DEPLOYMENT,
        "chain": "base",
        "spec_version": "1.2.0",
        "mapping_api_version": "0.0.7",
        "manifest_repository_metadata": EXPECTED_MANIFEST_REPOSITORY,
        "manifest_repository_is_protocol_identity": False,
        "features": ["nonFatalErrors", "grafting"],
        "concrete_graft": None,
        "data_sources": [
            {
                "kind": "data_source",
                "name": "Factory",
                "address": "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
                "start_block": 13843704,
                "mapping_cid": EXPECTED_ARTIFACTS["factory_mapping_wasm"]["cid"],
            },
            {
                "kind": "data_source",
                "name": "NonfungiblePositionManager",
                "address": "0x827922686190790b37229fd06084350e74485b72",
                "start_block": 13843719,
                "mapping_cid": EXPECTED_ARTIFACTS["npm_mapping_wasm"]["cid"],
            },
            {
                "kind": "template",
                "name": "Pool",
                "address": None,
                "start_block": None,
                "mapping_cid": EXPECTED_ARTIFACTS["pool_mapping_wasm"]["cid"],
            },
        ],
    }:
        fail("provenance deployment or metadata-lineage boundary drift")
    if lock.get("protocol_identity") != {
        "authority": "deployed_addresses_manifest_event_signatures_and_abi_shape",
        "classification": "aerodrome_slipstream_cl_base_not_canonical_uniswap_v3",
        "factory_pool_created": (
            "PoolCreated(indexed address,indexed address,indexed int24,address)"
        ),
        "canonical_v3_pool_created": (
            "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)"
        ),
        "pool_abi_specific_markers": [
            "gauge():(address)",
            "rewardGrowthGlobalX128():(uint256)",
            "stakedLiquidity():(uint128)",
            "unstakedFee():(uint24)",
        ],
    }:
        fail("provenance protocol identity drift")
    if lock.get("external_prior_art") != {
        "repository": "https://github.com/pinax-network/substreams-evm",
        "revision": "970a665e15619de8ad7f686bd89412a1030d46dc",
        "tree": "eac7466daba7f89a8c3b2e4742fcf24a155a2c24",
        "aerodrome_module": (
            "Solidly V2 event extractor; wrong PoolCreated ABI and no Graph entity writer"
        ),
        "uniswap_v3_module": (
            "Canonical V3 event extractor; wrong Factory ABI, no NPM handlers/call "
            "inputs, and no Graph entity writer"
        ),
        "drop_in_package_safe": False,
    }:
        fail("provenance public prior-art assessment drift")
    if lock.get("kubernetes_evidence") != {
        "repository": "https://github.com/pinax-network/k8s-subgraphs",
        "revision": "272b5babcc2717682e7becd7e3374b054063ee93",
        "tree": "f3b343d9123adb3204d5a565dabfea414b9cfd96",
        "path": "core/kan/graph-node-aerodrome.yaml",
        "scope": "read_only_identity_and_current_placement_evidence_only",
        "mutated": False,
    }:
        fail("provenance Kubernetes evidence boundary drift")
    artifacts = verify_artifacts(root, lock)
    verify_manifest(root, artifacts)
    verify_abi_contracts(root, artifacts)
    verify_schema(root, artifacts, lock)
    verify_profile(root, lock, artifacts)
    verify_source_boundary(lock)
    verify_binding(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    args = parser.parse_args()
    try:
        verify(args.root.resolve(), args.lock)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"Aerodrome Slipstream Base target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified 11 CIDv0 artifacts, exact Base manifest/ABIs/handlers/call inputs, "
        "20-entity/302-field Qma8 delta, retained-WASM behavior boundary, bounded "
        "unresolved-source provenance, and complete false M7 truth gates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
