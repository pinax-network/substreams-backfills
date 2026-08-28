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


LOCK_PATH = Path("docs/provenance/uniswap-v3-matic-target.json")
EXPECTED_DEPLOYMENT = "QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3"
EXPECTED_SCHEMA = "QmVYKvi799Cpg4WVXjhSWjRXNcNg4p1JQxj1WBdbcfHvoq"
EXPECTED_SOURCE_STATUS = "exact_reproduction"
EXPECTED_SOURCE_COMMIT = "d07374a05719e68a10a339f79cdfbc048807cfdc"
EXPECTED_SOURCE_TREE = "8f5cefd138068952bee909522a0f1d88fdc87b42"


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


def verify_source_pin(lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    source = lock.get("exact_source")
    if not isinstance(source, dict):
        fail("exact_source must be an object")
    if source.get("status") != EXPECTED_SOURCE_STATUS:
        fail("Matic source must remain bound to the exact reproduction")
    if source.get("repository") != "https://github.com/Uniswap/v3-subgraph":
        fail("exact source repository drift")
    if source.get("earliest_exact_commit") != EXPECTED_SOURCE_COMMIT:
        fail("earliest exact source commit drift")
    if source.get("tree") != EXPECTED_SOURCE_TREE:
        fail("exact source tree drift")
    for key in ("earliest_exact_commit", "mainline_equivalent_commit", "tree"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(source.get(key, ""))):
            fail(f"invalid exact source {key}")

    build = source.get("build")
    if not isinstance(build, dict) or build.get("result") != "byte_exact_to_deployed_mapping_objects":
        fail("exact source build result drift")
    for prefix, role in (
        ("factory", "factory_mapping_wasm"),
        ("pool", "pool_mapping_wasm"),
    ):
        if build.get(f"{prefix}_wasm_bytes") != artifacts[role]["source_bytes"]:
            fail(f"{prefix} exact source byte count drift")
        if build.get(f"{prefix}_wasm_sha256") != artifacts[role]["source_sha256"]:
            fail(f"{prefix} exact source digest drift")

    toolchain = source.get("toolchain")
    if toolchain != {
        "reference_node": "18.18.0",
        "reference_corepack": "0.19.0",
        "yarn": "1.22.22",
        "graph_cli": "0.64.1",
        "graph_ts": "0.38.1",
        "assemblyscript_root": "0.19.23",
        "assemblyscript_graph_ts_nested": "0.27.31",
    }:
        fail("exact source toolchain drift")

    source_files = source.get("source_files")
    if not isinstance(source_files, list) or len(source_files) != 6:
        fail("exact source file lock drift")
    if {entry.get("path") for entry in source_files if isinstance(entry, dict)} != {
        "package.json",
        "yarn.lock",
        "script/build.ts",
        "config/matic/chain.ts",
        "config/matic/config.json",
        "src/v3/schema.graphql",
    }:
        fail("exact source file inventory drift")
    remaining = lock.get("remaining_gates")
    if not isinstance(remaining, list) or len(remaining) != 2:
        fail("remaining Matic gates must stay explicit")


def manifest_semantic_shape(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "<content-addressed-artifact>" if key == "file" else manifest_semantic_shape(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [manifest_semantic_shape(item) for item in value]
    return value


def verify_exact_source_build(
    root: Path,
    source_root: Path,
    lock: dict[str, object],
    artifacts: dict[str, dict[str, object]],
) -> None:
    source = lock["exact_source"]
    deployed_manifest = yaml.safe_load(
        (root / str(artifacts["deployment"]["vendored_path"])).read_text()
    )
    built_manifest = yaml.safe_load((source_root / "build/subgraph.yaml").read_text())
    if manifest_semantic_shape(built_manifest) != manifest_semantic_shape(deployed_manifest):
        fail("exact source generated manifest is not semantically identical to the deployment")

    deployed_schema = (root / str(artifacts["schema"]["vendored_path"])).read_bytes()
    normalized_schema, replacements = re.subn(
        rb"@entity\(immutable: (?:true|false)\)", b"@entity", deployed_schema
    )
    normalization = source["schema_normalization"]
    if replacements != normalization["remove_explicit_immutable_arguments"]:
        fail("deployed schema immutable-argument normalization drift")
    if len(normalized_schema) != normalization["source_bytes"]:
        fail("normalized exact source schema byte count drift")
    if sha256(normalized_schema) != normalization["source_sha256"]:
        fail("normalized exact source schema digest drift")
    for schema_path in ("src/v3/schema.graphql", "build/schema.graphql"):
        if (source_root / schema_path).read_bytes() != normalized_schema:
            fail(f"exact source schema mismatch: {schema_path}")

    built_artifacts = {
        "factory_abi": "build/Factory/abis/factory.json",
        "erc20_abi": "build/Factory/abis/ERC20.json",
        "erc20_symbol_bytes_abi": "build/Factory/abis/ERC20SymbolBytes.json",
        "erc20_name_bytes_abi": "build/Factory/abis/ERC20NameBytes.json",
        "pool_abi": "build/Factory/abis/pool.json",
        "factory_mapping_wasm": "build/Factory/Factory.wasm",
        "pool_mapping_wasm": "build/templates/Pool/Pool.wasm",
    }
    for role, relative_path in built_artifacts.items():
        payload = (source_root / relative_path).read_bytes()
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
        "assemblyscript_root": load_json(source_root / "node_modules/assemblyscript/package.json")[
            "version"
        ],
        "assemblyscript_graph_ts_nested": load_json(
            source_root / "node_modules/@graphprotocol/graph-ts/node_modules/assemblyscript/package.json"
        )["version"],
    }
    for key, value in installed_versions.items():
        if value != source["toolchain"][key]:
            fail(f"installed exact source toolchain drift: {key}")


def verify(root: Path, lock_path: Path, exact_source_root: Path | None = None) -> None:
    lock = load_json(root / lock_path)
    if not isinstance(lock, dict) or lock.get("format_version") != 1:
        fail("unsupported Matic target lock")
    deployment = lock.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("cid") != EXPECTED_DEPLOYMENT:
        fail("deployment identity drift")
    artifacts = verify_artifact_lock(root, lock)
    verify_manifest(root, lock, artifacts)
    verify_schema(root, lock, artifacts)
    verify_source_pin(lock, artifacts)
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
        print(f"Uniswap V3 Matic target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified immutable Matic deployment/schema/ABI artifacts, exact manifest shape, "
        "16-entity gap contract, and the exact source/toolchain reproduction"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
