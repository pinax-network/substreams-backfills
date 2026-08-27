#!/usr/bin/env python3
"""Verify the pinned V3 ChainConfig overlay, manifests, runtime, and packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

CONFIG_VERSION = "uniswap-v3-chain-config/v1"
CONFIG_DIGESTS = {
    "mainnet": "30f5caf9ee8906a8886dc103e55286b9d5b6dbd8784d1c97d21b9a38b266bb55",
    "base": "2eeed82547cea2d8e6c6adb9b3770bd8f8bbdde3b43ce4c7a5410325cf9b2832",
}
CONFIGURED_MODULES = (
    "map_pools_created",
    "map_tokens_whitelist_pools",
    "map_extract_data_types",
    "store_total_tx_counts",
    "store_swaps_volume",
    "store_eth_prices",
    "store_derived_tvl",
    "graph_out",
)
EXPECTED_RUNTIME_CHANGES = {
    "Cargo.lock",
    "Cargo.toml",
    "configs/base-v1.json",
    "configs/mainnet-v1.json",
    "src/config.rs",
    "src/db.rs",
    "src/filtering.rs",
    "src/lib.rs",
    "src/pb/mod.rs",
    "src/price.rs",
    "src/rpc.rs",
    "src/utils.rs",
    "substreams.base.yaml",
    "substreams.mainnet.yaml",
}
EXPECTED_CRITICAL = {
    "mainnet": {
        "deployment": "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
        "schema": "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru",
        "graft_base": "QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF",
        "graft_block": 19_470_000,
        "factory": "1f98431c8ad98523631ae4a59f267346ea31f984",
        "factory_entity_id": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "manager": "c36442b4a4522e871399cd717abdd847ab11fe88",
        "module_start": 12_369_621,
        "manager_start": 12_369_651,
        "wrapped": "c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        "reference_pool": "8ad599c3a0ff1de082011efddc58f1908eb6e6d8",
        "reference_token": "a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "reference_side": 0,
        "minimum": "52",
        "stable_count": 6,
        "whitelist_count": 21,
        "metadata_count": 6,
    },
    "base": {
        "deployment": "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP",
        "schema": "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru",
        "graft_base": "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
        "graft_block": 19_852_000,
        "factory": "33128a8fc17869897dce68ed026d694621f6fdfd",
        "factory_entity_id": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "manager": "03a520b32c04bf3beef7beb72e919cf822ed34f1",
        "module_start": 1_371_713,
        "manager_start": 1_371_713,
        "wrapped": "4200000000000000000000000000000000000006",
        "reference_pool": "4c36388be6f416a29c8d8eee81c771ce6be14b18",
        "reference_token": "d9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
        "reference_side": 1,
        "minimum": "1",
        "stable_count": 1,
        "whitelist_count": 4,
        "metadata_count": 0,
    },
}
BASE_STABLE_ARTIFACT = "b97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"
IGNORED_POOL = "8fe8d9bb8eeba3ed688069c3d6b556c9ca258248"
SWAP_IGNORED_POOL = "9663f2ca0454accad3e094448ea6f77443880454"
ADDRESS_RE = re.compile(r"^[0-9a-f]{40}$")
ADDRESS_LITERAL_RE = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
CID_RE = re.compile(r"^Qm[1-9A-HJ-NP-Za-km-z]{44}$")


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_keys(value: dict[str, object], expected: set[str], field: str) -> None:
    actual = set(value)
    require(actual == expected, f"{field} keys are {sorted(actual)}, expected {sorted(expected)}")


def address(value: object, field: str) -> str:
    require(isinstance(value, str) and ADDRESS_RE.fullmatch(value) is not None, f"{field} is not a lowercase address")
    return value


def address_list(value: object, field: str, allow_empty: bool) -> list[str]:
    require(isinstance(value, list), f"{field} is not a list")
    require(allow_empty or bool(value), f"{field} cannot be empty")
    result = [address(item, field) for item in value]
    require(len(result) == len(set(result)), f"{field} contains duplicates")
    return result


def validate_config(config: dict[str, object], network: str) -> None:
    exact_keys(
        config,
        {
            "format_version",
            "config_version",
            "network",
            "deployment",
            "schema_cid",
            "graft",
            "contracts",
            "initial_blocks",
            "pricing",
            "filters",
            "static_token_metadata",
        },
        network,
    )
    require(config["format_version"] == 1, f"{network} format version drift")
    require(config["config_version"] == CONFIG_VERSION, f"{network} config version drift")
    require(config["network"] == network, f"{network} network mismatch")
    require(CID_RE.fullmatch(config["deployment"]) is not None, f"{network} deployment CID malformed")
    require(CID_RE.fullmatch(config["schema_cid"]) is not None, f"{network} schema CID malformed")

    graft = config["graft"]
    exact_keys(graft, {"base", "block"}, f"{network}.graft")
    require(CID_RE.fullmatch(graft["base"]) is not None, f"{network} graft CID malformed")
    require(type(graft["block"]) is int and graft["block"] > 0, f"{network} graft block malformed")

    contracts = config["contracts"]
    exact_keys(contracts, {"factory", "factory_entity_id", "nonfungible_position_manager"}, f"{network}.contracts")
    factory = address(contracts["factory"], f"{network}.factory")
    manager = address(contracts["nonfungible_position_manager"], f"{network}.manager")
    require(factory != manager, f"{network} factory and manager match")
    entity_id = contracts["factory_entity_id"]
    require(isinstance(entity_id, str) and entity_id.startswith("0x") and entity_id[2:].lower() == factory, f"{network} factory entity ID mismatch")

    starts = config["initial_blocks"]
    exact_keys(starts, {"module", "factory", "factory_creation", "nonfungible_position_manager"}, f"{network}.initial_blocks")
    require(all(type(value) is int and value > 0 for value in starts.values()), f"{network} initial block malformed")
    require(starts["module"] == starts["factory"] == starts["factory_creation"], f"{network} factory starts disagree")
    require(starts["nonfungible_position_manager"] >= starts["module"], f"{network} manager starts too early")

    pricing = config["pricing"]
    exact_keys(
        pricing,
        {
            "wrapped_native_token",
            "usd_reference_pool",
            "usd_reference_token",
            "usd_reference_token_side",
            "minimum_native_locked",
            "stablecoins",
            "whitelist_tokens",
        },
        f"{network}.pricing",
    )
    wrapped = address(pricing["wrapped_native_token"], f"{network}.wrapped")
    reference_pool = address(pricing["usd_reference_pool"], f"{network}.reference_pool")
    address(pricing["usd_reference_token"], f"{network}.reference_token")
    require(pricing["usd_reference_token_side"] in (0, 1), f"{network} reference side malformed")
    require(isinstance(pricing["minimum_native_locked"], str) and pricing["minimum_native_locked"].isdigit(), f"{network} minimum malformed")
    address_list(pricing["stablecoins"], f"{network}.stablecoins", False)
    whitelist = address_list(pricing["whitelist_tokens"], f"{network}.whitelist", False)
    require(wrapped in whitelist, f"{network} wrapped token is not whitelisted")
    require(pricing["usd_reference_token"] in whitelist, f"{network} reference token is not whitelisted")
    require(wrapped != pricing["usd_reference_token"], f"{network} wrapped and reference tokens match")

    filters = config["filters"]
    exact_keys(filters, {"ignored_pools", "swap_ignored_pools"}, f"{network}.filters")
    ignored = address_list(filters["ignored_pools"], f"{network}.ignored_pools", True)
    swap_ignored = address_list(filters["swap_ignored_pools"], f"{network}.swap_ignored_pools", True)
    require(not set(ignored) & set(swap_ignored), f"{network} ignored pool lists overlap")
    require(reference_pool not in ignored + swap_ignored, f"{network} reference pool is filtered")

    metadata = config["static_token_metadata"]
    require(isinstance(metadata, list), f"{network} static metadata is not a list")
    seen: set[str] = set()
    for index, token in enumerate(metadata):
        exact_keys(token, {"address", "name", "symbol", "decimals"}, f"{network}.metadata[{index}]")
        token_address = address(token["address"], f"{network}.metadata[{index}].address")
        require(token_address not in seen, f"{network} duplicate metadata")
        seen.add(token_address)
        require(isinstance(token["name"], str) and token["name"], f"{network} metadata name empty")
        require(isinstance(token["symbol"], str) and token["symbol"], f"{network} metadata symbol empty")
        require(type(token["decimals"]) is int and 0 <= token["decimals"] < 255, f"{network} metadata decimals malformed")

    critical = EXPECTED_CRITICAL[network]
    actual = {
        "deployment": config["deployment"],
        "schema": config["schema_cid"],
        "graft_base": graft["base"],
        "graft_block": graft["block"],
        "factory": factory,
        "factory_entity_id": entity_id,
        "manager": manager,
        "module_start": starts["module"],
        "manager_start": starts["nonfungible_position_manager"],
        "wrapped": wrapped,
        "reference_pool": reference_pool,
        "reference_token": pricing["usd_reference_token"],
        "reference_side": pricing["usd_reference_token_side"],
        "minimum": pricing["minimum_native_locked"],
        "stable_count": len(pricing["stablecoins"]),
        "whitelist_count": len(whitelist),
        "metadata_count": len(metadata),
    }
    require(actual == critical, f"{network} critical constant drift: {actual}")


def load_configs(root: Path) -> dict[str, dict[str, object]]:
    configs: dict[str, dict[str, object]] = {}
    for network, digest in CONFIG_DIGESTS.items():
        path = root / f"uniswap-v3/chain-config/configs/{network}-v1.json"
        require(path.is_file(), f"missing {path}")
        require(sha256(path) == digest, f"{network} config digest drift")
        config = json.loads(path.read_text())
        validate_config(config, network)
        configs[network] = config

    base = configs["base"]
    require(base["pricing"]["stablecoins"] == [BASE_STABLE_ARTIFACT], "Base deployed stable-list artifact drift")
    for network, config in configs.items():
        require(config["filters"]["ignored_pools"] == [IGNORED_POOL], f"{network} ignored-pool drift")
        require(config["filters"]["swap_ignored_pools"] == [SWAP_IGNORED_POOL], f"{network} swap hotfix drift")
    return configs


def selector(network: str) -> str:
    return f"version=1;network={network};sha256={CONFIG_DIGESTS[network]}"


def load_manifests(root: Path, configs: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    manifests: dict[str, dict[str, object]] = {}
    binary_paths: dict[str, str] = {}
    for network, config in configs.items():
        path = root / f"uniswap-v3/chain-config/manifests/substreams.{network}.yaml"
        manifest = yaml.safe_load(path.read_text())
        require(manifest["network"] == network, f"{network} manifest network mismatch")
        require(manifest["package"]["name"] == f"uniswap_v3_{network}_backfill", f"{network} package name mismatch")
        require(manifest["package"]["version"] == "v0.3.0", f"{network} package version mismatch")
        binary_paths[network] = manifest["binaries"]["default"]["file"]
        require(manifest["binaries"]["default"]["type"] == "wasm/rust-v1", f"{network} binary type mismatch")

        modules = {module["name"]: module for module in manifest["modules"]}
        require(len(modules) == len(manifest["modules"]) == 22, f"{network} module set malformed")
        require(set(manifest.get("params", {})) == set(CONFIGURED_MODULES), f"{network} params module set mismatch")
        for name, module in modules.items():
            params_inputs = [item for item in module.get("inputs", []) if "params" in item]
            if name in CONFIGURED_MODULES:
                require(params_inputs == [{"params": "string"}], f"{network}.{name} params input malformed")
                require(module["inputs"][0] == {"params": "string"}, f"{network}.{name} params must be first")
                require(manifest["params"][name] == selector(network), f"{network}.{name} selector mismatch")
            else:
                require(not params_inputs, f"{network}.{name} has an unexpected params input")
            if "initialBlock" in module:
                require(module["initialBlock"] == config["initial_blocks"]["module"], f"{network}.{name} initial block mismatch")
        manifests[network] = manifest

    require(binary_paths["mainnet"] == binary_paths["base"], "manifests do not reference one shared WASM path")
    return manifests


def production_prefix(path: Path) -> str:
    text = path.read_text()
    marker = re.search(r"(?m)^#\[cfg\(test\)\]\s*$", text)
    return text[: marker.start()] if marker else text


def non_build_files(directory: Path) -> dict[str, Path]:
    return {
        path.relative_to(directory).as_posix(): path
        for path in directory.rglob("*")
        if path.is_file() and "target" not in path.relative_to(directory).parts
    }


def verify_runtime(root: Path, runtime: Path, configs: dict[str, dict[str, object]], manifests: dict[str, dict[str, object]]) -> Path:
    require(runtime.is_dir(), f"runtime directory does not exist: {runtime}")
    source = root / "uniswap-v3/source"
    changed: set[str] = set()
    source_files = non_build_files(source)
    runtime_files = non_build_files(runtime)
    for relative in set(source_files) | set(runtime_files):
        if relative not in source_files or relative not in runtime_files or source_files[relative].read_bytes() != runtime_files[relative].read_bytes():
            changed.add(relative)
    require(changed == EXPECTED_RUNTIME_CHANGES, f"materialized runtime change set is {sorted(changed)}")

    for network in configs:
        require(
            (runtime / f"configs/{network}-v1.json").read_bytes()
            == (root / f"uniswap-v3/chain-config/configs/{network}-v1.json").read_bytes(),
            f"runtime {network} config differs",
        )
        require(
            (runtime / f"substreams.{network}.yaml").read_bytes()
            == (root / f"uniswap-v3/chain-config/manifests/substreams.{network}.yaml").read_bytes(),
            f"runtime {network} manifest differs",
        )

    forbidden = set()
    for config in configs.values():
        forbidden.update(
            [
                config["contracts"]["factory"],
                config["contracts"]["nonfungible_position_manager"],
                config["pricing"]["wrapped_native_token"],
                config["pricing"]["usd_reference_pool"],
                config["pricing"]["usd_reference_token"],
            ]
        )
        forbidden.update(config["pricing"]["stablecoins"])
        forbidden.update(config["pricing"]["whitelist_tokens"])
        forbidden.update(config["filters"]["ignored_pools"])
        forbidden.update(config["filters"]["swap_ignored_pools"])
        forbidden.update(item["address"] for item in config["static_token_metadata"])

    findings: list[str] = []
    for path in (runtime / "src").rglob("*.rs"):
        if path.name == "config.rs":
            continue
        text = production_prefix(path).lower()
        for value in sorted(set(ADDRESS_LITERAL_RE.findall(text))):
            findings.append(f"{path.relative_to(runtime)}:undocumented address literal {value}")
        for value in forbidden:
            if value in text:
                findings.append(f"{path.relative_to(runtime)}:{value}")
        if "12369621" in text or "1371713" in text:
            findings.append(f"{path.relative_to(runtime)}:hard-coded start block")
    require(not findings, "chain constants remain in executable Rust: " + ", ".join(findings))

    config_source = (runtime / "src/config.rs").read_text()
    for digest in CONFIG_DIGESTS.values():
        require(digest in config_source, f"runtime selector does not pin {digest}")
    require("deny_unknown_fields" in config_source, "runtime config is not fail-closed")
    require("missing ChainConfig selector" in config_source, "runtime does not refuse missing config")

    binary_relative = manifests["mainnet"]["binaries"]["default"]["file"]
    require(binary_relative == manifests["base"]["binaries"]["default"]["file"], "runtime binary paths diverge")
    return runtime / binary_relative


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        require(offset < len(data), "truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        require(shift < 70, "invalid protobuf varint")


def wire_fields(data: bytes) -> list[tuple[int, int, bytes | int]]:
    fields: list[tuple[int, int, bytes | int]] = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        number, wire_type = tag >> 3, tag & 7
        require(number > 0, "invalid protobuf field number")
        if wire_type == 0:
            value, offset = read_varint(data, offset)
        elif wire_type == 1:
            require(offset + 8 <= len(data), "truncated fixed64")
            value, offset = data[offset : offset + 8], offset + 8
        elif wire_type == 2:
            length, offset = read_varint(data, offset)
            require(offset + length <= len(data), "truncated length-delimited field")
            value, offset = data[offset : offset + length], offset + length
        elif wire_type == 5:
            require(offset + 4 <= len(data), "truncated fixed32")
            value, offset = data[offset : offset + 4], offset + 4
        else:
            raise VerificationError(f"unsupported protobuf wire type {wire_type}")
        fields.append((number, wire_type, value))
    return fields


def embedded_wasm_binaries(package: Path) -> list[bytes]:
    package_fields = wire_fields(package.read_bytes())
    modules_messages = [value for number, wire, value in package_fields if number == 6 and wire == 2]
    require(len(modules_messages) == 1, f"{package} has {len(modules_messages)} Modules messages")
    binaries = [value for number, wire, value in wire_fields(modules_messages[0]) if number == 2 and wire == 2]
    contents: list[bytes] = []
    for binary in binaries:
        content = [value for number, wire, value in wire_fields(binary) if number == 2 and wire == 2]
        require(len(content) == 1, f"{package} binary has {len(content)} content fields")
        contents.append(content[0])
    require(contents, f"{package} contains no binaries")
    return contents


def package_info(path: Path) -> dict[str, object]:
    output = subprocess.check_output(["substreams", "info", "--json", str(path)], text=True)
    return json.loads(output)


def require_shared_embedded_wasm(expected_wasm: bytes, embedded: dict[str, bytes]) -> None:
    require(set(embedded) == {"mainnet", "base"}, "both packaged WASM payloads are required")
    for network, payload in embedded.items():
        require(payload == expected_wasm, f"{network} embedded WASM differs from the shared build")
    require(embedded["mainnet"] == embedded["base"], "embedded WASM bytes diverge across packages")


def verify_packages(
    runtime_wasm: Path,
    mainnet_package: Path,
    base_package: Path,
    evidence_out: Path | None,
) -> dict[str, object]:
    require(runtime_wasm.is_file(), f"shared runtime WASM missing: {runtime_wasm}")
    expected_wasm = runtime_wasm.read_bytes()
    package_paths = {"mainnet": mainnet_package, "base": base_package}
    package_evidence: dict[str, object] = {}
    embedded: dict[str, bytes] = {}
    execution_hashes: dict[str, dict[str, str]] = {}

    for network, path in package_paths.items():
        require(path.is_file(), f"missing diagnostic package {path}")
        binaries = embedded_wasm_binaries(path)
        require(len(binaries) == 1, f"{network} package contains {len(binaries)} binaries")
        embedded[network] = binaries[0]

        info = package_info(path)
        require(info["network"] == network, f"{network} package network mismatch")
        require(info["name"] == f"uniswap_v3_{network}_backfill", f"{network} package name mismatch")
        require(info["version"] == "v0.3.0", f"{network} package version mismatch")
        require(len(info["modules"]) == 22, f"{network} package module count mismatch")
        hashes: dict[str, str] = {}
        for module in info["modules"]:
            hashes[module["name"]] = module["hash"]
            params = [item for item in module.get("inputs", []) if item["type"] == "params"]
            if module["name"] in CONFIGURED_MODULES:
                require(params == [{"type": "params", "name": selector(network)}], f"{network}.{module['name']} packaged selector mismatch")
            else:
                require(not params, f"{network}.{module['name']} packaged unexpected selector")
        execution_hashes[network] = hashes
        package_evidence[network] = {
            "spkg_sha256": sha256(path),
            "bytes": path.stat().st_size,
            "execution_module_hashes": hashes,
        }

    require_shared_embedded_wasm(expected_wasm, embedded)
    require(execution_hashes["mainnet"] != execution_hashes["base"], "chain execution hashes unexpectedly match")
    evidence = {
        "format_version": 1,
        "status": "diagnostic-not-a-production-pin",
        "shared_wasm": {
            "sha256": hashlib.sha256(expected_wasm).hexdigest(),
            "bytes": len(expected_wasm),
            "embedded_identically_in": ["mainnet", "base"],
        },
        "packages": package_evidence,
        "hash_semantics": "WASM content is identical. Execution module hashes intentionally differ because params and initialBlock are hashed inputs.",
    }
    if evidence_out:
        evidence_out.parent.mkdir(parents=True, exist_ok=True)
        evidence_out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def verify_provenance(root: Path) -> None:
    path = root / "provenance/uniswap-v3-chain-config-v1.json"
    provenance = json.loads(path.read_text())
    require(provenance["format_version"] == 1, "ChainConfig provenance format drift")
    require(provenance["config_version"] == CONFIG_VERSION, "ChainConfig provenance version drift")
    overlay = root / provenance["overlay"]["path"]
    require(sha256(overlay) == provenance["overlay"]["raw_sha256"], "runtime overlay provenance drift")
    for network, digest in CONFIG_DIGESTS.items():
        require(provenance["configurations"][network]["raw_sha256"] == digest, f"{network} provenance digest drift")
        require(provenance["configurations"][network]["selector"] == selector(network), f"{network} provenance selector drift")
        manifest = root / provenance["configurations"][network]["manifest"]
        require(
            sha256(manifest) == provenance["configurations"][network]["manifest_raw_sha256"],
            f"{network} generated manifest provenance drift",
        )
        require(
            provenance["targets"][network]["deployment_manifest"]["cid"] == EXPECTED_CRITICAL[network]["deployment"],
            f"{network} provenance deployment drift",
        )
    require(provenance["shared_artifacts"]["schema"]["raw_sha256"] == "ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c", "schema provenance drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--mainnet-spkg", type=Path)
    parser.add_argument("--base-spkg", type=Path)
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args()
    if bool(args.mainnet_spkg) != bool(args.base_spkg):
        parser.error("--mainnet-spkg and --base-spkg must be passed together")
    if args.mainnet_spkg and not args.runtime:
        parser.error("package verification requires --runtime")

    try:
        root = args.root.resolve()
        configs = load_configs(root)
        manifests = load_manifests(root, configs)
        verify_provenance(root)
        runtime_wasm = None
        if args.runtime:
            runtime_wasm = verify_runtime(root, args.runtime.resolve(), configs, manifests)
        if args.mainnet_spkg:
            verify_packages(runtime_wasm, args.mainnet_spkg.resolve(), args.base_spkg.resolve(), args.evidence_out)
        print("verified pinned mainnet/Base ChainConfigs, manifests, provenance, and fail-closed bindings")
        return 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError, VerificationError) as error:
        print(f"Uniswap V3 ChainConfig verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
