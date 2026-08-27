#!/usr/bin/env python3
"""Verify the immutable Uniswap V3 Matic deployment baseline and gap contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml


LOCK_PATH = Path("provenance/uniswap-v3-matic-target.json")
EXPECTED_DEPLOYMENT = "QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3"
EXPECTED_SCHEMA = "QmVYKvi799Cpg4WVXjhSWjRXNcNg4p1JQxj1WBdbcfHvoq"
EXPECTED_SOURCE_STATUS = "candidate_not_exact_mapping_reproduction"


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> object:
    with path.open() as handle:
        return json.load(handle)


def cid_from_file(value: object) -> str:
    if not isinstance(value, dict) or set(value) != {"/"}:
        fail(f"unexpected IPFS file value: {value!r}")
    location = value["/"]
    if not isinstance(location, str) or not location.startswith("/ipfs/Qm"):
        fail(f"unexpected IPFS location: {location!r}")
    return location.removeprefix("/ipfs/")


def normalize_source_bytes(payload: bytes, normalization: str) -> bytes:
    if normalization == "identity":
        return payload
    if normalization == "remove_one_trailing_lf":
        if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
            fail("ABI normalization requires exactly one vendored trailing LF")
        return payload[:-1]
    fail(f"unknown normalization: {normalization}")


def verify_artifact_lock(root: Path, lock: dict[str, object]) -> dict[str, dict[str, object]]:
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
        if vendored_path is None:
            for required in ("source_bytes", "source_sha256"):
                if required not in record:
                    fail(f"unvendored {role} is missing {required}")
            continue
        if not isinstance(vendored_path, str):
            fail(f"invalid vendored path for {role}")
        path = root / vendored_path
        payload = path.read_bytes()
        if len(payload) != record.get("vendored_bytes"):
            fail(f"vendored byte count drift for {role}")
        if sha256(payload) != record.get("vendored_sha256"):
            fail(f"vendored digest drift for {role}")

        source_payload = normalize_source_bytes(payload, str(record.get("normalization")))
        if len(source_payload) != record.get("source_bytes"):
            fail(f"source byte count drift for {role}")
        if sha256(source_payload) != record.get("source_sha256"):
            fail(f"source digest drift for {role}")
        if role.endswith("_abi"):
            json.loads(source_payload)

    expected_roles = {
        "deployment",
        "schema",
        "factory_abi",
        "erc20_abi",
        "erc20_symbol_bytes_abi",
        "erc20_name_bytes_abi",
        "pool_abi",
        "factory_mapping_wasm",
        "pool_mapping_wasm",
    }
    if set(by_role) != expected_roles:
        fail(f"artifact roles drift: {sorted(set(by_role) ^ expected_roles)}")
    return by_role


def normalize_event(event: str) -> str:
    return re.sub(r"\s+", "", event)


def abi_contract(mapping: dict[str, object]) -> list[tuple[str, str]]:
    entries = mapping.get("abis")
    if not isinstance(entries, list):
        fail("mapping ABI contract must be a list")
    return [(str(entry.get("name")), cid_from_file(entry.get("file"))) for entry in entries]


def verify_manifest(root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    path = root / str(artifacts["deployment"]["vendored_path"])
    manifest = yaml.safe_load(path.read_text())
    deployment = lock["deployment"]

    if deployment.get("data_sources") != ["Factory"] or deployment.get("templates") != ["Pool"]:
        fail("deployment component inventory drift")
    if deployment.get("features") != ["nonFatalErrors", "grafting"]:
        fail("deployment feature lock drift")
    if deployment.get("position_manager") is not False or deployment.get("flash_handler") is not False:
        fail("deployment absence contract drift")

    if manifest.get("specVersion") != deployment["spec_version"]:
        fail("manifest specVersion drift")
    if manifest.get("repository") != "https://github.com/Uniswap/uniswap-v3-subgraph":
        fail("manifest source repository drift")
    if manifest.get("features") != ["nonFatalErrors", "grafting"]:
        fail("manifest feature contract drift")
    if "graft" in manifest:
        fail("target manifest unexpectedly gained a concrete graft")
    if cid_from_file(manifest["schema"]["file"]) != EXPECTED_SCHEMA:
        fail("manifest schema CID drift")

    data_sources = manifest.get("dataSources")
    templates = manifest.get("templates")
    if not isinstance(data_sources, list) or len(data_sources) != 1:
        fail("expected exactly one Factory data source")
    if not isinstance(templates, list) or len(templates) != 1:
        fail("expected exactly one Pool template")

    factory = data_sources[0]
    factory_mapping = factory["mapping"]
    if (
        factory.get("name") != "Factory"
        or factory.get("network") != "matic"
        or factory.get("kind") != "ethereum/contract"
    ):
        fail("Factory data-source identity drift")
    if factory["source"] != {
        "abi": "Factory",
        "address": deployment["factory"],
        "startBlock": deployment["start_block"],
    }:
        fail("Factory source contract drift")
    if factory_mapping.get("apiVersion") != deployment["mapping_api_version"]:
        fail("Factory mapping apiVersion drift")
    if (
        factory_mapping.get("kind") != "ethereum/events"
        or factory_mapping.get("language") != "wasm/assemblyscript"
        or factory_mapping.get("entities") != ["Pool", "Token"]
    ):
        fail("Factory mapping shape drift")
    if abi_contract(factory_mapping) != [
        ("Factory", artifacts["factory_abi"]["cid"]),
        ("ERC20", artifacts["erc20_abi"]["cid"]),
        ("ERC20SymbolBytes", artifacts["erc20_symbol_bytes_abi"]["cid"]),
        ("ERC20NameBytes", artifacts["erc20_name_bytes_abi"]["cid"]),
        ("Pool", artifacts["pool_abi"]["cid"]),
    ]:
        fail("Factory ABI inventory drift")
    if cid_from_file(factory_mapping["file"]) != artifacts["factory_mapping_wasm"]["cid"]:
        fail("Factory mapping CID drift")
    factory_handlers = factory_mapping.get("eventHandlers")
    if not isinstance(factory_handlers, list) or [entry.get("handler") for entry in factory_handlers] != [
        "handlePoolCreated"
    ]:
        fail("Factory handler contract drift")
    if normalize_event(factory_handlers[0].get("event", "")) != normalize_event(
        "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)"
    ):
        fail("Factory event signature drift")

    pool = templates[0]
    pool_mapping = pool["mapping"]
    if (
        pool.get("name") != "Pool"
        or pool.get("network") != "matic"
        or pool.get("kind") != "ethereum/contract"
    ):
        fail("Pool template identity drift")
    if pool.get("source") != {"abi": "Pool"}:
        fail("Pool source contract drift")
    if pool_mapping.get("apiVersion") != deployment["mapping_api_version"]:
        fail("Pool mapping apiVersion drift")
    if (
        pool_mapping.get("kind") != "ethereum/events"
        or pool_mapping.get("language") != "wasm/assemblyscript"
        or pool_mapping.get("entities") != ["Pool", "Token"]
    ):
        fail("Pool mapping shape drift")
    if abi_contract(pool_mapping) != [
        ("Pool", artifacts["pool_abi"]["cid"]),
        ("Factory", artifacts["factory_abi"]["cid"]),
        ("ERC20", artifacts["erc20_abi"]["cid"]),
    ]:
        fail("Pool ABI inventory drift")
    if cid_from_file(pool_mapping["file"]) != artifacts["pool_mapping_wasm"]["cid"]:
        fail("Pool mapping CID drift")

    expected_handlers = [
        "handleInitialize",
        "handleSwap",
        "handleMint",
        "handleBurn",
        "handleCollect",
    ]
    handlers = pool_mapping.get("eventHandlers")
    if not isinstance(handlers, list) or [entry.get("handler") for entry in handlers] != expected_handlers:
        fail("Pool handler order or set drift")
    if any(entry.get("handler") == "handleFlash" for entry in handlers):
        fail("target manifest unexpectedly gained Flash")

    expected_events = [
        "Initialize(uint160,int24)",
        "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24)",
        "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
        "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
        "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)",
    ]
    if [normalize_event(entry["event"]) for entry in handlers] != [
        normalize_event(event) for event in expected_events
    ]:
        fail("Pool event signatures drift")


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


def contract_diff(
    matic: dict[str, dict[str, str]], qma8: dict[str, dict[str, str]]
) -> tuple[list[str], dict[str, dict[str, object]]]:
    missing = sorted(set(qma8) - set(matic))
    differences: dict[str, dict[str, object]] = {}
    for entity in sorted(set(matic) & set(qma8)):
        matic_fields = matic[entity]
        qma8_fields = qma8[entity]
        entry: dict[str, object] = {}
        missing_fields = sorted(set(qma8_fields) - set(matic_fields))
        if missing_fields:
            entry["missing_from_matic"] = missing_fields
        type_differences = {
            field: [matic_fields[field], qma8_fields[field]]
            for field in sorted(set(matic_fields) & set(qma8_fields))
            if matic_fields[field] != qma8_fields[field]
        }
        if type_differences:
            entry["type_differences"] = type_differences
        if entry:
            differences[entity] = entry
    return missing, differences


def verify_schema(root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    contract = lock["logical_contract"]
    matic, immutable, mutable = parse_schema(root / str(artifacts["schema"]["vendored_path"]))
    qma8, _, _ = parse_schema(root / "uniswap-v3/source/schema.graphql")

    if sorted(matic) != contract["entities"] or len(matic) != contract["entity_count"]:
        fail("Matic entity set drift")
    if logical_hash(matic) != contract["logical_sha256"]:
        fail("Matic logical schema digest drift")
    if sorted(immutable) != contract["immutable_entities"]:
        fail("Matic immutable entity contract drift")
    if sorted(mutable) != contract["mutable_entities"]:
        fail("Matic mutable entity contract drift")
    if len(qma8) != contract["qma8_entity_count"] or logical_hash(qma8) != contract["qma8_logical_sha256"]:
        fail("Qma8 logical reference drift")

    missing, differences = contract_diff(matic, qma8)
    if missing != contract["missing_from_matic"]:
        fail("Matic missing-entity gap list drift")
    if differences != contract["field_differences"]:
        fail("Matic field/type gap list drift")


def verify_source_boundary(lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    candidate = lock.get("source_candidate")
    if not isinstance(candidate, dict):
        fail("source_candidate must be an object")
    if candidate.get("status") != EXPECTED_SOURCE_STATUS:
        fail("source candidate must remain explicitly unproven until mapping bytes reproduce")
    probe = candidate.get("locked_build_probe")
    if not isinstance(probe, dict) or probe.get("result") != "does_not_match_deployed_mapping_bytes":
        fail("source build-probe boundary drift")
    if probe.get("factory_wasm_sha256") == artifacts["factory_mapping_wasm"]["source_sha256"]:
        fail("Factory build probe unexpectedly matches; update and review the source pin")
    if probe.get("pool_wasm_sha256") == artifacts["pool_mapping_wasm"]["source_sha256"]:
        fail("Pool build probe unexpectedly matches; update and review the source pin")
    for key in ("branch_commit", "merge_commit", "tree"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(candidate.get(key, ""))):
            fail(f"invalid source candidate {key}")
    remaining = lock.get("remaining_gates")
    if not isinstance(remaining, list) or len(remaining) != 3:
        fail("remaining Matic gates must stay explicit")


def verify(root: Path, lock_path: Path) -> None:
    lock = load_json(root / lock_path)
    if not isinstance(lock, dict) or lock.get("format_version") != 1:
        fail("unsupported Matic target lock")
    deployment = lock.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("cid") != EXPECTED_DEPLOYMENT:
        fail("deployment identity drift")
    artifacts = verify_artifact_lock(root, lock)
    verify_manifest(root, lock, artifacts)
    verify_schema(root, lock, artifacts)
    verify_source_boundary(lock, artifacts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    args = parser.parse_args()
    try:
        verify(args.root.resolve(), args.lock)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"Uniswap V3 Matic target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified immutable Matic deployment/schema/ABI artifacts, exact manifest shape, "
        "16-entity gap contract, mapping pins, and the deliberately unproven source boundary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
