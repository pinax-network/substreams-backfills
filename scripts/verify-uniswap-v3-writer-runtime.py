#!/usr/bin/env python3
"""Fail-closed verification for the diagnostic Uniswap V3 writer runtime."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import yaml


SOURCE_WRITER_CONTRACT = Path("uniswap-v3/graft-ancestry/v2/writer-compatibility.json")
SOURCE_WRITER_CONTRACT_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
PROFILE_CONTRACT_VERSION = "uniswap-v3-writer-runtime-segment-profiles/v1"
PROFILE_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
CONFIG_VERSION = "uniswap-v3-chain-config/v2"
CONFIG_DIGESTS = {
    "mainnet": "1438edbd94e492190ce15d059ab766a03022f7255fdfa1cde9ef32e78a0fe547",
    "base": "a227784961973c72b47f663d7ee66b2f9306372bf2232dfb416abbba6ccf8df0",
}
CONFIGURED_MODULES = (
    "map_pools_created",
    "map_tokens_whitelist_pools",
    "map_extract_data_types",
    "map_writer_events",
    "store_total_tx_counts",
    "store_swaps_volume",
    "store_eth_prices",
    "store_derived_tvl",
    "graph_out",
)
WRITER_RUNTIME_BINDING = {
    "contract_version": "uniswap-v3-writer-runtime/v1",
    "mode": "diagnostic-only",
    "segment_profiles_version": PROFILE_CONTRACT_VERSION,
    "segment_profiles_sha256": PROFILE_SHA256,
    "source_writer_contract_sha256": SOURCE_WRITER_CONTRACT_SHA256,
    "graph_out_replaced": False,
    "runtime_population_complete": False,
    "backfill_ready": False,
    "production_ready": False,
}
EXPECTED_RANGES = (
    ("mainnet", 12_369_621, 13_450_880, "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB"),
    ("mainnet", 13_450_881, 13_498_328, "QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry"),
    ("mainnet", 13_498_329, 13_591_197, "QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P"),
    ("mainnet", 13_591_198, 13_605_860, "QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX"),
    ("mainnet", 13_605_861, 19_470_000, "QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF"),
    ("mainnet", 19_470_001, None, "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7"),
    ("base", 1_371_679, 19_852_000, "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR"),
    ("base", 19_852_001, None, "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP"),
)
EXPECTED_RUNTIME_CHANGES = {
    "Cargo.lock",
    "Cargo.toml",
    "build.rs",
    "configs/base-v1.json",
    "configs/base-v2.json",
    "configs/mainnet-v1.json",
    "configs/mainnet-v2.json",
    "configs/segment-profiles-v1.json",
    "fixtures/events-v1.json",
    "proto/uniswap/v1/writer.proto",
    "rust-toolchain.toml",
    "src/config.rs",
    "src/db.rs",
    "src/filtering.rs",
    "src/lib.rs",
    "src/pb/mod.rs",
    "src/pb/uniswap.writer.v1.rs",
    "src/price.rs",
    "src/rpc.rs",
    "src/utils.rs",
    "src/writer_runtime.rs",
    "substreams.base.yaml",
    "substreams.mainnet.yaml",
}
EXPECTED_PATCH_FILES = {
    "Cargo.lock",
    "Cargo.toml",
    "build.rs",
    "proto/uniswap/v1/writer.proto",
    "rust-toolchain.toml",
    "src/config.rs",
    "src/lib.rs",
    "src/pb/mod.rs",
    "src/pb/uniswap.writer.v1.rs",
    "src/writer_runtime.rs",
}
PROTO_SHA256 = "f87b4bc718349bae2ff8fe799e4a4dadbb507240b7b6e9bc8d7a199299e33c59"
GENERATED_PROTO_SHA256 = "b41a3890341f96d8b8eb5afb1345f47c28f6690668097637fcf46699217a9184"
NPM_ABI_SHA256 = "46d1799f648e25edbcfdda629075a7d857437b62384f10a945daa199c7f63c75"
CONTRACT_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
CLIPPY_BASELINE_SHA256 = "5708c324097b2f1ae0efa71516eb61927f16357be8b58e95f804a4dea84f174b"
PACKAGE_MODULE_STRUCTURE_SHA256 = {
    "mainnet": "db28c04e1e2b3a075562bb3186b62e752a1497bb7e6bcf065b37f747b417f0eb",
    "base": "552adeef65ec2b6654194178fd0869bc0d51c89a6e3b47805aabcb87dc8dafed",
}
PACKAGE_MODULE_HASH_ALGORITHM = "substreams-v1.20.3-sha1"
PACKAGE_DESCRIPTOR_COUNT = 17
PACKAGE_DESCRIPTOR_SET_SHA256 = "b437d2e7999acea5d0e23de99af19236030bc797133f7cc5b4e3a83985ec2b2c"
WRITER_DESCRIPTOR_SHA256 = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def derive_profile_document(source_path: Path, source: dict[str, object]) -> dict[str, object]:
    segments = source["segments"]
    writer_contracts = source["segment_writer_contracts"]
    npm_profiles = {profile["profile_id"]: profile for profile in source["npm_semantic_profiles"]}
    require(len(segments) == len(writer_contracts) == 8, "source does not contain exactly eight segments")
    output = {
        "format_version": 1,
        "profile_contract_version": PROFILE_CONTRACT_VERSION,
        "profiles": [],
        "source_truth_boundary": source["truth_boundary"],
        "source_writer_contract": {
            "contract_version": source["contract_version"],
            "path": SOURCE_WRITER_CONTRACT.as_posix(),
            "raw_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        },
        "tranche_truth_boundary": {
            "backfill_ready": False,
            "boundary_state_continuity_complete": False,
            "diagnostic_only": True,
            "graph_out_replaced": False,
            "logical_oracle_complete": False,
            "physical_parity_complete": False,
            "poi_parity_complete": False,
            "production_ready": False,
            "rpc_calls_added": False,
            "runtime_population_complete": False,
            "stores_added": False,
        },
    }
    for segment, writer in zip(segments, writer_contracts, strict=True):
        identity = (segment["network"], segment["start_block_inclusive"], segment["end_block_inclusive"], segment["deployment"])
        writer_identity = (writer["network"], writer["start_block_inclusive"], writer["end_block_inclusive"], writer["deployment"])
        require(identity == writer_identity, "source segment/writer order drift")
        npm = npm_profiles[segment["npm_profile_id"]]
        bindings = writer["artifact_bindings"]
        output["profiles"].append(
            {
                "artifact_identity_sha256": writer["artifact_identity_sha256"],
                "backfill_allowed": segment["backfill_allowed"],
                "deployment": segment["deployment"],
                "end_block_inclusive": segment["end_block_inclusive"],
                "execution_model": segment["execution_model"],
                "factory_mapping_cid": segment["factory_mapping_cid"],
                "factory_profile_id": bindings["factory"]["profile_id"],
                "historical_guard": {
                    "block": segment["historical_guard"]["block"],
                    "effective_in_segment": segment["historical_guard"]["effective_in_segment"],
                    "present_in_mapping": segment["historical_guard"]["present_in_mapping"],
                },
                "network": segment["network"],
                "npm_block_guard_handlers": npm["definition"]["block_guard_handlers"],
                "npm_full_handler_or_field_writer_audit_complete": npm["full_handler_or_field_writer_audit_complete"],
                "npm_mapping_cid": segment["npm_mapping_cid"],
                "npm_profile_id": segment["npm_profile_id"],
                "pool_mapping_cid": segment["pool_mapping_cid"],
                "pool_profile_id": bindings["pool"]["profile_id"],
                "segment_id": writer["segment_id"],
                "semantic_contract_sha256": writer["semantic_contract_sha256"],
                "source_segment_sha256": canonical_sha256(segment),
                "start_block_inclusive": segment["start_block_inclusive"],
                "target_runtime_identity_bound": segment["target_runtime_identity_bound"],
            }
        )
    return output


def validate_profile_document(document: dict[str, object]) -> None:
    require(set(document) == {"format_version", "profile_contract_version", "profiles", "source_truth_boundary", "source_writer_contract", "tranche_truth_boundary"}, "profile document key drift")
    profiles = document["profiles"]
    require(len(profiles) == 8, "profile document must contain exactly eight segments")
    actual_ranges = tuple((item["network"], item["start_block_inclusive"], item["end_block_inclusive"], item["deployment"]) for item in profiles)
    require(actual_ranges == EXPECTED_RANGES, "profile ranges, order, or deployment bindings drift")
    for item in profiles:
        require(item["segment_id"] == f'{item["network"]}:{item["deployment"]}', "segment identity drift")
        require(item["execution_model"] == "undecided", "segment execution model promoted")
        require(item["target_runtime_identity_bound"] is False, "target runtime identity promoted")
        require(item["backfill_allowed"] is False, "segment backfill gate promoted")
        require(item["npm_full_handler_or_field_writer_audit_complete"] is False, "NPM audit gate promoted")
    source_truth = document["source_truth_boundary"]
    for key in ("backfill_ready", "boundary_state_continuity_complete", "logical_oracle_complete", "physical_parity_complete", "poi_parity_complete", "production_ready", "runtime_population_complete", "segment_execution_models_decided", "target_graph_node_runtime_identity_bound"):
        require(source_truth[key] is False, f"source truth gate {key} promoted")
    tranche = document["tranche_truth_boundary"]
    require(tranche == derive_tranche_truth_boundary(), "tranche truth boundary drift")


def derive_tranche_truth_boundary() -> dict[str, bool]:
    return {
        "backfill_ready": False,
        "boundary_state_continuity_complete": False,
        "diagnostic_only": True,
        "graph_out_replaced": False,
        "logical_oracle_complete": False,
        "physical_parity_complete": False,
        "poi_parity_complete": False,
        "production_ready": False,
        "rpc_calls_added": False,
        "runtime_population_complete": False,
        "stores_added": False,
    }


def load_profiles(root: Path) -> dict[str, object]:
    source_path = root / SOURCE_WRITER_CONTRACT
    require(sha256(source_path) == SOURCE_WRITER_CONTRACT_SHA256, "source writer contract raw digest drift")
    source = json.loads(source_path.read_text())
    expected = derive_profile_document(source_path, source)
    path = root / "uniswap-v3/writer-runtime/segment-profiles-v1.json"
    require(sha256(path) == PROFILE_SHA256, "segment-profile raw digest drift")
    actual = json.loads(path.read_text())
    require(actual == expected, "segment profiles are not the exact ordered projection of the source writer contract")
    validate_profile_document(actual)
    return actual


def select_profile(document: dict[str, object], network: str, block: int) -> dict[str, object]:
    require(network in {"mainnet", "base"}, f"unknown network {network}")
    matches = [profile for profile in document["profiles"] if profile["network"] == network and profile["start_block_inclusive"] <= block and (profile["end_block_inclusive"] is None or block <= profile["end_block_inclusive"])]
    require(len(matches) == 1, f"expected one {network} segment at {block}, found {len(matches)}")
    return matches[0]


def selector(network: str) -> str:
    return f"version=2;network={network};sha256={CONFIG_DIGESTS[network]}"


def load_configs(root: Path) -> dict[str, dict[str, object]]:
    result = {}
    for network, digest in CONFIG_DIGESTS.items():
        old = json.loads((root / f"uniswap-v3/chain-config/configs/{network}-v1.json").read_text())
        expected = copy.deepcopy(old)
        expected["config_version"] = CONFIG_VERSION
        expected["writer_runtime"] = WRITER_RUNTIME_BINDING
        if network == "base":
            expected["initial_blocks"].update(module=1_371_679, factory=1_371_679, factory_creation=1_371_679)
            expected["initial_blocks"]["nonfungible_position_manager"] = 1_371_713
        path = root / f"uniswap-v3/writer-runtime/configs/{network}-v2.json"
        require(sha256(path) == digest, f"{network} v2 config raw digest drift")
        actual = json.loads(path.read_text())
        require(actual == expected, f"{network} v2 config is not the exact versioned ChainConfig transformation")
        require(actual["initial_blocks"]["module"] == actual["initial_blocks"]["factory"] == actual["initial_blocks"]["factory_creation"], f"{network} runtime/Factory starts disagree")
        require(actual["initial_blocks"]["nonfungible_position_manager"] >= actual["initial_blocks"]["module"], f"{network} NPM gate precedes runtime")
        result[network] = actual
    require(result["base"]["initial_blocks"] == {"module": 1_371_679, "factory": 1_371_679, "factory_creation": 1_371_679, "nonfungible_position_manager": 1_371_713}, "Base start/gate split drift")
    return result


def expected_manifest(root: Path, network: str, config: dict[str, object]) -> dict[str, object]:
    manifest = yaml.safe_load((root / f"uniswap-v3/chain-config/manifests/substreams.{network}.yaml").read_text())
    manifest["package"]["version"] = "v0.4.0"
    manifest["protobuf"]["files"].append("uniswap/v1/writer.proto")
    if network == "base":
        for module in manifest["modules"]:
            if "initialBlock" in module:
                module["initialBlock"] = config["initial_blocks"]["module"]
    diagnostic = {
        "name": "map_writer_events",
        "kind": "map",
        "initialBlock": config["initial_blocks"]["nonfungible_position_manager"],
        "inputs": [{"params": "string"}, {"source": "sf.ethereum.type.v2.Block"}],
        "output": {"type": "proto:uniswap.writer.v1.WriterEvents"},
        "doc": "Diagnostic-only raw NPM event stream; it has no stores or path to graph_out and is not a parity or production output.",
    }
    index = next(index for index, module in enumerate(manifest["modules"]) if module["name"] == "map_extract_data_types") + 1
    manifest["modules"].insert(index, diagnostic)
    manifest["params"] = {name: selector(network) for name in (*manifest["params"], "map_writer_events")}
    return manifest


def load_manifests(root: Path, configs: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    manifests = {}
    for network, config in configs.items():
        path = root / f"uniswap-v3/writer-runtime/manifests/substreams.{network}.yaml"
        actual = yaml.safe_load(path.read_text())
        expected = expected_manifest(root, network, config)
        require(actual == expected, f"{network} writer-runtime manifest drift")
        modules = {module["name"]: module for module in actual["modules"]}
        require(len(modules) == len(actual["modules"]) == 23, f"{network} module set is not exact")
        require(set(actual["params"]) == set(CONFIGURED_MODULES), f"{network} configured-module set drift")
        diagnostic = modules["map_writer_events"]
        require(diagnostic["initialBlock"] == config["initial_blocks"]["nonfungible_position_manager"], f"{network} diagnostic NPM gate drift")
        require(diagnostic["inputs"] == [{"params": "string"}, {"source": "sf.ethereum.type.v2.Block"}], f"{network} diagnostic inputs drift")
        require(diagnostic["output"] == {"type": "proto:uniswap.writer.v1.WriterEvents"}, f"{network} diagnostic output drift")
        graph_out = modules["graph_out"]
        require(graph_out["output"] == {"type": "proto:sf.substreams.entity.v1.EntityChanges"}, f"{network} graph_out output changed")
        require(not any(item.get("map") == "map_writer_events" or item.get("store") == "map_writer_events" for item in graph_out["inputs"]), f"{network} graph_out consumes the diagnostic map")
        reachable = {"graph_out"}
        pending = ["graph_out"]
        while pending:
            name = pending.pop()
            for item in modules[name].get("inputs", []):
                dependency = item.get("map") or item.get("store")
                if dependency and dependency not in reachable:
                    reachable.add(dependency)
                    pending.append(dependency)
        require("map_writer_events" not in reachable, f"{network} diagnostic map has a transitive path to graph_out")
        require(all(not any(item.get("map") == "map_writer_events" or item.get("store") == "map_writer_events" for item in module.get("inputs", [])) for name, module in modules.items() if name != "map_writer_events"), f"{network} diagnostic map has a consumer")
        manifests[network] = actual
    require(manifests["mainnet"]["binaries"] == manifests["base"]["binaries"], "manifests do not reference one shared WASM")
    return manifests


def verify_fixture(root: Path) -> None:
    fixture = json.loads((root / "uniswap-v3/writer-runtime/fixtures/events-v1.json").read_text())
    require(set(fixture) == {"format_version", "fixture_version", "quantity_encoding", "addresses", "cases"}, "writer fixture key drift")
    require([case["id"] for case in fixture["cases"]] == ["transfer-only-mainnet", "all-occurrences-global-order-and-filtering-mainnet", "base-npm-gate"], "writer fixture case/order drift")
    all_case = fixture["cases"][1]
    require(all_case["expected_ordinals"] == [10, 20, 30, 40, 50], "global-order expectation drift")
    raw = json.dumps(fixture)
    require("115792089237316195423570985008687907853269984665640564039457584007913129639935" in raw, "max uint256 fixture missing")


def load_runtime_contract(root: Path) -> dict[str, object]:
    path = root / "uniswap-v3/writer-runtime/contract-v1.json"
    require(sha256(path) == CONTRACT_SHA256, "writer-runtime contract raw digest drift")
    contract = json.loads(path.read_text())
    require(contract["format_version"] == 1, "writer-runtime contract format drift")
    require(contract["contract_version"] == "uniswap-v3-writer-runtime/v1", "writer-runtime contract version drift")
    require(contract["mode"] == "diagnostic-only", "writer-runtime mode promoted")
    require(contract["truth_boundary"] == derive_tranche_truth_boundary(), "writer-runtime contract truth boundary drift")
    require(contract["ordered_materialization"] == [
        {"path": "uniswap-v3/chain-config/runtime.patch", "sha256": "4f87d22239b84aebca6712a72e2c4047b0735e911756973b6e7c228fe455e8ae"},
        {"path": "uniswap-v3/writer-runtime/runtime.patch", "sha256": "2514c67179b92c583fef1b092caa6486f14f0008694ac3660b8f708417e1bb53"},
    ], "writer-runtime patch order or binding drift")
    for artifact in (*contract["ordered_materialization"], *contract["repository_artifacts"].values()):
        require(sha256(root / artifact["path"]) == artifact["sha256"], f'bound artifact drift: {artifact["path"]}')
    require(contract["repository_artifacts"]["clippy_baseline"]["sha256"] == CLIPPY_BASELINE_SHA256, "Clippy contract binding drift")
    require(contract["base_origins"] == {
        "factory_runtime_and_factory_creation": 1_371_679,
        "nonfungible_position_manager_gate": 1_371_713,
        "evidence_basis": ["QmPW root manifest", "uniswap-v3 graft ancestry v2"],
        "independent_bytecode_creation_proof": False,
    }, "Base origin evidence boundary drift")
    require(contract["package_contract"] == {
        "module_count": 23,
        "diagnostic_module": "map_writer_events",
        "diagnostic_consumers": [],
        "graph_out_output": "proto:sf.substreams.entity.v1.EntityChanges",
        "shared_wasm_binary_count": 1,
        "both_packages_must_embed_byte_identical_wasm": True,
        "binary_type": "wasm/rust-v1",
        "module_binary_index": 0,
        "module_binary_entrypoint": "module_name",
        "stable_module_structure_sha256": PACKAGE_MODULE_STRUCTURE_SHA256,
        "module_hash_algorithm": PACKAGE_MODULE_HASH_ALGORITHM,
        "module_hashes_recomputed_from_embedded_wasm": True,
        "protobuf_descriptor_count": PACKAGE_DESCRIPTOR_COUNT,
        "protobuf_descriptor_set_sha256": PACKAGE_DESCRIPTOR_SET_SHA256,
        "writer_descriptor_sha256": WRITER_DESCRIPTOR_SHA256,
    }, "writer package contract drift")
    return contract


def verify_overlay_static(root: Path) -> None:
    patch = root / "uniswap-v3/writer-runtime/runtime.patch"
    text = patch.read_text()
    files = set(re.findall(r"^diff --git a/(\S+) b/\1$", text, re.MULTILINE))
    require(files == EXPECTED_PATCH_FILES, f"writer patch file set drift: {sorted(files)}")
    require("diff --git a/src/writer_runtime.rs b/src/writer_runtime.rs" in text, "writer runtime missing from patch")
    require("pub fn map_writer_events" in text, "diagnostic handler missing from patch")
    require("pub fn graph_out" not in text, "writer patch modifies graph_out")
    require("block.logs()" in text and "if log.address != manager" in text, "writer runtime is not direct successful-receipt/address scanning")
    require("duplicate writer-event ordinal" in text, "duplicate ordinal refusal missing")
    require("writer-event transaction hash must be 32 bytes" in text, "transaction identity width refusal missing")
    require("malformed recognized" in text, "malformed recognized-event refusal missing")
    require("rpc::eth_call" not in text and "StoreSet" not in text and "StoreAdd" not in text, "writer tranche adds an RPC call or store")

    source = root / "uniswap-v3/source"
    result = subprocess.run(["patch", "--directory", str(source), "--strip", "1", "--forward", "--batch", "--dry-run"], input=text, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    require(result.returncode != 0, "writer patch unexpectedly applies before ChainConfig")


def non_build_files(directory: Path) -> dict[str, Path]:
    return {path.relative_to(directory).as_posix(): path for path in directory.rglob("*") if path.is_file() and "target" not in path.relative_to(directory).parts}


def materialize_pinned_source(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    records = subprocess.check_output(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", "HEAD:uniswap-v3/source"]
    ).split(b"\0")
    for record in records:
        if not record:
            continue
        metadata, raw_relative = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode().split()
        require(object_type == "blob", f"unexpected pinned source object type {object_type}")
        relative = raw_relative.decode()
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            subprocess.check_output(["git", "-C", str(root), "cat-file", "blob", object_id])
        )
        path.chmod(0o755 if mode == "100755" else 0o644)


def materialize_expected(root: Path, destination: Path) -> None:
    materialize_pinned_source(root, destination)
    for patch in (root / "uniswap-v3/chain-config/runtime.patch", root / "uniswap-v3/writer-runtime/runtime.patch"):
        subprocess.run(["patch", "--directory", str(destination), "--strip", "1", "--forward", "--batch"], input=patch.read_text(), text=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (destination / "configs").mkdir(exist_ok=True)
    (destination / "fixtures").mkdir(exist_ok=True)
    for path in (root / "uniswap-v3/chain-config/configs").glob("*.json"):
        shutil.copy2(path, destination / "configs" / path.name)
    for path in (root / "uniswap-v3/writer-runtime/configs").glob("*.json"):
        shutil.copy2(path, destination / "configs" / path.name)
    shutil.copy2(root / "uniswap-v3/writer-runtime/segment-profiles-v1.json", destination / "configs/segment-profiles-v1.json")
    shutil.copy2(root / "uniswap-v3/writer-runtime/fixtures/events-v1.json", destination / "fixtures/events-v1.json")
    for path in (root / "uniswap-v3/writer-runtime/manifests").glob("substreams.*.yaml"):
        shutil.copy2(path, destination / path.name)


def verify_toolchain(runtime: Path) -> None:
    cargo = tomllib.loads((runtime / "Cargo.toml").read_text())
    expected_dependencies = {
        "prost": "=0.13.3",
        "prost-types": "=0.13.3",
        "substreams": "=0.6.4",
        "substreams-ethereum": "=0.10.6",
        "substreams-entity-change": "=2.0.0",
        "pest": "=2.7.14",
        "pest_derive": "=2.7.14",
        "pest_generator": "=2.7.14",
        "pest_meta": "=2.7.14",
    }
    for name, version in expected_dependencies.items():
        require(cargo["dependencies"].get(name) == version, f"direct dependency {name} is not pinned to {version}")
    require(cargo["build-dependencies"].get("prost-build") == "=0.13.3", "prost-build is not pinned to 0.13.3")
    require(cargo["build-dependencies"].get("substreams-ethereum") == "=0.10.6", "build-time substreams-ethereum is not pinned")
    lock = tomllib.loads((runtime / "Cargo.lock").read_text())
    versions = {}
    for package in lock["package"]:
        versions.setdefault(package["name"], set()).add(package["version"])
    for name, version in {"substreams": "0.6.4", "substreams-ethereum": "0.10.6", "substreams-entity-change": "2.0.0", "pest": "2.7.14", "pest_derive": "2.7.14", "pest_generator": "2.7.14", "pest_meta": "2.7.14"}.items():
        require(versions.get(name) == {version}, f"Cargo.lock {name} versions drift: {versions.get(name)}")
    for name in ("prost", "prost-types", "prost-build"):
        require("0.13.3" in versions.get(name, set()), f"Cargo.lock lacks {name} 0.13.3")
        require(versions[name] <= {"0.11.9", "0.13.3"}, f"Cargo.lock has unapproved {name} versions: {versions[name]}")
    require(tomllib.loads((runtime / "rust-toolchain.toml").read_text())["toolchain"]["channel"] == "1.79.0", "Rust toolchain is not exact 1.79.0")
    build = (runtime / "build.rs").read_text()
    require("Abigen" not in build and "write_to_file" not in build, "build.rs still mutates checked-in ABI bindings")


def verify_protobuf(runtime: Path) -> None:
    require(sha256(runtime / "proto/uniswap/v1/writer.proto") == PROTO_SHA256, "writer proto digest drift")
    require(sha256(runtime / "src/pb/uniswap.writer.v1.rs") == GENERATED_PROTO_SHA256, "checked-in writer protobuf binding digest drift")
    proto = (runtime / "proto/uniswap/v1/writer.proto").read_text()
    require("package uniswap.writer.v1;" in proto, "writer protobuf namespace drift")
    require("repeated WriterEvent events = 1;" in proto and "oneof event" in proto, "writer protobuf is not one repeated oneof stream")
    expected_fields = {"ordinal": 1, "transaction_hash": 2, "block_number": 3, "transaction_log_index": 4, "block_log_index": 5, "contract_address": 6}
    for name, number in expected_fields.items():
        require(re.search(rf"\b{name}\s*=\s*{number};", proto) is not None, f"writer protobuf descriptor drift for {name}")


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object]) -> Path:
    require(runtime.is_dir(), f"runtime directory missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="uniswap-v3-writer-expected-") as temporary:
        expected = Path(temporary) / "runtime"
        materialize_expected(root, expected)
        source_files = non_build_files(root / "uniswap-v3/source")
        runtime_files = non_build_files(runtime)
        expected_files = non_build_files(expected)
        changed = {relative for relative in set(source_files) | set(runtime_files) if relative not in source_files or relative not in runtime_files or source_files[relative].read_bytes() != runtime_files[relative].read_bytes()}
        require(changed == EXPECTED_RUNTIME_CHANGES, f"materialized runtime change set drift: {sorted(changed)}")
        require(set(runtime_files) == set(expected_files), "materialized runtime file set differs from exact two-patch reconstruction")
        for relative, path in expected_files.items():
            require(runtime_files[relative].read_bytes() == path.read_bytes(), f"materialized runtime content drift: {relative}")
            require(runtime_files[relative].stat().st_mode & 0o111 == path.stat().st_mode & 0o111, f"materialized runtime mode drift: {relative}")
    for abi in ("erc20.rs", "factory.rs", "pool.rs", "positionmanager.rs"):
        require((runtime / f"src/abi/{abi}").read_bytes() == (root / f"uniswap-v3/source/src/abi/{abi}").read_bytes(), f"checked-in ABI binding mutated: {abi}")
    require(sha256(runtime / "abis/NonfungiblePositionManager.json") == NPM_ABI_SHA256, "NPM ABI drift")
    verify_toolchain(runtime)
    verify_protobuf(runtime)
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized contract artifact drift: {relative}")
    return runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"


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
    fields = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, offset = read_varint(data, offset)
        elif wire == 2:
            length, offset = read_varint(data, offset)
            require(offset + length <= len(data), "truncated protobuf field")
            value, offset = data[offset : offset + length], offset + length
        elif wire in (1, 5):
            length = 8 if wire == 1 else 4
            require(offset + length <= len(data), "truncated fixed protobuf field")
            value, offset = data[offset : offset + length], offset + length
        else:
            raise VerificationError(f"unsupported protobuf wire type {wire}")
        fields.append((number, wire, value))
    return fields


def embedded_wasm_binaries(package: Path) -> list[bytes]:
    modules = [value for number, wire, value in wire_fields(package.read_bytes()) if number == 6 and wire == 2]
    require(len(modules) == 1, f"{package} Modules envelope drift")
    binaries = [value for number, wire, value in wire_fields(modules[0]) if number == 2 and wire == 2]
    output = []
    for binary in binaries:
        contents = [value for number, wire, value in wire_fields(binary) if number == 2 and wire == 2]
        require(len(contents) == 1, f"{package} binary content drift")
        output.append(contents[0])
    require(output, f"{package} contains no WASM binary")
    return output


def verify_package_binary_bindings(package: Path, expected_module_names: list[str]) -> bytes:
    envelopes = [
        value
        for number, wire, value in wire_fields(package.read_bytes())
        if number == 6 and wire == 2
    ]
    require(len(envelopes) == 1, f"{package} Modules envelope drift")
    fields = wire_fields(envelopes[0])
    module_payloads = [value for number, wire, value in fields if number == 1 and wire == 2]
    binary_payloads = [value for number, wire, value in fields if number == 2 and wire == 2]
    require(len(binary_payloads) == 1, f"{package} binary inventory drift")
    binary_fields = wire_fields(binary_payloads[0])
    binary_types = [value.decode() for number, wire, value in binary_fields if number == 1 and wire == 2]
    binary_contents = [value for number, wire, value in binary_fields if number == 2 and wire == 2]
    require(binary_types == ["wasm/rust-v1"], f"{package} binary type drift")
    require(len(binary_contents) == 1, f"{package} binary content drift")

    bindings = []
    for payload in module_payloads:
        module_fields = wire_fields(payload)
        names = [value.decode() for number, wire, value in module_fields if number == 1 and wire == 2]
        indexes = [value for number, wire, value in module_fields if number == 4 and wire == 0]
        entrypoints = [value.decode() for number, wire, value in module_fields if number == 5 and wire == 2]
        block_filters = [value for number, wire, value in module_fields if number == 9 and wire == 2]
        require(len(names) == 1 and len(indexes) <= 1 and len(entrypoints) == 1, f"{package} module binary binding shape drift")
        require(not block_filters, f"{package} unexpected module block filter")
        bindings.append((names[0], indexes[0] if indexes else 0, entrypoints[0]))
    require(
        bindings == [(name, 0, name) for name in expected_module_names],
        f"{package} module binary index/entrypoint binding drift",
    )
    return binary_contents[0]


def package_descriptors(package: Path) -> list[bytes]:
    return [
        value
        for number, wire, value in wire_fields(package.read_bytes())
        if number == 1 and wire == 2
    ]


def verify_descriptor_payloads(
    descriptors: list[bytes],
    expected_count: int,
    expected_set_sha256: str,
    expected_writer_sha256: str,
    label: str,
) -> None:
    require(len(descriptors) == expected_count, f"{label} protobuf descriptor count drift")
    framed = b"".join(len(descriptor).to_bytes(8, "big") + descriptor for descriptor in descriptors)
    require(
        hashlib.sha256(framed).hexdigest() == expected_set_sha256,
        f"{label} protobuf descriptor set drift",
    )
    writer_descriptors = []
    for descriptor in descriptors:
        fields = wire_fields(descriptor)
        names = [value.decode() for number, wire, value in fields if number == 1 and wire == 2]
        packages = [value.decode() for number, wire, value in fields if number == 2 and wire == 2]
        if packages == ["uniswap.writer.v1"]:
            writer_descriptors.append((names, descriptor))
    require(len(writer_descriptors) == 1, f"{label} writer protobuf descriptor multiplicity drift")
    names, descriptor = writer_descriptors[0]
    require(names == ["uniswap/v1/writer.proto"], f"{label} writer protobuf path drift")
    require(
        hashlib.sha256(descriptor).hexdigest() == expected_writer_sha256,
        f"{label} writer protobuf descriptor drift",
    )


def verify_package_descriptors(package: Path) -> None:
    verify_descriptor_payloads(
        package_descriptors(package),
        PACKAGE_DESCRIPTOR_COUNT,
        PACKAGE_DESCRIPTOR_SET_SHA256,
        WRITER_DESCRIPTOR_SHA256,
        str(package),
    )


def expected_package_module_structure(manifest: dict[str, object]) -> list[dict[str, object]]:
    modules = {module["name"]: module for module in manifest["modules"]}
    starts: dict[str, int] = {}

    def initial_block(name: str, pending: frozenset[str] = frozenset()) -> int:
        require(name not in pending, f"module dependency cycle at {name}")
        if name in starts:
            return starts[name]
        module = modules[name]
        if "initialBlock" in module:
            value = module["initialBlock"]
        else:
            dependencies = [
                item.get("map") or item.get("store")
                for item in module.get("inputs", [])
                if item.get("map") or item.get("store")
            ]
            require(dependencies, f"module {name} has no explicit or inherited initial block")
            value = max(initial_block(dependency, pending | {name}) for dependency in dependencies)
        starts[name] = value
        return value

    output = []
    for module in manifest["modules"]:
        name = module["name"]
        inputs = []
        for item in module.get("inputs", []):
            if "params" in item:
                require(item == {"params": "string"}, f"module {name} params input drift")
                inputs.append({"type": "params", "name": manifest["params"][name]})
            elif "source" in item:
                inputs.append({"type": "source", "name": item["source"]})
            elif "map" in item:
                inputs.append({"type": "map", "name": item["map"]})
            elif "store" in item:
                inputs.append(
                    {
                        "type": "store",
                        "name": item["store"],
                        "mode": item.get("mode", "get"),
                    }
                )
            else:
                raise VerificationError(f"module {name} contains an unsupported input")
        expected = {
            "name": name,
            "kind": module["kind"],
            "inputs": inputs,
            "initial_block": initial_block(name),
        }
        if module["kind"] == "map":
            expected["output_type"] = module["output"]["type"]
        elif module["kind"] == "store":
            expected["value_type"] = module["valueType"]
            expected["update_policy"] = module["updatePolicy"]
        else:
            raise VerificationError(f"module {name} has unsupported kind {module['kind']}")
        output.append(expected)
    return output


def actual_package_module_structure(modules: list[dict[str, object]]) -> list[dict[str, object]]:
    keys = {
        "map": ("name", "kind", "inputs", "output_type", "initial_block"),
        "store": ("name", "kind", "inputs", "value_type", "update_policy", "initial_block"),
    }
    output = []
    for module in modules:
        require(module.get("kind") in keys, f"unsupported packaged module kind {module.get('kind')}")
        required = {*keys[module["kind"]], "hash"}
        actual = set(module)
        require(
            required <= actual <= required | {"documentation"},
            f"packaged module graph field drift for {module.get('name')}",
        )
        output.append({key: module[key] for key in keys[module["kind"]]})
    return output


def verify_package_module_structure(
    modules: list[dict[str, object]],
    manifest: dict[str, object],
    network: str,
) -> None:
    require(
        actual_package_module_structure(modules)
        == expected_package_module_structure(manifest),
        f"{network} packaged module graph differs from the exact manifest",
    )


def expected_package_module_hashes(
    manifest: dict[str, object],
    wasm: bytes,
) -> list[str]:
    """Independently reproduce Substreams v1.20.3's package module hashes."""

    require(set(manifest["binaries"]) == {"default"}, "package binary inventory drift")
    binary = manifest["binaries"]["default"]
    require(binary["type"] == "wasm/rust-v1", "package binary type drift")
    require(not any("blockFilter" in module for module in manifest["modules"]), "block filters are not part of the exact package contract")

    ordered = [module["name"] for module in manifest["modules"]]
    modules = {module["name"]: module for module in manifest["modules"]}
    structure = {
        module["name"]: module
        for module in expected_package_module_structure(manifest)
    }
    dependencies = {
        name: [
            item.get("map") or item.get("store")
            for item in module.get("inputs", [])
            if item.get("map") or item.get("store")
        ]
        for name, module in modules.items()
    }
    for name, names in dependencies.items():
        require(all(dependency in modules for dependency in names), f"module {name} dependency drift")

    def ancestor_names(name: str) -> list[str]:
        found: set[str] = set()
        pending: set[str] = set()

        def visit(current: str) -> None:
            require(current not in pending, f"module dependency cycle at {current}")
            if current in found:
                return
            pending.add(current)
            found.add(current)
            for dependency in dependencies[current]:
                visit(dependency)
            pending.remove(current)

        for dependency in dependencies[name]:
            visit(dependency)
        return [candidate for candidate in ordered if candidate in found]

    cache: dict[str, bytes] = {}
    hashing: set[str] = set()

    def module_hash(name: str) -> bytes:
        if name in cache:
            return cache[name]
        require(name not in hashing, f"module dependency cycle at {name}")
        hashing.add(name)
        module = modules[name]
        payload = bytearray()
        payload.extend(b"initial_block")
        payload.extend(int(structure[name]["initial_block"]).to_bytes(8, "little"))
        payload.extend(b"kind")
        payload.extend(module["kind"].encode())
        payload.extend(b"binary")
        payload.extend(binary["type"].encode())
        payload.extend(wasm)
        payload.extend(b"inputs")
        for item in module.get("inputs", []):
            if "params" in item:
                input_type, value = "params", manifest["params"][name]
            elif "source" in item:
                input_type, value = "source", item["source"]
            elif "map" in item:
                input_type, value = "map", ""
            elif "store" in item:
                input_type, value = "store", ""
            else:
                raise VerificationError(f"module {name} contains an unsupported input")
            payload.extend(input_type.encode())
            payload.extend(value.encode())
        payload.extend(b"ancestors")
        for ancestor in ancestor_names(name):
            payload.extend(module_hash(ancestor))
        payload.extend(b"entrypoint")
        payload.extend(name.encode())
        digest = hashlib.sha1(payload).digest()
        hashing.remove(name)
        cache[name] = digest
        return digest

    return [module_hash(name).hex() for name in ordered]


def verify_package_module_hashes(
    modules: list[dict[str, object]],
    manifest: dict[str, object],
    wasm: bytes,
    network: str,
) -> None:
    require(
        [module["hash"] for module in modules]
        == expected_package_module_hashes(manifest, wasm),
        f"{network} packaged module hash/binary binding drift",
    )


def verify_packages(runtime_wasm: Path, packages: dict[str, Path]) -> None:
    require(runtime_wasm.is_file(), f"shared runtime WASM missing: {runtime_wasm}")
    expected = runtime_wasm.read_bytes()
    embedded = {}
    for network, path in packages.items():
        require(path.is_file(), f"missing {network} package")
        binaries = embedded_wasm_binaries(path)
        require(len(binaries) == 1, f"{network} package must contain exactly one WASM")
        embedded[network] = binaries[0]
        verify_package_descriptors(path)
        info = json.loads(subprocess.check_output(["substreams", "info", "--json", str(path)], text=True))
        require(info["network"] == network, f"{network} package network drift")
        require(info["name"] == f"uniswap_v3_{network}_backfill" and info["version"] == "v0.4.0", f"{network} package identity drift")
        manifest = yaml.safe_load((runtime_wasm.parents[3] / f"substreams.{network}.yaml").read_text())
        require(
            verify_package_binary_bindings(
                path,
                [module["name"] for module in manifest["modules"]],
            )
            == embedded[network],
            f"{network} package binary parser disagreement",
        )
        verify_package_module_structure(info["modules"], manifest, network)
        require(
            canonical_sha256(expected_package_module_structure(manifest))
            == PACKAGE_MODULE_STRUCTURE_SHA256[network],
            f"{network} stable module structure digest drift",
        )
        verify_package_module_hashes(
            info["modules"], manifest, embedded[network], network
        )
        require(len(info["modules"]) == 23, f"{network} package module count drift")
        modules = {module["name"]: module for module in info["modules"]}
        require(set(modules) == {module["name"] for module in manifest["modules"]}, f"{network} packaged module set drift")
        writer = modules["map_writer_events"]
        require(writer["kind"] == "map", f"{network} packaged writer kind drift")
        require(writer["inputs"] == [
            {"type": "params", "name": selector(network)},
            {"type": "source", "name": "sf.ethereum.type.v2.Block"},
        ], f"{network} packaged writer inputs drift")
        require(writer["output_type"] == "proto:uniswap.writer.v1.WriterEvents", f"{network} packaged writer output drift")
        require(writer["initial_block"] == (12_369_651 if network == "mainnet" else 1_371_713), f"{network} packaged writer start drift")
        require(modules["graph_out"]["output_type"] == "proto:sf.substreams.entity.v1.EntityChanges", f"{network} packaged graph_out output drift")
        require(all(
            input_item.get("name") != "map_writer_events"
            for name, module in modules.items()
            if name != "map_writer_events"
            for input_item in module.get("inputs", [])
        ), f"{network} packaged diagnostic map has a consumer")
    require(embedded == {"mainnet": expected, "base": expected}, "packages do not embed byte-identical shared WASM")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--mainnet-spkg", type=Path)
    parser.add_argument("--base-spkg", type=Path)
    args = parser.parse_args()
    if bool(args.mainnet_spkg) != bool(args.base_spkg):
        parser.error("--mainnet-spkg and --base-spkg must be passed together")
    if args.mainnet_spkg and not args.runtime:
        parser.error("package checks require --runtime")
    try:
        root = args.root.resolve()
        contract = load_runtime_contract(root)
        profiles = load_profiles(root)
        configs = load_configs(root)
        load_manifests(root, configs)
        verify_fixture(root)
        verify_overlay_static(root)
        for network, start, end, _ in EXPECTED_RANGES:
            select_profile(profiles, network, start)
            if end is not None:
                select_profile(profiles, network, end)
        runtime_wasm = None
        if args.runtime:
            runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract)
        if args.mainnet_spkg:
            verify_packages(runtime_wasm, {"mainnet": args.mainnet_spkg.resolve(), "base": args.base_spkg.resolve()})
        print("verified exact eight-segment diagnostic writer runtime, config/package isolation, fixtures, and conservative gates")
        return 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError, VerificationError, subprocess.CalledProcessError) as error:
        print(f"Uniswap V3 writer-runtime verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
