#!/usr/bin/env python3
"""Verify the immutable Exchange V3 BSC target and exact-source contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml


LOCK_PATH = Path("docs/provenance/exchange-v3-bsc-target.json")
PROFILE_PATH = Path("exchange-v3-bsc/layout-profile-v1.json")
BINDING_PATH = Path(
    "exchange-v3-bsc/"
    "QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn.yaml"
)
EXPECTED_DEPLOYMENT = "QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn"
EXPECTED_SCHEMA = "QmP9xqULGJzQE7SFKyzkgD8LEkjoy1aChCJnbNkCT4VDRi"
EXPECTED_SOURCE_COMMIT = "1da7ba61abb26633ff819ce8cdfe945be8770a92"
EXPECTED_SOURCE_TREE = "a2a113c9eedd7ed0e6fdcaea275153233223c95d"
EXPECTED_SOURCE_PARENT = "e2019f716f4310f4ce28addc4439980804d9e413"
EXPECTED_PROFILE_BYTES = 10417
EXPECTED_PROFILE_SHA256 = "8a5193a2eb5c4e938aed0faed4d829589c1b1e5bc4a0549d5efd7c41e4f96b16"

EXPECTED_PROFILE_HANDLERS = {
    "Factory": [
        (
            "handlePoolCreated",
            "PoolCreated(address,address,uint24,int24,address)",
            "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
        )
    ],
    "NonfungiblePositionManager": [
        (
            "handleIncreaseLiquidity",
            "IncreaseLiquidity(uint256,uint128,uint256,uint256)",
            "0x3067048beee31b25b2f1681f88dac838c8bba36af25bfb2b7cf7473a5847e35f",
        ),
        (
            "handleDecreaseLiquidity",
            "DecreaseLiquidity(uint256,uint128,uint256,uint256)",
            "0x26f6a048ee9138f2c0ce266f322cb99228e8d619ae2bff30c67f8dcf9d2377b4",
        ),
        (
            "handleCollect",
            "Collect(uint256,address,uint256,uint256)",
            "0x40d0efd1a53d60ecbf40971b9daf7dc90178c3aadc7aab1765632738fa8b8f01",
        ),
        (
            "handleTransfer",
            "Transfer(address,address,uint256)",
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
        ),
    ],
    "Pool": [
        (
            "handleInitialize",
            "Initialize(uint160,int24)",
            "0x98636036cb66a9c19a37435efc1e90142190214e8abeb821bdba3f2990dd4c95",
        ),
        (
            "handleSwap",
            "Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)",
            "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83",
        ),
        (
            "handleMint",
            "Mint(address,address,int24,int24,uint128,uint256,uint256)",
            "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde",
        ),
        (
            "handleBurn",
            "Burn(address,int24,int24,uint128,uint256,uint256)",
            "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c",
        ),
        (
            "handleFlash",
            "Flash(address,address,uint256,uint256,uint256,uint256)",
            "0xbdbdb71d7860376ba52b25a5028beea23581364a40522f6bcfb86bb1f2dca633",
        ),
        (
            "handleCollect",
            "Collect(address,address,int24,int24,uint128,uint128)",
            "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0",
        ),
        (
            "handleCollectProtocol",
            "CollectProtocol(address,address,uint128,uint128)",
            "0x596b573906218d3411850b26a6b437d6c4522fdb43d2d2386263f86d50b8b151",
        ),
    ],
}

EXPECTED_REQUIRED_CHANGES = [
    "profile_driven_legacy_spec_0_0_2_physical_schema_and_metadata_support",
    "bsc_factory_position_manager_and_dynamic_pool_component_routing",
    "pancake_swap_decoder_with_two_protocol_fee_amounts",
    "packed_fee_protocol_defaults_and_collect_protocol_semantics",
    "all_mutable_twenty_entity_layout_and_pancake_day_aggregate",
    "protocol_fee_fields_aggregates_and_source_compatibility_quirks",
    "bsc_pricing_stable_pool_whitelist_and_minimum_liquidity_configuration",
    "target_specific_packages_module_hashes_and_initial_blocks",
    "bsc_canonical_event_metadata_and_reducer_fixtures",
    "exact_graph_node_schema_poi_vid_and_postgresql_parity_certification",
]


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                fail(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    with path.open() as handle:
        return json.load(handle, object_pairs_hook=reject_duplicate_keys)


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
    # Every locked object fits in one default IPFS chunk. Build the canonical
    # UnixFS File protobuf in a link-free DAG-PB node and then its CIDv0.
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


def verify_artifacts(root: Path, lock: dict[str, object]) -> dict[str, dict[str, object]]:
    records = lock.get("artifact_lock")
    if not isinstance(records, list):
        fail("artifact_lock must be a list")

    by_role: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            fail("artifact record must be an object")
        role = record.get("role")
        cid = record.get("cid")
        if not isinstance(role, str) or role in by_role:
            fail(f"duplicate or invalid artifact role: {role!r}")
        if not isinstance(cid, str) or not cid.startswith("Qm"):
            fail(f"invalid CID for {role}: {cid!r}")
        by_role[role] = record

        vendored_path = record.get("vendored_path")
        if not isinstance(vendored_path, str):
            fail(f"invalid vendored path for {role}")
        path = (root / vendored_path).resolve()
        if root.resolve() not in path.parents:
            fail(f"vendored path escapes repository root for {role}")
        payload = path.read_bytes()
        if len(payload) != record.get("source_bytes"):
            fail(f"vendored byte count drift for {role}")
        if sha256(payload) != record.get("source_sha256"):
            fail(f"vendored digest drift for {role}")
        if unixfs_file_cidv0(payload) != cid:
            fail(f"vendored CIDv0 drift for {role}")
        if role.endswith("_abi"):
            json.loads(payload)
        if role.endswith("_mapping_wasm"):
            exports = record.get("exports")
            if not payload.startswith(b"\0asm\x01\0\0\0"):
                fail(f"vendored mapping is not WebAssembly v1 for {role}")
            if not isinstance(exports, list) or not exports:
                fail(f"mapping export lock missing for {role}")
            if any(not isinstance(name, str) or name.encode() not in payload for name in exports):
                fail(f"vendored mapping is missing a locked handler export for {role}")

    expected_roles = {
        "deployment",
        "schema",
        "factory_abi",
        "erc20_abi",
        "erc20_symbol_bytes_abi",
        "erc20_name_bytes_abi",
        "pool_abi",
        "position_manager_abi",
        "factory_mapping_wasm",
        "position_manager_mapping_wasm",
        "pool_mapping_wasm",
    }
    if set(by_role) != expected_roles:
        fail(f"artifact roles drift: {sorted(set(by_role) ^ expected_roles)}")
    expected_exports = {
        "factory_mapping_wasm": ["handlePoolCreated"],
        "position_manager_mapping_wasm": [
            "handleIncreaseLiquidity",
            "handleDecreaseLiquidity",
            "handleCollect",
            "handleTransfer",
        ],
        "pool_mapping_wasm": [
            "handleInitialize",
            "handleSwap",
            "handleMint",
            "handleBurn",
            "handleFlash",
            "handleCollect",
            "handleCollectProtocol",
        ],
    }
    for role, exports in expected_exports.items():
        if by_role[role].get("exports") != exports:
            fail(f"mapping export inventory drift for {role}")
    if by_role["deployment"]["cid"] != EXPECTED_DEPLOYMENT:
        fail("deployment CID lock drift")
    if by_role["schema"]["cid"] != EXPECTED_SCHEMA:
        fail("schema CID lock drift")
    return by_role


def normalize_event(event: str) -> str:
    return re.sub(r"\s+", "", event)


def abi_contract(mapping: dict[str, object]) -> list[tuple[str, str]]:
    entries = mapping.get("abis")
    if not isinstance(entries, list):
        fail("mapping ABI contract must be a list")
    return [(str(entry.get("name")), cid_from_file(entry.get("file"))) for entry in entries]


def verify_mapping_common(mapping: dict[str, object], expected_cid: str) -> None:
    if mapping.get("apiVersion") != "0.0.4":
        fail("mapping apiVersion drift")
    if mapping.get("kind") != "ethereum/events" or mapping.get("language") != "wasm/assemblyscript":
        fail("mapping runtime shape drift")
    if mapping.get("entities") != ["Pool", "Token"]:
        fail("mapping entity declaration drift")
    if cid_from_file(mapping.get("file")) != expected_cid:
        fail("mapping CID drift")


def verify_handlers(
    mapping: dict[str, object], expected: list[tuple[str, str]], component: str
) -> None:
    handlers = mapping.get("eventHandlers")
    if not isinstance(handlers, list):
        fail(f"{component} handlers must be a list")
    actual = [
        (str(entry.get("handler")), normalize_event(str(entry.get("event", ""))))
        for entry in handlers
    ]
    normalized_expected = [(handler, normalize_event(event)) for handler, event in expected]
    if actual != normalized_expected:
        fail(f"{component} handler order or signature drift")


def verify_manifest(
    root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]
) -> None:
    manifest = yaml.safe_load(
        (root / str(artifacts["deployment"]["vendored_path"])).read_text()
    )
    deployment = lock["deployment"]
    if manifest.get("specVersion") != "0.0.2":
        fail("manifest specVersion drift")
    if manifest.get("repository") != "https://github.com/pancakeswap/pancake-subgraph":
        fail("manifest repository drift")
    if manifest.get("features") != ["nonFatalErrors"] or "graft" in manifest:
        fail("manifest feature/graft contract drift")
    if cid_from_file(manifest["schema"]["file"]) != EXPECTED_SCHEMA:
        fail("manifest schema CID drift")

    data_sources = manifest.get("dataSources")
    templates = manifest.get("templates")
    if not isinstance(data_sources, list) or len(data_sources) != 2:
        fail("expected Factory and NonfungiblePositionManager data sources")
    if not isinstance(templates, list) or len(templates) != 1:
        fail("expected exactly one Pool template")

    factory = data_sources[0]
    factory_mapping = factory["mapping"]
    if (
        factory.get("kind") != "ethereum/contract"
        or factory.get("name") != "Factory"
        or factory.get("network") != "bsc"
        or factory.get("source")
        != {
            "abi": "Factory",
            "address": "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
            "startBlock": 26956207,
        }
    ):
        fail("Factory source contract drift")
    verify_mapping_common(factory_mapping, str(artifacts["factory_mapping_wasm"]["cid"]))
    if abi_contract(factory_mapping) != [
        ("Factory", str(artifacts["factory_abi"]["cid"])),
        ("ERC20", str(artifacts["erc20_abi"]["cid"])),
        ("ERC20SymbolBytes", str(artifacts["erc20_symbol_bytes_abi"]["cid"])),
        ("ERC20NameBytes", str(artifacts["erc20_name_bytes_abi"]["cid"])),
        ("Pool", str(artifacts["pool_abi"]["cid"])),
    ]:
        fail("Factory ABI inventory drift")
    verify_handlers(
        factory_mapping,
        [("handlePoolCreated", "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)")],
        "Factory",
    )

    position_manager = data_sources[1]
    position_mapping = position_manager["mapping"]
    if (
        position_manager.get("kind") != "ethereum/contract"
        or position_manager.get("name") != "NonfungiblePositionManager"
        or position_manager.get("network") != "bsc"
        or position_manager.get("source")
        != {
            "abi": "NonfungiblePositionManager",
            "address": "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364",
            "startBlock": 26931961,
        }
    ):
        fail("NonfungiblePositionManager source contract drift")
    verify_mapping_common(
        position_mapping, str(artifacts["position_manager_mapping_wasm"]["cid"])
    )
    if abi_contract(position_mapping) != [
        ("NonfungiblePositionManager", str(artifacts["position_manager_abi"]["cid"])),
        ("Pool", str(artifacts["pool_abi"]["cid"])),
        ("Factory", str(artifacts["factory_abi"]["cid"])),
        ("ERC20", str(artifacts["erc20_abi"]["cid"])),
    ]:
        fail("NonfungiblePositionManager ABI inventory drift")
    verify_handlers(
        position_mapping,
        [
            ("handleIncreaseLiquidity", "IncreaseLiquidity(indexed uint256,uint128,uint256,uint256)"),
            ("handleDecreaseLiquidity", "DecreaseLiquidity(indexed uint256,uint128,uint256,uint256)"),
            ("handleCollect", "Collect(indexed uint256,address,uint256,uint256)"),
            ("handleTransfer", "Transfer(indexed address,indexed address,indexed uint256)"),
        ],
        "NonfungiblePositionManager",
    )

    pool = templates[0]
    pool_mapping = pool["mapping"]
    if (
        pool.get("kind") != "ethereum/contract"
        or pool.get("name") != "Pool"
        or pool.get("network") != "bsc"
        or pool.get("source") != {"abi": "Pool"}
    ):
        fail("Pool template contract drift")
    verify_mapping_common(pool_mapping, str(artifacts["pool_mapping_wasm"]["cid"]))
    if abi_contract(pool_mapping) != [
        ("Pool", str(artifacts["pool_abi"]["cid"])),
        ("Factory", str(artifacts["factory_abi"]["cid"])),
        ("ERC20", str(artifacts["erc20_abi"]["cid"])),
    ]:
        fail("Pool ABI inventory drift")
    verify_handlers(
        pool_mapping,
        [
            ("handleInitialize", "Initialize(uint160,int24)"),
            ("handleSwap", "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24,uint128,uint128)"),
            ("handleMint", "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"),
            ("handleBurn", "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"),
            ("handleFlash", "Flash(indexed address,indexed address,uint256,uint256,uint256,uint256)"),
            ("handleCollect", "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)"),
            ("handleCollectProtocol", "CollectProtocol(indexed address,indexed address,uint128,uint128)"),
        ],
        "Pool",
    )

    expected_deployment = {
        "cid": EXPECTED_DEPLOYMENT,
        "chain": "bsc",
        "spec_version": "0.0.2",
        "mapping_api_version": "0.0.4",
        "repository": "https://github.com/pancakeswap/pancake-subgraph",
        "features": ["nonFatalErrors"],
        "data_sources": [
            {
                "name": "Factory",
                "address": "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
                "start_block": 26956207,
                "mapping_role": "factory_mapping_wasm",
            },
            {
                "name": "NonfungiblePositionManager",
                "address": "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364",
                "start_block": 26931961,
                "mapping_role": "position_manager_mapping_wasm",
            },
        ],
        "templates": [{"name": "Pool", "mapping_role": "pool_mapping_wasm"}],
    }
    if deployment != expected_deployment:
        fail("machine-readable deployment profile drift")


def parse_schema(path: Path) -> tuple[dict[str, dict[str, str]], set[str], set[str]]:
    entities: dict[str, dict[str, str]] = {}
    immutable: set[str] = set()
    mutable: set[str] = set()
    current: str | None = None
    declaration_pattern = re.compile(
        r"^type\s+([_A-Za-z][_0-9A-Za-z]*)\s+@entity\s*"
        r"(?:\(immutable:\s*(true|false)\))?\s*\{"
    )
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        declaration = declaration_pattern.match(line)
        if declaration:
            current = declaration.group(1)
            entities[current] = {}
            if declaration.group(2) == "true":
                immutable.add(current)
            else:
                mutable.add(current)
            continue
        if current and line == "}":
            current = None
            continue
        if current:
            field = re.match(r"^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)", line)
            if field:
                entities[current][field.group(1)] = field.group(2)
    return entities, immutable, mutable


def logical_hash(entities: dict[str, dict[str, str]]) -> str:
    payload = json.dumps(entities, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode())


def field_differences(
    exchange: dict[str, dict[str, str]], uniswap: dict[str, dict[str, str]]
) -> dict[str, dict[str, object]]:
    differences: dict[str, dict[str, object]] = {}
    for entity in sorted(set(exchange) & set(uniswap)):
        exchange_fields = exchange[entity]
        uniswap_fields = uniswap[entity]
        entry: dict[str, object] = {}
        missing = sorted(set(uniswap_fields) - set(exchange_fields))
        extra = sorted(set(exchange_fields) - set(uniswap_fields))
        type_diff = {
            field: [exchange_fields[field], uniswap_fields[field]]
            for field in sorted(set(exchange_fields) & set(uniswap_fields))
            if exchange_fields[field] != uniswap_fields[field]
        }
        if missing:
            entry["missing_from_exchange"] = missing
        if extra:
            entry["extra_in_exchange"] = extra
        if type_diff:
            entry["type_differences"] = type_diff
        if entry:
            differences[entity] = entry
    return differences


def verify_schema(
    root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]
) -> None:
    contract = lock["logical_contract"]
    exchange, exchange_immutable, exchange_mutable = parse_schema(
        root / str(artifacts["schema"]["vendored_path"])
    )
    uniswap, uniswap_immutable, _ = parse_schema(root / "uniswap-v3/source/schema.graphql")

    if len(exchange) != contract["entity_count"] or sorted(exchange) != contract["entities"]:
        fail("Exchange V3 entity inventory drift")
    if logical_hash(exchange) != contract["logical_sha256"]:
        fail("Exchange V3 logical schema digest drift")
    if sorted(exchange_immutable) != contract["immutable_entities"]:
        fail("Exchange V3 immutable-entity contract drift")
    if sorted(exchange_mutable) != contract["mutable_entities"]:
        fail("Exchange V3 mutable-entity contract drift")

    reference = contract["frozen_uniswap_v3"]
    if len(uniswap) != reference["entity_count"] or logical_hash(uniswap) != reference["logical_sha256"]:
        fail("frozen Uniswap V3 schema reference drift")
    if sorted(set(uniswap) - set(exchange)) != reference["missing_from_exchange"]:
        fail("Exchange V3 missing-entity profile drift")
    if sorted(set(exchange) - set(uniswap)) != reference["extra_in_exchange"]:
        fail("Exchange V3 extra-entity profile drift")
    if sorted(uniswap_immutable - exchange_immutable) != reference[
        "immutable_in_uniswap_but_mutable_in_exchange"
    ]:
        fail("Exchange V3 mutability gap profile drift")
    if field_differences(exchange, uniswap) != reference["field_differences"]:
        fail("Exchange V3 static field gap profile drift")
    if reference.get("scope") != "static_schema_only_pending_certified_runtime_gap":
        fail("static schema comparison scope drift")


def verify_profile(
    root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]
) -> None:
    profile_payload = (root / PROFILE_PATH).read_bytes()
    if (
        len(profile_payload) != EXPECTED_PROFILE_BYTES
        or sha256(profile_payload) != EXPECTED_PROFILE_SHA256
    ):
        fail("machine-readable Exchange V3 layout profile digest drift")
    if lock.get("layout_profile") != {
        "path": str(PROFILE_PATH),
        "bytes": EXPECTED_PROFILE_BYTES,
        "sha256": EXPECTED_PROFILE_SHA256,
    }:
        fail("Exchange V3 layout profile provenance lock drift")
    profile = load_json(root / PROFILE_PATH)
    if not isinstance(profile, dict):
        fail("Exchange V3 layout profile must be an object")
    if (
        profile.get("format_version") != 1
        or profile.get("profile_id") != "exchange-v3-bsc-QmY67iZD"
        or profile.get("status") != "immutable_target_and_exact_source_contract_only"
        or profile.get("runtime_parity") is not False
        or profile.get("eligibility_decision") != "awaiting_same_pod_72_hour_evidence"
        or profile.get("family") != "exchange-v3-bsc"
        or profile.get("chain") != "bsc"
    ):
        fail("Exchange V3 layout profile identity or baseline-only status drift")
    if profile.get("deployment") != {
        "cid": EXPECTED_DEPLOYMENT,
        "spec_version": "0.0.2",
        "mapping_api_version": "0.0.4",
        "module_initial_block": 26931961,
        "graft": None,
        "features": ["nonFatalErrors"],
    }:
        fail("Exchange V3 profile deployment contract drift")

    expected_component_contracts = {
        "Factory": {
            "kind": "data_source",
            "address": "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
            "start_block": 26956207,
            "mapping_cid": artifacts["factory_mapping_wasm"]["cid"],
        },
        "NonfungiblePositionManager": {
            "kind": "data_source",
            "address": "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364",
            "start_block": 26931961,
            "mapping_cid": artifacts["position_manager_mapping_wasm"]["cid"],
        },
        "Pool": {
            "kind": "template",
            "created_by": "Factory.handlePoolCreated",
            "mapping_cid": artifacts["pool_mapping_wasm"]["cid"],
        },
    }
    components = profile.get("components")
    if (
        not isinstance(components, list)
        or not all(isinstance(item, dict) for item in components)
        or [item.get("name") for item in components] != [
            "Factory",
            "NonfungiblePositionManager",
            "Pool",
        ]
    ):
        fail("Exchange V3 profile component inventory or order drift")
    for component in components:
        if not isinstance(component, dict):
            fail("Exchange V3 profile component must be an object")
        name = str(component.get("name"))
        handlers = component.get("handlers")
        contract = {
            key: value
            for key, value in component.items()
            if key not in {"name", "handlers"}
        }
        if contract != expected_component_contracts[name]:
            fail(f"Exchange V3 profile component contract drift: {name}")
        if not isinstance(handlers, list) or [
            (handler.get("name"), handler.get("signature"), handler.get("topic0"))
            for handler in handlers
            if isinstance(handler, dict)
        ] != EXPECTED_PROFILE_HANDLERS[name]:
            fail(f"Exchange V3 profile handler/topic contract drift: {name}")

    if profile.get("pool_creation") != {
        "pool_id": "lowercase_pool_address_hex",
        "token_ids": "lowercase_token_address_hex",
        "factory_entity_id": "factory_address",
        "bundle_entity_id": "1",
        "fee_tier_source": "PoolCreated.fee",
        "dynamic_pool_template_created": True,
        "missing_token_decimals_behavior": "return_without_pool_token_or_factory_saves",
    }:
        fail("Exchange V3 pool-creation contract drift")
    if profile.get("fee_and_protocol") != {
        "tick_spacing_by_fee_tier": {"100": 1, "500": 10, "2500": 50, "10000": 200},
        "default_packed_fee_protocol_by_fee_tier": {
            "100": 216272100,
            "500": 222825800,
            "2500": 209718400,
            "10000": 209718400,
            "fallback": 209718400,
        },
        "swap_protocol_fee_inputs": ["protocolFeesToken0", "protocolFeesToken1"],
        "swap_amount_fee_usd": "combined_adjusted_protocol_fee_usd",
        "protocol_fee_aggregates": [
            "Factory.totalProtocolFeesETH",
            "Factory.totalProtocolFeesUSD",
            "Pool.protocolFeesUSD",
            "Token.protocolFeesUSD",
            "PancakeDayData.protocolFeesUSD",
            "PoolDayData.protocolFeesUSD",
            "PoolHourData.protocolFeesUSD",
            "TokenDayData.protocolFeesUSD",
            "TokenHourData.protocolFeesUSD",
        ],
        "collect_protocol_behavior": (
            "subtract_amounts_from_pool_and_token_tvl_increment_tx_counts_without_event_entity"
        ),
        "flash_behavior": "refresh_pool_fee_growth_globals_only",
    }:
        fail("Exchange V3 fee/protocol behavior contract drift")
    if profile.get("positions") != {
        "position_id": "decimal_token_id_string",
        "lazy_source": "NonfungiblePositionManager.try_positions",
        "pool_source": "Factory.getPool_token0_token1_fee",
        "initial_owner": "zero_address_until_transfer",
        "transfer_updates_owner": True,
        "burn_delete": False,
        "snapshot_id": "position_id_hash_block_number",
        "snapshot_written_by": [
            "IncreaseLiquidity",
            "DecreaseLiquidity",
            "Collect",
            "Transfer",
        ],
        "fee_growth_refreshed_by": ["IncreaseLiquidity", "DecreaseLiquidity", "Collect"],
        "source_compatibility_quirk": (
            "position_manager_collect_adds_amount0_to_both_collected_fee_token_fields"
        ),
    }:
        fail("Exchange V3 position behavior contract drift")

    logical_contract = lock["logical_contract"]
    if profile.get("entity_layout") != {
        "entity_count": logical_contract["entity_count"],
        "all_entities_mutable": True,
        "immutable_entities": logical_contract["immutable_entities"],
        "entities": logical_contract["entities"],
    }:
        fail("Exchange V3 profile entity layout drift")
    if profile.get("aggregates") != {
        "swap_amounts": "absolute_token_deltas",
        "tracked_volume_divisor": 2,
        "untracked_volume_divisor": 2,
        "lp_fee_formula": "tracked_swap_volume_times_pool_fee_tier_div_1000000",
        "protocol_fee_formula": "adjusted_event_protocol_fee_amounts",
        "intervals": [
            "pancake_day",
            "pool_day",
            "pool_hour",
            "token_day",
            "token_hour",
            "tick_day",
            "tick_hour",
        ],
        "tick_crossing_update_cap": 100,
        "pool_collect_tvl_change": "none_to_avoid_double_counting_burn",
        "pool_collect_protocol_tvl_change": "subtract_collected_protocol_amounts",
    }:
        fail("Exchange V3 aggregate behavior contract drift")

    chain = lock["exact_source"]["chain_configuration"]
    if profile.get("pricing") != {
        "wrapped_native_address": chain["wrapped_native"],
        "stablecoin_wrapped_native_pool": chain["wrapped_native_stable_pool"],
        "stablecoin_is_token0": chain["stable_is_token0"],
        "minimum_native_locked": chain["minimum_native_locked"],
        "stablecoin_addresses": chain["stable_coins"],
        "whitelist_tokens": chain["whitelist_tokens"],
        "static_token_definitions": [],
        "pools_to_skip": [],
        "pool_mappings": [],
    }:
        fail("Exchange V3 BSC pricing configuration drift")
    if profile.get("metadata") != {
        "symbol_and_name_fallback": "string_then_bytes32_then_static_definition_then_unknown",
        "static_definitions_enabled": False,
        "total_supply_call": True,
        "decimals_call": "uint8_with_static_definition_fallback",
        "null_bytes32_sentinel_handling": True,
    }:
        fail("Exchange V3 token metadata behavior contract drift")

    reference = logical_contract["frozen_uniswap_v3"]
    expected_extra_fields = {
        entity: difference["extra_in_exchange"]
        for entity, difference in reference["field_differences"].items()
    }
    if profile.get("frozen_uniswap_v3_static_gap") != {
        "entity_rename": {"UniswapDayData": "PancakeDayData"},
        "immutable_in_uniswap_but_mutable_in_exchange": reference[
            "immutable_in_uniswap_but_mutable_in_exchange"
        ],
        "extra_exchange_fields": expected_extra_fields,
        "scope": "static_schema_and_exact_source_semantics_pending_certified_runtime_gap",
    }:
        fail("Exchange V3 frozen Uniswap V3 gap profile drift")
    if profile.get("required_target_changes") != EXPECTED_REQUIRED_CHANGES:
        fail("Exchange V3 required target-change inventory drift")
    if profile.get("remaining_gates") != [
        "fresh_24_hour_and_same_pod_72_hour_graph_node_catchup_forecasts_both_greater_than_28_days",
        "generic_loader_legacy_spec_0_0_2_physical_schema_and_metadata_proof",
        "certified_uniswap_v3_runtime_functional_gap_after_issues_5_and_9",
        "paused_restore_differential_validation_and_separate_operational_activation_approval",
    ]:
        fail("Exchange V3 remaining-gate profile drift")


def verify_source_pin(lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    source = lock.get("exact_source")
    if not isinstance(source, dict):
        fail("exact_source must be an object")
    if source.get("status") != "exact_reproduction":
        fail("Exchange V3 source must remain bound to the exact reproduction")
    if source.get("repository") != "https://github.com/pancakeswap/pancake-subgraph":
        fail("exact source repository drift")
    if source.get("branch") != "v3":
        fail("exact source branch drift")
    if source.get("earliest_exact_commit") != EXPECTED_SOURCE_COMMIT:
        fail("earliest exact source commit drift")
    if source.get("tree") != EXPECTED_SOURCE_TREE:
        fail("exact source tree drift")
    if source.get("parent") != EXPECTED_SOURCE_PARENT:
        fail("exact source parent drift")
    if any(
        not re.fullmatch(r"[0-9a-f]{40}", str(source.get(key, "")))
        for key in ("earliest_exact_commit", "tree", "parent")
    ):
        fail("invalid exact source commit, tree, or parent")

    expected_toolchain = {
        "source_ci_node_range": "14.x",
        "reproduction_node": "14.21.3",
        "reproduction_yarn": "1.22.22",
        "graph_cli": "0.21.0",
        "graph_ts": "0.20.1",
        "assemblyscript": "0.6.0",
        "assemblyscript_git_commit": "3ed76a97f05335504166fce1653da75f4face28f",
    }
    if source.get("toolchain") != expected_toolchain:
        fail("exact source toolchain drift")

    source_files = source.get("source_files")
    expected_source_paths = {
        "package.json",
        "yarn.lock",
        ".github/workflows/build.yml",
        "config/bsc.js",
        "subgraphs/exchange-v3/template/package.json",
        "subgraphs/exchange-v3/template/subgraph.template.yaml",
        "subgraphs/exchange-v3/template/schema.graphql",
        "subgraphs/exchange-v3/template/mappings/factory.ts",
        "subgraphs/exchange-v3/template/mappings/position-manager.ts",
        "subgraphs/exchange-v3/template/mappings/core.ts",
        "subgraphs/exchange-v3/template/utils/pricing.template.ts",
    }
    if not isinstance(source_files, list) or {
        entry.get("path") for entry in source_files if isinstance(entry, dict)
    } != expected_source_paths:
        fail("exact source file inventory drift")
    for entry in source_files:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("bytes"), int)
            or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))
            or not re.fullmatch(r"[0-9a-f]{40}", str(entry.get("git_blob", "")))
        ):
            fail("invalid exact source file record")

    expected_transport = {
        "reason": "The lock's deleted concat-stream GitHub fork tarball now returns 404.",
        "locked_request": "concat-stream@github:hugomrdias/concat-stream#feat/smaller",
        "dead_url": "https://codeload.github.com/hugomrdias/concat-stream/tar.gz/057bc7b5d6d8df26c8cf00a3f151b6721a0a8034",
        "replacement": "https://registry.yarnpkg.com/concat-stream/-/concat-stream-2.0.0.tgz#414cf5af790a48c60ab9be4527d56d5e41133cb1",
        "replacement_integrity": "sha512-MWufYdFw53ccGjCA+Ol7XJYpAlW6/prSMzuPOTRnJGcGzuhLn4Scrz7qf6o8bROZ514ltazcIFJZevcfbo0x7A==",
        "scope": "install_transport_only_graph_cli_ipfs_client_not_compiler",
        "original_lock_restored_before_validation": True,
    }
    if source.get("install_transport_override") != expected_transport:
        fail("install transport override drift")

    build = source.get("build")
    if not isinstance(build, dict) or build.get("result") != "byte_exact_to_all_deployed_mapping_objects":
        fail("exact source build result drift")
    for prefix, role in (
        ("factory", "factory_mapping_wasm"),
        ("position_manager", "position_manager_mapping_wasm"),
        ("pool", "pool_mapping_wasm"),
    ):
        if build.get(f"{prefix}_wasm_bytes") != artifacts[role]["source_bytes"]:
            fail(f"{prefix} exact source byte count drift")
        if build.get(f"{prefix}_wasm_sha256") != artifacts[role]["source_sha256"]:
            fail(f"{prefix} exact source digest drift")

    boundary = source.get("earliest_exact_boundary")
    if not isinstance(boundary, dict) or boundary.get("previous_commit") != (
        "e2019f716f4310f4ce28addc4439980804d9e413"
    ):
        fail("earliest exact source boundary drift")
    if boundary.get("exact_change") != "Set BSC v3.minETHLocked from 60 to 10.":
        fail("earliest exact source change drift")

    chain = source.get("chain_configuration")
    if not isinstance(chain, dict) or chain.get("minimum_native_locked") != "10":
        fail("exact BSC chain configuration drift")
    if len(lock.get("remaining_gates", [])) != 4:
        fail("remaining Exchange V3 gates must stay explicit")


def git_blob_hash(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def local_path_from_file(value: object) -> str:
    if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts:
        fail(f"unexpected generated-manifest path: {value!r}")
    return value


def replace_generated_files_with_cids(
    value: object, build_root: Path
) -> object:
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key == "file":
                relative = local_path_from_file(item)
                payload = (build_root / relative).read_bytes()
                output[key] = {"/": f"/ipfs/{unixfs_file_cidv0(payload)}"}
            else:
                output[key] = replace_generated_files_with_cids(item, build_root)
        return output
    if isinstance(value, list):
        return [replace_generated_files_with_cids(item, build_root) for item in value]
    return value


def verify_exact_source_build(
    root: Path,
    source_root: Path,
    lock: dict[str, object],
    artifacts: dict[str, dict[str, object]],
) -> None:
    source = lock["exact_source"]
    for record in source["source_files"]:
        payload = (source_root / record["path"]).read_bytes()
        if (
            len(payload) != record["bytes"]
            or sha256(payload) != record["sha256"]
            or git_blob_hash(payload) != record["git_blob"]
        ):
            fail(f"exact source file drift: {record['path']}")

    build_root = source_root / "subgraphs/exchange-v3/template/build"
    deployed_manifest = yaml.safe_load(
        (root / str(artifacts["deployment"]["vendored_path"])).read_text()
    )
    built_manifest = yaml.safe_load((build_root / "subgraph.yaml").read_text())
    if replace_generated_files_with_cids(built_manifest, build_root) != deployed_manifest:
        fail("exact source generated manifest does not resolve to the deployed CID graph")

    built_artifacts = {
        "schema": "schema.graphql",
        "factory_abi": "Factory/abis/factory.json",
        "erc20_abi": "Factory/abis/ERC20.json",
        "erc20_symbol_bytes_abi": "Factory/abis/ERC20SymbolBytes.json",
        "erc20_name_bytes_abi": "Factory/abis/ERC20NameBytes.json",
        "pool_abi": "Factory/abis/pool.json",
        "position_manager_abi": "NonfungiblePositionManager/abis/NonfungiblePositionManager.json",
        "factory_mapping_wasm": "Factory/Factory.wasm",
        "position_manager_mapping_wasm": (
            "NonfungiblePositionManager/NonfungiblePositionManager.wasm"
        ),
        "pool_mapping_wasm": "templates/Pool/Pool.wasm",
    }
    for role, relative_path in built_artifacts.items():
        payload = (build_root / relative_path).read_bytes()
        deployed_payload = (root / str(artifacts[role]["vendored_path"])).read_bytes()
        if payload != deployed_payload:
            fail(f"exact source build is not byte-identical for {role}")
        if len(payload) != artifacts[role]["source_bytes"]:
            fail(f"exact source build byte count drift for {role}")
        if sha256(payload) != artifacts[role]["source_sha256"]:
            fail(f"exact source build digest drift for {role}")

    installed_versions = {
        "graph_cli": load_json(source_root / "node_modules/@graphprotocol/graph-cli/package.json")[
            "version"
        ],
        "graph_ts": load_json(source_root / "node_modules/@graphprotocol/graph-ts/package.json")[
            "version"
        ],
        "assemblyscript": load_json(source_root / "node_modules/assemblyscript/package.json")[
            "version"
        ],
    }
    for key, value in installed_versions.items():
        if value != source["toolchain"][key]:
            fail(f"installed exact source toolchain drift: {key}")


def verify_binding(root: Path) -> None:
    binding = yaml.safe_load((root / BINDING_PATH).read_text())
    if (
        not isinstance(binding, dict)
        or binding.get("deployment") != EXPECTED_DEPLOYMENT
        or binding.get("family") != "exchange-v3-bsc"
        or binding.get("schema") != EXPECTED_SCHEMA
        or binding.get("chain") != "bsc"
        or binding.get("milestone") != "M6"
        or binding.get("eligibility", {}).get("latest", {}).get("decision")
        != "indeterminate"
        or binding.get("eligibility", {}).get("latest", {}).get("reason")
        != "no_fresh_evidence"
    ):
        fail("Exchange V3 target binding, M6 milestone, or fail-closed eligibility drift")


def verify(root: Path, lock_path: Path, exact_source_root: Path | None = None) -> None:
    lock = load_json(root / lock_path)
    if not isinstance(lock, dict) or lock.get("format_version") != 1:
        fail("unsupported Exchange V3 BSC target lock")
    if (
        lock.get("family") != "exchange-v3-bsc"
        or lock.get("implementation_status")
        != "immutable_target_and_exact_source_baseline_only"
        or lock.get("runtime_parity") is not False
        or lock.get("eligibility_decision") != "awaiting_same_pod_72_hour_evidence"
        or len(lock.get("remaining_gates", [])) != 4
    ):
        fail("Exchange V3 baseline status, runtime-parity refusal, or remaining gates drift")
    deployment = lock.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("cid") != EXPECTED_DEPLOYMENT:
        fail("deployment identity drift")
    artifacts = verify_artifacts(root, lock)
    verify_manifest(root, lock, artifacts)
    verify_schema(root, lock, artifacts)
    verify_profile(root, lock, artifacts)
    verify_source_pin(lock, artifacts)
    verify_binding(root)
    if exact_source_root is not None:
        verify_exact_source_build(root, exact_source_root.resolve(), lock, artifacts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--exact-source-root", type=Path)
    args = parser.parse_args()
    try:
        verify(args.root.resolve(), args.lock, args.exact_source_root)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"Exchange V3 BSC target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified all eleven Exchange V3 CIDv0 artifacts, legacy manifest and 20-entity "
        "mutable schema, implementation-gap profile, exact source commit/tree/parent and "
        "toolchain reproduction, and fail-closed M6 binding"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
