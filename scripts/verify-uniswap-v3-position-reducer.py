#!/usr/bin/env python3
"""Fail-closed verification for the host-only Uniswap V3 Position reducer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


CONTRACT_PATH = Path("uniswap-v3/position-reducer/contract-v1.json")
CONTRACT_SHA256 = "6cbe12850889f4cf5538ac8bbf938618656c29efbb8b6ea40823def84a111526"
OVERLAY = Path("uniswap-v3/position-reducer")
WRITER_VERIFIER_PATH = Path("scripts/verify-uniswap-v3-writer-runtime.py")
WRITER_RUNTIME_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
WRITER_DESCRIPTOR_SHA256 = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0"
WRITER_SOURCE_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
PROFILE_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
REDUCER_SEMANTICS_SHA256 = "7b734cca8bf10038c73fd11a9af1a29e0aa7d7082ad621658485fec4bf947d2b"
REDUCER_SOURCE_SHA256 = "55beaef4e69e073ad8c1888901e9b16275c4dcfc038cbff05670aec2342dfdc2"
RUNTIME_PATCH_SHA256 = "281836847abbc800528d487777757e1ffd44a7962bdb8c686aaeae4a874dd717"
EXPECTED_REDUCER_RUNTIME_DELTA = {
    "configs/position-reducer-v1.json",
    "src/lib.rs",
    "src/position_reducer.rs",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_writer_verifier(root: Path):
    path = root / WRITER_VERIFIER_PATH
    spec = importlib.util.spec_from_file_location("uniswap_v3_writer_runtime_verifier", path)
    require(spec is not None and spec.loader is not None, "writer verifier cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_keys(value: dict[str, object], expected: set[str], name: str) -> None:
    require(set(value) == expected, f"{name} field set drift: {sorted(value)}")


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "position-reducer runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "position-reducer runtime contract raw digest drift")
    contract = json.loads(path.read_text())
    exact_keys(
        contract,
        {
            "format_version",
            "contract_version",
            "mode",
            "ordered_materialization",
            "repository_artifacts",
            "materialized_runtime_artifacts",
            "producer_contract",
            "reducer_contract",
            "package_contract",
            "truth_boundary",
        },
        "position-reducer runtime contract",
    )
    require(
        (
            contract["format_version"],
            contract["contract_version"],
            contract["mode"],
        )
        == (1, "uniswap-v3-position-reducer-runtime/v1", "host-diagnostic-only"),
        "unsupported position-reducer runtime contract",
    )
    require(
        contract["ordered_materialization"]
        == [
            {
                "path": "uniswap-v3/writer-runtime/contract-v1.json",
                "contract_version": "uniswap-v3-writer-runtime/v1",
                "sha256": WRITER_RUNTIME_SHA256,
            },
            {
                "path": "uniswap-v3/position-reducer/runtime.patch",
                "sha256": RUNTIME_PATCH_SHA256,
            },
        ],
        "position-reducer materialization order drift",
    )
    expected_artifacts = {
        "readme": ("uniswap-v3/position-reducer/README.md", None),
        "reducer_contract": (
            "uniswap-v3/position-reducer/position-reducer-v1.json",
            "uniswap-v3-position-reducer/v1",
        ),
        "reducer_source": (
            "uniswap-v3/position-reducer/src/position_reducer.rs",
            None,
        ),
        "segment_profiles": (
            "uniswap-v3/writer-runtime/segment-profiles-v1.json",
            "uniswap-v3-writer-runtime-segment-profiles/v1",
        ),
        "source_writer_contract": (
            "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
            "uniswap-v3-writer-compatibility/v3",
        ),
    }
    require(set(contract["repository_artifacts"]) == set(expected_artifacts), "repository artifact set drift")
    for name, (relative, version) in expected_artifacts.items():
        artifact = contract["repository_artifacts"][name]
        expected_keys = {"path", "sha256"} | ({"contract_version"} if version else set())
        exact_keys(artifact, expected_keys, f"repository artifact {name}")
        require(artifact["path"] == relative, f"repository artifact path drift: {name}")
        if version:
            require(artifact["contract_version"] == version, f"repository artifact version drift: {name}")
        require(sha256(root / relative) == artifact["sha256"], f"repository artifact digest drift: {name}")
    require(
        contract["repository_artifacts"]["reducer_contract"]["sha256"] == REDUCER_SEMANTICS_SHA256
        and contract["repository_artifacts"]["reducer_source"]["sha256"] == REDUCER_SOURCE_SHA256
        and contract["repository_artifacts"]["segment_profiles"]["sha256"] == PROFILE_SHA256
        and contract["repository_artifacts"]["source_writer_contract"]["sha256"] == WRITER_SOURCE_SHA256,
        "position-reducer pinned repository digest drift",
    )
    require(
        contract["producer_contract"]
        == {
            "writer_runtime_sha256": WRITER_RUNTIME_SHA256,
            "writer_descriptor_sha256": WRITER_DESCRIPTOR_SHA256,
            "writer_source_contract_sha256": WRITER_SOURCE_SHA256,
            "segment_profiles_sha256": PROFILE_SHA256,
            "mainnet_runtime_start_block": 12_369_621,
            "mainnet_npm_start_block": 12_369_651,
            "base_runtime_start_block": 1_371_679,
            "base_npm_start_block": 1_371_713,
        },
        "position-reducer producer contract drift",
    )
    require(
        contract["reducer_contract"]
        == {
            "state_entities": ["Position", "PositionSnapshot"],
            "event_order": "global ordinal and block_log_index strictly increasing",
            "graph_call_cache": "invocation-local; exact block pointer, target address, and calldata",
            "token_reads": "event ordinal scoped",
            "block_context": "number, timestamp, optional hash",
            "decimal_precision": 34,
            "uint_width_bits": 256,
            "segment_count": 8,
            "npm_profile_count": 5,
            "transaction_entity_side_effects": False,
        },
        "position-reducer execution summary drift",
    )
    require(
        contract["package_contract"]
        == {
            "module_count": 23,
            "diagnostic_module": "map_writer_events",
            "diagnostic_consumers": [],
            "position_reducer_substreams_module": False,
            "graph_out_output": "proto:sf.substreams.entity.v1.EntityChanges",
            "manifests_changed_from_writer_runtime": False,
            "protobuf_descriptors_changed_from_writer_runtime": False,
            "shared_wasm_binary_count": 1,
            "wasm_identical_to_writer_runtime": True,
            "writer_package_verifier_inherited": True,
        },
        "position-reducer package contract drift",
    )
    require(
        contract["truth_boundary"]
        == {
            "backfill_ready": False,
            "boundary_state_continuity_complete": False,
            "diagnostic_only": True,
            "full_npm_handler_semantics": False,
            "graph_out_replaced": False,
            "live_calls_added": False,
            "logical_oracle_complete": False,
            "physical_parity_complete": False,
            "poi_parity_complete": False,
            "production_ready": False,
            "runtime_population_complete": False,
            "stores_added": False,
            "substreams_handler_added": False,
            "transaction_entity_effects_implemented": False,
        },
        "position-reducer truth boundary promoted",
    )
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "position-reducer-v1.json"
    require(sha256(path) == REDUCER_SEMANTICS_SHA256, "position-reducer semantics digest drift")
    contract = json.loads(path.read_text())
    require(contract["format_version"] == 1, "position-reducer semantics format drift")
    require(contract["contract_version"] == "uniswap-v3-position-reducer/v1", "position-reducer semantics version drift")
    require(contract["mode"] == "host-diagnostic-only", "position-reducer semantics mode drift")
    require(contract["source_writer_runtime"]["sha256"] == WRITER_RUNTIME_SHA256, "writer runtime binding drift")
    require(
        contract["source_writer_runtime"]["writer_descriptor_sha256"] == WRITER_DESCRIPTOR_SHA256,
        "writer descriptor binding drift",
    )
    require(contract["source_writer_contract"]["sha256"] == WRITER_SOURCE_SHA256, "writer source binding drift")
    require(contract["source_segment_profiles"]["sha256"] == PROFILE_SHA256, "segment profile binding drift")
    require(len(contract["segments"]) == 8, "position-reducer requires exactly eight segments")
    require(len(contract["npm_profiles"]) == 5, "position-reducer requires exactly five NPM profiles")
    base_root = next(profile for profile in contract["npm_profiles"] if profile["profile_id"] == "base-root-amount0-to-both")
    require(base_root["collect_token_reads"] == ["token0"], "Base-root Collect must read only token0")
    require(all(value is False for key, value in contract["truth_boundary"].items() if key != "diagnostic_only"), "semantic readiness flag promoted")
    require(contract["truth_boundary"]["diagnostic_only"] is True, "semantic diagnostic boundary drift")
    return contract


def verify_overlay_static(root: Path, writer) -> None:
    patch_path = root / OVERLAY / "runtime.patch"
    require(sha256(patch_path) == RUNTIME_PATCH_SHA256, "position-reducer patch digest drift")
    patch = patch_path.read_text()
    files = set(re.findall(r"^diff --git a/(\S+) b/\1$", patch, re.MULTILINE))
    require(files == {"src/lib.rs"}, f"position-reducer patch file set drift: {sorted(files)}")
    require(patch.count("+pub mod position_reducer;") == 1, "position-reducer module declaration drift")
    require(
        patch.count('+#[cfg(not(target_arch = "wasm32"))]') == 1,
        "position-reducer module must remain excluded from the WASM target",
    )
    require("pub fn graph_out(" in patch, "position-reducer patch lost its exact writer-runtime anchor")

    source_path = root / OVERLAY / "src/position_reducer.rs"
    require(sha256(source_path) == REDUCER_SOURCE_SHA256, "position-reducer source digest drift")
    source = source_path.read_text()
    for required in (
        "pub trait ReducerInputs",
        "pub fn reduce_position_block",
        "struct GraphCallCache",
        "transaction_entity_effects_implemented: false",
        "full_npm_handler_semantics: false",
    ):
        require(required in source, f"position-reducer source contract missing `{required}`")
    for forbidden in (
        "#[substreams::handlers",
        "rpc::eth_call",
        "pub fn graph_out",
        "StoreSet",
        "StoreAdd",
        "EntityChanges",
        "std::fs",
        "std::net",
    ):
        require(forbidden not in source, f"position-reducer source contains forbidden runtime capability `{forbidden}`")

    with tempfile.TemporaryDirectory(prefix="uniswap-v3-position-patch-") as temporary:
        writer_runtime = Path(temporary) / "writer"
        writer.materialize_expected(root, writer_runtime)
        result = subprocess.run(
            [
                "patch",
                "--directory",
                str(writer_runtime),
                "--strip",
                "1",
                "--forward",
                "--batch",
                "-F",
                "0",
                "--dry-run",
            ],
            input=patch,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        require(result.returncode == 0, "position-reducer patch does not apply after exact writer runtime")


def materialize_expected(root: Path, destination: Path, writer=None) -> None:
    writer = writer or load_writer_verifier(root)
    writer.materialize_expected(root, destination)
    patch = (root / OVERLAY / "runtime.patch").read_text()
    subprocess.run(
        [
            "patch",
            "--directory",
            str(destination),
            "--strip",
            "1",
            "--forward",
            "--batch",
            "-F",
            "0",
        ],
        input=patch,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    shutil.copy2(root / OVERLAY / "src/position_reducer.rs", destination / "src/position_reducer.rs")
    shutil.copy2(
        root / OVERLAY / "position-reducer-v1.json",
        destination / "configs/position-reducer-v1.json",
    )


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object], writer) -> Path:
    require(runtime.is_dir(), f"position-reducer runtime missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="uniswap-v3-position-expected-") as temporary:
        temporary_path = Path(temporary)
        expected_writer = temporary_path / "writer"
        expected_final = temporary_path / "final"
        writer.materialize_expected(root, expected_writer)
        materialize_expected(root, expected_final, writer)
        writer_files = writer.non_build_files(expected_writer)
        final_files = writer.non_build_files(expected_final)
        runtime_files = writer.non_build_files(runtime)
        delta = {
            relative
            for relative in set(writer_files) | set(final_files)
            if relative not in writer_files
            or relative not in final_files
            or writer_files[relative].read_bytes() != final_files[relative].read_bytes()
        }
        require(delta == EXPECTED_REDUCER_RUNTIME_DELTA, f"position-reducer runtime delta drift: {sorted(delta)}")
        require(set(runtime_files) == set(final_files), "position-reducer runtime file set drift")
        for relative, expected in final_files.items():
            actual = runtime_files[relative]
            require(actual.read_bytes() == expected.read_bytes(), f"position-reducer runtime content drift: {relative}")
            require(
                actual.stat().st_mode & 0o111 == expected.stat().st_mode & 0o111,
                f"position-reducer runtime mode drift: {relative}",
            )
    writer.verify_toolchain(runtime)
    writer.verify_protobuf(runtime)
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized position-reducer artifact drift: {relative}")
    return runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"


def verify_writer_runtime(root: Path, writer) -> None:
    writer_contract = writer.load_runtime_contract(root)
    require(writer.CONTRACT_SHA256 == WRITER_RUNTIME_SHA256, "loaded writer verifier digest drift")
    require(sha256(root / "uniswap-v3/writer-runtime/contract-v1.json") == WRITER_RUNTIME_SHA256, "writer runtime contract digest drift")
    profiles = writer.load_profiles(root)
    configs = writer.load_configs(root)
    writer.load_manifests(root, configs)
    writer.verify_fixture(root)
    writer.verify_overlay_static(root)
    require(writer_contract["package_contract"]["module_count"] == 23, "writer module count drift")
    require(len(profiles["profiles"]) == 8, "writer segment count drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--writer-runtime", type=Path)
    parser.add_argument("--mainnet-spkg", type=Path)
    parser.add_argument("--base-spkg", type=Path)
    args = parser.parse_args()
    if bool(args.mainnet_spkg) != bool(args.base_spkg):
        parser.error("--mainnet-spkg and --base-spkg must be passed together")
    if args.mainnet_spkg and not args.runtime:
        parser.error("package checks require --runtime")
    if args.writer_runtime and not args.runtime:
        parser.error("writer-runtime comparison requires --runtime")
    try:
        root = args.root.resolve()
        writer = load_writer_verifier(root)
        contract = load_contract(root)
        load_semantics(root)
        verify_writer_runtime(root, writer)
        verify_overlay_static(root, writer)
        runtime_wasm = None
        if args.runtime:
            runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract, writer)
        if args.writer_runtime:
            writer_wasm = args.writer_runtime.resolve() / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"
            require(runtime_wasm.is_file(), "position-reducer WASM missing")
            require(writer_wasm.is_file(), "writer-runtime WASM missing")
            require(runtime_wasm.read_bytes() == writer_wasm.read_bytes(), "host-only reducer changed the writer WASM")
        if args.mainnet_spkg:
            writer.verify_packages(
                runtime_wasm,
                {
                    "mainnet": args.mainnet_spkg.resolve(),
                    "base": args.base_spkg.resolve(),
                },
            )
        print("verified host-only Uniswap V3 Position/Snapshot reducer, exact writer binding, and conservative gates")
        return 0
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
        VerificationError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Uniswap V3 position-reducer verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
