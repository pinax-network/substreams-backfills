#!/usr/bin/env python3
"""Build a fail-closed manifest for one V3 mainnet parity candidate build.

This records a candidate produced by a controlled CI or operator environment. It
does not promote the packages or turn them into immutable production pins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


EXPECTED_MODULES = {
    "graph_out",
    "map_extract_data_types",
    "map_pools_created",
    "map_tokens_whitelist_pools",
    "store_derived_factory_tvl",
    "store_derived_tvl",
    "store_eth_prices",
    "store_max_windows",
    "store_min_windows",
    "store_native_amounts",
    "store_pool_count",
    "store_pool_liquidities",
    "store_pool_sqrt_price",
    "store_pools_created",
    "store_positions",
    "store_prices",
    "store_swaps_volume",
    "store_ticks_liquidities",
    "store_token_tvl",
    "store_tokens",
    "store_tokens_whitelist_pools",
    "store_total_tx_counts",
}
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
SUBSTREAMS_VERSION = "substreams version 1.20.3 (Commit cc555bd, Commit Date 2026-07-31T14:30:54Z)"
CAPTURE_CLIENT_VERSION = (
    "uniswap-v3-mainnet-parity-client-v1 "
    "(protocol v3; upstream v1.20.3 cc555bd4e325b65ac3f95dfde4655076f88d4a0a)"
)
CAPTURE_UPSTREAM_COMMIT = "cc555bd4e325b65ac3f95dfde4655076f88d4a0a"
CAPTURE_UPSTREAM_TREE = "38ea588549e5e41698da00ee149278aa2d855c64"
GO_VERSION_RE = re.compile(r"^go version go1\.26\.5 (?:darwin|linux)/(?:amd64|arm64)$")
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


class CandidateError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise CandidateError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


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
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as error:
        raise CandidateError(f"{source} is not valid UTF-8") from error
    except json.JSONDecodeError as error:
        raise CandidateError(f"{source} is not one strict JSON document: {error.msg}") from error


def strict_json_file(path: Path) -> dict[str, object]:
    require(path.is_file() and not path.is_symlink(), f"missing regular JSON input: {path}")
    value = strict_json_bytes(path.read_bytes(), str(path))
    require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"missing regular input: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def substreams_identity(root: Path) -> dict[str, object]:
    located = shutil.which("substreams")
    require(located is not None, "Substreams CLI is unavailable")
    binary = Path(located).resolve()
    require(binary.is_file() and not binary.is_symlink(), "Substreams CLI does not resolve to a regular binary")
    version = run_text([str(binary), "--version"], root)
    require(version == SUBSTREAMS_VERSION, "Substreams CLI version identity is not the exact official v1.20.3 release")
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    release_platform = f"{system}-{machine}"
    require(release_platform in OFFICIAL_SUBSTREAMS_BINARIES, "Substreams CLI platform is unsupported")
    expected = OFFICIAL_SUBSTREAMS_BINARIES[release_platform]
    binary_sha256 = sha256(binary)
    binary_bytes = binary.stat().st_size
    require(
        binary_sha256 == expected["binary_sha256"] and binary_bytes == expected["binary_bytes"],
        "Substreams CLI binary is not the checksum-pinned official v1.20.3 release",
    )
    return {
        "version": version,
        "release_platform": release_platform,
        "release_archive_sha256": expected["release_archive_sha256"],
        "binary_sha256": binary_sha256,
        "binary_bytes": binary_bytes,
    }


def capture_client_identity(root: Path, binary: Path) -> dict[str, object]:
    client_root = root / "scripts/parity-client"
    source = client_root / "main.go"
    tests = client_root / "main_test.go"
    go_mod = client_root / "go.mod"
    go_sum = client_root / "go.sum"
    stub_mod = client_root / "services-control-plane-stub/go.mod"
    for item in (source, tests, go_mod, go_sum, stub_mod):
        require(item.is_file() and not item.is_symlink(), f"capture-client input is missing: {item}")

    resolved = binary.resolve()
    require(resolved.is_file() and not resolved.is_symlink(), "capture client is not a regular binary")
    version = run_text([str(resolved), "--version"], root)
    require(version == CAPTURE_CLIENT_VERSION, "capture-client version identity drift")
    go_version = run_text(["go", "version"], client_root)
    require(GO_VERSION_RE.fullmatch(go_version) is not None, "capture client requires exact Go 1.26.5")
    go_env = run_text(["go", "env", "GOVERSION", "GOOS", "GOARCH"], client_root).splitlines()
    require(
        len(go_env) == 3
        and go_env[0] == "go1.26.5"
        and go_env[1] in {"darwin", "linux"}
        and go_env[2] in {"amd64", "arm64"}
        and go_version == f"go version go1.26.5 {go_env[1]}/{go_env[2]}",
        "capture-client Go environment drift",
    )

    try:
        result = subprocess.run(
            [
                "go",
                "list",
                "-mod=readonly",
                "-deps",
                "-f",
                "{{if .Standard}}{{.ImportPath}}|stdlib||{{else if .Module}}{{.ImportPath}}|{{.Module.Path}}|{{.Module.Version}}|{{.Module.Sum}}{{else}}{{.ImportPath}}|nomodule||{{end}}",
                "./...",
            ],
            cwd=client_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError("could not inventory capture-client dependencies") from error
    try:
        inventory = sorted({line for line in result.stdout.decode("utf-8", errors="strict").splitlines() if line})
    except UnicodeDecodeError as error:
        raise CandidateError("capture-client dependency inventory is not UTF-8") from error
    require(bool(inventory), "capture-client dependency inventory is empty")
    require(
        all("services-control-plane" not in line for line in inventory),
        "package-less private-module replacement entered the capture-client dependency graph",
    )
    substreams_lines = [
        line for line in inventory if "|github.com/streamingfast/substreams|v1.20.3|" in line
    ]
    require(bool(substreams_lines), "capture client is not bound to the v1.20.3 package closure")
    inventory_raw = ("\n".join(inventory) + "\n").encode("utf-8")
    raw = resolved.read_bytes()
    try:
        build_info_result = subprocess.run(
            ["go", "version", "-m", str(resolved)],
            cwd=client_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError("could not inspect capture-client binary build information") from error
    try:
        build_info_lines = build_info_result.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as error:
        raise CandidateError("capture-client binary build information is not UTF-8") from error
    require(bool(build_info_lines) and build_info_lines[0].endswith(": go1.26.5"), "capture-client binary was not built by Go 1.26.5")
    normalized_build_info = ["go\tgo1.26.5", *build_info_lines[1:]]
    require(
        "\tpath\tgithub.com/pinax-network/substreams-backfills/scripts/parity-client" in normalized_build_info,
        "capture-client binary module path drift",
    )
    required_settings = {
        "\tbuild\t-trimpath=true",
        "\tbuild\tCGO_ENABLED=0",
        f"\tbuild\tGOOS={go_env[1]}",
        f"\tbuild\tGOARCH={go_env[2]}",
    }
    require(required_settings <= set(normalized_build_info), "capture-client binary build settings drift")
    module_inventory = sorted(line for line in normalized_build_info if line.startswith("\tdep\t"))
    require(bool(module_inventory), "capture-client binary module inventory is empty")
    require(
        all("services-control-plane" not in line for line in normalized_build_info),
        "package-less private replacement entered the capture-client binary",
    )
    require(
        any(line.startswith("\tdep\tgithub.com/streamingfast/substreams\tv1.20.3\t") for line in module_inventory),
        "capture-client binary is not bound to Substreams v1.20.3",
    )
    require(all("\th1:" in line for line in module_inventory), "capture-client binary contains an unhashed module dependency")
    normalized_build_raw = ("\n".join(normalized_build_info) + "\n").encode("utf-8")
    module_graph_patch_raw = (
        b"scripts/parity-client/go.mod\0"
        + go_mod.read_bytes()
        + b"\0scripts/parity-client/services-control-plane-stub/go.mod\0"
        + stub_mod.read_bytes()
    )
    return {
        "version": version,
        "binary_sha256": hashlib.sha256(raw).hexdigest(),
        "binary_bytes": len(raw),
        "build": {
            "go_version": go_version,
            "goos": go_env[1],
            "goarch": go_env[2],
            "command": [
                "go",
                "build",
                "-mod=readonly",
                "-trimpath",
                "-buildvcs=false",
                "-ldflags=-buildid=",
                "-o",
                "<capture-client>",
                ".",
            ],
            "cgo_enabled": False,
        },
        "source": {
            "upstream_version": "v1.20.3",
            "upstream_commit": CAPTURE_UPSTREAM_COMMIT,
            "upstream_tree": CAPTURE_UPSTREAM_TREE,
            "client_sha256": sha256(source),
            "tests_sha256": sha256(tests),
            "go_mod_sha256": sha256(go_mod),
            "go_sum_sha256": sha256(go_sum),
            "package_less_replacement_go_mod_sha256": sha256(stub_mod),
            "public_module_graph_patch_sha256": hashlib.sha256(module_graph_patch_raw).hexdigest(),
            "runtime_dependency_inventory": inventory,
            "runtime_dependency_inventory_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "runtime_dependency_count": len(inventory),
            "binary_build_info": normalized_build_info,
            "binary_build_info_sha256": hashlib.sha256(normalized_build_raw).hexdigest(),
            "binary_module_inventory": module_inventory,
            "binary_module_count": len(module_inventory),
            "private_replacement_imported": False,
        },
    }


def run_text(command: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError(f"command failed: {command[0]} {command[1]}") from error
    try:
        value = result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise CandidateError(f"{command[0]} emitted invalid UTF-8") from error
    require(bool(value), f"{command[0]} emitted an empty identity")
    return value


def git_value(root: Path, revision: str) -> str:
    return run_text(["git", "rev-parse", "--verify", revision], root)


def require_head_file(root: Path, path: Path, revision: str) -> None:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise CandidateError(f"input is outside the exact checkout: {path}") from error
    try:
        committed = subprocess.run(
            ["git", "show", f"{revision}:{relative}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError(f"input is not present at the exact revision: {relative}") from error
    require(committed == resolved.read_bytes(), f"input differs from exact revision: {relative}")


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
            fail(f"unsupported protobuf wire type {wire_type}")
        fields.append((number, wire_type, value))
    return fields


def embedded_wasm(package: Path) -> bytes:
    package_fields = wire_fields(package.read_bytes())
    modules_messages = [
        value for number, wire, value in package_fields if number == 6 and wire == 2
    ]
    require(len(modules_messages) == 1, f"{package} must contain one Modules message")
    modules_message = modules_messages[0]
    require(isinstance(modules_message, bytes), f"{package} Modules field is malformed")
    binaries = [
        value for number, wire, value in wire_fields(modules_message) if number == 2 and wire == 2
    ]
    require(len(binaries) == 1, f"{package} must contain one binary")
    binary = binaries[0]
    require(isinstance(binary, bytes), f"{package} binary field is malformed")
    binary_fields = wire_fields(binary)
    binary_types = [
        value for number, wire, value in binary_fields if number == 1 and wire == 2
    ]
    require(binary_types == [b"wasm/rust-v1"], f"{package} binary type is not wasm/rust-v1")
    contents = [value for number, wire, value in binary_fields if number == 2 and wire == 2]
    require(len(contents) == 1, f"{package} binary must contain one payload")
    content = contents[0]
    require(isinstance(content, bytes) and bool(content), f"{package} WASM payload is empty")
    return content


def package_info(root: Path, package: Path) -> dict[str, object]:
    try:
        result = subprocess.run(
            ["substreams", "info", "--json", str(package)],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError(f"could not inspect package {package.name}") from error
    value = strict_json_bytes(result.stdout, f"substreams info for {package.name}")
    require(isinstance(value, dict), f"package info for {package.name} must be an object")
    return value


def module_hashes(info: dict[str, object], package: Path) -> dict[str, str]:
    modules = info.get("modules")
    require(isinstance(modules, list), f"{package.name} module inventory is missing")
    result: dict[str, str] = {}
    for item in modules:
        require(isinstance(item, dict), f"{package.name} module entry is malformed")
        name = item.get("name")
        digest = item.get("hash")
        require(isinstance(name, str) and name in EXPECTED_MODULES, f"{package.name} has an unexpected module")
        require(name not in result, f"{package.name} has duplicate module {name}")
        require(isinstance(digest, str) and HEX40_RE.fullmatch(digest) is not None, f"{package.name}.{name} hash is malformed")
        result[name] = digest
    require(set(result) == EXPECTED_MODULES, f"{package.name} module set is incomplete")
    graph_out = next(item for item in modules if item.get("name") == "graph_out")
    require(graph_out.get("kind") == "map", f"{package.name} graph_out is not a map module")
    require(
        graph_out.get("output_type") == "proto:sf.substreams.entity.v1.EntityChanges",
        f"{package.name} graph_out output type drift",
    )
    return dict(sorted(result.items()))


def artifact_record(root: Path, package: Path, expected: tuple[str, str, str]) -> tuple[dict[str, object], bytes]:
    require(package.is_file() and not package.is_symlink(), f"missing regular package: {package}")
    info = package_info(root, package)
    expected_name, expected_version, expected_network = expected
    require(info.get("name") == expected_name, f"{package.name} package name drift")
    require(info.get("version") == expected_version, f"{package.name} package version drift")
    require(info.get("network") == expected_network, f"{package.name} package network drift")
    wasm = embedded_wasm(package)
    return (
        {
            "spkg_sha256": sha256(package),
            "bytes": package.stat().st_size,
            "wasm_sha256": hashlib.sha256(wasm).hexdigest(),
            "wasm_bytes": len(wasm),
            "execution_module_hashes": module_hashes(info, package),
        },
        wasm,
    )


def write_exclusive(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def build_manifest(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    revision = args.source_revision
    require(HEX40_RE.fullmatch(revision) is not None, "source revision must be 40 lowercase hex characters")
    require(git_value(root, "HEAD^{commit}") == revision, "source revision does not match checked-out HEAD")
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError("could not inspect checked-out revision") from error
    require(not status, "checked-out revision is not clean")
    tree = git_value(root, "HEAD^{tree}")
    require(HEX40_RE.fullmatch(tree) is not None, "repository tree identity is malformed")

    profile = args.profile.resolve()
    config = root / "uniswap-v3/chain-config/configs/mainnet-v1.json"
    provenance_path = root / "provenance/uniswap-v3-chain-config-v1.json"
    overlay = root / "uniswap-v3/chain-config/runtime.patch"
    builder = root / "scripts/build-uniswap-v3-mainnet-parity-candidate.py"
    capture_source = root / "scripts/parity-client/main.go"
    capture_tests = root / "scripts/parity-client/main_test.go"
    capture_go_mod = root / "scripts/parity-client/go.mod"
    capture_go_sum = root / "scripts/parity-client/go.sum"
    capture_stub_mod = root / "scripts/parity-client/services-control-plane-stub/go.mod"
    for exact_input in (
        profile,
        config,
        provenance_path,
        overlay,
        builder,
        capture_source,
        capture_tests,
        capture_go_mod,
        capture_go_sum,
        capture_stub_mod,
    ):
        require_head_file(root, exact_input, revision)
    provenance = strict_json_file(provenance_path)
    source = provenance.get("source")
    require(isinstance(source, dict), "ChainConfig source provenance is missing")
    import_commit = source.get("commit")
    import_tree = source.get("tree")
    require(isinstance(import_commit, str) and HEX40_RE.fullmatch(import_commit) is not None, "import commit is malformed")
    require(isinstance(import_tree, str) and HEX40_RE.fullmatch(import_tree) is not None, "import tree is malformed")
    require(source.get("repository") == "pinax-network/substreams-uniswap-v3", "import repository drift")
    require(source.get("import_path") == "uniswap-v3/source", "import path drift")

    config_digest = sha256(config)
    overlay_digest = sha256(overlay)
    configurations = provenance.get("configurations")
    require(isinstance(configurations, dict) and isinstance(configurations.get("mainnet"), dict), "mainnet config provenance is missing")
    require(configurations["mainnet"].get("raw_sha256") == config_digest, "mainnet config provenance digest drift")
    provenance_overlay = provenance.get("overlay")
    require(isinstance(provenance_overlay, dict) and provenance_overlay.get("raw_sha256") == overlay_digest, "runtime overlay provenance digest drift")
    shared = provenance.get("shared_artifacts")
    require(isinstance(shared, dict) and isinstance(shared.get("schema"), dict), "schema provenance is missing")
    schema_digest = shared["schema"].get("raw_sha256")
    require(
        isinstance(schema_digest, str) and re.fullmatch(r"[0-9a-f]{64}", schema_digest) is not None,
        "target schema provenance digest is malformed",
    )

    baseline, baseline_wasm = artifact_record(
        root,
        args.baseline_spkg.resolve(),
        ("uniswap_v3", "v0.2.11", "mainnet"),
    )
    configured_mainnet, configured_wasm = artifact_record(
        root,
        args.mainnet_spkg.resolve(),
        ("uniswap_v3_mainnet_backfill", "v0.3.0", "mainnet"),
    )
    configured_base, base_wasm = artifact_record(
        root,
        args.base_spkg.resolve(),
        ("uniswap_v3_base_backfill", "v0.3.0", "base"),
    )
    require(configured_wasm == base_wasm, "configured mainnet and Base WASM payloads differ")
    require(baseline_wasm != configured_wasm, "baseline and configured mainnet WASM payloads unexpectedly match")

    return {
        "format_version": 1,
        "kind": "uniswap-v3-mainnet-chain-config-parity-controlled-build-candidate",
        "status": "candidate-not-a-production-pin",
        "source": {
            "repository": "pinax-network/substreams-backfills",
            "revision": revision,
            "tree": tree,
            "import_repository": source["repository"],
            "import_commit": import_commit,
            "import_tree": import_tree,
        },
        "inputs": {
            "profile_sha256": sha256(profile),
            "chain_config_sha256": config_digest,
            "chain_config_provenance_sha256": sha256(provenance_path),
            "runtime_overlay_sha256": overlay_digest,
            "schema_sha256": schema_digest,
        },
        "toolchain": {
            "rustc": run_text(["rustc", "-Vv"], root / "uniswap-v3/source"),
            "cargo": run_text(["cargo", "--version"], root / "uniswap-v3/source"),
            "substreams": substreams_identity(root),
            "capture_client": capture_client_identity(root, args.capture_client),
            "go": run_text(["go", "version"], root),
            "python": sys.version.splitlines()[0],
            "platform": platform.platform(),
        },
        "artifacts": {
            "baseline": baseline,
            "configured_mainnet": configured_mainnet,
            "configured_base": configured_base,
        },
        "assertions": {
            "configured_mainnet_and_base_wasm_equal": True,
            "baseline_and_configured_mainnet_wasm_equal": False,
        },
        "trust_boundary": {
            "promotion_eligible": False,
            "authoritative_graph_reference": False,
            "physical_or_poi_parity": False,
            "production_pin": False,
            "approved_runtime_contract": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--baseline-spkg", type=Path, required=True)
    parser.add_argument("--mainnet-spkg", type=Path, required=True)
    parser.add_argument("--base-spkg", type=Path, required=True)
    parser.add_argument("--capture-client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_manifest(args)
        write_exclusive(args.output.resolve(), manifest)
    except (CandidateError, KeyError, TypeError, ValueError) as error:
        print(f"Uniswap V3 controlled-build candidate failed: {error}", file=sys.stderr)
        return 1
    print(f"wrote controlled-build candidate manifest to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
