#!/usr/bin/env python3
"""Fail-closed verification for the host-only Uniswap V3 Pool Flash reducer."""

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


CONTRACT_PATH = Path("uniswap-v3/flash-reducer/contract-v1.json")
CONTRACT_SHA256 = "46e397776c332e30d5c74fe5e73803b378ace6bef869f33eb69f055a5b2cd36c"
OVERLAY = Path("uniswap-v3/flash-reducer")
WRITER_VERIFIER_PATH = Path("scripts/verify-uniswap-v3-writer-runtime.py")
WRITER_RUNTIME_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
WRITER_DESCRIPTOR_SHA256 = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0"
WRITER_SOURCE_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
PROFILE_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
EXECUTION_ORDER_PATH = Path("uniswap-v3/execution-order/v1/contract.json")
EXECUTION_ORDER_VERSION = "uniswap-v3-execution-order/v1"
EXECUTION_ORDER_SHA256 = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"
REDUCER_SEMANTICS_SHA256 = "85a3eb1037223dc7794706f860723df0f2897dd043e5e4a9db23f4a2de52af4f"
REDUCER_SOURCE_SHA256 = "751df82569aff4a232e3c2bbb93d97abe2c6057bb857c08a69f7b832bda40a3f"
REDUCER_TESTS_SHA256 = "d33e1d5cea4f174d40ed1aab979f59c3c748e55dd2b9376c9cf89b7b969d68b4"
RUNTIME_PATCH_SHA256 = "1d916ba62f75541d8ce36dc986e49e53f9213a8dc3881acdcc19e77f0aead5f9"
EXPECTED_REDUCER_RUNTIME_DELTA = {
    "configs/flash-reducer-v1.json",
    "src/flash_reducer.rs",
    "src/lib.rs",
}
EXPECTED_TRUTH = {
    "backfill_ready": False,
    "boundary_state_continuity_complete": False,
    "combined_handler_order_implemented": False,
    "cross_component_order_proven": False,
    "diagnostic_only": True,
    "dynamic_datasource_stage_order_implemented": False,
    "full_pool_handler_semantics": False,
    "graph_node_execution_order_supplement_bound": True,
    "graph_out_replaced": False,
    "live_rpc_added": False,
    "logical_oracle_complete": False,
    "physical_parity_complete": False,
    "poi_parity_complete": False,
    "production_ready": False,
    "rpc_trigger_binding_complete": False,
    "runtime_consumes_execution_order_contract": False,
    "runtime_population_complete": False,
    "same_path_order_machine_proven": False,
    "stores_added": False,
    "substreams_handler_added": False,
    "target_runtime_identity_bound": False,
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


def load_writer_verifier(root: Path):
    path = root / WRITER_VERIFIER_PATH
    spec = importlib.util.spec_from_file_location("uniswap_v3_writer_runtime_verifier", path)
    require(spec is not None and spec.loader is not None, "writer verifier cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "flash-reducer runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "flash-reducer runtime contract raw digest drift")
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
        "flash-reducer runtime contract",
    )
    require(
        (contract["format_version"], contract["contract_version"], contract["mode"])
        == (1, "uniswap-v3-flash-reducer-runtime/v1", "host-diagnostic-only"),
        "unsupported flash-reducer runtime contract",
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
                "path": "uniswap-v3/flash-reducer/runtime.patch",
                "sha256": RUNTIME_PATCH_SHA256,
            },
        ],
        "flash-reducer materialization order drift",
    )
    expected_artifacts = {
        "readme": ("uniswap-v3/flash-reducer/README.md", None),
        "reducer_contract": (
            "uniswap-v3/flash-reducer/flash-reducer-v1.json",
            "uniswap-v3-flash-reducer/v1",
        ),
        "reducer_source": ("uniswap-v3/flash-reducer/src/flash_reducer.rs", None),
        "reducer_tests": ("scripts/tests/test_uniswap_v3_flash_reducer.py", None),
        "source_execution_order_contract": (
            EXECUTION_ORDER_PATH.as_posix(),
            EXECUTION_ORDER_VERSION,
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
        exact_keys(artifact, {"path", "sha256"} | ({"contract_version"} if version else set()), f"repository artifact {name}")
        require(artifact["path"] == relative, f"repository artifact path drift: {name}")
        if version:
            require(artifact["contract_version"] == version, f"repository artifact version drift: {name}")
        require(sha256(root / relative) == artifact["sha256"], f"repository artifact digest drift: {name}")
    require(
        contract["repository_artifacts"]["reducer_contract"]["sha256"] == REDUCER_SEMANTICS_SHA256
        and contract["repository_artifacts"]["reducer_source"]["sha256"] == REDUCER_SOURCE_SHA256
        and contract["repository_artifacts"]["reducer_tests"]["sha256"] == REDUCER_TESTS_SHA256
        and contract["repository_artifacts"]["source_execution_order_contract"]["sha256"]
        == EXECUTION_ORDER_SHA256
        and contract["repository_artifacts"]["segment_profiles"]["sha256"] == PROFILE_SHA256
        and contract["repository_artifacts"]["source_writer_contract"]["sha256"] == WRITER_SOURCE_SHA256,
        "flash-reducer pinned repository digest drift",
    )
    require(
        contract["producer_contract"]
        == {
            "writer_runtime_sha256": WRITER_RUNTIME_SHA256,
            "writer_descriptor_sha256": WRITER_DESCRIPTOR_SHA256,
            "writer_source_contract_sha256": WRITER_SOURCE_SHA256,
            "execution_order_contract_sha256": EXECUTION_ORDER_SHA256,
            "segment_profiles_sha256": PROFILE_SHA256,
            "mainnet_runtime_start_block": 12_369_621,
            "base_runtime_start_block": 1_371_679,
        },
        "flash-reducer producer contract drift",
    )
    require(
        contract["reducer_contract"]
        == {
            "state_entities": ["Pool", "PoolDatasourceMembership"],
            "event_order": "diagnostic envelope ordinal and block_log_index strictly increasing; not Graph Node cross-stage order",
            "membership": "diagnostic creation-ordinal convention; not Graph Node block-scoped activation",
            "graph_node_order_scope": "dynamic-datasource stage order is not implemented; no same-path or cross-component order claim",
            "fatal_rollback_scope": "diagnostic Pool and membership state only; excludes VID, PoI, persisted data sources, deterministic-error streams, and physical transaction semantics",
            "call_order": ["f3058399", "46141319"],
            "call_cache": "none",
            "call_block_scope": "post-block hash when available; number fallback",
            "atomic_pool_update": True,
            "segment_count": 8,
            "fatal_segment_count": 5,
            "nonfatal_segment_count": 3,
            "emitted_row_types": ["Pool"],
            "synthetic_row_types": [],
        },
        "flash-reducer execution summary drift",
    )
    require(
        contract["package_contract"]
        == {
            "module_count": 23,
            "diagnostic_module": "map_writer_events",
            "diagnostic_consumers": [],
            "flash_reducer_substreams_module": False,
            "graph_out_output": "proto:sf.substreams.entity.v1.EntityChanges",
            "manifests_changed_from_writer_runtime": False,
            "protobuf_descriptors_changed_from_writer_runtime": False,
            "shared_wasm_binary_count": 1,
            "wasm_identical_to_writer_runtime": True,
            "writer_package_verifier_inherited": True,
        },
        "flash-reducer package contract drift",
    )
    require(contract["truth_boundary"] == EXPECTED_TRUTH, "flash-reducer truth boundary promoted")
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "flash-reducer-v1.json"
    require(sha256(path) == REDUCER_SEMANTICS_SHA256, "flash-reducer semantics digest drift")
    contract = json.loads(path.read_text())
    exact_keys(
        contract,
        {
            "format_version",
            "contract_version",
            "mode",
            "source_writer_contract",
            "source_segment_profiles",
            "source_writer_runtime",
            "source_execution_order_contract",
            "network_contracts",
            "execution_contract",
            "segments",
            "truth_boundary",
        },
        "flash-reducer semantics",
    )
    require(
        (contract["format_version"], contract["contract_version"], contract["mode"])
        == (1, "uniswap-v3-flash-reducer/v1", "host-diagnostic-only"),
        "flash-reducer semantics identity drift",
    )
    require(contract["source_writer_runtime"]["sha256"] == WRITER_RUNTIME_SHA256, "writer runtime binding drift")
    require(contract["source_writer_runtime"]["writer_descriptor_sha256"] == WRITER_DESCRIPTOR_SHA256, "writer descriptor binding drift")
    require(contract["source_writer_contract"]["sha256"] == WRITER_SOURCE_SHA256, "writer source binding drift")
    require(contract["source_segment_profiles"]["sha256"] == PROFILE_SHA256, "segment profile binding drift")
    require(
        contract["source_execution_order_contract"]
        == {
            "path": EXECUTION_ORDER_PATH.as_posix(),
            "contract_version": EXECUTION_ORDER_VERSION,
            "raw_sha256": EXECUTION_ORDER_SHA256,
        },
        "execution-order supplement binding drift",
    )
    require(len(contract["segments"]) == 8, "flash-reducer requires exactly eight segments")
    require(
        [segment["nonfatal_errors"] for segment in contract["segments"]]
        == [False, False, False, False, False, True, True, True],
        "flash-reducer fatal/nonfatal policy drift",
    )
    execution = contract["execution_contract"]
    require(
        execution["event_order"]
        == "diagnostic input convention: ordinal and block_log_index strictly increase within the supplied PoolCreated/Flash envelope",
        "diagnostic input ordering convention drift",
    )
    require(
        execution["membership"]
        == "diagnostic creation-ordinal input convention: an earlier supplied PoolCreated marks membership for a later supplied Flash; this does not model Graph Node block-scoped activation",
        "diagnostic membership convention drift",
    )
    require(
        execution["graph_node_order_scope"]
        == "does not model Graph Node dynamic-datasource stage order, breadth-first whole-block replay, or block-scoped activation; no same-path or cross-component order claim",
        "Graph Node ordering scope promoted",
    )
    require(
        execution["fatal_error"]
        == "discard diagnostic Pool and membership changes from this reducer block and stop; excludes Graph Node VID, PoI, persisted-data-source, deterministic-error-stream, and physical transaction semantics",
        "fatal rollback scope promoted",
    )
    require(execution["fee_growth_0_calldata"] == "f3058399", "fee0 selector drift")
    require(execution["fee_growth_1_calldata"] == "46141319", "fee1 selector drift")
    require(execution["call_cache"] == "none; every active Flash attempts its own fee0 then fee1 calls", "call cache enabled")
    require(execution["flash_specific_guards"] == [], "Flash-specific guard introduced")
    require(execution["emitted_row_types"] == ["Pool"] and execution["synthetic_row_types"] == [], "synthetic row contract drift")
    require(contract["truth_boundary"] == EXPECTED_TRUTH, "semantic readiness flag promoted")
    return contract


def verify_execution_order_binding(
    root: Path,
    semantics: dict[str, object],
    runtime_contract: dict[str, object],
) -> None:
    path = root / EXECUTION_ORDER_PATH
    require(path.is_file(), "execution-order supplement missing")
    require(sha256(path) == EXECUTION_ORDER_SHA256, "execution-order supplement raw digest drift")
    reference = json.loads(path.read_text())
    require(
        (
            reference.get("format_version"),
            reference.get("contract_version"),
            reference.get("mode"),
        )
        == (1, EXECUTION_ORDER_VERSION, "reference-truth-supplement"),
        "execution-order supplement identity drift",
    )
    expected_semantic_binding = {
        "path": EXECUTION_ORDER_PATH.as_posix(),
        "contract_version": EXECUTION_ORDER_VERSION,
        "raw_sha256": EXECUTION_ORDER_SHA256,
    }
    expected_runtime_binding = {
        "path": EXECUTION_ORDER_PATH.as_posix(),
        "contract_version": EXECUTION_ORDER_VERSION,
        "sha256": EXECUTION_ORDER_SHA256,
    }
    require(
        semantics.get("source_execution_order_contract") == expected_semantic_binding,
        "semantic execution-order supplement binding removed",
    )
    require(
        runtime_contract["repository_artifacts"].get("source_execution_order_contract")
        == expected_runtime_binding,
        "runtime execution-order supplement binding removed",
    )
    dynamic = reference["execution_model"]["dynamic_data_sources"]
    require(
        dynamic["stage_scope"] == "stage_local"
        and dynamic["traversal"] == "breadth_first"
        and dynamic["activation_scope"] == "entire_creation_block"
        and dynamic["raw_global_flattening"] is False
        and dynamic["creation_log_ordinal_gate"] is False,
        "execution-order supplement dynamic-stage truth drift",
    )
    require(
        reference["truth_boundary"]
        == {
            "backfill_allowed": False,
            "combined_handler_order_implemented": False,
            "dynamic_datasource_stage_reference_modeled": True,
            "graph_node_reference_source_bound": True,
            "physical_parity_complete": False,
            "poi_parity_complete": False,
            "production_ready": False,
            "runtime_consumes_contract": False,
            "same_path_order_machine_proven": False,
            "target_runtime_identity_bound": False,
        },
        "execution-order supplement truth boundary drift",
    )


def verify_segment_binding(root: Path, semantics: dict[str, object]) -> None:
    profiles_path = root / "uniswap-v3/writer-runtime/segment-profiles-v1.json"
    require(sha256(profiles_path) == PROFILE_SHA256, "source profile raw digest drift")
    profiles = json.loads(profiles_path.read_text())["profiles"]
    require(len(profiles) == len(semantics["segments"]) == 8, "segment/profile count drift")
    fields = (
        "network",
        "start_block_inclusive",
        "end_block_inclusive",
        "deployment",
        "segment_id",
        "semantic_contract_sha256",
        "pool_mapping_cid",
        "pool_profile_id",
    )
    for index, (source, reducer) in enumerate(zip(profiles, semantics["segments"])):
        for field in fields:
            require(source[field] == reducer[field], f"segment {index} source binding drift: {field}")


def verify_overlay_static(root: Path, writer) -> None:
    patch_path = root / OVERLAY / "runtime.patch"
    require(sha256(patch_path) == RUNTIME_PATCH_SHA256, "flash-reducer patch digest drift")
    patch = patch_path.read_text()
    files = set(re.findall(r"^diff --git a/(\S+) b/\1$", patch, re.MULTILINE))
    require(files == {"src/lib.rs"}, f"flash-reducer patch file set drift: {sorted(files)}")
    require(patch.count("+pub mod flash_reducer;") == 1, "flash-reducer module declaration drift")
    require(patch.count('+#[cfg(not(target_arch = "wasm32"))]') == 1, "flash reducer must remain excluded from WASM")
    require("pub fn graph_out(" in patch, "flash-reducer patch lost its writer-runtime anchor")

    source_path = root / OVERLAY / "src/flash_reducer.rs"
    require(sha256(source_path) == REDUCER_SOURCE_SHA256, "flash-reducer source digest drift")
    source = source_path.read_text()
    for required in (
        "pub trait FlashCalls",
        "pub fn reduce_flash_block",
        "const FEE_GROWTH_0_CALLDATA: [u8; 4] = [0xf3, 0x05, 0x83, 0x99]",
        "const FEE_GROWTH_1_CALLDATA: [u8; 4] = [0x46, 0x14, 0x13, 0x19]",
        "pub struct PoolUpdate",
        "SOURCE_EXECUTION_ORDER_CONTRACT_RAW_SHA256",
        "graph_node_execution_order_supplement_bound: true",
        "dynamic_datasource_stage_order_implemented: false",
        "combined_handler_order_implemented: false",
        "runtime_consumes_execution_order_contract: false",
        "same_path_order_machine_proven: false",
        "cross_component_order_proven: false",
        "target_runtime_identity_bound: false",
    ):
        require(required in source, f"flash-reducer source contract missing `{required}`")
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
        require(forbidden not in source, f"flash-reducer source contains forbidden runtime capability `{forbidden}`")

    with tempfile.TemporaryDirectory(prefix="uniswap-v3-flash-patch-") as temporary:
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
        require(result.returncode == 0, "flash-reducer patch does not apply after exact writer runtime")


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
    shutil.copy2(root / OVERLAY / "src/flash_reducer.rs", destination / "src/flash_reducer.rs")
    shutil.copy2(root / OVERLAY / "flash-reducer-v1.json", destination / "configs/flash-reducer-v1.json")


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object], writer) -> Path:
    require(runtime.is_dir(), f"flash-reducer runtime missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="uniswap-v3-flash-expected-") as temporary:
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
        require(delta == EXPECTED_REDUCER_RUNTIME_DELTA, f"flash-reducer runtime delta drift: {sorted(delta)}")
        require(set(runtime_files) == set(final_files), "flash-reducer runtime file set drift")
        for relative, expected in final_files.items():
            actual = runtime_files[relative]
            require(actual.read_bytes() == expected.read_bytes(), f"flash-reducer runtime content drift: {relative}")
            require(
                actual.stat().st_mode & 0o111 == expected.stat().st_mode & 0o111,
                f"flash-reducer runtime mode drift: {relative}",
            )
    writer.verify_toolchain(runtime)
    writer.verify_protobuf(runtime)
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized flash-reducer artifact drift: {relative}")
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
        semantics = load_semantics(root)
        verify_execution_order_binding(root, semantics, contract)
        verify_segment_binding(root, semantics)
        verify_writer_runtime(root, writer)
        verify_overlay_static(root, writer)
        runtime_wasm = None
        if args.runtime:
            runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract, writer)
        if args.writer_runtime:
            writer_wasm = args.writer_runtime.resolve() / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"
            require(runtime_wasm.is_file(), "flash-reducer WASM missing")
            require(writer_wasm.is_file(), "writer-runtime WASM missing")
            require(runtime_wasm.read_bytes() == writer_wasm.read_bytes(), "host-only reducer changed writer WASM")
        if args.mainnet_spkg:
            writer.verify_packages(
                runtime_wasm,
                {
                    "mainnet": args.mainnet_spkg.resolve(),
                    "base": args.base_spkg.resolve(),
                },
            )
        print(
            "verified host-only Uniswap V3 Pool Flash reducer, exact writer/execution-order bindings, "
            "diagnostic-only ordering, and conservative gates"
        )
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
        print(f"Uniswap V3 flash-reducer verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
