#!/usr/bin/env python3
"""Fail-closed verification for provider-free Uniswap V3 NPM source blocks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import yaml


OVERLAY = Path("uniswap-v3/npm-source-block")
CONTRACT_PATH = OVERLAY / "contract-v1.json"
CONTRACT_SHA256 = "701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5"
SEMANTICS_SHA256 = "267dfc6b7240c36cdf345553e02a4f7b5332fa70548349bc6ef4b3075b4fcb4b"
WRITER_RUNTIME_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
WRITER_PROFILES_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
WRITER_CONTRACT_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
WRITER_PROTO_SHA256 = "f87b4bc718349bae2ff8fe799e4a4dadbb507240b7b6e9bc8d7a199299e33c59"
SEGMENT_MATRIX_SHA256 = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
EXECUTION_ORDER_SHA256 = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"
SOURCE_PROTO_SHA256 = "bd394a11de37449710f0fd7dc10eac4e7f4ad299141a9fd54ec156980246fe1e"
SOURCE_BINDING_SHA256 = "0dba8501e790d4efd0cda3cf64c9eddbca01cb9ce90da3931568224b38c7be3d"
SOURCE_CODE_SHA256 = "5dac40f6f81223b0e373eb69e12a652754bc92879c0da28244ba80849b95c177"
SOURCE_LIB_SHA256 = "b5b53f6d349c4c5864eeea14d8a37858089c33789ac2c2542aadd386e4034d96"
SOURCE_CARGO_SHA256 = "f77b5c5ade0e9f122a75c76ff023fcf6da12226cde5ef16009f977bdd91da1b8"
SOURCE_CARGO_LOCK_SHA256 = "16fd0e4d795edfee345399ff79be9d68640b6bcea266363e06a75933893895ab"
MATERIALIZER_SHA256 = "48d677ebcc8808e299f97efdc772ce53ec50d95fdc02d4f6a5b0198468f09f72"
MAINNET_MANIFEST_SHA256 = "8241798587b74762f5383f730f7e840dc906fd33ca1deaa91f7c90bcc105022c"
BASE_MANIFEST_SHA256 = "26ec892f55fe31f5253ac28db815e3abb17a505c0c923484cb594f81515ecbd0"
SOURCE_DESCRIPTOR_COUNT = 16
SOURCE_DESCRIPTOR_SET_SHA256 = "2cca938c9695f93e4529337aa7557011c6b047991910b79cfcfa681673372c55"
SOURCE_DESCRIPTOR_SHA256 = "777168d4bedafe072acc88ed33a6292f761d72e91d9508e2071719a84876a603"

NETWORK = {
    "mainnet": {
        "initial_block": 12_369_651,
        "selector": "version=2;network=mainnet;sha256=1438edbd94e492190ce15d059ab766a03022f7255fdfa1cde9ef32e78a0fe547",
        "package": "uniswap_v3_mainnet_npm_source",
    },
    "base": {
        "initial_block": 1_371_713,
        "selector": "version=2;network=base;sha256=a227784961973c72b47f663d7ee66b2f9306372bf2232dfb416abbba6ccf8df0",
        "package": "uniswap_v3_base_npm_source",
    },
}

EXPECTED_OVERLAY_FILES = {
    "README.md",
    "contract-v1.json",
    "docs/eligibility.md",
    "docs/provenance.md",
    "manifests/substreams.npm-source.base.yaml",
    "manifests/substreams.npm-source.mainnet.yaml",
    "npm-source-block-v1.json",
    "proto/uniswap/npm/source/v1/npm_source_block.proto",
    "runtime/Cargo.toml",
    "runtime/Cargo.lock",
    "runtime/src/lib.rs",
    "runtime/src/npm_source_block.rs",
    "runtime/src/pb/mod.rs",
    "runtime/src/pb/uniswap.npm.source.v1.rs",
}

EXPECTED_RUNTIME_EXTRAS = {
    "npm-source-block-runtime/Cargo.lock",
    "npm-source-block-runtime/Cargo.toml",
    "npm-source-block-runtime/configs/npm-source-block-v1.json",
    "npm-source-block-runtime/configs/segment-profiles-v1.json",
    "npm-source-block-runtime/rust-toolchain.toml",
    "npm-source-block-runtime/rustfmt.toml",
    "npm-source-block-runtime/src/lib.rs",
    "npm-source-block-runtime/src/npm_source_block.rs",
    "npm-source-block-runtime/src/pb/mod.rs",
    "npm-source-block-runtime/src/pb/uniswap.npm.source.v1.rs",
    "npm-source-block-runtime/src/pb/uniswap.writer.v1.rs",
    "npm-source-package/README.md",
    "npm-source-package/substreams.npm-source.base.yaml",
    "npm-source-package/substreams.npm-source.mainnet.yaml",
    "proto/uniswap/npm/source/v1/npm_source_block.proto",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_keys(value: dict[str, object], expected: set[str], name: str) -> None:
    require(set(value) == expected, f"{name} field set drift: {sorted(value)}")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_writer_verifier(root: Path):
    return load_module(root / "scripts/verify-uniswap-v3-writer-runtime.py", "npm_source_writer_verifier")


def expected_artifacts() -> dict[str, tuple[str, str]]:
    return {
        "readme": ("uniswap-v3/npm-source-block/README.md", "dc15bd710adaed16aa679b3cb0d39bbf862b04b21b2f41764d2f1465b9eb5021"),
        "eligibility": ("uniswap-v3/npm-source-block/docs/eligibility.md", "aa5340333aae541bab46391a45b42ab6978b3893c1e5db684e996e8fae032ccc"),
        "provenance": ("uniswap-v3/npm-source-block/docs/provenance.md", "f1dc73686abd74c39f0b37f62a8d0b9fdbf5e8314080de42a610b10c11415220"),
        "semantics": ("uniswap-v3/npm-source-block/npm-source-block-v1.json", SEMANTICS_SHA256),
        "source_proto": (
            "uniswap-v3/npm-source-block/proto/uniswap/npm/source/v1/npm_source_block.proto",
            SOURCE_PROTO_SHA256,
        ),
        "source_binding": (
            "uniswap-v3/npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs",
            SOURCE_BINDING_SHA256,
        ),
        "source_code": ("uniswap-v3/npm-source-block/runtime/src/npm_source_block.rs", SOURCE_CODE_SHA256),
        "source_lib": ("uniswap-v3/npm-source-block/runtime/src/lib.rs", SOURCE_LIB_SHA256),
        "source_cargo": ("uniswap-v3/npm-source-block/runtime/Cargo.toml", SOURCE_CARGO_SHA256),
        "source_cargo_lock": (
            "uniswap-v3/npm-source-block/runtime/Cargo.lock",
            SOURCE_CARGO_LOCK_SHA256,
        ),
        "mainnet_manifest": (
            "uniswap-v3/npm-source-block/manifests/substreams.npm-source.mainnet.yaml",
            MAINNET_MANIFEST_SHA256,
        ),
        "base_manifest": (
            "uniswap-v3/npm-source-block/manifests/substreams.npm-source.base.yaml",
            BASE_MANIFEST_SHA256,
        ),
        "materializer": ("scripts/materialize-uniswap-v3-npm-source-block.sh", MATERIALIZER_SHA256),
    }


def expected_materialized_sha256() -> dict[str, str]:
    return {
        "npm-source-block-runtime/Cargo.lock": SOURCE_CARGO_LOCK_SHA256,
        "npm-source-block-runtime/Cargo.toml": SOURCE_CARGO_SHA256,
        "npm-source-block-runtime/configs/npm-source-block-v1.json": SEMANTICS_SHA256,
        "npm-source-block-runtime/configs/segment-profiles-v1.json": WRITER_PROFILES_SHA256,
        "npm-source-block-runtime/rust-toolchain.toml": "efa0faa3c4987d0cd1df72b56623b94ffb15f0ab5e5617536f43980d02bc9a2c",
        "npm-source-block-runtime/rustfmt.toml": "f33bda44a494d17c95b7bc1b3dd88c203030b75be766f3a7f9b63ef45d960bb0",
        "npm-source-block-runtime/src/lib.rs": SOURCE_LIB_SHA256,
        "npm-source-block-runtime/src/npm_source_block.rs": SOURCE_CODE_SHA256,
        "npm-source-block-runtime/src/pb/mod.rs": "6be07e6fcbc554e660e0f6f00eda78bef08e45909fd0b15ea154340947bb13d5",
        "npm-source-block-runtime/src/pb/uniswap.npm.source.v1.rs": SOURCE_BINDING_SHA256,
        "npm-source-block-runtime/src/pb/uniswap.writer.v1.rs": "b41a3890341f96d8b8eb5afb1345f47c28f6690668097637fcf46699217a9184",
        "npm-source-package/README.md": expected_artifacts()["readme"][1],
        "npm-source-package/substreams.npm-source.base.yaml": BASE_MANIFEST_SHA256,
        "npm-source-package/substreams.npm-source.mainnet.yaml": MAINNET_MANIFEST_SHA256,
        "proto/uniswap/npm/source/v1/npm_source_block.proto": SOURCE_PROTO_SHA256,
    }


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "NPM source runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "NPM source runtime contract raw digest drift")
    contract = json.loads(path.read_text())
    exact_keys(
        contract,
        {
            "format_version",
            "contract_version",
            "mode",
            "source_authorities",
            "repository_artifacts",
            "materialized_runtime",
            "protobuf_contract",
            "module_contract",
            "truth_boundary",
        },
        "NPM source runtime contract",
    )
    require(
        (contract["format_version"], contract["contract_version"], contract["mode"])
        == (1, "uniswap-v3-npm-source-block-runtime/v1", "provider-free-source-only"),
        "unsupported NPM source runtime contract",
    )
    require(
        contract["source_authorities"]
        == {
            "writer_runtime_sha256": WRITER_RUNTIME_SHA256,
            "writer_profiles_sha256": WRITER_PROFILES_SHA256,
            "writer_contract_sha256": WRITER_CONTRACT_SHA256,
            "writer_proto_sha256": WRITER_PROTO_SHA256,
            "segment_matrix_sha256": SEGMENT_MATRIX_SHA256,
            "execution_order_sha256": EXECUTION_ORDER_SHA256,
        },
        "NPM source authority binding drift",
    )
    require(contract["repository_artifacts"] == {
        key: {"path": relative, "sha256": digest}
        for key, (relative, digest) in expected_artifacts().items()
    }, "NPM source repository artifact contract drift")
    for key, (relative, digest) in expected_artifacts().items():
        require(sha256(root / relative) == digest, f"NPM source repository artifact drift: {key}")
    require(
        contract["materialized_runtime"]
        == {
            "extra_files": sorted(EXPECTED_RUNTIME_EXTRAS),
            "sha256": expected_materialized_sha256(),
        },
        "NPM source materialized-runtime contract drift",
    )
    require(
        contract["protobuf_contract"]
        == {
            "namespace": "uniswap.npm.source.v1",
            "output_type": "proto:uniswap.npm.source.v1.NpmSourceBlock",
            "writer_events_tag": 1,
            "block_tag": 2,
            "transactions_tag": 3,
            "source_contract_sha256_tag": 4,
            "canonical_decode_required": True,
            "timestamp_seconds_validation": "positive whole second in protobuf Timestamp range; no post-projection Firehose cross-check",
            "writer_protobuf_changed": False,
            "provider_observations_present": False,
            "unresolved_error_classes_present": False,
            "package_descriptor_count": SOURCE_DESCRIPTOR_COUNT,
            "package_descriptor_set_sha256": SOURCE_DESCRIPTOR_SET_SHA256,
            "writer_descriptor_sha256": "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0",
            "source_descriptor_sha256": SOURCE_DESCRIPTOR_SHA256,
        },
        "NPM source protobuf contract drift",
    )
    require(
        contract["module_contract"]
        == {
            "module_names": ["map_writer_events", "map_npm_source_block"],
            "binary_names": ["writer", "npm_source"],
            "module_count": 2,
            "wasm_binary_count": 2,
            "source_inputs": ["sf.ethereum.type.v2.Block", "map_writer_events"],
            "source_params_added": False,
            "writer_wasm_must_match_original": True,
            "original_writer_module_count": 23,
            "source_package_inherits_complete_writer_descriptor_set": False,
            "original_writer_package_descriptor_set_must_match_baseline": True,
            "package_documentation_must_match_readme": True,
            "module_hash_algorithm": "substreams-v1.20.3-sha1",
            "package_determinism_required": True,
            "packages": {
                "mainnet": {
                    "name": "uniswap_v3_mainnet_npm_source",
                    "initial_block": 12_369_651,
                },
                "base": {
                    "name": "uniswap_v3_base_npm_source",
                    "initial_block": 1_371_713,
                },
            },
        },
        "NPM source module contract drift",
    )
    require(
        contract["truth_boundary"]
        == {
            "backfill_ready": False,
            "checkpoint_authority": False,
            "diagnostic_only": True,
            "graph_block_success_authority": False,
            "graph_out_added": False,
            "integrated_host_engine_added": False,
            "production_ready": False,
            "provider_observations_serialized": False,
            "rpc_calls_added": False,
            "source_module_implemented": True,
            "stores_added": False,
            "unresolved_errors_serialized": False,
        },
        "NPM source truth boundary promoted",
    )
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "npm-source-block-v1.json"
    require(sha256(path) == SEMANTICS_SHA256, "NPM source semantic contract raw digest drift")
    semantics = json.loads(path.read_text())
    require(
        semantics
        == {
            "format_version": 1,
            "contract_version": "uniswap-v3-npm-source-block/v1",
            "mode": "provider-free-source-only",
            "source_writer_runtime_sha256": WRITER_RUNTIME_SHA256,
            "source_writer_profiles_sha256": WRITER_PROFILES_SHA256,
            "source_writer_contract_sha256": WRITER_CONTRACT_SHA256,
            "source_writer_proto_sha256": WRITER_PROTO_SHA256,
            "source_segment_matrix_sha256": SEGMENT_MATRIX_SHA256,
            "source_execution_order_sha256": EXECUTION_ORDER_SHA256,
            "protobuf_namespace": "uniswap.npm.source.v1",
            "output_type": "proto:uniswap.npm.source.v1.NpmSourceBlock",
            "provider_observations_serialized": False,
            "unresolved_errors_serialized": False,
            "checkpoint_authority": False,
            "graph_block_success_authority": False,
            "backfill_ready": False,
            "production_ready": False,
        },
        "NPM source semantic contract drift",
    )
    return semantics


def verify_upstream(root: Path) -> None:
    require(sha256(root / "uniswap-v3/writer-runtime/contract-v1.json") == WRITER_RUNTIME_SHA256, "writer runtime authority drift")
    require(sha256(root / "uniswap-v3/writer-runtime/segment-profiles-v1.json") == WRITER_PROFILES_SHA256, "writer profiles authority drift")
    require(sha256(root / "uniswap-v3/graft-ancestry/v2/writer-compatibility.json") == WRITER_CONTRACT_SHA256, "writer source contract drift")
    require(sha256(root / "uniswap-v3/segment-writer-matrix/v1/contract.json") == SEGMENT_MATRIX_SHA256, "segment writer matrix authority drift")
    require(sha256(root / "uniswap-v3/execution-order/v1/contract.json") == EXECUTION_ORDER_SHA256, "execution-order authority drift")
    writer = load_writer_verifier(root)
    writer.load_runtime_contract(root)
    writer.load_profiles(root)
    with tempfile.TemporaryDirectory(prefix="npm-source-writer-proto-") as temporary:
        runtime = Path(temporary) / "runtime"
        writer.materialize_expected(root, runtime)
        require(sha256(runtime / "proto/uniswap/v1/writer.proto") == WRITER_PROTO_SHA256, "writer protobuf authority drift")


def verify_proto(root: Path) -> None:
    proto = root / OVERLAY / "proto/uniswap/npm/source/v1/npm_source_block.proto"
    require(sha256(proto) == SOURCE_PROTO_SHA256, "NPM source protobuf digest drift")
    text = proto.read_text()
    require("package uniswap.npm.source.v1;" in text, "NPM source protobuf namespace drift")
    require('import "uniswap/v1/writer.proto";' in text, "NPM source writer import drift")
    fields = {
        "writer_events": 1,
        "block": 2,
        "transactions": 3,
        "source_contract_sha256": 4,
        "number": 1,
        "hash": 2,
        "parent_hash": 3,
        "timestamp_seconds": 4,
        "index": 2,
        "gas_limit": 3,
        "gas_price_be": 4,
    }
    for name, tag in fields.items():
        require(re.search(rf"\b{name}\s*=\s*{tag};", text) is not None, f"NPM source protobuf field drift: {name}")
    require("Position" not in text and "PoolCall" not in text and "TokenRead" not in text, "provider observation leaked into source protobuf")


def load_manifests(root: Path) -> dict[str, dict[str, object]]:
    manifests = {}
    for network, expected in NETWORK.items():
        path = root / OVERLAY / "manifests" / f"substreams.npm-source.{network}.yaml"
        require(sha256(path) == (MAINNET_MANIFEST_SHA256 if network == "mainnet" else BASE_MANIFEST_SHA256), f"{network} source manifest digest drift")
        manifest = yaml.safe_load(path.read_text())
        require(manifest["network"] == network, f"{network} source manifest network drift")
        require(manifest["package"]["name"] == expected["package"] and manifest["package"]["version"] == "v0.1.0", f"{network} source package identity drift")
        require("doc" not in manifest["package"], f"{network} source manifest uses deprecated package.doc")
        require(set(manifest["binaries"]) == {"writer", "npm_source"}, f"{network} source binary set drift")
        require(
            manifest["binaries"]
            == {
                "writer": {
                    "type": "wasm/rust-v1",
                    "file": "../target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm",
                },
                "npm_source": {
                    "type": "wasm/rust-v1",
                    "file": "../npm-source-block-runtime/target/wasm32-unknown-unknown/release/uniswap_v3_npm_source_block.wasm",
                },
            },
            f"{network} source binary path drift",
        )
        require([module["name"] for module in manifest["modules"]] == ["map_writer_events", "map_npm_source_block"], f"{network} source module set/order drift")
        writer, source = manifest["modules"]
        require(writer["binary"] == "writer" and source["binary"] == "npm_source", f"{network} module/binary binding drift")
        require(writer["initialBlock"] == source["initialBlock"] == expected["initial_block"], f"{network} source initial block drift")
        require(writer["inputs"] == [{"params": "string"}, {"source": "sf.ethereum.type.v2.Block"}], f"{network} writer inputs drift")
        require(source["inputs"] == [{"source": "sf.ethereum.type.v2.Block"}, {"map": "map_writer_events"}], f"{network} source inputs drift")
        require(writer["output"]["type"] == "proto:uniswap.writer.v1.WriterEvents", f"{network} writer output drift")
        require(source["output"]["type"] == "proto:uniswap.npm.source.v1.NpmSourceBlock", f"{network} source output drift")
        require(manifest["params"] == {"map_writer_events": expected["selector"]}, f"{network} writer selector drift")
        require(manifest["protobuf"]["files"] == ["uniswap/v1/writer.proto", "uniswap/npm/source/v1/npm_source_block.proto"], f"{network} source protobuf set drift")
        require(manifest["protobuf"]["importPaths"] == ["../proto"], f"{network} source protobuf import path drift")
        require(
            set(manifest) == {"specVersion", "package", "protobuf", "binaries", "network", "modules", "params"},
            f"{network} source manifest top-level shape drift",
        )
        require(
            all(module["kind"] == "map" and module["name"] != "graph_out" for module in manifest["modules"]),
            f"{network} source manifest contains graph_out or Store modules",
        )
        manifests[network] = manifest
    return manifests


def verify_static_source(root: Path) -> None:
    require(
        (root / "scripts/materialize-uniswap-v3-npm-source-block.sh").stat().st_mode & 0o111,
        "NPM source materializer must be executable",
    )
    overlay_files = {
        path.relative_to(root / OVERLAY).as_posix()
        for path in (root / OVERLAY).rglob("*")
        if path.is_file() and "target" not in path.relative_to(root / OVERLAY).parts
    }
    require(overlay_files == EXPECTED_OVERLAY_FILES, f"NPM source overlay file set drift: {sorted(overlay_files)}")
    cargo = tomllib.loads((root / OVERLAY / "runtime/Cargo.toml").read_text())
    require(
        set(cargo["dependencies"])
        == {
            "hex",
            "pest",
            "pest_derive",
            "pest_generator",
            "pest_meta",
            "prost",
            "prost-types",
            "serde",
            "serde_json",
            "sha2",
            "substreams",
            "substreams-ethereum",
        },
        "NPM source runtime dependency set drift",
    )
    require(cargo.get("workspace") == {}, "NPM source runtime must be a standalone Cargo workspace")
    require(
        cargo.get("build-dependencies")
        == {"home": "=0.5.9", "indexmap": "=2.2.5", "tempfile": "=3.10.1"},
        "NPM source build-dependency pin drift",
    )
    require(cargo["dependencies"]["substreams"] == "=0.6.4", "NPM source substreams pin drift")
    require(cargo["dependencies"]["substreams-ethereum"] == "=0.10.6", "NPM source Ethereum pin drift")
    require(cargo["dependencies"]["prost"] == "=0.13.3", "NPM source prost pin drift")
    for dependency in ("pest", "pest_derive", "pest_generator", "pest_meta"):
        require(cargo["dependencies"][dependency] == "=2.7.14", f"NPM source {dependency} pin drift")
    lib = (root / OVERLAY / "runtime/src/lib.rs").read_text()
    source = (root / OVERLAY / "runtime/src/npm_source_block.rs").read_text()
    production = source.split("#[cfg(test)]", 1)[0]
    require("#[substreams::handlers::map]" in lib and "pub fn map_npm_source_block(" in lib, "NPM source handler missing")
    require("build_npm_source_block(&block, &writer_events)" in lib, "NPM source handler composition drift")
    unstable_sentinel = "Provider" + "Unavailable"
    for forbidden in (unstable_sentinel, "PossibleReorg", "reqwest::", "rpc::", "StoreGet", "EntityChanges"):
        require(forbidden not in production, f"forbidden host/provider symbol in NPM source runtime: {forbidden}")
    require("transaction.gas_used" not in production and "receipt.gas_used" not in production, "NPM source reads gas_used")
    expected_tests = {
        "all_eight_segment_boundaries_emit_deterministic_empty_source_frames",
        "referenced_transactions_are_successful_unique_sorted_and_use_transaction_gas",
        "missing_failed_duplicate_and_malformed_transaction_metadata_fail_closed",
        "block_identity_header_parent_and_timestamp_corruption_fail_closed",
        "writer_network_segment_contract_address_and_order_corruption_fail_closed",
        "canonical_decoder_rejects_unknown_fields_and_source_table_corruption",
    }
    require({name for name in expected_tests if f"fn {name}()" in source} == expected_tests, "NPM source adversarial Rust inventory drift")


def non_build_files(directory: Path) -> dict[str, Path]:
    return {
        path.relative_to(directory).as_posix(): path
        for path in directory.rglob("*")
        if path.is_file() and "target" not in path.relative_to(directory).parts
    }


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object]) -> tuple[Path, Path]:
    require(runtime.is_dir(), f"NPM source materialized runtime missing: {runtime}")
    writer = load_writer_verifier(root)
    with tempfile.TemporaryDirectory(prefix="npm-source-writer-baseline-") as temporary:
        baseline = Path(temporary) / "runtime"
        writer.materialize_expected(root, baseline)
        baseline_files = non_build_files(baseline)
        runtime_files = non_build_files(runtime)
        require(set(runtime_files) - set(baseline_files) == EXPECTED_RUNTIME_EXTRAS, "NPM source materialized extra-file set drift")
        require(set(baseline_files) <= set(runtime_files), "NPM source materialization removed writer files")
        for relative, baseline_path in baseline_files.items():
            require(runtime_files[relative].read_bytes() == baseline_path.read_bytes(), f"NPM source mutated writer runtime file: {relative}")
            require((runtime_files[relative].stat().st_mode & 0o111) == (baseline_path.stat().st_mode & 0o111), f"NPM source mutated writer runtime mode: {relative}")
    source_runtime = runtime / "npm-source-block-runtime"
    require(sha256(source_runtime / "Cargo.toml") == SOURCE_CARGO_SHA256, "materialized source Cargo drift")
    require(sha256(source_runtime / "Cargo.lock") == SOURCE_CARGO_LOCK_SHA256, "materialized source Cargo.lock drift")
    require(
        (source_runtime / "Cargo.lock").read_bytes() != (runtime / "Cargo.lock").read_bytes(),
        "standalone source runtime reused the writer Cargo.lock",
    )
    require(sha256(source_runtime / "src/npm_source_block.rs") == SOURCE_CODE_SHA256, "materialized source code drift")
    require(sha256(source_runtime / "src/pb/uniswap.npm.source.v1.rs") == SOURCE_BINDING_SHA256, "materialized source binding drift")
    require(sha256(source_runtime / "configs/npm-source-block-v1.json") == SEMANTICS_SHA256, "materialized source semantics drift")
    require(sha256(source_runtime / "configs/segment-profiles-v1.json") == WRITER_PROFILES_SHA256, "materialized source profiles drift")
    require(sha256(runtime / "proto/uniswap/npm/source/v1/npm_source_block.proto") == SOURCE_PROTO_SHA256, "materialized source protobuf drift")
    package_dir = runtime / "npm-source-package"
    require(
        (package_dir / "README.md").read_bytes() == (root / OVERLAY / "README.md").read_bytes(),
        "materialized NPM source package README drift",
    )
    for network in NETWORK:
        require(
            (package_dir / f"substreams.npm-source.{network}.yaml").read_bytes()
            == (root / OVERLAY / "manifests" / f"substreams.npm-source.{network}.yaml").read_bytes(),
            f"materialized {network} source manifest drift",
        )
    expected_materialized = contract["materialized_runtime"]["sha256"]
    require(expected_materialized == expected_materialized_sha256(), "materialized NPM source digest table drift")
    for relative, digest in expected_materialized.items():
        require(sha256(runtime / relative) == digest, f"materialized NPM source artifact drift: {relative}")
    return (
        runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm",
        source_runtime / "target/wasm32-unknown-unknown/release/uniswap_v3_npm_source_block.wasm",
    )


def verify_two_binary_bindings(writer, package: Path, expected_wasm: list[bytes]) -> None:
    envelopes = [
        value
        for number, wire, value in writer.wire_fields(package.read_bytes())
        if number == 6 and wire == 2
    ]
    require(len(envelopes) == 1, f"{package} Modules envelope drift")
    fields = writer.wire_fields(envelopes[0])
    module_payloads = [value for number, wire, value in fields if number == 1 and wire == 2]
    binary_payloads = [value for number, wire, value in fields if number == 2 and wire == 2]
    require(len(module_payloads) == len(binary_payloads) == 2, f"{package} two-module/two-binary shape drift")
    binary_contents = []
    for payload in binary_payloads:
        binary_fields = writer.wire_fields(payload)
        types = [value.decode() for number, wire, value in binary_fields if number == 1 and wire == 2]
        contents = [value for number, wire, value in binary_fields if number == 2 and wire == 2]
        require(types == ["wasm/rust-v1"] and len(contents) == 1, f"{package} binary payload drift")
        binary_contents.append(contents[0])
    require(binary_contents == expected_wasm, f"{package} embedded WASM order/content drift")
    bindings = []
    for payload in module_payloads:
        fields = writer.wire_fields(payload)
        names = [value.decode() for number, wire, value in fields if number == 1 and wire == 2]
        indexes = [value for number, wire, value in fields if number == 4 and wire == 0]
        entrypoints = [value.decode() for number, wire, value in fields if number == 5 and wire == 2]
        require(len(names) == len(entrypoints) == 1 and len(indexes) <= 1, f"{package} module binding drift")
        bindings.append((names[0], indexes[0] if indexes else 0, entrypoints[0]))
    require(
        bindings
        == [
            ("map_writer_events", 0, "map_writer_events"),
            ("map_npm_source_block", 1, "map_npm_source_block"),
        ],
        f"{package} module binary index/entrypoint drift",
    )


def verify_source_descriptors(writer, package: Path, writer_package: Path | None) -> None:
    descriptors = writer.package_descriptors(package)
    writer.verify_descriptor_payloads(
        descriptors,
        SOURCE_DESCRIPTOR_COUNT,
        SOURCE_DESCRIPTOR_SET_SHA256,
        writer.WRITER_DESCRIPTOR_SHA256,
        str(package),
    )
    source = []
    inherited = []
    for descriptor in descriptors:
        fields = writer.wire_fields(descriptor)
        names = [value.decode() for number, wire, value in fields if number == 1 and wire == 2]
        packages = [value.decode() for number, wire, value in fields if number == 2 and wire == 2]
        if packages == ["uniswap.npm.source.v1"]:
            source.append((names, descriptor))
        else:
            inherited.append(descriptor)
    require(len(source) == 1, f"{package} source descriptor multiplicity drift")
    names, descriptor = source[0]
    require(names == ["uniswap/npm/source/v1/npm_source_block.proto"], f"{package} source descriptor path drift")
    require(hashlib.sha256(descriptor).hexdigest() == SOURCE_DESCRIPTOR_SHA256, f"{package} source descriptor drift")
    writer_descriptors = [
        item
        for item in inherited
        if [value.decode() for number, wire, value in writer.wire_fields(item) if number == 2 and wire == 2]
        == ["uniswap.writer.v1"]
    ]
    require(len(writer_descriptors) == 1, f"{package} writer descriptor multiplicity drift")
    require(
        hashlib.sha256(writer_descriptors[0]).hexdigest() == writer.WRITER_DESCRIPTOR_SHA256,
        f"{package} writer descriptor drift",
    )
    if writer_package is not None:
        writer.verify_package_descriptors(writer_package)


def package_documentation(writer, package: Path) -> str:
    metadata = [
        value
        for number, wire, value in writer.wire_fields(package.read_bytes())
        if number == 8 and wire == 2
    ]
    require(len(metadata) == 1, f"{package} package metadata multiplicity drift")
    docs = [
        value.decode()
        for number, wire, value in writer.wire_fields(metadata[0])
        if number == 4 and wire == 2
    ]
    require(len(docs) == 1, f"{package} package documentation multiplicity drift")
    return docs[0]


def expected_module_hashes(writer, manifest: dict[str, object], wasm: dict[str, bytes]) -> list[str]:
    ordered = [module["name"] for module in manifest["modules"]]
    modules = {module["name"]: module for module in manifest["modules"]}
    structure = {item["name"]: item for item in writer.expected_package_module_structure(manifest)}
    dependencies = {
        name: [
            item.get("map") or item.get("store")
            for item in module.get("inputs", [])
            if item.get("map") or item.get("store")
        ]
        for name, module in modules.items()
    }
    cache: dict[str, bytes] = {}
    hashing: set[str] = set()

    def module_hash(name: str) -> bytes:
        if name in cache:
            return cache[name]
        require(name not in hashing, f"module dependency cycle at {name}")
        hashing.add(name)
        module = modules[name]
        binary = manifest["binaries"][module["binary"]]
        payload = bytearray()
        payload.extend(b"initial_block")
        payload.extend(int(structure[name]["initial_block"]).to_bytes(8, "little"))
        payload.extend(b"kind")
        payload.extend(module["kind"].encode())
        payload.extend(b"binary")
        payload.extend(binary["type"].encode())
        payload.extend(wasm[module["binary"]])
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
        ancestors: set[str] = set()

        def visit(candidate: str) -> None:
            if candidate in ancestors:
                return
            ancestors.add(candidate)
            for dependency in dependencies[candidate]:
                visit(dependency)

        for dependency in dependencies[name]:
            visit(dependency)
        for candidate in ordered:
            if candidate in ancestors:
                payload.extend(module_hash(candidate))
        payload.extend(b"entrypoint")
        payload.extend(name.encode())
        digest = hashlib.sha1(payload).digest()
        hashing.remove(name)
        cache[name] = digest
        return digest

    return [module_hash(name).hex() for name in ordered]


def verify_packages(
    root: Path,
    runtime: Path,
    writer_wasm: Path,
    source_wasm: Path,
    packages: dict[str, Path],
    writer_packages: dict[str, Path] | None,
) -> None:
    writer = load_writer_verifier(root)
    manifests = load_manifests(root)
    require(writer_wasm.is_file(), "writer WASM missing for source-package verification")
    require(source_wasm.is_file(), "source WASM missing for source-package verification")
    for network, package in packages.items():
        require(package.is_file(), f"missing {network} NPM source package")
        binaries = writer.embedded_wasm_binaries(package)
        expected_wasm = [writer_wasm.read_bytes(), source_wasm.read_bytes()]
        require(binaries == expected_wasm, f"{network} NPM source package binary order/content drift")
        verify_two_binary_bindings(writer, package, expected_wasm)
        writer_package = writer_packages[network] if writer_packages else None
        verify_source_descriptors(writer, package, writer_package)
        info = json.loads(subprocess.check_output(["substreams", "info", "--json", str(package)], text=True))
        require(info["network"] == network, f"{network} NPM source packaged network drift")
        require(info["name"] == NETWORK[network]["package"] and info["version"] == "v0.1.0", f"{network} NPM source package identity drift")
        require(
            package_documentation(writer, package) == (root / OVERLAY / "README.md").read_text(),
            f"{network} NPM source package documentation drift",
        )
        require(len(info["modules"]) == 2, f"{network} NPM source package module count drift")
        modules = {module["name"]: module for module in info["modules"]}
        require(set(modules) == {"map_writer_events", "map_npm_source_block"}, f"{network} NPM source packaged module set drift")
        require(modules["map_writer_events"]["inputs"] == [
            {"type": "params", "name": NETWORK[network]["selector"]},
            {"type": "source", "name": "sf.ethereum.type.v2.Block"},
        ], f"{network} packaged writer inputs drift")
        require(modules["map_npm_source_block"]["inputs"] == [
            {"type": "source", "name": "sf.ethereum.type.v2.Block"},
            {"type": "map", "name": "map_writer_events"},
        ], f"{network} packaged source inputs drift")
        require(modules["map_npm_source_block"]["output_type"] == "proto:uniswap.npm.source.v1.NpmSourceBlock", f"{network} packaged source output drift")
        require(modules["map_npm_source_block"]["initial_block"] == NETWORK[network]["initial_block"], f"{network} packaged source initial block drift")
        writer.verify_package_module_structure(info["modules"], manifests[network], network)
        require(
            [module["hash"] for module in info["modules"]]
            == expected_module_hashes(
                writer,
                manifests[network],
                {"writer": expected_wasm[0], "npm_source": expected_wasm[1]},
            ),
            f"{network} packaged module hashes drift",
        )
        if writer_packages:
            baseline = json.loads(subprocess.check_output(["substreams", "info", "--json", str(writer_packages[network])], text=True))
            baseline_writer = next(module for module in baseline["modules"] if module["name"] == "map_writer_events")
            require(modules["map_writer_events"]["hash"] == baseline_writer["hash"], f"{network} map_writer_events hash changed in source package")
    require((runtime / "substreams.mainnet.yaml").read_bytes() == (root / "uniswap-v3/writer-runtime/manifests/substreams.mainnet.yaml").read_bytes(), "mainnet writer manifest changed")
    require((runtime / "substreams.base.yaml").read_bytes() == (root / "uniswap-v3/writer-runtime/manifests/substreams.base.yaml").read_bytes(), "Base writer manifest changed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--mainnet-spkg", type=Path)
    parser.add_argument("--base-spkg", type=Path)
    parser.add_argument("--writer-mainnet-spkg", type=Path)
    parser.add_argument("--writer-base-spkg", type=Path)
    args = parser.parse_args()
    source_package_args = bool(args.mainnet_spkg) or bool(args.base_spkg)
    writer_package_args = bool(args.writer_mainnet_spkg) or bool(args.writer_base_spkg)
    if bool(args.mainnet_spkg) != bool(args.base_spkg):
        parser.error("--mainnet-spkg and --base-spkg must be passed together")
    if bool(args.writer_mainnet_spkg) != bool(args.writer_base_spkg):
        parser.error("--writer-mainnet-spkg and --writer-base-spkg must be passed together")
    if writer_package_args and not source_package_args:
        parser.error("writer package checks require --mainnet-spkg and --base-spkg")
    if (source_package_args or writer_package_args) and not args.runtime:
        parser.error("package checks require --runtime")
    try:
        root = args.root.resolve()
        contract = load_contract(root)
        load_semantics(root)
        verify_upstream(root)
        verify_proto(root)
        load_manifests(root)
        verify_static_source(root)
        if args.runtime:
            runtime = args.runtime.resolve()
            writer_wasm, source_wasm = verify_runtime(root, runtime, contract)
            if source_package_args:
                writer_packages = None
                if writer_package_args:
                    writer_packages = {
                        "mainnet": args.writer_mainnet_spkg.resolve(),
                        "base": args.writer_base_spkg.resolve(),
                    }
                verify_packages(
                    root,
                    runtime,
                    writer_wasm,
                    source_wasm,
                    {"mainnet": args.mainnet_spkg.resolve(), "base": args.base_spkg.resolve()},
                    writer_packages,
                )
        print("verified provider-free two-WASM Uniswap V3 NPM source-block boundary and conservative authority gates")
        return 0
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
        VerificationError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Uniswap V3 NPM source-block verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
