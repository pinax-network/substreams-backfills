#!/usr/bin/env python3
"""Verify the immutable PancakeSwap Infinity CL BSC target and source baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml


LOCK_PATH = Path("docs/provenance/pancakeswap-infinity-cl-bsc-target.json")
PROFILE_PATH = Path("pancakeswap-infinity-cl-bsc/layout-profile-v1.json")
BINDING_PATH = Path(
    "pancakeswap-infinity-cl-bsc/"
    "QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz.yaml"
)
PARENT_SCHEMA_PATH = Path(
    "uniswap-v4/artifacts/deployment/"
    "QmS1ehFzXTD9eA1f1EgjZvdyAj2EHtVNMrEN91H3pLuHMy/schema.graphql"
)
CHILD_SCHEMA_PATH = Path(
    "uniswap-v4/artifacts/deployment/"
    "Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB/schema.graphql"
)

EXPECTED_DEPLOYMENT = "QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz"
EXPECTED_SCHEMA = "QmcWb81VRk9SycZYgLyr9i6tYCnHsVsPTyTvfNpywDRJfr"
EXPECTED_SOURCE_REPOSITORY = "https://github.com/NgoKimPhu/infinity-cl-subgraph"
EXPECTED_SOURCE_COMMIT = "40b0021be04cda3e32dde8e3cf0c3397863fc0c0"
EXPECTED_SOURCE_TREE = "b7a7778bc5c7f316cc46913b7b1d54ffcfa07c22"
EXPECTED_SOURCE_PARENT = "e53351269ab0bb9a265ab04d71189156f3fa03a8"
EXPECTED_PROFILE_BYTES = 9077
EXPECTED_PROFILE_SHA256 = "372f7845b6426422d1d5b31f972ab5b40ba0106223a2b10a8cf6b55115671d86"

EXPECTED_TOOLCHAIN = {
    "node": "24.13.1",
    "npm": "11.11.0",
    "package_lock_version": 3,
    "graph_cli": "0.64.1",
    "graph_ts": "0.32.0",
    "assemblyscript": "0.19.23",
    "binaryen": "102.0.0-nightly.20211028",
    "typescript": "3.9.9",
    "npm_run_all": "4.1.5",
    "relationship_to_historical_ci": "independent_byte_exact_reproduction_not_original_deployment_toolchain",
}

EXPECTED_HISTORICAL_SOURCE_CI = {
    "workflow": ".github/workflows/CI.yml",
    "node": "18.x",
    "dependency_install": "yarn install",
    "build": "yarn build",
    "package_manager_version": None,
    "immutable_toolchain": False,
}

EXPECTED_SOURCE_FILES = {
    "package.json": (1547, "216d2b1e9fe7f1fa853a50c325b715ef0c3aac180d6ebc4d07590349b806396d", "85349919ed10c0ef119d103285ad4af675dfa896"),
    "package-lock.json": (402813, "2c6ef0c4e651cb9082ce64e3c9b7bb2f67728880a038190e1328a97808cf4c9e", "38f8e12ad7568140da676b9da965f7556c9bf464"),
    "yarn.lock": (231900, "00635b81287cddc5eae332d71786ae352245f89c0682260fa53ed7d9e26e53a7", "a9af8809688e371a0fba18161785cbe24d0d0c36"),
    ".yarnrc.yml": (25, "473e6def86fc03638120e0c01d0c8bbab095677256460fa4ea763e5d4697f270", "3186f3f0795ab612d5508593672dc9ad94bccca0"),
    "subgraph.yaml": (2145, "6bcbee5032de14963e9c05a39fb2458a92c392705f000c9d9ee54cb4e82c0ecc", "c50ab98eb077325a335de3290cefbe78ab81d2bb"),
    "schema.graphql": (13473, "af4a4495ef03ac1cb0228cc81b9d6033965715fca5b7ceaa039416fff8d02219", "17dfca6dee452ec2be30dbf756b67dbf2c9efc02"),
    "networks.json": (262, "df96a2d83f1de3aec01d4f8b775b46c677a260e1dcc8c4066e8087fc82f08ef7", "f443cbcb5288e70b33ef1f7334820cb3a17acc7b"),
    ".github/workflows/CI.yml": (1974, "497280d4df95f856f203161f757376f2f67e609b2ad8dd624c689a66e8c4eba6", "4b8a9ec86d2b261dfdee50360bae491c5b815d5f"),
}

EXPECTED_SOURCE_ABIS = {
    "abis/ERC20.json": (3686, "929f801517d474eae12c45fc263502bc0644364854379f46a7bb273354d96d2e"),
    "abis/ERC20NameBytes.json": (269, "f2931748c6851e1636b458030361de258db60441c353351e7eb4616c90039bce"),
    "abis/ERC20SymbolBytes.json": (271, "6e114ca21ff78fcae5364358aec454862cdcef2cebdb541752e45ee84d38ace9"),
    "abis/PoolManager.json": (28147, "4b09ffd628dca73228fdf699fbcbba11f6c5495cf5bdaf5922c1685bbe559392"),
    "abis/PositionManager.json": (28827, "21d4794971609c029d880140151507b9f51e645667d487d4d34749a0e882d56e"),
}

EXPECTED_HANDLERS = {
    "PoolManager": [
        ("handleInitialize", "Initialize(indexed bytes32,indexed address,indexed address,address,uint24,bytes32,uint160,int24)"),
        ("handleModifyLiquidity", "ModifyLiquidity(indexed bytes32,indexed address,int24,int24,int256,bytes32)"),
        ("handleSwap", "Swap(indexed bytes32,indexed address,int128,int128,uint160,uint128,int24,uint24,uint16)"),
    ],
    "PositionManager": [
        ("handleSubscription", "Subscription(indexed uint256,indexed address)"),
        ("handleUnsubscription", "Unsubscription(indexed uint256,indexed address)"),
        ("handleTransfer", "Transfer(indexed address,indexed address,indexed uint256)"),
    ],
}

EXPECTED_TOPICS = {
    "handleInitialize": "0x426cc62fe6a33a40ba2788c2c87a9c34ee4582b95bc9fa5a7bb7ae70b750b99c",
    "handleModifyLiquidity": "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec",
    "handleSwap": "0x04206ad2b7c0f463bff3dd4f33c5735b0f2957a351e4f79763a4fa9e775dd237",
    "handleSubscription": "0x9709492381f90bdc5938bb4e3b8e35b7e0eac8af058619e27191c5a40ce79fa9",
    "handleUnsubscription": "0xa0ebb1de82db929a9153472f37d3a66dbede4436258311ad0f52a35a2c91d150",
    "handleTransfer": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
}

EXPECTED_REQUIRED_CHANGES = [
    "profile_driven_network_deployment_address_and_start_block_validation",
    "pancake_initialize_and_swap_abi_decoders",
    "protobuf_fields_for_raw_parameters_hooks_registration_and_protocol_fee",
    "pool_state_poi_writer_and_seed_fields_for_parameters_and_hooks_registration",
    "bsc_native_token_stable_pool_whitelist_and_minimum_liquidity_configuration",
    "static_initialize_fee_policy_and_intentional_swap_fee_protocol_fee_ignores",
    "remove_base_arrakis_and_creator_content_hook_semantics",
    "make_all_seventeen_target_entities_temporal_and_mutable",
    "target_specific_substreams_packages_module_hashes_and_initial_blocks",
    "bsc_canonical_event_metadata_and_reducer_fixtures",
    "exact_graph_node_schema_poi_vid_and_postgresql_parity_certification",
]


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> object:
    with path.open() as handle:
        return json.load(handle)


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
    # All locked objects fit in one default IPFS chunk. This is the canonical
    # UnixFS File protobuf wrapped in a link-free DAG-PB node.
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


def normalize_event(event: str) -> str:
    return re.sub(r"\s+", "", event)


def parse_schema(path: Path) -> tuple[dict[str, dict[str, str]], set[str], set[str]]:
    entities: dict[str, dict[str, str]] = {}
    immutable: set[str] = set()
    explicit_mutable: set[str] = set()
    current: str | None = None
    declaration_pattern = re.compile(
        r"^type\s+([_A-Za-z][_0-9A-Za-z]*)\s+@entity\s*"
        r"(?:\(\s*immutable:\s*(true|false)\s*\))?\s*\{"
    )
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        declaration = declaration_pattern.match(line)
        if declaration:
            current = declaration.group(1)
            entities[current] = {}
            if declaration.group(2) == "true":
                immutable.add(current)
            elif declaration.group(2) == "false":
                explicit_mutable.add(current)
            continue
        if current and line == "}":
            current = None
            continue
        if current:
            field = re.match(r"^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)", line)
            if field:
                entities[current][field.group(1)] = field.group(2)
    return entities, immutable, explicit_mutable


def logical_hash(entities: dict[str, dict[str, str]]) -> str:
    canonical = json.dumps(entities, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode())


def verify_artifact_lock(root: Path, lock: dict[str, object]) -> dict[str, dict[str, object]]:
    records = lock.get("artifact_lock")
    if not isinstance(records, list):
        fail("artifact_lock must be a list")
    expected_roles = {
        "deployment", "schema", "erc20_abi", "erc20_name_bytes_abi",
        "erc20_symbol_bytes_abi", "pool_manager_abi", "position_manager_abi",
        "mapping_wasm",
    }
    artifacts: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("role"), str):
            fail("artifact record must have a string role")
        role = str(record["role"])
        if role in artifacts:
            fail(f"duplicate artifact role: {role}")
        artifacts[role] = record
        relative = record.get("path")
        if not isinstance(relative, str):
            fail(f"artifact path missing for {role}")
        path = (root / relative).resolve()
        if root.resolve() not in path.parents:
            fail(f"artifact path escapes root for {role}")
        payload = path.read_bytes()
        if len(payload) != record.get("bytes"):
            fail(f"artifact byte count drift for {role}")
        if sha256(payload) != record.get("sha256"):
            fail(f"artifact SHA-256 drift for {role}")
        if unixfs_file_cidv0(payload) != record.get("cid"):
            fail(f"artifact CIDv0 drift for {role}")
        if role.endswith("_abi"):
            json.loads(payload)
        if role == "mapping_wasm":
            if not payload.startswith(b"\0asm\x01\0\0\0"):
                fail("mapping artifact is not a WebAssembly v1 module")
            expected_exports = [
                "handleInitialize", "handleModifyLiquidity", "handleSubscription",
                "handleSwap", "handleTransfer", "handleUnsubscription",
            ]
            if record.get("exports") != expected_exports:
                fail("mapping export lock drift")
            if any(name.encode() not in payload for name in expected_exports):
                fail("mapping artifact is missing a locked handler export")
    if set(artifacts) != expected_roles:
        fail(f"artifact role drift: {sorted(set(artifacts) ^ expected_roles)}")
    if artifacts["deployment"]["cid"] != EXPECTED_DEPLOYMENT:
        fail("deployment CID lock drift")
    if artifacts["schema"]["cid"] != EXPECTED_SCHEMA:
        fail("schema CID lock drift")
    return artifacts


def abi_contract(mapping: dict[str, object]) -> list[tuple[str, str]]:
    abis = mapping.get("abis")
    if not isinstance(abis, list):
        fail("mapping ABI inventory must be a list")
    return [(str(abi.get("name")), cid_from_file(abi.get("file"))) for abi in abis]


def verify_manifest(root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    manifest = yaml.safe_load((root / str(artifacts["deployment"]["path"])).read_text())
    deployment = lock.get("deployment")
    if not isinstance(manifest, dict) or not isinstance(deployment, dict):
        fail("deployment manifests must be objects")
    if manifest.get("specVersion") != "0.0.4" or manifest.get("repository") != EXPECTED_SOURCE_REPOSITORY:
        fail("manifest identity drift")
    if manifest.get("features") != ["nonFatalErrors", "grafting"] or "graft" in manifest:
        fail("manifest feature or concrete-graft contract drift")
    if cid_from_file(manifest.get("schema", {}).get("file")) != EXPECTED_SCHEMA:
        fail("manifest schema CID drift")
    data_sources = manifest.get("dataSources")
    if not isinstance(data_sources, list) or [source.get("name") for source in data_sources] != [
        "PoolManager", "PositionManager"
    ]:
        fail("manifest data-source order or inventory drift")

    expected_sources = {
        "PoolManager": {
            "abi": "PoolManager",
            "address": "0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b",
            "startBlock": 47214308,
        },
        "PositionManager": {
            "abi": "PositionManager",
            "address": "0x55f4c8abA71A1e923edC303eb4fEfF14608cC226",
            "startBlock": 47215015,
        },
    }
    expected_abis = {
        "PoolManager": [
            ("ERC20", artifacts["erc20_abi"]["cid"]),
            ("ERC20SymbolBytes", artifacts["erc20_symbol_bytes_abi"]["cid"]),
            ("ERC20NameBytes", artifacts["erc20_name_bytes_abi"]["cid"]),
            ("PoolManager", artifacts["pool_manager_abi"]["cid"]),
        ],
        "PositionManager": [("PositionManager", artifacts["position_manager_abi"]["cid"])],
    }
    expected_entities = {"PoolManager": ["Pool", "Token"], "PositionManager": ["Position"]}
    for data_source in data_sources:
        name = data_source["name"]
        mapping = data_source.get("mapping")
        if (
            data_source.get("kind") != "ethereum/contract"
            or data_source.get("network") != "bsc"
            or data_source.get("source") != expected_sources[name]
            or not isinstance(mapping, dict)
        ):
            fail(f"{name} source contract drift")
        if (
            mapping.get("kind") != "ethereum/events"
            or mapping.get("apiVersion") != "0.0.7"
            or mapping.get("language") != "wasm/assemblyscript"
            or mapping.get("entities") != expected_entities[name]
            or cid_from_file(mapping.get("file")) != artifacts["mapping_wasm"]["cid"]
            or abi_contract(mapping) != expected_abis[name]
        ):
            fail(f"{name} mapping contract drift")
        handlers = mapping.get("eventHandlers")
        actual_handlers = [
            (entry.get("handler"), normalize_event(str(entry.get("event", "")))) for entry in handlers
        ] if isinstance(handlers, list) else []
        expected_handlers = [
            (handler, normalize_event(event)) for handler, event in EXPECTED_HANDLERS[name]
        ]
        if actual_handlers != expected_handlers:
            fail(f"{name} handler order or signature drift")

    expected_deployment_sources = [
        {"name": "PoolManager", "address": expected_sources["PoolManager"]["address"], "start_block": 47214308},
        {"name": "PositionManager", "address": expected_sources["PositionManager"]["address"], "start_block": 47215015},
    ]
    if (
        deployment.get("cid") != EXPECTED_DEPLOYMENT
        or deployment.get("chain") != "bsc"
        or deployment.get("spec_version") != "0.0.4"
        or deployment.get("mapping_api_version") != "0.0.7"
        or deployment.get("features") != ["nonFatalErrors", "grafting"]
        or deployment.get("concrete_graft") is not None
        or deployment.get("data_sources") != expected_deployment_sources
    ):
        fail("provenance deployment contract drift")


def verify_schema_contract(root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    target, target_immutable, target_explicit_mutable = parse_schema(
        root / str(artifacts["schema"]["path"])
    )
    parent, _, _ = parse_schema(root / PARENT_SCHEMA_PATH)
    child, child_immutable, _ = parse_schema(root / CHILD_SCHEMA_PATH)
    contract = lock.get("logical_contract")
    if not isinstance(contract, dict):
        fail("logical_contract must be an object")
    if len(target) != 17 or logical_hash(target) != "e9bdfc5b10be66cd3c0ebead32cd31497ba3e0ad380e5ddffd9c1ecdc455641e":
        fail("Pancake logical schema drift")
    if target_immutable or target_explicit_mutable != set(target):
        fail("all 17 Pancake entities must remain explicitly mutable")
    if len(parent) != 17 or logical_hash(parent) != "caf9ba372feb9e9e1370d866f1b48d08cc8f10fb261075dc516e9e6e96e65e53":
        fail("imported Uniswap V4 parent logical reference drift")
    if set(target) != set(parent):
        fail("Pancake and imported V4 parent entity sets diverged")
    differences: dict[str, dict[str, str]] = {}
    for entity in target:
        added = {key: value for key, value in target[entity].items() if key not in parent[entity]}
        missing = set(parent[entity]) - set(target[entity])
        changed = {
            key for key in set(target[entity]) & set(parent[entity])
            if target[entity][key] != parent[entity][key]
        }
        if missing or changed:
            fail(f"unexpected Pancake/V4 parent field or type difference in {entity}")
        if added:
            differences[entity] = added
    if differences != {"Pool": {"parameters": "Bytes!", "hooksRegistration": "Bytes!"}}:
        fail("Pancake/V4 parent schema gap drift")
    if set(child) - set(parent) != {"ArrakisHook"} or set(parent) - set(child):
        fail("imported V4 child ArrakisHook reference drift")
    expected_immutable = {"Transaction", "Swap", "ModifyLiquidity", "Subscribe", "Unsubscribe", "Transfer"}
    if child_immutable != expected_immutable:
        fail("imported V4 child immutable-event reference drift")
    if (
        contract.get("entity_count") != 17
        or contract.get("logical_sha256") != logical_hash(target)
        or contract.get("immutable_entities") != []
        or contract.get("all_entities_mutable") is not True
        or set(contract.get("runtime_critical_mutability_difference", [])) != expected_immutable
    ):
        fail("provenance logical schema contract drift")


def verify_profile(root: Path, lock: dict[str, object]) -> None:
    profile_payload = (root / PROFILE_PATH).read_bytes()
    if len(profile_payload) != EXPECTED_PROFILE_BYTES or sha256(profile_payload) != EXPECTED_PROFILE_SHA256:
        fail("machine-readable layout profile digest drift")
    profile_lock = lock.get("layout_profile")
    if profile_lock != {
        "path": str(PROFILE_PATH), "bytes": EXPECTED_PROFILE_BYTES, "sha256": EXPECTED_PROFILE_SHA256
    }:
        fail("layout profile provenance lock drift")
    profile = json.loads(profile_payload)
    if (
        profile.get("format_version") != 1
        or profile.get("status") != "immutable_target_contract_only"
        or profile.get("deployment", {}).get("cid") != EXPECTED_DEPLOYMENT
        or profile.get("deployment", {}).get("graft") is not None
    ):
        fail("layout profile identity or status drift")
    profile_handlers = {
        handler["name"]: handler["topic0"]
        for source in profile.get("data_sources", [])
        for handler in source.get("handlers", [])
    }
    if profile_handlers != EXPECTED_TOPICS:
        fail("layout profile event-topic contract drift")
    pool_key = profile.get("pool_key", {})
    if (
        pool_key.get("pool_id_strategy") != "authoritative_initialize_event_id_bytes32"
        or pool_key.get("recompute_pool_id") is not False
        or pool_key.get("contract_tuple_fields") != [
            "currency0", "currency1", "hooks", "poolManager", "fee", "parameters"
        ]
        or pool_key.get("parameters", {}).get("hooks_registration", {}).get("byte_slice") != [30, 32]
        or pool_key.get("parameters", {}).get("tick_spacing", {}).get("byte_slice") != [27, 30]
        or pool_key.get("parameters", {}).get("tick_spacing", {}).get("operation")
        != "reverse_then_graph_bigint_from_byte_array"
    ):
        fail("Pancake PoolKey or parameter decoding contract drift")
    fees = profile.get("fee_and_protocol", {})
    if fees != {
        "pool_fee_tier_source": "initialize.fee",
        "swap_event_fee": "decoded_for_signature_but_ignored_by_mapping",
        "swap_protocol_fee": "decoded_for_signature_but_ignored_by_mapping",
        "dynamic_lp_fee_updated_handler": False,
        "protocol_fee_updated_handler": False,
        "fee_amount_formula": "tracked_swap_amount_times_pool_fee_tier_div_1000000",
        "protocol_fee_entity_or_aggregate": False,
    }:
        fail("Pancake fee/protocol behavior contract drift")
    positions = profile.get("positions", {})
    if (
        positions.get("created_by") != "first_position_manager_transfer"
        or positions.get("owner_update") != "every_position_manager_transfer_to_address"
        or positions.get("burn_delete") is not False
        or positions.get("subscription_mutates_position") is not False
        or positions.get("unsubscription_mutates_position") is not False
        or positions.get("position_manager_modify_liquidity_handler") is not False
    ):
        fail("Pancake position/subscription/transfer behavior contract drift")
    pricing = profile.get("pricing", {})
    if (
        pricing.get("stablecoin_wrapped_native_pool_id")
        != "0x752e76950f6167b8dbb0495b957d264d61724dfa26e3dd6fad1ba820862ce9cf"
        or pricing.get("stablecoin_is_token0") is not False
        or pricing.get("wrapped_native_address") != "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
        or pricing.get("minimum_native_locked") != "10"
        or pricing.get("native_token") != {"symbol": "BNB", "name": "Binance Coin", "decimals": 18}
    ):
        fail("Pancake BSC pricing configuration drift")
    if profile.get("uniswap_v4_prior_art", {}).get("required_target_changes") != EXPECTED_REQUIRED_CHANGES:
        fail("complete Pancake implementation-gap list drift")
    if len(profile.get("remaining_gates", [])) != 4:
        fail("Pancake remaining gate list drift")


def verify_source_pin(lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    source = lock.get("exact_source")
    if not isinstance(source, dict):
        fail("exact_source must be an object")
    if (
        source.get("status") != "exact_reproduction"
        or source.get("repository") != EXPECTED_SOURCE_REPOSITORY
        or source.get("commit") != EXPECTED_SOURCE_COMMIT
        or source.get("tree") != EXPECTED_SOURCE_TREE
        or source.get("parent") != EXPECTED_SOURCE_PARENT
        or source.get("tracked_file_count") != 58
        or source.get("historical_source_ci") != EXPECTED_HISTORICAL_SOURCE_CI
        or source.get("reproduction_toolchain") != EXPECTED_TOOLCHAIN
    ):
        fail("exact source commit/tree/toolchain lock drift")
    source_files = source.get("source_files")
    actual_source_files = {
        item.get("path"): (item.get("bytes"), item.get("sha256"), item.get("git_blob"))
        for item in source_files
    } if isinstance(source_files, list) else {}
    if actual_source_files != EXPECTED_SOURCE_FILES:
        fail("exact source key-file lock drift")
    source_abis = source.get("source_abi_payloads")
    actual_source_abis = {
        item.get("path"): (item.get("bytes"), item.get("sha256"))
        for item in source_abis
    } if isinstance(source_abis, list) else {}
    if actual_source_abis != EXPECTED_SOURCE_ABIS:
        fail("exact source ABI lock drift")
    build = source.get("build", {})
    if (
        build.get("method") != "independent_byte_exact_reproduction"
        or
        build.get("commands") != [
            "npm ci --legacy-peer-deps --ignore-scripts", "npm run build"
        ]
        or build.get("generated_manifest_bytes") != 2195
        or build.get("generated_manifest_sha256")
        != "3d466cb0e39c5d02c9204feae156192984f735ef00488577d0660b8d15343ada"
        or build.get("mapping_bytes") != artifacts["mapping_wasm"]["bytes"]
        or build.get("mapping_sha256") != artifacts["mapping_wasm"]["sha256"]
        or build.get("result") != "byte_exact_to_all_deployed_child_artifacts"
    ):
        fail("exact source build lock drift")


def git_blob_hash(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def local_path_from_file(value: object) -> str:
    if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts:
        fail(f"unexpected generated-manifest path: {value!r}")
    return value


def replace_generated_files_with_cids(value: object, source_root: Path) -> object:
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key == "file":
                relative = local_path_from_file(item)
                payload = (source_root / "build" / relative).read_bytes()
                output[key] = {"/": f"/ipfs/{unixfs_file_cidv0(payload)}"}
            else:
                output[key] = replace_generated_files_with_cids(item, source_root)
        return output
    if isinstance(value, list):
        return [replace_generated_files_with_cids(item, source_root) for item in value]
    return value


def verify_exact_source_build(
    root: Path,
    source_root: Path,
    lock: dict[str, object],
    artifacts: dict[str, dict[str, object]],
) -> None:
    source = lock["exact_source"]
    for relative, expected in EXPECTED_SOURCE_FILES.items():
        payload = (source_root / relative).read_bytes()
        if (len(payload), sha256(payload), git_blob_hash(payload)) != expected:
            fail(f"exact source key-file mismatch: {relative}")
    for relative, expected in EXPECTED_SOURCE_ABIS.items():
        payload = (source_root / relative).read_bytes()
        if (len(payload), sha256(payload)) != expected:
            fail(f"exact source ABI mismatch: {relative}")

    built_manifest_payload = (source_root / "build/subgraph.yaml").read_bytes()
    if (
        len(built_manifest_payload) != source["build"]["generated_manifest_bytes"]
        or sha256(built_manifest_payload) != source["build"]["generated_manifest_sha256"]
    ):
        fail("generated exact-source manifest byte drift")
    built_manifest = yaml.safe_load(built_manifest_payload)
    deployed_manifest = yaml.safe_load(
        (root / str(artifacts["deployment"]["path"])).read_text()
    )
    if replace_generated_files_with_cids(built_manifest, source_root) != deployed_manifest:
        fail("generated manifest does not resolve exactly to deployed artifact links")

    built_artifacts = {
        "schema": "build/schema.graphql",
        "erc20_abi": "build/PoolManager/abis/ERC20.json",
        "erc20_name_bytes_abi": "build/PoolManager/abis/ERC20NameBytes.json",
        "erc20_symbol_bytes_abi": "build/PoolManager/abis/ERC20SymbolBytes.json",
        "pool_manager_abi": "build/PoolManager/abis/PoolManager.json",
        "position_manager_abi": "build/PositionManager/abis/PositionManager.json",
        "mapping_wasm": "build/PoolManager/PoolManager.wasm",
    }
    for role, relative in built_artifacts.items():
        built_payload = (source_root / relative).read_bytes()
        deployed_payload = (root / str(artifacts[role]["path"])).read_bytes()
        if built_payload != deployed_payload:
            fail(f"exact source build is not byte-identical for {role}")
    for relative, (deployed_role, _, _) in {
        "abis/ERC20.json": ("erc20_abi", 0, 0),
        "abis/ERC20NameBytes.json": ("erc20_name_bytes_abi", 0, 0),
        "abis/ERC20SymbolBytes.json": ("erc20_symbol_bytes_abi", 0, 0),
        "abis/PoolManager.json": ("pool_manager_abi", 0, 0),
        "abis/PositionManager.json": ("position_manager_abi", 0, 0),
    }.items():
        source_payload = (source_root / relative).read_bytes()
        deployed_payload = (root / str(artifacts[deployed_role]["path"])).read_bytes()
        if source_payload != deployed_payload + b"\n":
            fail(f"Graph CLI one-trailing-LF ABI normalization drift: {relative}")

    package_lock = load_json(source_root / "package-lock.json")
    if not isinstance(package_lock, dict) or package_lock.get("lockfileVersion") != 3:
        fail("exact source package-lock version drift")
    packages = package_lock.get("packages", {})
    installed_versions = {
        "graph_cli": packages["node_modules/@graphprotocol/graph-cli"]["version"],
        "graph_ts": packages["node_modules/@graphprotocol/graph-ts"]["version"],
        "assemblyscript": packages["node_modules/assemblyscript"]["version"],
        "binaryen": packages["node_modules/binaryen"]["version"],
        "typescript": packages["node_modules/typescript"]["version"],
        "npm_run_all": packages["node_modules/npm-run-all"]["version"],
    }
    for key, actual in installed_versions.items():
        if actual != EXPECTED_TOOLCHAIN[key]:
            fail(f"locked exact-source package drift: {key}")


def verify_binding(root: Path) -> None:
    binding = yaml.safe_load((root / BINDING_PATH).read_text())
    if (
        not isinstance(binding, dict)
        or binding.get("deployment") != EXPECTED_DEPLOYMENT
        or binding.get("family") != "pancakeswap-infinity-cl-bsc"
        or binding.get("chain") != "bsc"
        or binding.get("milestone") != "M5"
        or binding.get("market_snapshot")
        != {
            "measured_at": "2026-08-31T17:20:00Z",
            "queries_24h": 25405,
            "query_fees_grt_24h": "30.041",
            "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
        }
        or any(
            field != "market_snapshot"
            and (
                field.startswith(("market_", "qos_", "query_fee"))
                or "grt" in field
                or field in {"queries_24h", "query_count_24h", "fees_24h"}
            )
            for field in binding
        )
        or binding.get("eligibility", {}).get("latest", {}).get("decision") != "indeterminate"
        or binding.get("eligibility", {}).get("latest", {}).get("reason") != "no_fresh_evidence"
    ):
        fail("Pancake target binding, M5 market snapshot, or fail-closed eligibility drift")


def verify(root: Path, lock_path: Path, exact_source_root: Path | None = None) -> None:
    lock = load_json(root / lock_path)
    if not isinstance(lock, dict) or lock.get("format_version") != 1:
        fail("unsupported Pancake target lock")
    if (
        lock.get("family") != "pancakeswap-infinity-cl-bsc"
        or lock.get("implementation_status") != "immutable_target_and_exact_source_baseline_only"
        or lock.get("runtime_parity") is not False
        or lock.get("eligibility_decision") != "awaiting_same_pod_72_hour_evidence"
        or len(lock.get("remaining_gates", [])) != 4
    ):
        fail("Pancake baseline status, runtime-parity refusal, or remaining gates drift")
    artifacts = verify_artifact_lock(root, lock)
    verify_manifest(root, lock, artifacts)
    verify_schema_contract(root, lock, artifacts)
    verify_profile(root, lock)
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
        print(f"Pancake Infinity CL BSC target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified all eight CIDv0 artifacts, exact manifest and 17-entity mutable schema, "
        "V4 implementation-gap profile, exact source pin, historical-CI/reproduction "
        "toolchain distinction, and fail-closed M5 binding"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
