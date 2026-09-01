#!/usr/bin/env python3
"""Verify the immutable Uniswap V2 Base target and fail-closed source baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


DEPLOYMENT = "QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8"
SCHEMA_CID = "QmeyYQ8ZJnzuQsoXnizGXLyFSt7mcuRNkmNQxMv3pXiMnW"
FACTORY = "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"
START_BLOCK = 6_601_915
LOCK_PATH = Path("docs/provenance/uniswap-v2-base-target.json")
PROFILE_PATH = Path("uniswap-v2-base/layout-profile-v1.json")
BINDING_PATH = Path(f"uniswap-v2-base/{DEPLOYMENT}.yaml")
SOURCE_COMMIT = "6fba1a6f7304df83c08c3555bc90a38028f1435c"
SOURCE_TREE = "c80a1d0ddfb378a1fd7e9177e59a94420b01bd5e"
GENERIC_COMMIT = "970a665e15619de8ad7f686bd89412a1030d46dc"
GENERIC_TREE = "eac7466daba7f89a8c3b2e4742fcf24a155a2c24"
LOGICAL_SHA256 = "7d249e34390b4eaaeca84e0fd5638e071fcd812a10813a03d284cf94a0dff5a2"
PROFILE_CANONICAL_SHA256 = (
    "0519b31237c3ebbae5167b98d96013102c9914152fbd1b412ba6ecf3f1c3203b"
)

LOCK_SECTION_SHA256 = {
    "deployment": "4b5085167331ac007aa70edd24b325a123df87a364e556c8718a92fa564148bb",
    "artifact_lock": "41b89c98b1e558718fa8c1cf424294f9ed9148ea91dc7feaf6386e6ae4da503c",
    "layout_profile": "073bb6362f4211dae9d42378110bb0c90d02230c99547ff993fc2cb7d2b8a3d8",
    "logical_contract": "ab160572d11461936d229de50910e257ed89b62dd83f5a21a81f1d7091397083",
    "source_evidence": "127a0ace05b87311c10af806d3a6f3259162b5d14caccdd7c85f1c0f560b7ea7",
    "generic_event_extractor": "addec4e3e33a3658712102a5c45e94d381f44513a65bc86107fc0c26bde1efcc",
    "truth_gates": "7a4da0d932f4fcebe4a3f2fbd92a279ff1f6a26e9b8c2dc8af6316771780aa65",
}

EXPECTED_ROLES = {
    "deployment",
    "schema",
    "factory_abi",
    "erc20_abi",
    "erc20_symbol_bytes_abi",
    "erc20_name_bytes_abi",
    "pair_abi",
    "factory_mapping_wasm",
    "pair_mapping_wasm",
}

EXPECTED_FACTORY_HANDLER = [
    ("handleNewPair", "PairCreated(indexed address,indexed address,address,uint256)")
]
EXPECTED_PAIR_HANDLERS = [
    ("handleMint", "Mint(indexed address,uint256,uint256)"),
    ("handleBurn", "Burn(indexed address,uint256,uint256,indexed address)"),
    (
        "handleSwap",
        "Swap(indexed address,uint256,uint256,uint256,uint256,indexed address)",
    ),
    ("handleTransfer", "Transfer(indexed address,indexed address,uint256)"),
    ("handleSync", "Sync(uint112,uint112)"),
]

EXPECTED_ENTITIES = [
    "Bundle",
    "Burn",
    "Mint",
    "Pair",
    "PairDayData",
    "PairHourData",
    "PairTokenLookup",
    "Swap",
    "Token",
    "TokenDayData",
    "TokenHourData",
    "Transaction",
    "UniswapDayData",
    "UniswapFactory",
    "User",
]
EXPECTED_MUTABLE = sorted(set(EXPECTED_ENTITIES) - {"PairTokenLookup"})
EXPECTED_DERIVED = {
    "Pair": ["burns", "mints", "pairHourData", "swaps"],
    "Token": [
        "pairBase",
        "pairDayDataBase",
        "pairDayDataQuote",
        "pairQuote",
        "tokenDayData",
    ],
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
    "issue_87_complete": False,
    "issue_89_complete": False,
    "issue_93_complete": False,
}

EXPECTED_MARKET_SNAPSHOT = {
    "measured_at": "2026-08-31T17:20:00Z",
    "queries_24h": 780_953,
    "query_fees_grt_24h": "954.416540",
    "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
}

EXPECTED_ELIGIBILITY = {
    "policy": "graph-node-net-catchup-v1",
    "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
    "latest": {
        "decision": "indeterminate",
        "reason": "no_fresh_evidence",
        "measured_at": None,
        "evidence": None,
        "sha256": None,
    },
}

EXPECTED_ELIGIBILITY_CONTRACT = {
    "policy": "graph-node-net-catchup-v1",
    "threshold_days": 28,
    "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
    "copy_inventory": "every_current_copy_or_fresh_structural_absence_proof",
    "copy_selection": "fastest_healthy_copy_per_cluster_and_window",
    "required_windows": ["24h", "72h"],
    "eligible_when": "all_required_cluster_window_minima_exceed_28_days_or_are_non_converging",
    "stop_when": "any_required_cluster_window_minimum_is_at_or_below_28_days",
    "stopped_actions": ["implementation", "compute", "load"],
    "current_decision": "indeterminate_no_fresh_evidence",
}

EXPECTED_REMAINING_GATES = [
    "M0: inventory both required clusters and every current copy or fresh structural absence proof; use each cluster's fastest healthy path; both fresh stable-copy 24-hour and 72-hour forecasts must exceed 28 days or be non-converging.",
    "M0 stop: if any required cluster's fastest healthy 24-hour or 72-hour forecast is at or below 28 days, stop implementation, compute, and load; native Graph Node syncing continues.",
    "Freeze the exact ordered handler and failure contract.",
    "Implement the target-specific runtime.",
    "Prove fixed-range logical and physical differential parity.",
    "Certify VID, PoI, failure, and PostgreSQL restore semantics.",
    "Validate a paused backfill load only after every preceding gate passes.",
    "Obtain separate production activation approval.",
]

EXPECTED_M8_ROADMAP = """8. **M8 — Uniswap V2 Base** (`QmQmz5kh…`): complete the immutable target and M0
   eligibility work in [#87](https://github.com/pinax-network/substreams-backfills/issues/87),
   then the target-specific implementation in
   [#89](https://github.com/pinax-network/substreams-backfills/issues/89), then differential
   certification and paused landing in
   [#93](https://github.com/pinax-network/substreams-backfills/issues/93). M8 orders work
   only: the generic V2 extractor is decoder prior art, not a Graph-compatible writer, and
   implementation, compute, and load stop whenever either fastest-healthy 24-hour or 72-hour
   path in either required cluster is at or below 28 days."""

MILESTONE_HEADING = re.compile(r"(?m)^[0-9]+\. \*\*M[0-9]+ — ")

TARGET_FILES = {
    "README.md",
    f"{DEPLOYMENT}.yaml",
    "layout-profile-v1.json",
    "reference/abis/ERC20.json",
    "reference/abis/ERC20NameBytes.json",
    "reference/abis/ERC20SymbolBytes.json",
    "reference/abis/factory.json",
    "reference/abis/pair.json",
    "reference/deployment.yaml",
    "reference/mappings/Factory.wasm",
    "reference/mappings/Pair.wasm",
    "reference/schema.graphql",
}


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently accepting the last value."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            fail(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(payload)


def verify_false_gates(value: object, label: str) -> None:
    if value != FALSE_GATES:
        fail(f"{label} must retain the complete false truth-gate inventory")


def load_json(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                fail(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as handle:
        value = json.load(handle, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def load_yaml(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.load(handle, Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def repository_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts:
        fail(f"invalid repository path for {label}: {value!r}")
    path = (root / value).resolve()
    if path != root.resolve() and root.resolve() not in path.parents:
        fail(f"repository path escapes root for {label}: {value}")
    return path


def cid(value: object) -> str:
    if not isinstance(value, dict) or set(value) != {"/"}:
        fail(f"invalid IPFS object: {value!r}")
    location = value["/"]
    if not isinstance(location, str) or not location.startswith("/ipfs/Qm"):
        fail(f"invalid IPFS path: {location!r}")
    return location.removeprefix("/ipfs/")


def normalize_event(value: object) -> str:
    if not isinstance(value, str):
        fail("event signature must be a string")
    return re.sub(r"\s+", "", value)


def verify_lock(lock: dict[str, object]) -> None:
    if set(lock) != {
        "format_version",
        "family",
        *LOCK_SECTION_SHA256,
    }:
        fail("provenance top-level field set drift")
    if lock["format_version"] != 1 or lock["family"] != "uniswap-v2-base":
        fail("provenance identity drift")
    for section, expected_digest in LOCK_SECTION_SHA256.items():
        if canonical_sha256(lock.get(section)) != expected_digest:
            fail(f"provenance {section} contract drift")

    verify_false_gates(lock["truth_gates"], "provenance truth_gates")


def normalize(payload: bytes, mode: object) -> bytes:
    if mode == "identity":
        return payload
    if mode == "remove_one_trailing_lf":
        if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
            fail("normalization requires exactly one trailing LF")
        return payload[:-1]
    fail(f"unsupported artifact normalization: {mode!r}")


def read_uleb(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(payload) or shift > 63:
            fail("invalid WASM unsigned LEB128 value")
        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def wasm_function_exports(payload: bytes) -> list[str]:
    if payload[:8] != b"\x00asm\x01\x00\x00\x00":
        fail("invalid WASM header")
    offset = 8
    function_exports: list[str] = []
    while offset < len(payload):
        section_id = payload[offset]
        offset += 1
        section_size, offset = read_uleb(payload, offset)
        section_end = offset + section_size
        if section_end > len(payload):
            fail("WASM section extends beyond payload")
        if section_id == 7:
            count, offset = read_uleb(payload, offset)
            for _ in range(count):
                name_size, offset = read_uleb(payload, offset)
                name_end = offset + name_size
                if name_end > section_end:
                    fail("WASM export name extends beyond section")
                try:
                    name = payload[offset:name_end].decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError("WASM export name is not UTF-8") from error
                offset = name_end
                if offset >= section_end:
                    fail("WASM export is missing kind")
                kind = payload[offset]
                offset += 1
                _, offset = read_uleb(payload, offset)
                if kind == 0:
                    function_exports.append(name)
            if offset != section_end:
                fail("WASM export section has trailing bytes")
        offset = section_end
    if offset != len(payload):
        fail("WASM section parsing did not consume payload")
    return function_exports


def verify_artifacts(
    root: Path, lock: dict[str, object]
) -> dict[str, dict[str, object]]:
    records = lock["artifact_lock"]
    if not isinstance(records, list):
        fail("artifact_lock must be a list")
    by_role: dict[str, dict[str, object]] = {}
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            fail("invalid artifact record")
        role = str(item["role"])
        if role in by_role:
            fail(f"duplicate artifact role: {role}")
        by_role[role] = item
        artifact_cid = item.get("cid")
        if not isinstance(artifact_cid, str) or not re.fullmatch(
            r"Qm[1-9A-HJ-NP-Za-km-z]{44}", artifact_cid
        ):
            fail(f"invalid artifact CID for {role}")

        if "vendored_path" not in item:
            fail(f"offline target closure is missing vendored artifact {role}")

        path = repository_path(root, item["vendored_path"], role)
        payload = path.read_bytes()
        if len(payload) != item.get("vendored_bytes"):
            fail(f"vendored byte count drift for {role}")
        if sha256(payload) != item.get("vendored_sha256"):
            fail(f"vendored digest drift for {role}")
        source_payload = normalize(payload, item.get("normalization"))
        if len(source_payload) != item.get("source_bytes"):
            fail(f"source byte count drift for {role}")
        if sha256(source_payload) != item.get("source_sha256"):
            fail(f"source digest drift for {role}")
        if role.endswith("_abi"):
            decoded = json.loads(source_payload)
            if not isinstance(decoded, list):
                fail(f"ABI artifact must be a JSON array: {role}")
        if role.endswith("_mapping_wasm"):
            handler_exports = [
                name
                for name in wasm_function_exports(source_payload)
                if name.startswith("handle")
            ]
            if handler_exports != item.get("exports"):
                fail(f"mapping handler export drift for {role}")

    if set(by_role) != EXPECTED_ROLES:
        fail(f"artifact role inventory drift: {sorted(set(by_role) ^ EXPECTED_ROLES)}")
    return by_role


def abi_contract(mapping: dict[str, object]) -> list[tuple[str, str]]:
    abis = mapping.get("abis")
    if not isinstance(abis, list):
        fail("mapping ABI inventory must be a list")
    result: list[tuple[str, str]] = []
    for item in abis:
        if not isinstance(item, dict):
            fail("mapping ABI entry must be an object")
        result.append((str(item.get("name")), cid(item.get("file"))))
    return result


def handler_contract(mapping: dict[str, object]) -> list[tuple[str, str]]:
    handlers = mapping.get("eventHandlers")
    if not isinstance(handlers, list):
        fail("eventHandlers must be a list")
    result: list[tuple[str, str]] = []
    for item in handlers:
        if not isinstance(item, dict) or set(item) != {"event", "handler"}:
            fail("event handler field set drift")
        result.append((str(item["handler"]), normalize_event(item["event"])))
    return result


def verify_manifest(root: Path, artifacts: dict[str, dict[str, object]]) -> None:
    path = repository_path(root, artifacts["deployment"]["vendored_path"], "deployment")
    manifest = load_yaml(path)
    if set(manifest) != {
        "dataSources",
        "description",
        "repository",
        "schema",
        "specVersion",
        "templates",
    }:
        fail("manifest top-level shape drift")
    if manifest["specVersion"] != "0.0.8":
        fail("manifest specVersion drift")
    if manifest["repository"] != "https://github.com/Uniswap/uniswap-v2-subgraph":
        fail("manifest repository identity drift")
    schema = manifest["schema"]
    if (
        not isinstance(schema, dict)
        or set(schema) != {"file"}
        or cid(schema["file"]) != SCHEMA_CID
    ):
        fail("manifest schema binding drift")

    data_sources = manifest["dataSources"]
    templates = manifest["templates"]
    if not isinstance(data_sources, list) or len(data_sources) != 1:
        fail("manifest must contain exactly one Factory data source")
    if not isinstance(templates, list) or len(templates) != 1:
        fail("manifest must contain exactly one Pair template")
    factory = data_sources[0]
    pair = templates[0]
    if not isinstance(factory, dict) or not isinstance(pair, dict):
        fail("manifest components must be objects")
    if set(factory) != {"kind", "mapping", "name", "network", "source"}:
        fail("Factory data-source shape drift")
    if set(pair) != {"kind", "mapping", "name", "network", "source"}:
        fail("Pair template shape drift")
    if (factory["kind"], factory["name"], factory["network"]) != (
        "ethereum/contract",
        "Factory",
        "base",
    ):
        fail("Factory data-source identity drift")
    if factory["source"] != {
        "abi": "Factory",
        "address": FACTORY,
        "startBlock": START_BLOCK,
    }:
        fail("Factory address/start-block binding drift")
    if (pair["kind"], pair["name"], pair["network"], pair["source"]) != (
        "ethereum/contract",
        "Pair",
        "base",
        {"abi": "Pair"},
    ):
        fail("Pair dynamic-template identity drift")

    factory_mapping = factory["mapping"]
    pair_mapping = pair["mapping"]
    if not isinstance(factory_mapping, dict) or not isinstance(pair_mapping, dict):
        fail("mapping records must be objects")
    expected_mapping_fields = {
        "abis",
        "apiVersion",
        "entities",
        "eventHandlers",
        "file",
        "kind",
        "language",
    }
    if (
        set(factory_mapping) != expected_mapping_fields
        or set(pair_mapping) != expected_mapping_fields
    ):
        fail("mapping field set drift")
    for name, mapping in (("Factory", factory_mapping), ("Pair", pair_mapping)):
        if (
            mapping["apiVersion"] != "0.0.7"
            or mapping["entities"] != ["Pair", "Token"]
            or mapping["kind"] != "ethereum/events"
            or mapping["language"] != "wasm/assemblyscript"
        ):
            fail(f"{name} mapping shape drift")

    if abi_contract(factory_mapping) != [
        ("Factory", str(artifacts["factory_abi"]["cid"])),
        ("ERC20", str(artifacts["erc20_abi"]["cid"])),
        ("ERC20SymbolBytes", str(artifacts["erc20_symbol_bytes_abi"]["cid"])),
        ("ERC20NameBytes", str(artifacts["erc20_name_bytes_abi"]["cid"])),
    ]:
        fail("Factory ABI inventory drift")
    if abi_contract(pair_mapping) != [
        ("Pair", str(artifacts["pair_abi"]["cid"])),
        ("Factory", str(artifacts["factory_abi"]["cid"])),
    ]:
        fail("Pair ABI inventory drift")
    if cid(factory_mapping["file"]) != artifacts["factory_mapping_wasm"]["cid"]:
        fail("Factory mapping CID drift")
    if cid(pair_mapping["file"]) != artifacts["pair_mapping_wasm"]["cid"]:
        fail("Pair mapping CID drift")
    if handler_contract(factory_mapping) != [
        (name, normalize_event(event)) for name, event in EXPECTED_FACTORY_HANDLER
    ]:
        fail("Factory handler contract drift")
    if handler_contract(pair_mapping) != [
        (name, normalize_event(event)) for name, event in EXPECTED_PAIR_HANDLERS
    ]:
        fail("Pair handler order or signature drift")


def parse_schema(
    path: Path,
) -> tuple[dict[str, dict[str, str]], set[str], set[str], dict[str, list[str]]]:
    entities: dict[str, dict[str, str]] = {}
    immutable: set[str] = set()
    mutable: set[str] = set()
    derived: dict[str, list[str]] = {}
    current: str | None = None
    declaration = re.compile(
        r"^type\s+([_A-Za-z][_0-9A-Za-z]*)\s+@entity(?:\(immutable:\s*(true|false)\))?\s*\{"
    )
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        match = declaration.match(line)
        if match:
            current = match.group(1)
            if current in entities:
                fail(f"duplicate schema entity: {current}")
            entities[current] = {}
            if match.group(2) == "true":
                immutable.add(current)
            else:
                mutable.add(current)
            continue
        if current and line == "}":
            current = None
            continue
        if current:
            field = re.match(
                r"^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)", line
            )
            if field:
                name = field.group(1)
                if name in entities[current]:
                    fail(f"duplicate schema field: {current}.{name}")
                entities[current][name] = field.group(2)
                if "@derivedFrom" in line:
                    derived.setdefault(current, []).append(name)
    return (
        entities,
        immutable,
        mutable,
        {key: sorted(value) for key, value in derived.items()},
    )


def verify_schema(
    root: Path, artifacts: dict[str, dict[str, object]], lock: dict[str, object]
) -> None:
    path = repository_path(root, artifacts["schema"]["vendored_path"], "schema")
    entities, immutable, mutable, derived = parse_schema(path)
    logical = sha256(
        json.dumps(entities, sort_keys=True, separators=(",", ":")).encode()
    )
    contract = lock["logical_contract"]
    if not isinstance(contract, dict):
        fail("logical contract must be an object")
    if sorted(entities) != EXPECTED_ENTITIES or len(entities) != 15:
        fail("schema entity inventory drift")
    if sum(len(fields) for fields in entities.values()) != 157:
        fail("schema field count drift")
    if logical != LOGICAL_SHA256 or logical != contract.get("logical_sha256"):
        fail("schema logical digest drift")
    if sorted(immutable) != ["PairTokenLookup"] or sorted(mutable) != EXPECTED_MUTABLE:
        fail("schema mutability drift")
    if derived != EXPECTED_DERIVED:
        fail("schema derived-field contract drift")


def verify_profile(root: Path, lock: dict[str, object]) -> None:
    profile_record = lock["layout_profile"]
    if not isinstance(profile_record, dict):
        fail("layout_profile lock must be an object")
    path = repository_path(root, profile_record["path"], "layout profile")
    payload = path.read_bytes()
    if len(payload) != profile_record.get("bytes") or sha256(
        payload
    ) != profile_record.get("sha256"):
        fail("layout profile byte lock drift")
    profile = load_json(path)
    if canonical_sha256(profile) != PROFILE_CANONICAL_SHA256:
        fail("layout profile semantic contract drift")
    if set(profile) != {
        "format_version",
        "family",
        "deployment",
        "target",
        "schema",
        "mapping_behavior",
        "generic_event_extractor",
        "eligibility_contract",
        "remaining_gates",
        "truth_gates",
    }:
        fail("layout profile top-level inventory drift")
    if (
        profile.get("format_version") != 1
        or profile.get("deployment") != DEPLOYMENT
        or profile.get("family") != "uniswap-v2-base"
        or profile.get("eligibility_contract") != EXPECTED_ELIGIBILITY_CONTRACT
        or profile.get("remaining_gates") != EXPECTED_REMAINING_GATES
    ):
        fail("layout profile identity drift")
    generic = profile.get("generic_event_extractor")
    if not isinstance(generic, dict):
        fail("generic extractor profile must be an object")
    if any(
        generic.get(field) is not False
        for field in (
            "pair_transfer_supported",
            "target_factory_filter_supported",
            "dynamic_pair_membership_filter_supported",
            "target_start_block_bound",
        )
    ):
        fail("generic event extractor gap was improperly promoted")
    verify_false_gates(profile.get("truth_gates"), "layout profile truth_gates")


def verify_binding(root: Path) -> None:
    binding = load_yaml(root / BINDING_PATH)
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
        binding.get("deployment") != DEPLOYMENT
        or binding.get("family") != "uniswap-v2-base"
        or binding.get("display_name") != "Uniswap V2 Base"
        or binding.get("schema") != SCHEMA_CID
        or binding.get("chain") != "base"
        or binding.get("milestone") != "M8"
        or binding.get("market_snapshot") != EXPECTED_MARKET_SNAPSHOT
        or binding.get("target_reference")
        != {
            "provenance": str(LOCK_PATH),
            "deployment_manifest": "uniswap-v2-base/reference/deployment.yaml",
            "status": "immutable_target_pinned_source_revision_unresolved",
        }
    ):
        fail("target binding identity, M8, market snapshot, or source status drift")
    verify_false_gates(binding.get("truth_gates"), "binding truth_gates")
    if binding.get("eligibility") != EXPECTED_ELIGIBILITY:
        fail("target binding must remain fail-closed without fresh M0 evidence")


def verify_roadmap(root: Path) -> None:
    readme = (root / "README.md").read_text(encoding="utf-8")
    marker = "8. **M8 — Uniswap V2 Base**"
    if readme.count(marker) != 1:
        fail("M8 roadmap entry inventory drift")
    _, tail = readme.split(marker, 1)
    next_milestone = MILESTONE_HEADING.search(tail)
    if next_milestone is None:
        section = tail.split("\n\n", 1)[0]
    else:
        section = tail[: next_milestone.start()].rstrip("\n")
    actual = marker + section
    work_items = re.findall(
        r"https://github\.com/pinax-network/substreams-backfills/issues/([0-9]+)",
        actual,
    )
    if actual != EXPECTED_M8_ROADMAP or work_items != ["87", "89", "93"]:
        fail("M8 roadmap or #87 -> #89 -> #93 work-item order drift")


def verify_target_file_inventory(root: Path) -> None:
    target = root / "uniswap-v2-base"
    files = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    if files != TARGET_FILES:
        fail(f"target file inventory drift: {sorted(files ^ TARGET_FILES)}")


def git_value(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"git command failed for {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def git_bytes(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        fail(
            f"git command failed for {root}: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def verify_source_records(root: Path, records: object, label: str) -> None:
    if not isinstance(records, list) or not records:
        fail(f"{label} records must be a non-empty list")
    for record in records:
        if not isinstance(record, dict):
            fail(f"{label} record must be an object")
        path = repository_path(root, record.get("path"), label)
        payload = path.read_bytes()
        if len(payload) != record.get("bytes") or sha256(payload) != record.get(
            "sha256"
        ):
            fail(f"{label} source payload drift: {record.get('path')}")
        if git_value(root, "hash-object", str(path)) != record.get("git_blob"):
            fail(f"{label} Git blob drift: {record.get('path')}")


def verify_behavioral_source(root: Path, lock: dict[str, object]) -> None:
    evidence = lock["source_evidence"]
    if not isinstance(evidence, dict):
        fail("source evidence must be an object")
    if git_value(root, "rev-parse", "HEAD^{commit}") != SOURCE_COMMIT:
        fail("behavioral source commit drift")
    if git_value(root, "show", "-s", "--format=%T", "HEAD") != SOURCE_TREE:
        fail("behavioral source tree drift")
    verify_source_records(root, evidence.get("source_records"), "behavioral source")
    if any(
        (root / name).exists()
        for name in ("yarn.lock", "package-lock.json", "pnpm-lock.yaml")
    ):
        fail("behavioral candidate unexpectedly gained a dependency lockfile")
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if package.get("devDependencies", {}).get("@graphprotocol/graph-cli") != "^0.64.1":
        fail("Graph CLI constraint drift")
    if package.get("devDependencies", {}).get("@graphprotocol/graph-ts") != "^0.32.0":
        fail("Graph TS constraint drift")
    config = json.loads((root / "config/base/config.json").read_text(encoding="utf-8"))
    if config != {
        "network": "base",
        "factory": FACTORY,
        "startblock": str(START_BLOCK),
    }:
        fail("behavioral source Base target config drift")
    helpers = (root / "src/common/helpers.ts").read_text(encoding="utf-8")
    if (
        "ERC20BigDecimals.bind(tokenAddress)" not in helpers
        or "BigInt.fromI32(255)" not in helpers
    ):
        fail("behavioral source decimals overflow guard drift")
    template = (root / "v2-subgraph.template.yaml").read_text(encoding="utf-8")
    if "name: ERC20BigDecimals" not in template:
        fail("behavioral source BigDecimals ABI dependency drift")
    source_schema = (root / "src/v2/schema.graphql").read_bytes()
    if (
        sha256(source_schema)
        == "310d8ce01f22505f20f8654e60fb67ac29a0a0c11d7e4fc19d57f5c23b4f1d97"
    ):
        fail("source evidence contradiction disappeared; re-audit before promotion")

    history = evidence.get("schema_history_search")
    if not isinstance(history, dict):
        fail("schema history search must be an object")
    revisions = history.get("revisions")
    if not isinstance(revisions, list) or len(revisions) != 7:
        fail("schema history revision inventory drift")
    seen_commits: set[str] = set()
    seen_blobs: set[str] = set()
    target_matches = 0
    for revision in revisions:
        if not isinstance(revision, dict):
            fail("schema history revision must be an object")
        commit = str(revision.get("commit"))
        if commit in seen_commits:
            fail(f"duplicate schema history commit: {commit}")
        seen_commits.add(commit)
        if git_value(root, "rev-parse", f"{commit}^{{commit}}") != commit:
            fail(f"schema history commit drift: {commit}")
        if git_value(root, "show", "-s", "--format=%T", commit) != revision.get("tree"):
            fail(f"schema history tree drift: {commit}")
        blob = git_value(root, "rev-parse", f"{commit}:src/v2/schema.graphql")
        if blob != revision.get("schema_git_blob"):
            fail(f"schema history Git blob drift: {commit}")
        seen_blobs.add(blob)
        payload = git_bytes(root, "show", f"{commit}:src/v2/schema.graphql")
        if len(payload) != revision.get("schema_bytes") or sha256(
            payload
        ) != revision.get("schema_sha256"):
            fail(f"schema history payload drift: {commit}")
        if (
            sha256(payload)
            == "310d8ce01f22505f20f8654e60fb67ac29a0a0c11d7e4fc19d57f5c23b4f1d97"
        ):
            target_matches += 1
    if len(seen_blobs) != history.get(
        "unique_blobs_checked"
    ) or target_matches != history.get("exact_target_matches"):
        fail("schema history aggregate drift")
    if len(seen_commits) != history.get("revisions_checked"):
        fail("schema history revision count drift")


def verify_generic_source(root: Path, lock: dict[str, object]) -> None:
    evidence = lock["generic_event_extractor"]
    if not isinstance(evidence, dict):
        fail("generic source evidence must be an object")
    if git_value(root, "rev-parse", "HEAD^{commit}") != GENERIC_COMMIT:
        fail("generic extractor commit drift")
    if git_value(root, "show", "-s", "--format=%T", "HEAD") != GENERIC_TREE:
        fail("generic extractor tree drift")
    verify_source_records(root, evidence.get("records"), "generic extractor")
    lib = (root / "dex/uniswap-v2/src/lib.rs").read_text(encoding="utf-8")
    proto = (root / "proto/v1/dex/uniswap-v2.proto").read_text(encoding="utf-8")
    yaml_text = (root / "dex/uniswap-v2/substreams.yaml").read_text(encoding="utf-8")
    for event in ("Swap", "Mint", "Burn", "Sync", "PairCreated"):
        if f"events::{event}::match_and_decode(log)" not in lib:
            fail(f"generic extractor lost {event} decoder")
    if "events::Transfer::match_and_decode" in lib or re.search(
        r"\bTransfer\s+transfer\s*=", proto
    ):
        fail("generic extractor unexpectedly gained Pair Transfer; re-audit required")
    if (
        FACTORY.lower() in lib.lower()
        or "PairCreated::match_and_decode(log)" not in lib
    ):
        fail("generic extractor target Factory scope contract drift")
    if "PairCreated" not in proto or "Transfer" in proto:
        fail("generic extractor protobuf event inventory drift")
    if "params:" in yaml_text or "store" in yaml_text.lower():
        fail(
            "generic extractor unexpectedly gained target parameters or store filtering"
        )


def verify(root: Path, source_root: Path | None, generic_root: Path | None) -> None:
    lock = load_json(root / LOCK_PATH)
    verify_lock(lock)
    artifacts = verify_artifacts(root, lock)
    verify_manifest(root, artifacts)
    verify_schema(root, artifacts, lock)
    verify_profile(root, lock)
    verify_binding(root)
    verify_roadmap(root)
    verify_target_file_inventory(root)
    if (source_root is None) != (generic_root is None):
        fail("--source-root and --generic-source-root must be supplied together")
    if source_root is not None and generic_root is not None:
        verify_behavioral_source(source_root.resolve(), lock)
        verify_generic_source(generic_root.resolve(), lock)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--generic-source-root", type=Path)
    args = parser.parse_args()
    try:
        verify(args.root.resolve(), args.source_root, args.generic_source_root)
        scope = "target/layout"
        if args.source_root is not None:
            scope += "/behavioral-source/generic-extractor"
        print(
            f"verified Uniswap V2 Base {scope}: deployment={DEPLOYMENT} "
            "entities=15 fields=157 work_milestone=M8 eligibility=M0_indeterminate "
            "source_revision_pinned=false source_reproducible=false readiness=false"
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"Uniswap V2 Base target verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
