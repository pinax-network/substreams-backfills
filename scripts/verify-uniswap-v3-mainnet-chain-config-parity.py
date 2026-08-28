#!/usr/bin/env python3
"""Verify one complete V3 mainnet ChainConfig protocol-v3 parity capture.

This proves ordered equality of the exact graph_out protobuf bytes for one fixed
range. It is deliberately not a Graph Node oracle, POI proof, production pin,
or promotion decision.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn


PROFILE_KIND = "uniswap-v3-mainnet-chain-config-parity-profile"
PROFILE_ID = "uniswap-v3-mainnet-chain-config-parity-v1"
BUILD_KIND = "uniswap-v3-mainnet-chain-config-parity-controlled-build-candidate"
BUILD_STATUS = "candidate-not-a-production-pin"
CERTIFICATE_KIND = "uniswap-v3-mainnet-chain-config-parity-certificate"
INVOCATION_KIND = "uniswap-v3-mainnet-parity-invocation-completion"
BLOCK_KIND = "uniswap-v3-mainnet-parity-block"
STREAM_COMPLETION_KIND = "uniswap-v3-mainnet-parity-stream-completion"
RPC_KIND = "uniswap-v3-mainnet-parity-ethereum-rpc-snapshot"
START_BLOCK = 12_369_621
END_BLOCK_EXCLUSIVE = 12_370_674
PROCESSED_BLOCK_LIMIT = END_BLOCK_EXCLUSIVE - START_BLOCK
BOUNDARY_BLOCKS = (12_369_621, 12_369_651, 12_370_624, 12_370_673)
MODULE = "graph_out"
OUTPUT_TYPE = "sf.substreams.entity.v1.EntityChanges"
IMPORT_REPOSITORY = "pinax-network/substreams-uniswap-v3"
IMPORT_COMMIT = "42c7b15345e6df80561b694e52a0eb622b374b96"
IMPORT_TREE = "a00e882e92d07b46550b74dea279c114d57631ac"
HISTORICAL_NOTE_COMMIT = "d3e5384b3ef47c78e8a1404b3c33de1ae8a78e3a"
HISTORICAL_NOTE_BLOB = "e0177270802668f4c2832ec0eba51f8c250219a6"
HISTORICAL_NOTE_SHA256 = "6726bc0a64d4a6c6e6a54b4db09fb8c28ed0a44c82d05cb962d0ab16851f011a"
CONFIG_SHA256 = "30f5caf9ee8906a8886dc103e55286b9d5b6dbd8784d1c97d21b9a38b266bb55"
CONFIG_PROVENANCE_SHA256 = "ca098e763dce0c139bff7137774cb27ae56058e3475f7de529fb179de0cf8667"
OVERLAY_SHA256 = "4f87d22239b84aebca6712a72e2c4047b0735e911756973b6e7c228fe455e8ae"
SOURCE_SCHEMA_SHA256 = "f234a0e4dc88c923d6ad28a3fcd1ed6093351bd2221d7c18486f0cbde41bb52c"
TARGET_SCHEMA_SHA256 = "ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c"
IMPORT_PROVENANCE_SHA256 = "9e44a654281d6d0d6ecfc8cf3fc70dcc56bcbd8999d13ecc20f77b84b133d165"
IMPORT_INVENTORY_SHA256 = "177a98f60f230d1b13dfa064f3b98a50163a506d2c7a08432330d47ee2170e60"
CAPTURE_CLIENT_VERSION = (
    "uniswap-v3-mainnet-parity-client-v1 "
    "(protocol v3; upstream v1.20.3 cc555bd4e325b65ac3f95dfde4655076f88d4a0a)"
)
CAPTURE_UPSTREAM_VERSION = "v1.20.3"
CAPTURE_UPSTREAM_COMMIT = "cc555bd4e325b65ac3f95dfde4655076f88d4a0a"
CAPTURE_UPSTREAM_TREE = "38ea588549e5e41698da00ee149278aa2d855c64"
GO_VERSION_RE = re.compile(r"^go version go1\.26\.5 (?:darwin|linux)/(?:amd64|arm64)$")
SUBSTREAMS_VERSION = "substreams version 1.20.3 (Commit cc555bd, Commit Date 2026-07-31T14:30:54Z)"
OFFICIAL_SUBSTREAMS_BINARIES = {
    "darwin-arm64": {
        "binary_sha256": "a9f40e2d4c5a612677ce13b96527a9a417b011f9b5e190294df05c10dddbfcca",
        "binary_bytes": 83_612_242,
        "release_archive_sha256": "8c1b32fcf503e80628012b82bb79871d25b696de091edaf92335c2fb2fdaeae3",
    },
    "darwin-x86_64": {
        "binary_sha256": "9354672a087c49ca7679eabbb9e459a7cc7cc4d68d16935faf858751bd89308c",
        "binary_bytes": 89_388_512,
        "release_archive_sha256": "4f8cbabe38b64bc4b7a449eb22d0f9d7604c231bfd2c93ad8037111715335102",
    },
    "linux-arm64": {
        "binary_sha256": "d20c27a3b480f556a1dc618b1cecc123dd1dd976cc9c37ac5eba9b4c46c46d7e",
        "binary_bytes": 82_575_625,
        "release_archive_sha256": "9c444214bc795799533ed32547236e36c275c937ee10aaec8d375446cb1b996b",
    },
    "linux-x86_64": {
        "binary_sha256": "f49de46e2fc5ae8e6bf92ef85cb3de96afc0998c485cfc56e187b20d94046ce5",
        "binary_bytes": 88_949_001,
        "release_archive_sha256": "90c71d04a75490efdf0493254a8563c3555690e622b3c6ade5100c0c773f8675",
    },
}
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
BLOCK_HASH_RE = re.compile(r"^0x[0-9a-f]{64}$")
ENDPOINT_RE = re.compile(r"^[A-Za-z0-9.-]+:[0-9]+$")
RPC_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
DNS_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

EXPECTED_ENTITIES = (
    "Bundle", "Burn", "Collect", "Factory", "Flash", "Mint", "Pool",
    "PoolDayData", "PoolHourData", "Position", "PositionSnapshot", "Swap",
    "Tick", "TickDayData", "TickHourData", "Token", "TokenDayData",
    "TokenHourData", "Transaction", "UniswapDayData",
)
KNOWN_UNIMPLEMENTED_ENTITY_ROWS = ("Collect", "Flash")
EXPECTED_MODULES = (
    "map_pools_created", "store_pools_created", "store_tokens", "store_pool_count",
    "map_tokens_whitelist_pools", "store_tokens_whitelist_pools", "map_extract_data_types",
    "store_pool_sqrt_price", "store_prices", "store_pool_liquidities",
    "store_total_tx_counts", "store_swaps_volume", "store_native_amounts",
    "store_eth_prices", "store_token_tvl", "store_derived_tvl",
    "store_derived_factory_tvl", "store_ticks_liquidities", "store_positions",
    "store_min_windows", "store_max_windows", "graph_out",
)
TRUST_BOUNDARY = {
    "promotion_eligible": False,
    "authoritative_graph_reference": False,
    "physical_or_poi_parity": False,
    "production_pin": False,
    "approved_runtime_contract": None,
}
HARNESS_PATHS = (
    ".github/workflows/ci.yaml",
    "scripts/build-uniswap-v3-mainnet-parity-candidate.py",
    "scripts/capture-uniswap-v3-mainnet-parity-invocation.py",
    "scripts/parity-client/go.mod",
    "scripts/parity-client/go.sum",
    "scripts/parity-client/main.go",
    "scripts/parity-client/main_test.go",
    "scripts/parity-client/services-control-plane-stub/go.mod",
    "scripts/run-uniswap-v3-mainnet-chain-config-parity.sh",
    "scripts/verify-uniswap-v3-mainnet-chain-config-parity.py",
    "uniswap-v3/PARITY.md",
    "uniswap-v3/chain-config/README.md",
    "uniswap-v3/fixtures/mainnet-chain-config-parity-v1.json",
)


class VerificationError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise VerificationError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def exact_keys(value: object, keys: set[str], field: str) -> dict[str, object]:
    require(isinstance(value, dict), f"{field} must be an object")
    require(set(value) == keys, f"{field} keys differ from the contract")
    return value


def reject_float(value: str) -> NoReturn:
    fail(f"floating-point JSON value is forbidden: {value}")


def reject_constant(value: str) -> NoReturn:
    fail(f"non-finite JSON value is forbidden: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_bytes(raw: bytes, source: str) -> object:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise VerificationError(f"{source} is not valid UTF-8") from error
    decoder = json.JSONDecoder(
        object_pairs_hook=reject_duplicate_keys,
        parse_float=reject_float,
        parse_constant=reject_constant,
    )
    start = len(text) - len(text.lstrip())
    require(start < len(text), f"{source} is empty")
    try:
        value, end = decoder.raw_decode(text, start)
    except json.JSONDecodeError as error:
        raise VerificationError(f"{source} is not strict JSON: {error.msg}") from error
    require(not text[end:].strip(), f"{source} contains trailing data")
    return value


def strict_json_file(path: Path, field: str) -> tuple[dict[str, object], bytes]:
    raw = regular_bytes(path, field)
    value = strict_json_bytes(raw, field)
    require(isinstance(value, dict), f"{field} must contain one object")
    return value, raw


def regular_bytes(path: Path, field: str) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"{field} is not a regular file: {path}")
    return path.read_bytes()


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise VerificationError(f"value cannot be canonicalized: {error}") from error


def compact_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(regular_bytes(path, "repository evidence"))


def validate_guard_fields(value: object, field: str) -> None:
    if isinstance(value, dict):
        for key, expected in TRUST_BOUNDARY.items():
            if key in value:
                require(value[key] is expected, f"{field}.{key} must remain {expected!r}")
        for key, child in value.items():
            validate_guard_fields(child, f"{field}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_guard_fields(child, f"{field}[{index}]")


def git_output(root: Path, arguments: list[str], field: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise VerificationError(f"could not resolve {field} from repository history") from error


def validate_profile(profile: dict[str, object], root: Path) -> None:
    exact_keys(
        profile,
        {
            "format_version", "kind", "profile_id", "network", "stream", "range",
            "boundaries", "repository_evidence", "entity_contract", "capture_contract",
            "build_contract", "trust_boundary",
        },
        "profile",
    )
    require(type(profile["format_version"]) is int and profile["format_version"] == 1, "profile version drift")
    require(profile["kind"] == PROFILE_KIND and profile["profile_id"] == PROFILE_ID, "profile identity drift")
    require(profile["network"] == "mainnet", "profile network drift")
    require(
        exact_keys(profile["stream"], {"module", "output_type"}, "profile.stream")
        == {"module": MODULE, "output_type": OUTPUT_TYPE},
        "profile stream drift",
    )
    expected_range = {
        "start_block": START_BLOCK,
        "end_block_exclusive": END_BLOCK_EXCLUSIVE,
        "processed_block_limit": PROCESSED_BLOCK_LIMIT,
        "complete_envelope_count": PROCESSED_BLOCK_LIMIT,
        "capture_mode": "source-pinned-protocol-v3-explicit-all-block-map-bytes",
    }
    require(exact_keys(profile["range"], set(expected_range), "profile.range") == expected_range, "profile range drift")
    expected_boundaries = {
        "module_start": START_BLOCK,
        "position_manager_start": 12_369_651,
        "historical_first_mints_start": 12_370_624,
        "range_last_block": END_BLOCK_EXCLUSIVE - 1,
    }
    require(
        exact_keys(profile["boundaries"], set(expected_boundaries), "profile.boundaries") == expected_boundaries,
        "profile boundaries drift",
    )
    evidence = exact_keys(
        profile["repository_evidence"],
        {"source_import", "chain_config", "runtime_overlay", "schema", "historical_first_mints_note"},
        "profile.repository_evidence",
    )
    source = exact_keys(
        evidence["source_import"],
        {"repository", "commit", "tree", "import_path", "provenance_path", "provenance_sha256", "inventory_path", "inventory_sha256"},
        "profile.source_import",
    )
    require(source == {
        "repository": IMPORT_REPOSITORY,
        "commit": IMPORT_COMMIT,
        "tree": IMPORT_TREE,
        "import_path": "uniswap-v3/source",
        "provenance_path": "provenance/uniswap-v3-qma8a81t-parity.json",
        "provenance_sha256": IMPORT_PROVENANCE_SHA256,
        "inventory_path": "provenance/uniswap-v3-qma8a81t-parity-files.json",
        "inventory_sha256": IMPORT_INVENTORY_SHA256,
    }, "profile source-import drift")
    config = exact_keys(
        evidence["chain_config"],
        {"path", "sha256", "provenance_path", "provenance_sha256", "selector", "module_start", "position_manager_start"},
        "profile.chain_config",
    )
    require(config == {
        "path": "uniswap-v3/chain-config/configs/mainnet-v1.json",
        "sha256": CONFIG_SHA256,
        "provenance_path": "provenance/uniswap-v3-chain-config-v1.json",
        "provenance_sha256": CONFIG_PROVENANCE_SHA256,
        "selector": f"version=1;network=mainnet;sha256={CONFIG_SHA256}",
        "module_start": START_BLOCK,
        "position_manager_start": 12_369_651,
    }, "profile ChainConfig drift")
    overlay = exact_keys(evidence["runtime_overlay"], {"path", "sha256"}, "profile.runtime_overlay")
    require(overlay == {"path": "uniswap-v3/chain-config/runtime.patch", "sha256": OVERLAY_SHA256}, "profile overlay drift")
    schema = exact_keys(
        evidence["schema"], {"path", "sha256", "target_cid", "target_raw_sha256", "logical_contract_sha256"}, "profile.schema"
    )
    require(schema == {
        "path": "uniswap-v3/source/schema.graphql",
        "sha256": SOURCE_SCHEMA_SHA256,
        "target_cid": "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru",
        "target_raw_sha256": TARGET_SCHEMA_SHA256,
        "logical_contract_sha256": "6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d",
    }, "profile schema drift")
    historical = exact_keys(
        evidence["historical_first_mints_note"],
        {"commit", "path", "blob", "sha256", "recorded_start_block", "recorded_end_block_exclusive", "retained_artifacts", "certification_authority", "classification"},
        "profile.historical_first_mints_note",
    )
    require(historical == {
        "commit": HISTORICAL_NOTE_COMMIT,
        "path": "uniswap-v3/PARITY.md",
        "blob": HISTORICAL_NOTE_BLOB,
        "sha256": HISTORICAL_NOTE_SHA256,
        "recorded_start_block": 12_370_624,
        "recorded_end_block_exclusive": END_BLOCK_EXCLUSIVE,
        "retained_artifacts": False,
        "certification_authority": False,
        "classification": "historical-unretained-smoke-context-only",
    }, "historical first-mints evidence drift")
    entity = exact_keys(
        profile["entity_contract"],
        {"schema_entities", "coverage_requirement", "known_unimplemented_entity_rows", "all_schema_entities_implemented", "authoritative_entity_coverage"},
        "profile.entity_contract",
    )
    require(entity == {
        "schema_entities": list(EXPECTED_ENTITIES),
        "coverage_requirement": "nonempty-observed-subset-equal-between-baseline-and-candidate",
        "known_unimplemented_entity_rows": list(KNOWN_UNIMPLEMENTED_ENTITY_ROWS),
        "all_schema_entities_implemented": False,
        "authoritative_entity_coverage": False,
    }, "profile entity truth boundary drift")
    capture = exact_keys(profile["capture_contract"], {
        "protocol", "protocol_version", "client_version", "upstream_version", "upstream_commit", "upstream_tree",
        "go_version", "package_closure", "private_services_control_plane_imported", "execution_mode", "network",
        "final_blocks_only", "production_mode", "noop_mode", "partial_blocks", "max_retries", "limit_processed_blocks",
        "dev_output_modules", "complete_block_records_required", "explicit_zero_byte_map_outputs_required",
        "reconstruction_of_missing_blocks", "clean_eof_required_after_last_block", "clock_hash_timestamp_and_finality_bound",
        "cursor_final_block_and_lib_bound", "raw_stdout_stderr_retained",
        "local_invocation_completion_is_signed_remote_attestation",
        "completion_is_local_capture_evidence_only",
    }, "profile.capture_contract")
    require(capture == {
        "protocol": "sf.substreams.rpc.v3.Stream/Blocks", "protocol_version": 3,
        "client_version": "uniswap-v3-mainnet-parity-client-v1", "upstream_version": CAPTURE_UPSTREAM_VERSION,
        "upstream_commit": CAPTURE_UPSTREAM_COMMIT, "upstream_tree": CAPTURE_UPSTREAM_TREE,
        "go_version": "go1.26.5", "package_closure": "v1.20.3-rpc-v3-package-closure",
        "private_services_control_plane_imported": False, "execution_mode": "development", "network": "mainnet",
        "final_blocks_only": True, "production_mode": False, "noop_mode": False, "partial_blocks": False,
        "max_retries": 0, "limit_processed_blocks": PROCESSED_BLOCK_LIMIT, "dev_output_modules": [MODULE],
        "complete_block_records_required": PROCESSED_BLOCK_LIMIT, "explicit_zero_byte_map_outputs_required": True,
        "reconstruction_of_missing_blocks": False, "clean_eof_required_after_last_block": True,
        "clock_hash_timestamp_and_finality_bound": True, "cursor_final_block_and_lib_bound": True,
        "raw_stdout_stderr_retained": True,
        "local_invocation_completion_is_signed_remote_attestation": False,
        "completion_is_local_capture_evidence_only": True,
    }, "profile capture contract drift")
    build = exact_keys(profile["build_contract"], {"repository", "candidate_artifact", "artifacts", "capture_client", "execution_modules"}, "profile.build_contract")
    require(build["repository"] == "pinax-network/substreams-backfills", "profile build repository drift")
    require(build["candidate_artifact"] == "configured_mainnet", "profile build candidate drift")
    require(build["artifacts"] == ["baseline", "configured_mainnet", "configured_base"], "profile build artifacts drift")
    require(build["capture_client"] == "scripts/parity-client", "profile capture-client path drift")
    require(build["execution_modules"] == list(EXPECTED_MODULES), "profile module inventory drift")
    require(exact_keys(profile["trust_boundary"], set(TRUST_BOUNDARY), "profile.trust_boundary") == TRUST_BOUNDARY, "profile trust boundary drift")
    for relative, expected in (
        (source["provenance_path"], IMPORT_PROVENANCE_SHA256), (source["inventory_path"], IMPORT_INVENTORY_SHA256),
        (config["path"], CONFIG_SHA256), (config["provenance_path"], CONFIG_PROVENANCE_SHA256),
        (overlay["path"], OVERLAY_SHA256), (schema["path"], SOURCE_SCHEMA_SHA256),
    ):
        require(digest_file(root / str(relative)) == expected, f"repository evidence digest drift: {relative}")
    config_value, _ = strict_json_file(root / str(config["path"]), "mainnet ChainConfig")
    starts = exact_keys(config_value.get("initial_blocks"), {"module", "factory", "factory_creation", "nonfungible_position_manager"}, "ChainConfig initial_blocks")
    require(starts["module"] == START_BLOCK and starts["nonfungible_position_manager"] == 12_369_651, "ChainConfig range boundary drift")
    historical_raw = git_output(root, ["show", f"{HISTORICAL_NOTE_COMMIT}:uniswap-v3/PARITY.md"], "historical first-mints note")
    require(digest_bytes(historical_raw) == HISTORICAL_NOTE_SHA256, "historical first-mints digest drift")
    historical_blob = git_output(root, ["rev-parse", f"{HISTORICAL_NOTE_COMMIT}:uniswap-v3/PARITY.md"], "historical first-mints blob").decode("ascii").strip()
    require(historical_blob == HISTORICAL_NOTE_BLOB, "historical first-mints blob drift")


def validate_artifact(value: object, field: str) -> dict[str, object]:
    artifact = exact_keys(value, {"spkg_sha256", "bytes", "wasm_sha256", "wasm_bytes", "execution_module_hashes"}, field)
    require(isinstance(artifact["spkg_sha256"], str) and HEX64_RE.fullmatch(artifact["spkg_sha256"]) is not None, f"{field} SPKG digest malformed")
    require(type(artifact["bytes"]) is int and artifact["bytes"] > 0, f"{field} SPKG size malformed")
    require(isinstance(artifact["wasm_sha256"], str) and HEX64_RE.fullmatch(artifact["wasm_sha256"]) is not None, f"{field} WASM digest malformed")
    require(type(artifact["wasm_bytes"]) is int and artifact["wasm_bytes"] > 0, f"{field} WASM size malformed")
    hashes = exact_keys(artifact["execution_module_hashes"], set(EXPECTED_MODULES), f"{field}.execution_module_hashes")
    for module, digest in hashes.items():
        require(isinstance(digest, str) and HEX40_RE.fullmatch(digest) is not None, f"{field}.{module} hash malformed")
    return artifact


def validate_capture_client_identity(value: object, root: Path) -> dict[str, object]:
    identity = exact_keys(value, {"version", "binary_sha256", "binary_bytes", "build", "source"}, "capture-client identity")
    require(identity["version"] == CAPTURE_CLIENT_VERSION, "capture-client version drift")
    require(isinstance(identity["binary_sha256"], str) and HEX64_RE.fullmatch(identity["binary_sha256"]) is not None, "capture-client digest malformed")
    require(type(identity["binary_bytes"]) is int and identity["binary_bytes"] > 0, "capture-client size malformed")
    build = exact_keys(identity["build"], {"go_version", "goos", "goarch", "command", "cgo_enabled"}, "capture-client build")
    require(isinstance(build["go_version"], str) and GO_VERSION_RE.fullmatch(build["go_version"]) is not None, "capture-client Go version drift")
    require(build["goos"] in {"darwin", "linux"}, "capture-client GOOS unsupported")
    require(build["goarch"] in {"amd64", "arm64"}, "capture-client GOARCH unsupported")
    require(build["go_version"] == f"go version go1.26.5 {build['goos']}/{build['goarch']}", "capture-client Go target drift")
    require(build["command"] == ["go", "build", "-mod=readonly", "-trimpath", "-buildvcs=false", "-ldflags=-buildid=", "-o", "<capture-client>", "."], "capture-client build command drift")
    require(build["cgo_enabled"] is False, "capture-client CGO boundary drift")
    source = exact_keys(identity["source"], {
        "upstream_version", "upstream_commit", "upstream_tree", "client_sha256", "tests_sha256", "go_mod_sha256",
        "go_sum_sha256", "package_less_replacement_go_mod_sha256", "runtime_dependency_inventory",
        "public_module_graph_patch_sha256",
        "runtime_dependency_inventory_sha256", "runtime_dependency_count", "binary_build_info", "binary_build_info_sha256",
        "binary_module_inventory", "binary_module_count", "private_replacement_imported",
    }, "capture-client source")
    require(source["upstream_version"] == CAPTURE_UPSTREAM_VERSION and source["upstream_commit"] == CAPTURE_UPSTREAM_COMMIT and source["upstream_tree"] == CAPTURE_UPSTREAM_TREE, "capture-client upstream identity drift")
    source_paths = {
        "client_sha256": "scripts/parity-client/main.go",
        "tests_sha256": "scripts/parity-client/main_test.go",
        "go_mod_sha256": "scripts/parity-client/go.mod",
        "go_sum_sha256": "scripts/parity-client/go.sum",
        "package_less_replacement_go_mod_sha256": "scripts/parity-client/services-control-plane-stub/go.mod",
    }
    for key, relative in source_paths.items():
        require(source[key] == digest_file(root / relative), f"capture-client source digest drift: {relative}")
    module_graph_patch_raw = (
        b"scripts/parity-client/go.mod\0"
        + (root / "scripts/parity-client/go.mod").read_bytes()
        + b"\0scripts/parity-client/services-control-plane-stub/go.mod\0"
        + (root / "scripts/parity-client/services-control-plane-stub/go.mod").read_bytes()
    )
    require(source["public_module_graph_patch_sha256"] == digest_bytes(module_graph_patch_raw), "capture-client public module-graph patch digest drift")
    inventory = source["runtime_dependency_inventory"]
    require(isinstance(inventory, list) and inventory == sorted(set(inventory)) and bool(inventory), "capture-client package dependency inventory drift")
    require(all(isinstance(line, str) and line.count("|") == 3 for line in inventory), "capture-client dependency entry malformed")
    inventory_raw = ("\n".join(inventory) + "\n").encode()
    require(source["runtime_dependency_inventory_sha256"] == digest_bytes(inventory_raw), "capture-client dependency inventory digest drift")
    require(type(source["runtime_dependency_count"]) is int and source["runtime_dependency_count"] == len(inventory), "capture-client dependency count drift")
    require(any("|github.com/streamingfast/substreams|v1.20.3|" in line for line in inventory), "capture-client Substreams v1.20.3 dependency missing")
    build_info = source["binary_build_info"]
    require(isinstance(build_info, list) and all(isinstance(line, str) for line in build_info), "capture-client binary build info malformed")
    require(build_info and build_info[0] == "go\tgo1.26.5", "capture-client binary Go identity drift")
    require("\tpath\tgithub.com/pinax-network/substreams-backfills/scripts/parity-client" in build_info, "capture-client binary path drift")
    require("\tbuild\t-trimpath=true" in build_info and "\tbuild\tCGO_ENABLED=0" in build_info, "capture-client binary settings drift")
    require(f"\tbuild\tGOOS={build['goos']}" in build_info and f"\tbuild\tGOARCH={build['goarch']}" in build_info, "capture-client binary target drift")
    build_info_raw = ("\n".join(build_info) + "\n").encode()
    require(source["binary_build_info_sha256"] == digest_bytes(build_info_raw), "capture-client build-info digest drift")
    modules = source["binary_module_inventory"]
    require(isinstance(modules, list) and modules == sorted(line for line in build_info if line.startswith("\tdep\t")), "capture-client binary module inventory drift")
    require(type(source["binary_module_count"]) is int and source["binary_module_count"] == len(modules) and bool(modules), "capture-client binary module count drift")
    require(all("\th1:" in line for line in modules), "capture-client binary dependency lacks a module sum")
    require(any(line.startswith("\tdep\tgithub.com/streamingfast/substreams\tv1.20.3\t") for line in modules), "capture-client binary Substreams dependency drift")
    require(not any("services-control-plane" in line for line in [*inventory, *build_info]), "private replacement entered capture-client dependency closure")
    require(source["private_replacement_imported"] is False, "private replacement import claim drift")
    return identity


def validate_build_manifest(value: dict[str, object], profile_sha256: str, root: Path) -> None:
    exact_keys(value, {"format_version", "kind", "status", "source", "inputs", "toolchain", "artifacts", "assertions", "trust_boundary"}, "controlled-build manifest")
    require(type(value["format_version"]) is int and value["format_version"] == 1, "controlled-build version drift")
    require(value["kind"] == BUILD_KIND and value["status"] == BUILD_STATUS, "controlled-build identity drift")
    source = exact_keys(value["source"], {"repository", "revision", "tree", "import_repository", "import_commit", "import_tree"}, "controlled-build source")
    require(source["repository"] == "pinax-network/substreams-backfills", "controlled-build repository drift")
    require(isinstance(source["revision"], str) and HEX40_RE.fullmatch(source["revision"]) is not None, "controlled-build revision malformed")
    require(isinstance(source["tree"], str) and HEX40_RE.fullmatch(source["tree"]) is not None, "controlled-build tree malformed")
    require(source["import_repository"] == IMPORT_REPOSITORY and source["import_commit"] == IMPORT_COMMIT and source["import_tree"] == IMPORT_TREE, "controlled-build import identity drift")
    head = git_output(root, ["rev-parse", "HEAD^{commit}"], "repository HEAD").decode("ascii").strip()
    tree = git_output(root, ["rev-parse", "HEAD^{tree}"], "repository tree").decode("ascii").strip()
    require(source["revision"] == head and source["tree"] == tree, "controlled-build source does not match repository HEAD")
    expected_inputs = {
        "profile_sha256": profile_sha256,
        "chain_config_sha256": CONFIG_SHA256,
        "chain_config_provenance_sha256": CONFIG_PROVENANCE_SHA256,
        "runtime_overlay_sha256": OVERLAY_SHA256,
        "schema_sha256": TARGET_SCHEMA_SHA256,
    }
    require(exact_keys(value["inputs"], set(expected_inputs), "controlled-build inputs") == expected_inputs, "controlled-build inputs drift")
    toolchain = exact_keys(value["toolchain"], {"rustc", "cargo", "substreams", "capture_client", "go", "python", "platform"}, "controlled-build toolchain")
    for name in ("rustc", "cargo", "go", "python", "platform"):
        require(isinstance(toolchain[name], str) and bool(toolchain[name].strip()), f"controlled-build {name} identity missing")
    require(isinstance(toolchain["go"], str) and GO_VERSION_RE.fullmatch(toolchain["go"]) is not None, "controlled-build Go version drift")
    substreams = exact_keys(toolchain["substreams"], {"version", "release_platform", "release_archive_sha256", "binary_sha256", "binary_bytes"}, "controlled-build Substreams CLI")
    require(substreams["version"] == SUBSTREAMS_VERSION, "controlled-build Substreams version drift")
    platform_name = substreams["release_platform"]
    require(isinstance(platform_name, str) and platform_name in OFFICIAL_SUBSTREAMS_BINARIES, "controlled-build Substreams platform unsupported")
    require({key: substreams[key] for key in ("binary_sha256", "binary_bytes", "release_archive_sha256")} == OFFICIAL_SUBSTREAMS_BINARIES[platform_name], "controlled-build Substreams binary is not the official checksum-pinned release")
    capture_client = validate_capture_client_identity(toolchain["capture_client"], root)
    require(toolchain["go"] == capture_client["build"]["go_version"], "controlled-build and capture-client Go identities differ")
    artifacts = exact_keys(value["artifacts"], {"baseline", "configured_mainnet", "configured_base"}, "controlled-build artifacts")
    baseline = validate_artifact(artifacts["baseline"], "controlled-build baseline")
    mainnet = validate_artifact(artifacts["configured_mainnet"], "controlled-build configured_mainnet")
    base = validate_artifact(artifacts["configured_base"], "controlled-build configured_base")
    assertions = exact_keys(value["assertions"], {"configured_mainnet_and_base_wasm_equal", "baseline_and_configured_mainnet_wasm_equal"}, "controlled-build assertions")
    require(assertions == {"configured_mainnet_and_base_wasm_equal": True, "baseline_and_configured_mainnet_wasm_equal": False}, "controlled-build assertions drift")
    require(mainnet["wasm_sha256"] == base["wasm_sha256"] and mainnet["wasm_bytes"] == base["wasm_bytes"], "configured mainnet/Base WASM drift")
    require(baseline["wasm_sha256"] != mainnet["wasm_sha256"], "baseline/configured WASM unexpectedly equal")
    require(mainnet["spkg_sha256"] != base["spkg_sha256"], "configured package identities unexpectedly equal")
    require(exact_keys(value["trust_boundary"], set(TRUST_BOUNDARY), "controlled-build trust boundary") == TRUST_BOUNDARY, "controlled-build trust boundary drift")


def validate_exact_source(root: Path, source_revision: str) -> dict[str, object]:
    require(git_output(root, ["rev-parse", "HEAD^{commit}"], "repository HEAD").decode("ascii").strip() == source_revision, "source revision is not repository HEAD")
    require(not git_output(root, ["status", "--porcelain", "--untracked-files=all"], "repository status"), "exact source checkout is dirty")
    binding: dict[str, object] = {}
    for relative in HARNESS_PATHS:
        current = regular_bytes(root / relative, f"harness source {relative}")
        committed = git_output(root, ["show", f"{source_revision}:{relative}"], f"harness source {relative}")
        require(current == committed, f"harness source differs from exact revision: {relative}")
        binding[relative] = {"sha256": digest_bytes(current), "bytes": len(current)}
    return binding


def request_contract(package: dict[str, object]) -> dict[str, object]:
    return {
        "protocol_version": 3,
        "network": "mainnet",
        "module": MODULE,
        "output_type": OUTPUT_TYPE,
        "start_block": START_BLOCK,
        "start_cursor": "",
        "end_block_exclusive": END_BLOCK_EXCLUSIVE,
        "processed_block_limit": PROCESSED_BLOCK_LIMIT,
        "final_blocks_only": True,
        "production_mode": False,
        "noop_mode": False,
        "partial_blocks": False,
        "max_retries": 0,
        "params": {},
        "debug_initial_store_snapshot_for_modules": [],
        "dev_output_modules": [MODULE],
        "package": package,
    }


def expected_argv(role: str, endpoint: str, session_id: str, invocation_id: str, source_revision: str, started: int) -> list[str]:
    return [
        "uniswap-v3-mainnet-parity-client", "--endpoint", endpoint,
        "--package", f"<package:{role}>", "--session-id", session_id,
        "--invocation-id", invocation_id, "--role", role,
        "--source-revision", source_revision, "--started-at-unix-nanos", str(started),
    ]


def parse_capture_stdout(
    raw: bytes,
    *,
    role: str,
    session_id: str,
    source_revision: str,
    endpoint: str,
    artifact: dict[str, object],
    capture_client: dict[str, object],
    invocation_id: str,
    auth_kind: str,
    started: int,
) -> tuple[list[dict[str, object]], list[bytes], dict[str, object]]:
    require(raw.endswith(b"\n") and b"\r" not in raw, f"{role} stdout must end in LF and contain no CR")
    lines = raw[:-1].split(b"\n")
    require(len(lines) == PROCESSED_BLOCK_LIMIT + 1, f"{role} stdout must contain exactly 1,053 blocks plus completion")
    block_lines = lines[:-1]
    records: list[dict[str, object]] = []
    decoded_outputs: list[bytes] = []
    previous_timestamp: tuple[int, int] | None = None
    for index, line in enumerate(block_lines):
        field = f"{role} stdout line {index + 1}"
        value = strict_json_bytes(line, field)
        record = exact_keys(value, {
            "format_version", "kind", "block", "block_id", "timestamp_seconds", "timestamp_nanos",
            "module", "output_type", "map_output_base64", "map_output_bytes", "map_output_sha256", "cursor_sha256",
        }, field)
        require(line == compact_json(record), f"{field} is not exact compact client JSON")
        block = START_BLOCK + index
        require(type(record["format_version"]) is int and record["format_version"] == 1 and record["kind"] == BLOCK_KIND, f"{field} identity drift")
        require(type(record["block"]) is int and record["block"] == block, f"{field} missing, duplicate, or out-of-range block")
        require(isinstance(record["block_id"], str) and HEX64_RE.fullmatch(record["block_id"]) is not None, f"{field} block hash malformed")
        seconds, nanos = record["timestamp_seconds"], record["timestamp_nanos"]
        require(type(seconds) is int and -62_135_596_800 <= seconds <= 253_402_300_799, f"{field} timestamp seconds malformed")
        require(type(nanos) is int and 0 <= nanos < 1_000_000_000, f"{field} timestamp nanos malformed")
        timestamp = (seconds, nanos)
        require(previous_timestamp is None or timestamp > previous_timestamp, f"{field} timestamp is not strictly increasing")
        previous_timestamp = timestamp
        require(record["module"] == MODULE and record["output_type"] == OUTPUT_TYPE, f"{field} output contract drift")
        encoded = record["map_output_base64"]
        require(isinstance(encoded, str) and encoded.isascii(), f"{field} map output base64 malformed")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VerificationError(f"{field} map output base64 malformed") from error
        require(base64.b64encode(decoded).decode() == encoded, f"{field} map output base64 is noncanonical")
        require(type(record["map_output_bytes"]) is int and record["map_output_bytes"] == len(decoded), f"{field} map output length drift")
        require(isinstance(record["map_output_sha256"], str) and record["map_output_sha256"] == digest_bytes(decoded), f"{field} map output digest drift")
        require(isinstance(record["cursor_sha256"], str) and HEX64_RE.fullmatch(record["cursor_sha256"]) is not None, f"{field} cursor digest malformed")
        records.append(record)
        decoded_outputs.append(decoded)
    completion_field = f"{role} stdout completion"
    completion_value = strict_json_bytes(lines[-1], completion_field)
    completion = exact_keys(completion_value, {
        "format_version", "kind", "client_version", "protocol_version", "upstream_version", "upstream_commit", "upstream_tree",
        "session_id", "invocation_id", "role", "source_revision", "endpoint", "auth_kind", "package", "capture_client",
        "request", "request_sha256", "sanitized_argv", "started_at_unix_nanos", "completed_at_unix_nanos",
        "first_block", "last_block", "block_count", "records_sha256", "completed",
    }, completion_field)
    require(lines[-1] == compact_json(completion), f"{completion_field} is not exact compact client JSON")
    package_identity = {"sha256": artifact["spkg_sha256"], "bytes": artifact["bytes"]}
    client_identity = {"sha256": capture_client["binary_sha256"], "bytes": capture_client["binary_bytes"]}
    request = request_contract(package_identity)
    completed = completion["completed_at_unix_nanos"]
    require(type(completed) is int and completed >= started, f"{completion_field} clock bounds drift")
    expected = {
        "format_version": 1, "kind": STREAM_COMPLETION_KIND,
        "client_version": "uniswap-v3-mainnet-parity-client-v1", "protocol_version": 3,
        "upstream_version": CAPTURE_UPSTREAM_VERSION, "upstream_commit": CAPTURE_UPSTREAM_COMMIT,
        "upstream_tree": CAPTURE_UPSTREAM_TREE, "session_id": session_id, "invocation_id": invocation_id,
        "role": role, "source_revision": source_revision, "endpoint": endpoint, "auth_kind": auth_kind,
        "package": package_identity, "capture_client": client_identity, "request": request,
        "request_sha256": digest_bytes(compact_json(request)),
        "sanitized_argv": expected_argv(role, endpoint, session_id, invocation_id, source_revision, started),
        "started_at_unix_nanos": started, "completed_at_unix_nanos": completed,
        "first_block": START_BLOCK, "last_block": END_BLOCK_EXCLUSIVE - 1,
        "block_count": PROCESSED_BLOCK_LIMIT,
        "records_sha256": digest_bytes(b"".join(line + b"\n" for line in block_lines)),
        "completed": True,
    }
    require(completion == expected, f"{completion_field} provenance or completion drift")
    return records, decoded_outputs, completion


def validate_capture(
    *,
    role: str,
    stdout_path: Path,
    stderr_path: Path,
    completion_path: Path,
    session_id: str,
    source_revision: str,
    endpoint: str,
    artifact: dict[str, object],
    capture_client: dict[str, object],
    redaction_values: tuple[bytes, ...],
) -> tuple[list[dict[str, object]], list[bytes], dict[str, object], dict[str, bytes]]:
    raw_files = {
        "stdout": regular_bytes(stdout_path, f"{role} raw stdout"),
        "stderr": regular_bytes(stderr_path, f"{role} raw stderr"),
        "completion": regular_bytes(completion_path, f"{role} capture completion"),
    }
    for field, raw in raw_files.items():
        for secret in redaction_values:
            require(secret not in raw, f"{role} {field} contains a supplied secret")
    require(raw_files["stderr"] == b"", f"{role} successful capture stderr is not empty")
    sidecar_value = strict_json_bytes(raw_files["completion"], f"{role} capture completion")
    sidecar = exact_keys(sidecar_value, {
        "format_version", "kind", "session_id", "invocation_id", "role", "source_revision", "package", "endpoint", "auth_kind",
        "capture_client", "request", "request_sha256", "sanitized_argv", "clock", "stream", "raw", "exit_code", "completed", "trust_boundary",
    }, f"{role} capture completion")
    validate_guard_fields(sidecar, f"{role} capture completion")
    require(type(sidecar["format_version"]) is int and sidecar["format_version"] == 1 and sidecar["kind"] == INVOCATION_KIND, f"{role} sidecar identity drift")
    invocation_id = sidecar["invocation_id"]
    require(isinstance(invocation_id, str) and HEX64_RE.fullmatch(invocation_id) is not None, f"{role} invocation ID malformed")
    require(sidecar["session_id"] == session_id and sidecar["role"] == role and sidecar["source_revision"] == source_revision, f"{role} sidecar session/source drift")
    require(sidecar["endpoint"] == endpoint and sidecar["auth_kind"] in {"x-api-key", "bearer-token"}, f"{role} endpoint/auth drift")
    artifact_name = "baseline" if role == "baseline" else "configured_mainnet"
    package = {"artifact": artifact_name, "sha256": artifact["spkg_sha256"], "bytes": artifact["bytes"]}
    require(exact_keys(sidecar["package"], set(package), f"{role} sidecar package") == package, f"{role} package binding drift")
    client_summary = {"version": capture_client["version"], "binary_sha256": capture_client["binary_sha256"], "binary_bytes": capture_client["binary_bytes"]}
    require(exact_keys(sidecar["capture_client"], set(client_summary), f"{role} capture client") == client_summary, f"{role} capture-client identity differs from controlled build")
    request = request_contract({"sha256": artifact["spkg_sha256"], "bytes": artifact["bytes"]})
    require(sidecar["request"] == request and sidecar["request_sha256"] == digest_bytes(compact_json(request)), f"{role} request contract drift")
    clock = exact_keys(sidecar["clock"], {"wrapper_started_at_unix_nanos", "client_completed_at_unix_nanos", "wrapper_completed_at_unix_nanos", "ordered"}, f"{role} capture clock")
    started, client_completed, wrapper_completed = clock["wrapper_started_at_unix_nanos"], clock["client_completed_at_unix_nanos"], clock["wrapper_completed_at_unix_nanos"]
    require(all(type(value) is int and value > 0 for value in (started, client_completed, wrapper_completed)), f"{role} capture clock malformed")
    require(started <= client_completed <= wrapper_completed and clock["ordered"] is True, f"{role} capture clock order drift")
    require(sidecar["sanitized_argv"] == expected_argv(role, endpoint, session_id, invocation_id, source_revision, started), f"{role} sanitized argv drift")
    records, decoded, stream_completion = parse_capture_stdout(
        raw_files["stdout"], role=role, session_id=session_id, source_revision=source_revision, endpoint=endpoint,
        artifact=artifact, capture_client=capture_client, invocation_id=invocation_id, auth_kind=str(sidecar["auth_kind"]), started=started,
    )
    require(stream_completion["completed_at_unix_nanos"] == client_completed, f"{role} sidecar/client completion replay drift")
    stream = exact_keys(sidecar["stream"], {
        "first_block", "last_block", "block_count", "started_at_unix_nanos", "completed_at_unix_nanos",
        "first_timestamp", "last_timestamp", "records_sha256", "block_hashes_sha256", "map_output_hashes_sha256", "cursor_hashes_sha256",
    }, f"{role} stream summary")
    block_hashes = {str(record["block"]): "0x" + str(record["block_id"]) for record in records}
    map_hashes = [str(record["map_output_sha256"]) for record in records]
    cursor_hashes = [str(record["cursor_sha256"]) for record in records]
    expected_stream = {
        "first_block": START_BLOCK, "last_block": END_BLOCK_EXCLUSIVE - 1, "block_count": PROCESSED_BLOCK_LIMIT,
        "started_at_unix_nanos": started, "completed_at_unix_nanos": client_completed,
        "first_timestamp": {"seconds": records[0]["timestamp_seconds"], "nanos": records[0]["timestamp_nanos"]},
        "last_timestamp": {"seconds": records[-1]["timestamp_seconds"], "nanos": records[-1]["timestamp_nanos"]},
        "records_sha256": stream_completion["records_sha256"],
        "block_hashes_sha256": digest_bytes(canonical_json(block_hashes)),
        "map_output_hashes_sha256": digest_bytes(compact_json(map_hashes)),
        "cursor_hashes_sha256": digest_bytes(compact_json(cursor_hashes)),
    }
    require(stream == expected_stream, f"{role} stream summary drift")
    raw = exact_keys(sidecar["raw"], {"stdout", "stderr"}, f"{role} sidecar raw")
    expected_raw = {
        "stdout": {"name": stdout_path.name, "sha256": digest_bytes(raw_files["stdout"]), "bytes": len(raw_files["stdout"])},
        "stderr": {"name": stderr_path.name, "sha256": digest_bytes(raw_files["stderr"]), "bytes": len(raw_files["stderr"])},
    }
    require(raw == expected_raw, f"{role} raw capture binding drift")
    require(type(sidecar["exit_code"]) is int and sidecar["exit_code"] == 0 and sidecar["completed"] is True, f"{role} capture is incomplete")
    require(exact_keys(sidecar["trust_boundary"], set(TRUST_BOUNDARY), f"{role} trust boundary") == TRUST_BOUNDARY, f"{role} trust boundary drift")
    return records, decoded, sidecar, raw_files


def validate_rpc_snapshot(
    value: dict[str, object],
    *,
    field: str,
    phase: str,
    session_id: str,
    rpc_label: str,
) -> dict[str, dict[str, object]]:
    exact_keys(value, {
        "format_version", "kind", "session_id", "phase", "rpc_label", "network", "chain_id", "range", "batches",
        "clock", "blocks", "blocks_sha256", "completed", "trust_boundary",
    }, field)
    validate_guard_fields(value, field)
    require(type(value["format_version"]) is int and value["format_version"] == 1 and value["kind"] == RPC_KIND, f"{field} identity drift")
    require(value["session_id"] == session_id and value["phase"] == phase, f"{field} session/phase drift")
    require(value["rpc_label"] == rpc_label and value["network"] == "mainnet" and value["chain_id"] == "0x1", f"{field} RPC identity drift")
    expected_range = {"start_block": START_BLOCK, "end_block_exclusive": END_BLOCK_EXCLUSIVE, "block_count": PROCESSED_BLOCK_LIMIT}
    require(exact_keys(value["range"], set(expected_range), f"{field}.range") == expected_range, f"{field} range drift")
    batches = exact_keys(value["batches"], {"maximum_batch_size", "request_count"}, f"{field}.batches")
    require(type(batches["maximum_batch_size"]) is int and 1 <= batches["maximum_batch_size"] <= 50, f"{field} RPC batch size is unsafe")
    expected_requests = (PROCESSED_BLOCK_LIMIT + batches["maximum_batch_size"] - 1) // batches["maximum_batch_size"]
    require(type(batches["request_count"]) is int and batches["request_count"] == expected_requests, f"{field} RPC request count drift")
    clock = exact_keys(value["clock"], {"started_at_unix_nanos", "completed_at_unix_nanos", "ordered"}, f"{field}.clock")
    require(type(clock["started_at_unix_nanos"]) is int and type(clock["completed_at_unix_nanos"]) is int and 0 < clock["started_at_unix_nanos"] <= clock["completed_at_unix_nanos"] and clock["ordered"] is True, f"{field} clock drift")
    blocks = exact_keys(value["blocks"], {str(block) for block in range(START_BLOCK, END_BLOCK_EXCLUSIVE)}, f"{field}.blocks")
    normalized: dict[str, dict[str, object]] = {}
    previous_timestamp: int | None = None
    for block in range(START_BLOCK, END_BLOCK_EXCLUSIVE):
        record = exact_keys(blocks[str(block)], {"number", "hash", "timestamp_seconds"}, f"{field}.blocks.{block}")
        require(type(record["number"]) is int and record["number"] == block, f"{field} block number drift at {block}")
        require(isinstance(record["hash"], str) and BLOCK_HASH_RE.fullmatch(record["hash"]) is not None, f"{field} block hash malformed at {block}")
        timestamp = record["timestamp_seconds"]
        require(type(timestamp) is int and timestamp > 0, f"{field} timestamp malformed at {block}")
        require(previous_timestamp is None or timestamp > previous_timestamp, f"{field} timestamps are not strictly increasing")
        previous_timestamp = timestamp
        normalized[str(block)] = {"number": block, "hash": record["hash"], "timestamp_seconds": timestamp}
    require(value["blocks_sha256"] == digest_bytes(canonical_json(normalized)), f"{field} blocks digest drift")
    require(value["completed"] is True, f"{field} is incomplete")
    require(exact_keys(value["trust_boundary"], set(TRUST_BOUNDARY), f"{field}.trust_boundary") == TRUST_BOUNDARY, f"{field} trust boundary drift")
    return normalized


def read_varint(data: bytes, offset: int, field: str) -> tuple[int, int]:
    start = offset
    value = 0
    shift = 0
    while True:
        require(offset < len(data), f"{field} has a truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            encoded_length = offset - start
            minimum_length = max(1, (value.bit_length() + 6) // 7)
            require(encoded_length == minimum_length, f"{field} has a noncanonical protobuf varint")
            return value, offset
        shift += 7
        require(shift < 70, f"{field} has an invalid protobuf varint")


def wire_fields(data: bytes, field: str) -> list[tuple[int, int, bytes | int]]:
    result: list[tuple[int, int, bytes | int]] = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset, field)
        number, wire = tag >> 3, tag & 7
        require(number > 0, f"{field} has an invalid protobuf field number")
        if wire == 0:
            value, offset = read_varint(data, offset, field)
        elif wire == 1:
            require(offset + 8 <= len(data), f"{field} has truncated fixed64 data")
            value, offset = data[offset:offset + 8], offset + 8
        elif wire == 2:
            length, offset = read_varint(data, offset, field)
            require(offset + length <= len(data), f"{field} has truncated length-delimited data")
            value, offset = data[offset:offset + length], offset + length
        elif wire == 5:
            require(offset + 4 <= len(data), f"{field} has truncated fixed32 data")
            value, offset = data[offset:offset + 4], offset + 4
        else:
            fail(f"{field} has unsupported protobuf wire type {wire}")
        result.append((number, wire, value))
    return result


def decode_utf8(value: bytes, field: str) -> str:
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise VerificationError(f"{field} is not valid UTF-8") from error


def entity_coverage(outputs: list[bytes], field: str) -> tuple[list[str], int]:
    coverage: set[str] = set()
    changes = 0
    allowed = set(EXPECTED_ENTITIES)
    for index, raw in enumerate(outputs):
        block = START_BLOCK + index
        for number, wire, value in wire_fields(raw, f"{field} block {block} EntityChanges"):
            require(number == 5 and wire == 2 and isinstance(value, bytes), f"{field} block {block} has an unknown EntityChanges field")
            nested = wire_fields(value, f"{field} block {block} EntityChange")
            entities = [item for item in nested if item[0] == 1]
            ids = [item for item in nested if item[0] == 2]
            operations = [item for item in nested if item[0] == 4]
            require(len(entities) == 1 and entities[0][1] == 2 and isinstance(entities[0][2], bytes), f"{field} block {block} entity name malformed")
            require(len(ids) == 1 and ids[0][1] == 2 and isinstance(ids[0][2], bytes) and bool(ids[0][2]), f"{field} block {block} entity ID malformed")
            require(len(operations) == 1 and operations[0][1] == 0 and operations[0][2] in {1, 2, 3, 4}, f"{field} block {block} entity operation malformed")
            require(all(item[0] in {1, 2, 3, 4, 5} for item in nested), f"{field} block {block} EntityChange has an unknown field")
            for nested_number, nested_wire, nested_value in nested:
                if nested_number == 3:
                    require(nested_wire == 0 and isinstance(nested_value, int), f"{field} block {block} ordinal malformed")
                if nested_number == 5:
                    require(nested_wire == 2 and isinstance(nested_value, bytes), f"{field} block {block} entity field malformed")
                    wire_fields(nested_value, f"{field} block {block} entity field")
            entity = decode_utf8(entities[0][2], f"{field} block {block} entity name")
            decode_utf8(ids[0][2], f"{field} block {block} entity ID")
            require(entity in allowed, f"{field} block {block} has unknown entity {entity}")
            coverage.add(entity)
            changes += 1
    require(bool(coverage) and changes > 0, f"{field} has no observed entity coverage")
    require(not coverage.intersection(KNOWN_UNIMPLEMENTED_ENTITY_ROWS), f"{field} contradicts the pinned known Collect/Flash implementation gap")
    return sorted(coverage), changes


def staged_install(outputs: list[tuple[Path, bytes]], redaction_values: tuple[bytes, ...]) -> None:
    destinations = [path.resolve(strict=False) for path, _ in outputs]
    require(len(destinations) == len(set(destinations)), "immutable output paths must be distinct")
    for path in destinations:
        require(path.parent.is_dir(), f"output parent does not exist: {path.parent}")
        require(not os.path.lexists(path), f"refusing to overwrite immutable output: {path}")
    for path, payload in outputs:
        for secret in redaction_values:
            require(secret not in payload, f"staged output {path.name} contains a supplied secret")
    staged: list[Path] = []
    published: list[Path] = []
    try:
        for destination, (_, payload) in zip(destinations, outputs, strict=True):
            handle = tempfile.NamedTemporaryFile(prefix=".parity-stage.", dir=destination.parent, delete=False)
            temporary = Path(handle.name)
            staged.append(temporary)
            os.chmod(temporary, 0o400)
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        for temporary, destination in zip(staged, destinations, strict=True):
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError as error:
                raise VerificationError(f"refusing to overwrite immutable output: {destination}") from error
            os.chmod(destination, 0o444, follow_symlinks=False)
            published.append(destination)
            directory = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        for path in reversed(published):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        for path in staged:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def verify_and_emit(
    *,
    root: Path,
    profile_path: Path,
    baseline_stdout_path: Path,
    baseline_stderr_path: Path,
    baseline_completion_path: Path,
    candidate_stdout_path: Path,
    candidate_stderr_path: Path,
    candidate_completion_path: Path,
    build_manifest_path: Path,
    rpc_before_path: Path,
    rpc_after_path: Path,
    baseline_stdout_retained_path: Path,
    baseline_stderr_retained_path: Path,
    baseline_completion_retained_path: Path,
    candidate_stdout_retained_path: Path,
    candidate_stderr_retained_path: Path,
    candidate_completion_retained_path: Path,
    baseline_capture_path: Path,
    candidate_capture_path: Path,
    baseline_canonical_path: Path,
    candidate_canonical_path: Path,
    certificate_path: Path,
    session_id: str,
    endpoint: str,
    rpc_label: str,
    redaction_values: tuple[bytes, ...],
) -> dict[str, object]:
    root = root.resolve()
    require(HEX64_RE.fullmatch(session_id) is not None, "capture session ID malformed")
    require(ENDPOINT_RE.fullmatch(endpoint) is not None, "Substreams endpoint must be credential-free host:port")
    host, port = endpoint.rsplit(":", 1)
    require(bool(host) and 1 <= int(port) <= 65_535, "Substreams endpoint port malformed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        fail("Substreams endpoint must use a DNS target")
    require(len(host) <= 253 and all(DNS_LABEL_RE.fullmatch(label) for label in host.split(".")), "Substreams endpoint DNS target malformed")
    require(RPC_LABEL_RE.fullmatch(rpc_label) is not None, "Ethereum RPC label must be an explicit short public label")
    profile, profile_raw = strict_json_file(profile_path, "parity profile")
    validate_guard_fields(profile, "parity profile")
    validate_profile(profile, root)
    profile_sha256 = digest_bytes(profile_raw)
    build_manifest, build_raw = strict_json_file(build_manifest_path, "controlled-build manifest")
    validate_guard_fields(build_manifest, "controlled-build manifest")
    validate_build_manifest(build_manifest, profile_sha256, root)
    source_revision = str(build_manifest["source"]["revision"])
    harness_binding = validate_exact_source(root, source_revision)
    rpc_before, rpc_before_raw = strict_json_file(rpc_before_path, "Ethereum RPC before snapshot")
    rpc_after, rpc_after_raw = strict_json_file(rpc_after_path, "Ethereum RPC after snapshot")
    before_blocks = validate_rpc_snapshot(rpc_before, field="Ethereum RPC before snapshot", phase="before", session_id=session_id, rpc_label=rpc_label)
    after_blocks = validate_rpc_snapshot(rpc_after, field="Ethereum RPC after snapshot", phase="after", session_id=session_id, rpc_label=rpc_label)
    require(before_blocks == after_blocks, "Ethereum RPC canonical range changed across capture")
    artifacts = build_manifest["artifacts"]
    capture_client = build_manifest["toolchain"]["capture_client"]
    baseline_records, baseline_outputs, baseline_sidecar, baseline_raw = validate_capture(
        role="baseline", stdout_path=baseline_stdout_path, stderr_path=baseline_stderr_path,
        completion_path=baseline_completion_path, session_id=session_id, source_revision=source_revision,
        endpoint=endpoint, artifact=artifacts["baseline"], capture_client=capture_client, redaction_values=redaction_values,
    )
    candidate_records, candidate_outputs, candidate_sidecar, candidate_raw = validate_capture(
        role="candidate", stdout_path=candidate_stdout_path, stderr_path=candidate_stderr_path,
        completion_path=candidate_completion_path, session_id=session_id, source_revision=source_revision,
        endpoint=endpoint, artifact=artifacts["configured_mainnet"], capture_client=capture_client, redaction_values=redaction_values,
    )
    require(baseline_sidecar["invocation_id"] != candidate_sidecar["invocation_id"], "baseline and candidate invocation IDs must differ")
    before_clock = rpc_before["clock"]
    after_clock = rpc_after["clock"]
    capture_starts = [baseline_sidecar["clock"]["wrapper_started_at_unix_nanos"], candidate_sidecar["clock"]["wrapper_started_at_unix_nanos"]]
    capture_ends = [baseline_sidecar["clock"]["wrapper_completed_at_unix_nanos"], candidate_sidecar["clock"]["wrapper_completed_at_unix_nanos"]]
    require(before_clock["completed_at_unix_nanos"] <= min(capture_starts), "before-RPC snapshot does not precede both captures")
    require(max(capture_ends) <= after_clock["started_at_unix_nanos"], "after-RPC snapshot does not follow both captures")
    for role, records in (("baseline", baseline_records), ("candidate", candidate_records)):
        for record in records:
            rpc_block = before_blocks[str(record["block"])]
            require("0x" + str(record["block_id"]) == rpc_block["hash"], f"{role} block {record['block']} hash differs from Ethereum RPC")
            require(record["timestamp_seconds"] == rpc_block["timestamp_seconds"] and record["timestamp_nanos"] == 0, f"{role} block {record['block']} timestamp differs from Ethereum RPC")
    require(
        [(record["block"], record["block_id"], record["timestamp_seconds"], record["timestamp_nanos"]) for record in baseline_records]
        == [(record["block"], record["block_id"], record["timestamp_seconds"], record["timestamp_nanos"]) for record in candidate_records],
        "baseline and candidate block clocks differ",
    )
    require(any(bool(raw) for raw in baseline_outputs) and any(bool(raw) for raw in candidate_outputs), "ordered envelope sequence has no nonempty map output")
    require(baseline_outputs == candidate_outputs, "baseline and candidate ordered graph_out protobuf bytes differ")
    baseline_coverage, baseline_changes = entity_coverage(baseline_outputs, "baseline stream")
    candidate_coverage, candidate_changes = entity_coverage(candidate_outputs, "candidate stream")
    require(baseline_coverage == candidate_coverage and baseline_changes == candidate_changes, "baseline and candidate observed entity coverage differs")
    canonical_records = [
        {
            "@block": record["block"],
            "@block_hash": "0x" + str(record["block_id"]),
            "@block_timestamp": {"seconds": record["timestamp_seconds"], "nanos": record["timestamp_nanos"]},
            "@module": MODULE,
            "@type": OUTPUT_TYPE,
            "@data_base64": record["map_output_base64"],
            "@data_bytes": record["map_output_bytes"],
            "@data_sha256": record["map_output_sha256"],
        }
        for record in baseline_records
    ]
    baseline_canonical = b"".join(canonical_json(record) + b"\n" for record in canonical_records)
    candidate_canonical = b"".join(canonical_json(record) + b"\n" for record in canonical_records)
    range_value = {
        "start_block": START_BLOCK, "end_block_exclusive": END_BLOCK_EXCLUSIVE,
        "processed_block_limit": PROCESSED_BLOCK_LIMIT, "complete_envelope_count": PROCESSED_BLOCK_LIMIT,
        "capture_mode": "source-pinned-protocol-v3-explicit-all-block-map-bytes",
    }
    baseline_capture_payload = canonical_json(baseline_sidecar) + b"\n"
    candidate_capture_payload = canonical_json(candidate_sidecar) + b"\n"
    rpc_blocks_sha256 = digest_bytes(canonical_json(before_blocks))
    certificate: dict[str, object] = {
        "format_version": 1,
        "kind": CERTIFICATE_KIND,
        "status": "ordered-logical-protobuf-parity-equal-nonpromotable",
        "profile": {"id": PROFILE_ID, "path": "uniswap-v3/fixtures/mainnet-chain-config-parity-v1.json", "sha256": profile_sha256},
        "repository": {
            "source_revision": source_revision,
            "source_tree": build_manifest["source"]["tree"],
            "harness_files": harness_binding,
            "harness_binding_sha256": digest_bytes(canonical_json(harness_binding)),
            "source_import": profile["repository_evidence"]["source_import"],
            "chain_config": profile["repository_evidence"]["chain_config"],
            "runtime_overlay": profile["repository_evidence"]["runtime_overlay"],
            "schema": profile["repository_evidence"]["schema"],
            "historical_first_mints_note": profile["repository_evidence"]["historical_first_mints_note"],
        },
        "controlled_build": {
            "manifest_sha256": digest_bytes(build_raw),
            "source": build_manifest["source"], "inputs": build_manifest["inputs"],
            "toolchain": build_manifest["toolchain"], "artifacts": build_manifest["artifacts"],
            "assertions": build_manifest["assertions"],
        },
        "capture_session": {
            "session_id": session_id, "substreams_endpoint": endpoint, "ethereum_rpc_label": rpc_label,
            "invocation_ids": [baseline_sidecar["invocation_id"], candidate_sidecar["invocation_id"]],
            "invocation_ids_distinct": True, "protocol_version": 3,
            "both_invocation_binaries_equal_controlled_build_binary": True,
            "both_invocation_packages_equal_controlled_build_packages": True,
            "request_and_completion_replay_binding_verified": True,
            "before_and_after_clock_bounds_verified": True,
            "local_completion_records_are_signed_remote_attestations": False,
        },
        "range": {**range_value, "sha256": digest_bytes(canonical_json(range_value))},
        "ethereum_rpc": {
            "label": rpc_label, "before_sha256": digest_bytes(rpc_before_raw), "after_sha256": digest_bytes(rpc_after_raw),
            "blocks_sha256": rpc_blocks_sha256, "block_count": PROCESSED_BLOCK_LIMIT, "unchanged": True,
            "all_stream_hashes_and_timestamps_match": True,
        },
        "streams": {
            "baseline": {
                "build_artifact": "baseline", "capture_manifest": baseline_capture_path.name,
                "capture_manifest_sha256": digest_bytes(baseline_capture_payload),
                "raw": {name: {"sha256": digest_bytes(raw), "bytes": len(raw)} for name, raw in baseline_raw.items()},
                "canonical_output": baseline_canonical_path.name, "canonical_sha256": digest_bytes(baseline_canonical),
                "record_count": PROCESSED_BLOCK_LIMIT, "nonempty_map_output_count": sum(bool(raw) for raw in baseline_outputs),
                "zero_byte_map_output_count": sum(not raw for raw in baseline_outputs),
                "entity_change_count": baseline_changes, "observed_entity_coverage": baseline_coverage,
            },
            "candidate": {
                "build_artifact": "configured_mainnet", "capture_manifest": candidate_capture_path.name,
                "capture_manifest_sha256": digest_bytes(candidate_capture_payload),
                "raw": {name: {"sha256": digest_bytes(raw), "bytes": len(raw)} for name, raw in candidate_raw.items()},
                "canonical_output": candidate_canonical_path.name, "canonical_sha256": digest_bytes(candidate_canonical),
                "record_count": PROCESSED_BLOCK_LIMIT, "nonempty_map_output_count": sum(bool(raw) for raw in candidate_outputs),
                "zero_byte_map_output_count": sum(not raw for raw in candidate_outputs),
                "entity_change_count": candidate_changes, "observed_entity_coverage": candidate_coverage,
            },
        },
        "entity_truth_boundary": {
            "schema_entities": list(EXPECTED_ENTITIES), "observed_equal_subset": baseline_coverage,
            "known_unimplemented_entity_rows": list(KNOWN_UNIMPLEMENTED_ENTITY_ROWS),
            "all_schema_entities_implemented": False, "authoritative_entity_coverage": False,
            "collect_and_flash_follow_up_required": True,
        },
        "comparison": {
            "algorithm": "exact-ordered-protobuf-bytes-with-block-hash-and-timestamp-cross-binding",
            "ordered_envelopes_equal": True, "missing_blocks_reconstructed": False,
            "explicit_zero_byte_outputs_verified": True, "clean_eof_completion_verified": True,
            "cursor_final_block_and_lib_binding_enforced": True,
            "record_count": PROCESSED_BLOCK_LIMIT,
            "transcript_sha256": digest_bytes(canonical_json({
                "source_revision": source_revision, "profile_sha256": profile_sha256,
                "build_manifest_sha256": digest_bytes(build_raw), "rpc_blocks_sha256": rpc_blocks_sha256,
                "baseline_stdout_sha256": digest_bytes(baseline_raw["stdout"]),
                "candidate_stdout_sha256": digest_bytes(candidate_raw["stdout"]),
                "canonical_sha256": digest_bytes(baseline_canonical),
            })),
        },
        "verifier": {
            "path": "scripts/verify-uniswap-v3-mainnet-chain-config-parity.py",
            "sha256": digest_file(root / "scripts/verify-uniswap-v3-mainnet-chain-config-parity.py"),
            "python": sys.version.splitlines()[0],
        },
        "trust_boundary": dict(TRUST_BOUNDARY),
    }
    validate_guard_fields(certificate, "certificate")
    certificate_payload = canonical_json(certificate) + b"\n"
    staged_install([
        (baseline_stdout_retained_path, baseline_raw["stdout"]),
        (baseline_stderr_retained_path, baseline_raw["stderr"]),
        (baseline_completion_retained_path, baseline_raw["completion"]),
        (candidate_stdout_retained_path, candidate_raw["stdout"]),
        (candidate_stderr_retained_path, candidate_raw["stderr"]),
        (candidate_completion_retained_path, candidate_raw["completion"]),
        (baseline_capture_path, baseline_capture_payload),
        (candidate_capture_path, candidate_capture_payload),
        (baseline_canonical_path, baseline_canonical),
        (candidate_canonical_path, candidate_canonical),
        (certificate_path, certificate_payload),
    ], redaction_values)
    return certificate


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--substreams-endpoint", required=True)
    parser.add_argument("--ethereum-rpc-label", required=True)
    for role in ("baseline", "candidate"):
        parser.add_argument(f"--{role}-stdout", type=Path, required=True)
        parser.add_argument(f"--{role}-stderr", type=Path, required=True)
        parser.add_argument(f"--{role}-completion", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--rpc-before", type=Path, required=True)
    parser.add_argument("--rpc-after", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = parse_args(arguments)
    artifact_dir = args.artifact_dir.resolve()
    redaction_values: list[bytes] = []
    for name in ("SUBSTREAMS_API_TOKEN", "SUBSTREAMS_API_KEY", "ETHEREUM_RPC_URL"):
        value = os.environ.pop(name, "")
        if value:
            redaction_values.append(value.encode("utf-8", errors="strict"))
    try:
        certificate = verify_and_emit(
            root=args.root, profile_path=args.profile,
            baseline_stdout_path=args.baseline_stdout, baseline_stderr_path=args.baseline_stderr,
            baseline_completion_path=args.baseline_completion,
            candidate_stdout_path=args.candidate_stdout, candidate_stderr_path=args.candidate_stderr,
            candidate_completion_path=args.candidate_completion,
            build_manifest_path=args.build_manifest, rpc_before_path=args.rpc_before, rpc_after_path=args.rpc_after,
            baseline_stdout_retained_path=artifact_dir / "baseline.protocol-v3.stdout.jsonl",
            baseline_stderr_retained_path=artifact_dir / "baseline.protocol-v3.stderr",
            baseline_completion_retained_path=artifact_dir / "baseline.protocol-v3.completion.json",
            candidate_stdout_retained_path=artifact_dir / "candidate.protocol-v3.stdout.jsonl",
            candidate_stderr_retained_path=artifact_dir / "candidate.protocol-v3.stderr",
            candidate_completion_retained_path=artifact_dir / "candidate.protocol-v3.completion.json",
            baseline_capture_path=artifact_dir / "baseline.capture.json",
            candidate_capture_path=artifact_dir / "candidate.capture.json",
            baseline_canonical_path=artifact_dir / "baseline.complete.canonical.jsonl",
            candidate_canonical_path=artifact_dir / "candidate.complete.canonical.jsonl",
            certificate_path=artifact_dir / "parity-certificate.json",
            session_id=args.session_id, endpoint=args.substreams_endpoint, rpc_label=args.ethereum_rpc_label,
            redaction_values=tuple(redaction_values),
        )
    except (VerificationError, KeyError, TypeError, ValueError, OSError, UnicodeError) as error:
        print(f"parity verification failed: {error}", file=sys.stderr)
        return 1
    print(
        f"verified exact ordered V3 mainnet ChainConfig protobuf parity for [{START_BLOCK},{END_BLOCK_EXCLUSIVE}); "
        f"certificate={artifact_dir / 'parity-certificate.json'} transcript={certificate['comparison']['transcript_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
