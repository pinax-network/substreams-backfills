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


LOCK_PATH = Path("provenance/exchange-v3-bsc-target.json")
EXPECTED_DEPLOYMENT = "QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn"
EXPECTED_SCHEMA = "QmP9xqULGJzQE7SFKyzkgD8LEkjoy1aChCJnbNkCT4VDRi"
EXPECTED_SOURCE_COMMIT = "1da7ba61abb26633ff819ce8cdfe945be8770a92"
EXPECTED_SOURCE_TREE = "a2a113c9eedd7ed0e6fdcaea275153233223c95d"


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
        if vendored_path is None:
            if not role.endswith("_mapping_wasm"):
                fail(f"only mapping WASM may remain unvendored: {role}")
            if not isinstance(record.get("exports"), list) or not record["exports"]:
                fail(f"mapping export lock missing for {role}")
            continue
        if not isinstance(vendored_path, str):
            fail(f"invalid vendored path for {role}")
        payload = (root / vendored_path).read_bytes()
        if len(payload) != record.get("source_bytes"):
            fail(f"vendored byte count drift for {role}")
        if sha256(payload) != record.get("source_sha256"):
            fail(f"vendored digest drift for {role}")
        if role.endswith("_abi"):
            json.loads(payload)

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
    if not re.fullmatch(r"[0-9a-f]{40}", str(source.get("tree", ""))):
        fail("invalid exact source tree")

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
    for record in source["source_files"]:
        payload = (source_root / record["path"]).read_bytes()
        if len(payload) != record["bytes"] or sha256(payload) != record["sha256"]:
            fail(f"exact source file drift: {record['path']}")

    build_root = source_root / "subgraphs/exchange-v3/template/build"
    deployed_manifest = yaml.safe_load(
        (root / str(artifacts["deployment"]["vendored_path"])).read_text()
    )
    built_manifest = yaml.safe_load((build_root / "subgraph.yaml").read_text())
    if manifest_semantic_shape(built_manifest) != manifest_semantic_shape(deployed_manifest):
        fail("exact source generated manifest is not semantically identical to the deployment")

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


def verify(root: Path, lock_path: Path, exact_source_root: Path | None = None) -> None:
    lock = load_json(root / lock_path)
    if not isinstance(lock, dict) or lock.get("format_version") != 1:
        fail("unsupported Exchange V3 BSC target lock")
    if lock.get("family") != "exchange-v3-bsc":
        fail("family identity drift")
    deployment = lock.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("cid") != EXPECTED_DEPLOYMENT:
        fail("deployment identity drift")
    artifacts = verify_artifacts(root, lock)
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
        print(f"Exchange V3 BSC target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified immutable Exchange V3 deployment/schema/ABIs, legacy manifest shape, "
        "machine-readable schema profile, and exact source/toolchain reproduction"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
